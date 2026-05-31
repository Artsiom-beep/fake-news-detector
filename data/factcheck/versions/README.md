# Dataset Versions

Immutable benchmark datasets for the fact-check product.

- `eval_cases_v2_60.jsonl`: older baseline copy from the legacy benchmark.
- `eval_cases_v3_60.jsonl`: canonical v3 benchmark with added metadata:
  - `claim_family_id`
  - `domain`
  - `source_type`
  - `language`
  - `published_at`
  - `url`
- `life_facts_v1.jsonl`: curated English everyday-facts benchmark for arithmetic, local common knowledge, Wikipedia-backed stable facts, and safe abstention cases.

Rule: do not edit an older version in place. Create a new file for every benchmark revision.
