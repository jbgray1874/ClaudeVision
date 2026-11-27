"""Hotel Chocolat: the estimating pack, built from every product's newest finished workbook.

    python hc_estimating_pack.py --plan PLAN.json --release RELEASE.json --schedule SCHEDULE.xlsx
                                 --out NEW_FOLDER [--rerun A.33446,A.34225]

Reads only. Writes, in a NEW folder:

  Hotel Chocolat estimating pack <date>.xlsx
      Price schedule     every product by family: unit cost, material, labour, what the figure rests on,
                         confidence, items to confirm, GBP at stake, run, workbook. No grand total
                         (alternative layouts are not added).
      Wall of Chocolate  both layouts side by side: totals, every sheet part (qty, blank, gauge, GBP),
                         bought-in lines, labour by operation, top review items with GBP at stake.
      Adjustments        the provisional corrections, line by line (from the schedule).
      Review items       the top GBP-at-stake items across the job, by product.
      Gaps and confirmations / Basis statement   from the schedule.
      <family> <drawing> one tab per product: its Estimate sheet as the run left it (values + formats).
  Review packs\\         the planner's family packs and master schedule, if given (--review DIR).
  <family>\\<drawing>\\   a copy of each product's newest workbook, report and client quote page.
  _Superseded\\          older results replaced by a rerun.
  _Withheld client quotes\\   quote pages whose price no longer applies (provisionally adjusted products).
  Handover note.docx    what changed, how to read the pack, what to confirm.
  index.html, manifest.csv

Both services must return their whole run history, or nothing is built. A --rerun product must have
a finished run on the verified release build; the schedule's original must match the run workbook.
Every link written is checked. Exit 0 only when every product has a workbook and no link is broken.
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
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

SERVICES = tuple(os.environ.get('HC_SERVICES', 'http://localhost:8071,http://localhost:8072').split(','))
LIMIT = int(os.environ.get('HC_RUN_LIMIT') or 5000)
DONE = ('done', 'complete', 'completed')
BOOK = re.compile(r'_\d{8}_\d{6}\.xlsx$', re.I)
H = Font(bold=True)
HEAD = PatternFill('solid', fgColor='DDE7F0')
WARN = PatternFill('solid', fgColor='FFF2CC')
BAD = PatternFill('solid', fgColor='F8CBAD')
WRAP = Alignment(wrap_text=True, vertical='top')


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


def money(v):
    try:
        return float(str(v).replace('£', '').replace('GBP', '').replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def runs_by_fingerprint():
    found, gaps = {}, []
    for s in SERVICES:
        try:
            with urllib.request.urlopen(s + '/api/estimate?limit=%d' % LIMIT, timeout=90) as r:
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
        raise SystemExit('NOT BUILT: the run history is incomplete (%s).' % '; '.join(gaps))
    return found


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


def read_book(path):
    """What an estimator needs from one finished workbook."""
    wb = openpyxl.load_workbook(long_path(path), data_only=True)
    est = wb['Estimate'] if 'Estimate' in wb.sheetnames else wb.active
    out = {'unit': value_after(est, 'Total Unit Cost Price'), 'material': value_after(est, 'Total Material Cost'),
           'labour': value_after(est, 'Total Labour Cost'), 'status': str(est['H6'].value or ''),
           'bought': [], 'sheet': [], 'labour_by_op': {}, 'confirm': [], 'missing': [], 'market_gbp': 0.0}
    for r in range(11, 51):
        c = est.cell(r, 3).value
        if c and isinstance(est.cell(r, 13).value, (int, float)):
            out['bought'].append((str(c).split('  [')[0], est.cell(r, 9).value, est.cell(r, 10).value,
                                  est.cell(r, 11).value, est.cell(r, 13).value))
    for r in range(52, 147):
        name, total = est.cell(r, 3).value, est.cell(r, 13).value
        if not isinstance(name, str) or not isinstance(total, (int, float)) or not total:
            continue
        # Sheet steel rows: qty E, blank F x G, gauge H. Acrylic/board rows: qty D, blank E x F, gauge G.
        if isinstance(est.cell(r, 5).value, (int, float)) and isinstance(est.cell(r, 8).value, (int, float)) \
                and est.cell(r, 4).value in (None, ''):
            out['sheet'].append((name, est.cell(r, 5).value, est.cell(r, 6).value, est.cell(r, 7).value, est.cell(r, 8).value, total))
        elif isinstance(est.cell(r, 4).value, (int, float)):
            out['sheet'].append((name, est.cell(r, 4).value, est.cell(r, 5).value, est.cell(r, 6).value, est.cell(r, 7).value, total))
    for r in range(148, 223):
        op, v = est.cell(r, 3).value, est.cell(r, 13).value
        if op and isinstance(v, (int, float)):
            out['labour_by_op'][str(op)] = out['labour_by_op'].get(str(op), 0.0) + v
    if 'AI Explanation' in wb.sheetnames:
        rows = list(wb['AI Explanation'].iter_rows(values_only=True))
        head = next((i for i, r in enumerate(rows) if r and str(r[0] or '').strip() == '#'), None)
        if head is not None:
            cols = [str(v or '') for v in rows[head]]
            for r in rows[head + 1:]:
                if not r or r[0] in (None, '') or not str(r[0]).strip().isdigit():
                    break
                item = dict(zip(cols, r))
                out['confirm'].append({'kind': str(item.get('Kind') or ''), 'decision': str(item.get('Decision') or ''),
                                       'part': str(item.get('Part') or ''), 'action': str(item.get('Action') or ''),
                                       'stake': money(item.get('£ at stake')) or 0.0})
                if item.get('Kind') == 'Market figure':
                    out['market_gbp'] += money(item.get('£ at stake')) or 0.0
                if item.get('Kind') == 'Missing price':
                    out['missing'].append(str(item.get('Part') or ''))
    out['est'] = est
    out['wb'] = wb
    return out


def copy_sheet(src, dst):
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
    dst.sheet_view.showGridLines = src.sheet_view.showGridLines


def table(ws, top, heads, rows, widths=None):
    for i, h in enumerate(heads, 1):
        c = ws.cell(row=top, column=i, value=h)
        c.font, c.fill, c.alignment = H, HEAD, WRAP
    for r, row in enumerate(rows, top + 1):
        for i, v in enumerate(row, 1):
            c = ws.cell(row=r, column=i, value=v)
            c.alignment = WRAP
            if isinstance(v, float):
                c.number_format = '#,##0.00'
    for i, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return top + 1 + len(rows)


def read_schedule(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    adj, head = {}, None
    for row in wb['Schedule'].iter_rows(values_only=True):
        if row and row[0] == 'Product':
            head = list(row)
            continue
        if head and row and row[0] and re.match(r'^[A-Z]\.\d{5}$', str(row[0])):
            adj[key(row[0])] = dict(zip(head, row))
    return wb, adj


def handover_note(path, stamp, rel_build, products, walls, adjustments, missing_books):
    """A plain handover note the estimator can read without opening the workbook."""
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError:
        return None
    doc = Document()
    doc.styles['Normal'].font.size = Pt(10.5)
    doc.add_heading('Hotel Chocolat (HotelChocolat-1204): AI estimating pack', 0)
    doc.add_paragraph('%s. Provisional costs for estimating review. Not a customer quotation.' % stamp)
    doc.add_heading('What this is', 1)
    doc.add_paragraph('AI estimates for all %d products in the Hotel Chocolat drawing pack, in eight product families. Each product '
                      'was estimated from its complete drawing pack: bill of materials, sheet parts, bought-in lines, operations and '
                      'finishes. Every figure is a unit cost per finished product at quantity 1.' % len(products))
    doc.add_heading('How to use the pack', 1)
    for line in ('1. Price schedule tab: every product by family, with its unit cost, material and labour, the confidence level, '
                 'how many items are open and the money at stake in them.',
                 '2. Confidence: DRAWING means costed from the drawings. PROVISIONAL means a corrected line sits on the Adjustments '
                 'tab and the revised unit cost is the one to use. ALLOWANCE means no readable drawings were supplied, so the product '
                 'is priced from a brief by analogy with its family.',
                 '3. Review items tab: the open decisions across the whole job, most money first. Work down it before quoting.',
                 '4. Each product has its own tab with its full estimate sheet, and its full workbook, report and client quote page '
                 'sit in its family folder.',
                 '5. Gaps and confirmations tab: what still needs an answer, by product.'):
        doc.add_paragraph(line)
    doc.add_heading('Wall of Chocolate', 1)
    for d, w in walls.items():
        doc.add_paragraph('%s %s: unit cost GBP %s (material %s, labour %s). 30 boxes: 150 spacers, 60 tops, 120 shelves, '
                          '120 ticket surrounds.' % (d, w['title'], fmt(w['unit']), fmt(w['material']), fmt(w['labour'])))
    doc.add_paragraph('The two layouts are ALTERNATIVES. Price them separately; never add them together.')
    doc.add_paragraph('Both are DRAFT. The items with the most at stake:')
    for d, w in walls.items():
        for c in w['top'][:6]:
            doc.add_paragraph('%s: %s (%s), GBP %s at stake' % (d, c['decision'], c['part'], fmt(c['stake'])), style='List Bullet')
    doc.add_heading('Products with a provisional adjustment', 1)
    doc.add_paragraph('For these, use the revised unit cost on the price schedule, not the workbook total. Each corrected line, its '
                      'quantity, the original and revised cost and the basis are on the Adjustments tab.')
    for k, a in adjustments.items():
        doc.add_paragraph('%s: workbook GBP %s, adjustment GBP %s, revised GBP %s' % (
            a.get('Product'), fmt(a.get('Original unit price (GBP)')), fmt(a.get('Adjustment (GBP)')),
            fmt(a.get('Revised unit price (GBP)'))), style='List Bullet')
    doc.add_heading('Please confirm before quoting', 1)
    for line in ('Cash desk panel C33799: 18 mm (material note) or 6 mm (section)?',
                 'Plinth finish system, including any fire-rated requirement (the GA scan is unreadable).',
                 'Whether both Wall of Chocolate layouts are being supplied, or one is an alternative.',
                 'Wall shelf pusher C-33490: its BOM row states 1, the sheet costs 150.',
                 'Wall unpriced lines (D-33491 and the plating freight) need a price.'):
        doc.add_paragraph(line, style='List Bullet')
    doc.add_heading('Scope notes', 1)
    doc.add_paragraph('Three shelving products (B.33381, B.33384, B.34469) were priced from a brief because the drawing files supplied '
                      'for them are empty. A.34504, A.33559 and B.34468 have brackets priced on whole stock sheets; their material is '
                      'likely overstated and a correction will follow. Drawings named by the pack but not supplied (D.34046, B.33542, '
                      'E.33599, C.33460, B.33520) are carried as allowances. Signage is a separate scope and is not in these prices.')
    if missing_books:
        doc.add_paragraph('NO WORKBOOK FOUND for: %s. Their prices are not in this pack.' % ', '.join(missing_books))
    doc.add_heading('Where the files are', 1)
    doc.add_paragraph('Everything in this folder is a copy; the originals stay in the per-product folders on K:. Each family folder '
                      'holds each product\'s workbook, report and client quote page. Client quote pages for the provisionally adjusted '
                      'products are in _Withheld client quotes and must not go to the customer as they stand.')
    doc.save(path)
    return path


def fmt(v):
    v = money(v)
    return '{:,.2f}'.format(v) if v is not None else 'n/a'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--plan', type=Path, required=True)
    ap.add_argument('--release', type=Path, required=True)
    ap.add_argument('--schedule', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--rerun', default='A.33446,A.34225')
    ap.add_argument('--review', type=Path, help='the planner review folder to copy (master schedule + family packs)')
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit('NOT BUILT: %s already exists; the pack is always a new folder.' % a.out)
    plan = json.loads(a.plan.read_text(encoding='utf-8-sig'))
    release = json.loads(a.release.read_text(encoding='utf-8-sig'))
    rel_build, verified = str(release['build'])[:7], float(release['loaded_verified_at'])
    rerun = {key(x) for x in a.rerun.split(',') if x.strip()}
    sched_wb, adjustments = read_schedule(a.schedule)
    runs = runs_by_fingerprint()

    def log_build(run):
        m = re.search(r'\[build\] engine source: ([0-9a-f]{7,40})', '\n'.join(str(x) for x in (run.get('log') or [])))
        return m.group(1) if m else ''

    products, problems = [], []
    for p in sorted(plan['products'], key=lambda p: (p['pack'], p['drawing'])):
        done = sorted((r for r in runs.get(p['fingerprint'], {}).values() if str(r.get('status')).lower() in DONE),
                      key=lambda r: float(r.get('queued_at') or 0), reverse=True)
        if key(p['drawing']) in rerun:
            ok = [r for r in done if float(r.get('queued_at') or 0) >= verified and (not log_build(r) or log_build(r).startswith(rel_build))]
            if not ok:
                problems.append('%s has no finished run since the verified release of %s' % (p['drawing'], rel_build))
                continue
            current, superseded = ok[0], [r for r in done if r is not ok[0]]
        else:
            current, superseded = (done[0] if done else None), (done[1:] if done else [])
        products.append({'p': p, 'run': current, 'superseded': superseded})
    if problems:
        raise SystemExit('NOT BUILT: ' + '; '.join(problems))

    a.out.mkdir(parents=True)
    stamp = datetime.datetime.now().strftime('%d %b %Y %H:%M')
    shutil.copy2(a.schedule, a.out / a.schedule.name)
    if a.review and a.review.is_dir():
        (a.out / 'Review packs').mkdir()
        for f in a.review.glob('*.xlsx'):
            shutil.copy2(f, a.out / 'Review packs' / f.name)
    wb = openpyxl.Workbook()
    ps = wb.active
    ps.title = 'Price schedule'
    ps['A1'] = 'Hotel Chocolat: consolidated estimating pack, %s. Provisional costs for estimating review, NOT a customer quotation.' % stamp
    ps['A1'].font = Font(bold=True, size=13)
    ps['A2'] = ('Unit cost per finished product (quantity 1), from each product\'s newest finished workbook. No grand total: the two '
                'Wall of Chocolate layouts are alternatives. Confidence: DRAWING = costed from the drawings; PROVISIONAL = known error, '
                'use the revised figure; ALLOWANCE = no readable drawings, priced from a brief by analogy.')
    ps['A2'].alignment = WRAP
    heads = ['Family', 'Drawing', 'Product', 'Unit cost GBP (workbook)', 'Material GBP', 'Labour GBP', 'Provisional adjustment GBP',
             'Revised unit cost GBP', 'Confidence', 'What the figure rests on', 'Items to confirm', 'GBP at stake (market lines)',
             'Unpriced lines', 'Run', 'Workbook', 'Detail tab']
    rows, manifest, index_rows, links, walls, review_items, missing_books = [], [], [], [], {}, [], []
    for item in products:
        p, run = item['p'], item['run']
        dkey = key(p['drawing'])
        fam_dir = a.out / re.sub(r'[<>:"/\\|?*]', '', p['pack'])
        facts, book_rel, tab, reports_rel, quotes_rel = None, '', '', [], []
        if run:
            book, reports, quotes = files_of(run, p['drawing'])
            dest = fam_dir / p['drawing']
            dest.mkdir(parents=True, exist_ok=True)
            if book and exists(book):
                shutil.copy2(long_path(book), dest / os.path.basename(book))
                book_rel = os.path.relpath(dest / os.path.basename(book), a.out)
                facts = read_book(book)
                tab = re.sub(r'[\[\]:*?/\\]', '', '%s %s' % (p['pack'].split(' ')[0], p['drawing']))[:31]
                copy_sheet(facts['est'], wb.create_sheet(tab))
                facts['wb'].close()
            else:
                missing_books.append(p['drawing'])
            for r in reports:
                if exists(r):
                    shutil.copy2(long_path(r), dest / os.path.basename(r))
                    reports_rel.append(os.path.relpath(dest / os.path.basename(r), a.out))
            withheld = dkey in adjustments and dkey not in rerun
            for q in quotes:
                if exists(q):
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
        else:
            missing_books.append(p['drawing'])
        unit = facts['unit'] if facts else None
        adj = adjustments.get(dkey)
        adjustment = None
        if dkey in rerun:
            confidence, rests = 'DRAWING', 'Costed from the complete drawing pack (build %s).' % rel_build
            revised = unit
            if facts:
                old = money(adj.get('Original unit price (GBP)')) if adj else None
                walls[p['drawing']] = dict(facts, title=p['title'], old=old, unit=unit,
                                           top=sorted(facts['confirm'], key=lambda c: -c['stake'])[:12])
        elif adj and adj.get('Adjustment (GBP)') is not None:
            orig = money(adj.get('Original unit price (GBP)'))
            if unit is not None and orig is not None and abs(orig - unit) > 0.01:
                raise SystemExit('NOT BUILT: %s schedule original %s does not match its run workbook %s' % (p['drawing'], orig, unit))
            adjustment = round(money(adj['Adjustment (GBP)']), 2)
            revised = round((unit or 0) + adjustment, 2) if unit is not None else None
            confidence = 'PROVISIONAL (use revised)'
            rests = str(adj.get('Basis / notes') or 'Corrected lines on the Adjustments tab.')
        elif p.get('brief'):
            confidence, rests, revised = 'ALLOWANCE', 'No readable drawings: priced from a brief by analogy with its family.', unit
        else:
            confidence, rests, revised = 'DRAWING', 'Completed run, unchanged.', unit
        if dkey in {'A34504', 'A33559', 'B34468'}:
            rests += ' Known stock-blank fault on its brackets (correction deferred): material likely overstated.'
        n_confirm = len(facts['confirm']) if facts else None
        rows.append([p['pack'], p['drawing'], p['title'], unit, facts['material'] if facts else None,
                     facts['labour'] if facts else None, adjustment, revised, confidence, rests, n_confirm,
                     round(facts['market_gbp'], 2) if facts else None, ', '.join(facts['missing']) if facts else None,
                     (run or {}).get('run_id'), os.path.basename(book_rel) if book_rel else 'NOT FOUND', tab])
        if facts:
            for c in facts['confirm']:
                if c['stake'] >= 50:
                    review_items.append((c['stake'], p['drawing'], c['kind'], c['decision'], c['part'], c['action']))
        portal = [(n, (run or {}).get(k)) for n, k in (('walkthrough', 'walkthrough_url'), ('bundle', 'bundle_url'),
                                                       ('pack', 'pack_url')) if (run or {}).get(k)]
        manifest.append({'family': p['pack'], 'drawing': p['drawing'], 'product': p['title'], 'confidence': confidence,
                         'run': (run or {}).get('run_id'), 'unit_gbp': unit, 'adjustment_gbp': adjustment,
                         'revised_unit_gbp': revised, 'workbook': book_rel, 'reports': '; '.join(reports_rel),
                         'client_quote': '; '.join(quotes_rel), 'portal': '; '.join(u for _, u in portal)})
        links += ([book_rel] if book_rel else []) + reports_rel + quotes_rel
        index_rows.append((p, confidence, revised, book_rel, reports_rel, quotes_rel, portal))
    end = table(ps, 4, heads, rows, [30, 10, 44, 14, 12, 12, 14, 14, 22, 60, 10, 14, 24, 14, 38, 14])
    for r in range(5, end):
        conf = str(ps.cell(r, 9).value or '')
        fill = BAD if conf.startswith('PROVISIONAL') else WARN if conf.startswith('ALLOWANCE') else None
        if fill:
            for c in range(1, 17):
                ps.cell(r, c).fill = fill
        if ps.cell(r, 15).value:
            ps.cell(r, 15).hyperlink = next((m['workbook'] for m in manifest if m['drawing'] == ps.cell(r, 2).value), None)
        if ps.cell(r, 16).value:
            ps.cell(r, 16).hyperlink = "#'%s'!A1" % ps.cell(r, 16).value
    ps.freeze_panes = 'D5'

    # Wall of Chocolate sheet
    ww = wb.create_sheet('Wall of Chocolate', 1)
    ww['A1'] = 'Wall of Chocolate: the two layouts (%s). ALTERNATIVES: never add together.' % stamp
    ww['A1'].font = Font(bold=True, size=13)
    r = 3
    r = table(ww, r, ['Layout', 'Product', 'Unit cost GBP', 'Material GBP', 'Labour GBP',
                      'Items to confirm', 'Market-priced GBP', 'Unpriced lines'],
              [[d, w['title'], w['unit'], w['material'], w['labour'], len(w['confirm']), round(w['market_gbp'], 2),
                ', '.join(w['missing'])] for d, w in walls.items()], [34, 44, 18, 14, 14, 12, 16, 40]) + 1
    ww.cell(row=r, column=1, value='Each layout is 30 boxes: 150 spacers, 60 tops, 120 shelves, 120 ticket surrounds.').alignment = WRAP
    r += 2
    for d, w in walls.items():
        ww.cell(row=r, column=1, value='%s: labour by operation (GBP, quantity 1)' % d).font = H
        r = table(ww, r + 1, ['Operation', 'GBP'], [[k, round(v, 2)] for k, v in sorted(w['labour_by_op'].items(), key=lambda x: -x[1])]) + 1
        ww.cell(row=r, column=1, value='%s: sheet-metal and board parts (per unit)' % d).font = H
        r = table(ww, r + 1, ['Part', 'Qty', 'Blank L mm', 'Blank W mm', 'Gauge mm', 'Material GBP'],
                  [list(s) for s in sorted(w['sheet'], key=lambda s: -(s[5] or 0))]) + 1
        ww.cell(row=r, column=1, value='%s: bought-in and commercial lines (per unit)' % d).font = H
        r = table(ww, r + 1, ['Line', 'Source', 'Unit GBP', 'Qty', 'Value GBP'],
                  [list(b) for b in sorted(w['bought'], key=lambda b: -(b[4] or 0))]) + 1
        ww.cell(row=r, column=1, value='%s: review items with the most at stake' % d).font = H
        r = table(ww, r + 1, ['Kind', 'Decision', 'Part', 'GBP at stake', 'Action'],
                  [[c['kind'], c['decision'], c['part'], c['stake'], c['action']] for c in w['top']]) + 2
    for i, wdt in enumerate([34, 60, 18, 14, 14, 12, 16, 40], 1):
        ww.column_dimensions[get_column_letter(i)].width = wdt

    rv = wb.create_sheet('Review items', 2)
    rv['A1'] = 'Open decisions across the job, most money first (from each workbook\'s AI Explanation tab; GBP 50 and over)'
    rv['A1'].font = Font(bold=True, size=12)
    table(rv, 3, ['GBP at stake', 'Drawing', 'Kind', 'Decision', 'Part', 'Action'],
          [[s, d, k, dec, part, act] for s, d, k, dec, part, act in sorted(review_items, key=lambda x: -x[0])[:400]],
          [14, 10, 22, 80, 16, 60])
    rv.freeze_panes = 'A4'
    at = 3
    for name, new in (('Adjustment lines', 'Adjustments'), ('Gaps and confirmations', 'Gaps and confirmations'), ('Basis statement', 'Basis statement')):
        if name in sched_wb.sheetnames:
            copy_sheet(sched_wb[name], wb.create_sheet(new, at))
            at += 1
    pack_name = 'Hotel Chocolat estimating pack %s.xlsx' % datetime.date.today().isoformat()
    wb.save(a.out / pack_name)

    note = handover_note(a.out / 'Handover note.docx', stamp, rel_build, products, walls, adjustments, missing_books)
    with (a.out / 'manifest.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0]))
        w.writeheader()
        w.writerows(manifest)
    e = html.escape
    trs = []
    for p, confidence, revised, book_rel, reps, quotes, portal in index_rows:
        link = lambda rel: '<a href="%s">%s</a>' % (e(rel.replace(os.sep, '/')), e(os.path.basename(rel)))
        trs.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td style="text-align:right">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            e(p['pack']), e(p['drawing']), e(p['title']), e(confidence), '' if revised is None else '{:,.2f}'.format(revised),
            link(book_rel) if book_rel else 'NOT FOUND', '<br>'.join(link(x) for x in reps),
            '<br>'.join(link(x) for x in quotes) or ('withheld' if key(p['drawing']) in adjustments and key(p['drawing']) not in rerun else ''),
            ' | '.join('<a href="%s">%s</a>' % (e(u), n) for n, u in portal)))
    (a.out / 'index.html').write_text(
        '<!doctype html><html><head><meta charset="utf-8"><title>Hotel Chocolat estimating handover</title><style>body{font:13px Segoe UI,Arial;'
        'margin:16px}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:4px 6px;vertical-align:top}th{background:#dde7f0}'
        '</style></head><body><h2>Hotel Chocolat: estimating handover (%s)</h2><p>Start with <a href="%s">%s</a>%s. Provisional costs for '
        'estimating review, not a customer quotation.</p><table><tr><th>Family</th><th>Drawing</th><th>Product</th><th>Confidence</th>'
        '<th>Revised unit cost GBP</th><th>Workbook</th><th>Reports</th><th>Client quote</th><th>Portal</th></tr>%s</table></body></html>'
        % (e(stamp), e(pack_name), e(pack_name), ' and <a href="Handover%20note.docx">Handover note.docx</a>' if note else '', ''.join(trs)),
        encoding='utf-8')
    broken = [x for x in links if not (a.out / x).exists()]
    print('Built %s: %d products, %d with workbooks, %d links checked, %d broken.'
          % (a.out, len(manifest), len(manifest) - len(missing_books), len(links), len(broken)))
    for x in broken:
        print('  BROKEN LINK: %s' % x)
    if missing_books:
        print('  NO WORKBOOK FOUND for: %s' % ', '.join(missing_books))
    if not note:
        print('  Handover note not written: python-docx is not installed in this interpreter.')
    return 0 if not broken and not missing_books else 3


if __name__ == '__main__':
    raise SystemExit(main())
