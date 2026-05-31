# Life Facts v1 Report

- Dataset: `C:\Users\marke\University\project\fake-news-detector_transfer_bundle\fake-news-detector\data\factcheck\versions\life_facts_v1.jsonl`
- Pipeline: `best_accuracy_v2`
- Cases: `122`
- Accuracy: `100.0%`
- Hard verdict precision: `100.0%`
- Hard verdict coverage: `83.6%`
- Uncertain rate: `16.4%`
- Error rate: `0.0%`

## Breakdown By Category

| Category | N | Accuracy | Uncertain | Predictions |
|---|---:|---:|---:|---|
| arithmetic_comparison | 4 | 100.0% | 0.0% | `{"fake": 2, "true": 2}` |
| arithmetic_equation | 16 | 100.0% | 0.0% | `{"fake": 8, "true": 8}` |
| local_common_knowledge | 52 | 100.0% | 0.0% | `{"fake": 26, "true": 26}` |
| safe_abstention | 20 | 100.0% | 100.0% | `{"uncertain": 20}` |
| wikipedia_backed | 30 | 100.0% | 0.0% | `{"true": 30}` |

## Breakdown By Source Type

| Source Type | N | Accuracy | Uncertain | Predictions |
|---|---:|---:|---:|---|
| local_arithmetic | 20 | 100.0% | 0.0% | `{"fake": 10, "true": 10}` |
| local_common_knowledge | 63 | 100.0% | 17.5% | `{"fake": 26, "true": 26, "uncertain": 11}` |
| unknown | 1 | 100.0% | 100.0% | `{"uncertain": 1}` |
| wikipedia | 38 | 100.0% | 21.1% | `{"true": 30, "uncertain": 8}` |

## Failures

No failures.
