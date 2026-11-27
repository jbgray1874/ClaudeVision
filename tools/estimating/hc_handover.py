"""Hotel Chocolat estimating handover: one consolidated, fully costed workbook and its files.

    python hc_handover.py --plan PLAN.json --release RELEASE.json --schedule SCHEDULE.xlsx --out NEW_FOLDER
                          [--rerun A.33446,A.34225]

Builds, in a NEW folder (an existing one is refused):

  <pack> estimating pack <date>.xlsx   the consolidated workbook
      Price schedule      every product, grouped by family: the run's unit cost, any provisional
                          adjustment, the revised unit cost, the basis, the status and a link to
                          the supporting workbook. No grand total: the Wall layouts are alternatives.
      Adjustments / Gaps and confirmations / Basis statement   from the provisional schedule
      one tab per product, in family order: its full Estimate sheet as the run left it, VALUES and
                          formats (formulas are not carried, so nothing can break or relink)
  <n family>\\<drawing>\\    copies of that product's full workbook, report and client quote page
  _Superseded\\<drawing>\\<run>\\   copies of older results replaced by a rerun
  _Withheld client quotes\\<drawing>\\   client quote pages whose price no longer applies
  index.html, manifest.csv, and a copy of the provisional schedule

Every source is only read. Both services must return their whole run history or nothing is built.
A product named in --rerun must have a finished run on the verified release build (its own log
shows the build), or nothing is built. Every link written is checked; the exit code is non-zero if
any link is broken. Generic: products, families and adjustments come from the plan and schedule.
"""
from __future__ import annotations

import argparse
import copy
import csv
import datetime
import html
import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

SERVICES = tuple(os.environ.get('HC_SERVICES', 'http://localhost:8071,http://localhost:8072').split(','))
LIMIT = int(os.environ.get('HC_RUN_LIMIT') or 500)
DONE = ('done', 'complete', 'completed')
BOOK = re.compile(r'_\d{8}_\d{6}\.xlsx$', re.I)


def key(v):
    return re.sub(r'[^A-Z0-9]', '', str(v or '').upper())


def long_path(p):
    s = str(p)
    if os.name != 'nt' or s.startswith('\\\\?\\'):
        return s
    s = os.path.abspath(s)
    return '\\\\?\\UNC\\' + s[2:] if s.startswith('\\\\') else '\\\\?\\' + s


def exists(p):
    return bool(p) and os.path.exists(long_path(p))


def runs_by_fingerprint():
    found, gaps = {}, []
    for s in SERVICES:
        try:
            with urllib.request.urlopen(s + '/api/estimate?limit=%d' % LIMIT, timeout=60) as r:
                runs = json.loads(r.read().decode('utf-8')).get('runs', [])
        except Exception as e:                                          # noqa: BLE001
            gaps.append('%s did not answer (%s)' % (s, type(e).__name__))
            continue
        if len(runs) >= LIMIT:
            gaps.append('%s returned %d runs, its limit' % (s, len(runs)))
        for r in runs:
            m = re.search(r'\[hc:([0-9a-f]{12})\]', str(r.get('job_title') or ''))
            if m:
                found.setdefault(m.group(1), {})[str(r.get('run_id'))] = r
    if gaps:
        raise SystemExit('NOT BUILT: the run history is incomplete (%s), so which run is current is unknown.'
                         % '; '.join(gaps))
    return found


def log_build(run):
    m = re.search(r'\[build\] engine source: ([0-9a-f]{7,40})', '\n'.join(str(x) for x in (run.get('log') or [])))
    return m.group(1) if m else ''


def files_of(run, drawing):
    book, reports, quotes = None, [], []
    for d in run.get('deliverables') or []:
        path = str((d or {}).get('path') or '') if isinstance(d, dict) else ''
        name = os.path.basename(path)
        if BOOK.search(name) and key(BOOK.sub('', name)) == key(drawing):
            book = book or path
        elif name.lower().endswith(('.html', '.htm')):
            (quotes if '_quote' in name.lower() else reports).append(path)
    return book, reports, quotes


def value_after(ws, label):
    for row in ws.iter_rows():
        for i, c in enumerate(row):
            if isinstance(c.value, str) and c.value.strip().startswith(label):
                for c2 in row[i + 1:]:
                    if isinstance(c2.value, (int, float)):
                        return float(c2.value)
    return None


def copy_sheet(src, dst):
    """The source sheet's values and formats into dst; formulas are not carried."""
    for row in src.iter_rows():
        for c in row:
            if c.value is None and not c.has_style:
                continue
            t = dst.cell(row=c.row, column=c.column, value=c.value)
            if c.has_style:
                t.font, t.fill, t.border = copy.copy(c.font), copy.copy(c.fill), copy.copy(c.border)
                t.alignment, t.number_format = copy.copy(c.alignment), c.number_format
    for rng in src.merged_cells.ranges:
        dst.merge_cells(str(rng))
    for col, dim in src.column_dimensions.items():
        dst.column_dimensions[col].width = dim.width
    for r, dim in src.row_dimensions.items():
        if dim.height:
            dst.row_dimensions[r].height = dim.height
    dst.sheet_view.showGridLines = src.sheet_view.showGridLines


def read_schedule(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    adj = {}
    ws = wb['Schedule']
    head = None
    for row in ws.iter_rows(values_only=True):
        if row and row[0] == 'Product':
            head = list(row)
            continue
        if head and row and row[0] and re.match(r'^[A-Z]\.\d{5}$', str(row[0])):
            rec = dict(zip(head, row))
            adj[key(row[0])] = rec
    return wb, adj


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--plan', type=Path, required=True)
    ap.add_argument('--release', type=Path, required=True)
    ap.add_argument('--schedule', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--rerun', default='A.33446,A.34225')
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit('NOT BUILT: %s already exists; the handover is always a new folder.' % a.out)
    plan = json.loads(a.plan.read_text(encoding='utf-8-sig'))
    release = json.loads(a.release.read_text(encoding='utf-8-sig'))
    rel_build, verified = str(release['build'])[:7], float(release['loaded_verified_at'])
    rerun = {key(x) for x in a.rerun.split(',') if x.strip()}
    sched_wb, adjustments = read_schedule(a.schedule)
    runs = runs_by_fingerprint()

    products, problems = [], []
    for p in sorted(plan['products'], key=lambda p: (p['pack'], p['drawing'])):
        done = sorted((r for r in runs.get(p['fingerprint'], {}).values() if str(r.get('status')).lower() in DONE),
                      key=lambda r: float(r.get('queued_at') or 0), reverse=True)
        on_release = [r for r in done if log_build(r).startswith(rel_build) and float(r.get('queued_at') or 0) >= verified]
        if key(p['drawing']) in rerun:
            if not on_release:
                problems.append('%s has no finished run on the verified build %s' % (p['drawing'], rel_build))
                continue
            current, superseded = on_release[0], [r for r in done if r is not on_release[0]]
        else:
            current, superseded = (done[0] if done else None), (done[1:] if done else [])
        products.append({'p': p, 'run': current, 'superseded': superseded})
    if problems:
        raise SystemExit('NOT BUILT: ' + '; '.join(problems))

    a.out.mkdir(parents=True)
    stamp = datetime.date.today().isoformat()
    pack_name = 'Hotel Chocolat estimating pack %s.xlsx' % stamp
    shutil.copy2(a.schedule, a.out / a.schedule.name)
    wb = openpyxl.Workbook()
    ps = wb.active
    ps.title = 'Price schedule'
    ps['A1'] = 'Hotel Chocolat - consolidated estimating pack (%s). Provisional costs for estimating review, NOT a customer quotation.' % stamp
    ps['A1'].font = openpyxl.styles.Font(bold=True, size=13)
    ps['A2'] = ('Unit costs per finished product (quantity 1). No grand total: alternative layouts are not added together. '
                'Each product\'s full Estimate sheet follows on its own tab; supporting files are in the family folders.')
    heads = ['Family', 'Drawing', 'Product', 'Quantity basis', 'Run unit cost GBP', 'Provisional adjustment GBP',
             'Revised unit cost GBP', 'Price basis', 'Run status', 'Run', 'Supporting workbook', 'Detail tab']
    ps.append([])
    ps.append(heads)
    for c in ps[4]:
        c.font = openpyxl.styles.Font(bold=True)
        c.fill = openpyxl.styles.PatternFill('solid', fgColor='DDE7F0')
    manifest, index_rows, links = [], [], []
    for item in products:
        p, run = item['p'], item['run']
        fam_dir = a.out / re.sub(r'[<>:"/\\|?*]', '', p['pack'])
        dkey = key(p['drawing'])
        unit, status, book_rel, tab = None, 'NO FINISHED RUN', '', ''
        reports_rel, quotes_rel = [], []
        if run:
            book, reports, quotes = files_of(run, p['drawing'])
            dest = fam_dir / p['drawing']
            dest.mkdir(parents=True, exist_ok=True)
            if book and exists(book):
                shutil.copy2(long_path(book), dest / os.path.basename(book))
                book_rel = os.path.relpath(dest / os.path.basename(book), a.out)
                src = openpyxl.load_workbook(long_path(book), data_only=True)
                est = src['Estimate'] if 'Estimate' in src.sheetnames else src.active
                unit = value_after(est, 'Total Unit Cost Price')
                status = str(est['H6'].value or 'finished')
                tab = re.sub(r'[\[\]:*?/\\]', '', '%s %s' % (p['pack'].split(' ')[0], p['drawing']))[:31]
                copy_sheet(est, wb.create_sheet(tab))
                src.close()
            else:
                status = 'WORKBOOK NOT FOUND (%s)' % (os.path.basename(book) if book else 'none listed')
            for r in reports:
                if exists(r):
                    shutil.copy2(long_path(r), dest / os.path.basename(r))
                    reports_rel.append(os.path.relpath(dest / os.path.basename(r), a.out))
            adj = adjustments.get(dkey)
            withheld = bool(adj) and key(p['drawing']) not in rerun
            for q in quotes:
                if not exists(q):
                    continue
                qdir = (a.out / '_Withheld client quotes' / p['drawing']) if withheld else dest
                qdir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(long_path(q), qdir / os.path.basename(q))
                if not withheld:
                    quotes_rel.append(os.path.relpath(qdir / os.path.basename(q), a.out))
        for old in item['superseded']:
            ob, orep, oq = files_of(old, p['drawing'])
            sdir = a.out / '_Superseded' / p['drawing'] / str(old.get('run_id'))
            for f in [ob] + orep + oq:
                if f and exists(f):
                    sdir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(long_path(f), sdir / os.path.basename(f))
        adj = adjustments.get(dkey)
        adjustment = revised = None
        if key(p['drawing']) in rerun:
            basis = 'RERUN on verified build %s' % rel_build
            revised = unit
        elif adj and adj.get('Adjustment (GBP)') is not None:
            orig = adj.get('Original unit price (GBP)')
            if unit is not None and orig is not None and abs(float(orig) - unit) > 0.01:
                raise SystemExit('NOT BUILT: %s schedule original %s does not match its run workbook %s'
                                 % (p['drawing'], orig, unit))
            adjustment = round(float(adj['Adjustment (GBP)']), 2)
            revised = round((unit or 0) + adjustment, 2) if unit is not None else None
            basis = 'Original run + PROVISIONAL adjustment (see Adjustments)'
        else:
            basis = 'Original run, unchanged' if not p.get('brief') else 'Original run: priced from a brief (allowance)'
            revised = unit
        r = ps.max_row + 1
        ps.append([p['pack'], p['drawing'], p['title'], 'per finished product (1)', unit, adjustment, revised, basis,
                   status[:120], (run or {}).get('run_id'), os.path.basename(book_rel) if book_rel else 'NOT FOUND', tab])
        if book_rel:
            ps.cell(row=r, column=11).hyperlink = book_rel
            links.append(book_rel)
        if tab:
            ps.cell(row=r, column=12).hyperlink = "#'%s'!A1" % tab
        for col in (5, 6, 7):
            ps.cell(row=r, column=col).number_format = '#,##0.00'
        portal = [(n, (run or {}).get(k)) for n, k in (('walkthrough', 'walkthrough_url'), ('bundle', 'bundle_url'),
                                                       ('pack', 'pack_url')) if (run or {}).get(k)]
        manifest.append({'family': p['pack'], 'drawing': p['drawing'], 'product': p['title'], 'basis': basis,
                         'run': (run or {}).get('run_id'), 'run_unit_gbp': unit, 'adjustment_gbp': adjustment,
                         'revised_unit_gbp': revised, 'workbook': book_rel, 'reports': '; '.join(reports_rel),
                         'client_quote': '; '.join(quotes_rel), 'portal': '; '.join(u for _, u in portal)})
        links += reports_rel + quotes_rel
        index_rows.append((p, basis, revised, book_rel, reports_rel, quotes_rel, portal))
    for i, w in enumerate([30, 10, 46, 22, 16, 18, 18, 44, 40, 14, 40, 14], 1):
        ps.column_dimensions[get_column_letter(i)].width = w
    ps.freeze_panes = 'A5'
    at = 1
    for name in ('Adjustment lines', 'Gaps and confirmations', 'Basis statement'):
        if name in sched_wb.sheetnames:
            copy_sheet(sched_wb[name], wb.create_sheet(name if name != 'Adjustment lines' else 'Adjustments', at))
            at += 1
    wb.save(a.out / pack_name)

    with (a.out / 'manifest.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0]))
        w.writeheader()
        w.writerows(manifest)
    e = html.escape
    rows = []
    for p, basis, revised, book_rel, reps, quotes, portal in index_rows:
        link = lambda rel: '<a href="%s">%s</a>' % (e(rel.replace(os.sep, '/')), e(os.path.basename(rel)))
        rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td style="text-align:right">%s</td><td>%s</td>'
                    '<td>%s</td><td>%s</td><td>%s</td></tr>' % (
                        e(p['pack']), e(p['drawing']), e(p['title']), e(basis),
                        '' if revised is None else '{:,.2f}'.format(revised),
                        link(book_rel) if book_rel else 'NOT FOUND', '<br>'.join(link(x) for x in reps),
                        '<br>'.join(link(x) for x in quotes) or ('withheld' if adjustments.get(key(p['drawing'])) else ''),
                        ' | '.join('<a href="%s">%s</a>' % (e(u), n) for n, u in portal)))
    (a.out / 'index.html').write_text(
        '<!doctype html><html><head><meta charset="utf-8"><title>Hotel Chocolat handover</title><style>'
        'body{font:13px Segoe UI,Arial;margin:16px}table{border-collapse:collapse}td,th{border:1px solid #bbb;'
        'padding:4px 6px;vertical-align:top}th{background:#dde7f0}</style></head><body>'
        '<h2>Hotel Chocolat - estimating handover (%s)</h2><p>Start with <a href="%s">%s</a>. Provisional costs for '
        'estimating review, not a customer quotation. Wall of Chocolate layouts are alternatives.</p><table><tr>'
        '<th>Family</th><th>Drawing</th><th>Product</th><th>Price basis</th><th>Revised unit cost GBP</th>'
        '<th>Workbook</th><th>Reports</th><th>Client quote</th><th>Portal</th></tr>%s</table></body></html>'
        % (stamp, e(pack_name), e(pack_name), ''.join(rows)), encoding='utf-8')

    broken = [x for x in links if not (a.out / x).exists()]
    missing_books = [m['drawing'] for m in manifest if not m['workbook']]
    print('Built %s: %d products, %d detail tabs, %d links checked, %d broken.'
          % (a.out, len(manifest), len(wb.sheetnames) - 1 - sum(1 for n in ('Adjustments', 'Gaps and confirmations', 'Basis statement') if n in wb.sheetnames), len(links), len(broken)))
    for x in broken:
        print('  BROKEN LINK: %s' % x)
    if missing_books:
        print('  NO WORKBOOK FOUND for: %s' % ', '.join(missing_books))
    return 0 if not broken and not missing_books else 3


if __name__ == '__main__':
    raise SystemExit(main())
