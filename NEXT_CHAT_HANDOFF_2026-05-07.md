# Next Chat Handoff - Fake News Detector

Use this file as the first message/context for a new Codex chat. The goal is that the new chat immediately understands what we are building, what already exists, how to run it, and what to do next.

## Project

Local path:

```powershell
C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector
```

Product goal:

Build a local-first prototype app that helps a user check whether a news item, claim, screenshot, or image is trustworthy.

Current product shape:

- Desktop/browser app with a simple assistant-like UI.
- One public flow: user enters URL/text or pastes/drops an image.
- No public modes in the UI. Internally the backend chooses the best strategy.
- News articles get a `credibility` score, not fake/true guessing.
- `true/fake` is reserved for explicit fact-check evidence or simple stable facts.
- Screenshots are checked via OCR.
- Images can be checked for AI-generation risk.

Important product principle:

When the system is not sure, it should say `uncertain` / “not enough certainty” instead of pretending it knows.

## Current Status

Working:

- Text claim checks.
- URL/news credibility checks.
- Explicit fact-check page handling.
- Simple everyday facts, including arithmetic and basic stable claims.
- Screenshot OCR flow.
- Paste/drop image support in UI.
- AI-image risk detection.
- Desktop wrapper using PyWebView.
- Local browser UI.
- Unit/integration tests.

Last known verification:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_factcheck_core -v
```

Last result: `72/72` tests passed.

Full system test report:

- `reports\full_system_test_20260507.md`

Latest live quality pack:

- `17/17` passed, `0` errors.
- Report: `reports\quality_pack_v3_live.md`
- JSON: `reports\quality_pack_v3_live.json`

Fake fact-check links smoke:

- `scripts\run_fake_links_test.py`
- Last result: 4/4 known fake fact-check links returned `fake` with evidence.

AI-image eval last result:

- Report: `outputs\ai_image_eval\ai_image_detector_eval.md`
- JSON: `outputs\ai_image_eval\ai_image_detector_eval.json`
- Versioned dataset: `data\image_eval\v1\manifest.jsonl`
- History report: `reports\image_detector_runs\20260507_final_after_factcheck_fixes.md`
- Dataset contents: 3 generated AI images from Pollinations + 10 real stock-like images from Picsum/Unsplash.
- Hard predictions: 11/13.
- Hard precision on that small test: 100%.
- Coverage: 84.62%.
- False positives, real labeled AI: 0.
- False negatives, AI labeled real: 0.
- 3/3 generated images detected as `likely_ai`.
- 8/10 real stock images detected as `likely_not_ai`.
- 2/10 real stock images safely abstained as `uncertain`.

Important caveat:

This is a small diagnostic test, not a scientific benchmark. AI-image detectors are unreliable in the wild, so the product must stay conservative.

## How To Run

Open PowerShell in the project folder:

```powershell
cd C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector
```

Run desktop app:

```powershell
.\run_desktop_app.bat
```

Alternative browser UI:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.ui:app --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000/check
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_factcheck_core -v
```

Run AI-image eval using existing downloaded/generated images:

```powershell
.\.venv\Scripts\python.exe scripts\run_ai_image_detector_eval.py --existing-only
```

Run AI-image eval with manifest downloads if a local image is missing:

```powershell
.\.venv\Scripts\python.exe scripts\run_ai_image_detector_eval.py
```

## Main Files

Backend:

- `src\factcheck\service.py` - main orchestrator `run_factcheck`.
- `src\factcheck\schemas.py` - public contract and result schemas.
- `src\factcheck\news_credibility.py` - news credibility scoring.
- `src\factcheck\common_knowledge.py` - simple/stable fact helper.
- `src\factcheck\image_analysis.py` - screenshot OCR and AI-image detection.
- `src\factcheck\retrieval.py` - search/retrieval.
- `src\factcheck\source_registry.py` - source trust classification.
- `src\factcheck\decision.py` - fact-check decision policy.

Entrypoints:

- `src\ui.py` - FastAPI web UI.
- `src\api_factcheck.py` - API.
- `src\predict_factcheck.py` - CLI.
- `src\desktop_app.py` - PyWebView desktop wrapper.
- `run_desktop_app.bat` - Windows launcher.

Testing/eval:

- `tests\test_factcheck_core.py` - main test suite.
- `data\image_eval\v1\manifest.jsonl` - versioned image detector benchmark manifest.
- `scripts\run_ai_image_detector_eval.py` - manifest-based image detector eval.
- `outputs\ai_image_eval\ai_image_detector_eval.md` - latest image detector report.
- `reports\image_detector_runs\` - versioned image detector run history.

Docs:

- `README.md`
- `RUNBOOK.md`
- `EVAL_WORKFLOW.md`

Note:

The folder currently does not appear to contain a `.git` directory. Treat local files as the source of truth unless the user gives a remote repo.

## Public Output Contract

The result should keep this shape:

```json
{
  "verdict": "true|fake|uncertain",
  "confidence": 0.0,
  "summary": "short grounded explanation",
  "claim": "normalized primary claim",
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
    "mode": "ai_image_detection|screenshot_ocr",
    "ai_generated_score": 0.0,
    "ai_label": "likely_ai|likely_not_ai|uncertain",
    "warnings": [],
    "reasons": [],
    "metadata": {}
  },
  "trace": {}
}
```

## Current AI Image Detector Policy

Default model:

```text
haywoodsloan/ai-image-detector-deploy
```

Configured in:

- `.env.example`
- `run_desktop_app.bat`
- `src\desktop_app.py`
- `scripts\run_ai_image_detector_eval.py`
- `src\factcheck\config.py` loads `.env` when present.

Important calibration policy:

- Metadata with explicit AI generator markers can produce `likely_ai`.
- The whitelisted model can produce `likely_ai` only with extremely strong AI signal:
  - `ai_score >= 0.995`
  - `margin >= 0.99`
- Strong real signal can produce `likely_not_ai`.
- Camera metadata alone must not produce `likely_not_ai`; metadata-only checks should abstain unless there is explicit AI-generator metadata.
- Suspicious but not decisive model signal must return `uncertain`, not a false accusation.

## Fixes From Full-System Test Pass

- Trusted news credibility calibration now lets direct trusted publisher articles reach `medium` from source quality alone when there are no severe risk flags, while still avoiding `high` without corroboration.
- `abcnews.com` is now classified as `major_news`.
- `scripts\run_fake_links_test.py` now uses the canonical fact-check engine.
- Generic fact-check parsing now catches refutation wording such as `misrepresented`, `falsely implied`, `peddled as`, and `claiming to show ... is from ...`.
- Trusted newsroom fact-check desks, such as Reuters Fact Check, can now produce explicit hard verdicts when the page is marked as a fact-check and has an extracted explicit verdict.
- AFP fact-check `doc.afp.com.*` URLs are treated as article-like fact-check URLs.
- Fetch cache version is now `fetch_v5`.

Why:

The previous detector `capcheck/ai-image-detection` falsely labeled many real stock photos as AI. The new detector plus conservative thresholds performed much better on the local diagnostic set.

## What To Do Next

Highest priority:

1. Expand the versioned image detector benchmark beyond the current 13-case v1 seed.
2. Add more real images: phone photos, screenshots, compressed social-media images, stock photos, news photos.
3. Add more generated images: Midjourney-like, Stable Diffusion-like, DALL-E-like, photoreal people, animals, landscapes, product shots, screenshots.
4. Keep tracking false positives separately from false negatives. False “AI” accusations are more harmful than abstaining.
5. Use the benchmark before changing detector thresholds or adding another model.

Recommended next engineering tasks:

- Add `data\image_eval\v2\manifest.jsonl` when the dataset changes materially, rather than silently editing v1 after recorded runs.
- Add image categories/tags to the manifest or report once there are enough cases to break metrics down by source type.
- Add UI/browser smoke around all three image badges: `Likely AI`, `Likely real`, `Not enough certainty`.
- Add optional second model only if it reduces false positives on the versioned benchmark.

Do not do yet unless user asks:

- Accounts/login.
- Cloud storage.
- Mobile app.
- Paid APIs.
- Public SaaS deployment.
- Removing legacy ML/training files.

## Useful Test Prompts For Manual UI

Simple facts:

- `2 plus 2 equals 4` should return true-style result.
- `Apple is blue` should return fake-style result.
- `Coffee cures cancer` should return not enough certainty.

Images:

- Paste a generated photoreal image: should be `likely_ai` only if signal is very strong.
- Paste a real cat/photo/stock image: should be `likely_not_ai` or `uncertain`, not false high AI risk.
- Paste a screenshot with text: use `Check screenshot`.
- Paste an image with no readable text: screenshot flow should abstain clearly.

News:

- BBC/AP/Reuters/Guardian-like article URLs should show credibility, not hard true/fake unless explicit fact-check evidence exists.
- Listing/search/homepage URLs should return low/unknown credibility, not high.

## MCP / Tools Available In The Previous Chat

The previous Codex chat had these useful MCP/tool servers or tool namespaces available:

- `mcp__filesystem__` - file read/write/list/search operations.
- `functions.shell_command` - PowerShell command execution.
- `mcp__playwright__` - browser automation.
- `mcp__playwright_extension__` - in-app browser automation.
- `mcp__node_repl__` - persistent Node.js REPL.
- `mcp__context7__` - up-to-date library documentation.
- `mcp__codex_apps__google_calendar` - calendar MCP, not needed for this project.
- `web` - internet search/opening pages.
- `image_gen` - image generation tool.

Enabled plugins/skills in the previous chat:

- Browser Use plugin.
- Documents plugin.
- Presentations plugin.
- Spreadsheets plugin.
- `imagegen` skill.
- `openai-docs` skill.
- `browser-use:browser` skill.

## Tools The Next Chat Should Have

Required or strongly recommended:

- Filesystem access.
- Shell/PowerShell command execution.
- Browser automation for localhost UI testing.
- Web search for fresh docs/source checks.
- Context7 or equivalent docs lookup for library/API questions.

Optional but useful:

- GitHub plugin/connector, if the user puts this project in GitHub.
- Image generation tool, only for generating visual test cases or UI assets.
- Node REPL, useful for quick frontend/JS experiments.

Tell the next chat:

If any of these are missing, ask the user to enable/install the most useful ones before deep work:

- Browser Use or Playwright automation.
- Filesystem tools.
- Shell command execution.
- Context7 docs lookup.
- GitHub plugin if repository sync, issues, PRs, or commits are needed.

Do not require Google Calendar, Documents, Presentations, or Spreadsheets for this project unless the user specifically asks for planning docs, slides, or spreadsheet reports.

## Collaboration Instructions For The Next Chat

Be direct and practical.

The user wants a working product, not only plans. Prefer implementing and testing.

When changing code:

- Keep the public UX simple.
- Do not reintroduce public mode switches.
- Preserve the JSON contract.
- Keep uncertainty as a first-class result.
- Run tests after changes.
- For UI changes, test in browser if possible.
- Avoid false confident verdicts.

If uncertain about the detector/model:

Use benchmark evidence, not vibes. Add cases, run the script, compare false positives/false negatives, then decide.
