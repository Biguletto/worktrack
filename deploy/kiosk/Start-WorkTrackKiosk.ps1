param(
    [string]$WorkTrackUrl = "http://127.0.0.1:8000/accounts/attendance/kiosk/"
)

$ErrorActionPreference = "Stop"

$chromeCandidates = @(
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $chromeCandidates) {
    Write-Error "Google Chrome was not found. Install Chrome or open the kiosk URL manually in a supported browser."
    exit 1
}

$chrome = $chromeCandidates[0]
$profilePath = Join-Path $env:LOCALAPPDATA "WorkTrackKiosk\ChromeProfile"
New-Item -ItemType Directory -Force -Path $profilePath | Out-Null

Write-Host "Starting WorkTrack in Chrome kiosk display mode..." -ForegroundColor Green
Write-Host "On first use, sign in with the dedicated Administrator account and confirm its password to activate the scanner." -ForegroundColor Yellow
Write-Host "This browser display mode does not disable Windows shortcuts or replace Windows Assigned Access." -ForegroundColor Yellow

$arguments = @(
    "--kiosk",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-translate",
    "--user-data-dir=`"$profilePath`"",
    $WorkTrackUrl
)

Start-Process -FilePath $chrome -ArgumentList $arguments
