"""Pack-specific assertions live in tests, never in production dispatch rules.

Saved records are a private fixture. These checks prepare evidence only: no real
job is priced, submitted or written back to a workbook.
"""
import copy
import json
import os
from pathlib import Path
import pytest
from drawing_reference import compact
from saved_scope_recovery import prepare
from source_precedence import _same_material
from test_hc_saved_scope_private import saved


def test_real_spacer_is_steel_with_a_flat_and_manufacturing_not_acrylic(saved):
    source = copy.deepcopy(saved['A.33446'])
    result, audit = prepare(saved['A.33446'])
    p = next(p for p in result['parts'] if compact(p['part_number']) == 'C33497')
    # One material in either spelling: the engine's own equivalence, not a string match.
    assert _same_material(p['normalized_material'], 'MILD_STEEL') and p['normalized_thickness_mm'] == 1.5
    assert (p['blank_length_mm'], p['blank_width_mm']) == (359.3, 234.6)
    assert {'laser_cutting', 'deburring', 'folding'} <= set(p.get('inferred_operations', []) + p.get('textual_operations', []))
    quantities = {compact(k): v for k, v in audit['quantities_per_finished_product'].items()}
    assert quantities['C33497'] == 150 and quantities['D33496'] == 60 and quantities['D33498'] == 120
    assert saved['A.33446'] == source and audit['priced'] is False


def test_real_shelf_keeps_one_bill_with_two_brackets_and_owned_gauges(saved):
    result, audit = prepare(saved['B.34471'], scope='B.34473', scope_basis='Reviewed assembly sheet')
    p = {compact(p['part_number']): p for p in result['parts']}
    assert not {'20126611', '20125999', '20126615'} & p.keys()
    assert p['B34471']['normalized_thickness_mm'] == 1.5
    assert p['C33383']['normalized_thickness_mm'] == 2.5
    assert p['D34472']['normalized_thickness_mm'] == 1.5
    assert (p['C33383']['blank_length_mm'], p['C33383']['blank_width_mm']) == (383.3, 125.5)
    for key in ('B34471', 'C33383', 'D34472'):
        assert _same_material(p[key]['normalized_material'], 'MILD_STEEL')
        assert p[key]['blank_length_mm'] and p[key]['blank_width_mm']
        assert 'laser_cutting' in p[key]['inferred_operations'] + p[key].get('textual_operations', [])
    q = {compact(k): v for k, v in audit['quantities_per_finished_product'].items()}
    assert q['C33383'] == 2 and q['B34471'] == 1 and q['D34472'] == 1


@pytest.mark.parametrize('drawing', ['B.34487', 'B.34490', 'B.34493'])
def test_real_panels_are_fire_rated_mdf_with_cnc_not_untyped_free_material(saved, drawing):
    aliases = {'B.34487': {'10100889': 'A.34488'}, 'B.34490': {'10100890': 'A.34491'},
               'B.34493': {'10100892': 'A.34494'}}[drawing]
    result, audit = prepare(saved[drawing], identity_aliases=aliases,
        scope_basis='Reviewed GA assembly stock identity, supplied explicitly; not a production exception')
    p = [p for p in result['parts'] if p.get('component_caption_blank')]
    assert len(p) == 3 and sorted(x['quantity'] for x in p) == [1, 1, 4]
    assert all(x['normalized_material'] == 'MDF' and x['normalized_thickness_mm'] == 18 for x in p)
    assert all('FR B' in x['material_specification'] for x in p)
    assert all('cnc_routing' in x['inferred_operations'] for x in p)
    assert audit['priced'] is False


def test_reviewed_raster_schedule_keeps_all_three_coats_and_consumables(saved):
    path = Path(os.environ.get('HC_OWNED_TEXT_FIXTURE', 'private-fixtures/plinth_owned_text.json'))
    if not path.exists():
        pytest.skip('Private reviewed raster transcription is not installed')
    decision = json.loads(path.read_text(encoding='utf-8'))
    result, audit = prepare(saved['B.34493'], identity_aliases={'10100892': 'A.34494'},
        scope_basis='Reviewed GA stock identity', owned_text=decision)
    parents = [p for p in result['parts'] if p.get('finish_schedule')]
    assert len(parents) == 1
    parent = parents[0]
    assert parent['finish_schedule']['passes'] == 3
    assert parent['_powder_members_coated_m2'] == pytest.approx(2.857922)
    costs = [p for p in result['parts'] if p.get('named_finish_consumable')]
    assert len(costs) == 3 and all(p['named_finish_consumable']['allowance_gbp'] > 0 for p in costs)
    assert all(p['bom_parent'] == parent['part_number'] for p in costs)
    assert audit['priced'] is False and 'final_estimate' not in result
