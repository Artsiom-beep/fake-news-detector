# Fake News Detector — Runbook

## 1) Setup on a new Windows PC

```powershell
cd C:\path\to\fake-news-detector
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock.txt
copy .env.example .env
python scripts/build_benchmark_v3.py
python scripts/make_eval_splits.py --src data/factcheck/versions/eval_cases_v3_60.jsonl
python scripts/bootstrap_factcheck.py
```

The default `requirements.lock.txt` is for the current product runtime. It
keeps the PC/API/UI/desktop path lightweight and does not install the archived
Torch/Transformers training stack. Install `requirements.optional-ai.txt` only
for an explicit optional image/classifier model, and
`requirements.legacy-train.txt` only for old research/training work.

## 2) Smoke Checks

```powershell
python -m py_compile src\predict_factcheck.py src\api_factcheck.py src\ui.py src\factcheck\service.py
python -m unittest discover -s tests -v
python -m src.predict_factcheck --text "100 is lower than 200"
python -m src.predict_factcheck --text "Salt is sweet"
python -m src.predict_factcheck --text "Elephant is a mammal"
python -m src.predict_factcheck --text "Coffee cures cancer"
python -m src.predict_factcheck --url "https://www.politifact.com/factchecks/2020/may/21/facebook-posts/disposable-homemade-masks-are-effective-stopping-a"
python -m src.predict_factcheck --text "A totally new unverified claim with no known fact-check page."
python scripts/run_product_acceptance.py
```

Expected: simple stable facts may return `true` or `fake`; unsupported life/medical claims should say no exact answer and return `uncertain`; trusted fact-check URLs with explicit rulings return `true` or `fake`; unknown claims should return `uncertain`; ordinary news URLs should return a `credibility` payload.

Image smoke checks in the UI:
- Upload a PNG/JPG and click `Detect AI image`. Expected: the UI shows `Likely AI`, `Likely real`, or `Not enough certainty`; weak signals should stay `uncertain` in `image_analysis.ai_label`. The app loads `.env` when present. The packaged desktop launcher defaults `FACTCHECK_AI_IMAGE_MODEL` to `metadata_only`; set a model such as `haywoodsloan/ai-image-detector-deploy` only when you intentionally want the optional classifier. Screenshot OCR remains available through the API/regression suite, but it is no longer exposed as a separate UI tab.

## 3) Start Services

API:

```powershell
python -m uvicorn src.api_factcheck:app --host 0.0.0.0 --port 8001
```

UI:

```powershell
python -m uvicorn src.ui:app --host 0.0.0.0 --port 8002
```

Image API:

```powershell
curl -X POST "http://127.0.0.1:8001/factcheck-image" -F "analysis_type=screenshot" -F "image_file=@screenshot.png"
curl -X POST "http://127.0.0.1:8001/factcheck-image" -F "analysis_type=ai_image" -F "image_file=@image.png"
```

Desktop app launcher:

```powershell
.\run_desktop_app.bat
```

Desktop smoke check without opening a window:

```powershell
python -m src.desktop_app --smoke
```

Windows portable `.exe` build:

```powershell
.\scripts\build_windows.ps1
```

Expected artifacts: `dist\FakeNewsDetector\FakeNewsDetector.exe` and `dist\FakeNewsDetector-Windows-Portable.zip`. The script generates the icon, ensures PyInstaller is available, runs tests, builds one-folder output, excludes optional Torch/Transformers research dependencies, refreshes the portable zip, and runs `FakeNewsDetector.exe --smoke --port 0`. Use `-SkipUnitTests` or `-SkipPackagedSmoke` only for local debugging.

Flutter mobile/web client:

```powershell
cd apps\fake_news_detector_flutter
.\tool\create_platforms.ps1
flutter run -d chrome --dart-define=API_BASE_URL=http://127.0.0.1:8001
flutter build apk --dart-define=API_BASE_URL=https://<render-app>.onrender.com
```

The Flutter client calls the API only; it does not embed the Python engine. Deploy the API with `render.yaml`, then set `API_BASE_URL` to the Render URL. The app shows an API connection banner and has a refresh button, so the phone can confirm whether it reaches the backend. See `docs\mobile_flutter_render.md`.

Temporary internet phone demo without Render:

```powershell
.\scripts\start_public_api_tunnel.ps1 -BuildApk
.\scripts\start_localtunnel_api.ps1 -BuildApk
```

Expected artifact: `outputs\phone_download\VerityLens-internet.apk`. The tunnel and local API must stay running on this PC.
Temporary tunnel readiness can become a warning in the final verifier if the
provider URL expires or stops forwarding; use LAN for local phone proof and
Render for the permanent phone path.
Verify the exact APK/API pair before installing:

```powershell
.\scripts\verify_phone_apk.ps1 -ExpectedMode release -RequireHttps
.\scripts\prepare_phone_install_page.ps1 -StartServer
.\scripts\check_phone_readiness.ps1
```

Open the printed install page URL on the phone to download the APK. The
readiness report should show `Phone install/download: True`, proving the page
returns HTTP 200 and the APK download length matches the built file.
For the permanent cloud APK, the install page only shows the cloud download
when `phone_permanent_cloud` is true and the cloud APK verification proves
release mode, a current Flutter source stamp, the embedded Render URL, and a
live API probe. Stale or debug cloud artifacts remain visible in reports but are
not advertised as the final APK download.
The APK verification report should also show `APK contains expected API URL:
True`; this proves the installed Flutter binary was built with the same backend
URL that the status file and live API probes describe.
It should also show `Flutter source stamp matches current source: True`; this
prevents accepting an old APK after changing the mobile client.

Optional real-device smoke after enabling USB debugging:

```powershell
adb devices
.\scripts\smoke_phone_on_device.ps1
```

For final proof, enable Developer options on the Android phone, turn on USB
debugging, connect it by USB, accept the RSA authorization prompt, and confirm
`adb devices` shows the phone with state `device`. States such as `offline` or
`unauthorized` do not count. If more than one device is attached, pass the chosen
serial with `-PhoneDeviceId` to the preflight/finalizer.
If PATH points to the wrong SDK, pass the exact ADB executable with
`-AdbPath C:\path\to\adb.exe` to the preflight, finalizer, or release gate.

Use `-RequireDevice -RequirePhysicalDevice` for the final manual phone proof; it
fails unless an authorized physical Android device is connected, the APK
installs, and Verity Lens launches with package id `app.veritylens.mobile`.
`-RequirePhysicalDevice` rejects emulator device IDs and ADB emulator
properties. When it runs on a device, it also saves
`outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png` and records the screenshot
SHA256 in `PHONE_DEVICE_SMOKE.json`. It records ADB identity fields too:
manufacturer, model, product, Android version, SDK, hardware and
`ro.kernel.qemu`. The release gate exposes the same check through
`-PhoneDeviceSmoke` and `-RequirePhoneDevice`; the strict final cloud wrapper
adds `-RequirePhysicalPhoneDevice`. A normal release gate refreshes a non-passing/skipped device-smoke report against the
current APK so stale phone evidence is not bundled, then refreshes phone
readiness so the embedded smoke summary matches `PHONE_DEVICE_SMOKE.json`.

Android emulator smoke, when an AVD is available:

```powershell
.\scripts\smoke_phone_emulator.ps1 -AvdName FakeNewsDetector_API36 -RequireEmulator
```

Expected artifact: `outputs\phone_download\PHONE_EMULATOR_SMOKE.*` plus
`outputs\phone_download\PHONE_EMULATOR_SCREENSHOT.png`. This is useful
phone-platform evidence, but it does not replace the final physical phone proof above.

Same-Wi-Fi physical phone build:

```powershell
.\scripts\build_phone_for_lan.ps1 -StartApi
```

Expected artifact: release APK `outputs\phone_download\VerityLens-lan.apk`. The status file records the API URL, mode, Flutter source SHA256, size, and SHA256. Keep the local API running and verify the phone can open `http://<your-laptop-lan-ip>:8001/health`.
`scripts\run_release_gate.ps1` additionally writes
`outputs\phone_download\PHONE_APK_VERIFICATION.*` for the HTTPS internet APK and
`outputs\phone_download\PHONE_LAN_APK_VERIFICATION.*` for the LAN APK to prove
each APK contains the recorded API URL and that the backend probe succeeds.

Submission bundle:

```powershell
.\scripts\make_submission_bundle.ps1
```

Expected artifact: `outputs\submission\VerityLens-submission.zip`, with `SUBMISSION_MANIFEST.md` and SHA256 checksums inside.
It also includes acceptance and live quality-pack reports plus `source\verity-lens-source.zip`, a clean source package for review/rebuilds without `.venv`, generated build folders, local outputs, cache files, IDE metadata, generated Flutter registrants, generated LaTeX outputs/logs, or archived legacy prototypes.
After permanent cloud finalization, the same submission command also includes `phone\VerityLens-cloud.apk`, `phone\PHONE_CLOUD_APK_VERIFICATION.*`, and `phone\VerityLens-cloud-status.md`.
The submission command also runs `scripts\verify_submission_bundle.ps1`, which writes `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md/json` and verifies the manifest, hashes, quality reports, release-mode phone evidence, Render smoke reports, and nested source ZIP cleanliness.

Permanent cloud phone finalization after Render deploy:

```powershell
.\scripts\finalize_cloud_deploy.ps1 -ApiBaseUrl https://<render-app>.onrender.com
.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady
.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com
.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com -AdbPath C:\path\to\adb.exe
.\scripts\audit_project_goal_completion.ps1
```

Expected artifact: `outputs\phone_download\VerityLens-cloud.apk` plus `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.md`.
The permanent cloud URL must be a real public HTTPS host. The shared policy in `scripts\cloud_url_policy.ps1` rejects localhost, LAN/private IPs, `.local` names, single-label hosts, and temporary tunnel domains such as `*.loca.lt` or `*.trycloudflare.com`.
`CLOUD_DEPLOYMENT_STATUS.md/json` should list `PHONE_CLOUD_APK_VERIFICATION.json`, the cloud APK Flutter source-stamp sidecar, and `Cloud APK source stamp matches current source: True`.
The status file derives `verification_ok` and `readiness_ok` from the
verification JSON, release mode, embedded Render URL, live API probe, and source
stamp checks. If a wrapper parameter claims success but those artifacts disagree,
the status is downgraded instead of being accepted as final evidence.
Temporary tunnel APK verification may warn when the tunnel URL is offline; it
still checks the APK binary, embedded URL, release mode, status file, and Flutter
source stamp. This relaxation does not apply to permanent Render/cloud APK
verification.
`check_final_external_prereqs.ps1 -RequireReady` writes `reports\final_external_preflight_latest.*` and checks the Render URL policy, retries `/health`, `/ready`, the fake-claim probe, and checks physical-device ADB authorization before the long final gate. It also records the exact `adb devices` command and raw output, which is the fastest way to distinguish no phone, `offline`, `unauthorized`, emulator-only, and ADB permission failures. The `Next Actions` section is state-specific, so it points to accepting the RSA prompt, reconnecting/restarting ADB, replacing an emulator with a real phone, or connecting a phone when the device list is empty.
When present, the submission bundle includes this report under `final/`, and
the submission verifier checks that the Markdown/JSON preflight pair is not
partial.
Its `Final Evidence Contract` section names the exact fields that the final
wrapper and audit will require: effective cloud deployment status, release cloud
APK mode, selected physical device, non-emulator proof, recorded phone identity,
captured screenshot, and matching screenshot SHA256.
The second command is the strict final wrapper for submission day: it requires an authorized physical USB Android device, runs the cloud release gate with `-RequirePhoneDevice -RequirePhysicalPhoneDevice`, requires `PHONE_DEVICE_SCREENSHOT.png`, writes `reports\final_cloud_phone_submission_latest.*`, treats that success report as immutable, refreshes the submission ZIP so the same report is packaged under `final\`, and reruns the verifier.
Failed finalizer reports remain in `reports\` for diagnosis but are not copied
into a normal submission ZIP; the verifier writes
`final_cloud_phone_submission_report.status` to make that state explicit.
The final report labels its embedded `submission_zip` and verifier hashes as a
`pre_final_report_bundle_snapshot`; the verifier output written after packaging
is the proof for the final ZIP that contains the report.
Its final evidence check and the goal audit require the cloud deployment status
to be effective, not merely requested: `outcome=permanent_cloud_phone_ready`,
`verification_ok=true`, `readiness_ok=true`, and
`cloud_apk_verification_status.ready_to_publish=true`.
The final wrapper always requires `-CloudApkMode release`; run `scripts\run_release_gate.ps1` directly for debug-only local diagnostics.

## 4) Benchmark Run

```powershell
python scripts/eval_factcheck_v3.py --dataset data/factcheck/versions/eval_cases_v3_60.jsonl --out outputs/factcheck_runs/eval_results_v1.json
python scripts/report_factcheck.py --eval outputs/factcheck_runs/eval_results_v1.json --out-md outputs/factcheck_runs/final_report.md
python scripts/register_eval_run.py --dataset data/factcheck/versions/eval_cases_v3_60.jsonl --eval outputs/factcheck_runs/eval_results_v1.json --dataset-version v3_60 --pipeline-version best_accuracy_v2 --notes "manual benchmark run"
```

Live news quality pack:

```powershell
python scripts/run_quality_pack_v3.py --per-source 1 --max-cases 18
```

Life-facts benchmark:

```powershell
python scripts/eval_life_facts.py
```

Product acceptance gate:

```powershell
python scripts/run_product_acceptance.py
```

Expected: visible product sections (`facts`, `news`, `images`, `api_contract`) plus the hidden screenshot-OCR regression section meet their section-specific minimum case counts and have a pass rate of 95% or higher.

AI-image detector benchmark:

```powershell
python scripts/run_ai_image_detector_eval.py --existing-only
```

Known fake fact-check link smoke:

```powershell
python scripts/run_fake_links_test.py
```

Read `reports/quality_pack_v3_live.md` first, then inspect `reports/quality_pack_v3_live.json` for evidence URLs, risk flags and timings.
Read `reports/life_facts_v1_report.md` for arithmetic, everyday-fact, Wikipedia-backed and safe-abstention performance.
Read `outputs/ai_image_eval/ai_image_detector_eval.md` for the latest image detector run, and `reports/image_detector_runs/` for versioned history.

## 5) Release Gates
One-command local release gate:

```powershell
.\scripts\run_release_gate.ps1
```

Cloud/mobile release gate after Render deployment:

```powershell
.\scripts\run_release_gate.ps1 -ApiBaseUrl https://<render-app>.onrender.com -BuildCloudApk -CloudApkMode release
```

- Best-accuracy gate: high precision on hard verdicts, no hard verdict without explicit trusted fact-check evidence or stable common-knowledge rules, and explainable evidence links.
- Product acceptance gate: `scripts/run_product_acceptance.py` must pass per section, not only overall.
- `scripts/run_release_gate.ps1` must pass before a demo or submission. It runs Python syntax checks, backend tests, product acceptance, LaTeX report PDF creation, Render deploy configuration verification, Render backend bundle creation, a fresh-venv smoke run from the extracted Render ZIP, cloud deployment status reporting, internet APK verification, phone install-page refresh, LAN API server startup, LAN APK verification, phone readiness reporting, local desktop smoke, packaged desktop verification, Flutter analyze/tests, device-smoke availability refresh, and a final phone-readiness refresh. It writes `reports/release_gate_latest.*`; the submission verifier requires that report to be successful, not run with debug skips, include the required release steps, and match the SHA/size of the artifacts inside the submission ZIP. The verifier also cross-checks internet/LAN APK verification, Flutter source stamps, emulator/device smoke evidence, phone-readiness embedded smoke data, Render deploy config, Render smoke reports, and the nested clean source ZIP. When `-BuildCloudApk` is used, it verifies the exact cloud APK/API pair and requires the Render URL to be embedded in a release APK before cloud readiness can pass. Cloud mode uses `scripts\cloud_url_policy.ps1`, so local/private/tunnel URLs cannot be counted as permanent phone readiness. Use `-CloudApkMode debug` or `-SkipFreshRenderVenv` only for narrow local debugging.
- The LAN API server step starts `src.api_factcheck:app` on the port recorded by `VerityLens-lan-api-url.txt` before checking the same-Wi-Fi APK. The release report records the LAN API port, health URL, healthy flag, PID, and log paths, and the submission verifier requires that summary to be healthy.
- Temporary tunnel internet APK probes are treated as warnings when the tunnel is unavailable; Render/cloud APK probes remain strict.
- `scripts/verify_render_deploy_config.py` writes `reports\render_deploy_config_latest.*` and validates that `render.yaml`, Dockerfile, `.dockerignore`, and `requirements.api.txt` are aligned for the permanent Docker-based Render web service.
- `scripts/finalize_cloud_deploy.ps1` repeats the Render ZIP smoke with `-FreshVenv`, proving that the bundle starts after installing only `requirements.api.txt` from the extracted deployment package.
- `scripts/check_final_external_prereqs.ps1` is the quick final preflight for external dependencies: it validates the permanent Render URL, retries the API probes, lists authorized physical Android devices through ADB, records raw `adb devices` output, supports explicit `-AdbPath`, and prints the exact finalizer command.
- Its report is copied into the submission bundle under `final/` when present; the verifier warns if the preflight says the finalizer is not ready to run.
- Its `Final Evidence Contract` section shows the cloud and physical-phone fields that must become true before completion can be claimed.
- `scripts/finalize_cloud_phone_submission.ps1` is the strict final cloud-and-phone submission wrapper; it combines the Render URL policy, release-only cloud APK build, physical phone proof, valid PNG screenshot proof, submission packaging, verifier, and final report.
- `scripts/audit_project_goal_completion.ps1` writes `reports\goal_completion_audit_latest.*` and maps the original user goals to current evidence. A non-complete audit is expected until permanent Render phone readiness and physical Android valid PNG screenshot proof are present.
- Track `hard_verdict_precision`, `hard_verdict_coverage`, `credibility_label_calibration`, `uncertain_rate`, `error_rate`, and domain breakdown.
- For AI-image detection, track false positives (`real` labeled `likely_ai`) separately from false negatives. False AI accusations are more harmful than abstentions.
- The older `v3_60` benchmark is diagnostic for coverage; ordinary news credibility also needs mixed live URL smoke runs.

## 6) Operational Notes
- CLI accepts only `text` and `url`; the UI exposes separate News, Facts and Images sections backed by the same canonical engine.
- `run_desktop_app.bat` opens the same local UI in a PyWebView desktop window; `scripts\build_windows.ps1` builds the portable Windows folder.
- The single public pipeline is `best_accuracy_v2`; it internally routes fact-check URLs, ordinary news URLs/text, and simple everyday facts.
- It does not use neural verdict scoring in the default product path. Everyday facts use local rules plus Wikipedia summaries/categories, with safe abstention when sources are not exact.
- Screenshot checks use RapidOCR locally, then pass extracted text to the same canonical engine.
- AI-image checking is a risk detector based on metadata/forensic signals plus an optional image classifier via `FACTCHECK_AI_IMAGE_MODEL`. The packaged desktop launcher defaults it to `metadata_only` for a smaller offline-friendly build; set it to a model name only when the optional classifier should be downloaded and used.
- Development cache is stored in `outputs/factcheck_runs/factcheck_cache.sqlite3`; packaged Windows builds use `%LOCALAPPDATA%\FakeNewsDetector\cache\factcheck_cache.sqlite3`.
- The UI, CLI, compatibility predictor and benchmark scripts now all use the same canonical engine in `src/factcheck/`.
- Legacy multimodal/training files are archived under `archive\legacy_multimodal\`, documented in `docs\legacy_ml_inventory.md`, and should not be imported by product entrypoints.
- Default dependency files are product-only. Optional AI runtime dependencies
  live in `requirements.optional-ai.txt`; archived training dependencies live
  in `requirements.legacy-train.txt`.
