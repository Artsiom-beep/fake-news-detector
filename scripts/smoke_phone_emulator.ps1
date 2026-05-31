[CmdletBinding()]
param(
  [string]$AvdName = "",
  [string]$ApkPath = "outputs\phone_download\VerityLens-internet.apk",
  [string]$PackageId = "app.veritylens.mobile",
  [string]$LaunchActivity = ".MainActivity",
  [string]$AdbPath = "",
  [string]$EmulatorPath = "",
  [int]$BootTimeoutSeconds = 240,
  [switch]$RequireEmulator,
  [switch]$KeepRunning,
  [string]$OutJson = "outputs\phone_download\PHONE_EMULATOR_SMOKE.json",
  [string]$OutMarkdown = "outputs\phone_download\PHONE_EMULATOR_SMOKE.md"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "path_safety.ps1")
$PowerShell = Get-ChildPowerShellCommand

function Resolve-ProjectPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  if ([System.IO.Path]::IsPathRooted($Path)) {
    return [System.IO.Path]::GetFullPath($Path)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Path))
}

function Resolve-Tool {
  param(
    [string]$RequestedPath,
    [Parameter(Mandatory = $true)][string[]]$Names,
    [string[]]$Fallbacks = @()
  )

  if ($RequestedPath.Trim()) {
    $Resolved = Resolve-ProjectPath $RequestedPath
    if (Test-Path $Resolved) {
      return (Resolve-Path $Resolved).Path
    }
    throw "Tool path does not exist: $Resolved"
  }

  foreach ($Name in $Names) {
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($Command) {
      return $Command.Source
    }
  }

  foreach ($Fallback in $Fallbacks) {
    if ($Fallback -and (Test-Path $Fallback)) {
      return (Resolve-Path $Fallback).Path
    }
  }

  return $null
}

function Invoke-Adb {
  param(
    [Parameter(Mandatory = $true)][string]$Adb,
    [string]$SelectedDevice = "",
    [Parameter(Mandatory = $true)][string[]]$Arguments
  )
  $FullArgs = @()
  if ($SelectedDevice.Trim()) {
    $FullArgs += @("-s", $SelectedDevice)
  }
  $FullArgs += $Arguments
  $Output = & $Adb @FullArgs 2>&1
  return [ordered]@{
    exit_code = $LASTEXITCODE
    output = ($Output -join "`n")
    command = "adb $($FullArgs -join ' ')"
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
  return $Rows
}

function Get-RunningEmulator {
  param([Parameter(Mandatory = $true)][string]$Adb)
  $Devices = @(Read-Devices -Adb $Adb | Where-Object { $_.id -like "emulator-*" -and $_.state -eq "device" })
  if ($Devices.Count -gt 0) {
    return $Devices[0].id
  }
  return ""
}

function Wait-EmulatorBoot {
  param(
    [Parameter(Mandatory = $true)][string]$Adb,
    [Parameter(Mandatory = $true)][string]$DeviceId,
    [int]$TimeoutSeconds = 240
  )
  $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $LastOutput = ""
  while ((Get-Date) -lt $Deadline) {
    $Boot = Invoke-Adb -Adb $Adb -SelectedDevice $DeviceId -Arguments @("shell", "getprop", "sys.boot_completed")
    $LastOutput = $Boot.output
    if ($Boot.exit_code -eq 0 -and $Boot.output.Trim() -eq "1") {
      return [ordered]@{ ok = $true; output = $Boot.output }
    }
    Start-Sleep -Seconds 2
  }
  return [ordered]@{ ok = $false; output = $LastOutput }
}

$ResolvedApk = Resolve-ProjectPath $ApkPath
$OutJsonPath = Resolve-ProjectPath $OutJson
$OutMarkdownPath = Resolve-ProjectPath $OutMarkdown
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutJsonPath), (Split-Path -Parent $OutMarkdownPath) | Out-Null

$Adb = Resolve-Tool `
  -RequestedPath $AdbPath `
  -Names @("adb", "adb.exe") `
  -Fallbacks @((Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"))
$Emulator = Resolve-Tool `
  -RequestedPath $EmulatorPath `
  -Names @("emulator", "emulator.exe") `
  -Fallbacks @((Join-Path $env:LOCALAPPDATA "Android\Sdk\emulator\emulator.exe"))

$EmulatorProcess = $null
$StartedEmulator = $false
$SelectedDevice = ""
$Boot = [ordered]@{ ok = $false; output = "" }
$DeviceSmoke = $null
$Result = [ordered]@{
  generated_at = (Get-Date).ToString("o")
  ok = $false
  skipped = $false
  skip_reason = ""
  avd_name = $AvdName
  adb = [ordered]@{ path = $Adb; found = [bool]$Adb }
  emulator = [ordered]@{ path = $Emulator; found = [bool]$Emulator; started = $false; kept_running = [bool]$KeepRunning }
  selected_device_id = ""
  boot_completed = $false
  apk_path = $ResolvedApk
  device_smoke = $null
  error = ""
}

try {
  if (-not (Test-Path $ResolvedApk)) {
    throw "APK not found: $ResolvedApk"
  }
  if (-not $Adb) {
    $Result.skipped = $true
    $Result.skip_reason = "adb_not_found"
  } elseif (-not $Emulator) {
    $Result.skipped = $true
    $Result.skip_reason = "emulator_not_found"
  } else {
    if (-not $AvdName.Trim()) {
      $Avds = @(& $Emulator -list-avds 2>&1 | Where-Object { $_.Trim() })
      if ($Avds.Count -eq 0) {
        $Result.skipped = $true
        $Result.skip_reason = "no_android_virtual_device"
      } else {
        $AvdName = [string]$Avds[0]
        $Result.avd_name = $AvdName
      }
    }

    if (-not $Result.skipped) {
      $SelectedDevice = Get-RunningEmulator -Adb $Adb
      if (-not $SelectedDevice.Trim()) {
        $EmulatorArgs = @(
          "-avd", $AvdName,
          "-no-window",
          "-no-audio",
          "-no-boot-anim",
          "-gpu", "swiftshader_indirect",
          "-no-snapshot-save"
        )
        $EmulatorProcess = Start-Process `
          -FilePath $Emulator `
          -ArgumentList $EmulatorArgs `
          -WindowStyle Hidden `
          -PassThru
        $StartedEmulator = $true
        $Result.emulator.started = $true

        $Deadline = (Get-Date).AddSeconds($BootTimeoutSeconds)
        while ((Get-Date) -lt $Deadline -and -not $SelectedDevice.Trim()) {
          Start-Sleep -Seconds 2
          $SelectedDevice = Get-RunningEmulator -Adb $Adb
        }
      }

      if (-not $SelectedDevice.Trim()) {
        throw "No running emulator became available before timeout."
      }

      $Result.selected_device_id = $SelectedDevice
      $Boot = Wait-EmulatorBoot -Adb $Adb -DeviceId $SelectedDevice -TimeoutSeconds $BootTimeoutSeconds
      $Result.boot_completed = [bool]$Boot.ok
      if (-not $Boot.ok) {
        throw "Emulator did not finish Android boot before timeout. Last output: $($Boot.output)"
      }

      $RawJson = Join-Path (Split-Path -Parent $OutJsonPath) "PHONE_EMULATOR_DEVICE_SMOKE.raw.json"
      $RawMarkdown = Join-Path (Split-Path -Parent $OutMarkdownPath) "PHONE_EMULATOR_DEVICE_SMOKE.raw.md"
      $ScreenshotPath = Join-Path (Split-Path -Parent $OutJsonPath) "PHONE_EMULATOR_SCREENSHOT.png"
      & $PowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "smoke_phone_on_device.ps1") `
        -ApkPath $ResolvedApk `
        -PackageId $PackageId `
        -LaunchActivity $LaunchActivity `
        -DeviceId $SelectedDevice `
        -ScreenshotPath $ScreenshotPath `
        -OutJson $RawJson `
        -OutMarkdown $RawMarkdown `
        -RequireDevice
      if ($LASTEXITCODE -ne 0) {
        throw "Emulator device smoke failed with exit code $LASTEXITCODE"
      }
      $DeviceSmoke = Get-Content $RawJson -Raw | ConvertFrom-Json
      $Result.device_smoke = $DeviceSmoke
      $Result.ok = [bool]$DeviceSmoke.ok
      if (-not $Result.ok) {
        throw "Emulator device smoke did not report ok=true."
      }

      Remove-Item -LiteralPath $RawJson, $RawMarkdown -Force -ErrorAction SilentlyContinue
    }
  }
} catch {
  $Result.error = $_.Exception.Message
} finally {
  if ($StartedEmulator -and -not $KeepRunning -and $SelectedDevice.Trim()) {
    [void](Invoke-Adb -Adb $Adb -SelectedDevice $SelectedDevice -Arguments @("emu", "kill"))
  }
}

$Result | ConvertTo-Json -Depth 10 | Set-Content -Path $OutJsonPath -Encoding UTF8

$Lines = @(
  "# Verity Lens Phone Emulator Smoke",
  "",
  "- Generated: ``$($Result.generated_at)``",
  "- OK: ``$($Result.ok)``",
  "- Skipped: ``$($Result.skipped)``",
  "- Skip reason: ``$($Result.skip_reason)``",
  "- Error: ``$($Result.error)``",
  "- AVD: ``$($Result.avd_name)``",
  "- ADB found: ``$($Result.adb.found)``",
  "- ADB path: ``$($Result.adb.path)``",
  "- Emulator found: ``$($Result.emulator.found)``",
  "- Emulator path: ``$($Result.emulator.path)``",
  "- Emulator started by script: ``$($Result.emulator.started)``",
  "- Emulator kept running: ``$($Result.emulator.kept_running)``",
  "- Selected device: ``$($Result.selected_device_id)``",
  "- Boot completed: ``$($Result.boot_completed)``",
  "- APK: ``$($Result.apk_path)``"
)
if ($DeviceSmoke) {
  $Lines += @(
    "- APK SHA256: ``$($DeviceSmoke.apk.sha256)``",
    "- Package installed: ``$($DeviceSmoke.package_check.installed)``",
    "- Launch started: ``$($DeviceSmoke.launch.started)``",
    "- Foreground matched package: ``$($DeviceSmoke.foreground_check.matched_package)``",
    "- Screenshot captured: ``$($DeviceSmoke.screenshot.captured)``",
    "- Screenshot: ``$($DeviceSmoke.screenshot.path)``",
    "- Screenshot SHA256: ``$($DeviceSmoke.screenshot.sha256)``"
  )
}
$Lines | Set-Content -Path $OutMarkdownPath -Encoding UTF8

Write-Host "Phone emulator smoke JSON: $OutJsonPath" -ForegroundColor Green
Write-Host "Phone emulator smoke report: $OutMarkdownPath" -ForegroundColor Green

if ($Result.ok) {
  exit 0
}
if ($Result.skipped -and -not $RequireEmulator) {
  exit 0
}
exit 1
