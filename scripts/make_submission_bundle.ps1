[CmdletBinding()]
param(
  [string]$OutputDir = "outputs\submission",
  [switch]$SkipLargeArtifacts
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "path_safety.ps1")

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PowerShell = Get-ChildPowerShellCommand
if ([System.IO.Path]::IsPathRooted($OutputDir)) {
  $OutputRoot = [System.IO.Path]::GetFullPath($OutputDir)
} else {
  $OutputRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutputDir))
}
$OutputRoot = Assert-PathInsideDirectory `
  -Path $OutputRoot `
  -Root $ProjectRoot `
  -Message "OutputDir must stay inside project: {0}"
if ($OutputRoot.Equals((ConvertTo-NormalizedFullPath -Path $ProjectRoot), [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "OutputDir must be a subdirectory inside project: $OutputRoot"
}
$Stage = Join-Path $OutputRoot "VerityLens-submission"
$ZipPath = Join-Path $OutputRoot "VerityLens-submission.zip"
$ManifestJson = Join-Path $Stage "SUBMISSION_MANIFEST.json"
$ManifestMarkdown = Join-Path $Stage "SUBMISSION_MANIFEST.md"
$SourceBundlePath = Join-Path $OutputRoot "verity-lens-source.zip"

function Remove-PathInsideProject {
  param([Parameter(Mandatory = $true)][string]$Path)
  Remove-PathInsideDirectory -Path $Path -Root $ProjectRoot
}

function Add-Artifact {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][string]$Kind,
    [Parameter(Mandatory = $true)][string]$Description,
    [bool]$Required = $true
  )

  $SourcePath = Join-Path $ProjectRoot $Source
  $DestinationPath = Join-Path $Stage $Destination
  if (-not (Test-Path $SourcePath)) {
    if ($Required) {
      throw "Required submission artifact missing: $Source"
    }
    return $null
  }

  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $DestinationPath) | Out-Null
  Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
  $Item = Get-Item -LiteralPath $DestinationPath
  $Hash = Get-FileHash -LiteralPath $DestinationPath -Algorithm SHA256
  return [ordered]@{
    kind = $Kind
    description = $Description
    source = $Source
    path = $Destination
    size_bytes = $Item.Length
    sha256 = $Hash.Hash
    modified_at = $Item.LastWriteTime.ToString("o")
  }
}

function Test-FinalCloudPhoneSubmissionReportReady {
  $JsonSource = Join-Path $ProjectRoot "reports\final_cloud_phone_submission_latest.json"
  $MarkdownSource = Join-Path $ProjectRoot "reports\final_cloud_phone_submission_latest.md"
  if (-not (Test-Path -LiteralPath $JsonSource) -or -not (Test-Path -LiteralPath $MarkdownSource)) {
    return $false
  }
  try {
    $Report = Get-Content -LiteralPath $JsonSource -Raw | ConvertFrom-Json
  } catch {
    return $false
  }
  if (-not [bool]$Report.ok -or -not $Report.packaging_contract) {
    return $false
  }
  return (
    [bool]$Report.packaging_contract.immutable_success_report -and
    [string]$Report.packaging_contract.packaged_under -eq "final/" -and
    [string]$Report.packaging_contract.submission_zip_artifact_scope -eq "pre_final_report_bundle_snapshot" -and
    [string]$Report.packaging_contract.submission_verification_artifact_scope -eq "pre_final_report_bundle_snapshot" -and
    [bool]$Report.packaging_contract.post_report_checks_required_after_snapshot
  )
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
Remove-PathInsideProject $Stage
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

& $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "make_source_bundle.ps1") -OutputPath (Join-Path $OutputDir "verity-lens-source.zip")
if ($LASTEXITCODE -ne 0) {
  throw "Source bundle creation failed with exit code $LASTEXITCODE"
}

$Artifacts = New-Object System.Collections.Generic.List[object]

$CoreArtifacts = @(
  @{ Source = ($SourceBundlePath.Substring($ProjectRoot.Length + 1)); Destination = "source\verity-lens-source.zip"; Kind = "source-bundle"; Description = "Clean reproducible source bundle without generated build outputs" },
  @{ Source = "docs\report\verity_lens_report.pdf"; Destination = "report\verity_lens_report.pdf"; Kind = "report"; Description = "University report PDF" },
  @{ Source = "docs\report\verity_lens_report.tex"; Destination = "report\verity_lens_report.tex"; Kind = "report-source"; Description = "University report LaTeX source" },
  @{ Source = "README.md"; Destination = "docs\README.md"; Kind = "documentation"; Description = "Project README" },
  @{ Source = "RUNBOOK.md"; Destination = "docs\RUNBOOK.md"; Kind = "documentation"; Description = "Operational runbook" },
  @{ Source = "docs\mobile_flutter_render.md"; Destination = "docs\mobile_flutter_render.md"; Kind = "documentation"; Description = "Mobile and Render deployment guide" },
  @{ Source = "docs\legacy_ml_inventory.md"; Destination = "docs\legacy_ml_inventory.md"; Kind = "documentation"; Description = "Legacy-code inventory" },
  @{ Source = "reports\product_acceptance_latest.md"; Destination = "quality\product_acceptance_latest.md"; Kind = "quality-report"; Description = "Product acceptance report with per-section 95 percent gate" },
  @{ Source = "reports\product_acceptance_latest.json"; Destination = "quality\product_acceptance_latest.json"; Kind = "quality-report-json"; Description = "Machine-readable product acceptance report" },
  @{ Source = "reports\quality_pack_v3_live.md"; Destination = "quality\quality_pack_v3_live.md"; Kind = "quality-report"; Description = "Live quality pack report with current-source checks" },
  @{ Source = "reports\quality_pack_v3_live.json"; Destination = "quality\quality_pack_v3_live.json"; Kind = "quality-report-json"; Description = "Machine-readable live quality pack report" },
  @{ Source = "reports\render_deploy_config_latest.md"; Destination = "quality\render_deploy_config_latest.md"; Kind = "quality-report"; Description = "Render blueprint, Dockerfile, dockerignore, and API dependency verification" },
  @{ Source = "reports\render_deploy_config_latest.json"; Destination = "quality\render_deploy_config_latest.json"; Kind = "quality-report-json"; Description = "Machine-readable Render deploy configuration verification" },
  @{ Source = "reports\release_gate_latest.md"; Destination = "quality\release_gate_latest.md"; Kind = "quality-report"; Description = "Release gate report covering PC, phone, Render bundle, and final packaging readiness" },
  @{ Source = "reports\release_gate_latest.json"; Destination = "quality\release_gate_latest.json"; Kind = "quality-report-json"; Description = "Machine-readable release gate report" },
  @{ Source = "reports\final_external_preflight_latest.md"; Destination = "final\final_external_preflight_latest.md"; Kind = "final-preflight-report"; Description = "Final external Render and physical-phone preflight report"; Required = $false },
  @{ Source = "reports\final_external_preflight_latest.json"; Destination = "final\final_external_preflight_latest.json"; Kind = "final-preflight-report-json"; Description = "Machine-readable final external Render and physical-phone preflight report"; Required = $false },
  @{ Source = "outputs\desktop_package\DESKTOP_PACKAGE_VERIFICATION.md"; Destination = "desktop\DESKTOP_PACKAGE_VERIFICATION.md"; Kind = "desktop-report"; Description = "Windows portable package verification"; Required = $false },
  @{ Source = "outputs\desktop_package\DESKTOP_PACKAGE_VERIFICATION.json"; Destination = "desktop\DESKTOP_PACKAGE_VERIFICATION.json"; Kind = "desktop-report-json"; Description = "Windows portable package machine-readable verification"; Required = $false },
  @{ Source = "outputs\phone_download\PHONE_READINESS.md"; Destination = "phone\PHONE_READINESS.md"; Kind = "phone-report"; Description = "Phone readiness report" },
  @{ Source = "outputs\phone_download\PHONE_APK_VERIFICATION.md"; Destination = "phone\PHONE_APK_VERIFICATION.md"; Kind = "phone-report"; Description = "APK verification report" },
  @{ Source = "outputs\phone_download\PHONE_LAN_APK_VERIFICATION.md"; Destination = "phone\PHONE_LAN_APK_VERIFICATION.md"; Kind = "phone-report"; Description = "Same-Wi-Fi APK verification report" },
  @{ Source = "outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.md"; Destination = "phone\PHONE_CLOUD_APK_VERIFICATION.md"; Kind = "phone-report"; Description = "Permanent cloud APK verification report"; Required = $false },
  @{ Source = "outputs\phone_download\PHONE_BUILD_STATUS.md"; Destination = "phone\PHONE_BUILD_STATUS.md"; Kind = "phone-report"; Description = "Temporary internet APK build status" },
  @{ Source = "outputs\phone_download\VerityLens-cloud-status.md"; Destination = "phone\VerityLens-cloud-status.md"; Kind = "phone-report"; Description = "Permanent cloud APK build status"; Required = $false },
  @{ Source = "outputs\phone_download\PHONE_INSTALL_PAGE.md"; Destination = "phone\PHONE_INSTALL_PAGE.md"; Kind = "phone-report"; Description = "Phone install page status" },
  @{ Source = "outputs\phone_download\PHONE_EMULATOR_SMOKE.md"; Destination = "phone\PHONE_EMULATOR_SMOKE.md"; Kind = "phone-report"; Description = "Android emulator install and launch smoke report"; Required = $false },
  @{ Source = "outputs\phone_download\PHONE_DEVICE_SMOKE.md"; Destination = "phone\PHONE_DEVICE_SMOKE.md"; Kind = "phone-report"; Description = "Real Android device install and launch smoke report"; Required = $false },
  @{ Source = "outputs\phone_download\phone_readiness.json"; Destination = "phone\phone_readiness.json"; Kind = "phone-report-json"; Description = "Phone readiness machine-readable report" },
  @{ Source = "outputs\phone_download\PHONE_APK_VERIFICATION.json"; Destination = "phone\PHONE_APK_VERIFICATION.json"; Kind = "phone-report-json"; Description = "APK verification machine-readable report" },
  @{ Source = "outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json"; Destination = "phone\PHONE_LAN_APK_VERIFICATION.json"; Kind = "phone-report-json"; Description = "Same-Wi-Fi APK machine-readable verification" },
  @{ Source = "outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json"; Destination = "phone\PHONE_CLOUD_APK_VERIFICATION.json"; Kind = "phone-report-json"; Description = "Permanent cloud APK machine-readable verification"; Required = $false },
  @{ Source = "outputs\phone_download\VerityLens-internet-flutter-source-stamp.json"; Destination = "phone\VerityLens-internet-flutter-source-stamp.json"; Kind = "phone-source-stamp"; Description = "Flutter source stamp recorded when the temporary internet APK was built" },
  @{ Source = "outputs\phone_download\VerityLens-lan-flutter-source-stamp.json"; Destination = "phone\VerityLens-lan-flutter-source-stamp.json"; Kind = "phone-source-stamp"; Description = "Flutter source stamp recorded when the same-Wi-Fi APK was built" },
  @{ Source = "outputs\phone_download\VerityLens-cloud-flutter-source-stamp.json"; Destination = "phone\VerityLens-cloud-flutter-source-stamp.json"; Kind = "phone-source-stamp"; Description = "Flutter source stamp recorded when the permanent cloud APK was built"; Required = $false },
  @{ Source = "outputs\phone_download\PHONE_INSTALL_PAGE.json"; Destination = "phone\PHONE_INSTALL_PAGE.json"; Kind = "phone-report-json"; Description = "Install page machine-readable report" },
  @{ Source = "outputs\phone_download\VerityLens-cloud-api-url.txt"; Destination = "phone\VerityLens-cloud-api-url.txt"; Kind = "phone-config"; Description = "Permanent cloud API URL embedded in cloud APK"; Required = $false },
  @{ Source = "outputs\phone_download\PHONE_EMULATOR_SMOKE.json"; Destination = "phone\PHONE_EMULATOR_SMOKE.json"; Kind = "phone-report-json"; Description = "Android emulator install and launch smoke machine-readable report"; Required = $false },
  @{ Source = "outputs\phone_download\PHONE_EMULATOR_SCREENSHOT.png"; Destination = "phone\PHONE_EMULATOR_SCREENSHOT.png"; Kind = "phone-screenshot"; Description = "Android emulator launch screenshot"; Required = $false },
  @{ Source = "outputs\phone_download\index.html"; Destination = "phone\install_page\index.html"; Kind = "phone-install-page"; Description = "Phone-friendly APK download page" },
  @{ Source = "outputs\phone_download\PHONE_DEVICE_SMOKE.json"; Destination = "phone\PHONE_DEVICE_SMOKE.json"; Kind = "phone-report-json"; Description = "Real Android device install and launch smoke machine-readable report"; Required = $false },
  @{ Source = "outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png"; Destination = "phone\PHONE_DEVICE_SCREENSHOT.png"; Kind = "phone-screenshot"; Description = "Real Android device launch screenshot"; Required = $false },
  @{ Source = "outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.md"; Destination = "cloud\CLOUD_DEPLOYMENT_STATUS.md"; Kind = "cloud-report"; Description = "Permanent cloud deployment status" },
  @{ Source = "outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json"; Destination = "cloud\CLOUD_DEPLOYMENT_STATUS.json"; Kind = "cloud-report-json"; Description = "Permanent cloud deployment machine-readable status" },
  @{ Source = "outputs\cloud_deploy\render_backend_smoke\RENDER_BUNDLE_SMOKE.md"; Destination = "cloud\RENDER_BUNDLE_SMOKE.md"; Kind = "cloud-report"; Description = "Render backend bundle smoke report"; Required = $false },
  @{ Source = "outputs\cloud_deploy\render_backend_smoke\RENDER_BUNDLE_SMOKE.json"; Destination = "cloud\RENDER_BUNDLE_SMOKE.json"; Kind = "cloud-report-json"; Description = "Render backend bundle smoke machine-readable report"; Required = $false }
)

if (Test-FinalCloudPhoneSubmissionReportReady) {
  $CoreArtifacts += @(
    @{ Source = "reports\final_cloud_phone_submission_latest.md"; Destination = "final\final_cloud_phone_submission_latest.md"; Kind = "final-submission-report"; Description = "Final strict cloud phone submission report"; Required = $true },
    @{ Source = "reports\final_cloud_phone_submission_latest.json"; Destination = "final\final_cloud_phone_submission_latest.json"; Kind = "final-submission-report-json"; Description = "Machine-readable final strict cloud phone submission report"; Required = $true }
  )
}

foreach ($Artifact in $CoreArtifacts) {
  $Added = Add-Artifact @Artifact
  if ($Added) {
    $Artifacts.Add($Added)
  }
}

if (-not $SkipLargeArtifacts) {
  $LargeArtifacts = @(
    @{ Source = "dist\FakeNewsDetector-Windows-Portable.zip"; Destination = "apps\FakeNewsDetector-Windows-Portable.zip"; Kind = "pc-app"; Description = "Windows portable desktop application" },
    @{ Source = "outputs\phone_download\VerityLens-internet.apk"; Destination = "phone\VerityLens-internet.apk"; Kind = "phone-apk"; Description = "Temporary internet Android APK" },
    @{ Source = "outputs\phone_download\VerityLens-lan.apk"; Destination = "phone\VerityLens-lan.apk"; Kind = "phone-apk"; Description = "Same-Wi-Fi Android APK" },
    @{ Source = "outputs\phone_download\VerityLens-cloud.apk"; Destination = "phone\VerityLens-cloud.apk"; Kind = "phone-apk"; Description = "Permanent cloud Android APK"; Required = $false },
    @{ Source = "outputs\cloud_deploy\verity-lens-render-backend.zip"; Destination = "cloud\verity-lens-render-backend.zip"; Kind = "cloud-backend"; Description = "Render backend deployment bundle" }
  )

  foreach ($Artifact in $LargeArtifacts) {
    $Added = Add-Artifact @Artifact
    if ($Added) {
      $Artifacts.Add($Added)
    }
  }
}

$Readiness = $null
$ReadinessSource = Join-Path $ProjectRoot "outputs\phone_download\phone_readiness.json"
if (Test-Path $ReadinessSource) {
  try {
    $Readiness = Get-Content $ReadinessSource -Raw | ConvertFrom-Json
  } catch {
    $Readiness = $null
  }
}

$Manifest = [ordered]@{
  product = "Verity Lens"
  generated_at = (Get-Date).ToString("o")
  source_project = $ProjectRoot
  includes_large_artifacts = -not [bool]$SkipLargeArtifacts
  readiness = if ($Readiness) { $Readiness.ready } else { $null }
  artifacts = $Artifacts
}

$Manifest | ConvertTo-Json -Depth 8 | Set-Content -Path $ManifestJson -Encoding UTF8

$Lines = @(
  "# Verity Lens Submission Manifest",
  "",
  "- Generated: ``$($Manifest.generated_at)``",
  "- Source project: ``$ProjectRoot``",
  "- Includes large artifacts: ``$(-not [bool]$SkipLargeArtifacts)``"
)
if ($Readiness) {
  $Lines += @(
    "- PC desktop package: ``$($Readiness.ready.pc_desktop)``",
    "- Phone same Wi-Fi: ``$($Readiness.ready.phone_same_wifi)``",
    "- Temporary tunnel phone: ``$($Readiness.ready.phone_temporary_tunnel)``",
    "- Permanent cloud phone: ``$($Readiness.ready.phone_permanent_cloud)``",
    "- Render deploy package: ``$($Readiness.ready.render_deploy_package)``"
  )
}
$Lines += @("", "## Artifacts", "")
foreach ($Artifact in $Artifacts) {
  $Lines += @(
    "### $($Artifact.path)",
    "",
    "- Kind: ``$($Artifact.kind)``",
    "- Description: $($Artifact.description)",
    "- Size bytes: ``$($Artifact.size_bytes)``",
    "- SHA256: ``$($Artifact.sha256)``",
    ""
  )
}
$Lines | Set-Content -Path $ManifestMarkdown -Encoding UTF8

if (Test-Path $ZipPath) {
  Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -Force

$Zip = Get-Item -LiteralPath $ZipPath
$ZipHash = Get-FileHash -LiteralPath $Zip.FullName -Algorithm SHA256
$ZipInfoPath = Join-Path $OutputRoot "VerityLens-submission-zip.md"
$VerificationJson = Join-Path $OutputRoot "SUBMISSION_BUNDLE_VERIFICATION.json"
$VerificationMarkdown = Join-Path $OutputRoot "SUBMISSION_BUNDLE_VERIFICATION.md"
@(
  "# Verity Lens Submission Zip",
  "",
  "- Zip: ``$($Zip.FullName)``",
  "- Size bytes: ``$($Zip.Length)``",
  "- SHA256: ``$($ZipHash.Hash)``",
  "- Manifest: ``$ManifestMarkdown``"
) | Set-Content -Path $ZipInfoPath -Encoding UTF8

$VerificationArgs = @(
  "-NoProfile",
  "-ExecutionPolicy",
  "Bypass",
  "-File",
  (Join-Path $PSScriptRoot "verify_submission_bundle.ps1"),
  "-ZipPath",
  $ZipPath,
  "-OutJson",
  $VerificationJson,
  "-OutMarkdown",
  $VerificationMarkdown
)
if ($SkipLargeArtifacts) {
  $VerificationArgs += "-AllowMissingLargeArtifacts"
}
& $PowerShell @VerificationArgs
if ($LASTEXITCODE -ne 0) {
  throw "Submission bundle verification failed with exit code $LASTEXITCODE"
}

Get-Item -LiteralPath $ZipPath | Select-Object FullName, Length, LastWriteTime
