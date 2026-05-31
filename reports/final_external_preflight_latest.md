# Verity Lens Final External Preflight

- Generated: `2026-05-31T11:05:05.9775983+02:00`
- Ready to run finalizer: `False`
- Allow emulator: `False`
- Require ready: `False`
- Finalizer command: `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com' -AdbPath 'C:\Users\marke\AppData\Local\Android\Sdk\platform-tools\adb.exe'`

## Render API

- Input URL: ``
- Normalized URL: ``
- URL policy OK: `False`
- URL policy error: `ApiBaseUrl is required for the final cloud phone submission.`
- Cloud API OK: `False`
- Health: `not_checked`
- Health attempts: `0`
- Ready: `not_checked`
- Ready attempts: `0`
- Fake probe: `not_checked`
- Fake probe attempts: `0`
- Cloud API error: `ApiBaseUrl is required for the final cloud phone submission.`

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
- Selected device authorized: `False`
- Selected device is emulator: `False`
- Selected physical device authorized: `False`
- Unauthorized devices: `0`
- Offline devices: `0`
- Authorized emulator devices: `0`
- Device error: `No authorized physical USB Android device is connected.`

### Raw ADB Devices Output

```text
List of devices attached
```

## Missing To Run Finalizer

- real public HTTPS Render API URL
- authorized physical USB Android device

## Next Actions

- Deploy the Render backend from render.yaml or outputs\cloud_deploy\verity-lens-render-backend.zip, then rerun this preflight with -ApiBaseUrl https://<render-app>.onrender.com -RequireReady.
- No Android devices are listed by adb devices. Connect a real phone by USB, enable USB debugging, accept the RSA prompt, and rerun adb devices until one row shows state device.
- After the missing items are fixed, run: .\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com' -AdbPath 'C:\Users\marke\AppData\Local\Android\Sdk\platform-tools\adb.exe'

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
- Complete: `False`
- Estimated completion: `92%`
- Remaining: `phone_permanent_cloud, physical_phone_proof`

## Artifacts

- Render backend ZIP: `True` C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\outputs\cloud_deploy\verity-lens-render-backend.zip
- Cloud APK: `False` C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\outputs\phone_download\VerityLens-cloud.apk
- Cloud APK verification JSON: `False` C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json
- Device smoke JSON: `True` C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\outputs\phone_download\PHONE_DEVICE_SMOKE.json
- Device screenshot: `False` C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png
