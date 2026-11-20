"""Round stock rows do not create a phantom bought-in child or a weldment."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ.setdefault('SDI_OFFLINE', '1')
import pytest
from section_profile import detect_section_stock
from part_identity import mint_uncoded_row_identities
from bom_pipeline import apply_stated_cut_list_to_parts


@pytest.mark.parametrize('description', ['12.7mm DIA x 1.2mm WALL 50',
                                      '12.7 DIA × 1.2 WALL 50'])
def test_explicit_round_cut_list_names_stock(description):
    s = detect_section_stock(description)
    assert s and s['profile_form'] == 'CHS'
    assert (s['a'], s['b'], s['t'], s['length_mm']) == (12.7, 12.7, 1.2, 50)
    rows = [dict(part_number='', description=description, quantity=1,
                 bom_parent='T-01M', bom_parent_known=True)]
    mint_uncoded_row_identities(rows)
    assert rows[0]['part_number'] == ''
    assert rows[0]['row_role'] == 'parent_cut_list'
    p = dict(part_number='T-01M', description='FIXING TUBE', page_roles=['detail'],
             normalized_material='MILD STEEL', is_assembly_parent=True,
             canonical_kind='assembly')
    assert apply_stated_cut_list_to_parts([p], rows) == 1
    assert p['section_stock']['cut_lengths_mm'] == [50]
    assert p['section_stock']['profile_form'] == 'CHS'
    assert not p['is_assembly_parent'] and not p['weldment_from_own_cut_list']
    assert p['section_from_own_cut_list']


def test_round_profile_does_not_invent_a_length_from_another_line():
    s = detect_section_stock('12.7mm DIA x 1.2mm WALL\nCopyright 2026')
    assert s['length_mm'] is None


def test_invalid_round_profile_is_not_canonical():
    s = detect_section_stock('2mm DIA x 2mm WALL 50')
    assert not s or s.get('detection_path') != 'canonical_profile'


def test_an_accessory_is_still_an_item():
    rows = [dict(part_number='', description='WALL BRACKET', quantity=1,
                 bom_parent='T-GA', bom_parent_known=True)]
    mint_uncoded_row_identities(rows)
    assert rows[0]['row_role'] == 'part'


def test_fresh_leaf_also_records_its_one_piece_basis():
    rows=[dict(part_number='', description='12.7mm DIA x 1.2mm WALL',
               length_mm=50, quantity=1, bom_parent='T-01M', bom_parent_known=True)]
    mint_uncoded_row_identities(rows)
    p=dict(part_number='T-01M', normalized_material='MILD STEEL', page_roles=['detail'])
    apply_stated_cut_list_to_parts([p],rows)
    assert p['section_from_own_cut_list']
    assert not p['weldment_from_own_cut_list']
    assert p['section_stock']['length_mm']==50


def _tube_in_frame(**over):
    import route_compiler as rc
    tube = dict(part_number='90001-01-02M', description='FIXING TUBE', quantity=6,
                normalized_material='MILD STEEL', normalized_finish='SEE ASSEMBLY DRAWING',
                page_roles=['detail'], section_from_own_cut_list=True,
                section_stock=dict(a=12.7, b=12.7, t=1.2, profile_form='CHS',
                                   length_mm=50, cut_lengths_mm=[50]),
                textual_operations=['welding', 'dress_welds', 'saw'])
    tube.update(over)
    parent = dict(part_number='90001-01-201', description='FRAME ASSEMBLY',
                  is_assembly_parent=True, assembly_children=['90001-01-02M'],
                  textual_operations=['welding'], weld_symbols={'fillet': 6},
                  operation_sources={'welding': 'drawing_deterministic'})
    route=rc.compile_job_route([parent, tube], known_assemblies=['90001-01-201'])
    return { (d['target_id'],d['operation']): d for d in route['decisions'] }


def test_single_stock_length_has_no_second_weld_beside_parent():
    decisions=_tube_in_frame()
    for op in ('welding','dress_welds'):
        d=decisions['90001-01-02M',op]
        assert d['status']=='not_applicable'
        assert d['field_provenance']['weld_owner']=='90001-01-201'
    assert decisions['90001-01-201','welding']['status']=='required'
    assert decisions['90001-01-02M','saw']['status']=='required'


@pytest.mark.parametrize('over', [
    {'weld_symbols': {'fillet': 1}},
    {'operation_sources': {'welding':'estimator_confirmed'}},
    {'operation_sources': {'welding':'drawing_deterministic'}},
    {'weld_stated_by_note': 'SEAM WELD'},
    {'weld_length_mm': 50},
    {'manufacturing_features': {'welding_required': True}},
    {'section_stock': {'cut_lengths_mm':[50,50]}},
])
def test_own_weld_evidence_or_multiple_pieces_keep_the_members_weld(over):
    assert _tube_in_frame(**over)['90001-01-02M','welding']['status']=='required'


def test_multibody_stock_frame_keeps_weldment_timing_not_minimal_bead():
    from estimator import estimate_process_times, is_weldment_parent
    import config
    p=dict(part_number='T-01M', description='FRAME', normalized_material='MILD STEEL',
           page_roles=['detail'], is_assembly_parent=False, canonical_kind='leaf',
           section_from_own_cut_list=True, weldment_from_own_cut_list=True,
           section_stock=dict(a=25.4,b=25.4,t=1.2,profile_form='SHS',
                              cut_lengths_mm=[2430,2430,1169.2,1169.2]),
           textual_operations=['welding','dress_welds'],
           operation_sources={'welding':'drawing_deterministic','dress_welds':'drawing_notes'})
    assert is_weldment_parent(p)
    times=estimate_process_times(p)['run_times_min_per_unit']
    assert times['welding']==config.WELD_TIME_MODEL['allowance_min_per_weldment']
    assert times['dress_welds']==config.WELD_TIME_MODEL['dress_allowance_min_per_weldment']
    assert p['weld_time_is_an_allowance']
    # An explicit joint count supersedes that allowance; no topology is guessed.
    p['weld_joint_count']=4
    times=estimate_process_times(p)['run_times_min_per_unit']
    assert times['welding']==4*config.WELD_TIME_MODEL['weld_min_per_joint']


def test_one_piece_cut_list_is_not_a_weldment_for_timing():
    from estimator import is_weldment_parent
    assert not is_weldment_parent(dict(part_number='T-01M', description='PIN TUBE',
        section_from_own_cut_list=True, weldment_from_own_cut_list=False,
        section_stock={'cut_lengths_mm':[50]}))
