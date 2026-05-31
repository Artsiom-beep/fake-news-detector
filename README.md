# Verity Lens v1

Local-first fact-check engine for text, article URLs, image AI-risk checks, and optional screenshot OCR.

## Product Path
- `text/url -> best_accuracy_pipeline -> CLI / REST API / Web UI`
- English-first, local demo product.
- Users do not choose modes. The engine internally selects explicit fact-check verdicts, ordinary news credibility scoring, or simple common-knowledge checks.
- The backend keeps optional screenshot OCR for regression/API use: `image -> extracted text -> best_accuracy_pipeline`.
- AI-image checking returns a risk assessment, not proof. If signals are weak, it returns `uncertain`.
- Ordinary news returns `credibility.score` and `credibility.label`; hard `true/fake` is reserved for explicit fact-check evidence or simple stable facts.
- Simple everyday facts are checked with local arithmetic, a versioned local common-knowledge registry, and Wikipedia summaries/categories. If those sources do not give an exact answer, the engine returns `uncertain` instead of guessing.
- Default product path does not require neural verdict scoring.
- Output contract:

```json
{
  "verdict": "true|fake|uncertain",
  "confidence": 0.0,
  "summary": "short grounded explanation",
  "claim": "normalized primary claim",
  "evidence": [
    {"url":"...", "title":"...", "stance":"support|refute|neutral", "score":0.0}
  ],
  "trace": {
    "queries": [],
    "filtered_urls": [],
    "selected_passages": [],
    "decision_reasons": [],
    "fallbacks_used": [],
    "mode": "best_accuracy",
    "pipeline": "best_accuracy",
    "stage_timings_ms": {}
  },
  "credibility": {
    "score": 0.0,
    "label": "high|medium|low|unknown",
    "source_score": 0.0,
    "article_quality_score": 0.0,
    "corroboration_score": 0.0,
    "risk_score": 0.0,
    "matched_sources": [],
    "risk_flags": [],
    "reasons": []
  },
  "image_analysis": {
    "mode": "screenshot_ocr|ai_image_detection",
    "ocr_text": "",
    "ocr_confidence": 0.0,
    "detected_urls": [],
    "ai_generated_score": 0.0,
    "ai_label": "likely_ai|likely_not_ai|uncertain|not_evaluated",
    "warnings": [],
    "reasons": [],
    "metadata": {}
  }
}
```

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock.txt
copy .env.example .env
python scripts/build_benchmark_v3.py
python scripts/make_eval_splits.py --src data/factcheck/versions/eval_cases_v3_60.jsonl
python scripts/bootstrap_factcheck.py
```

`requirements.lock.txt` is the default product/runtime environment for API,
Web UI, desktop smoke, OCR and packaging. It intentionally does not install the
old Torch/Transformers training stack. Use `requirements.optional-ai.txt` only
when enabling an optional image/classifier model, and
`requirements.legacy-train.txt` only for archived research/training experiments.

## Run

CLI:

```powershell
python -m src.predict_factcheck --text "Wearing face masks will stop the spread of covid 19"
python -m src.predict_factcheck --text "Elephant is a mammal"
python -m src.predict_factcheck --text "Coffee cures cancer"
python -m src.predict_factcheck --url "https://www.politifact.com/factchecks/2020/may/21/facebook-posts/disposable-homemade-masks-are-effective-stopping-a"
python -m src.predict_factcheck --url "https://apnews.com/article/iran-us-pilot-military-rescue-fde473d07fb59e871a71cd2ad2ffe4fe"
```

CLI accepts only `--text` and `--url`.

REST API:

```powershell
python -m uvicorn src.api_factcheck:app --host 0.0.0.0 --port 8001
```

Web UI:

```powershell
python -m uvicorn src.ui:app --host 0.0.0.0 --port 8002
```

In the UI you can upload an image and choose `Detect AI image`, which returns a conservative risk badge: `Likely AI`, `Likely real`, or `Not enough certainty`. The app loads `.env` when present; `.env.example` uses `haywoodsloan/ai-image-detector-deploy` as the optional classifier. The packaged desktop app defaults to `FACTCHECK_AI_IMAGE_MODEL=metadata_only` to keep the Windows build lightweight. Screenshot OCR remains available as an internal/API capability but is not exposed as a separate product tab.

Desktop prototype:

```powershell
.\run_desktop_app.bat
```

The desktop prototype uses PyWebView to open the same local UI in a native window. You can verify the local desktop server without opening a window:

```powershell
python -m src.desktop_app --smoke
```

Windows portable app build:

```powershell
.\scripts\build_windows.ps1
```

The build script generates the Windows icon, installs PyInstaller into the active project environment if needed, runs tests, builds `dist/FakeNewsDetector/FakeNewsDetector.exe`, refreshes `dist/FakeNewsDetector-Windows-Portable.zip`, and runs the packaged smoke check. The packaged app is online-first, stores its runtime cache under `%LOCALAPPDATA%\FakeNewsDetector`, and excludes optional Torch/Transformers research dependencies from the portable folder.

Flutter mobile/web app:

```powershell
cd apps\fake_news_detector_flutter
.\tool\create_platforms.ps1
flutter run -d chrome --dart-define=API_BASE_URL=http://127.0.0.1:8001
flutter build apk --dart-define=API_BASE_URL=https://<render-app>.onrender.com
.\tool\build_internet_apk.ps1 -ApiBaseUrl https://<render-app>.onrender.com
```

The Flutter client, branded as Verity Lens, supports News, Facts and Images by calling the existing REST API. Android builds use package id `app.veritylens.mobile`. Use `render.yaml` to deploy the FastAPI backend to Render, then pass the public API URL with `--dart-define=API_BASE_URL=...`. The app also has a gear-button API setting and a visible API connection banner, so an installed APK can be pointed at a new cloud API URL and immediately show whether the phone can reach it. For a permanent phone build that does not need this PC, deploy Render first and run `.\scripts\build_phone_for_cloud.ps1 -ApiBaseUrl https://<render-app>.onrender.com -Mode release`. Permanent cloud scripts require a real public HTTPS host and reject localhost, LAN/private IPs, `.local` names, single-label hosts, and temporary tunnel domains. See `docs/mobile_flutter_render.md`.

For a temporary phone demo through the internet before Render is deployed:

```powershell
.\scripts\start_public_api_tunnel.ps1 -BuildApk
.\scripts\start_localtunnel_api.ps1 -BuildApk
```

These scripts create a public temporary HTTPS URL for the local API, verify `/health`, `/ready`, and a real fact-check probe, then build `outputs/phone_download/VerityLens-internet.apk`.
Use LocalTunnel when Cloudflare quick tunnels are unavailable.
The tunnel must stay running on this PC; Render is the permanent deployment path.
Because quick tunnel URLs can expire or return provider-side errors, the final
submission verifier treats temporary tunnel readiness as a warning. Same-Wi-Fi
phone readiness and the permanent Render path are the stable phone checks.
Before installing, verify the exact APK/API pair:

```powershell
.\scripts\verify_phone_apk.ps1 -ExpectedMode release -RequireHttps
.\scripts\prepare_phone_install_page.ps1 -StartServer
.\scripts\check_phone_readiness.ps1
```

Then open the printed install page URL on the phone and download the APK. The
readiness report verifies the temporary API, the install page, and the APK
download content length before marking the temporary phone path ready.
The same install page exposes the permanent cloud APK download only when
`phone_permanent_cloud` is true and `PHONE_CLOUD_APK_VERIFICATION.json` proves a
release APK, current Flutter source stamp, embedded Render API URL, and live API
probe. A stale or debug cloud APK can still be reported, but it is not offered
as the final download.
The APK verifier also opens the APK itself and confirms the expected API URL is
embedded in the Flutter binary, so a stale build cannot be mistaken for the
current API/API-status pair. It also compares a Flutter source SHA256 stamp
written during the APK build with the current Flutter source tree, so a stale
APK built before the latest mobile code change cannot pass the release gate.

With USB debugging enabled, a real-device smoke can install and launch the APK:

```powershell
adb devices
.\scripts\smoke_phone_on_device.ps1
.\scripts\smoke_phone_on_device.ps1 -ApkPath outputs\phone_download\VerityLens-cloud.apk -RequireDevice -RequirePhysicalDevice
```

Before the final proof, enable Developer options on the Android phone, turn on
USB debugging, connect it by USB, accept the RSA authorization prompt, and run
`adb devices`. The final proof needs one row whose state is `device`; `offline`
or `unauthorized` is not enough. If several phones are connected, pass the chosen
serial with `-PhoneDeviceId` to the preflight/finalizer.
If ADB is installed outside PATH or several Android SDKs are present, pass the
exact executable with `-AdbPath C:\path\to\adb.exe` to the preflight, finalizer,
or release gate.

The smoke writes `PHONE_DEVICE_SMOKE.*` and, when a device is present,
`PHONE_DEVICE_SCREENSHOT.png` with its SHA256, PNG signature check and dimensions in the JSON report. It also records
ADB device identity fields such as manufacturer, model, product, Android
version, SDK, hardware and `ro.kernel.qemu`, so the final proof is tied to a
specific physical phone rather than only a screenshot file. Without a connected
authorized Android device it records a skipped report; `-RequireDevice` makes
that a failing final check. For final proof, also use
`-RequirePhysicalDevice`, which rejects emulator device IDs and ADB emulator
properties. The release gate can also run the same proof with
`-PhoneDeviceSmoke` or require it with `-RequirePhoneDevice`; the strict final
cloud wrapper additionally passes `-RequirePhysicalPhoneDevice`. A normal release gate refreshes a
non-passing/skipped device-smoke report against the current APK so stale phone
evidence is not bundled, then refreshes phone readiness so the embedded smoke
summary matches `PHONE_DEVICE_SMOKE.json`.

When an Android Virtual Device is available, run a separate emulator proof:

```powershell
.\scripts\smoke_phone_emulator.ps1 -AvdName FakeNewsDetector_API36 -RequireEmulator
```

That writes `PHONE_EMULATOR_SMOKE.*` plus `PHONE_EMULATOR_SCREENSHOT.png` and
proves the APK installs and launches on Android without claiming that the
physical-phone proof has been completed.

For a physical phone on the same Wi-Fi network as this PC:

```powershell
.\scripts\build_phone_for_lan.ps1 -StartApi
```

This builds a release APK at `outputs/phone_download/VerityLens-lan.apk` and writes the detected backend URL, mode, Flutter source SHA256, size, and SHA256 to `outputs/phone_download/VerityLens-lan-status.md`.
The release gate also writes `outputs/phone_download/PHONE_APK_VERIFICATION.*`
for the HTTPS internet APK and `outputs/phone_download/PHONE_LAN_APK_VERIFICATION.*`
for the same-Wi-Fi APK. Both reports prove the APK embeds the expected API URL
and that the release APK backend responds before the submission bundle is accepted.

Release gate before a demo/submission:

```powershell
.\scripts\run_release_gate.ps1
.\scripts\run_release_gate.ps1 -ApiBaseUrl https://<render-app>.onrender.com -BuildCloudApk -CloudApkMode release
.\scripts\finalize_cloud_deploy.ps1
.\scripts\finalize_cloud_deploy.ps1 -ApiBaseUrl https://<render-app>.onrender.com
.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady
.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com
.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com -AdbPath C:\path\to\adb.exe
.\scripts\audit_project_goal_completion.ps1
.\scripts\make_submission_bundle.ps1
.\scripts\verify_submission_bundle.ps1
```

The submission ZIP includes the report, verification reports, acceptance and
live quality-pack reports, desktop ZIP, phone APKs, Render backend bundle, and a
clean `source/verity-lens-source.zip` with the reproducible project source. When
a permanent Render APK has been built, the same bundle also includes
`phone/VerityLens-cloud.apk` and `PHONE_CLOUD_APK_VERIFICATION.*`. The source
bundle excludes `.venv`,
`build`, `dist`, `outputs`, cache files, IDE metadata, generated Flutter
registrants, generated LaTeX outputs/logs, and archived legacy prototypes.

The first command checks Python syntax, backend tests, product acceptance, LaTeX report PDF creation, Render deploy configuration, Render backend bundle creation, a fresh-venv smoke run from the extracted Render ZIP, starts or refreshes the phone install-page server, runs phone readiness reporting, local desktop smoke, packaged desktop verification, `flutter analyze`, and `flutter test`. Phone readiness includes the API probe plus install-page and APK-download checks when a phone install page exists.
For the same-Wi-Fi phone path, the gate now also starts the LAN FastAPI server
on the port recorded by `VerityLens-lan-api-url.txt` before verifying
`VerityLens-lan.apk`, so a stale stopped local API is caught and repaired during
the check. `release_gate_latest.json` records the LAN API port, health URL,
healthy flag, PID, and logs so the same-Wi-Fi phone proof is machine-readable.
It writes `reports/release_gate_latest.json` and `reports/release_gate_latest.md`, which are included in the submission ZIP as the final machine-readable proof that the gate ran without debug skips.
The release gate also writes `reports/render_deploy_config_latest.*`, proving that
`render.yaml`, Dockerfile, `.dockerignore`, and `requirements.api.txt` are
aligned for a Docker-based Render web service before the bundle is created. The
submission verifier requires this report to pass.
The cloud finalizer repeats the same strict Render ZIP smoke in a fresh virtual environment, installing only `requirements.api.txt` from the extracted bundle before starting the API.
When `-ApiBaseUrl` is provided, the gate first applies the shared permanent-cloud URL policy from `scripts/cloud_url_policy.ps1`, then verifies the public HTTPS backend; `-BuildCloudApk` builds a phone APK against that backend, verifies the APK/API pair, and confirms the Render URL is embedded in the APK before cloud readiness can pass.
Cloud APK builds default to release mode; pass `-CloudApkMode debug` only for local diagnostics outside final submission.
Temporary tunnel internet APK verification is allowed to warn when the tunnel is
offline, as long as the APK binary, embedded URL, release mode, status file, and
Flutter source stamp still match. Permanent Render/cloud APK verification does
not use this relaxation.
`CLOUD_DEPLOYMENT_STATUS.*` also records the cloud APK verification JSON and Flutter source-stamp sidecar, so the permanent APK evidence proves the binary was built from the current mobile source.
Its final `verification_ok` and `readiness_ok` values are derived from that
JSON evidence, not only from wrapper parameters; a non-release, stale, or
non-API-verified cloud APK cannot be reported as ready.
For the final cloud phone handoff with a USB-authorized physical Android device connected, `finalize_cloud_phone_submission.ps1` runs the cloud release gate with `-RequirePhoneDevice -RequirePhysicalPhoneDevice`, requires a captured `PHONE_DEVICE_SCREENSHOT.png`, writes `reports/final_cloud_phone_submission_latest.*`, then treats that success report as immutable, refreshes the submission ZIP so the same report is packaged under `final/`, and reruns the verifier.
The final handoff and goal audit also require
`CLOUD_DEPLOYMENT_STATUS.json` to report `outcome=permanent_cloud_phone_ready`,
`verification_ok=true`, `readiness_ok=true`, and
`cloud_apk_verification_status.ready_to_publish=true`; phone readiness alone is
not enough for completion.
The final wrapper always requires `-CloudApkMode release`; run `run_release_gate.ps1` directly for debug-only local diagnostics.
Before the long final gate, `check_final_external_prereqs.ps1 -RequireReady` verifies the Render URL policy, retries `/health`, `/ready`, the fake-claim probe, and checks physical-device ADB authorization. The final wrapper runs the same preflight with `-RequireReady`, so missing Render/device prerequisites fail early with `reports/final_external_preflight_latest.*`.
That preflight stores the exact `adb devices` command and raw output in the
JSON/Markdown report, so `offline`, `unauthorized`, sandbox permission failures,
and an empty device list are visible without rerunning the check.
Its next-action text is state-specific: it tells whether to accept the RSA
prompt, reconnect/restart ADB, replace an emulator with a real phone, or connect
a phone when `adb devices` is empty.
When this preflight report exists, `make_submission_bundle.ps1` copies it into
the submission ZIP under `final/`, and `verify_submission_bundle.ps1` checks the
Markdown/JSON pair for consistency.
The same bundle path is used for `reports/final_cloud_phone_submission_latest.*`
after the strict final wrapper succeeds; the verifier checks that a packaged OK
final report carries the immutable packaging contract plus the required cloud
and physical-phone evidence fields.
Failed finalizer reports stay in `reports/` for diagnosis but are not packaged
by `make_submission_bundle.ps1`; the submission verifier records
`final_cloud_phone_submission_report.status` so a reviewer can distinguish
`absent`, `ok`, `not_ok`, and invalid report states.
Because the final report is inside the ZIP, any `submission_zip` and
`submission_verification_json` hashes inside that report are explicitly marked
as a `pre_final_report_bundle_snapshot`; the post-report verifier output outside
the ZIP is the proof for the final packaged bundle itself.
The preflight report also includes a `Final Evidence Contract` section listing
the exact cloud and phone fields that must become true in the final wrapper:
effective cloud deployment status, release cloud APK mode, physical device
selection, non-emulator proof, captured valid PNG screenshot, and matching
screenshot SHA256.
The submission script runs `verify_submission_bundle.ps1` after creating the ZIP. The verifier writes `outputs/submission/SUBMISSION_BUNDLE_VERIFICATION.*` and checks manifest hashes, the release gate report, quality reports, phone evidence, cloud bundle smoke reports, cross-artifact SHA/size consistency, and the nested clean source ZIP.
`audit_project_goal_completion.ps1` writes `reports/goal_completion_audit_latest.*`, a compact requirement-by-requirement audit against the original refactor, 95% quality, PC/phone and LaTeX-report goals. It is intentionally allowed to report `Complete: False` until the permanent Render APK and real Android device screenshot proof exist.
Use `-SkipFlutter`, `-SkipDesktopSmoke`, or `-SkipFreshRenderVenv` only for narrow local debugging.

Image API:

```powershell
curl -X POST "http://127.0.0.1:8001/factcheck-image" -F "analysis_type=screenshot" -F "image_file=@screenshot.png"
curl -X POST "http://127.0.0.1:8001/factcheck-image" -F "analysis_type=ai_image" -F "image_file=@image.png"
```

## Evaluate

```powershell
python scripts/eval_factcheck_v3.py --dataset data/factcheck/versions/eval_cases_v3_60.jsonl --out outputs/factcheck_runs/eval_results_v1.json
python scripts/report_factcheck.py --eval outputs/factcheck_runs/eval_results_v1.json --out-md outputs/factcheck_runs/final_report.md
python scripts/register_eval_run.py --dataset data/factcheck/versions/eval_cases_v3_60.jsonl --eval outputs/factcheck_runs/eval_results_v1.json --dataset-version v3_60 --pipeline-version best_accuracy_v2 --notes "best accuracy v2"
```

Live news credibility smoke:

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

This deterministic gate checks News, Facts, Images, hidden screenshot-OCR regressions, and the API/mobile contract separately.
It fails if any section drops below 95% or below its section-specific minimum case count.

AI-image detector benchmark:

```powershell
python scripts/run_ai_image_detector_eval.py --existing-only
```

The image benchmark reads `data/image_eval/v1/manifest.jsonl`, writes the latest report under `outputs/ai_image_eval/`, and records versioned run history under `reports/image_detector_runs/`. Treat false positives (`real` images labeled `likely_ai`) as the highest-risk failure mode.

Outputs:
- `reports/quality_pack_v3_live.json`
- `reports/quality_pack_v3_live.md`
- `outputs/factcheck_runs/life_facts_v1_results.json`
- `reports/life_facts_v1_report.md`
- `outputs/ai_image_eval/ai_image_detector_eval.md`
- `reports/image_detector_runs/<run-id>.md`

Judge release quality by hard-verdict precision, credibility calibration for ordinary news, clean abstention behavior, and source/domain breakdown.
Broad claim datasets such as `v3_60` remain useful diagnostics, but ordinary news credibility should also be evaluated with live URL smoke sets.

## Repo Notes
- Canonical engine lives in `src/factcheck/`.
- `src/predict.py` and `src/api.py` are compatibility shims over the canonical engine.
- Legacy multimodal / training code is archived under `archive/legacy_multimodal/`.
- Legacy fact-check v1 wrappers are archived under `archive/legacy_factcheck_v1/`.
- Archived code is outside the default product path; see `docs/legacy_ml_inventory.md`.
- Default `requirements.txt` and `requirements.lock.txt` are product-runtime
  files. Optional Torch/Transformers dependencies live in
  `requirements.optional-ai.txt`, while archived training dependencies live in
  `requirements.legacy-train.txt`.
