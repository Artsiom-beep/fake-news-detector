[CmdletBinding()]
param(
  [string]$ExePath = "dist\FakeNewsDetector\FakeNewsDetector.exe",
  [string]$ZipPath = "dist\FakeNewsDetector-Windows-Portable.zip",
  [string]$OutputDir = "outputs\desktop_package",
  [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ExeFullPath = Join-Path $ProjectRoot $ExePath
$ZipFullPath = Join-Path $ProjectRoot $ZipPath
$OutputFullDir = Join-Path $ProjectRoot $OutputDir
$JsonOut = Join-Path $OutputFullDir "DESKTOP_PACKAGE_VERIFICATION.json"
$MarkdownOut = Join-Path $OutputFullDir "DESKTOP_PACKAGE_VERIFICATION.md"
$SmokeStdout = Join-Path $OutputFullDir "desktop_package_smoke.stdout.log"
$SmokeStderr = Join-Path $OutputFullDir "desktop_package_smoke.stderr.log"

function Get-FileStatus {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    return [ordered]@{ exists = $false; path = $Path; size_bytes = 0; sha256 = "" }
  }
  $Item = Get-Item -LiteralPath $Path
  $Hash = Get-FileHash -LiteralPath $Item.FullName -Algorithm SHA256
  return [ordered]@{
    exists = $true
    path = $Item.FullName
    size_bytes = $Item.Length
    sha256 = $Hash.Hash
  }
}

New-Item -ItemType Directory -Force -Path $OutputFullDir | Out-Null

$ExeStatus = Get-FileStatus $ExeFullPath
$ZipStatus = Get-FileStatus $ZipFullPath
$ZipEntryCount = 0
$RequiredZipEntries = @("FakeNewsDetector/FakeNewsDetector.exe")
$MissingZipEntries = New-Object System.Collections.Generic.List[string]
$ForbiddenZipEntries = New-Object System.Collections.Generic.List[string]
$ForbiddenPackages = @(
  "torch",
  "torchvision",
  "transformers",
  "datasets",
  "pandas",
  "pyarrow",
  "sklearn",
  "huggingface_hub",
  "tokenizers",
  "safetensors"
)
$SmokeExitCode = $null
$SmokeOk = $false
$SmokeOutputOk = $false
$ErrorMessage = ""

try {
  if (-not $ExeStatus.exists) {
    throw "Desktop executable not found: $ExeFullPath"
  }
  if (-not $ZipStatus.exists) {
    throw "Desktop portable zip not found: $ZipFullPath"
  }

  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipFullPath)
  try {
    $Entries = @($Archive.Entries | ForEach-Object { $_.FullName.Replace("\", "/") })
    $ZipEntryCount = $Entries.Count
    foreach ($RequiredEntry in $RequiredZipEntries) {
      if ($Entries -notcontains $RequiredEntry) {
        $MissingZipEntries.Add($RequiredEntry)
      }
    }
    foreach ($Entry in $Entries) {
      foreach ($Package in $ForbiddenPackages) {
        if (
          $Entry -like "FakeNewsDetector/_internal/$Package/*" -or
          $Entry -like "FakeNewsDetector/_internal/$Package-*.dist-info/*" -or
          $Entry -like "FakeNewsDetector/_internal/$Package*.pyd"
        ) {
          $ForbiddenZipEntries.Add($Entry)
          break
        }
      }
    }
  } finally {
    $Archive.Dispose()
  }

  if ($MissingZipEntries.Count -gt 0) {
    throw "Desktop portable zip is missing required entries: $($MissingZipEntries -join ', ')"
  }
  if ($ForbiddenZipEntries.Count -gt 0) {
    throw "Desktop portable zip contains forbidden heavy packages: $($ForbiddenZipEntries[0])"
  }

  Remove-Item -LiteralPath $SmokeStdout, $SmokeStderr -Force -ErrorAction SilentlyContinue
  $Process = Start-Process `
    -FilePath $ExeFullPath `
    -ArgumentList @("--smoke", "--port", "0") `
    -WorkingDirectory (Split-Path -Parent $ExeFullPath) `
    -RedirectStandardOutput $SmokeStdout `
    -RedirectStandardError $SmokeStderr `
    -WindowStyle Hidden `
    -PassThru

  $Exited = $Process.WaitForExit($TimeoutSeconds * 1000)
  if (-not $Exited) {
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    throw "Desktop packaged smoke timed out after $TimeoutSeconds seconds"
  }

  $Process.Refresh()
  $SmokeExitCode = $Process.ExitCode
  $SmokeOutput = if (Test-Path $SmokeStdout) { Get-Content $SmokeStdout -Raw } else { "" }
  $SmokeOutputOk = ($SmokeOutput -match "Smoke OK:")
  if (-not $SmokeOutputOk) {
    throw "Desktop packaged smoke did not print Smoke OK"
  }
  if ($null -ne $SmokeExitCode -and $SmokeExitCode -ne 0) {
    throw "Desktop packaged smoke failed with exit code $SmokeExitCode"
  }
  $SmokeOk = $true
} catch {
  $ErrorMessage = $_.Exception.Message
  throw
} finally {
  $Ok = (
    $ExeStatus.exists -and
    $ZipStatus.exists -and
    $MissingZipEntries.Count -eq 0 -and
    $ForbiddenZipEntries.Count -eq 0 -and
    $SmokeOk
  )
  $Report = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    ok = $Ok
    executable = $ExeStatus
    zip = $ZipStatus
    zip_entry_count = $ZipEntryCount
    missing_zip_entries = @($MissingZipEntries)
    forbidden_zip_entries = @($ForbiddenZipEntries)
    smoke = [ordered]@{
      ok = $SmokeOk
      exit_code = $SmokeExitCode
      output_has_smoke_ok = $SmokeOutputOk
      timeout_seconds = $TimeoutSeconds
      stdout = $SmokeStdout
      stderr = $SmokeStderr
    }
    error = $ErrorMessage
  }
  $Report | ConvertTo-Json -Depth 8 | Set-Content -Path $JsonOut -Encoding UTF8
  @(
    "# Verity Lens Desktop Package Verification",
    "",
    "- Generated: ``$($Report.generated_at)``",
    "- OK: ``$($Report.ok)``",
    "- Exe: ``$($Report.executable.path)`` exists=``$($Report.executable.exists)``",
    "- Exe SHA256: ``$($Report.executable.sha256)``",
    "- Zip: ``$($Report.zip.path)`` exists=``$($Report.zip.exists)``",
    "- Zip SHA256: ``$($Report.zip.sha256)``",
    "- Zip size bytes: ``$($Report.zip.size_bytes)``",
    "- Zip entry count: ``$($Report.zip_entry_count)``",
    "- Missing zip entries: ``$($Report.missing_zip_entries -join ', ')``",
    "- Forbidden zip entries: ``$($Report.forbidden_zip_entries.Count)``",
    "- Packaged smoke OK: ``$($Report.smoke.ok)``",
    "- Packaged smoke exit code: ``$($Report.smoke.exit_code)``",
    "- Packaged smoke output has Smoke OK: ``$($Report.smoke.output_has_smoke_ok)``",
    "- Error: ``$($Report.error)``",
    "- Stdout log: ``$($Report.smoke.stdout)``",
    "- Stderr log: ``$($Report.smoke.stderr)``"
  ) | Set-Content -Path $MarkdownOut -Encoding UTF8
}

Write-Host "Desktop package verification JSON: $JsonOut" -ForegroundColor Green
Write-Host "Desktop package verification report: $MarkdownOut" -ForegroundColor Green
