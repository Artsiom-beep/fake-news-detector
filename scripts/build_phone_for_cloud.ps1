[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$ApiBaseUrl,

  [ValidateSet("debug", "release")]
  [string]$Mode = "release",

  [string]$OutputName = "VerityLens-cloud.apk"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "cloud_url_policy.ps1")
. (Join-Path $PSScriptRoot "path_safety.ps1")
$OutputName = Assert-ApkOutputName -Name $OutputName
$ApiBaseUrl = Assert-PermanentCloudApiUrl -Value $ApiBaseUrl -Purpose "Cloud phone build API"

Write-Host "Checking cloud API: $ApiBaseUrl" -ForegroundColor Cyan
$Health = Invoke-RestMethod -Uri "$ApiBaseUrl/health" -TimeoutSec 45
if ($Health.status -ne "ok") {
  throw "Cloud API /health did not return status=ok."
}

$Ready = Invoke-RestMethod -Uri "$ApiBaseUrl/ready" -TimeoutSec 45
if ($Ready.status -ne "ready") {
  throw "Cloud API /ready did not return status=ready."
}

$ProbeBody = @{ text = "Elephants are insects." } | ConvertTo-Json -Compress
$Probe = Invoke-RestMethod -Uri "$ApiBaseUrl/factcheck" -Method Post -ContentType "application/json" -Body $ProbeBody -TimeoutSec 90
if ($Probe.verdict -ne "fake") {
  throw "Cloud API fact-check probe failed. Expected verdict=fake, got '$($Probe.verdict)'."
}

Write-Host "Cloud API OK. Building APK..." -ForegroundColor Green
$BuildScript = Join-Path $PSScriptRoot "..\apps\fake_news_detector_flutter\tool\build_internet_apk.ps1"
& $BuildScript -ApiBaseUrl $ApiBaseUrl -Mode $Mode -OutputName $OutputName

$DownloadDir = Join-Path $ProjectRoot "outputs\phone_download"
$FlutterRoot = Join-Path $ProjectRoot "apps\fake_news_detector_flutter"
. (Join-Path $FlutterRoot "tool\flutter_source_stamp.ps1")
$ApkPath = Join-Path $DownloadDir $OutputName
if (-not (Test-Path $ApkPath)) {
  throw "Cloud APK was not produced: $ApkPath"
}

$Apk = Get-Item -LiteralPath $ApkPath
$ApkHash = Get-FileHash -LiteralPath $Apk.FullName -Algorithm SHA256
$FlutterSourceStamp = Get-FlutterSourceStamp -FlutterRoot $FlutterRoot
$CreatedAt = (Get-Date).ToString("o")
$UrlPath = Join-Path $DownloadDir "VerityLens-cloud-api-url.txt"
$StatusPath = Join-Path $DownloadDir "VerityLens-cloud-status.md"
Set-Content -Path $UrlPath -Value $ApiBaseUrl -Encoding UTF8
@(
  "# Verity Lens Cloud Phone Build",
  "",
  "- Created: ``$CreatedAt``",
  "- APK mode: ``$Mode``",
  "- Public API: ``$ApiBaseUrl``",
  "- API health: ``$($Health.status)``",
  "- API ready: ``$($Ready.status)``",
  "- Fake probe: ``$($Probe.verdict) / $($Probe.confidence)``",
  "- Flutter source SHA256: ``$($FlutterSourceStamp.sha256)``",
  "- Flutter source files: ``$($FlutterSourceStamp.file_count)``",
  "- APK: ``$($Apk.FullName)``",
  "- APK size bytes: ``$($Apk.Length)``",
  "- APK SHA256: ``$($ApkHash.Hash)``",
  "",
  "This APK targets the permanent public HTTPS backend above."
) | Set-Content -Path $StatusPath -Encoding UTF8
