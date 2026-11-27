param(
    [Parameter(Mandatory=$true)][string]$PythonA,
    [Parameter(Mandatory=$true)][string]$ScriptA,
    [Parameter(Mandatory=$true)][string]$ArgsA,
    [Parameter(Mandatory=$true)][string]$PythonB,
    [Parameter(Mandatory=$true)][string]$ScriptB,
    [Parameter(Mandatory=$true)][string]$ArgsB,
    [Parameter(Mandatory=$true)][string]$RunName,
    [int]$TimeoutSeconds=900
)
$ErrorActionPreference="Continue"
$root="C:\scratch\asr50\WP23"
$outDir=Join-Path $root "device_runs\$RunName"
New-Item -ItemType Directory -Force $outDir | Out-Null
$start=Get-Date
$before=@(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Display';Id=4101;StartTime=$start.AddMinutes(-2)} -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,Message)
$env:HF_HUB_OFFLINE="1";$env:TRANSFORMERS_OFFLINE="1";$env:HF_HUB_DISABLE_TELEMETRY="1"
$exitA=Join-Path $outDir "a_exit_code.txt";$exitB=Join-Path $outDir "b_exit_code.txt"
$commandA="/d /v:on /c `"`"$PythonA`" -I `"$ScriptA`" $ArgsA & echo !ERRORLEVEL! > `"$exitA`"`""
$commandB="/d /v:on /c `"`"$PythonB`" -I `"$ScriptB`" $ArgsB & echo !ERRORLEVEL! > `"$exitB`"`""
$pa=Start-Process -FilePath $env:ComSpec -ArgumentList $commandA -PassThru -NoNewWindow `
    -RedirectStandardOutput (Join-Path $outDir "a_stdout.txt") -RedirectStandardError (Join-Path $outDir "a_stderr.txt")
$pb=Start-Process -FilePath $env:ComSpec -ArgumentList $commandB -PassThru -NoNewWindow `
    -RedirectStandardOutput (Join-Path $outDir "b_stdout.txt") -RedirectStandardError (Join-Path $outDir "b_stderr.txt")
$rootA=[string]$pa.Id;$rootB=[string]$pb.Id
$targetsA=[System.Collections.Generic.HashSet[string]]::new();[void]$targetsA.Add($rootA)
$targetsB=[System.Collections.Generic.HashSet[string]]::new();[void]$targetsB.Add($rootB)
$samples=[System.Collections.Generic.List[object]]::new()
$timedOut=$false
while(-not ($pa.HasExited -and $pb.HasExited)){
    if(((Get-Date)-$start).TotalSeconds -ge $TimeoutSeconds){$timedOut=$true;break}
    $procs=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    foreach($targets in @($targetsA,$targetsB)){
        $grew=$true
        while($grew){$grew=$false;foreach($q in $procs){
            if($targets.Contains([string]$q.ParentProcessId) -and $targets.Add([string]$q.ProcessId)){$grew=$true}
        }}
    }
    $cs=@()
    foreach($counter in @('\GPU Engine(*)\Utilization Percentage','\GPU Process Memory(*)\Dedicated Usage')){
        $batch=Get-Counter -Counter $counter -ErrorAction SilentlyContinue
        $cs+=@($batch.CounterSamples|Where-Object{$_.Status -eq 0})
    }
    $vals=@()
    foreach($c in $cs){
        $owner=$null
        foreach($pidText in $targetsA){if($c.Path.IndexOf("pid_$($pidText)_",[System.StringComparison]::OrdinalIgnoreCase)-ge 0){$owner="A";break}}
        if(-not $owner){foreach($pidText in $targetsB){if($c.Path.IndexOf("pid_$($pidText)_",[System.StringComparison]::OrdinalIgnoreCase)-ge 0){$owner="B";break}}}
        if($owner){$vals+= [ordered]@{owner=$owner;path=$c.Path;value=[double]$c.CookedValue}}
    }
    $samples.Add([ordered]@{at=(Get-Date).ToString("o");counters=$vals})
    Start-Sleep -Milliseconds 250
    $pa.Refresh();$pb.Refresh()
}
if($timedOut){
    foreach($id in @($targetsA)+@($targetsB)){& taskkill.exe /PID $id /T /F 2>$null|Out-Null}
}
$pa.WaitForExit();$pb.WaitForExit();$pa.Refresh();$pb.Refresh()
$exitCodeA=if($timedOut){$null}elseif(Test-Path $exitA){[int](Get-Content $exitA -Raw).Trim()}else{$pa.ExitCode}
$exitCodeB=if($timedOut){$null}elseif(Test-Path $exitB){[int](Get-Content $exitB -Raw).Trim()}else{$pb.ExitCode}
$end=Get-Date
$after=@(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Display';Id=4101;StartTime=$start.AddSeconds(-2);EndTime=$end.AddSeconds(2)} -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,Message)
$meta=[ordered]@{run=$RunName;start=$start.ToString("o");end=$end.ToString("o");timeout_seconds=$TimeoutSeconds;timed_out=$timedOut;
    root_a=$rootA;target_pids_a=@($targetsA);exit_code_a=$exitCodeA;
    root_b=$rootB;target_pids_b=@($targetsB);exit_code_b=$exitCodeB;
    system_display_4101_before=$before;system_display_4101_after=$after;
    stdout_a=(Join-Path $outDir "a_stdout.txt");stderr_a=(Join-Path $outDir "a_stderr.txt");
    stdout_b=(Join-Path $outDir "b_stdout.txt");stderr_b=(Join-Path $outDir "b_stderr.txt");
    exit_code_file_a=$exitA;exit_code_file_b=$exitB}
$meta|ConvertTo-Json -Depth 8|Set-Content -Encoding utf8 (Join-Path $outDir "pair_meta.json")
([ordered]@{samples=$samples}|ConvertTo-Json -Depth 8)|Set-Content -Encoding utf8 (Join-Path $outDir "gpu_counters.json")
Get-Content (Join-Path $outDir "a_stdout.txt")
Get-Content (Join-Path $outDir "a_stderr.txt")
Get-Content (Join-Path $outDir "b_stdout.txt")
Get-Content (Join-Path $outDir "b_stderr.txt")
"PAIR_META=$(Join-Path $outDir 'pair_meta.json')"
