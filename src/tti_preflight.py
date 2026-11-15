"""Read-only tracker/pack preflight. Never submits or changes live data."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import contextlib
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

SCHEMA = 'tti_preflight.v1'
REF = re.compile(r'(?<![0-9A-Za-z])(?:[A-Za-z]{1,4}-)?\d{3,}[A-Za-z]?(?:-[A-Za-z0-9]+)*')
RISKS = {
    'weld_scope': r'\bweld(?:ed|ing|s)?\b|\bdressing\b',
    'mirror_or_handed_parts': r'\bmirror(?:ed|s)?\b|\bleft.?hand|\bright.?hand',
    'fixing_identity': r'\bthumb\s*nut|\bscrew|\bfixing|\bfastener',
    'edging_units_and_scope': r'\bedg(?:e|ing|ed)\b',
    'print_evidence_and_rate': r'\bprint(?:ed|ing)?\b|\bgraphic',
    'material_specification': r'\bMDF\b|\bPVC\b|\bPETG\b|\bacrylic|\btimber|\bplywood|\bsteel',
    'change_or_decision': r'\bconfirm|\bTBC\b|\bTBD\b|\bchange|\bupdate|\bawait|\brevis',
}


def text(value):
    return '' if value is None else str(value).strip()


def header_key(value):
    return re.sub(r'[^a-z0-9]', '', text(value).lower())


def positive_quantity(value):
    """No rounding, default-one, blank-as-zero or boolean coercion."""
    if value is None or isinstance(value, bool) or not text(value):
        return None
    try:
        n = Decimal(text(value))
        if n.is_finite() and n > 0 and n == n.to_integral_value():
            return int(n)
    except InvalidOperation:
        pass
    return None


def references(value):
    return list(dict.fromkeys(m.group().upper() for m in REF.finditer(text(value))))


def risk_signals(fields):
    return [{'risk': name, 'source': label, 'matched': m.group()}
            for label, value in fields for name, pattern in RISKS.items()
            if (m := re.search(pattern, text(value), re.I))]


def find_headers(rows):
    for i, row in enumerate(rows[:20], 1):
        keys = [header_key(v) for v in row]
        drawing = [j for j, k in enumerate(keys) if k in ('drawingnumber', 'drawing', 'dwg', 'dwgnumber')]
        if not drawing:
            continue
        if len(drawing) != 1:
            raise ValueError('Duplicate drawing headers')
        cols = {'drawing': drawing[0]}
        for name, options in {'quantity': ('quantity', 'qty'), 'cost': ('aicost',),
                              'description': ('description', 'itemdescription')}.items():
            found = [j for j, k in enumerate(keys) if k in options]
            if len(found) != 1:
                raise ValueError(f'Expected one {name} header, found {len(found)}')
            cols[name] = found[0]
        cols['feedback'] = [j for j, k in enumerate(keys) if 'feedback' in k]
        for required in ('previousfeedback', 'latestfeedback'):
            if sum(required in keys[j] for j in cols['feedback']) != 1:
                raise ValueError(f'Expected one {required} header')
        return i, cols
    raise ValueError('Drawing header not found in first 20 rows')


def brief_for(row):
    lines = [row['description'], f"Drawing as requested: {row['drawing_cell']}"]
    lines += [f"{f['label']}:\n{f['text']}" for f in row['feedback'] if f['text']]
    return '\n\n'.join(x for x in lines if x)


def rows_from_values(values, formulas=None):
    header_row, cols = find_headers(values)
    labels = values[header_row - 1]
    out = []
    for number, cells in enumerate(values[header_row:], header_row + 1):
        get = lambda c: cells[c] if c < len(cells) else None
        raw = text(get(cols['drawing']))
        desc = text(get(cols['description']))
        feedback = [{'label': text(labels[c]), 'text': text(get(c)), 'column': c + 1} for c in cols['feedback']]
        if header_key(raw) in ('drawingnumber', 'drawing', 'dwg'):
            continue
        if not (raw or desc or any(f['text'] for f in feedback)):
            continue
        refs = references(raw)
        qraw = get(cols['quantity'])
        row = {'row': number, 'drawing_cell': raw, 'drawing': refs[0] if len(refs) == 1 else '',
               'references': refs, 'description': desc, 'quantity_raw': qraw,
               'quantity': positive_quantity(qraw), 'feedback': feedback,
               'cost_before': get(cols['cost']), 'holds': [], 'review_reasons': []}
        if len(refs) != 1:
            row['holds'].append('No unique drawing reference' if not refs else 'Multiple drawing references in one row')
        elif '-' not in refs[0]:
            row['holds'].append('Job number only; establish the intended drawing/configuration')
        if row['quantity'] is None:
            row['holds'].append('Quantity must be an explicit positive whole number')
        if formulas:
            source = formulas[number - 1]
            for name in ('drawing', 'quantity', 'description', 'cost'):
                c = cols[name]
                if c < len(source) and isinstance(source[c], str) and source[c].startswith('='):
                    row['review_reasons'].append(f'{name} uses a cached formula result; freshness not established')
                    if name in ('drawing', 'quantity'):
                        row['holds'].append(f'Confirm formula-derived {name} before queueing')
            for c in cols['feedback']:
                if c < len(source) and isinstance(source[c], str) and source[c].startswith('='):
                    row['holds'].append(f'Confirm formula-derived feedback in column {c + 1}')
        if any(f['text'].startswith(('#REF!', '#VALUE!', '#N/A', '#NAME?', '#DIV/0!')) for f in feedback):
            row['holds'].append('Feedback contains a spreadsheet error')
        if row['cost_before'] is not None and text(row['cost_before']):
            row['holds'].append('AI cost already present; explicit reprice decision required')
        row['brief'] = brief_for(row)
        row['risk_signals'] = risk_signals([('description', desc)] + [(f['label'], f['text']) for f in feedback])
        row['brief_sha256'] = hashlib.sha256(row['brief'].encode()).hexdigest()
        row['input_key'] = hashlib.sha256(json.dumps([raw, row['quantity'], row['brief_sha256']], ensure_ascii=False).encode()).hexdigest()
        out.append(row)
    grouped = defaultdict(list)
    for row in out:
        if row['drawing']:
            grouped[(row['drawing'], row['quantity'])].append(row)
    for group in grouped.values():
        if len(group) > 1:
            conflict = len({r['input_key'] for r in group}) > 1
            for row in group:
                row['holds'].append('Conflicting briefs/revisions for same drawing and quantity' if conflict else 'Duplicate tracker row; select one explicitly')
                row['related_rows'] = [r['row'] for r in group if r is not row]
    by_drawing = defaultdict(list)
    for row in out:
        if row['drawing']:
            by_drawing[row['drawing']].append(row)
    for group in by_drawing.values():
        if len({r['quantity'] for r in group}) > 1:
            for row in group:
                row['holds'].append('Drawing repeated at different quantities; confirm grouping and preserve each row brief')
    return out, {'header_row': header_row, 'columns': cols,
                 'feedback_headers': [text(labels[c]) for c in cols['feedback']]}


def read_tracker(path, sheet_name=None):
    import openpyxl
    snapshots = []
    title = None
    for data_only in (True, False):
        book = openpyxl.load_workbook(path, read_only=True, data_only=data_only, keep_links=False)
        try:
            sheet = book[sheet_name] if sheet_name else book.active
            if sheet.max_row > 100000 or sheet.max_column > 500:
                raise ValueError('Workbook dimensions exceed preflight limits')
            title = sheet.title
            snapshots.append(list(sheet.iter_rows(values_only=True)))
        finally:
            book.close()
    rows, meta = rows_from_values(*snapshots)
    meta['sheet'] = title
    return rows, meta


def open_index(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def index_inventory(path, drawings):
    with contextlib.closing(open_index(path)) as db:
        meta = dict(db.execute('SELECT k,v FROM meta'))
        found = {}
        for drawing in sorted(set(drawings)):
            found[drawing] = [dict(zip(('folder', 'name', 'size', 'mtime', 'archive'), rec)) for rec in db.execute(
                'SELECT folders.path, files.name, files.size, files.mtime, folders.archive '
                'FROM files JOIN folders ON folders.id=files.folder WHERE files.did=?', (drawing,))]
    return found, meta


def classify(row):
    if row['holds']:
        return 'hold'
    pack = row.get('pack') or {}
    if pack.get('state') != 'resolved':
        return 'unchecked'
    m = pack.get('manifest') or {}
    requested_revision = re.search(r'\bREV(?:ISION)?\s*[:.-]?\s*([A-Z0-9]+)\b', row.get('drawing_cell', ''), re.I)
    if requested_revision and requested_revision.group(1).upper() != text(m.get('revision')).upper():
        return 'hold'
    if not m.get('price_ok') or m.get('conflicts') or m.get('configurations_unconfirmed'):
        return 'hold'
    if not m.get('complete') or not m.get('references_read') or m.get('unread_assemblies') or m.get('missing'):
        return 'review_incomplete_pack'
    if m.get('identity') != 'verified' or m.get('bought_in_unmatched') or row['risk_signals'] or row['review_reasons']:
        return 'review'
    return 'candidate_for_pilot'


def same_time(mtime, listed):
    """Is a file's time on disk the time its listing gave?

    The resolver's manifest gives each file `modified`, an ISO time to the minute, and no
    `mtime`. The first form of this check read `mtime`, so every pack that reached its files
    failed with KeyError and none was validated (the 02:06 report, 15 Nov 2026: 41 of 76).
    A listing that carries a raw `mtime` is compared to the second; one that carries only
    `modified` is compared to the minute; one that carries neither cannot be compared and is
    not called changed on that account."""
    if listed.get('mtime') is not None:
        try:
            return abs(float(mtime) - float(listed['mtime'])) <= 1.0
        except (TypeError, ValueError):
            return False
    stamp = text(listed.get('modified'))
    if not stamp:
        return True
    return datetime.fromtimestamp(mtime).isoformat(timespec='minutes') == stamp[:16]


def worker_resolve(repo, index, drawing, client):
    """Avoid folders_for/build_db/run_batch: those can write or dispatch work."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(repo) / 'src'))
    import drawing_index as di
    import pack_resolver as pr
    db = Path(index)
    rows = di.db_rows_for(db, drawing)
    holders = {folder for folder, files, archived in rows if not archived and
               any(pr._same(pr.drawing_id(p.name), drawing) for p, _, _ in files)}
    if not holders:
        return {'state': 'not_found', 'reason': 'No current indexed GA candidate; index is not an exhaustive live search'}
    live = []
    for folder in sorted(holders):
        try:
            listed = di.live_rows(folder, depth=6)
        except OSError as exc:
            return {'state': 'unavailable', 'reason': f'Cannot read {folder}: {type(exc).__name__}'}
        if listed is None:
            return {'state': 'unavailable', 'reason': f'Cannot read candidate folder: {folder}'}
        live.extend(listed)
    m = pr.resolve(drawing, live, client=client, lookup=lambda did: di.db_lookup(db, did), client_folders_only=True)
    errors = []
    selected = [f for member in m.get('members', []) for f in member.get('files', [])]
    for f in selected:
        p = Path(f['path'])
        try:
            st = p.stat()
            with p.open('rb') as stream:
                stream.read(1)
            if st.st_size != f.get('size') or not same_time(st.st_mtime, f):
                errors.append(f'Changed since listing: {p}')
        except OSError as exc:
            errors.append(f'Cannot open {p}: {type(exc).__name__}')
    return {'state': 'unavailable' if errors else 'resolved', 'errors': errors,
            'selected_file_count': len(selected), 'manifest': m,
            'limits': 'PDF text/resolver only; no SolidWorks read or visual approval. Shared lookups use existing index. Recheck at submission.'}


def bounded_resolve(repo, index, drawing, client, seconds):
    cmd = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', '--repo', str(repo),
           '--index', str(index), '--drawing', drawing, '--client', client]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=seconds)
        if done.returncode:
            return {'state': 'error', 'reason': done.stderr[-1500:]}
        result = json.loads(done.stdout)
        if not isinstance(result, dict) or result.get('state') not in ('resolved', 'not_found', 'unavailable'):
            return {'state': 'error', 'reason': 'Invalid worker result schema'}
        return result
    except subprocess.TimeoutExpired:
        return {'state': 'timeout', 'reason': f'Pack check exceeded {seconds:g}s; nothing queued'}
    except (OSError, ValueError) as exc:
        return {'state': 'error', 'reason': str(exc)}


def safe_csv(value):
    value = text(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def reasons_for(row):
    reasons = row['holds'] + row['review_reasons']
    pack = row.get('pack') or {}
    if pack.get('state', 'not_checked') != 'resolved':
        reasons = reasons + [pack.get('reason') or 'Live pack not checked']
    m = pack.get('manifest') or {}
    for field in ('missing', 'unread_assemblies', 'conflicts', 'bought_in_unmatched', 'assumptions'):
        if m.get(field):
            reasons = reasons + [f'{field}: {m[field]}']
    if m.get('configurations_unconfirmed'):
        reasons = reasons + ['Configurations not confirmed']
    rev = re.search(r'\bREV(?:ISION)?\s*[:.-]?\s*([A-Z0-9]+)\b', row.get('drawing_cell', ''), re.I)
    if rev and pack.get('state') == 'resolved' and rev.group(1).upper() != text(m.get('revision')).upper():
        reasons = reasons + [f"Requested revision {rev.group(1)} does not match resolved revision {m.get('revision')}"]
    reasons += [f"Review {r['risk']} ({r['source']}: {r['matched']})" for r in row['risk_signals']]
    return reasons


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'preflight.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, default=str)
    columns = ['row', 'drawing', 'drawing_cell', 'quantity', 'status', 'indexed_files', 'pack_state', 'reasons', 'brief']
    with (output / 'preflight.csv').open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for r in report['rows']:
            values = {k: r.get(k, '') for k in columns}
            values.update(indexed_files=len(r.get('indexed_candidates', [])), pack_state=(r.get('pack') or {}).get('state', 'not_checked'),
                          reasons='; '.join(reasons_for(r)))
            writer.writerow({k: safe_csv(v) for k, v in values.items()})
    lines = ['# TTI preflight review', '', 'Read-only evidence, not a queue or costing approval.', '', '## Counts', '']
    lines += [f'- {k}: {v}' for k, v in report['summary'].items()]
    lines += ['', '## Limitations', '', '- Index matches are not complete drawing packs.',
              '- No CAD/model extraction, final cost verification, queue reconciliation, tracker write-back or runner test is performed.',
              '- Feedback risk matches are review prompts. No match does not prove absence of risk.',
              '- Existing AI costs are held. Completed runs with blank costs need separate ledger reconciliation.',
              '', '## Rows', '', '| Row | Drawing | Qty | Position | Reason |', '| --- | --- | --- | --- | --- |']
    for r in report['rows']:
        reason = '; '.join(reasons_for(r))
        esc = lambda x: text(x).replace('|', '\\|').replace('\n', ' ')
        lines.append('| ' + ' | '.join(esc(x) for x in (r['row'], r['drawing'] or r['drawing_cell'], r['quantity'], r['status'], reason)) + ' |')
    with (output / 'REVIEW.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sheet')
    ap.add_argument('--sheet-name')
    ap.add_argument('--index', required=True)
    ap.add_argument('--repo', default=r'C:\ClaudeVision')
    ap.add_argument('--client', default='TTI')
    ap.add_argument('--output')
    ap.add_argument('--resolve', action='store_true', help='Read live packs; never submit jobs')
    ap.add_argument('--timeout', type=float, default=45)
    ap.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--drawing', help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.timeout <= 0 or args.timeout > 300:
        ap.error('timeout must be >0 and <=300 seconds')
    if args.worker:
        with contextlib.redirect_stdout(io.StringIO()):
            result = worker_resolve(args.repo, args.index, args.drawing, args.client)
        print(json.dumps(result, ensure_ascii=True, default=str))
        return 0
    if not args.sheet or not args.output:
        ap.error('--sheet and --output are required')
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        ap.error('output must be a new or empty report directory')
    started = time.monotonic()
    source_hashes = {str(Path(p).resolve()): file_sha256(p) for p in (args.sheet, args.index)}
    print('Reading tracker values and formulas (read-only; images not loaded)', flush=True)
    rows, meta = read_tracker(args.sheet, args.sheet_name)
    drawings = sorted({r['drawing'] for r in rows if r['drawing']})
    found, index_meta = index_inventory(args.index, drawings)
    packs = {}
    if args.resolve:
        for n, drawing in enumerate(drawings, 1):
            print(f'[{n}/{len(drawings)}] checking {drawing} (limit {args.timeout:g}s)', flush=True)
            packs[drawing] = bounded_resolve(args.repo, args.index, drawing, args.client, args.timeout)
            print(f"  {packs[drawing]['state']}", flush=True)
    for r in rows:
        r['indexed_candidates'] = found.get(r['drawing'], [])
        r['pack'] = packs.get(r['drawing'], {'state': 'not_checked'})
        r['status'] = classify(r)
    report = {'schema': SCHEMA, 'created_at': datetime.now(timezone.utc).isoformat(),
              'tracker': str(Path(args.sheet).resolve()), 'tracker_metadata': meta,
              'index': str(Path(args.index).resolve()), 'index_metadata': index_meta,
              'source_sha256': source_hashes,
              'live_resolution_requested': args.resolve, 'elapsed_seconds': round(time.monotonic() - started, 2), 'rows': rows}
    report['summary'] = {'tracker_item_rows': len(rows), 'rows_with_drawing_text': sum(bool(r['drawing_cell']) for r in rows),
                         'rows_with_one_reference': sum(bool(r['drawing']) for r in rows), 'unique_references': len(drawings),
                         'references_with_index_matches': sum(bool(v) for v in found.values()),
                         'live_pack_checks_completed': sum(p.get('state') == 'resolved' for p in packs.values()),
                         'rows_by_position': dict(Counter(r['status'] for r in rows))}
    for path, digest in source_hashes.items():
        if file_sha256(path) != digest:
            raise RuntimeError(f'Source changed during preflight; rerun without concurrent edits: {path}')
    report['source_hashes_unchanged'] = True
    write_report(report, output)
    print(json.dumps(report['summary'], indent=2))
    print(f"Report: {output / 'REVIEW.md'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
