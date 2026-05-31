[CmdletBinding()]
param(
  [string]$ZipPath = "outputs\cloud_deploy\verity-lens-render-backend.zip",
  [string]$OutputDir = "outputs\cloud_deploy\render_backend_smoke",
  [int]$TimeoutSeconds = 60,
  [switch]$FreshVenv
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "path_safety.ps1")

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([System.IO.Path]::IsPathRooted($ZipPath)) {
  $ZipFullPath = [System.IO.Path]::GetFullPath($ZipPath)
} else {
  $ZipFullPath = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $ZipPath))
}
if ([System.IO.Path]::IsPathRooted($OutputDir)) {
  $SmokeRoot = [System.IO.Path]::GetFullPath($OutputDir)
} else {
  $SmokeRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutputDir))
}
$SmokeRoot = Assert-PathInsideDirectory `
  -Path $SmokeRoot `
  -Root $ProjectRoot `
  -Message "OutputDir must stay inside project: {0}"
if ($SmokeRoot.Equals((ConvertTo-NormalizedFullPath -Path $ProjectRoot), [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "OutputDir must be a subdirectory inside project: $SmokeRoot"
}
$ExtractDir = Join-Path $SmokeRoot "extracted"
$JsonOut = Join-Path $SmokeRoot "RENDER_BUNDLE_SMOKE.json"
$MarkdownOut = Join-Path $SmokeRoot "RENDER_BUNDLE_SMOKE.md"
$ApiStdout = Join-Path $SmokeRoot "api.stdout.log"
$ApiStderr = Join-Path $SmokeRoot "api.stderr.log"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BasePython = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$Python = $BasePython
$FreshVenvDir = Join-Path $SmokeRoot "fresh_venv"
$FreshVenvPython = Join-Path $FreshVenvDir "Scripts\python.exe"
$ApiProcess = $null

function Remove-PathInsideProject {
  param([Parameter(Mandatory = $true)][string]$Path)
  Remove-PathInsideDirectory -Path $Path -Root $ProjectRoot
}

function Get-FreePort {
  $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
  try {
    $Listener.Start()
    return $Listener.LocalEndpoint.Port
  }
  finally {
    $Listener.Stop()
  }
}

function Test-HttpJson {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSec = 10
  )
  try {
    $Response = Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec
    return [ordered]@{ ok = $true; value = $Response; error = "" }
  } catch {
    return [ordered]@{ ok = $false; value = $null; error = $_.Exception.Message }
  }
}

if (-not (Test-Path $ZipFullPath)) {
  throw "Render backend bundle not found: $ZipFullPath"
}

Remove-PathInsideProject $SmokeRoot
New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($ZipFullPath, $ExtractDir)

$RequiredFiles = @(
  "Dockerfile",
  "render.yaml",
  "requirements.api.txt",
  "src\api_factcheck.py",
  "src\factcheck\service.py",
  "config\config.yaml"
)
foreach ($RelativePath in $RequiredFiles) {
  if (-not (Test-Path (Join-Path $ExtractDir $RelativePath))) {
    throw "Extracted Render bundle is missing required file: $RelativePath"
  }
}

$ZipHash = Get-FileHash -LiteralPath $ZipFullPath -Algorithm SHA256
$Port = Get-FreePort
$BaseUrl = "http://127.0.0.1:$Port"
$StartedAt = (Get-Date).ToString("o")
$HealthStatus = "not_checked"
$ReadyStatus = "not_checked"
$FakeProbe = "not_checked"
$Ok = $false
$ErrorMessage = ""
$FreshVenvInstallOk = $false
$FreshVenvInstallSeconds = 0.0
$FreshVenvInstallError = ""
$OldImageModel = $env:FACTCHECK_AI_IMAGE_MODEL
$OldCors = $env:FACTCHECK_CORS_ORIGINS

try {
  $env:FACTCHECK_AI_IMAGE_MODEL = "metadata_only"
  $env:FACTCHECK_CORS_ORIGINS = "*"

  if ($FreshVenv) {
    $InstallStarted = Get-Date
    try {
      & $BasePython -m venv $FreshVenvDir
      if ($LASTEXITCODE -ne 0) {
        throw "python -m venv failed with exit code $LASTEXITCODE"
      }
      if (-not (Test-Path $FreshVenvPython)) {
        throw "Fresh venv python was not created: $FreshVenvPython"
      }
      $Python = $FreshVenvPython
      & $Python -m pip install -r (Join-Path $ExtractDir "requirements.api.txt")
      if ($LASTEXITCODE -ne 0) {
        throw "pip install requirements.api.txt failed with exit code $LASTEXITCODE"
      }
      $FreshVenvInstallOk = $true
    } catch {
      $FreshVenvInstallError = $_.Exception.Message
      throw
    } finally {
      $FreshVenvInstallSeconds = ((Get-Date) - $InstallStarted).TotalSeconds
    }
  }

  $ApiProcess = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "src.api_factcheck:app", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $ExtractDir `
    -RedirectStandardOutput $ApiStdout `
    -RedirectStandardError $ApiStderr `
    -WindowStyle Hidden `
    -PassThru

  $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $LastError = "API did not start"
  while ((Get-Date) -lt $Deadline) {
    if ($ApiProcess.HasExited) {
      $LastError = "API process exited with code $($ApiProcess.ExitCode)"
      break
    }
    $Health = Test-HttpJson "$BaseUrl/health" -TimeoutSec 3
    if ($Health.ok -and $Health.value.status -eq "ok") {
      $HealthStatus = $Health.value.status
      break
    }
    if ($Health.error) {
      $LastError = $Health.error
    }
    Start-Sleep -Milliseconds 750
  }

  if ($HealthStatus -ne "ok") {
    throw "Extracted Render bundle API did not become healthy. Last error: $LastError"
  }

  $Ready = Test-HttpJson "$BaseUrl/ready" -TimeoutSec 10
  $ReadyStatus = if ($Ready.ok) { $Ready.value.status } else { "failed" }
  if (-not $Ready.ok -or $Ready.value.status -ne "ready") {
    throw "Extracted Render bundle API did not return ready. Error: $($Ready.error)"
  }

  $Probe = Invoke-RestMethod `
    -Uri "$BaseUrl/factcheck" `
    -Method Post `
    -ContentType "application/json" `
    -Body (@{ text = "Elephants are insects." } | ConvertTo-Json -Compress) `
    -TimeoutSec 30
  $FakeProbe = "$($Probe.verdict) / $($Probe.confidence)"
  if ($Probe.verdict -ne "fake") {
    throw "Expected fake probe verdict=fake, got $($Probe.verdict)"
  }

  $Ok = $true
} catch {
  $ErrorMessage = $_.Exception.Message
  throw
} finally {
  if ($ApiProcess -and -not $ApiProcess.HasExited) {
    Stop-Process -Id $ApiProcess.Id -Force -ErrorAction SilentlyContinue
  }
  $env:FACTCHECK_AI_IMAGE_MODEL = $OldImageModel
  $env:FACTCHECK_CORS_ORIGINS = $OldCors

  $Report = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    started_at = $StartedAt
    ok = $Ok
    zip = [ordered]@{
      path = (Resolve-Path $ZipFullPath).Path
      sha256 = $ZipHash.Hash
      size_bytes = (Get-Item -LiteralPath $ZipFullPath).Length
    }
    extract_dir = $ExtractDir
    python = $Python
    fresh_venv = [ordered]@{
      requested = [bool]$FreshVenv
      path = if ($FreshVenv) { $FreshVenvDir } else { "" }
      requirements = Join-Path $ExtractDir "requirements.api.txt"
      install_ok = $FreshVenvInstallOk
      install_seconds = [Math]::Round($FreshVenvInstallSeconds, 2)
      install_error = $FreshVenvInstallError
    }
    base_url = $BaseUrl
    health = $HealthStatus
    ready = $ReadyStatus
    fake_probe = $FakeProbe
    error = $ErrorMessage
    logs = [ordered]@{
      stdout = $ApiStdout
      stderr = $ApiStderr
    }
  }
  $Report | ConvertTo-Json -Depth 8 | Set-Content -Path $JsonOut -Encoding UTF8

  @(
    "# Verity Lens Render Bundle Smoke",
    "",
    "- Generated: ``$($Report.generated_at)``",
    "- OK: ``$($Report.ok)``",
    "- Zip: ``$($Report.zip.path)``",
    "- Zip SHA256: ``$($Report.zip.sha256)``",
    "- Zip size bytes: ``$($Report.zip.size_bytes)``",
    "- Extract dir: ``$($Report.extract_dir)``",
    "- Python: ``$($Report.python)``",
    "- Fresh venv requested: ``$($Report.fresh_venv.requested)``",
    "- Fresh venv requirements OK: ``$($Report.fresh_venv.install_ok)``",
    "- Fresh venv install seconds: ``$($Report.fresh_venv.install_seconds)``",
    "- Fresh venv install error: ``$($Report.fresh_venv.install_error)``",
    "- Local API: ``$($Report.base_url)``",
    "- Health: ``$($Report.health)``",
    "- Ready: ``$($Report.ready)``",
    "- Fake probe: ``$($Report.fake_probe)``",
    "- Error: ``$($Report.error)``",
    "- Stdout log: ``$($Report.logs.stdout)``",
    "- Stderr log: ``$($Report.logs.stderr)``"
  ) | Set-Content -Path $MarkdownOut -Encoding UTF8
}

Write-Host "Render bundle smoke JSON: $JsonOut" -ForegroundColor Green
Write-Host "Render bundle smoke report: $MarkdownOut" -ForegroundColor Green
