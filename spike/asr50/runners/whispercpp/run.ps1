param(
    [Parameter(Mandatory=$true)][string]$Model,
    [Parameter(Mandatory=$true)][string]$Audio,
    [Parameter(Mandatory=$true)][string]$Output,
    [ValidateSet("cpu-vulkan","cpu-only","vulkan")][string]$Device = "cpu-vulkan",
    [int]$Threads = 12,
    [string]$Dtw = ""
)

$ErrorActionPreference = "Stop"
$root = "C:\scratch\asr50\WP8"
$binaryDir = if ($Device -eq "cpu-only") { Join-Path $root "bin\cpu" } else { Join-Path $root "bin\vulkan" }
$argsList = @("-m", $Model, "-f", $Audio, "-l", "en", "-t", "$Threads", "-ojf", "-of", $Output)
if ($Device -ne "vulkan") { $argsList += "-ng" } else { $argsList += @("-dev", "0") }
if ($Dtw) { $argsList += @("-dtw", $Dtw) }
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
& (Join-Path $binaryDir "whisper-cli.exe") @argsList
exit $LASTEXITCODE
