[CmdletBinding()]
param(
  [string]$OutJson = "reports\goal_completion_audit_latest.json",
  [string]$OutMarkdown = "reports\goal_completion_audit_latest.md"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "path_safety.ps1")
. (Join-Path $PSScriptRoot "cloud_url_policy.ps1")

function Resolve-ProjectPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  if ([System.IO.Path]::IsPathRooted($Path)) {
    return [System.IO.Path]::GetFullPath($Path)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Path))
}

function Read-JsonFile {
  param([Parameter(Mandatory = $true)][string]$Path)
  $Resolved = Resolve-ProjectPath $Path
  if (-not (Test-Path -LiteralPath $Resolved)) {
    return $null
  }
  try {
    return Get-Content -LiteralPath $Resolved -Raw | ConvertFrom-Json
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

function Test-FileTextContains {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Needle
  )
  $Resolved = Resolve-ProjectPath $Path
  if (-not (Test-Path -LiteralPath $Resolved)) {
    return $false
  }
  $Text = Get-Content -LiteralPath $Resolved -Raw
  return $Text.Contains($Needle)
}

function Get-StepPassed {
  param(
    $ReleaseGate,
    [Parameter(Mandatory = $true)][string]$Label
  )
  if (-not $ReleaseGate -or -not $ReleaseGate.steps) {
    return $false
  }
  foreach ($Step in @($ReleaseGate.steps)) {
    if ([string]$Step.label -eq $Label -and [string]$Step.status -eq "passed") {
      return $true
    }
  }
  return $false
}

function New-Requirement {
  param(
    [Parameter(Mandatory = $true)][string]$Id,
    [Parameter(Mandatory = $true)][string]$Title,
    [Parameter(Mandatory = $true)][bool]$Ok,
    [string[]]$Evidence = @(),
    [string[]]$Gaps = @()
  )
  return [ordered]@{
    id = $Id
    title = $Title
    ok = $Ok
    evidence = @($Evidence | Where-Object { $_ })
    gaps = @($Gaps | Where-Object { $_ })
  }
}

function New-Gaps {
  param(
    [Parameter(Mandatory = $true)][bool]$Ok,
    [Parameter(Mandatory = $true)][string]$Message
  )
  if ($Ok) {
    return @()
  }
  return @($Message)
}

$OutJsonPath = Assert-PathInsideDirectory `
  -Path (Resolve-ProjectPath $OutJson) `
  -Root $ProjectRoot `
  -Message "OutJson must stay inside project: {0}"
$OutMarkdownPath = Assert-PathInsideDirectory `
  -Path (Resolve-ProjectPath $OutMarkdown) `
  -Root $ProjectRoot `
  -Message "OutMarkdown must stay inside project: {0}"

$Product = Read-JsonFile "reports\product_acceptance_latest.json"
$ReleaseGate = Read-JsonFile "reports\release_gate_latest.json"
$PhoneReadiness = Read-JsonFile "outputs\phone_download\phone_readiness.json"
$SubmissionVerification = Read-JsonFile "outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json"
$CloudStatus = Read-JsonFile "outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json"
$DesktopPackage = Read-JsonFile "outputs\desktop_package\DESKTOP_PACKAGE_VERIFICATION.json"
$DeviceSmoke = Read-JsonFile "outputs\phone_download\PHONE_DEVICE_SMOKE.json"
$CloudApkVerification = Read-JsonFile "outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json"

$ProductSummary = if ($Product -and $Product.summary) { $Product.summary } else { $Product }
$AcceptanceSections = [ordered]@{}
$AcceptanceOk = $false
if ($ProductSummary -and $ProductSummary.sections) {
  $AcceptanceOk = (
    [bool]$ProductSummary.gate_passed -and
    [double]$ProductSummary.pass_rate -ge 0.95 -and
    [int]$ProductSummary.passed -eq [int]$ProductSummary.total
  )
  foreach ($Section in $ProductSummary.sections.PSObject.Properties) {
    $Minimum = [int]$ProductSummary.min_cases_per_section
    if ($ProductSummary.min_cases_by_section -and $ProductSummary.min_cases_by_section.PSObject.Properties.Name -contains $Section.Name) {
      $Minimum = [int]$ProductSummary.min_cases_by_section.$($Section.Name)
    }
    $SectionOk = ([double]$Section.Value.pass_rate -ge 0.95 -and [int]$Section.Value.total -ge $Minimum)
    $AcceptanceSections[$Section.Name] = [ordered]@{
      total = [int]$Section.Value.total
      passed = [int]$Section.Value.passed
      pass_rate = [double]$Section.Value.pass_rate
      minimum_cases = $Minimum
      ok = $SectionOk
    }
    if (-not $SectionOk) {
      $AcceptanceOk = $false
    }
  }
}

$CanonicalEngineOk = (
  (Test-Path -LiteralPath (Resolve-ProjectPath "src\factcheck\service.py")) -and
  (Test-Path -LiteralPath (Resolve-ProjectPath "src\api_factcheck.py")) -and
  (Test-Path -LiteralPath (Resolve-ProjectPath "src\predict_factcheck.py")) -and
  (Test-FileTextContains "src\api.py" "api_factcheck") -and
  (Test-FileTextContains "src\predict.py" "run_factcheck")
)
$LegacyArchivedOk = (
  (Test-Path -LiteralPath (Resolve-ProjectPath "archive\legacy_multimodal")) -and
  (Test-Path -LiteralPath (Resolve-ProjectPath "archive\legacy_factcheck_v1")) -and
  (Test-Path -LiteralPath (Resolve-ProjectPath "docs\legacy_ml_inventory.md"))
)
$CleanSourceOk = (
  $SubmissionVerification -and
  $SubmissionVerification.source_zip -and
  [int]$SubmissionVerification.source_zip.forbidden_count -eq 0
)
$RefactorOk = ($CanonicalEngineOk -and $LegacyArchivedOk -and $CleanSourceOk)

$ReportOk = (
  (Test-Path -LiteralPath (Resolve-ProjectPath "docs\report\verity_lens_report.tex")) -and
  (Test-Path -LiteralPath (Resolve-ProjectPath "docs\report\verity_lens_report.pdf")) -and
  (Get-StepPassed $ReleaseGate "University report PDF")
)

$PcOk = (
  $ReleaseGate -and [bool]$ReleaseGate.ok -and
  $DesktopPackage -and [bool]$DesktopPackage.ok -and
  (Test-Path -LiteralPath (Resolve-ProjectPath "dist\FakeNewsDetector-Windows-Portable.zip"))
)

$PhoneReady = if ($PhoneReadiness -and $PhoneReadiness.ready) { $PhoneReadiness.ready } else { $null }
$PhoneLocalOk = (
  $PhoneReady -and
  [bool]$PhoneReady.phone_same_wifi -and
  [bool]$PhoneReady.phone_install_download -and
  [bool]$PhoneReady.phone_emulator_smoke
)
$CloudApkReleaseModeOk = (
  $CloudApkVerification -and
  $CloudApkVerification.apk -and
  [string]$CloudApkVerification.apk.expected_mode -eq "release"
)
$CloudApkVerificationOk = if ($CloudApkVerification) { [bool]$CloudApkVerification.ok } else { $false }
$CloudApkApiOk = if ($CloudApkVerification -and $CloudApkVerification.api) { [bool]$CloudApkVerification.api.ok } else { $false }
$CloudApkApiBaseUrl = if ($CloudApkVerification -and $CloudApkVerification.api -and $CloudApkVerification.api.base_url) {
  ([string]$CloudApkVerification.api.base_url).Trim().TrimEnd("/")
} else {
  ""
}
$CloudApkApiPermanentUrl = $false
if ($CloudApkApiBaseUrl) {
  try {
    $CloudApkApiPermanentUrl = ((Assert-PermanentCloudApiUrl -Value $CloudApkApiBaseUrl -Purpose "Goal audit cloud APK API") -eq $CloudApkApiBaseUrl)
  } catch {
    $CloudApkApiPermanentUrl = $false
  }
}
$CloudApkApiNotTemporary = (
  $CloudApkVerification -and
  $CloudApkVerification.api -and
  $CloudApkVerification.api.PSObject.Properties.Name -contains "is_temporary_tunnel" -and
  -not [bool]$CloudApkVerification.api.is_temporary_tunnel
)
$CloudApkEmbeddedUrlOk = if ($CloudApkVerification -and $CloudApkVerification.embedded_api_url) { [bool]$CloudApkVerification.embedded_api_url.found } else { $false }
$CloudApkEmbeddedExpectedUrl = if ($CloudApkVerification -and $CloudApkVerification.embedded_api_url -and $CloudApkVerification.embedded_api_url.expected_url) {
  ([string]$CloudApkVerification.embedded_api_url.expected_url).Trim().TrimEnd("/")
} else {
  ""
}
$CloudApkEmbeddedMatchesApiUrl = (
  $CloudApkEmbeddedExpectedUrl -and
  $CloudApkApiBaseUrl -and
  $CloudApkEmbeddedExpectedUrl -eq $CloudApkApiBaseUrl
)
$CloudApkStatusMatchesUrl = if ($CloudApkVerification -and $CloudApkVerification.status_file) { [bool]$CloudApkVerification.status_file.matches_url } else { $false }
$CloudApkStatusMatchesMode = if ($CloudApkVerification -and $CloudApkVerification.status_file) { [bool]$CloudApkVerification.status_file.matches_mode } else { $false }
$CloudApkSourceFresh = (
  $CloudApkVerification -and
  $CloudApkVerification.flutter_source_stamp -and
  [bool]$CloudApkVerification.flutter_source_stamp.sidecar_exists -and
  [bool]$CloudApkVerification.flutter_source_stamp.matches_current_source -and
  $CloudApkVerification.status_file -and
  $CloudApkStatusMatchesUrl -and
  $CloudApkStatusMatchesMode -and
  [bool]$CloudApkVerification.status_file.matches_flutter_source_stamp
)
$CloudStatusOutcomeReady = if ($CloudStatus) { [string]$CloudStatus.outcome -eq "permanent_cloud_phone_ready" } else { $false }
$CloudStatusVerificationOk = if ($CloudStatus) { [bool]$CloudStatus.verification_ok } else { $false }
$CloudStatusReadinessOk = if ($CloudStatus) { [bool]$CloudStatus.readiness_ok } else { $false }
$CloudStatusReadyToPublish = if ($CloudStatus -and $CloudStatus.cloud_apk_verification_status) {
  [bool]$CloudStatus.cloud_apk_verification_status.ready_to_publish
} else {
  $false
}
$PhonePermanentCloudOk = (
  $PhoneReady -and
  [bool]$PhoneReady.phone_permanent_cloud -and
  $CloudApkVerificationOk -and
  $CloudApkReleaseModeOk -and
  $CloudApkApiOk -and
  $CloudApkApiPermanentUrl -and
  $CloudApkApiNotTemporary -and
  $CloudApkEmbeddedUrlOk -and
  $CloudApkEmbeddedMatchesApiUrl -and
  $CloudApkSourceFresh -and
  $CloudStatusOutcomeReady -and
  $CloudStatusVerificationOk -and
  $CloudStatusReadinessOk -and
  $CloudStatusReadyToPublish
)
$DeviceScreenshotPath = Resolve-ProjectPath "outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png"
$DeviceSmokeRequiresPhysical = (
  $DeviceSmoke -and
  $DeviceSmoke.PSObject.Properties.Name -contains "require_physical_device" -and
  [bool]$DeviceSmoke.require_physical_device
)
$DeviceSmokeHasSelectedDevice = (
  $DeviceSmoke -and
  $DeviceSmoke.PSObject.Properties.Name -contains "selected_device_id" -and
  ([string]$DeviceSmoke.selected_device_id).Trim()
)
$DeviceSmokeUsesPhysical = (
  $DeviceSmokeHasSelectedDevice -and
  $DeviceSmoke.PSObject.Properties.Name -contains "selected_device_is_emulator" -and
  -not [bool]$DeviceSmoke.selected_device_is_emulator
)
$DeviceSmokeIdentityRecorded = (
  $DeviceSmoke -and
  $DeviceSmoke.device_identity -and
  [bool]$DeviceSmoke.device_identity.recorded -and
  (([string]$DeviceSmoke.device_identity.manufacturer).Trim().Length -gt 0) -and
  (([string]$DeviceSmoke.device_identity.model).Trim().Length -gt 0) -and
  (([string]$DeviceSmoke.device_identity.android_version).Trim().Length -gt 0) -and
  (([string]$DeviceSmoke.device_identity.sdk).Trim().Length -gt 0) -and
  (([string]$DeviceSmoke.device_identity.hardware).Trim().Length -gt 0)
)
$DeviceScreenshotCaptured = (
  $DeviceSmoke -and
  $DeviceSmoke.screenshot -and
  [bool]$DeviceSmoke.screenshot.captured -and
  (Test-Path -LiteralPath $DeviceScreenshotPath)
)
$DeviceScreenshotSha = if ($DeviceSmoke -and $DeviceSmoke.screenshot -and $DeviceSmoke.screenshot.sha256) {
  ([string]$DeviceSmoke.screenshot.sha256).Trim().ToUpperInvariant()
} else {
  ""
}
$DeviceScreenshotFileSha = if (Test-Path -LiteralPath $DeviceScreenshotPath) {
  (Get-FileHash -LiteralPath $DeviceScreenshotPath -Algorithm SHA256).Hash.ToUpperInvariant()
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
$PhoneDeviceOk = (
  $PhoneReady -and [bool]$PhoneReady.phone_device_smoke -and
  $DeviceSmoke -and [bool]$DeviceSmoke.ok -and
  $DeviceSmokeRequiresPhysical -and
  $DeviceSmokeUsesPhysical -and
  $DeviceSmokeIdentityRecorded -and
  $DeviceScreenshotCaptured -and
  $DeviceScreenshotShaMatches -and
  $DeviceScreenshotValidPng
)

$SubmissionOk = (
  $SubmissionVerification -and
  [bool]$SubmissionVerification.ok -and
  $SubmissionVerification.source_zip -and
  [int]$SubmissionVerification.source_zip.forbidden_count -eq 0
)

$Requirements = @(
  (New-Requirement `
    -Id "refactor" `
    -Title "Canonical refactor and legacy isolation" `
    -Ok $RefactorOk `
    -Evidence @(
      "Canonical engine: src/factcheck/service.py",
      "API/UI/mobile use canonical fact-check paths",
      "Legacy prototypes live under archive/",
      "Source ZIP forbidden generated/local paths: $(if ($SubmissionVerification) { $SubmissionVerification.source_zip.forbidden_count } else { 'unknown' })"
    ) `
    -Gaps (New-Gaps -Ok $RefactorOk -Message "Inspect canonical shims, archived legacy paths, or source ZIP cleanliness."))
  (New-Requirement `
    -Id "section_accuracy" `
    -Title "Per-section product acceptance at or above 95 percent" `
    -Ok $AcceptanceOk `
    -Evidence @(
      "Product acceptance: $(if ($ProductSummary) { "$($ProductSummary.passed)/$($ProductSummary.total), pass_rate=$($ProductSummary.pass_rate)" } else { 'missing' })",
      "Sections: $([string]::Join(', ', @($AcceptanceSections.Keys)))"
    ) `
    -Gaps (New-Gaps -Ok $AcceptanceOk -Message "Run scripts/run_product_acceptance.py and fix any section below 95 percent or below its minimum case count."))
  (New-Requirement `
    -Id "university_report" `
    -Title "University report in LaTeX and PDF" `
    -Ok $ReportOk `
    -Evidence @(
      "LaTeX: docs/report/verity_lens_report.tex",
      "PDF: docs/report/verity_lens_report.pdf",
      "Release gate University report PDF step passed: $(Get-StepPassed $ReleaseGate 'University report PDF')"
    ) `
    -Gaps (New-Gaps -Ok $ReportOk -Message "Build the LaTeX report with scripts/build_report.ps1 and rerun the release gate."))
  (New-Requirement `
    -Id "pc_product" `
    -Title "Working PC product package" `
    -Ok $PcOk `
    -Evidence @(
      "Release gate OK: $(if ($ReleaseGate) { [bool]$ReleaseGate.ok } else { $false })",
      "Desktop package OK: $(if ($DesktopPackage) { [bool]$DesktopPackage.ok } else { $false })",
      "Desktop ZIP: dist/FakeNewsDetector-Windows-Portable.zip"
    ) `
    -Gaps (New-Gaps -Ok $PcOk -Message "Rerun scripts/run_release_gate.ps1 and inspect desktop package verification."))
  (New-Requirement `
    -Id "phone_local_product" `
    -Title "Working phone product for local/LAN and emulator proof" `
    -Ok $PhoneLocalOk `
    -Evidence @(
      "Phone same Wi-Fi: $(if ($PhoneReady) { [bool]$PhoneReady.phone_same_wifi } else { $false })",
      "Phone install/download: $(if ($PhoneReady) { [bool]$PhoneReady.phone_install_download } else { $false })",
      "Phone emulator smoke: $(if ($PhoneReady) { [bool]$PhoneReady.phone_emulator_smoke } else { $false })"
    ) `
    -Gaps (New-Gaps -Ok $PhoneLocalOk -Message "Refresh phone APKs/install page and rerun emulator smoke."))
  (New-Requirement `
    -Id "phone_permanent_cloud" `
    -Title "Permanent HTTPS cloud APK for phones" `
    -Ok $PhonePermanentCloudOk `
    -Evidence @(
      "Permanent cloud phone readiness: $(if ($PhoneReady) { [bool]$PhoneReady.phone_permanent_cloud } else { $false })",
      "Cloud APK verification OK: $CloudApkVerificationOk",
      "Cloud APK release mode: $([bool]$CloudApkReleaseModeOk)",
      "Cloud APK API OK: $CloudApkApiOk",
      "Cloud APK API permanent URL: $CloudApkApiPermanentUrl",
      "Cloud APK API temporary tunnel: $(-not $CloudApkApiNotTemporary)",
      "Cloud APK embedded API URL: $CloudApkEmbeddedUrlOk",
      "Cloud APK embedded URL matches API: $CloudApkEmbeddedMatchesApiUrl",
      "Cloud APK status file matches URL: $CloudApkStatusMatchesUrl",
      "Cloud APK status file matches mode: $CloudApkStatusMatchesMode",
      "Cloud APK source current: $CloudApkSourceFresh",
      "Cloud deployment outcome: $(if ($CloudStatus) { $CloudStatus.outcome } else { 'missing' })",
      "Cloud deployment verification OK: $CloudStatusVerificationOk",
      "Cloud deployment readiness OK: $CloudStatusReadinessOk",
      "Cloud deployment ready to publish: $CloudStatusReadyToPublish"
    ) `
    -Gaps (New-Gaps -Ok $PhonePermanentCloudOk -Message "Deploy the Render HTTPS backend, then run scripts/finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com."))
  (New-Requirement `
    -Id "physical_phone_proof" `
    -Title "Physical Android device smoke proof" `
    -Ok $PhoneDeviceOk `
    -Evidence @(
      "Real Android device smoke: $(if ($PhoneReady) { [bool]$PhoneReady.phone_device_smoke } else { $false })",
      "Device smoke requires physical device: $DeviceSmokeRequiresPhysical",
      "Selected device id: $(if ($DeviceSmokeHasSelectedDevice) { $DeviceSmoke.selected_device_id } else { 'missing' })",
      "Selected device is physical: $DeviceSmokeUsesPhysical",
      "Device identity recorded: $DeviceSmokeIdentityRecorded",
      "PHONE_DEVICE_SCREENSHOT.png exists: $(Test-Path -LiteralPath $DeviceScreenshotPath)",
      "Screenshot SHA256 recorded: $([bool]$DeviceScreenshotSha)",
      "Screenshot SHA256 matches file: $DeviceScreenshotShaMatches",
      "Screenshot valid PNG with dimensions: $DeviceScreenshotValidPng"
    ) `
    -Gaps (New-Gaps -Ok $PhoneDeviceOk -Message "Connect an authorized physical Android phone by USB and run scripts/finalize_cloud_phone_submission.ps1; it invokes the release gate with -RequirePhoneDevice -RequirePhysicalPhoneDevice."))
  (New-Requirement `
    -Id "submission_package" `
    -Title "Submission bundle and verifier" `
    -Ok $SubmissionOk `
    -Evidence @(
      "Submission verifier OK: $(if ($SubmissionVerification) { [bool]$SubmissionVerification.ok } else { $false })",
      "Submission ZIP entries: $(if ($SubmissionVerification) { $SubmissionVerification.zip.entry_count } else { 'missing' })",
      "Source ZIP forbidden count: $(if ($SubmissionVerification) { $SubmissionVerification.source_zip.forbidden_count } else { 'missing' })"
    ) `
    -Gaps (New-Gaps -Ok $SubmissionOk -Message "Run scripts/make_submission_bundle.ps1 and inspect outputs/submission/SUBMISSION_BUNDLE_VERIFICATION.md."))
)

$Weights = @{
  refactor = 17
  section_accuracy = 25
  university_report = 12
  pc_product = 12
  phone_local_product = 14
  submission_package = 12
  phone_permanent_cloud = 5
  physical_phone_proof = 3
}
$EstimatedCompletion = 0
foreach ($Requirement in $Requirements) {
  if ([bool]$Requirement.ok -and $Weights.ContainsKey([string]$Requirement.id)) {
    $EstimatedCompletion += [int]$Weights[[string]$Requirement.id]
  }
}
$OverallComplete = (@($Requirements | Where-Object { -not [bool]$_.ok }).Count -eq 0)
$Remaining = @($Requirements | Where-Object { -not [bool]$_.ok } | ForEach-Object { $_.id })

$Report = [ordered]@{
  generated_at = (Get-Date).ToString("o")
  complete = $OverallComplete
  estimated_completion_percent = $EstimatedCompletion
  estimated_remaining_percent = (100 - $EstimatedCompletion)
  estimate_note = "Weighted project estimate; final completion still requires every requirement to be true."
  requirements = $Requirements
  acceptance_sections = $AcceptanceSections
  current_external_gaps = $Remaining
  artifacts = [ordered]@{
    release_gate = Get-FileStatus "reports\release_gate_latest.json"
    product_acceptance = Get-FileStatus "reports\product_acceptance_latest.json"
    submission_verification = Get-FileStatus "outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json"
    submission_zip = Get-FileStatus "outputs\submission\VerityLens-submission.zip"
    report_pdf = Get-FileStatus "docs\report\verity_lens_report.pdf"
    desktop_zip = Get-FileStatus "dist\FakeNewsDetector-Windows-Portable.zip"
    cloud_apk = Get-FileStatus "outputs\phone_download\VerityLens-cloud.apk"
    device_screenshot = Get-FileStatus "outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png"
  }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutJsonPath), (Split-Path -Parent $OutMarkdownPath) | Out-Null
$Report | ConvertTo-Json -Depth 10 | Set-Content -Path $OutJsonPath -Encoding UTF8

$Lines = @(
  "# Verity Lens Goal Completion Audit",
  "",
  "- Generated: ``$($Report.generated_at)``",
  "- Complete: ``$($Report.complete)``",
  "- Estimated completion: ``$($Report.estimated_completion_percent)%``",
  "- Estimated remaining: ``$($Report.estimated_remaining_percent)%``",
  "- Note: $($Report.estimate_note)",
  "",
  "## Requirements",
  ""
)
foreach ($Requirement in $Requirements) {
  $Lines += "- ``$($Requirement.ok)`` $($Requirement.title) (``$($Requirement.id)``)"
  foreach ($Evidence in @($Requirement.evidence)) {
    $Lines += "  - Evidence: $Evidence"
  }
  foreach ($Gap in @($Requirement.gaps | Where-Object { $_ })) {
    $Lines += "  - Gap: $Gap"
  }
}

$Lines += @("", "## Acceptance Sections", "")
foreach ($SectionName in $AcceptanceSections.Keys) {
  $Section = $AcceptanceSections[$SectionName]
  $Lines += "- ${SectionName}: ``$($Section.passed)/$($Section.total)`` pass_rate=``$($Section.pass_rate)`` minimum=``$($Section.minimum_cases)`` ok=``$($Section.ok)``"
}

$Lines += @("", "## Current External Gaps", "")
if ($Remaining.Count -eq 0) {
  $Lines += "- None"
} else {
  foreach ($Item in $Remaining) {
    $Lines += "- $Item"
  }
}

$Lines | Set-Content -Path $OutMarkdownPath -Encoding UTF8

Write-Host "Goal completion audit JSON: $OutJsonPath" -ForegroundColor Green
Write-Host "Goal completion audit report: $OutMarkdownPath" -ForegroundColor Green

if (-not $OverallComplete) {
  Write-Host "Goal is not complete. Remaining: $($Remaining -join ', ')" -ForegroundColor Yellow
}
