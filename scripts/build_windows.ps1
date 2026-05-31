[CmdletBinding()]
param(
  [switch]$SkipUnitTests,
  [switch]$SkipPackagedSmoke
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "path_safety.ps1")

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$SpecPath = Join-Path $ProjectRoot "packaging\FakeNewsDetector.spec"
$WorkPath = Join-Path $ProjectRoot "build\pyinstaller"
$DistPath = Join-Path $ProjectRoot "dist"
$AppDistPath = Join-Path $DistPath "FakeNewsDetector"
$ExePath = Join-Path $AppDistPath "FakeNewsDetector.exe"
$ZipPath = Join-Path $DistPath "FakeNewsDetector-Windows-Portable.zip"
$IconPath = Join-Path $ProjectRoot "build\icon\FakeNewsDetector.ico"

function Invoke-Step {
  param(
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][scriptblock]$Command
  )
  Write-Host ""
  Write-Host "==> $Label" -ForegroundColor Cyan
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE"
  }
}

function Remove-PathInsideProject {
  param([Parameter(Mandatory = $true)][string]$Path)
  Remove-PathInsideDirectory -Path $Path -Root $ProjectRoot
}

Push-Location $ProjectRoot
try {
  Invoke-Step "Check Python" { & $Python --version }

  Invoke-Step "Ensure PyInstaller" {
    & $Python -m PyInstaller --version
    if ($LASTEXITCODE -ne 0) {
      & $Python -m pip install "pyinstaller>=6.6,<7"
    }
  }

  Invoke-Step "Generate Windows icon" {
    & $Python "scripts\make_windows_icon.py" --out $IconPath --png "build\icon\FakeNewsDetector.png"
  }

  if (-not $SkipUnitTests) {
    Invoke-Step "Run unit tests" {
      & $Python -m unittest discover -s tests -v
    }
  }

  Write-Host ""
  Write-Host "==> Clean previous build output" -ForegroundColor Cyan
  Remove-PathInsideProject $WorkPath
  Remove-PathInsideProject $AppDistPath
  Remove-PathInsideProject $ZipPath

  Invoke-Step "Build portable Windows folder" {
    & $Python -m PyInstaller $SpecPath --noconfirm --clean --distpath $DistPath --workpath $WorkPath
  }

  if (-not (Test-Path $ExePath)) {
    throw "Build did not produce expected executable: $ExePath"
  }

  if (-not $SkipPackagedSmoke) {
    Invoke-Step "Run packaged smoke test" {
      & $ExePath --smoke --port 0
    }
  }

  Invoke-Step "Create portable Windows zip" {
    Compress-Archive -LiteralPath $AppDistPath -DestinationPath $ZipPath -Force
  }

  Write-Host ""
  Write-Host "Build complete: $ExePath" -ForegroundColor Green
  Write-Host "Portable zip: $ZipPath" -ForegroundColor Green
}
finally {
  Pop-Location
}
