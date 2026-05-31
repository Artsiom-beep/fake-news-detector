[CmdletBinding()]
param(
  [string]$ApiBaseUrl = "",

  [ValidateSet("debug", "release")]
  [string]$CloudApkMode = "release",

  [string]$CloudApkOutputName = "VerityLens-cloud.apk",

  [switch]$SkipFlutter,
  [switch]$SkipDesktopSmoke,
  [switch]$SkipFreshRenderVenv,
  [switch]$BuildCloudApk,
  [switch]$PhoneDeviceSmoke,
  [switch]$RequirePhoneDevice,
  [switch]$RequirePhysicalPhoneDevice,
  [string]$PhoneDeviceApkPath = "outputs\phone_download\VerityLens-internet.apk",
  [string]$PhoneDeviceId = "",
  [string]$AdbPath = "",
  [string]$OutJson = "reports\release_gate_latest.json",
  [string]$OutMarkdown = "reports\release_gate_latest.md"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$FlutterRoot = Join-Path $ProjectRoot "apps\fake_news_detector_flutter"
$BuildReport = Join-Path $ProjectRoot "scripts\build_report.ps1"
$VerifyRenderDeployConfig = Join-Path $ProjectRoot "scripts\verify_render_deploy_config.py"
$MakeRenderBackendBundle = Join-Path $ProjectRoot "scripts\make_render_backend_bundle.ps1"
$SmokeRenderBackendBundle = Join-Path $ProjectRoot "scripts\smoke_render_backend_bundle.ps1"
$WriteCloudDeploymentStatus = Join-Path $ProjectRoot "scripts\write_cloud_deployment_status.ps1"
$VerifyCloudApi = Join-Path $ProjectRoot "scripts\verify_cloud_api.ps1"
$BuildPhoneForCloud = Join-Path $ProjectRoot "scripts\build_phone_for_cloud.ps1"
$PreparePhoneInstallPage = Join-Path $ProjectRoot "scripts\prepare_phone_install_page.ps1"
$CheckPhoneReadiness = Join-Path $ProjectRoot "scripts\check_phone_readiness.ps1"
$VerifyPhoneApk = Join-Path $ProjectRoot "scripts\verify_phone_apk.ps1"
$SmokePhoneOnDevice = Join-Path $ProjectRoot "scripts\smoke_phone_on_device.ps1"
$VerifyDesktopPackage = Join-Path $ProjectRoot "scripts\verify_desktop_package.ps1"
. (Join-Path $ProjectRoot "scripts\cloud_url_policy.ps1")
. (Join-Path $ProjectRoot "scripts\path_safety.ps1")
$CloudApkOutputName = Assert-ApkOutputName -Name $CloudApkOutputName -Purpose "Cloud APK output name"
$PowerShell = Get-ChildPowerShellCommand

$ReportJsonPath = if ([System.IO.Path]::IsPathRooted($OutJson)) {
  [System.IO.Path]::GetFullPath($OutJson)
} else {
  [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutJson))
}
$ReportMarkdownPath = if ([System.IO.Path]::IsPathRooted($OutMarkdown)) {
  [System.IO.Path]::GetFullPath($OutMarkdown)
} else {
  [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutMarkdown))
}
$ReleaseStartedAt = (Get-Date).ToString("o")
$ReleaseSteps = New-Object System.Collections.Generic.List[object]
$ReleaseGateOk = $false
$ReleaseGateError = ""

$CloudUrl = if ($ApiBaseUrl.Trim()) {
  Assert-PermanentCloudApiUrl -Value $ApiBaseUrl -Purpose "Release gate cloud API"
} else {
  ""
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

function Get-ArtifactStatus {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return [ordered]@{
      exists = $false
      path = $Path
      size_bytes = 0
      sha256 = ""
      modified_at = $null
    }
  }
  $Item = Get-Item -LiteralPath $Path
  $Hash = Get-FileHash -LiteralPath $Path -Algorithm SHA256
  return [ordered]@{
    exists = $true
    path = $Item.FullName
    size_bytes = $Item.Length
    sha256 = $Hash.Hash
    modified_at = $Item.LastWriteTime.ToString("o")
  }
}

function Write-ReleaseGateReport {
  param(
    [Parameter(Mandatory = $true)][bool]$Ok,
    [string]$ErrorMessage = ""
  )

  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportJsonPath), (Split-Path -Parent $ReportMarkdownPath) | Out-Null

  $Product = Read-JsonFile (Join-Path $ProjectRoot "reports\product_acceptance_latest.json")
  $ProductSummary = if ($Product -and $Product.summary) { $Product.summary } else { $Product }
  $PhoneReadiness = Read-JsonFile (Join-Path $ProjectRoot "outputs\phone_download\phone_readiness.json")
  $RenderDeployConfig = Read-JsonFile (Join-Path $ProjectRoot "reports\render_deploy_config_latest.json")
  $RenderSmoke = Read-JsonFile (Join-Path $ProjectRoot "outputs\cloud_deploy\render_backend_smoke\RENDER_BUNDLE_SMOKE.json")
  $DesktopPackage = Read-JsonFile (Join-Path $ProjectRoot "outputs\desktop_package\DESKTOP_PACKAGE_VERIFICATION.json")
  $LanApiSummary = Get-LanApiStatus

  $ProductAcceptanceSummary = $null
  if ($ProductSummary) {
    $ProductAcceptanceSummary = $ProductSummary
  }
  $PhoneReadinessSummary = $null
  if ($PhoneReadiness) {
    $PhoneReadinessSummary = $PhoneReadiness.ready
  }
  $RenderSmokeSummary = $null
  $RenderDeployConfigSummary = $null
  if ($RenderDeployConfig) {
    $RenderDeployConfigSummary = [ordered]@{
      ok = [bool]$RenderDeployConfig.ok
      service_name = $RenderDeployConfig.render.service_name
      runtime = $RenderDeployConfig.render.runtime
      dockerfile_path = $RenderDeployConfig.render.dockerfilePath
      health_check_path = $RenderDeployConfig.render.healthCheckPath
      failures = @($RenderDeployConfig.failures)
    }
  }
  if ($RenderSmoke) {
    $RenderSmokeSummary = [ordered]@{
      ok = [bool]$RenderSmoke.ok
      fresh_venv = [bool]$RenderSmoke.fresh_venv.requested
      fresh_venv_requirements_ok = [bool]$RenderSmoke.fresh_venv.install_ok
      health = $RenderSmoke.health
      ready = $RenderSmoke.ready
      fake_probe = $RenderSmoke.fake_probe
    }
  }
  $DesktopPackageSummary = $null
  if ($DesktopPackage) {
    $DesktopPackageSummary = $DesktopPackage
  }
  $RecordedSteps = @($ReleaseSteps | ForEach-Object { $_ })

  $Report = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    started_at = $ReleaseStartedAt
    ok = $Ok
    error = $ErrorMessage
    project_root = $ProjectRoot
    options = [ordered]@{
      api_base_url = $CloudUrl
      build_cloud_apk = [bool]$BuildCloudApk
      cloud_apk_mode = $CloudApkMode
      cloud_apk_output_name = $CloudApkOutputName
      skip_flutter = [bool]$SkipFlutter
      skip_desktop_smoke = [bool]$SkipDesktopSmoke
      skip_fresh_render_venv = [bool]$SkipFreshRenderVenv
      phone_device_smoke = [bool]$PhoneDeviceSmoke
      require_phone_device = [bool]$RequirePhoneDevice
      require_physical_phone_device = [bool]$RequirePhysicalPhoneDevice
      phone_device_apk_path = $PhoneDeviceApkPath
      phone_device_id = $PhoneDeviceId
      adb_path = $AdbPath
    }
    steps = $RecordedSteps
    summaries = [ordered]@{
      product_acceptance = $ProductAcceptanceSummary
      phone_readiness = $PhoneReadinessSummary
      lan_api_server = $LanApiSummary
      render_deploy_config = $RenderDeployConfigSummary
      render_smoke = $RenderSmokeSummary
      desktop_package = $DesktopPackageSummary
    }
    artifacts = [ordered]@{
      report_pdf = Get-ArtifactStatus (Join-Path $ProjectRoot "docs\report\verity_lens_report.pdf")
      render_deploy_config = Get-ArtifactStatus (Join-Path $ProjectRoot "reports\render_deploy_config_latest.json")
      render_backend_zip = Get-ArtifactStatus (Join-Path $ProjectRoot "outputs\cloud_deploy\verity-lens-render-backend.zip")
      desktop_zip = Get-ArtifactStatus (Join-Path $ProjectRoot "dist\FakeNewsDetector-Windows-Portable.zip")
      internet_apk = Get-ArtifactStatus (Join-Path $ProjectRoot "outputs\phone_download\VerityLens-internet.apk")
      internet_apk_verification = Get-ArtifactStatus (Join-Path $ProjectRoot "outputs\phone_download\PHONE_APK_VERIFICATION.json")
      lan_apk = Get-ArtifactStatus (Join-Path $ProjectRoot "outputs\phone_download\VerityLens-lan.apk")
      lan_apk_verification = Get-ArtifactStatus (Join-Path $ProjectRoot "outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json")
      device_smoke = Get-ArtifactStatus (Join-Path $ProjectRoot "outputs\phone_download\PHONE_DEVICE_SMOKE.json")
      emulator_smoke = Get-ArtifactStatus (Join-Path $ProjectRoot "outputs\phone_download\PHONE_EMULATOR_SMOKE.json")
      cloud_apk = Get-ArtifactStatus (Join-Path $ProjectRoot "outputs\phone_download\VerityLens-cloud.apk")
    }
  }

  $Report | ConvertTo-Json -Depth 12 | Set-Content -Path $ReportJsonPath -Encoding UTF8

  $ProductAcceptanceText = if ($ProductSummary) {
    "$($ProductSummary.passed)/$($ProductSummary.total)"
  } else {
    "not available"
  }
  $RenderSmokeOkText = if ($RenderSmoke) { [string]([bool]$RenderSmoke.ok) } else { "not available" }
  $RenderDeployConfigOkText = if ($RenderDeployConfig) { [string]([bool]$RenderDeployConfig.ok) } else { "not available" }
  $FreshRenderRequirementsText = if ($RenderSmoke) { [string]([bool]$RenderSmoke.fresh_venv.install_ok) } else { "not available" }
  $PhoneInstallDownloadText = if ($PhoneReadiness) { [string]([bool]$PhoneReadiness.ready.phone_install_download) } else { "not available" }
  $PhoneTemporaryTunnelText = if ($PhoneReadiness) { [string]([bool]$PhoneReadiness.ready.phone_temporary_tunnel) } else { "not available" }
  $PhonePermanentCloudText = if ($PhoneReadiness) { [string]([bool]$PhoneReadiness.ready.phone_permanent_cloud) } else { "not available" }
  $LanApiText = "$($LanApiSummary.health_url) healthy=$($LanApiSummary.healthy) pid=$($LanApiSummary.pid)"

  $Lines = @(
    "# Verity Lens Release Gate",
    "",
    "- Generated: ``$($Report.generated_at)``",
    "- Started: ``$($Report.started_at)``",
    "- OK: ``$($Report.ok)``",
    "- Error: ``$($Report.error)``",
    "- Skip Flutter: ``$($Report.options.skip_flutter)``",
    "- Skip desktop smoke: ``$($Report.options.skip_desktop_smoke)``",
    "- Skip fresh Render venv: ``$($Report.options.skip_fresh_render_venv)``",
    "- Build cloud APK: ``$($Report.options.build_cloud_apk)``",
    "- Phone device smoke: ``$($Report.options.phone_device_smoke)``",
    "- Require phone device: ``$($Report.options.require_phone_device)``",
    "",
    "## Steps",
    ""
  )
  foreach ($Step in $ReleaseSteps) {
    $Lines += "- ``$($Step.status)`` $($Step.label) ($($Step.duration_seconds)s, exit=$($Step.exit_code))"
    if ($Step.error) {
      $Lines += "  - Error: $($Step.error)"
    }
  }
  $Lines += @(
    "",
    "## Summaries",
    "",
    "- Product acceptance: ``$ProductAcceptanceText``",
    "- Render deploy config OK: ``$RenderDeployConfigOkText``",
    "- Render smoke OK: ``$RenderSmokeOkText``",
    "- Fresh Render requirements OK: ``$FreshRenderRequirementsText``",
    "- LAN API server: ``$LanApiText``",
    "- Phone install/download: ``$PhoneInstallDownloadText``",
    "- Temporary tunnel phone: ``$PhoneTemporaryTunnelText``",
    "- Permanent cloud phone: ``$PhonePermanentCloudText``"
  )
  $Lines | Set-Content -Path $ReportMarkdownPath -Encoding UTF8
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
  $ReleaseSteps.Add($Step) | Out-Null
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

function Get-LanApiPort {
  $UrlPath = Join-Path $ProjectRoot "outputs\phone_download\VerityLens-lan-api-url.txt"
  if (Test-Path -LiteralPath $UrlPath) {
    $Url = (Get-Content -LiteralPath $UrlPath -Raw).Trim()
    $Uri = $null
    if ([System.Uri]::TryCreate($Url, [System.UriKind]::Absolute, [ref]$Uri) -and $Uri.Port -gt 0) {
      return [int]$Uri.Port
    }
  }
  return 8001
}

function Test-LocalLanApi {
  param([Parameter(Mandatory = $true)][int]$Port)
  try {
    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
    return [string]$Health.status -eq "ok"
  } catch {
    return $false
  }
}

function Get-LanApiStatus {
  $Port = Get-LanApiPort
  $PidPath = Join-Path $ProjectRoot "outputs\phone-lan-api-release-gate-pid.txt"
  $StdoutLog = Join-Path $ProjectRoot "outputs\phone-lan-api-release-gate.log"
  $StderrLog = Join-Path $ProjectRoot "outputs\phone-lan-api-release-gate.err.log"
  $ProcessId = 0
  $ProcessRunning = $false
  if (Test-Path -LiteralPath $PidPath) {
    $PidText = (Get-Content -LiteralPath $PidPath -Raw).Trim()
    if ([int]::TryParse($PidText, [ref]$ProcessId) -and $ProcessId -gt 0) {
      $ProcessRunning = [bool](Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
    }
  }

  return [ordered]@{
    port = $Port
    health_url = "http://127.0.0.1:$Port/health"
    healthy = [bool](Test-LocalLanApi -Port $Port)
    pid_path = $PidPath
    pid = $ProcessId
    pid_running = $ProcessRunning
    stdout_log = $StdoutLog
    stderr_log = $StderrLog
  }
}

function Ensure-LanApiServer {
  $Port = Get-LanApiPort
  if (Test-LocalLanApi -Port $Port) {
    Write-Host "LAN API already healthy on http://127.0.0.1:$Port/health" -ForegroundColor Green
    return
  }

  $OutputsDir = Join-Path $ProjectRoot "outputs"
  New-Item -ItemType Directory -Force -Path $OutputsDir | Out-Null
  $Process = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "src.api_factcheck:app", "--host", "0.0.0.0", "--port", "$Port") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput (Join-Path $OutputsDir "phone-lan-api-release-gate.log") `
    -RedirectStandardError (Join-Path $OutputsDir "phone-lan-api-release-gate.err.log") `
    -WindowStyle Hidden `
    -PassThru
  Set-Content -Path (Join-Path $OutputsDir "phone-lan-api-release-gate-pid.txt") -Value $Process.Id -Encoding UTF8

  for ($Attempt = 1; $Attempt -le 30; $Attempt++) {
    Start-Sleep -Seconds 1
    if (Test-LocalLanApi -Port $Port) {
      Write-Host "LAN API started on http://127.0.0.1:$Port/health" -ForegroundColor Green
      return
    }
    if ($Process.HasExited) {
      throw "LAN API process exited before becoming healthy. See outputs\phone-lan-api-release-gate.err.log."
    }
  }

  throw "LAN API did not become healthy on http://127.0.0.1:$Port/health"
}

Push-Location $ProjectRoot
try {
  Invoke-Step "Check Python" {
    & $Python --version
  }

  Invoke-Step "Python syntax" {
    & $Python -m py_compile `
      src\api.py `
      src\api_factcheck.py `
      src\predict.py `
      src\predict_factcheck.py `
      src\ui.py `
      src\desktop_app.py `
      src\factcheck\service.py `
      scripts\verify_render_deploy_config.py `
      scripts\run_product_acceptance.py
  }

  Invoke-Step "Backend unit and integration tests" {
    & $Python -m unittest discover -s tests -v
  }

  Invoke-Step "Product acceptance gate" {
    & $Python scripts\run_product_acceptance.py
  }

  Invoke-Step "University report PDF" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $BuildReport -BootstrapTectonic
  }

  Invoke-Step "Render deploy config verification" {
    & $Python scripts\verify_render_deploy_config.py
  }

  Invoke-Step "Render backend bundle" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $MakeRenderBackendBundle
  }

  Invoke-Step "Render backend bundle smoke" {
    $SmokeArgs = @(
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      $SmokeRenderBackendBundle
    )
    if (-not $SkipFreshRenderVenv) {
      $SmokeArgs += "-FreshVenv"
    }
    & $PowerShell @SmokeArgs
  }

  Invoke-Step "Cloud deployment status report" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $WriteCloudDeploymentStatus
  }

  Invoke-Step "Internet APK verification" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $VerifyPhoneApk `
      -ApkPath (Join-Path $ProjectRoot "outputs\phone_download\VerityLens-internet.apk") `
      -ExpectedMode release `
      -RequireHttps `
      -AllowTemporaryTunnelApiFailure `
      -StatusPath (Join-Path $ProjectRoot "outputs\phone_download\PHONE_BUILD_STATUS.md") `
      -OutJson (Join-Path $ProjectRoot "outputs\phone_download\PHONE_APK_VERIFICATION.json") `
      -OutMarkdown (Join-Path $ProjectRoot "outputs\phone_download\PHONE_APK_VERIFICATION.md")
  }

  Invoke-Step "Phone install page server" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $PreparePhoneInstallPage -StartServer
  }

  Invoke-Step "LAN API server" {
    Ensure-LanApiServer
  }

  Invoke-Step "LAN APK verification" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $VerifyPhoneApk `
      -ApkPath (Join-Path $ProjectRoot "outputs\phone_download\VerityLens-lan.apk") `
      -ExpectedMode release `
      -StatusPath (Join-Path $ProjectRoot "outputs\phone_download\VerityLens-lan-status.md") `
      -OutJson (Join-Path $ProjectRoot "outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json") `
      -OutMarkdown (Join-Path $ProjectRoot "outputs\phone_download\PHONE_LAN_APK_VERIFICATION.md")
  }

  Invoke-Step "Phone readiness report" {
    & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $CheckPhoneReadiness
  }

  if (-not $SkipDesktopSmoke) {
    Invoke-Step "Desktop smoke" {
      & $Python -m src.desktop_app --smoke --port 0
    }

    Invoke-Step "Desktop package verification" {
      & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $VerifyDesktopPackage
    }
  }

  if (-not $SkipFlutter) {
    if (-not (Test-Path $FlutterRoot)) {
      throw "Flutter project not found: $FlutterRoot"
    }

    Push-Location $FlutterRoot
    try {
      Invoke-Step "Flutter analyze" {
        & flutter analyze
      }

      Invoke-Step "Flutter tests" {
        & flutter test
      }
    }
    finally {
      Pop-Location
    }
  }

  if ($CloudUrl) {
    Invoke-Step "Cloud API verification" {
      & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $VerifyCloudApi -ApiBaseUrl $CloudUrl
    }

    if ($BuildCloudApk) {
      Invoke-Step "Cloud APK build" {
        & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $BuildPhoneForCloud `
          -ApiBaseUrl $CloudUrl `
          -Mode $CloudApkMode `
          -OutputName $CloudApkOutputName
      }

      Invoke-Step "Cloud APK verification" {
        & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $VerifyPhoneApk `
          -ApkPath (Join-Path $ProjectRoot "outputs\phone_download\$CloudApkOutputName") `
          -ApiBaseUrl $CloudUrl `
          -ExpectedMode $CloudApkMode `
          -RequireHttps `
          -PermanentCloud `
          -StatusPath (Join-Path $ProjectRoot "outputs\phone_download\VerityLens-cloud-status.md") `
          -OutJson (Join-Path $ProjectRoot "outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json") `
          -OutMarkdown (Join-Path $ProjectRoot "outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.md")
      }

      Invoke-Step "Cloud phone readiness report" {
        & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $CheckPhoneReadiness `
          -ApiBaseUrl $CloudUrl `
          -RequireCloud
      }

      Invoke-Step "Permanent cloud deployment status report" {
        & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $WriteCloudDeploymentStatus `
          -ApiBaseUrl $CloudUrl `
          -Outcome "permanent_cloud_phone_ready" `
          -OutputName $CloudApkOutputName `
          -VerificationOk $true `
          -ReadinessOk $true
      }
    }
    else {
      Invoke-Step "Cloud API readiness report" {
        & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $CheckPhoneReadiness -ApiBaseUrl $CloudUrl
      }

      Invoke-Step "Cloud API deployment status report" {
        & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $WriteCloudDeploymentStatus `
          -ApiBaseUrl $CloudUrl `
          -Outcome "permanent_cloud_api_verified"
      }
    }
  }
  elseif ($BuildCloudApk) {
    throw "Pass -ApiBaseUrl https://<render-app>.onrender.com when using -BuildCloudApk."
  }

  if (-not ($PhoneDeviceSmoke -or $RequirePhoneDevice)) {
    $ExistingDeviceSmoke = Read-JsonFile (Join-Path $ProjectRoot "outputs\phone_download\PHONE_DEVICE_SMOKE.json")
    if (-not ($ExistingDeviceSmoke -and [bool]$ExistingDeviceSmoke.ok)) {
      Invoke-Step "Phone device smoke availability" {
        & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $SmokePhoneOnDevice `
          -ApkPath $PhoneDeviceApkPath
      }
    }
  }

  if ($PhoneDeviceSmoke -or $RequirePhoneDevice) {
    Invoke-Step "Phone device smoke" {
      $DeviceSmokeArgs = @(
        "-ApkPath", $PhoneDeviceApkPath
      )
      if ($PhoneDeviceId.Trim()) {
        $DeviceSmokeArgs += @("-DeviceId", $PhoneDeviceId)
      }
      if ($AdbPath.Trim()) {
        $DeviceSmokeArgs += @("-AdbPath", $AdbPath)
      }
      if ($RequirePhoneDevice) {
        $DeviceSmokeArgs += "-RequireDevice"
      }
      if ($RequirePhysicalPhoneDevice) {
        $DeviceSmokeArgs += "-RequirePhysicalDevice"
      }
      & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $SmokePhoneOnDevice @DeviceSmokeArgs
    }
  }

  Invoke-Step "Phone readiness report refresh" {
    if ($CloudUrl -and $BuildCloudApk) {
      & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $CheckPhoneReadiness `
        -ApiBaseUrl $CloudUrl `
        -RequireCloud
    }
    elseif ($CloudUrl) {
      & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $CheckPhoneReadiness `
        -ApiBaseUrl $CloudUrl
    }
    else {
      & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $CheckPhoneReadiness
    }
  }

  Write-Host ""
  Write-Host "Release gate passed." -ForegroundColor Green
  $ReleaseGateOk = $true
} catch {
  $ReleaseGateError = $_.Exception.Message
  throw
}
finally {
  try {
    Write-ReleaseGateReport -Ok $ReleaseGateOk -ErrorMessage $ReleaseGateError
  } catch {
    Write-Warning "Failed to write release gate report: $($_.Exception.Message) $($_.ScriptStackTrace)"
  } finally {
    Pop-Location
  }
}
