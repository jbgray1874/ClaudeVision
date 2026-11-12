"""Read-only probe of a saved job record against its calculated workbook (D-578):

    python tools/diagnose/probe_final_charges.py output/json/<stem>.json output/estimates/<book>.xlsx [--out proof.json]

Prints the final-charge audit — the section requirements against the charged cells, the
saved file's cached values included — and exits 2 where it fails. Nothing is written
unless --out names a file. Probe as proposed in the Codex review package of 21 Oct 2026.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from final_charge_contract import record

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('record'); p.add_argument('workbook'); p.add_argument('--out')
    a=p.parse_args()
    doc=json.loads(Path(a.record).read_text(encoding='utf-8'))
    result=record(doc, a.workbook)
    text=json.dumps(result,indent=2,ensure_ascii=False)
    print(text)
    if a.out: Path(a.out).write_text(text,encoding='utf-8')
    sys.exit(0 if result['passed'] else 2)
