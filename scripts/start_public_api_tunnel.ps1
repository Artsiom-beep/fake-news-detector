[CmdletBinding()]
param(
  [int]$LocalPort = 8001,
  [switch]$BuildApk,
  [switch]$Restart,
  [int]$VerifyTimeoutSeconds = 120,
  [switch]$KeepProcessesOnFailure
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "path_safety.ps1")
$PowerShell = Get-ChildPowerShellCommand
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}

$OutputsDir = Join-Path $ProjectRoot "outputs"
$ToolsDir = Join-Path $OutputsDir "tools"
$TunnelLog = Join-Path $OutputsDir "public-api-tunnel.log"
$TunnelErr = Join-Path $OutputsDir "public-api-tunnel.err.log"
$TunnelInfo = Join-Path $OutputsDir "public_api_tunnel_info.json"
$PublicUrlFile = Join-Path $OutputsDir "public_api_url.txt"
$Cloudflared = Join-Path $ToolsDir "cloudflared.exe"
$StartedLocalApiProcess = $null

function Test-Health {
  param([Parameter(Mandatory = $true)][int]$Port)
  try {
    $Response = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 4
    return $Response.status -eq "ok"
  } catch {
    return $false
  }
}

function Get-TunnelUrlFromLogs {
  $Combined = ""
  foreach ($Path in @($TunnelLog, $TunnelErr)) {
    if (Test-Path $Path) {
      $Combined += "`n" + (Get-Content -Path $Path -Raw -ErrorAction SilentlyContinue)
    }
  }
  $Match = [regex]::Match($Combined, "https://[a-zA-Z0-9-]+\.trycloudflare\.com")
  if ($Match.Success) {
    return $Match.Value
  }
  return $null
}

function Get-ErrorDetail {
  param([Parameter(Mandatory = $true)]$ErrorRecord)
  $Message = $ErrorRecord.Exception.Message
  try {
    if ($ErrorRecord.Exception.Response -and $ErrorRecord.Exception.Response.StatusCode) {
      $Message = "$Message (HTTP $([int]$ErrorRecord.Exception.Response.StatusCode))"
    }
  } catch {
    # Best-effort diagnostics only.
  }
  return $Message
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

    $Health = $null
    try {
      $Health = Invoke-RestMethod -Uri "$ApiBaseUrl/health" -TimeoutSec 10
    } catch {
      $LastError = "health check failed: $(Get-ErrorDetail $_)"
      Start-Sleep -Seconds 2
      continue
    }
    if ($Health.status -ne "ok") {
      $LastError = "health check returned status='$($Health.status)'"
      Start-Sleep -Seconds 2
      continue
    }

    $Ready = $null
    try {
      $Ready = Invoke-RestMethod -Uri "$ApiBaseUrl/ready" -TimeoutSec 10
    } catch {
      $LastError = "ready check failed: $(Get-ErrorDetail $_)"
      Start-Sleep -Seconds 2
      continue
    }
    if ($Ready.status -ne "ready") {
      $LastError = "ready check returned status='$($Ready.status)'"
      Start-Sleep -Seconds 2
      continue
    }

    try {
      $Probe = Invoke-RestMethod `
        -Uri "$ApiBaseUrl/factcheck" `
        -Method Post `
        -ContentType "application/json" `
        -Body (@{ text = "Elephants are insects." } | ConvertTo-Json -Compress) `
        -TimeoutSec 30
      if ($Probe.verdict -eq "fake") {
        return [ordered]@{
          health = $Health.status
          ready = $Ready.status
          fake_probe = "$($Probe.verdict) / $($Probe.confidence)"
        }
      }
      $LastError = "fact-check probe returned verdict='$($Probe.verdict)'"
    } catch {
      $LastError = "fact-check probe failed: $(Get-ErrorDetail $_)"
    }

    Start-Sleep -Seconds 2
  }

  throw "Public API did not pass health/ready/factcheck checks at $ApiBaseUrl. Last error: $LastError"
}

New-Item -ItemType Directory -Force -Path $OutputsDir, $ToolsDir | Out-Null

if ($Restart) {
  try {
    $Listeners = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
    foreach ($Listener in $Listeners) {
      $ProcessId = [int]$Listener.OwningProcess
      $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
      if ($ProcessInfo -and $ProcessInfo.CommandLine -match "uvicorn.*src\.api_factcheck|src\.api_factcheck") {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
      }
    }
  } catch {
    # Ignore stale listeners; health check below will decide whether to start a fresh API.
  }

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
    -RedirectStandardOutput (Join-Path $OutputsDir "public-api-local.log") `
    -RedirectStandardError (Join-Path $OutputsDir "public-api-local.err.log") `
    -WindowStyle Hidden `
    -PassThru

  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Health -Port $LocalPort) {
      break
    }
  }
}

if (-not (Test-Health -Port $LocalPort)) {
  throw "Local API did not become healthy on http://127.0.0.1:$LocalPort/health"
}

if (-not (Test-Path $Cloudflared)) {
  Write-Host "Downloading cloudflared quick tunnel client..." -ForegroundColor Cyan
  $DownloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
  Invoke-WebRequest -Uri $DownloadUrl -OutFile $Cloudflared
}

Remove-Item -LiteralPath $TunnelLog, $TunnelErr -Force -ErrorAction SilentlyContinue

Write-Host "Opening public tunnel to http://127.0.0.1:$LocalPort ..." -ForegroundColor Cyan
$TunnelProcess = Start-Process `
  -FilePath $Cloudflared `
  -ArgumentList @("tunnel", "--url", "http://127.0.0.1:$LocalPort", "--no-autoupdate") `
  -WorkingDirectory $ProjectRoot `
  -RedirectStandardOutput $TunnelLog `
  -RedirectStandardError $TunnelErr `
  -WindowStyle Hidden `
  -PassThru

$PublicUrl = $null
for ($i = 0; $i -lt 45; $i++) {
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
  $TunnelPid = if ($TunnelProcess) { $TunnelProcess.Id } else { $null }
  $FailureInfo = [ordered]@{
    status = "failed_tunnel_url"
    local_api_url = "http://127.0.0.1:$LocalPort"
    tunnel_process_id = $TunnelPid
    local_port = $LocalPort
    failed_at = (Get-Date).ToString("o")
    error = "Cloudflare tunnel did not produce a public URL."
    tunnel_error_tail = $ErrText
  }
  $FailureInfo | ConvertTo-Json | Set-Content -Path $TunnelInfo -Encoding UTF8
  if (-not $KeepProcessesOnFailure) {
    if ($TunnelProcess -and -not $TunnelProcess.HasExited) {
      Stop-Process -Id $TunnelProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($StartedLocalApiProcess -and -not $StartedLocalApiProcess.HasExited) {
      Stop-Process -Id $StartedLocalApiProcess.Id -Force -ErrorAction SilentlyContinue
    }
  }
  throw "Cloudflare tunnel did not produce a public URL. $ErrText"
}

Set-Content -Path $PublicUrlFile -Value $PublicUrl -Encoding UTF8

$Info = [ordered]@{
  provider = "cloudflare_quick_tunnel"
  status = "active_or_unknown"
  public_api_url = $PublicUrl
  local_api_url = "http://127.0.0.1:$LocalPort"
  tunnel_process_id = $TunnelProcess.Id
  local_port = $LocalPort
  started_at = (Get-Date).ToString("o")
  note = "This quick tunnel works while this PC, local API, and cloudflared process are running. Use Render for a permanent URL."
}
$Info | ConvertTo-Json | Set-Content -Path $TunnelInfo -Encoding UTF8

Write-Host "Public API URL: $PublicUrl" -ForegroundColor Green
Write-Host "Saved to: $PublicUrlFile" -ForegroundColor Green

try {
  $PublicCheck = Wait-PublicApi -ApiBaseUrl $PublicUrl -Port $LocalPort -TimeoutSeconds $VerifyTimeoutSeconds
}
catch {
  if (-not $KeepProcessesOnFailure) {
    if ($TunnelProcess -and -not $TunnelProcess.HasExited) {
      Stop-Process -Id $TunnelProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($StartedLocalApiProcess -and -not $StartedLocalApiProcess.HasExited) {
      Stop-Process -Id $StartedLocalApiProcess.Id -Force -ErrorAction SilentlyContinue
    }
  }
  Remove-Item -LiteralPath $PublicUrlFile -Force -ErrorAction SilentlyContinue
  $FailureInfo = [ordered]@{
    public_api_url = $PublicUrl
    local_api_url = "http://127.0.0.1:$LocalPort"
    tunnel_process_id = $TunnelProcess.Id
    local_port = $LocalPort
    status = "failed_public_verification"
    failed_at = (Get-Date).ToString("o")
    error = $_.Exception.Message
    local_api_healthy = (Test-Health -Port $LocalPort)
    kept_processes_on_failure = [bool]$KeepProcessesOnFailure
  }
  $FailureInfo | ConvertTo-Json | Set-Content -Path $TunnelInfo -Encoding UTF8
  throw
}
Write-Host "Public API verified: health=$($PublicCheck.health), ready=$($PublicCheck.ready), fake=$($PublicCheck.fake_probe)" -ForegroundColor Green

$Info = [ordered]@{
  provider = "cloudflare_quick_tunnel"
  status = "active_verified"
  public_api_url = $PublicUrl
  local_api_url = "http://127.0.0.1:$LocalPort"
  tunnel_process_id = $TunnelProcess.Id
  local_port = $LocalPort
  started_at = (Get-Date).ToString("o")
  health = $PublicCheck.health
  ready = $PublicCheck.ready
  fake_probe = $PublicCheck.fake_probe
  note = "This quick tunnel works while this PC, local API, and cloudflared process are running. Use Render for a permanent URL."
}
$Info | ConvertTo-Json | Set-Content -Path $TunnelInfo -Encoding UTF8

if ($BuildApk) {
  $BuildScript = Join-Path $ProjectRoot "apps\fake_news_detector_flutter\tool\build_internet_apk.ps1"
  & $PowerShell -NoProfile -ExecutionPolicy Bypass -File $BuildScript -ApiBaseUrl $PublicUrl
  if ($LASTEXITCODE -ne 0) {
    throw "Phone APK build failed with exit code $LASTEXITCODE"
  }
}

$ApkPath = Join-Path $ProjectRoot "outputs\phone_download\VerityLens-internet.apk"
$StatusPath = Join-Path $ProjectRoot "outputs\phone_download\PHONE_BUILD_STATUS.md"
if (Test-Path $ApkPath) {
  $Apk = Get-Item -LiteralPath $ApkPath
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
  $LocalApi = "http://127.0.0.1:$LocalPort"
  @(
    "# Verity Lens Phone Build Status",
    "",
    "- Created: ``$CreatedAt``",
    "- Public API: ``$PublicUrl``",
    "- Local API: ``$LocalApi``",
    "- API health: ``$($PublicCheck.health)``",
    "- API ready: ``$($PublicCheck.ready)``",
    "- Fake probe: ``$($PublicCheck.fake_probe)``",
    "- Flutter source SHA256: ``$FlutterSourceSha``",
    "- Flutter source files: ``$FlutterSourceFileCount``",
    "- APK: ``$($Apk.FullName)``",
    "- APK size bytes: ``$($Apk.Length)``",
    "",
    "This quick-tunnel APK works while this PC, the local API and the cloudflared tunnel process are running. Use Render for the permanent phone build."
  ) | Set-Content -Path $StatusPath -Encoding UTF8
  Write-Host "Phone build status: $StatusPath" -ForegroundColor Green
}
