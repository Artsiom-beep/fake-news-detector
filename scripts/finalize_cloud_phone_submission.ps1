[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$ApiBaseUrl,

  [ValidateSet("debug", "release")]
  [string]$CloudApkMode = "release",

  [string]$CloudApkOutputName = "VerityLens-cloud.apk",

  [string]$PhoneDeviceId = "",

  [string]$AdbPath = "",

  [string]$OutputDir = "outputs\submission",

  [string]$OutJson = "reports\final_cloud_phone_submission_latest.json",

  [string]$OutMarkdown = "reports\final_cloud_phone_submission_latest.md"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "cloud_url_policy.ps1")
. (Join-Path $PSScriptRoot "path_safety.ps1")
$CloudApkOutputName = Assert-ApkOutputName -Name $CloudApkOutputName -Purpose "Cloud APK output name"
$PowerShell = Get-ChildPowerShellCommand

if ($CloudApkMode -ne "release") {
  throw "Final cloud phone submission requires -CloudApkMode release. Use scripts\run_release_gate.ps1 directly for debug-only local diagnostics."
}

function Resolve-ProjectPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  if ([System.IO.Path]::IsPathRooted($Path)) {
    return [System.IO.Path]::GetFullPath($Path)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Path))
}

function Read-JsonFile {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  try {
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
  } catch {
    return $null
  }
}

function Get-FileStatus {
  param([Parameter(Mandatory = $true)][string]$Path)
  $Resolved = Resolve-ProjectPath $Path
  if (-not (Test-Path -LiteralPath $Resolved)) {
    return [ordered]@{
      exists = $false
      path = $Resolved
      size_bytes = 0
      sha256 = ""
      modified_at = $null
    }
  }
  $Item = Get-Item -LiteralPath $Resolved
  $Hash = Get-FileHash -LiteralPath $Resolved -Algorithm SHA256
  return [ordered]@{
    exists = $true
    path = $Item.FullName
    size_bytes = $Item.Length
    sha256 = $Hash.Hash
    modified_at = $Item.LastWriteTime.ToString("o")
  }
}

function Get-FinalEvidence {
  $ReleaseGateJson = Resolve-ProjectPath "reports\release_gate_latest.json"
  $SubmissionVerificationJson = Join-Path $OutputRoot "SUBMISSION_BUNDLE_VERIFICATION.json"
  $PhoneReadinessJson = Resolve-ProjectPath "outputs\phone_download\phone_readiness.json"
  $DeviceSmokeJson = Resolve-ProjectPath "outputs\phone_download\PHONE_DEVICE_SMOKE.json"
  $DeviceScreenshot = Resolve-ProjectPath "outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png"
  $GoalAuditJson = Resolve-ProjectPath "reports\goal_completion_audit_latest.json"
  $CloudStatusJson = Resolve-ProjectPath "outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json"
  $CloudApkVerificationJson = Resolve-ProjectPath "outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json"

  $ReleaseGate = Read-JsonFile $ReleaseGateJson
  $SubmissionVerification = Read-JsonFile $SubmissionVerificationJson
  $Readiness = Read-JsonFile $PhoneReadinessJson
  $DeviceSmoke = Read-JsonFile $DeviceSmokeJson
  $GoalAudit = Read-JsonFile $GoalAuditJson
  $CloudStatus = Read-JsonFile $CloudStatusJson
  $CloudApkVerification = Read-JsonFile $CloudApkVerificationJson

  $DeviceScreenshotCaptured = (
    $DeviceSmoke -and
    $DeviceSmoke.screenshot -and
    [bool]$DeviceSmoke.screenshot.captured -and
    [bool](Test-Path -LiteralPath $DeviceScreenshot)
  )
  $DeviceSmokeRequiresPhysical = (
    $DeviceSmoke -and
    $DeviceSmoke.PSObject.Properties.Name -contains "require_physical_device" -and
    [bool]$DeviceSmoke.require_physical_device
  )
  $DeviceSmokeSelectedId = if (
    $DeviceSmoke -and
    $DeviceSmoke.PSObject.Properties.Name -contains "selected_device_id"
  ) {
    ([string]$DeviceSmoke.selected_device_id).Trim()
  } else {
    ""
  }
  $DeviceSmokeUsesPhysical = (
    $DeviceSmokeSelectedId -and
    $DeviceSmoke.PSObject.Properties.Name -contains "selected_device_is_emulator" -and
    -not [bool]$DeviceSmoke.selected_device_is_emulator
  )
  $DeviceScreenshotSha = if ($DeviceSmoke -and $DeviceSmoke.screenshot -and $DeviceSmoke.screenshot.sha256) {
    ([string]$DeviceSmoke.screenshot.sha256).Trim().ToUpperInvariant()
  } else {
    ""
  }
  $DeviceScreenshotFileSha = if (Test-Path -LiteralPath $DeviceScreenshot) {
    (Get-FileHash -LiteralPath $DeviceScreenshot -Algorithm SHA256).Hash.ToUpperInvariant()
  } else {
    ""
  }
  $DeviceScreenshotShaMatches = (
    $DeviceScreenshotSha -and
    $DeviceScreenshotFileSha -and
    $DeviceScreenshotSha -eq $DeviceScreenshotFileSha
  )
  $DeviceScreenshotValidPng = (
    $DeviceSmoke -and
    $DeviceSmoke.screenshot -and
    $DeviceSmoke.screenshot.PSObject.Properties.Name -contains "valid_png" -and
    [bool]$DeviceSmoke.screenshot.valid_png -and
    $DeviceSmoke.screenshot.PSObject.Properties.Name -contains "width" -and
    [int]$DeviceSmoke.screenshot.width -gt 0 -and
    $DeviceSmoke.screenshot.PSObject.Properties.Name -contains "height" -and
    [int]$DeviceSmoke.screenshot.height -gt 0
  )
  $DeviceIdentityRecorded = (
    $DeviceSmoke -and
    $DeviceSmoke.device_identity -and
    [bool]$DeviceSmoke.device_identity.recorded -and
    (([string]$DeviceSmoke.device_identity.manufacturer).Trim().Length -gt 0) -and
    (([string]$DeviceSmoke.device_identity.model).Trim().Length -gt 0) -and
    (([string]$DeviceSmoke.device_identity.android_version).Trim().Length -gt 0) -and
    (([string]$DeviceSmoke.device_identity.sdk).Trim().Length -gt 0) -and
    (([string]$DeviceSmoke.device_identity.hardware).Trim().Length -gt 0)
  )
  $CloudApkStatus = if ($CloudStatus -and $CloudStatus.cloud_apk_verification_status) {
    $CloudStatus.cloud_apk_verification_status
  } else {
    $null
  }
  $CloudApkApiNotTemporary = if (
    $CloudApkStatus -and
    $CloudApkStatus.PSObject.Properties.Name -contains "api_is_temporary_tunnel"
  ) {
    -not [bool]$CloudApkStatus.api_is_temporary_tunnel
  } else {
    $false
  }

  return [ordered]@{
    release_gate_ok = if ($ReleaseGate) { [bool]$ReleaseGate.ok } else { $false }
    submission_verification_ok = if ($SubmissionVerification) { [bool]$SubmissionVerification.ok } else { $false }
    phone_permanent_cloud = if ($Readiness) { [bool]$Readiness.ready.phone_permanent_cloud } else { $false }
    cloud_status_outcome_ready = if ($CloudStatus) { [string]$CloudStatus.outcome -eq "permanent_cloud_phone_ready" } else { $false }
    cloud_status_verification_ok = if ($CloudStatus) { [bool]$CloudStatus.verification_ok } else { $false }
    cloud_status_readiness_ok = if ($CloudStatus) { [bool]$CloudStatus.readiness_ok } else { $false }
    cloud_status_ready_to_publish = if ($CloudStatus -and $CloudStatus.cloud_apk_verification_status) { [bool]$CloudStatus.cloud_apk_verification_status.ready_to_publish } else { $false }
    cloud_apk_release_mode = if ($CloudApkVerification -and $CloudApkVerification.apk) { [string]$CloudApkVerification.apk.expected_mode -eq "release" } else { $false }
    cloud_apk_api_permanent_url = if ($CloudApkStatus) { [bool]$CloudApkStatus.api_permanent_cloud_url } else { $false }
    cloud_apk_api_not_temporary_tunnel = $CloudApkApiNotTemporary
    cloud_apk_api_matches_requested_url = if ($CloudApkStatus) { [bool]$CloudApkStatus.api_matches_requested_url } else { $false }
    cloud_apk_embedded_api_url_found = if ($CloudApkStatus) { [bool]$CloudApkStatus.embedded_api_url_found } else { $false }
    cloud_apk_embedded_api_matches_base_url = if ($CloudApkStatus) { [bool]$CloudApkStatus.embedded_api_matches_base_url } else { $false }
    cloud_apk_status_matches_url = if ($CloudApkStatus) { [bool]$CloudApkStatus.status_file_matches_url } else { $false }
    cloud_apk_status_matches_mode = if ($CloudApkStatus) { [bool]$CloudApkStatus.status_file_matches_mode } else { $false }
    cloud_apk_status_matches_flutter_source_stamp = if ($CloudApkStatus) { [bool]$CloudApkStatus.status_file_matches_flutter_source_stamp } else { $false }
    phone_device_smoke_ok = if ($DeviceSmoke) { [bool]$DeviceSmoke.ok } else { $false }
    phone_device_requires_physical = $DeviceSmokeRequiresPhysical
    phone_device_selected_id = $DeviceSmokeSelectedId
    phone_device_selected_physical = $DeviceSmokeUsesPhysical
    phone_device_identity_recorded = $DeviceIdentityRecorded
    phone_device_screenshot_captured = $DeviceScreenshotCaptured
    phone_device_screenshot_sha256_recorded = [bool]$DeviceScreenshotSha
    phone_device_screenshot_sha256_matches = $DeviceScreenshotShaMatches
    phone_device_screenshot_valid_png = $DeviceScreenshotValidPng
    goal_audit_complete = if ($GoalAudit) { [bool]$GoalAudit.complete } else { $false }
    goal_audit_remaining = if ($GoalAudit -and $GoalAudit.current_external_gaps) { @($GoalAudit.current_external_gaps) } else { @("goal_completion_audit_missing") }
  }
}

function Assert-FinalEvidenceReady {
  $Evidence = Get-FinalEvidence
  $Missing = New-Object System.Collections.Generic.List[string]
  if (-not [bool]$Evidence.release_gate_ok) { $Missing.Add("release_gate_ok") | Out-Null }
  if (-not [bool]$Evidence.submission_verification_ok) { $Missing.Add("submission_verification_ok") | Out-Null }
  if (-not [bool]$Evidence.phone_permanent_cloud) { $Missing.Add("phone_permanent_cloud") | Out-Null }
  if (-not [bool]$Evidence.cloud_status_outcome_ready) { $Missing.Add("cloud_status_outcome_ready") | Out-Null }
  if (-not [bool]$Evidence.cloud_status_verification_ok) { $Missing.Add("cloud_status_verification_ok") | Out-Null }
  if (-not [bool]$Evidence.cloud_status_readiness_ok) { $Missing.Add("cloud_status_readiness_ok") | Out-Null }
  if (-not [bool]$Evidence.cloud_status_ready_to_publish) { $Missing.Add("cloud_status_ready_to_publish") | Out-Null }
  if (-not [bool]$Evidence.cloud_apk_release_mode) { $Missing.Add("cloud_apk_release_mode") | Out-Null }
  if (-not [bool]$Evidence.cloud_apk_api_permanent_url) { $Missing.Add("cloud_apk_api_permanent_url") | Out-Null }
  if (-not [bool]$Evidence.cloud_apk_api_not_temporary_tunnel) { $Missing.Add("cloud_apk_api_not_temporary_tunnel") | Out-Null }
  if (-not [bool]$Evidence.cloud_apk_api_matches_requested_url) { $Missing.Add("cloud_apk_api_matches_requested_url") | Out-Null }
  if (-not [bool]$Evidence.cloud_apk_embedded_api_url_found) { $Missing.Add("cloud_apk_embedded_api_url_found") | Out-Null }
  if (-not [bool]$Evidence.cloud_apk_embedded_api_matches_base_url) { $Missing.Add("cloud_apk_embedded_api_matches_base_url") | Out-Null }
  if (-not [bool]$Evidence.cloud_apk_status_matches_url) { $Missing.Add("cloud_apk_status_matches_url") | Out-Null }
  if (-not [bool]$Evidence.cloud_apk_status_matches_mode) { $Missing.Add("cloud_apk_status_matches_mode") | Out-Null }
  if (-not [bool]$Evidence.cloud_apk_status_matches_flutter_source_stamp) { $Missing.Add("cloud_apk_status_matches_flutter_source_stamp") | Out-Null }
  if (-not [bool]$Evidence.phone_device_smoke_ok) { $Missing.Add("phone_device_smoke_ok") | Out-Null }
  if (-not [bool]$Evidence.phone_device_requires_physical) { $Missing.Add("phone_device_requires_physical") | Out-Null }
  if (-not ([string]$Evidence.phone_device_selected_id).Trim()) { $Missing.Add("phone_device_selected_id") | Out-Null }
  if (-not [bool]$Evidence.phone_device_selected_physical) { $Missing.Add("phone_device_selected_physical") | Out-Null }
  if (-not [bool]$Evidence.phone_device_identity_recorded) { $Missing.Add("phone_device_identity_recorded") | Out-Null }
  if (-not [bool]$Evidence.phone_device_screenshot_captured) { $Missing.Add("phone_device_screenshot_captured") | Out-Null }
  if (-not [bool]$Evidence.phone_device_screenshot_sha256_recorded) { $Missing.Add("phone_device_screenshot_sha256_recorded") | Out-Null }
  if (-not [bool]$Evidence.phone_device_screenshot_sha256_matches) { $Missing.Add("phone_device_screenshot_sha256_matches") | Out-Null }
  if (-not [bool]$Evidence.phone_device_screenshot_valid_png) { $Missing.Add("phone_device_screenshot_valid_png") | Out-Null }
  if (-not [bool]$Evidence.goal_audit_complete) {
    $GoalGaps = if ($Evidence.goal_audit_remaining -and @($Evidence.goal_audit_remaining).Count -gt 0) {
      @($Evidence.goal_audit_remaining) -join ", "
    } else {
      "unknown"
    }
    $Missing.Add("goal_audit_complete ($GoalGaps)") | Out-Null
  }
  if ($Missing.Count -gt 0) {
    throw "Final cloud phone evidence is incomplete: $($Missing -join ', ')"
  }
  return $Evidence
}

function Invoke-Step {
  param(
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][scriptblock]$Command
  )

  Write-Host ""
  Write-Host "==> $Label" -ForegroundColor Cyan
  $Step = [ordered]@{
    label = $Label
    status = "running"
    started_at = (Get-Date).ToString("o")
    ended_at = ""
    duration_seconds = 0.0
    exit_code = $null
    error = ""
  }
  $Steps.Add($Step) | Out-Null
  $Timer = [System.Diagnostics.Stopwatch]::StartNew()
  $global:LASTEXITCODE = 0
  try {
    & $Command
    $Step.exit_code = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) {
      throw "$Label failed with exit code $LASTEXITCODE"
    }
    $Step.status = "passed"
  } catch {
    $Step.status = "failed"
    if ($Step.exit_code -eq $null) {
      $Step.exit_code = $LASTEXITCODE
    }
    $Step.error = $_.Exception.Message
    throw
  } finally {
    $Timer.Stop()
    $Step.ended_at = (Get-Date).ToString("o")
    $Step.duration_seconds = [math]::Round($Timer.Elapsed.TotalSeconds, 2)
  }
}

function Write-FinalReport {
  param(
    [Parameter(Mandatory = $true)][bool]$Ok,
    [string]$ErrorMessage = ""
  )

  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutJsonPath), (Split-Path -Parent $OutMarkdownPath) | Out-Null

  $ReleaseGateJson = Resolve-ProjectPath "reports\release_gate_latest.json"
  $SubmissionVerificationJson = Join-Path $OutputRoot "SUBMISSION_BUNDLE_VERIFICATION.json"
  $SubmissionZip = Join-Path $OutputRoot "VerityLens-submission.zip"
  $CloudApk = Resolve-ProjectPath "outputs\phone_download\$CloudApkOutputName"
  $CloudApkVerificationJson = Resolve-ProjectPath "outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json"
  $CloudStatusJson = Resolve-ProjectPath "outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json"
  $PhoneReadinessJson = Resolve-ProjectPath "outputs\phone_download\phone_readiness.json"
  $DeviceSmokeJson = Resolve-ProjectPath "outputs\phone_download\PHONE_DEVICE_SMOKE.json"
  $DeviceScreenshot = Resolve-ProjectPath "outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png"

  $ReleaseGate = Read-JsonFile $ReleaseGateJson
  $SubmissionVerification = Read-JsonFile $SubmissionVerificationJson
  $Readiness = Read-JsonFile $PhoneReadinessJson
  $DeviceSmoke = Read-JsonFile $DeviceSmokeJson
  $Evidence = Get-FinalEvidence

  $DeviceScreenshotCaptured = (
    $DeviceSmoke -and
    $DeviceSmoke.screenshot -and
    [bool]$DeviceSmoke.screenshot.captured -and
    [bool](Test-Path -LiteralPath $DeviceScreenshot)
  )

  $FinalReady = (
    $Ok -and
    [bool]$Evidence.release_gate_ok -and
    [bool]$Evidence.submission_verification_ok -and
    [bool]$Evidence.phone_permanent_cloud -and
    [bool]$Evidence.cloud_status_outcome_ready -and
    [bool]$Evidence.cloud_status_verification_ok -and
    [bool]$Evidence.cloud_status_readiness_ok -and
    [bool]$Evidence.cloud_status_ready_to_publish -and
    [bool]$Evidence.cloud_apk_release_mode -and
    [bool]$Evidence.cloud_apk_api_permanent_url -and
    [bool]$Evidence.cloud_apk_api_not_temporary_tunnel -and
    [bool]$Evidence.cloud_apk_api_matches_requested_url -and
    [bool]$Evidence.cloud_apk_embedded_api_url_found -and
    [bool]$Evidence.cloud_apk_embedded_api_matches_base_url -and
    [bool]$Evidence.cloud_apk_status_matches_url -and
    [bool]$Evidence.cloud_apk_status_matches_mode -and
    [bool]$Evidence.cloud_apk_status_matches_flutter_source_stamp -and
    [bool]$Evidence.phone_device_smoke_ok -and
    [bool]$Evidence.phone_device_requires_physical -and
    ([string]$Evidence.phone_device_selected_id).Trim() -and
    [bool]$Evidence.phone_device_selected_physical -and
    [bool]$Evidence.phone_device_identity_recorded -and
    [bool]$Evidence.phone_device_screenshot_captured -and
    [bool]$Evidence.phone_device_screenshot_sha256_recorded -and
    [bool]$Evidence.phone_device_screenshot_sha256_matches -and
    [bool]$Evidence.phone_device_screenshot_valid_png -and
    [bool]$Evidence.goal_audit_complete
  )

  $Report = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    ok = $FinalReady
    error = $ErrorMessage
    api_base_url = $NormalizedApiBaseUrl
    cloud_apk_mode = $CloudApkMode
    cloud_apk_output_name = $CloudApkOutputName
    phone_device_id = $PhoneDeviceId
    adb_path = $AdbPath
    packaging_contract = [ordered]@{
      immutable_success_report = $true
      packaged_under = "final/"
      submission_zip_artifact_scope = "pre_final_report_bundle_snapshot"
      submission_verification_artifact_scope = "pre_final_report_bundle_snapshot"
      post_report_checks_required_after_snapshot = $true
      post_report_checks = @(
        "Final submission bundle with final report",
        "Final submission verifier with final report",
        "Goal completion audit refresh",
        "Final cloud phone evidence recheck"
      )
    }
    steps = @($Steps | ForEach-Object { $_ })
    evidence = [ordered]@{
      release_gate_ok = [bool]$Evidence.release_gate_ok
      submission_verification_ok = [bool]$Evidence.submission_verification_ok
      phone_permanent_cloud = [bool]$Evidence.phone_permanent_cloud
      cloud_status_outcome_ready = [bool]$Evidence.cloud_status_outcome_ready
      cloud_status_verification_ok = [bool]$Evidence.cloud_status_verification_ok
      cloud_status_readiness_ok = [bool]$Evidence.cloud_status_readiness_ok
      cloud_status_ready_to_publish = [bool]$Evidence.cloud_status_ready_to_publish
      cloud_apk_release_mode = [bool]$Evidence.cloud_apk_release_mode
      cloud_apk_api_permanent_url = [bool]$Evidence.cloud_apk_api_permanent_url
      cloud_apk_api_not_temporary_tunnel = [bool]$Evidence.cloud_apk_api_not_temporary_tunnel
      cloud_apk_api_matches_requested_url = [bool]$Evidence.cloud_apk_api_matches_requested_url
      cloud_apk_embedded_api_url_found = [bool]$Evidence.cloud_apk_embedded_api_url_found
      cloud_apk_embedded_api_matches_base_url = [bool]$Evidence.cloud_apk_embedded_api_matches_base_url
      cloud_apk_status_matches_url = [bool]$Evidence.cloud_apk_status_matches_url
      cloud_apk_status_matches_mode = [bool]$Evidence.cloud_apk_status_matches_mode
      cloud_apk_status_matches_flutter_source_stamp = [bool]$Evidence.cloud_apk_status_matches_flutter_source_stamp
      phone_device_smoke_ok = [bool]$Evidence.phone_device_smoke_ok
      phone_device_requires_physical = [bool]$Evidence.phone_device_requires_physical
      phone_device_selected_id = [string]$Evidence.phone_device_selected_id
      phone_device_selected_physical = [bool]$Evidence.phone_device_selected_physical
      phone_device_identity_recorded = [bool]$Evidence.phone_device_identity_recorded
      phone_device_screenshot_captured = [bool]$Evidence.phone_device_screenshot_captured
      phone_device_screenshot_sha256_recorded = [bool]$Evidence.phone_device_screenshot_sha256_recorded
      phone_device_screenshot_sha256_matches = [bool]$Evidence.phone_device_screenshot_sha256_matches
      phone_device_screenshot_valid_png = [bool]$Evidence.phone_device_screenshot_valid_png
      goal_audit_complete = [bool]$Evidence.goal_audit_complete
      goal_audit_remaining = @($Evidence.goal_audit_remaining)
    }
    artifacts = [ordered]@{
      release_gate_json = Get-FileStatus $ReleaseGateJson
      submission_verification_json = Get-FileStatus $SubmissionVerificationJson
      submission_zip = Get-FileStatus $SubmissionZip
      cloud_apk = Get-FileStatus $CloudApk
      cloud_apk_verification_json = Get-FileStatus $CloudApkVerificationJson
      cloud_deployment_status_json = Get-FileStatus $CloudStatusJson
      phone_readiness_json = Get-FileStatus $PhoneReadinessJson
      phone_device_smoke_json = Get-FileStatus $DeviceSmokeJson
      phone_device_screenshot = Get-FileStatus $DeviceScreenshot
    }
  }

  $Report | ConvertTo-Json -Depth 12 | Set-Content -Path $OutJsonPath -Encoding UTF8

  $Lines = @(
    "# Verity Lens Final Cloud Phone Submission",
    "",
    "- Generated: ``$($Report.generated_at)``",
    "- OK: ``$($Report.ok)``",
    "- Error: ``$($Report.error)``",
    "- API base URL: ``$($Report.api_base_url)``",
    "- Cloud APK mode: ``$($Report.cloud_apk_mode)``",
    "- Cloud APK output: ``$($Report.cloud_apk_output_name)``",
    "- Phone device id: ``$($Report.phone_device_id)``",
    "- ADB path: ``$($Report.adb_path)``",
    "- Immutable success report: ``$($Report.packaging_contract.immutable_success_report)``",
    "- Packaged under: ``$($Report.packaging_contract.packaged_under)``",
    "- Submission ZIP artifact scope: ``$($Report.packaging_contract.submission_zip_artifact_scope)``",
    "- Submission verification artifact scope: ``$($Report.packaging_contract.submission_verification_artifact_scope)``",
    "- Post-report checks required: ``$($Report.packaging_contract.post_report_checks_required_after_snapshot)``",
    "",
    "## Evidence",
    "",
    "- Release gate OK: ``$($Report.evidence.release_gate_ok)``",
    "- Submission verification OK: ``$($Report.evidence.submission_verification_ok)``",
    "- Permanent cloud phone ready: ``$($Report.evidence.phone_permanent_cloud)``",
    "- Cloud status outcome ready: ``$($Report.evidence.cloud_status_outcome_ready)``",
    "- Cloud status verification OK: ``$($Report.evidence.cloud_status_verification_ok)``",
    "- Cloud status readiness OK: ``$($Report.evidence.cloud_status_readiness_ok)``",
    "- Cloud status ready to publish: ``$($Report.evidence.cloud_status_ready_to_publish)``",
    "- Cloud APK release mode: ``$($Report.evidence.cloud_apk_release_mode)``",
    "- Cloud APK API permanent URL: ``$($Report.evidence.cloud_apk_api_permanent_url)``",
    "- Cloud APK API not temporary tunnel: ``$($Report.evidence.cloud_apk_api_not_temporary_tunnel)``",
    "- Cloud APK API matches requested URL: ``$($Report.evidence.cloud_apk_api_matches_requested_url)``",
    "- Cloud APK embedded API URL found: ``$($Report.evidence.cloud_apk_embedded_api_url_found)``",
    "- Cloud APK embedded API matches verified URL: ``$($Report.evidence.cloud_apk_embedded_api_matches_base_url)``",
    "- Cloud APK status matches URL: ``$($Report.evidence.cloud_apk_status_matches_url)``",
    "- Cloud APK status matches mode: ``$($Report.evidence.cloud_apk_status_matches_mode)``",
    "- Cloud APK status matches Flutter source stamp: ``$($Report.evidence.cloud_apk_status_matches_flutter_source_stamp)``",
    "- Phone device smoke OK: ``$($Report.evidence.phone_device_smoke_ok)``",
    "- Phone smoke required physical device: ``$($Report.evidence.phone_device_requires_physical)``",
    "- Phone selected device id: ``$($Report.evidence.phone_device_selected_id)``",
    "- Phone selected device is physical: ``$($Report.evidence.phone_device_selected_physical)``",
    "- Phone device identity recorded: ``$($Report.evidence.phone_device_identity_recorded)``",
    "- Phone screenshot captured: ``$($Report.evidence.phone_device_screenshot_captured)``",
    "- Phone screenshot SHA256 recorded: ``$($Report.evidence.phone_device_screenshot_sha256_recorded)``",
    "- Phone screenshot SHA256 matches file: ``$($Report.evidence.phone_device_screenshot_sha256_matches)``",
    "- Phone screenshot valid PNG: ``$($Report.evidence.phone_device_screenshot_valid_png)``",
    "- Goal audit complete: ``$($Report.evidence.goal_audit_complete)``",
    "- Goal audit remaining: ``$(@($Report.evidence.goal_audit_remaining) -join ', ')``",
    "",
    "## Steps",
    ""
  )
  foreach ($Step in $Report.steps) {
    $Lines += "- ``$($Step.status)`` $($Step.label) ($($Step.duration_seconds)s, exit=$($Step.exit_code))"
    if ($Step.error) {
      $Lines += "  - Error: $($Step.error)"
    }
  }
  $Lines += @(
    "",
    "## Artifacts",
    "",
    "- Submission ZIP: ``$($Report.artifacts.submission_zip.path)`` SHA256=``$($Report.artifacts.submission_zip.sha256)``",
    "- Cloud APK: ``$($Report.artifacts.cloud_apk.path)`` SHA256=``$($Report.artifacts.cloud_apk.sha256)``",
    "- Device screenshot: ``$($Report.artifacts.phone_device_screenshot.path)`` SHA256=``$($Report.artifacts.phone_device_screenshot.sha256)``"
  )
  $Lines | Set-Content -Path $OutMarkdownPath -Encoding UTF8
}

$NormalizedApiBaseUrl = Assert-PermanentCloudApiUrl -Value $ApiBaseUrl -Purpose "Final cloud phone submission API"
$OutJsonPath = Assert-PathInsideDirectory `
  -Path (Resolve-ProjectPath $OutJson) `
  -Root $ProjectRoot `
  -Message "OutJson must stay inside project: {0}"
$OutMarkdownPath = Assert-PathInsideDirectory `
  -Path (Resolve-ProjectPath $OutMarkdown) `
  -Root $ProjectRoot `
  -Message "OutMarkdown must stay inside project: {0}"

$OutputRoot = Assert-PathInsideDirectory `
  -Path (Resolve-ProjectPath $OutputDir) `
  -Root $ProjectRoot `
  -Message "OutputDir must stay inside project: {0}"
if ($OutputRoot.Equals((ConvertTo-NormalizedFullPath -Path $ProjectRoot), [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "OutputDir must be a directory inside project, not the project root: $OutputRoot"
}

$Steps = New-Object System.Collections.Generic.List[object]
$Ok = $false
$ErrorMessage = ""
$FinalReportPackaged = $false

Push-Location $ProjectRoot
try {
  Invoke-Step "Final external preflight" {
    $PreflightArgs = @(
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      (Join-Path $PSScriptRoot "check_final_external_prereqs.ps1"),
      "-ApiBaseUrl",
      $NormalizedApiBaseUrl,
      "-CloudApkOutputName",
      $CloudApkOutputName,
      "-RequireReady"
    )
    if ($PhoneDeviceId.Trim()) {
      $PreflightArgs += @("-PhoneDeviceId", $PhoneDeviceId)
    }
    if ($AdbPath.Trim()) {
      $PreflightArgs += @("-AdbPath", $AdbPath)
    }
    & $PowerShell @PreflightArgs
  }

  Invoke-Step "Strict cloud phone release gate" {
    $GateArgs = @(
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      (Join-Path $PSScriptRoot "run_release_gate.ps1"),
      "-ApiBaseUrl",
      $NormalizedApiBaseUrl,
      "-BuildCloudApk",
      "-CloudApkMode",
      $CloudApkMode,
      "-CloudApkOutputName",
      $CloudApkOutputName,
      "-PhoneDeviceApkPath",
      (Join-Path $ProjectRoot "outputs\phone_download\$CloudApkOutputName"),
      "-RequirePhoneDevice",
      "-RequirePhysicalPhoneDevice"
    )
    if ($PhoneDeviceId.Trim()) {
      $GateArgs += @("-PhoneDeviceId", $PhoneDeviceId)
    }
    if ($AdbPath.Trim()) {
      $GateArgs += @("-AdbPath", $AdbPath)
    }
    & $PowerShell @GateArgs
  }

  Invoke-Step "Submission bundle" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "make_submission_bundle.ps1") -OutputDir $OutputRoot
  }

  Invoke-Step "Submission verifier" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_submission_bundle.ps1") `
      -ZipPath (Join-Path $OutputRoot "VerityLens-submission.zip") `
      -OutJson (Join-Path $OutputRoot "SUBMISSION_BUNDLE_VERIFICATION.json") `
      -OutMarkdown (Join-Path $OutputRoot "SUBMISSION_BUNDLE_VERIFICATION.md")
  }

  Invoke-Step "Goal completion audit" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "audit_project_goal_completion.ps1")
  }

  Invoke-Step "Final cloud phone evidence check" {
    [void](Assert-FinalEvidenceReady)
  }

  Write-FinalReport -Ok $true -ErrorMessage ""

  Invoke-Step "Final submission bundle with final report" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "make_submission_bundle.ps1") -OutputDir $OutputRoot
  }

  Invoke-Step "Final submission verifier with final report" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_submission_bundle.ps1") `
      -ZipPath (Join-Path $OutputRoot "VerityLens-submission.zip") `
      -OutJson (Join-Path $OutputRoot "SUBMISSION_BUNDLE_VERIFICATION.json") `
      -OutMarkdown (Join-Path $OutputRoot "SUBMISSION_BUNDLE_VERIFICATION.md")
  }

  Invoke-Step "Goal completion audit refresh" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "audit_project_goal_completion.ps1")
  }

  Invoke-Step "Final cloud phone evidence recheck" {
    [void](Assert-FinalEvidenceReady)
  }

  $Ok = $true
  $FinalReportPackaged = $true
} catch {
  $ErrorMessage = $_.Exception.Message
  throw
} finally {
  try {
    if (-not ($Ok -and $FinalReportPackaged)) {
      Write-FinalReport -Ok $Ok -ErrorMessage $ErrorMessage
    }
  } catch {
    Write-Warning "Failed to write final cloud phone submission report: $($_.Exception.Message)"
  }
  Pop-Location
}
