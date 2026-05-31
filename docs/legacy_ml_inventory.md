# Legacy ML inventory

Verity Lens has one canonical product engine: `src/factcheck/`, exposed by
`src.api_factcheck`, `src.ui`, `src.desktop_app`, and the Flutter client.

The files below are legacy research/prototype code. They were moved out of
`src/` into archive directories so they are visibly outside the product runtime.
They are kept for reference, experiments, or future dataset work, but they are
not part of the default product path, Windows desktop smoke path, Render API
image, or Flutter client release gate.

## Legacy prototype modules

- `archive/legacy_multimodal/src/models.py`: old multimodal Torch model definition.
- `archive/legacy_multimodal/src/dataset.py`: old dataset helpers for the prototype model.
- `archive/legacy_multimodal/src/train.py`: old training entrypoint.
- `archive/legacy_multimodal/src/evaluate.py`: old evaluation entrypoint for the prototype model.
- `archive/legacy_multimodal/src/fetch_news_dataset.py` and
  `archive/legacy_multimodal/src/fetch_text_dataset.py`: dataset acquisition
  helpers that are not needed by the current product runtime.
- `archive/legacy_multimodal/src/build_manifest.py`,
  `archive/legacy_multimodal/src/prepare_data.py`, and
  `archive/legacy_multimodal/src/split_data.py`: old CSV/manifest preparation
  helpers for the multimodal prototype.
- `archive/legacy_multimodal/src/callbacks.py` and
  `archive/legacy_multimodal/src/utils.py`: helper modules used by the old
  prototype training scripts.
- `archive/legacy_factcheck_v1/src/`: old root-level fact-check compatibility
  wrappers from before the canonical `src/factcheck/` package existed.

## Compatibility files

- `src/api.py`: legacy `/predict` route. It no longer loads the old model and
  delegates to `src.api_factcheck`.
- `src/predict.py`: legacy command-line entrypoint. It no longer loads the old
  model and delegates to the canonical fact-check engine.
- `scripts/_factcheck_eval_adapter.py`: compatibility adapter for older
  evaluation scripts that still need legacy-shaped result dictionaries.

## Optional ML dependencies

Torch and Transformers are optional research/runtime extensions, not required by
the default product environment. The default `requirements.txt` and
`requirements.lock.txt` files are intentionally lightweight and omit the old ML
stack. Install `requirements.optional-ai.txt` only when an optional classifier
or local claim-prior model should be enabled.

The archived training stack is isolated in `requirements.legacy-train.txt`.
Use it only for explicit experiments around the archived prototype or claim
prior training scripts. The lightweight claim-prior helpers import Torch only
when an explicit local model exists, and the Windows PyInstaller spec excludes
those packages from the portable app. AI-image detection defaults to
metadata-only in the packaged desktop launcher unless `FACTCHECK_AI_IMAGE_MODEL`
is set manually.

## Cleanup rule

New product code should not import archived prototype modules. If the old
prototype is needed later, run it as an explicit experiment from
`archive/legacy_multimodal/` instead of mixing it into the public API, UI,
desktop launcher, or Flutter release path.
