[CmdletBinding()]
param(
  [string]$ApiBaseUrl = "",
  [ValidateSet("debug", "release")]
  [string]$Mode = "release",
  [string]$OutputName = "VerityLens-cloud.apk",
  [switch]$SkipBundle
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$CloudDir = Join-Path $ProjectRoot "outputs\cloud_deploy"
$PhoneDir = Join-Path $ProjectRoot "outputs\phone_download"
$StatusMarkdown = Join-Path $CloudDir "CLOUD_DEPLOYMENT_STATUS.md"
$WriteCloudDeploymentStatus = Join-Path $PSScriptRoot "write_cloud_deployment_status.ps1"

. (Join-Path $PSScriptRoot "cloud_url_policy.ps1")
. (Join-Path $PSScriptRoot "path_safety.ps1")
$OutputName = Assert-ApkOutputName -Name $OutputName
$PowerShell = Get-ChildPowerShellCommand

function Normalize-ApiUrl {
  param([string]$Value)
  if (-not $Value.Trim()) {
    return ""
  }
  return Assert-PermanentCloudApiUrl -Value $Value -Purpose "Permanent cloud deploy API"
}

$ApiBaseUrl = Normalize-ApiUrl $ApiBaseUrl

New-Item -ItemType Directory -Force -Path $CloudDir, $PhoneDir | Out-Null

if (-not $SkipBundle) {
  & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "make_render_backend_bundle.ps1")
  if ($LASTEXITCODE -ne 0) {
    throw "Render backend bundle creation failed with exit code $LASTEXITCODE"
  }
}

& $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "smoke_render_backend_bundle.ps1") -FreshVenv
if ($LASTEXITCODE -ne 0) {
  throw "Render backend bundle smoke failed with exit code $LASTEXITCODE"
}

$CloudApkPath = Join-Path $PhoneDir $OutputName
$VerificationJson = Join-Path $PhoneDir "PHONE_CLOUD_APK_VERIFICATION.json"
$VerificationMarkdown = Join-Path $PhoneDir "PHONE_CLOUD_APK_VERIFICATION.md"
$CloudStatusPath = Join-Path $PhoneDir "VerityLens-cloud-status.md"
$Outcome = "awaiting_public_https_backend"
$VerificationOk = $false
$ReadinessOk = $false
$ErrorMessage = ""

try {
  if ($ApiBaseUrl) {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_cloud_api.ps1") -ApiBaseUrl $ApiBaseUrl
    if ($LASTEXITCODE -ne 0) {
      throw "Cloud API verification failed with exit code $LASTEXITCODE"
    }

    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_phone_for_cloud.ps1") `
      -ApiBaseUrl $ApiBaseUrl `
      -Mode $Mode `
      -OutputName $OutputName
    if ($LASTEXITCODE -ne 0) {
      throw "Cloud APK build failed with exit code $LASTEXITCODE"
    }

    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_phone_apk.ps1") `
      -ApkPath $CloudApkPath `
      -ApiBaseUrl $ApiBaseUrl `
      -ExpectedMode $Mode `
      -RequireHttps `
      -PermanentCloud `
      -StatusPath $CloudStatusPath `
      -OutJson $VerificationJson `
      -OutMarkdown $VerificationMarkdown
    if ($LASTEXITCODE -ne 0) {
      throw "Cloud APK verification failed with exit code $LASTEXITCODE"
    }
    $VerificationOk = $true

    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "check_phone_readiness.ps1") `
      -ApiBaseUrl $ApiBaseUrl `
      -RequireCloud
    if ($LASTEXITCODE -ne 0) {
      throw "Cloud phone readiness failed with exit code $LASTEXITCODE"
    }
    $ReadinessOk = $true
    $Outcome = "permanent_cloud_phone_ready"
  }
}
catch {
  $Outcome = "failed"
  $ErrorMessage = $_.Exception.Message
}

$StatusArgs = @(
  "-NoProfile",
  "-ExecutionPolicy",
  "Bypass",
  "-File",
  $WriteCloudDeploymentStatus,
  "-Outcome",
  $Outcome,
  "-OutputName",
  $OutputName,
  "-VerificationOk",
  $VerificationOk,
  "-ReadinessOk",
  $ReadinessOk,
  "-ErrorMessage",
  $ErrorMessage
)
if ($ApiBaseUrl) {
  $StatusArgs += @("-ApiBaseUrl", $ApiBaseUrl)
}
& $PowerShell @StatusArgs
if ($LASTEXITCODE -ne 0) {
  throw "Cloud deployment status report failed with exit code $LASTEXITCODE"
}

Get-Item -LiteralPath $StatusMarkdown | Select-Object FullName, Length, LastWriteTime

if ($Outcome -eq "failed") {
  exit 1
}
