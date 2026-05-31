# Fake News Detector Flutter App

Mobile and web Flutter client for the existing FastAPI fact-check backend.

## Setup

Install Flutter, then generate the Android, iOS and Web platform folders:

```powershell
cd apps\fake_news_detector_flutter
.\tool\create_platforms.ps1
flutter pub get
```

If you are on macOS and need iOS builds, run the same `flutter create --platforms=android,ios,web .` command from this folder after installing Xcode.

## Run

Local web against a local backend:

```powershell
python -m uvicorn src.api_factcheck:app --host 0.0.0.0 --port 8001
cd apps\fake_news_detector_flutter
flutter run -d chrome --dart-define=API_BASE_URL=http://127.0.0.1:8001
```

Android emulator against a local backend on the host machine:

```powershell
flutter run -d android --dart-define=API_BASE_URL=http://10.0.2.2:8001
```

Cloud demo against Render:

```powershell
flutter run -d chrome --dart-define=API_BASE_URL=https://<render-app>.onrender.com
flutter build web --dart-define=API_BASE_URL=https://<render-app>.onrender.com
flutter build apk --dart-define=API_BASE_URL=https://<render-app>.onrender.com
```

## Test

```powershell
flutter analyze
flutter test
```

## Modes

- News calls `POST /factcheck` with `url` and optional `text`.
- Facts calls `POST /factcheck` with `text`.
- Images calls `POST /factcheck-image` with `analysis_type=ai_image`.
