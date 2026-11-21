"""Offline replays of saved production evidence, not specially shaped example BOMs.

Fixtures retain source hashes and describe the 12133 raw-extract limitation.
No CAD process, pricing, service submission, tracker or share writes occur.
"""
import copy
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.environ.get('TTI_REPLAY_SOURCE', str(Path(__file__).resolve().parents[1] / 'src')))
import route_compiler as rc
import source_connectors.solidworks as sw
import pack_resolver as pr
from bom_tree import drawn_counts_by_code

# THE FIXTURES ARE REAL JOB RECORDS AND ARE NOT KEPT IN GIT (standing rule: a customer's
# drawings and records never go into the repository). They live beside a checkout that has
# them (the laptop's, or wherever SDI_TTI_AUDIT_FIXTURES points); elsewhere this file skips
# and says why, so a skip here is not a pass.
FIXTURES = Path(os.environ.get('SDI_TTI_AUDIT_FIXTURES')
                or Path(__file__).parent / 'fixtures' / 'tti_quantity_pack_audit')
if not all((FIXTURES / (n + '.json')).is_file() for n in ('12110-01-GA1', '12133-00-GA', 'ga17')):
    pytest.skip(f'the actual-record fixtures are not here ({FIXTURES}); they are customer records '
                f'kept out of git. Set SDI_TTI_AUDIT_FIXTURES to run these replays.',
                allow_module_level=True)


def fixture(name):
    return json.loads((FIXTURES / (name + '.json')).read_text(encoding='utf-8'))


def replay(name, saved=False):
    f = fixture(name)
    parts = copy.deepcopy(f['parts'])
    if saved:
        s = f['saved_native']
        job = sw.NativeJob(found=True, bom=[sw.NativeBomRow(**r) for r in s['bom']],
                           hierarchy=copy.deepcopy(s['hierarchy']),
                           assembly_pns=sorted(set(s['hierarchy']) | {r['part_number'] for r in s['bom'] if r['is_assembly']}),
                           meta={'top_assembly': s['top_assembly']})
    else:
        job = sw.normalize_native_extract(f['native_records'], job_codes={p['part_number'] for p in parts if p.get('part_number')})
    for part in parts:
        # Remove only previously derived model results to replay the observation.
        if str(part.get('quantity_source', '')).startswith('solidworks'):
            part.pop('quantity_source', None)
            part.pop('quantity_confidence', None)
        for key in ('quantity_total_per_unit', 'quantity_total_per_unit_source',
                    'quantity_total_per_unit_product', 'quantity_by_parent', 'quantity_by_parent_source'):
            part.pop(key, None)
    sw.apply_native_to_pre_estimate(parts, job, drawn_counts=drawn_counts_by_code(f['bom_rows']))
    sw.apply_native_hierarchy_to_parts(parts, job)
    graph = rc.build_part_graph(parts, f['extract'], f['bom_rows'], f['known_assemblies'],
                               f['page_owner'], pack_mode=f['pack_mode'],
                               declared_product=f['declared_product'], source_names=f['source_names'])
    return job, graph


def test_actual_12110_seven_frames_and_four_glazing_panels():
    job, graph = replay('12110-01-GA1')
    q = graph['quantities']
    assert q['12110-02-201'] == 7
    assert q['12110-03-01A'] == 4
    assert q['12110-02-02M'] == 7
    assert q['12110-02-03M'] == 14
    assert q['12110-02-05M'] == 42
    assert dict(job.hierarchy['12110-02-201'])['12110-02-02M'] == 1
    assert next(r.quantity for r in job.bom if r.part_number == '12110-02-GA') == 7
    assert len([r for r in job.bom if r.part_number == '12110-02-GA']) == 1
    assert job.meta['bom_configuration_totals']['12110-02-GA'] == {'Acoustic': 3, 'Glazing': 4}


@pytest.mark.parametrize('saved', [False, True], ids=['recorded-original-model-observations', 'unchanged-legacy-normalized-record'])
def test_actual_12133_six_of_each_hat_holder_part(saved):
    job, graph = replay('12133-00-GA', saved=saved)
    for code in ('12133-05-01M', '12133-05-02M', '12133-05-03M', '12133-05-04M'):
        assert graph['quantities'][code] == 6
    if not saved:
        assert graph['quantities']['12133-05-GA'] == 6
        assert graph['quantities']['12133-05-101'] == 6
        assert next(r.quantity for r in job.bom if r.part_number == '12133-05-101') == 6


def make_pack(tmp_path, texts, drawing='50005-01-GA3', extra=()):
    root = tmp_path / 'TTI' / '50005 - Stands' / '50005-Technical'
    root.mkdir(parents=True)
    rows = []
    for code, text in texts.items():
        p = root / (code + '.pdf')
        p.write_text(text, encoding='utf-8')
        rows.append((p, p.stat().st_size, p.stat().st_mtime))
    for name in extra:
        p = root / name
        p.write_bytes(b'model fixture')
        rows.append((p, p.stat().st_size, p.stat().st_mtime))
    return pr.resolve(drawing, [(root, rows, False)], read_text=lambda p: p.read_text(encoding='utf-8'), area_rank=lambda p: 0)


def test_numeric_subassembly_children_retained_and_sibling_missing_removed(tmp_path):
    m = make_pack(tmp_path, {
        '50005-01-GA3': '50005-01-GA3 A\nITEM DWG NO QTY\n1 50005-01-101 FRAME 1',
        '50005-01-101': '50005-01-101 A\nITEM DWG NO QTY\n1 50005-01-03M PANEL 1',
        '50005-01-03M': '50005-01-03M A',
        '50005-01-GA1': '50005-01-GA1 A\nITEM DWG NO QTY\n1 50005-01-99M OTHER PRODUCT 1',
    })
    assert '50005-01-03M' in {x['drawing'] for x in m['members']}
    assert '50005-01-GA1' not in {x['drawing'] for x in m['members']}
    assert '50005-01-99M' not in m['missing']
    assert m['missing'] == []


def test_unread_model_assembly_is_not_declared_complete(tmp_path):
    m = make_pack(tmp_path, {'50005-01-GA3': '50005-01-GA3 A\n50005-01-101'},
                  extra=['50005-01-101.sldasm'])
    assert '50005-01-101' in m['unread_assemblies']
    assert not m['complete']


@pytest.mark.parametrize('model_root,printed,expected', [
    ('50005-00-GA', 4, 4), ('50005-00-GA2', 4, 7),
    ('', 4, 7), ('50005-00-GA', 5, 7)])
def test_product_total_needs_matching_model_scope_and_printed_count(model_root, printed, expected):
    root, sub, part = '50005-00-GA', '50005-02-GA', '50005-03-01A'
    parts = [{'part_number': root, 'is_assembly_parent': True},
             {'part_number': sub, 'is_assembly_parent': True},
             {'part_number': part, 'quantity': 1, 'quantity_total_per_unit': 4,
              'quantity_total_per_unit_product': model_root,
              'quantity_total_per_unit_source': 'solidworks_api'}]
    extract = {'assemblies': [{'part_number': root, 'children': [{'part_number': sub, 'qty': 7}]},
                             {'part_number': sub, 'children': [{'part_number': part, 'qty': 1}]}]}
    rows = [{'part_number': part, 'quantity': printed, 'bom_parent': root, 'bom_sheet': 'GA.pdf#2'}]
    g = rc.build_part_graph(parts, extract, rows, [root, sub], declared_product=root)
    assert g['quantities'][part] == expected


def test_product_total_does_not_override_an_estimators_confirmed_quantity():
    root, sub, part = '50005-00-GA', '50005-02-GA', '50005-03-01A'
    parts = [{'part_number': root, 'is_assembly_parent': True},
             {'part_number': sub, 'is_assembly_parent': True},
             {'part_number': part, 'quantity': 2, 'quantity_source': 'estimator_confirmed',
              'quantity_total_per_unit': 4, 'quantity_total_per_unit_product': root}]
    extract = {'assemblies': [{'part_number': root, 'children': [{'part_number': sub, 'qty': 7}]},
                             {'part_number': sub, 'children': [{'part_number': part, 'qty': 1}]}]}
    rows = [{'part_number': part, 'quantity': 4, 'bom_parent': root, 'bom_sheet': 'GA.pdf#2'}]
    g = rc.build_part_graph(parts, extract, rows, [root, sub], declared_product=root)
    assert g['quantities'][part] == 14


def test_archived_numeric_assembly_pdf_is_followed_before_pruning(tmp_path):
    root = tmp_path / 'TTI' / '50005 - Stands' / '50005-Technical'
    archive = root / 'Archive'
    archive.mkdir(parents=True)
    names = {
        root / '50005-01-GA3.pdf': '50005-01-GA3 A\n50005-01-101',
        root / '50005-01-GA1.pdf': '50005-01-GA1 A\n50005-01-88M',
        root / '50005-01-101.sldasm': 'model',
        root / '50005-01-03M.pdf': '50005-01-03M A',
        archive / '50005-01-101_revA.pdf': '50005-01-101 A\n50005-01-03M',
    }
    for p, text in names.items():
        p.write_text(text)
    folders = [(f, [(p, p.stat().st_size, p.stat().st_mtime) for p in names if p.parent == f], f == archive)
               for f in [root, archive]]
    m = pr.resolve('50005-01-GA3', folders, read_text=lambda p: names[p], area_rank=lambda p: 0)
    assert '50005-01-03M' in {x['drawing'] for x in m['members']}
    assert '50005-01-101' not in m['unread_assemblies']


def test_numbered_sheets_and_their_children_survive_pruning(tmp_path):
    m = make_pack(tmp_path, {
        '50005-01-GA3': '50005-01-GA3 A\n50005-02-GA',
        '50005-01-GA1': '50005-01-GA1 A',
        '50005-02-GA-01': '50005-02-GA A\nSHEET 1 OF 2\n50005-02-01M',
        '50005-02-01M': '50005-02-01M A',
    }, extra=['50005-02-GA.sldasm'])
    ids = {x['drawing'] for x in m['members']}
    assert {'50005-02-GA-01', '50005-02-01M'} <= ids


def test_actual_ga17_retains_available_dependencies_and_names_absent_library_drawings(tmp_path, monkeypatch):
    f = fixture('ga17')
    root = tmp_path / 'TTI' / '11671 - Audit'
    root.mkdir(parents=True)
    rows = [(root / x['name'], x['size'], x['mtime']) for x in f['files']]
    monkeypatch.setattr(pr, 'fingerprint', lambda *args, **kwargs: 'fixture-no-binary')
    def read(p):
        evidence = f.get('production_pdf_evidence', {}).get(p.name)
        if evidence and hasattr(pr, 'DrawingText'):
            return pr.DrawingText(evidence['text'], evidence['page_drawings'])
        return f['pdf_text'].get(p.name, '')
    m = pr.resolve('11671-01-GA17', [(root, rows, False)], client='TTI',
                   read_text=read, area_rank=lambda p: 0)
    ids = {x['drawing'] for x in m['members']}
    required = {'11671-01-GA17', '11671-02-GA', '11671-06-02M', '11671-14-01M',
                '11671-15-GA', '11671-17-GA', '11671-27-GA', '11671-28-01M',
                '11671-29-GA', '11671-53-GA'}
    required |= {'11671-53-101', '11671-53-102', '11671-53-01M', '11671-53-02M',
                 '11671-53-03M', '11671-53-04M', '11671-02-201', '11671-27-101'}
    assert required <= ids
    assert {'1264-GA', '1338-GA', '3512-GA-A', '9976-01'} <= set(m['missing'])
    assert not m['complete']
    assert not m['price_ok'], 'pruning is not proved safe while required library drawings are unresolved'
    assert '11671-01-GA16' not in ids and '11671-01-GA18' not in ids
    assert '11671-52-01M' not in m['missing']  # another product, not GA17
    assert len(m['members']) == 45
    assert sum(len(x['files']) for x in m['members']) == 108
    assert not m['unread_assemblies']
    assert m['embedded_drawing_pages']['11671-53-101'] == '11671-53-GA'
    assert m['pdfs_read'] <= 12


def test_pdf_reader_follows_beyond_page_six(monkeypatch):
    import types
    class Page:
        def __init__(self, n): self.n = n
        def extract_text(self): return f'50005-02-{self.n:02d}M'
    class PDF:
        pages = [Page(n) for n in range(1, 9)]
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setitem(sys.modules, 'pdfplumber', types.SimpleNamespace(open=lambda p: PDF()))
    monkeypatch.setitem(sys.modules, 'drawing_facts', types.SimpleNamespace(
        _title_block_part=lambda page, text, box_only=False: text))
    text = pr.read_pdf_text(Path('not-a-real-file.pdf'))
    assert '50005-02-08M' in text
    assert '50005-02-08M' in text.page_drawings
