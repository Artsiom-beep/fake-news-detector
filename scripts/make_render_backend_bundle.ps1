[CmdletBinding()]
param(
  [string]$OutputPath = "outputs\cloud_deploy\verity-lens-render-backend.zip"
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "path_safety.ps1")

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([System.IO.Path]::IsPathRooted($OutputPath)) {
  $OutputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
} else {
  $OutputFullPath = [System.IO.Path]::GetFullPath((Join-Path $Root $OutputPath))
}
$OutputFullPath = Assert-PathInsideDirectory `
  -Path $OutputFullPath `
  -Root $Root `
  -Message "OutputPath must stay inside project: {0}"
if ($OutputFullPath.Equals((ConvertTo-NormalizedFullPath -Path $Root), [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "OutputPath must be a file path inside project: $OutputFullPath"
}
$StageRoot = Join-Path $Root "outputs\cloud_deploy"
$Stage = Join-Path $StageRoot ("render_backend_source_" + [System.Guid]::NewGuid().ToString("N"))

function Remove-PathInsideProject {
  param([Parameter(Mandatory = $true)][string]$Path)
  Remove-PathInsideDirectory -Path $Path -Root $Root
}

if (Test-Path $Stage) {
  Remove-PathInsideProject $Stage
}
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFullPath) | Out-Null

$Items = @(
  "Dockerfile",
  ".dockerignore",
  "render.yaml",
  "requirements.api.txt",
  "README.md",
  ".env.example",
  "src",
  "data\factcheck",
  "config"
)

foreach ($Item in $Items) {
  $Source = Join-Path $Root $Item
  if (-not (Test-Path $Source)) {
    continue
  }
  $Destination = Join-Path $Stage $Item
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
  Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

Get-ChildItem -LiteralPath $Stage -Recurse -Directory -Filter "__pycache__" |
  ForEach-Object { Remove-PathInsideProject $_.FullName }
Get-ChildItem -LiteralPath $Stage -Recurse -File |
  Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
  ForEach-Object { Remove-PathInsideProject $_.FullName }

$RequiredStageFiles = @(
  "Dockerfile",
  ".dockerignore",
  "render.yaml",
  "requirements.api.txt",
  "src\api_factcheck.py",
  "src\factcheck\service.py",
  "config\config.yaml"
)
foreach ($RelativePath in $RequiredStageFiles) {
  $RequiredPath = Join-Path $Stage $RelativePath
  if (-not (Test-Path $RequiredPath)) {
    throw "Render bundle staging is missing required file: $RelativePath"
  }
}

if (Test-Path $OutputFullPath) {
  Remove-Item -LiteralPath $OutputFullPath -Force
}
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $OutputFullPath -Force

Add-Type -AssemblyName System.IO.Compression.FileSystem
$Zip = [System.IO.Compression.ZipFile]::OpenRead($OutputFullPath)
try {
  $Entries = @($Zip.Entries | ForEach-Object { $_.FullName.Replace("\", "/") })
  foreach ($RelativePath in @("Dockerfile", ".dockerignore", "render.yaml", "requirements.api.txt", "src/api_factcheck.py", "src/factcheck/service.py")) {
    if ($Entries -notcontains $RelativePath) {
      throw "Render bundle zip is missing required file: $RelativePath"
    }
  }
  if ($Entries | Where-Object { $_ -like "archive/*" -or $_ -like "*__pycache__*" -or $_ -like "*.pyc" -or $_ -like "*.pyo" }) {
    throw "Render bundle zip contains archived or cache files."
  }
}
finally {
  $Zip.Dispose()
}

$Bundle = Get-Item -LiteralPath $OutputFullPath
Remove-PathInsideProject $Stage

$Bundle | Select-Object FullName, Length, LastWriteTime
