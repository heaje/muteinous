param(
  [Parameter(Mandatory=$true)][int]$TargetPID,
  [Parameter(Mandatory=$true)][string]$OutFile
)
$ErrorActionPreference = "Continue"
$rows = [System.Collections.Generic.List[object]]::new()
$self = [Diagnostics.Process]::GetCurrentProcess()
$self.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
$deadline = [DateTime]::UtcNow.AddSeconds(600)
while ([DateTime]::UtcNow -lt $deadline -and (Get-Process -Id $TargetPID -ErrorAction SilentlyContinue)) {
  $now = [DateTime]::UtcNow.ToString("o")
  foreach ($setName in @("GPU Engine","GPU Process Memory")) {
    try {
      $set = Get-Counter -ListSet $setName -ErrorAction Stop
      $paths = @($set.PathsWithInstances | Where-Object {
        $_ -match "pid_$TargetPID(_|\\)" -and
        $_ -match 'luid_0x00000000_0x000164ac' -and
        (($setName -eq "GPU Engine" -and $_ -match '\\Utilization Percentage$') -or
         ($setName -eq "GPU Process Memory" -and $_ -match '\\Dedicated Usage$'))
      })
      if ($paths.Count) {
        $sample = Get-Counter -Counter $paths -MaxSamples 1 -ErrorAction Stop
        foreach ($c in $sample.CounterSamples | Where-Object { $_.Status -eq 0 }) {
          $rows.Add([pscustomobject]@{utc=$now;counter_set=$setName;pid=$TargetPID;path=$c.Path;value=$c.CookedValue})
        }
      } else {
        $rows.Add([pscustomobject]@{utc=$now;counter_set=$setName;pid=$TargetPID;matching_instances=0})
      }
    } catch {
      $rows.Add([pscustomobject]@{utc=$now;counter_set=$setName;pid=$TargetPID;error=$_.Exception.Message})
    }
  }
  $rows | ForEach-Object { $_ | ConvertTo-Json -Compress } | Set-Content -Encoding UTF8 $OutFile
  Start-Sleep -Seconds 1
}
