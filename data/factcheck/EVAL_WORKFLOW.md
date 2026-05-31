# Fact-check eval workflow (versioned)

С этого момента каждый прогон делаем только через версионированный датасет и запись в историю.

## 1) База датасетов

- Храним версию датасета в `data/factcheck/versions/`.
- Формат: JSONL, минимум поля:
  - `id`
  - `text`
  - `expected` (`true` | `fake` | `uncertain`)
- Рекомендуемые поля для аналитики:
  - `domain` (reuters / boomlive / afp / newschecker / ...)
  - `source_url`
  - `added_in` (версия, где кейс добавлен)
  - `note`

Рекомендуемая именовка: `eval_cases_<version>.jsonl`.

## 2) Правило роста набора

- Не работаем на сверхмалых выборках (4-10 кейсов).
- Рабочий минимум: `30+`.
- Целевой базовый набор: `60+`.
- На каждом новом тест-цикле добавляем/уточняем hard-cases и фиксируем новую версию набора.

## 3) Прогон

```powershell
.\.venv\Scripts\python.exe scripts/eval_factcheck_v3.py `
  --dataset data/factcheck/versions/eval_cases_vX.jsonl `
  --out outputs/factcheck_runs/eval_results_vX_runY.json
```

## 4) Регистрация результата

```powershell
.\.venv\Scripts\python.exe scripts/register_eval_run.py `
  --dataset data/factcheck/versions/eval_cases_vX.jsonl `
  --eval outputs/factcheck_runs/eval_results_vX_runY.json `
  --dataset-version vX `
  --model-version fact_pipeline_v3 `
  --notes "что поменяли перед прогоном"
```

История пишется в `data/factcheck/benchmark_runs.jsonl`.

## 5) Целевые метрики

- `accuracy`
- `uncertain_rate`
- `error_rate`
- `by_domain` (разбивка по источникам)

## 6) Дисциплина

- Один логичный change-set = один осмысленный commit.
- Артефакты прогона оставляем в `outputs/` (они игнорируются git).
