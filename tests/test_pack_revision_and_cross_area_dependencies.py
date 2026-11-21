"""Offline pack-selection regressions. Synthetic IDs; no share, service or CAD calls."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pack_resolver as pr

GA = '50042-01-GA'
PART = '50042-01-01M'
SUB = '50042-02-GA'


def folder(tmp, area, files, archive=False, job='50042'):
    root = tmp / area / 'TTI' / (job + ' - Display') / 'Technical'
    if archive:
        root /= 'Archive'
    root.mkdir(parents=True, exist_ok=True)
    out = []
    for name, text in files.items():
        path = root / name
        path.write_text(text, encoding='utf-8')
        out.append((path, path.stat().st_size, 1_000_000))
    return root, out, archive


def resolve(rows, **kw):
    return pr.resolve(GA, rows, client='TTI',
                      read_text=lambda p: p.read_text(encoding='utf-8'),
                      area_rank=lambda p: 1 if 'Prototype' in p.parts else 0, **kw)


def live_lookup():
    class Lookup:
        evidence = []
        def __call__(self, code):
            pytest.fail('own-job files must not cause a library search: ' + code)
        def sheet_files(self, code):
            return []
    return Lookup()


@pytest.mark.parametrize('archive', [False, True])
def test_newer_prototype_issue_is_not_ignored_even_when_design_pdf_is_archived(tmp_path, archive):
    rows = [folder(tmp_path, 'Design', {GA + '.sldasm': 'model'})]
    rows += [folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B'}, archive)]
    rows += [folder(tmp_path, 'Prototype', {GA + '_revC.pdf': GA + ' C'})]
    m = resolve(rows)
    assert not m['price_ok']
    assert m['status'] == 'ambiguous'
    assert any('revision C' in c and 'revision B' in c for c in m['conflicts'])
    assert m['revision_conflicts'][0]['alternative_revision'] == 'C'


@pytest.mark.parametrize('revision', ['A', 'B'])
def test_older_or_equal_prototype_issue_keeps_design_preference(tmp_path, revision):
    rows = [folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B'}),
            folder(tmp_path, 'Prototype', {GA + '_rev' + revision + '.pdf': GA + ' ' + revision})]
    m = resolve(rows)
    assert m['price_ok'] and 'Design' in m['selected_folder']


def test_incomparable_later_area_revision_is_a_decision_not_a_date_tiebreak(tmp_path):
    m = resolve([folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B'}),
                 folder(tmp_path, 'Prototype', {GA + '_rev2.pdf': GA + ' 2'})])
    assert not m['price_ok']
    assert 'not comparable' in ' '.join(m['conflicts'])


def test_another_jobs_copy_does_not_override_own_job_revision(tmp_path):
    m = resolve([folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B'}),
                 folder(tmp_path, 'Prototype', {GA + '_revZ.pdf': GA + ' Z'}, job='50099')])
    assert m['price_ok']


def test_own_part_in_prototype_is_found_without_library_or_sibling_product(tmp_path):
    rows = [folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B\n' + PART}),
            folder(tmp_path, 'Prototype', {PART + '_revB.pdf': PART + ' B',
                                           '50042-01-GA2.pdf': '50042-01-GA2 A'})]
    m = resolve(rows, lookup=live_lookup())
    assert PART not in m['missing']
    assert PART in {x['drawing'] for x in m['members']}
    assert '50042-01-GA2' not in {x['drawing'] for x in m['members']}
    assert any(x['drawing'] == PART for x in m['cross_area_recovery'])


def test_cross_area_subassembly_pdf_is_followed_recursively(tmp_path):
    rows = [folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B\n' + SUB,
                                      SUB + '.sldasm': 'model'}),
            folder(tmp_path, 'Prototype', {SUB + '_revB.pdf': SUB + ' B\n' + PART,
                                           PART + '_revB.pdf': PART + ' B'})]
    m = resolve(rows, lookup=live_lookup())
    assert m['missing'] == []
    assert PART in m['dependency_references'][SUB]
    assert SUB not in m['unread_assemblies']


def test_newer_prototype_part_is_not_ignored_when_design_part_pdf_exists(tmp_path):
    rows = [folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B\n' + PART,
                                      PART + '_revB.pdf': PART + ' B'}),
            folder(tmp_path, 'Prototype', {PART + '_revC.pdf': PART + ' C'})]
    m = resolve(rows)
    assert not m['price_ok']
    assert any(c['drawing'] == PART and c['alternative_revision'] == 'C'
               for c in m['revision_conflicts'])


@pytest.mark.parametrize('revision', ['A', 'B', 'C'])
def test_missing_pdf_does_not_silently_mix_named_model_and_drawing_issues(tmp_path, revision):
    rows = [folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B\n' + PART,
                                      PART + '_revB.sldprt': 'model'}),
            folder(tmp_path, 'Prototype', {PART + '_rev' + revision + '.pdf': PART + ' ' + revision})]
    m = resolve(rows)
    assert m['price_ok'] is (revision == 'B')
    if revision == 'B':
        assert any(x['drawing'] == PART for x in m['cross_area_recovery'])
    else:
        assert any(PART in c for c in m['conflicts'])


def test_cross_area_numbered_sheets_are_followed(tmp_path):
    rows = [folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B\n' + SUB}),
            folder(tmp_path, 'Prototype', {SUB + '-01_revB.pdf': SUB + ' B\nSHEET 1 OF 1\n' + PART,
                                           PART + '_revB.pdf': PART + ' B'})]
    m = resolve(rows, lookup=live_lookup())
    assert PART in {x['drawing'] for x in m['members']}
    assert SUB + '-01' in {x['drawing'] for x in m['members']}


def test_own_job_recovery_does_not_take_another_jobs_part_copy(tmp_path):
    rows = [folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B\n' + PART}),
            folder(tmp_path, 'Prototype', {PART + '_revB.pdf': PART + ' B'}, job='50099')]
    m = resolve(rows, lookup=live_lookup())
    assert PART in m['missing']


def test_pruned_product_with_unresolved_library_cannot_claim_safe_pricing(tmp_path):
    rows = [folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B\n50088-01-GA',
                                      '50042-01-GA2.pdf': '50042-01-GA2 A\n50042-01-99M',
                                      '50042-01-99M.pdf': '50042-01-99M A'})]
    m = resolve(rows)
    assert m['left_out_other_products']
    assert '50088-01-GA' in m['missing']
    assert not m['price_ok']
    assert 'unresolved' in m['question'].lower()


def test_unpruned_missing_part_keeps_existing_labelled_allowance_policy(tmp_path):
    m = resolve([folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B\n' + PART})])
    assert m['missing'] == [PART] and m['price_ok']


@pytest.mark.parametrize('name', [PART + ' - HANDED.SLDPRT', PART + '_HANDED_revB.pdf',
                                PART + '-HANDED_revB.pdf', PART + ' HANDED.dxf'])
def test_handed_filename_keeps_its_distinct_identity(name):
    assert pr.drawing_id(name) == PART + '-HANDED'


def test_present_handed_model_is_not_reported_missing_or_merged_into_base(tmp_path):
    rows = [folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B\n' + PART + '\n' + PART + '-HANDED',
                                      PART + '.sldprt': 'base', PART + ' - HANDED.sldprt': 'hand'})]
    m = resolve(rows)
    members = {x['drawing']: x for x in m['members']}
    assert PART + '-HANDED' not in m['missing']
    assert len(members[PART]['files']) == len(members[PART + '-HANDED']['files']) == 1


def test_archived_pdf_is_recorded_and_never_makes_a_verified_current_pack(tmp_path):
    rows = [folder(tmp_path, 'Design', {GA + '.sldasm': 'model'}),
            folder(tmp_path, 'Design', {GA + '_revB.pdf': GA + ' B'}, archive=True)]
    m = resolve(rows)
    assert m['ga_pdf_source']['archive'] is True
    assert m['status'] == 'provisional'
    assert m['price_ok']  # No competing issue: retain existing labelled archive policy.
