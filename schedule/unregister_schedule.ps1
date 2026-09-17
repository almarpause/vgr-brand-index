# Remove the VGR Brand Score scheduled tasks.
#   powershell -ExecutionPolicy Bypass -File schedule\unregister_schedule.ps1
$ErrorActionPreference = "Continue"
foreach ($task in @("VBI-FetchNightly", "VBI-Monthly")) {
  schtasks /Delete /TN $task /F
}
