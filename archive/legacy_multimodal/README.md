# Legacy multimodal prototype

This folder contains the old Torch/DistilBERT multimodal prototype that used to
live directly under `src/`.

It is archived on purpose:

- The current Verity Lens product runtime is `src/factcheck/`.
- Public product entrypoints are `src.api_factcheck`, `src.ui`,
  `src.desktop_app`, `src.predict_factcheck`, `src.api`, and `src.predict`.
- The archived prototype is not included in the release gate, Render API image,
  Windows desktop smoke path, or Flutter client path.

Use these files only as research history or as a starting point for a separate
experiment. Do not import them from product code.
