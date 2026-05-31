# Verity Lens Mobile + Render Deployment

## 1. Deploy the API on Render

1. Push this repository to a Git provider connected to Render.
2. In Render, create a new Blueprint or Web Service from `render.yaml`.
3. Keep the Docker runtime and health check path `/health`.
4. Set `FACTCHECK_CORS_ORIGINS=*` for the demo build, or replace it with the final Flutter Web origin.
5. After deploy, copy the public API URL, for example `https://fake-news-detector-api.onrender.com`.

Render provides `$PORT`; the Dockerfile uses that value automatically. The cloud Docker image installs
`requirements.api.txt`, not the full desktop/training dependency set, so the phone backend can start on a smaller
Render instance. The default cloud AI-image mode is `metadata_only`: it detects strong metadata/forensics signals and
avoids downloading a heavy vision model during startup. If a larger paid instance is available, set
`FACTCHECK_AI_IMAGE_MODEL=haywoodsloan/ai-image-detector-deploy` in Render to enable the optional model.

## 2. Build the Flutter app

Install Flutter, then generate platform wrappers:

```powershell
cd apps\fake_news_detector_flutter
.\tool\create_platforms.ps1
```

Build or run with the Render API URL:

```powershell
flutter run -d chrome --dart-define=API_BASE_URL=https://<render-app>.onrender.com
flutter build web --dart-define=API_BASE_URL=https://<render-app>.onrender.com
flutter build apk --dart-define=API_BASE_URL=https://<render-app>.onrender.com
.\tool\build_internet_apk.ps1 -ApiBaseUrl https://<render-app>.onrender.com
```

From the repository root, the safer one-command phone build is:

```powershell
.\scripts\build_phone_for_cloud.ps1 -ApiBaseUrl https://<render-app>.onrender.com -Mode release
.\scripts\finalize_cloud_deploy.ps1 -ApiBaseUrl https://<render-app>.onrender.com
.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady
.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com
```

That script defaults to a release APK and checks `/health`, `/ready`, and one real fact-check before writing the APK to:

```text
outputs/phone_download/VerityLens-cloud.apk
```

`build_phone_for_cloud.ps1` intentionally uses the shared policy in
`scripts/cloud_url_policy.ps1`. It rejects temporary tunnel domains such as
`*.loca.lt` and `*.trycloudflare.com`, local names such as `localhost` or
`*.local`, single-label hosts, and private/LAN IPs such as `127.x.x.x`,
`10.x.x.x`, `172.16-31.x.x`, and `192.168.x.x`. Use the temporary internet
scripts below for tunnel URLs, and reserve `VerityLens-cloud.apk` for a stable
public cloud backend such as Render.
`finalize_cloud_deploy.ps1` chains the final steps: cloud API verification,
cloud APK build, APK verification, and `-RequireCloud` readiness reporting.
After that succeeds, `scripts/make_submission_bundle.ps1` carries the cloud APK,
the embedded API URL record, and `PHONE_CLOUD_APK_VERIFICATION.*` into the final
submission ZIP.
`CLOUD_DEPLOYMENT_STATUS.*` records the verification JSON and the
`VerityLens-cloud-flutter-source-stamp.json` sidecar so the permanent cloud APK
can be tied back to the exact Flutter source used for the build.
The status file derives its final verification/readiness booleans from that
JSON evidence, release mode, embedded Render URL, live API probe, and source
stamp match, so a stale or debug cloud APK cannot become final evidence through
wrapper parameters alone.
When a USB-authorized physical Android phone is connected, the strict final wrapper
`scripts/finalize_cloud_phone_submission.ps1` runs the cloud release gate with
`-RequirePhoneDevice -RequirePhysicalPhoneDevice`, requires
`PHONE_DEVICE_SCREENSHOT.png`, writes `reports/final_cloud_phone_submission_latest.*`,
keeps the success report immutable, refreshes the submission ZIP so the same
report is included under `final/`, and reruns `verify_submission_bundle.ps1`.
Failed finalizer reports are kept in `reports/` for diagnosis but are skipped by
the normal submission bundle; the verifier records
`final_cloud_phone_submission_report.status` for that distinction.
Since that report is packaged inside the ZIP, its own `submission_zip` and
verifier artifact hashes are labeled as a `pre_final_report_bundle_snapshot`;
the verifier output after packaging proves the final ZIP.
The final wrapper and goal audit require the effective cloud deployment status
too: `outcome=permanent_cloud_phone_ready`, `verification_ok=true`,
`readiness_ok=true`, and `cloud_apk_verification_status.ready_to_publish=true`.
The wrapper also records and requires the real-device proof fields from
`PHONE_DEVICE_SMOKE.json`: `require_physical_device=true`, a selected device
serial, `selected_device_is_emulator=false`, recorded manufacturer/model/Android
SDK identity fields, a valid PNG screenshot with positive dimensions, and a
screenshot SHA256 that matches `PHONE_DEVICE_SCREENSHOT.png`.
Its preflight retries `/health`, `/ready`, and the fake-claim probe before the
long release gate starts.
The same preflight writes a `Final Evidence Contract` section naming the exact
cloud and physical-phone fields that must become true before the goal audit can
mark the phone path complete.
It also saves the exact `adb devices` command and raw output, so the report shows
whether the connected phone is missing, `offline`, `unauthorized`, emulator-only,
or blocked by ADB execution permissions.
Its `Next Actions` section then gives the matching fix, such as accepting the RSA
prompt, reconnecting/restarting ADB, or using a real USB phone instead of an
emulator for the final proof.
It always requires a release cloud APK; use `scripts/run_release_gate.ps1`
directly for debug-only local diagnostics.
Before running it, enable Developer options on the Android phone, turn on
USB debugging, connect the phone, accept the RSA authorization prompt, and run
`adb devices`. The final proof requires a row whose state is `device`; `offline`
or `unauthorized` means the phone is not ready. If more than one Android device
is attached, pass the selected serial with `-PhoneDeviceId`.
If ADB is installed outside PATH or several SDKs are present, pass the exact
executable with `-AdbPath C:\path\to\adb.exe` to the preflight, finalizer, or
release gate.
The local install page generated by `scripts/prepare_phone_install_page.ps1`
also shows a separate permanent-cloud APK download block only after
`phone_permanent_cloud` is true and `PHONE_CLOUD_APK_VERIFICATION.json` proves
release mode, a current Flutter source stamp, the embedded Render URL, and a
live API probe. Stale or debug cloud APK files stay visible in reports but are
not offered as the final download.
For a USB-connected Android phone, `scripts/smoke_phone_on_device.ps1` can
install the APK, verify package id `app.veritylens.mobile`, launch the app,
capture `PHONE_DEVICE_SCREENSHOT.png`, record ADB device identity fields, and
write `PHONE_DEVICE_SMOKE.*`. Run it with
`-RequireDevice -RequirePhysicalDevice` for the final real-device proof; the
physical flag rejects emulator device IDs and ADB emulator properties.
If an Android Virtual Device is available, `scripts/smoke_phone_emulator.ps1`
can also start the emulator headlessly, install the APK, launch Verity Lens, and
write `PHONE_EMULATOR_SMOKE.*` and `PHONE_EMULATOR_SCREENSHOT.png`. Treat this
as emulator evidence only; the final physical-phone proof still comes from
`PHONE_DEVICE_SMOKE.*` with `-RequireDevice -RequirePhysicalDevice`.

The app also has runtime API settings. Open the gear icon, enter the public API URL, and tap Save.
The home screen shows an API connection banner; tap its refresh button after changing URLs to confirm the phone can reach `/health`.
This lets one installed APK switch from a local laptop server to a Render server without rebuilding.
If a new APK is built with a public HTTPS API URL, it automatically ignores a previously saved local address such as
`http://192.168.x.x:8001`, so an old Wi-Fi setting will not block the internet build.

## 3. Temporary internet demo without Render

For a quick demo before the API is deployed permanently, use a Cloudflare quick tunnel from this PC:

```powershell
.\scripts\start_public_api_tunnel.ps1 -BuildApk
```

The script starts the local API if needed, opens a public `https://*.trycloudflare.com` URL, saves it to
`outputs/public_api_url.txt`, and builds:

```text
outputs/phone_download/VerityLens-internet.apk
```

Install that APK on the phone. It will work on mobile data or any Wi-Fi while this PC stays on and the tunnel process is
running. This URL is temporary and can change after restart. Use Render for a stable URL.

If the quick tunnel creates a URL but the phone/API checks fail, inspect
`outputs/public_api_tunnel_info.json` and `outputs/public-api-tunnel.err.log`.
For diagnosis you can keep the local API and tunnel processes alive after a failed check:

```powershell
.\scripts\start_public_api_tunnel.ps1 -Restart -VerifyTimeoutSeconds 180 -KeepProcessesOnFailure
```

Do not use a quick-tunnel APK as the final submission build; use the Render URL for that.

If Cloudflare quick tunnels are unavailable, the project also has a LocalTunnel fallback:

```powershell
.\scripts\start_localtunnel_api.ps1 -BuildApk
.\scripts\start_localtunnel_api.ps1 -BuildApk -ApkMode release
```

This command uses `npx localtunnel`, verifies `/health`, `/ready`, and one
fact-check probe, then writes the same `outputs/public_api_url.txt` and
`outputs/phone_download/VerityLens-internet.apk` artifacts.

## 4. Local development URLs

- Flutter Web on the same PC: `http://127.0.0.1:8001`
- Android emulator to host PC: `http://10.0.2.2:8001`
- Physical phone on the same Wi-Fi: `http://<your-laptop-lan-ip>:8001`

Start the API locally with:

```powershell
python -m uvicorn src.api_factcheck:app --host 0.0.0.0 --port 8001
```

To build an APK for a physical phone on the same Wi-Fi network as this PC:

```powershell
.\scripts\build_phone_for_lan.ps1 -StartApi
```

That command detects the LAN IP, starts the local API if needed, builds release APK `outputs/phone_download/VerityLens-lan.apk`, and writes `outputs/phone_download/VerityLens-lan-status.md` with the API URL, mode, size, and SHA256.
The phone and PC must stay on the same network, and Windows Firewall must allow the phone to reach `http://<your-laptop-lan-ip>:8001/health`.
The release gate writes `PHONE_LAN_APK_VERIFICATION.*` after checking that the
LAN APK embeds the same API URL, is release mode, and that the backend fact-check probe succeeds.

## 5. Release checks

```powershell
python -m unittest discover -s tests -v
cd apps\fake_news_detector_flutter
flutter analyze
flutter test
```

After Render is deployed, verify the cloud API from the repository root:

```powershell
.\scripts\verify_cloud_api.ps1 -ApiBaseUrl https://<render-app>.onrender.com
```

To generate a single phone-readiness report for the current artifacts:

```powershell
.\scripts\check_phone_readiness.ps1
.\scripts\check_phone_readiness.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireCloud
```

The report is written to `outputs/phone_download/PHONE_READINESS.md` and records
whether the PC package, LAN APK, Render backend bundle, quick tunnel, install
page/APK download, and permanent cloud phone path are ready.
For the permanent cloud path, readiness also requires
`PHONE_CLOUD_APK_VERIFICATION.json` to show that the cloud APK passed live API
checks and contains the requested Render URL in the Flutter binary.

Before using the Render bundle, the release gate also runs
`scripts/smoke_render_backend_bundle.ps1`. This extracts
`outputs/cloud_deploy/verity-lens-render-backend.zip`, starts the API from the
extracted copy, and checks `/health`, `/ready`, and a fact-check probe.
The final cloud preflight (`scripts/finalize_cloud_deploy.ps1`) runs the same
smoke with `-FreshVenv`, installing only the extracted `requirements.api.txt`
before starting the API.

To verify the exact APK you are about to install:

```powershell
.\scripts\verify_phone_apk.ps1 -ExpectedMode release -RequireHttps
```

That command records the APK size, SHA256 hash, API URL, `/health`, `/ready`,
and a fact-check probe in `outputs/phone_download/PHONE_APK_VERIFICATION.md`.
It also scans the APK contents for the expected API URL in the Flutter binary,
so verification fails if the APK was accidentally built with an older backend
address.
The release gate runs the same verification for `VerityLens-internet.apk` and
the submission verifier cross-checks the recorded SHA256 against the APK inside
the final ZIP.

To create a phone-friendly download page for the APK:

```powershell
.\scripts\prepare_phone_install_page.ps1 -StartServer
```

Open the printed `http://<laptop-ip>:8010/index.html` URL on the phone. The page
links to the APK and the verification/readiness reports.

For a university submission bundle containing the report, app artifacts and
checksums:

```powershell
.\scripts\make_submission_bundle.ps1
```

Manual checks:

- Facts: `2 plus 2 equals 4` returns likely reliable.
- Facts: `2 plus 2 equals 5` returns likely false.
- Screenshots: upload a readable claim screenshot.
- Images: upload a PNG/JPG and verify AI risk output.

## 6. Phone demo without a laptop server

For a phone demo where the app only needs internet:

1. Deploy the API to Render and wait until `/health` returns `{"status":"ok","service":"factcheck"}`.
2. Install the APK on the phone.
3. Open Verity Lens, tap the gear icon, and save `https://<render-app>.onrender.com`.
4. Confirm the API banner changes to `API connected`.
5. Run one Facts check to confirm the phone can reach the cloud API.
6. For final submission proof, connect the same physical phone over USB and run
   `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`.

The APK does not contain the Python fact-check engine. The mobile app is a client, so offline checking is not part of v1.
