[CmdletBinding()]
param(
  [string]$ApkPath = "outputs\phone_download\VerityLens-internet.apk",
  [string]$ApiBaseUrl = "",
  [ValidateSet("", "debug", "release")]
  [string]$ExpectedMode = "",
  [switch]$RequireHttps,
  [switch]$PermanentCloud,
  [switch]$AllowTemporaryTunnelApiFailure,
  [string]$StatusPath = "outputs\phone_download\PHONE_BUILD_STATUS.md",
  [string]$OutJson = "outputs\phone_download\PHONE_APK_VERIFICATION.json",
  [string]$OutMarkdown = "outputs\phone_download\PHONE_APK_VERIFICATION.md"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "cloud_url_policy.ps1")
$FlutterRoot = Join-Path $ProjectRoot "apps\fake_news_detector_flutter"
. (Join-Path $FlutterRoot "tool\flutter_source_stamp.ps1")
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Resolve-ProjectPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  if ([System.IO.Path]::IsPathRooted($Path)) {
    return $Path
  }
  return (Join-Path $ProjectRoot $Path)
}

function Normalize-ApiUrl {
  param([string]$Value)
  $Trimmed = $Value.Trim().TrimEnd("/")
  if (-not $Trimmed) {
    throw "API URL is required. Pass -ApiBaseUrl or create the APK-specific api-url sidecar next to the APK."
  }
  $Uri = $null
  if (-not [System.Uri]::TryCreate($Trimmed, [System.UriKind]::Absolute, [ref]$Uri)) {
    throw "API URL must be absolute, for example https://your-api.onrender.com"
  }
  if ($PermanentCloud) {
    $Trimmed = Assert-PermanentCloudApiUrl -Value $Trimmed -Purpose "Permanent cloud APK verification API"
    [void][System.Uri]::TryCreate($Trimmed, [System.UriKind]::Absolute, [ref]$Uri)
  }
  if ($RequireHttps -and $Uri.Scheme -ne "https") {
    throw "APK verification requires an https API URL."
  }
  return [ordered]@{ value = $Trimmed; uri = $Uri }
}

function Test-Api {
  param(
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [int]$Attempts = 4,
    [int]$RetryDelaySeconds = 2
  )
  $Out = [ordered]@{
    health = "failed"
    ready = "failed"
    fake_probe = "failed"
    ok = $false
    error = ""
    attempts = 0
  }

  $TotalAttempts = [Math]::Max(1, $Attempts)
  for ($Attempt = 1; $Attempt -le $TotalAttempts; $Attempt++) {
    $Out.attempts = $Attempt
    try {
      $Health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 30
      $Ready = Invoke-RestMethod -Uri "$BaseUrl/ready" -TimeoutSec 30
      $Probe = Invoke-RestMethod `
        -Uri "$BaseUrl/factcheck" `
        -Method Post `
        -ContentType "application/json" `
        -Body (@{ text = "Elephants are insects." } | ConvertTo-Json -Compress) `
        -TimeoutSec 90
      $Out.health = $Health.status
      $Out.ready = $Ready.status
      $Out.fake_probe = "$($Probe.verdict) / $($Probe.confidence)"
      $Out.ok = ($Health.status -eq "ok" -and $Ready.status -eq "ready" -and $Probe.verdict -eq "fake")
      if ($Out.ok) {
        $Out.error = ""
        return $Out
      }
      $Out.error = "expected health=ok, ready=ready and fake probe verdict=fake"
    } catch {
      $Out.health = "failed"
      $Out.ready = "failed"
      $Out.fake_probe = "failed"
      $Out.error = $_.Exception.Message
    }

    if ($Attempt -lt $TotalAttempts) {
      Start-Sleep -Seconds $RetryDelaySeconds
    }
  }

  return $Out
}

function Find-ApkApiUrlMatches {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$ExpectedUrl
  )

  $Matches = @()
  $Zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
  try {
    foreach ($Entry in $Zip.Entries) {
      $ShouldScan = (
        $Entry.FullName -like "lib/*/libapp.so" -or
        $Entry.FullName -like "assets/flutter_assets/*" -or
        $Entry.FullName -eq "AndroidManifest.xml" -or
        $Entry.FullName -eq "resources.arsc"
      )
      if (-not $ShouldScan -or $Entry.Length -le 0 -or $Entry.Length -gt 100MB) {
        continue
      }

      $Stream = $Entry.Open()
      try {
        $Memory = New-Object System.IO.MemoryStream
        $Stream.CopyTo($Memory)
        $Bytes = $Memory.ToArray()
        $Utf8Text = [System.Text.Encoding]::UTF8.GetString($Bytes)
        $Utf16Text = [System.Text.Encoding]::Unicode.GetString($Bytes)
        $Utf8Match = $Utf8Text.Contains($ExpectedUrl)
        $Utf16Match = $Utf16Text.Contains($ExpectedUrl)
        if ($Utf8Match -or $Utf16Match) {
          $Matches += [ordered]@{
            entry = $Entry.FullName
            utf8 = $Utf8Match
            utf16 = $Utf16Match
            size_bytes = $Entry.Length
          }
        }
      } finally {
        $Stream.Dispose()
      }
    }
  } finally {
    $Zip.Dispose()
  }
  return $Matches
}

$ResolvedApk = Resolve-ProjectPath $ApkPath
if (-not (Test-Path $ResolvedApk)) {
  throw "APK not found: $ResolvedApk"
}

$ApkBaseName = [System.IO.Path]::GetFileNameWithoutExtension($ResolvedApk)
if (-not $ApiBaseUrl.Trim()) {
  $UrlFile = Join-Path (Split-Path -Parent $ResolvedApk) "$ApkBaseName-api-url.txt"
  if (Test-Path $UrlFile) {
    $ApiBaseUrl = Get-Content $UrlFile -Raw
  }
}

$Api = Normalize-ApiUrl $ApiBaseUrl
$ApiUrl = $Api.value
$ApiHost = $Api.uri.Host
$IsTemporaryTunnel = Test-TemporaryTunnelHost -HostName $ApiHost
$Apk = Get-Item -LiteralPath $ResolvedApk
$Hash = Get-FileHash -LiteralPath $Apk.FullName -Algorithm SHA256
$ResolvedStatusPath = Resolve-ProjectPath $StatusPath
$StatusText = if (Test-Path $ResolvedStatusPath) { Get-Content $ResolvedStatusPath -Raw } else { "" }
$StatusMatchesUrl = if ($StatusText) { $StatusText.Contains($ApiUrl) } else { $false }
$StatusMatchesMode = if ($ExpectedMode) { $StatusText.Contains("APK mode: ``$ExpectedMode``") } else { $true }
$CurrentSourceStamp = Get-FlutterSourceStamp -FlutterRoot $FlutterRoot
$SourceStampPath = Join-Path (Split-Path -Parent $ResolvedApk) "$ApkBaseName-flutter-source-stamp.json"
$BuildSourceStamp = $null
if (Test-Path $SourceStampPath) {
  $BuildSourceStamp = Get-Content $SourceStampPath -Raw | ConvertFrom-Json
}
$BuildSourceSha = if ($BuildSourceStamp -and $BuildSourceStamp.sha256) { ([string]$BuildSourceStamp.sha256).ToUpperInvariant() } else { "" }
$CurrentSourceSha = ([string]$CurrentSourceStamp.sha256).ToUpperInvariant()
$SourceStampMatches = ($BuildSourceSha -and $BuildSourceSha -eq $CurrentSourceSha)
$StatusMatchesSourceStamp = if ($StatusText) { $StatusText.Contains("Flutter source SHA256: ``$CurrentSourceSha``") } else { $false }
$ApiCheck = Test-Api $ApiUrl
$EmbeddedApiMatches = @(Find-ApkApiUrlMatches -Path $Apk.FullName -ExpectedUrl $ApiUrl)
$EmbeddedApiMatchesUrl = $EmbeddedApiMatches.Count -gt 0

$BinaryEvidenceOk = (
  $Apk.Length -gt 0 -and
  $StatusMatchesUrl -and
  $StatusMatchesMode -and
  $SourceStampMatches -and
  $StatusMatchesSourceStamp -and
  $EmbeddedApiMatchesUrl
)
$TemporaryTunnelApiFailureAllowed = (
  [bool]$AllowTemporaryTunnelApiFailure -and
  -not [bool]$PermanentCloud -and
  [bool]$IsTemporaryTunnel -and
  [bool]$BinaryEvidenceOk -and
  -not [bool]$ApiCheck.ok
)

$Ok = (
  [bool]$BinaryEvidenceOk -and
  ([bool]$ApiCheck.ok -or [bool]$TemporaryTunnelApiFailureAllowed)
)

$Result = [ordered]@{
  generated_at = (Get-Date).ToString("o")
  ok = $Ok
  binary_evidence_ok = $BinaryEvidenceOk
  temporary_tunnel_api_failure_allowed = $TemporaryTunnelApiFailureAllowed
  apk = [ordered]@{
    path = $Apk.FullName
    size_bytes = $Apk.Length
    modified_at = $Apk.LastWriteTime.ToString("o")
    sha256 = $Hash.Hash
    expected_mode = $ExpectedMode
  }
  api = [ordered]@{
    base_url = $ApiUrl
    host = $ApiHost
    is_temporary_tunnel = $IsTemporaryTunnel
    health = $ApiCheck.health
    ready = $ApiCheck.ready
    fake_probe = $ApiCheck.fake_probe
    attempts = $ApiCheck.attempts
    ok = $ApiCheck.ok
    error = $ApiCheck.error
  }
  status_file = [ordered]@{
    path = $ResolvedStatusPath
    exists = [bool]$StatusText
    matches_url = $StatusMatchesUrl
    matches_mode = $StatusMatchesMode
    matches_flutter_source_stamp = $StatusMatchesSourceStamp
  }
  flutter_source_stamp = [ordered]@{
    sidecar_path = $SourceStampPath
    sidecar_exists = [bool]$BuildSourceStamp
    current_sha256 = $CurrentSourceSha
    build_sha256 = $BuildSourceSha
    current_file_count = $CurrentSourceStamp.file_count
    build_file_count = if ($BuildSourceStamp -and $BuildSourceStamp.file_count) { [int]$BuildSourceStamp.file_count } else { 0 }
    matches_current_source = $SourceStampMatches
  }
  embedded_api_url = [ordered]@{
    expected_url = $ApiUrl
    found = $EmbeddedApiMatchesUrl
    match_count = $EmbeddedApiMatches.Count
    matching_entries = $EmbeddedApiMatches
  }
}

$OutJsonPath = Resolve-ProjectPath $OutJson
$OutMarkdownPath = Resolve-ProjectPath $OutMarkdown
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutJsonPath), (Split-Path -Parent $OutMarkdownPath) | Out-Null
$Result | ConvertTo-Json -Depth 8 | Set-Content -Path $OutJsonPath -Encoding UTF8

@(
  "# Verity Lens APK Verification",
  "",
  "- Generated: ``$($Result.generated_at)``",
  "- OK: ``$($Result.ok)``",
  "- Binary evidence OK: ``$($Result.binary_evidence_ok)``",
  "- Temporary tunnel API failure allowed: ``$($Result.temporary_tunnel_api_failure_allowed)``",
  "- APK: ``$($Result.apk.path)``",
  "- APK size bytes: ``$($Result.apk.size_bytes)``",
  "- APK SHA256: ``$($Result.apk.sha256)``",
  "- Expected mode: ``$($Result.apk.expected_mode)``",
  "- API: ``$($Result.api.base_url)``",
  "- Temporary tunnel URL: ``$($Result.api.is_temporary_tunnel)``",
  "- Health: ``$($Result.api.health)``",
  "- Ready: ``$($Result.api.ready)``",
  "- Fake probe: ``$($Result.api.fake_probe)``",
  "- API probe attempts: ``$($Result.api.attempts)``",
  "- API error: ``$($Result.api.error)``",
  "- Status file matches URL: ``$($Result.status_file.matches_url)``",
  "- Status file matches mode: ``$($Result.status_file.matches_mode)``",
  "- Status file matches Flutter source stamp: ``$($Result.status_file.matches_flutter_source_stamp)``",
  "- Flutter source stamp sidecar exists: ``$($Result.flutter_source_stamp.sidecar_exists)``",
  "- Flutter source SHA256 in APK build: ``$($Result.flutter_source_stamp.build_sha256)``",
  "- Current Flutter source SHA256: ``$($Result.flutter_source_stamp.current_sha256)``",
  "- Flutter source stamp matches current source: ``$($Result.flutter_source_stamp.matches_current_source)``",
  "- APK contains expected API URL: ``$($Result.embedded_api_url.found)``",
  "- APK API URL match count: ``$($Result.embedded_api_url.match_count)``"
) | Set-Content -Path $OutMarkdownPath -Encoding UTF8

Write-Host "APK verification JSON: $OutJsonPath" -ForegroundColor Green
Write-Host "APK verification report: $OutMarkdownPath" -ForegroundColor Green

if (-not $Ok) {
  exit 1
}
