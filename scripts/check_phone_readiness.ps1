[CmdletBinding()]
param(
  [string]$ApiBaseUrl = "",
  [switch]$RequireCloud
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutputDir = Join-Path $ProjectRoot "outputs\phone_download"
$JsonOut = Join-Path $OutputDir "phone_readiness.json"
$MarkdownOut = Join-Path $OutputDir "PHONE_READINESS.md"
. (Join-Path $PSScriptRoot "cloud_url_policy.ps1")

function Test-HttpJson {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSec = 15,
    [int]$Attempts = 1,
    [int]$RetryDelaySeconds = 2
  )
  $TotalAttempts = [Math]::Max(1, $Attempts)
  $LastError = ""
  for ($Attempt = 1; $Attempt -le $TotalAttempts; $Attempt++) {
    try {
      $Response = Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec
      return [ordered]@{ ok = $true; value = $Response; error = $null; attempts = $Attempt }
    } catch {
      $LastError = $_.Exception.Message
    }
    if ($Attempt -lt $TotalAttempts) {
      Start-Sleep -Seconds $RetryDelaySeconds
    }
  }
  return [ordered]@{ ok = $false; value = $null; error = $LastError; attempts = $TotalAttempts }
}

function Test-FactcheckProbe {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSec = 60,
    [int]$Attempts = 3,
    [int]$RetryDelaySeconds = 2
  )
  $TotalAttempts = [Math]::Max(1, $Attempts)
  $LastError = ""
  for ($Attempt = 1; $Attempt -le $TotalAttempts; $Attempt++) {
    try {
      $Probe = Invoke-RestMethod `
        -Uri $Url `
        -Method Post `
        -ContentType "application/json" `
        -Body (@{ text = "Elephants are insects." } | ConvertTo-Json -Compress) `
        -TimeoutSec $TimeoutSec
      return [ordered]@{ ok = $true; value = $Probe; error = ""; attempts = $Attempt }
    } catch {
      $LastError = $_.Exception.Message
    }
    if ($Attempt -lt $TotalAttempts) {
      Start-Sleep -Seconds $RetryDelaySeconds
    }
  }
  return [ordered]@{ ok = $false; value = $null; error = $LastError; attempts = $TotalAttempts }
}

function Read-JsonFile {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    return $null
  }
  try {
    return Get-Content $Path -Raw | ConvertFrom-Json
  } catch {
    return $null
  }
}

function Invoke-BasicHttpRequest {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [ValidateSet("GET", "HEAD")]
    [string]$Method = "GET",
    [int]$TimeoutSec = 10
  )

  $Result = [ordered]@{
    ok = $false
    status_code = 0
    content = ""
    headers = @{}
    error = ""
  }

  $Request = [System.Net.HttpWebRequest]::Create($Url)
  $Request.Method = $Method
  $Request.Timeout = $TimeoutSec * 1000
  $Request.AllowAutoRedirect = $true
  $Response = $null
  try {
    $Response = [System.Net.HttpWebResponse]$Request.GetResponse()
    $Result.status_code = [int]$Response.StatusCode
    foreach ($Key in $Response.Headers.AllKeys) {
      $Result.headers[$Key] = $Response.Headers[$Key]
    }
    if ($Method -ne "HEAD") {
      $Stream = $Response.GetResponseStream()
      $Reader = New-Object System.IO.StreamReader($Stream, [System.Text.Encoding]::UTF8)
      try {
        $Result.content = $Reader.ReadToEnd()
      } finally {
        $Reader.Dispose()
        $Stream.Dispose()
      }
    }
    $Result.ok = $true
  } catch {
    $Result.error = $_.Exception.Message
  } finally {
    if ($Response) {
      $Response.Dispose()
    }
  }

  return $Result
}

function Test-InstallDownload {
  param(
    [Parameter(Mandatory = $true)][string]$JsonPath,
    [int]$TimeoutSec = 10
  )

  $Status = [ordered]@{
    exists = $false
    page_url = ""
    download_url = ""
    page_status = "not_checked"
    download_status = "not_checked"
    download_content_length = 0
    expected_apk_size_bytes = 0
    page_ok = $false
    download_ok = $false
    ok = $false
    error = ""
  }

  if (-not (Test-Path $JsonPath)) {
    $Status.error = "PHONE_INSTALL_PAGE.json not found"
    return $Status
  }

  $Status.exists = $true
  try {
    $InstallInfo = Get-Content $JsonPath -Raw | ConvertFrom-Json
    $Status.page_url = if ($InstallInfo.page_url) { [string]$InstallInfo.page_url } else { "" }
    $Status.download_url = if ($InstallInfo.download_url) { [string]$InstallInfo.download_url } else { "" }
    if ($InstallInfo.apk -and $InstallInfo.apk.size_bytes) {
      $Status.expected_apk_size_bytes = [long]$InstallInfo.apk.size_bytes
    }
  } catch {
    $Status.error = "install page json: $($_.Exception.Message)"
    return $Status
  }

  if (-not $Status.page_url -or -not $Status.download_url) {
    $Status.error = "install page json does not include page_url and download_url"
    return $Status
  }

  $PageResponse = Invoke-BasicHttpRequest -Url $Status.page_url -Method GET -TimeoutSec $TimeoutSec
  $Status.page_status = if ($PageResponse.ok) { [string]$PageResponse.status_code } else { "failed" }
  $Status.page_ok = ($PageResponse.status_code -eq 200 -and $PageResponse.content -match "Verity Lens")
  if (-not $PageResponse.ok) {
    $Status.page_status = "failed"
    $Status.error = "install page: $($PageResponse.error)"
    return $Status
  }
  if (-not $Status.page_ok) {
    $Status.error = "install page did not return HTTP 200 with Verity Lens content"
    return $Status
  }

  $DownloadResponse = Invoke-BasicHttpRequest -Url $Status.download_url -Method HEAD -TimeoutSec $TimeoutSec
  $Status.download_status = if ($DownloadResponse.ok) { [string]$DownloadResponse.status_code } else { "failed" }
  $LengthHeader = $DownloadResponse.headers["Content-Length"]
  $ParsedLength = 0L
  if ([long]::TryParse([string]$LengthHeader, [ref]$ParsedLength)) {
    $Status.download_content_length = $ParsedLength
  }
  $SizeMatches = ($Status.expected_apk_size_bytes -le 0 -or $Status.download_content_length -eq $Status.expected_apk_size_bytes)
  $Status.download_ok = ($DownloadResponse.status_code -eq 200 -and $SizeMatches)
  if (-not $DownloadResponse.ok) {
    $Status.download_status = "failed"
    $Status.error = "APK download: $($DownloadResponse.error)"
    return $Status
  }
  if (-not $Status.download_ok) {
    $Status.error = "APK download did not return HTTP 200 with expected content length"
    return $Status
  }

  $Status.ok = ($Status.page_ok -and $Status.download_ok)
  return $Status
}

function Read-ApkVerification {
  param(
    [Parameter(Mandatory = $true)][string]$JsonPath,
    [string]$ExpectedApiUrl = ""
  )

  $Status = [ordered]@{
    exists = $false
    path = $JsonPath
    ok = $false
    api_base_url = ""
    expected_mode = ""
    is_release_mode = $false
    matches_expected_api_url = $false
    embedded_api_url_found = $false
    embedded_api_url_match_count = 0
    flutter_source_stamp_sidecar_exists = $false
    flutter_source_stamp_matches_current_source = $false
    status_matches_flutter_source_stamp = $false
    error = ""
  }

  if (-not (Test-Path $JsonPath)) {
    $Status.error = "APK verification json not found"
    return $Status
  }

  $Status.exists = $true
  try {
    $Payload = Get-Content $JsonPath -Raw | ConvertFrom-Json
    $Status.ok = [bool]$Payload.ok
    if ($Payload.api -and $Payload.api.base_url) {
      $Status.api_base_url = [string]$Payload.api.base_url
    }
    if ($Payload.apk -and $Payload.apk.expected_mode) {
      $Status.expected_mode = [string]$Payload.apk.expected_mode
      $Status.is_release_mode = ($Status.expected_mode -eq "release")
    }
    $Status.matches_expected_api_url = (
      -not $ExpectedApiUrl -or
      $Status.api_base_url.Trim().TrimEnd("/") -eq $ExpectedApiUrl.Trim().TrimEnd("/")
    )
    if ($Payload.embedded_api_url) {
      $Status.embedded_api_url_found = [bool]$Payload.embedded_api_url.found
      if ($Payload.embedded_api_url.match_count -ne $null) {
        $Status.embedded_api_url_match_count = [int]$Payload.embedded_api_url.match_count
      }
    }
    if ($Payload.flutter_source_stamp) {
      $Status.flutter_source_stamp_sidecar_exists = [bool]$Payload.flutter_source_stamp.sidecar_exists
      $Status.flutter_source_stamp_matches_current_source = [bool]$Payload.flutter_source_stamp.matches_current_source
    }
    if ($Payload.status_file) {
      $Status.status_matches_flutter_source_stamp = [bool]$Payload.status_file.matches_flutter_source_stamp
    }
  } catch {
    $Status.error = $_.Exception.Message
  }

  if (-not $Status.error -and -not $Status.matches_expected_api_url) {
    $Status.error = "APK verification API URL does not match expected API URL"
  }
  return $Status
}

function Get-FileStatus {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    return [ordered]@{ exists = $false; path = $Path; size_bytes = 0; modified_at = $null }
  }
  $Item = Get-Item -LiteralPath $Path
  return [ordered]@{
    exists = $true
    path = $Item.FullName
    size_bytes = $Item.Length
    modified_at = $Item.LastWriteTime.ToString("o")
  }
}

function Normalize-ApiUrl {
  param([string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) {
    return ""
  }
  return Assert-PermanentCloudApiUrl -Value $Value -Purpose "Permanent cloud phone readiness API"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$LanStatusPath = Join-Path $OutputDir "VerityLens-lan-status.md"
$CloudApkPath = Join-Path $OutputDir "VerityLens-cloud.apk"
$LanApkPath = Join-Path $OutputDir "VerityLens-lan.apk"
$InternetApkPath = Join-Path $OutputDir "VerityLens-internet.apk"
$RenderBundlePath = Join-Path $ProjectRoot "outputs\cloud_deploy\verity-lens-render-backend.zip"
$DesktopZipPath = Join-Path $ProjectRoot "dist\FakeNewsDetector-Windows-Portable.zip"
$ReportPdfPath = Join-Path $ProjectRoot "docs\report\verity_lens_report.pdf"
$TunnelInfoPath = Join-Path $ProjectRoot "outputs\public_api_tunnel_info.json"
$ApkVerificationPath = Join-Path $OutputDir "PHONE_APK_VERIFICATION.md"
$ApkVerificationJsonPath = Join-Path $OutputDir "PHONE_APK_VERIFICATION.json"
$LanApkVerificationPath = Join-Path $OutputDir "PHONE_LAN_APK_VERIFICATION.md"
$LanApkVerificationJsonPath = Join-Path $OutputDir "PHONE_LAN_APK_VERIFICATION.json"
$CloudApkVerificationPath = Join-Path $OutputDir "PHONE_CLOUD_APK_VERIFICATION.md"
$CloudApkVerificationJsonPath = Join-Path $OutputDir "PHONE_CLOUD_APK_VERIFICATION.json"
$DeviceSmokePath = Join-Path $OutputDir "PHONE_DEVICE_SMOKE.md"
$DeviceSmokeJsonPath = Join-Path $OutputDir "PHONE_DEVICE_SMOKE.json"
$EmulatorSmokePath = Join-Path $OutputDir "PHONE_EMULATOR_SMOKE.md"
$EmulatorSmokeJsonPath = Join-Path $OutputDir "PHONE_EMULATOR_SMOKE.json"
$InstallPagePath = Join-Path $OutputDir "PHONE_INSTALL_PAGE.md"
$InstallPageJsonPath = Join-Path $OutputDir "PHONE_INSTALL_PAGE.json"

$CloudUrl = Normalize-ApiUrl $ApiBaseUrl
$CloudUri = $null
$CloudIsTemporaryTunnel = $false
if ($CloudUrl) {
  [void][System.Uri]::TryCreate($CloudUrl, [System.UriKind]::Absolute, [ref]$CloudUri)
  if ($CloudUri -and (Test-TemporaryTunnelHost -HostName $CloudUri.Host)) {
    $CloudIsTemporaryTunnel = $true
  }
}
$CloudCheck = [ordered]@{
  requested = [bool]$CloudUrl
  api_base_url = $CloudUrl
  is_temporary_tunnel = $CloudIsTemporaryTunnel
  health = "not_checked"
  ready = "not_checked"
  fake_probe = "not_checked"
  ok = $false
  error = $null
}

if ($CloudUrl -and $CloudIsTemporaryTunnel) {
  $CloudCheck.error = "temporary tunnel URLs are not counted as permanent cloud readiness"
}
elseif ($CloudUrl) {
  $Health = Test-HttpJson "$CloudUrl/health" -TimeoutSec 45 -Attempts 3
  $Ready = Test-HttpJson "$CloudUrl/ready" -TimeoutSec 45 -Attempts 3
  $CloudCheck.health = if ($Health.ok) { $Health.value.status } else { "failed" }
  $CloudCheck.ready = if ($Ready.ok) { $Ready.value.status } else { "failed" }
  if (-not $Health.ok) {
    $CloudCheck.error = "health: $($Health.error)"
  } elseif (-not $Ready.ok) {
    $CloudCheck.error = "ready: $($Ready.error)"
  } else {
    $ProbeResult = Test-FactcheckProbe "$CloudUrl/factcheck" -TimeoutSec 90 -Attempts 3
    if ($ProbeResult.ok) {
      $Probe = $ProbeResult.value
      $CloudCheck.fake_probe = "$($Probe.verdict) / $($Probe.confidence)"
      $CloudCheck.ok = ($Health.value.status -eq "ok" -and $Ready.value.status -eq "ready" -and $Probe.verdict -eq "fake")
      if (-not $CloudCheck.ok) {
        $CloudCheck.error = "expected health=ok, ready=ready and fake probe verdict=fake"
      }
    } else {
      $CloudCheck.fake_probe = "failed"
      $CloudCheck.error = "factcheck: $($ProbeResult.error)"
    }
  }
}

$TunnelStatus = [ordered]@{
  exists = $false
  provider = ""
  status = "not_checked"
  public_api_url = ""
  health = "not_checked"
  ready = "not_checked"
  fake_probe = "not_checked"
  verified = $false
  last_checked_at = ""
  error = ""
}
if (Test-Path $TunnelInfoPath) {
  try {
    $TunnelInfo = Get-Content $TunnelInfoPath -Raw | ConvertFrom-Json
    $TunnelStatus.exists = $true
    $TunnelStatus.provider = if ($TunnelInfo.provider) { $TunnelInfo.provider } else { "cloudflare_quick_tunnel" }
    $TunnelStatus.status = if ($TunnelInfo.status) { $TunnelInfo.status } else { "active_or_unknown" }
    $TunnelStatus.public_api_url = if ($TunnelInfo.public_api_url) { $TunnelInfo.public_api_url } else { "" }
    $TunnelStatus.error = if ($TunnelInfo.error) { $TunnelInfo.error } else { "" }
  } catch {
    $TunnelStatus.exists = $true
    $TunnelStatus.provider = "unknown"
    $TunnelStatus.status = "unreadable"
    $TunnelStatus.error = $_.Exception.Message
  }
}

if ($TunnelStatus.public_api_url -and $TunnelStatus.status -in @("active_or_unknown", "active_verified")) {
  $TunnelUrl = $TunnelStatus.public_api_url.Trim().TrimEnd("/")
  $TunnelStatus.last_checked_at = (Get-Date).ToString("o")
  $TunnelHealth = Test-HttpJson "$TunnelUrl/health" -TimeoutSec 20 -Attempts 4
  $TunnelReady = Test-HttpJson "$TunnelUrl/ready" -TimeoutSec 20 -Attempts 4
  $TunnelStatus.health = if ($TunnelHealth.ok) { $TunnelHealth.value.status } else { "failed" }
  $TunnelStatus.ready = if ($TunnelReady.ok) { $TunnelReady.value.status } else { "failed" }
  if (-not $TunnelHealth.ok) {
    $TunnelStatus.status = "active_probe_failed"
    $TunnelStatus.error = "health: $($TunnelHealth.error)"
  } elseif (-not $TunnelReady.ok) {
    $TunnelStatus.status = "active_probe_failed"
    $TunnelStatus.error = "ready: $($TunnelReady.error)"
  } else {
    $TunnelProbeResult = Test-FactcheckProbe "$TunnelUrl/factcheck" -TimeoutSec 60 -Attempts 4
    if ($TunnelProbeResult.ok) {
      $TunnelProbe = $TunnelProbeResult.value
      $TunnelStatus.fake_probe = "$($TunnelProbe.verdict) / $($TunnelProbe.confidence)"
      $TunnelStatus.verified = (
        $TunnelHealth.value.status -eq "ok" -and
        $TunnelReady.value.status -eq "ready" -and
        $TunnelProbe.verdict -eq "fake"
      )
      if (-not $TunnelStatus.verified) {
        $TunnelStatus.status = "active_probe_failed"
        $TunnelStatus.error = "expected health=ok, ready=ready and fake probe verdict=fake"
      } else {
        $TunnelStatus.status = "active_verified"
      }
    } else {
      $TunnelStatus.status = "active_probe_failed"
      $TunnelStatus.fake_probe = "failed"
      $TunnelStatus.error = "factcheck: $($TunnelProbeResult.error)"
    }
  }
}

$InstallDownloadStatus = Test-InstallDownload $InstallPageJsonPath
$ApkVerification = Read-ApkVerification -JsonPath $ApkVerificationJsonPath -ExpectedApiUrl $TunnelStatus.public_api_url
$LanApkVerification = Read-ApkVerification -JsonPath $LanApkVerificationJsonPath
$CloudApkVerification = Read-ApkVerification -JsonPath $CloudApkVerificationJsonPath -ExpectedApiUrl $CloudUrl
$DeviceSmoke = Read-JsonFile $DeviceSmokeJsonPath
$EmulatorSmoke = Read-JsonFile $EmulatorSmokeJsonPath

$Artifacts = [ordered]@{
  lan_apk = Get-FileStatus $LanApkPath
  cloud_apk = Get-FileStatus $CloudApkPath
  internet_apk = Get-FileStatus $InternetApkPath
  lan_status = Get-FileStatus $LanStatusPath
  render_bundle = Get-FileStatus $RenderBundlePath
  desktop_zip = Get-FileStatus $DesktopZipPath
  report_pdf = Get-FileStatus $ReportPdfPath
  apk_verification = Get-FileStatus $ApkVerificationPath
  apk_verification_json = Get-FileStatus $ApkVerificationJsonPath
  lan_apk_verification = Get-FileStatus $LanApkVerificationPath
  cloud_apk_verification = Get-FileStatus $CloudApkVerificationPath
  phone_device_smoke = Get-FileStatus $DeviceSmokePath
  phone_emulator_smoke = Get-FileStatus $EmulatorSmokePath
  install_page = Get-FileStatus $InstallPagePath
}

$Ready = [ordered]@{
  pc_desktop = $Artifacts.desktop_zip.exists
  phone_same_wifi = (
    $Artifacts.lan_apk.exists -and
    $Artifacts.lan_status.exists -and
    $LanApkVerification.ok -and
    $LanApkVerification.is_release_mode -and
    $LanApkVerification.embedded_api_url_found
  )
  render_deploy_package = $Artifacts.render_bundle.exists
  phone_permanent_cloud = (
    $CloudCheck.ok -and
    -not $CloudCheck.is_temporary_tunnel -and
    $Artifacts.cloud_apk.exists -and
    $CloudApkVerification.ok -and
    $CloudApkVerification.is_release_mode -and
    $CloudApkVerification.matches_expected_api_url -and
    $CloudApkVerification.embedded_api_url_found
  )
  phone_install_download = $InstallDownloadStatus.ok
  phone_temporary_tunnel = (
    $TunnelStatus.verified -and
    $Artifacts.internet_apk.exists -and
    $InstallDownloadStatus.ok -and
    $ApkVerification.ok -and
    $ApkVerification.is_release_mode -and
    $ApkVerification.matches_expected_api_url -and
    $ApkVerification.embedded_api_url_found
  )
  phone_device_smoke = if ($DeviceSmoke) { [bool]$DeviceSmoke.ok } else { $false }
  phone_emulator_smoke = if ($EmulatorSmoke) { [bool]$EmulatorSmoke.ok } else { $false }
}

$Missing = @()
if (-not $Ready.pc_desktop) { $Missing += "desktop portable zip" }
if (-not $Ready.phone_same_wifi) { $Missing += "LAN release APK/status/verification" }
if (-not $Ready.render_deploy_package) { $Missing += "Render backend bundle" }
if ($RequireCloud -and -not $Ready.phone_permanent_cloud) { $Missing += "verified public HTTPS API and cloud APK" }

$Report = [ordered]@{
  generated_at = (Get-Date).ToString("o")
  artifacts = $Artifacts
  cloud_check = $CloudCheck
  quick_tunnel = $TunnelStatus
  internet_apk_verification = $ApkVerification
  lan_apk_verification = $LanApkVerification
  cloud_apk_verification = $CloudApkVerification
  phone_device_smoke = if ($DeviceSmoke) { $DeviceSmoke } else { $null }
  phone_emulator_smoke = if ($EmulatorSmoke) { $EmulatorSmoke } else { $null }
  install_download = $InstallDownloadStatus
  ready = $Ready
  missing_for_required_scope = $Missing
}

$Report | ConvertTo-Json -Depth 8 | Set-Content -Path $JsonOut -Encoding UTF8

$Lines = @(
  "# Verity Lens Phone Readiness",
  "",
  "- Generated: ``$($Report.generated_at)``",
  "- PC desktop package: ``$($Ready.pc_desktop)``",
  "- Phone on same Wi-Fi: ``$($Ready.phone_same_wifi)``",
  "- Render deploy package: ``$($Ready.render_deploy_package)``",
  "- Phone install/download: ``$($Ready.phone_install_download)``",
  "- Permanent cloud phone: ``$($Ready.phone_permanent_cloud)``",
  "- Temporary tunnel phone: ``$($Ready.phone_temporary_tunnel)``",
  "- Real Android device smoke: ``$($Ready.phone_device_smoke)``",
  "- Android emulator smoke: ``$($Ready.phone_emulator_smoke)``",
  "",
  "## Cloud",
  "",
  "- Checked URL: ``$($CloudCheck.api_base_url)``",
  "- Temporary tunnel URL: ``$($CloudCheck.is_temporary_tunnel)``",
  "- Health: ``$($CloudCheck.health)``",
  "- Ready: ``$($CloudCheck.ready)``",
  "- Fake probe: ``$($CloudCheck.fake_probe)``",
  "- Error: ``$($CloudCheck.error)``",
  "",
  "## Internet APK Verification",
  "",
  "- Exists: ``$($ApkVerification.exists)``",
  "- OK: ``$($ApkVerification.ok)``",
  "- Expected mode: ``$($ApkVerification.expected_mode)``",
  "- Release mode: ``$($ApkVerification.is_release_mode)``",
  "- API URL: ``$($ApkVerification.api_base_url)``",
  "- Matches quick tunnel URL: ``$($ApkVerification.matches_expected_api_url)``",
  "- Embedded API URL found: ``$($ApkVerification.embedded_api_url_found)``",
  "- Embedded API URL match count: ``$($ApkVerification.embedded_api_url_match_count)``",
  "- Flutter source stamp sidecar exists: ``$($ApkVerification.flutter_source_stamp_sidecar_exists)``",
  "- Flutter source stamp matches current source: ``$($ApkVerification.flutter_source_stamp_matches_current_source)``",
  "- Status matches Flutter source stamp: ``$($ApkVerification.status_matches_flutter_source_stamp)``",
  "- Error: ``$($ApkVerification.error)``",
  "",
  "## LAN APK Verification",
  "",
  "- Exists: ``$($LanApkVerification.exists)``",
  "- OK: ``$($LanApkVerification.ok)``",
  "- Expected mode: ``$($LanApkVerification.expected_mode)``",
  "- Release mode: ``$($LanApkVerification.is_release_mode)``",
  "- API URL: ``$($LanApkVerification.api_base_url)``",
  "- Embedded API URL found: ``$($LanApkVerification.embedded_api_url_found)``",
  "- Embedded API URL match count: ``$($LanApkVerification.embedded_api_url_match_count)``",
  "- Flutter source stamp sidecar exists: ``$($LanApkVerification.flutter_source_stamp_sidecar_exists)``",
  "- Flutter source stamp matches current source: ``$($LanApkVerification.flutter_source_stamp_matches_current_source)``",
  "- Status matches Flutter source stamp: ``$($LanApkVerification.status_matches_flutter_source_stamp)``",
  "- Error: ``$($LanApkVerification.error)``",
  "",
  "## Cloud APK Verification",
  "",
  "- Exists: ``$($CloudApkVerification.exists)``",
  "- OK: ``$($CloudApkVerification.ok)``",
  "- Expected mode: ``$($CloudApkVerification.expected_mode)``",
  "- Release mode: ``$($CloudApkVerification.is_release_mode)``",
  "- API URL: ``$($CloudApkVerification.api_base_url)``",
  "- Matches requested cloud URL: ``$($CloudApkVerification.matches_expected_api_url)``",
  "- Embedded API URL found: ``$($CloudApkVerification.embedded_api_url_found)``",
  "- Embedded API URL match count: ``$($CloudApkVerification.embedded_api_url_match_count)``",
  "- Flutter source stamp sidecar exists: ``$($CloudApkVerification.flutter_source_stamp_sidecar_exists)``",
  "- Flutter source stamp matches current source: ``$($CloudApkVerification.flutter_source_stamp_matches_current_source)``",
  "- Status matches Flutter source stamp: ``$($CloudApkVerification.status_matches_flutter_source_stamp)``",
  "- Error: ``$($CloudApkVerification.error)``",
  "",
  "## Quick Tunnel",
  "",
  "- Status: ``$($TunnelStatus.status)``",
  "- Provider: ``$($TunnelStatus.provider)``",
  "- URL: ``$($TunnelStatus.public_api_url)``",
  "- Health: ``$($TunnelStatus.health)``",
  "- Ready: ``$($TunnelStatus.ready)``",
  "- Fake probe: ``$($TunnelStatus.fake_probe)``",
  "- Verified: ``$($TunnelStatus.verified)``",
  "- Error: ``$($TunnelStatus.error)``",
  "",
  "## Phone Install Download",
  "",
  "- Page URL: ``$($InstallDownloadStatus.page_url)``",
  "- Download URL: ``$($InstallDownloadStatus.download_url)``",
  "- Page status: ``$($InstallDownloadStatus.page_status)``",
  "- Download status: ``$($InstallDownloadStatus.download_status)``",
  "- Download content length: ``$($InstallDownloadStatus.download_content_length)``",
  "- Expected APK size bytes: ``$($InstallDownloadStatus.expected_apk_size_bytes)``",
  "- Verified: ``$($InstallDownloadStatus.ok)``",
  "- Error: ``$($InstallDownloadStatus.error)``",
  "",
  "## Artifacts",
  "",
  "- Internet APK: ``$($Artifacts.internet_apk.path)`` exists=``$($Artifacts.internet_apk.exists)``",
  "- LAN APK: ``$($Artifacts.lan_apk.path)`` exists=``$($Artifacts.lan_apk.exists)``",
  "- Cloud APK: ``$($Artifacts.cloud_apk.path)`` exists=``$($Artifacts.cloud_apk.exists)``",
  "- Render bundle: ``$($Artifacts.render_bundle.path)`` exists=``$($Artifacts.render_bundle.exists)``",
  "- Desktop zip: ``$($Artifacts.desktop_zip.path)`` exists=``$($Artifacts.desktop_zip.exists)``",
  "- Report PDF: ``$($Artifacts.report_pdf.path)`` exists=``$($Artifacts.report_pdf.exists)``",
  "- APK verification: ``$($Artifacts.apk_verification.path)`` exists=``$($Artifacts.apk_verification.exists)``",
  "- APK verification JSON: ``$($Artifacts.apk_verification_json.path)`` exists=``$($Artifacts.apk_verification_json.exists)``",
  "- LAN APK verification: ``$($Artifacts.lan_apk_verification.path)`` exists=``$($Artifacts.lan_apk_verification.exists)``",
  "- Cloud APK verification: ``$($Artifacts.cloud_apk_verification.path)`` exists=``$($Artifacts.cloud_apk_verification.exists)``",
  "- Phone device smoke: ``$($Artifacts.phone_device_smoke.path)`` exists=``$($Artifacts.phone_device_smoke.exists)``",
  "- Phone emulator smoke: ``$($Artifacts.phone_emulator_smoke.path)`` exists=``$($Artifacts.phone_emulator_smoke.exists)``",
  "- Install page: ``$($Artifacts.install_page.path)`` exists=``$($Artifacts.install_page.exists)``"
)

if ($Missing.Count -gt 0) {
  $Lines += @("", "## Missing For Required Scope", "")
  foreach ($Item in $Missing) {
    $Lines += "- $Item"
  }
}

$Lines | Set-Content -Path $MarkdownOut -Encoding UTF8
Write-Host "Phone readiness JSON: $JsonOut" -ForegroundColor Green
Write-Host "Phone readiness report: $MarkdownOut" -ForegroundColor Green

if ($Missing.Count -gt 0) {
  Write-Host "Missing: $($Missing -join ', ')" -ForegroundColor Yellow
  if ($RequireCloud) {
    exit 1
  }
}
