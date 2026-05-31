# Legacy fact-check v1 wrappers

These files are archived compatibility modules from the pre-`src/factcheck`
layout. The active product engine now lives in `src/factcheck/`, with public
entrypoints in `src/api_factcheck.py`, `src/ui.py`, `src/desktop_app.py`, and
`src/predict_factcheck.py`.

Keep these modules for historical comparison only. New code should import the
canonical engine or use `scripts/_factcheck_eval_adapter.py` when an older
evaluation payload shape is needed.

