param(
  [Parameter(Mandatory=$true)][ValidateSet("turbo","small-en")][string]$Model,
  [Parameter(Mandatory=$true)][ValidateSet(4,12)][int]$Threads,
  [Parameter(Mandatory=$true)][string]$Clip,
  [Parameter(Mandatory=$true)][string]$Config
)
$ErrorActionPreference = "Stop"
$base = "C:\scratch\asr50"
$out = Join-Path $base "WP22"
$corpus = if ($Clip.StartsWith("v3_")) { Join-Path $base "corpus_v3_frozen" } else { Join-Path $base "corpus_v2_frozen" }
$bin = Join-Path $base "WP2\artifacts\whisper-vulkan-dl-windows-x64"
$exe = Join-Path $bin "whisper-cli.exe"
$modelInfo = if ($Model -eq "turbo") {
  @{ path = "$base\models\whisper-large-v3-turbo-whisper-cpp-q5-0\ggml-large-v3-turbo-q5_0.bin" }
} else {
  @{ path = "$base\models\whisper-small-en-whisper-cpp-q5-1\ggml-small.en-q5_1.bin" }
}
$dest = Join-Path $out "$Config-gpu-sample"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$prefix = Join-Path $dest $Clip
$counterFile = Join-Path $dest "pid-counters.jsonl"
$sampleScript = "C:\code\muteinous-spike50\spike\asr50\speed\sample_gpu_pid.ps1"
$env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"; $env:HF_HUB_DISABLE_TELEMETRY="1"
$arguments = @("-m",$modelInfo.path,"-f",(Join-Path $corpus "$Clip.wav"),"-l","en","-t","$Threads","-ojf","-of",$prefix,"-dev","0")
$child = Start-Process -FilePath $exe -ArgumentList $arguments -PassThru -NoNewWindow `
  -RedirectStandardOutput "$prefix.stdout" -RedirectStandardError "$prefix.stderr"
$samplerArgs = @("-NoProfile","-ExecutionPolicy","Bypass","-File",$sampleScript,
  "-TargetPID","$($child.Id)","-OutFile",$counterFile)
$sampler = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
  -ArgumentList $samplerArgs -PassThru -WindowStyle Hidden -PriorityClass BelowNormal
$started = [DateTime]::UtcNow
$lastProgress = $started
$samplerStatus = "sampling"
$candidateTimeout = $false
try {
  while (-not $child.WaitForExit(1000)) {
    if (Test-Path $counterFile) {
      $lastProgress = (Get-Item $counterFile).LastWriteTimeUtc
    }
    if ($samplerStatus -eq "sampling" -and ([DateTime]::UtcNow - $lastProgress).TotalSeconds -gt 20) {
      Stop-Process -Id $sampler.Id -Force -ErrorAction SilentlyContinue
      $samplerStatus = "watchdog_killed_stalled_sampler"
    }
    if (([DateTime]::UtcNow - $started).TotalSeconds -ge 600) {
      $candidateTimeout = $true
      Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue
      break
    }
  }
} finally {
  Stop-Process -Id $sampler.Id -Force -ErrorAction SilentlyContinue
  try { $sampler.WaitForExit() } catch {}
}
$metadata = [pscustomobject]@{
  config=$Config; clip_id=$Clip; pid=$child.Id; process_exit_code=$child.ExitCode
  sampled_pass="untimed; never used for latency/RTF"
  sampler_pid=$sampler.Id; sampler_priority="BelowNormal"
  sampler_status=if($candidateTimeout){"candidate_timeout_600s"}else{$samplerStatus}
  counter_file=$counterFile; counter_sampling_period_s=1
  watchdog="sampler stopped if counter file made no progress for >20 seconds; candidate has separate 600-second timeout"
}
$metadata | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $dest "metadata.json")
Write-Output "Wrote untimed GPU sample: $dest"
