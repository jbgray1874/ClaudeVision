"""Read-only saved-record diagnostic. Does not recost or rewrite a workbook."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owned_route_evidence import findings as graded_findings

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path)
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding='utf-8-sig'))
    findings = {kind: [f['message'] for f in graded_findings(record) if f['kind'] == kind]
                for kind in ('contradiction', 'unresolved')}
    print(json.dumps({'record': str(args.record), 'findings': findings,
                      'acceptance_proven': False,
                      'note': 'Diagnostic only; a clean result is not full estimate acceptance.'}, indent=2))
