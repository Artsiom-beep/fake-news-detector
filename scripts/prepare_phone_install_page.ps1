[CmdletBinding()]
param(
  [string]$LanIp = "",
  [int]$Port = 8010,
  [string]$ApkName = "VerityLens-internet.apk",
  [switch]$StartServer,
  [switch]$Restart
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}

$DownloadDir = Join-Path $ProjectRoot "outputs\phone_download"
$OutputsDir = Join-Path $ProjectRoot "outputs"
$IndexPath = Join-Path $DownloadDir "index.html"
$JsonPath = Join-Path $DownloadDir "PHONE_INSTALL_PAGE.json"
$MarkdownPath = Join-Path $DownloadDir "PHONE_INSTALL_PAGE.md"
$ServerPidPath = Join-Path $OutputsDir "phone_download_server_pid.txt"
$ApkPath = Join-Path $DownloadDir $ApkName
$CloudApkName = "VerityLens-cloud.apk"
$CloudApkPath = Join-Path $DownloadDir $CloudApkName

function Get-DefaultLanIp {
  $Candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*" -and
      $_.PrefixOrigin -ne "WellKnown" -and
      $_.InterfaceAlias -notmatch "Loopback|vEthernet|Virtual|VMware|VirtualBox|WSL|Tailscale"
    } |
    Sort-Object InterfaceMetric, InterfaceIndex
  if ($Candidates) {
    return $Candidates[0].IPAddress
  }
  throw "Could not detect a LAN IPv4 address. Pass -LanIp manually, for example -LanIp 192.168.1.16."
}

function Html {
  param([object]$Value)
  return [System.Net.WebUtility]::HtmlEncode([string]$Value)
}

function Read-JsonFile {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    return $null
  }
  try {
    return Get-Content $Path -Raw | ConvertFrom-Json
  } catch {
    return $null
  }
}

function Stop-RecordedServer {
  try {
    if (Test-Path $ServerPidPath) {
      $ProcessId = [int](Get-Content $ServerPidPath -Raw).Trim()
      $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
      if ($ProcessInfo -and $ProcessInfo.CommandLine -match "http\.server") {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
      }
    }
  } catch {
    # Ignore stale metadata.
  }

  $EscapedDir = [regex]::Escape($DownloadDir)
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.CommandLine -match "http\.server\s+$Port" -and
      $_.CommandLine -match $EscapedDir
    } |
    ForEach-Object {
      Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue
    }
}

function Test-HttpStatusCode {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSec = 5
  )

  $Request = [System.Net.HttpWebRequest]::Create($Url)
  $Request.Method = "GET"
  $Request.Timeout = $TimeoutSec * 1000
  $Request.AllowAutoRedirect = $true
  $Response = $null
  try {
    $Response = [System.Net.HttpWebResponse]$Request.GetResponse()
    return [int]$Response.StatusCode
  } finally {
    if ($Response) {
      $Response.Dispose()
    }
  }
}

New-Item -ItemType Directory -Force -Path $DownloadDir, $OutputsDir | Out-Null

if (-not (Test-Path $ApkPath)) {
  throw "APK not found: $ApkPath"
}

if (-not $LanIp.Trim()) {
  $LanIp = Get-DefaultLanIp
}

$ParsedIp = $null
if (-not [System.Net.IPAddress]::TryParse($LanIp, [ref]$ParsedIp) -or $ParsedIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
  throw "LAN IP must be an IPv4 address, got '$LanIp'."
}

$Apk = Get-Item -LiteralPath $ApkPath
$ApkHash = Get-FileHash -LiteralPath $Apk.FullName -Algorithm SHA256
$Verification = Read-JsonFile (Join-Path $DownloadDir "PHONE_APK_VERIFICATION.json")
$CloudVerification = Read-JsonFile (Join-Path $DownloadDir "PHONE_CLOUD_APK_VERIFICATION.json")
$Readiness = Read-JsonFile (Join-Path $DownloadDir "phone_readiness.json")
$PublicApiUrl = ""
$PublicApiUrlPath = Join-Path $ProjectRoot "outputs\public_api_url.txt"
if (Test-Path $PublicApiUrlPath) {
  $PublicApiUrl = (Get-Content $PublicApiUrlPath -Raw).Trim()
}
$CloudApiUrl = ""
$CloudApiUrlPath = Join-Path $DownloadDir "VerityLens-cloud-api-url.txt"
if (Test-Path $CloudApiUrlPath) {
  $CloudApiUrl = (Get-Content $CloudApiUrlPath -Raw).Trim()
}

$PageUrl = "http://$LanIp`:$Port/index.html"
$DownloadUrl = "http://$LanIp`:$Port/$ApkName"
$CloudDownloadUrl = "http://$LanIp`:$Port/$CloudApkName"
$GeneratedAt = (Get-Date).ToString("o")
$ApiOk = if ($Verification) { [bool]$Verification.api.ok } else { $false }
$VerificationOk = if ($Verification) { [bool]$Verification.ok } else { $false }
$CloudApkExists = Test-Path $CloudApkPath
$CloudVerificationOk = if ($CloudVerification) { [bool]$CloudVerification.ok } else { $false }
$TemporaryPhoneReady = if ($Readiness) { [bool]$Readiness.ready.phone_temporary_tunnel } else { $false }
$PermanentPhoneReady = if ($Readiness) { [bool]$Readiness.ready.phone_permanent_cloud } else { $false }
$CloudVerificationReleaseMode = if ($CloudVerification -and $CloudVerification.apk) {
  [string]$CloudVerification.apk.expected_mode -eq "release"
} else {
  $false
}
$CloudVerificationApiOk = if ($CloudVerification -and $CloudVerification.api) {
  [bool]$CloudVerification.api.ok
} else {
  $false
}
$CloudVerificationEmbeddedUrl = if ($CloudVerification -and $CloudVerification.embedded_api_url) {
  [bool]$CloudVerification.embedded_api_url.found
} else {
  $false
}
$CloudVerificationSourceFresh = if ($CloudVerification -and $CloudVerification.flutter_source_stamp -and $CloudVerification.status_file) {
  [bool]$CloudVerification.flutter_source_stamp.sidecar_exists -and
    [bool]$CloudVerification.flutter_source_stamp.matches_current_source -and
    [bool]$CloudVerification.status_file.matches_flutter_source_stamp
} else {
  $false
}
$CloudApkDownloadReady = (
  $CloudApkExists -and
  $CloudVerificationOk -and
  $CloudVerificationReleaseMode -and
  $CloudVerificationApiOk -and
  $CloudVerificationEmbeddedUrl -and
  $CloudVerificationSourceFresh -and
  $PermanentPhoneReady
)
$CloudApkSection = ""
$CloudReportLink = ""
$CloudMarkdownDownload = if ($CloudApkDownloadReady) { $CloudDownloadUrl } else { "" }
$CloudMarkdownLines = @(
  "- Cloud APK available: ``$CloudApkExists``",
  "- Cloud APK verification OK: ``$CloudVerificationOk``",
  "- Cloud APK release mode: ``$CloudVerificationReleaseMode``",
  "- Cloud APK source stamp current: ``$CloudVerificationSourceFresh``",
  "- Cloud APK download ready: ``$CloudApkDownloadReady``",
  "- Cloud APK download: ``$CloudMarkdownDownload``",
  "- Cloud API: ``$CloudApiUrl``"
)
$CloudApkReport = [ordered]@{
  exists = $CloudApkExists
  download_ready = $CloudApkDownloadReady
  download_url = if ($CloudApkDownloadReady) { $CloudDownloadUrl } else { "" }
  api_url = $CloudApiUrl
  verification_ok = $CloudVerificationOk
  release_mode = $CloudVerificationReleaseMode
  api_ok = $CloudVerificationApiOk
  embedded_api_url_found = $CloudVerificationEmbeddedUrl
  source_stamp_current = $CloudVerificationSourceFresh
  permanent_phone_ready = $PermanentPhoneReady
  path = ""
  name = ""
  size_bytes = 0
  sha256 = ""
}
if ($CloudApkExists) {
  $CloudApk = Get-Item -LiteralPath $CloudApkPath
  $CloudApkHash = Get-FileHash -LiteralPath $CloudApk.FullName -Algorithm SHA256
  $CloudApkReport["path"] = $CloudApk.FullName
  $CloudApkReport["name"] = $CloudApk.Name
  $CloudApkReport["size_bytes"] = $CloudApk.Length
  $CloudApkReport["sha256"] = $CloudApkHash.Hash
  if ($CloudApkDownloadReady) {
    $CloudApkSection = @"
    <section class="panel">
      <h2>Permanent Cloud APK</h2>
      <p><a class="download secondary" href="$(Html $CloudApkName)" download>Download Permanent Cloud APK</a></p>
      <div class="meta">
        <div class="label">File</div><div><code>$(Html $CloudApk.Name)</code></div>
        <div class="label">Size bytes</div><div><code>$(Html $CloudApk.Length)</code></div>
        <div class="label">SHA256</div><div><code>$(Html $CloudApkHash.Hash)</code></div>
        <div class="label">Cloud API URL</div><div><code>$(Html $CloudApiUrl)</code></div>
        <div class="label">Cloud APK verification</div><div class="$(if ($CloudVerificationOk) { "ok" } else { "warn" })">$(Html $CloudVerificationOk)</div>
        <div class="label">Cloud APK download ready</div><div class="ok">$(Html $CloudApkDownloadReady)</div>
      </div>
    </section>
"@
  }
}
if (Test-Path (Join-Path $DownloadDir "PHONE_CLOUD_APK_VERIFICATION.md")) {
  $CloudReportLink = '      <p><a href="PHONE_CLOUD_APK_VERIFICATION.md">Cloud APK verification</a></p>'
}

$HtmlText = @"
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Verity Lens Phone Install</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, -apple-system, Segoe UI, sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #17202a; }
    main { max-width: 780px; margin: 0 auto; padding: 28px 18px 40px; }
    h1 { font-size: 30px; margin: 0 0 8px; }
    h2 { font-size: 18px; margin: 26px 0 10px; }
    p { line-height: 1.5; }
    .panel { background: #ffffff; border: 1px solid #d9dee7; border-radius: 8px; padding: 18px; margin-top: 16px; }
    .download { display: inline-block; background: #0f766e; color: white; padding: 14px 18px; border-radius: 7px; text-decoration: none; font-weight: 700; }
    .download.secondary { background: #1d4ed8; }
    .meta { display: grid; grid-template-columns: minmax(130px, 220px) 1fr; gap: 8px 14px; font-size: 14px; }
    .label { color: #51606f; }
    code { overflow-wrap: anywhere; word-break: break-word; }
    .ok { color: #0f766e; font-weight: 700; }
    .warn { color: #a15c00; font-weight: 700; }
    @media (prefers-color-scheme: dark) {
      body { background: #101418; color: #eef2f7; }
      .panel { background: #171d23; border-color: #2d3742; }
      .label { color: #aab6c3; }
      .download { background: #14b8a6; color: #081012; }
      .download.secondary { background: #93c5fd; color: #081012; }
    }
  </style>
</head>
<body>
  <main>
    <h1>Verity Lens</h1>
    <p>Phone install page for the current APK build.</p>

    <section class="panel">
      <a class="download" href="$(Html $ApkName)" download>Download Current Android APK</a>
      <p>After downloading, Android may ask you to allow installing apps from this browser.</p>
    </section>

    <section class="panel">
      <h2>Status</h2>
      <div class="meta">
        <div class="label">Generated</div><div><code>$(Html $GeneratedAt)</code></div>
        <div class="label">APK verification</div><div class="$(if ($VerificationOk) { "ok" } else { "warn" })">$(Html $VerificationOk)</div>
        <div class="label">Backend verified</div><div class="$(if ($ApiOk) { "ok" } else { "warn" })">$(Html $ApiOk)</div>
        <div class="label">Temporary phone ready</div><div class="$(if ($TemporaryPhoneReady) { "ok" } else { "warn" })">$(Html $TemporaryPhoneReady)</div>
        <div class="label">Permanent cloud phone</div><div class="$(if ($PermanentPhoneReady) { "ok" } else { "warn" })">$(Html $PermanentPhoneReady)</div>
        <div class="label">Cloud APK available</div><div class="$(if ($CloudApkExists) { "ok" } else { "warn" })">$(Html $CloudApkExists)</div>
        <div class="label">Cloud APK verification</div><div class="$(if ($CloudVerificationOk) { "ok" } else { "warn" })">$(Html $CloudVerificationOk)</div>
        <div class="label">Cloud APK release mode</div><div class="$(if ($CloudVerificationReleaseMode) { "ok" } else { "warn" })">$(Html $CloudVerificationReleaseMode)</div>
        <div class="label">Cloud APK source current</div><div class="$(if ($CloudVerificationSourceFresh) { "ok" } else { "warn" })">$(Html $CloudVerificationSourceFresh)</div>
        <div class="label">Cloud APK download ready</div><div class="$(if ($CloudApkDownloadReady) { "ok" } else { "warn" })">$(Html $CloudApkDownloadReady)</div>
      </div>
    </section>

    <section class="panel">
      <h2>APK</h2>
      <div class="meta">
        <div class="label">File</div><div><code>$(Html $Apk.Name)</code></div>
        <div class="label">Size bytes</div><div><code>$(Html $Apk.Length)</code></div>
        <div class="label">SHA256</div><div><code>$(Html $ApkHash.Hash)</code></div>
      </div>
    </section>

$CloudApkSection

    <section class="panel">
      <h2>Backend</h2>
      <div class="meta">
        <div class="label">API URL</div><div><code>$(Html $PublicApiUrl)</code></div>
        <div class="label">Health</div><div><code>$(Html $(if ($Verification) { $Verification.api.health } else { "not checked" }))</code></div>
        <div class="label">Ready</div><div><code>$(Html $(if ($Verification) { $Verification.api.ready } else { "not checked" }))</code></div>
        <div class="label">Probe</div><div><code>$(Html $(if ($Verification) { $Verification.api.fake_probe } else { "not checked" }))</code></div>
      </div>
    </section>

    <section class="panel">
      <h2>Reports</h2>
      <p><a href="PHONE_APK_VERIFICATION.md">APK verification</a></p>
$CloudReportLink
      <p><a href="PHONE_READINESS.md">Phone readiness</a></p>
      <p><a href="PHONE_BUILD_STATUS.md">Build status</a></p>
    </section>
  </main>
</body>
</html>
"@

Set-Content -Path $IndexPath -Value $HtmlText -Encoding UTF8

$Report = [ordered]@{
  generated_at = $GeneratedAt
  page_url = $PageUrl
  download_url = $DownloadUrl
  lan_ip = $LanIp
  port = $Port
  apk = [ordered]@{
    path = $Apk.FullName
    name = $Apk.Name
    size_bytes = $Apk.Length
    sha256 = $ApkHash.Hash
  }
  api = [ordered]@{
    public_api_url = $PublicApiUrl
    verification_ok = $VerificationOk
    backend_ok = $ApiOk
  }
  cloud_apk = $CloudApkReport
  readiness = [ordered]@{
    temporary_phone_ready = $TemporaryPhoneReady
    permanent_cloud_phone = $PermanentPhoneReady
  }
}
$Report | ConvertTo-Json -Depth 8 | Set-Content -Path $JsonPath -Encoding UTF8

@(
  "# Verity Lens Phone Install Page",
  "",
  "- Generated: ``$GeneratedAt``",
  "- Install page: ``$PageUrl``",
  "- APK download: ``$DownloadUrl``",
  "- APK: ``$($Apk.FullName)``",
  "- APK size bytes: ``$($Apk.Length)``",
  "- APK SHA256: ``$($ApkHash.Hash)``",
  "- API: ``$PublicApiUrl``",
  "- APK verification OK: ``$VerificationOk``",
  "- Backend verification OK: ``$ApiOk``",
  "- Temporary phone ready: ``$TemporaryPhoneReady``",
  "- Permanent cloud phone: ``$PermanentPhoneReady``"
) | Set-Content -Path $MarkdownPath -Encoding UTF8

Add-Content -Path $MarkdownPath -Value $CloudMarkdownLines -Encoding UTF8

if ($Restart) {
  Stop-RecordedServer
}

if ($StartServer) {
  $Existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($Existing) {
    Write-Host "A server is already listening on port $Port; using existing listener." -ForegroundColor Yellow
  } else {
    $ServerProcess = Start-Process `
      -FilePath $Python `
      -ArgumentList @("-m", "http.server", "$Port", "--bind", "0.0.0.0", "--directory", $DownloadDir) `
      -WorkingDirectory $ProjectRoot `
      -RedirectStandardOutput (Join-Path $OutputsDir "phone-download-server.log") `
      -RedirectStandardError (Join-Path $OutputsDir "phone-download-server.err.log") `
      -WindowStyle Hidden `
      -PassThru
    $ServerProcess.Id | Set-Content -Path $ServerPidPath -Encoding UTF8

    for ($i = 0; $i -lt 20; $i++) {
      Start-Sleep -Milliseconds 500
      try {
        if ((Test-HttpStatusCode -Url "http://127.0.0.1:$Port/index.html" -TimeoutSec 3) -eq 200) {
          $Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
          if ($Listener) {
            [string]$Listener.OwningProcess | Set-Content -Path $ServerPidPath -Encoding UTF8
          }
          break
        }
      } catch {
        # Keep waiting briefly.
      }
    }
  }

  if ((Test-HttpStatusCode -Url "http://127.0.0.1:$Port/index.html" -TimeoutSec 5) -ne 200) {
    throw "Phone install page server did not return HTTP 200."
  }
}

Write-Host "Phone install page: $IndexPath" -ForegroundColor Green
Write-Host "Open on phone: $PageUrl" -ForegroundColor Green
