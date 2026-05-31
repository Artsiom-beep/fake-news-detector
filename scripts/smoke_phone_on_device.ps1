[CmdletBinding()]
param(
  [string]$ApkPath = "outputs\phone_download\VerityLens-internet.apk",
  [string]$PackageId = "app.veritylens.mobile",
  [string]$LaunchActivity = ".MainActivity",
  [string]$DeviceId = "",
  [string]$AdbPath = "",
  [switch]$RequireDevice,
  [switch]$RequirePhysicalDevice,
  [switch]$SkipInstall,
  [string]$ScreenshotPath = "outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png",
  [string]$OutJson = "outputs\phone_download\PHONE_DEVICE_SMOKE.json",
  [string]$OutMarkdown = "outputs\phone_download\PHONE_DEVICE_SMOKE.md"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Resolve-ProjectPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  if ([System.IO.Path]::IsPathRooted($Path)) {
    return $Path
  }
  return (Join-Path $ProjectRoot $Path)
}

function Resolve-Adb {
  param([string]$RequestedPath)

  if ($RequestedPath.Trim()) {
    $Resolved = Resolve-ProjectPath $RequestedPath
    if (Test-Path $Resolved) {
      return (Resolve-Path $Resolved).Path
    }
    throw "ADB path does not exist: $Resolved"
  }

  foreach ($Name in @("adb", "adb.exe")) {
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($Command) {
      return $Command.Source
    }
  }

  $Candidates = @()
  foreach ($Root in @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, (Join-Path $env:LOCALAPPDATA "Android\Sdk"))) {
    if ($Root) {
      $Candidates += (Join-Path $Root "platform-tools\adb.exe")
    }
  }

  foreach ($Candidate in $Candidates) {
    if ($Candidate -and (Test-Path $Candidate)) {
      return (Resolve-Path $Candidate).Path
    }
  }

  return $null
}

function Invoke-Adb {
  param(
    [Parameter(Mandatory = $true)][string]$Adb,
    [string]$SelectedDevice = "",
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [int]$TimeoutMilliseconds = 30000
  )

  $FullArgs = @()
  if ($SelectedDevice.Trim()) {
    $FullArgs += @("-s", $SelectedDevice)
  }
  $FullArgs += $Arguments

  $ProcessInfo = [System.Diagnostics.ProcessStartInfo]::new()
  $ProcessInfo.FileName = $Adb
  foreach ($Argument in $FullArgs) {
    [void]$ProcessInfo.ArgumentList.Add($Argument)
  }
  $ProcessInfo.UseShellExecute = $false
  $ProcessInfo.RedirectStandardOutput = $true
  $ProcessInfo.RedirectStandardError = $true
  $ProcessInfo.CreateNoWindow = $true

  $Process = [System.Diagnostics.Process]::new()
  $Process.StartInfo = $ProcessInfo
  $CommandText = "adb $($FullArgs -join ' ')"
  try {
    [void]$Process.Start()
    $StdOutTask = $Process.StandardOutput.ReadToEndAsync()
    $StdErrTask = $Process.StandardError.ReadToEndAsync()
    if (-not $Process.WaitForExit($TimeoutMilliseconds)) {
      try { $Process.Kill() } catch {}
      return [ordered]@{
        exit_code = -1
        output = "adb timed out after $TimeoutMilliseconds ms: $($FullArgs -join ' ')"
        command = $CommandText
      }
    }
    $StdOut = $StdOutTask.GetAwaiter().GetResult()
    $StdErr = $StdErrTask.GetAwaiter().GetResult()
    return [ordered]@{
      exit_code = $Process.ExitCode
      output = (@($StdOut.TrimEnd(), $StdErr.TrimEnd()) | Where-Object { $_ }) -join "`n"
      command = $CommandText
    }
  } catch {
    return [ordered]@{
      exit_code = -1
      output = $_.Exception.Message
      command = $CommandText
    }
  } finally {
    $Process.Dispose()
  }
}

function Invoke-AdbBinaryToFile {
  param(
    [Parameter(Mandatory = $true)][string]$Adb,
    [string]$SelectedDevice = "",
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [int]$TimeoutMilliseconds = 30000
  )

  $FullArgs = @()
  if ($SelectedDevice.Trim()) {
    $FullArgs += @("-s", $SelectedDevice)
  }
  $FullArgs += $Arguments

  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
  if (Test-Path $OutputPath) {
    Remove-Item -LiteralPath $OutputPath -Force
  }

  $Psi = [System.Diagnostics.ProcessStartInfo]::new()
  $Psi.FileName = $Adb
  foreach ($Argument in $FullArgs) {
    [void]$Psi.ArgumentList.Add($Argument)
  }
  $Psi.UseShellExecute = $false
  $Psi.RedirectStandardOutput = $true
  $Psi.RedirectStandardError = $true
  $Psi.CreateNoWindow = $true

  $Process = [System.Diagnostics.Process]::new()
  $Process.StartInfo = $Psi
  $Started = $false
  $FileStream = $null
  $CopyTask = $null
  $ErrorTask = $null
  try {
    $Started = $Process.Start()
    if (-not $Started) {
      throw "Failed to start adb process for binary output."
    }

    $FileStream = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
    $CopyTask = $Process.StandardOutput.BaseStream.CopyToAsync($FileStream)
    $ErrorTask = $Process.StandardError.ReadToEndAsync()

    if (-not $Process.WaitForExit($TimeoutMilliseconds)) {
      try { $Process.Kill() } catch {}
      return [ordered]@{
        exit_code = -1
        output = "adb timed out after $TimeoutMilliseconds ms: $($FullArgs -join ' ')"
        command = "adb $($FullArgs -join ' ') > $OutputPath"
      }
    }
    if ($CopyTask) {
      $CopyTask.GetAwaiter().GetResult()
    }
    $ErrorOutput = if ($ErrorTask) { $ErrorTask.GetAwaiter().GetResult() } else { "" }

    return [ordered]@{
      exit_code = $Process.ExitCode
      output = $ErrorOutput
      command = "adb $($FullArgs -join ' ') > $OutputPath"
    }
  } catch {
    return [ordered]@{
      exit_code = -1
      output = $_.Exception.Message
      command = "adb $($FullArgs -join ' ') > $OutputPath"
    }
  } finally {
    if ($FileStream) {
      $FileStream.Dispose()
    }
    $Process.Dispose()
  }
}

function Read-Devices {
  param([Parameter(Mandatory = $true)][string]$Adb)

  $Raw = Invoke-Adb -Adb $Adb -Arguments @("devices")
  $Rows = @()
  foreach ($Line in ($Raw.output -split "`r?`n")) {
    if ($Line -match "^([^\s]+)\s+(\S+)$" -and $Matches[1] -ne "List") {
      $Rows += [ordered]@{
        id = $Matches[1]
        state = $Matches[2]
      }
    }
  }
  return [ordered]@{
    command = $Raw.command
    exit_code = $Raw.exit_code
    output = $Raw.output
    devices = $Rows
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

  $Qemu = Invoke-Adb -Adb $Adb -SelectedDevice $DeviceId -Arguments @("shell", "getprop", "ro.kernel.qemu")
  if ($Qemu.exit_code -eq 0 -and $Qemu.output.Trim() -eq "1") {
    return $true
  }

  $Hardware = Invoke-Adb -Adb $Adb -SelectedDevice $DeviceId -Arguments @("shell", "getprop", "ro.hardware")
  if ($Hardware.exit_code -eq 0 -and $Hardware.output.Trim() -match "ranchu|goldfish|qemu") {
    return $true
  }

  return $false
}

function Get-DeviceProperty {
  param(
    [Parameter(Mandatory = $true)][string]$Adb,
    [Parameter(Mandatory = $true)][string]$DeviceId,
    [Parameter(Mandatory = $true)][string]$Name
  )

  $Value = Invoke-Adb -Adb $Adb -SelectedDevice $DeviceId -Arguments @("shell", "getprop", $Name)
  if ($Value.exit_code -ne 0) {
    return ""
  }
  return ([string]$Value.output).Trim()
}

function Get-DeviceIdentity {
  param(
    [Parameter(Mandatory = $true)][string]$Adb,
    [Parameter(Mandatory = $true)][string]$DeviceId
  )

  $Identity = [ordered]@{
    attempted = $true
    manufacturer = Get-DeviceProperty -Adb $Adb -DeviceId $DeviceId -Name "ro.product.manufacturer"
    model = Get-DeviceProperty -Adb $Adb -DeviceId $DeviceId -Name "ro.product.model"
    product = Get-DeviceProperty -Adb $Adb -DeviceId $DeviceId -Name "ro.product.name"
    device = Get-DeviceProperty -Adb $Adb -DeviceId $DeviceId -Name "ro.product.device"
    android_version = Get-DeviceProperty -Adb $Adb -DeviceId $DeviceId -Name "ro.build.version.release"
    sdk = Get-DeviceProperty -Adb $Adb -DeviceId $DeviceId -Name "ro.build.version.sdk"
    hardware = Get-DeviceProperty -Adb $Adb -DeviceId $DeviceId -Name "ro.hardware"
    qemu = Get-DeviceProperty -Adb $Adb -DeviceId $DeviceId -Name "ro.kernel.qemu"
    serial_no = Get-DeviceProperty -Adb $Adb -DeviceId $DeviceId -Name "ro.serialno"
    recorded = $false
  }
  $Identity.recorded = (
    (([string]$Identity.manufacturer).Trim().Length -gt 0) -and
    (([string]$Identity.model).Trim().Length -gt 0) -and
    (([string]$Identity.android_version).Trim().Length -gt 0) -and
    (([string]$Identity.sdk).Trim().Length -gt 0) -and
    (([string]$Identity.hardware).Trim().Length -gt 0)
  )
  return $Identity
}

function Limit-Text {
  param(
    [string]$Value = "",
    [int]$MaxLength = 12000
  )
  if ($Value.Length -le $MaxLength) {
    return $Value
  }
  return ($Value.Substring(0, $MaxLength) + "`n...[truncated]")
}

function Get-PngFileInfo {
  param([Parameter(Mandatory = $true)][string]$Path)

  $Info = [ordered]@{
    exists = [bool](Test-Path -LiteralPath $Path)
    read_bytes = 0
    png_signature_ok = $false
    width = 0
    height = 0
    valid_png = $false
    error = ""
  }
  if (-not $Info.exists) {
    $Info.error = "file_missing"
    return $Info
  }

  $Stream = $null
  try {
    $Header = [byte[]]::new(24)
    $Stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
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
    if ($Stream) {
      $Stream.Dispose()
    }
  }
  return $Info
}

$ResolvedApk = Resolve-ProjectPath $ApkPath
$ResolvedScreenshotPath = Resolve-ProjectPath $ScreenshotPath
$OutJsonPath = Resolve-ProjectPath $OutJson
$OutMarkdownPath = Resolve-ProjectPath $OutMarkdown
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutJsonPath), (Split-Path -Parent $OutMarkdownPath), (Split-Path -Parent $ResolvedScreenshotPath) | Out-Null

$Adb = Resolve-Adb $AdbPath
$ApkExists = Test-Path $ResolvedApk
$Result = [ordered]@{
  generated_at = (Get-Date).ToString("o")
  ok = $false
  skipped = $false
  skip_reason = ""
  adb = [ordered]@{
    path = $Adb
    found = [bool]$Adb
    accessible = $false
    devices_command = ""
    devices_exit_code = $null
    devices_output = ""
  }
  requested_device_id = $DeviceId
  require_physical_device = [bool]$RequirePhysicalDevice
  selected_device_id = ""
  selected_device_is_emulator = $false
  device_identity = [ordered]@{
    attempted = $false
    manufacturer = ""
    model = ""
    product = ""
    device = ""
    android_version = ""
    sdk = ""
    hardware = ""
    qemu = ""
    serial_no = ""
    recorded = $false
  }
  devices = @()
  apk = [ordered]@{
    path = $ResolvedApk
    exists = $ApkExists
    size_bytes = 0
    sha256 = ""
  }
  package_id = $PackageId
  launch_activity = $LaunchActivity
  install = [ordered]@{ attempted = $false; exit_code = $null; output = "" }
  package_check = [ordered]@{ attempted = $false; exit_code = $null; output = ""; installed = $false }
  launch = [ordered]@{ attempted = $false; exit_code = $null; output = ""; started = $false }
  foreground_check = [ordered]@{ attempted = $false; exit_code = $null; output = ""; matched_package = $false }
  screenshot = [ordered]@{ attempted = $false; exit_code = $null; path = $ResolvedScreenshotPath; exists = $false; size_bytes = 0; sha256 = ""; output = ""; captured = $false; png_signature_ok = $false; width = 0; height = 0; valid_png = $false }
  error = ""
}

try {
  if ($ApkExists) {
    $Apk = Get-Item -LiteralPath $ResolvedApk
    $Hash = Get-FileHash -LiteralPath $ResolvedApk -Algorithm SHA256
    $Result.apk.size_bytes = $Apk.Length
    $Result.apk.sha256 = $Hash.Hash
  } else {
    throw "APK not found: $ResolvedApk"
  }

  if (-not $Adb) {
    $Result.skipped = $true
    $Result.skip_reason = "adb_not_found"
  } else {
    $DeviceReport = Read-Devices -Adb $Adb
    $Result.adb.devices_command = $DeviceReport.command
    $Result.adb.devices_exit_code = $DeviceReport.exit_code
    $Result.adb.devices_output = Limit-Text $DeviceReport.output
    if ($DeviceReport.exit_code -ne 0) {
      $Result.skipped = $true
      $Result.skip_reason = "adb_not_accessible"
      $Result.error = "adb devices failed: $($DeviceReport.output)"
    } else {
      $Result.adb.accessible = $true
      foreach ($Device in @($DeviceReport.devices)) {
      if ($Device.state -eq "device") {
        $Device["is_emulator"] = [bool](Test-EmulatorDevice -Adb $Adb -DeviceId ([string]$Device.id))
      } else {
        $Device["is_emulator"] = $false
      }
    }
    $Result.devices = $DeviceReport.devices
    $ConnectedDevices = @($DeviceReport.devices | Where-Object { $_.state -eq "device" })
    if ($DeviceId.Trim()) {
      $ConnectedDevices = @($ConnectedDevices | Where-Object { $_.id -eq $DeviceId })
    }
    if ($RequirePhysicalDevice) {
      $ConnectedDevices = @($ConnectedDevices | Where-Object { -not [bool]$_.is_emulator })
    }

    if ($ConnectedDevices.Count -eq 0) {
      $Result.skipped = $true
      $Result.skip_reason = if ($RequirePhysicalDevice -and $DeviceId.Trim()) {
        "requested_device_not_connected_authorized_or_physical"
      } elseif ($RequirePhysicalDevice) {
        "no_authorized_physical_android_device"
      } elseif ($DeviceId.Trim()) {
        "requested_device_not_connected_or_authorized"
      } else {
        "no_authorized_android_device"
      }
    } else {
      $SelectedDevice = $ConnectedDevices[0].id
      $Result.selected_device_id = $SelectedDevice
      $Result.selected_device_is_emulator = [bool]$ConnectedDevices[0].is_emulator
      $Result.device_identity = Get-DeviceIdentity -Adb $Adb -DeviceId $SelectedDevice

      if (-not $SkipInstall) {
        $Install = Invoke-Adb -Adb $Adb -SelectedDevice $SelectedDevice -Arguments @("install", "-r", $ResolvedApk) -TimeoutMilliseconds 180000
        $Result.install.attempted = $true
        $Result.install.exit_code = $Install.exit_code
        $Result.install.output = $Install.output
        if ($Install.exit_code -ne 0) {
          throw "adb install failed: $($Install.output)"
        }
      }

      $PackageCheck = Invoke-Adb -Adb $Adb -SelectedDevice $SelectedDevice -Arguments @("shell", "pm", "list", "packages", $PackageId)
      $Result.package_check.attempted = $true
      $Result.package_check.exit_code = $PackageCheck.exit_code
      $Result.package_check.output = $PackageCheck.output
      $Result.package_check.installed = ($PackageCheck.exit_code -eq 0 -and $PackageCheck.output -match [regex]::Escape("package:$PackageId"))
      if (-not $Result.package_check.installed) {
        throw "package was not installed or not visible through adb: $PackageId"
      }

      $Component = "$PackageId/$LaunchActivity"
      $Launch = Invoke-Adb -Adb $Adb -SelectedDevice $SelectedDevice -Arguments @("shell", "am", "start", "-n", $Component)
      $Result.launch.attempted = $true
      $Result.launch.exit_code = $Launch.exit_code
      $Result.launch.output = $Launch.output
      $Result.launch.started = ($Launch.exit_code -eq 0 -and $Launch.output -match "Starting|Warning")
      if (-not $Result.launch.started) {
        throw "app launch failed: $($Launch.output)"
      }

      Start-Sleep -Seconds 2
      $Foreground = Invoke-Adb -Adb $Adb -SelectedDevice $SelectedDevice -Arguments @("shell", "dumpsys", "window", "windows")
      $Result.foreground_check.attempted = $true
      $Result.foreground_check.exit_code = $Foreground.exit_code
      $Result.foreground_check.output = Limit-Text $Foreground.output
      $Result.foreground_check.matched_package = ($Foreground.exit_code -eq 0 -and $Foreground.output -match [regex]::Escape($PackageId))

      $Screenshot = Invoke-AdbBinaryToFile `
        -Adb $Adb `
        -SelectedDevice $SelectedDevice `
        -Arguments @("exec-out", "screencap", "-p") `
        -OutputPath $ResolvedScreenshotPath `
        -TimeoutMilliseconds 30000
      $Result.screenshot.attempted = $true
      $Result.screenshot.exit_code = $Screenshot.exit_code
      $Result.screenshot.output = Limit-Text $Screenshot.output
      if ($Screenshot.exit_code -eq 0 -and (Test-Path $ResolvedScreenshotPath)) {
        $ScreenshotFile = Get-Item -LiteralPath $ResolvedScreenshotPath
        $Result.screenshot.exists = $true
        $Result.screenshot.size_bytes = $ScreenshotFile.Length
        $PngInfo = Get-PngFileInfo -Path $ResolvedScreenshotPath
        $Result.screenshot.png_signature_ok = [bool]$PngInfo.png_signature_ok
        $Result.screenshot.width = [int]$PngInfo.width
        $Result.screenshot.height = [int]$PngInfo.height
        $Result.screenshot.valid_png = [bool]$PngInfo.valid_png
        if (-not [bool]$PngInfo.valid_png -and $PngInfo.error) {
          $Result.screenshot.output = (Limit-Text ((@($Result.screenshot.output, "PNG check: $($PngInfo.error)") | Where-Object { $_ }) -join "`n"))
        }
        if ($ScreenshotFile.Length -gt 0) {
          $ScreenshotHash = Get-FileHash -LiteralPath $ResolvedScreenshotPath -Algorithm SHA256
          $Result.screenshot.sha256 = $ScreenshotHash.Hash
          $Result.screenshot.captured = [bool]$PngInfo.valid_png
        }
      }

      $Result.ok = (
        $Result.package_check.installed -and
        $Result.launch.started -and
        $Result.foreground_check.matched_package -and
        $Result.screenshot.captured -and
        $Result.screenshot.valid_png -and
        $Result.device_identity.recorded
      )
      if (-not $Result.ok) {
        throw "app launched but foreground/screenshot/device identity proof did not confirm package $PackageId"
      }
    }
    }
  }
}
catch {
  $Result.error = $_.Exception.Message
}

$Result | ConvertTo-Json -Depth 8 | Set-Content -Path $OutJsonPath -Encoding UTF8

$Lines = @(
  "# Verity Lens Phone Device Smoke",
  "",
  "- Generated: ``$($Result.generated_at)``",
  "- OK: ``$($Result.ok)``",
  "- Skipped: ``$($Result.skipped)``",
  "- Skip reason: ``$($Result.skip_reason)``",
  "- Error: ``$($Result.error)``",
  "- ADB found: ``$($Result.adb.found)``",
  "- ADB executable accessible: ``$($Result.adb.accessible)``",
  "- ADB path: ``$($Result.adb.path)``",
  "- ADB devices exit code: ``$($Result.adb.devices_exit_code)``",
  "- Requested device: ``$($Result.requested_device_id)``",
  "- Require physical device: ``$($Result.require_physical_device)``",
  "- Selected device: ``$($Result.selected_device_id)``",
  "- Selected device is emulator: ``$($Result.selected_device_is_emulator)``",
  "- Device identity recorded: ``$($Result.device_identity.recorded)``",
  "- Device manufacturer: ``$($Result.device_identity.manufacturer)``",
  "- Device model: ``$($Result.device_identity.model)``",
  "- Device product: ``$($Result.device_identity.product)``",
  "- Android version: ``$($Result.device_identity.android_version)``",
  "- Android SDK: ``$($Result.device_identity.sdk)``",
  "- Device hardware: ``$($Result.device_identity.hardware)``",
  "- Device qemu flag: ``$($Result.device_identity.qemu)``",
  "- APK: ``$($Result.apk.path)``",
  "- APK size bytes: ``$($Result.apk.size_bytes)``",
  "- APK SHA256: ``$($Result.apk.sha256)``",
  "- Package id: ``$($Result.package_id)``",
  "- Install attempted: ``$($Result.install.attempted)``",
  "- Package installed: ``$($Result.package_check.installed)``",
  "- Launch started: ``$($Result.launch.started)``",
  "- Foreground matched package: ``$($Result.foreground_check.matched_package)``",
  "- Screenshot captured: ``$($Result.screenshot.captured)``",
  "- Screenshot: ``$($Result.screenshot.path)``",
  "- Screenshot size bytes: ``$($Result.screenshot.size_bytes)``",
  "- Screenshot SHA256: ``$($Result.screenshot.sha256)``",
  "- Screenshot PNG signature OK: ``$($Result.screenshot.png_signature_ok)``",
  "- Screenshot dimensions: ``$($Result.screenshot.width)x$($Result.screenshot.height)``",
  "- Screenshot valid PNG: ``$($Result.screenshot.valid_png)``",
  "",
  "## Devices",
  ""
)
if ($Result.devices.Count -eq 0) {
  $Lines += "- None"
} else {
  foreach ($Device in $Result.devices) {
    $Lines += "- ``$($Device.id)`` state=``$($Device.state)`` emulator=``$($Device.is_emulator)``"
  }
}
$Lines | Set-Content -Path $OutMarkdownPath -Encoding UTF8

Write-Host "Phone device smoke JSON: $OutJsonPath" -ForegroundColor Green
Write-Host "Phone device smoke report: $OutMarkdownPath" -ForegroundColor Green

if ($Result.ok) {
  exit 0
}
if ($Result.skipped -and -not $RequireDevice) {
  exit 0
}
exit 1
