# Next Chat Handoff - Verity Lens / Fake News Detector

Дата handoff: 2026-05-29  
Основной язык общения с пользователем: русский  
Проект лежит здесь:

```powershell
C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector
```

Этот файл сделан как один большой контекст для следующего Codex-чата. Если ты новый агент, начни отсюда: здесь описано, что построено, как всё запускать, где лежат важные файлы, что уже тестировалось, какие есть риски, и что делать дальше.

## Коротко О Проекте

Продукт называется **Verity Lens**. Изначально это был fake news detector, но сейчас продукт шире:

- проверка новостных URL;
- проверка отдельных фактов/утверждений;
- проверка скриншотов через OCR;
- проверка фото/картинок на риск AI-generation;
- Windows desktop app;
- Flutter mobile app для Android/iOS/Web;
- FastAPI backend, который можно запускать локально или деплоить в Render.

Главная идея продукта: **не притворяться уверенным, когда данных мало**. Для настоящей проверки фактов `true/fake` выдаётся только когда есть надёжная причина. Для новостей чаще выдаётся credibility score, а не жёсткое “true/fake”.

## Важный Продуктовый Принцип

Система должна быть осторожной:

- Если факт явно подтверждён: `true`.
- Если факт явно опровергнут: `fake`.
- Если доказательств мало, источники конфликтуют или текст слишком общий: `uncertain`.
- Для новостной статьи результат обычно `verdict="uncertain"` плюс `credibility`.
- Для AI-картинок это **risk assessment**, а не абсолютное доказательство.

Не делай так, чтобы приложение уверенно называло что-то фейком без сильного сигнала. Это уже было критическим багом в прошлых итерациях.

## Текущее Состояние

Работает:

- Web UI на FastAPI.
- REST API для мобильного клиента.
- Windows desktop wrapper через PyWebView.
- Flutter mobile app, бренд `Verity Lens`.
- APK сборка.
- Временный internet tunnel через Cloudflare quick tunnel.
- Подготовка к постоянному cloud backend через Render/Docker.
- Unit/integration tests для backend.
- Flutter analyze/test.

Последняя полная проверка была 2026-05-29 после source-bundle hardening и
финальной упаковки:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Результат:

```text
Ran 111 tests
OK
```

Flutter:

```powershell
cd apps\fake_news_detector_flutter
flutter analyze
flutter test
```

Результат:

```text
No issues found
7 tests passed
```

Также проходит `scripts\run_release_gate.ps1`: backend tests, product acceptance,
PDF report, Render bundle, smoke-тест распакованного Render ZIP, phone readiness
refresh, desktop smoke, desktop package verification, Flutter analyze и Flutter
tests.

## Главные Директории И Файлы

Backend core:

```text
src\factcheck\service.py
src\factcheck\decision.py
src\factcheck\retrieval.py
src\factcheck\evidence.py
src\factcheck\claims.py
src\factcheck\common_knowledge.py
src\factcheck\news_credibility.py
src\factcheck\image_analysis.py
src\factcheck\source_registry.py
src\factcheck\schemas.py
src\factcheck\config.py
```

Entrypoints:

```text
src\ui.py              - browser/web UI
src\api_factcheck.py   - REST API for mobile/cloud
src\desktop_app.py     - Windows/PyWebView desktop app
src\predict_factcheck.py
run_desktop_app.bat
```

Flutter:

```text
apps\fake_news_detector_flutter\lib\main.dart
apps\fake_news_detector_flutter\lib\api_client.dart
apps\fake_news_detector_flutter\test\widget_test.dart
apps\fake_news_detector_flutter\tool\build_internet_apk.ps1
```

Cloud/Render:

```text
Dockerfile
render.yaml
requirements.api.txt
scripts\verify_cloud_api.ps1
scripts\build_phone_for_cloud.ps1
scripts\make_render_backend_bundle.ps1
docs\mobile_flutter_render.md
```

Windows desktop packaging:

```text
packaging\FakeNewsDetector.spec
scripts\build_windows.ps1
scripts\make_windows_icon.py
assets\app_icon.svg
assets\app_icon.png
assets\app_icon_square.png
```

Tests:

```text
tests\test_factcheck_core.py
apps\fake_news_detector_flutter\test\widget_test.dart
```

Existing handoffs:

```text
HANDOFF_2026-03-17.md
HANDOFF_2026-04-08.md
NEXT_CHAT_HANDOFF_2026-05-07.md
NEXT_CHAT_HANDOFF_2026-05-29.md  - this file
```

## Public API Contract

REST API:

```text
GET  /health
GET  /ready
POST /factcheck
POST /factcheck-image
```

`POST /factcheck` body:

```json
{
  "text": "claim or article note",
  "url": "optional URL"
}
```

`POST /factcheck-image` multipart fields:

```text
image_file=<file>
analysis_type=screenshot|ai_image
question=<optional text/context>
```

Public result shape:

```json
{
  "verdict": "true|fake|uncertain",
  "confidence": 0.0,
  "summary": "short explanation",
  "claim": "normalized claim",
  "evidence": [],
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
    "ai_label": "likely_ai|likely_not_ai|uncertain",
    "warnings": [],
    "reasons": [],
    "metadata": {}
  },
  "trace": {}
}
```

Important: keep this contract stable. Flutter depends on it.

## Backend Поведение

### Fact Mode

Main orchestrator:

```text
src\factcheck\service.py
```

Important behavior:

- Public pipeline is `best_accuracy`.
- Public UI/API do not expose internal modes.
- The orchestrator can internally run fact-check strategy and trusted research fallback.
- Simple facts can be answered locally by common knowledge / arithmetic / office-holder helpers.
- If explicit fact-check evidence is missing, system should abstain unless trusted research fallback has enough support.

Important improvements already made:

- Fact-check-only decision accepts explicit verdict even if parser did not set `verdict_source`.
- Summary now lists only verdict-relevant sources. For `fake`, it should not cite neutral/support sources as if they refuted the claim.
- When factcheck-only misses, service can run trusted research fallback over trusted news/research domains.
- Simple facts were expanded: elephants/mammals/insects, capitals, Earth/Sun orbit, arithmetic, basic everyday facts.
- Screenshot question claim can override noisy OCR text when the user provides an assertive claim.

### News Mode

Main file:

```text
src\factcheck\news_credibility.py
```

Current policy:

- News URL returns `verdict="uncertain"` plus `credibility`.
- It should not say “Likely reliable” as a truth verdict.
- Credibility score uses source trust, article quality, corroboration, and risk.
- Unknown/social/low-trust sources are penalized.
- Official/institutional pages can be `high` even without independent corroboration if the page is a proper article/release and has no severe flags.

Important recent fix:

```text
trusted_article_source_quality_floor
```

Current floor behavior:

- `institutional`: floor `0.720`
- `primary_news`: floor `0.640`
- `major_news`: floor `0.500`

This was added because official sources were being scored too low when there was no independent corroboration.

Regression tests:

```text
test_trusted_news_article_without_corroboration_can_still_be_medium
test_institutional_article_without_corroboration_can_still_be_high
```

### Screenshot Mode

Main file:

```text
src\factcheck\image_analysis.py
```

Flow:

1. Validate image.
2. OCR via `rapidocr_onnxruntime`.
3. If user provided an assertive claim in `question`, check that claim.
4. Otherwise check OCR text and use detected URL only when OCR text is the check input.

Important fix:

If screenshot OCR says one thing but user asks a specific assertive claim, the app should verify the user claim, not blindly verify the OCR noise. This fixed a real critical UX/logic issue.

Regression test:

```text
test_screenshot_factcheck_uses_user_claim_as_focus_when_provided
```

### AI Image Mode

Main file:

```text
src\factcheck\image_analysis.py
```

Policy:

- Metadata markers like `Stable Diffusion`, `ComfyUI`, `DALL-E`, `Midjourney` are strong AI signals.
- Common square dimensions are weak signals.
- Missing camera metadata is **not proof** of AI.
- Camera metadata is **not proof** of real.
- Optional model can be enabled by env var.
- Without strong metadata/model signal, the detector should return `uncertain`.

Important env var:

```text
FACTCHECK_AI_IMAGE_MODEL
```

Values:

- `metadata_only` or `disabled`: no heavy model, use metadata/forensics only.
- `haywoodsloan/ai-image-detector-deploy`: optional HuggingFace image classifier.

Cloud default is now `metadata_only`, because Render free/small instances may not survive heavy model download/load.

## Common Knowledge And Current Facts Risk

File:

```text
src\factcheck\common_knowledge.py
data\factcheck\common_knowledge_v1.json
```

There are local facts and current-office helpers, including US President, UK Prime Minister, Fed Chair transition, Artemis II crew, etc.

Warning for successor:

Some “current office” facts are time-sensitive. The system date now is 2026-05-29. If user asks about latest/current political or office-holder facts, do not trust memory. Verify with official sources or update the local rules. The code may contain date-bound assumptions from earlier testing.

## Web UI

Main file:

```text
src\ui.py
```

UI has four sections:

- News
- Facts
- Screenshots
- Images

Design changes already made:

- Section menu/navigation.
- Smooth movement between sections.
- Warm colors.
- Mode-specific colors.
- Guide/instruction buttons.
- Mobile-friendly layout.
- Separate result rendering for credibility vs fact verdict.
- Paste/drop image support.

Common web run command:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.ui:app --host 127.0.0.1 --port 8018
```

Then open:

```text
http://127.0.0.1:8018/check#newsTool
```

## Windows Desktop App

Entry:

```text
src\desktop_app.py
```

Build files:

```text
packaging\FakeNewsDetector.spec
scripts\build_windows.ps1
scripts\make_windows_icon.py
```

Desktop app is a PyWebView wrapper around existing web UI. It does not rewrite backend behavior.

Run smoke:

```powershell
.\.venv\Scripts\python.exe -m src.desktop_app --smoke --port 0
```

Build portable Windows folder:

```powershell
.\scripts\build_windows.ps1
```

Expected output:

```text
dist\FakeNewsDetector\FakeNewsDetector.exe
```

## Flutter Mobile App

Path:

```text
apps\fake_news_detector_flutter
```

App label:

```text
Verity Lens
```

Important files:

```text
apps\fake_news_detector_flutter\lib\main.dart
apps\fake_news_detector_flutter\lib\api_client.dart
apps\fake_news_detector_flutter\android\app\src\main\AndroidManifest.xml
apps\fake_news_detector_flutter\test\widget_test.dart
```

Android manifest includes:

```xml
<uses-permission android:name="android.permission.INTERNET" />
android:label="Verity Lens"
android:usesCleartextTraffic="true"
```

Flutter dependencies:

```yaml
file_picker
http
http_parser
shared_preferences
```

Mobile modes:

- News: URL + optional article note -> `POST /factcheck`
- Facts: claim text -> `POST /factcheck`
- Screenshots: image + optional question -> `POST /factcheck-image`, `analysis_type=screenshot`
- Images: image + optional context -> `POST /factcheck-image`, `analysis_type=ai_image`

Mobile UI was updated to show:

- `News credibility`
- source/article/corroboration/risk metrics
- risk flags
- screenshot OCR confidence
- image reasons/warnings

Tests:

```powershell
cd apps\fake_news_detector_flutter
flutter analyze
flutter test
```

Known latest result:

```text
No issues found
7 tests passed
```

## APKs And Phone Artifacts

Current phone output folder:

```text
outputs\phone_download
```

Known files as of 2026-05-29:

```text
FakeNewsDetector.apk             49,663,093 bytes  2026-05-07 21:39:54
VerityLens.apk                   49,663,093 bytes  2026-05-07 21:39:54
VerityLens-internet.apk         186,791,714 bytes  2026-05-16 13:10:35
VerityLens-internet-api-url.txt          61 bytes  2026-05-16 13:10:36
```

`VerityLens-internet.apk` was built with temporary Cloudflare tunnel URL:

```text
https://tim-hardware-impressive-forgotten.trycloudflare.com
```

That URL only works while the local PC server/tunnel is running. It is **not** permanent.

For a permanent phone app, use Render backend and build:

```powershell
.\scripts\build_phone_for_cloud.ps1 -ApiBaseUrl https://<render-app>.onrender.com -Mode release
```

Expected output:

```text
outputs\phone_download\VerityLens-cloud.apk
```

## Permanent Phone Without Computer

This is the current highest-priority next product step.

The phone app cannot run the Python engine locally. It is a Flutter client. For the phone to work without the computer, the FastAPI backend must run in the cloud.

Prepared cloud deployment package:

```text
outputs\cloud_deploy\verity-lens-render-backend.zip
```

Known metadata:

```text
verity-lens-render-backend.zip  1,575,140 bytes  2026-05-21 17:34:43
```

Staged source folder:

```text
outputs\cloud_deploy\render_backend_source
```

It contains:

```text
Dockerfile
render.yaml
requirements.api.txt
README.md
.env.example
src
data\factcheck
config
```

How to regenerate the zip:

```powershell
.\scripts\make_render_backend_bundle.ps1
```

How to deploy:

1. Upload/push the Render backend source to a GitHub repo.
2. In Render, create Blueprint/Web Service from `render.yaml`.
3. Wait for deploy.
4. Confirm:

```text
https://<render-app>.onrender.com/health
```

should return:

```json
{"status":"ok","service":"factcheck"}
```

5. Verify from local repo:

```powershell
.\scripts\verify_cloud_api.ps1 -ApiBaseUrl https://<render-app>.onrender.com
```

6. Build final APK:

```powershell
.\scripts\build_phone_for_cloud.ps1 -ApiBaseUrl https://<render-app>.onrender.com -Mode release
```

Important limitation:

The current agent could not create Render service automatically because no Render/GitHub auth was available in environment and no `render` CLI was installed. User must provide a Render URL or credentials/account workflow.

## Cloud Docker Details

Dockerfile currently uses:

```dockerfile
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FACTCHECK_AI_IMAGE_MODEL=metadata_only
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.api.txt /app/requirements.api.txt
RUN pip install --no-cache-dir -r /app/requirements.api.txt
COPY . /app
EXPOSE 8001
CMD python -m uvicorn src.api_factcheck:app --host 0.0.0.0 --port ${PORT:-8001}
```

`requirements.api.txt`:

```text
fastapi==0.111.0
uvicorn==0.30.0
python-multipart==0.0.9
requests==2.32.5
beautifulsoup4==4.12.0
numpy==1.26.4
PyYAML==6.0.1
Pillow==10.0.0
rapidocr-onnxruntime==1.4.4
```

Render config:

```yaml
services:
  - type: web
    name: fake-news-detector-api
    runtime: docker
    plan: free
    dockerfilePath: ./Dockerfile
    healthCheckPath: /health
    envVars:
      - key: FACTCHECK_CORS_ORIGINS
        value: "*"
      - key: FACTCHECK_AI_IMAGE_MODEL
        value: metadata_only
      - key: FACTCHECK_MAX_SEARCH_RESULTS
        value: "6"
      - key: FACTCHECK_MAX_DOCUMENTS
        value: "6"
      - key: FACTCHECK_MAX_EVIDENCE
        value: "5"
```

Why `metadata_only`:

- Render free/small plans can be tight on RAM/startup time.
- Heavy `transformers/torch` vision model may fail or make deploy slow.
- Metadata/forensics mode still catches strong AI metadata signals and stays conservative.
- If user gets a larger Render instance, they can set:

```text
FACTCHECK_AI_IMAGE_MODEL=haywoodsloan/ai-image-detector-deploy
```

and add heavier deps if needed.

## Temporary Internet Demo

There is a script:

```text
scripts\start_public_api_tunnel.ps1
```

Usage:

```powershell
.\scripts\start_public_api_tunnel.ps1 -BuildApk
```

It starts local API and Cloudflare quick tunnel, then builds `VerityLens-internet.apk`.

Important:

- This is only for demos.
- PC must stay on.
- Tunnel process must stay running.
- URL can change after restart.
- This does not satisfy “phone works without computer”.

## Typical Commands

Root:

```powershell
cd C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector
```

Run API locally:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.api_factcheck:app --host 0.0.0.0 --port 8001
```

Run web UI:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.ui:app --host 127.0.0.1 --port 8018
```

Run backend tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Run desktop smoke:

```powershell
.\.venv\Scripts\python.exe -m src.desktop_app --smoke --port 0
```

Run Flutter checks:

```powershell
cd apps\fake_news_detector_flutter
flutter analyze
flutter test
```

Build temporary internet APK:

```powershell
.\scripts\start_public_api_tunnel.ps1 -BuildApk
```

Build APK for permanent Render URL:

```powershell
.\scripts\build_phone_for_cloud.ps1 -ApiBaseUrl https://<render-app>.onrender.com -Mode release
```

Verify cloud API:

```powershell
.\scripts\verify_cloud_api.ps1 -ApiBaseUrl https://<render-app>.onrender.com
```

Make Render backend zip:

```powershell
.\scripts\make_render_backend_bundle.ps1
```

## Known Good Live Test Matrix From Earlier Work

These were tested in previous iterations, not re-run on 2026-05-29:

Facts:

```text
Elephants are mammals. -> true ~0.82
Elephants are insects. -> fake ~0.78
The capital of France is Paris. -> true ~0.82
The capital of France is Berlin. -> fake ~0.78
Earth orbits the Sun. -> true ~0.82
The Sun orbits the Earth. -> fake ~0.78
COVID-19 vaccines contain microchips. -> fake ~0.84, evidence from politifact.com
```

News:

```text
https://www.federalreserve.gov/newsevents/pressreleases/other20260515a.htm
-> verdict uncertain, credibility high, score ~0.72
```

Screenshots:

```text
upload screenshot + question "Elephants are insects."
-> fake ~0.78, because user claim overrides OCR text
```

AI image:

```text
PNG with Stable Diffusion/ComfyUI metadata
-> ai_label likely_ai, score high

ordinary real vehicle photo without strong AI signal
-> uncertain, not accused
```

## Important Tests To Know

Backend single test file has many regression tests:

```text
tests\test_factcheck_core.py
```

Particularly important:

```text
test_service_uses_trusted_research_after_factcheck_miss
test_factcheck_only_accepts_explicit_verdict_without_parser_source_name
test_summary_lists_only_verdict_relevant_sources
test_best_pipeline_handles_capital_and_orbit_claims
test_screenshot_factcheck_uses_user_claim_as_focus_when_provided
test_institutional_article_without_corroboration_can_still_be_high
test_trusted_news_article_without_corroboration_can_still_be_medium
test_flutter_mobile_project_and_render_files_exist
test_api_cors_preflight_supports_flutter_web
```

Flutter tests:

```text
apps\fake_news_detector_flutter\test\widget_test.dart
```

Important Flutter test cases:

```text
Facts mode submits a claim and renders the verdict
Image modes show a friendly missing-file error
News mode renders credibility details from the API
Result card renders image warnings and OCR confidence
API settings save a reusable backend URL
public build default replaces a saved local API URL
```

## Current Known UX State

Web UI:

- Good enough warm design.
- Four sections.
- Guide buttons.
- Mobile responsive-ish.
- Browser UI path works when server is running.

Flutter UI:

- Warm Material 3 style.
- Bottom NavigationBar on phone.
- NavigationRail on wider screens.
- Gear button for API URL.
- API URL saved via shared_preferences.
- If APK built with public HTTPS URL, app ignores previously saved local/private API URL.

This behavior is important because user previously saved `http://192.168.1.16:8001`, which broke outside Wi-Fi. Logic now prefers build default if it is public HTTPS and saved URL is local/private.

## How User Installs APK

User only needs one file:

```text
outputs\phone_download\VerityLens-cloud.apk
```

or temporary:

```text
outputs\phone_download\VerityLens-internet.apk
```

On Android:

1. Transfer APK by USB/Telegram/Drive.
2. Open APK.
3. Allow install from this source if prompted.
4. Install or update.
5. App appears as `Verity Lens`.

## Git/Repo Notes

At earlier points this working folder did not contain a `.git` directory. Do not assume `git status` works. Treat local files as source of truth unless user gives a GitHub repo.

Do not delete unrelated folders:

```text
.venv
build
dist
outputs
data
reports
```

Build outputs can be large; cloud bundle script intentionally selects only needed files.

## Important Engineering Constraints

When editing:

- Prefer existing project patterns.
- Keep public API contract stable.
- Use tests for logic changes.
- Do not make fact checker more aggressive without evidence.
- Do not silently change mobile API fields.
- Do not break Windows desktop while changing cloud/mobile.
- Do not put heavy training dependencies into cloud image unless required.

If adding dependencies:

- Full local requirements: `requirements.txt` / `requirements.lock.txt`.
- Cloud API requirements: `requirements.api.txt`.
- Flutter deps: `apps\fake_news_detector_flutter\pubspec.yaml`.

## User’s Recent Intent

The user wants:

1. Phone app that works without a computer.
2. Better fact-checking reliability.
3. Better behavior for news, screenshots, AI images.
4. Easy APK install/update on phone.
5. Eventually a polished demo.

Most urgent unfinished task:

```text
Deploy backend to Render or another cloud host, get permanent HTTPS API URL, then build VerityLens-cloud.apk.
```

The current blocker is not code; it is cloud account/deployment access.

## If User Gives Render URL

Run:

```powershell
.\scripts\verify_cloud_api.ps1 -ApiBaseUrl https://THE-URL.onrender.com
```

If OK:

```powershell
.\scripts\build_phone_for_cloud.ps1 -ApiBaseUrl https://THE-URL.onrender.com -Mode release
```

Then tell user to install:

```text
outputs\phone_download\VerityLens-cloud.apk
```

Also test from phone if possible:

- Facts: `Elephants are insects.`
- Facts: `The capital of France is Paris.`
- News: an official/government article URL.
- Screenshots: upload readable claim screenshot.
- Images: upload AI-metadata sample and real photo.

## If User Wants You To Deploy To Render

You need one of:

- Render dashboard access from user in browser;
- GitHub repo already connected to Render;
- Render API key/CLI configured;
- user manually creates service and gives URL.

Without that, you can only prepare files and instructions.

Do not fake that deployment is done. A phone app cannot work independently until backend is actually live on public HTTPS.

## If User Wants Offline Phone App

Current Flutter app cannot do offline fact-checking. It does not embed Python, OCR engine, retrieval, or models. Offline version would be a different project:

- on-device OCR;
- local rules/data;
- maybe small on-device models;
- no web fact retrieval;
- much lower capability.

For v1, recommended path is cloud backend.

## Known Risk Areas

1. Current facts may become outdated.
2. Render free plan may sleep, causing first request delay.
3. OCR can misread screenshots.
4. AI image detection is inherently unreliable.
5. Search/retrieval quality depends on live web and accessible pages.
6. Some official sites block scraping; Jina/fallback parser may help but not always.
7. Heavy AI image model on cloud can fail due to RAM/time.
8. Flutter release APK still needs manual install unless Play Store/TestFlight pipeline is added.

## Update: Desktop Packaging Cleanup

Completed on 2026-05-29:

- `src/desktop_app.py` now defaults `FACTCHECK_AI_IMAGE_MODEL` to `metadata_only` for the packaged desktop app.
- `src/factcheck/claim_prior.py` and `src/factcheck/claim_prior_transformer.py` no longer import Torch/Transformers at module load; the old helper `utils.py` is now archived under `archive/legacy_multimodal/src/`.
- `packaging/FakeNewsDetector.spec` no longer collects all `src` submodules and excludes optional heavy ML/research packages (`torch`, `torchvision`, `transformers`, `datasets`, `pandas`, `pyarrow`, `sklearn`, `huggingface_hub`, `tokenizers`, `safetensors`).
- `scripts/build_windows.ps1` now refreshes `dist\FakeNewsDetector-Windows-Portable.zip` after each successful build.
- Fresh Windows build passed packaged smoke. Current artifact sizes:
  - folder: `dist\FakeNewsDetector` = about 248 MiB, 916 files;
  - zip: `dist\FakeNewsDetector-Windows-Portable.zip` = about 106 MiB.
- Verified the folder and zip contain no top-level heavy ML packages listed above.
- Added `scripts\verify_desktop_package.ps1`; it verifies the EXE, portable ZIP,
  required ZIP entries, absence of heavy optional ML packages, and packaged
  `--smoke --port 0` output.
- Latest desktop package verification:
  - generated: `2026-05-29T16:42:12.2024083+02:00`;
  - OK: true;
  - EXE SHA256:
    `617D9BF8D0A93A04B28EE9B7C534F3949F59524F3182750FA7503E339FB215DB`;
  - ZIP SHA256:
    `750C5A9A07977E4FAB32FC4AD4B238964D2ECF9C49EFE5CAC61EC00B1D93A83E`;
  - ZIP size: `110789654` bytes;
  - ZIP entries: `929`;
  - forbidden heavy-package entries: `0`;
  - packaged smoke output contains `Smoke OK:`.
- `python -m unittest discover -s tests -v` passes: 111 tests OK.
- Product acceptance passes: 61/61, all sections at 100%.
- `scripts/run_release_gate.ps1` passes, including PDF report, Render bundle,
  Render bundle smoke, phone readiness refresh, desktop smoke, desktop package
  verification, Flutter analyze, and Flutter tests.
- Report PDF was rebuilt after layout cleanup. Tectonic still prints harmless underfull/fontconfig warnings, but no overfull warnings remain.

## Update: Flutter Backend Status

Completed after the desktop packaging cleanup:

- Flutter `FactCheckGateway` now has `checkHealth()`.
- `FactCheckApiClient` calls `/health` with a short timeout and returns a structured `ApiHealthStatus`.
- The mobile app shows a visible API connection banner at the top of every mode:
  - `API connected` when `/health` returns `{"status":"ok"}`;
  - `API not reachable` when the phone cannot reach the backend;
  - refresh button tooltip: `Check API connection`.
- Runtime API settings still work through the gear icon; after changing URL, the app refreshes backend status.
- Flutter tests increased to 7/7 and include the connected/offline banner behavior.
- README, RUNBOOK, mobile Render docs, and LaTeX report were updated.
- Fresh LAN APK rebuilt after the Flutter status change and later mobile
  release polish:
  - `outputs\phone_download\VerityLens-lan.apk`
  - API base URL: `http://192.168.1.16:8001`
  - APK mode: release
  - APK size: `49843613` bytes
  - APK SHA256: `6D1B9D0372ABA7020D866DA65EF882A2B5E99ADBA53FEC88BD8E8776F1B8290E`
  - status file: `outputs\phone_download\VerityLens-lan-status.md`
- Verified LAN backend health from this PC: `http://192.168.1.16:8001/health` returns `{"status":"ok","service":"factcheck"}`.
- Final release gate after this change passed:
  - backend tests: 108 OK;
  - product acceptance: 61/61;
  - Flutter analyze: no issues;
  - Flutter tests: 7/7.

## Update: Runtime `src` Cleanup

Completed after the Flutter backend status work:

- Active `src` now contains only runtime entrypoints (`api_factcheck.py`, `api.py`,
  `desktop_app.py`, `predict_factcheck.py`, `predict.py`, `ui.py`, `nli.py`) and
  the canonical `src/factcheck/` package.
- Old multimodal helper modules (`build_manifest.py`, `callbacks.py`,
  `prepare_data.py`, `split_data.py`, `utils.py`) are archived under
  `archive/legacy_multimodal/src/`.
- Old root-level fact-check v1 wrappers (`cache.py`, `claims.py`,
  `eval_factcheck.py`, `fact_pipeline.py`, `fact_pipeline_v3.py`, `retrieval.py`,
  `seed_evidence.py`, `source_scoring.py`) are archived under
  `archive/legacy_factcheck_v1/src/`.
- The single-eval markdown reporter was moved to `scripts/report_factcheck.py`,
  and README/RUNBOOK now point there.
- Backend regression coverage includes a guard that these legacy modules stay
  outside runtime `src`.
- After later verification, project-generated cache directories were removed:
  `src\__pycache__`, `src\factcheck\__pycache__`, `scripts\__pycache__`,
  `tests\__pycache__`, and `.pytest_cache`. The `.venv` caches were left alone.
  A root-level runtime scan confirms there are no old archived modules such as
  `src\utils.py`, `src\fact_pipeline.py`, or matching stale `.pyc` files in
  runtime `src`.

## Update: Phone Readiness And Tunnel Diagnostics

Completed after runtime cleanup:

- `scripts/start_public_api_tunnel.ps1` now records a more useful failure reason
  in `outputs\public_api_tunnel_info.json`, supports `-VerifyTimeoutSeconds`,
  and has `-KeepProcessesOnFailure` for diagnosis.
- A quick-tunnel retry on 2026-05-29 created Cloudflare URLs, but public
  verification failed because DNS did not resolve the generated
  `*.trycloudflare.com` host even after 180 seconds. No internet APK was built
  from that failed URL.
- Added `scripts/check_phone_readiness.ps1`.
  It writes `outputs\phone_download\PHONE_READINESS.md` and
  `outputs\phone_download\phone_readiness.json`.
- It now also reads `outputs\phone_download\PHONE_INSTALL_PAGE.json`, checks the
  install page with HTTP GET, checks the APK download with HTTP HEAD, compares
  content length to the expected APK size, and exposes
  `phone_install_download` in readiness.
- Current readiness report says:
  - PC desktop package: true;
  - phone on same Wi-Fi: true;
  - Render deploy package: true;
  - permanent cloud phone: false until a verified public HTTPS API and
    `VerityLens-cloud.apk` exist;
  - temporary tunnel phone may be false until the LocalTunnel fallback below is
    running and rechecked.
- `scripts/run_release_gate.ps1` now refreshes the phone readiness report and,
  when `-ApiBaseUrl ... -BuildCloudApk` is used, requires cloud phone readiness.

## Update: Temporary Internet Phone APK Via LocalTunnel

Completed after Cloudflare quick-tunnel failure:

- Added `scripts/start_localtunnel_api.ps1` as a fallback temporary internet
  demo path. It starts/reuses local API on port 8001, opens `npx localtunnel`,
  verifies `/health`, `/ready`, and `Elephants are insects.` before trusting the
  URL, and can build `VerityLens-internet.apk`.
- Current verified temporary API:
  `https://slick-rules-deny.loca.lt`
- Current temporary internet APK:
  `outputs\phone_download\VerityLens-internet.apk`
  size `49843613` bytes.
- Current status file:
  `outputs\phone_download\PHONE_BUILD_STATUS.md`
- Current `outputs\phone_download\PHONE_READINESS.md` reports:
  - PC desktop package: true;
  - phone on same Wi-Fi: true;
  - Render deploy package: true;
  - phone install/download: true;
  - temporary tunnel phone: true;
  - permanent cloud phone: false until Render/public HTTPS backend and
    `VerityLens-cloud.apk` are built.
  - latest generated timestamp: `2026-05-29T17:21:43.6145043+02:00`;
  - quick tunnel probe: `fake / 0.78`.
  - install page: `http://192.168.1.16:8010/index.html` status 200;
  - APK download: `http://192.168.1.16:8010/VerityLens-internet.apk` status
    200 with content length `49843613`.
- Added `scripts/verify_phone_apk.ps1`; it writes
  `outputs\phone_download\PHONE_APK_VERIFICATION.md` and `.json` with APK size,
  SHA256, expected mode, API URL, `/health`, `/ready`, and a fact-check probe.
- The APK verifier now also scans the APK contents and requires the expected
  API URL to be embedded in the Flutter binary, preventing stale APK/API URL
  mismatches from passing verification.
- Latest APK verification for `VerityLens-internet.apk`:
  - generated: `2026-05-29T17:16:36.9672512+02:00`;
  - OK: true;
  - mode: release;
  - SHA256: `5B238B73268402CBD42970E7B6FD3719FA93B89B3DFF8EE3C13BBBA768FA2AC3`;
  - API: `https://slick-rules-deny.loca.lt`;
  - health: ok;
  - ready: ready;
  - fake probe: `fake / 0.78`.
  - APK contains expected API URL: true;
  - APK API URL match count: `3`.
- Added `scripts/prepare_phone_install_page.ps1`; it creates
  `outputs\phone_download\index.html`,
  `outputs\phone_download\PHONE_INSTALL_PAGE.md`, and can start a local
  download server with `-StartServer`.
- Added `scripts/make_submission_bundle.ps1`; it gathers report, docs, phone
  reports, install page, desktop zip, APKs, and Render backend bundle into
  `outputs\submission\VerityLens-submission.zip` with
  `SUBMISSION_MANIFEST.md` and SHA256 checksums.
- Latest submission zip after refreshing source bundle, release phone APKs,
  phone readiness and
  install checks:
  - path: `outputs\submission\VerityLens-submission.zip`;
  - generated: `2026-05-29T17:21:58.3826824+02:00` manifest,
    zip modified `2026-05-29T17:22:03.0638877+02:00`;
  - size: `161622904` bytes;
  - SHA256: `5F3F0963CC3969AFCFDD832D02D91A9D3F28A4BB7EF051C78DF0B2115C5C80F9`;
  - ZIP entries: `27`;
  - includes report PDF, desktop portable zip, LAN APK, temporary internet APK,
    Render backend bundle, Render bundle smoke report, phone readiness, APK
    verification, desktop package verification, install page, cloud deployment
    status, and `source\verity-lens-source.zip`.
- Added `scripts/finalize_cloud_deploy.ps1`; without `-ApiBaseUrl` it writes
  `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.md` showing that a public
  Render URL is still needed. With `-ApiBaseUrl https://<render-app>.onrender.com`
  it verifies cloud API, builds `VerityLens-cloud.apk`, verifies the APK, and
  runs phone readiness with `-RequireCloud`.
- Added `scripts/smoke_render_backend_bundle.ps1`. It extracts
  `outputs\cloud_deploy\verity-lens-render-backend.zip`, starts
  `src.api_factcheck:app` from the extracted copy, and verifies `/health`,
  `/ready`, and the `Elephants are insects.` fact-check probe.
  It also supports `-FreshVenv`, which creates a clean virtual environment,
  installs only the extracted `requirements.api.txt`, and then starts the API.
- `scripts/run_release_gate.ps1` and `scripts/finalize_cloud_deploy.ps1` both
  run this Render bundle smoke. `finalize_cloud_deploy.ps1` uses `-FreshVenv`.
  Current smoke report:
  `outputs\cloud_deploy\render_backend_smoke\RENDER_BUNDLE_SMOKE.md`, OK true,
  fresh venv requirements OK true, fake probe `fake / 0.78`.
- Current `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.md`:
  - generated: latest finalizer run after mobile release polish;
  - outcome: `awaiting_public_https_backend`;
  - Render bundle SHA256:
    `3228DAAD30D327EBE2DF1A0C18E0F96F133B5DB872DCDC6951073885F4BC5534`;
  - Render bundle smoke OK: true;
  - Render bundle requirements OK: true;
  - cloud APK exists: false.
- Keep the local API process and LocalTunnel process running while testing this
  APK. It is not a permanent submission backend.
- `scripts/build_phone_for_cloud.ps1`, `scripts/verify_cloud_api.ps1`,
  `scripts/check_phone_readiness.ps1`, and related release/finalizer scripts
  now use `scripts\cloud_url_policy.ps1`, so local/private/tunnel URLs cannot
  be mistaken for permanent cloud readiness.

## Update: Fact Reliability Expansion

Completed after the cloud/desktop package checks:

- Fixed a real product error where natural-language numeric claims such as
  `Two plus two equals four` could fall through to web retrieval and receive a
  wrong hard verdict. These now use the local arithmetic path.
- `src\factcheck\common_knowledge.py` now parses simple English number words
  from zero to ninety-nine in arithmetic equations and numeric comparisons.
- `src\factcheck\service.py` now routes short number-word arithmetic/comparison
  claims into the simple-knowledge path before retrieval.
- Added common-knowledge aliases for `USA`, `U.S.`, `US`, `U.S.A.`, colloquial
  `America`, and Poland capital claims.
- Added regression coverage:
  - `test_best_pipeline_handles_word_number_arithmetic_and_comparison`;
  - expanded `test_best_pipeline_handles_capital_and_orbit_claims`.
- Product acceptance now has 61 deterministic cases and passes:
  - facts: 31/31;
  - news: 11/11;
  - screenshots: 6/6;
  - images: 6/6;
  - API/mobile contract: 7/7.
- LaTeX report was updated and rebuilt with `111 testów OK` and `61/61 OK`.
- Windows portable desktop and Render backend bundle were rebuilt after this
  logic change, so the distributed artifacts include the fix.

## Update: Cloud APK Verification In Release Gate

Completed after the fact reliability expansion:

- `scripts\verify_phone_apk.ps1` scans the APK itself and requires the expected
  API URL to be embedded in the Flutter binary.
- `scripts\run_release_gate.ps1 -ApiBaseUrl ... -BuildCloudApk` now runs
  `verify_phone_apk.ps1` for `VerityLens-cloud.apk` with `-PermanentCloud`,
  writes `PHONE_CLOUD_APK_VERIFICATION.md/json`, and only then runs cloud phone
  readiness.
- `scripts\check_phone_readiness.ps1` now includes a `Cloud APK Verification`
  section and counts `phone_permanent_cloud=true` only when:
  - the public HTTPS API probes pass;
  - the cloud APK exists;
  - `PHONE_CLOUD_APK_VERIFICATION.json` says OK;
  - the verification API URL matches the requested cloud URL;
  - the expected API URL is found inside the APK.
- README, RUNBOOK, mobile Render docs, and the LaTeX report now describe this
  APK/API verification step.
- Release gate passed after this change. Since no Render URL was supplied,
  the new cloud APK verification step was not executed in cloud mode yet; it is
  ready for the first real Render URL.

## Update: Permanent Cloud URL Policy

Completed after cloud APK verification work:

- Added `scripts\cloud_url_policy.ps1` with shared helpers:
  - `Assert-PermanentCloudApiUrl`;
  - `Test-PrivateOrLocalHost`;
  - `Test-TemporaryTunnelHost`.
- Permanent cloud scripts now use the shared policy instead of duplicating weak
  ad hoc checks:
  - `scripts\verify_cloud_api.ps1`;
  - `scripts\build_phone_for_cloud.ps1`;
  - `scripts\finalize_cloud_deploy.ps1`;
  - `scripts\check_phone_readiness.ps1`;
  - `scripts\verify_phone_apk.ps1` when `-PermanentCloud` is passed;
  - `scripts\run_release_gate.ps1`.
- The policy requires an absolute `https://` URL and rejects:
  - temporary tunnel hosts `*.loca.lt` and `*.trycloudflare.com`;
  - `localhost`, `*.localhost`, `host.docker.internal`, and `.local` /
    `.localdomain` names;
  - single-label hosts such as `https://mybackend`;
  - private/local IPv4 ranges including `127.x.x.x`, `10.x.x.x`,
    `172.16-31.x.x`, `192.168.x.x`, `169.254.x.x`, and `0.0.0.0`;
  - IPv6 loopback/link-local/unique-local hosts.
- Added a subprocess regression test that dot-sources the PowerShell policy,
  verifies `https://example.onrender.com/` normalizes correctly, and confirms
  local/private/tunnel URLs are rejected.
- README, RUNBOOK, mobile Render docs, and the LaTeX report now document that
  permanent phone readiness requires a real public HTTPS cloud host, not a LAN
  address or temporary tunnel.
- Verification after this change:
  - targeted cloud/mobile policy tests: OK;
  - backend tests: `111` tests OK;
  - product acceptance: `61/61` OK;
  - local `scripts\run_release_gate.ps1`: passed;
  - `scripts\finalize_cloud_deploy.ps1` without Render URL: passed fresh-venv
    Render smoke and kept outcome `awaiting_public_https_backend`;
  - `scripts\make_submission_bundle.ps1`: refreshed submission ZIP; final
    source-bundle-aware SHA is recorded below.

## Update: Reproducible Source Bundle In Submission

Completed after permanent cloud URL policy:

- Added `scripts\make_source_bundle.ps1`.
- Hardened `scripts\make_source_bundle.ps1` so `-OutputPath` may be relative
  or absolute, but must stay inside the project directory.
- `scripts\make_submission_bundle.ps1` now creates and includes
  `source\verity-lens-source.zip` inside `outputs\submission\VerityLens-submission.zip`.
- The source ZIP contains the reproducible project source:
  - `src`;
  - `scripts`;
  - `tests`;
  - `apps\fake_news_detector_flutter` source/tooling;
  - `docs`, `config`, selected `data`, requirements, Docker/Render files,
    packaging files, README/RUNBOOK.
- It excludes generated/local-heavy content:
  `.venv`, `build`, `dist`, `outputs`, `archive`, `__pycache__`, `.pyc/.pyo`,
  Flutter `.dart_tool`, Flutter build output, and Android `local.properties`.
- Added regression coverage that builds a test source ZIP and checks required
  entries plus forbidden generated/local paths, using an absolute output path.
- README, RUNBOOK, and LaTeX report now mention the clean source bundle as part
  of the university submission package.
- Final verification after this change:
  - `python -m unittest discover -s tests -v`: `111` tests OK;
  - `scripts\run_release_gate.ps1`: passed;
  - `scripts\finalize_cloud_deploy.ps1`: passed fresh-venv Render smoke;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `233` entries,
    size `2867620`, SHA256
    `B628E39AD7B53F405B02B9DB5A613F72E259EC0E1B44F63AE704E79D47E7916D`;
  - final submission ZIP: `outputs\submission\VerityLens-submission.zip`,
    size `161622904`, SHA256
    `5F3F0963CC3969AFCFDD832D02D91A9D3F28A4BB7EF051C78DF0B2115C5C80F9`.

## Update: Mobile Release Polish And APK Refresh

Completed after source-bundle work:

- Android release builds now use product package id
  `app.veritylens.mobile` instead of the scaffold-like fake-news package id.
- Removed remaining Android Gradle scaffold `TODO:` comments and documented
  that university/demo release builds use debug signing until a private release
  keystore is provided.
- `scripts\build_phone_for_lan.ps1` now builds release APKs by default and
  records APK mode plus SHA256 in `VerityLens-lan-status.md`.
- Renamed internal retrieval helper `_result_relevance_stub` to
  `_query_relevance_score` so runtime code no longer carries a misleading
  prototype/stub name.
- Rebuilt and verified current APKs:
  - LAN APK: size `49843613`, SHA256
    `6D1B9D0372ABA7020D866DA65EF882A2B5E99ADBA53FEC88BD8E8776F1B8290E`;
  - temporary internet APK: size `49843613`, SHA256
    `5B238B73268402CBD42970E7B6FD3719FA93B89B3DFF8EE3C13BBBA768FA2AC3`;
  - `aapt dump badging` confirms package `app.veritylens.mobile` and label
    `Verity Lens`.
- `verify_phone_apk.ps1` passed for both LAN and temporary internet APKs:
  embedded API URL found, match count `3`, `/health` ok, `/ready` ready,
  fact-check probe `fake / 0.78`.
- Verification after this change:
  - backend tests: `111` OK;
  - product acceptance: `61/61` OK;
  - `scripts\run_release_gate.ps1`: passed;
  - `scripts\finalize_cloud_deploy.ps1`: passed fresh-venv Render smoke;
  - phone readiness: same-Wi-Fi true, temporary tunnel true, permanent cloud
    false until a real public HTTPS backend and `VerityLens-cloud.apk` exist.

## Update: Live Quality Pack In Final Submission

Completed after mobile release polish:

- Ran live quality pack against current RSS/manual guardrail cases:
  - report: `reports\quality_pack_v3_live.md`;
  - machine-readable report: `reports\quality_pack_v3_live.json`;
  - result: `17/17` passed, `0` failed, `0` errors.
- Release gate refreshed product acceptance:
  - overall: `61/61` passed;
  - facts: `31/31`;
  - news: `11/11`;
  - screenshots: `6/6`;
  - images: `6/6`;
  - API/mobile contract: `7/7`.
- Updated `docs\report\verity_lens_report.tex` and rebuilt
  `docs\report\verity_lens_report.pdf` so the university report now mentions
  both the `61/61` acceptance gate and the `17/17` live quality pack.
- Updated `scripts\make_submission_bundle.ps1` so the final ZIP includes:
  - `quality\product_acceptance_latest.md`;
  - `quality\product_acceptance_latest.json`;
  - `quality\quality_pack_v3_live.md`;
  - `quality\quality_pack_v3_live.json`.
- `scripts\make_submission_bundle.ps1` is also ready for permanent cloud
  phone finalization: if Render has been deployed and `VerityLens-cloud.apk`
  exists, it will include:
  - `phone\VerityLens-cloud.apk`;
  - `phone\PHONE_CLOUD_APK_VERIFICATION.md`;
  - `phone\PHONE_CLOUD_APK_VERIFICATION.json`;
  - `phone\VerityLens-cloud-status.md`;
  - `phone\VerityLens-cloud-api-url.txt`.
- `scripts\prepare_phone_install_page.ps1` is also ready for the permanent
  cloud APK. It always shows the current APK download, and if
  `outputs\phone_download\VerityLens-cloud.apk` exists it adds a separate
  permanent cloud APK download block with size, SHA256, embedded API URL, and
  `PHONE_CLOUD_APK_VERIFICATION` status.
- Updated README/RUNBOOK and regression tests so this does not silently
  disappear from future submissions.
- Final verification after this change:
  - targeted submission/report tests: OK;
  - targeted mobile/cloud/submission test after optional cloud-artifact support:
    OK;
  - temporary positive install-page simulation with a fake cloud APK: OK, then
    temporary cloud artifacts were removed and the real install page was
    regenerated;
  - `python -m unittest discover -s tests -v`: `111` tests OK;
  - `scripts\run_release_gate.ps1`: passed;
  - `scripts\finalize_cloud_deploy.ps1`: passed fresh-venv Render smoke;
  - `scripts\prepare_phone_install_page.ps1`: passed;
  - `scripts\check_phone_readiness.ps1`: same-Wi-Fi true, temporary tunnel
    true, permanent cloud false;
  - `scripts\make_submission_bundle.ps1`: passed.
- Current final artifacts:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161643344`, SHA256
    `A864A626CEE263165EFACD88FD96EECAB6EB6E0E814019D31855A7BDAF302AAF`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `233` entries,
    forbidden generated/local paths `0`, size `2869927`, SHA256
    `CF92792A62311794C7E32C00EF31B3B78D3C427BE559C548CAC829159C82A307`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1347988`, SHA256
    `91C16EC840F885B7AFF30345A0BBA08067A9D9E41DB85A93C723B8920AA89185`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `6CB96C455709E1C945883CB4FF6B7358DF6549382168873F91B7620C28E8326F`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843613`, SHA256
    `5B238B73268402CBD42970E7B6FD3719FA93B89B3DFF8EE3C13BBBA768FA2AC3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843613`,
    SHA256
    `6D1B9D0372ABA7020D866DA65EF882A2B5E99ADBA53FEC88BD8E8776F1B8290E`.
- Submission ZIP currently has `31` entries and includes the quality reports
  under `quality/`. It does not yet include `phone/VerityLens-cloud.apk`
  because permanent Render phone finalization has not been run with a real
  public HTTPS backend URL.

## Update: Real Android Device Smoke Hook

Completed after live quality/submission work:

- Added `scripts\smoke_phone_on_device.ps1`.
- The script finds `adb` from PATH or common Android SDK locations, installs the
  selected APK on an authorized Android device, verifies package id
  `app.veritylens.mobile`, launches `.MainActivity`, and checks foreground
  package evidence through `dumpsys`.
- Default behavior is safe for machines without a connected phone:
  - writes `outputs\phone_download\PHONE_DEVICE_SMOKE.md`;
  - writes `outputs\phone_download\PHONE_DEVICE_SMOKE.json`;
  - exits `0` with `skipped=true` if no authorized Android device is connected.
- `-RequireDevice` turns that into a strict final proof and exits non-zero
  unless the APK installs and launches on a real device.
- `scripts\run_release_gate.ps1` now supports:
  - `-PhoneDeviceSmoke` for optional report generation;
  - `-RequirePhoneDevice` for final manual proof;
  - `-PhoneDeviceApkPath`;
  - `-PhoneDeviceId`.
- `scripts\check_phone_readiness.ps1` now reports
  `Real Android device smoke` from `PHONE_DEVICE_SMOKE.json`.
- `scripts\make_submission_bundle.ps1` now includes `PHONE_DEVICE_SMOKE.md/json`
  in the submission ZIP when they exist.
- README, RUNBOOK, and mobile Render docs now document the real-device smoke
  path.
- Verification after this change:
  - `scripts\smoke_phone_on_device.ps1`: passed as skipped because no
    authorized Android device is currently connected; `adb` was found at
    `C:\Users\marke\AppData\Local\Android\Sdk\platform-tools\adb.exe`;
  - `scripts\smoke_phone_on_device.ps1 -RequireDevice`: expected failure
    without a connected phone;
  - targeted mobile/cloud/submission tests: OK;
  - `scripts\run_release_gate.ps1 -SkipFlutter -SkipDesktopSmoke -PhoneDeviceSmoke`:
    passed and generated the skipped device report;
  - full `scripts\run_release_gate.ps1`: passed;
  - `scripts\finalize_cloud_deploy.ps1`: passed fresh-venv Render smoke;
  - `scripts\prepare_phone_install_page.ps1`: passed;
  - `scripts\check_phone_readiness.ps1`: same-Wi-Fi true, temporary tunnel true,
    permanent cloud false, real Android device smoke false;
  - `scripts\make_submission_bundle.ps1`: passed.
- Current final artifacts:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161649791`, SHA256
    `DBB0AAF6CAB8FECD85408581607E205CF258710F6A5577AB1012ECCEE3D8226A`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `234` entries,
    forbidden generated/local paths `0`, size `2873620`, SHA256
    `C5AB2DCB10071D526F31DA4BB3FC8135D437B4DEC6558E6917CF27E97DADB2D0`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348185`, SHA256
    `6CD0516D13737C82821367C4503AD63463E28F59F024E9CA9A323983E50007F2`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `B31EF76FC2A19052F8D1435224611E2E8FAD3F17E04BF793F9F87E0E9856232D`;
  - phone device smoke report:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.md`, size `776`, SHA256
    `EFC1C6BFE57DA2EB7590A230A28256A063E20AAC7836A2D2DF7B36C0AC9341CD`.
- Submission ZIP currently has `33` entries and includes
  `phone/PHONE_DEVICE_SMOKE.md` and `phone/PHONE_DEVICE_SMOKE.json`. It still
  does not include `phone/VerityLens-cloud.apk` because permanent Render phone
  finalization has not been run with a real public HTTPS backend URL.

## Update: Submission Bundle Verifier And Refreshed Final Package

Completed after the real-device smoke hook:

- Added `scripts\verify_submission_bundle.ps1`.
- `scripts\make_submission_bundle.ps1` now runs the verifier after creating
  `outputs\submission\VerityLens-submission.zip`.
- The verifier writes:
  - `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`;
  - `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`.
- It checks the final ZIP manifest, SHA256/size metadata, quality reports,
  phone readiness evidence, device-smoke evidence, cloud/Render smoke status,
  suspiciously small required files, and nested source ZIP cleanliness.
- It also checks that permanent cloud phone artifacts are either all present or
  all absent. Partial cloud artifacts are treated as a failure.
- Latest verification after refreshing README/RUNBOOK/tests/source ZIP:
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`;
  - failures: none;
  - warnings: permanent cloud phone is still false; phone device smoke is still
    skipped because no authorized Android phone is connected.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161653884`, SHA256
    `D3837107C39861AB66694DCC7F41A8F03E7DFB1AD23F1D65319069728D171D89`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `235` entries,
    forbidden generated/local paths `0`, size `2877957`, SHA256
    `9BA939B89E30CFD876CD8298FEC44FC95CA9A97A3C8961EBAA0DC91716186DDA`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348185`, SHA256
    `6CD0516D13737C82821367C4503AD63463E28F59F024E9CA9A323983E50007F2`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `B31EF76FC2A19052F8D1435224611E2E8FAD3F17E04BF793F9F87E0E9856232D`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843613`, SHA256
    `5B238B73268402CBD42970E7B6FD3719FA93B89B3DFF8EE3C13BBBA768FA2AC3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843613`,
    SHA256
    `6D1B9D0372ABA7020D866DA65EF882A2B5E99ADBA53FEC88BD8E8776F1B8290E`;
  - phone device smoke report:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.md`, size `776`, SHA256
    `EFC1C6BFE57DA2EB7590A230A28256A063E20AAC7836A2D2DF7B36C0AC9341CD`.
- Important: this is the freshest artifact block. Older artifact blocks above
  are historical and have been superseded by this section.

## Update: Path Safety Refactor For Build And Bundle Scripts

Completed after the submission verifier refresh:

- Added `scripts\path_safety.ps1`.
- Refactored path checks in:
  - `scripts\build_windows.ps1`;
  - `scripts\make_source_bundle.ps1`;
  - `scripts\make_render_backend_bundle.ps1`;
  - `scripts\smoke_render_backend_bundle.ps1`;
  - `scripts\make_submission_bundle.ps1`.
- The shared helper now rejects sibling paths with the same string prefix as
  the project root by checking the directory boundary, not only raw
  `StartsWith`.
- `make_source_bundle.ps1` and `make_render_backend_bundle.ps1` now use unique
  staging directories per run, so parallel source/submission bundle generation
  does not collide. Render staging is also removed after ZIP validation.
- `make_submission_bundle.ps1` now passes `-OutJson` and `-OutMarkdown` to
  `verify_submission_bundle.ps1`, so custom `-OutputDir` runs write verifier
  reports next to the ZIP they actually verified.
- Verification after this refactor:
  - path-safety self check: OK;
  - source bundle rejects an output path in a sibling directory: OK;
  - parallel source bundle + custom submission bundle run: OK;
  - targeted mobile/cloud/source-bundle tests: OK;
  - full backend unittest: `111` tests OK;
  - `scripts\finalize_cloud_deploy.ps1`: passed fresh-venv Render smoke;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160133529`, SHA256
    `239C55CFB4908CC1C92A763F6C418C1C8A3F7BA82EE7A94C718FD9721339E06D`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `236` entries,
    forbidden generated/local paths `0`, size `2879187`, SHA256
    `7782675759BF2C4220D153E08AEB42D3CA3C90A0C63E5BB4624D725DAD0E2A20`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348287`, SHA256
    `E10FEF081F1199926CAD5965CD536D87AE9ADEE3B2FB3A035BB4A80D16340D87`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `B31EF76FC2A19052F8D1435224611E2E8FAD3F17E04BF793F9F87E0E9856232D`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Release Gate Now Proves Fresh Render Dependencies And Phone Install Download

Completed after the path-safety refactor:

- `scripts\run_release_gate.ps1` now runs
  `scripts\smoke_render_backend_bundle.ps1 -FreshVenv` by default.
- A new `-SkipFreshRenderVenv` switch exists only for narrow local debugging.
- `scripts\run_release_gate.ps1` now starts or refreshes the phone install-page
  server via `scripts\prepare_phone_install_page.ps1 -StartServer` before
  running `scripts\check_phone_readiness.ps1`.
- `scripts\prepare_phone_install_page.ps1` no longer depends on fragile
  `Invoke-WebRequest` probing for the local install-page server. It uses a
  direct `.NET HttpWebRequest` status check.
- `scripts\check_phone_readiness.ps1` also uses a direct `.NET HttpWebRequest`
  helper for the phone install page and APK `HEAD` check. This fixed a Windows
  PowerShell `NullReferenceException` that could mark phone download readiness
  false even while `http.server` was serving the page.
- README/RUNBOOK and regression tests were updated to document and guard this.
- Verification after this change:
  - targeted release-gate/mobile-cloud tests: OK;
  - `scripts\prepare_phone_install_page.ps1 -StartServer`: OK;
  - `scripts\check_phone_readiness.ps1`: phone install/download true,
    temporary tunnel true, permanent cloud false, real Android device smoke
    false;
  - full `scripts\run_release_gate.ps1`: passed before the HTTP helper fix;
  - `scripts\run_release_gate.ps1 -SkipFlutter -SkipDesktopSmoke`: passed after
    the HTTP helper fix, including backend `111` tests OK, product acceptance
    `61/61`, LaTeX report rebuild, fresh-venv Render smoke, install-page server,
    and phone readiness;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160134654`, SHA256
    `6EE8F1EFC4AECB6E4F4AF4919B2BD5A197A92D0AB816276EF3B8AA332C2E72E3`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `236` entries,
    forbidden generated/local paths `0`, size `2879924`, SHA256
    `FBFB9FCB98D12A451E9D65B37B9226BABC2F83ECF0F5E4C7B7444C9C8542ECE8`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348324`, SHA256
    `B72EE7B64B5BB5816E807D897E8C56CDFB1EE75506E79679BF3D6D42654B7884`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63351`, SHA256
    `4844A3E6CB3A8FE7A27C7C844A3C19458F1C1FDC7A888ECC913F362CB2ACEC32`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Release Gate Report Included In Submission

Completed after the fresh Render/phone install release gate change:

- `scripts\run_release_gate.ps1` now writes
  `reports\release_gate_latest.json` and `reports\release_gate_latest.md`.
- The release gate report records every gate step with status, timestamps,
  duration, exit code, selected options, product acceptance summary, phone
  readiness summary, Render fresh-venv smoke summary, desktop package summary,
  and important artifact hashes.
- The report writer was made compatible with Windows PowerShell 5.1 by avoiding
  fragile inline `if` expressions inside `[ordered]` hashtables.
- The Render smoke summary now maps the actual smoke output correctly:
  `fresh_venv.requested` and `fresh_venv.install_ok` become
  `fresh_venv` and `fresh_venv_requirements_ok` in the release gate report.
- `scripts\make_submission_bundle.ps1` now includes the release gate report in
  the final ZIP under `quality\release_gate_latest.*`.
- `scripts\verify_submission_bundle.ps1` now requires that report and fails if
  the gate was run with `-SkipFlutter`, `-SkipDesktopSmoke`, or
  `-SkipFreshRenderVenv`, if any recorded step did not pass, or if the Render
  fresh-venv/install and phone download readiness summaries are not OK.
- README/RUNBOOK and regression tests were updated to document and guard this.
- Verification after this change:
  - PowerShell parse checks for changed scripts: OK;
  - targeted release-gate/submission/source-bundle tests: OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `13` steps, `skip_flutter=False`,
    `skip_desktop_smoke=False`, `skip_fresh_render_venv=False`,
    `fresh_venv=True`, `fresh_venv_requirements_ok=True`,
    `phone_install_download=True`, `phone_temporary_tunnel=True`,
    product acceptance `61/61`;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android device.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160140652`, SHA256
    `D090762D3D63E7AD89133E6607426FD55834FF4DB80946A0E52A108B5627F52A`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `236` entries,
    forbidden generated/local paths `0`, size `2882532`, SHA256
    `1C890CA23C0FF86B0E352E24370F435C90B22FC776059CF107235A1AD637FD6D`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348400`, SHA256
    `138571270D5D29449714DD0AD7850819E8260CBB36F4A2DA446CF614F99D1614`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63351`, SHA256
    `A79A333AE4630AC2DEE3BBC392DB3A12F1617268A6C7655058680EB128E1D675`;
  - release gate JSON: `reports\release_gate_latest.json`, size `17728`,
    SHA256
    `CD7657F3A63C362190943D5DC2A12535595941B3621E0A7FEBEA94ACB6AEE11A`;
  - release gate Markdown: `reports\release_gate_latest.md`, size `1219`,
    SHA256
    `1D9DC908B29FA4CA66503319DEE461CFD40FBDC29AD7B32C7A3934566D6C115C`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Submission Verifier Cross-Artifact Consistency

Completed after adding the release gate report to the submission bundle:

- Added `scripts\write_cloud_deployment_status.ps1`.
- `scripts\run_release_gate.ps1` now runs a `Cloud deployment status report`
  step after the fresh Render bundle smoke, so
  `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.*` is generated from the same
  current Render ZIP/smoke that the release gate just produced.
- `scripts\verify_submission_bundle.ps1` now cross-checks SHA256 and size
  metadata from:
  - `quality\release_gate_latest.json` against the real ZIP entries for the
    report PDF, Render backend ZIP, desktop ZIP, internet APK and LAN APK;
  - `cloud\CLOUD_DEPLOYMENT_STATUS.json` against the real Render backend ZIP
    and Render smoke Markdown entry.
- This caught a real stale-status issue: the previous cloud deployment status
  still referenced an older Render ZIP hash. The new release gate flow refreshes
  that status before the submission is packaged.
- `scripts\make_source_bundle.ps1` and the submission verifier now require
  `scripts\write_cloud_deployment_status.ps1` in the clean source ZIP.
- README/RUNBOOK and regression tests were updated to document and guard this.
- Verification after this change:
  - PowerShell parse checks for changed scripts: OK;
  - targeted source/mobile/release-gate tests: OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `14` steps, no debug skips, product
    acceptance `61/61`;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android device;
  - clean source ZIP: `237` entries, forbidden generated/local paths `0`, and
    includes `scripts\write_cloud_deployment_status.ps1`.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160143183`, SHA256
    `60AE3CE3E7F7AFFF85F68228D5273FC980DCD8437BC359AF891E29D1FC315D51`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `237` entries,
    forbidden generated/local paths `0`, size `2884975`, SHA256
    `5091C44C9426C4154090B32D5B1BB16DA4185185B231A293EAB887F88F644222`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348420`, SHA256
    `3015E21F274BF62318151A70B2A6D06105FCC7E5944132930F7B69365FC01367`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `6F9777D9C5C575DC1CCBDD4A4A1CB7897F67F069FEC71D36BD065441E44FE727`;
  - release gate JSON: `reports\release_gate_latest.json`, size `18154`,
    SHA256
    `BB5E5FD0C0BFF4D4AC8A9CA97A9EEF3019604C9F9392EA02B529993BA14228E8`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `2210`, SHA256
    `6E6874811DB6B40B776288FCA695C1A260D34FC83DD45A28AE7B9183AACB66B1`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Android Emulator Smoke And Final Bundle Refresh

Completed after the cross-artifact verifier work:

- Added `scripts\smoke_phone_emulator.ps1`.
- The emulator smoke starts the configured AVD headlessly, waits for
  `sys.boot_completed`, delegates the actual APK install/launch/foreground
  proof to `scripts\smoke_phone_on_device.ps1`, writes
  `PHONE_EMULATOR_SMOKE.md/json`, and shuts the emulator down unless
  `-KeepRunning` is passed.
- This is intentionally separate from real-device proof:
  `PHONE_EMULATOR_SMOKE.*` proves Android emulator launch, while final
  physical-phone evidence still comes from `PHONE_DEVICE_SMOKE.*`.
- Fixed the Android package/namespace mismatch that made emulator launch fail:
  - Android namespace is now `app.veritylens.mobile`;
  - Android application id is `app.veritylens.mobile`;
  - `MainActivity` package is now `app.veritylens.mobile`.
- `scripts\smoke_phone_on_device.ps1` now truncates long `dumpsys` output with
  `Limit-Text`, so smoke JSON stays reviewable.
- `scripts\check_phone_readiness.ps1` now reports both:
  - `Real Android device smoke`;
  - `Android emulator smoke`.
- `scripts\make_submission_bundle.ps1` includes optional
  `PHONE_EMULATOR_SMOKE.md/json`.
- `scripts\verify_submission_bundle.ps1` validates emulator smoke artifacts if
  they are present and fails on partial/bad emulator evidence.
- README, RUNBOOK, mobile Render docs, source-bundle checks, and regression
  tests were updated for the emulator workflow.
- Emulator proof that passed locally:
  - AVD: `FakeNewsDetector_API36`;
  - device id: `emulator-5554`;
  - APK: `outputs\phone_download\VerityLens-internet.apk`;
  - APK size: `49,843,593` bytes;
  - APK SHA256:
    `694E4EFDA69196012D566F306CF29F5F5443DB46D5B62CAE3102C119F4B8BF06`;
  - boot completed: `true`;
  - package installed: `true`;
  - launch started: `true`;
  - foreground package matched: `true`.
- Verification after this refresh:
  - PowerShell parse checks for changed phone/submission scripts: OK;
  - targeted mobile/source/release-gate tests: OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `14` steps, product acceptance `61/61`,
    Flutter analyze/test OK, desktop smoke OK, Render fresh-venv smoke OK,
    phone install/download true, temporary tunnel phone true, emulator smoke
    true;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android phone.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161675999`, SHA256
    `9E7916A4733077EA68DC5CB4E7F3058520A040F90F2C0B41653E7269F8BCB1B3`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `238` entries,
    forbidden generated/local paths `0`, size `2888879`, SHA256
    `9F85B7603A8913FF4E4BFD16DAC88912B6483BB63DBC7EC6532390E668F031D7`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348537`, SHA256
    `6A7C41D289AEA0486589CC61BFDBE4E41EA7391BC47F8199EF560D484ED9A579`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63351`, SHA256
    `C96FF4ADCE6DDFE76DA5E47BC01981CE2424AEFF01853C5E075F8AFE0FF7550D`;
  - release gate JSON: `reports\release_gate_latest.json`, size `9685`,
    SHA256
    `1C3CC5F4499348524EB0FCFD35F2262598293B6E3959C18A2A2D919F6D32AA2B`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `2210`, SHA256
    `3E164D23EF64264F6EE835BC643D1C75500F2A73326570018D43D42FFCD02001`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `16049`, SHA256
    `7403D7A4534A4C9DA104DF872A84EDDE7E58AD83DF6D92B3544DD796C52BC8BE`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Android Namespace Path Cleanup And APK Metadata Fix

Completed after the emulator smoke refresh:

- Removed the remaining old Android Kotlin package path:
  - moved `MainActivity.kt` from
    `apps\fake_news_detector_flutter\android\app\src\main\kotlin\com\fakenewsdetector\fake_news_detector_flutter\MainActivity.kt`
    to
    `apps\fake_news_detector_flutter\android\app\src\main\kotlin\app\veritylens\mobile\MainActivity.kt`;
  - removed the empty legacy `com\fakenewsdetector\...` directories;
  - regression tests now assert that the new path exists and the old
    `MainActivity.kt` path is absent.
- Fixed `apps\fake_news_detector_flutter\tool\build_internet_apk.ps1` so it
  writes APK-specific sidecar metadata:
  - `VerityLens-internet-api-url.txt` for the internet APK;
  - `VerityLens-lan-api-url.txt` for the LAN APK;
  - `VerityLens-cloud-api-url.txt` through the cloud wrapper script.
- Fixed `scripts\verify_phone_apk.ps1` so default API discovery reads the
  sidecar that matches the APK being verified instead of always reading the
  internet sidecar.
- The build script now writes a fresh status report after direct APK builds, so
  `PHONE_BUILD_STATUS.md` is not left with stale size/SHA metadata.
- Rebuilt and verified current phone APKs:
  - temporary internet APK targets `https://slick-rules-deny.loca.lt`;
  - LAN APK targets `http://192.168.1.16:8001`;
  - both APK verifiers passed.
- Re-ran Android emulator smoke after the APK rebuild:
  - AVD: `FakeNewsDetector_API36`;
  - device id: `emulator-5554`;
  - APK SHA256:
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - boot completed: `true`;
  - package installed: `true`;
  - launch started: `true`;
  - foreground package matched: `true`.
- Verification after this refresh:
  - PowerShell parse checks for changed mobile scripts: OK;
  - targeted mobile/source tests: OK;
  - Flutter analyze: OK;
  - Flutter tests: OK, `7` tests passed;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `14` steps, product acceptance `61/61`,
    Render fresh-venv smoke OK, phone install/download true, temporary tunnel
    phone true, emulator smoke true;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android phone.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161676215`, SHA256
    `7F646A95447A4BB4C027528F624EE7D4E102BF1695C62E6C2A612B95E63F0E32`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `238` entries,
    forbidden generated/local paths `0`, size `2889349`, SHA256
    `8225A4CA0FCE0424AB2A01CC307CB2AA6F33D510E299852AEA855DEC5D6DD04E`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348537`, SHA256
    `6A7C41D289AEA0486589CC61BFDBE4E41EA7391BC47F8199EF560D484ED9A579`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `7F3F0CB0154EC18258AE0548FE9971FFF3BE438F6BC83CF73071DB01D1CF9263`;
  - release gate JSON: `reports\release_gate_latest.json`, size `9684`,
    SHA256
    `CC380280992290C1B853C1BA273AE57F30329FF69BD949A5A8F53982A02BFDEE`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `2210`, SHA256
    `65568AA51C138BFD84A4033A92ECAE7139CD508D5D65364F66D432436918B4B5`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `14345`, SHA256
    `829B165DD5580AADA65C967966C44B7E0A505F9D5CE9BCAC684C512616F6FACC`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: LAN APK Verification Is Now A Release Gate Artifact

Completed after the Android namespace cleanup:

- `scripts\run_release_gate.ps1` now has a required `LAN APK verification`
  step before `Phone readiness report`.
- That step runs `scripts\verify_phone_apk.ps1` against
  `outputs\phone_download\VerityLens-lan.apk` and writes:
  - `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.md`;
  - `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`.
- `scripts\check_phone_readiness.ps1` now treats same-Wi-Fi phone readiness as
  true only when:
  - `VerityLens-lan.apk` exists;
  - `VerityLens-lan-status.md` exists;
  - `PHONE_LAN_APK_VERIFICATION.json` is OK;
  - the LAN APK verifier found the embedded API URL.
- `scripts\make_submission_bundle.ps1` now includes
  `PHONE_LAN_APK_VERIFICATION.md/json`.
- `scripts\verify_submission_bundle.ps1` now requires those LAN verification
  artifacts, checks that the verifier is OK, checks the API probe, checks the
  embedded API URL evidence, and cross-checks the LAN verifier JSON against the
  release gate artifact hash/size.
- README, RUNBOOK, mobile Render docs, LaTeX report commands, and regression
  tests were updated.
- Current LAN APK verification:
  - APK: `outputs\phone_download\VerityLens-lan.apk`;
  - API: `http://192.168.1.16:8001`;
  - API probe OK: `true`;
  - status matches URL: `true`;
  - status matches mode: `true`;
  - embedded API URL found: `true`;
  - embedded API URL match count: `3`;
  - APK SHA256:
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`.
- Verification after this refresh:
  - PowerShell parse checks for changed scripts: OK;
  - targeted mobile/source/release-gate tests: OK;
  - Flutter analyze: OK;
  - Flutter tests: OK, `7` tests passed;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `15` steps, product acceptance `61/61`,
    Render fresh-venv smoke OK, LAN APK verification OK, phone same-Wi-Fi true,
    phone install/download true, temporary tunnel phone true, emulator smoke
    true;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android phone.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161678869`, SHA256
    `8A254728C70A6EABE76DE3E429EDFB8FF25B593F403FB11324EE531C249BD33F`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `238` entries,
    forbidden generated/local paths `0`, size `2889882`, SHA256
    `4B2A3BEDFF4C44EC8210ED892143A71C9B2044995381077FF7877F42A85A6E1C`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348594`, SHA256
    `D78A26534F3A9808AC3EBDB845A53E948D515EEF2F930EADB5D3F783775F1CA8`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63351`, SHA256
    `DC37EDA730779BC33A5D860DF22FDC1929E2E7781780F7B28AE446CC387E3672`;
  - release gate JSON: `reports\release_gate_latest.json`, size `10355`,
    SHA256
    `108E66D24658CF8EBE7835E1754FE92A97B17192154D43DF6218C90A69781618`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `2210`, SHA256
    `86E9F820640458185F28656276AEC2E69FF611B2B17E2B74205FCF3FA3D2AD44`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `154FC0AACCA2442C88F578C6DD0EC527BF6F7CB74CFC7818AC5D7FF354FC3140`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `14345`, SHA256
    `829B165DD5580AADA65C967966C44B7E0A505F9D5CE9BCAC684C512616F6FACC`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Emulator Smoke Cross-Artifact Consistency

Completed after adding LAN APK verification:

- `scripts\run_release_gate.ps1` now records
  `outputs\phone_download\PHONE_EMULATOR_SMOKE.json` as
  `artifacts.emulator_smoke`.
- `scripts\verify_submission_bundle.ps1` now cross-checks:
  - release gate `artifacts.emulator_smoke` against the ZIP entry
    `phone\PHONE_EMULATOR_SMOKE.json`;
  - the APK SHA256 recorded inside `PHONE_EMULATOR_SMOKE.json`
    (`device_smoke.apk.sha256`) against the actual ZIP entry
    `phone\VerityLens-internet.apk`.
- This prevents a stale emulator smoke report from being accepted after a new
  internet APK build.
- Regression tests now guard the new release-gate field and verifier failure
  message.
- Verification after this refresh:
  - PowerShell parse checks for changed scripts: OK;
  - targeted release-gate/mobile tests: OK;
  - `scripts\verify_submission_bundle.ps1`: OK with the new SHA cross-check;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `15` steps, product acceptance `61/61`,
    LAN APK verification OK, phone same-Wi-Fi true, temporary tunnel phone true,
    emulator smoke true;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android phone.
- Current emulator consistency evidence:
  - release gate emulator smoke artifact exists: `true`;
  - emulator smoke JSON SHA256:
    `829B165DD5580AADA65C967966C44B7E0A505F9D5CE9BCAC684C512616F6FACC`;
  - emulator-recorded APK SHA256:
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - current internet APK SHA256:
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - emulator smoke matches current internet APK: `true`.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161679208`, SHA256
    `560AF610F70FFF4D9A12C4426D5B83A1DFEA89D450EF124DCCB5F0FA667A0EB1`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `238` entries,
    forbidden generated/local paths `0`, size `2890095`, SHA256
    `BEBEEF6396A0E235A0F7A4A93A8703543ECD761B6B726DB8B2615BB704AD4640`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348594`, SHA256
    `D78A26534F3A9808AC3EBDB845A53E948D515EEF2F930EADB5D3F783775F1CA8`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `7E75BAB69646F9967297C0A8956ECBE9A72AC881ECA3624AF31099C641B1EEF2`;
  - release gate JSON: `reports\release_gate_latest.json`, size `10747`,
    SHA256
    `1F2F30158E40DD950464BCC2C91BCB7EDCD04013BA249089706FBE0BDF3702EE`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `2210`, SHA256
    `F5E96B81CF25F563BB48E9D2781CC2DA43B3DCD31C70A0E7150049EB3A0D6335`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `9C15AAB7AFBC49B171D01488CE4673327AE419B368A428E193C81002FDF1FCD3`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `14345`, SHA256
    `829B165DD5580AADA65C967966C44B7E0A505F9D5CE9BCAC684C512616F6FACC`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Internet APK Verification Is Release-Gated

Completed after emulator smoke cross-artifact consistency:

- `scripts\run_release_gate.ps1` now has a required
  `Internet APK verification` step before the phone install page server step.
  It verifies `outputs\phone_download\VerityLens-internet.apk` in release mode,
  requires HTTPS, probes `/health`, `/ready`, and `/factcheck`, scans the APK
  for the embedded API URL, and rewrites
  `outputs\phone_download\PHONE_APK_VERIFICATION.*`.
- `scripts\run_release_gate.ps1` also records
  `artifacts.internet_apk_verification` for
  `outputs\phone_download\PHONE_APK_VERIFICATION.json`.
- `scripts\check_phone_readiness.ps1` now includes
  `internet_apk_verification` in the JSON report and only marks
  `phone_temporary_tunnel=true` when the tunnel is verified, the install page
  download is verified, the APK verification is OK, the verification API URL
  matches the quick tunnel URL, and the embedded API URL is found.
- `scripts\verify_submission_bundle.ps1` now validates
  `phone\PHONE_APK_VERIFICATION.json`, checks OK/API/HTTPS/embedded URL, checks
  the release gate artifact hash for that JSON, and compares the verification
  APK SHA256 against the actual `phone\VerityLens-internet.apk` entry in the
  final ZIP.
- Docs updated in `README.md`, `RUNBOOK.md`, and
  `docs\mobile_flutter_render.md`; regression tests now guard the new release
  gate step, readiness section, and submission verifier failure messages.
- Verification after this refresh:
  - `scripts\verify_phone_apk.ps1` for `VerityLens-internet.apk`: OK;
  - targeted release-gate/mobile tests: OK;
  - PowerShell parser check for changed scripts: OK;
  - `scripts\check_phone_readiness.ps1`: OK with temporary tunnel, install
    download, and same-Wi-Fi readiness true;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `16` steps, product acceptance `61/61`,
    internet APK verification OK, LAN APK verification OK, phone same-Wi-Fi
    true, temporary tunnel phone true, emulator smoke true;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android phone.
- Current internet APK verification evidence:
  - API URL: `https://slick-rules-deny.loca.lt`;
  - verification OK: `true`;
  - verification API URL matches quick tunnel URL: `true`;
  - embedded API URL found: `true`;
  - embedded API URL match count: `3`;
  - verification APK SHA256:
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - current internet APK SHA256:
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160157854`, SHA256
    `C21B3AD69413936378ADA8F9FBCE124228C3946999527C876C1B8A682DDC23EF`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `238` entries,
    forbidden generated/local paths `0`, size `2890673`, SHA256
    `0E0EC12D5981FE6843F76E0AF8AEA04BB6D8C2B65987E2050902B06202CFED5F`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348618`, SHA256
    `A6B192946841FFEDB70D9D5ED5EBC0D127AD6249953DA567202D02970526AB2D`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `6A74C6A5E908B1D58D5C64CC5B452367C96F9F738D8F61CEDDA42077DC6CD698`;
  - release gate JSON: `reports\release_gate_latest.json`, size `21141`,
    SHA256
    `AC6F3D6A8D76809C415694E77E94A78A2B4C246DAC6DD532C4B4EA31A7786F36`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `2210`, SHA256
    `27BDF4381C09E22BFF5AFB716771B34B55655AF37451CFE41CC17554EDB60279`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `D0A433166C7E7067F700CE68A68D62D65FB0DB47B026B11C86AD8C8B97CED646`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `AAE1617225F56A1489485030B94C329EC83493BB6BCE919829841D1698FD9AA0`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `14345`, SHA256
    `829B165DD5580AADA65C967966C44B7E0A505F9D5CE9BCAC684C512616F6FACC`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Source Bundle Generated-File Cleanup

Completed after internet APK verification was release-gated:

- `scripts\make_source_bundle.ps1` now prunes additional generated/local files
  from `source\verity-lens-source.zip`:
  - Flutter `GeneratedPluginRegistrant.*`;
  - `.iml` IDE metadata;
  - `.log` build logs, including `docs\report\verity_lens_report.log`;
  - existing local/ephemeral Flutter files remain excluded.
- `scripts\verify_submission_bundle.ps1` now fails if the nested source ZIP
  contains any `GeneratedPluginRegistrant.*`, `.iml`, `.log`, local properties,
  build outputs, caches, archives, or Python bytecode.
- `tests\test_factcheck_core.py` now guards this source-bundle cleanliness.
- `README.md` and `RUNBOOK.md` document the stricter clean-source rule.
- Verification after this refresh:
  - PowerShell parser check for changed scripts: OK;
  - targeted source-bundle test: OK;
  - clean source ZIP probe for local/generated Flutter files and LaTeX logs:
    OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `16` steps, product acceptance `61/61`,
    temporary tunnel phone true, same-Wi-Fi phone true, emulator smoke true;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android phone;
  - safe non-output/non-venv `__pycache__` directories removed after tests.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160156074`, SHA256
    `D832474CABD84C9714AAC605B679077EA34A44434894A82C06348F220AF21B9D`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `235` entries,
    forbidden generated/local paths `0`, size `2888518`, SHA256
    `986E5D9B3150236F2DD90FE03234866249CB2433C8944241404D6462212891CC`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348618`, SHA256
    `A6B192946841FFEDB70D9D5ED5EBC0D127AD6249953DA567202D02970526AB2D`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `AEBF7D2B5146F49D9212E501B5B6139614DBE73E234C27A029A8BF444085E224`;
  - release gate JSON: `reports\release_gate_latest.json`, size `21139`,
    SHA256
    `AD3D3989FDCD8DD1E7E1F38D023FE428AF5F8F8804FC5B2147E7D76699B7FF76`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `18147C7A0FA40BCB5337AFEAAE8439616EC2E267EB98429A1203A410BA0C7326`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `3E61FA56B787812C13265D990D99EF4C80EDB80415AABDE2190B66EF91C112E4`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `1AEA69D20D068951D30E27C42830B5C24706A0B31C5F7F5DEB2A40E0158CFC7D`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Physical Device Smoke APK Consistency

Completed after source bundle generated-file cleanup:

- `scripts\run_release_gate.ps1` now records
  `outputs\phone_download\PHONE_DEVICE_SMOKE.json` as
  `artifacts.device_smoke` when writing `reports\release_gate_latest.json`.
- `scripts\verify_submission_bundle.ps1` now cross-checks:
  - release gate `artifacts.device_smoke` against the ZIP entry
    `phone\PHONE_DEVICE_SMOKE.json` when the artifact exists;
  - if `PHONE_DEVICE_SMOKE.json` reports `ok=true`, the recorded
    `apk.sha256` must match one of the packaged phone APKs in the submission
    ZIP: `VerityLens-cloud.apk`, `VerityLens-internet.apk`, or
    `VerityLens-lan.apk`.
- This means a future real Android phone proof cannot accidentally point to an
  APK that is not inside the final submission archive.
- Current `PHONE_DEVICE_SMOKE.json` is still skipped because no authorized
  physical Android phone is connected; the new SHA rule is enforced for
  `ok=true` smoke reports.
- Regression tests now guard the new release-gate artifact field and verifier
  failure message.
- Verification after this refresh:
  - PowerShell parser check for changed scripts: OK;
  - targeted release-gate/mobile tests: OK;
  - `scripts\verify_submission_bundle.ps1` before full gate: OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `16` steps, product acceptance `61/61`,
    device smoke artifact exists, temporary tunnel phone true, same-Wi-Fi phone
    true, emulator smoke true;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android phone;
  - nested source ZIP cleanliness check: OK;
  - safe non-output/non-venv `__pycache__` directories removed after tests.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160156453`, SHA256
    `5F3BF159E16468EAD091FB06FA44860F7F20A303D0CEAF9DEB29B30F764075D1`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `235` entries,
    forbidden generated/local paths `0`, size `2888760`, SHA256
    `A1CF468B7E3956A759808ED36DEC29A6CFB578A1BC9186144989F1108B38C4CB`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348645`, SHA256
    `864602F93F5ACEE9DC2DF950EF951D2F7D2E47C78E85A8C7A6DBC89C3F69A10A`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `BA3A94BB436894870E06815B93373BFDBFB2EE1909AC6C0E8B14ACFDE548D070`;
  - release gate JSON: `reports\release_gate_latest.json`, size `21771`,
    SHA256
    `9D5C13333466826579035D31DA3C8F20E556A1BE3984D9681A61CDFD5B1D0CB4`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `B9487236287BF4F3B76E9A431B56BC9B39F19D4696D9A18BEDF2710538294A82`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `D9F963C01F15CCC507C6D7A2CFE99A7CD4B7FFAC62ED11C65120EAC94561AD56`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `451DA685895A2ED14D3AB53D4A4EBE191A7C6A43FDF163BBB1B9119FA9C1081C`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `E0B8C4A1C95B6D2EDF78605438DE180DBA3F6566DB3FC031A532FFE9B637075C`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Device Smoke Availability Refresh

Completed after physical device smoke APK consistency:

- Found a real stale-evidence issue:
  - `outputs\phone_download\PHONE_DEVICE_SMOKE.json` was skipped, but it still
    recorded an older internet APK SHA256
    `5B238B73268402CBD42970E7B6FD3719FA93B89B3DFF8EE3C13BBBA768FA2AC3`;
  - the current `VerityLens-internet.apk` SHA256 is
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`.
- `scripts\run_release_gate.ps1` now refreshes a missing/non-passing/skipped
  `PHONE_DEVICE_SMOKE.*` by default with a non-strict
  `Phone device smoke availability` step. If a real `ok=true` device proof
  already exists, a normal release gate does not overwrite it; rerun with
  `-PhoneDeviceSmoke` or `-RequirePhoneDevice` when you want to replace it.
- `README.md`, `RUNBOOK.md`, and regression tests now document/guard this
  behavior.
- The refreshed skipped report now records the current internet APK:
  - generated at `2026-05-29T19:53:03.7650050+02:00`;
  - skipped: `true`;
  - skip reason: `no_authorized_android_device`;
  - APK size: `49843593`;
  - APK SHA256:
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - matches current internet APK SHA256: `true`.
- Verification after this refresh:
  - PowerShell parser check for changed scripts: OK;
  - targeted release-gate test: OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `17` steps, product acceptance `61/61`,
    `Phone device smoke availability` passed, device smoke artifact exists,
    temporary tunnel phone true, same-Wi-Fi phone true, emulator smoke true;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android phone;
  - nested source ZIP cleanliness check: OK;
  - safe non-output/non-venv `__pycache__` directories removed after tests.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160156879`, SHA256
    `EA4E955733AD9BB58BA2040B6058C1A61FC0391FB64576968DFC958262FDECC8`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `235` entries,
    forbidden generated/local paths `0`, size `2888943`, SHA256
    `313CFF455C0E82CDE7FCF6D838DC8DFF5B1CF833751655E81C7720A8FCBA7378`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348696`, SHA256
    `434AD1F34501E3C8C413D33C16F5D23104732727771EA41292D8C5F8453BE11E`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63351`, SHA256
    `CB7D627683F317233444272D8571DE575C3B8E79586EB9790391952410420FB3`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22200`,
    SHA256
    `0C4A72034D59491281ED23C30C09B1D462436428F9FD91037E93CADEE798509B`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `F4515942650F0134DCD987F01A8EA4059118108E96CC22A0C562071D43F561D1`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `54417BC74CA7F29B3321EE8A7575F4EFE346F9C37C846C1317DA798A5715309D`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `371734257E28A74888823B090678923AECBFB5EEA57BEBBADA3A20B6919904F2`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `B2717448472493AE1869DBBA2D4F074C3EDDA995EECEA61073A6D96EDB964F7D`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Phone Readiness Device-Smoke Consistency

Completed after device smoke availability refresh:

- Found a second stale-evidence issue:
  - `outputs\phone_download\PHONE_DEVICE_SMOKE.json` was refreshed, but
    `outputs\phone_download\phone_readiness.json` had already been written
    earlier in the release gate;
  - therefore `phone_readiness.json.phone_device_smoke` still contained the
    older skipped report and older APK SHA.
- `scripts\run_release_gate.ps1` now runs a final
  `Phone readiness report refresh` step after device-smoke availability or
  explicit device smoke. This keeps the final readiness JSON aligned with the
  final device-smoke evidence.
- `scripts\verify_submission_bundle.ps1` now fails if
  `phone\phone_readiness.json.phone_device_smoke` disagrees with
  `phone\PHONE_DEVICE_SMOKE.json` by `generated_at` or APK SHA256.
- `README.md`, `RUNBOOK.md`, and regression tests now document/guard this
  behavior.
- Current consistency evidence:
  - `phone_readiness.json.phone_device_smoke.generated_at` matches
    `PHONE_DEVICE_SMOKE.json.generated_at`: `true`;
  - `phone_readiness.json.phone_device_smoke.apk.sha256` matches
    `PHONE_DEVICE_SMOKE.json.apk.sha256`: `true`;
  - shared recorded APK SHA256:
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - device smoke is still skipped with
    `skip_reason=no_authorized_android_device`.
- Verification after this refresh:
  - PowerShell parser check for changed scripts: OK;
  - targeted release-gate/mobile tests: OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `18` steps, product acceptance `61/61`,
    `Phone device smoke availability` passed,
    `Phone readiness report refresh` passed, temporary tunnel phone true,
    same-Wi-Fi phone true, emulator smoke true;
  - `scripts\make_submission_bundle.ps1`: passed;
  - `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android phone;
  - nested source ZIP cleanliness check: OK;
  - safe non-output/non-venv `__pycache__` directories removed after tests.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160157214`, SHA256
    `0046B05DF88A3D0A03FA43E49BF419C8ACDF8BDCC42F848F25A0C2FB044E5772`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `235` entries,
    forbidden generated/local paths `0`, size `2889216`, SHA256
    `CCA71FBE793723E5C1A78F1D9A6A38E0F8CCDFD5E51136B6875749B1990D2778`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348724`, SHA256
    `92FAAF28568F88294D9943F198B77CF8D6BAA09E6A7B8DC0DAF0AEBEA5099B64`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63348`, SHA256
    `0C68BED9E0E263C762790DDCC4BA9FDB41B13CA8C612D8E8657E57FCE02C192B`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22622`,
    SHA256
    `DBE02671BA45DF6CE9B2D3830CA3A5D8EF88756E3EF4AE1395051CE2E5576C6C`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `E88A4A109DC7F1E63C527C3D8C154ABC36BECDF5DF3D5C5828C0AD8BDC82DD8B`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `32776`, SHA256
    `FAC3820A5964156A0F28442D47AC001A486B539E99B96D01FA0CD242DB49559A`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `4189741607DD4E15494704652D280A684072921ECB8D5CB81497BCB45AC0BACA`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `D0FEF8F4706134A9AE666EE52487675779B848F95B5DDCA4F013E77B3C786F0B`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `BD0C83FAB8D7D28673B654921EB8C1F976856FB0755FAF15B228FB1A9D02A698`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Release Gate Required-Step Enforcement

Completed after phone readiness/device-smoke consistency:

- `scripts\verify_submission_bundle.ps1` now requires the release gate report
  to contain the critical step labels, not merely "whatever steps were recorded
  all passed".
- Required base steps now include:
  - Python/version and syntax checks;
  - backend unit/integration tests;
  - product acceptance gate;
  - university report PDF;
  - Render backend bundle and fresh-venv smoke;
  - cloud deployment status report;
  - internet APK verification;
  - phone install page server;
  - LAN APK verification;
  - phone readiness report;
  - desktop smoke and desktop package verification;
  - Flutter analyze and tests;
  - final phone readiness refresh.
- The verifier also now requires either:
  - `Phone device smoke availability`; or
  - `Phone device smoke` when the gate was run with explicit real-device
    smoke settings.
- Conditional permanent-cloud steps are enforced when the release gate options
  include an API URL:
  - `Cloud API verification` is always required for cloud URL runs;
  - API-only runs require cloud API readiness/deployment status steps;
  - cloud APK runs require cloud APK build/verification, cloud phone readiness,
    and permanent-cloud deployment status steps.
- `phone\PHONE_DEVICE_SMOKE.json` is now always cross-checked against
  `ReleaseGate.artifacts.device_smoke`, because the normal release gate creates
  a current skipped report even without a physical Android phone.
- Regression tests now guard the new required-step failure messages.
- Verification after this refresh:
  - PowerShell parser check for changed verifier: OK;
  - targeted release-gate/mobile tests: OK;
  - `scripts\verify_submission_bundle.ps1` before full gate: OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - release gate report: `ok=True`, `18` steps, product acceptance `61/61`;
  - required step presence confirmed for:
    `Internet APK verification`, `LAN APK verification`,
    `Phone device smoke availability`, and `Phone readiness report refresh`;
  - `scripts\make_submission_bundle.ps1`: passed;
  - strict `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness is still false until
    a real Render HTTPS URL/cloud APK exists, and real phone-device smoke is
    still skipped without an authorized Android phone;
  - nested source ZIP cleanliness check: OK;
  - safe non-output/non-venv `__pycache__` directories removed after tests.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160157627`, SHA256
    `E1B24F7DC03C28B52BCF7B66B89A56232C6C4AD0922C9E83A024E1188AE11F44`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `235` entries,
    forbidden generated/local paths `0`, size `2889589`, SHA256
    `4EE19AF0EAED7084FE33F7923F077F3222383D878F7307F45535906B5897281B`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348724`, SHA256
    `92FAAF28568F88294D9943F198B77CF8D6BAA09E6A7B8DC0DAF0AEBEA5099B64`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `63351`, SHA256
    `8B3B224D402C5E558130C8DBE76999E1A035343844C70E0F7A58840F165C24DB`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22627`,
    SHA256
    `AE9E0357A3A20CCA31AE07DEB946F1DE1AFA25B8AA3534000BF484C0D4827736`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `E0FB5C3D217A2AEB027055287FB7A5045A7F7139FC5938F110759E060074CA5D`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `32776`, SHA256
    `14904AF18AE556144A85DA63819FBCF9C0C19E8961E570F62A8CF4AD8625495A`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `876EAB99A977F82CA40E56A780428B0B234E8321E5F74D45850D35FD8379FBD1`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `0E264E84BFF60AE56D25E3568C6501C53DBE7D5FB3B99200CA32286276C5C508`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `97206139186FB6E0AC4B0944D2AAD3E7C8975F127A33316F65C8172DD382B597`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: LaTeX Report Reflects Current Proof Chain

Completed after release-gate required-step enforcement:

- Updated `docs\report\verity_lens_report.tex` so the university report now
  describes the current mobile/release evidence rather than the older shorter
  gate summary:
  - release gate result is described as `18` steps without debug skips;
  - phone section names internet APK verification, LAN APK verification,
    emulator smoke, physical-device smoke, and the distinction between
    temporary tunnel, LAN, emulator, permanent Render, and final USB-device
    proof;
  - release-gate section now lists internet APK verification, LAN APK
    verification, device-smoke availability, final phone-readiness refresh,
    submission-bundle consistency checks, and clean source ZIP verification;
  - limitations/conclusions explicitly say permanent Render HTTPS/cloud APK
    and real Android `-RequireDevice` smoke are still the external final steps.
- Updated `RUNBOOK.md` release-gate wording to match the stricter gate and
  submission verifier.
- Strengthened
  `tests.test_factcheck_core.FactCheckCoreTests.test_university_latex_report_has_required_structure_and_results`
  so report coverage of the current phone proof chain is guarded.
- Verification after this refresh:
  - targeted report unittest: OK;
  - `scripts\build_report.ps1 -BootstrapTectonic`: OK, PDF rebuilt;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - backend tests inside the gate: `111/111` OK;
  - product acceptance: `61/61`, pass rate `1.0`;
  - release gate report: `ok=True`, `18` steps, `0` failed steps;
  - `scripts\make_submission_bundle.ps1`: passed;
  - strict `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness still awaits real
    Render HTTPS/cloud APK, and physical phone smoke is skipped until an
    authorized Android device is connected and run with `-RequireDevice`;
  - nested source ZIP: `235` entries, forbidden generated/local paths `0`;
  - `git status --short` still fails because this directory is not a Git
    repository.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160164202`, SHA256
    `3EBF3D6D79CBD4A2C24C16DD72C78E85CA1DF6C8FFDE18B5892ACC04A59285AF`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `235` entries,
    forbidden generated/local paths `0`, size `2892899`, SHA256
    `EEEF79468F5427E986E90BC640863DD7686CB39053B3F139978C4658074C59EF`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348724`, SHA256
    `92FAAF28568F88294D9943F198B77CF8D6BAA09E6A7B8DC0DAF0AEBEA5099B64`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `65898`, SHA256
    `604B089150F0607E940F63D028249D4C522E75DE93F6D5455AD48D6A04089353`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22624`,
    SHA256
    `7D93F8C01E50D52DE1387DAFFA6A67A973BCA6565C00CF8334DD7285009A6952`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `674221ED1A63FC82019FD5E36662B98B3494C0F27E365E13142B618C520EA3E4`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `32776`, SHA256
    `FD5EF99BDAE03DB7167167A35A6C78067F978D7E33D8C21F6AC9C9E68790E547`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `435F39C4F7A03580762789E140260B48C2F966B0EA58F505CA345EDD8807DAFA`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `951CF818997CC93D24F5B7D3BA7CAB8B0A3F9E85D434800A078BA578902A64AB`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `5CF40C025BC25326188E5E70C9DE0F0A1B2C91A6D904A0C4F066FE098ECF4E39`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Product Acceptance Expanded to 82 Cases

Completed after the LaTeX proof-chain update:

- Expanded `scripts\run_product_acceptance.py` from `61` to `82` deterministic
  cases, keeping the same `95%` per-section gate and minimum five cases per
  section.
- New coverage added:
  - Facts: additional arithmetic/comparison cases and common-knowledge cases
    for bananas, cucumbers, grass, snow, Moon, sky, etc.;
  - News: an extra corroborated Reuters/NOAA climate-data case;
  - Screenshots: OCR cases for sky, Moon, and banana facts;
  - Images: Firefly and Ideogram metadata markers;
  - API/mobile contract: rejection checks for empty fact-check requests and
    invalid image analysis modes.
- Updated `docs\report\verity_lens_report.tex` so the report now states:
  - Product gate: `82/82 OK`;
  - Facts `44/44`;
  - News `12/12`;
  - Screenshots `9/9`;
  - Images `8/8`;
  - API/mobile contract `9/9`.
- Strengthened
  `tests.test_factcheck_core.FactCheckCoreTests.test_product_acceptance_gate_covers_mobile_api_contract`
  and refreshed the LaTeX report assertions for the new totals.
- Verification after this refresh:
  - standalone `scripts\run_product_acceptance.py`: `82/82`, pass rate `1.0`;
  - targeted acceptance/report tests: OK;
  - `scripts\build_report.ps1 -BootstrapTectonic`: OK, PDF rebuilt;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - backend tests inside the gate: `111/111` OK;
  - release gate report: `ok=True`, `18` steps, `0` failed steps;
  - `scripts\make_submission_bundle.ps1`: passed;
  - strict `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness still awaits real
    Render HTTPS/cloud APK, and physical phone smoke is skipped until an
    authorized Android device is connected and run with `-RequireDevice`;
  - nested source ZIP: `235` entries, forbidden generated/local paths `0`;
  - search for stale `61/61` and old report table counts in docs/tests/scripts:
    no matches.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160165554`, SHA256
    `8A9BF37B72E6FE3572A9F1D678A968B3F497EB963F9FC69D7987952A84F73190`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `235` entries,
    forbidden generated/local paths `0`, size `2893510`, SHA256
    `2C2AB44DE970A3CDEEFD78D71A6FEBC416B391641E310B7C34D1F619B79528A2`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348724`, SHA256
    `92FAAF28568F88294D9943F198B77CF8D6BAA09E6A7B8DC0DAF0AEBEA5099B64`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `65890`, SHA256
    `5DBA0FC914F31EE1265FA9F31487934831166E1DFEC0286B04A05312F8EA56F2`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22627`,
    SHA256
    `59CA6381BE0C5FB1C3D4CF6C34382F55FB6B20C746982C51E90AECADC5AAD378`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `A7462C44CA3D723531B77727AFF47B014756992C30C4C8853123CD428508451E`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `DEF8B729F6D1ECA32437B9590F8C983665ED5BA799E865A3F0335F24DD631F5B`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `32776`, SHA256
    `99D1E0A8DE2AC80B4FAF2C4637A04FC8CF8538CAE38F215D018D6B7F8D657BF7`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `D30ACDC07DA1617E07E07BC10DBD8F292BD1820EFB0CB7A3147446A56E931B0C`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `F1883DD6625286D2EDA1545027A42C98A404A3D5C254854CCCF9180868E6B95A`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `4DE1FA81D77803F0BE25AF906A848BF89D6514AC85371F18FC0280F1A0A5C7E6`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Source Bundle Excludes Generated Report PDF

Completed after product acceptance expansion:

- Tightened the clean source package so
  `source\verity-lens-source.zip` contains LaTeX source
  `docs/report/verity_lens_report.tex` but no generated
  `docs/report/verity_lens_report.pdf`.
- The university PDF is still included and verified separately in the
  submission ZIP as `report/verity_lens_report.pdf`.
- Changed files:
  - `scripts\make_source_bundle.ps1` prunes
    `docs\report\verity_lens_report.pdf` from the staged source package and
    forbids it during source ZIP validation;
  - `scripts\verify_submission_bundle.ps1` now treats
    `docs/report/verity_lens_report.pdf` inside the nested source ZIP as a
    generated/local artifact;
  - `tests\test_factcheck_core.py` guards the same invariant;
  - `README.md` and `RUNBOOK.md` now describe exclusion of generated LaTeX
    outputs/logs, not only logs.
- Verification after this refresh:
  - targeted source-bundle tests: OK;
  - source ZIP direct check: `234` entries, `has_tex=True`,
    `has_pdf=False`, forbidden count `0`;
  - PowerShell parser check for `scripts\verify_submission_bundle.ps1`: OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - backend tests inside the gate: `111/111` OK;
  - product acceptance: `82/82`, pass rate `1.0`;
  - release gate report: `ok=True`, `18` steps, `0` failed steps;
  - `scripts\make_submission_bundle.ps1`: passed;
  - strict `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness still awaits real
    Render HTTPS/cloud APK, and physical phone smoke is skipped until an
    authorized Android device is connected and run with `-RequireDevice`.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160100785`, SHA256
    `F00D18734E29D8045D81235F56FA59D0F38875E5090D79B302DA0C42EF9C0C0F`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `234` entries,
    forbidden generated/local paths `0`, size `2828684`, SHA256
    `D3FA964E5D72647F0D6B7A96C9186376A67EAFB0B447C5B58F8517D06329DAD3`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348728`, SHA256
    `220978A9C0939CEFB21684AC03A3DE55CFB12467BE1F689C2293456B9754CFF2`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `65890`, SHA256
    `2F2E965EDDD4E3FFCAA5A8A22DCC0C020DF999BEB6840E853A3B83FBE21A3F40`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22628`,
    SHA256
    `D0D1AF4B229013AB9F8F9022AE19D11322CC425C7CE7FA986FBB3DC18B2FD9BF`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `EFC20F5EF49F7A7C131CA3EFF9AA3E60E5A81513D58E5D91ECCD829702077625`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `7B39C4691DD44E46DBC2F062976B83C8E8DD471E6EF605030A4D7718C4CBBFA3`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `32776`, SHA256
    `C7FD8A19A188243D8BC0489AB02D89A6B3BC4E7F9FAE7B3438B05A7B0D600560`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `B2C1ED39945C949D3F021A1B0F8ACBB6E67CCE33C4A6EE368B02EC4D302DCAF6`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `4DC6238A9D7FB8561B69CA0F9E158D24053093E75B98371325539EF68C7E4E27`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `8E6E676D7599A4E4F260B9CA86A9B7D03781606E636B11511C59E11886F0CFFD`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Flutter API URL Validation

Completed after source bundle PDF cleanup:

- Improved the Flutter mobile client API settings flow so users cannot save an
  incomplete or unsupported backend URL such as `demo.onrender.com` or
  `ftp://demo.onrender.com`.
- `apps\fake_news_detector_flutter\lib\main.dart` now has
  `validateApiBaseUrl`:
  - accepts `https://...` public Render/cloud URLs;
  - accepts `http://192.168.x.x:8001` and other `http://` local/LAN URLs for
    same-Wi-Fi demos;
  - rejects URLs without a host and URLs whose scheme is not `http`/`https`;
  - shows a SnackBar before saving invalid settings.
- `apps\fake_news_detector_flutter\test\widget_test.dart` now covers:
  - valid API URL normalization/saving;
  - invalid incomplete API URL rejection;
  - LAN HTTP URL acceptance;
  - unsupported scheme rejection.
- `tests\test_factcheck_core.py` now guards the Flutter validation and widget
  test strings as part of the broader mobile/render structure test.
- Verification after this refresh:
  - `flutter test`: `8/8` OK;
  - `flutter analyze`: no issues;
  - targeted Python mobile structure test: OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - backend tests inside the gate: `111/111` OK;
  - product acceptance: `82/82`, pass rate `1.0`;
  - release gate report: `ok=True`, `18` steps, `0` failed steps;
  - `scripts\make_submission_bundle.ps1`: passed;
  - strict `scripts\verify_submission_bundle.ps1`: `OK=True`, `0` failures,
    `2` expected warnings: permanent cloud phone readiness still awaits real
    Render HTTPS/cloud APK, and physical phone smoke is skipped until an
    authorized Android device is connected and run with `-RequireDevice`;
  - nested source ZIP: `234` entries, `has_mobile_main=True`,
    `has_mobile_test=True`, `has_pdf=False`, forbidden generated/local paths
    `0`.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160101119`, SHA256
    `41E188F35AD008AE5EEED56A645DC04204F2A9414C69D20F5CDBF4A750B2F3FA`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `234` entries,
    forbidden generated/local paths `0`, size `2828988`, SHA256
    `B49DD5A6AF8ABE06AA805E37174FEC6F55A124C3528C340CCC94AB61A319C08F`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348728`, SHA256
    `220978A9C0939CEFB21684AC03A3DE55CFB12467BE1F689C2293456B9754CFF2`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `65890`, SHA256
    `3A19CA67DB36D1CDE3B89F19C9AE32BF47717BD044D1D8649F7C0B4709B3B834`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22623`,
    SHA256
    `60AAF8A22AD03041B2C5CFE91D39B7D3303CA5783CEA6E2F6E9921E2FD0126B1`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `55C8945476DF79F190E4EC7DEAE9AADB72D792AE23D6729BB6BB56CABBDDBD38`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `E01DA01ED95177326F9FF2DA457D7B296F976BA32A6F91436082E7D3838732FD`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `32776`, SHA256
    `87463117080A3562ED9A2A053E06679C6BD64660D2EB3772E43EC1A1A1FC977D`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `A7F1B818BE812374910B2F9D67337AB29A6B20AED404396F144D3CB97EAD9AE5`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `BAD645CD6062B8B31E7A0D7194703EABBEBDB08106705209E0AD2F2D54D46CB3`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `2AF4C61BAA3ECB9E77C3F344ADA4C5FB5D072CD418A8571499EDCC146E35CE59`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `6120AA7B7CF8BC08EA10780608673A083AAA4FD3F3F920360AA7ADC001B26C55`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `713D960A74BDA03B051D60745CB1B50D9CC9613C648DC68898F1AF910A469E36`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Report Drift Fix And Fresh APK Rebuild

Completed after Flutter API URL validation:

- Fixed report/test drift:
  - `docs\report\verity_lens_report.tex` now says `Flutter tests` are `8/8`
    OK, matching the current Flutter suite.
  - The report now says the clean source ZIP has `234` entries, matching the
    current source bundle.
  - `tests\test_factcheck_core.py` now guards those fresh report strings.
- Rebuilt mobile APKs from the current Flutter source, so the shipped APKs now
  include the API URL validation code in `apps\fake_news_detector_flutter\lib\main.dart`:
  - `VerityLens-internet.apk` against `https://slick-rules-deny.loca.lt`;
  - `VerityLens-lan.apk` against `http://192.168.1.16:8001`.
- Reverified both APK/API pairs:
  - internet APK verification: API `/health`, `/ready`, fact-check probe, mode,
    status file, and embedded API URL all OK;
  - LAN APK verification: API `/health`, `/ready`, fact-check probe, mode,
    status file, and embedded API URL all OK.
- Refreshed phone evidence after APK SHA changed:
  - emulator smoke passed on `FakeNewsDetector_API36`;
  - physical device smoke was refreshed and remains a current skipped report
    because no authorized Android phone is connected.
- Verification after this rebuild:
  - targeted report test: OK;
  - university report PDF rebuild: OK;
  - full `scripts\run_release_gate.ps1`: passed without debug skips;
  - backend tests inside the gate: `111/111` OK;
  - product acceptance: `82/82`, pass rate `1.0`;
  - `flutter analyze`: no issues;
  - `flutter test`: `8/8` OK;
  - `scripts\make_submission_bundle.ps1`: passed;
  - strict submission verifier: `OK=True`, `0` failures, `2` expected warnings
    for missing permanent Render/cloud APK and skipped physical phone proof.
- Current final artifacts after this refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160099712`, SHA256
    `6141A4E3EDAFBFD391833E1BEA1DBFD899300089C9A9C3A8EA302CA8DEA1E4EF`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `234` entries,
    forbidden generated/local paths `0`, `has_tex=True`, `has_pdf=False`, size
    `2829006`, SHA256
    `631B6284F49B4DD5259BAD35F5AB37DDD01664CAA3FBA87F324EDB2934448CFD`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348728`, SHA256
    `220978A9C0939CEFB21684AC03A3DE55CFB12467BE1F689C2293456B9754CFF2`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `65891`, SHA256
    `1248CFE622C54CB94D4BD9485EB995CB46E59DD7BB0AAC5B308821AAAB293D2B`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22627`,
    SHA256
    `26A094928B3FE39551035F05C6CA2AFD14CEB2E264699B17A93E06880ABDB62B`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `A4F6AAB97BCDE865A8468D4517C1ACEF0662083FA011FB0E47C35866FC597B47`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `C9C1CFB79F78C28211A3C2499A9D1F5D7945138531B086290993BAE65FCD31DA`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `32776`, SHA256
    `C823C868D4B65D48032C71BE09858741F2EB160F50EBA3832B8D189C72869F55`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `16049`, SHA256
    `97B811175F80981F50C7BE715F537D6B78B9E4155A8F46094362ED5CE058EA84`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `23AD5B916ABC2425C9D71FF69F16036FF046C275EF09B51D38BE57379D3624E2`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `27CF0A49AE8595EEE382CC85D47A938A1B5D7EE48E8F16C59E7FDE0471BAF905`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `A014A7AABE248FB15D382625B30E9FEAD54A767A75306431052FEEDA101BF496`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `4FF9AF7B12895D6FD6DA56BE4BEEBB67897FF8B4D0FCA1EC23F0F83715FE313B`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `9E529169DA289D29AD04C7ED1D99398BE4452D227C702949C4B1D2D1B2C8E7C7`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Final Dependency Split And Submission Refresh

Completed after the report/APK refresh:

- Split runtime dependencies so the default product install is lightweight:
  - `requirements.txt` and `requirements.lock.txt` are now product/runtime only
    for API, UI, desktop, OCR and packaging.
  - `requirements.optional-ai.txt` contains optional Torch/Transformers model
    dependencies.
  - `requirements.legacy-train.txt` contains archived training/research
    dependencies such as TorchVision, datasets, pandas and scikit-learn.
  - `pyproject.toml`, `README.md`, `RUNBOOK.md`,
    `docs\legacy_ml_inventory.md` and the LaTeX report describe this split.
- Updated source-bundle/report guards:
  - the clean source ZIP now has `236` entries;
  - generated/local artifacts remain excluded;
  - the source ZIP includes the optional/legacy requirements files;
  - `tests\test_factcheck_core.py` guards the dependency split and report
    strings.
- Verification after this final refresh:
  - full `scripts\run_release_gate.ps1`: OK;
  - backend unit/integration tests inside the gate: `111/111` OK;
  - product acceptance: `82/82` OK;
  - university report PDF build: OK;
  - Render bundle + fresh-venv smoke: OK;
  - desktop smoke/package verification: OK;
  - Flutter analyze/tests: OK, `8/8`;
  - internet/LAN APK verification: OK;
  - emulator smoke evidence remains passing;
  - physical device smoke remains a current skipped report because no
    authorized Android phone is connected.
- Final submission verifier:
  - `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`
  - generated `2026-05-29T20:44:12.9340316+02:00`;
  - `OK=True`;
  - failures: `0`;
  - expected warnings: `2`:
    - permanent cloud phone readiness is false until a real Render HTTPS URL
      and cloud APK are verified;
    - physical phone smoke is skipped until rerun with `-RequireDevice` on an
      authorized Android phone.
- Current final artifacts after dependency split:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160101737`, SHA256
    `5DC4573E8858FE7E571F1FBA0149359D58297C62ABDB95E880C6522CD163D923`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `236` entries,
    forbidden generated/local paths `0`, `has_tex=True`, `has_pdf=False`, size
    `2830133`, SHA256
    `50F9C2F1450483A6F4C5EFED26165078CB288AEA96DE14471ABE31B3DC86C3E6`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348905`, SHA256
    `DB856F18D2E912C369AD6C3A50BAD8A301AF22E3513E9FC3CC61C365BCC649FB`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `66243`, SHA256
    `17CE9D669DB64AC125E59649E35DF578C32FE937045D751D2691097F9C806FD1`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22628`,
    SHA256
    `3D4D76C400B9036AA97104E58B5B2F611011F5F518A90D8D30806739AD267B10`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `E85BBF71F9CE4458FEE5808B0E64DAAD3C4C9E256DE89E0AF16D2ACCE3C18120`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `2537818F394E51B1894536C62CE94B17FA2A4BD73C7A2B6EC38CD7C60425AF3F`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `32776`, SHA256
    `244C3B23E4499F8AC375437E8A8EDA42ADAA1BDE5BA1B1AB7348430A8570E16D`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `16049`,
    SHA256
    `97B811175F80981F50C7BE715F537D6B78B9E4155A8F46094362ED5CE058EA84`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `A0A0EF27940E9E6B6D50E40D07C09C7336534990C80096A0C691787F0C37E762`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `27CF0A49AE8595EEE382CC85D47A938A1B5D7EE48E8F16C59E7FDE0471BAF905`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `A014A7AABE248FB15D382625B30E9FEAD54A767A75306431052FEEDA101BF496`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2947`,
    SHA256
    `5B094BE24D5815A55DBABB7BE8350962DB7644F1D31E44CA18ACF4DD88783BAE`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2918`,
    SHA256
    `8A1FCCC2722B525B3DB9748EC317F9F8386E473BCCC60CD6B0F609D97DE8ADF1`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: LaTeX Source Bundle Hygiene Hardening

Completed after the dependency split refresh:

- Hardened report/source packaging against generated LaTeX byproducts:
  - `scripts\build_report.ps1` now removes common report auxiliary files such
    as `.aux`, `.out`, `.toc`, `.fls`, `.fdb_latexmk`, `.synctex.gz`, `.bbl`,
    `.blg`, `.nav`, `.snm` and `.vrb` after a successful PDF build.
  - `scripts\make_source_bundle.ps1` now prunes the same report byproducts
    from the source ZIP staging area even if they already exist on disk.
  - `scripts\verify_submission_bundle.ps1` now rejects those LaTeX byproducts
    if they ever appear inside `source/verity-lens-source.zip`.
  - `tests\test_factcheck_core.py` now creates fake report byproducts during
    the source-bundle test and verifies that none are packaged.
- Verification:
  - targeted source-bundle hygiene test: OK;
  - `scripts\build_report.ps1`: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside the gate: `111/111` OK;
  - product acceptance: `82/82` OK;
  - Flutter analyze/tests: OK, `8/8`;
  - final `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: `OK=True`, `0` failures, `2` expected warnings.
- Latest release/submission reports:
  - release gate: `reports\release_gate_latest.md`, generated
    `2026-05-29T20:49:20.9069091+02:00`;
  - submission verification:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`, generated
    `2026-05-29T20:49:46.1041013+02:00`.
- Current final artifacts after LaTeX hygiene hardening:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160102285`, SHA256
    `1E33D9CCE3A2D913DFB09D01C6FDF4A3C121C42C96C8C2AA40982EBD73846C9F`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `236` entries,
    LaTeX auxiliary files `0`, forbidden generated/local paths `0`, size
    `2830746`, SHA256
    `79B2E5D6F3D788FF48834A2401C2887A22DE8961C3E01648E35F103A65DE9959`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `66244`, SHA256
    `3D887EC9F585EDD2E6721E6C77E0BB9196ED3A01608E0F4BDB5C73BD6D1AF202`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22621`,
    SHA256
    `86934DFD1487D3B5D4E7D9D059EE4B9A58A489A8953AAE3F8BFBD4E417782BF3`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `39678A003CFC44F537F84A944779003629D174470DFDB2C0D37C9566527A2A06`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `32776`, SHA256
    `DA5FDA5B65BED910F89BAF5CBB6D75C6DB3380E1D3855F82A296273A8B4A3304`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Mobile API Error Handling And Fresh APKs

Completed after LaTeX/source hygiene hardening:

- Improved the Flutter phone API client:
  - `apps\fake_news_detector_flutter\lib\api_client.dart` now has explicit
    health/text/image timeouts that can be injected in tests.
  - Text and image API calls now convert timeout, invalid JSON and HTTP client
    failures into clear `FactCheckApiException` messages instead of falling
    through to one generic UI error.
  - Health checks now report invalid JSON and timeout as offline states with
    specific messages.
- Added Flutter coverage:
  - `apps\fake_news_detector_flutter\test\widget_test.dart` now tests invalid
    API JSON, request timeout handling and invalid health JSON.
  - Flutter tests increased to `11/11`.
  - `docs\report\verity_lens_report.tex` and
    `tests\test_factcheck_core.py` now guard `Flutter tests` as `11/11 OK`.
- Rebuilt phone artifacts from the updated Flutter source:
  - internet APK against `https://slick-rules-deny.loca.lt`;
  - LAN APK against `http://192.168.1.16:8001`.
- Reverified phone evidence after APK SHA changed:
  - internet APK verification OK, including live `/health`, `/ready`,
    fact-check probe and embedded API URL;
  - LAN APK verification OK, including live API checks and embedded API URL;
  - emulator smoke rerun against the fresh internet APK and passed;
  - physical device smoke refreshed and remains skipped because no authorized
    Android phone is connected.
- Verification:
  - `flutter analyze`: OK;
  - `flutter test`: `11/11` OK;
  - targeted report/source-bundle tests: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside gate: `111/111` OK;
  - product acceptance: `82/82` OK;
  - final `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: `OK=True`, `0` failures, `2` expected warnings.
- Latest release/submission reports:
  - release gate: `reports\release_gate_latest.md`, generated
    `2026-05-29T20:57:57.3103146+02:00`;
  - submission verification:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`, generated
    `2026-05-29T20:58:23.5662146+02:00`.
- Current final artifacts after mobile API hardening:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160119675`, SHA256
    `66056143B4A7D80F8B3A94B41FB21DCBAE6C06085061514BF7BE81E3F60D8698`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `236` entries,
    forbidden generated/local paths `0`, size `2831372`, SHA256
    `9DC1C8D920A417149CD61990BEEF526CFAA3EC92AAB93948F5D0D92974F79D3E`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `66248`, SHA256
    `324AC4E028A0ACA28F9833AD1635266B135E9857BBA9FEECFA53051A084AE5BB`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22627`,
    SHA256
    `1E04E80C9C324B676043654AD160D895AB2390E228820D8AE554CD4633818653`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `B48CCE263032B30B2FAFEA455B0FA1B0CFF75CB34939E13412BD3972689144A6`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `34C914A6D290EA91886EFD7D4A205B627692BDFD4FAEE6B2180E570FCB3A88DF`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `A32EC3666258D3D2706C86AABE581552D6C0C6DE9563710CFDB6DC6DB1D4AF29`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `16049`,
    SHA256
    `ACF097491266FB75A6B3A953F8E7CB5D1774B8EBEF2C68742A15D2EAC3E97165`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `32776`, SHA256
    `A8704FA2ACC70381602A97811412C174ACB87D7AE03C0EFB52E9BDE57BECCD05`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: APK Flutter Source Stamp Freshness Guard

Completed after mobile API error handling:

- Added a deterministic Flutter source stamp:
  - new helper `apps\fake_news_detector_flutter\tool\flutter_source_stamp.ps1`;
  - hashes the mobile runtime source/config used for APK builds (`lib`,
    Android main source/resources, `pubspec`, Gradle config);
  - current stamp SHA256:
    `2128A42C6FA9CBAD23B8A9DA94A625C090E8FE572A93B94D7D900EE651F09304`;
  - current stamp file count: `19`.
- Hardened APK build/verification:
  - `apps\fake_news_detector_flutter\tool\build_internet_apk.ps1` now writes
    `*-flutter-source-stamp.json` beside each APK and records the Flutter
    source SHA256 in build status markdown.
  - `scripts\build_phone_for_lan.ps1` and `scripts\build_phone_for_cloud.ps1`
    preserve the same source SHA in their final status reports.
  - `scripts\verify_phone_apk.ps1` now recomputes the current Flutter source
    stamp and fails if it does not match the stamp saved during APK build.
  - `scripts\check_phone_readiness.ps1` reports whether the source-stamp
    sidecar exists and matches current source.
  - `scripts\verify_submission_bundle.ps1` now fails if internet/LAN APK
    verification lacks the Flutter source stamp, reports a mismatch, or if the
    bundled sidecar JSON does not match the verification evidence.
- Updated docs/report/tests:
  - `README.md` and `RUNBOOK.md` explain that APK verification now prevents
    stale mobile binaries after Flutter source changes.
  - `docs\report\verity_lens_report.tex` describes this source-stamp check.
  - The clean source ZIP count is now `237` because the helper is included.
  - `tests\test_factcheck_core.py` guards the stamp workflow and report count.
- Rebuilt fresh APKs from stamped source:
  - internet APK against `https://slick-rules-deny.loca.lt`;
  - LAN APK against `http://192.168.1.16:8001`.
- Reverified phone evidence after APK SHA changed:
  - internet APK verification OK; source stamp sidecar exists, status matches
    stamp, and `matches_current_source=True`;
  - LAN APK verification OK with the same stamp checks;
  - emulator smoke rerun against the fresh internet APK and passed;
  - physical device smoke refreshed and remains skipped because no authorized
    Android phone is connected.
- Verification:
  - helper source-stamp probe: OK;
  - source ZIP probe: `237` entries, helper present, forbidden `0`;
  - targeted tests: OK;
  - `flutter analyze`: OK;
  - `flutter test`: `11/11` OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside gate: `111/111` OK;
  - product acceptance: `82/82` OK;
  - final `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: `OK=True`, `0` failures, `2` expected warnings.
- Latest release/submission reports:
  - release gate: `reports\release_gate_latest.md`, generated
    `2026-05-29T21:11:58.8645944+02:00`;
  - submission verification:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`, generated
    `2026-05-29T21:12:26.6589827+02:00`.
- Submission ZIP source-stamp sidecars:
  - submission entry count: `41`;
  - source ZIP entry count: `237`;
  - source ZIP helper present:
    `apps/fake_news_detector_flutter/tool/flutter_source_stamp.ps1`;
  - source ZIP forbidden generated/local paths: `0`;
  - source ZIP LaTeX aux byproducts: `0`;
  - bundled phone sidecars:
    `phone/VerityLens-internet-flutter-source-stamp.json`,
    `phone/VerityLens-lan-flutter-source-stamp.json`;
  - internet verification: `sidecar_exists=True`,
    `matches_current_source=True`, `status_matches_stamp=True`;
  - LAN verification: `sidecar_exists=True`, `matches_current_source=True`,
    `status_matches_stamp=True`;
  - Flutter source stamp SHA256:
    `2128A42C6FA9CBAD23B8A9DA94A625C090E8FE572A93B94D7D900EE651F09304`.
- Current final artifacts after bundled APK source-stamp sidecar refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160124979`, SHA256
    `06F7108E88A7E700B2CB44BC8484F5D09311AE86897485C43653B6EFCB0E3BE1`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `237` entries,
    helper present, forbidden generated/local paths `0`, size `2834532`,
    SHA256
    `3CF8C16A8059AAD78A6DCAEABEEF71F4D3F19547EA7F3E7DE189AE4E88A5F2E1`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1348981`, SHA256
    `327017678D80A8C3B14D9792241B3124E6C8DE20DC24428524EC6D9758FD4263`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `66337`, SHA256
    `D01E91E3142F994E3BF8161D01880AAEF1FD79826B630C44372ACEC61B6EF900`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22628`,
    SHA256
    `5D32977262254E610132129779FCB5CF2E636F1F88344F26CB21369601E52F99`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `0ACF01EE61AFEDE3653B1FF2E0026D232F5FE8CE1B1A032F593A984ABE4F9A5E`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `27C9E358EB38DDDF82D9AF9D71EBC8345DAD3778F7DCCFFA1E12DB12350B058C`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `8D8F59168F81CBF4F85B679FD39A8C4FF4A0D2F0791A9AC267A912B5DCE7C584`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `1AF7CA38F17F65A6853FAC34D9B597797796987A4FDE0B95EEF3B609AE14A4CE`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `3781`,
    SHA256
    `E309FECFC6FD1392305980219926302A957EFFE955F7427754D60B6DD1F326A6`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `3747`,
    SHA256
    `BB18C23C46AC4BD569FDCB967CF4D2B0C55FEC7BFA444E900D1962260F151159`;
  - internet source-stamp sidecar:
    `outputs\phone_download\VerityLens-internet-flutter-source-stamp.json`,
    size `1318`, SHA256
    `C2FF7B7F2F3E3E6AED25ABB0E7323262150B9E3EE1A0A1F497B565BB7C31A0D5`;
  - LAN source-stamp sidecar:
    `outputs\phone_download\VerityLens-lan-flutter-source-stamp.json`,
    size `1318`, SHA256
    `C2FF7B7F2F3E3E6AED25ABB0E7323262150B9E3EE1A0A1F497B565BB7C31A0D5`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `33546`, SHA256
    `56DF582501EC8A1A44D018A092D967BB32668821F458192DA3938660D6321DD7`;
  - device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `B985A65F306E4B8917FA651FFD943E633A73B8DB8D2E46D42F7CC82AB0C40CFA`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `16049`,
    SHA256
    `317D8965E72E7EB66E077CE2E8673980768B9CE6B240325481B58F6457B40A21`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Cloud Status Refactor And APK Probe Retry

Completed after the bundled source-stamp sidecar refresh:

- Refactored permanent-cloud status writing:
  - `scripts\finalize_cloud_deploy.ps1` now delegates final status generation
    to `scripts\write_cloud_deployment_status.ps1` instead of duplicating the
    same artifact/status JSON logic.
  - `scripts\write_cloud_deployment_status.ps1` now records:
    - `PHONE_CLOUD_APK_VERIFICATION.json`;
    - `VerityLens-cloud-flutter-source-stamp.json`;
    - whether the cloud APK source stamp matches current Flutter source;
    - whether the cloud APK status file matches that Flutter source stamp.
  - This keeps the future Render/cloud APK path aligned with the internet/LAN
    APK source-stamp evidence already in the submission verifier.
- Hardened APK verification against transient tunnel/cold-start failures:
  - `scripts\verify_phone_apk.ps1` now retries the `/health`, `/ready`, and
    `/factcheck` probe before failing.
  - The APK verification JSON/markdown now includes `api.attempts` /
    `API probe attempts`.
  - This fixed a real release-gate transient where LocalTunnel briefly returned
    HTTP 404 during the first internet APK verification; the final gate passed
    after the retry-aware verifier was added.
- Cleaned report byproducts:
  - `scripts\build_report.ps1` now removes `docs\report\verity_lens_report.log`
    along with the other LaTeX auxiliary files.
  - The source bundle test now creates/checks that `.log` byproduct too.
- Updated docs/report/tests:
  - `README.md`, `RUNBOOK.md`, and `docs\mobile_flutter_render.md` mention the
    cloud APK source-stamp status evidence.
  - `docs\report\verity_lens_report.tex` documents that
    `CLOUD_DEPLOYMENT_STATUS.json` records the cloud verification JSON and cloud
    Flutter source-stamp sidecar.
  - `tests\test_factcheck_core.py` now guards the refactor, cloud source-stamp
    status, retry-aware APK probe, and `.log` cleanup.
- Verification:
  - PowerShell parser checks: OK for `finalize_cloud_deploy.ps1`,
    `write_cloud_deployment_status.ps1`, `verify_phone_apk.ps1`,
    `build_report.ps1`;
  - targeted tests for mobile/cloud/report/source bundle: OK;
  - backend tests inside final gate: `111/111` OK;
  - product acceptance: `82/82` OK;
  - Flutter analyze/tests inside final gate: OK, `11/11`;
  - final `scripts\run_release_gate.ps1`: OK;
  - final `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: `OK=True`, `0` failures, `2` expected warnings.
- Latest release/submission reports:
  - release gate: `reports\release_gate_latest.md`, generated
    `2026-05-29T21:23:57.5714783+02:00`;
  - submission verification:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`, generated
    `2026-05-29T21:24:27.8179240+02:00`.
- Current final artifacts after cloud status/retry refresh:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160126339`, SHA256
    `A38501DB10A282D1C0107AE7E9F631E38BEF3BFCF1899B006EA7E7ADF1029D93`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `237` entries,
    helper present, forbidden generated/local paths `0`, LaTeX aux/log count
    `0`, size `2834915`, SHA256
    `9D68AB0EF13D2ECF7C40C2283A752E9006B7701E3327460013E84DA5265E0B90`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349064`, SHA256
    `2693363CBF985227C3FC8BCC5C81BF1748E135F986F1B1DC626C43A4C665E89B`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `66595`, SHA256
    `23206CC7E89F0F8A5AF534462CFE33CE87B51209B31FE4A6882146B4FF651FFC`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22626`,
    SHA256
    `F9E73FC6EB62928EAC2F0660C9DB665AEA2081CDF779ACEC58D2C1774F183F69`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `DF05A451DEE558A4F558E6C90FC519FE70D0121F7EEEE90898AE78B7AE903436`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `A6CAB4D507A538A447625AE05CCF57BCFD6A0B86A5C86B79DBE03A51A3932E24`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3859`, SHA256
    `3C9AD322287E429A8114B172AB2889570A2BF776D156628D20EF7DD30EC2CFC4`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `8D8F59168F81CBF4F85B679FD39A8C4FF4A0D2F0791A9AC267A912B5DCE7C584`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `1AF7CA38F17F65A6853FAC34D9B597797796987A4FDE0B95EEF3B609AE14A4CE`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `3814`,
    SHA256
    `FD45EFA5DF036C5E474A7EACEF6489F33CCD91AA23033E1B3F0DB0DAE2BED4F5`,
    `api.attempts=1`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `3780`,
    SHA256
    `9E04618EF9053726CAF9666A8F0DD732E748970DDCB7E85ACB4A8F95F5CB5784`,
    `api.attempts=1`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `33546`, SHA256
    `670AF58750717F017C87E4BB81A7A0EF7768C78168158FC4AD6DD5CDA4A8D921`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `1755`, SHA256
    `3221115C915C35ED8C06C8536F7A2A4448A34B0CE37B3C93C4386928A975E93C`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `16049`, SHA256
    `317D8965E72E7EB66E077CE2E8673980768B9CE6B240325481B58F6457B40A21`.
- Current remaining external gap is unchanged:
  - `phone_permanent_cloud=False` until a real Render HTTPS backend and
    `VerityLens-cloud.apk` are built/verified;
  - `PHONE_DEVICE_SMOKE.json` is still skipped without an authorized physical
    Android device and must be rerun with `-RequireDevice` for final proof.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Phone Device Screenshot Proof

Completed after cloud status/retry hardening:

- Strengthened final physical Android proof:
  - `scripts\smoke_phone_on_device.ps1` now captures a binary-safe device
    screenshot with `adb exec-out screencap -p` after install/launch/foreground
    verification.
  - When an authorized device is present, the smoke now writes
    `outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png` and records screenshot
    size/SHA256 in `PHONE_DEVICE_SMOKE.json`.
  - A non-skipped successful device smoke now requires screenshot capture in
    addition to package installed, launch started, and foreground package match.
  - Without an authorized Android device, the report remains a clean skipped
    proof and does not create a screenshot file.
- Strengthened emulator proof path:
  - `scripts\smoke_phone_emulator.ps1` passes an emulator screenshot path into
    `smoke_phone_on_device.ps1`.
  - Future emulator runs will write
    `outputs\phone_download\PHONE_EMULATOR_SCREENSHOT.png` and include its
    SHA256 in the nested device-smoke evidence.
- Updated packaging/verifier:
  - `scripts\make_submission_bundle.ps1` optionally includes
    `phone\PHONE_DEVICE_SCREENSHOT.png` and
    `phone\PHONE_EMULATOR_SCREENSHOT.png`.
  - `scripts\verify_submission_bundle.ps1` now fails if a successful physical
    device smoke lacks a captured screenshot SHA or if the bundled screenshot
    hash does not match.
  - If an emulator smoke includes a captured screenshot, the verifier also
    cross-checks the bundled emulator screenshot hash.
- Updated docs/report/tests:
  - `README.md`, `RUNBOOK.md`, and `docs\mobile_flutter_render.md` document the
    screenshot proof files.
  - `docs\report\verity_lens_report.tex` states that physical device smoke
    saves `PHONE_DEVICE_SCREENSHOT.png` and its SHA256.
  - `tests\test_factcheck_core.py` guards the new screenshot proof flow.
- Verification:
  - PowerShell parser checks for changed smoke/submission scripts: OK;
  - skipped physical-device smoke path: OK, no authorized Android device found;
  - targeted tests for mobile/cloud/report/source/gate coverage: OK;
  - backend tests inside final gate: `111/111` OK;
  - product acceptance: `82/82` OK;
  - Flutter analyze/tests inside final gate: OK, `11/11`;
  - final `scripts\run_release_gate.ps1`: OK;
  - final `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: `OK=True`, `0` failures, `2` expected warnings.
- Latest release/submission reports:
  - release gate: `reports\release_gate_latest.md`, generated
    `2026-05-29T21:31:15.5854057+02:00`;
  - submission verification:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`, generated
    `2026-05-29T21:31:44.7350530+02:00`.
- Current final artifacts after phone screenshot proof:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `160128448`, SHA256
    `E80FC1A181B8A74F54207D819D0A384C6624063B1B450FA6AF1A309619D334C7`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `237` entries,
    forbidden generated/local paths `0`, size `2836252`, SHA256
    `2BEC88E418DB3C7784BFD9A4FAB292887953EE621CDA8B38BA2A488304E8D648`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349111`, SHA256
    `583B3A91BF44305D17BB1E06DE6FFF2A7467A7AB61803EC69022963D95B483F6`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `66801`, SHA256
    `EE656ADA27FA259C6F3B9CFA14686F22CD102E2A7ED3373D1DE94D0616808671`;
  - release gate JSON: `reports\release_gate_latest.json`, size `22624`,
    SHA256
    `89445281B22C01CEE20F953010631DC5720C54936D3B432A2EE1A2A8A234CDBB`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `1D6461E06226046C11E473116C95D0812B210571131E5B2081DFD61E0B3C62F4`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `8FFEEC98052DB9AAB2E67DB54892A3E5DDFE1F68AAFA3D5F51D0EBCD4877CB7A`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `34340`, SHA256
    `FC85FFA285DA2398E1489BA80158949E432F91FD34DD177C61778529EB29FCCE`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `2278`, SHA256
    `4AD4D277F70D0AC29662830B57B3EA0F070C2BA81215544B935D26FEBC319036`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `16049`, SHA256
    `317D8965E72E7EB66E077CE2E8673980768B9CE6B240325481B58F6457B40A21`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `3814`,
    SHA256
    `7C77A736D6F30F98A2B833C5B0B2CCE7F645A1C0DDA40649D39F8CB5631C7891`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `3780`,
    SHA256
    `896B34C31D59CD35C6B031B8169210DCDAA8462920ED6B09ADA71E182D56A05A`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `8D8F59168F81CBF4F85B679FD39A8C4FF4A0D2F0791A9AC267A912B5DCE7C584`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `1AF7CA38F17F65A6853FAC34D9B597797796987A4FDE0B95EEF3B609AE14A4CE`;
  - no screenshot files are present yet because the physical device smoke is
    skipped and the emulator screenshot path has not been rerun after this
    change.
- Current remaining external gap is unchanged:
  - `phone_permanent_cloud=False` until a real Render HTTPS backend and
    `VerityLens-cloud.apk` are built/verified;
  - `PHONE_DEVICE_SMOKE.json` is still skipped without an authorized physical
    Android device and must be rerun with `-RequireDevice` for final proof;
  - after that real-device run, expect `PHONE_DEVICE_SCREENSHOT.png` to be
    included in the submission bundle and cross-checked by SHA256.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Strict Final Cloud Phone Submission Wrapper

Completed after the phone screenshot proof:

- Added the strict final external-closeout command:
  - `scripts\finalize_cloud_phone_submission.ps1`
  - It requires a permanent public HTTPS Render-style API URL via the shared
    `cloud_url_policy.ps1`.
  - It runs `scripts\run_release_gate.ps1` with `-BuildCloudApk`,
    `-CloudApkMode release`, `-PhoneDeviceApkPath`, and
    `-RequirePhoneDevice`.
  - It then runs `scripts\make_submission_bundle.ps1` and
    `scripts\verify_submission_bundle.ps1`.
  - It writes `reports\final_cloud_phone_submission_latest.json/md`.
  - Final OK requires: release gate OK, submission verifier OK,
    `phone_permanent_cloud=True`, physical device smoke OK, and
    `PHONE_DEVICE_SCREENSHOT.png` captured/present.
  - Output paths are guarded with `path_safety.ps1` so the wrapper cannot write
    final reports/submission output outside the project.
- Updated packaging/tests/docs:
  - `scripts\make_source_bundle.ps1` now requires and checks
    `scripts\finalize_cloud_phone_submission.ps1`.
  - Source bundle expected clean entry count is now `238`.
  - `README.md`, `RUNBOOK.md`, `docs\mobile_flutter_render.md`, and
    `docs\report\verity_lens_report.tex` document the strict final wrapper.
  - `tests\test_factcheck_core.py` guards the wrapper, source bundle inclusion,
    report text, and final cloud/phone evidence requirements.
- Verification:
  - PowerShell parser checks for `finalize_cloud_phone_submission.ps1` and
    `make_source_bundle.ps1`: OK;
  - targeted tests for mobile/render files, source bundle, and LaTeX report:
    OK (`3/3`);
  - final `scripts\run_release_gate.ps1`: OK;
  - backend tests inside final gate: `111/111` OK;
  - product acceptance: `82/82` OK;
  - Flutter analyze/tests inside final gate: OK, `11/11`;
  - final `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: `OK=True`, `0` failures, `2` expected warnings:
    permanent cloud phone readiness still awaits a real Render HTTPS URL/cloud
    APK, and physical Android smoke is still skipped without an authorized
    device.
- Latest release/submission reports:
  - release gate: `reports\release_gate_latest.md`, generated
    `2026-05-29T21:38:50.0004377+02:00`;
  - submission verification:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`, generated
    `2026-05-29T21:39:14.0816012+02:00`.
- Current final artifacts after strict wrapper addition:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161656062`, SHA256
    `E0F54021A1CF7633207B12BB2ACD0A1975951B0E046EA9AB44BDC3EC32D6BFA6`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `238` entries,
    forbidden generated/local paths `0`, size `2839738`, SHA256
    `9A1D5D3F58C84C8C7D5CECB95077B314473D6E0887CBF615CAD07BD2D2DED4F3`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349207`, SHA256
    `8FF88BC172BA670B38FBBCF5AECD8A822E76BC0411DA5F3ED5C7F72051351BC6`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67139`, SHA256
    `C5AB00DB89BFBB41A0B84E1A9080B8C01CAC238AD7C13B2153B5EAC83BD794B0`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12375`,
    SHA256
    `3D443E7EE2D3AEB161ACB6935D8DAC2647BE07A43E9E777ED7D9E010ECCCC06F`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `32768`, SHA256
    `FA94813A89094E4F3EF1395996E9C1012694B48EA5D1D3D9948777F23A2A8E30`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `64CD7E0B61386C6A91577771485DCBFBD0B3EAA23D426707B2D78DCBEA06179D`;
  - phone readiness JSON:
    `outputs\phone_download\phone_readiness.json`, size `34340`, SHA256
    `564A9B7FDA842075E1629624EF6EBA0511930E2FB18F8AD05B2DFE4F820C5C21`;
  - physical device smoke JSON:
    `outputs\phone_download\PHONE_DEVICE_SMOKE.json`, size `2278`, SHA256
    `9A5A81A3D960F3E1F606A177EC475CF0308C21FC0485475CFD79E70759CCB833`;
  - emulator smoke JSON:
    `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`, size `16049`, SHA256
    `317D8965E72E7EB66E077CE2E8673980768B9CE6B240325481B58F6457B40A21`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `3814`,
    SHA256
    `70260DEFE79C3AF668F7C2453764D217E0E4B100D3142161508F7BE68B7591AD`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `3780`,
    SHA256
    `3A8B35BB47532B6E35BD6C98C855E532AEFF7822F8F0455970F4600DCD89ECED`;
  - temporary internet APK: `outputs\phone_download\VerityLens-internet.apk`,
    size `49843593`, SHA256
    `8D8F59168F81CBF4F85B679FD39A8C4FF4A0D2F0791A9AC267A912B5DCE7C584`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `1AF7CA38F17F65A6853FAC34D9B597797796987A4FDE0B95EEF3B609AE14A4CE`.
- `reports\final_cloud_phone_submission_latest.*` intentionally has not been
  generated yet because the wrapper needs the real Render URL and authorized
  USB Android device.
- Remaining work is still about `8-10%`, and it is external/stateful:
  deploy Render, run the strict wrapper with the real URL and phone connected,
  confirm `phone_permanent_cloud=True`, and capture/bundle
  `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Expanded Acceptance Matrix To 93 Cases

Completed after the strict final wrapper work:

- Strengthened the 95% product-evidence gate:
  - `scripts\run_product_acceptance.py` now has `93` deterministic acceptance
    cases instead of `82`.
  - Facts remain `44/44`.
  - News credibility expanded to `15/15`, including FDA institutional
    corroboration, EAC institutional high-source coverage, and Reddit/social
    guardrail coverage.
  - Screenshot OCR expanded to `12/12`, including extra true/fake everyday and
    numeric screenshot claims.
  - AI-image risk expanded to `11/11`, including Leonardo AI,
    AUTOMATIC1111/Stable Diffusion metadata markers, and another plain JPEG
    false-positive guard.
  - API/mobile contract expanded to `11/11`, adding missing image upload and
    unsupported GET method rejection cases.
- Adjusted the submission verifier:
  - A live temporary tunnel is no longer a hard final ZIP failure because
    LocalTunnel/quick-tunnel URLs can expire or return provider-side 404s
    between builds.
  - `phone_temporary_tunnel=False` is now reported as a warning.
  - Stable phone gates remain hard checks: PC package, same-Wi-Fi/LAN phone
    readiness, install/download page, Render deployment bundle, permanent cloud
    warning, and physical-device final proof via the strict wrapper.
- Updated docs/report/tests:
  - `docs\report\verity_lens_report.tex` now reports `93/93` and the expanded
    per-section counts.
  - `README.md` and `RUNBOOK.md` explain that temporary tunnel readiness can
    warn because tunnel URLs are not permanent.
  - `tests\test_factcheck_core.py` guards the new acceptance case IDs and the
    temporary-tunnel warning behavior.
- Verification:
  - `scripts\run_product_acceptance.py`: `93/93` OK, every section `100%`;
  - targeted tests for acceptance/report/mobile verifier behavior: OK;
  - final `scripts\run_release_gate.ps1`: OK;
  - backend tests inside that gate: `111/111` OK;
  - product acceptance inside that gate: `93/93` OK;
  - Flutter analyze/tests inside that gate: OK, `11/11`;
  - final `scripts\make_submission_bundle.ps1`: OK after verifier adjustment;
  - full unittest after all edits: `111/111` OK.
- Latest release/submission reports:
  - release gate: `reports\release_gate_latest.md`, generated
    `2026-05-29T21:44:38.2237201+02:00`;
  - submission verification:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`, generated
    `2026-05-29T21:46:36.5463981+02:00`.
- Current final artifacts after acceptance expansion:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161657840`, SHA256
    `2D684A0546FBD37994598649081069FEAD85559E647D6F52C198F3F0B0957B80`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `238` entries,
    forbidden generated/local paths `0`, size `2840719`, SHA256
    `EEB1E34A6F1EA110BE7D50683D117AEF95C3F9CEC7F4AB487B727DD497F3211D`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67153`, SHA256
    `FC40D380D0DE7D210B4C9C60DBA1ED6EA296984655FD7F28A91D74183AF049B3`;
  - release gate JSON: `reports\release_gate_latest.json`, SHA256
    `F6E516448D84B2F39E08EC7D13B1431EEA8B8B14F81FC4E39B4A7E95B6EBB35E`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, SHA256
    `1966FC7B544F091F9CF6F807C7A8339A4BA434D45A68D5F3B41FA50FE2C9B5F7`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, SHA256
    `CF73D7BC4FCE1856DCAD9ED9DDC84B040445365C808ACE3D6568F5F9DE9CCE23`.
- Current verifier state:
  - `OK=True`, `0` failures;
  - `4` warnings:
    1. release gate temporary tunnel readiness is false;
    2. temporary tunnel phone readiness is false;
    3. permanent cloud phone readiness is false until real Render HTTPS/cloud
       APK;
    4. physical Android device smoke is skipped until a connected authorized
       phone is used.
- Remaining work is still external/stateful:
  - Deploy permanent Render HTTPS backend.
  - Run `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`
    with an authorized Android phone connected.
  - Verify `phone_permanent_cloud=True` and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Section-Specific Acceptance Minimums

Completed after expanding the acceptance matrix:

- Strengthened `scripts\run_product_acceptance.py` so the gate cannot silently
  shrink back to a small 5-case-per-section suite.
- New explicit minimums in `min_cases_by_section`:
  - `facts`: `40`;
  - `news`: `15`;
  - `screenshots`: `12`;
  - `images`: `11`;
  - `api_contract`: `11`.
- `scripts\verify_submission_bundle.ps1` now reads
  `min_cases_by_section` from `quality/product_acceptance_latest.json` inside
  the submission ZIP and fails if any section has fewer than its required
  number of cases.
- Documentation/report alignment:
  - `README.md` and `RUNBOOK.md` now describe section-specific minimum case
    counts instead of the old generic five-case floor.
  - `docs\report\verity_lens_report.tex` now explains the section-specific
    minimums and no longer says that expanding the acceptance benchmark is the
    next main product task.
- Verification after this hardening:
  - `scripts\run_product_acceptance.py`: `93/93` OK with
    `min_cases_by_section` present in JSON;
  - targeted tests for mobile/render, acceptance and LaTeX report: OK;
  - final `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `111/111` OK;
  - Flutter analyze/tests inside release gate: OK, `11/11`;
  - final `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: `OK=True`, `0` failures, `2` expected warnings.
- Latest release/submission reports:
  - release gate: `reports\release_gate_latest.md`, generated
    `2026-05-29T21:51:43.7575857+02:00`;
  - submission verification:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`, generated
    `2026-05-29T21:52:09.8719055+02:00`.
- Current final artifacts after section-minimum hardening:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161658656`, SHA256
    `ADD3FFF6DE05475B60E5E3CD9BD147A0D5AE8B6CD61BA3C7AA4981FAF2D10BF8`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `238` entries,
    forbidden generated/local paths `0`, size `2841093`, SHA256
    `13293D5852C23B660A2E942445135E3AFC6C6ADC7FA0D63090CD988E0246D7EA`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349297`, SHA256
    `16216CD00A6604D83E75128D959B357AA2DAB4FB5355B72129A2D6B3C27F2651`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67417`, SHA256
    `022D83C6D5671400D1561717A1FD30DA5DE40EE51DDDDBD73CE4522217A8CAE0`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12548`,
    SHA256
    `2B149C175D6CDF5386F93D452521A3D4F373C58F5AE658077406F28167023CA3`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `7185902520A49ED7982F74437D7FE378AF5919625D83CC5FC785D047337EA589`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, SHA256
    `2D27BE99A84AAA610FEEDC6C9F24D4FFFF8A100DE12C082F7109793213BFC634`.
- Current verifier state:
  - `OK=True`, `0` failures;
  - `2` expected warnings:
    1. permanent cloud phone readiness is false until real Render HTTPS/cloud
       APK;
    2. physical Android device smoke is skipped until a connected authorized
       phone is used.
- Remaining work is still external/stateful:
  - Deploy permanent Render HTTPS backend.
  - Run `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`
    with an authorized Android phone connected.
  - Verify `phone_permanent_cloud=True` and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Emulator Screenshot Proof Included In Submission

Completed after rerunning emulator proof and refreshing the release/submission
artifacts:

- Reran `scripts\smoke_phone_emulator.ps1 -AvdName FakeNewsDetector_API36 -RequireEmulator`.
- Emulator proof is now captured and packaged:
  - emulator smoke JSON: `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`,
    size `14770`, SHA256
    `157F077D2A0302A72D431B36780B81FACAE88F8ED9B68553B3D52E2DF106F0B2`;
  - emulator screenshot:
    `outputs\phone_download\PHONE_EMULATOR_SCREENSHOT.png`, size `89342`,
    SHA256
    `218D31BAD8CEAD94307C4611EB0F8B7A0E475B62A8307E6C10EC4497E5F54C84`;
  - nested `device_smoke.ok=True`;
  - nested `device_smoke.screenshot.captured=True`.
- Reran full release gate after the emulator proof so artifact hashes match:
  - release gate: `reports\release_gate_latest.json`, generated
    `2026-05-29T21:56:41+02:00`, `OK=True`, size `12548`, SHA256
    `C4B2A704E9B4A6591214E12C7288F520B5197AA8CF4B217C3E85779C008505F0`;
  - backend tests inside release gate: `111/111` OK;
  - product acceptance inside release gate: `93/93` OK;
  - Flutter analyze/tests inside release gate: OK, `11/11`;
  - TeX build: OK with only non-failing fontconfig/underfull warnings.
- Reran `scripts\make_submission_bundle.ps1` after the release gate:
  - submission verifier: `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.md`,
    generated `2026-05-29T21:57:49.5854105+02:00`;
  - verifier state: `OK=True`, `0` failures, `2` expected warnings;
  - submission ZIP entry count: `42`;
  - `phone/PHONE_EMULATOR_SCREENSHOT.png` is present inside the submission ZIP.
- Fresh final artifacts:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161734813`, SHA256
    `367E71B8AF0AD902A4995D3D40FFE845DDBFF9CC1C7393B9E624C588F825ED37`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `238` entries,
    forbidden generated/local paths `0`, size `2841093`, SHA256
    `CF7640C3830B5F0EF71145BEEA3E9DCD87C2E8C878C22301A0917AC310FCF7AE`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    `58` entries, size `1349297`, SHA256
    `16216CD00A6604D83E75128D959B357AA2DAB4FB5355B72129A2D6B3C27F2651`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67417`, SHA256
    `79FA9324A4A8EBF5DE4A5E8BA80CC0564952E0362FBD26BCDDEE37BE18300AAB`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `DA8BB43640C8562276ED816E25A448E2C535F9F43FCB71EB624B9CB36C1EF3A3`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `BB793174A53E9546C9B62ADFE8DF469119F0B1E508AD935C03C8B5DA9ABC566D`.
- Current verifier warnings are only the two expected external gaps:
  1. permanent cloud phone readiness is false until real Render HTTPS/cloud APK;
  2. physical Android device smoke is skipped until a connected authorized phone
     is used.
- Remaining work is still external/stateful:
  - Deploy permanent Render HTTPS backend.
  - Run `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`
    with an authorized Android phone connected.
  - Verify `phone_permanent_cloud=True` and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Goal Completion Audit Script

Completed after adding a requirement-by-requirement audit for the original user
goals:

- Added `scripts\audit_project_goal_completion.ps1`.
- The audit reads current evidence from release gate, product acceptance, phone
  readiness, cloud deployment status, desktop package verification and
  submission verifier JSON.
- It writes:
  - `reports\goal_completion_audit_latest.json`;
  - `reports\goal_completion_audit_latest.md`.
- Current audit result:
  - `complete=False`;
  - estimated completion `92%`;
  - estimated remaining `8%`;
  - remaining gaps: `phone_permanent_cloud`, `physical_phone_proof`.
- Internal requirements now audit as true:
  - canonical refactor and legacy isolation;
  - per-section product acceptance;
  - university LaTeX/PDF report;
  - PC product package;
  - local/LAN/emulator phone proof;
  - submission bundle/verifier.
- The audit script is included in the clean source ZIP. The audit report itself
  is kept outside the submission ZIP to avoid self-referential ZIP hash/entry
  count evidence.
- Documentation updated:
  - `README.md`;
  - `RUNBOOK.md`.
- Verification after this change:
  - targeted mobile/render packaging unittest: OK;
  - source bundle reproducibility unittest: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `111/111` OK;
  - product acceptance inside release gate: `93/93` OK;
  - Flutter analyze/tests inside release gate: OK, `11/11`;
  - final `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: `OK=True`, `0` failures, `2` expected warnings.
- Latest artifacts after the audit-script change:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161739298`, SHA256
    `729E56B132AEB60463F7773ED048A7D62C632BB834E97E49A7A696A169103D88`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `239` entries,
    forbidden generated/local paths `0`, size `2845680`, SHA256
    `CF5222120E96CFBFB9D7D78A6E85ECEAA0AEEC043CDDD37D236BABF5F880A243`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T22:06:36+02:00`, size `12549`, SHA256
    `BB50B6386B0E82E8CF5850B36A3FB50BE711356B67F8B612D976E50862CC79EE`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `3232CE4CFA2D97B8584DEBCE3413A89C98501792E3D0CB59EEA375BABF995A13`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6839`, SHA256
    `8D1501D774F761A61E1F5BB61C6FC1EE2B0AD8697D0603620DF4A93B8379C380`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67415`, SHA256
    `1EFF78CB2ADD582A0A0DA938C3454EE2B6BC57D2E2F5C1F6DB7F8972924F356A`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349425`, SHA256
    `052E755B5DDD99C364E788DD3BF814EA201E3BF1EC99E3AB0577851278F0D96F`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `DF1F268B484AAB1806761D1BE2E96D5B3C928C95EF8E92E95D60A265A07E8D7D`.
- Current verifier warnings are only the two expected external gaps:
  1. permanent cloud phone readiness is false until real Render HTTPS/cloud APK;
  2. physical Android device smoke is skipped until a connected authorized phone
     is used.
- Remaining work is still external/stateful:
  - Deploy permanent Render HTTPS backend.
  - Run `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`
    with an authorized Android phone connected.
  - Verify `phone_permanent_cloud=True` and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Strict Final Wrapper Now Requires Goal Audit Complete

Completed after strengthening the final cloud/phone submission path:

- Updated `scripts\finalize_cloud_phone_submission.ps1`.
- The final wrapper now runs two extra final checks after the strict release
  gate, submission bundle, and submission verifier:
  - `Goal completion audit`;
  - `Final cloud phone evidence check`.
- The final evidence check fails if any of these are false:
  - release gate OK;
  - submission verifier OK;
  - `phone_permanent_cloud=True`;
  - real device smoke OK;
  - `PHONE_DEVICE_SCREENSHOT.png` captured;
  - goal completion audit `complete=True`.
- The final report now records:
  - `goal_audit_complete`;
  - `goal_audit_remaining`.
- This closes a proof gap: even if lower-level scripts pass unexpectedly, the
  final wrapper cannot silently report success unless the original project-goal
  audit is complete.
- Verification after this change:
  - PowerShell parser check for `finalize_cloud_phone_submission.ps1`: OK;
  - PowerShell parser check for `audit_project_goal_completion.ps1`: OK;
  - targeted mobile/render packaging unittest: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `111/111` OK;
  - product acceptance inside release gate: `93/93` OK;
  - Flutter analyze/tests inside release gate: OK, `11/11`;
  - final `scripts\make_submission_bundle.ps1`: OK;
  - final `scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated completion `92%`, remaining gaps `phone_permanent_cloud` and
    `physical_phone_proof`.
- Latest artifacts after the strict-final-wrapper change:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161739780`, SHA256
    `E2F1EC9B73FF9B72E821286C6303CD96FA407F6FF1910B3888595F198DB35D2D`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `239` entries,
    forbidden generated/local paths `0`, size `2846186`, SHA256
    `925EFA86DCDA9834EF8931277255095D80F66FDAB233E24997F0BB38EB96D315`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T22:11:15+02:00`, size `12549`, SHA256
    `D58A46CAAA4E18379DF11F5A53DDE28F9D374F64B3ABE932EF4B7EDD5A6DEAFF`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `1684DA0A1DCBA5F5FEE54291E9A967328D3904B9D05C236CFAAED675ED25946F`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6839`, SHA256
    `13F06A21373E6B12AD45EE028BF7C0EA5BDDDC3BBCF226BE834D31E7EAAEC12E`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67417`, SHA256
    `A1081376BE4AC6FD49FEF7AF142FBCF69351A8E3CC5778DD6F155FAB8ED9FAE3`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349425`, SHA256
    `052E755B5DDD99C364E788DD3BF814EA201E3BF1EC99E3AB0577851278F0D96F`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `7CF486ADD9CCD4E0FA91887BF5638306B5495E55A3625C68505D62670AE824B2`.
- Current verifier warnings are still only the two expected external gaps:
  1. permanent cloud phone readiness is false until real Render HTTPS/cloud APK;
  2. physical Android device smoke is skipped until a connected authorized phone
     is used.
- Remaining work is still external/stateful:
  - Deploy permanent Render HTTPS backend.
  - Run `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`
    with an authorized Android phone connected.
  - Verify `goal_completion_audit_latest.json` has `complete=True`,
    `phone_permanent_cloud=True`, and captured `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Final External Preflight Added

Completed after adding an explicit preflight for the two remaining external
requirements:

- Added `scripts\check_final_external_prereqs.ps1`.
- The preflight checks:
  - permanent Render URL policy through `Assert-PermanentCloudApiUrl`;
  - Render `/health`;
  - Render `/ready`;
  - fake-claim `/factcheck` probe;
  - ADB availability;
  - authorized USB Android device selection;
  - current goal-audit status;
  - important final artifacts.
- It writes:
  - `reports\final_external_preflight_latest.json`;
  - `reports\final_external_preflight_latest.md`.
- It supports `-RequireReady`; without that flag it reports missing external
  items but exits successfully so it can be used as a diagnostic.
- `scripts\finalize_cloud_phone_submission.ps1` now runs this preflight first
  as `Final external preflight` with `-RequireReady`, so bad/missing Render URL
  or missing authorized phone fails early before the long strict release gate.
- Documentation updated:
  - `README.md`;
  - `RUNBOOK.md`.
- The clean source ZIP now includes both:
  - `scripts\audit_project_goal_completion.ps1`;
  - `scripts\check_final_external_prereqs.ps1`.
- Verification after this change:
  - PowerShell parser check for final/preflight/source/verifier scripts: OK;
  - standalone `scripts\check_final_external_prereqs.ps1`: OK diagnostic run;
  - targeted mobile/render packaging unittest: OK;
  - source bundle reproducibility unittest: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `111/111` OK;
  - product acceptance inside release gate: `93/93` OK;
  - Flutter analyze/tests inside release gate: OK, `11/11`;
  - final `scripts\make_submission_bundle.ps1`: OK;
  - final `scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated completion `92%`, remaining gaps `phone_permanent_cloud` and
    `physical_phone_proof`;
  - final preflight diagnostic:
    `ready_to_run_finalizer=False`, missing `real public HTTPS Render API URL`
    and `authorized USB Android device`.
- Latest artifacts after the final-external-preflight change:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161744701`, SHA256
    `8EACABCAE20DCAAD00387985C6D76CDC2D16DDE6C2710B684B0D5C823C10E96C`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `240` entries,
    forbidden generated/local paths `0`, size `2850546`, SHA256
    `DCFF9F5A9EAB4CCABC903D47625A4E5C8E61612891A5831B7FC3B93A0DB4E025`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T22:17:28+02:00`, size `12548`, SHA256
    `003499735DE8C5AE25A63BB384B42D8B70EC45A830D976A9AE6503B9275AA004`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `F5D7529F6BC84F1A1F811224A53DF18636737030569CB01759980E4AAA0BBEC1`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6839`, SHA256
    `93C5030B75F6A5D90AE97B23E95C301C0F0290EC4C5C7B8B9DEDFBD270B377B5`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4081`, SHA256
    `858C30FC27DE86FE3F72DC4BA0445B18AD5C71484791CD16294CDC91020E2908`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67417`, SHA256
    `FEF22F881A1577603445213A7912AF147FA5854584EE7F46FD771D31A91352F8`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349545`, SHA256
    `5688789024A515F735CC1033678DED10FAE115A7569F211FF14C6A4755E993AF`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, size `981`,
    SHA256
    `A43B0728AF199CBDB24CD2E56A4FA00C7A041ECF602D85153B6CBD27849A261C`.
- Current verifier warnings are still only the two expected external gaps:
  1. permanent cloud phone readiness is false until real Render HTTPS/cloud APK;
  2. physical Android device smoke is skipped until a connected authorized phone
     is used.
- Remaining work is still external/stateful:
  - Deploy permanent Render HTTPS backend.
  - Connect and authorize a real Android phone over USB.
  - Run `scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady`.
  - Run `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`.
  - Verify `goal_completion_audit_latest.json` has `complete=True`,
    `phone_permanent_cloud=True`, and captured `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Physical Android Proof Rejects Emulators

Completed after tightening the final phone proof so an Android emulator cannot
count as the final real-phone deliverable:

- `scripts\smoke_phone_on_device.ps1` now supports `-RequirePhysicalDevice`.
- Device smoke records:
  - `require_physical_device`;
  - `selected_device_is_emulator`;
  - per-device `is_emulator`.
- Emulator detection checks:
  - device ids such as `emulator-*` and `localhost:*`;
  - `adb shell getprop ro.kernel.qemu`;
  - `adb shell getprop ro.hardware` values like `ranchu`, `goldfish`, `qemu`.
- `scripts\check_final_external_prereqs.ps1` now requires an authorized
  physical USB Android device by default.
- `-AllowEmulator` exists only for diagnostic/debug preflight runs; final
  readiness keeps `allow_emulator=False`.
- `scripts\run_release_gate.ps1` now accepts `-RequirePhysicalPhoneDevice` and
  forwards `-RequirePhysicalDevice` into the phone device smoke step.
- `scripts\finalize_cloud_phone_submission.ps1` now passes
  `-RequirePhysicalPhoneDevice`, so the strict final wrapper requires a real
  phone proof.
- `scripts\audit_project_goal_completion.ps1` now requires device smoke with
  `require_physical_device=True` and `selected_device_is_emulator=False` before
  considering `physical_phone_proof` complete.
- `scripts\verify_submission_bundle.ps1` now fails if an OK
  `PHONE_DEVICE_SMOKE.json` was not run with `-RequirePhysicalDevice`, is
  missing `selected_device_is_emulator`, or selected an emulator.
- Tests in `tests\test_factcheck_core.py` now lock these physical-device fields,
  strict final wrapper wiring, preflight wording, and verifier failures.
- Verification after this physical-phone hardening:
  - PowerShell parser check for all touched scripts: OK;
  - standalone `scripts\check_final_external_prereqs.ps1`: OK diagnostic run,
    `ready_to_run_finalizer=False`;
  - targeted mobile/render packaging unittest: OK;
  - source bundle reproducibility unittest: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `111/111` OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - `scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated completion `92%`, estimated remaining `8%`, remaining gaps
    `phone_permanent_cloud` and `physical_phone_proof`;
  - final preflight diagnostic: `ready_to_run_finalizer=False`, missing
    `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after the physical-phone hardening:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161746026`, SHA256
    `49C075949771D29A0F137A5F54CFE758564F123D31CDCF9EF4CE1C76C1D9B1FF`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `240` entries,
    forbidden generated/local paths `0`, includes
    `scripts\audit_project_goal_completion.ps1` and
    `scripts\check_final_external_prereqs.ps1`, size `2851755`, SHA256
    `C0F329A766536C1DFFC21DFD38E0AD8C031B164DFE66536DC8A552852A44DFBC`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `1004`, SHA256
    `1EF385B1A9F12FFB02BB7B7FACCAD23C4838AFB015E32AEF9FFEE0B810EF1A1C`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T22:24:17.6733833+02:00`, size `12592`, SHA256
    `FEED0EC69070521587799E3CF1DFE0A9480A8A9E2588478AE3D652FC7499D32B`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `033B0C6EB044C6A2145BC13274B071EAA09041B2C0F8FD37C0C1404550902BCD`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6943`, SHA256
    `2ECE2EC8E9CB3C8C8338DA78261FFD049B434EF7BE396770F55C8DD197896B36`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4265`, SHA256
    `7AC33AFE18567C04E5C50B7CB7C7CECC3CF1709E2FA23529A1B63E7F09F6FD7D`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67415`, SHA256
    `66F3583795B8905837F21B40773476739B8A3C6999ADEE9C2769F3C66250645E`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349545`, SHA256
    `5688789024A515F735CC1033678DED10FAE115A7569F211FF14C6A4755E993AF`.
- Current verifier warnings are exactly the expected external gaps:
  1. permanent cloud phone readiness is false until a real Render HTTPS URL and
     cloud APK are verified;
  2. phone device smoke is skipped until
     `-RequireDevice -RequirePhysicalDevice` is run on a connected Android
     phone.
- Remaining work is still external/stateful:
  - deploy permanent Render HTTPS backend;
  - connect and authorize a real Android phone over USB;
  - run
    `scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady`;
  - run
    `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`;
  - verify `goal_completion_audit_latest.json` has `complete=True`,
    `phone_permanent_cloud=True`, `physical_phone_proof=True`, and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Final Docs Match Physical-Phone Enforcement

Completed after noticing that some user-facing docs still described the final
phone proof with older, less explicit wording:

- Updated `README.md`, `RUNBOOK.md`, and `docs\mobile_flutter_render.md` so the
  final real-phone path explicitly says:
  - use `-RequireDevice -RequirePhysicalDevice` for direct device smoke;
  - the strict final wrapper runs the gate with
    `-RequirePhoneDevice -RequirePhysicalPhoneDevice`;
  - emulator evidence is useful platform evidence but cannot replace the
    physical Android final proof.
- Updated `docs\report\verity_lens_report.tex` with the same physical-device
  wording and rebuilt `docs\report\verity_lens_report.pdf`.
- Updated `scripts\audit_project_goal_completion.ps1` gap text so it tells the
  next operator to connect an authorized physical Android phone and run the
  finalizer that invokes both strict phone flags.
- Updated `tests\test_factcheck_core.py` so the LaTeX report test locks the
  physical-phone wording and the current clean source ZIP count.
- Verification after this documentation/evidence sync:
  - parser check for `scripts\audit_project_goal_completion.ps1`: OK;
  - targeted LaTeX report structure unittest: OK;
  - targeted mobile/render packaging unittest: OK;
  - source bundle reproducibility unittest: OK;
  - `scripts\build_report.ps1`: OK, PDF rebuilt;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `111/111` OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - final `scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated completion `92%`, estimated remaining `8%`, remaining gaps
    `phone_permanent_cloud` and `physical_phone_proof`;
  - final `scripts\check_final_external_prereqs.ps1`: diagnostic OK,
    `ready_to_run_finalizer=False`, missing `real public HTTPS Render API URL`
    and `authorized physical USB Android device`.
- Latest artifacts after the docs/evidence sync:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161746902`, SHA256
    `53FC42B3D73F6DBF366EF42B9F9E16CB81B91C6015FBF4DEF32879B6A0F09A1D`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `240` entries,
    forbidden generated/local paths `0`, includes
    `scripts\audit_project_goal_completion.ps1` and
    `scripts\check_final_external_prereqs.ps1`, size `2852081`, SHA256
    `D90B7483D43B576C5B85F67232B2227D26C5B6415F7C9B330E9CF52C60553329`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `4`, failures `0`, size `1266`, SHA256
    `9A81927C406468E0B61B0E76908AC6368F017E07D49CBEFD383BA998CB8AD94F`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T22:30:57.9092014+02:00`, size `12593`, SHA256
    `743FF893FCF648B24774DE3F238CA857F60FA392D85A164268AAECA31ABA9FD9`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `912E310448EE1575DEAB4F65ECDBBF0CEC3FB05514418F1CCB4280B07F4A992C`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6987`, SHA256
    `16E95A2B191932A2CB07B1FA0025D71B34DE928E6A147E90203C3CC747FA0A7A`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4266`, SHA256
    `4B370BA7F06F74786AF0EB68981F0C39E1B384B5CA0D207523366F59374CCEEB`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67511`, SHA256
    `38A607560ECE2ECBB6C1FC46A8FB68E38362CCCC43B60CED43E4F2CA934ADDF8`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349641`, SHA256
    `9C472BDA13BFB70ADDD0D6CA8999673F0EDD9CD5084968F9E35A2E28BDCF03DF`.
- Current verifier warnings:
  1. temporary tunnel phone readiness is false;
  2. temporary tunnel demo readiness is false;
  3. permanent cloud phone readiness is false until a real Render HTTPS URL and
     cloud APK are verified;
  4. phone device smoke is skipped until
     `-RequireDevice -RequirePhysicalDevice` is run on a connected Android
     phone.
- Remaining work is still external/stateful:
  - deploy permanent Render HTTPS backend;
  - connect and authorize a real Android phone over USB;
  - run
    `scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady`;
  - run
    `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`;
  - verify `goal_completion_audit_latest.json` has `complete=True`,
    `phone_permanent_cloud=True`, `physical_phone_proof=True`, and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Temporary Tunnel Readiness Status Fixed And Bundle Refreshed

Completed after the verifier briefly showed extra temporary-tunnel warnings:

- `scripts\check_phone_readiness.ps1` now records `last_checked_at` for the
  tunnel probe and changes stale/broken tunnel state to `active_probe_failed`
  when `/health`, `/ready`, or `/factcheck` fails.
- `scripts\start_public_api_tunnel.ps1` now writes explicit
  `provider = cloudflare_quick_tunnel` and status metadata, and updates the
  tunnel info to `active_verified` only after public probes pass.
- `tests\test_factcheck_core.py` now locks the new readiness status strings.
- Refreshed `outputs\phone_download\PHONE_READINESS.json`; current temporary
  tunnel is `active_verified`, `verified=True`, fake probe `fake / 0.78`.
- Verification after this status fix:
  - PowerShell parser check for `check_phone_readiness.ps1` and
    `start_public_api_tunnel.ps1`: OK;
  - targeted mobile/render packaging unittest: OK;
  - source bundle reproducibility unittest: OK;
  - standalone `scripts\check_phone_readiness.ps1`: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `111/111` OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - final `scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated completion `92%`, estimated remaining `8%`, remaining gaps
    `phone_permanent_cloud` and `physical_phone_proof`;
  - final `scripts\check_final_external_prereqs.ps1`: diagnostic OK,
    `ready_to_run_finalizer=False`, missing `real public HTTPS Render API URL`
    and `authorized physical USB Android device`.
- Latest artifacts after the tunnel-status fix:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161746975`, SHA256
    `9C5DC906C3E9ABE2399B10887E7A9405F420DC0BBD7EA34D28BBA3DE8A319FDA`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `240` entries,
    forbidden generated/local paths `0`, includes
    `scripts\audit_project_goal_completion.ps1` and
    `scripts\check_final_external_prereqs.ps1`, size `2852215`, SHA256
    `EF0093EE299776006A54ED82D3FF8F5CED8AA1E2107BB08A193C0AE96F7F699E`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `1004`, SHA256
    `C31716F432B03891AF97ACBFE07BE110F0CEC8C6F9622B461FFF49F6514870EE`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T22:35:43.673735+02:00`, size `12590`, SHA256
    `3508D89C26A4097F2DFB29FF8777987F009AA91980823EDC8214F79D484F5CC9`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `52D0DDF6D0A1317A05BF6A987A1B80D6F97ECE096261D29BD8DE928BA288C63F`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6987`, SHA256
    `7482672E23A26FF72278C8A15A13D8ED11325F5DE44B7F878F0A64AA240B7C2A`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4265`, SHA256
    `862A40DD613F66869FD30B9CE18785EC2F2A7CC512D7323FA3CB06AF58AFB0DC`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67511`, SHA256
    `CEF8EBD50D45A10C51065BE1D1CEAA93439AC2D60DFE1D7AF709BDAD597DCF14`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349641`, SHA256
    `9C472BDA13BFB70ADDD0D6CA8999673F0EDD9CD5084968F9E35A2E28BDCF03DF`.
- Current verifier warnings are back to only the two true external gaps:
  1. permanent cloud phone readiness is false until a real Render HTTPS URL and
     cloud APK are verified;
  2. phone device smoke is skipped until
     `-RequireDevice -RequirePhysicalDevice` is run on a connected Android
     phone.
- Remaining work is still external/stateful:
  - deploy permanent Render HTTPS backend;
  - connect and authorize a real Android phone over USB;
  - run
    `scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady`;
  - run
    `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`;
  - verify `goal_completion_audit_latest.json` has `complete=True`,
    `phone_permanent_cloud=True`, `physical_phone_proof=True`, and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Final Preflight Command Preserves Custom Cloud APK Name

Completed after checking the current external blockers and finalizer path:

- `scripts\check_final_external_prereqs.ps1` already preserved
  `-PhoneDeviceId` in the printed finalizer command.
- Fixed the remaining edge case: when the preflight is run with a non-default
  `-CloudApkOutputName`, its `finalizer_command` now includes
  `-CloudApkOutputName <name>` too.
- `tests\test_factcheck_core.py` now locks both `-CloudApkOutputName` and
  `-PhoneDeviceId` in the final external preflight script.
- This makes the preflight report a reproducible handoff command even when
  multiple APK names or a specific Android device ID are used.
- Verification after this preflight-command fix:
  - parser check for `scripts\check_final_external_prereqs.ps1`: OK;
  - standalone `scripts\check_final_external_prereqs.ps1`: OK diagnostic run,
    `ready_to_run_finalizer=False`;
  - targeted mobile/render packaging unittest: OK;
  - source bundle reproducibility unittest: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `111/111` OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - final `scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated completion `92%`, estimated remaining `8%`, remaining gaps
    `phone_permanent_cloud` and `physical_phone_proof`;
  - final `scripts\check_final_external_prereqs.ps1`: diagnostic OK,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after the preflight-command fix:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161747007`, SHA256
    `467D5BA849DE3D7682A7C2630BA7E3386AF85A43291D0532F442D05E2527B06A`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `240` entries,
    forbidden generated/local paths `0`, includes
    `scripts\audit_project_goal_completion.ps1` and
    `scripts\check_final_external_prereqs.ps1`, size `2852249`, SHA256
    `862EF49F217C33D214EF142FE2C64F747F446F679A3BB9C0D911239DE6427429`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `1004`, SHA256
    `EFF26BC907CBC5A7766C8AE49D8267D561681DEC169D1ADC49EEB8526E50486B`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T22:39:49.340403+02:00`, size `12592`, SHA256
    `EDEFE612B494702609236BBF10B5D8C23C218A1299FBC99B494E41413438F293`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `B05B371986BC8481680E74017C857D1595CFFAD1F8D691D47F675FEA710A634B`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6987`, SHA256
    `C2418A3401E61ED4EC57FFC8A09F30B4B13C5126A68E832A7579A25C4FC71941`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4265`, SHA256
    `C5575B66D430FC4A6572AC5A6AB4B9F3AD791F9C53D8C3E1842EA3AEBCDDD83C`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67512`, SHA256
    `EC10144B86EFE05B8702E18518BC73F999BA7C425419D92DA0F07A81C3108272`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349641`, SHA256
    `9C472BDA13BFB70ADDD0D6CA8999673F0EDD9CD5084968F9E35A2E28BDCF03DF`.
- Current readiness/verifier status:
  - temporary tunnel: `active_verified`, fake probe `fake / 0.78`;
  - submission verifier warnings are only:
    1. permanent cloud phone readiness is false until a real Render HTTPS URL
       and cloud APK are verified;
    2. phone device smoke is skipped until
       `-RequireDevice -RequirePhysicalDevice` is run on a connected Android
       phone.
- Remaining work is still external/stateful:
  - deploy permanent Render HTTPS backend;
  - connect and authorize a real Android phone over USB;
  - run
    `scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady`;
  - run
    `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`;
  - verify `goal_completion_audit_latest.json` has `complete=True`,
    `phone_permanent_cloud=True`, `physical_phone_proof=True`, and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: APK Output Name Path Safety Hardened

Completed after auditing the final cloud APK naming path:

- Added `Assert-FileNameOnly` and `Assert-ApkOutputName` to
  `scripts\path_safety.ps1`.
- APK output names must now be plain file names ending in `.apk`; absolute
  paths, `..\`, nested paths, empty names, and non-APK extensions are rejected.
- Connected the validator in:
  - `apps\fake_news_detector_flutter\tool\build_internet_apk.ps1`;
  - `scripts\build_phone_for_cloud.ps1`;
  - `scripts\finalize_cloud_deploy.ps1`;
  - `scripts\check_final_external_prereqs.ps1`;
  - `scripts\finalize_cloud_phone_submission.ps1`;
  - `scripts\run_release_gate.ps1`;
  - `scripts\start_localtunnel_api.ps1`;
  - `scripts\write_cloud_deployment_status.ps1`.
- Added regression coverage in `tests\test_factcheck_core.py`:
  `test_apk_output_name_policy_rejects_paths`.
- Verification after this hardening:
  - PowerShell parser check for all touched scripts: OK;
  - `test_apk_output_name_policy_rejects_paths`: OK;
  - targeted mobile/render packaging unittest: OK;
  - source bundle reproducibility unittest: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `112/112` OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - final `scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated completion `92%`, estimated remaining `8%`, remaining gaps
    `phone_permanent_cloud` and `physical_phone_proof`;
  - final `scripts\check_final_external_prereqs.ps1`: diagnostic OK,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after APK output-name hardening:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161747755`, SHA256
    `C7424322B5F9AF6F843914E4F27B03EC687BBB2FB01CBC129CE9678BBBB7242D`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `240` entries,
    forbidden generated/local paths `0`, includes
    `scripts\audit_project_goal_completion.ps1` and
    `scripts\check_final_external_prereqs.ps1`, size `2852955`, SHA256
    `D566AC7808D6847A9B08D4F007CA8BECAC77114FAA079A870EABA7F33107A4C4`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `1004`, SHA256
    `24E0FCA45A17B744B12F6E6C9008BBBCE5FB8265E3647E3D26CE63BB1E01F8F7`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T22:46:15.2942266+02:00`, size `12591`, SHA256
    `8A1597974C8BC2EC05C2142B21C875E0A78377694DF974E53771A7E2BB1A3CDA`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `B8F04EA479240CB1B9554F4884633649CBA948EAC981E616065BB7DEB82E42E6`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6987`, SHA256
    `0CCAA52DE090F431AB0A9E68520A05E00928A961B3A71D95FC683083AE7FB1F9`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4265`, SHA256
    `D5AB00394EE5BE11E96D1BD46C4C072A1F86F909731FC64C65691020CABFCD07`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67511`, SHA256
    `C0688235BC76E1DF3DEC9B610A5400022D28CCE2A4D351DC39F7EEAC67356714`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349641`, SHA256
    `9C472BDA13BFB70ADDD0D6CA8999673F0EDD9CD5084968F9E35A2E28BDCF03DF`.
- Current readiness/verifier status:
  - temporary tunnel: `active_verified`, fake probe `fake / 0.78`;
  - submission verifier warnings are only:
    1. permanent cloud phone readiness is false until a real Render HTTPS URL
       and cloud APK are verified;
    2. phone device smoke is skipped until
       `-RequireDevice -RequirePhysicalDevice` is run on a connected Android
       phone.
- Remaining work is still external/stateful:
  - deploy permanent Render HTTPS backend;
  - connect and authorize a real Android phone over USB;
  - run
    `scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady`;
  - run
    `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`;
  - verify `goal_completion_audit_latest.json` has `complete=True`,
    `phone_permanent_cloud=True`, `physical_phone_proof=True`, and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this artifact block has been superseded by the next update
  section.

## Update: LaTeX Report Backend Test Count Synced To 112

Completed after noticing report drift caused by the new APK output-name policy
test:

- Updated `docs\report\verity_lens_report.tex` so the backend row now says
  `112 testów OK`.
- Updated `tests\test_factcheck_core.py` so the university report structure
  test expects `112 testów OK`.
- Rebuilt `docs\report\verity_lens_report.pdf`.
- Verification after the report-count sync:
  - `test_university_latex_report_has_required_structure_and_results`: OK;
  - `test_apk_output_name_policy_rejects_paths`: OK;
  - `scripts\build_report.ps1`: OK;
  - `test_source_bundle_contains_reproducible_source_without_generated_outputs`:
    OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `112/112` OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - final `scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated completion `92%`, estimated remaining `8%`, remaining gaps
    `phone_permanent_cloud` and `physical_phone_proof`;
  - final `scripts\check_final_external_prereqs.ps1`: diagnostic OK,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after report-count sync:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161747835`, SHA256
    `FFC8313E6E8AC017609464C3B6735C50034A156E0DCD51DEC70960CDCF5E2D61`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `240` entries,
    forbidden generated/local paths `0`, includes
    `scripts\audit_project_goal_completion.ps1` and
    `scripts\check_final_external_prereqs.ps1`, size `2852955`, SHA256
    `2A4496E5FAC09C2C5349156B7F08EBCB318A168D3D66E11FE1D1EFB7F8AC485A`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `1004`, SHA256
    `2E6B33FD3E24D465ABEE6D072C0BAFF66CE400773EBFBE85C30594B9421F1D90`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T22:53:11.3378283+02:00`, size `12594`, SHA256
    `C135DE39C32AA12972DDE4C0DAF0A523C410B83F2638287C0A1A9BC6C90FEF43`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `793334D7FF72BCA3B7B93C0FCA44B712074010547F956D90C771FF6F326670C2`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6987`, SHA256
    `C714B447A552A1832BF4FFA746256EC36DE10D5A96DC700F332B3E590A44FD3C`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4265`, SHA256
    `937D1CECBF5D5471C1DF712BE4D52344E8CF32E5FA42F44AC812FFB143CC625D`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67621`, SHA256
    `DCCF54E34FA1438BBDB76D3A1E1D1725C4434B8565AF1559A5FC2DF6035A7522`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349641`, SHA256
    `9C472BDA13BFB70ADDD0D6CA8999673F0EDD9CD5084968F9E35A2E28BDCF03DF`.
- Current readiness/verifier status:
  - temporary tunnel: `active_verified`, fake probe `fake / 0.78`;
  - submission verifier warnings are only:
    1. permanent cloud phone readiness is false until a real Render HTTPS URL
       and cloud APK are verified;
    2. phone device smoke is skipped until
       `-RequireDevice -RequirePhysicalDevice` is run on a connected Android
       phone.
- Remaining work is still external/stateful:
  - deploy permanent Render HTTPS backend;
  - connect and authorize a real Android phone over USB;
  - run
    `scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady`;
  - run
    `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`;
  - verify `goal_completion_audit_latest.json` has `complete=True`,
    `phone_permanent_cloud=True`, `physical_phone_proof=True`, and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this artifact block has been superseded by the next update
  section.

## Update: Final Preflight Command Quoting Hardened

Completed while continuing the remaining external-proof work:

- Hardened `scripts\check_final_external_prereqs.ps1` so the reported
  `finalizer_command` is copy-paste safe:
  - dynamic values are single-quoted and embedded quotes are escaped;
  - custom `-CloudApkOutputName` and `-PhoneDeviceId` are preserved even when
    the Render URL is still a placeholder.
- Added regression coverage in `tests\test_factcheck_core.py`:
  `test_final_external_preflight_quotes_copy_paste_command`.
- Because this added one backend test, synchronized the LaTeX report and report
  structure test from `112 testów OK` to `113 testów OK`.
- Rebuilt `docs\report\verity_lens_report.pdf`.
- Verification after this preflight hardening:
  - PowerShell parser check for `check_final_external_prereqs.ps1`: OK;
  - `test_final_external_preflight_quotes_copy_paste_command`: OK;
  - `test_release_gate_covers_pc_mobile_and_cloud_paths`: OK;
  - `test_university_latex_report_has_required_structure_and_results`: OK;
  - `scripts\build_report.ps1`: OK;
  - `test_source_bundle_contains_reproducible_source_without_generated_outputs`:
    OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `113/113` OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - final `scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated completion `92%`, estimated remaining `8%`, remaining gaps
    `phone_permanent_cloud` and `physical_phone_proof`;
  - final `scripts\check_final_external_prereqs.ps1`: diagnostic OK,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after preflight command quoting:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161748197`, SHA256
    `6ED71A331EE93DAF5AB3BF5FF6432770E2BFCBF399E672BFBC18E36AAAB9F09A`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `240` entries,
    forbidden generated/local paths `0`, includes
    `scripts\audit_project_goal_completion.ps1` and
    `scripts\check_final_external_prereqs.ps1`, size `2853370`, SHA256
    `6E41A55A4AA4C49BEDB35327DC18519D2E912488AA8937986536849C88D85583`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `1004`, SHA256
    `54FC52448AAE8D01A23ACFA0F2839D1A0FCEA903AD8D8EA34405556ED7375752`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T23:00:20.1872841+02:00`, size `12593`, SHA256
    `AD683573D77F8A0A0E83FD68AFE01545CCA4B51E2B126B675A0BEF49C9B74205`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `428EF1FF48ECE263DF0F7821EDFE00CB00CD88BD485AC13BB43FD5EAAE68A6AC`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6987`, SHA256
    `962CD31D6C6104B3A6039BD6896101308125B0B0D3F48A5ACB04FAE47F4CE038`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4267`, SHA256
    `D038E2D4E0791922BAB760640A4EA14FAEA959E8ADD627775E7D6BD6BC649AEE`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67510`, SHA256
    `3CDB6E5A83AF4E24F8D31957027FC8571C3BE179264D49D88BB387DEDAC988C9`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1349641`, SHA256
    `9C472BDA13BFB70ADDD0D6CA8999673F0EDD9CD5084968F9E35A2E28BDCF03DF`.
- Current readiness/verifier status:
  - temporary tunnel: `active_verified`, fake probe `fake / 0.78`;
  - finalizer command in preflight:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`;
  - submission verifier warnings are only:
    1. permanent cloud phone readiness is false until a real Render HTTPS URL
       and cloud APK are verified;
    2. phone device smoke is skipped until
       `-RequireDevice -RequirePhysicalDevice` is run on a connected Android
       phone.
- Remaining work is still external/stateful:
  - deploy permanent Render HTTPS backend;
  - connect and authorize a real Android phone over USB;
  - run
    `scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady`;
  - run
    `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`;
  - verify `goal_completion_audit_latest.json` has `complete=True`,
    `phone_permanent_cloud=True`, `physical_phone_proof=True`, and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this artifact block has been superseded by the next update
  section.

## Update: Child PowerShell And Flutter Source Stamp Stabilized

Completed after hardening the final orchestration path:

- Added `Get-ChildPowerShellCommand` to `scripts\path_safety.ps1`.
- Updated these important orchestration scripts to use the current/compatible
  child PowerShell executable instead of hardcoded `powershell`:
  - `scripts\run_release_gate.ps1`;
  - `scripts\finalize_cloud_phone_submission.ps1`;
  - `scripts\make_submission_bundle.ps1`;
  - `scripts\finalize_cloud_deploy.ps1`.
- Fixed `apps\fake_news_detector_flutter\tool\flutter_source_stamp.ps1` to use
  ordinal deterministic sorting via `SortedSet[string]` and
  `StringComparer.Ordinal`. This removed a hidden mismatch where Windows
  PowerShell and PowerShell 7 produced different Flutter source SHA256 values
  for the same files.
- Rebuilt:
  - `outputs\phone_download\VerityLens-internet.apk`;
  - `outputs\phone_download\VerityLens-lan.apk`.
- Refreshed `PHONE_EMULATOR_SMOKE.json` so emulator proof matches the rebuilt
  internet APK SHA256.
- Verification after this stabilization:
  - PowerShell parser check for touched orchestration scripts: OK;
  - `test_flutter_mobile_project_and_render_files_exist`: OK;
  - `test_release_gate_covers_pc_mobile_and_cloud_paths`: OK;
  - child PowerShell helper resolved `pwsh 7.6.1` and can access
    `Get-FileHash`: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - backend tests inside release gate: `113/113` OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - internet APK verification: OK, Flutter source stamp matches current source;
  - LAN APK verification: OK, Flutter source stamp matches current source;
  - emulator smoke: OK, nested APK SHA256 matches rebuilt internet APK;
  - `scripts\make_submission_bundle.ps1`: OK;
  - final `scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated completion `92%`, estimated remaining `8%`, remaining gaps
    `phone_permanent_cloud` and `physical_phone_proof`;
  - final `scripts\check_final_external_prereqs.ps1`: diagnostic OK,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after child PowerShell/stamp stabilization:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, `42`
    entries, size `161683070`, SHA256
    `3AE19209FA7839FE10317246BB35BA6659B14AC62C3E76D75ABEAB85E49B7A45`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, `240` entries,
    forbidden generated/local paths `0`, includes
    `scripts\audit_project_goal_completion.ps1`,
    `scripts\check_final_external_prereqs.ps1`, and
    `apps\fake_news_detector_flutter\tool\flutter_source_stamp.ps1`, size
    `2836756`, SHA256
    `E3D4E0F71F9277D98278B68C5D01A5D044BA75C64300D220D01D64009DF50227`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `4`, failures `0`, size `1019`, SHA256
    `7FB5E56B2DFC4F5ED5F98EC582372CF1B6F26ACA1CE2A9AB58F8FDE104AE01F5`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T23:12:46.2568706+02:00`, size `12588`, SHA256
    `6130A24163F3E29B487433DD77D6E3E3276D16F4A6237ABBE1CE6FC5E7391F7E`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `FDFE1EADE463FDF6E2BC5734B972CC8A4A7676346D174D2C0160AA5EFA6EEB8D`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6987`, SHA256
    `3E30472F518264A381223AE9DB1C6E929EF5FB40006598D25C73E8C5CF94C16B`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4268`, SHA256
    `7448175650DA9527F7D57DEE4D46C24181A9713165284713BF97A2FE8BE6C8A9`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67510`, SHA256
    `B300CB8A43AB27DBC7DDC4EAE477F4E917B70F91F0EC41793D8858FA6C79106A`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331075`, SHA256
    `C48C90A1BE306B0BD195588F0D195BDBC5EC4E1E3073D960E2EB914C6BEF284A`;
  - internet APK: `outputs\phone_download\VerityLens-internet.apk`, size
    `49843593`, SHA256
    `D2BD815C0CF934ACF1BC3D7A51662B43B0F02F177ABCA648DC90669B0D55AB87`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `457CC8F6FEFFF88E079860B1F52CBD416A6B1AEF9FBC8BECF97E65D1E7E3F4B1`;
  - emulator smoke JSON: `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`,
    size `14883`, SHA256
    `7DF0FAE045E277FB95E9984AAD302DF2C8018C2F029AC0928AC3989932A52B74`.
- Current readiness/verifier status:
  - submission verifier warnings are now `4`:
    1. release gate temporary tunnel readiness is false because the temporary
       LocalTunnel probe currently returns 404 on one endpoint;
    2. standalone temporary tunnel readiness is false for the same temporary
       demo reason;
    3. permanent cloud phone readiness is false until a real Render HTTPS URL
       and cloud APK are verified;
    4. phone device smoke is skipped until
       `-RequireDevice -RequirePhysicalDevice` is run on a connected Android
       phone.
  - internet APK verification itself is still OK for
    `https://slick-rules-deny.loca.lt`, and LAN APK verification is OK for
    `http://192.168.1.16:8001`;
  - finalizer command in preflight:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`.
- Remaining work is still external/stateful:
  - deploy permanent Render HTTPS backend;
  - connect and authorize a real Android phone over USB;
  - run
    `scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady`;
  - run
    `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`;
  - verify `goal_completion_audit_latest.json` has `complete=True`,
    `phone_permanent_cloud=True`, `physical_phone_proof=True`, and captured
    `PHONE_DEVICE_SCREENSHOT.png`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Temporary Tunnel Restored And Status Stamp Fixed

- User asked how much remains. Current answer from the latest goal audit:
  `92%` complete, `8%` remaining.
- Fixed the last hardcoded child PowerShell calls in temporary tunnel helpers:
  - `scripts\start_public_api_tunnel.ps1` now dots `path_safety.ps1`, uses
    `$PowerShell = Get-ChildPowerShellCommand`, and launches APK builds through
    that resolved executable.
  - `scripts\start_localtunnel_api.ps1` now does the same for its APK build.
- Fixed tunnel-generated `PHONE_BUILD_STATUS.md` so it preserves APK freshness
  evidence:
  - both temporary tunnel scripts now include `Flutter source SHA256` and
    `Flutter source files` from the APK sidecar stamp.
  - This matters because `verify_phone_apk.ps1` requires the status file to
    match the current Flutter source stamp.
- Restored the temporary LocalTunnel phone demo:
  - current temporary public API:
    `https://empty-trains-reply.loca.lt`;
  - `outputs\public_api_tunnel_info.json`: `active_verified`;
  - health `ok`, ready `ready`, fake probe `fake / 0.78`.
- Rebuilt the internet APK against that current temporary URL:
  - `outputs\phone_download\VerityLens-internet.apk`;
  - SHA256
    `3C24FC4C1425C702F7AEA37BB0456B3AD17F51B6F357EA17C1FE712F1B8AA31B`.
- Re-ran and passed:
  - targeted structural test
    `test_flutter_mobile_project_and_render_files_exist`: OK;
  - full backend suite: `113/113` OK;
  - `scripts\verify_phone_apk.ps1`: OK;
  - `scripts\smoke_phone_emulator.ps1`: OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - `scripts\make_submission_bundle.ps1`: OK;
  - `scripts\audit_project_goal_completion.ps1`: still not complete, remaining
    `phone_permanent_cloud` and `physical_phone_proof`;
  - `scripts\check_final_external_prereqs.ps1`: diagnostic OK, missing
    `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Current `outputs\phone_download\phone_readiness.json`:
  - `pc_desktop=True`;
  - `phone_same_wifi=True`;
  - `render_deploy_package=True`;
  - `phone_install_download=True`;
  - `phone_temporary_tunnel=True`;
  - `phone_emulator_smoke=True`;
  - `phone_permanent_cloud=False`;
  - `phone_device_smoke=False`.
- Current submission verifier is OK with only `2` warnings:
  1. permanent cloud phone readiness is false until a real Render HTTPS URL and
     cloud APK are verified;
  2. physical phone device smoke is skipped until a real USB Android device is
     connected and required.
- Latest artifacts after temporary tunnel restoration:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161676468`, SHA256
    `A9FB181FAC787B95D31625F0FD5551658AE6499E5617A8EED149715DC2634EFF`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2837292`,
    SHA256
    `58BD8E6949D92D86D4F9DDF433CE36F866EDFCB134400C979053067FFAE59FF7`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `791`, SHA256
    `29F86637216AD6F5178B7CF5FFA03F0AF0D23F68D9A1C7748E720C4C65E04EFE`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12590`,
    SHA256
    `4FE62A7CE38D254DACDFD75D01093E8DE8D6C08E8A4A46CC727FC196AD1D2B10`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `40A7DBB1084A7742EB44804D4B2C9D934B6BAE98E0496856FFAEAF58B8CCEA88`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `6986`, SHA256
    `8994C72C27234E371844F3F87D7498A4E50F12AB1BFBAD9016C3047111E9FFE7`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4267`, SHA256
    `A67B70C9A152C4FFC9F2693DDE875A479A5E12A5B9FB440270090FD1824C8ED7`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67510`, SHA256
    `E892DCDEF94FFDD6CCCC349580A3BDB54438B9A178393C2118FA50446B62D19F`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331075`, SHA256
    `C48C90A1BE306B0BD195588F0D195BDBC5EC4E1E3073D960E2EB914C6BEF284A`;
  - internet APK: `outputs\phone_download\VerityLens-internet.apk`, size
    `49843593`, SHA256
    `3C24FC4C1425C702F7AEA37BB0456B3AD17F51B6F357EA17C1FE712F1B8AA31B`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `457CC8F6FEFFF88E079860B1F52CBD416A6B1AEF9FBC8BECF97E65D1E7E3F4B1`;
  - APK verification JSON: `outputs\phone_download\PHONE_APK_VERIFICATION.json`,
    size `2161`, SHA256
    `8F44C4EA3E7EB24B0298C0715A774C41FDF930C987C007446A456228CC800C32`;
  - emulator smoke JSON: `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`,
    size `14883`, SHA256
    `C605AB4EC29F6AAFF58A3B78F581E3803A26357ED87023CD9DFB56B2E3FE96A4`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24215`, SHA256
    `BE0DBF1388086D9A62CD57C1B52283EC97B7AD348D196067758CCE26F294D21A`;
  - tunnel info JSON: `outputs\public_api_tunnel_info.json`, size `485`,
    SHA256
    `59A3E1577DCFB166DE34B9B335E6A28EAE7D075949E599748BE68552FC1FA652`.
- Remaining `8%` is still genuinely external/stateful:
  - deploy a permanent Render HTTPS backend;
  - build and verify `VerityLens-cloud.apk` against that permanent URL;
  - connect and authorize a physical Android phone over USB;
  - run finalizer:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`;
  - verify `goal_completion_audit_latest.json` reaches `complete=True`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Honest Physical Phone Audit And Tunnel Retry Hardening

- Current goal status is still `92%` complete / `8%` remaining.
- Tightened `scripts\audit_project_goal_completion.ps1` so physical-phone
  evidence is honest:
  - `Selected device is physical` now requires a real non-empty
    `selected_device_id`;
  - current physical evidence is correctly:
    `Selected device id: missing` and `Selected device is physical: False`.
- Hardened `scripts\check_phone_readiness.ps1` against transient LocalTunnel
  failures:
  - `Test-HttpJson` now supports attempts and retry delay;
  - new `Test-FactcheckProbe` retries `/factcheck`;
  - cloud and temporary tunnel readiness now retry `/health`, `/ready`, and
    `/factcheck` before marking `active_probe_failed`.
- This fixed the recurring temporary tunnel false-negative where LocalTunnel
  occasionally returned one `404` on `/ready` while the APK verifier still saw
  the API as OK.
- Verification after these changes:
  - targeted structural test
    `test_flutter_mobile_project_and_render_files_exist`: OK;
  - full backend suite: `113/113` OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - release gate phone readiness summary:
    `phone_temporary_tunnel=True`, `phone_emulator_smoke=True`,
    `phone_permanent_cloud=False`, `phone_device_smoke=False`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: OK, failures `0`, warnings `2`;
  - `scripts\audit_project_goal_completion.ps1`: not complete, remaining
    `phone_permanent_cloud` and `physical_phone_proof`;
  - `scripts\check_final_external_prereqs.ps1`: not ready to run finalizer,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Current temporary public API is still:
  `https://empty-trains-reply.loca.lt`.
- Current `outputs\phone_download\phone_readiness.json`:
  - `pc_desktop=True`;
  - `phone_same_wifi=True`;
  - `render_deploy_package=True`;
  - `phone_install_download=True`;
  - `phone_temporary_tunnel=True`;
  - `phone_emulator_smoke=True`;
  - `phone_permanent_cloud=False`;
  - `phone_device_smoke=False`.
- Latest artifacts after honest physical audit and tunnel retry hardening:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161676775`, SHA256
    `1B019F166AAA0D68AAD8D25CF02C5E830F7F652354BF4DC85844AC6D709317C8`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2837607`,
    SHA256
    `10DF4EF42F7FBD55B14A2BA110E08FB81B27C27B7DA0F121C7FD88250E89618D`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `791`, SHA256
    `1821FC3FED0213974E349F003C1419E5F68D04F581C5CC119C4005D78507A979`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T23:34:01.4886842+02:00`, size `12588`, SHA256
    `D06D43C498505B03D297D9D344A6E73F518C5128BD2229D5D1C36197D459252A`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `FB2FFD032E2DF2B5A4947703A5478ED5C68BDCBA25F80F6F66563C98DE4D3215`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7027`, SHA256
    `62521C13B8395AC9B278A0827EC0DB23A0F900B89C1A4B7CAA6B356F1CC02F18`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4267`, SHA256
    `30B2528B8CEB7972B1F25CE35ADBBD88FA65A9C0818603A8B0588E8911786E0A`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67510`, SHA256
    `F8FE4302D703C1CA215F3C50C4C0D09CA5261DE2A1B39DF301170084FE0EAADF`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331075`, SHA256
    `C48C90A1BE306B0BD195588F0D195BDBC5EC4E1E3073D960E2EB914C6BEF284A`;
  - internet APK: `outputs\phone_download\VerityLens-internet.apk`, size
    `49843593`, SHA256
    `3C24FC4C1425C702F7AEA37BB0456B3AD17F51B6F357EA17C1FE712F1B8AA31B`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `457CC8F6FEFFF88E079860B1F52CBD416A6B1AEF9FBC8BECF97E65D1E7E3F4B1`;
  - APK verification JSON: `outputs\phone_download\PHONE_APK_VERIFICATION.json`,
    size `2161`, SHA256
    `19C64C5E67881D5F7C1B38404583D4DD720459500502E5DC8643FA3C2CE36C3C`;
  - emulator smoke JSON: `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`,
    size `14883`, SHA256
    `C605AB4EC29F6AAFF58A3B78F581E3803A26357ED87023CD9DFB56B2E3FE96A4`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24215`, SHA256
    `4F86534FEC963D433A19EBD4E23249DFA5D15C8F649A1ED983ECE3AFDFC1E925`;
  - tunnel info JSON: `outputs\public_api_tunnel_info.json`, size `485`,
    SHA256
    `59A3E1577DCFB166DE34B9B335E6A28EAE7D075949E599748BE68552FC1FA652`.
- Remaining `8%` is still genuinely external/stateful:
  - deploy a permanent Render HTTPS backend;
  - build and verify `VerityLens-cloud.apk` against that permanent URL;
  - connect and authorize a physical Android phone over USB;
  - run finalizer:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`;
  - verify `goal_completion_audit_latest.json` reaches `complete=True`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Final Render/USB Instructions Tightened

- Current goal status remains `92%` complete / `8%` remaining.
- Tightened final manual instructions in:
  - `README.md`;
  - `RUNBOOK.md`;
  - `docs\mobile_flutter_render.md`.
- The final external preflight examples now show the strict command:
  `.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://<render-app>.onrender.com -RequireReady`.
- Added explicit physical Android USB checklist to the docs:
  - enable Developer options;
  - enable `USB debugging`;
  - connect phone by USB;
  - accept the RSA authorization prompt;
  - run `adb devices`;
  - require one row with state `device`;
  - `offline` or `unauthorized` does not count;
  - if multiple devices are attached, pass `-PhoneDeviceId`.
- Updated `tests\test_factcheck_core.py` so README/RUNBOOK/mobile Render docs
  must keep `USB debugging`, `adb devices`, `-RequireReady`, and
  `-PhoneDeviceId`.
- Verification after these doc/checklist changes:
  - targeted structural test
    `test_flutter_mobile_project_and_render_files_exist`: OK;
  - full backend suite: `113/113` OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - release gate phone readiness summary:
    `phone_temporary_tunnel=True`, `phone_emulator_smoke=True`,
    `phone_permanent_cloud=False`, `phone_device_smoke=False`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: OK, failures `0`, warnings `2`;
  - `scripts\audit_project_goal_completion.ps1`: not complete, remaining
    `phone_permanent_cloud` and `physical_phone_proof`;
  - `scripts\check_final_external_prereqs.ps1`: not ready to run finalizer,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after final Render/USB instruction tightening:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161678133`, SHA256
    `FB928F6CE299BD32A71FFD8F4CDC40EE10A24E5105AFDFDE3E160145E8AA0F88`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2838229`,
    SHA256
    `33CAFB60890314C00F72A77E377643AED3B19E04BBB40D3ADE64EE6F310D6726`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `791`, SHA256
    `8552991A2893AD3C6CBFBAC055C80AB3668AB1A3E1B6C33028DF7974EC9BBBA5`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T23:40:02.1148329+02:00`, size `12590`, SHA256
    `CC3D2584759E1322C05E30171A66EFCE0D08A365880DC7DF1A3154CA13EF23AE`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `ADC42E925032FC57B580315B57337535BFE99B1243A774B99338AA3C1EDCD0AD`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7027`, SHA256
    `628434A0CEAE4189C67E922FE3DF525F2384E6114A8ED81C871802F7DBBE1A9A`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4267`, SHA256
    `CE269C558E325D7A482A9931B2678F732AE0927CB4F6DCF75B23230859B71FB6`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `67510`, SHA256
    `F47B667DE716D954D67E26191DF90D6097EA01F3C947AA6AB3946006E64BFD21`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331248`, SHA256
    `684655CAA3201C5362371ADB981C4C35A29FC694257A1AD16C24C4532E7D6992`;
  - internet APK: `outputs\phone_download\VerityLens-internet.apk`, size
    `49843593`, SHA256
    `3C24FC4C1425C702F7AEA37BB0456B3AD17F51B6F357EA17C1FE712F1B8AA31B`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `457CC8F6FEFFF88E079860B1F52CBD416A6B1AEF9FBC8BECF97E65D1E7E3F4B1`;
  - APK verification JSON: `outputs\phone_download\PHONE_APK_VERIFICATION.json`,
    size `2161`, SHA256
    `6127F1EBF053BEEFF0F232A1590FB6BE798F3F37BBE9F16A480577A343094B6B`;
  - emulator smoke JSON: `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`,
    size `14883`, SHA256
    `C605AB4EC29F6AAFF58A3B78F581E3803A26357ED87023CD9DFB56B2E3FE96A4`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24215`, SHA256
    `2EB40539F5D50379F959888F8A091E086DFC9C57A2D16A9EB666F3295B31E56F`;
  - tunnel info JSON: `outputs\public_api_tunnel_info.json`, size `485`,
    SHA256
    `59A3E1577DCFB166DE34B9B335E6A28EAE7D075949E599748BE68552FC1FA652`.
- Remaining `8%` is still genuinely external/stateful:
  - deploy a permanent Render HTTPS backend;
  - build and verify `VerityLens-cloud.apk` against that permanent URL;
  - connect and authorize a physical Android phone over USB;
  - run strict preflight:
    `.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com' -RequireReady`;
  - run finalizer:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`;
  - verify `goal_completion_audit_latest.json` reaches `complete=True`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: LaTeX Report Includes Final Preflight And ADB Proof Steps

- Current goal status remains `92%` complete / `8%` remaining.
- Updated the university LaTeX report:
  - `docs\report\verity_lens_report.tex` now documents the strict final
    preflight command
    `.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl https://app.onrender.com -RequireReady`;
  - it explains that final proof checks Render URL policy, `/health`, `/ready`,
    `/factcheck`, and physical-device ADB authorization;
  - it explicitly says final phone proof requires `USB debugging`,
    `adb devices` with state `device`, and that `offline`/`unauthorized` do not
    count;
  - it documents `-PhoneDeviceId` for multi-device cases;
  - the appendix command block now includes `adb devices` and strict final
    preflight before the finalizer.
- Updated `tests\test_factcheck_core.py` so the university report must keep
  `check_final_external_prereqs.ps1`, `-RequireReady`, `USB debugging`,
  `adb devices`, and `-PhoneDeviceId`.
- Verification after this report update:
  - targeted report structure test
    `test_university_latex_report_has_required_structure_and_results`: OK;
  - `scripts\build_report.ps1`: OK, PDF rebuilt;
  - full backend suite: `113/113` OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - release gate phone readiness summary:
    `phone_temporary_tunnel=True`, `phone_emulator_smoke=True`,
    `phone_permanent_cloud=False`, `phone_device_smoke=False`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: OK, failures `0`, warnings `2`;
  - `scripts\audit_project_goal_completion.ps1`: not complete, remaining
    `phone_permanent_cloud` and `physical_phone_proof`;
  - `scripts\check_final_external_prereqs.ps1`: not ready to run finalizer,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after LaTeX final-preflight/ADB proof update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161679687`, SHA256
    `79211C3D81D9D2F4EA6C4266D511F190D4D126183023FC7D2D73ACC0E1293206`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2838524`,
    SHA256
    `B0B6E8D4F16AE26492671A0AF7DACB3489DD1B9F26670819F79A621EBC4A5AAC`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `791`, SHA256
    `FFFDDE393C45530CF227EA9F1352383B15EF95A83FBFB20A070A57A716CB04F9`;
  - release gate JSON: `reports\release_gate_latest.json`, generated
    `2026-05-29T23:44:39.0298224+02:00`, size `12590`, SHA256
    `5EF2E7C4F223F58F1782430CAD27A4FBDBFF7330F39E3A2D6CC56DFCA47E6239`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `4D5C9AFDF6FEBD63EC0864FCB6511A98A9EE4A68A3C1134A7F51919308B2B5E6`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7027`, SHA256
    `6A3BC4BDFED6C1FA9EA84A686B80CFCCE298AEDD3EC1CB39F5CF2814D9ABB04B`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4267`, SHA256
    `2E494F98F16FA6E11137AB5311D03B460F073AC32FED7F8A686C384C7525168E`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `68522`, SHA256
    `BFAB6C781A48E4964BFB7355AA9090803C7985A1036DEEBC7E2482B0EBDBC84E`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331248`, SHA256
    `684655CAA3201C5362371ADB981C4C35A29FC694257A1AD16C24C4532E7D6992`;
  - internet APK: `outputs\phone_download\VerityLens-internet.apk`, size
    `49843593`, SHA256
    `3C24FC4C1425C702F7AEA37BB0456B3AD17F51B6F357EA17C1FE712F1B8AA31B`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `457CC8F6FEFFF88E079860B1F52CBD416A6B1AEF9FBC8BECF97E65D1E7E3F4B1`;
  - APK verification JSON: `outputs\phone_download\PHONE_APK_VERIFICATION.json`,
    size `2161`, SHA256
    `2DE67E4F05B7B97AA50771F4B9F6F989B966F3D8C2532AA0D81B7DF9011D00B0`;
  - emulator smoke JSON: `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`,
    size `14883`, SHA256
    `C605AB4EC29F6AAFF58A3B78F581E3803A26357ED87023CD9DFB56B2E3FE96A4`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24215`, SHA256
    `CD71E7DDAA77CC74463431F7BC3ACCA90F46EDACECC126F77BB97CB838497CD0`;
  - tunnel info JSON: `outputs\public_api_tunnel_info.json`, size `485`,
    SHA256
    `59A3E1577DCFB166DE34B9B335E6A28EAE7D075949E599748BE68552FC1FA652`.
- Remaining `8%` is still genuinely external/stateful:
  - deploy a permanent Render HTTPS backend;
  - build and verify `VerityLens-cloud.apk` against that permanent URL;
  - connect and authorize a physical Android phone over USB;
  - run strict preflight:
    `.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com' -RequireReady`;
  - run finalizer:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`;
  - verify `goal_completion_audit_latest.json` reaches `complete=True`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Final Cloud Submission Now Rejects Debug APK Mode

- Current goal status remains `92%` complete / `8%` remaining.
- Closed one local final-submission risk:
  - `scripts\finalize_cloud_phone_submission.ps1` now rejects
    `-CloudApkMode debug` immediately;
  - the final wrapper requires `-CloudApkMode release`;
  - debug-only diagnostics should use `scripts\run_release_gate.ps1` directly.
- Updated documentation to match:
  - `README.md`;
  - `RUNBOOK.md`;
  - `docs\mobile_flutter_render.md`;
  - `docs\report\verity_lens_report.tex`.
- Updated `tests\test_factcheck_core.py` so the final submission wrapper must
  keep the release-only debug rejection message.
- Verification after this update:
  - direct debug rejection smoke:
    `pwsh -NoProfile -ExecutionPolicy Bypass -File scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://example.onrender.com -CloudApkMode debug`
    exits with the expected error:
    `Final cloud phone submission requires -CloudApkMode release`;
  - targeted structural test
    `test_flutter_mobile_project_and_render_files_exist`: OK;
  - full backend suite: `113/113` OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - release gate phone readiness summary:
    `phone_temporary_tunnel=True`, `phone_emulator_smoke=True`,
    `phone_permanent_cloud=False`, `phone_device_smoke=False`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: OK, failures `0`, warnings `2`;
  - `scripts\audit_project_goal_completion.ps1`: not complete, remaining
    `phone_permanent_cloud` and `physical_phone_proof`;
  - `scripts\check_final_external_prereqs.ps1`: not ready to run finalizer,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after release-only final-wrapper update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161680504`, SHA256
    `6D3618B5554BA1731D1CC58F1C7F8535AFC21C1E929822FDDE870739C2CE7FBE`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2838828`,
    SHA256
    `211923555EFE812E4AD77F4CCE5293AAF6819B7963B6CC0137E97ACF5714E774`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `791`, SHA256
    `88247BB3684E5C5AFE3DE9B015D9ADC5447D754C907FA173F990A228574A6012`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12589`,
    SHA256
    `511E4EF0555BF93EEFE476C6C3A509A347B6B6FEB13ACB7F115B6C2DC25826E1`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `689139DBFAD11F535C578E8F225BF9B923C138FD46F5C6D03E7F8D63E08C68C8`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7027`, SHA256
    `7D1EBB632E970672F2BF12B6447C2DEC34EF284F49FF40B1EEB0025E53FDE317`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4267`, SHA256
    `E8A7B8791D1A3D21AD8B66646B72B6099B67C52034A6962FD4AC660A6D2A58D2`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `68768`, SHA256
    `785F44490C56F69BE23A9492C6F4066357A470F7D6A33819BC71F8C2573ED429`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331289`, SHA256
    `9535562E59A683B52E6BA72B3F82CF7BD75441A54F357A0D2B8C9E543766B234`;
  - internet APK: `outputs\phone_download\VerityLens-internet.apk`, size
    `49843593`, SHA256
    `3C24FC4C1425C702F7AEA37BB0456B3AD17F51B6F357EA17C1FE712F1B8AA31B`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `457CC8F6FEFFF88E079860B1F52CBD416A6B1AEF9FBC8BECF97E65D1E7E3F4B1`;
  - APK verification JSON: `outputs\phone_download\PHONE_APK_VERIFICATION.json`,
    size `2161`, SHA256
    `52023C8483F003EECC5EB46672068D653A140E55992BE0208F85157724F20391`;
  - emulator smoke JSON: `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`,
    size `14883`, SHA256
    `C605AB4EC29F6AAFF58A3B78F581E3803A26357ED87023CD9DFB56B2E3FE96A4`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24215`, SHA256
    `E8A75BDEB0BA6F7BF7984E6D6552892490908EF73DE57FB8E8FF0447DC1C97C1`;
  - tunnel info JSON: `outputs\public_api_tunnel_info.json`, size `485`,
    SHA256
    `59A3E1577DCFB166DE34B9B335E6A28EAE7D075949E599748BE68552FC1FA652`.
- Remaining `8%` is still external/stateful:
  - deploy a permanent Render HTTPS backend;
  - build and verify `VerityLens-cloud.apk` against that permanent URL;
  - connect and authorize a physical Android phone over USB;
  - run strict preflight:
    `.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com' -RequireReady`;
  - run finalizer:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`;
  - verify `goal_completion_audit_latest.json` reaches `complete=True`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Cloud APK Release Mode Is Now Required Across Readiness

- Current goal status remains `92%` complete / `8%` remaining.
- Closed another local cloud/mobile finalization risk:
  - `scripts\build_phone_for_cloud.ps1` now defaults to `release`;
  - `scripts\run_release_gate.ps1` now defaults `-CloudApkMode release`;
  - `scripts\check_phone_readiness.ps1` records APK verification
    `expected_mode` and `is_release_mode`, and permanent cloud phone readiness
    requires `is_release_mode=True`;
  - `scripts\audit_project_goal_completion.ps1` requires the cloud APK
    verification report to prove `expected_mode=release`;
  - `scripts\verify_submission_bundle.ps1` fails if a cloud APK verification
    report or cloud release-gate report proves a debug cloud APK.
- Updated documentation to match:
  - `README.md`;
  - `RUNBOOK.md`;
  - `docs\mobile_flutter_render.md`;
  - `docs\report\verity_lens_report.tex`.
- Updated `tests\test_factcheck_core.py` so defaults and release-only cloud
  evidence checks stay covered.
- Verification after this update:
  - targeted structural tests:
    `test_flutter_mobile_project_and_render_files_exist`,
    `test_release_gate_covers_pc_mobile_and_cloud_paths`, and
    `test_university_latex_report_has_required_structure_and_results`: OK;
  - `scripts\check_phone_readiness.ps1`: OK, readiness JSON now includes
    `expected_mode` and `is_release_mode` in APK verification summaries;
  - `scripts\audit_project_goal_completion.ps1`: not complete, remaining
    `phone_permanent_cloud` and `physical_phone_proof`;
  - full backend suite: `113/113` OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - release gate phone readiness summary:
    `phone_temporary_tunnel=True`, `phone_emulator_smoke=True`,
    `phone_permanent_cloud=False`, `phone_device_smoke=False`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: OK, failures `0`, warnings `2`;
  - `scripts\check_final_external_prereqs.ps1`: not ready to run finalizer,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after cloud release-mode readiness update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161681064`, SHA256
    `414F5F5AF75608FEACD84D537E7DBF963002CC1AEB5F9C466E8538D738010AF1`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2839189`,
    SHA256
    `42F091D56B6C6F412E1D1DF58639629D1BA5392E4109A03B5670CFC3590BBCCA`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `791`, SHA256
    `0D7D6B7BA1E88A6D1A1F7EBA5D3B64D8BEF07488C2123354D0559BA99926A181`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12593`,
    SHA256
    `DBEF210DB374F544ED4CA20135317B85E6F15183EC195ECC9808CD3558E53531`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `2BD5CDACF581C613E0D13A34C8F064FBF6332851516E4825E1D0E8E808BD0F55`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7069`, SHA256
    `5D82D8C85AA6B1DCAFEA8EF00FF0441CD127CCF3E9D48145A67FCDA0902E0C62`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4267`, SHA256
    `6BB1E4FF2D965AAE83F8BB28EBE5F123CA91DEBEB76A3C51CC6D2B72DF20BCE8`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `68826`, SHA256
    `ED5BCA726D033D839C5917AA8D2C33E90025D1E07357499C9AA71659C3A0C222`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331322`, SHA256
    `A265054981D73DA3FB2B77087356473E5670813881B8AE848A9063EF2C88E182`;
  - internet APK: `outputs\phone_download\VerityLens-internet.apk`, size
    `49843593`, SHA256
    `3C24FC4C1425C702F7AEA37BB0456B3AD17F51B6F357EA17C1FE712F1B8AA31B`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `457CC8F6FEFFF88E079860B1F52CBD416A6B1AEF9FBC8BECF97E65D1E7E3F4B1`;
  - APK verification JSON: `outputs\phone_download\PHONE_APK_VERIFICATION.json`,
    size `2161`, SHA256
    `6F8B2FFE9FF0747B4F5975216AF18855D3419B58D2AA70306E58B676CB4636D6`;
  - emulator smoke JSON: `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`,
    size `14883`, SHA256
    `C605AB4EC29F6AAFF58A3B78F581E3803A26357ED87023CD9DFB56B2E3FE96A4`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24397`, SHA256
    `5E9FA96074DFEB261935299AD90D454210B6F5F487690DBB881F525137F08C3F`;
  - tunnel info JSON: `outputs\public_api_tunnel_info.json`, size `485`,
    SHA256
    `59A3E1577DCFB166DE34B9B335E6A28EAE7D075949E599748BE68552FC1FA652`.
- Remaining `8%` is still external/stateful:
  - deploy a permanent Render HTTPS backend;
  - build and verify `VerityLens-cloud.apk` against that permanent URL;
  - connect and authorize a physical Android phone over USB;
  - run strict preflight:
    `.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com' -RequireReady`;
  - run finalizer:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`;
  - verify `goal_completion_audit_latest.json` reaches `complete=True`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: LAN And Temporary Phone Readiness Require Release APKs

- Current goal status remains `92%` complete / `8%` remaining.
- Closed a local phone-readiness/verifier gap:
  - `scripts\check_phone_readiness.ps1` now requires
    `PHONE_APK_VERIFICATION.json` to prove `is_release_mode=True` before
    `phone_temporary_tunnel` can pass;
  - it also requires `PHONE_LAN_APK_VERIFICATION.json` to prove
    `is_release_mode=True` before `phone_same_wifi` can pass;
  - `scripts\verify_submission_bundle.ps1` now fails if internet or LAN APK
    verification reports do not prove `expected_mode=release`;
  - the phone readiness markdown now prints expected/release mode for internet,
    LAN, and cloud APK verification.
- Updated documentation to match:
  - `README.md`;
  - `RUNBOOK.md`;
  - `docs\mobile_flutter_render.md`;
  - `docs\report\verity_lens_report.tex`.
- Updated `tests\test_factcheck_core.py` so release-mode checks for internet,
  LAN and cloud APK evidence remain covered.
- Verification after this update:
  - targeted structural tests:
    `test_flutter_mobile_project_and_render_files_exist` and
    `test_university_latex_report_has_required_structure_and_results`: OK;
  - `scripts\check_phone_readiness.ps1`: OK;
  - `scripts\audit_project_goal_completion.ps1`: not complete, remaining
    `phone_permanent_cloud` and `physical_phone_proof`;
  - full backend suite: `113/113` OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - release gate phone readiness summary:
    `phone_temporary_tunnel=True`, `phone_same_wifi=True`,
    `phone_emulator_smoke=True`, `phone_permanent_cloud=False`,
    `phone_device_smoke=False`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: OK, failures `0`, warnings `2`;
  - `scripts\check_final_external_prereqs.ps1`: not ready to run finalizer,
    missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`.
- Latest artifacts after LAN/temporary release-mode readiness update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161681291`, SHA256
    `A6F37F3AA383A28F100A1894CC3FB1BF69A6C0D393FD329C9185D5EA3DD80F68`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2839307`,
    SHA256
    `EF3800392030FE55A00BE5AF9309FF5D7B0F5BAF8BD24A15EC02ABE824D82007`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `791`, SHA256
    `A91ECA70F0F856CF1C842BDD0CF92E7DA41E2857E49A10914D6AACB22BFABF1E`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12593`,
    SHA256
    `1394ED8D9785698D790DA43EBF530EE029B50B17912E8D53B7797B0A91F924E4`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `9F682A758283A3E3BE7B37A2BF9D38F089F8287EB9DC6D7CB2AE2C6CF62EA0C9`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7069`, SHA256
    `38F8D3E2A6DA5486F841C928A553BBBC0BE844274C22A14D9D7A2753F900818A`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4267`, SHA256
    `6B1A35C208097E5DE3B15B809229023F4D515C350F40025F9EDA69782540CB9C`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `68881`, SHA256
    `E347AA985A747A7F813D410E09A8246DB25184037EA26AB686A32D49DFAABA70`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331324`, SHA256
    `0D31D973A76E6B427ABA499CE485227DFCABE4017EC5639768032E67DA123285`;
  - internet APK: `outputs\phone_download\VerityLens-internet.apk`, size
    `49843593`, SHA256
    `3C24FC4C1425C702F7AEA37BB0456B3AD17F51B6F357EA17C1FE712F1B8AA31B`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `457CC8F6FEFFF88E079860B1F52CBD416A6B1AEF9FBC8BECF97E65D1E7E3F4B1`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2161`,
    SHA256
    `CC300F3EA9A1ABF34F6E006410F5FF84771117B9FCCA2D55B2E1516E219290C4`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2121`,
    SHA256
    `3910A2748BA9216D58FFCFD8331BD5A885277E2B39EFA1BF6AB4DC44E188D27D`;
  - emulator smoke JSON: `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`,
    size `14883`, SHA256
    `C605AB4EC29F6AAFF58A3B78F581E3803A26357ED87023CD9DFB56B2E3FE96A4`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24398`, SHA256
    `8B9149C39C2C09ECD226E29CFDF6752859DA0658EBAD0F3B57257D1AA599A0A2`;
  - tunnel info JSON: `outputs\public_api_tunnel_info.json`, size `485`,
    SHA256
    `59A3E1577DCFB166DE34B9B335E6A28EAE7D075949E599748BE68552FC1FA652`.
- Remaining `8%` is still external/stateful:
  - deploy a permanent Render HTTPS backend;
  - build and verify `VerityLens-cloud.apk` against that permanent URL;
  - connect and authorize a physical Android phone over USB;
  - run strict preflight:
    `.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com' -RequireReady`;
  - run finalizer:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`;
  - verify `goal_completion_audit_latest.json` reaches `complete=True`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Update: Final External Preflight Retries Render API Probes

- Current goal status remains `92%` complete / `8%` remaining.
- Closed a final-preflight reliability gap:
  - `scripts\check_final_external_prereqs.ps1` now retries `/health`,
    `/ready`, and the fake-claim `/factcheck` probe;
  - it writes `health_attempts`, `ready_attempts`, and
    `fake_probe_attempts` into `reports\final_external_preflight_latest.json`;
  - this makes the final Render/phone preflight less brittle around Render cold
    starts and brief network hiccups.
- Updated documentation to match:
  - `README.md`;
  - `RUNBOOK.md`;
  - `docs\mobile_flutter_render.md`;
  - `docs\report\verity_lens_report.tex`.
- Updated `tests\test_factcheck_core.py` so the retry behavior and attempt
  fields remain covered.
- Verification after this update:
  - targeted structural tests:
    `test_flutter_mobile_project_and_render_files_exist`,
    `test_final_external_preflight_quotes_copy_paste_command`, and
    `test_university_latex_report_has_required_structure_and_results`: OK;
  - `scripts\check_final_external_prereqs.ps1`: OK report generation, not ready
    as expected because missing `real public HTTPS Render API URL` and
    `authorized physical USB Android device`;
  - `scripts\audit_project_goal_completion.ps1`: not complete, remaining
    `phone_permanent_cloud` and `physical_phone_proof`;
  - full backend suite: `113/113` OK;
  - full `scripts\run_release_gate.ps1`: OK;
  - product acceptance inside release gate: `93/93` OK, pass rate `1.0`;
  - release gate phone readiness summary:
    `phone_temporary_tunnel=True`, `phone_same_wifi=True`,
    `phone_emulator_smoke=True`, `phone_permanent_cloud=False`,
    `phone_device_smoke=False`;
  - `scripts\make_submission_bundle.ps1`: OK;
  - submission verifier: OK, failures `0`, warnings `2`.
- Latest artifacts after final-preflight retry update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161681751`, SHA256
    `3A0D5D4A79D0AA601673AD7128B8EC95B9617EF5909F3E0143AA529BB175CB30`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2839649`,
    SHA256
    `026B1F321BEA76ECF84890F8209A4CB48DA922DE2A6E814930810986BCC327AE`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, verifier OK
    `True`, warnings `2`, failures `0`, size `791`, SHA256
    `D9FCC4BA4D1972C5C29575341ADE273D5A14A2309A052902C4AF0484DBABD3F2`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12592`,
    SHA256
    `F168974CEE0AC1DD0BEA707F681D95BEAF67CD9367EC83A97559235C5D8A2669`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `DA25BAED13BC749B201A016064065B626FAD00A1F9B1D44553658F2BDEB99E3C`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7069`, SHA256
    `2BB7E641F0363336E80FEA4883F145F0412186523558C0B7D49A15D6EE6B99DF`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `4357`, SHA256
    `422DC97FCEE9C282652DBFE3CF75C945990C660B04D3023302222EE66DBF04C0`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `68920`, SHA256
    `C28CCFA1D9E04C86763A616DFE0B4CC9C32B2AC5AFF3DBF86F09AF78C2CC5ECD`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331328`, SHA256
    `C3896893B8D2A8445FFBB366C78175EA8D077F453FA43E9617AD55ECFA17DB2A`;
  - internet APK: `outputs\phone_download\VerityLens-internet.apk`, size
    `49843593`, SHA256
    `3C24FC4C1425C702F7AEA37BB0456B3AD17F51B6F357EA17C1FE712F1B8AA31B`;
  - LAN APK: `outputs\phone_download\VerityLens-lan.apk`, size `49843593`,
    SHA256
    `457CC8F6FEFFF88E079860B1F52CBD416A6B1AEF9FBC8BECF97E65D1E7E3F4B1`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2161`,
    SHA256
    `003196E7EF143F9915DC11F64A497982807FA3B5A284A867C5225C18B9FD7CAC`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2121`,
    SHA256
    `3C3698EBCB1CCA0ABFD9D146F2F8A3A3E4BBA253DC9283C2EF5DA6E81CBA9116`;
  - emulator smoke JSON: `outputs\phone_download\PHONE_EMULATOR_SMOKE.json`,
    size `14883`, SHA256
    `C605AB4EC29F6AAFF58A3B78F581E3803A26357ED87023CD9DFB56B2E3FE96A4`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24398`, SHA256
    `B32C1FF5001B650E54BA8488CC990B4455F7FFDB7032D84D4EF0C9FDC929C899`;
  - tunnel info JSON: `outputs\public_api_tunnel_info.json`, size `485`,
    SHA256
    `59A3E1577DCFB166DE34B9B335E6A28EAE7D075949E599748BE68552FC1FA652`.
- Remaining `8%` is still external/stateful:
  - deploy a permanent Render HTTPS backend;
  - build and verify `VerityLens-cloud.apk` against that permanent URL;
  - connect and authorize a physical Android phone over USB;
  - run strict preflight:
    `.\scripts\check_final_external_prereqs.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com' -RequireReady`;
  - run finalizer:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`;
  - verify `goal_completion_audit_latest.json` reaches `complete=True`.
- Important: this is now the freshest artifact block. Older artifact blocks
  above are historical and have been superseded by this section.

## Recommended Next Steps

1. Get a GitHub repo or Render access.
2. Deploy backend with `render.yaml`.
3. Verify cloud API using `scripts\verify_cloud_api.ps1`.
4. Build `VerityLens-cloud.apk`.
5. Install on phone and run full manual matrix.
6. With a USB-connected Android phone, run
   `scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl https://<render-app>.onrender.com`
   to build/verify the cloud APK, require the physical phone proof, rebuild the
   submission ZIP, and produce the final cloud-phone report.
7. If Render sleeps too often, move to paid Render plan or another host.
8. If AI-image mode matters, test whether paid host can run optional model; otherwise keep metadata-only and explain conservatively.
9. Install the cloud APK on a real phone and verify the new `API connected` banner against the Render URL.

## Final Mental Model For Successor

Think of this as two apps sharing one brain:

- **Brain:** Python/FastAPI fact-check backend.
- **Faces:** Web UI, Windows PyWebView desktop, Flutter mobile.

The phone is not self-contained. It calls the brain over HTTPS. The big job now is making that brain live permanently in the cloud.

## Update: Install Page No Longer Advertises Unproven Cloud APK

- Tightened the phone install-page path so a permanent cloud APK download is
  shown only when all final evidence is true:
  - `outputs\phone_download\VerityLens-cloud.apk` exists;
  - `PHONE_CLOUD_APK_VERIFICATION.json` is `ok=True`;
  - the cloud verification proves `expected_mode=release`;
  - the API probe and embedded Render URL are present;
  - the Flutter source stamp sidecar exists and matches current source;
  - `phone_readiness.json` reports `phone_permanent_cloud=True`.
- `scripts\prepare_phone_install_page.ps1` now records cloud APK
  `download_ready`, `release_mode`, `api_ok`, `embedded_api_url_found`,
  `source_stamp_current`, and `permanent_phone_ready`. The generated install
  page keeps reporting stale/missing cloud status, but it does not expose the
  `Download Permanent Cloud APK` button until the final cloud path is proven.
- `scripts\verify_submission_bundle.ps1` now fails if
  `PHONE_INSTALL_PAGE.json` exposes a cloud APK download before permanent cloud
  readiness and release verification are true.
- Updated docs/report:
  - `README.md`
  - `RUNBOOK.md`
  - `docs\mobile_flutter_render.md`
  - `docs\report\verity_lens_report.tex`
- Updated structural tests in `tests\test_factcheck_core.py`.
- Verification after this change:
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests`: `113/113 OK`;
  - `.\scripts\build_report.ps1`: OK, PDF rebuilt; only underfull hbox/fontconfig warnings;
  - `.\scripts\run_release_gate.ps1`: OK;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Fresh artifact hashes from this update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161683950`, SHA256
    `A5EAA2F26F4CCF830727463B437BBC3124058C443A007A9F2576BB0F008A0ED9`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2840797`,
    SHA256
    `3748D311561B71B672838965409430EC576CBB4D54368F616E79D85B225A7907`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, warnings `2`, size `791`, SHA256
    `F1BCBE7E8EC8FFC0DD67863F217A113CC40D792F448C79F49800EB2F7A646D53`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12591`,
    SHA256
    `EE50A445732C1507153AA92DDCD2338FD877520B849424631593DC9EF56A4B33`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `51B6A0FC38080A5CB9DE06D3C15642ADD80B88410B61D3157008F07FFB507707`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7069`, SHA256
    `71BA510FD8287AF0C30705ABD5B3E04416452B3743D9B6AEFE1DA71FA12B1431`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `69264`, SHA256
    `6BB101D8D5BBFCA97E62C277735F3A3389AAB97AADABDC02A6F72127913FFF4D`;
  - phone install-page JSON:
    `outputs\phone_download\PHONE_INSTALL_PAGE.json`, size `1177`, SHA256
    `1C85881C154C0CB7D42DD467295067FADCEADD9D87E7FA329A7C3778533C08F6`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24397`, SHA256
    `E1B0A9B3CA64A4852D3DEF90EBB1FBD77D8FC2D5DD34F8A1A1C11B33285E922C`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331442`, SHA256
    `61764775D5F4A3AAF00B22C37B3A73CE22FF24423EE97384B3621248A33455CF`.
- Current install-page cloud section in the submission copy correctly reports:
  - `cloud_apk.exists=False`;
  - `download_ready=False`;
  - `download_url=""`;
  - `permanent_phone_ready=False`.
- Remaining `8%` is unchanged and external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device and screenshot proof.
- This section supersedes older artifact hash blocks above.

## Update: Final Wrapper Requires Physical Device Evidence

- Tightened `scripts\finalize_cloud_phone_submission.ps1` so the final
  evidence check cannot pass with only a generic device smoke result.
- `Get-FinalEvidence` now records and `Assert-FinalEvidenceReady` requires:
  - `phone_device_requires_physical`;
  - `phone_device_selected_id`;
  - `phone_device_selected_physical`;
  - `phone_device_screenshot_sha256_recorded`;
  - `phone_device_screenshot_sha256_matches`.
- The final JSON/Markdown report now includes the selected phone serial,
  physical-device requirement, non-emulator proof, and screenshot SHA256 match.
- Updated structural tests in `tests\test_factcheck_core.py`.
- Updated documentation/report:
  - `docs\mobile_flutter_render.md`;
  - `docs\report\verity_lens_report.tex`.
- Verification after this change:
  - PowerShell parser check for finalizer/audit/verifier: OK;
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests`: `113/113 OK`;
  - `.\scripts\build_report.ps1`: OK, PDF rebuilt; only underfull hbox/fontconfig warnings;
  - `.\scripts\run_release_gate.ps1`: OK;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Submission verifier remains OK with two expected warnings:
  - permanent cloud phone readiness is false until a real Render HTTPS URL and
    cloud APK are verified;
  - phone device smoke is skipped until run with
    `-RequireDevice -RequirePhysicalDevice` on a connected Android phone.
- Fresh artifact hashes from this update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161689153`, SHA256
    `0D1B1C5D3DBF0A10988317E10AC1FE747974AF11EFECB3C25D4951B23454D817`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2844011`,
    SHA256
    `3B8E3351715AF674654D4EA5D6CA83852197635B9DC4176663A7618C88720BE2`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, warnings `2`, size `791`, SHA256
    `D572B06ECB857FAA0A7B835F1007E8C4291161A0E7E7EC56EC3AB873CC79DF3C`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12591`,
    SHA256
    `41C49C519AE800D82C56292AA78D4E0AF58E1B8C82AACE59B03513798BEFBE02`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `800F5D6CB501465FAF0730ADBC467D94227DD4AEDF8FF0AB5F1707AFD946D2AB`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7394`, SHA256
    `F24ACC2F31AF187BCCCABD7997142851E345DCF1E26F842837CD69B185138C59`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `70050`, SHA256
    `B331CDD223AE31DFF2C81F60163579CD50F66AE01B4CE495523574500A616B22`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3198`, SHA256
    `B0E1F02172FE502619CD0F11E30CCCB80B6EDB22B9EA6A5FA328315EFAA1379B`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331614`, SHA256
    `E2D1EA1A911B986146A44C674D5DFB8EA5122F7A4A844C426D23BB76BBA9B1CF`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24398`, SHA256
    `7A10233FA9A264298AE3991078D04E26939F31172F0638DD55FAE28C285893BD`.
- Remaining `8%` is still external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device and screenshot proof.
- This section supersedes older artifact hash blocks above.

## Update: Release Gate Handles Temporary Tunnel Expiry And Starts LAN API

- Fixed `scripts\check_final_external_prereqs.ps1` ADB execution:
  - `Invoke-AdbText` now uses `System.Diagnostics.ProcessStartInfo`;
  - stdout/stderr are redirected explicitly;
  - ADB calls have a timeout and return a structured error instead of crashing
    PowerShell with `StandardOutputEncoding` issues.
- Added a `Final Evidence Contract` section to
  `reports\final_external_preflight_latest.*`:
  - cloud fields include `phone_permanent_cloud`,
    `cloud_status_ready_to_publish`, and release cloud APK mode;
  - physical-phone fields include selected device id, non-emulator proof,
    captured screenshot, and matching screenshot SHA256;
  - required final reports are listed explicitly.
- Relaxed only the temporary-tunnel internet APK path:
  - `scripts\verify_phone_apk.ps1` has
    `-AllowTemporaryTunnelApiFailure`;
  - it still requires binary evidence, embedded API URL, release mode, status
    file, and Flutter source stamp to match;
  - `scripts\verify_submission_bundle.ps1` converts a dead temporary tunnel API
    probe into a warning;
  - permanent Render/cloud APK verification remains strict.
- Fixed same-Wi-Fi phone verification in `scripts\run_release_gate.ps1`:
  - new `LAN API server` step starts `src.api_factcheck:app` on the port from
    `outputs\phone_download\VerityLens-lan-api-url.txt`;
  - `LAN APK verification` now checks against a live local API instead of
    failing when the API had simply been stopped.
- Updated tests and docs:
  - `tests\test_factcheck_core.py`;
  - `README.md`;
  - `RUNBOOK.md`;
  - `docs\mobile_flutter_render.md`.
- Verification after this change:
  - PowerShell parser checks for changed scripts: OK;
  - `.\scripts\check_final_external_prereqs.ps1`: OK, not ready because Render
    URL and physical phone are missing;
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests`: `113/113 OK`;
  - `.\scripts\run_release_gate.ps1`: OK;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Important current warnings are expected:
  - temporary tunnel API is unavailable/expired;
  - permanent cloud phone readiness is false until a real Render HTTPS URL and
    cloud APK are verified;
  - physical phone smoke is skipped until a real authorized USB Android device
    is connected.
- Fresh artifact hashes from this update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161692591`, SHA256
    `5F6867FEB427497E10F1147FF8DF03C405DD9102D28753EA646B5B9CD9F8E89D`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2846447`,
    SHA256
    `D4D40B6F7226F9CCD5AFF97550BCC10C584D5C813521DABC535E4E7C27E8900D`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, size `1167`, SHA256
    `364EFA3134F582BD993B3B85C33356EBB1FB7C742F52B1B6262093D0D10804DE`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12862`,
    SHA256
    `4BC1DF01D4DB97A348DA65FA66A22A5C780B51E15AC23DACE1F182256F651CD5`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `876E2816D41C1462FB8391EAFB1AD848908F22F6C0294FA45BBA3AA4F02E3F7A`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7395`, SHA256
    `B304DDA2E7E28E8A7B175F987E7FD901ED470142C24024A304F253D004A575D5`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `5698`, SHA256
    `C2676430C9BA3CB0E316CDF4738709026B0A113E13AC4C4B3DD1B9061125452A`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `70050`, SHA256
    `6D2E1108D1D6104E3DF467C85370971529C714C8A3DB5063121D513C19CC66BA`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3198`, SHA256
    `84110D713F116508E7227BDF7A52A923964942E05022D82B9CAD6655426B28E8`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331899`, SHA256
    `824BE2C21482EB62E4018282433BB75AB21F06EAA3A8BAA195413B537A80C19B`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24491`, SHA256
    `B0DC78478E6990C99D6FE5857E3D3B0855F33F5CDA243E25A4226E70A1CEC2BB`;
  - internet APK verification JSON:
    `outputs\phone_download\PHONE_APK_VERIFICATION.json`, size `2316`,
    SHA256
    `40BAFBA627A4F65A370FC39FF0D3176EFC63954269CEFF8B57327F421ED265BD`;
  - LAN APK verification JSON:
    `outputs\phone_download\PHONE_LAN_APK_VERIFICATION.json`, size `2202`,
    SHA256
    `8AC1E5976DE5780C1B2383D191EAC440A5DDCB27BE5C63162BB3C3606B9EF340`.
- Remaining `8%` is still external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device and screenshot proof.
- This section supersedes older artifact hash blocks above.

## Update: Removed Remaining Hardcoded PowerShell Child Calls

- Replaced the last runtime `& powershell` child-script calls with
  `Get-ChildPowerShellCommand`:
  - `scripts\build_phone_for_lan.ps1`;
  - `scripts\smoke_phone_emulator.ps1`.
- Added structural tests proving both scripts use
  `$PowerShell = Get-ChildPowerShellCommand` and no longer contain
  `& powershell`.
- `rg` no longer finds `& powershell` / `powershell -NoProfile` in runtime
  `.ps1` scripts.
- Verification after this change:
  - PowerShell parser checks for changed scripts: OK;
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests`: `113/113 OK`;
  - `.\scripts\run_release_gate.ps1`: OK;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Submission verifier remains OK with expected external warnings:
  - temporary tunnel API is unavailable/expired;
  - permanent Render cloud phone readiness is false;
  - physical phone smoke is skipped until a real authorized USB Android device
    is connected.
- Fresh artifact hashes from this update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161692661`, SHA256
    `BF6C56ECFBAF4353FA858DF2774414F93DC40514DC058F6ECD5516927215FD14`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2846538`,
    SHA256
    `1CC3FE18712F0391FD3516D9D40FB59BA2C9A0E77CDD34B44CDEB0BB600821CF`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, size `1167`, SHA256
    `7B60BA53AC495A40CD4A61DF093DC36329725D79D818631C0E9CC9B7BA410449`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12860`,
    SHA256
    `597CE7EDC869F1339287AE0BF1767A52BBF3BDB6AA8D705626E20FF78B9126EC`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `3E72A42155543D65ABA7C04581911010F56FD63D4C816A92ACD3A24E77EE5860`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7395`, SHA256
    `CD6D67FD73976F6945F04EF98D712EEEC01D06D9607836BD6B9D1E35FE10AB10`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `70050`, SHA256
    `E469A3399CD276A0010D7813F4E2E1D732DE11930FA7AA54B3F33093C9CD9E59`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3198`, SHA256
    `CAF6E816CE80D7E5E7EF0A3DABDAC91F760DED94AF711D25A4B4BE3675842A4B`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331899`, SHA256
    `824BE2C21482EB62E4018282433BB75AB21F06EAA3A8BAA195413B537A80C19B`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24491`, SHA256
    `E79B00EB91D9F12D2784DBABDFDED6B495ED77D8B9388C18AF1BB128349E7539`.
- Remaining `8%` is still external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device and screenshot proof.
- This section supersedes older artifact hash blocks above.

## Update: Finalizer And Goal Audit Require Effective Cloud Status

- Tightened `scripts\finalize_cloud_phone_submission.ps1`:
  - `Get-FinalEvidence` now reads
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json` and
    `outputs\phone_download\PHONE_CLOUD_APK_VERIFICATION.json`;
  - final evidence now requires:
    - `cloud_status_outcome_ready=True`;
    - `cloud_status_verification_ok=True`;
    - `cloud_status_readiness_ok=True`;
    - `cloud_status_ready_to_publish=True`;
    - `cloud_apk_release_mode=True`;
  - the final report now includes these fields and the
    `cloud_deployment_status_json` artifact.
- Tightened `scripts\audit_project_goal_completion.ps1`:
  - `phone_permanent_cloud` now requires cloud APK verification `ok=True`,
    release mode, API OK, embedded API URL, current Flutter source stamp,
    cloud deployment `outcome=permanent_cloud_phone_ready`,
    `verification_ok=True`, `readiness_ok=True`, and
    `cloud_apk_verification_status.ready_to_publish=True`;
  - the audit now prints those proof bits explicitly in the
    `phone_permanent_cloud` requirement evidence.
- Updated docs/report:
  - `README.md`
  - `RUNBOOK.md`
  - `docs\mobile_flutter_render.md`
  - `docs\report\verity_lens_report.tex`
- Updated structural tests in `tests\test_factcheck_core.py`.
- Verification after this change:
  - PowerShell parser check for `finalize_cloud_phone_submission.ps1` and
    `audit_project_goal_completion.ps1`: OK;
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests`: `113/113 OK`;
  - `.\scripts\build_report.ps1`: OK, PDF rebuilt; only underfull hbox/fontconfig warnings;
  - `.\scripts\run_release_gate.ps1`: OK;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Current goal audit evidence for `phone_permanent_cloud` now explicitly says:
  - `Permanent cloud phone readiness: False`;
  - `Cloud APK verification OK: False`;
  - `Cloud APK release mode: False`;
  - `Cloud APK API OK: False`;
  - `Cloud APK embedded API URL: False`;
  - `Cloud APK source current: False`;
  - `Cloud deployment outcome: awaiting_public_https_backend`;
  - `Cloud deployment verification OK: False`;
  - `Cloud deployment readiness OK: False`;
  - `Cloud deployment ready to publish: False`.
- Current bundled `cloud\CLOUD_DEPLOYMENT_STATUS.json` still correctly reports:
  - `requested_outcome=awaiting_public_https_backend`;
  - `outcome=awaiting_public_https_backend`;
  - `cloud_apk_verification_status.ready_to_publish=False`;
  - `verification_ok=False`;
  - `readiness_ok=False`.
- Fresh artifact hashes from this update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161688062`, SHA256
    `3A7862FCACBDB60B6EDDBBAFF83A14090606F7709D881F4B2324AE4102EA8E94`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2843294`,
    SHA256
    `983D4E11E7CE5F5849563A0C24D3D10A1A4CE21D14B1AE28898955A23AF8CCCC`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, warnings `2`, size `791`, SHA256
    `86BF4EAF38714CD9E5CE80A307C11F52054C507273DD3BC7A3FE64C9590D5AD2`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12591`,
    SHA256
    `C8591F85E4E927636DF0956F34ABC5D49CB752F8311D0951A5CD44E394C20412`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `8FEED1926BEC76016D8932C22DAAAF573B45E60E9D3C950FCD2FB62EA26EA339`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7394`, SHA256
    `6D3CCE2F167FB9EE8904935556CA55BD9624E954F4C34DBA8263457C95F2B9DA`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `69803`, SHA256
    `644C684F158818303A4BF71034CB39BE73A91229E98309E7AE757B2A56555D0A`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3198`, SHA256
    `6F3FDA73B108A55B0D761F96DE9791035FF6E5E38D561819FDD118FCFD7DB6F6`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331614`, SHA256
    `E2D1EA1A911B986146A44C674D5DFB8EA5122F7A4A844C426D23BB76BBA9B1CF`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24398`, SHA256
    `4A15E2A6732D0ACD53423ACB3DDF1717B3F474E3821F391E31852D906B50A5EF`.
- Remaining `8%` is unchanged and external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device and screenshot proof.
- This section supersedes older artifact hash blocks above.

## Update: Cloud Deployment Status Derives Readiness From Verification JSON

- Tightened `scripts\write_cloud_deployment_status.ps1` so
  `CLOUD_DEPLOYMENT_STATUS.json` no longer trusts wrapper booleans alone.
  It now parses `PHONE_CLOUD_APK_VERIFICATION.json` and records
  `cloud_apk_verification_status` with:
  - `verification_json_ok`;
  - `api_ok`;
  - `expected_mode`;
  - `release_mode`;
  - `embedded_api_url_found`;
  - `flutter_source_stamp_sidecar_exists`;
  - `flutter_source_stamp_matches_current_source`;
  - `status_file_matches_flutter_source_stamp`;
  - `ready_to_publish`.
- The status now keeps both requested and effective booleans:
  - `verification_requested_ok` / `readiness_requested_ok`;
  - effective `verification_ok` / `readiness_ok`.
- If `permanent_cloud_phone_ready` is requested but the verification JSON is
  missing, stale, non-release, not API-verified, or not source-current, the
  status is downgraded to `outcome=failed` with an explicit error.
- `scripts\verify_submission_bundle.ps1` now cross-checks cloud deployment
  status against bundled cloud APK verification/readiness evidence. It fails if
  status claims verification/readiness without release-mode, source-current,
  publish-ready cloud APK evidence.
- Updated docs/report:
  - `README.md`
  - `RUNBOOK.md`
  - `docs\mobile_flutter_render.md`
  - `docs\report\verity_lens_report.tex`
- Updated structural tests in `tests\test_factcheck_core.py`.
- Verification after this change:
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests`: `113/113 OK`;
  - `.\scripts\build_report.ps1`: OK, PDF rebuilt; only underfull hbox/fontconfig warnings;
  - `.\scripts\run_release_gate.ps1`: OK;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Current bundled `cloud\CLOUD_DEPLOYMENT_STATUS.json` correctly reports:
  - `requested_outcome=awaiting_public_https_backend`;
  - `outcome=awaiting_public_https_backend`;
  - `cloud_apk_verification_status.ready_to_publish=False`;
  - `verification_requested_ok=False`;
  - `readiness_requested_ok=False`;
  - `verification_ok=False`;
  - `readiness_ok=False`.
- Fresh artifact hashes from this update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161686199`, SHA256
    `6D803B5E566EB8E90235AE06F6FA8A1BE4B76DB96E604CBE19634C6365CBB8D9`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2842118`,
    SHA256
    `1F91B0FABCF62242005EDBA2054986C4D9D8920008B3D83DED69833482BE66C5`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, warnings `2`, size `791`, SHA256
    `6C83A1594499F04973BA083F9933D2B5CB8AF8F89FD5CD5F62AB9D2F592B2699`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12592`,
    SHA256
    `1D8F3D9185EAFC1CA274F869D281AF90A1A7539AD2EBA06DE22369696D728614`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `4AE41082DC8AD1924A38BC77398E1D997A855D7F38802F5A41235A7FEB8753DC`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7069`, SHA256
    `10DDC9F6CA02FD9817492733F88DDC98D1695735F22086950D83B7433E6CAB4E`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `69530`, SHA256
    `F9E7DE341150A4FD805FF6722BE91545EE5FA44A9189C140DB8C81A9AF1FF30E`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3198`, SHA256
    `3D23F67D7BED67B14A7E78AEF968721B38BB2E7B842849CF396329C24A5CA6D7`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331524`, SHA256
    `BD1EAB63240B50C8A16A83A9DD42C1221198A630C4C09B5CEBF2ECF95F3E9B98`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24398`, SHA256
    `C93A1B90E0CB898E3E8C26334EFDDD6133FA2F7392268DE8A5962152F2BD9BCB`.
- Remaining `8%` is unchanged and external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device and screenshot proof.
- This section supersedes older artifact hash blocks above.

## Update: Final Wrapper Requires Physical Device Evidence

- Tightened `scripts\finalize_cloud_phone_submission.ps1` so the final
  evidence check cannot pass with only a generic device smoke result.
- `Get-FinalEvidence` now records and `Assert-FinalEvidenceReady` requires:
  - `phone_device_requires_physical`;
  - `phone_device_selected_id`;
  - `phone_device_selected_physical`;
  - `phone_device_screenshot_sha256_recorded`;
  - `phone_device_screenshot_sha256_matches`.
- The final JSON/Markdown report now includes the selected phone serial,
  physical-device requirement, non-emulator proof, and screenshot SHA256 match.
- Updated structural tests in `tests\test_factcheck_core.py`.
- Updated documentation/report:
  - `docs\mobile_flutter_render.md`;
  - `docs\report\verity_lens_report.tex`.
- Verification after this change:
  - PowerShell parser check for finalizer/audit/verifier: OK;
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests`: `113/113 OK`;
  - `.\scripts\build_report.ps1`: OK, PDF rebuilt; only underfull hbox/fontconfig warnings;
  - `.\scripts\run_release_gate.ps1`: OK;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Submission verifier remains OK with two expected warnings:
  - permanent cloud phone readiness is false until a real Render HTTPS URL and
    cloud APK are verified;
  - phone device smoke is skipped until run with
    `-RequireDevice -RequirePhysicalDevice` on a connected Android phone.
- Fresh artifact hashes from this update:
  - submission ZIP: `outputs\submission\VerityLens-submission.zip`, size
    `161689153`, SHA256
    `0D1B1C5D3DBF0A10988317E10AC1FE747974AF11EFECB3C25D4951B23454D817`;
  - source ZIP: `outputs\submission\verity-lens-source.zip`, size `2844011`,
    SHA256
    `3B8E3351715AF674654D4EA5D6CA83852197635B9DC4176663A7618C88720BE2`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, warnings `2`, size `791`, SHA256
    `D572B06ECB857FAA0A7B835F1007E8C4291161A0E7E7EC56EC3AB873CC79DF3C`;
  - release gate JSON: `reports\release_gate_latest.json`, size `12591`,
    SHA256
    `41C49C519AE800D82C56292AA78D4E0AF58E1B8C82AACE59B03513798BEFBE02`;
  - product acceptance JSON: `reports\product_acceptance_latest.json`, size
    `37767`, SHA256
    `800F5D6CB501465FAF0730ADBC467D94227DD4AEDF8FF0AB5F1707AFD946D2AB`;
  - goal completion audit JSON:
    `reports\goal_completion_audit_latest.json`, size `7394`, SHA256
    `F24ACC2F31AF187BCCCABD7997142851E345DCF1E26F842837CD69B185138C59`;
  - university report PDF: `docs\report\verity_lens_report.pdf`, size
    `70050`, SHA256
    `B331CDD223AE31DFF2C81F60163579CD50F66AE01B4CE495523574500A616B22`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3198`, SHA256
    `B0E1F02172FE502619CD0F11E30CCCB80B6EDB22B9EA6A5FA328315EFAA1379B`;
  - Render backend ZIP: `outputs\cloud_deploy\verity-lens-render-backend.zip`,
    size `1331614`, SHA256
    `E2D1EA1A911B986146A44C674D5DFB8EA5122F7A4A844C426D23BB76BBA9B1CF`;
  - phone readiness JSON: `outputs\phone_download\phone_readiness.json`, size
    `24398`, SHA256
    `7A10233FA9A264298AE3991078D04E26939F31172F0638DD55FAE28C285893BD`.
- Remaining `8%` is still external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device and screenshot proof.
- This section supersedes older artifact hash blocks above.

## Update: Removed Remaining Hardcoded PowerShell Child Calls (Tail Copy)

- Replaced the last runtime `& powershell` child-script calls with `Get-ChildPowerShellCommand` in:
  - `scripts\build_phone_for_lan.ps1`;
  - `scripts\smoke_phone_emulator.ps1`.
- Parser checks: OK; tests: `113/113 OK`; release gate: OK; submission bundle: OK; verifier: OK; audit: `complete=False`, estimated `92%`, remaining `8%`.
- Fresh key hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161692661`, SHA256 `BF6C56ECFBAF4353FA858DF2774414F93DC40514DC058F6ECD5516927215FD14`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2846538`, SHA256 `1CC3FE18712F0391FD3516D9D40FB59BA2C9A0E77CDD34B44CDEB0BB600821CF`;
  - release gate JSON `reports\release_gate_latest.json`: size `12860`, SHA256 `597CE7EDC869F1339287AE0BF1767A52BBF3BDB6AA8D705626E20FF78B9126EC`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7395`, SHA256 `CD6D67FD73976F6945F04EF98D712EEEC01D06D9607836BD6B9D1E35FE10AB10`.
- Remaining `8%` is still external/stateful: permanent Render HTTPS backend, release cloud APK verified against it, and authorized physical Android USB screenshot proof.
- This tail copy supersedes older artifact hash blocks above.

## Update: LAN API Evidence Added To Release Gate (Tail Copy)

- Tightened same-Wi-Fi phone evidence in the release/submission path.
- `scripts\run_release_gate.ps1` now records `summaries.lan_api_server`
  in `reports\release_gate_latest.json`, including:
  - port;
  - health URL;
  - healthy flag;
  - PID and PID-running flag;
  - stdout/stderr log paths.
- `scripts\verify_submission_bundle.ps1` now requires the release gate LAN
  API summary to exist, be healthy, and include port plus health URL.
- Updated docs/tests:
  - `README.md`;
  - `RUNBOOK.md`;
  - `tests\test_factcheck_core.py`.
- Verification after this change:
  - release gate: OK, generated `2026-05-30T12:39:34+02:00`;
  - release gate LAN API summary: healthy `True`, port `8001`,
    health URL `http://127.0.0.1:8001/health`, PID running `True`;
  - release gate steps: `19`, includes `LAN API server` and
    `LAN APK verification`;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Fresh key hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size
    `161693435`, SHA256
    `23F1A45924B89CF67CE4B256A80BC77FD5170ABA5CE514E9D214DBD946C3B621`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2847035`,
    SHA256
    `758F6C3CD0D7B306055EFDDE1D9347D784F077B859279848F6180C63DFD7127B`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, warnings `5`, size `1167`, SHA256
    `013B4858BC2ECAFAEBFC103DF185BB07DFBE130D686B20A9C98207D05FEE0C80`;
  - release gate JSON `reports\release_gate_latest.json`: size `13519`,
    SHA256
    `42C3BAEDF8E6EA27E67940E5FF51F517F60A396462922F0C3DDF801CF59966D2`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size
    `7395`, SHA256
    `E5E523CDB841475187A639E8600B46A9413AD2A23A9B1F821705FD567F8E39D1`;
  - product acceptance JSON `reports\product_acceptance_latest.json`: size
    `37767`, SHA256
    `83C28D3C43C031B88431E7EFDAB1F68C01D80D20AA7D011CDC721DEA7CD2B311`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size
    `70049`, SHA256
    `A547FE5E898C810F3CDC6022E0DE6E7848118BFD41031218D5AD372AD374E098`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3198`,
    SHA256
    `5B5EDA2BA0C90B4B9C37C2A51DB1AED26314EABFA91341653C96B4B908367320`;
  - Render backend ZIP `outputs\cloud_deploy\verity-lens-render-backend.zip`:
    size `1331942`, SHA256
    `4E2F36A01DB8C4CBF8F73BAD86B74C64A1BC6BF754ED640E81AA50E6B4B78AAA`;
  - phone readiness JSON `outputs\phone_download\phone_readiness.json`: size
    `24491`, SHA256
    `299AF002043043887C164F2C54C556FBDACBBE11988D6EF87378D46A5267A67E`.
- Remaining `8%` is still external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device and screenshot proof.
- This tail copy supersedes older artifact hash blocks above.

## Latest EOF State: Render Deploy Config Verification (Authoritative Tail)

- Most recent completed change: added `scripts\verify_render_deploy_config.py`
  and wired it into release gate, submission bundle, submission verifier,
  source bundle, README, RUNBOOK, LaTeX report, and tests.
- Current release gate: OK, generated `2026-05-30T13:00:12+02:00`,
  `20` steps, includes `Render deploy config verification`.
- Render deploy config report: OK, `reports\render_deploy_config_latest.json`,
  SHA256 `180ABB9883327A2087199C6FD06864E2C54187AF7A6DA248AEA4470D41BAF3FA`.
- Current submission verifier: OK, failures `0`, warnings `6`, ZIP entries
  `46`; ZIP includes `quality/render_deploy_config_latest.md/json` and
  `final/final_external_preflight_latest.md/json`.
- Current audit: `complete=False`, estimated `92%`, remaining `8%`.
- Fresh artifact hashes:
  - submission ZIP: size `161704809`, SHA256
    `BAC0A1FBF3E1A60776E10EF0D2584358F991E151235711430FA46D7BF1062211`;
  - source ZIP: size `2851627`, SHA256
    `B3D2F96EF4E6B1EF4516C85FB93914D233F91335F557D5131F9764922B7C432C`;
  - release gate JSON: size `14431`, SHA256
    `61E2B6EEBFFAF7572AD3E575B4C107E8399DD51485B81786FA62A1BB24832956`;
  - goal audit JSON: size `7395`, SHA256
    `31E9939EE8E44B4E5AB40FBA2461E3E0FC76BB329E8D19A35E8A4EFBB2958585`;
  - report PDF: size `70064`, SHA256
    `BEBFA1B454BA6DDE745ECCA84BDB54DB243BBC1FC4697A463D2B9685C2320231`.
- Still remaining external proof:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB screenshot proof.

## Latest EOF State: Physical Phone Identity Proof Tightened (Authoritative Tail)

- Most recent completed change: strengthened physical Android final proof.
- `scripts\smoke_phone_on_device.ps1` now records ADB device identity when a
  device is selected: manufacturer, model, product/device, Android version,
  SDK, hardware, `ro.kernel.qemu`, and serial number.
- A successful phone-device smoke now requires package install, launch,
  foreground package match, screenshot SHA256, and recorded device identity.
- Submission verifier, final cloud phone wrapper, final external preflight, and
  goal audit now require/track `phone_device_identity_recorded`.
- Verification after this change:
  - parser checks for changed PowerShell scripts: OK;
  - tests: `113/113 OK`;
  - final external preflight: report written, not ready because Render URL and
    authorized physical Android device are missing;
  - release gate: OK, generated `2026-05-30T13:10:00+02:00`, `20` steps;
  - submission verifier: OK, failures `0`, warnings `6`, ZIP entries `46`;
  - audit: `complete=False`, estimated `92%`, remaining `8%`.
- Fresh artifact hashes:
  - submission ZIP: size `161706745`, SHA256
    `5E635D3EE71334709ACDF2727C1E78FAFBCF794D4427F27F02472C1F654871A6`;
  - source ZIP: size `2852769`, SHA256
    `4761F95281C3833592B72F7DFEE9B43672A5BD9270C4CAF2A55064A27E22BF37`;
  - release gate JSON: size `14428`, SHA256
    `56DBC5F96CBF61E4214E8D5D30F942210169860BD0A653CB87574C225C31D1CE`;
  - goal audit JSON: size `7439`, SHA256
    `FB50C75B4EB64462C8AADDD888B6AA0247FA66E8AE5802FD7E475D71B330145D`;
  - final preflight JSON: size `5740`, SHA256
    `DDBC86769B2CDEBE2BFF98AA769393A31EE58DC8261D1F5016CFC0DFA763AFD2`;
  - report PDF: size `70210`, SHA256
    `C4EB9164F0DB1D1E1546BE84B3930FF2CC5C3B6499C03F5A040537FBFA37D6CA`.
- Still remaining external proof:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device with screenshot and identity proof.

## Latest EOF State: Physical Phone Identity Proof Tightened (Authoritative Tail)

- Most recent completed change: strengthened physical Android final proof.
- `scripts\smoke_phone_on_device.ps1` now records ADB device identity when a
  device is selected:
  - manufacturer;
  - model;
  - product/device;
  - Android version;
  - SDK;
  - hardware;
  - `ro.kernel.qemu`;
  - serial number.
- A successful phone-device smoke now requires:
  - package `app.veritylens.mobile` installed;
  - launch started;
  - foreground matched package;
  - screenshot captured with SHA256;
  - device identity recorded.
- `scripts\verify_submission_bundle.ps1` now fails an OK device smoke if
  physical-device identity is missing or incomplete.
- `scripts\finalize_cloud_phone_submission.ps1`,
  `scripts\check_final_external_prereqs.ps1`, and
  `scripts\audit_project_goal_completion.ps1` now include/require
  `phone_device_identity_recorded`.
- Updated docs/tests:
  - `README.md`;
  - `RUNBOOK.md`;
  - `docs\mobile_flutter_render.md`;
  - `docs\report\verity_lens_report.tex`;
  - `tests\test_factcheck_core.py`.
- Verification after this change:
  - parser checks for changed PowerShell scripts: OK;
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests`: `113/113 OK`;
  - `.\scripts\check_final_external_prereqs.ps1`: OK report written, still not
    ready because Render URL and authorized physical Android device are missing;
  - final external preflight physical contract includes
    `phone_device_identity_recorded`;
  - `.\scripts\run_release_gate.ps1`: OK, generated
    `2026-05-30T13:10:00+02:00`, `20` steps;
  - product acceptance: `93/93`, pass rate `100%`;
  - render deploy config summary: OK;
  - LAN API summary: healthy `True`;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK, failures `0`,
    warnings `6`, ZIP entry count `46`;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Fresh key hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size
    `161706745`, SHA256
    `5E635D3EE71334709ACDF2727C1E78FAFBCF794D4427F27F02472C1F654871A6`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2852769`,
    SHA256
    `4761F95281C3833592B72F7DFEE9B43672A5BD9270C4CAF2A55064A27E22BF37`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, warnings `6`, size `1314`, SHA256
    `D220224955F811F9436FE604DE51E788C722A355CAB822C5ED441B0E09B19D12`;
  - release gate JSON `reports\release_gate_latest.json`: size `14428`,
    SHA256
    `56DBC5F96CBF61E4214E8D5D30F942210169860BD0A653CB87574C225C31D1CE`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size
    `7439`, SHA256
    `FB50C75B4EB64462C8AADDD888B6AA0247FA66E8AE5802FD7E475D71B330145D`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `5740`, SHA256
    `DDBC86769B2CDEBE2BFF98AA769393A31EE58DC8261D1F5016CFC0DFA763AFD2`;
  - render deploy config JSON `reports\render_deploy_config_latest.json`:
    size `4963`, SHA256
    `A3D18E6B39135E07699496D913BF793B4F11E41618CEEDC2DAFDC31BB4FED93E`;
  - product acceptance JSON `reports\product_acceptance_latest.json`: size
    `37767`, SHA256
    `BF3D7083E8457990D0C71579021E3054349F9E4159CA66D492C4B7760C9E3734`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size
    `70210`, SHA256
    `C4EB9164F0DB1D1E1546BE84B3930FF2CC5C3B6499C03F5A040537FBFA37D6CA`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3198`,
    SHA256
    `AAA18B08D028466484F38656492FD380B386063FB4AD7C188DA2CE0C494400DD`;
  - Render backend ZIP `outputs\cloud_deploy\verity-lens-render-backend.zip`:
    size `1332196`, SHA256
    `F2FDA66993900BB651298736E187C1E26AD6B73BD167D4E0721E40D21464F20E`;
  - phone readiness JSON `outputs\phone_download\phone_readiness.json`: size
    `24781`, SHA256
    `D39B74680482F5A320AA8223DD9B9C64841E97DF5EA64D5E19B69C3EC028AC4A`.
- Remaining `8%` is still external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device with screenshot and identity proof.

## Update: Render Deploy Config Verification Added (Tail Copy)

- Added `scripts\verify_render_deploy_config.py`.
- The new verifier writes:
  - `reports\render_deploy_config_latest.json`;
  - `reports\render_deploy_config_latest.md`.
- It validates the permanent Render deploy surface before a public deploy:
  - `render.yaml` parses and defines a Docker web service;
  - service points to `./Dockerfile`;
  - health check path is `/health`;
  - required Render env vars are present;
  - Dockerfile uses `requirements.api.txt`;
  - Dockerfile starts `src.api_factcheck:app`;
  - Dockerfile uses Render `$PORT` with `8001` fallback;
  - `.dockerignore` excludes generated, desktop, mobile, report, and large
    binary artifacts;
  - `requirements.api.txt` includes API dependencies and excludes
    desktop/training packages.
- Integrated this into:
  - `scripts\run_release_gate.ps1` as step `Render deploy config verification`;
  - `scripts\make_submission_bundle.ps1` as required quality artifacts;
  - `scripts\verify_submission_bundle.ps1` as required bundle checks;
  - `scripts\make_source_bundle.ps1` as a required source entry.
- Updated docs/tests/report:
  - `README.md`;
  - `RUNBOOK.md`;
  - `docs\report\verity_lens_report.tex`;
  - `tests\test_factcheck_core.py`.
- Verification after this change:
  - `.\.venv\Scripts\python.exe scripts\verify_render_deploy_config.py`: OK;
  - parser checks for changed PowerShell scripts: OK;
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests`: `113/113 OK`;
  - `.\scripts\run_release_gate.ps1`: OK, generated
    `2026-05-30T13:00:12+02:00`, `20` steps;
  - release gate render config summary: OK, health path `/health`;
  - product acceptance: `93/93`, pass rate `100%`;
  - Render bundle smoke: OK;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK, failures `0`,
    warnings `6`, ZIP entry count `46`;
  - submission ZIP includes:
    - `quality/render_deploy_config_latest.md/json`;
    - `final/final_external_preflight_latest.md/json`;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Fresh key hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size
    `161704809`, SHA256
    `BAC0A1FBF3E1A60776E10EF0D2584358F991E151235711430FA46D7BF1062211`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2851627`,
    SHA256
    `B3D2F96EF4E6B1EF4516C85FB93914D233F91335F557D5131F9764922B7C432C`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, warnings `6`, size `1314`, SHA256
    `371E67C5EECFF81B32B9293704E518BC84BF75C993C353F359B9EC5B5B3EC258`;
  - release gate JSON `reports\release_gate_latest.json`: size `14431`,
    SHA256
    `61E2B6EEBFFAF7572AD3E575B4C107E8399DD51485B81786FA62A1BB24832956`;
  - Render deploy config JSON `reports\render_deploy_config_latest.json`:
    size `4963`, SHA256
    `180ABB9883327A2087199C6FD06864E2C54187AF7A6DA248AEA4470D41BAF3FA`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size
    `7395`, SHA256
    `31E9939EE8E44B4E5AB40FBA2461E3E0FC76BB329E8D19A35E8A4EFBB2958585`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `5699`, SHA256
    `60A1DB3535F361B981566253BB77B0599BD4C03B7804572A7B74B00558D466C3`;
  - product acceptance JSON `reports\product_acceptance_latest.json`: size
    `37767`, SHA256
    `5D68E86E09014C2A7C864C074D1F8E4A1E23E8F96CF3E010C8E54BD38F43BBFC`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size
    `70064`, SHA256
    `BEBFA1B454BA6DDE745ECCA84BDB54DB243BBC1FC4697A463D2B9685C2320231`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3198`,
    SHA256
    `7BC57943A466236E6801DA70297914A1D52391D0726ED5AF88C4D3447C843491`;
  - Render backend ZIP `outputs\cloud_deploy\verity-lens-render-backend.zip`:
    size `1332103`, SHA256
    `9C8384A6C41FFAAC05628E46B29D4C6686617D4DEAB00F11B3D5A9EDF441A7CA`;
  - phone readiness JSON `outputs\phone_download\phone_readiness.json`: size
    `24491`, SHA256
    `93B36E9F798AD96B1D1C2BDCF54ED02B2DBE252B6BEABFA844C952FEF3EF33F9`.
- Remaining `8%` is still external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device and screenshot proof.
- This tail copy supersedes older artifact hash blocks above.

## Update: Final External Preflight Included In Submission Bundle (Tail Copy)

- Added final external preflight artifacts to the submission package when they
  exist:
  - `reports\final_external_preflight_latest.md` ->
    `final\final_external_preflight_latest.md`;
  - `reports\final_external_preflight_latest.json` ->
    `final\final_external_preflight_latest.json`.
- `scripts\verify_submission_bundle.ps1` now checks that the preflight md/json
  pair is not partial, requires the JSON to include the finalizer command and
  final evidence contract, and warns when the preflight says the finalizer is
  not ready.
- Updated docs/tests:
  - `README.md`;
  - `RUNBOOK.md`;
  - `tests\test_factcheck_core.py`.
- Generated the current preflight without `-RequireReady`; it reports:
  - ready to run finalizer: `False`;
  - missing: `real public HTTPS Render API URL, authorized physical USB Android device`;
  - finalizer command:
    `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`.
- Verification after this change:
  - parser checks for changed PowerShell scripts: OK;
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests`: `113/113 OK`;
  - `.\scripts\run_release_gate.ps1`: OK, generated
    `2026-05-30T12:49:28+02:00`, `19` steps;
  - product acceptance: `93/93`, pass rate `100%`;
  - release gate LAN API summary: healthy `True`,
    `http://127.0.0.1:8001/health`;
  - Render bundle smoke: OK;
  - `.\scripts\make_submission_bundle.ps1`: OK;
  - `.\scripts\verify_submission_bundle.ps1`: OK, failures `0`,
    warnings `6`, ZIP entry count `44`;
  - submission ZIP includes `final/final_external_preflight_latest.md/json`;
  - `.\scripts\audit_project_goal_completion.ps1`: `complete=False`,
    estimated `92%`, remaining `8%`.
- Fresh key hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size
    `161697798`, SHA256
    `728BB477F2069EA8AA9C3A999EF78B9A3C45E51226884D3640DEB919A596E70D`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2847587`,
    SHA256
    `3808409E86C01DB031C29A4EE630477CAD13B669BD5C3879E14629413C694B34`;
  - submission verification JSON:
    `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`, OK `True`,
    failures `0`, warnings `6`, size `1314`, SHA256
    `FF1159E2D2582B0B309CD041B478EAE05CA5BFE5100AC215CB3539CBF5D583BF`;
  - release gate JSON `reports\release_gate_latest.json`: size `13523`,
    SHA256
    `E123FBE58E37EBF92DA3969CF19173E9BB6D597CB29A3306076FDEC9861051D6`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size
    `7395`, SHA256
    `901F8C55031B4E8CA1C0CAD1EE912EAAE26E8D92843D96352A72C53B3507FEDF`;
  - final external preflight JSON:
    `reports\final_external_preflight_latest.json`, size `5699`, SHA256
    `60A1DB3535F361B981566253BB77B0599BD4C03B7804572A7B74B00558D466C3`;
  - product acceptance JSON `reports\product_acceptance_latest.json`: size
    `37767`, SHA256
    `52464503666869DB559B4DD11A1A1BFC7CA3C0309322BB9F94BB6F992CDD14C9`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size
    `70050`, SHA256
    `EE9E7D58BABE22DFC2D3C6DD6FD63FD8207ED3006309117C5B802E6995A48CB4`;
  - cloud deployment status JSON:
    `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`, size `3198`,
    SHA256
    `5E751D414674BFA53EFFE54F0E70BA074E8F425ACA052952D598434F98785C41`;
  - Render backend ZIP `outputs\cloud_deploy\verity-lens-render-backend.zip`:
    size `1332001`, SHA256
    `145EFE014CA6BC41056A4C35D2F0067F8B0C7DE60FB5DDCE283D4B3BA7079521`;
  - phone readiness JSON `outputs\phone_download\phone_readiness.json`: size
    `24491`, SHA256
    `C7AC29AC653DB45DE3F1AD06DB38FCC68A2A7A6F0BF7D5CDB847B5B57EE7758D`.
- Remaining `8%` is still external/stateful:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB device and screenshot proof.
- This tail copy supersedes older artifact hash blocks above.

## Latest EOF State: Render Deploy Config Verification (Authoritative Tail)

- Most recent completed change: added `scripts\verify_render_deploy_config.py`
  and wired it into release gate, submission bundle, submission verifier,
  source bundle, README, RUNBOOK, LaTeX report, and tests.
- Current release gate: OK, generated `2026-05-30T13:00:12+02:00`,
  `20` steps, includes `Render deploy config verification`.
- Render deploy config report: OK, `reports\render_deploy_config_latest.json`,
  SHA256 `180ABB9883327A2087199C6FD06864E2C54187AF7A6DA248AEA4470D41BAF3FA`.
- Current submission verifier: OK, failures `0`, warnings `6`, ZIP entries
  `46`; ZIP includes `quality/render_deploy_config_latest.md/json` and
  `final/final_external_preflight_latest.md/json`.
- Current audit: `complete=False`, estimated `92%`, remaining `8%`.
- Fresh artifact hashes:
  - submission ZIP: size `161704809`, SHA256
    `BAC0A1FBF3E1A60776E10EF0D2584358F991E151235711430FA46D7BF1062211`;
  - source ZIP: size `2851627`, SHA256
    `B3D2F96EF4E6B1EF4516C85FB93914D233F91335F557D5131F9764922B7C432C`;
  - release gate JSON: size `14431`, SHA256
    `61E2B6EEBFFAF7572AD3E575B4C107E8399DD51485B81786FA62A1BB24832956`;
  - goal audit JSON: size `7395`, SHA256
    `31E9939EE8E44B4E5AB40FBA2461E3E0FC76BB329E8D19A35E8A4EFBB2958585`;
  - report PDF: size `70064`, SHA256
    `BEBFA1B454BA6DDE745ECCA84BDB54DB243BBC1FC4697A463D2B9685C2320231`.
- Still remaining external proof:
  - permanent Render HTTPS backend;
  - release cloud APK built and verified against that backend;
  - authorized physical Android USB screenshot proof.

## Latest EOF State: Physical Phone Identity Proof Tightened (Authoritative Tail)

- Most recent completed change: strengthened physical Android final proof.
- `scripts\smoke_phone_on_device.ps1` now records ADB device identity when a device is selected: manufacturer, model, product/device, Android version, SDK, hardware, `ro.kernel.qemu`, and serial number.
- A successful phone-device smoke now requires package install, launch, foreground package match, screenshot SHA256, and recorded device identity.
- Submission verifier, final cloud phone wrapper, final external preflight, and goal audit now require/track `phone_device_identity_recorded`.
- Verification after this change: parser checks OK; tests `113/113 OK`; release gate OK at `2026-05-30T13:10:00+02:00` with `20` steps; submission verifier OK with failures `0`, warnings `6`, ZIP entries `46`; audit `complete=False`, estimated `92%`, remaining `8%`.
- Fresh hashes: submission ZIP `5E635D3EE71334709ACDF2727C1E78FAFBCF794D4427F27F02472C1F654871A6`; source ZIP `4761F95281C3833592B72F7DFEE9B43672A5BD9270C4CAF2A55064A27E22BF37`; release gate JSON `56DBC5F96CBF61E4214E8D5D30F942210169860BD0A653CB87574C225C31D1CE`; goal audit JSON `FB50C75B4EB64462C8AADDD888B6AA0247FA66E8AE5802FD7E475D71B330145D`; final preflight JSON `DDBC86769B2CDEBE2BFF98AA769393A31EE58DC8261D1F5016CFC0DFA763AFD2`; report PDF `C4EB9164F0DB1D1E1546BE84B3930FF2CC5C3B6499C03F5A040537FBFA37D6CA`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against it, and authorized physical Android USB device with screenshot and identity proof.

## Latest EOF State: Device Identity Contract Aligned (Authoritative Tail)

- Most recent completed change: aligned the physical Android identity contract across smoke, finalizer, verifier, and audit.
- `scripts\smoke_phone_on_device.ps1` now sets `device_identity.recorded=true` only when manufacturer, model, Android version, SDK, and hardware are all present. This matches `scripts\verify_submission_bundle.ps1`, which already required those fields for an OK physical-device smoke.
- `scripts\finalize_cloud_phone_submission.ps1` and `scripts\audit_project_goal_completion.ps1` now also require `device_identity.hardware` before accepting `phone_device_identity_recorded` / `DeviceSmokeIdentityRecorded`.
- Tests now assert that the phone smoke, goal audit, and final submission wrapper preserve the `ro.hardware` / `device_identity.hardware` part of the proof.
- Verification after this change:
  - PowerShell parser checks OK for changed scripts.
  - Unit tests: `113/113 OK`.
  - Final external preflight: not ready only because missing `real public HTTPS Render API URL` and `authorized physical USB Android device`.
  - Release gate OK, generated `2026-05-30T13:19:05+02:00`, `20` steps, product acceptance `93/93`.
  - Submission verifier OK, failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit: `complete=False`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161706794`, SHA256 `8918103F9F2156CDB1D1A266D9A8A07293B3F84A1B543AF75BF4C288614F2E77`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2852820`, SHA256 `FBE40EBC60D5F60FCE18E0C7EF6E06EEB71987FE2D568955F2CB409CD3232E54`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `93F4925053530B8068EB1B90D3E077133B24DD09B183CC752991E5D2C2F99A66`;
  - release gate JSON `reports\release_gate_latest.json`: size `14428`, SHA256 `18CD667C6CF86EE20B9FCA0C704CE68E5DE2C40B8DDA3B7DE87EABD8B949325B`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7439`, SHA256 `6FCF14DCB1593431CA38C84261340C55007FAC0F760DA27529200DA53FE7EE6F`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `5740`, SHA256 `A9AB6F7A543422FFD3EA4D1F6F814C3C5C37EEB41CDBC2D941A0BD153C65520E`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `70209`, SHA256 `7E629D1C6092A4BE5EFE9ADC1609449CEAB51220D04D6DB529EFA428AFB78AA8`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against it, and authorized physical Android USB device with screenshot and full identity proof.

## Latest EOF State: Goal Audit Requires Screenshot SHA Proof (Authoritative Tail)

- Most recent completed change: strengthened the goal audit's physical Android proof.
- `scripts\audit_project_goal_completion.ps1` now computes the SHA256 of `outputs\phone_download\PHONE_DEVICE_SCREENSHOT.png` and requires it to match `PHONE_DEVICE_SMOKE.json -> screenshot.sha256` before `physical_phone_proof` can pass.
- The physical phone evidence now explicitly reports:
  - screenshot file exists;
  - screenshot SHA256 recorded;
  - screenshot SHA256 matches file.
- `tests\test_factcheck_core.py` now asserts the goal audit keeps `DeviceScreenshotShaMatches`, `screenshot.sha256`, and the human-readable evidence line.
- Verification after this change:
  - PowerShell parser check OK for `scripts\audit_project_goal_completion.ps1`.
  - Unit tests: `113/113 OK`.
  - Final external preflight: not ready only because missing `real public HTTPS Render API URL` and `authorized physical USB Android device`.
  - Release gate OK, generated `2026-05-30T13:25:59+02:00`, `20` steps, product acceptance `93/93`.
  - Submission verifier OK, failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit: `complete=False`, estimated `92%`, remaining `8%`; physical phone evidence now includes `Screenshot SHA256 recorded: False` and `Screenshot SHA256 matches file: False` until a real USB phone smoke is run.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161706959`, SHA256 `C830B66ADB182E70C2234F0D673FD45524182389766EEF6306856B97F9BC36C1`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2852998`, SHA256 `156EB33D42FA4486C5528F63CC05DFA964119ED2C5E8B7996CDEF81F755C32A4`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `02EECF4BD71740C6FC6A64BAAD443090AF1C35DD8E2D5B4612DE6526476205BB`;
  - release gate JSON `reports\release_gate_latest.json`: size `14430`, SHA256 `4BF6B58418BD0D542374FA44210C3E345736A305F4659F6E00A90275498BA668`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7535`, SHA256 `99C4B1395DBBA2582616F421C0637D827C8B64060C81B142CA29A38C7A252342`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `5740`, SHA256 `F44F5950077D7B404238B12712354A8D1845BE2AA1402CF76F96DF8929C82A93`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `70210`, SHA256 `7681E13543C5C8BF255F26DE8F90B8DA0472C16B253AD961BB654CFB9EEBCAB3`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against it, and authorized physical Android USB device with screenshot, SHA256 match, and full identity proof.

## Latest EOF State: Cloud APK URL and Status Proof Tightened (Authoritative Tail)

- Most recent completed change: strengthened the permanent-cloud phone proof so temporary tunnels cannot satisfy the final phone requirement.
- `scripts\audit_project_goal_completion.ps1` now requires the cloud APK proof to use a permanent public HTTPS API URL, reject temporary tunnel URLs, find the embedded API URL, match it to the verified API base URL, and match the cloud status file's URL, mode, and current Flutter source stamp.
- `scripts\verify_submission_bundle.ps1` now independently enforces the same strict packaged `PHONE_CLOUD_APK_VERIFICATION.json` contract before accepting permanent cloud artifacts.
- `scripts\write_cloud_deployment_status.ps1` now records and reports `api_permanent_cloud_url`, `api_is_temporary_tunnel`, `embedded_api_expected_url`, `embedded_api_matches_base_url`, `status_file_matches_url`, and `status_file_matches_mode`; `ready_to_publish` requires those fields.
- `tests\test_factcheck_core.py` now asserts the stricter audit/verifier/status evidence strings and fields.
- Verification after this change:
  - PowerShell parser checks OK for changed scripts.
  - Unit tests: `113/113 OK`.
  - Release gate OK, generated `2026-05-30T13:33:04+02:00`, `20` steps, product acceptance `93/93`.
  - Submission verifier OK, failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit: `complete=False`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161708131`, SHA256 `F818A1382ED48AD44E95BB2D1585D4F75AFDB6A247A947D9BA93223F5AC011B3`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2854051`, SHA256 `4400AC92C705325B50438FF95224644C01AA0FFB44B6F5686E2F335938B0977C`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `724BF99809E9983C478638A09BFC744B18F724E0F11AB70E6608B5EC1524586C`;
  - release gate JSON `reports\release_gate_latest.json`: size `14429`, SHA256 `511E82CB451601253F70F9A514FA626939E8210AC4AC6856C4474BD72B5615F4`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7792`, SHA256 `84BAE24D7C01101A1AEC97F6170B229B852CDAA35F7EF8C0F7D55FBCB03A8F4A`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `5740`, SHA256 `10601E91AE22F01825F6175D4320DEE21EA613A68285BA0C5CB135F938C31112`;
  - cloud deployment status JSON `outputs\cloud_deploy\CLOUD_DEPLOYMENT_STATUS.json`: size `3504`, SHA256 `B6A162C159E18DB3DCE404CFC4B8CFF22DB20643C0B5F7FBC1F63BB52E61EB1E`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `70210`, SHA256 `E71E71965E72D0F3FF0AB914404DEF8109011A445DA2CCEE843F185DD6D71A97`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with screenshot, SHA256 match, and full identity proof.

## Latest EOF State: Finalizer Evidence and ADB Preflight Tightened (Authoritative Tail)

- Most recent completed change: strengthened the final external path without changing product behavior.
- `scripts\finalize_cloud_phone_submission.ps1` now carries the stricter permanent-cloud APK evidence into the final submission report itself: permanent public API URL, not temporary tunnel, requested URL match, embedded API URL found/matched, status-file URL/mode/source-stamp match, and release mode.
- `scripts\check_final_external_prereqs.ps1` now separates `adb_found` from `adb_accessible` and records the `adb devices` exit code, so sandbox/permission problems are distinguishable from a missing authorized phone.
- The preflight final evidence contract now lists the same strict cloud APK fields required by the finalizer.
- `tests\test_factcheck_core.py` now asserts these finalizer/preflight proof fields and ADB accessibility diagnostics.
- Verification after this change:
  - PowerShell parser checks OK for changed scripts.
  - Unit tests: `113/113 OK`.
  - Final external preflight was rerun outside the sandbox: `adb_found=true`, `adb_accessible=true`, `adb_devices_exit_code=0`, but no authorized physical USB Android device is connected.
  - Submission verifier OK, failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit: `complete=False`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161708997`, SHA256 `CE51765415C42811C93B12F5C5791C247E2CD29485FC7FDF42A4F930997E24CB`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2854878`, SHA256 `D596EB44366B8F71D4A59CBA4E46321934119F1A02359F827AEDA847D9A9674D`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `F6559780769FAE4F533DA00C3A628EB11819D739DC2127BA068FBEB22986CF09`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7792`, SHA256 `376F7F7073E24F31F37E1BC35A9EA6E65D06D94BD1B89BDBD17CF6309E57E344`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `5885`, SHA256 `73EF3F7499B04A9A800614AFC13DC782D9624B31F601715BF95DC91702B1F80F`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with screenshot, SHA256 match, and full identity proof.

## Latest EOF State: Full Release Gate Refreshed After Finalizer Changes (Authoritative Tail)

- Most recent completed action: reran the full release gate after the finalizer/preflight evidence changes, then regenerated final external preflight, submission bundle, submission verifier, and goal audit.
- Full release gate: OK, generated `2026-05-30T13:48:30+02:00`, `20` steps passed.
- Product acceptance remains `93/93`, pass rate `1.0`; sections remain facts `44/44`, news `15/15`, screenshots `12/12`, images `11/11`, API contract `11/11`.
- University PDF was rebuilt by the gate; `tectonic` emitted only layout/fontconfig warnings, not a failed build.
- Final external preflight was rerun outside the sandbox: `adb_found=true`, `adb_accessible=true`, `adb_devices_exit_code=0`, but no authorized physical USB Android device is connected.
- Submission verifier: OK, failures `0`, warnings `6`, ZIP entries `46`; warnings remain the expected external ones.
- Goal audit: `complete=False`, estimated `92%`, remaining `8%`; current external gaps are `phone_permanent_cloud` and `physical_phone_proof`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161709027`, SHA256 `034468BF99FCABEE21F5DDB3F1A19BEA1BA007BFD77F38FB06B46494187AB8BE`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2854878`, SHA256 `425A99CED5DFCB269A769E916C142B88F47E4E275542ACEAC79CA8138A5C09F2`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `A46A59910EAC42FE822DC56F3BAA7BBB4E7FF49438D3E037C4FBB974EEA02211`;
  - release gate JSON `reports\release_gate_latest.json`: size `14431`, SHA256 `0E92620B66653922A5FB58BF22D21D955F55F0413F942D63BB3AF42636C326E9`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7792`, SHA256 `39E14288941A50AE5BA25E79A2BBF06DB7B4DFD39D79CDB0CC9BC2298911839A`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `5885`, SHA256 `E5415F95B8B06D134FBAC608C12A9D4F39481DEA0936FA94301E4A434D3D585A`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `70210`, SHA256 `FBEBE290829D6989348B768F59015C40C6062247EAEC78233FEA2558F7B4712D`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with screenshot, SHA256 match, and full identity proof.

## Latest EOF State: Final Preflight Next Actions Added (Authoritative Tail)

- Most recent completed change: made the final external preflight more actionable for the remaining Render + USB steps.
- `scripts\check_final_external_prereqs.ps1` now writes machine-readable `next_actions` and a Markdown `Next Actions` section.
- The current preflight now says exactly to deploy the Render backend from `render.yaml` or `outputs\cloud_deploy\verity-lens-render-backend.zip`, rerun preflight with `-ApiBaseUrl https://<render-app>.onrender.com -RequireReady`, enable USB debugging on a real Android phone, accept the RSA prompt, verify `adb devices` shows state `device`, then run `.\scripts\finalize_cloud_phone_submission.ps1 -ApiBaseUrl 'https://<render-app>.onrender.com'`.
- ADB was checked outside the sandbox again: `adb_found=true`, `adb_accessible=true`, `adb_devices_exit_code=0`; no authorized physical USB Android device is currently connected.
- Verification after this change:
  - PowerShell parser check OK for `scripts\check_final_external_prereqs.ps1`.
  - Unit tests: `113/113 OK`.
  - Submission verifier OK, failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit: `complete=False`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161709792`, SHA256 `E648FA8442300959913376587912A61675777501EA5F51FF8BE0C06D73E0CBF4`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2855306`, SHA256 `846F88088FDBFE0B0167CC808EE02BC78E905287DB80544C035AB51E00105182`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `CD28E224A61010DA0DE1722D1561E8810CF0B9A154E9FDC0B9F9BECAB428BA6F`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7792`, SHA256 `13B2088C3CBD0AA2B8D99BD28FE908733FA93DDDA170845FCB184E5F5059E0C6`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6408`, SHA256 `010468471392989F4161259703676BF2B777CC538DBFC00F46413EF46E0E584B`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with screenshot, SHA256 match, and full identity proof.

## Latest EOF State: Submission Verifier Requires Fresh Release Gate (Authoritative Tail)

- Most recent completed change: strengthened `scripts\verify_submission_bundle.ps1` so a green release gate cannot be reused after key source/test/script changes.
- The verifier now reads timestamps from the nested `source/verity-lens-source.zip` and fails if `reports\release_gate_latest.json` is older than gated source entries under `src/`, `scripts/`, `tests/`, Flutter `lib/`/`test/`, Render config, requirements, Dockerfile, or the LaTeX report source.
- `tests\test_factcheck_core.py` now asserts this freshness contract via `Read-NestedZipEntryInfo`, `Test-GatedSourceEntry`, and the failure text `Release gate report is older than gated source entries`.
- Verification after this change:
  - PowerShell parser check OK for `scripts\verify_submission_bundle.ps1`.
  - Unit tests: `113/113 OK`.
  - Full release gate rerun after the verifier change: OK, generated `2026-05-30T14:02:20+02:00`, `20` steps passed, product acceptance `93/93`.
  - Final external preflight rerun outside the sandbox: ADB accessible, no authorized physical USB Android device connected.
  - Submission verifier OK with the new freshness check active: failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit: `complete=False`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161710296`, SHA256 `758E68E3F43A39D88FD5DCB2E4E25F2D45F1A8D823BFC16CCCE1A7924EE17C7C`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2855826`, SHA256 `8748F83142AE9BEA2C100C36474C1084E3A13C6B8969FC2816DF53627E41938B`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `7DC7BB53FC6A660D93F8A8E670368EA4260527EE3C4AE0D0D204A168285FAF0E`;
  - release gate JSON `reports\release_gate_latest.json`: size `14432`, SHA256 `0CCF460F33BD455F97A1F5F2DEDDE20B2F84174DCA35C7BC1DFFBF9582FFA3ED`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7792`, SHA256 `927836EA90221621D958538E07AFA944C3DEE661E37326129DC2BA583F6C9D80`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6408`, SHA256 `DA97041390FA80410D4E271E432813891062A00826F684EDB64C63C1EDE4A911`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `70210`, SHA256 `71C49EAD2C7380E67F71F4CB1FF1E3ABCF389E05BF17D348A8B3C08299ED1B47`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with screenshot, SHA256 match, and full identity proof.

## Latest EOF State: Physical Phone Smoke ADB Diagnostics Hardened (Authoritative Tail)

- Most recent completed change: hardened `scripts\smoke_phone_on_device.ps1`, the final physical USB phone proof script.
- Text ADB calls now use `System.Diagnostics.ProcessStartInfo` with captured stdout/stderr and explicit timeouts instead of direct PowerShell invocation; this mirrors the safer preflight ADB path.
- `adb install -r` gets a longer `180000` ms timeout, while ordinary ADB probes and screenshot capture keep bounded timeouts so the final wrapper cannot hang indefinitely on a bad USB/ADB state.
- `PHONE_DEVICE_SMOKE.json` now records `adb.accessible`, `adb.devices_command`, `adb.devices_exit_code`, and `adb.devices_output`.
- Non-strict device smoke now reports `skipped=true`, `skip_reason=adb_not_accessible` when sandbox or permissions block `adb devices`; strict final runs still fail because `-RequireDevice`/`-RequirePhysicalDevice` is required by the finalizer.
- Verification after this change:
  - PowerShell parser check OK for `scripts\smoke_phone_on_device.ps1`.
  - Unit tests: `113/113 OK`.
  - Non-strict sandbox smoke writes a clean skip instead of failing when `adb.exe` access is denied.
  - Full release gate rerun after the source/test change: OK, generated `2026-05-30T14:15:14+02:00`, `20` steps passed, product acceptance `93/93`.
  - Final external preflight rerun outside the sandbox: `adb_found=true`, `adb_accessible=true`, `adb_devices_exit_code=0`, but no authorized physical USB Android device is connected.
  - Submission verifier OK with freshness check active: failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit: `complete=False`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161710966`, SHA256 `971BFF0A4DD2CC8D5D23137F73BB270C47E4B93EFC0CE7A105387739ECDC9CB8`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: SHA256 `DE0D7D1F1636C817673DFBBA48881A7E18C44768E8BEC261B6CA5720F1C02BAD`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: SHA256 `D889497180B312DE9D926206ED08D027735BDD3BD6D423C808E10169FE59B4A3`;
  - release gate JSON `reports\release_gate_latest.json`: SHA256 `2755AA7F71B3B03CA983B8814CFB0F7A68AB7645468123FF3DB77280C1C38EF1`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: SHA256 `D11CFF98EB6A42F703531316272B3AEF19A195B8DB307A0CD96213C306650BDC`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: SHA256 `EFE98D6240D1D0AAF8FA9964957AED8EB17D1E05726562E864BBA3FB43ADE02B`;
  - university report PDF `docs\report\verity_lens_report.pdf`: SHA256 `BBB302953A9A8AF2368D486722558ED8FAE96107B7CFF0019AAB77BD7B394C4B`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with screenshot, SHA256 match, and full identity proof.

## Latest EOF State: Physical Phone Screenshot PNG Proof Hardened (Authoritative Tail)

- Most recent completed change: hardened the final physical Android screenshot proof so `PHONE_DEVICE_SMOKE.json` cannot pass with a missing, corrupt, zero-size, or dimensionless screenshot.
- `scripts\smoke_phone_on_device.ps1` now records `screenshot.png_signature_ok`, `screenshot.width`, `screenshot.height`, and `screenshot.valid_png`; `screenshot.captured` and the final device-smoke `ok` require a valid PNG with positive dimensions.
- `scripts\verify_submission_bundle.ps1` now reads `phone/PHONE_DEVICE_SCREENSHOT.png` from the submission ZIP and, when phone smoke is OK, requires the packaged PNG to be valid and dimension-matched to `PHONE_DEVICE_SMOKE.json`.
- `scripts\audit_project_goal_completion.ps1`, `scripts\finalize_cloud_phone_submission.ps1`, and `scripts\check_final_external_prereqs.ps1` now include `phone_device_screenshot_valid_png` in the final physical-phone evidence contract.
- Docs were aligned in `README.md`, `RUNBOOK.md`, `docs\mobile_flutter_render.md`, and `docs\report\verity_lens_report.tex`.
- Verification after this change:
  - PowerShell parser check OK for the changed scripts.
  - Unit tests: `113/113 OK`.
  - Non-strict sandbox phone smoke writes a skip with `valid_png=false` when no authorized Android device is available.
  - Full release gate rerun after the source/docs/test changes: OK, generated `2026-05-30T14:24:28+02:00`, `20` steps passed, product acceptance `93/93`.
  - Final external preflight rerun outside the sandbox: `adb_found=true`, `adb_accessible=true`, `adb_devices_exit_code=0`, but no authorized physical USB Android device is connected.
  - Submission bundle rebuilt at `2026-05-30T14:26:34+02:00`; verifier OK, failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit rerun at `2026-05-30T14:26:42+02:00`: `complete=false`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161712922`, SHA256 `7D33391EE6DA4F0D38FA0229EC2C97264313E29FA1B38E955159456FE7B4966F`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2857957`, SHA256 `1BC43F73A2249765596AB49916E8C9BEDFA476E3F7A408C7F58569E21110766E`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `3C60E0C148B374A7B32C9CF85DF9E9F4684CA4D99C33C01E317AC728AE72A64A`;
  - release gate JSON `reports\release_gate_latest.json`: size `14431`, SHA256 `272D94F800CE5C1A5B1B551251B225176EA1AA9513EA4AFA8749BFA8D6037BA1`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7848`, SHA256 `99B4548C33EC37875E6F9FF3E5165A6A3E0DB1C80483C29EB2CF6E2ABC149071`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6452`, SHA256 `985AE8CC27BCB883F0F5BDBA4A0EBE337EAFCF308F96770FDF65DF9A2548DB87`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `70267`, SHA256 `033B2C0A921D77A6CBCDA5A2912C0A31778D374AC26A3DC5D8FD43541465FF1B`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with valid PNG screenshot, SHA256 match, dimensions, and full identity proof.

## Latest EOF State: Raw ADB Diagnostics Added To Final Preflight (Authoritative Tail)

- Most recent completed change: `scripts\check_final_external_prereqs.ps1` now records raw ADB diagnostics in the final external preflight report.
- The Android section now includes `adb_devices_command` and `adb_devices_output` in JSON, plus a readable `Raw ADB Devices Output` fenced block in Markdown.
- This makes the final preflight actionable for the common phone states: no device, `offline`, `unauthorized`, emulator-only, or ADB execution/access failure.
- `Invoke-AdbText` in the preflight now returns the command string alongside exit code and stdout/stderr output.
- Tests were updated in `tests\test_factcheck_core.py` to require the new ADB command/output fields and Markdown heading.
- Docs were aligned in `README.md`, `RUNBOOK.md`, `docs\mobile_flutter_render.md`, and `docs\report\verity_lens_report.tex`.
- Verification after this change:
  - PowerShell parser check OK for the touched preflight script and related gate scripts.
  - Unit tests: `113/113 OK`.
  - Full release gate rerun outside the sandbox after source/docs/test changes: OK, generated `2026-05-30T15:14:47+02:00`, `20` steps passed, product acceptance `93/93`, pass rate `1.0`.
  - Final external preflight rerun outside the sandbox: not ready only because missing `real public HTTPS Render API URL` and `authorized physical USB Android device`.
  - Fresh ADB evidence in `reports\final_external_preflight_latest.json`: ADB found `true`, accessible `true`, command `adb devices`, output `List of devices attached`, selected physical device authorized `false`.
  - Submission bundle rebuilt at `2026-05-30T15:15:14+02:00`; verifier OK, failures `0`, warnings `6`, ZIP entries `46`, final cloud phone report status `absent`.
  - Goal audit rerun at `2026-05-30T15:15:26+02:00`: `complete=false`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161718775`, SHA256 `D7D44F1D7AA875E2718189FF4DBDB8C75062A78BEAB000F09CBCEF1F26936FA3`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2861253`, SHA256 `5DFEA7D97DA26B1C0CA05F1B511A6A07AF9B1F853788C29319E898613ACEBE20`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1465`, SHA256 `3DFCFD3EB645F4559549928A08BBD7590D065471CC98922DC2E0F9475765DAA5`;
  - release gate JSON `reports\release_gate_latest.json`: size `14432`, SHA256 `D708A85A3DB09D7D68058A20750D45DA6562A5B99E1F82C21B6F7995EFAEFC9C`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7848`, SHA256 `2FCC6C61E5FDCB2899D573783AC3AD364A5F5E08AAA59F572C35FCB4C019ADD1`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6549`, SHA256 `35E5B8D084E54755FB0B3DD589565E477DDC50F6829C3B082B8DB52A90940198`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `71279`, SHA256 `A6A476E9FE447E305A9B770F46605A5297A8DED1D5D780B1F7FC85F169D5B95C`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with valid PNG screenshot, SHA256 match, dimensions, and full identity proof.

## Latest EOF State: Final Cloud Phone Report Packaged And Verified (Authoritative Tail)

- Most recent completed change: closed a final packaging gap for the strict Render + physical-phone wrapper.
- `scripts\make_submission_bundle.ps1` now optionally packages `reports\final_cloud_phone_submission_latest.md` and `.json` under `final/`.
- `scripts\verify_submission_bundle.ps1` now detects partial final cloud phone report pairs and, when a packaged final report says `ok=true`, checks the required cloud and physical-phone evidence fields including release cloud APK evidence, effective cloud status, physical selected device id, identity proof, screenshot SHA256 match, and valid PNG proof.
- `scripts\finalize_cloud_phone_submission.ps1` now writes an OK final report snapshot after the first strict evidence check, refreshes the submission ZIP so that report is included, reruns the verifier, reruns the goal audit, and rechecks final evidence.
- Docs were aligned in `README.md`, `RUNBOOK.md`, `docs\mobile_flutter_render.md`, and `docs\report\verity_lens_report.tex`.
- Verification after this change:
  - PowerShell parser check OK for `scripts\make_submission_bundle.ps1`, `scripts\verify_submission_bundle.ps1`, `scripts\finalize_cloud_phone_submission.ps1`, and `scripts\check_final_external_prereqs.ps1`.
  - Unit tests: `113/113 OK`.
  - Full release gate rerun outside the sandbox after source/docs/test changes: OK, generated `2026-05-30T14:35:59+02:00`, `20` steps passed, product acceptance `93/93`, pass rate `1.0`.
  - Final external preflight rerun outside the sandbox: not ready only because missing `real public HTTPS Render API URL` and `authorized physical USB Android device`.
  - Submission bundle rebuilt at `2026-05-30T14:36:43+02:00`; verifier OK, failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit rerun at `2026-05-30T14:36:46+02:00`: `complete=false`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161714390`, SHA256 `BB8D8A3C00AC946D7582A4C73F626A67CA7295243D17145433CE14C1ECBDD9DF`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2858844`, SHA256 `ABCDF6F23631AF8F3DEAC9E08751D059BCF4FF832BA394C4058F2C84C77AFB2C`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `F2D2B47EE3222DDEF6464FDDA2070EA16817783388DAD15E1C5026B1DD2C0BF8`;
  - release gate JSON `reports\release_gate_latest.json`: size `14430`, SHA256 `FBBF74EBEC358C89AE11F215635EBA6DCDAD4CDA401E9EA14708D31516323526`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7848`, SHA256 `E8D456B0A331383FECDA89EB90840A5B69D02A747D3F3D674E26F117F73FE69C`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6452`, SHA256 `797B7E6ED8D9B45E46BD9AD5D749B82B7A2C47BA97E16FDFE6EF225E1F50227B`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `70557`, SHA256 `87904D9BB9D4F007861E25B94DF8A4FA7E489698EB1E4A3D78BEC0715155721B`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with valid PNG screenshot, SHA256 match, dimensions, and full identity proof.

## Latest EOF State: Immutable Final Report Packaging Contract Added (Authoritative Tail)

- Most recent completed change: fixed the final wrapper's self-packaging edge case where `final_cloud_phone_submission_latest.*` could be packaged and then rewritten after the ZIP was created.
- `scripts\finalize_cloud_phone_submission.ps1` now records `packaging_contract.immutable_success_report=true` and `packaged_under=final/` in a successful final report.
- On success, the wrapper writes the final report, packages that immutable report into the submission ZIP, reruns the verifier, refreshes the goal audit, rechecks final evidence, and then does not rewrite the report in `finally`.
- On failure, the wrapper still writes a failure report normally, so failed runs remain diagnosable.
- `scripts\verify_submission_bundle.ps1` now fails a packaged OK final cloud phone report if it does not carry the immutable final packaging contract.
- Docs were aligned in `README.md`, `RUNBOOK.md`, `docs\mobile_flutter_render.md`, and `docs\report\verity_lens_report.tex`.
- Verification after this change:
  - PowerShell parser check OK for `scripts\finalize_cloud_phone_submission.ps1`, `scripts\verify_submission_bundle.ps1`, `scripts\make_submission_bundle.ps1`, and `scripts\check_final_external_prereqs.ps1`.
  - Unit tests: `113/113 OK`.
  - Full release gate rerun outside the sandbox after source/docs/test changes: OK, generated `2026-05-30T14:42:43+02:00`, `20` steps passed, product acceptance `93/93`, pass rate `1.0`.
  - Final external preflight rerun outside the sandbox: not ready only because missing `real public HTTPS Render API URL` and `authorized physical USB Android device`.
  - Submission bundle rebuilt at `2026-05-30T14:43:19+02:00`; verifier OK, failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit rerun at `2026-05-30T14:43:22+02:00`: `complete=false`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161714854`, SHA256 `B7A535A492A89FED95974D07716DFA76B109FEAE246701B17CB55F55BFD91D9F`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2859248`, SHA256 `7C9E37C8C4610B953DE2BB04A68024BACCC5C567CACB54927AB92A15E1D7F82B`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `021019EF6B479427756534447A56B728F79AB7D679D14098A2547A13464A9420`;
  - release gate JSON `reports\release_gate_latest.json`: size `14431`, SHA256 `3FF3512415EEDEF36D679C18ABC6E4B563E3D63779A6CD7F8DAAFC2E86E6CCA3`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7848`, SHA256 `09FB52BE8D6B935403DEEC8150AD4F0458622BAFD98243EC143C7259F77C5113`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6452`, SHA256 `94D3AB449B17347D9DF080F4320115971B3725EF1CB7E2ED06269649DDAD9CB5`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `70570`, SHA256 `0935ABBC97411DD7560FCCEB44D6B8FDD76839E33DE09A15487A9367DC5ACE0C`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with valid PNG screenshot, SHA256 match, dimensions, and full identity proof.

## Latest EOF State: Final Report Snapshot Scope Made Explicit (Authoritative Tail)

- Most recent completed change: made the final cloud phone report's self-reference contract explicit.
- `scripts\finalize_cloud_phone_submission.ps1` now records `packaging_contract.submission_zip_artifact_scope=pre_final_report_bundle_snapshot`, `submission_verification_artifact_scope=pre_final_report_bundle_snapshot`, and `post_report_checks_required_after_snapshot=true`.
- This documents that `submission_zip` and submission verifier hashes inside `final_cloud_phone_submission_latest.*` describe the bundle state before the report is packaged into the ZIP; the verifier output written after packaging is the proof for the final ZIP itself.
- `scripts\verify_submission_bundle.ps1` now requires those snapshot-scope fields and requires all post-report checks to be listed when a packaged final cloud phone report says `ok=true`.
- Docs were aligned in `README.md`, `RUNBOOK.md`, `docs\mobile_flutter_render.md`, and `docs\report\verity_lens_report.tex`.
- Verification after this change:
  - PowerShell parser check OK for `scripts\finalize_cloud_phone_submission.ps1`, `scripts\verify_submission_bundle.ps1`, `scripts\make_submission_bundle.ps1`, and `scripts\check_final_external_prereqs.ps1`.
  - Unit tests: `113/113 OK`.
  - Full release gate rerun outside the sandbox after source/docs/test changes: OK, generated `2026-05-30T14:51:18+02:00`, `20` steps passed, product acceptance `93/93`, pass rate `1.0`.
  - Final external preflight rerun outside the sandbox: not ready only because missing `real public HTTPS Render API URL` and `authorized physical USB Android device`.
  - Submission bundle rebuilt at `2026-05-30T14:52:01+02:00`; verifier OK, failures `0`, warnings `6`, ZIP entries `46`.
  - Goal audit rerun at `2026-05-30T14:52:05+02:00`: `complete=false`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161716337`, SHA256 `CB0A508ECD7F714430B749FDCF99409380D4610C41C541ACA982F638C714D5B1`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2859941`, SHA256 `65743ED53F50D942E47EC46E549104C453E28B184EC99862E5FAD60B15CC3054`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1314`, SHA256 `459F8C77A02E20F6CC85D56AEFF3C06CD16D5F2216EBC8932DF1868EB1B28795`;
  - release gate JSON `reports\release_gate_latest.json`: size `14432`, SHA256 `400926CEBEB3217A8E25DEA12CF239270378D651702AAB21F992FEB3278988C3`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7848`, SHA256 `B2CFB56FBE33FDB1FAEF19578DE8CF86AD2C26F5E4EAD3A12844CCB519EB3D63`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6452`, SHA256 `261E42F977CB929A791AD7190C62EF087CF2A7E2D30F6669A79A0F97082849B7`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `70869`, SHA256 `B915E1961458934E3D7575842AA781723E60ACA6F3863965D85634D6FD8B6980`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with valid PNG screenshot, SHA256 match, dimensions, and full identity proof.

## Latest EOF State: Failed Finalizer Reports Excluded From Normal Bundle (Authoritative Tail)

- Most recent completed change: made finalizer-report packaging stricter so failed finalizer attempts do not make a normal submission ZIP look partially final.
- `scripts\make_submission_bundle.ps1` now includes `reports\final_cloud_phone_submission_latest.md/json` only when the JSON exists, has `ok=true`, and carries the immutable/snapshot packaging contract.
- Failed `final_cloud_phone_submission_latest.*` files remain in `reports/` for diagnosis, but are skipped by the normal bundle.
- `scripts\verify_submission_bundle.ps1` now records `final_cloud_phone_submission_report.present`, `.ok`, `.status`, and `.packaged_only_when_ok` in `SUBMISSION_BUNDLE_VERIFICATION.json`; current status is `absent`.
- The verifier warning for a packaged non-OK final report now explains that such a ZIP likely came from a failed finalizer run or an older bundle script.
- Docs were aligned in `README.md`, `RUNBOOK.md`, `docs\mobile_flutter_render.md`, and `docs\report\verity_lens_report.tex`.
- Verification after this change:
  - PowerShell parser check OK for `scripts\make_submission_bundle.ps1`, `scripts\verify_submission_bundle.ps1`, `scripts\finalize_cloud_phone_submission.ps1`, and `scripts\check_final_external_prereqs.ps1`.
  - Unit tests: `113/113 OK`.
  - Full release gate rerun outside the sandbox after source/docs/test changes: OK, generated `2026-05-30T14:59:47+02:00`, `20` steps passed, product acceptance `93/93`, pass rate `1.0`.
  - Final external preflight rerun outside the sandbox: not ready only because missing `real public HTTPS Render API URL` and `authorized physical USB Android device`.
  - Submission bundle rebuilt at `2026-05-30T15:00:38+02:00`; verifier OK, failures `0`, warnings `6`, ZIP entries `46`, final report status `absent`.
  - Goal audit rerun at `2026-05-30T15:00:42+02:00`: `complete=false`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161717708`, SHA256 `DBE4A5D71868D6ACD635CAE9266A12B65870430253DC3D2A97B999BDCFB4E407`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2860799`, SHA256 `8D373CA6B9158A1A3E4D9DCFFD8F4F157E032D1076801853D9E7C0FE451D3E65`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1465`, SHA256 `82985AA147F5A70477FC76B5FD978FA2D7C25ADED93D9C62318730D024B61C95`;
  - release gate JSON `reports\release_gate_latest.json`: size `14431`, SHA256 `E0D755177D93F2BBA0496085C3FD4CBD6D70113233A70E94E19B51BA9A7B249A`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7848`, SHA256 `D7E747DAE59325AE37D054A4A01CCF6DAC8BD8DA555BA92A31DBEFD8F1F5018D`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6452`, SHA256 `07CBC43203C2EBF089A42BAF20A0473A88475FF5C8DD01EA39F2480E2D8E069A`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `71087`, SHA256 `6A0F42F6A7CED23FD9050BF435C86408BC002C1D20E5EFC89B4B69B809679CCE`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with valid PNG screenshot, SHA256 match, dimensions, and full identity proof.

## Latest EOF State: Raw ADB Diagnostics Added To Final Preflight (Authoritative Tail)

- Most recent completed change: `scripts\check_final_external_prereqs.ps1` now records raw ADB diagnostics in the final external preflight report.
- The Android section now includes `adb_devices_command` and `adb_devices_output` in JSON, plus a readable `Raw ADB Devices Output` fenced block in Markdown.
- This makes the final preflight actionable for the common phone states: no device, `offline`, `unauthorized`, emulator-only, or ADB execution/access failure.
- `Invoke-AdbText` in the preflight now returns the command string alongside exit code and stdout/stderr output.
- Tests were updated in `tests\test_factcheck_core.py` to require the new ADB command/output fields and Markdown heading.
- Docs were aligned in `README.md`, `RUNBOOK.md`, `docs\mobile_flutter_render.md`, and `docs\report\verity_lens_report.tex`.
- Verification after this change:
  - PowerShell parser check OK for the touched preflight script and related gate scripts.
  - Unit tests: `113/113 OK`.
  - Full release gate rerun outside the sandbox after source/docs/test changes: OK, generated `2026-05-30T15:14:47+02:00`, `20` steps passed, product acceptance `93/93`, pass rate `1.0`.
  - Final external preflight rerun outside the sandbox: not ready only because missing `real public HTTPS Render API URL` and `authorized physical USB Android device`.
  - Fresh ADB evidence in `reports\final_external_preflight_latest.json`: ADB found `true`, accessible `true`, command `adb devices`, output `List of devices attached`, selected physical device authorized `false`.
  - Submission bundle rebuilt at `2026-05-30T15:15:14+02:00`; verifier OK, failures `0`, warnings `6`, ZIP entries `46`, final cloud phone report status `absent`.
  - Goal audit rerun at `2026-05-30T15:15:26+02:00`: `complete=false`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161718775`, SHA256 `D7D44F1D7AA875E2718189FF4DBDB8C75062A78BEAB000F09CBCEF1F26936FA3`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2861253`, SHA256 `5DFEA7D97DA26B1C0CA05F1B511A6A07AF9B1F853788C29319E898613ACEBE20`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1465`, SHA256 `3DFCFD3EB645F4559549928A08BBD7590D065471CC98922DC2E0F9475765DAA5`;
  - release gate JSON `reports\release_gate_latest.json`: size `14432`, SHA256 `D708A85A3DB09D7D68058A20750D45DA6562A5B99E1F82C21B6F7995EFAEFC9C`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7848`, SHA256 `2FCC6C61E5FDCB2899D573783AC3AD364A5F5E08AAA59F572C35FCB4C019ADD1`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6549`, SHA256 `35E5B8D084E54755FB0B3DD589565E477DDC50F6829C3B082B8DB52A90940198`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `71279`, SHA256 `A6A476E9FE447E305A9B770F46605A5297A8DED1D5D780B1F7FC85F169D5B95C`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with valid PNG screenshot, SHA256 match, dimensions, and full identity proof.

## Latest EOF State: State-Specific ADB Next Actions Added (Authoritative Tail)

- Most recent completed change: `scripts\check_final_external_prereqs.ps1` now records and acts on detailed ADB device states.
- The final external preflight Android JSON now includes `unauthorized_devices`, `offline_devices`, `authorized_emulator_devices`, and `requested_device_state`.
- The Markdown report now shows counts for unauthorized/offline/emulator devices and the requested device state.
- The `Next Actions` section now distinguishes:
  - empty `adb devices` output: connect a real phone, enable USB debugging, accept RSA;
  - `unauthorized`: unlock the phone and accept the RSA prompt;
  - `offline`: reconnect USB and, if needed, run `adb kill-server` / `adb start-server`;
  - emulator-only: connect a real USB phone for final proof or use `-AllowEmulator` only for diagnostics.
- Tests were updated in `tests\test_factcheck_core.py` to require the new fields and state-specific action text.
- Docs were aligned in `README.md`, `RUNBOOK.md`, `docs\mobile_flutter_render.md`, and `docs\report\verity_lens_report.tex`.
- Verification after this change:
  - PowerShell parser check OK for `scripts\check_final_external_prereqs.ps1`, `scripts\verify_submission_bundle.ps1`, `scripts\make_submission_bundle.ps1`, and `scripts\audit_project_goal_completion.ps1`.
  - Unit tests: `113/113 OK`.
  - Full release gate rerun outside the sandbox after source/docs/test changes: OK, generated `2026-05-30T15:24:51+02:00`, `20` steps passed, product acceptance `93/93`, pass rate `1.0`.
  - Final external preflight rerun outside the sandbox: not ready only because missing `real public HTTPS Render API URL` and `authorized physical USB Android device`.
  - Current ADB evidence: ADB found `true`, accessible `true`, command `adb devices`, raw output `List of devices attached`, no devices listed, next action says to connect a real phone and accept RSA.
  - Submission bundle rebuilt at `2026-05-30T15:25:22+02:00`; verifier OK, failures `0`, warnings `6`, ZIP entries `46`, final cloud phone report status `absent`.
  - Goal audit rerun at `2026-05-30T15:25:32+02:00`: `complete=false`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161720310`, SHA256 `D43986699B65980ACA9774A9C040504BBD06B8DFF9E2AF76BDFCD7DFD84C1794`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2862184`, SHA256 `80CD67C9FDE519329F20E47DE3DC3959AD5FEF1D51CAE504357353E362E62BB5`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1465`, SHA256 `4708EDB201AE5644ED222F70AEC1E50D25AE9A76F6E3C321BF9787C98E52F1CE`;
  - release gate JSON `reports\release_gate_latest.json`: size `14431`, SHA256 `F555003347C036B2FFD7D0FAE41AE2FA74F03BAC48765E9398AF0A4A6C279B0E`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7848`, SHA256 `99EF18C7961FD766B808CD6E3325A51D4390EBB56390CD70E0C3D4BBAA462F8D`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6717`, SHA256 `8A19CD67B6F28BD4E4FBA6AAD3DCCCFF1D829063F282A3608B28458D9CDA6B3C`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `71481`, SHA256 `79F4AE8A4F3091043455E22CC972FCE9396A06EF05A1A8D242E50F53BE0C7876`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with valid PNG screenshot, SHA256 match, dimensions, and full identity proof.

## Latest EOF State: Explicit ADB Path Passthrough Added (Authoritative Tail)

- Most recent completed change: final phone/cloud scripts now support an explicit `-AdbPath` all the way through the final workflow.
- `scripts\check_final_external_prereqs.ps1` accepts `-AdbPath`, resolves command names or filesystem paths, records `adb_requested_path`, and includes the path in the generated finalizer command.
- `scripts\finalize_cloud_phone_submission.ps1` accepts `-AdbPath`, records it in the final report, passes it to the final preflight, and passes it to `run_release_gate.ps1`.
- `scripts\run_release_gate.ps1` accepts `-AdbPath`, records it in release options, and passes it to `smoke_phone_on_device.ps1` for physical-phone proof.
- Docs were aligned in `README.md`, `RUNBOOK.md`, `docs\mobile_flutter_render.md`, and `docs\report\verity_lens_report.tex`.
- Tests were updated in `tests\test_factcheck_core.py`, including the copy-paste finalizer command test with an ADB path containing spaces.
- Verification after this change:
  - PowerShell parser check OK for `scripts\check_final_external_prereqs.ps1`, `scripts\run_release_gate.ps1`, `scripts\finalize_cloud_phone_submission.ps1`, `scripts\verify_submission_bundle.ps1`, `scripts\make_submission_bundle.ps1`, and `scripts\audit_project_goal_completion.ps1`.
  - Unit tests: `113/113 OK`.
  - Final external preflight rerun outside the sandbox with explicit `-AdbPath C:\Users\marke\AppData\Local\Android\Sdk\platform-tools\adb.exe`: not ready only because missing `real public HTTPS Render API URL` and `authorized physical USB Android device`; ADB found/accessed OK; raw `adb devices` output is `List of devices attached`.
  - Full release gate rerun outside the sandbox after source/docs/test changes: OK, generated `2026-05-30T15:39:02+02:00`, `20` steps passed, product acceptance `93/93`, pass rate `1.0`.
  - Submission bundle rebuilt at `2026-05-30T15:39:38+02:00`; verifier OK, failures `0`, warnings `6`, ZIP entries `46`, final cloud phone report status `absent`.
  - Goal audit rerun at `2026-05-30T15:39:46+02:00`: `complete=false`, estimated `92%`, remaining `8%`.
- Fresh hashes:
  - submission ZIP `outputs\submission\VerityLens-submission.zip`: size `161721573`, SHA256 `AE20B5015B127603BF5EF66708D37BA0F4B713CE159CFF09BC98E9B4CB5C1AF6`;
  - source ZIP `outputs\submission\verity-lens-source.zip`: size `2862920`, SHA256 `E11FE759D00BFD936B8CCF9B8733122CF96CD29220B8671ED068B6D13AAFD5E7`;
  - submission verification JSON `outputs\submission\SUBMISSION_BUNDLE_VERIFICATION.json`: size `1465`, SHA256 `3FBDBA27CB999D4545143EA0826444849BDD9241136AFC7D0EB6465D6E73D60E`;
  - release gate JSON `reports\release_gate_latest.json`: size `14451`, SHA256 `B10C32744076521BA8C09A44961C2DF4D484D34EA31DE7791AB6FE5ED2ABD420`;
  - goal audit JSON `reports\goal_completion_audit_latest.json`: size `7848`, SHA256 `1390AEE25BCD9DEEE00BCC470D893A2DD0A817304A185EF00616A6CA2DCBA4F3`;
  - final external preflight JSON `reports\final_external_preflight_latest.json`: size `6985`, SHA256 `719C296C85C090136D29C406A36F1DD8A81CA526C409D45E720F97FCDD4D590B`;
  - university report PDF `docs\report\verity_lens_report.pdf`: size `71636`, SHA256 `FE572F7C0073DC7EB56CBA12BA0E9222AF61971B030C6789FCC1CCFA387A38FE`.
- Still remaining external proof: permanent Render HTTPS backend, release cloud APK built and verified against that backend, and authorized physical Android USB device with valid PNG screenshot, SHA256 match, dimensions, and full identity proof.
