param(
  [Parameter(Mandatory=$true)][ValidateSet("turbo","small-en")][string]$Model,
  [Parameter(Mandatory=$true)][ValidateSet("vulkan","cpu")][string]$Device,
  [Parameter(Mandatory=$true)][ValidateSet(4,12)][int]$Threads,
  [switch]$Drift
)
$ErrorActionPreference = "Stop"
$base = "C:\scratch\asr50"
$out = Join-Path $base "WP22"
$corpusV3 = Join-Path $base "corpus_v3_frozen"
$corpusV2 = Join-Path $base "corpus_v2_frozen"
$binRoot = Join-Path $base "WP2\artifacts"
$exe = if ($Device -eq "vulkan") {
  Join-Path $binRoot "whisper-vulkan-dl-windows-x64\whisper-cli.exe"
} else {
  Join-Path $binRoot "whisper-cpu-dl-windows-x64\whisper-cli.exe"
}
$modelInfo = if ($Model -eq "turbo") {
  @{ path = "$base\models\whisper-large-v3-turbo-whisper-cpp-q5-0\ggml-large-v3-turbo-q5_0.bin"; slug = "whisper-large-v3-turbo-whisper-cpp-q5-0" }
} else {
  @{ path = "$base\models\whisper-small-en-whisper-cpp-q5-1\ggml-small.en-q5_1.bin"; slug = "whisper-small-en-whisper-cpp-q5-1" }
}
$config = "$Model-$Device-t$Threads" + $(if ($Drift) { "-drift" } else { "" })
$checkpoint = Join-Path $out "$config.jsonl"
$logDir = Join-Path $out "$config-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$short = @(
  @{id="v3_clean_001_0"; root=$corpusV3}, @{id="v3_clean_002_0"; root=$corpusV3},
  @{id="v3_clean_003_0"; root=$corpusV3}, @{id="v3_clean_004_0"; root=$corpusV3},
  @{id="v3_clean_005_0"; root=$corpusV3}, @{id="v3_clean_006_0"; root=$corpusV3},
  @{id="v3_clean_007_0"; root=$corpusV3}, @{id="v3_clean_008_0"; root=$corpusV3}
)
$medium = @(
  @{id="natural_18s_00"; root=$corpusV2}, @{id="natural_25s_00"; root=$corpusV2},
  @{id="natural_18s_01"; root=$corpusV2}, @{id="natural_25s_01"; root=$corpusV2}
)
$long = @(
  @{id="natural_sentences_00"; root=$corpusV2}, @{id="natural_sentences_01"; root=$corpusV2}
)

# The shared timing lock is kept for the whole timed block. Never remove a lock
# that this process did not create.
$lock = Join-Path $base "timing.lock.d"
try {
  New-Item -ItemType Directory -Path $lock -ErrorAction Stop | Out-Null
} catch {
  throw "Could not acquire timing lock $lock; no run started."
}
try {
  # Before EVERY config (including the explicit drift invocation), require
  # three consecutive one-second samples below 5% CPU and near-zero 3D/Compute.
  $idleRows = @()
  $idleDeadline = [DateTime]::UtcNow.AddSeconds(60)
  do {
    $cpu = Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 3
    $gpu = Get-Counter '\GPU Engine(*)\Utilization Percentage' -SampleInterval 1 -MaxSamples 3
    $cpuValues = @($cpu.CounterSamples | ForEach-Object { [double]$_.CookedValue })
    $gpuValues = @()
    foreach ($sample in $gpu) {
      $gpuValues += @($sample.CounterSamples |
        Where-Object { $_.Path -match 'luid_0x00000000_0x000164ac' -and $_.Path -match 'engtype_(3d|compute)' } |
        ForEach-Object { [double]$_.CookedValue })
    }
    $gpuMax = if ($gpuValues.Count) { ($gpuValues | Measure-Object -Maximum).Maximum } else { 0.0 }
    $idleRows += [pscustomobject]@{ utc=(Get-Date).ToUniversalTime().ToString("o"); cpu_percent=$cpuValues; rx7900_3d_compute_max_percent=[math]::Round($gpuMax,4) }
    if (($cpuValues | Where-Object { $_ -ge 5 }).Count -eq 0 -and $gpuMax -lt 0.1) { break }
    if ([DateTime]::UtcNow -ge $idleDeadline) { throw "Idle threshold not met within 60 seconds; configuration not started." }
    Start-Sleep -Seconds 2
  } while ($true)
  $background = @(Get-Process | Sort-Object CPU -Descending | Select-Object ProcessName,Id,
    @{n="cpu_seconds_before";e={if ($_.CPU) {[math]::Round($_.CPU,3)} else {0}}},
    @{n="working_set_bytes";e={$_.WorkingSet64}})
  $preflight = [pscustomobject]@{config=$config; idle_samples=$idleRows; background_processes=$background; retries=[math]::Max(0,[math]::Floor($idleRows.Count/3)-1)}
  $preflight | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $out "$config-preflight.json")

  $env:HF_HUB_OFFLINE = "1"; $env:TRANSFORMERS_OFFLINE = "1"; $env:HF_HUB_DISABLE_TELEMETRY = "1"
  $env:GGML_VK_VISIBLE_DEVICES = "0"
  $groundV3 = Get-Content (Join-Path $corpusV3 "ground_truth_v3.json") -Raw | ConvertFrom-Json
  $groundV2 = Get-Content (Join-Path $corpusV2 "ground_truth_v2.json") -Raw | ConvertFrom-Json
  $truth = @{}
  foreach ($clip in $groundV3.clips) { $truth[$clip.clip_id] = $clip }
  foreach ($clip in $groundV2.clips) { $truth[$clip.clip_id] = $clip }
  $classes = @(@{name="short";clips=$short},@{name="medium";clips=$medium},@{name="long";clips=$long})
  $records = [System.Collections.Generic.List[object]]::new()
  foreach ($class in $classes) {
    $classTimer = [Diagnostics.Stopwatch]::StartNew()
    :clipLoop foreach ($clip in $class.clips) {
      for ($rep=1; $rep -le 5; $rep++) {
        if ($classTimer.Elapsed.TotalMinutes -ge 10) {
          $row = [pscustomobject]@{config=$config;class=$class.name;clip_id=$clip.id;repeat=$rep;status="class_timeout_10m"}
          $records.Add($row); ($row | ConvertTo-Json -Compress) | Add-Content -Encoding UTF8 $checkpoint
          break clipLoop
        }
        $wav = Join-Path $clip.root "$($clip.id).wav"
        $tag = "$($clip.id)-r$rep"
        $prefix = Join-Path $logDir $tag
        $logPath = "$prefix.log"
        $jsonPath = "$prefix.json"
        $argv = @("-m",$modelInfo.path,"-f",$wav,"-l","en","-t","$Threads","-ojf","-of",$prefix)
        if ($Device -eq "vulkan") { $argv += @("-dev","0") } else { $argv += "-ng" }
        $started = [DateTime]::UtcNow
        $metaPath = "$prefix.meta.json"
        $python = "C:\scratch\asr50\WP10\venv\Scripts\python.exe"
        $wrapper = "C:\code\muteinous-spike50\spike\asr50\speed\run_cli_timed.py"
        & $python $wrapper --stdout $logPath --stderr "$prefix.err" --meta $metaPath --timeout 600 -- $exe @argv | Out-Null
        $timingExit = $LASTEXITCODE
        $postprocessor = "C:\code\muteinous-spike50\spike\asr50\speed\postprocess_cli.py"
        & $python $postprocessor --config $config --clip-class $class.name --clip-id $clip.id `
          --repeat $rep --device $Device --started $started.ToString("o") `
          --meta $metaPath --stdout $logPath --stderr "$prefix.err" --json $jsonPath `
          --checkpoint $checkpoint | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "postprocessor failed for $tag with exit $LASTEXITCODE" }
      }
    }
    $classTimer.Stop()
  }
  Write-Output "Completed $config; checkpoint: $checkpoint"
} finally {
  Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
}
