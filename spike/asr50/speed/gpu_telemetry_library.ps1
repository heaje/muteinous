param(
  [Parameter(Mandatory=$true)][ValidateSet("ort-turbo","ort-small")][string]$Kind,
  [Parameter(Mandatory=$true)][ValidateSet("dml")][string]$Device,
  [Parameter(Mandatory=$true)][ValidateSet(4,12)][int]$Threads,
  [int]$Beam = 5
)
$ErrorActionPreference = "Stop"
$base = "C:\scratch\asr50"
$repo = "C:\code\muteinous-spike50\spike\asr50\speed"
$out = Join-Path $base "WP22"
$python = if ($Kind -eq "ort-turbo") { "$base\WP12\venv\dml\Scripts\python.exe" } else { "$base\WP13\venv-dml\Scripts\python.exe" }
$config = "$Kind-$Device-t$Threads"
$dest = Join-Path $out "$config-gpu-sample"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$counterFile = Join-Path $dest "pid-counters.jsonl"
$workerOut = Join-Path $dest "worker.stdout"
$workerErr = Join-Path $dest "worker.stderr"
$workerArgs = @((Join-Path $repo "library_timing.py"),"--kind",$Kind,"--threads","$Threads",
  "--beam","$Beam","--device",$Device,"--clips","long","--clip-id","natural_sentences_00",
  "--out",(Join-Path $dest "telemetry-only.jsonl"),"--repeats","1")
$env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"; $env:HF_HUB_DISABLE_TELEMETRY="1"
$worker = Start-Process -FilePath $python -ArgumentList $workerArgs -PassThru -NoNewWindow `
  -RedirectStandardOutput $workerOut -RedirectStandardError $workerErr
$samplerScript = Join-Path $repo "sample_gpu_pid.ps1"
$sampler = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
  -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File",$samplerScript,
                  "-TargetPID","$($worker.Id)","-OutFile",$counterFile) `
  -PassThru -WindowStyle Hidden -PriorityClass BelowNormal
$start = [DateTime]::UtcNow
$lastProgress = $start
$samplerStatus = "sampling"
$timedOut = $false
try {
  while (-not $worker.WaitForExit(1000)) {
    if (Test-Path $counterFile) { $lastProgress = (Get-Item $counterFile).LastWriteTimeUtc }
    if ($samplerStatus -eq "sampling" -and ([DateTime]::UtcNow - $lastProgress).TotalSeconds -gt 20) {
      Stop-Process -Id $sampler.Id -Force -ErrorAction SilentlyContinue
      $samplerStatus = "watchdog_killed_stalled_sampler"
    }
    if (([DateTime]::UtcNow - $start).TotalSeconds -ge 600) {
      $timedOut = $true
      Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue
      break
    }
  }
} finally {
  Stop-Process -Id $sampler.Id -Force -ErrorAction SilentlyContinue
  try { $sampler.WaitForExit() } catch {}
}
$meta = [pscustomobject]@{
  config=$config; model=$Kind; clip_id="natural_sentences_00"; device=$Device; pid=$worker.Id
  worker_exit_code=$worker.ExitCode; telemetry_pass="untimed; output latency excluded"
  counter_sampling_period_s=1; sampler_priority="BelowNormal"
  sampler_status=if($timedOut){"worker_timeout_600s"}else{$samplerStatus}
  watchdog="sampler killed after >20 seconds without counter-file progress; worker has separate 600-second watchdog"
  counter_file=$counterFile
}
$meta | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $dest "metadata.json")
Write-Output "Wrote separate untimed GPU telemetry under $dest"
