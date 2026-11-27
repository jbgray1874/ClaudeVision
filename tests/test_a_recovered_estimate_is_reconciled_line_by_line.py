"""A recovered estimate passes only when every line of the run it came from is accounted for.

A positive, error-free workbook total proves nothing about completeness: an offline replay
can leave lines the original priced at zero. Synthetic lines only.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('reconcile_recovery',
                                               ROOT / 'tools' / 'estimating' / 'reconcile_recovery.py')
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)


def line(pn, unit, qty=1.0, kind='leaf'):
    return {'part_number': pn, 'engine_unit_gbp': unit, 'qty_per_unit': qty, 'kind': kind}


BEFORE = [line('C.100', 80.0), line('30000854', 1.25, 42, 'bought_in'), line('B.200', 12.0, 2, 'assembly')]


def test_an_identical_recovery_is_complete():
    out = rr.compare_lines(BEFORE, [dict(l) for l in BEFORE])
    assert out['unexplained'] == 0 and out['unchanged'] == 3


def test_a_bought_in_price_lost_offline_is_never_complete():
    after = [line('C.100', 80.0), line('30000854', 0.0, 42, 'bought_in'), line('B.200', 12.0, 2, 'assembly')]
    out = rr.compare_lines(BEFORE, after)
    assert [r['line'] for r in out['lost_price']] == ['30000854'] and out['unexplained'] == 1


def test_only_the_named_correction_may_change_and_it_is_reported():
    after = [line('C.100', 46.43), line('30000854', 1.25, 42, 'bought_in'), line('B.200', 12.0, 2, 'assembly')]
    assert rr.compare_lines(BEFORE, after)['money_changed'][0]['line'] == 'C.100'
    out = rr.compare_lines(BEFORE, after, changed=['C 100'])
    assert out['unexplained'] == 0 and out['intended'][0]['unit_after_gbp'] == 46.43


def test_missing_lines_quantity_changes_and_unexpected_additions_are_unexplained():
    after = [line('C.100', 80.0), line('B.200', 12.0, 3, 'assembly'), line('X.9', 5.0)]
    out = rr.compare_lines(BEFORE, after)
    assert [r['line'] for r in out['missing']] == ['30000854']
    assert [r['line'] for r in out['quantity_changed']] == ['B.200']
    assert [r['line'] for r in out['added']] == ['X.9'] and out['unexplained'] == 3


def test_rounding_inside_tolerance_is_not_a_difference():
    after = [line('C.100', 80.3), line('30000854', 1.25, 42, 'bought_in'), line('B.200', 12.0, 2, 'assembly')]
    assert rr.compare_lines(BEFORE, after)['unexplained'] == 0


def _part(**kw):
    p = {'part_number': 'C.100', 'normalized_material': 'MDF', 'normalized_thickness_mm': 18.0,
         'blank_length_mm': 1866.0, 'blank_width_mm': 770.0, 'normalized_finish': 'WET SPRAY',
         'inferred_operations': ['cnc_routing', 'wet_spray'], 'owned_thickness_conflict': {'printed_mm': [6]}}
    p.update(kw)
    return {'manufacturing_writeup': {'parts': [p]}}


SPEC = {'part': 'C.100', 'material': 'MDF', 'thickness': 18.0, 'blank': [1866.0, 770.0],
        'ops': ['cnc_routing', 'wet_spray'], 'absent_ops': ['folding'], 'conflict_printed': [6]}


def test_the_corrected_part_is_checked_against_what_the_caller_names():
    assert rr.check_part({}, _part(), SPEC)['problems'] == []
    bad = rr.check_part({}, _part(blank_width_mm=1518.0, inferred_operations=['cnc_routing', 'wet_spray', 'folding'],
                                  owned_thickness_conflict=None), SPEC)['problems']
    assert len(bad) == 3


def test_the_tool_fails_without_a_recalculated_total_and_writes_a_new_report(tmp_path, monkeypatch):
    for name, body in (('orig.json', {'L': BEFORE}), ('prep.json', {}), ('rep.json', dict(_part(), L=BEFORE))):
        (tmp_path / name).write_text(json.dumps(body), encoding='utf-8')
    monkeypatch.setattr(rr, 'lines_of', lambda s: s.get('L') or [])
    args = [str(tmp_path / 'orig.json'), str(tmp_path / 'prep.json'), str(tmp_path / 'rep.json'),
            '--part', 'C.100', '--blank', '1866x770', '--material', 'MDF', '--thickness', '18',
            '--ops', 'cnc_routing,wet_spray', '--absent-ops', 'folding', '--conflict-printed', '6']
    assert rr.main(args + ['--report', str(tmp_path / 'r1.json')]) == 1
    assert rr.main(args + ['--recovered-book-total', '4000', '--report', str(tmp_path / 'r2.json')]) == 0
    assert json.loads((tmp_path / 'r2.json').read_text())['complete'] is True
    with pytest.raises(SystemExit):
        rr.main(args + ['--recovered-book-total', '4000', '--report', str(tmp_path / 'r2.json')])
