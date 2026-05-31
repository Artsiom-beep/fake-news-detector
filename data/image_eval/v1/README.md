# Image Eval v1

Versioned diagnostic set for AI-image risk calibration.

The manifest is the source of truth:

```text
data/image_eval/v1/manifest.jsonl
```

Each row is immutable once used in a run. Add new cases by creating a new dataset version or appending only before the next recorded run. The highest-risk metric is false positives on real images: the detector should abstain instead of confidently accusing a real image when evidence is weak.
