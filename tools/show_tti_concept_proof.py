"""Show the two concept proof rows for a person to review. Read-only.

It reads the local archive only and changes nothing. It is NOT an approval and its exit
code means nothing to the batch: approval is the batch's own --approve-proof, run by the
person who has looked at both estimates.
"""
import argparse
import json
from pathlib import Path
import sys


def summary(archive, rows):
    archive = Path(archive)
    plan = json.loads((archive/'plan.json').read_text(encoding='utf-8'))
    state = json.loads((archive/'state.json').read_text(encoding='utf-8'))
    out = []
    for n in rows:
        item = next((r for r in plan['rows'] if r['row'] == n), None)
        if item is None:
            out.append({'row': n, 'phase': 'not in the plan'}); continue
        entry = state['entries'].get(item['reference'], {})
        results = archive/item['reference']/'results'
        books = sorted(p.name for p in results.glob('*.xlsx')) if results.is_dir() else []
        out.append({'row': n, 'reference': item['reference'], 'phase': entry.get('phase') or 'not started',
                    'run_id': entry.get('run_id'), 'build': entry.get('expected_build'),
                    'unit_gbp': entry.get('unit_gbp'), 'quantity': item['quantity'],
                    'quantity_assumed': bool(item.get('quantity_assumed')),
                    'pictures': len(item.get('images') or []), 'description': item.get('description') or '',
                    'held_reason': entry.get('why'),
                    'AiCost_status': 'written' if entry.get('phase')=='done' else ('pending write-back' if entry.get('phase')=='archived' else 'not ready'),
                    'writeback_reason': entry.get('writeback_reason'),
                    'results_folder': str(results), 'workbooks': books})
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--local-archive', required=True, help='The batch folder that holds plan.json and state.json')
    p.add_argument('--rows', default='6,12')
    a = p.parse_args(argv)
    rows = [int(v) for v in a.rows.split(',')]
    for r in summary(a.local_archive, rows):
        print('=' * 78)
        print(f"row {r['row']}: {r['phase']}" + (f" | run {r['run_id']} | build {r['build']}" if r.get('run_id') else ''))
        if 'reference' not in r: continue
        print('  description:', r['description'][:300])
        print(f"  pictures sent: {r['pictures']} | quantity: {r['quantity']}" + (' (ASSUMED 1: none on the sheet)' if r['quantity_assumed'] else ''))
        print('  unit price GBP:', r['unit_gbp'] if r['unit_gbp'] is not None else '-')
        print('  AiCost:', r['AiCost_status'])
        if r['writeback_reason']: print('  write-back:', r['writeback_reason'])
        if r['held_reason']: print('  why:', r['held_reason'])
        print('  open to review:', r['results_folder'])
        for b in r['workbooks']: print('    ', b)
    print('=' * 78)
    print('This is a summary for review only. It approves nothing.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
