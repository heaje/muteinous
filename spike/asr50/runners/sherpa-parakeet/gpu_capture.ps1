$ErrorActionPreference = "Stop"
$lock = "C:\scratch\asr50\timing.lock.d"
foreach ($provider in @("cpu", "directml")) {
        $out = "C:\scratch\asr50\WP9\gpu-$provider"
        $stdout = "C:\scratch\asr50\WP9\gpu-$provider.log"
        $stderr = "C:\scratch\asr50\WP9\gpu-$provider.err"
        $arguments = @(
            "-I", "C:\code\muteinous-spike50\spike\asr50\runners\sherpa-parakeet\run.py",
            "--threads", "4", "--provider", $provider, "--passes", "5", "--out", $out
        )
        $process = Start-Process -FilePath "C:\scratch\asr50\WP9\venv\Scripts\python.exe" `
            -ArgumentList $arguments -PassThru -NoNewWindow `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $samples = [System.Collections.Generic.List[object]]::new()
        while (-not $process.HasExited) {
            try {
                $counter = Get-Counter -Counter `
                    "\GPU Engine(*)\Utilization Percentage",
                    "\GPU Process Memory(*)\Dedicated Usage" -MaxSamples 1
                foreach ($sample in $counter.CounterSamples) {
                    if ($sample.InstanceName -match "pid_$($process.Id)_") {
                        $samples.Add([pscustomobject]@{
                            time = (Get-Date).ToString("o")
                            path = $sample.Path
                            instance = $sample.InstanceName
                            value = $sample.CookedValue
                        })
                    }
                }
            } catch {
                $samples.Add([pscustomobject]@{
                    time = (Get-Date).ToString("o")
                    error = $_.Exception.Message
                })
            }
            Start-Sleep -Milliseconds 300
            $process.Refresh()
        }
        $samples | ConvertTo-Json -Depth 5 |
            Set-Content -Encoding utf8 "C:\scratch\asr50\WP9\gpu-$provider-counters.json"
        Write-Output "provider=$provider pid=$($process.Id) exit=$($process.ExitCode) pid_samples=$($samples.Count)"
}
