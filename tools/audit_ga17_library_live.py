"""Read-only evidence for four GA17 library drawings; prints JSON, never submits.

Run with Python from this review package, not the production service. Checks BOTH
areas independently, even if Design has a match. Access failures remain errors.
No drawing contents are changed/copied and no index is opened or created.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from live_library_lookup import LiveLibraryLookup
from pack_resolver import PackCheckStalled, _archive_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--design', default=r'\\sdi-dc01\CAD\Design')
    ap.add_argument('--prototype', default=r'\\sdi-dc01\CAD\Prototype')
    args = ap.parse_args()
    report = {'at_utc': datetime.now(timezone.utc).isoformat(), 'read_only': True,
              'index_used': False, 'results': [],
              'scope_limit': 'Own numbered jobs and non-job library containers. Unrelated numbered jobs not traversed.'}
    blocked = False
    for label, root in [('Design', args.design), ('Prototype', args.prototype)]:
        # Audit archived candidates too, without choosing them for an estimate.
        lookup = LiveLibraryLookup([(label, Path(root))], include_archives=True)
        for drawing in ['1264-GA', '1338-GA', '3512-GA-A', '9976-01']:
            try:
                files = lookup(drawing) + lookup.sheet_files(drawing)
                report['results'].append({'drawing': drawing, 'area': label,
                    'status': 'found_candidates' if files else 'not_found_in_checked_scope',
                    'files': [{'path': str(p), 'bytes': s, 'mtime': m, 'archive': _archive_path(p)} for p, s, m in files]})
            except PackCheckStalled as exc:
                blocked = True
                report['results'].append({'drawing': drawing, 'area': label,
                                          'status': 'blocked', 'reason': str(exc)})
        report.setdefault('search_evidence', []).extend(lookup.evidence)
    print(json.dumps(report, indent=2))
    return 2 if blocked else 0


if __name__ == '__main__':
    raise SystemExit(main())
