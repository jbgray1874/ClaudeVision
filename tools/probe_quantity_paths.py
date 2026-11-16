"""Read-only saved-record comparison. No workbook calculation, pricing or model call."""
import argparse
import importlib.util
import json
import hashlib
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quantity_flow_contract import audit  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('record')
parser.add_argument('--baseline', required=True)
parser.add_argument('--out', required=True)
args = parser.parse_args()
spec = importlib.util.spec_from_file_location('baseline_quantity', args.baseline)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
summary = json.loads(Path(args.record).read_text(encoding='utf-8-sig'))
before, after = baseline.audit(summary), audit(summary)
result = {'record': args.record, 'scope': 'quantity audit only; not workbook acceptance',
          'record_sha256': hashlib.sha256(Path(args.record).read_bytes()).hexdigest(),
          'baseline_sha256': hashlib.sha256(Path(args.baseline).read_bytes()).hexdigest(),
          'before': before, 'after': after,
          'before_counts': dict(Counter(i['code'] for i in before['issues'])),
          'after_counts': dict(Counter(i['code'] for i in after['issues']))}
Path(args.out).write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps({k: result[k] for k in ('scope', 'before_counts', 'after_counts')}, indent=2))
