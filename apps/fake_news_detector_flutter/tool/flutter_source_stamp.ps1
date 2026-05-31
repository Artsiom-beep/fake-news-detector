[CmdletBinding()]
param(
  [string]$InputFlutterRoot = ""
)

$ErrorActionPreference = "Stop"

function ConvertTo-HexString {
  param([Parameter(Mandatory = $true)][byte[]]$Bytes)
  return ([System.BitConverter]::ToString($Bytes)).Replace("-", "")
}

function Get-FlutterSourceStamp {
  param([string]$FlutterRoot = "")

  if (-not $FlutterRoot.Trim()) {
    $FlutterRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
  } else {
    $FlutterRoot = (Resolve-Path $FlutterRoot).Path
  }

  $RelativePaths = New-Object "System.Collections.Generic.List[string]"
  foreach ($Path in @("pubspec.yaml", "pubspec.lock", "analysis_options.yaml", "android\app\build.gradle.kts", "android\build.gradle.kts", "android\settings.gradle.kts")) {
    if (Test-Path (Join-Path $FlutterRoot $Path)) {
      $RelativePaths.Add($Path)
    }
  }

  foreach ($Dir in @("lib", "android\app\src\main")) {
    $FullDir = Join-Path $FlutterRoot $Dir
    if (-not (Test-Path $FullDir)) {
      continue
    }
    Get-ChildItem -LiteralPath $FullDir -Recurse -File -Force |
      Where-Object {
        $_.FullName -notmatch "\\GeneratedPluginRegistrant\.[^\\]+$" -and
        $_.FullName -notmatch "\\build\\|\\.dart_tool\\|\\.gradle\\"
      } |
      ForEach-Object {
        $Relative = $_.FullName.Substring($FlutterRoot.Length).TrimStart("\")
        $RelativePaths.Add($Relative)
      }
  }

  $UniqueRelativePathSet = [System.Collections.Generic.SortedSet[string]]::new([System.StringComparer]::Ordinal)
  foreach ($RelativePath in $RelativePaths) {
    [void]$UniqueRelativePathSet.Add($RelativePath.Replace("/", "\"))
  }
  $UniqueRelativePaths = @($UniqueRelativePathSet)
  $Sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    foreach ($RelativePath in $UniqueRelativePaths) {
      $Normalized = $RelativePath.Replace("\", "/")
      $Header = [System.Text.Encoding]::UTF8.GetBytes("FILE:$Normalized`n")
      [void]$Sha.TransformBlock($Header, 0, $Header.Length, $null, 0)

      $Bytes = [System.IO.File]::ReadAllBytes((Join-Path $FlutterRoot $RelativePath))
      if ($Bytes.Length -gt 0) {
        [void]$Sha.TransformBlock($Bytes, 0, $Bytes.Length, $null, 0)
      }

      $Footer = [System.Text.Encoding]::UTF8.GetBytes("`nEND_FILE`n")
      [void]$Sha.TransformBlock($Footer, 0, $Footer.Length, $null, 0)
    }
    [void]$Sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
    return [ordered]@{
      sha256 = ConvertTo-HexString $Sha.Hash
      file_count = $UniqueRelativePaths.Count
      files = @($UniqueRelativePaths | ForEach-Object { $_.Replace("\", "/") })
    }
  } finally {
    $Sha.Dispose()
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Get-FlutterSourceStamp -FlutterRoot $InputFlutterRoot | ConvertTo-Json -Depth 4
}
