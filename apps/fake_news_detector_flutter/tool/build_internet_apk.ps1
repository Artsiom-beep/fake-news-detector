[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$ApiBaseUrl,

  [ValidateSet("debug", "release")]
  [string]$Mode = "debug",

  [string]$OutputName = "VerityLens-internet.apk"
)

$ErrorActionPreference = "Stop"

function Normalize-ApiUrl {
  param([Parameter(Mandatory = $true)][string]$Value)
  $Trimmed = $Value.Trim()
  if (-not $Trimmed) {
    throw "API URL cannot be empty."
  }
  if ($Trimmed.EndsWith("/")) {
    $Trimmed = $Trimmed.TrimEnd("/")
  }
  $Uri = $null
  if (-not [System.Uri]::TryCreate($Trimmed, [System.UriKind]::Absolute, [ref]$Uri)) {
    throw "API URL must be absolute, for example https://your-api.onrender.com"
  }
  if ($Uri.Scheme -notin @("http", "https")) {
    throw "API URL must use http or https."
  }
  return $Trimmed
}

$ApiBaseUrl = Normalize-ApiUrl $ApiBaseUrl
$FlutterRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProjectRoot = (Resolve-Path (Join-Path $FlutterRoot "..\..")).Path
. (Join-Path $ProjectRoot "scripts\path_safety.ps1")
$OutputName = Assert-ApkOutputName -Name $OutputName
$DownloadDir = Join-Path $ProjectRoot "outputs\phone_download"
$OutputPath = Join-Path $DownloadDir $OutputName
. (Join-Path $PSScriptRoot "flutter_source_stamp.ps1")
$FlutterSourceStamp = Get-FlutterSourceStamp -FlutterRoot $FlutterRoot

Push-Location $FlutterRoot
try {
  New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null

  Write-Host "Building Verity Lens APK for API: $ApiBaseUrl" -ForegroundColor Cyan
  if ($Mode -eq "release") {
    flutter build apk --release "--dart-define=API_BASE_URL=$ApiBaseUrl"
    $BuiltApk = Join-Path $FlutterRoot "build\app\outputs\flutter-apk\app-release.apk"
  } else {
    flutter build apk --debug "--dart-define=API_BASE_URL=$ApiBaseUrl"
    $BuiltApk = Join-Path $FlutterRoot "build\app\outputs\flutter-apk\app-debug.apk"
  }

  if (-not (Test-Path $BuiltApk)) {
    throw "Flutter did not produce APK: $BuiltApk"
  }

  Copy-Item -LiteralPath $BuiltApk -Destination $OutputPath -Force
  $ApkBaseName = [System.IO.Path]::GetFileNameWithoutExtension($OutputName)
  $StatusName = if ($OutputName -eq "VerityLens-internet.apk") { "PHONE_BUILD_STATUS.md" } else { "$ApkBaseName-status.md" }
  $Apk = Get-Item -LiteralPath $OutputPath
  $ApkHash = Get-FileHash -LiteralPath $Apk.FullName -Algorithm SHA256
  $CreatedAt = (Get-Date).ToString("o")
  Set-Content -Path (Join-Path $DownloadDir "$ApkBaseName-api-url.txt") -Value $ApiBaseUrl -Encoding UTF8
  $FlutterSourceStamp | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $DownloadDir "$ApkBaseName-flutter-source-stamp.json") -Encoding UTF8
  @(
    "# Verity Lens Phone Build",
    "",
    "- Created: ``$CreatedAt``",
    "- APK mode: ``$Mode``",
    "- API base URL: ``$ApiBaseUrl``",
    "- Flutter source SHA256: ``$($FlutterSourceStamp.sha256)``",
    "- Flutter source files: ``$($FlutterSourceStamp.file_count)``",
    "- APK: ``$($Apk.FullName)``",
    "- APK size bytes: ``$($Apk.Length)``",
    "- APK SHA256: ``$($ApkHash.Hash)``"
  ) | Set-Content -Path (Join-Path $DownloadDir $StatusName) -Encoding UTF8
  Write-Host "APK ready: $OutputPath" -ForegroundColor Green
}
finally {
  Pop-Location
}
