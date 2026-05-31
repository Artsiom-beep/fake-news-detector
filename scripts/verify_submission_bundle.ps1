[CmdletBinding()]
param(
  [string]$ZipPath = "outputs\submission\VerityLens-submission.zip",
  [switch]$AllowMissingLargeArtifacts,
  [string]$OutJson = "outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json",
  [string]$OutMarkdown = "outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "cloud_url_policy.ps1")
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Resolve-ProjectPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  if ([System.IO.Path]::IsPathRooted($Path)) {
    return $Path
  }
  return (Join-Path $ProjectRoot $Path)
}

function Normalize-ZipName {
  param([Parameter(Mandatory = $true)][string]$Name)
  return $Name.Replace("\", "/").TrimStart("/")
}

function Add-Failure {
  param([Parameter(Mandatory = $true)][string]$Message)
  $script:Failures.Add($Message) | Out-Null
}

function Add-WarningMessage {
  param([Parameter(Mandatory = $true)][string]$Message)
  $script:Warnings.Add($Message) | Out-Null
}

function ConvertTo-UtcDateTime {
  param($Value)
  if ($null -eq $Value) {
    return $null
  }
  if ($Value -is [datetimeoffset]) {
    return $Value.UtcDateTime
  }
  if ($Value -is [datetime]) {
    if ($Value.Kind -eq [System.DateTimeKind]::Unspecified) {
      return ([datetime]::SpecifyKind($Value, [System.DateTimeKind]::Local)).ToUniversalTime()
    }
    return $Value.ToUniversalTime()
  }
  return [datetimeoffset]::Parse(
    [string]$Value,
    [System.Globalization.CultureInfo]::InvariantCulture,
    [System.Globalization.DateTimeStyles]::AssumeLocal
  ).UtcDateTime
}

function Get-ZipEntry {
  param([Parameter(Mandatory = $true)][string]$Name)
  $Normalized = Normalize-ZipName $Name
  if ($script:EntryMap.ContainsKey($Normalized)) {
    return $script:EntryMap[$Normalized]
  }
  return $null
}

function Test-RequiredEntry {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [bool]$Required = $true
  )
  $Entry = Get-ZipEntry $Name
  if (-not $Entry -and $Required) {
    Add-Failure "Missing required entry: $Name"
  }
  return [bool]$Entry
}

function Read-EntryText {
  param([Parameter(Mandatory = $true)][string]$Name)
  $Entry = Get-ZipEntry $Name
  if (-not $Entry) {
    return $null
  }
  $Stream = $Entry.Open()
  try {
    $Reader = New-Object System.IO.StreamReader($Stream, [System.Text.Encoding]::UTF8)
    try {
      return $Reader.ReadToEnd()
    } finally {
      $Reader.Dispose()
    }
  } finally {
    $Stream.Dispose()
  }
}

function Read-EntryJson {
  param([Parameter(Mandatory = $true)][string]$Name)
  $Text = Read-EntryText $Name
  if ($null -eq $Text) {
    Add-Failure "Missing JSON entry: $Name"
    return $null
  }
  try {
    return $Text | ConvertFrom-Json
  } catch {
    Add-Failure "Invalid JSON in $Name`: $($_.Exception.Message)"
    return $null
  }
}

function Get-EntryHash {
  param([Parameter(Mandatory = $true)]$Entry)
  $Sha = [System.Security.Cryptography.SHA256]::Create()
  $Stream = $Entry.Open()
  try {
    $HashBytes = $Sha.ComputeHash($Stream)
    return [BitConverter]::ToString($HashBytes).Replace("-", "")
  } finally {
    $Stream.Dispose()
    $Sha.Dispose()
  }
}

function Read-ZipEntryPngInfo {
  param([Parameter(Mandatory = $true)]$Entry)

  $Info = [ordered]@{
    read_bytes = 0
    png_signature_ok = $false
    width = 0
    height = 0
    valid_png = $false
    error = ""
  }
  $Stream = $Entry.Open()
  try {
    $Header = [byte[]]::new(24)
    $Info.read_bytes = $Stream.Read($Header, 0, $Header.Length)
    $Expected = [byte[]](0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)
    $SignatureOk = ($Info.read_bytes -ge $Expected.Length)
    for ($Index = 0; $Index -lt $Expected.Length -and $SignatureOk; $Index++) {
      if ($Header[$Index] -ne $Expected[$Index]) {
        $SignatureOk = $false
      }
    }
    $Info.png_signature_ok = $SignatureOk
    if ($Info.read_bytes -ge 24 -and $SignatureOk) {
      $Info.width = (
        ([int]$Header[16] -shl 24) -bor
        ([int]$Header[17] -shl 16) -bor
        ([int]$Header[18] -shl 8) -bor
        [int]$Header[19]
      )
      $Info.height = (
        ([int]$Header[20] -shl 24) -bor
        ([int]$Header[21] -shl 16) -bor
        ([int]$Header[22] -shl 8) -bor
        [int]$Header[23]
      )
    }
    $Info.valid_png = ($Info.png_signature_ok -and [int]$Info.width -gt 0 -and [int]$Info.height -gt 0)
    if (-not $Info.valid_png) {
      $Info.error = "invalid_png_or_dimensions"
    }
  } catch {
    $Info.error = $_.Exception.Message
  } finally {
    $Stream.Dispose()
  }
  return $Info
}

function Test-EntryMatchesArtifactStatus {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    $Status,
    [Parameter(Mandatory = $true)][string]$Label
  )
  if (-not $Status) {
    Add-Failure "$Label status is missing for $Name"
    return
  }

  $Entry = Get-ZipEntry $Name
  if (-not $Entry) {
    Add-Failure "$Label references an entry that is missing from ZIP: $Name"
    return
  }

  $Properties = @($Status.PSObject.Properties.Name)
  if ($Properties -contains "exists" -and -not [bool]$Status.exists) {
    Add-Failure "$Label says artifact does not exist, but ZIP entry is required: $Name"
  }

  if ($Properties -contains "size_bytes" -and [long]$Status.size_bytes -ne [long]$Entry.Length) {
    Add-Failure "$Label size mismatch for $Name"
  }

  if ($Properties -contains "sha256" -and [string]$Status.sha256) {
    $ExpectedHash = ([string]$Status.sha256).ToUpperInvariant()
    $ActualHash = Get-EntryHash $Entry
    if ($ActualHash -ne $ExpectedHash) {
      Add-Failure "$Label SHA256 mismatch for $Name"
    }
  }
}

function Test-ApkSourceStampEntry {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)]$Verification,
    [Parameter(Mandatory = $true)][string]$Label,
    [bool]$Required = $true
  )

  $Entry = Get-ZipEntry $Name
  if (-not $Entry) {
    if ($Required) {
      Add-Failure "$Label Flutter source stamp sidecar is missing from ZIP: $Name"
    }
    return
  }

  $Stamp = Read-EntryJson $Name
  if (-not $Stamp) {
    return
  }
  if (-not $Verification -or -not $Verification.flutter_source_stamp) {
    Add-Failure "$Label verification does not record a Flutter source stamp."
    return
  }

  $BundledSha = if ($Stamp.sha256) { ([string]$Stamp.sha256).ToUpperInvariant() } else { "" }
  $VerificationBuildSha = if ($Verification.flutter_source_stamp.build_sha256) { ([string]$Verification.flutter_source_stamp.build_sha256).ToUpperInvariant() } else { "" }
  $VerificationCurrentSha = if ($Verification.flutter_source_stamp.current_sha256) { ([string]$Verification.flutter_source_stamp.current_sha256).ToUpperInvariant() } else { "" }
  if (-not $BundledSha) {
    Add-Failure "$Label Flutter source stamp sidecar does not record sha256."
  }
  if (-not $VerificationBuildSha) {
    Add-Failure "$Label APK verification does not record build source sha256."
  }
  if ($BundledSha -and $VerificationBuildSha -and $BundledSha -ne $VerificationBuildSha) {
    Add-Failure "$Label bundled Flutter source stamp SHA256 does not match APK verification build stamp."
  }
  if ($BundledSha -and $VerificationCurrentSha -and $BundledSha -ne $VerificationCurrentSha) {
    Add-Failure "$Label bundled Flutter source stamp SHA256 does not match APK verification current source stamp."
  }
  if ($Verification.flutter_source_stamp.build_file_count -and $Stamp.file_count -and [int]$Verification.flutter_source_stamp.build_file_count -ne [int]$Stamp.file_count) {
    Add-Failure "$Label bundled Flutter source stamp file count does not match APK verification."
  }
}

function Read-NestedZipEntries {
  param([Parameter(Mandatory = $true)][string]$Name)
  $Entry = Get-ZipEntry $Name
  if (-not $Entry) {
    Add-Failure "Missing nested ZIP entry: $Name"
    return @()
  }

  $Memory = New-Object System.IO.MemoryStream
  $Stream = $Entry.Open()
  try {
    $Stream.CopyTo($Memory)
  } finally {
    $Stream.Dispose()
  }
  $Memory.Position = 0

  $Nested = [System.IO.Compression.ZipArchive]::new($Memory, [System.IO.Compression.ZipArchiveMode]::Read, $false)
  try {
    return @($Nested.Entries | ForEach-Object { Normalize-ZipName $_.FullName })
  } finally {
    $Nested.Dispose()
    $Memory.Dispose()
  }
}

function Read-NestedZipEntryInfo {
  param([Parameter(Mandatory = $true)][string]$Name)
  $Entry = Get-ZipEntry $Name
  if (-not $Entry) {
    Add-Failure "Missing nested ZIP entry: $Name"
    return @()
  }

  $Memory = New-Object System.IO.MemoryStream
  $Stream = $Entry.Open()
  try {
    $Stream.CopyTo($Memory)
  } finally {
    $Stream.Dispose()
  }
  $Memory.Position = 0

  $Nested = [System.IO.Compression.ZipArchive]::new($Memory, [System.IO.Compression.ZipArchiveMode]::Read, $false)
  try {
    return @($Nested.Entries | Where-Object { $_.FullName } | ForEach-Object {
        [ordered]@{
          name = Normalize-ZipName $_.FullName
          last_write_time_utc = $_.LastWriteTime.UtcDateTime
        }
      })
  } finally {
    $Nested.Dispose()
    $Memory.Dispose()
  }
}

function Test-GatedSourceEntry {
  param([Parameter(Mandatory = $true)][string]$Name)

  if ($Name -match '^(src|tests|scripts)/') {
    return $true
  }
  if ($Name -match '^apps/fake_news_detector_flutter/(lib|test)/') {
    return $true
  }
  foreach ($Exact in @(
      "apps/fake_news_detector_flutter/pubspec.yaml",
      "apps/fake_news_detector_flutter/pubspec.lock",
      "docs/report/verity_lens_report.tex",
      "render.yaml",
      "Dockerfile",
      "requirements.api.txt",
      "requirements.lock.txt"
    )) {
    if ($Name -eq $Exact) {
      return $true
    }
  }
  return $false
}

$ResolvedZipPath = Resolve-ProjectPath $ZipPath
$OutJsonPath = Resolve-ProjectPath $OutJson
$OutMarkdownPath = Resolve-ProjectPath $OutMarkdown
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutJsonPath), (Split-Path -Parent $OutMarkdownPath) | Out-Null

$Failures = New-Object System.Collections.Generic.List[string]
$Warnings = New-Object System.Collections.Generic.List[string]
$Checks = New-Object System.Collections.Generic.List[object]
$FinalCloudPhoneSubmissionPresent = $false
$FinalCloudPhoneSubmissionOk = $false
$FinalCloudPhoneSubmissionStatus = "absent"

if (-not (Test-Path $ResolvedZipPath)) {
  throw "Submission ZIP not found: $ResolvedZipPath"
}

$ZipFile = Get-Item -LiteralPath $ResolvedZipPath
$ZipHash = Get-FileHash -LiteralPath $ResolvedZipPath -Algorithm SHA256
$EntryMap = @{}
$Zip = [System.IO.Compression.ZipFile]::OpenRead($ResolvedZipPath)
try {
  foreach ($Entry in $Zip.Entries) {
    $EntryMap[(Normalize-ZipName $Entry.FullName)] = $Entry
  }

  $RequiredCore = @(
    "SUBMISSION_MANIFEST.json",
    "SUBMISSION_MANIFEST.md",
    "source/verity-lens-source.zip",
    "report/verity_lens_report.pdf",
    "report/verity_lens_report.tex",
    "docs/README.md",
    "docs/RUNBOOK.md",
    "docs/mobile_flutter_render.md",
    "docs/legacy_ml_inventory.md",
    "quality/product_acceptance_latest.md",
    "quality/product_acceptance_latest.json",
    "quality/quality_pack_v3_live.md",
    "quality/quality_pack_v3_live.json",
    "quality/render_deploy_config_latest.md",
    "quality/render_deploy_config_latest.json",
    "quality/release_gate_latest.md",
    "quality/release_gate_latest.json",
    "phone/PHONE_READINESS.md",
    "phone/phone_readiness.json",
    "phone/PHONE_APK_VERIFICATION.md",
    "phone/PHONE_APK_VERIFICATION.json",
    "phone/PHONE_LAN_APK_VERIFICATION.md",
    "phone/PHONE_LAN_APK_VERIFICATION.json",
    "phone/VerityLens-internet-flutter-source-stamp.json",
    "phone/VerityLens-lan-flutter-source-stamp.json",
    "phone/PHONE_BUILD_STATUS.md",
    "phone/PHONE_INSTALL_PAGE.md",
    "phone/PHONE_INSTALL_PAGE.json",
    "phone/PHONE_DEVICE_SMOKE.md",
    "phone/PHONE_DEVICE_SMOKE.json",
    "phone/install_page/index.html",
    "cloud/CLOUD_DEPLOYMENT_STATUS.md",
    "cloud/CLOUD_DEPLOYMENT_STATUS.json",
    "cloud/RENDER_BUNDLE_SMOKE.md",
    "cloud/RENDER_BUNDLE_SMOKE.json"
  )
  foreach ($Name in $RequiredCore) {
    [void](Test-RequiredEntry $Name)
  }

  $LargeEntries = @(
    "apps/FakeNewsDetector-Windows-Portable.zip",
    "phone/VerityLens-internet.apk",
    "phone/VerityLens-lan.apk",
    "cloud/verity-lens-render-backend.zip",
    "desktop/DESKTOP_PACKAGE_VERIFICATION.md",
    "desktop/DESKTOP_PACKAGE_VERIFICATION.json"
  )
  foreach ($Name in $LargeEntries) {
    [void](Test-RequiredEntry -Name $Name -Required:(-not $AllowMissingLargeArtifacts))
  }

  $CloudOptional = @(
    "phone/VerityLens-cloud.apk",
    "phone/PHONE_CLOUD_APK_VERIFICATION.md",
    "phone/PHONE_CLOUD_APK_VERIFICATION.json",
    "phone/VerityLens-cloud-status.md",
    "phone/VerityLens-cloud-api-url.txt",
    "phone/VerityLens-cloud-flutter-source-stamp.json"
  )
  $CloudPresent = @($CloudOptional | Where-Object { Get-ZipEntry $_ })
  if ($CloudPresent.Count -gt 0 -and $CloudPresent.Count -ne $CloudOptional.Count) {
    Add-Failure "Permanent cloud phone artifacts are partial: $($CloudPresent -join ', ')"
  }

  $FinalExternalPreflightOptional = @(
    "final/final_external_preflight_latest.md",
    "final/final_external_preflight_latest.json"
  )
  $FinalExternalPreflightPresent = @($FinalExternalPreflightOptional | Where-Object { Get-ZipEntry $_ })
  if ($FinalExternalPreflightPresent.Count -gt 0 -and $FinalExternalPreflightPresent.Count -ne $FinalExternalPreflightOptional.Count) {
    Add-Failure "Final external preflight artifacts are partial: $($FinalExternalPreflightPresent -join ', ')"
  }

  $FinalCloudPhoneOptional = @(
    "final/final_cloud_phone_submission_latest.md",
    "final/final_cloud_phone_submission_latest.json"
  )
  $FinalCloudPhonePresent = @($FinalCloudPhoneOptional | Where-Object { Get-ZipEntry $_ })
  if ($FinalCloudPhonePresent.Count -gt 0 -and $FinalCloudPhonePresent.Count -ne $FinalCloudPhoneOptional.Count) {
    Add-Failure "Final cloud phone submission artifacts are partial: $($FinalCloudPhonePresent -join ', ')"
  }

  $EmulatorOptional = @(
    "phone/PHONE_EMULATOR_SMOKE.md",
    "phone/PHONE_EMULATOR_SMOKE.json"
  )
  $EmulatorPresent = @($EmulatorOptional | Where-Object { Get-ZipEntry $_ })
  if ($EmulatorPresent.Count -gt 0 -and $EmulatorPresent.Count -ne $EmulatorOptional.Count) {
    Add-Failure "Phone emulator smoke artifacts are partial: $($EmulatorPresent -join ', ')"
  }

  $Manifest = Read-EntryJson "SUBMISSION_MANIFEST.json"
  if ($Manifest) {
    if ($Manifest.product -ne "Verity Lens") {
      Add-Failure "Manifest product is not Verity Lens."
    }
    foreach ($Artifact in @($Manifest.artifacts)) {
      $Path = Normalize-ZipName ([string]$Artifact.path)
      $Entry = Get-ZipEntry $Path
      if (-not $Entry) {
        Add-Failure "Manifest artifact missing from ZIP: $Path"
        continue
      }
      if ([long]$Artifact.size_bytes -ne [long]$Entry.Length) {
        Add-Failure "Manifest size mismatch for $Path"
      }
      $ActualHash = Get-EntryHash $Entry
      if ([string]$Artifact.sha256 -and $ActualHash -ne ([string]$Artifact.sha256).ToUpperInvariant()) {
        Add-Failure "Manifest SHA256 mismatch for $Path"
      }
    }
  }

  if (Get-ZipEntry "final/final_external_preflight_latest.json") {
    $FinalExternalPreflight = Read-EntryJson "final/final_external_preflight_latest.json"
    if ($FinalExternalPreflight) {
      if (-not $FinalExternalPreflight.finalizer_command) {
        Add-Failure "Final external preflight does not record the finalizer command."
      }
      if (-not $FinalExternalPreflight.final_evidence_contract) {
        Add-Failure "Final external preflight does not record the final evidence contract."
      }
      if (-not [bool]$FinalExternalPreflight.ready_to_run_finalizer) {
        $MissingPreflight = @($FinalExternalPreflight.missing_to_run_finalizer) -join ", "
        if (-not $MissingPreflight) {
          $MissingPreflight = "unknown"
        }
        Add-WarningMessage "Final external preflight is not ready to run finalizer; missing: $MissingPreflight."
      }
    }
  }

  if (Get-ZipEntry "final/final_cloud_phone_submission_latest.json") {
    $FinalCloudPhoneSubmissionPresent = $true
    $FinalCloudPhoneSubmission = Read-EntryJson "final/final_cloud_phone_submission_latest.json"
    if ($FinalCloudPhoneSubmission) {
      $FinalCloudPhoneSubmissionOk = [bool]$FinalCloudPhoneSubmission.ok
      $FinalCloudPhoneSubmissionStatus = if ($FinalCloudPhoneSubmissionOk) { "ok" } else { "not_ok" }
      if (-not ($FinalCloudPhoneSubmission.PSObject.Properties.Name -contains "ok")) {
        $FinalCloudPhoneSubmissionStatus = "invalid"
        Add-Failure "Final cloud phone submission report does not record ok."
      }
      if (-not $FinalCloudPhoneSubmission.evidence) {
        $FinalCloudPhoneSubmissionStatus = "invalid"
        Add-Failure "Final cloud phone submission report does not record evidence."
      }
      if ([bool]$FinalCloudPhoneSubmission.ok) {
        if (-not (
            $FinalCloudPhoneSubmission.packaging_contract -and
            [bool]$FinalCloudPhoneSubmission.packaging_contract.immutable_success_report -and
            [string]$FinalCloudPhoneSubmission.packaging_contract.packaged_under -eq "final/" -and
            [string]$FinalCloudPhoneSubmission.packaging_contract.submission_zip_artifact_scope -eq "pre_final_report_bundle_snapshot" -and
            [string]$FinalCloudPhoneSubmission.packaging_contract.submission_verification_artifact_scope -eq "pre_final_report_bundle_snapshot" -and
            [bool]$FinalCloudPhoneSubmission.packaging_contract.post_report_checks_required_after_snapshot
          )) {
          Add-Failure "Final cloud phone submission OK report does not record the immutable final packaging contract."
        }
        $RequiredPostReportChecks = @(
          "Final submission bundle with final report",
          "Final submission verifier with final report",
          "Goal completion audit refresh",
          "Final cloud phone evidence recheck"
        )
        $RecordedPostReportChecks = @($FinalCloudPhoneSubmission.packaging_contract.post_report_checks)
        foreach ($RequiredPostReportCheck in $RequiredPostReportChecks) {
          if ($RecordedPostReportChecks -notcontains $RequiredPostReportCheck) {
            Add-Failure "Final cloud phone submission OK report is missing required post-report packaging check: $RequiredPostReportCheck"
          }
        }
      }
      if ([bool]$FinalCloudPhoneSubmission.ok -and $FinalCloudPhoneSubmission.evidence) {
        $RequiredFinalEvidence = @(
          "release_gate_ok",
          "submission_verification_ok",
          "phone_permanent_cloud",
          "cloud_status_outcome_ready",
          "cloud_status_verification_ok",
          "cloud_status_readiness_ok",
          "cloud_status_ready_to_publish",
          "cloud_apk_release_mode",
          "cloud_apk_api_permanent_url",
          "cloud_apk_api_not_temporary_tunnel",
          "cloud_apk_api_matches_requested_url",
          "cloud_apk_embedded_api_url_found",
          "cloud_apk_embedded_api_matches_base_url",
          "cloud_apk_status_matches_url",
          "cloud_apk_status_matches_mode",
          "cloud_apk_status_matches_flutter_source_stamp",
          "phone_device_smoke_ok",
          "phone_device_requires_physical",
          "phone_device_selected_physical",
          "phone_device_identity_recorded",
          "phone_device_screenshot_captured",
          "phone_device_screenshot_sha256_recorded",
          "phone_device_screenshot_sha256_matches",
          "phone_device_screenshot_valid_png",
          "goal_audit_complete"
        )
        foreach ($Field in $RequiredFinalEvidence) {
          if (-not (
              $FinalCloudPhoneSubmission.evidence.PSObject.Properties.Name -contains $Field -and
              [bool]$FinalCloudPhoneSubmission.evidence.$Field
            )) {
            Add-Failure "Final cloud phone submission OK report has false or missing evidence field: $Field"
          }
        }
        if (-not ([string]$FinalCloudPhoneSubmission.evidence.phone_device_selected_id).Trim()) {
          Add-Failure "Final cloud phone submission OK report does not record the physical phone device id."
        }
      } elseif (-not [bool]$FinalCloudPhoneSubmission.ok) {
        Add-WarningMessage "Final cloud phone submission report is present but not OK; make_submission_bundle.ps1 only packages successful final reports, so this ZIP likely came from a failed finalizer run or an older bundle script."
      }
    } else {
      $FinalCloudPhoneSubmissionStatus = "invalid"
    }
  }

  $Product = Read-EntryJson "quality/product_acceptance_latest.json"
  if ($Product) {
    $ProductSummary = if ($Product.summary) { $Product.summary } else { $Product }
    if (-not [bool]$ProductSummary.gate_passed) {
      Add-Failure "Product acceptance gate_passed is false."
    }
    if ([int]$ProductSummary.passed -lt [int]$ProductSummary.total -or [double]$ProductSummary.pass_rate -lt 0.95) {
      Add-Failure "Product acceptance is below the 95 percent target."
    }
    foreach ($Section in $ProductSummary.sections.PSObject.Properties) {
      $MinimumForSection = [int]$ProductSummary.min_cases_per_section
      if ($ProductSummary.min_cases_by_section -and $ProductSummary.min_cases_by_section.PSObject.Properties.Name -contains $Section.Name) {
        $MinimumForSection = [int]$ProductSummary.min_cases_by_section.$($Section.Name)
      }
      if ([int]$Section.Value.total -lt $MinimumForSection) {
        Add-Failure "Product acceptance section has fewer than required cases: $($Section.Name)"
      }
      if ([double]$Section.Value.pass_rate -lt 0.95) {
        Add-Failure "Product acceptance section below 95 percent: $($Section.Name)"
      }
    }
  }

  $Quality = Read-EntryJson "quality/quality_pack_v3_live.json"
  if ($Quality) {
    if ([int]$Quality.failed -ne 0 -or [int]$Quality.errors -ne 0) {
      Add-Failure "Live quality pack has failures or errors."
    }
    if ([int]$Quality.passed -lt [int]$Quality.total) {
      Add-Failure "Live quality pack did not pass all cases."
    }
  }

  $RenderDeployConfig = Read-EntryJson "quality/render_deploy_config_latest.json"
  if ($RenderDeployConfig) {
    if (-not [bool]$RenderDeployConfig.ok) {
      Add-Failure "Render deploy config verification is not OK."
    }
    if ($RenderDeployConfig.render) {
      if ([string]$RenderDeployConfig.render.runtime -ne "docker") {
        Add-Failure "Render deploy config runtime is not docker."
      }
      if ([string]$RenderDeployConfig.render.dockerfilePath -ne "./Dockerfile") {
        Add-Failure "Render deploy config does not point at ./Dockerfile."
      }
      if ([string]$RenderDeployConfig.render.healthCheckPath -ne "/health") {
        Add-Failure "Render deploy config health check path is not /health."
      }
    } else {
      Add-Failure "Render deploy config report is missing render service details."
    }
    if (-not ($RenderDeployConfig.dockerfile -and [bool]$RenderDeployConfig.dockerfile.uses_api_app)) {
      Add-Failure "Render deploy config does not prove Dockerfile starts the canonical API app."
    }
    if (-not ($RenderDeployConfig.dockerfile -and [bool]$RenderDeployConfig.dockerfile.uses_render_port)) {
      Add-Failure "Render deploy config does not prove Dockerfile uses the Render PORT."
    }
    if ($RenderDeployConfig.requirements -and @($RenderDeployConfig.requirements.forbidden_present).Count -gt 0) {
      Add-Failure "Render deploy config found forbidden API requirements: $(@($RenderDeployConfig.requirements.forbidden_present) -join ', ')"
    }
  }

  $ReleaseGate = Read-EntryJson "quality/release_gate_latest.json"
  if ($ReleaseGate) {
    if (-not [bool]$ReleaseGate.ok) {
      Add-Failure "Release gate report ok is false."
    }
    if (-not $ReleaseGate.steps -or @($ReleaseGate.steps).Count -eq 0) {
      Add-Failure "Release gate report has no recorded steps."
    } else {
      $StepLabels = @($ReleaseGate.steps | ForEach-Object { [string]$_.label })
      $FailedSteps = @($ReleaseGate.steps | Where-Object { [string]$_.status -ne "passed" })
      if ($FailedSteps.Count -gt 0) {
        Add-Failure "Release gate report contains non-passed steps: $(@($FailedSteps | ForEach-Object { $_.label }) -join ', ')"
      }
      foreach ($RequiredStep in @(
          "Check Python",
          "Python syntax",
          "Backend unit and integration tests",
          "Product acceptance gate",
          "University report PDF",
          "Render deploy config verification",
          "Render backend bundle",
          "Render backend bundle smoke",
          "Cloud deployment status report",
          "Internet APK verification",
          "Phone install page server",
          "LAN APK verification",
          "Phone readiness report",
          "Desktop smoke",
          "Desktop package verification",
          "Flutter analyze",
          "Flutter tests",
          "Phone readiness report refresh"
        )) {
        if ($StepLabels -notcontains $RequiredStep) {
          Add-Failure "Release gate report is missing required step: $RequiredStep"
        }
      }
      if ($StepLabels -notcontains "Phone device smoke availability" -and $StepLabels -notcontains "Phone device smoke") {
        Add-Failure "Release gate report is missing required phone device smoke step."
      }
      if ($ReleaseGate.options.api_base_url) {
        if ($StepLabels -notcontains "Cloud API verification") {
          Add-Failure "Release gate report is missing required step: Cloud API verification"
        }
        if ([bool]$ReleaseGate.options.build_cloud_apk) {
          if ([string]$ReleaseGate.options.cloud_apk_mode -ne "release") {
            Add-Failure "Release gate cloud APK mode is not release."
          }
          foreach ($RequiredCloudStep in @(
              "Cloud APK build",
              "Cloud APK verification",
              "Cloud phone readiness report",
              "Permanent cloud deployment status report"
            )) {
            if ($StepLabels -notcontains $RequiredCloudStep) {
              Add-Failure "Release gate report is missing required step: $RequiredCloudStep"
            }
          }
        } else {
          foreach ($RequiredCloudStep in @(
              "Cloud API readiness report",
              "Cloud API deployment status report"
            )) {
            if ($StepLabels -notcontains $RequiredCloudStep) {
              Add-Failure "Release gate report is missing required step: $RequiredCloudStep"
            }
          }
        }
      }
    }
    foreach ($Flag in @("skip_flutter", "skip_desktop_smoke", "skip_fresh_render_venv")) {
      if ([bool]$ReleaseGate.options.$Flag) {
        Add-Failure "Release gate was run with debug skip enabled: $Flag"
      }
    }
    if (-not [bool]$ReleaseGate.summaries.render_smoke.ok) {
      Add-Failure "Release gate Render smoke summary is not OK."
    }
    if (-not [bool]$ReleaseGate.summaries.render_smoke.fresh_venv) {
      Add-Failure "Release gate Render smoke did not use a fresh virtual environment."
    }
    if (-not [bool]$ReleaseGate.summaries.render_smoke.fresh_venv_requirements_ok) {
      Add-Failure "Release gate Render smoke fresh-venv requirements check is not OK."
    }
    if (-not $ReleaseGate.summaries.lan_api_server) {
      Add-Failure "Release gate LAN API server summary is missing."
    } else {
      if (-not [bool]$ReleaseGate.summaries.lan_api_server.healthy) {
        Add-Failure "Release gate LAN API server summary is not healthy."
      }
      if (-not [int]$ReleaseGate.summaries.lan_api_server.port) {
        Add-Failure "Release gate LAN API server summary does not record a port."
      }
      if (-not [string]$ReleaseGate.summaries.lan_api_server.health_url) {
        Add-Failure "Release gate LAN API server summary does not record a health URL."
      }
    }
    foreach ($Flag in @("pc_desktop", "phone_install_download", "render_deploy_package")) {
      if (-not [bool]$ReleaseGate.summaries.phone_readiness.$Flag) {
        Add-Failure "Release gate phone readiness summary flag is false: $Flag"
      }
    }
    if (-not [bool]$ReleaseGate.summaries.phone_readiness.phone_temporary_tunnel) {
      Add-WarningMessage "Release gate temporary tunnel phone readiness is false; temporary tunnel URLs are demo-only and may expire."
    }
    if (-not [bool]$ReleaseGate.summaries.product_acceptance.gate_passed -or [double]$ReleaseGate.summaries.product_acceptance.pass_rate -lt 0.95) {
      Add-Failure "Release gate product acceptance summary is below the 95 percent target."
    }
    Test-EntryMatchesArtifactStatus "report/verity_lens_report.pdf" $ReleaseGate.artifacts.report_pdf "Release gate artifact"
    Test-EntryMatchesArtifactStatus "cloud/verity-lens-render-backend.zip" $ReleaseGate.artifacts.render_backend_zip "Release gate artifact"
    Test-EntryMatchesArtifactStatus "apps/FakeNewsDetector-Windows-Portable.zip" $ReleaseGate.artifacts.desktop_zip "Release gate artifact"
    Test-EntryMatchesArtifactStatus "phone/VerityLens-internet.apk" $ReleaseGate.artifacts.internet_apk "Release gate artifact"
    Test-EntryMatchesArtifactStatus "phone/PHONE_APK_VERIFICATION.json" $ReleaseGate.artifacts.internet_apk_verification "Release gate artifact"
    Test-EntryMatchesArtifactStatus "phone/VerityLens-lan.apk" $ReleaseGate.artifacts.lan_apk "Release gate artifact"
    Test-EntryMatchesArtifactStatus "phone/PHONE_LAN_APK_VERIFICATION.json" $ReleaseGate.artifacts.lan_apk_verification "Release gate artifact"
    Test-EntryMatchesArtifactStatus "phone/PHONE_DEVICE_SMOKE.json" $ReleaseGate.artifacts.device_smoke "Release gate artifact"
    if ($ReleaseGate.artifacts.emulator_smoke -and [bool]$ReleaseGate.artifacts.emulator_smoke.exists) {
      Test-EntryMatchesArtifactStatus "phone/PHONE_EMULATOR_SMOKE.json" $ReleaseGate.artifacts.emulator_smoke "Release gate artifact"
    }
    if ($ReleaseGate.artifacts.cloud_apk -and [bool]$ReleaseGate.artifacts.cloud_apk.exists) {
      Test-EntryMatchesArtifactStatus "phone/VerityLens-cloud.apk" $ReleaseGate.artifacts.cloud_apk "Release gate artifact"
    }
  }

  $InternetApkVerification = Read-EntryJson "phone/PHONE_APK_VERIFICATION.json"
  if ($InternetApkVerification) {
    $InternetTemporaryApiFailureAllowed = (
      $InternetApkVerification.PSObject.Properties.Name -contains "temporary_tunnel_api_failure_allowed" -and
      [bool]$InternetApkVerification.temporary_tunnel_api_failure_allowed -and
      $InternetApkVerification.api -and
      [bool]$InternetApkVerification.api.is_temporary_tunnel
    )
    if (-not [bool]$InternetApkVerification.ok) {
      Add-Failure "Internet APK verification is not OK."
    }
    if (-not [bool]$InternetApkVerification.api.ok) {
      if ($InternetTemporaryApiFailureAllowed) {
        Add-WarningMessage "Internet APK verification API probe is not OK because the temporary tunnel is unavailable; permanent cloud APK verification remains strict."
      } else {
        Add-Failure "Internet APK verification API probe is not OK."
      }
    }
    if ($InternetApkVerification.api -and $InternetApkVerification.api.base_url) {
      $InternetVerificationApiUrl = [string]$InternetApkVerification.api.base_url
      if (-not $InternetVerificationApiUrl.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
        Add-Failure "Internet APK verification API URL is not HTTPS."
      }
    } else {
      Add-Failure "Internet APK verification does not record an API URL."
    }
    if (-not [bool]$InternetApkVerification.embedded_api_url.found) {
      Add-Failure "Internet APK verification did not find the embedded API URL."
    }
    if (-not ($InternetApkVerification.apk -and [string]$InternetApkVerification.apk.expected_mode -eq "release")) {
      Add-Failure "Internet APK verification expected mode is not release."
    }
    if (-not $InternetApkVerification.flutter_source_stamp -or -not [bool]$InternetApkVerification.flutter_source_stamp.sidecar_exists) {
      Add-Failure "Internet APK verification does not include a Flutter source stamp sidecar."
    } elseif (-not [bool]$InternetApkVerification.flutter_source_stamp.matches_current_source) {
      Add-Failure "Internet APK verification Flutter source stamp does not match the current source."
    }
    if (-not $InternetApkVerification.status_file -or -not [bool]$InternetApkVerification.status_file.matches_flutter_source_stamp) {
      Add-Failure "Internet APK verification status file does not match the Flutter source stamp."
    }
    Test-ApkSourceStampEntry "phone/VerityLens-internet-flutter-source-stamp.json" $InternetApkVerification "Internet APK"
    $InternetApkEntry = Get-ZipEntry "phone/VerityLens-internet.apk"
    $VerificationApkSha = ""
    if ($InternetApkVerification.apk -and $InternetApkVerification.apk.sha256) {
      $VerificationApkSha = ([string]$InternetApkVerification.apk.sha256).ToUpperInvariant()
    }
    if (-not $VerificationApkSha) {
      Add-Failure "Internet APK verification does not record the APK SHA256."
    } elseif ($InternetApkEntry) {
      $InternetApkHash = Get-EntryHash $InternetApkEntry
      if ($VerificationApkSha -ne $InternetApkHash) {
        Add-Failure "Internet APK verification SHA256 does not match phone/VerityLens-internet.apk."
      }
    }
  }

  $LanApkVerification = Read-EntryJson "phone/PHONE_LAN_APK_VERIFICATION.json"
  if ($LanApkVerification) {
    if (-not [bool]$LanApkVerification.ok) {
      Add-Failure "LAN APK verification is not OK."
    }
    if (-not [bool]$LanApkVerification.api.ok) {
      Add-Failure "LAN APK verification API probe is not OK."
    }
    if (-not [bool]$LanApkVerification.embedded_api_url.found) {
      Add-Failure "LAN APK verification did not find the embedded API URL."
    }
    if (-not ($LanApkVerification.apk -and [string]$LanApkVerification.apk.expected_mode -eq "release")) {
      Add-Failure "LAN APK verification expected mode is not release."
    }
    if (-not $LanApkVerification.flutter_source_stamp -or -not [bool]$LanApkVerification.flutter_source_stamp.sidecar_exists) {
      Add-Failure "LAN APK verification does not include a Flutter source stamp sidecar."
    } elseif (-not [bool]$LanApkVerification.flutter_source_stamp.matches_current_source) {
      Add-Failure "LAN APK verification Flutter source stamp does not match the current source."
    }
    if (-not $LanApkVerification.status_file -or -not [bool]$LanApkVerification.status_file.matches_flutter_source_stamp) {
      Add-Failure "LAN APK verification status file does not match the Flutter source stamp."
    }
    Test-ApkSourceStampEntry "phone/VerityLens-lan-flutter-source-stamp.json" $LanApkVerification "LAN APK"
  }

  $CloudApkVerification = $null
  if (Get-ZipEntry "phone/PHONE_CLOUD_APK_VERIFICATION.json") {
    $CloudApkVerification = Read-EntryJson "phone/PHONE_CLOUD_APK_VERIFICATION.json"
    if ($CloudApkVerification) {
      if (-not [bool]$CloudApkVerification.ok) {
        Add-Failure "Cloud APK verification is not OK."
      }
      $CloudApiBaseUrl = if ($CloudApkVerification.api -and $CloudApkVerification.api.base_url) {
        ([string]$CloudApkVerification.api.base_url).Trim().TrimEnd("/")
      } else {
        ""
      }
      if (-not $CloudApiBaseUrl) {
        Add-Failure "Cloud APK verification does not record an API URL."
      } else {
        try {
          [void](Assert-PermanentCloudApiUrl -Value $CloudApiBaseUrl -Purpose "Submission cloud APK API")
        } catch {
          Add-Failure "Cloud APK verification API URL is not a permanent public HTTPS cloud URL: $($_.Exception.Message)"
        }
      }
      if (-not ($CloudApkVerification.api -and [bool]$CloudApkVerification.api.ok)) {
        Add-Failure "Cloud APK verification API probe is not OK."
      }
      if ($CloudApkVerification.api -and [bool]$CloudApkVerification.api.is_temporary_tunnel) {
        Add-Failure "Cloud APK verification uses a temporary tunnel API URL."
      }
      if (-not [bool]$CloudApkVerification.embedded_api_url.found) {
        Add-Failure "Cloud APK verification did not find the embedded API URL."
      }
      $CloudEmbeddedExpectedUrl = if ($CloudApkVerification.embedded_api_url -and $CloudApkVerification.embedded_api_url.expected_url) {
        ([string]$CloudApkVerification.embedded_api_url.expected_url).Trim().TrimEnd("/")
      } else {
        ""
      }
      if (-not $CloudEmbeddedExpectedUrl) {
        Add-Failure "Cloud APK verification does not record the expected embedded API URL."
      } elseif ($CloudApiBaseUrl -and $CloudEmbeddedExpectedUrl -ne $CloudApiBaseUrl) {
        Add-Failure "Cloud APK verification embedded API URL does not match the verified API URL."
      }
      if (-not ($CloudApkVerification.apk -and [string]$CloudApkVerification.apk.expected_mode -eq "release")) {
        Add-Failure "Cloud APK verification expected mode is not release."
      }
      if (-not ($CloudApkVerification.status_file -and [bool]$CloudApkVerification.status_file.matches_url)) {
        Add-Failure "Cloud APK verification status file does not match the verified API URL."
      }
      if (-not ($CloudApkVerification.status_file -and [bool]$CloudApkVerification.status_file.matches_mode)) {
        Add-Failure "Cloud APK verification status file does not match release mode."
      }
      if (-not ($CloudApkVerification.status_file -and [bool]$CloudApkVerification.status_file.matches_flutter_source_stamp)) {
        Add-Failure "Cloud APK verification status file does not match the Flutter source stamp."
      }
      if (-not $CloudApkVerification.flutter_source_stamp -or -not [bool]$CloudApkVerification.flutter_source_stamp.sidecar_exists) {
        Add-Failure "Cloud APK verification does not include a Flutter source stamp sidecar."
      } elseif (-not [bool]$CloudApkVerification.flutter_source_stamp.matches_current_source) {
        Add-Failure "Cloud APK verification Flutter source stamp does not match the current source."
      }
      Test-ApkSourceStampEntry "phone/VerityLens-cloud-flutter-source-stamp.json" $CloudApkVerification "Cloud APK"
    }
  }

  $Readiness = Read-EntryJson "phone/phone_readiness.json"
  if ($Readiness) {
    foreach ($Flag in @("pc_desktop", "phone_same_wifi", "render_deploy_package", "phone_install_download")) {
      if (-not [bool]$Readiness.ready.$Flag) {
        Add-Failure "Phone readiness flag is false: $Flag"
      }
    }
    if (-not [bool]$Readiness.ready.phone_temporary_tunnel) {
      Add-WarningMessage "Temporary tunnel phone readiness is false; rebuild or restart the tunnel for a temporary internet demo."
    }
    if (-not [bool]$Readiness.ready.phone_permanent_cloud) {
      Add-WarningMessage "Permanent cloud phone readiness is false until a real Render HTTPS URL and cloud APK are verified."
    }
  }

  $InstallPage = Read-EntryJson "phone/PHONE_INSTALL_PAGE.json"
  if ($InstallPage -and $InstallPage.cloud_apk) {
    $CloudInstall = $InstallPage.cloud_apk
    $CloudInstallDownloadUrl = if ($CloudInstall.download_url) { [string]$CloudInstall.download_url } else { "" }
    $CloudInstallDownloadReady = if ($CloudInstall.PSObject.Properties.Name -contains "download_ready") {
      [bool]$CloudInstall.download_ready
    } else {
      [bool]$CloudInstallDownloadUrl
    }

    if ($CloudInstallDownloadUrl -and -not $CloudInstallDownloadReady) {
      Add-Failure "Phone install page exposes cloud APK download before permanent cloud readiness."
    }
    if ($CloudInstallDownloadReady) {
      if (-not (Get-ZipEntry "phone/VerityLens-cloud.apk")) {
        Add-Failure "Phone install page marks cloud APK download ready, but phone/VerityLens-cloud.apk is missing."
      }
      if (-not ($Readiness -and [bool]$Readiness.ready.phone_permanent_cloud)) {
        Add-Failure "Phone install page marks cloud APK download ready before phone_permanent_cloud is true."
      }
      if (-not ($CloudApkVerification -and [bool]$CloudApkVerification.ok)) {
        Add-Failure "Phone install page marks cloud APK download ready without OK cloud APK verification."
      }
      if (-not ($CloudApkVerification -and $CloudApkVerification.apk -and [string]$CloudApkVerification.apk.expected_mode -eq "release")) {
        Add-Failure "Phone install page marks cloud APK download ready without release cloud APK verification."
      }
      if (-not ($CloudApkVerification -and $CloudApkVerification.flutter_source_stamp -and [bool]$CloudApkVerification.flutter_source_stamp.matches_current_source)) {
        Add-Failure "Phone install page marks cloud APK download ready without a current Flutter source stamp."
      }
    }
  }

  $DeviceSmoke = Read-EntryJson "phone/PHONE_DEVICE_SMOKE.json"
  if ($DeviceSmoke) {
    if (-not [bool]$DeviceSmoke.ok -and -not [bool]$DeviceSmoke.skipped) {
      Add-Failure "Phone device smoke is neither OK nor skipped."
    }
    if ([bool]$DeviceSmoke.ok) {
      $DeviceSmokeApkSha = ""
      if ($DeviceSmoke.apk -and $DeviceSmoke.apk.sha256) {
        $DeviceSmokeApkSha = ([string]$DeviceSmoke.apk.sha256).ToUpperInvariant()
      }
      if (-not $DeviceSmokeApkSha) {
        Add-Failure "Phone device smoke is OK but does not record the APK SHA256."
      } else {
        $MatchingPackagedApk = $false
        foreach ($Candidate in @("phone/VerityLens-cloud.apk", "phone/VerityLens-internet.apk", "phone/VerityLens-lan.apk")) {
          $CandidateEntry = Get-ZipEntry $Candidate
          if ($CandidateEntry -and (Get-EntryHash $CandidateEntry) -eq $DeviceSmokeApkSha) {
            $MatchingPackagedApk = $true
            break
          }
        }
        if (-not $MatchingPackagedApk) {
          Add-Failure "Phone device smoke APK SHA256 does not match any packaged phone APK."
        }
      }
      $DeviceScreenshotEntry = Get-ZipEntry "phone/PHONE_DEVICE_SCREENSHOT.png"
      $DeviceScreenshotSha = ""
      if ($DeviceSmoke.screenshot -and $DeviceSmoke.screenshot.sha256) {
        $DeviceScreenshotSha = ([string]$DeviceSmoke.screenshot.sha256).ToUpperInvariant()
      }
      if (-not ($DeviceSmoke.screenshot -and [bool]$DeviceSmoke.screenshot.captured -and $DeviceScreenshotSha)) {
        Add-Failure "Phone device smoke is OK but does not record a captured screenshot SHA256."
      } elseif (-not $DeviceScreenshotEntry) {
        Add-Failure "Phone device smoke is OK but phone/PHONE_DEVICE_SCREENSHOT.png is missing from the submission bundle."
      } elseif ((Get-EntryHash $DeviceScreenshotEntry) -ne $DeviceScreenshotSha) {
        Add-Failure "Phone device smoke screenshot SHA256 does not match phone/PHONE_DEVICE_SCREENSHOT.png."
      } else {
        $DeviceScreenshotPngInfo = Read-ZipEntryPngInfo $DeviceScreenshotEntry
        $DeviceScreenshotValidPng = (
          $DeviceSmoke.screenshot.PSObject.Properties.Name -contains "valid_png" -and
          [bool]$DeviceSmoke.screenshot.valid_png
        )
        $DeviceScreenshotWidth = if ($DeviceSmoke.screenshot.PSObject.Properties.Name -contains "width") { [int]$DeviceSmoke.screenshot.width } else { 0 }
        $DeviceScreenshotHeight = if ($DeviceSmoke.screenshot.PSObject.Properties.Name -contains "height") { [int]$DeviceSmoke.screenshot.height } else { 0 }
        if (-not $DeviceScreenshotValidPng) {
          Add-Failure "Phone device smoke screenshot is not recorded as a valid PNG."
        }
        if ($DeviceScreenshotWidth -le 0 -or $DeviceScreenshotHeight -le 0) {
          Add-Failure "Phone device smoke screenshot does not record positive PNG dimensions."
        }
        if (-not [bool]$DeviceScreenshotPngInfo.valid_png) {
          Add-Failure "phone/PHONE_DEVICE_SCREENSHOT.png is not a valid PNG screenshot."
        }
        if ($DeviceScreenshotValidPng -and [bool]$DeviceScreenshotPngInfo.valid_png -and (
            $DeviceScreenshotWidth -ne [int]$DeviceScreenshotPngInfo.width -or
            $DeviceScreenshotHeight -ne [int]$DeviceScreenshotPngInfo.height
          )) {
          Add-Failure "Phone device smoke screenshot dimensions do not match phone/PHONE_DEVICE_SCREENSHOT.png."
        }
      }
      if (-not ($DeviceSmoke.PSObject.Properties.Name -contains "require_physical_device") -or -not [bool]$DeviceSmoke.require_physical_device) {
        Add-Failure "Phone device smoke is OK but was not run with -RequirePhysicalDevice."
      }
      if (-not ($DeviceSmoke.PSObject.Properties.Name -contains "selected_device_is_emulator")) {
        Add-Failure "Phone device smoke is OK but does not record whether the selected device is an emulator."
      } elseif ([bool]$DeviceSmoke.selected_device_is_emulator) {
        Add-Failure "Phone device smoke is OK but selected an emulator; final proof requires a physical Android device."
      }
      if (-not $DeviceSmoke.device_identity) {
        Add-Failure "Phone device smoke is OK but does not record physical device identity."
      } else {
        if (-not [bool]$DeviceSmoke.device_identity.recorded) {
          Add-Failure "Phone device smoke physical device identity is incomplete."
        }
        foreach ($RequiredIdentityField in @("manufacturer", "model", "android_version", "sdk", "hardware")) {
          if (-not ([string]$DeviceSmoke.device_identity.$RequiredIdentityField).Trim()) {
            Add-Failure "Phone device smoke physical device identity is missing $RequiredIdentityField."
          }
        }
      }
    }
    if ([bool]$DeviceSmoke.skipped) {
      Add-WarningMessage "Phone device smoke is skipped; run with -RequireDevice -RequirePhysicalDevice on a connected Android phone for final proof."
    }
    if ($Readiness -and $Readiness.phone_device_smoke) {
      $ReadinessDeviceSmokeGenerated = if ($Readiness.phone_device_smoke.generated_at) { [string]$Readiness.phone_device_smoke.generated_at } else { "" }
      $DeviceSmokeGenerated = if ($DeviceSmoke.generated_at) { [string]$DeviceSmoke.generated_at } else { "" }
      $ReadinessDeviceSmokeSha = ""
      $DeviceSmokeSha = ""
      if ($Readiness.phone_device_smoke.apk -and $Readiness.phone_device_smoke.apk.sha256) {
        $ReadinessDeviceSmokeSha = ([string]$Readiness.phone_device_smoke.apk.sha256).ToUpperInvariant()
      }
      if ($DeviceSmoke.apk -and $DeviceSmoke.apk.sha256) {
        $DeviceSmokeSha = ([string]$DeviceSmoke.apk.sha256).ToUpperInvariant()
      }
      if ($ReadinessDeviceSmokeGenerated -and $DeviceSmokeGenerated -and $ReadinessDeviceSmokeGenerated -ne $DeviceSmokeGenerated) {
        Add-Failure "Phone readiness embedded device smoke does not match PHONE_DEVICE_SMOKE.json generated_at."
      }
      if ($ReadinessDeviceSmokeSha -and $DeviceSmokeSha -and $ReadinessDeviceSmokeSha -ne $DeviceSmokeSha) {
        Add-Failure "Phone readiness embedded device smoke SHA256 does not match PHONE_DEVICE_SMOKE.json."
      }
    }
  }

  if (Get-ZipEntry "phone/PHONE_EMULATOR_SMOKE.json") {
    $EmulatorSmoke = Read-EntryJson "phone/PHONE_EMULATOR_SMOKE.json"
    if ($EmulatorSmoke) {
      if (-not [bool]$EmulatorSmoke.ok -and -not [bool]$EmulatorSmoke.skipped) {
        Add-Failure "Phone emulator smoke is neither OK nor skipped."
      }
      if ([bool]$EmulatorSmoke.skipped) {
        Add-WarningMessage "Phone emulator smoke is skipped; run scripts\smoke_phone_emulator.ps1 when an Android AVD is available."
      }
      if ([bool]$EmulatorSmoke.ok -and -not [bool]$EmulatorSmoke.boot_completed) {
        Add-Failure "Phone emulator smoke is OK but boot_completed is false."
      }
      if ([bool]$EmulatorSmoke.ok -and -not [bool]$EmulatorSmoke.device_smoke.ok) {
        Add-Failure "Phone emulator wrapper is OK but nested device smoke is not OK."
      }
      if ([bool]$EmulatorSmoke.ok) {
        $InternetApkEntry = Get-ZipEntry "phone/VerityLens-internet.apk"
        $SmokeApkSha = ""
        if ($EmulatorSmoke.device_smoke -and $EmulatorSmoke.device_smoke.apk -and $EmulatorSmoke.device_smoke.apk.sha256) {
          $SmokeApkSha = ([string]$EmulatorSmoke.device_smoke.apk.sha256).ToUpperInvariant()
        }
        if (-not $SmokeApkSha) {
          Add-Failure "Phone emulator smoke is OK but does not record the APK SHA256."
        } elseif ($InternetApkEntry) {
          $InternetApkHash = Get-EntryHash $InternetApkEntry
          if ($SmokeApkSha -ne $InternetApkHash) {
            Add-Failure "Phone emulator smoke APK SHA256 does not match phone/VerityLens-internet.apk."
          }
        }
        if ($EmulatorSmoke.device_smoke -and $EmulatorSmoke.device_smoke.screenshot -and [bool]$EmulatorSmoke.device_smoke.screenshot.captured) {
          $EmulatorScreenshotEntry = Get-ZipEntry "phone/PHONE_EMULATOR_SCREENSHOT.png"
          $EmulatorScreenshotSha = if ($EmulatorSmoke.device_smoke.screenshot.sha256) { ([string]$EmulatorSmoke.device_smoke.screenshot.sha256).ToUpperInvariant() } else { "" }
          if (-not $EmulatorScreenshotSha) {
            Add-Failure "Phone emulator smoke screenshot is captured but does not record SHA256."
          } elseif (-not $EmulatorScreenshotEntry) {
            Add-Failure "Phone emulator smoke screenshot is missing from the submission bundle."
          } elseif ((Get-EntryHash $EmulatorScreenshotEntry) -ne $EmulatorScreenshotSha) {
            Add-Failure "Phone emulator smoke screenshot SHA256 does not match phone/PHONE_EMULATOR_SCREENSHOT.png."
          }
        }
      }
    }
  }

  $CloudStatus = Read-EntryJson "cloud/CLOUD_DEPLOYMENT_STATUS.json"
  if ($CloudStatus) {
    if ($CloudStatus.outcome -eq "failed") {
      Add-Failure "Cloud deployment status outcome is failed."
    }
    if (-not [bool]$CloudStatus.render_bundle_smoke_ok) {
      Add-Failure "Render bundle smoke is not OK."
    }
    if (-not [bool]$CloudStatus.render_bundle_requirements_ok) {
      Add-Failure "Render bundle fresh-venv requirements check is not OK."
    }
    Test-EntryMatchesArtifactStatus "cloud/verity-lens-render-backend.zip" $CloudStatus.render_bundle "Cloud deployment status"
    Test-EntryMatchesArtifactStatus "cloud/RENDER_BUNDLE_SMOKE.md" $CloudStatus.render_bundle_smoke "Cloud deployment status"
    if ($CloudStatus.cloud_apk -and [bool]$CloudStatus.cloud_apk.exists) {
      Test-EntryMatchesArtifactStatus "phone/VerityLens-cloud.apk" $CloudStatus.cloud_apk "Cloud deployment status"
    }
    if ($CloudStatus.cloud_apk_verification -and [bool]$CloudStatus.cloud_apk_verification.exists) {
      Test-EntryMatchesArtifactStatus "phone/PHONE_CLOUD_APK_VERIFICATION.md" $CloudStatus.cloud_apk_verification "Cloud deployment status"
    }
    if ([bool]$CloudStatus.verification_ok) {
      if (-not ($CloudApkVerification -and [bool]$CloudApkVerification.ok)) {
        Add-Failure "Cloud deployment status says verification OK, but cloud APK verification JSON is not OK."
      }
      if (-not ($CloudApkVerification -and $CloudApkVerification.apk -and [string]$CloudApkVerification.apk.expected_mode -eq "release")) {
        Add-Failure "Cloud deployment status says verification OK, but cloud APK verification is not release mode."
      }
      if (-not ($CloudApkVerification -and $CloudApkVerification.flutter_source_stamp -and [bool]$CloudApkVerification.flutter_source_stamp.matches_current_source)) {
        Add-Failure "Cloud deployment status says verification OK, but cloud APK Flutter source stamp is not current."
      }
    }
    if ([bool]$CloudStatus.readiness_ok) {
      if (-not [bool]$CloudStatus.verification_ok) {
        Add-Failure "Cloud deployment status says readiness OK, but verification OK is false."
      }
      if (-not ($Readiness -and [bool]$Readiness.ready.phone_permanent_cloud)) {
        Add-Failure "Cloud deployment status says readiness OK, but phone_permanent_cloud is false."
      }
    }
    if ($CloudStatus.cloud_apk_verification_status) {
      if ([bool]$CloudStatus.cloud_apk_verification_status.ready_to_publish -and -not [bool]$CloudStatus.verification_ok) {
        Add-Failure "Cloud deployment status records publish-ready cloud APK evidence, but verification_ok is false."
      }
      if ([bool]$CloudStatus.verification_ok -and -not [bool]$CloudStatus.cloud_apk_verification_status.ready_to_publish) {
        Add-Failure "Cloud deployment status says verification OK without publish-ready cloud APK evidence."
      }
      if ([bool]$CloudStatus.cloud_apk_verification_status.ready_to_publish -and -not [bool]$CloudStatus.cloud_apk_verification_status.release_mode) {
        Add-Failure "Cloud deployment status marks cloud APK publish-ready without release mode."
      }
    }
    if ($CloudStatus.outcome -eq "permanent_cloud_phone_ready") {
      if (-not [bool]$CloudStatus.readiness_ok) {
        Add-Failure "Cloud deployment status outcome is permanent_cloud_phone_ready but readiness_ok is false."
      }
      if (-not (Get-ZipEntry "phone/VerityLens-cloud.apk")) {
        Add-Failure "Cloud deployment status outcome is permanent_cloud_phone_ready but cloud APK is missing from ZIP."
      }
      if (-not (Get-ZipEntry "phone/PHONE_CLOUD_APK_VERIFICATION.json")) {
        Add-Failure "Cloud deployment status outcome is permanent_cloud_phone_ready but cloud APK verification JSON is missing from ZIP."
      }
    }
  }

  $SizeMinimums = @{
    "report/verity_lens_report.pdf" = 10000
    "phone/VerityLens-internet.apk" = 1000000
    "phone/VerityLens-lan.apk" = 1000000
    "cloud/verity-lens-render-backend.zip" = 100000
    "source/verity-lens-source.zip" = 100000
  }
  foreach ($Item in $SizeMinimums.GetEnumerator()) {
    $Entry = Get-ZipEntry $Item.Key
    if ($Entry -and $Entry.Length -lt [long]$Item.Value) {
      Add-Failure "Entry is suspiciously small: $($Item.Key)"
    }
  }

  $SourceEntryInfo = Read-NestedZipEntryInfo "source/verity-lens-source.zip"
  $SourceEntries = @($SourceEntryInfo | ForEach-Object { [string]$_.name })
  $SourceEntrySet = New-Object 'System.Collections.Generic.HashSet[string]'
  foreach ($Entry in $SourceEntries) {
    [void]$SourceEntrySet.Add($Entry)
  }
  $ReleaseGateGeneratedAtUtc = $null
  if ($ReleaseGate -and $ReleaseGate.generated_at) {
    try {
      $ReleaseGateGeneratedAtUtc = ConvertTo-UtcDateTime $ReleaseGate.generated_at
    } catch {
      Add-Failure "Release gate generated_at cannot be parsed for freshness check."
    }
  } else {
    Add-Failure "Release gate generated_at is missing for freshness check."
  }
  if ($ReleaseGateGeneratedAtUtc) {
    $StaleGatedSources = @($SourceEntryInfo | Where-Object {
        (Test-GatedSourceEntry -Name ([string]$_.name)) -and
        $_.last_write_time_utc -gt $ReleaseGateGeneratedAtUtc.AddSeconds(1)
      } | ForEach-Object { $_.name })
    if ($StaleGatedSources.Count -gt 0) {
      Add-Failure "Release gate report is older than gated source entries: $($StaleGatedSources -join ', ')"
    }
  }
  foreach ($RequiredSource in @(
    "src/api_factcheck.py",
    "src/factcheck/service.py",
    "scripts/verify_render_deploy_config.py",
    "scripts/path_safety.ps1",
    "scripts/check_final_external_prereqs.ps1",
    "scripts/audit_project_goal_completion.ps1",
    "scripts/run_release_gate.ps1",
    "scripts/write_cloud_deployment_status.ps1",
    "scripts/smoke_phone_emulator.ps1",
    "scripts/smoke_phone_on_device.ps1",
    "scripts/verify_submission_bundle.ps1",
    "scripts/make_submission_bundle.ps1",
    "tests/test_factcheck_core.py",
    "apps/fake_news_detector_flutter/lib/main.dart",
    "docs/report/verity_lens_report.tex",
    "README.md",
    "RUNBOOK.md",
    "render.yaml",
    "Dockerfile",
    "requirements.api.txt"
  )) {
    if (-not $SourceEntrySet.Contains($RequiredSource)) {
      Add-Failure "Source ZIP missing required source entry: $RequiredSource"
    }
  }
  $ForbiddenSource = @($SourceEntries | Where-Object {
    $_ -match '(^|/)(\.venv|outputs|dist|build|archive|__pycache__|\.pytest_cache|\.dart_tool)(/|$)' -or
    $_ -match '(^|/)local\.properties$' -or
    $_ -match '(^|/)GeneratedPluginRegistrant\.[^/]+$' -or
    $_ -eq "docs/report/verity_lens_report.pdf" -or
    $_ -match '^docs/report/[^/]+\.(aux|out|toc|fls|fdb_latexmk|xdv|bbl|blg|nav|snm|vrb)$' -or
    $_ -match '^docs/report/[^/]+\.synctex\.gz$' -or
    $_ -match '\.iml$' -or
    $_ -match '\.log$' -or
    $_ -match '\.pyc$'
  })
  if ($ForbiddenSource.Count -gt 0) {
    Add-Failure "Source ZIP contains generated/local artifacts: $($ForbiddenSource -join ', ')"
  }
} finally {
  $Zip.Dispose()
}

$Result = [ordered]@{
  generated_at = (Get-Date).ToString("o")
  ok = ($Failures.Count -eq 0)
  zip = [ordered]@{
    path = $ZipFile.FullName
    size_bytes = $ZipFile.Length
    sha256 = $ZipHash.Hash
    entry_count = $EntryMap.Count
  }
  source_zip = [ordered]@{
    entry_count = if ($SourceEntries) { $SourceEntries.Count } else { 0 }
    forbidden_count = if ($ForbiddenSource) { $ForbiddenSource.Count } else { 0 }
  }
  permanent_cloud_artifacts_present = ($CloudPresent.Count -eq $CloudOptional.Count)
  final_cloud_phone_submission_report = [ordered]@{
    present = $FinalCloudPhoneSubmissionPresent
    ok = $FinalCloudPhoneSubmissionOk
    status = $FinalCloudPhoneSubmissionStatus
    packaged_only_when_ok = $true
  }
  failures = @($Failures)
  warnings = @($Warnings)
}
$Result | ConvertTo-Json -Depth 8 | Set-Content -Path $OutJsonPath -Encoding UTF8

$Lines = @(
  "# Verity Lens Submission Bundle Verification",
  "",
  "- Generated: ``$($Result.generated_at)``",
  "- OK: ``$($Result.ok)``",
  "- ZIP: ``$($Result.zip.path)``",
  "- ZIP size bytes: ``$($Result.zip.size_bytes)``",
  "- ZIP SHA256: ``$($Result.zip.sha256)``",
  "- ZIP entry count: ``$($Result.zip.entry_count)``",
  "- Source ZIP entry count: ``$($Result.source_zip.entry_count)``",
  "- Source ZIP forbidden count: ``$($Result.source_zip.forbidden_count)``",
  "- Permanent cloud artifacts present: ``$($Result.permanent_cloud_artifacts_present)``",
  "- Final cloud phone submission report status: ``$($Result.final_cloud_phone_submission_report.status)``",
  "",
  "## Failures",
  ""
)
if ($Failures.Count -eq 0) {
  $Lines += "- None"
} else {
  foreach ($Failure in $Failures) {
    $Lines += "- $Failure"
  }
}
$Lines += @("", "## Warnings", "")
if ($Warnings.Count -eq 0) {
  $Lines += "- None"
} else {
  foreach ($Warning in $Warnings) {
    $Lines += "- $Warning"
  }
}
$Lines | Set-Content -Path $OutMarkdownPath -Encoding UTF8

Write-Host "Submission verification JSON: $OutJsonPath" -ForegroundColor Green
Write-Host "Submission verification report: $OutMarkdownPath" -ForegroundColor Green

if (-not $Result.ok) {
  exit 1
}
