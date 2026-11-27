"""Fresh 27-Nov result evidence, prepared OFFLINE WITHOUT PRICING real jobs.

Dimension annotations are read from the actual submitted PDFs by the same
generic reader wired into a fresh scan. No injected stock aliases or prices.
"""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import pytest
from drawing_reference import compact
from saved_scope_recovery import prepare


@pytest.fixture(scope='module')
def fresh():
    path=Path(os.environ.get('HC_FRESH_EVIDENCE','private-fixtures/fresh_evidence.json'))
    if not path.exists():
        pytest.skip('Private fresh-run evidence not installed')
    return json.loads(path.read_text(encoding='utf-8'))


def recover(source):
    with contextlib.redirect_stdout(io.StringIO()):
        return prepare(source)


@pytest.mark.parametrize('drawing',['A.33446','A.34225'])
def test_wall_keeps_box_quantities_but_not_page_vector_laser_paths(fresh,drawing):
    original=copy.deepcopy(fresh[drawing])
    result,audit=recover(fresh[drawing])
    p={compact(p['part_number']):p for p in result['parts']}
    assert (p['C33497']['blank_length_mm'],p['C33497']['blank_width_mm'])==(359.3,234.6)
    for code in ('C33497','D33496','D33498','E33488'):
        part=p[code]
        cut=float((part.get('normalized_geometry') or {}).get('cut_length_mm') or 0)
        assert 0 < cut < 20000, (code,cut)
        assert part.get('_cut_allowance')
        assert 'laser_cutting' in part.get('inferred_operations',[])+part.get('textual_operations',[])
    q={compact(k):v for k,v in audit['quantities_per_finished_product'].items()}
    assert [q[k] for k in ('C33497','D33496','D33498','E33488')]==[150,60,120,120]
    assert fresh[drawing]==original and audit['priced'] is False
    assert 'final_estimate' not in result and 'estimate_summary' not in result


@pytest.mark.parametrize('drawing,height',[('B.34487',750),('B.34490',900),('B.34493',1050)])
def test_raster_assembly_members_survive_without_manual_alias_injection(fresh,drawing,height):
    result,audit=recover(fresh[drawing])
    panels=[p for p in result['parts'] if p.get('component_caption_blank')]
    assert len(panels)==3
    assert sorted(p['quantity'] for p in panels)==[1,1,4]
    assert {(p['blank_length_mm'],p['blank_width_mm']) for p in panels}=={(height,300),(300,300),(281,281)}
    assert all(p['normalized_material']=='MDF' and p['normalized_thickness_mm']==18 for p in panels)
    assert all('cnc_routing' in p.get('inferred_operations',[]) for p in panels)
    assert len(result['assembly_identity_inferences'])==1
    assert result['assembly_identity_inferences'][0]['provisional'] is True
    ballast=next(p for p in result['parts'] if compact(p['part_number'])=='D34496')
    assert (ballast['blank_length_mm'],ballast['blank_width_mm'])==(259,259)
    assert ballast['quantity']==4
    parents=[p for p in result['parts'] if p.get('finish_schedule')]
    assert len(parents)==1 and parents[0]['finish_schedule']['inferred'] is True
    assert parents[0]['finish_schedule']['passes']==3
    assert len([p for p in result['parts'] if p.get('named_finish_consumable')])==3
    assert all(p['part_number'] not in [x['part_number'] for x in result.get('set_aside_outside_product',[])] for p in panels)


@pytest.mark.parametrize('drawing',['B.34473','B.34468'])
def test_both_shelf_products_use_component_not_stock_blanks(fresh,drawing):
    result,audit=recover(fresh[drawing])
    bracket=next(p for p in result['parts'] if compact(p['part_number']) in ('C33383','20125999'))
    assert (bracket['blank_length_mm'],bracket['blank_width_mm'])==(383.3,125.5)
    for p in result['parts']:
        if 'UNDER SIDE SUPPORT' in (p.get('description') or ''):
            assert 0 < p['blank_length_mm'] < 1000 and 0 < p['blank_width_mm'] < 200
    assert audit['priced'] is False


@pytest.mark.parametrize('drawing',['A.34504','A.33559'])
def test_two_other_cupboards_have_the_same_confirmed_bracket_fault(fresh,drawing):
    result,audit=recover(fresh[drawing])
    brackets=[p for p in result['parts'] if 'ENGAGEMENT BRACKET' in (p.get('description') or '')]
    assert len(brackets)==2
    assert all(sorted((p['blank_length_mm'],p['blank_width_mm']))==[112.6,123.6] for p in brackets)
    assert all(p.get('owned_blank_basis') for p in brackets)


def test_cash_gap_is_own_sheet_raw_sprayed_mdf_not_inherited_laminate(fresh):
    result,audit=recover(fresh['B.33792'])
    part=next(p for p in result['parts'] if compact(p['part_number'])=='C33799')
    assert part['normalized_material']=='MDF' and part['normalized_thickness_mm']==18
    assert (part['blank_length_mm'],part['blank_width_mm'])==(1866,770)
    from estimator import _faced_board_promotion
    assert _faced_board_promotion(part,'MDF')==(None,'')
    assert part['owned_board_construction']['mode']=='raw_board_with_wet_finish'
    assert {'cnc_routing','wet_spray'} <= set(part.get('inferred_operations',[])+part.get('textual_operations',[]))
    assert 'folding' not in part.get('inferred_operations',[])+part.get('textual_operations',[])
    # 18 mm (material note) against the 6 printed on its section: kept as a review item.
    assert part['owned_thickness_conflict']['printed_mm']==[6]
    # ...and costing does not read the ruled-out dashed lines back as press-brake folds.
    import estimator
    assert 'folding' not in estimator.estimate_process_times(copy.deepcopy(part),1).get('setup_times_min',{})
    assert audit['priced'] is False


@pytest.mark.parametrize('drawing',['B.34473','B.34468'])
def test_live_pre_costing_owned_pass_replaces_existing_stock_blanks_without_index_rebuild(fresh,drawing):
    from owned_component_manufacturing import prepare as owned_pass
    summary=copy.deepcopy(fresh[drawing])
    owned_pass(summary)
    parts=summary['manufacturing_writeup']['parts']
    bracket=next(p for p in parts if compact(p['part_number']) in ('C33383','20125999'))
    assert (bracket['blank_length_mm'],bracket['blank_width_mm'])==(383.3,125.5)
