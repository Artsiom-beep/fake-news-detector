[CmdletBinding()]
param(
  [int]$LocalPort = 8001,
  [switch]$BuildApk,
  [ValidateSet("debug", "release")]
  [string]$ApkMode = "release",
  [string]$ApkOutputName = "VerityLens-internet.apk",
  [switch]$Restart,
  [int]$VerifyTimeoutSeconds = 120,
  [switch]$KeepProcessesOnFailure
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "path_safety.ps1")
$PowerShell = Get-ChildPowerShellCommand
$ApkOutputName = Assert-ApkOutputName -Name $ApkOutputName
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}

$OutputsDir = Join-Path $ProjectRoot "outputs"
$TunnelLog = Join-Path $OutputsDir "localtunnel.log"
$TunnelErr = Join-Path $OutputsDir "localtunnel.err.log"
$TunnelInfo = Join-Path $OutputsDir "public_api_tunnel_info.json"
$PublicUrlFile = Join-Path $OutputsDir "public_api_url.txt"
$LocalApiPidFile = Join-Path $OutputsDir "local_api_process_id.txt"
$TunnelPidFile = Join-Path $OutputsDir "localtunnel_process_id.txt"
$StartedLocalApiProcess = $null
$TunnelProcess = $null

function Test-Health {
  param([Parameter(Mandatory = $true)][int]$Port)
  try {
    $Response = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 4
    return $Response.status -eq "ok"
  } catch {
    return $false
  }
}

function Stop-RecordedProcess {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    return
  }
  try {
    $ProcessId = [int](Get-Content $Path -Raw).Trim()
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
  } catch {
    # Ignore stale process metadata.
  }
}

function Get-TunnelUrlFromLogs {
  $Combined = ""
  foreach ($Path in @($TunnelLog, $TunnelErr)) {
    if (Test-Path $Path) {
      $Combined += "`n" + (Get-Content -Path $Path -Raw -ErrorAction SilentlyContinue)
    }
  }
  $Match = [regex]::Match($Combined, "https://[a-zA-Z0-9-]+\.loca\.lt")
  if ($Match.Success) {
    return $Match.Value
  }
  return $null
}

function Wait-PublicApi {
  param(
    [Parameter(Mandatory = $true)][string]$ApiBaseUrl,
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][int]$TimeoutSeconds
  )

  $Attempts = [Math]::Max(1, [Math]::Ceiling($TimeoutSeconds / 2))
  $LastError = "public API verification did not run"

  for ($i = 0; $i -lt $Attempts; $i++) {
    if (-not (Test-Health -Port $Port)) {
      $LastError = "local API is no longer healthy on http://127.0.0.1:$Port/health"
      break
    }

    try {
      $Health = Invoke-RestMethod -Uri "$ApiBaseUrl/health" -TimeoutSec 10
      $Ready = Invoke-RestMethod -Uri "$ApiBaseUrl/ready" -TimeoutSec 10
      $Probe = Invoke-RestMethod `
        -Uri "$ApiBaseUrl/factcheck" `
        -Method Post `
        -ContentType "application/json" `
        -Body (@{ text = "Elephants are insects." } | ConvertTo-Json -Compress) `
        -TimeoutSec 30

      if ($Health.status -eq "ok" -and $Ready.status -eq "ready" -and $Probe.verdict -eq "fake") {
        return [ordered]@{
          health = $Health.status
          ready = $Ready.status
          fake_probe = "$($Probe.verdict) / $($Probe.confidence)"
        }
      }
      $LastError = "expected health=ok, ready=ready and fake probe verdict=fake"
    } catch {
      $LastError = $_.Exception.Message
    }

    Start-Sleep -Seconds 2
  }

  throw "LocalTunnel API did not pass health/ready/factcheck checks at $ApiBaseUrl. Last error: $LastError"
}

function Write-FailureInfo {
  param(
    [string]$Status,
    [string]$PublicUrl,
    [string]$ErrorMessage
  )
  $Info = [ordered]@{
    provider = "localtunnel"
    status = $Status
    public_api_url = $PublicUrl
    local_api_url = "http://127.0.0.1:$LocalPort"
    tunnel_process_id = if ($TunnelProcess) { $TunnelProcess.Id } else { $null }
    local_port = $LocalPort
    failed_at = (Get-Date).ToString("o")
    error = $ErrorMessage
    local_api_healthy = (Test-Health -Port $LocalPort)
    kept_processes_on_failure = [bool]$KeepProcessesOnFailure
  }
  $Info | ConvertTo-Json | Set-Content -Path $TunnelInfo -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $OutputsDir | Out-Null

if ($Restart) {
  Stop-RecordedProcess $TunnelPidFile
  if (Test-Path $TunnelInfo) {
    try {
      $Existing = Get-Content $TunnelInfo -Raw | ConvertFrom-Json
      if ($Existing.tunnel_process_id) {
        Stop-Process -Id ([int]$Existing.tunnel_process_id) -Force -ErrorAction SilentlyContinue
      }
    } catch {
      # Ignore stale metadata.
    }
  }
}

if (-not (Test-Health -Port $LocalPort)) {
  Write-Host "Starting local API on port $LocalPort..." -ForegroundColor Cyan
  $StartedLocalApiProcess = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "src.api_factcheck:app", "--host", "0.0.0.0", "--port", "$LocalPort") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput (Join-Path $OutputsDir "localtunnel-api.log") `
    -RedirectStandardError (Join-Path $OutputsDir "localtunnel-api.err.log") `
    -WindowStyle Hidden `
    -PassThru
  $StartedLocalApiProcess.Id | Set-Content -Path $LocalApiPidFile -Encoding UTF8

  for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Health -Port $LocalPort) {
      break
    }
  }
}

if (-not (Test-Health -Port $LocalPort)) {
  throw "Local API did not become healthy on http://127.0.0.1:$LocalPort/health"
}

Remove-Item -LiteralPath $TunnelLog, $TunnelErr -Force -ErrorAction SilentlyContinue

Write-Host "Opening LocalTunnel to http://127.0.0.1:$LocalPort ..." -ForegroundColor Cyan
$TunnelProcess = Start-Process `
  -FilePath "npx.cmd" `
  -ArgumentList @("--yes", "localtunnel", "--port", "$LocalPort", "--local-host", "127.0.0.1") `
  -WorkingDirectory $ProjectRoot `
  -RedirectStandardOutput $TunnelLog `
  -RedirectStandardError $TunnelErr `
  -WindowStyle Hidden `
  -PassThru
$TunnelProcess.Id | Set-Content -Path $TunnelPidFile -Encoding UTF8

$PublicUrl = $null
for ($i = 0; $i -lt 90; $i++) {
  Start-Sleep -Seconds 1
  $PublicUrl = Get-TunnelUrlFromLogs
  if ($PublicUrl) {
    break
  }
  if ($TunnelProcess.HasExited) {
    break
  }
}

if (-not $PublicUrl) {
  $ErrText = ""
  if (Test-Path $TunnelErr) {
    $ErrText = Get-Content $TunnelErr -Raw -ErrorAction SilentlyContinue
  }
  if (-not $KeepProcessesOnFailure) {
    if ($TunnelProcess -and -not $TunnelProcess.HasExited) {
      Stop-Process -Id $TunnelProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($StartedLocalApiProcess -and -not $StartedLocalApiProcess.HasExited) {
      Stop-Process -Id $StartedLocalApiProcess.Id -Force -ErrorAction SilentlyContinue
    }
  }
  Write-FailureInfo -Status "failed_tunnel_url" -PublicUrl "" -ErrorMessage "LocalTunnel did not produce a public URL. $ErrText"
  throw "LocalTunnel did not produce a public URL. $ErrText"
}

Set-Content -Path $PublicUrlFile -Value $PublicUrl -Encoding UTF8
Write-Host "Public API URL: $PublicUrl" -ForegroundColor Green

try {
  $PublicCheck = Wait-PublicApi -ApiBaseUrl $PublicUrl -Port $LocalPort -TimeoutSeconds $VerifyTimeoutSeconds
} catch {
  if (-not $KeepProcessesOnFailure) {
    if ($TunnelProcess -and -not $TunnelProcess.HasExited) {
      Stop-Process -Id $TunnelProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($StartedLocalApiProcess -and -not $StartedLocalApiProcess.HasExited) {
      Stop-Process -Id $StartedLocalApiProcess.Id -Force -ErrorAction SilentlyContinue
    }
  }
  Remove-Item -LiteralPath $PublicUrlFile -Force -ErrorAction SilentlyContinue
  Write-FailureInfo -Status "failed_public_verification" -PublicUrl $PublicUrl -ErrorMessage $_.Exception.Message
  throw
}

$Info = [ordered]@{
  provider = "localtunnel"
  status = "active_verified"
  public_api_url = $PublicUrl
  local_api_url = "http://127.0.0.1:$LocalPort"
  tunnel_process_id = $TunnelProcess.Id
  local_port = $LocalPort
  started_at = (Get-Date).ToString("o")
  health = $PublicCheck.health
  ready = $PublicCheck.ready
  fake_probe = $PublicCheck.fake_probe
  note = "This temporary URL works while this PC, local API, and LocalTunnel process are running. Use Render for a permanent URL."
}
$Info | ConvertTo-Json | Set-Content -Path $TunnelInfo -Encoding UTF8
Write-Host "Public API verified: health=$($PublicCheck.health), ready=$($PublicCheck.ready), fake=$($PublicCheck.fake_probe)" -ForegroundColor Green

if ($BuildApk) {
  $BuildScript = Join-Path $ProjectRoot "apps\fake_news_detector_flutter\tool\build_internet_apk.ps1"
  & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $BuildScript `
    -ApiBaseUrl $PublicUrl `
    -Mode $ApkMode `
    -OutputName $ApkOutputName
  if ($LASTEXITCODE -ne 0) {
    throw "Phone APK build failed with exit code $LASTEXITCODE"
  }
}

$ApkPath = Join-Path $ProjectRoot "outputs\phone_download\$ApkOutputName"
$StatusPath = Join-Path $ProjectRoot "outputs\phone_download\PHONE_BUILD_STATUS.md"
if (Test-Path $ApkPath) {
  $Apk = Get-Item -LiteralPath $ApkPath
  $ApkHash = Get-FileHash -LiteralPath $Apk.FullName -Algorithm SHA256
  $ApkBaseName = [System.IO.Path]::GetFileNameWithoutExtension($Apk.Name)
  $SourceStampPath = Join-Path $Apk.DirectoryName "$ApkBaseName-flutter-source-stamp.json"
  $FlutterSourceStamp = $null
  if (Test-Path -LiteralPath $SourceStampPath) {
    $FlutterSourceStamp = Get-Content -LiteralPath $SourceStampPath -Raw | ConvertFrom-Json
  }
  $FlutterSourceSha = if ($FlutterSourceStamp -and $FlutterSourceStamp.sha256) {
    ([string]$FlutterSourceStamp.sha256).ToUpperInvariant()
  } else {
    "missing"
  }
  $FlutterSourceFileCount = if ($FlutterSourceStamp -and $FlutterSourceStamp.file_count) {
    [int]$FlutterSourceStamp.file_count
  } else {
    0
  }
  $CreatedAt = (Get-Date).ToString("o")
  @(
    "# Verity Lens Phone Build Status",
    "",
    "- Created: ``$CreatedAt``",
    "- Tunnel provider: ``localtunnel``",
    "- APK mode: ``$ApkMode``",
    "- Public API: ``$PublicUrl``",
    "- Local API: ``http://127.0.0.1:$LocalPort``",
    "- API health: ``$($PublicCheck.health)``",
    "- API ready: ``$($PublicCheck.ready)``",
    "- Fake probe: ``$($PublicCheck.fake_probe)``",
    "- Flutter source SHA256: ``$FlutterSourceSha``",
    "- Flutter source files: ``$FlutterSourceFileCount``",
    "- APK: ``$($Apk.FullName)``",
    "- APK size bytes: ``$($Apk.Length)``",
    "- APK SHA256: ``$($ApkHash.Hash)``",
    "",
    "This temporary APK works while this PC, the local API and the LocalTunnel process are running. Use Render for the permanent phone build."
  ) | Set-Content -Path $StatusPath -Encoding UTF8
  Write-Host "Phone build status: $StatusPath" -ForegroundColor Green
}
