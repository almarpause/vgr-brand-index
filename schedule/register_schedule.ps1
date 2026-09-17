# Register the VGR Brand Score with Windows Task Scheduler — two jobs, both at
# night, mirroring the polyamide-index pattern:
#
#   VBI-FetchNightly : every day at 02:30 — fetches one staggered shard of brand
#                      signals (pageviews, GDELT, Trends). Over ~a month the whole
#                      universe is refreshed gently, never hammering any endpoint.
#   VBI-Monthly      : the 1st of each month at 04:00 — assembles the shot from
#                      cache, builds the .docx report, and emails it.
#
# UNATTENDED (default): runs as SYSTEM with highest privileges whether or not you
# are logged on. MUST be run from an ELEVATED (Run as administrator) PowerShell:
#   powershell -ExecutionPolicy Bypass -File schedule\register_schedule.ps1
#
# Under YOUR account instead (e.g. if SMTP/network needs your profile), pass
# -CurrentUser (schtasks will prompt for your password):
#   powershell -ExecutionPolicy Bypass -File schedule\register_schedule.ps1 -CurrentUser

param([switch]$CurrentUser)

$ErrorActionPreference = "Stop"
$nightlyBat = Join-Path $PSScriptRoot "fetch_nightly.bat"
$monthlyBat = Join-Path $PSScriptRoot "run_monthly.bat"
foreach ($b in @($nightlyBat, $monthlyBat)) {
  if (-not (Test-Path $b)) { throw "launcher not found: $b" }
}

function Quote($p) { if ($p -match '\s') { '"' + $p + '"' } else { $p } }

function Register-Job($task, $bat, [string[]]$scheduleArgs) {
  $tr = Quote $bat
  Write-Host "task   : $task -> $bat"
  if ($CurrentUser) {
    schtasks /Create @scheduleArgs /TN $task /TR $tr /RL HIGHEST /RU $env:USERNAME /IT /F
  } else {
    schtasks /Create @scheduleArgs /TN $task /TR $tr /RU SYSTEM /RL HIGHEST /F
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Create failed for $task (exit $LASTEXITCODE). SYSTEM tasks need an ELEVATED shell; or retry with -CurrentUser."
    exit $LASTEXITCODE
  }
}

Register-Job "VBI-FetchNightly" $nightlyBat @("/SC", "DAILY", "/ST", "02:30")
Register-Job "VBI-Monthly"      $monthlyBat @("/SC", "MONTHLY", "/D", "1", "/ST", "04:00")

Write-Host ""
Write-Host "Registered both jobs. Verify:"
Write-Host "  schtasks /Query /TN VBI-FetchNightly /V /FO LIST"
Write-Host "  schtasks /Query /TN VBI-Monthly /V /FO LIST"
Write-Host "Trigger once now:"
Write-Host "  schtasks /Run /TN VBI-FetchNightly"
Write-Host "  schtasks /Run /TN VBI-Monthly     (builds AND emails)"
