"""Prepare evidence for collecting completed drawing runs; never submit or write prices.

Reads a ledger, local service history and explicitly named local result folders.
Only a new report is written. This is deliberately not a recovery executor: a
matching brief does not prove that two drawing packs contained identical files.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile


def read_json(path):
    raw = Path(path).read_bytes()
    return json.loads(raw.decode('utf-8-sig')), hashlib.sha256(raw).hexdigest()


def positive_money(value):
    try:
        if isinstance(value, bool):
            return None
        number = Decimal(str(value))
        return str(number) if number.is_finite() and number > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def scope_matches(old, new):
    """No fuzzy matching, cross-quantity reuse or missing evidence treated as equal."""
    fields = ('client', 'drawing_number', 'units', 'method', 'brief_sha256')
    a, b = old.get('submitted_scope') or {}, new.get('submitted_scope') or {}
    if not all(a.get(k) is not None and a.get(k) != '' for k in fields):
        return False
    if not all(a.get(k) == b.get(k) for k in fields):
        return False
    return (a.get('brief_status') == b.get('brief_status') == 'filed'
            and isinstance(a.get('reference_documents'), list)
            and a.get('reference_documents') == b.get('reference_documents'))


def service_price_validated(run):
    """Persisted history omits the computed API flag; reproduce its documented gate.

    An explicit API refusal always wins. This is not independent workbook validation.
    """
    if run.get('price_validated') is False or run.get('error'):
        return False
    names = [str(d.get('name') or '').lower() for d in run.get('deliverables') or [] if isinstance(d, dict)]
    return (run.get('status') == 'done' and positive_money(run.get('engine_price_gbp')) is not None
            and any(n.endswith(('.xlsx', '.xlsm')) for n in names))


def candidate_runs(entry, runs, old):
    quantity = entry.get('quantity')
    candidates = []
    for run in runs:
        # The service's own price_validated gate is not waived here.
        if (not service_price_validated(run)
                or positive_money(run.get('engine_price_gbp')) is None
                or run.get('stopped_by_hand') or run.get('cancel_requested')
                or run.get('instruction_refused') or run.get('units') != quantity
                or run.get('drawing_number') != entry.get('drawing')
                or run.get('client') != (entry.get('inputs') or {}).get('client')):
            continue
        if not scope_matches(old, run):
            continue
        ended = run.get('finished_at')
        if not isinstance(ended, (float, int)) or isinstance(ended, bool) or ended <= 0:
            continue
        candidates.append(run)
    return sorted(candidates, key=lambda r: (r['finished_at'], r['run_id']), reverse=True)


def verify_saved_pair(run, record, book):
    """Cross-check the run's own record and cached Excel result, without recalculation.

    Never use a fixed M105: longer estimates move the totals. The final read-back
    names the cell. D5 may abbreviate the product, so exact identity comes from the
    run-bound record and its submitted scope, not fuzzy matching that header.
    """
    data, _ = read_json(record)
    provenance = data.get('run_provenance') or {}
    totals = (data.get('final_estimate') or {}).get('totals') or {}
    address = str(totals.get('unit_cell') or '')
    if (data.get('declared_product') != run.get('drawing_number')
            or provenance.get('service_run_id') != run.get('run_id')
            or not scope_matches({'submitted_scope': provenance.get('submitted_scope')}, run)
            or data.get('assumed_job_quantity') != run.get('units')
            or not re.fullmatch(r'Estimate![A-Z]+[1-9][0-9]*', address)):
        raise ValueError('Canonical record identity, scope, quantity or price-cell binding failed')
    expected = Decimal(positive_money(run.get('engine_price_gbp')) or '0').quantize(Decimal('.01'))
    recorded = Decimal(positive_money(totals.get('unit_gbp')) or '0').quantize(Decimal('.01'))
    if expected <= 0 or recorded != expected:
        raise ValueError('Record read-back price differs from the service result')
    namespace = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    rid = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
    with zipfile.ZipFile(book) as archive:
        if archive.testzip() is not None:
            raise ValueError('Workbook ZIP CRC failed')
        sheets = ET.fromstring(archive.read('xl/workbook.xml')).findall('s:sheets/s:sheet', namespace)
        sheet = next(s for s in sheets if s.get('name') == 'Estimate')
        relationships = {r.get('Id'): r.get('Target') for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        target = relationships[sheet.get(rid)]
        target = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
        wanted = {'D6', address.split('!')[1]}
        values = {}
        for cell in ET.fromstring(archive.read(target)).findall('.//s:sheetData/s:row/s:c', namespace):
            if cell.get('r') not in wanted:
                continue
            if cell.get('t') not in (None, 'n'):
                raise ValueError('Price/quantity cell is not numeric')
            value = cell.find('s:v', namespace)
            if value is None or value.text is None:
                raise ValueError('Price/quantity cell has no cached result')
            values[cell.get('r')] = Decimal(value.text)
    if (not all(v.is_finite() for v in values.values()) or set(values) != wanted
            or values['D6'] != Decimal(str(run['units']))
            or values[address.split('!')[1]].quantize(Decimal('.01')) != expected):
        raise ValueError('Workbook cached quantity/price differs from the run-bound record')
    return {'workbook_price_independently_checked': True, 'price_cell': address,
            'cached_unit_gbp': str(expected), 'quantity': run['units'],
            'calculation_reexecuted': False, 'price_quality_approved': False}


def result_files(run, roots):
    """Only exact canonical filenames declared by THIS run, never generic latest files."""
    declared = {str(d.get('name') or '') for d in run.get('deliverables') or [] if isinstance(d, dict)}
    code = str(run.get('drawing_number') or '')
    # Reference is escaped: it is data, not a glob or regex instruction.
    pattern = re.compile(re.escape(code) + r'_\d{8}_\d{6}_record\.json\Z', re.I)
    names = sorted(n for n in declared if pattern.fullmatch(n))
    found = []
    for name in names:
        book_name = name.removesuffix('_record.json') + '.xlsx'
        if book_name not in declared:
            continue
        for root in roots:
            record, book = Path(root) / name, Path(root) / book_name
            if not record.is_file() or not book.is_file():
                continue
            item = {'record': str(record), 'record_sha256': hashlib.sha256(record.read_bytes()).hexdigest(),
                    'workbook': str(book), 'workbook_sha256': hashlib.sha256(book.read_bytes()).hexdigest(),
                    'workbook_price_independently_checked': False}
            try:
                item.update(verify_saved_pair(run, record, book))
            except (ValueError, KeyError, StopIteration, ET.ParseError, zipfile.BadZipFile, InvalidOperation) as exc:
                item['validation_error'] = str(exc)
            found.append(item)
    return found


def prepare(ledger_path, runs_dir, roots, rows):
    ledger, ledger_hash = read_json(ledger_path)
    if not isinstance(ledger, dict):
        raise ValueError('Ledger must be an object')
    runs = []
    for path in sorted(Path(runs_dir).glob('*.json')):
        run, sha = read_json(path)
        if not isinstance(run, dict) or not run.get('run_id'):
            continue
        run['_evidence'] = {'path': str(path), 'sha256': sha}
        runs.append(run)
    indexed = {r['run_id']: r for r in runs}
    entries = [e for e in ledger.values() if isinstance(e, dict) and e.get('row') in rows]
    if len(entries) != len(rows) or {e['row'] for e in entries} != set(rows):
        raise ValueError('Every selected row must have exactly one ledger entry')
    report = {'schema': 'drawing_recovery_preparation.v1', 'jobs_submitted': 0,
              'production_writes': 0, 'ledger': str(ledger_path), 'ledger_sha256': ledger_hash,
              'automatic_collection_authorised': False, 'rows': []}
    for entry in sorted(entries, key=lambda e: e['row']):
        old = indexed.get(entry.get('run_id'), {})
        matches = candidate_runs(entry, runs, old)
        item = {'source_row': entry['row'], 'drawing': entry.get('drawing'),
                'quantity': entry.get('quantity'), 'ledger_state': entry.get('state'),
                'ledger_run_id': entry.get('run_id'), 'candidates': [],
                'next_action': 'investigate_no_validated_matching_result; not permission to resubmit'}
        for run in matches:
            item['candidates'].append({'run_id': run['run_id'], 'unit_gbp': positive_money(run['engine_price_gbp']),
                'finished_at': run['finished_at'], 'evidence': run['_evidence'],
                'same_recorded_brief_quantity_method': True, 'pack_bytes_verified_equal': False,
                'files': result_files(run, roots)})
        if matches:
            item['next_action'] = ('validate_latest_candidate_workbook_and_pack_binding_then_collect_existing_only; '
                                   'do_not_rerun_or_write_during_active_batch')
        report['rows'].append(item)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--runs-dir', required=True, type=Path)
    parser.add_argument('--records-root', action='append', required=True, type=Path)
    parser.add_argument('--rows', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    rows = [int(r) for r in args.rows.split(',')]
    if not rows or len(rows) != len(set(rows)) or min(rows) <= 0:
        parser.error('Rows must be distinct positive integers')
    output = args.output.resolve()
    # Refuse production/source locations, including a new filename in a source folder.
    sources = [args.ledger.resolve().parent, args.runs_dir.resolve(), *(r.resolve() for r in args.records_root)]
    if output == args.ledger.resolve() or any(output.is_relative_to(root) for root in sources):
        parser.error('Report must be outside source folders and cannot replace the ledger')
    result = prepare(args.ledger, args.runs_dir, args.records_root, rows)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(f'PREPARED {len(result["rows"])} rows; no source edits, services, jobs or workbook writes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
