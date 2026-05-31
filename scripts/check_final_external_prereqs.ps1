[CmdletBinding()]
param(
  [string]$ApiBaseUrl = "",
  [string]$PhoneDeviceId = "",
  [string]$AdbPath = "",
  [string]$CloudApkOutputName = "VerityLens-cloud.apk",
  [switch]$AllowEmulator,
  [switch]$RequireReady,
  [string]$OutJson = "reports\final_external_preflight_latest.json",
  [string]$OutMarkdown = "reports\final_external_preflight_latest.md"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "cloud_url_policy.ps1")
. (Join-Path $PSScriptRoot "path_safety.ps1")
$CloudApkOutputName = Assert-ApkOutputName -Name $CloudApkOutputName -Purpose "Cloud APK output name"

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

function Test-HttpJson {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSec = 30,
    [int]$Attempts = 1,
    [int]$RetryDelaySeconds = 2
  )
  $TotalAttempts = [Math]::Max(1, $Attempts)
  $LastError = ""
  for ($Attempt = 1; $Attempt -le $TotalAttempts; $Attempt++) {
    try {
      $Value = Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec
      return [ordered]@{ ok = $true; value = $Value; error = ""; attempts = $Attempt }
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
    [int]$TimeoutSec = 90,
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

function Test-CloudApi {
  param([string]$BaseUrl)

  $Status = [ordered]@{
    requested = [bool]$BaseUrl
    ok = $false
    health = "not_checked"
    health_attempts = 0
    ready = "not_checked"
    ready_attempts = 0
    fake_probe = "not_checked"
    fake_probe_attempts = 0
    error = ""
  }

  if (-not $BaseUrl) {
    $Status.error = "ApiBaseUrl was not provided."
    return $Status
  }

  $Health = Test-HttpJson "$BaseUrl/health" -TimeoutSec 45 -Attempts 3
  $Ready = Test-HttpJson "$BaseUrl/ready" -TimeoutSec 45 -Attempts 3
  $Status.health = if ($Health.ok) { [string]$Health.value.status } else { "failed" }
  $Status.health_attempts = [int]$Health.attempts
  $Status.ready = if ($Ready.ok) { [string]$Ready.value.status } else { "failed" }
  $Status.ready_attempts = [int]$Ready.attempts
  if (-not $Health.ok) {
    $Status.error = "health: $($Health.error)"
    return $Status
  }
  if (-not $Ready.ok) {
    $Status.error = "ready: $($Ready.error)"
    return $Status
  }

  $ProbeResult = Test-FactcheckProbe "$BaseUrl/factcheck" -TimeoutSec 90 -Attempts 3
  $Status.fake_probe_attempts = [int]$ProbeResult.attempts
  if ($ProbeResult.ok) {
    $Probe = $ProbeResult.value
    $Status.fake_probe = "$($Probe.verdict) / $($Probe.confidence)"
    $Status.ok = ($Status.health -eq "ok" -and $Status.ready -eq "ready" -and $Probe.verdict -eq "fake")
    if (-not $Status.ok) {
      $Status.error = "expected health=ok, ready=ready and fake probe verdict=fake"
    }
  } else {
    $Status.fake_probe = "failed"
    $Status.error = "factcheck: $($ProbeResult.error)"
  }

  return $Status
}

function Resolve-Adb {
  param([string]$RequestedPath = "")

  if ($RequestedPath.Trim()) {
    if (
      -not [System.IO.Path]::IsPathRooted($RequestedPath) -and
      $RequestedPath -notmatch "[\\/]"
    ) {
      $RequestedCommand = Get-Command $RequestedPath -ErrorAction SilentlyContinue
      if ($RequestedCommand) {
        return $RequestedCommand.Source
      }
    }
    $Resolved = Resolve-ProjectPath $RequestedPath
    if (Test-Path -LiteralPath $Resolved) {
      return (Resolve-Path -LiteralPath $Resolved).Path
    }
    return $null
  }

  foreach ($Name in @("adb", "adb.exe")) {
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($Command) {
      return $Command.Source
    }
  }
  foreach ($Root in @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, (Join-Path $env:LOCALAPPDATA "Android\Sdk"))) {
    if (-not $Root) {
      continue
    }
    $Candidate = Join-Path $Root "platform-tools\adb.exe"
    if (Test-Path -LiteralPath $Candidate) {
      return (Resolve-Path -LiteralPath $Candidate).Path
    }
  }
  return $null
}

function Invoke-AdbText {
  param(
    [Parameter(Mandatory = $true)][string]$Adb,
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [int]$TimeoutMilliseconds = 30000
  )
  $ProcessInfo = [System.Diagnostics.ProcessStartInfo]::new()
  $ProcessInfo.FileName = $Adb
  foreach ($Argument in $Arguments) {
    [void]$ProcessInfo.ArgumentList.Add($Argument)
  }
  $ProcessInfo.UseShellExecute = $false
  $ProcessInfo.RedirectStandardOutput = $true
  $ProcessInfo.RedirectStandardError = $true
  $ProcessInfo.CreateNoWindow = $true

  $Process = [System.Diagnostics.Process]::new()
  $Process.StartInfo = $ProcessInfo
  try {
    [void]$Process.Start()
    $StdOutTask = $Process.StandardOutput.ReadToEndAsync()
    $StdErrTask = $Process.StandardError.ReadToEndAsync()
    if (-not $Process.WaitForExit($TimeoutMilliseconds)) {
      try { $Process.Kill() } catch {}
      return [ordered]@{
        exit_code = -1
        output = "adb timed out after $TimeoutMilliseconds ms: $($Arguments -join ' ')"
        command = "adb $($Arguments -join ' ')"
      }
    }
    $StdOut = $StdOutTask.GetAwaiter().GetResult()
    $StdErr = $StdErrTask.GetAwaiter().GetResult()
    return [ordered]@{
      exit_code = $Process.ExitCode
      output = (@($StdOut.TrimEnd(), $StdErr.TrimEnd()) | Where-Object { $_ }) -join "`n"
      command = "adb $($Arguments -join ' ')"
    }
  } catch {
    return [ordered]@{
      exit_code = -1
      output = $_.Exception.Message
      command = "adb $($Arguments -join ' ')"
    }
  } finally {
    $Process.Dispose()
  }
}

function Test-EmulatorDevice {
  param(
    [Parameter(Mandatory = $true)][string]$Adb,
    [Parameter(Mandatory = $true)][string]$DeviceId
  )

  if ($DeviceId -match "^emulator-" -or $DeviceId -match "^localhost:") {
    return $true
  }

  $Qemu = Invoke-AdbText -Adb $Adb -Arguments @("-s", $DeviceId, "shell", "getprop", "ro.kernel.qemu")
  if ($Qemu.exit_code -eq 0 -and $Qemu.output.Trim() -eq "1") {
    return $true
  }

  $Hardware = Invoke-AdbText -Adb $Adb -Arguments @("-s", $DeviceId, "shell", "getprop", "ro.hardware")
  if ($Hardware.exit_code -eq 0 -and $Hardware.output.Trim() -match "ranchu|goldfish|qemu") {
    return $true
  }

  return $false
}

function ConvertTo-PowerShellSingleQuotedArgument {
  param([AllowEmptyString()][string]$Value)

  $Escaped = $Value.Replace("'", "''")
  return "'$Escaped'"
}

function New-FinalizerCommand {
  param([Parameter(Mandatory = $true)][string]$ApiUrl)

  $Parts = @(
    ".\scripts\finalize_cloud_phone_submission.ps1",
    "-ApiBaseUrl",
    (ConvertTo-PowerShellSingleQuotedArgument $ApiUrl)
  )
  if ($CloudApkOutputName -ne "VerityLens-cloud.apk") {
    $Parts += @("-CloudApkOutputName", (ConvertTo-PowerShellSingleQuotedArgument $CloudApkOutputName))
  }
  if ($PhoneDeviceId.Trim()) {
    $Parts += @("-PhoneDeviceId", (ConvertTo-PowerShellSingleQuotedArgument $PhoneDeviceId.Trim()))
  }
  if ($AdbPath.Trim()) {
    $Parts += @("-AdbPath", (ConvertTo-PowerShellSingleQuotedArgument $AdbPath.Trim()))
  }
  return ($Parts -join " ")
}

function Read-AndroidDevices {
  param(
    [string]$Adb,
    [string]$RequestedAdbPath = ""
  )

  $Status = [ordered]@{
    adb_requested_path = $RequestedAdbPath
    adb_path = $Adb
    adb_found = [bool]$Adb
    adb_accessible = $false
    adb_devices_command = "adb devices"
    adb_devices_exit_code = $null
    adb_devices_output = ""
    devices = @()
    authorized_devices = @()
    authorized_physical_devices = @()
    unauthorized_devices = @()
    offline_devices = @()
    authorized_emulator_devices = @()
    selected_device_id = ""
    selected_device_authorized = $false
    selected_device_is_emulator = $false
    selected_physical_device_authorized = $false
    requested_device_state = ""
    error = ""
  }

  if (-not $Adb) {
    $Status.error = if ($RequestedAdbPath.Trim()) {
      "Requested ADB path does not exist or is not accessible: $RequestedAdbPath"
    } else {
      "ADB was not found. Install Android SDK platform-tools or set ANDROID_HOME."
    }
    return $Status
  }

  $Raw = Invoke-AdbText -Adb $Adb -Arguments @("devices")
  $Status.adb_devices_command = [string]$Raw.command
  $Status.adb_devices_exit_code = $Raw.exit_code
  $Status.adb_devices_output = [string]$Raw.output
  if ($Raw.exit_code -ne 0) {
    $Status.error = "adb devices failed: $($Raw.output)"
    return $Status
  }
  $Status.adb_accessible = $true

  $Rows = @()
  foreach ($Line in ($Raw.output -split "`r?`n")) {
    if ($Line -match "^([^\s]+)\s+(\S+)$" -and $Matches[1] -ne "List") {
      $DeviceId = $Matches[1]
      $State = $Matches[2]
      $Rows += [ordered]@{
        id = $DeviceId
        state = $State
        is_emulator = if ($State -eq "device") { [bool](Test-EmulatorDevice -Adb $Adb -DeviceId $DeviceId) } else { $false }
      }
    }
  }
  $Status.devices = @($Rows)
  $Authorized = @($Rows | Where-Object { $_.state -eq "device" })
  $AuthorizedPhysical = @($Authorized | Where-Object { -not [bool]$_.is_emulator })
  $AuthorizedEmulators = @($Authorized | Where-Object { [bool]$_.is_emulator })
  $Unauthorized = @($Rows | Where-Object { $_.state -eq "unauthorized" })
  $Offline = @($Rows | Where-Object { $_.state -eq "offline" })
  $Status.authorized_devices = @($Authorized)
  $Status.authorized_physical_devices = @($AuthorizedPhysical)
  $Status.unauthorized_devices = @($Unauthorized)
  $Status.offline_devices = @($Offline)
  $Status.authorized_emulator_devices = @($AuthorizedEmulators)
  $Eligible = if ($AllowEmulator) { @($Authorized) } else { @($AuthorizedPhysical) }
  $RequestedRows = if ($PhoneDeviceId.Trim()) {
    @($Rows | Where-Object { $_.id -eq $PhoneDeviceId.Trim() })
  } else {
    @()
  }
  if ($RequestedRows.Count -gt 0) {
    $Status.requested_device_state = [string]$RequestedRows[0].state
  }
  $Matching = if ($PhoneDeviceId.Trim()) {
    @($Authorized | Where-Object { $_.id -eq $PhoneDeviceId.Trim() })
  } else {
    @($Eligible)
  }
  if ($Matching.Count -gt 0) {
    $Status.selected_device_id = [string]$Matching[0].id
    $Status.selected_device_authorized = $true
    $Status.selected_device_is_emulator = [bool]$Matching[0].is_emulator
    $Status.selected_physical_device_authorized = (-not [bool]$Matching[0].is_emulator)
    if (-not $AllowEmulator -and [bool]$Matching[0].is_emulator) {
      $Status.error = "Selected Android device is an emulator; final physical proof requires a real USB Android device."
      $Status.selected_physical_device_authorized = $false
    }
  } elseif ($PhoneDeviceId.Trim()) {
    if ($RequestedRows.Count -gt 0 -and $Status.requested_device_state -eq "unauthorized") {
      $Status.error = "Requested Android device is connected but unauthorized: $PhoneDeviceId"
    } elseif ($RequestedRows.Count -gt 0 -and $Status.requested_device_state -eq "offline") {
      $Status.error = "Requested Android device is connected but offline: $PhoneDeviceId"
    } elseif ($RequestedRows.Count -gt 0) {
      $Status.error = "Requested Android device is connected but not ready for final proof: $PhoneDeviceId ($($Status.requested_device_state))"
    } else {
      $Status.error = "Requested Android device is not connected, not authorized, or not physical: $PhoneDeviceId"
    }
  } else {
    $Status.error = if ($AllowEmulator) { "No authorized Android device is connected." } else { "No authorized physical USB Android device is connected." }
  }
  return $Status
}

$OutJsonPath = Assert-PathInsideDirectory `
  -Path (Resolve-ProjectPath $OutJson) `
  -Root $ProjectRoot `
  -Message "OutJson must stay inside project: {0}"
$OutMarkdownPath = Assert-PathInsideDirectory `
  -Path (Resolve-ProjectPath $OutMarkdown) `
  -Root $ProjectRoot `
  -Message "OutMarkdown must stay inside project: {0}"

$NormalizedApiBaseUrl = ""
$ApiPolicyOk = $false
$ApiPolicyError = ""
if ($ApiBaseUrl.Trim()) {
  try {
    $NormalizedApiBaseUrl = Assert-PermanentCloudApiUrl -Value $ApiBaseUrl -Purpose "Final external preflight API"
    $ApiPolicyOk = $true
  } catch {
    $ApiPolicyError = $_.Exception.Message
  }
} else {
  $ApiPolicyError = "ApiBaseUrl is required for the final cloud phone submission."
}

$CloudApi = if ($ApiPolicyOk) {
  Test-CloudApi -BaseUrl $NormalizedApiBaseUrl
} else {
  [ordered]@{
    requested = $false
    ok = $false
    health = "not_checked"
    health_attempts = 0
    ready = "not_checked"
    ready_attempts = 0
    fake_probe = "not_checked"
    fake_probe_attempts = 0
    error = $ApiPolicyError
  }
}

$Adb = Resolve-Adb -RequestedPath $AdbPath
$DeviceStatus = Read-AndroidDevices -Adb $Adb -RequestedAdbPath $AdbPath
$PhoneReadiness = Read-JsonFile "outputs\phone_download\phone_readiness.json"
$GoalAudit = Read-JsonFile "reports\goal_completion_audit_latest.json"

$Artifacts = [ordered]@{
  render_backend_zip = Get-FileStatus "outputs\cloud_deploy\verity-lens-render-backend.zip"
  report_pdf = Get-FileStatus "docs\report\verity_lens_report.pdf"
  desktop_zip = Get-FileStatus "dist\FakeNewsDetector-Windows-Portable.zip"
  cloud_apk = Get-FileStatus "outputs\phone_download\$CloudApkOutputName"
  cloud_apk_verification_json = Get-FileStatus "outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json"
  device_smoke_json = Get-FileStatus "outputs\phone_download\PHONE_DEVICE_SMOKE.json"
  device_screenshot = Get-FileStatus "outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png"
}

$FinalEvidenceContract = [ordered]@{
  cloud = @(
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
    "cloud_apk_status_matches_flutter_source_stamp"
  )
  physical_phone = @(
    "phone_device_smoke_ok",
    "phone_device_requires_physical",
    "phone_device_selected_id",
    "phone_device_selected_physical",
    "phone_device_identity_recorded",
    "phone_device_screenshot_captured",
    "phone_device_screenshot_sha256_recorded",
    "phone_device_screenshot_sha256_matches",
    "phone_device_screenshot_valid_png"
  )
  required_reports = @(
    "outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json",
    "outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json",
    "outputs\phone_download\PHONE_DEVICE_SMOKE.json",
    "outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png",
    "outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json",
    "reports\goal_completion_audit_latest.json",
    "reports\final_cloud_phone_submission_latest.json"
  )
}

$ReadyToRunFinalizer = (
  $ApiPolicyOk -and
  [bool]$CloudApi.ok -and
  [bool]$DeviceStatus.adb_found -and
  [bool]$DeviceStatus.adb_accessible -and
  [bool]$DeviceStatus.selected_device_authorized -and
  ([bool]$AllowEmulator -or [bool]$DeviceStatus.selected_physical_device_authorized)
)

$Missing = New-Object System.Collections.Generic.List[string]
if (-not $ApiPolicyOk) { $Missing.Add("real public HTTPS Render API URL") | Out-Null }
if ($ApiPolicyOk -and -not [bool]$CloudApi.ok) { $Missing.Add("verified /health, /ready, and /factcheck on Render API") | Out-Null }
if (-not [bool]$DeviceStatus.adb_found) {
  $Missing.Add("ADB/platform-tools") | Out-Null
} elseif (-not [bool]$DeviceStatus.adb_accessible) {
  $Missing.Add("ADB executable access permission") | Out-Null
} elseif (-not ([bool]$AllowEmulator -or [bool]$DeviceStatus.selected_physical_device_authorized)) {
  $Missing.Add("authorized physical USB Android device") | Out-Null
}

$FinalizerCommand = New-FinalizerCommand -ApiUrl $(if ($NormalizedApiBaseUrl) { $NormalizedApiBaseUrl } else { "https://<render-app>.onrender.com" })

$NextActions = New-Object System.Collections.Generic.List[string]
if (-not $ApiPolicyOk) {
  $NextActions.Add("Deploy the Render backend from render.yaml or outputs\cloud_deploy\verity-lens-render-backend.zip, then rerun this preflight with -ApiBaseUrl https://<render-app>.onrender.com -RequireReady.") | Out-Null
} elseif (-not [bool]$CloudApi.ok) {
  $NextActions.Add("Open the Render dashboard/logs, wait for the service to wake up, and confirm $NormalizedApiBaseUrl/health, /ready, and /factcheck respond before rerunning this preflight.") | Out-Null
}
if (-not [bool]$DeviceStatus.adb_found) {
  if ($AdbPath.Trim()) {
    $NextActions.Add("Fix the requested -AdbPath value or remove it so the script can discover adb.exe from PATH, ANDROID_HOME, ANDROID_SDK_ROOT, or LocalAppData Android SDK.") | Out-Null
  } else {
    $NextActions.Add("Install Android SDK platform-tools or set ANDROID_HOME/ANDROID_SDK_ROOT so adb.exe is discoverable.") | Out-Null
  }
} elseif (-not [bool]$DeviceStatus.adb_accessible) {
  $NextActions.Add("Run this preflight outside the sandbox or fix execution permissions for $($DeviceStatus.adb_path) until adb devices exits with code 0.") | Out-Null
} elseif (-not ([bool]$AllowEmulator -or [bool]$DeviceStatus.selected_physical_device_authorized)) {
  if (@($DeviceStatus.unauthorized_devices).Count -gt 0) {
    $Ids = (@($DeviceStatus.unauthorized_devices) | ForEach-Object { $_.id }) -join ", "
    $NextActions.Add("Authorize Android USB debugging for device(s) ${Ids}: unlock the phone, accept the RSA prompt, then rerun adb devices until the state is device.") | Out-Null
  } elseif (@($DeviceStatus.offline_devices).Count -gt 0) {
    $Ids = (@($DeviceStatus.offline_devices) | ForEach-Object { $_.id }) -join ", "
    $NextActions.Add("Reconnect or restart ADB for offline device(s) ${Ids}: unplug/replug USB, run adb kill-server and adb start-server if needed, then rerun adb devices until the state is device.") | Out-Null
  } elseif (@($DeviceStatus.authorized_devices).Count -gt 0 -and @($DeviceStatus.authorized_physical_devices).Count -eq 0) {
    $Ids = (@($DeviceStatus.authorized_emulator_devices) | ForEach-Object { $_.id }) -join ", "
    $NextActions.Add("Only emulator device(s) are authorized ($Ids). Connect a real Android phone by USB for final physical proof, or pass -AllowEmulator only for local diagnostics.") | Out-Null
  } elseif (@($DeviceStatus.devices).Count -eq 0) {
    $NextActions.Add("No Android devices are listed by adb devices. Connect a real phone by USB, enable USB debugging, accept the RSA prompt, and rerun adb devices until one row shows state device.") | Out-Null
  } else {
    $NextActions.Add("Enable USB debugging on a real Android phone, connect it by USB, accept the RSA prompt, and verify adb devices shows one row with state device.") | Out-Null
  }
}
if ($ReadyToRunFinalizer) {
  $NextActions.Add("Run the final wrapper now: $FinalizerCommand") | Out-Null
} else {
  $NextActions.Add("After the missing items are fixed, run: $FinalizerCommand") | Out-Null
}

$Report = [ordered]@{
  generated_at = (Get-Date).ToString("o")
  ready_to_run_finalizer = $ReadyToRunFinalizer
  allow_emulator = [bool]$AllowEmulator
  require_ready = [bool]$RequireReady
  api = [ordered]@{
    input = $ApiBaseUrl
    normalized = $NormalizedApiBaseUrl
    policy_ok = $ApiPolicyOk
    policy_error = $ApiPolicyError
    cloud_api = $CloudApi
  }
  android = $DeviceStatus
  artifacts = $Artifacts
  final_evidence_contract = $FinalEvidenceContract
  current_readiness = if ($PhoneReadiness) { $PhoneReadiness.ready } else { $null }
  current_goal_audit = [ordered]@{
    exists = [bool]$GoalAudit
    complete = if ($GoalAudit) { [bool]$GoalAudit.complete } else { $false }
    estimated_completion_percent = if ($GoalAudit) { [int]$GoalAudit.estimated_completion_percent } else { 0 }
    remaining = if ($GoalAudit -and $GoalAudit.current_external_gaps) { @($GoalAudit.current_external_gaps) } else { @() }
  }
  missing_to_run_finalizer = @($Missing)
  next_actions = @($NextActions)
  finalizer_command = $FinalizerCommand
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutJsonPath), (Split-Path -Parent $OutMarkdownPath) | Out-Null
$Report | ConvertTo-Json -Depth 10 | Set-Content -Path $OutJsonPath -Encoding UTF8

$AdbDevicesOutput = [string]$Report.android.adb_devices_output
if (-not $AdbDevicesOutput) {
  $AdbDevicesOutput = "(empty)"
}

$Lines = @(
  "# Verity Lens Final External Preflight",
  "",
  "- Generated: ``$($Report.generated_at)``",
  "- Ready to run finalizer: ``$($Report.ready_to_run_finalizer)``",
  "- Allow emulator: ``$($Report.allow_emulator)``",
  "- Require ready: ``$($Report.require_ready)``",
  "- Finalizer command: ``$($Report.finalizer_command)``",
  "",
  "## Render API",
  "",
  "- Input URL: ``$($Report.api.input)``",
  "- Normalized URL: ``$($Report.api.normalized)``",
  "- URL policy OK: ``$($Report.api.policy_ok)``",
  "- URL policy error: ``$($Report.api.policy_error)``",
  "- Cloud API OK: ``$($Report.api.cloud_api.ok)``",
  "- Health: ``$($Report.api.cloud_api.health)``",
  "- Health attempts: ``$($Report.api.cloud_api.health_attempts)``",
  "- Ready: ``$($Report.api.cloud_api.ready)``",
  "- Ready attempts: ``$($Report.api.cloud_api.ready_attempts)``",
  "- Fake probe: ``$($Report.api.cloud_api.fake_probe)``",
  "- Fake probe attempts: ``$($Report.api.cloud_api.fake_probe_attempts)``",
  "- Cloud API error: ``$($Report.api.cloud_api.error)``",
  "",
  "## Android Device",
  "",
  "- ADB found: ``$($Report.android.adb_found)``",
  "- ADB executable accessible: ``$($Report.android.adb_accessible)``",
  "- ADB requested path: ``$($Report.android.adb_requested_path)``",
  "- ADB devices command: ``$($Report.android.adb_devices_command)``",
  "- ADB devices exit code: ``$($Report.android.adb_devices_exit_code)``",
  "- ADB path: ``$($Report.android.adb_path)``",
  "- Requested device: ``$PhoneDeviceId``",
  "- Requested device state: ``$($Report.android.requested_device_state)``",
  "- Selected device: ``$($Report.android.selected_device_id)``",
  "- Selected device authorized: ``$($Report.android.selected_device_authorized)``",
  "- Selected device is emulator: ``$($Report.android.selected_device_is_emulator)``",
  "- Selected physical device authorized: ``$($Report.android.selected_physical_device_authorized)``",
  "- Unauthorized devices: ``$(@($Report.android.unauthorized_devices).Count)``",
  "- Offline devices: ``$(@($Report.android.offline_devices).Count)``",
  "- Authorized emulator devices: ``$(@($Report.android.authorized_emulator_devices).Count)``",
  "- Device error: ``$($Report.android.error)``",
  "",
  "### Raw ADB Devices Output",
  "",
  '```text',
  $AdbDevicesOutput,
  '```',
  "",
  "## Missing To Run Finalizer",
  ""
)
if ($Missing.Count -eq 0) {
  $Lines += "- None"
} else {
  foreach ($Item in $Missing) {
    $Lines += "- $Item"
  }
}
$Lines += @(
  "",
  "## Next Actions",
  ""
)
foreach ($Item in $Report.next_actions) {
  $Lines += "- $Item"
}
$Lines += @(
  "",
  "## Final Evidence Contract",
  "",
  "Cloud fields:"
)
foreach ($Item in $Report.final_evidence_contract.cloud) {
  $Lines += "- ``$Item``"
}
$Lines += @(
  "",
  "Physical phone fields:"
)
foreach ($Item in $Report.final_evidence_contract.physical_phone) {
  $Lines += "- ``$Item``"
}
$Lines += @(
  "",
  "Required final reports:"
)
foreach ($Item in $Report.final_evidence_contract.required_reports) {
  $Lines += "- ``$Item``"
}
$Lines += @(
  "",
  "## Current Goal Audit",
  "",
  "- Exists: ``$($Report.current_goal_audit.exists)``",
  "- Complete: ``$($Report.current_goal_audit.complete)``",
  "- Estimated completion: ``$($Report.current_goal_audit.estimated_completion_percent)%``",
  "- Remaining: ``$(@($Report.current_goal_audit.remaining) -join ', ')``",
  "",
  "## Artifacts",
  "",
  "- Render backend ZIP: ``$($Report.artifacts.render_backend_zip.exists)`` $($Report.artifacts.render_backend_zip.path)",
  "- Cloud APK: ``$($Report.artifacts.cloud_apk.exists)`` $($Report.artifacts.cloud_apk.path)",
  "- Cloud APK verification JSON: ``$($Report.artifacts.cloud_apk_verification_json.exists)`` $($Report.artifacts.cloud_apk_verification_json.path)",
  "- Device smoke JSON: ``$($Report.artifacts.device_smoke_json.exists)`` $($Report.artifacts.device_smoke_json.path)",
  "- Device screenshot: ``$($Report.artifacts.device_screenshot.exists)`` $($Report.artifacts.device_screenshot.path)"
)
$Lines | Set-Content -Path $OutMarkdownPath -Encoding UTF8

Write-Host "Final external preflight JSON: $OutJsonPath" -ForegroundColor Green
Write-Host "Final external preflight report: $OutMarkdownPath" -ForegroundColor Green
if (-not $ReadyToRunFinalizer) {
  Write-Host "Not ready to run finalizer. Missing: $($Missing -join ', ')" -ForegroundColor Yellow
}

if ($RequireReady -and -not $ReadyToRunFinalizer) {
  exit 1
}
