param(
  [Parameter(Mandatory=$true)][ValidateSet("ort-turbo","ort-small","parakeet","faster","moonshine","vad","aligner")][string]$Kind,
  [Parameter(Mandatory=$true)][ValidateSet("cpu","dml")][string]$Device,
  [Parameter(Mandatory=$true)][ValidateSet(4,12)][int]$Threads,
  [int]$Beam = 5
)
$ErrorActionPreference = "Stop"
$base = "C:\scratch\asr50"
$out = Join-Path $base "WP22"
$script = "C:\code\muteinous-spike50\spike\asr50\speed\library_timing.py"
$python = switch ($Kind) {
  "ort-turbo" { if ($Device -eq "dml") { "$base\WP12\venv\dml\Scripts\python.exe" } else { "$base\WP12\venv\cpu\Scripts\python.exe" } }
  "ort-small" { if ($Device -eq "dml") { "$base\WP13\venv-dml\Scripts\python.exe" } else { "$base\WP13\venv-cpu\Scripts\python.exe" } }
  "parakeet" { "$base\WP9\venv\Scripts\python.exe" }
  "faster" { "$base\WP10\venv\Scripts\python.exe" }
  "moonshine" { "$base\WP11\cpu-venv\Scripts\python.exe" }
  "vad" { "$base\WP18\venv\Scripts\python.exe" }
  "aligner" { "$base\WP12\venv\cpu\Scripts\python.exe" }
}
if (($Kind -in @("parakeet","faster","moonshine","vad","aligner")) -and $Device -ne "cpu") {
  throw "$Kind only has an approved CPU speed configuration."
}
$config = "$Kind-$Device-t$Threads" + $(if ($Kind -eq "faster") { "-b$Beam" } else { "" })
$checkpoint = Join-Path $out "$config.jsonl"
$logDir = Join-Path $out "$config-library-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$classes = @("short","medium","long")
$lock = Join-Path $base "timing.lock.d"
$env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"; $env:HF_HUB_DISABLE_TELEMETRY="1"
foreach ($class in $classes) {
  # Acquire lock and idle gate before each class process. The process loads its
  # model once, performs one untimed warm-up per clip, then five timed repeats.
  $lockDeadline = [DateTime]::UtcNow.AddMinutes(20)
  while ($true) {
    try { New-Item -ItemType Directory -Path $lock -ErrorAction Stop | Out-Null; break }
    catch {
      if (Test-Path $lock) {
        $age = ([DateTime]::UtcNow - (Get-Item $lock).LastWriteTimeUtc).TotalMinutes
        if ($age -gt 30) {
          Remove-Item -LiteralPath $lock -Force
          Add-Content -Encoding UTF8 (Join-Path $out "lock-events.txt") "Removed stale lock older than 30 minutes: $(Get-Date -Format o)"
          continue
        }
      }
      if ([DateTime]::UtcNow -ge $lockDeadline) { throw "timing lock wait exceeded 20 minutes" }
      Start-Sleep -Seconds 5
    }
  }
  try {
    $idleDeadline = [DateTime]::UtcNow.AddSeconds(60)
    $idleSamples = @()
    $idle = $false
    while ([DateTime]::UtcNow -lt $idleDeadline) {
      $cpu = Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 3
      $gpu = Get-Counter '\GPU Engine(*)\Utilization Percentage' -SampleInterval 1 -MaxSamples 3
      $cpuValues = @($cpu.CounterSamples | ForEach-Object { [double]$_.CookedValue })
      $gpuMax = 0.0
      foreach ($s in $gpu) {
        $vals = @($s.CounterSamples | Where-Object {
          $_.Path -match 'luid_0x00000000_0x000164ac' -and $_.Path -match 'engtype_(3d|compute)'
        } | ForEach-Object { [double]$_.CookedValue })
        if ($vals.Count) { $gpuMax = [Math]::Max($gpuMax,($vals | Measure-Object -Maximum).Maximum) }
      }
      $idleSamples += [pscustomobject]@{utc=(Get-Date).ToUniversalTime().ToString("o");cpu_percent=$cpuValues;rx7900_3d_compute_max_percent=$gpuMax}
      if (($cpuValues | Where-Object { $_ -ge 5 }).Count -eq 0 -and $gpuMax -lt 0.1) { $idle=$true; break }
      Start-Sleep -Seconds 2
    }
    if (-not $idle) { throw "idle gate not met within 60 seconds for $config/$class" }
    $bg = @(Get-Process | Select-Object ProcessName,Id,@{n="cpu_s";e={if($_.CPU){[math]::Round($_.CPU,3)}else{0}}},@{n="working_set_bytes";e={$_.WorkingSet64}})
    $preflight = [pscustomobject]@{config=$config;clip_class=$class;idle_samples=$idleSamples;retries=[Math]::Max(0,[Math]::Floor($idleSamples.Count/3)-1);background_processes=$bg}
    $preflight | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $out "$config-$class-preflight.json")

    $stdout = Join-Path $logDir "$class.stdout"
    $stderr = Join-Path $logDir "$class.stderr"
    $arguments = @($script,"--kind",$Kind,"--threads","$Threads","--beam","$Beam","--device",$Device,"--clips",$class,"--out",$checkpoint,"--repeats","5")
    $worker = Start-Process -FilePath $python -ArgumentList $arguments -PassThru -NoNewWindow `
      -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while (-not $worker.WaitForExit(1000)) {
      if ($timer.Elapsed.TotalSeconds -ge 600) {
        Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue
        $timeout = [pscustomobject]@{event="class_timeout_10m";config=$config;class=$class;worker_pid=$worker.Id;timeout_seconds=600}
        ($timeout | ConvertTo-Json -Compress) | Add-Content -Encoding UTF8 $checkpoint
        break
      }
    }
    $timer.Stop()
    if ($worker.HasExited -and $worker.ExitCode -ne 0) {
      $failure = [pscustomobject]@{event="class_failed";config=$config;class=$class;exit_code=$worker.ExitCode;stderr=$stderr}
      ($failure | ConvertTo-Json -Compress) | Add-Content -Encoding UTF8 $checkpoint
    }
  } finally {
    Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
  }
}
Write-Output "Completed library config $config; checkpoint: $checkpoint"
