param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Script,
    [Parameter(Mandatory=$true)][string]$ArgumentLine,
    [Parameter(Mandatory=$true)][string]$RunName,
    [int]$TimeoutSeconds = 600
)
$ErrorActionPreference = "Continue"
$root = "C:\scratch\asr50\WP23"
$outDir = Join-Path $root "device_runs\$RunName"
New-Item -ItemType Directory -Force $outDir | Out-Null
$stdout = Join-Path $outDir "stdout.txt"
$stderr = Join-Path $outDir "stderr.txt"
$exitCodeFile = Join-Path $outDir "child_exit_code.txt"
$samplesPath = Join-Path $outDir "gpu_counters.json"
$metaPath = Join-Path $outDir "run_meta.json"
$since = (Get-Date).AddMinutes(-2)
$before = @(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Display'; Id=4101; StartTime=$since} -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,Message)
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$start = Get-Date
$commandLine = "/d /v:on /c `"`"$Python`" -I `"$Script`" $ArgumentLine & echo !ERRORLEVEL! > `"$exitCodeFile`"`""
$p = Start-Process -FilePath $env:ComSpec -ArgumentList $commandLine -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$pidValue = $p.Id
$samples = [System.Collections.Generic.List[object]]::new()
$diagnosticPaths = @()
$observedPids = [System.Collections.Generic.HashSet[string]]::new()
$targetPids = [System.Collections.Generic.HashSet[string]]::new()
[void]$targetPids.Add([string]$pidValue)
$timedOut = $false
while (-not $p.HasExited) {
    if (((Get-Date) - $start).TotalSeconds -ge $TimeoutSeconds) {
        $timedOut = $true
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        break
    }
    $values = @()
    $counterError = $null
    try {
        $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
        $grew = $true
        while ($grew) {
            $grew = $false
            foreach ($proc in $processes) {
                if ($targetPids.Contains([string]$proc.ParentProcessId) -and
                    $targetPids.Add([string]$proc.ProcessId)) { $grew = $true }
            }
        }
        $cs = @()
        foreach ($counter in @('\GPU Engine(*)\Utilization Percentage','\GPU Process Memory(*)\Dedicated Usage')) {
            $batch = Get-Counter -Counter $counter -ErrorAction SilentlyContinue
            $cs += @($batch.CounterSamples | Where-Object { $_.Status -eq 0 })
        }
        foreach ($c in $cs) {
            if ($c.Path -match '(?i)pid_(\d+)_') { [void]$observedPids.Add($Matches[1]) }
            if ($diagnosticPaths.Count -lt 500 -and $c.Path -match '(?i)pid_' -and
                -not ($diagnosticPaths | Where-Object { $_.path -eq $c.Path })) {
                $diagnosticPaths += [ordered]@{path=$c.Path; value=[double]$c.CookedValue}
            }
            $isTargetPid = $false
            foreach ($targetPid in $targetPids) {
                if ($c.Path.IndexOf("pid_$($targetPid)_", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                    $isTargetPid = $true
                    break
                }
            }
            if ($isTargetPid) {
                $values += [ordered]@{ path=$c.Path; value=[double]$c.CookedValue }
            }
        }
    } catch { $counterError = $_.Exception.Message }
    $samples.Add([ordered]@{at=(Get-Date).ToString("o"); counters=$values; error=$counterError})
    Start-Sleep -Milliseconds 250
    $p.Refresh()
}
$p.WaitForExit()
$p.Refresh()
$exitCode = if ($timedOut) { $null } elseif (Test-Path $exitCodeFile) {
    [int](Get-Content $exitCodeFile -Raw).Trim()
} else { $p.ExitCode }
$end = Get-Date
$after = @(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Display'; Id=4101; StartTime=$start.AddSeconds(-2); EndTime=$end.AddSeconds(2)} -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,Message)
$sampleDoc = [ordered]@{ pid=$pidValue; target_pids=@($targetPids); observed_pids=@($observedPids); diagnostic_paths=$diagnosticPaths; samples=$samples }
$sampleDoc | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 $samplesPath
$meta = [ordered]@{
    run=$RunName; pid=$pidValue; target_pids=@($targetPids); start=$start.ToString("o"); end=$end.ToString("o")
    timeout_seconds=$TimeoutSeconds; timed_out=$timedOut; exit_code=$(if ($timedOut) { $null } else { $exitCode })
    system_display_4101_before=$before; system_display_4101_after=$after
    stdout=$stdout; stderr=$stderr; child_exit_code_file=$exitCodeFile; gpu_samples=$samplesPath
}
$meta | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 $metaPath
Get-Content $stdout
Get-Content $stderr
"RUN_META=$metaPath"
