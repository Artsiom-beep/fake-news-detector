# Fact-check Eval Workflow

Every benchmark run must use an immutable dataset version and the canonical `factcheck_v1` pipeline.

## 1) Prepare dataset v3

```powershell
python scripts/build_benchmark_v3.py
python scripts/make_eval_splits.py --src data/factcheck/versions/eval_cases_v3_60.jsonl
```

## 2) Run eval

```powershell
python scripts/eval_factcheck_v3.py --dataset data/factcheck/versions/eval_cases_v3_60.jsonl --out outputs/factcheck_runs/eval_results_v1.json
```

## 3) Register the run

```powershell
python scripts/register_eval_run.py --dataset data/factcheck/versions/eval_cases_v3_60.jsonl --eval outputs/factcheck_runs/eval_results_v1.json --dataset-version v3_60 --pipeline-version factcheck_v1 --notes "describe what changed"
```

## 4) Metrics
- accuracy
- uncertain_rate
- error_rate
- by_domain
- by_source_type

## 5) Rules
- Never silently edit an older dataset version.
- Keep split isolation at claim-family level.
- Use new fast/degraded mode only for smoke tests, not for release metrics.

## 6) AI-image detector eval

The AI-image detector uses its own versioned manifest:

```powershell
python scripts/run_ai_image_detector_eval.py --existing-only
```

Inputs:
- `data/image_eval/v1/manifest.jsonl`
- `data/image_eval/v1/images/`

Outputs:
- `outputs/ai_image_eval/ai_image_detector_eval.json`
- `outputs/ai_image_eval/ai_image_detector_eval.md`
- `reports/image_detector_runs/<run-id>.json`
- `reports/image_detector_runs/<run-id>.md`

Track `false_positive_real_as_ai` separately from `false_negative_ai_as_real`. A real image incorrectly labeled `likely_ai` is the most harmful detector failure, so abstention is preferred when model-only evidence is not decisive.
