[CmdletBinding()]
param(
  [string]$LanIp = "",

  [int]$LocalPort = 8001,

  [ValidateSet("debug", "release")]
  [string]$Mode = "release",

  [switch]$StartApi
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "path_safety.ps1")
$PowerShell = Get-ChildPowerShellCommand
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}

$OutputsDir = Join-Path $ProjectRoot "outputs"
$DownloadDir = Join-Path $ProjectRoot "outputs\phone_download"
$StatusPath = Join-Path $DownloadDir "VerityLens-lan-status.md"
$FlutterRoot = Join-Path $ProjectRoot "apps\fake_news_detector_flutter"
$BuildScript = Join-Path $ProjectRoot "apps\fake_news_detector_flutter\tool\build_internet_apk.ps1"
. (Join-Path $FlutterRoot "tool\flutter_source_stamp.ps1")
$StartedApiProcess = $null

function Get-DefaultLanIp {
  $Candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*" -and
      $_.PrefixOrigin -ne "WellKnown" -and
      $_.InterfaceAlias -notmatch "Loopback|vEthernet|Virtual|VMware|VirtualBox|WSL"
    } |
    Sort-Object InterfaceMetric, InterfaceIndex
  if ($Candidates) {
    return $Candidates[0].IPAddress
  }
  throw "Could not detect a LAN IPv4 address. Pass -LanIp manually, for example -LanIp 192.168.1.16."
}

function Test-LocalApi {
  param([Parameter(Mandatory = $true)][int]$Port)
  try {
    $Health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 4
    return $Health.status -eq "ok"
  } catch {
    return $false
  }
}

New-Item -ItemType Directory -Force -Path $OutputsDir, $DownloadDir | Out-Null

if (-not $LanIp.Trim()) {
  $LanIp = Get-DefaultLanIp
}

$ParsedIp = $null
if (-not [System.Net.IPAddress]::TryParse($LanIp, [ref]$ParsedIp) -or $ParsedIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
  throw "LAN IP must be an IPv4 address, got '$LanIp'."
}

if (-not (Test-LocalApi -Port $LocalPort)) {
  if (-not $StartApi) {
    throw "Local API is not healthy on port $LocalPort. Start it or pass -StartApi."
  }
  $StartedApiProcess = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "src.api_factcheck:app", "--host", "0.0.0.0", "--port", "$LocalPort") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput (Join-Path $OutputsDir "phone-lan-api.log") `
    -RedirectStandardError (Join-Path $OutputsDir "phone-lan-api.err.log") `
    -WindowStyle Hidden `
    -PassThru

  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-LocalApi -Port $LocalPort) {
      break
    }
  }
}

if (-not (Test-LocalApi -Port $LocalPort)) {
  if ($StartedApiProcess -and -not $StartedApiProcess.HasExited) {
    Stop-Process -Id $StartedApiProcess.Id -Force -ErrorAction SilentlyContinue
  }
  throw "Local API did not become healthy on http://127.0.0.1:$LocalPort/health"
}

$ApiBaseUrl = "http://$LanIp`:$LocalPort"
& $PowerShell -NoProfile -ExecutionPolicy Bypass -File $BuildScript `
  -ApiBaseUrl $ApiBaseUrl `
  -Mode $Mode `
  -OutputName "VerityLens-lan.apk"
if ($LASTEXITCODE -ne 0) {
  throw "LAN APK build failed with exit code $LASTEXITCODE"
}

$ApkPath = Join-Path $DownloadDir "VerityLens-lan.apk"
$LanUrlPath = Join-Path $DownloadDir "VerityLens-lan-api-url.txt"
if (-not (Test-Path $ApkPath)) {
  throw "LAN APK was not produced: $ApkPath"
}

Set-Content -Path $LanUrlPath -Value $ApiBaseUrl -Encoding UTF8

$Apk = Get-Item -LiteralPath $ApkPath
$ApkHash = Get-FileHash -LiteralPath $Apk.FullName -Algorithm SHA256
$FlutterSourceStamp = Get-FlutterSourceStamp -FlutterRoot $FlutterRoot
$CreatedAt = (Get-Date).ToString("o")
@(
  "# Verity Lens LAN Phone Build",
  "",
  "- Created: ``$CreatedAt``",
  "- APK mode: ``$Mode``",
  "- API base URL: ``$ApiBaseUrl``",
  "- API health on this PC: ``ok``",
  "- Flutter source SHA256: ``$($FlutterSourceStamp.sha256)``",
  "- Flutter source files: ``$($FlutterSourceStamp.file_count)``",
  "- APK: ``$($Apk.FullName)``",
  "- APK size bytes: ``$($Apk.Length)``",
  "- APK SHA256: ``$($ApkHash.Hash)``",
  "",
  "Install this APK on a phone connected to the same Wi-Fi network as this PC. Keep the local API running. If the phone cannot connect, check Windows Firewall and confirm that the phone can reach ``$ApiBaseUrl/health``."
) | Set-Content -Path $StatusPath -Encoding UTF8

Get-Item -LiteralPath $ApkPath | Select-Object FullName, Length, LastWriteTime
