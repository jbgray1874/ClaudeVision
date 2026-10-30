"""Compare two saved job records by identity (D-579), with no model, pricing, database or
Excel call:

    python tools/diagnose/compare_saved_runs.py before.json after.json [--out comparison.json]

Exit 0 means structurally comparable — not unchanged, not approved; exit 2 means a warning
(an ambiguous or missing identity, no calculated read-back) or a different product or order
quantity. --out is exclusive-create: an existing file is never overwritten.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from run_comparison import compare

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('before'); p.add_argument('after'); p.add_argument('--out')
    a=p.parse_args()
    docs=[json.loads(Path(x).read_text(encoding='utf-8-sig')) for x in (a.before,a.after)]
    result=compare(*docs)
    text=json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)
    if a.out:
        with Path(a.out).open('x',encoding='utf-8') as f: f.write(text+'\n')
    print(text)
    return 2 if any(result['warnings'].values()) or not result['same_product'] or not result['same_order_quantity'] else 0

if __name__=='__main__': sys.exit(main())
