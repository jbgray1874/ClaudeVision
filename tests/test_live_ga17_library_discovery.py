"""Local filesystem regressions; these do not claim the four files exist on W:."""
import json
import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0, os.environ.get('TTI_REPLAY_SOURCE', str(Path(__file__).resolve().parents[1] / 'src')))
import pack_resolver as pr
from live_library_lookup import LiveLibraryLookup, library_areas


def put(root, name, text='drawing'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_four_ga17_references_outside_job_across_clients_and_loose_library(tmp_path):
    design = tmp_path / 'Design'
    prototype = tmp_path / 'Prototype'
    prototype.mkdir()
    paths = [put(design, 'Other client/1264 Fact tag/1264-GA.pdf'),
             put(design, 'TTi/1338 Hooks/1338-GA.SLDASM'),
             put(design, 'Shared library/Holders/3512-GA-A.pdf'),
             put(prototype, 'TTi/9976 Shelves/9976-01.pdf')]
    lookup = LiveLibraryLookup([('Design', design), ('Prototype', prototype)])
    for did, path in zip(['1264-GA', '1338-GA', '3512-GA-A', '9976-01'], paths):
        assert [f[0] for f in lookup(did)] == [path]
    assert not list(tmp_path.rglob('*index*'))
    assert lookup.evidence[-1]['area'] == 'Prototype'


def test_design_wins_without_mixing_prototype_pdf(tmp_path):
    d, p = tmp_path/'Design', tmp_path/'Prototype'
    model = put(d, '1264 Test/1264-GA.sldasm')
    put(p, '1264 Test/1264-GA.pdf')
    lookup = LiveLibraryLookup([('Design', d), ('Prototype', p)])
    assert [f[0] for f in lookup('1264-GA')] == [model]
    assert len(lookup.evidence) == 1


def test_unreadable_design_holds_instead_of_prototype_fallback(tmp_path):
    p = tmp_path/'Prototype'
    put(p, '1264 Test/1264-GA.pdf')
    lookup = LiveLibraryLookup([('Design', tmp_path/'absent'), ('Prototype', p)])
    with pytest.raises(pr.PackCheckStalled, match='could not be read'):
        lookup('1264-GA')


def test_ai_design_only_and_exact_job_boundary_and_archives(tmp_path, monkeypatch):
    d, p = tmp_path/'Design', tmp_path/'Prototype'
    put(d, '12640 Other/1264-GA.pdf')
    put(d, '1264 Test/Archive/1264-GA.pdf')
    put(p, '1264 Test/1264-GA.pdf')
    monkeypatch.setenv('SDI_PACK_LIBRARY_DESIGN_ROOT', str(d))
    monkeypatch.setenv('SDI_PACK_LIBRARY_PROTOTYPE_ROOT', str(p))
    lookup = LiveLibraryLookup(library_areas(design_only=True))
    assert lookup('1264-GA') == []
    assert all(e['area'] == 'Design' for e in lookup.evidence)
    audit = LiveLibraryLookup([('Design', d)], include_archives=True)
    assert len(audit('1264-GA')) == 1
    assert 'Archive' in str(audit('1264-GA')[0][0])


def test_unrelated_numbered_jobs_are_never_walked(tmp_path, monkeypatch):
    import live_library_lookup as lib
    d = tmp_path/'Design'
    put(d, '99999 Other/1264-GA.pdf')
    real = lib.os.scandir
    def scan(path):
        assert '99999 Other' not in str(path)
        return real(path)
    monkeypatch.setattr(lib.os, 'scandir', scan)
    assert LiveLibraryLookup([('Design', d)])('1264-GA') == []


def test_external_numbered_sheets_and_numeric_descendants_are_retained(tmp_path):
    d = tmp_path/'Design'
    top = put(d, '11671 Job/11671-01-GA17.pdf')
    sheet = put(d, '1264 Library/1264-GA-01.pdf')
    child = put(d, '1264 Library/1264-01-101.pdf')
    part = put(d, '1264 Library/1264-01M.dxf')
    texts = {top.name: '11671-01-GA17 REV A\nITEM PART NUMBER QTY\n1 1264-GA 11',
             sheet.name: '1264-GA REV A\nITEM PART NUMBER QTY\n1 1264-01-101 1',
             child.name: '1264-01-101 REV A\nITEM PART NUMBER QTY\n1 1264-01M 1'}
    lookup = LiveLibraryLookup([('Design', d)])
    m = pr.resolve('11671-01-GA17', [(top.parent, [(top, top.stat().st_size, 1)], False)],
                   read_text=lambda path: texts.get(path.name, ''), lookup=lookup)
    files = {f['path'] for member in m['members'] for f in member['files']}
    assert {str(top), str(sheet), str(child), str(part)} <= files, json.dumps(m, indent=2)
    assert m['live_library_search']
    assert '1264-GA' not in m['missing']


def test_ai_entrypoint_returns_design_only_live_lookup(tmp_path, monkeypatch):
    d, p = tmp_path/'Design', tmp_path/'Prototype'
    d.mkdir(); p.mkdir()
    monkeypatch.setattr(pr, 'area_roots', lambda: [('Design', d), ('Prototype', p)])
    monkeypatch.setattr(pr, 'rows_for_job_now', lambda *args: ([], 'test', set()))
    monkeypatch.setenv('SDI_PACK_LIBRARY_DESIGN_ROOT', str(d))
    monkeypatch.setenv('SDI_PACK_LIBRARY_PROTOTYPE_ROOT', str(p))
    _, _, lookup = pr.folders_now('11671-01-GA17', design_only=True)
    assert lookup.areas == [('Design', d)]


def test_tti_direct_entrypoint_supplies_live_callback(tmp_path, monkeypatch):
    import tti_pricer as tp
    monkeypatch.setattr(tp, '_DIRECT', [True])
    monkeypatch.setattr(pr, 'rows_for_job_now', lambda *a: ([(tmp_path, [], False)], 'test', {str(tmp_path)}))
    captured = {}
    def resolve(*a, **kw):
        captured.update(kw)
        return {'status': 'not found'}
    monkeypatch.setattr(pr, 'resolve', resolve)
    tp.pack_for('11671-01-GA17', [], 'TTI')
    assert isinstance(captured['lookup'], LiveLibraryLookup)
    assert [label for label, _ in captured['lookup'].areas] == ['Design', 'Prototype']


def test_one_walk_of_each_area_serves_every_outside_drawing(tmp_path, monkeypatch):
    """20 Nov 2026: GA17's four outside drawings were four full walks of the Design area over the
    VPN. Each area is now walked once; each drawing then lists only its own job's folders."""
    d, p = tmp_path / 'Design', tmp_path / 'Prototype'
    p.mkdir()
    put(d, 'Client A/1264 Tag/1264-GA.pdf')
    put(d, 'Client B/1338 Hook/1338-GA.pdf')
    put(d, 'Shared library/3512-GA-A.pdf')
    lookup = LiveLibraryLookup([('Design', d), ('Prototype', p)])
    walks = []
    real = lookup._containers
    monkeypatch.setattr(lookup, '_containers', lambda root: (walks.append(str(root)), real(root))[1])
    for did in ('1264-GA', '1338-GA', '3512-GA-A'):
        assert lookup(did), did
    assert walks.count(str(d)) == 3 and len(lookup._walked) == 1, \
        "the area's folders were walked again for each drawing"


def test_the_walk_stops_at_the_container_depth(tmp_path):
    """A loose file buried deeper than the container depth is not reached: the search is bounded,
    and a miss there is said, not taken as proof of absence."""
    d, p = tmp_path / 'Design', tmp_path / 'Prototype'
    p.mkdir()
    put(d, 'a/b/c/d/e/1264-GA.pdf')
    lookup = LiveLibraryLookup([('Design', d), ('Prototype', p)])
    assert lookup('1264-GA') == []
