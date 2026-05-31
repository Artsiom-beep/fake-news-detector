# Full System Test - 2026-05-07

## Summary

All final test cycles passed after fixes.

Fixes made during this pass:
- Calibrated trusted news credibility so direct articles from trusted publishers can reach `medium` even when fresh live search finds no independent corroboration, while listing/social/unknown guardrails stay low or unknown.
- Added `abcnews.com` to the source registry.
- Repaired `scripts/run_fake_links_test.py` to use the canonical fact-check engine.
- Extended fact-check parsing for trusted fact-check pages whose refutation is expressed as `misrepresented`, `falsely implied`, `peddled as`, or `claiming to show ... is from ...`.
- Allowed explicit fact-check verdicts from trusted newsroom fact-check desks, not only dedicated fact-check domains.
- Added support for AFP fact-check `doc.afp.com.*` article URLs.
- Bumped fetch cache version to `fetch_v5` so parser fixes are not hidden by old cached payloads.

## Final Results

| Area | Command / check | Result |
|---|---|---|
| Python syntax | `python -m py_compile <all project .py files>` | Passed |
| Unit/integration tests | `python -m unittest discover -s tests -v` | 72/72 passed |
| CLI facts | 8 manual CLI cases: arithmetic, everyday facts, unsupported medical claim, unknown claim | 8/8 passed |
| URL fact-check/news smoke | PolitiFact explicit fact-check and AP ordinary news URL | Passed |
| API smoke | health, ready, text fact, validation, AI image, real image, screenshot OCR abstention | Passed |
| UI browser smoke | fake fact, uncertain claim, generated image, real image | Passed |
| Desktop smoke | `python -m src.desktop_app --smoke --port 0` | Passed |
| Fake fact-check links | `python scripts/run_fake_links_test.py` | 4/4 fake with evidence |
| Life facts benchmark | `python scripts/eval_life_facts.py` | 122 cases, accuracy 1.0, hard precision 1.0, error 0 |
| Image detector benchmark | `python scripts/run_ai_image_detector_eval.py --existing-only --run-id 20260507_final_after_factcheck_fixes` | 13/13 evaluated, hard precision 1.0, false positives 0, false negatives 0 |
| Image metadata-only safety | `FACTCHECK_AI_IMAGE_MODEL=disabled python scripts/run_ai_image_detector_eval.py --existing-only --out-dir outputs/ai_image_eval_metadata_only --run-id 20260507_fulltest_image_metadata_only` | 0 hard predictions, false positives 0 |
| News credibility smoke | `python scripts/run_news_credibility_smoke.py` | Passed guardrails |
| Live quality pack | `python scripts/run_quality_pack_v3.py --per-source 1 --max-cases 18` | 17/17 passed, errors 0 |
| Legacy broad claim eval | `python scripts/eval_factcheck_v3.py --dataset data/factcheck/versions/eval_cases_v3_60.jsonl --out outputs/factcheck_runs/eval_results_fulltest_20260507.json` | Completed, error 0, all 60 abstained by current conservative policy |

## Key Output Files

- `reports/quality_pack_v3_live.md`
- `reports/quality_pack_v3_live.json`
- `reports/life_facts_v1_report.md`
- `outputs/factcheck_runs/life_facts_v1_results.json`
- `outputs/factcheck_runs/final_report_fulltest_20260507.md`
- `outputs/factcheck_runs/eval_results_fulltest_20260507.json`
- `outputs/ai_image_eval/ai_image_detector_eval.md`
- `reports/image_detector_runs/20260507_final_after_factcheck_fixes.md`
- `outputs/ai_image_eval_metadata_only/ai_image_detector_eval.md`
