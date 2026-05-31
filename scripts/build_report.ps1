[CmdletBinding()]
param(
  [ValidateSet("auto", "pdflatex", "tectonic")]
  [string]$Engine = "auto",

  [switch]$BootstrapTectonic
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReportDir = Join-Path $ProjectRoot "docs\report"
$SourceTex = Join-Path $ReportDir "verity_lens_report.tex"
$OutputPdf = Join-Path $ReportDir "verity_lens_report.pdf"
$BuildDir = Join-Path $ProjectRoot "outputs\report_build"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$VenvTectonic = Join-Path $ProjectRoot ".venv\Scripts\tectonic.exe"
$ReportAuxiliaryFiles = @(
  "verity_lens_report.aux",
  "verity_lens_report.log",
  "verity_lens_report.out",
  "verity_lens_report.toc",
  "verity_lens_report.fls",
  "verity_lens_report.fdb_latexmk",
  "verity_lens_report.synctex.gz",
  "verity_lens_report.xdv",
  "verity_lens_report.bbl",
  "verity_lens_report.blg",
  "verity_lens_report.nav",
  "verity_lens_report.snm",
  "verity_lens_report.vrb"
)

function Resolve-ReportEngine {
  if ($Engine -eq "pdflatex") {
    $Cmd = Get-Command pdflatex -ErrorAction SilentlyContinue
    if (-not $Cmd) {
      throw "pdflatex was requested but is not available."
    }
    return @{ Name = "pdflatex"; Path = $Cmd.Source }
  }

  if ($Engine -eq "tectonic") {
    return Resolve-Tectonic
  }

  $PdfLatex = Get-Command pdflatex -ErrorAction SilentlyContinue
  if ($PdfLatex) {
    return @{ Name = "pdflatex"; Path = $PdfLatex.Source }
  }
  return Resolve-Tectonic
}

function Resolve-Tectonic {
  $Cmd = Get-Command tectonic -ErrorAction SilentlyContinue
  if ($Cmd) {
    return @{ Name = "tectonic"; Path = $Cmd.Source }
  }
  if (Test-Path $VenvTectonic) {
    return @{ Name = "tectonic"; Path = $VenvTectonic }
  }
  if ($BootstrapTectonic) {
    if (-not (Test-Path $VenvPython)) {
      throw "Cannot bootstrap Tectonic because .venv Python was not found."
    }
    & $VenvPython -m pip install tecto
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to install the local Tectonic binary via the tecto wheel."
    }
    if (Test-Path $VenvTectonic) {
      return @{ Name = "tectonic"; Path = $VenvTectonic }
    }
  }
  throw "No LaTeX engine found. Install pdflatex or run .\scripts\build_report.ps1 -BootstrapTectonic."
}

function Convert-PolishToLatexMacros {
  param([Parameter(Mandatory = $true)][string]$Text)

  $Pairs = @(
    @([string][char]0x0105, '\k{a}'),
    @([string][char]0x0104, '\k{A}'),
    @([string][char]0x0107, "\'c"),
    @([string][char]0x0106, "\'C"),
    @([string][char]0x0119, '\k{e}'),
    @([string][char]0x0118, '\k{E}'),
    @([string][char]0x0142, '\l{}'),
    @([string][char]0x0141, '\L{}'),
    @([string][char]0x0144, "\'n"),
    @([string][char]0x0143, "\'N"),
    @([string][char]0x00F3, "\'o"),
    @([string][char]0x00D3, "\'O"),
    @([string][char]0x015B, "\'s"),
    @([string][char]0x015A, "\'S"),
    @([string][char]0x017A, "\'z"),
    @([string][char]0x0179, "\'Z"),
    @([string][char]0x017C, '\.z'),
    @([string][char]0x017B, '\.Z')
  )
  foreach ($Pair in $Pairs) {
    $Text = $Text.Replace($Pair[0], $Pair[1])
  }
  return $Text
}

function Invoke-PdfLatex {
  param([Parameter(Mandatory = $true)][string]$Path)
  Push-Location $ReportDir
  try {
    for ($i = 0; $i -lt 2; $i++) {
      & $Path -interaction=nonstopmode -halt-on-error "verity_lens_report.tex"
      if ($LASTEXITCODE -ne 0) {
        throw "pdflatex failed."
      }
    }
  }
  finally {
    Pop-Location
  }
}

function Invoke-Tectonic {
  param([Parameter(Mandatory = $true)][string]$Path)
  New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
  $PreparedTex = Join-Path $BuildDir "verity_lens_report.tex"
  $Source = Get-Content -Path $SourceTex -Raw -Encoding UTF8
  Convert-PolishToLatexMacros $Source | Set-Content -Path $PreparedTex -Encoding UTF8
  & $Path $PreparedTex --outdir $ReportDir
  if ($LASTEXITCODE -ne 0) {
    throw "tectonic failed."
  }
}

function Remove-ReportAuxiliaryFiles {
  foreach ($FileName in $ReportAuxiliaryFiles) {
    $Path = Join-Path $ReportDir $FileName
    if (Test-Path $Path) {
      Remove-Item -LiteralPath $Path -Force
    }
  }
}

if (-not (Test-Path $SourceTex)) {
  throw "Report source not found: $SourceTex"
}

$Resolved = Resolve-ReportEngine
Write-Host "Building report with $($Resolved.Name): $($Resolved.Path)" -ForegroundColor Cyan

if ($Resolved.Name -eq "pdflatex") {
  Invoke-PdfLatex $Resolved.Path
}
else {
  Invoke-Tectonic $Resolved.Path
}

if (-not (Test-Path $OutputPdf)) {
  throw "Report build did not produce expected PDF: $OutputPdf"
}

Remove-ReportAuxiliaryFiles

Get-Item -LiteralPath $OutputPdf | Select-Object FullName, Length, LastWriteTime
