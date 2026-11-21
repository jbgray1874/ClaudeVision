"""Offline, fail-closed reconciliation of completed TTI runs to a revised tracker.

No portal client, estimation imports, network calls or job submission. XLSX edits
are deliberately surgical: native in-cell pictures and all other ZIP members stay
byte-identical. The existing production tracker writer is not changed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import posixpath
import re
import time
import tempfile
import uuid
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
RID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
REF = re.compile(r'(?<![0-9A-Za-z])(?:[A-Za-z]{1,4}-)?\d{3,}[A-Za-z]?(?:-[A-Za-z0-9]+)*')
FIELDS = ('A', 'D', 'E', 'F', 'G', 'H', 'L', 'N', 'AN')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def norm(v):
    return ' '.join(str(v if v is not None else '').split()).casefold()


def quantity(v):
    try:
        n = float(v)
        return int(n) if math.isfinite(n) and n > 0 and n.is_integer() else None
    except (TypeError, ValueError):
        return None


def money(v):
    if isinstance(v, bool) or v is None:
        raise ValueError('missing/invalid unit cost')
    n = Decimal(str(v))
    if not n.is_finite() or n < 0:
        raise ValueError('non-finite or negative unit cost')
    return float(n.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def drawing(v):
    m = REF.search(str(v or ''))
    return m.group(0).upper() if m else ''


class Tracker:
    """Read cached cell values without dropping richData, pictures, or tables."""
    def __init__(self, path, tab='Milwaukee'):
        self.path = Path(path).resolve()
        self.raw = self.path.read_bytes()
        self.sha256 = digest(self.raw)
        self.tab = tab
        with zipfile.ZipFile(io.BytesIO(self.raw)) as z:
            if len(z.namelist()) != len(set(z.namelist())):
                raise ValueError('duplicate XLSX ZIP members')
            book = ET.fromstring(z.read('xl/workbook.xml'))
            matches = [s for s in book.findall('s:sheets/s:sheet', NS) if s.get('name') == tab]
            if len(matches) != 1:
                raise ValueError(f'exact worksheet not found: {tab}')
            rid = matches[0].get(RID)
            rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
            target = next(r.get('Target') for r in rels if r.get('Id') == rid)
            self.member = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            self.xml = z.read(self.member).decode('utf-8')
            strings = []
            if 'xl/sharedStrings.xml' in z.namelist():
                strings = [''.join(si.itertext()) for si in ET.fromstring(z.read('xl/sharedStrings.xml'))]
            root = ET.fromstring(self.xml)
            self.rows, self.formulas = {}, set()
            for c in root.findall('s:sheetData/s:row/s:c', NS):
                address = c.get('r')
                m = re.fullmatch(r'([A-Z]+)(\d+)', address or '')
                if not m:
                    raise ValueError('cell without an ordinary A1 address')
                col, row = m[1], int(m[2])
                if c.find('s:f', NS) is not None:
                    self.formulas.add(address)
                v = c.find('s:v', NS)
                value = v.text if v is not None else None
                if c.get('t') == 's' and value is not None:
                    value = strings[int(value)]
                elif c.get('t') == 'inlineStr':
                    value = ''.join(t.text or '' for t in c.findall('.//s:t', NS))
                self.rows.setdefault(row, {})[col] = value
            headers = [(n, r) for n, r in self.rows.items() if n <= 20 and norm(r.get('L')) in ('drawing number', 'drawing no.', 'drawing no')]
            if not headers:
                raise ValueError('expected Drawing Number in L, within first 20 rows')
            # Prefer the literal table heading, not its linked display formula.
            self.header, heads = next(((n, r) for n, r in headers if f'L{n}' not in self.formulas), headers[0])
            for col, label in [('E', 'description'), ('N', 'quantity')]:
                if norm(heads.get(col)) != label:
                    raise ValueError(f'unsupported layout: expected {label} in {col}')
            costcols = {col for n, r in self.rows.items() if n <= self.header for col, v in r.items()
                        if re.sub(r'[^a-z]', '', norm(v)) in ('aicost', 'aicosts', 'aicosting', 'aipricing')}
            if len(costcols) != 1:
                raise ValueError('expected exactly one AI cost column heading; nothing guessed')
            self.costcol = costcols.pop()
            self.heads = heads
            self.merges = [m.get('ref') for m in root.findall('s:mergeCells/s:mergeCell', NS)]

    def jobs(self):
        return {n: r for n, r in self.rows.items() if n > self.header and r.get('E')}

    def identity(self, row):
        r = self.rows[row]
        # No fuzzy descriptions, GA-family matching, or reuse across quantities.
        return tuple(str(quantity(r.get(c))) if c == 'N' else norm(r.get(c)) for c in FIELDS)

    def brief_hash(self, row):
        """Exact 2026-11 tti_pricer.brief_for contract, to validate ledger binding."""
        r = self.rows[row]
        cell = str(r.get('L') or '').strip()
        ref = drawing(cell)
        bits = [f'TTI job, sheet row {row}.']
        if ref:
            extra = f' (the sheet says: {cell})' if cell and cell.upper() != ref else ''
            bits.append(f'Drawing number {ref}{extra}.')
        if r.get('E'):
            bits.append(f"Description: {str(r['E']).strip()}.")
        if r.get('G'):
            label = self.heads.get('G') if 'feedback' in norm(self.heads.get('G')) else 'Notes'
            bits.append(f"{label}: {str(r['G']).strip()}.")
        # Production includes every feedback column except G.
        for col, label in self.heads.items():
            if col != 'G' and re.search(r'\bfeedback', str(label), re.I) and r.get(col):
                bits.append(f'{label}: {str(r[col]).strip()}.')
        bits.append(f"Quantity: {quantity(r.get('N'))}.")
        return hashlib.sha1(' '.join(bits).encode()).hexdigest()[:12]


def read_json(path, sources):
    path = Path(path).resolve()
    raw = path.read_bytes()
    sources[str(path)] = digest(raw)
    return json.loads(raw.decode('utf-8-sig'))


def run_price(run, qty):
    prices = [money(p.get('unit_gbp')) for p in run.get('quantity_prices') or []
              if quantity(p.get('quantity')) == qty]
    if len(set(prices)) > 1:
        raise ValueError('conflicting quantity break prices')
    if prices:
        return prices[0]
    if quantity(run.get('units')) != qty:
        raise ValueError('run does not price this order quantity')
    return money(run.get('engine_price_gbp'))


def merged_cell(address, ranges):
    def split(a):
        col, row = re.fullmatch(r'([A-Z]+)(\d+)', a).groups()
        num = 0
        for ch in col: num = num * 26 + ord(ch) - 64
        return num, int(row)
    c, r = split(address)
    for span in ranges:
        lo, _, hi = span.partition(':')
        c1, r1 = split(lo)
        c2, r2 = split(hi or lo)
        if c1 <= c <= c2 and r1 <= r <= r2:
            return True
    return False


def make_plan(target, source, ledgers, runs_dir):
    sources = {str(target.path): target.sha256, str(source.path): source.sha256}
    entries = []
    for p in ledgers:
        data = read_json(p, sources)
        if not isinstance(data, dict):
            raise ValueError(f'not a ledger object: {p}')
        for e in data.values():
            if isinstance(e, dict) and e.get('row') is not None:
                entries.append(dict(e, ledger=str(Path(p).resolve())))
    indexed = {}
    for n in source.jobs():
        indexed.setdefault(source.identity(n), []).append(n)
    # A ledger can lag behind a completed service run. Do not label its older
    # result "latest" while an unbound newer result could belong to this scope.
    bound = {}
    for e in entries:
        oldrow = e.get('row')
        if oldrow not in source.jobs() or e.get('tab') != source.tab:
            continue
        if ((e.get('inputs') or {}).get('brief') == source.brief_hash(oldrow)
                and norm((e.get('inputs') or {}).get('client')) == 'tti'
                and norm(e.get('drawing')) == norm(drawing(source.rows[oldrow].get('L')))
                and quantity(e.get('quantity')) == quantity(source.rows[oldrow].get('N'))):
            bound.setdefault(str(e.get('run_id')), set()).add(source.identity(oldrow))
    runfiles = sorted(Path(runs_dir).glob('*.json'))
    if not runfiles:
        raise ValueError('no local service run files found')
    relevant_drawings = {drawing(r.get('L')) for r in target.jobs().values()}
    recent_runs = []
    for path in runfiles:
        raw = path.read_bytes()
        run = json.loads(raw.decode('utf-8-sig'))
        if norm(run.get('client')) == 'tti' and drawing(run.get('drawing_number')) in relevant_drawings:
            sources[str(path.resolve())] = digest(raw)
            recent_runs.append(run)
    results = []
    for n, row in target.jobs().items():
        result = dict(row=n, cell=f'{target.costcol}{n}', drawing=drawing(row.get('L')),
                      quantity=quantity(row.get('N')), description=row.get('E'),
                      before=row.get(target.costcol), action='held', reason='')
        results.append(result)
        if result['quantity'] is None:
            result['reason'] = 'quantity missing, zero, fractional or invalid; not priced or inferred'
            continue
        if not result['drawing']:
            result.update(action='unpriced', reason='no drawing reference; thumbnail/description pricing is a separate job')
            continue
        matches = indexed.get(target.identity(n), [])
        if len(matches) != 1:
            result['reason'] = 'changed/new brief or quantity, or ambiguous source rows; no row-number fallback'
            continue
        oldrow = matches[0]
        result['source_row'] = oldrow
        candidates, problems = [], []
        for e in entries:
            if e.get('row') != oldrow or e.get('tab') != source.tab:
                continue
            if norm(e.get('drawing')) != norm(result['drawing']) or quantity(e.get('quantity')) != result['quantity']:
                continue
            inputs = e.get('inputs') or {}
            if inputs.get('brief') != source.brief_hash(oldrow) or norm(inputs.get('client')) != 'tti':
                problems.append('ledger brief/client does not match the source tracker')
                continue
            runid = str(e.get('run_id') or '')
            if not re.fullmatch(r'[0-9a-f]{8,64}', runid):
                problems.append('no valid linked run ID')
                continue
            try:
                runpath = Path(runs_dir) / (runid + '.json')
                run = read_json(runpath, sources)
                if (run.get('run_id') != runid or norm(run.get('client')) != 'tti'
                        or norm(run.get('drawing_number')) != norm(result['drawing'])
                        or run.get('source') != 'TTI batch'):
                    raise ValueError('run identity/client/source mismatch')
                if run.get('status') != 'done':
                    raise ValueError(f"run is {run.get('status')}, not finished")
                finished = float(run.get('finished_at') or 0)
                if not math.isfinite(finished) or finished <= 0:
                    raise ValueError('run has no valid finish time')
                cost = run_price(run, result['quantity'])
                # The current ledger must actually bind this run, not merely retain
                # an older run_id while a new attempt is planned/held.
                if e.get('state') not in ('done', 'running', 'submitted'):
                    raise ValueError('ledger does not bind a completed/in-flight attempt')
                if e.get('state') == 'done' and money(e.get('unit_cost')) != cost:
                    raise ValueError('ledger cost and run cost disagree')
                candidates.append((finished, runid, cost, run, e))
            except (OSError, ValueError, TypeError, ArithmeticError) as exc:
                problems.append(str(exc))
        if not candidates:
            result['reason'] = '; '.join(sorted(set(problems))) or 'no verified completed run linked to this brief'
            continue
        candidates.sort(key=lambda x: x[0], reverse=True)
        finished, runid, cost, run, entry = candidates[0]
        if len({(c[1], c[2]) for c in candidates if c[0] == finished}) != 1:
            result['reason'] = 'ambiguous latest completed runs'
            continue
        result.update(run_id=runid, finished_at=finished, unit_cost=cost,
                      ledger=entry['ledger'], run_file=str(Path(runs_dir).resolve() / (runid + '.json')),
                      approval=entry.get('approval') or 'provisional: review required',
                      review=run.get('review') or {}, estimate_path=run.get('output_path'),
                      warning='Latest saved estimate only, not approval. Consult run review for missing costs and decisions.')
        unknown_newer = []
        for other in recent_runs:
            if (norm(other.get('drawing_number')) != norm(result['drawing'])
                    or other.get('status') != 'done' or float(other.get('finished_at') or 0) <= finished):
                continue
            try:
                run_price(other, result['quantity'])
            except (ValueError, ArithmeticError):
                continue
            known = bound.get(str(other.get('run_id')), set())
            if not known or target.identity(n) in known:
                unknown_newer.append(other.get('run_id'))
        if unknown_newer:
            result['reason'] = 'newer completed run not reconciled to this row: ' + ', '.join(sorted(unknown_newer))
            continue
        source_cost = source.rows[oldrow].get(source.costcol)
        if source_cost not in (None, ''):
            try:
                if money(source_cost) != cost:
                    result['reason'] = 'source tracker cost disagrees with linked completed run; reconcile history first'
                    continue
            except (ValueError, ArithmeticError):
                result['reason'] = 'source tracker has a non-numeric cost'
                continue
        if result['cell'] in target.formulas:
            result['reason'] = 'AI cost cell is a formula; not overwritten'
            continue
        if merged_cell(result['cell'], target.merges):
            result['reason'] = 'AI cost cell is merged; not overwritten'
            continue
        if result['before'] not in (None, ''):
            try:
                if money(result['before']) == cost:
                    result.update(action='unchanged', reason='already the latest verified saved price')
                    continue
            except (ValueError, ArithmeticError):
                result['reason'] = 'AI cost cell contains text/manual instruction; not overwritten'
                continue
            result.update(action='replace', reason='existing numeric price differs; explicit replacement required')
        else:
            result.update(action='fill', reason='latest verified completed run for unchanged brief and quantity')
    return dict(schema='tti_cost_reconcile.v1', created_at=time.time(), target=str(target.path),
                source=str(source.path), tab=target.tab, column=target.costcol,
                sources=sources, runs_dir=str(Path(runs_dir).resolve()),
                run_files=[p.name for p in runfiles], rows=results)


def patch_xml(xml, changes):
    """Replace only numeric AI-cost cells, preserving the rest of XML byte-for-byte."""
    for address, value in changes.items():
        if not re.fullmatch(r'[A-Z]+[1-9]\d*', address):
            raise ValueError('invalid cell address')
        price = money(value)
        pat = re.compile(r'<c\b(?=[^>]*\br="' + address + r'")[^>]*?(?:/>|>.*?</c>)', re.S)
        hits = list(pat.finditer(xml))
        if len(hits) > 1:
            raise ValueError('duplicate cell address')
        if hits:
            old = hits[0].group()
            if re.search(r'<f(?:\s|>)', old):
                raise ValueError('refusing formula overwrite')
            opening = old.split('>', 1)[0].rstrip('/')
            opening = re.sub(r'\s+t="[^"]*"', '', opening)
            # Only ordinary value/style cells may be replaced.
            if re.search(r'\b(?:cm|vm)=', opening):
                raise ValueError('cost cell carries metadata/picture')
            new = opening + f'><v>{price:.2f}</v></c>'
            xml = xml[:hits[0].start()] + new + xml[hits[0].end():]
        else:
            n = int(re.search(r'\d+', address)[0])
            rowpat = re.compile(r'<row\b(?=[^>]*\br="' + str(n) + r'")[^>]*>.*?</row>', re.S)
            m = rowpat.search(xml)
            if not m:
                raise ValueError('target row missing')
            content = m.group()
            def colnum(a):
                out = 0
                for ch in re.match(r'[A-Z]+', a)[0]: out = out * 26 + ord(ch) - 64
                return out
            pos = content.rfind('</row>')
            for c in re.finditer(r'<c\b[^>]*\br="([A-Z]+\d+)"', content):
                if colnum(c[1]) > colnum(address):
                    pos = c.start()
                    break
            new = f'<c r="{address}"><v>{price:.2f}</v></c>'
            xml = xml[:m.start()] + content[:pos] + new + content[pos:] + xml[m.end():]
    ET.fromstring(xml)  # Fail before writing if the package was not ordinary OOXML.
    return xml


def write_copy(target, changes, output):
    output = Path(output).resolve()
    if output == target.path or output.exists():
        raise ValueError('output must be a NEW file; source/previous outputs are never overwritten')
    if output.suffix.lower() != '.xlsx':
        raise ValueError('output must be .xlsx')
    if any(merged_cell(a, target.merges) for a in changes):
        raise ValueError('refusing merged cost cell')
    xml = patch_xml(target.xml, changes).encode('utf-8')
    data = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(target.raw)) as old, zipfile.ZipFile(data, 'w') as new:
        new.comment = old.comment
        for info in old.infolist():
            new.writestr(info, xml if info.filename == target.member else old.read(info.filename))
    written = data.getvalue()
    with zipfile.ZipFile(io.BytesIO(target.raw)) as old, zipfile.ZipFile(io.BytesIO(written)) as new:
        assert old.namelist() == new.namelist()
        for name in old.namelist():
            if name != target.member and old.read(name) != new.read(name):
                raise ValueError(f'unrelated XLSX member changed: {name}')
    # Validate a temporary file before atomically exposing it. A hard link is a
    # no-clobber publish on the same local volume; unsupported filesystems fail.
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.xlsx', delete=False) as f:
            temp = Path(f.name)
            f.write(written)
            f.flush()
            os.fsync(f.fileno())
        check = Tracker(temp, target.tab)
        for address, value in changes.items():
            col, row = re.fullmatch(r'([A-Z]+)(\d+)', address).groups()
            if money(check.rows[int(row)].get(col)) != money(value):
                raise ValueError('output value verification failed')
        if digest(target.path.read_bytes()) != target.sha256:
            raise ValueError('target changed before output publication')
        os.link(temp, output)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return digest(written)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--target', required=True, type=Path)
    ap.add_argument('--source', required=True, type=Path, help='older tracker whose row numbers the ledgers use')
    ap.add_argument('--ledger', required=True, action='append', type=Path, help='repeat only for ledgers of that source tracker')
    ap.add_argument('--runs-dir', required=True, type=Path, help='local service run JSON directory; no network lookup')
    ap.add_argument('--sheet-name', default='Milwaukee')
    ap.add_argument('--audit-dir', required=True, type=Path)
    ap.add_argument('--apply', action='store_true', help='write a NEW output copy; default is report only')
    ap.add_argument('--output', type=Path)
    ap.add_argument('--replace-existing', action='store_true', help='also replace matched numeric AI costs, with before/after audit')
    args = ap.parse_args(argv)
    if args.apply and not args.output:
        ap.error('--apply requires --output (a new workbook, never the input)')
    args.audit_dir.mkdir(parents=True, exist_ok=True)
    session = args.audit_dir / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    session.mkdir()
    def event(kind, **data):
        with (session / 'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(dict(time=time.time(), event=kind, **data), ensure_ascii=True) + '\n')
            f.flush()
            os.fsync(f.fileno())
    event('started', mode='apply' if args.apply else 'dry-run')
    try:
        target, source = Tracker(args.target, args.sheet_name), Tracker(args.source, args.sheet_name)
        plan = make_plan(target, source, args.ledger, args.runs_dir)
        (session / 'plan.json').write_text(json.dumps(plan, indent=2, ensure_ascii=True), encoding='utf-8')
        fields = ['row','cell','drawing','quantity','description','source_row','before','unit_cost','action','reason','run_id','finished_at','approval','warning','estimate_path']
        with (session / 'rows.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in plan['rows']:
                # Spreadsheet-safe strings in the audit CSV.
                writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v for k, v in row.items()})
        changes = {r['cell']: r['unit_cost'] for r in plan['rows'] if r['action'] == 'fill' or (r['action'] == 'replace' and args.replace_existing)}
        counts = {k: sum(r['action'] == k for r in plan['rows']) for k in ('fill','replace','unchanged','held','unpriced')}
        event('planned', counts=counts, selected=len(changes))
        if args.apply:
            # Freeze inputs. In-flight edits/runs mean retry, not a partial stale update.
            for path, expected in plan['sources'].items():
                if digest(Path(path).read_bytes()) != expected:
                    raise ValueError(f'source changed during reconciliation: {path}')
            if sorted(p.name for p in args.runs_dir.glob('*.json')) != plan['run_files']:
                raise ValueError('run inventory changed during reconciliation; retry')
            if not changes:
                raise ValueError('no eligible changes; no workbook written')
            output_hash = write_copy(target, changes, args.output)
            event('completed', output=str(args.output.resolve()), sha256=output_hash, cells=changes)
            print('WROTE new copy:', args.output)
        else:
            event('dry-run-completed')
            print('DRY RUN: no workbook changed; no estimates queued.')
        print('Rows:', json.dumps(counts), 'Selected:', len(changes))
        print('Audit:', session)
        return 0
    except Exception as exc:
        event('failed', error=str(exc))
        print('STOP:', exc)
        print('Audit:', session)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
