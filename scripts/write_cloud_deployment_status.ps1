[CmdletBinding()]
param(
  [string]$ApiBaseUrl = "",

  [ValidateSet("", "awaiting_public_https_backend", "permanent_cloud_api_verified", "permanent_cloud_phone_ready", "failed")]
  [string]$Outcome = "",

  [string]$OutputName = "VerityLens-cloud.apk",
  [bool]$VerificationOk = $false,
  [bool]$ReadinessOk = $false,
  [string]$ErrorMessage = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "path_safety.ps1")
$OutputName = Assert-ApkOutputName -Name $OutputName
$CloudDir = Join-Path $ProjectRoot "outputs\cloud_deploy"
$PhoneDir = Join-Path $ProjectRoot "outputs\phone_download"
$StatusJson = Join-Path $CloudDir "CLOUD_DEPLOYMENT_STATUS.json"
$StatusMarkdown = Join-Path $CloudDir "CLOUD_DEPLOYMENT_STATUS.md"
$BundlePath = Join-Path $CloudDir "verity-lens-render-backend.zip"
$BundleSmokeJson = Join-Path $CloudDir "render_backend_smoke\RENDER_BUNDLE_SMOKE.json"
$BundleSmokeMarkdown = Join-Path $CloudDir "render_backend_smoke\RENDER_BUNDLE_SMOKE.md"
$CloudApkPath = Join-Path $PhoneDir $OutputName
$VerificationMarkdown = Join-Path $PhoneDir "PHONE_CLOUD_APK_VERIFICATION.md"
$VerificationJson = Join-Path $PhoneDir "PHONE_CLOUD_APK_VERIFICATION.json"
$CloudApkBaseName = [System.IO.Path]::GetFileNameWithoutExtension($OutputName)
$CloudSourceStampPath = Join-Path $PhoneDir "$CloudApkBaseName-flutter-source-stamp.json"

. (Join-Path $PSScriptRoot "cloud_url_policy.ps1")

function Normalize-ApiUrl {
  param([string]$Value)
  if (-not $Value.Trim()) {
    return ""
  }
  return Assert-PermanentCloudApiUrl -Value $Value -Purpose "Permanent cloud deploy API"
}

function File-Status {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    return [ordered]@{ exists = $false; path = $Path; size_bytes = 0; sha256 = "" }
  }
  $Item = Get-Item -LiteralPath $Path
  $Hash = Get-FileHash -LiteralPath $Item.FullName -Algorithm SHA256
  return [ordered]@{
    exists = $true
    path = $Item.FullName
    size_bytes = $Item.Length
    sha256 = $Hash.Hash
  }
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

function Read-SmokeOk {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    return $false
  }
  try {
    $Smoke = Get-Content $Path -Raw | ConvertFrom-Json
    return [bool]$Smoke.ok
  } catch {
    return $false
  }
}

function Read-SmokeFreshVenvOk {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    return $false
  }
  try {
    $Smoke = Get-Content $Path -Raw | ConvertFrom-Json
    return ([bool]$Smoke.fresh_venv.requested -and [bool]$Smoke.fresh_venv.install_ok)
  } catch {
    return $false
  }
}

function Read-CloudApkSourceStampStatus {
  param([Parameter(Mandatory = $true)][string]$Path)

  $Status = [ordered]@{
    verification_json_exists = $false
    sidecar_exists = $false
    current_sha256 = ""
    build_sha256 = ""
    current_file_count = 0
    build_file_count = 0
    matches_current_source = $false
    status_file_matches_flutter_source_stamp = $false
    error = ""
  }

  $Verification = Read-JsonFile $Path
  if (-not $Verification) {
    if (Test-Path $Path) {
      $Status.error = "Cloud APK verification JSON could not be parsed."
    } else {
      $Status.error = "Cloud APK verification JSON not found."
    }
    return $Status
  }

  $Status.verification_json_exists = $true
  if ($Verification.flutter_source_stamp) {
    $Stamp = $Verification.flutter_source_stamp
    $Status.sidecar_exists = [bool]$Stamp.sidecar_exists
    $Status.current_sha256 = if ($Stamp.current_sha256) { [string]$Stamp.current_sha256 } else { "" }
    $Status.build_sha256 = if ($Stamp.build_sha256) { [string]$Stamp.build_sha256 } else { "" }
    if ($Stamp.current_file_count -ne $null) {
      $Status.current_file_count = [int]$Stamp.current_file_count
    }
    if ($Stamp.build_file_count -ne $null) {
      $Status.build_file_count = [int]$Stamp.build_file_count
    }
    $Status.matches_current_source = [bool]$Stamp.matches_current_source
  }
  if ($Verification.status_file) {
    $Status.status_file_matches_flutter_source_stamp = [bool]$Verification.status_file.matches_flutter_source_stamp
  }
  return $Status
}

function Read-CloudApkVerificationStatus {
  param([Parameter(Mandatory = $true)][string]$Path)

  $Status = [ordered]@{
    verification_json_exists = $false
    verification_json_ok = $false
    api_ok = $false
    api_base_url = ""
    api_permanent_cloud_url = $false
    api_is_temporary_tunnel = $false
    api_matches_requested_url = $false
    expected_mode = ""
    release_mode = $false
    embedded_api_url_found = $false
    embedded_api_expected_url = ""
    embedded_api_matches_base_url = $false
    flutter_source_stamp_sidecar_exists = $false
    flutter_source_stamp_matches_current_source = $false
    status_file_matches_url = $false
    status_file_matches_mode = $false
    status_file_matches_flutter_source_stamp = $false
    ready_to_publish = $false
    error = ""
  }

  $Verification = Read-JsonFile $Path
  if (-not $Verification) {
    if (Test-Path $Path) {
      $Status.error = "Cloud APK verification JSON could not be parsed."
    } else {
      $Status.error = "Cloud APK verification JSON not found."
    }
    return $Status
  }

  $Status.verification_json_exists = $true
  $Status.verification_json_ok = [bool]$Verification.ok
  if ($Verification.api) {
    $Status.api_ok = [bool]$Verification.api.ok
    if ($Verification.api.base_url) {
      $Status.api_base_url = ([string]$Verification.api.base_url).Trim().TrimEnd("/")
      $Status.api_matches_requested_url = ([bool]$ApiBaseUrl -and $Status.api_base_url -eq $ApiBaseUrl)
      try {
        $Status.api_permanent_cloud_url = ((Assert-PermanentCloudApiUrl -Value $Status.api_base_url -Purpose "Cloud deployment status APK API") -eq $Status.api_base_url)
      } catch {
        $Status.api_permanent_cloud_url = $false
      }
    }
    if ($Verification.api.PSObject.Properties.Name -contains "is_temporary_tunnel") {
      $Status.api_is_temporary_tunnel = [bool]$Verification.api.is_temporary_tunnel
    }
  }
  if ($Verification.apk -and $Verification.apk.expected_mode) {
    $Status.expected_mode = [string]$Verification.apk.expected_mode
    $Status.release_mode = ($Status.expected_mode -eq "release")
  }
  if ($Verification.embedded_api_url) {
    $Status.embedded_api_url_found = [bool]$Verification.embedded_api_url.found
    if ($Verification.embedded_api_url.expected_url) {
      $Status.embedded_api_expected_url = ([string]$Verification.embedded_api_url.expected_url).Trim().TrimEnd("/")
      $Status.embedded_api_matches_base_url = ([bool]$Status.api_base_url -and $Status.embedded_api_expected_url -eq $Status.api_base_url)
    }
  }
  if ($Verification.flutter_source_stamp) {
    $Status.flutter_source_stamp_sidecar_exists = [bool]$Verification.flutter_source_stamp.sidecar_exists
    $Status.flutter_source_stamp_matches_current_source = [bool]$Verification.flutter_source_stamp.matches_current_source
  }
  if ($Verification.status_file) {
    $Status.status_file_matches_url = [bool]$Verification.status_file.matches_url
    $Status.status_file_matches_mode = [bool]$Verification.status_file.matches_mode
    $Status.status_file_matches_flutter_source_stamp = [bool]$Verification.status_file.matches_flutter_source_stamp
  }
  $Status.ready_to_publish = (
    $Status.verification_json_ok -and
    $Status.api_ok -and
    $Status.api_permanent_cloud_url -and
    -not $Status.api_is_temporary_tunnel -and
    $Status.api_matches_requested_url -and
    $Status.release_mode -and
    $Status.embedded_api_url_found -and
    $Status.embedded_api_matches_base_url -and
    $Status.flutter_source_stamp_sidecar_exists -and
    $Status.flutter_source_stamp_matches_current_source -and
    $Status.status_file_matches_url -and
    $Status.status_file_matches_mode -and
    $Status.status_file_matches_flutter_source_stamp
  )
  return $Status
}

$ApiBaseUrl = Normalize-ApiUrl $ApiBaseUrl
New-Item -ItemType Directory -Force -Path $CloudDir, $PhoneDir | Out-Null

if (-not $Outcome.Trim()) {
  $Outcome = if ($ReadinessOk) {
    "permanent_cloud_phone_ready"
  } elseif ($ApiBaseUrl) {
    "permanent_cloud_api_verified"
  } else {
    "awaiting_public_https_backend"
  }
}

$RequestedOutcome = $Outcome
$CloudApkSourceStampStatus = Read-CloudApkSourceStampStatus $VerificationJson
$CloudApkVerificationStatus = Read-CloudApkVerificationStatus $VerificationJson
$EffectiveVerificationOk = ([bool]$VerificationOk -and [bool]$CloudApkVerificationStatus.ready_to_publish)
$EffectiveReadinessOk = ([bool]$ReadinessOk -and [bool]$EffectiveVerificationOk)
if ($Outcome -eq "permanent_cloud_phone_ready" -and -not $EffectiveReadinessOk) {
  $Outcome = "failed"
  if (-not $ErrorMessage.Trim()) {
    $ErrorMessage = "Permanent cloud phone readiness was requested, but cloud APK verification evidence is incomplete, non-release, stale, or not API-verified."
  }
}

$Status = [ordered]@{
  generated_at = (Get-Date).ToString("o")
  requested_outcome = $RequestedOutcome
  outcome = $Outcome
  api_base_url = $ApiBaseUrl
  render_bundle = File-Status $BundlePath
  render_bundle_smoke = File-Status $BundleSmokeMarkdown
  render_bundle_smoke_ok = Read-SmokeOk $BundleSmokeJson
  render_bundle_requirements_ok = Read-SmokeFreshVenvOk $BundleSmokeJson
  cloud_apk = File-Status $CloudApkPath
  cloud_apk_verification = File-Status $VerificationMarkdown
  cloud_apk_verification_json = File-Status $VerificationJson
  cloud_apk_source_stamp = File-Status $CloudSourceStampPath
  cloud_apk_source_stamp_check = $CloudApkSourceStampStatus
  cloud_apk_verification_status = $CloudApkVerificationStatus
  verification_requested_ok = [bool]$VerificationOk
  readiness_requested_ok = [bool]$ReadinessOk
  verification_ok = $EffectiveVerificationOk
  readiness_ok = $EffectiveReadinessOk
  error = $ErrorMessage
  next_step = if ($Outcome -eq "permanent_cloud_phone_ready") {
    "Install outputs\phone_download\$OutputName on a phone and confirm the in-app API banner says API connected."
  } elseif ($ApiBaseUrl) {
    "Build and verify outputs\phone_download\$OutputName, then run phone readiness and real-device smoke."
  } else {
    "Deploy outputs\cloud_deploy\verity-lens-render-backend.zip or this repository to Render, then rerun release gate with -ApiBaseUrl https://<render-app>.onrender.com -BuildCloudApk."
  }
}
$Status | ConvertTo-Json -Depth 8 | Set-Content -Path $StatusJson -Encoding UTF8

@(
  "# Verity Lens Cloud Deployment Status",
  "",
  "- Generated: ``$($Status.generated_at)``",
  "- Requested outcome: ``$($Status.requested_outcome)``",
  "- Outcome: ``$($Status.outcome)``",
  "- API base URL: ``$($Status.api_base_url)``",
  "- Render bundle: ``$($Status.render_bundle.path)`` exists=``$($Status.render_bundle.exists)``",
  "- Render bundle SHA256: ``$($Status.render_bundle.sha256)``",
  "- Render bundle smoke: ``$($Status.render_bundle_smoke.path)`` exists=``$($Status.render_bundle_smoke.exists)``",
  "- Render bundle smoke OK: ``$($Status.render_bundle_smoke_ok)``",
  "- Render bundle requirements OK: ``$($Status.render_bundle_requirements_ok)``",
  "- Cloud APK: ``$($Status.cloud_apk.path)`` exists=``$($Status.cloud_apk.exists)``",
  "- Cloud APK SHA256: ``$($Status.cloud_apk.sha256)``",
  "- Cloud APK verification JSON: ``$($Status.cloud_apk_verification_json.path)`` exists=``$($Status.cloud_apk_verification_json.exists)``",
  "- Cloud APK source stamp: ``$($Status.cloud_apk_source_stamp.path)`` exists=``$($Status.cloud_apk_source_stamp.exists)``",
  "- Cloud APK source stamp matches current source: ``$($Status.cloud_apk_source_stamp_check.matches_current_source)``",
  "- Cloud APK status matches source stamp: ``$($Status.cloud_apk_source_stamp_check.status_file_matches_flutter_source_stamp)``",
  "- Cloud APK source stamp SHA256: ``$($Status.cloud_apk_source_stamp_check.current_sha256)``",
  "- Cloud APK verification requested OK: ``$($Status.verification_requested_ok)``",
  "- Cloud readiness requested OK: ``$($Status.readiness_requested_ok)``",
  "- Cloud APK verification JSON OK: ``$($Status.cloud_apk_verification_status.verification_json_ok)``",
  "- Cloud APK verified API URL: ``$($Status.cloud_apk_verification_status.api_base_url)``",
  "- Cloud APK API permanent URL: ``$($Status.cloud_apk_verification_status.api_permanent_cloud_url)``",
  "- Cloud APK API temporary tunnel: ``$($Status.cloud_apk_verification_status.api_is_temporary_tunnel)``",
  "- Cloud APK API matches requested URL: ``$($Status.cloud_apk_verification_status.api_matches_requested_url)``",
  "- Cloud APK expected mode: ``$($Status.cloud_apk_verification_status.expected_mode)``",
  "- Cloud APK release mode: ``$($Status.cloud_apk_verification_status.release_mode)``",
  "- Cloud APK API OK: ``$($Status.cloud_apk_verification_status.api_ok)``",
  "- Cloud APK embedded API URL found: ``$($Status.cloud_apk_verification_status.embedded_api_url_found)``",
  "- Cloud APK embedded API expected URL: ``$($Status.cloud_apk_verification_status.embedded_api_expected_url)``",
  "- Cloud APK embedded API matches verified URL: ``$($Status.cloud_apk_verification_status.embedded_api_matches_base_url)``",
  "- Cloud APK status matches URL: ``$($Status.cloud_apk_verification_status.status_file_matches_url)``",
  "- Cloud APK status matches mode: ``$($Status.cloud_apk_verification_status.status_file_matches_mode)``",
  "- Cloud APK ready to publish: ``$($Status.cloud_apk_verification_status.ready_to_publish)``",
  "- Cloud APK verification OK: ``$($Status.verification_ok)``",
  "- Cloud readiness OK: ``$($Status.readiness_ok)``",
  "- Error: ``$($Status.error)``",
  "- Next step: $($Status.next_step)"
) | Set-Content -Path $StatusMarkdown -Encoding UTF8

Write-Host "Cloud deployment status JSON: $StatusJson" -ForegroundColor Green
Write-Host "Cloud deployment status report: $StatusMarkdown" -ForegroundColor Green
