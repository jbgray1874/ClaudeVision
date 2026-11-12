"""Deliberate losses, conflicting facts and generic sizes; no golden job-number rules."""
import copy
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from robust_ownership import brief_oval_shape, section_shipping, nonphysical, release_email_lines
from requirement_coverage import audit
from page_coverage import build


@pytest.mark.parametrize('a,b,t', [(30,15,1.5), (40,20,2), (60,30,3)])
def test_shape_is_scoped(a,b,t):
    assert brief_oval_shape(f'Tube {a} x {b} x {t} flat-sided oval.', [a,b], t) == 'flat_sided'
    assert brief_oval_shape(f'Tube {a} x {b} x {t} flat-sided oval; {a} x {b} x {t} elliptical.', [a,b], t) is None
    assert brief_oval_shape(f'Tube {a} x {b} x {t} FSO.', [a+1,b], t) is None
    assert brief_oval_shape(f'Tube {a} x {b} x {t} FSO.', [a,b], t+1) is None


def test_section_not_strip():
    p = {'section_stock': {'a':30,'b':15,'t':1.5,'length_mm':1192,
                           'profile_form':'OVAL','oval_shape':'flat_sided'}}
    result = section_shipping(p,7850)
    assert result['kg'] == pytest.approx(1.017,abs=.002)
    del p['section_stock']['length_mm']
    assert 'error' in section_shipping(p,7850)
    assert 'error' in section_shipping({'stock_form':'tube','blank_length_mm':500},7850)


def test_real_stock_mapper_carries_fso():
    from concept_scan import resolve_stocks, _apply_stock
    part = {'kind':'fabricated','name':'tube', 'stock':{'form':'oval_tube',
            'section_mm':[40,20],'wall_mm':2},
            'assumed_blank_mm':{'length':700,'width':40,'thickness':2}}
    stock = resolve_stocks([part], '40 x 20 x 2 flat-sided oval tube.')[0]
    assert stock['oval_shape'] == 'flat_sided'


def test_real_shipment_counts_section_mass_not_flat_strip():
    from commercial_lines import describe_order
    part = {'part_number':'MEMBER-A','quantity':2,'normalized_material':'MILD_STEEL',
            'section_stock':{'a':30,'b':15,'t':1.5,'length_mm':1192,
                             'profile_form':'OVAL','oval_shape':'flat_sided'}}
    result = describe_order([part],10)
    assert result['unit_weight_kg'] == pytest.approx(2.03,abs=.01)
    assert 'FSO' in result['counted_parts'][0]['weight_basis']


def test_service_is_not_object_but_name_is_not_classifier():
    assert nonphysical({'_plating_placeholder':True})
    assert nonphysical({'line_kind':'service'})
    assert not nonphysical({'part_number':'PLATE','description':'plating support plate'})


def test_email_preserves_authority_and_findings():
    record = {'release': {'status':'draft','outstanding':2}}
    summary = {'read_charge_result': {'applicable':True,'passed':False,
               'issues':[{'item':'W1','code':'weld_missing'}]}}
    before = copy.deepcopy((record,summary))
    text = ' '.join(release_email_lines(record,summary))
    assert 'draft' in text and 'weld_missing' in text
    assert (record,summary) == before
    assert 'unavailable' in release_email_lines({}, {})[0]


def page(**kw):
    return dict(document='drawing.pdf',page=1,has_text=True,chars=300,width_pt=595,height_pt=842,**kw)


def test_unread_text_and_document_not_silent():
    assert build({},[page()])['gaps'][0]['kind'] == 'text_not_read'
    assert build({},[{'document':'bad.pdf','page':None,'error':'cannot open'}])['gaps'][0]['kind'] == 'document_unread'
    assert build({},[])['gaps'][0]['kind'] == 'inventory_missing'


def test_render_is_not_response():
    summary = {'concept_read': {'pages_rendered':[{'document':'drawing.pdf','page':1,'px':[2000,3000]}]}}
    assert 'image_response_unverified' in {g['kind'] for g in build(summary,[page()])['gaps']}
    summary['concept_read']['raw_response'] = '{"parts":[]}'
    assert not build(summary,[page()])['gaps']  # Transport only, NOT evidence of a complete BOM.


def test_other_page_and_squashed_image_do_not_prove_coverage():
    from page_coverage import effective_dpi
    s = {'concept_read':{'raw_response':'answer','pages_rendered':[
         {'document':'other.pdf','page':1,'px':[2000,3000]}]}}
    assert build(s,[page()])['gaps'][0]['kind']=='text_not_read'
    assert effective_dpi([100,3000],595,842) < 20


def test_real_unit_count_excludes_service():
    from concept_scan import unit_assembly_part
    pieces = [{'part_number':'A','concept_kind':'fabricated','quantity':2,
               'normalized_material':'MILD_STEEL'},
              {'part_number':'B','concept_kind':'fabricated','quantity':3},
              {'part_number':'SERVICE-A','concept_kind':'bought_in','quantity':1,
               '_plating_placeholder':True}]
    result = unit_assembly_part(pieces,{'product':{'name':'test unit'}},'TEST')
    assert result['pieces_fitted']==5


def test_compiled_route_keeps_service_but_does_not_fit_it():
    from route_compiler import compile_job_route
    result=compile_job_route([
        {'part_number':'A-GA','is_assembly_parent':True,'quantity':1,
         'assembly_children':['A-01M','A-SVC']},
        {'part_number':'A-01M','quantity':1,'normalized_material':'MILD_STEEL'},
        {'part_number':'A-SVC','quantity':1,'_plating_placeholder':True,
         '_commercial_placeholder':True}])
    assert any(n['part_number']=='A-SVC' for n in result['nodes'])
    rows=[d for d in result['decisions'] if d['operation']=='assembly']
    assert rows and rows[0]['participants']==['A-01M']


def fixture():
    return ([dict(id='source-A',document='a.pdf',page=2,part_number='PART-A',quantity=2,
                  operation='saw',charge_ids=['cut-A'])],
            [dict(part_number='PART-A',quantity=2)],
            [dict(charge_id='cut-A',requirement_ids=['source-A'],operations=['saw'],
                  cell='Labour!K20',value=3.4,saved_value=3.4,basis_verified=True)])


def test_normal_pack_baseline_and_missing_capture():
    assert audit(*fixture())['passed']
    assert not audit([],[],[])['passed']


@pytest.mark.parametrize('mutation,expected', [
    ('part','part_missing'),('quantity','quantity_mismatch'),('operation','operation_missing'),
    ('charge','coverage_not_named'),('zero','charged_cell_unverified'),
    ('text','charged_cell_unverified'),('cached','charged_cell_unverified'),
    ('basis','charge_basis_unverified'),('page','source_missing'),
    ('exclude','exclusion_unapproved'),('duplicate','part_identity_ambiguous')])
def test_deliberate_losses(mutation,expected):
    r,p,c = fixture()
    if mutation=='part': p.clear()
    if mutation=='quantity': p[0]['quantity']=4
    if mutation=='operation': c[0]['operations']=[]
    if mutation=='charge': c.clear()
    if mutation=='zero': c[0]['value']=c[0]['saved_value']=0
    if mutation=='text': c[0]['value']=c[0]['saved_value']='3.4'
    if mutation=='cached': c[0]['saved_value']=3.5
    if mutation=='basis': c[0]['basis_verified']=False
    if mutation=='page': r[0]['page']=None
    if mutation=='exclude': r[0]['state']='excluded'
    if mutation=='duplicate': p.append(dict(p[0]))
    result=audit(r,p,c)
    assert not result['passed'] and any(expected in x for x in result['findings'])


# ── D-598: the e-mail repeats the release record and the ledger, pointing at §9 ────────────

def _release_record():
    return {'release': {'status': 'provisional', 'draft': True, 'to_confirm': 17,
                        'reasons': ['6 automated check(s) to review',
                                    '4 of them from the read ledger: S.finish'],
                        'held_allowances_gbp_per_unit': 26.49,
                        'held_at_breaks': [
                            {'quantity': 1, 'unit_gbp': 236.46, 'held_gbp_per_unit': 26.49,
                             'unit_excluding_held_gbp': 209.97},
                            {'quantity': 1000, 'unit_gbp': 54.82, 'held_gbp_per_unit': 26.49,
                             'unit_excluding_held_gbp': 28.33}]}}


def _ledger_summary():
    return {'read_charge_result': {
        'applicable': True, 'passed': False,
        'counts': {'charged': 11, 'covered': 2, 'excluded': 0, 'unresolved': 2},
        'items': [{'id': 'S.finish', 'label': 'plate: polished chrome'}],
        'issues': [{'code': 'read_item_unresolved', 'item': 'S.finish',
                    'why': 'the plating line carries no price'},
                   {'code': 'engine_allowance_unconfirmed', 'item': 'allowance:brush_before_plate',
                    'basis': 'stated for another product'}]}}


def test_every_panel_line_points_at_the_release_section():
    from robust_ownership import release_focus_lines
    lines = release_focus_lines(_release_record(), _ledger_summary())
    assert lines and all('§9' in l for l in lines)
    said = ' '.join(lines)
    assert 'provisional, a draft — 17 to confirm' in said
    assert '£26.49 a unit rests on engine allowances' in said and '£28.33 at 1,000 off' in said
    assert '1 item(s) the read returned reach no charge and no ruling (S.finish)' in said
    assert 'unavailable' in release_focus_lines({}, {})[0]


def test_the_release_section_lists_reasons_held_allowances_and_ledger_findings():
    from estimate_explained import release_section_html
    html = release_section_html(_release_record(), _ledger_summary())
    assert '<h3>9. The release record and the read ledger</h3>' in html
    assert '4 of them from the read ledger' in html and '£209.97' in html and '£28.33' in html
    assert 'plate: polished chrome' in html and 'stated for another product' in html
    assert 'it holds the release' in html
    missing = release_section_html({}, {})
    assert 'not available' in missing and 'not release evidence' in missing


def test_a_part_the_model_read_off_the_sheet_is_not_said_to_be_drawn_nowhere():
    from estimate_explained import _tracing_failures
    rec = {'part_number': 'X-CPT02', 'description': 'HOOK BRACKET', 'concept': True,
           'concept_drawn': 'page 2, bracket detail', 'geometry_source': 'vision_concept'}
    out = _tracing_failures({'X-CPT02': rec}, [], {'X-CPT02': {'total_value_gbp': 0.27}}, {})
    why = ' '.join(out[0]['why'])
    assert 'read by the vision model off the pack' in why and 'page 2, bracket detail' in why
    assert 'nothing in the pack draws' not in why
