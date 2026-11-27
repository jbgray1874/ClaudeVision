"""Offline regression coverage. No services, CAD, Excel, research or job submission."""
import copy
import json
import os
from pathlib import Path
import pytest
import openpyxl


@pytest.mark.parametrize('required',[101,131,133,188])
def test_department_scan_grows_with_every_cost_row_and_survives_save(required,tmp_path):
    from test_12517_complete_cost_coverage import book
    from workbook_labour_capacity import ensure_labour_capacity
    from wb_populate import labour_sheet_coverage,repair_labour_sheet_references
    wb,cm=book();flags=[]
    assert ensure_labour_capacity(wb,cm,required,flags)==required-72
    repair_labour_sheet_references(wb,cm,flags)
    assert labour_sheet_coverage(wb,cm)['ok']
    assert wb['Labour'][f'A{required}'].value==f'=Estimate!G{150+required}'
    assert wb['Labour'][f'B{required}'].value==f'=Estimate!J{150+required}'
    assert f'$A$1:$B${required}' in wb['Labour']['C2'].value.text
    assert wb['Labour']['F3'].value=='=M225'
    assert wb['Labour']['F5'].value=="='[External.xlsx]Estimate'!M225"
    total=151+required
    assert wb['Estimate'][f'M{total}'].value==f'=SUM(M151:M{total-1})'
    assert ensure_labour_capacity(wb,cm,required)==0
    p=tmp_path/'generated.xlsx';wb.save(p)
    reopened=openpyxl.load_workbook(p)
    assert reopened['Labour']['C2'].value.text==wb['Labour']['C2'].value.text


def test_department_expansion_never_overwrites_unrelated_inputs():
    from test_12517_complete_cost_coverage import book
    from workbook_labour_capacity import ensure_labour_capacity
    wb,cm=book();wb['Labour']['A101']='manual note'
    with pytest.raises(ValueError,match='occupied'):
        ensure_labour_capacity(wb,cm,133)
    assert cm['labour']['last_row']==222 and wb['Labour']['A101'].value=='manual note'
    assert wb['Estimate']['M225'].value=='=(M147+M223)/(1-M227)/0.92'


def _tube(length=617.5):
    return {'pages':[{'source_pdf_name':'nc1-d77111.pdf','page_number':7,
      'pypdf_text':f' {length}  42\nSUPPORT TUBE\nPART NO. :20127777\nMATERIAL:42 X 1.5MM ERW ROUND TUBE 6M (30059999)'}],
      'manufacturing_writeup':{'parts':[{'part_number':'D.77111','description':'SUPPORT TUBE','quantity':3}]}}


def test_owned_round_tube_recovers_profile_and_piece_length_not_stock_bar(monkeypatch):
    from owned_component_manufacturing import prepare
    import estimator as E
    s=_tube();prepare(s);p=s['manufacturing_writeup']['parts'][0]
    assert (p['section_stock']['a'],p['section_stock']['t'],p['section_stock']['length_mm'])==(42,1.5,617.5)
    assert p['section_stock']['profile_form']=='CHS' and p['quantity']==3
    assert not p.get('blank_width_mm')
    monkeypatch.setattr(E,'_lookup_catalogue_section_stock_rate',lambda *a,**k:None)
    monkeypatch.setattr(E,'_resolve_material_price',lambda *a,**k:{})
    result=E.estimate_material(p)
    assert result['stock_form']=='tube' and result['requires_flat_blank'] is False
    assert result['cost_per_part_gbp']>0 and result['unit_material_mass_kg']>0
    before=copy.deepcopy(s);prepare(s);assert s==before


@pytest.mark.parametrize('text', ['42 x 1.5mm ERW ROUND TUBE 6M','42mm x 1.5mm CHS','44.45 x 2 MM ROUND TUBE'])
def test_round_stock_wording_variations(text):
    from section_profile import stock_in_material_words
    s=stock_in_material_words(text)
    assert s and s['profile_form']=='CHS' and s['length_mm'] is None


def test_a_foreign_sheet_or_invalid_wall_cannot_repair_the_tube():
    from owned_component_manufacturing import prepare
    from section_profile import stock_in_material_words
    s=_tube();s['manufacturing_writeup']['parts'][0]['part_number']='D.77112';prepare(s)
    assert not s['manufacturing_writeup']['parts'][0].get('section_stock')
    assert stock_in_material_words('42 x 30mm ERW ROUND TUBE') is None


def _purchase():
    return {'pages':[{'source_pdf_name':'nc1-d88111.pdf','page_number':8,
      'pypdf_text':' 96 CRITICAL\n 372 CRITICAL\n 128\nSHELF PUSHER\nPART NO. :30058888\nSAME SPEC AS PREVIOUSLY SUPPLIED'}],
      'manufacturing_writeup':{'parts':[{'part_number':'D.88111','description':'SHELF PUSHER',
          'quantity':150,'textual_operations':['hole_machining','handling']}]}}


def test_repeat_supply_keeps_full_component_scope_article_and_count():
    from owned_component_manufacturing import prepare
    from bought_in_policy import is_bought_in
    s=_purchase();prepare(s);p=s['manufacturing_writeup']['parts'][0]
    assert is_bought_in(p) and p['quantity']==150
    assert p['supplier_part_number']=='30058888'
    assert '372 CRITICAL' in p['price_chain_description'] and 'COMPLETE' in p['price_chain_description']
    assert p['repeat_supply_basis']['provisional'] is True
    assert p['textual_operations']==['handling']
    before=copy.deepcopy(s);prepare(s);assert s==before


def test_a_repeat_part_with_own_stock_spec_is_not_automatically_a_purchase():
    from owned_component_manufacturing import prepare
    s=_purchase();s['pages'][0]['pypdf_text']+='\nMATERIAL:3mm CLEAR ACRYLIC'
    prepare(s);assert not s['manufacturing_writeup']['parts'][0].get('is_bought_in')


def test_the_complete_repeat_supplied_component_reaches_the_price_chain(monkeypatch):
    from owned_component_manufacturing import prepare
    import estimator as E
    s=_purchase();prepare(s);p=s['manufacturing_writeup']['parts'][0];seen=[]
    def lookup(request):
        seen.append(request)
        return {'selected':{'price':19.5,'source':'synthetic_catalogue'}}
    monkeypatch.setattr(E,'get_best_price',lookup)
    quote=E._resolve_part_system_cost(p)
    assert quote['applied_unit_cost']==19.5
    assert 'COMPLETE' in seen[0].description and '372 CRITICAL' in seen[0].description
    assert p['quantity']==150


def _subcontracts():
    return [{'part_number':'A.77100-PLATE','quantity':1,'_plating_placeholder':True,
             '_plating_members':['D.77111'],'material_estimate':{'unit_material_mass_kg':12.0},
             '_price_explicitly_withheld':True,'unit_total_cost_gbp':0},
            {'part_number':'PLATERFREIGHT','quantity':1,'_plater_freight':True,
             '_commercial_placeholder':True,'material_estimate':{},'_price_explicitly_withheld':True}]


def _answer(price=8,unit='kg',minimum=100):
    return {'price_gbp':price,'unit':unit,'minimum_gbp':minimum,'as_of':'2026-11-27',
      'source':'Synthetic test supplier, not a real quote','quantity_basis':'trade order',
      'price_is_reproducible':True,'item_priced':'finishing for the stated members'}


def test_process_and_round_trip_budgets_reach_the_charged_material_price():
    from subcontract_cost_completion import complete_subcontract_costs
    from wb_populate import _bom_line_price,waste_already_in_price
    parts=_subcontracts();seen=[]
    def ask(brief):
        seen.append(brief)
        return _answer(80,'order',None) if brief['kind']=='commercial' else _answer()
    raw=[{'part_number':'D.77111','normalized_finish':'CHROME PLATED'}]
    assert complete_subcontract_costs(parts,{},raw,2,ask)==2
    # 12kg x GBP8 = GBP96. Minimum GBP100 / 2 units = GBP50: max, not sum.
    assert _bom_line_price(parts[0])==96
    assert _bom_line_price(parts[1])==40
    assert sum(p['extended_total_cost_gbp'] for p in parts)==136
    assert parts[1]['commercial_line']['order_gbp']==80
    assert parts[0]['unit_with_order_minimum']=={'unit_gbp':96,'order_minimum_gbp':100}
    assert all(waste_already_in_price(p) for p in parts)
    assert all(not p['_price_explicitly_withheld'] and not p['price_verified'] for p in parts)
    assert 'CHROME' in seen[0]['finish_spec']
    assert 'ROUND' in seen[1]['description'].upper()
    before=copy.deepcopy(parts)
    assert complete_subcontract_costs(parts,{},raw,2,lambda _:pytest.fail('duplicate research'))==0
    assert parts==before


def test_minimum_is_spread_once_over_the_finished_order():
    from subcontract_cost_completion import complete_subcontract_costs
    p=_subcontracts()[:1]
    complete_subcontract_costs(p,{},[],1,lambda _:_answer(2,'kg',100))
    assert p[0]['unit_material_cost_gbp']==100


def test_area_rate_is_not_multiplied_by_kilograms():
    from subcontract_cost_completion import complete_subcontract_costs
    p=_subcontracts()[:1]
    raw=[{'part_number':'D.77111','normalized_finish':'BRASS PLATED','_powder_members_coated_m2':3}]
    complete_subcontract_costs(p,{},raw,1,lambda _:_answer(20,'m2',None))
    assert p[0]['unit_material_cost_gbp']==60


def test_the_wrong_finish_does_not_sneak_in_as_an_allowance():
    from subcontract_cost_completion import complete_subcontract_costs
    p=_subcontracts()[:1]
    reply=dict(_answer(),item_priced='trade zinc plating')
    assert complete_subcontract_costs(p,{},[{'part_number':'D.77111','normalized_finish':'CHROME PLATED'}],1,lambda _:reply)==0
    assert p[0]['_price_explicitly_withheld']


def test_an_explicit_one_way_rate_allows_two_legs_once():
    from subcontract_cost_completion import complete_subcontract_costs
    p=_subcontracts()[1:]
    assert complete_subcontract_costs(p,{},[],4,lambda _:_answer(40,'leg',None))==1
    assert p[0]['unit_material_cost_gbp']==20  # GBP40 x 2 journeys / 4 units


@pytest.mark.parametrize('bad', [{},{'price_gbp':0},_answer(5,'mile'),_answer(5,'each')])
def test_no_answer_or_wrong_units_stay_visible_and_are_not_invented(bad):
    from subcontract_cost_completion import complete_subcontract_costs
    p=_subcontracts()[:1]
    assert complete_subcontract_costs(p,{},[],1,lambda _:bad)==0
    assert p[0]['_price_explicitly_withheld'] is True
    assert p[0]['subcontract_allowance_attempt'].get('missing')


def test_a_genuine_price_and_free_issue_are_preserved():
    from subcontract_cost_completion import complete_subcontract_costs
    p=_subcontracts();p[0]['material_estimate']['unit_material_cost_gbp']=220
    p[1]['supplied_by_third_party']=True
    before=copy.deepcopy(p)
    assert complete_subcontract_costs(p,{},[],1,lambda _:pytest.fail('must not research'))==0
    assert p==before


def test_completion_is_before_totals_in_the_real_estimator():
    import inspect,estimator
    source=inspect.getsource(estimator.estimate_document)
    assert source.index('complete_subcontract_costs(')<source.index('material_total_raw =')


def test_plating_mass_uses_nested_quantities_not_the_members_local_one():
    from subcontract_cost_completion import complete_subcontract_costs
    p=_subcontracts()[:1]+[{'part_number':'D.77111','quantity':1,'material_estimate':{'unit_material_mass_kg':2}}]
    raw=[{'part_number':'A.77100','quantity':1,'is_assembly_parent':True,'assembly_children':['D.77111']},
         {'part_number':'D.77111','quantity':1,'normalized_finish':'CHROME'}]
    summary={'declared_product':'A.77100','llm_full_extract':{'assemblies':[
        {'part_number':'A.77100','children':[{'part_number':'D.77111','qty':12}]}]}}
    complete_subcontract_costs(p,summary,raw,1,lambda _:_answer(5,'kg',None))
    assert p[0]['unit_material_cost_gbp']==120  # 12 pieces x 2kg x GBP5, not 1 x 2kg
    assert p[1]['quantity']==1 and raw[1]['quantity']==1


def test_private_saved_wall_evidence_recovers_without_running_a_job():
    fixture=os.getenv('HC_COMPLETION_FIXTURE')
    if not fixture:pytest.skip('private saved evidence supplied separately')
    from owned_component_manufacturing import prepare
    from wb_populate import _bom_line_price
    from subcontract_cost_completion import complete_subcontract_costs
    data=json.loads(Path(fixture).read_text(encoding='utf-8'))
    for source in data['walls']:
        summary=copy.deepcopy(source['owned_summary']);prepare(summary)
        by={p['part_number']:p for p in summary['manufacturing_writeup']['parts']}
        pusher=by[data['pusher']]
        assert pusher['repeat_supply_basis']['article']==data['article']
        assert '372 CRITICAL' in pusher['price_chain_description']
        for code,length in data['tube_lengths'].items():
            if code in by:
                assert by[code]['section_stock']['length_mm']==length
        priced=copy.deepcopy(source['costed_parts'])
        assert complete_subcontract_costs(priced,summary,summary['manufacturing_writeup']['parts'],1,
            lambda brief:_answer(80,'order',None) if brief['kind']=='commercial' else _answer())==2
        resolved=[p for p in priced if p.get('_plating_placeholder') or p.get('_plater_freight')]
        assert all(_bom_line_price(p)>0 for p in resolved)
        plate=next(p for p in resolved if p.get('_plating_placeholder'))
        contributions={c['part']:c for c in plate['subcontract_mass_basis']['contributions']}
        assert contributions['D-33492']['qty_per_product']==150
        assert contributions['E-33488']['qty_per_product']==120
        assert source['protected_quantities']==data['protected_quantities']
        # Expand an in-memory copy of the actual finished workbook. No source save.
        import io
        from wb_populate import CELL_MAP,labour_sheet_coverage,repair_labour_sheet_references
        from workbook_labour_capacity import ensure_labour_capacity
        book_path=Path(source['book'])
        if not book_path.is_absolute():book_path=Path(fixture).parent/book_path
        book=openpyxl.load_workbook(io.BytesIO(book_path.read_bytes()))
        sheet=book['Estimate'];labels={str(sheet.cell(r,3).value or '').strip().lower():r for r in range(1,sheet.max_row+1)}
        first=labels['operation']+1;last=next(r for label,r in labels.items() if label.startswith('total labour cost'))-1
        cm=copy.deepcopy(CELL_MAP);cm['labour'].update(first_row=first,last_row=last)
        required=last-first+1+source['omitted_groups']
        assert ensure_labour_capacity(book,cm,required)>0
        repair_labour_sheet_references(book,cm)
        assert labour_sheet_coverage(book,cm)['ok']
