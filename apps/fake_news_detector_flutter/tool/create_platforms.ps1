$ErrorActionPreference = "Stop"

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
  throw "Flutter is not installed or is not in PATH. Install Flutter first, then re-run this script."
}

Push-Location (Split-Path -Parent $PSScriptRoot)
try {
  flutter create --platforms=android,ios,web --project-name fake_news_detector_flutter --org com.fakenewsdetector .
  flutter pub get
  flutter doctor
}
finally {
  Pop-Location
}
