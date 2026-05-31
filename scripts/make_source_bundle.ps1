[CmdletBinding()]
param(
  [string]$OutputPath = "outputs\submission\verity-lens-source.zip"
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "path_safety.ps1")

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([System.IO.Path]::IsPathRooted($OutputPath)) {
  $OutputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
} else {
  $OutputFullPath = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutputPath))
}
$OutputFullPath = Assert-PathInsideDirectory `
  -Path $OutputFullPath `
  -Root $ProjectRoot `
  -Message "OutputPath must stay inside project: {0}"
if ($OutputFullPath.Equals((ConvertTo-NormalizedFullPath -Path $ProjectRoot), [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "OutputPath must be a file path inside project: $OutputFullPath"
}
$StageRoot = Join-Path $ProjectRoot "outputs\submission"
$Stage = Join-Path $StageRoot ("verity-lens-source-stage-" + [System.Guid]::NewGuid().ToString("N"))

function Remove-PathInsideProject {
  param([Parameter(Mandatory = $true)][string]$Path)
  Remove-PathInsideDirectory -Path $Path -Root $ProjectRoot
}

function Copy-ProjectItem {
  param(
    [Parameter(Mandatory = $true)][string]$RelativePath
  )

  $Source = Join-Path $ProjectRoot $RelativePath
  if (-not (Test-Path $Source)) {
    return
  }
  $Destination = Join-Path $Stage $RelativePath
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
  Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

function Remove-StageRelative {
  param([Parameter(Mandatory = $true)][string]$RelativePath)
  Remove-PathInsideProject (Join-Path $Stage $RelativePath)
}

function Get-StageRelativePath {
  param([Parameter(Mandatory = $true)][string]$Path)
  return $Path.Substring($Stage.Length).TrimStart("\").Replace("\", "/")
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFullPath) | Out-Null
Remove-PathInsideProject $Stage
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

$Items = @(
  ".dockerignore",
  ".env.example",
  ".gitignore",
  "Dockerfile",
  "EVAL_WORKFLOW.md",
  "README.md",
  "RUNBOOK.md",
  "pyproject.toml",
  "render.yaml",
  "requirements.api.txt",
  "requirements.optional-ai.txt",
  "requirements.legacy-train.txt",
  "requirements.lock.txt",
  "requirements.txt",
  "run_desktop_app.bat",
  "assets",
  "config",
  "data\factcheck",
  "data\image_eval\v1",
  "docs",
  "packaging",
  "scripts",
  "src",
  "tests",
  "apps\fake_news_detector_flutter"
)

foreach ($Item in $Items) {
  Copy-ProjectItem $Item
}

$PruneRelativePaths = @(
  "apps\fake_news_detector_flutter\.dart_tool",
  "apps\fake_news_detector_flutter\.idea",
  "apps\fake_news_detector_flutter\build",
  "apps\fake_news_detector_flutter\.flutter-plugins-dependencies",
  "apps\fake_news_detector_flutter\.metadata",
  "apps\fake_news_detector_flutter\fake_news_detector_flutter.iml",
  "apps\fake_news_detector_flutter\android\local.properties",
  "apps\fake_news_detector_flutter\android\fake_news_detector_flutter_android.iml",
  "apps\fake_news_detector_flutter\android\app\src\main\java\io\flutter\plugins\GeneratedPluginRegistrant.java",
  "apps\fake_news_detector_flutter\android\.gradle",
  "apps\fake_news_detector_flutter\ios\Flutter\ephemeral",
  "apps\fake_news_detector_flutter\ios\Flutter\Generated.xcconfig",
  "apps\fake_news_detector_flutter\ios\Flutter\flutter_export_environment.sh",
  "apps\fake_news_detector_flutter\ios\Runner\GeneratedPluginRegistrant.h",
  "apps\fake_news_detector_flutter\ios\Runner\GeneratedPluginRegistrant.m",
  "docs\report\verity_lens_report.pdf",
  "docs\report\verity_lens_report.log",
  "docs\report\verity_lens_report.aux",
  "docs\report\verity_lens_report.out",
  "docs\report\verity_lens_report.toc",
  "docs\report\verity_lens_report.fls",
  "docs\report\verity_lens_report.fdb_latexmk",
  "docs\report\verity_lens_report.synctex.gz",
  "docs\report\verity_lens_report.xdv",
  "docs\report\verity_lens_report.bbl",
  "docs\report\verity_lens_report.blg",
  "docs\report\verity_lens_report.nav",
  "docs\report\verity_lens_report.snm",
  "docs\report\verity_lens_report.vrb"
)
foreach ($RelativePath in $PruneRelativePaths) {
  Remove-StageRelative $RelativePath
}

Get-ChildItem -LiteralPath $Stage -Recurse -Directory -Force |
  Where-Object {
    $Relative = Get-StageRelativePath $_.FullName
    $_.Name -in @("__pycache__", ".pytest_cache") -or
    $Relative -eq ".venv" -or $Relative -like ".venv/*" -or
    $Relative -eq "outputs" -or $Relative -like "outputs/*" -or
    $Relative -eq "dist" -or $Relative -like "dist/*" -or
    $Relative -eq "build" -or $Relative -like "build/*" -or
    $Relative -eq "archive" -or $Relative -like "archive/*" -or
    $Relative -eq "apps/fake_news_detector_flutter/build" -or
    $Relative -like "apps/fake_news_detector_flutter/build/*" -or
    $Relative -eq "apps/fake_news_detector_flutter/.dart_tool" -or
    $Relative -like "apps/fake_news_detector_flutter/.dart_tool/*"
  } |
  Sort-Object FullName -Descending |
  ForEach-Object { Remove-PathInsideProject $_.FullName }

Get-ChildItem -LiteralPath $Stage -Recurse -File -Force |
  Where-Object {
    $Relative = Get-StageRelativePath $_.FullName
    $_.Extension -in @(".pyc", ".pyo") -or
    $_.Extension -in @(".iml", ".log") -or
    $_.Name -in @(".DS_Store", "Thumbs.db") -or
    $_.Name -like "GeneratedPluginRegistrant.*" -or
    $_.FullName -match "\\(?:local\.properties|flutter_export_environment\.sh)$" -or
    (
      $Relative -like "docs/report/*" -and (
        $_.Extension -in @(".aux", ".out", ".toc", ".fls", ".fdb_latexmk", ".xdv", ".bbl", ".blg", ".nav", ".snm", ".vrb") -or
        $_.Name -like "*.synctex.gz"
      )
    )
  } |
  ForEach-Object { Remove-PathInsideProject $_.FullName }

$RequiredStageFiles = @(
  "README.md",
  "RUNBOOK.md",
  "pyproject.toml",
  "Dockerfile",
  "render.yaml",
  "src\api_factcheck.py",
  "src\factcheck\service.py",
  "scripts\cloud_url_policy.ps1",
  "scripts\path_safety.ps1",
  "scripts\verify_render_deploy_config.py",
  "scripts\run_release_gate.ps1",
  "scripts\check_final_external_prereqs.ps1",
  "scripts\audit_project_goal_completion.ps1",
  "scripts\finalize_cloud_phone_submission.ps1",
  "scripts\write_cloud_deployment_status.ps1",
  "scripts\smoke_phone_emulator.ps1",
  "scripts\make_submission_bundle.ps1",
  "tests\test_factcheck_core.py",
  "docs\report\verity_lens_report.tex",
  "apps\fake_news_detector_flutter\pubspec.yaml",
  "apps\fake_news_detector_flutter\lib\main.dart",
  "apps\fake_news_detector_flutter\lib\api_client.dart",
  "apps\fake_news_detector_flutter\tool\flutter_source_stamp.ps1",
  "apps\fake_news_detector_flutter\test\widget_test.dart"
)
foreach ($RelativePath in $RequiredStageFiles) {
  if (-not (Test-Path (Join-Path $Stage $RelativePath))) {
    throw "Source bundle staging is missing required file: $RelativePath"
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
  foreach ($RelativePath in @(
      "README.md",
      "src/api_factcheck.py",
      "scripts/cloud_url_policy.ps1",
      "scripts/path_safety.ps1",
      "scripts/verify_render_deploy_config.py",
      "scripts/check_final_external_prereqs.ps1",
      "scripts/audit_project_goal_completion.ps1",
      "scripts/finalize_cloud_phone_submission.ps1",
      "tests/test_factcheck_core.py",
      "apps/fake_news_detector_flutter/lib/main.dart"
    )) {
    if ($Entries -notcontains $RelativePath) {
      throw "Source bundle zip is missing required file: $RelativePath"
    }
  }
  $Forbidden = @(
    $Entries | Where-Object {
      $_ -like ".venv/*" -or
      $_ -like "outputs/*" -or
      $_ -like "dist/*" -or
      $_ -like "build/*" -or
      $_ -like "archive/*" -or
      $_ -like "*__pycache__*" -or
      $_ -like "*.pyc" -or
      $_ -like "*.pyo" -or
      $_ -like "*.iml" -or
      $_ -like "*.log" -or
      $_ -match "^docs/report/[^/]+\.(aux|out|toc|fls|fdb_latexmk|xdv|bbl|blg|nav|snm|vrb)$" -or
      $_ -match "^docs/report/[^/]+\.synctex\.gz$" -or
      $_ -like "*GeneratedPluginRegistrant.*" -or
      $_ -like "docs/report/verity_lens_report.pdf" -or
      $_ -like "apps/fake_news_detector_flutter/build/*" -or
      $_ -like "apps/fake_news_detector_flutter/.dart_tool/*" -or
      $_ -like "apps/fake_news_detector_flutter/android/local.properties"
    }
  )
  if ($Forbidden.Count -gt 0) {
    throw "Source bundle zip contains forbidden generated or local files: $($Forbidden[0])"
  }
}
finally {
  $Zip.Dispose()
}

$Bundle = Get-Item -LiteralPath $OutputFullPath
Remove-PathInsideProject $Stage

$Bundle | Select-Object FullName, Length, LastWriteTime
