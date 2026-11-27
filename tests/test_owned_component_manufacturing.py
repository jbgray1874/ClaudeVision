import copy
import pytest
from owned_component_manufacturing import prepare, finish_schedule, apply_reviewed_text


def sample(material='1.5mm CR4 SHEET STEEL 2500X1250'):
    return {'pages': [{'source_pdf_name': 'nc1-c45678.pdf', 'page_number': 7,
        'pypdf_text': '383.3 CUT\n125.5 CUT\nBRACKET\nPART NO. :20129991\nMATERIAL:' + material}],
        'manufacturing_writeup': {'parts': [{'part_number': 'C.45678', 'quantity': 2}]}}


def test_owned_label_material_blank_and_route_not_the_stock_sheet():
    s = sample()
    prepare(s)
    p = s['manufacturing_writeup']['parts'][0]
    assert (p['normalized_material'], p['normalized_thickness_mm']) == ('MILD_STEEL', 1.5)
    assert (p['blank_length_mm'], p['blank_width_mm']) == (383.3, 125.5)
    assert {'laser_cutting', 'deburring'} <= set(p['inferred_operations'])
    assert p['quantity'] == 2
    before = copy.deepcopy(s)
    prepare(s)
    assert s == before


@pytest.mark.parametrize('flag', ['is_bought_in', 'reference_only', 'is_reference_only',
    'for_reference_only', 'supplied_by_third_party'])
def test_explicit_exclusions_remain_intentional(flag):
    s = sample(); p = s['manufacturing_writeup']['parts'][0]; p[flag] = True
    prepare(s)
    assert 'inferred_operations' not in p and 'normalized_material' not in p


def test_foreign_or_conflicting_sheet_cannot_supply_material():
    s = sample(); p = s['manufacturing_writeup']['parts'][0]
    s['pages'][0]['source_pdf_name'] = 'nc1-d45679.pdf'
    s['pages'][0]['pypdf_text'] += '\nDRG No. C.45678'
    prepare(s)
    assert 'normalized_material' not in p


def test_native_material_gauge_dimensions_and_explicit_flat_are_preserved():
    import source_precedence as sp
    s = sample(); p = s['manufacturing_writeup']['parts'][0]
    for field, value in [('normalized_material', 'STAINLESS_STEEL'),
                         ('normalized_thickness_mm', 3), ('blank_length_mm', 420), ('blank_width_mm', 90)]:
        sp.apply_field(p, field, value, 'solidworks_api')
    p['native_flat_solid'] = True
    s['pages'][0]['pypdf_text'] += '\nCHANNEL RETURN'
    prepare(s)
    assert p['normalized_material'] == 'STAINLESS_STEEL' and p['normalized_thickness_mm'] == 3
    assert (p['blank_length_mm'], p['blank_width_mm']) == (420, 90)
    assert 'folding' not in p['inferred_operations']


def test_exact_numeric_stock_duplicate_folds_once_without_changing_pieces():
    s = sample(); parts = s['manufacturing_writeup']['parts']
    parts.append({'part_number': '20129991', 'quantity': 2, 'bom_parent': 'A.45670'})
    prepare(s)
    assert len(parts) == 1 and parts[0]['quantity'] == 2
    assert parts[0]['raw_aliases'] == ['20129991']
    prepare(s)
    assert len(parts) == 1


def test_uncertain_envelope_is_labelled_and_never_claimed_measured():
    s = sample(); s['pages'][0]['pypdf_text'] = s['pages'][0]['pypdf_text'].replace(' CUT', '')
    prepare(s); p = s['manufacturing_writeup']['parts'][0]
    assert p['owned_blank_basis']['provisional'] is True
    assert p['blank_length_mm_source'] == 'geometry_inference'
    assert 'PROVISIONAL' in p['owned_blank_basis']['basis']


def test_no_sheet_size_or_date_can_become_the_missing_blank():
    s = sample(); s['pages'][0]['pypdf_text'] = 'PART NO.:20129991\nMATERIAL:2mm CR4 2500X1250\n2026\n1000'
    prepare(s); p = s['manufacturing_writeup']['parts'][0]
    assert not p.get('blank_length_mm')


def test_uncertain_material_callouts_do_not_choose_one_arbitrarily():
    s = sample(); s['pages'].append(dict(s['pages'][0], page_number=8,
        pypdf_text=s['pages'][0]['pypdf_text'].replace('1.5mm', '3mm')))
    prepare(s)
    assert 'normalized_thickness_mm' not in s['manufacturing_writeup']['parts'][0]


def test_finish_schedule_is_generic_and_deduplicates_repeated_text():
    text = '1 X COAT OF CLEAR ISOLATOR\n1 X COAT OF BASECOAT\n2 X COAT OF TOPCOAT'
    s = finish_schedule(text + '\n' + text)
    assert s['passes'] == 4 and len(s['stages']) == 3
    assert finish_schedule('COLOUR: BROWN') is None


def test_reviewed_raster_transcription_is_explicit_page_bound_and_atomic():
    s = sample(); before = copy.deepcopy(s)
    item = {'source_pdf_name': 'nc1-c45678.pdf', 'page_number': 7,
            'text': 'DRG No. C.45678\n1 X COAT OF BASECOAT', 'basis': 'Read and checked the raster title block'}
    bad = dict(item, page_number=8)
    with pytest.raises(ValueError):
        apply_reviewed_text(s, {'schema': 'owned_manufacturing_text.v1', 'pages': [item, bad]})
    assert s == before
    apply_reviewed_text(s, {'schema': 'owned_manufacturing_text.v1', 'pages': [item]})
    assert s['pages'][0]['pypdf_text'] == before['pages'][0]['pypdf_text']
    assert s['reviewed_manufacturing_text']['sha256']


def test_mdf_specification_and_quantities_survive_caption_repair():
    from test_component_caption_blanks import _summary
    from component_caption_blanks import repair
    s = _summary()
    # Each caption carries its own MATERIAL field, including the final caption.
    s['pages'][0]['normalized_text'] += '\nMATERIAL:18mm FR B MDF 3050 X 1220mm'
    repair(s); prepare(s)
    parts = s['manufacturing_writeup']['parts']
    assert [p['quantity'] for p in parts] == [4, 1, 1]
    assert all(p['normalized_material'] == 'MDF' and p['normalized_thickness_mm'] == 18 for p in parts)
    assert all('FR B' in p['material_specification'] for p in parts)
    assert all('cnc_routing' in p['inferred_operations'] for p in parts)


@pytest.mark.parametrize('material,required', [
    ('18mm FR B MDF 3050 X 1220', {'cnc_routing', 'bench_work'}),
    ('1.5mm CR4 SHEET STEEL 2500 X 1250', {'laser_cutting', 'deburring', 'folding'})])
def test_recovered_materials_and_manufacturing_reach_positive_costs_not_only_notes(material, required):
    from estimator import estimate_material, estimate_process_times, estimate_labour_costs
    s = sample(material)
    s['pages'][0]['pypdf_text'] += '\nUPSTAND'
    prepare(s)
    p = s['manufacturing_writeup']['parts'][0]
    m = estimate_material(p)
    t = estimate_process_times(p, quantity=2)
    labour = estimate_labour_costs(t, job_quantity=2, material=p['normalized_material'])
    assert m['unit_material_cost_gbp'] > 0
    assert m['extended_material_cost_gbp'] > m['unit_material_cost_gbp']
    assert all(labour['costs_gbp'].get(op, 0) > 0 for op in required)
    assert p['quantity'] == 2


def test_round_bar_is_not_given_a_sheet_laser_allowance():
    s = sample('25mm MILD STEEL ROUND BAR')
    prepare(s)
    assert 'laser_cutting' not in s['manufacturing_writeup']['parts'][0].get('inferred_operations', [])


@pytest.mark.parametrize('held', ['MILD STEEL', 'MILD_STEEL'])
def test_a_sheet_part_is_cut_whichever_spelling_its_steel_already_has(held):
    # The extractor writes "MILD STEEL"; the lexicon codes it MILD_STEEL. The engine counts
    # them as one material, so the route must not depend on which one the part already has.
    import source_precedence as sp
    s = sample(); p = s['manufacturing_writeup']['parts'][0]
    sp.apply_field(p, 'normalized_material', held, 'drawing_deterministic')
    prepare(s)
    assert {'laser_cutting', 'deburring'} <= set(p['inferred_operations'])
