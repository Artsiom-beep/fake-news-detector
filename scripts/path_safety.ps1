[CmdletBinding()]
param()

function ConvertTo-NormalizedFullPath {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$BasePath = ""
  )

  $Candidate = $Path
  if ($BasePath -and -not [System.IO.Path]::IsPathRooted($Candidate)) {
    $Candidate = Join-Path $BasePath $Candidate
  }

  return [System.IO.Path]::GetFullPath($Candidate).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
}

function Test-PathInsideDirectory {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Root
  )

  $FullPath = ConvertTo-NormalizedFullPath -Path $Path
  $FullRoot = ConvertTo-NormalizedFullPath -Path $Root
  $Boundary = $FullRoot + [System.IO.Path]::DirectorySeparatorChar

  return (
    $FullPath.Equals($FullRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $FullPath.StartsWith($Boundary, [System.StringComparison]::OrdinalIgnoreCase)
  )
}

function Assert-PathInsideDirectory {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Root,
    [string]$Message = "Path must stay inside project: {0}"
  )

  $FullPath = ConvertTo-NormalizedFullPath -Path $Path
  if (-not (Test-PathInsideDirectory -Path $FullPath -Root $Root)) {
    throw ($Message -f $FullPath)
  }
  return $FullPath
}

function Assert-FileNameOnly {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Purpose = "File name"
  )

  $Trimmed = $Name.Trim()
  if (-not $Trimmed) {
    throw "$Purpose cannot be empty."
  }
  if ([System.IO.Path]::IsPathRooted($Trimmed)) {
    throw "$Purpose must be a file name, not an absolute path: $Trimmed"
  }
  if ($Trimmed -in @(".", "..")) {
    throw "$Purpose cannot be '.' or '..'."
  }
  if ([System.IO.Path]::GetFileName($Trimmed) -ne $Trimmed) {
    throw "$Purpose must not contain directory separators: $Trimmed"
  }
  foreach ($Char in [System.IO.Path]::GetInvalidFileNameChars()) {
    if ($Trimmed.IndexOf($Char) -ge 0) {
      throw "$Purpose contains an invalid file-name character: $Trimmed"
    }
  }
  return $Trimmed
}

function Assert-ApkOutputName {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Purpose = "APK output name"
  )

  $FileName = Assert-FileNameOnly -Name $Name -Purpose $Purpose
  if (-not $FileName.EndsWith(".apk", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "$Purpose must end with .apk: $FileName"
  }
  return $FileName
}

function Get-ChildPowerShellCommand {
  $Candidates = New-Object System.Collections.Generic.List[string]

  if ($PSHOME) {
    $CurrentHostName = if ($PSVersionTable.PSEdition -eq "Core") { "pwsh.exe" } else { "powershell.exe" }
    $SameHost = Join-Path $PSHOME $CurrentHostName
    if (Test-Path -LiteralPath $SameHost) {
      $Candidates.Add($SameHost) | Out-Null
    }
  }

  foreach ($Name in @("pwsh", "pwsh.exe", "powershell", "powershell.exe")) {
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($Command -and $Command.Source) {
      $Candidates.Add($Command.Source) | Out-Null
    }
  }

  foreach ($Candidate in $Candidates) {
    if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
      return $Candidate
    }
  }

  throw "No PowerShell executable was found for child script execution."
}

function Remove-PathInsideDirectory {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Root,
    [switch]$AllowRoot
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }

  $Resolved = (Resolve-Path -LiteralPath $Path).Path
  $FullPath = Assert-PathInsideDirectory `
    -Path $Resolved `
    -Root $Root `
    -Message "Refusing to remove path outside project: {0}"
  $FullRoot = ConvertTo-NormalizedFullPath -Path $Root

  if (-not $AllowRoot -and $FullPath.Equals($FullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove project root: $FullPath"
  }

  Remove-Item -LiteralPath $FullPath -Recurse -Force
}
