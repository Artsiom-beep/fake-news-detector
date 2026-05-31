# Verity Lens Final External Preflight

- Generated: `2026-05-31T12:32:05.0002411+02:00`
- Ready to run finalizer: `True`
- Allow emulator: `False`
- Require ready: `True`
- Finalizer command: `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://fake-news-detector-poi6.onrender.com' -AdbPath 'C:\Users\marke\AppData\Local\Android\Sdk\platform-tools\adb.exe'`

## Render API

- Input URL: `https://fake-news-detector-poi6.onrender.com`
- Normalized URL: `https://fake-news-detector-poi6.onrender.com`
- URL policy OK: `True`
- URL policy error: ``
- Cloud API OK: `True`
- Health: `ok`
- Health attempts: `1`
- Ready: `ready`
- Ready attempts: `1`
- Fake probe: `fake / 0.78`
- Fake probe attempts: `1`
- Cloud API error: ``

## Android Device

- ADB found: `True`
- ADB executable accessible: `True`
- ADB requested path: `C:\Users\marke\AppData\Local\Android\Sdk\platform-tools\adb.exe`
- ADB devices command: `adb devices`
- ADB devices exit code: `0`
- ADB path: `C:\Users\marke\AppData\Local\Android\Sdk\platform-tools\adb.exe`
- Requested device: ``
- Requested device state: ``
- Selected device: ``
- Selected device authorized: `True`
- Selected device is emulator: `False`
- Selected physical device authorized: `True`
- Unauthorized devices: `0`
- Offline devices: `0`
- Authorized emulator devices: `0`
- Device error: ``

### Raw ADB Devices Output

```text
List of devices attached
RFCTC07YX2N	device
```

## Missing To Run Finalizer

- None

## Next Actions

- Run the final wrapper now: .\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://fake-news-detector-poi6.onrender.com' -AdbPath 'C:\Users\marke\AppData\Local\Android\Sdk\platform-tools\adb.exe'

## Final Evidence Contract

Cloud fields:
- `phone_permanent_cloud`
- `cloud_status_outcome_ready`
- `cloud_status_verification_ok`
- `cloud_status_readiness_ok`
- `cloud_status_ready_to_publish`
- `cloud_apk_release_mode`
- `cloud_apk_api_permanent_url`
- `cloud_apk_api_not_temporary_tunnel`
- `cloud_apk_api_matches_requested_url`
- `cloud_apk_embedded_api_url_found`
- `cloud_apk_embedded_api_matches_base_url`
- `cloud_apk_status_matches_url`
- `cloud_apk_status_matches_mode`
- `cloud_apk_status_matches_flutter_source_stamp`

Physical phone fields:
- `phone_device_smoke_ok`
- `phone_device_requires_physical`
- `phone_device_selected_id`
- `phone_device_selected_physical`
- `phone_device_identity_recorded`
- `phone_device_screenshot_captured`
- `phone_device_screenshot_sha256_recorded`
- `phone_device_screenshot_sha256_matches`
- `phone_device_screenshot_valid_png`

Required final reports:
- `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`
- `outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json`
- `outputs\phone_download\PHONE_DEVICE_SMOKE.json`
- `outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png`
- `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`
- `reports\goal_completion_audit_latest.json`
- `reports\final_cloud_phone_submission_latest.json`

## Current Goal Audit

- Exists: `True`
- Complete: `True`
- Estimated completion: `100%`
- Remaining: ``

## Artifacts

- Render backend ZIP: `True` C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\outputs\cloud_deploy\verity-lens-render-backend.zip
- Cloud APK: `True` C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\outputs\phone_download\VerityLens-cloud.apk
- Cloud APK verification JSON: `True` C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json
- Device smoke JSON: `True` C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\outputs\phone_download\PHONE_DEVICE_SMOKE.json
- Device screenshot: `True` C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png
