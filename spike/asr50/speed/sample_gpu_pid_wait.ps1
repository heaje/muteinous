param(
  [Parameter(Mandatory=$true)][string]$PidFile,
  [Parameter(Mandatory=$true)][string]$ReadyFile,
  [Parameter(Mandatory=$true)][string]$OutFile
)
$ErrorActionPreference = "Continue"
$self = [Diagnostics.Process]::GetCurrentProcess()
$self.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
Set-Content -LiteralPath $ReadyFile -Value "ready" -Encoding ASCII
$deadline = [DateTime]::UtcNow.AddSeconds(60)
while (-not (Test-Path -LiteralPath $PidFile) -and [DateTime]::UtcNow -lt $deadline) {
  Start-Sleep -Milliseconds 100
}
if (-not (Test-Path -LiteralPath $PidFile)) { exit 2 }
$targetPID = [int](Get-Content -LiteralPath $PidFile -Raw)
$rows = [System.Collections.Generic.List[object]]::new()
$writer = [IO.StreamWriter]::new($OutFile,$false,[Text.Encoding]::UTF8)
try {
  $whileDeadline = [DateTime]::UtcNow.AddSeconds(600)
  while ([DateTime]::UtcNow -lt $whileDeadline -and
         (Get-Process -Id $targetPID -ErrorAction SilentlyContinue)) {
    $now = [DateTime]::UtcNow.ToString("o")
    foreach ($setName in @("GPU Engine","GPU Process Memory")) {
      try {
        $set = Get-Counter -ListSet $setName -ErrorAction Stop
        $paths = @($set.PathsWithInstances | Where-Object {
          $_ -match 'luid_0x00000000_0x000164ac' -and
          (($setName -eq "GPU Engine" -and $_ -match 'engtype_(3d|compute)' -and $_ -match '\\Utilization Percentage$') -or
           ($setName -eq "GPU Process Memory" -and $_ -match '\\Dedicated Usage$'))
        })
        if ($paths.Count) {
          $sample = Get-Counter -Counter $paths -MaxSamples 1 -ErrorAction Stop
          foreach ($c in $sample.CounterSamples | Where-Object { $_.Status -eq 0 }) {
            $pidMatched = $c.Path -match "pid_$targetPID(_|\\)"
            $rows.Add([pscustomobject]@{utc=$now;counter_set=$setName;pid=$targetPID;
              pid_matched=$pidMatched;path=$c.Path;value=$c.CookedValue})
          }
        } else {
          $rows.Add([pscustomobject]@{utc=$now;counter_set=$setName;pid=$targetPID;
            pid_matching_instances=0;adapter_matching_instances=0})
        }
      } catch {
        $rows.Add([pscustomobject]@{utc=$now;counter_set=$setName;pid=$targetPID;error=$_.Exception.Message})
      }
    }
    foreach ($row in $rows) {
      $writer.WriteLine(($row | ConvertTo-Json -Compress))
    }
    $rows.Clear()
    $writer.Flush()
    Start-Sleep -Seconds 1
  }
} finally {
  $writer.Dispose()
}
