"""The estimating handover is one consolidated, fully costed workbook with its files by family.

The Wall reruns must come from the verified release build; older results go to _Superseded.
Provisionally adjusted products show original, adjustment and revised, and their client quote
pages (old prices) are withheld. Every link is checked. Synthetic data only.
"""
import http.server
import importlib.util
import json
import threading
import time
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('hc_estimating_pack', ROOT / 'tools' / 'estimating' / 'hc_estimating_pack.py')
hh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hh)


def _book(path: Path, drawing: str, unit: float):
    wb = openpyxl.Workbook()
    est = wb.active
    est.title = 'Estimate'
    est['C5'], est['D5'] = 'Drawing No.', drawing
    est['H6'] = 'DRAFT - 1 item to confirm'
    est['C20'], est['H20'] = 'MDF 18mm sheet', 12.5
    est['C20'].font = openpyxl.styles.Font(bold=True)
    est['C225'], est['M225'] = 'Total Unit Cost Price', unit
    est['C147'], est['M147'] = 'Total Material Cost', round(unit * 0.5, 2)
    est['C223'], est['M223'] = 'Total Labour Cost (Including  Downtime)', round(unit * 0.45, 2)
    est['C60'], est['D60'], est['E60'], est['F60'], est['G60'], est['M60'] = 'C-33497  WOC BOX BASE SPACER', 150, 359.3, 234.6, 1.5, 215.28
    est['C154'], est['M154'] = 'Laser (Metal)', 73.48
    est.merge_cells('C2:F2')
    ai = wb.create_sheet('AI Explanation')
    ai.append(['FOR THE ESTIMATOR TO CONFIRM'])
    ai.append(['#', 'Kind', 'Decision', 'Part', 'Current assumption', 'Action', '\u00a3 at stake'])
    ai.append([1, 'Market figure', 'EDGE rests on a market price', 'EDGE', 'web', 'replace', '\u00a3666.43'])
    ai.append([2, 'Quantity check', 'C-33490: BOM states 1, sheet costs 150', 'C-33490', '150', 'rule', '\u00a31,862.50'])
    wb.save(path)


class _Services:
    def __init__(self, runs):
        svc = self
        self.runs = runs

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({'runs': svc.runs}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(body)

        self.servers = [http.server.ThreadingHTTPServer(('127.0.0.1', 0), H) for _ in range(2)]
        for s in self.servers:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        self.urls = tuple('http://127.0.0.1:%d' % s.server_address[1] for s in self.servers)

    def close(self):
        for s in self.servers:
            s.shutdown()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    src = tmp_path / 'runs'
    src.mkdir()
    verified = time.time() - 3600
    products = [('6 Wall of Chocolate layouts', 'A.33446', 'WALL MIDFLOOR', 'f1'),
                ('8 Plinths and column planter', 'B.34487', '750MM HIGH PLINTH', 'f2'),
                ('1 Perimeter panels and infills', 'A.33324', 'PANEL 1000', 'f3')]
    plan = {'products': [{'pack': pk, 'drawing': d, 'title': t, 'fingerprint': fp * 6, 'files': [], 'brief': ''}
                         for pk, d, t, fp in products]}
    runs = []

    def run(rid, drawing, fp, unit, queued, build):
        d = src / rid
        d.mkdir()
        book = d / ('%s_20261127_120000.xlsx' % drawing)
        _book(book, drawing, unit)
        (d / ('%s_report.html' % drawing)).write_text('<p>report</p>')
        (d / ('%s_quote.html' % drawing)).write_text('<p>quote %s</p>' % unit)
        runs.append({'run_id': rid, 'status': 'done', 'queued_at': queued, 'client': 'Hotel Chocolat',
                     'job_title': 'T [hc:%s]' % (fp * 6), 'drawing_number': drawing,
                     'log': ['   [build] engine source: %s · src x' % build],
                     'deliverables': [{'path': str(book)}, {'path': str(d / ('%s_report.html' % drawing))},
                                      {'path': str(d / ('%s_quote.html' % drawing))}],
                     'walkthrough_url': 'https://portal/estimating/walkthrough/%s' % rid})

    run('wall-old', 'A.33446', 'f1', 137675.71, verified - 7200, '8e03a71')
    run('wall-new', 'A.33446', 'f1', 21000.00, verified + 60, 'c4ad620')
    run('plinth', 'B.34487', 'f2', 730.94, verified - 9000, '8e03a71')
    run('panel', 'A.33324', 'f3', 410.00, verified - 9000, 'bbd48e0')
    sched = openpyxl.Workbook()
    ws = sched.active
    ws.title = 'Schedule'
    ws.append(['title'])
    ws.append([])
    ws.append([])
    ws.append(['Product', 'Description', 'Original unit price (GBP)', 'Adjustment (GBP)', 'Revised unit price (GBP)', 'Basis / notes'])
    ws.append(['B.34487', '750MM HIGH PLINTH', 730.94, -300.57, 430.37, 'Ballast as plates, panels restored'])
    ws.append(['A.33446', 'WALL', 137675.71, None, None, None])
    sched.create_sheet('Adjustment lines').append(['Product', 'Line', 'Change'])
    sched.create_sheet('Gaps and confirmations').append(['Item'])
    sched.create_sheet('Basis statement').append(['BASIS'])
    (tmp_path / 'schedule.xlsx').parent.mkdir(exist_ok=True)
    sched.save(tmp_path / 'schedule.xlsx')
    (tmp_path / 'plan.json').write_text(json.dumps(plan))
    (tmp_path / 'release.json').write_text(json.dumps({'build': 'c4ad6203', 'loaded_verified_at': verified}))
    svc = _Services(runs)
    monkeypatch.setattr(hh, 'SERVICES', svc.urls)
    args = ['--plan', str(tmp_path / 'plan.json'), '--release', str(tmp_path / 'release.json'),
            '--schedule', str(tmp_path / 'schedule.xlsx'), '--rerun', 'A.33446']
    yield tmp_path, args, svc
    svc.close()


def _has_docx():
    try:
        import docx  # noqa: F401
        return True
    except ImportError:
        return False


def test_one_consolidated_workbook_with_detail_tabs_family_folders_and_checked_links(setup):
    tmp, args, _ = setup
    out = tmp / 'handover'
    assert hh.main(args + ['--out', str(out)]) == 0
    pack = next(out.glob('Hotel Chocolat estimating pack *.xlsx'))
    wb = openpyxl.load_workbook(pack)
    rows = {r[1]: r for r in wb['Price schedule'].iter_rows(min_row=5, values_only=True) if r[1]}
    assert rows['A.33446'][3] == 21000.00 and rows['A.33446'][13] == 'wall-new'          # verified rerun
    assert rows['A.33446'][8] == 'DRAWING' and 'c4ad620' in rows['A.33446'][9]
    assert (rows['B.34487'][3], rows['B.34487'][6], rows['B.34487'][7]) == (730.94, -300.57, 430.37)
    assert rows['B.34487'][8].startswith('PROVISIONAL') and rows['A.33324'][7] == 410.00 and rows['A.33324'][8] == 'DRAWING'
    assert rows['A.33446'][10] == 2 and rows['A.33446'][11] == 666.43
    assert {'Wall of Chocolate', 'Review items', '6 A.33446', '8 B.34487', '1 A.33324', 'Adjustments', 'Gaps and confirmations'} <= set(wb.sheetnames)
    woc = [r for r in wb['Wall of Chocolate'].iter_rows(values_only=True) if r[0]]
    assert any(r[0] == 'A.33446' and r[2] == 21000.00 for r in woc)
    assert any(r[0] == 'C-33497  WOC BOX BASE SPACER' and r[1] == 150 for r in woc)
    review = [r for r in wb['Review items'].iter_rows(min_row=4, values_only=True) if r[0]]
    assert review[0][0] == 1862.5 and 'C-33490' in review[0][3] and {r[1] for r in review} == {'A.33446', 'B.34487', 'A.33324'}
    assert wb['6 A.33446']['M225'].value == 21000.00 and wb['6 A.33446']['C20'].font.bold
    assert (out / '6 Wall of Chocolate layouts' / 'A.33446' / 'A.33446_20261127_120000.xlsx').exists()
    assert (out / '_Superseded' / 'A.33446' / 'wall-old' / 'A.33446_20261127_120000.xlsx').exists()
    assert (out / '_Withheld client quotes' / 'B.34487' / 'B.34487_quote.html').exists()
    assert not (out / '8 Plinths and column planter' / 'B.34487' / 'B.34487_quote.html').exists()
    assert (out / '1 Perimeter panels and infills' / 'A.33324' / 'A.33324_quote.html').exists()
    index = (out / 'index.html').read_text()
    assert 'withheld' in index and 'walkthrough/wall-new' in index and 'walkthrough/wall-old' not in index
    assert (out / 'schedule.xlsx').exists() and (out / 'manifest.csv').exists()
    assert (out / 'Handover note.docx').exists() or not _has_docx()


def test_a_wall_without_a_run_on_the_verified_build_builds_nothing(setup):
    tmp, args, svc = setup
    svc.runs[:] = [r for r in svc.runs if r['run_id'] != 'wall-new']
    with pytest.raises(SystemExit, match='no finished run since the verified release'):
        hh.main(args + ['--out', str(tmp / 'h2')])
    assert not (tmp / 'h2').exists()


def test_an_unreachable_service_builds_nothing(setup, monkeypatch):
    tmp, args, svc = setup
    monkeypatch.setattr(hh, 'SERVICES', (svc.urls[0], 'http://127.0.0.1:9'))
    with pytest.raises(SystemExit, match='run history is incomplete'):
        hh.main(args + ['--out', str(tmp / 'h3')])
    assert not (tmp / 'h3').exists()


def test_an_existing_folder_is_never_written_into(setup):
    tmp, args, _ = setup
    (tmp / 'h4').mkdir()
    with pytest.raises(SystemExit, match='already exists'):
        hh.main(args + ['--out', str(tmp / 'h4')])


def test_a_schedule_whose_original_disagrees_with_the_run_builds_nothing(setup):
    tmp, args, _ = setup
    wb = openpyxl.load_workbook(tmp / 'schedule.xlsx')
    wb['Schedule']['C5'] = 999.0
    wb.save(tmp / 'schedule.xlsx')
    with pytest.raises(SystemExit, match='does not match its run workbook'):
        hh.main(args + ['--out', str(tmp / 'h5')])
