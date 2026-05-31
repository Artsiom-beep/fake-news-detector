import json
from pathlib import Path
import itertools
import os
import subprocess

BASE = Path('outputs/factcheck_runs')
DATA = Path('data/factcheck/splits/dev.jsonl')

# Grid for FACTCHECK_MODE and simple env knobs (implemented in pipeline as mode only for now)
MODES = ['strict', 'balanced', 'bold']

results = []
for mode in MODES:
    out = BASE / f'dev_calib_{mode}.json'
    env = os.environ.copy()
    env['FACTCHECK_MODE'] = mode
    cmd = ['.\\.venv\\Scripts\\python', 'src\\eval_factcheck.py', '--dataset', str(DATA), '--out', str(out)]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    acc = None
    if out.exists():
        try:
            acc = json.loads(out.read_text(encoding='utf-8')).get('accuracy')
        except Exception:
            pass
    results.append({'mode': mode, 'returncode': p.returncode, 'accuracy': acc, 'out': str(out)})

best = sorted([r for r in results if r['accuracy'] is not None], key=lambda x: x['accuracy'], reverse=True)
report = {'results': results, 'best': best[0] if best else None}
rep_path = BASE / 'dev_calibration_report.json'
rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
