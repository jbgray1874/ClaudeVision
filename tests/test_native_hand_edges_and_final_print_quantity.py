"""Generic regressions: model-only hands and setup at the final BOM quantity."""
import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import route_compiler as rc
import print_costing as pc
import wb_populate as wb
from source_connectors import solidworks as sw

ROOT, SUB, BASE, HAND = '50009-00-GA', '50009-02-101', '50009-02-01X', '50009-02-01X-HANDED'

def model_case(root_total=6, model_root=ROOT):
    parts = [{'part_number': p, 'quantity': q, 'description': d} for p,q,d in
             [(ROOT,1,'PRODUCT'), (SUB,3,'MODULE'), (BASE,6,'LED SET UP'), (HAND,6,'LED STRIP')]]
    job = sw.NativeJob(found=True,
        bom=[sw.NativeBomRow(part_number=SUB, quantity=3, is_assembly=True),
             sw.NativeBomRow(part_number=BASE, quantity=6, is_assembly=True),
             sw.NativeBomRow(part_number='Mirror'+BASE, quantity=6)],
        hierarchy={ROOT:[(SUB,3)], SUB:[(BASE,2)], BASE:[('Mirror'+BASE,1)]},
        assembly_pns=[ROOT,SUB,BASE], meta={'top_assembly':model_root})
    rows = [{'part_number':c, 'quantity':q, 'bom_parent':p, 'bom_sheet':p+'.PDF#0'}
            for p,c,q in [(ROOT,SUB,3),(ROOT,BASE,root_total),(ROOT,HAND,6),(SUB,BASE,2)]]
    sw.apply_native_to_pre_estimate(parts, job)
    sw.apply_native_hierarchy_to_parts(parts, job)
    return parts,job,rows

def graph_case(**kw):
    parts,job,rows=model_case(**kw)
    extract={'assemblies':[{'part_number':owner,'children':[
        {'part_number':r['part_number'],'qty':r['quantity']} for r in rows if r['bom_parent']==owner]}
        for owner in (ROOT,SUB)]}
    graph=rc.build_part_graph(parts, extract, rows, job.assembly_pns, declared_product=ROOT)
    return parts,graph,{n.part_number:n for n in graph['nodes']}

def test_edge_only_mirror_has_one_identity_six_of_each_no_self_child():
    _,g,n=graph_case()
    assert g['quantities'][BASE] == 6
    assert g['quantities'][HAND] == 6
    assert 'MIRROR'+BASE not in n
    assert all(e.part_number != p for p,node in n.items() for e in node.children)
    assert n[HAND].evidence['raw_aliases'] == ['MIRROR'+BASE]

def test_each_printed_purchase_is_not_free_assembly_overhead():
    _,_,n=graph_case()
    assert n[BASE].kind == n[HAND].kind == 'bought_in'
    assert n[BASE].evidence['purchased_mirror_peer']

@pytest.mark.parametrize('kwargs', [{'root_total':7}, {'model_root':'50010-00-GA'}])
def test_no_assembly_dedup_without_matching_product_total(kwargs):
    _,g,n=graph_case(**kwargs)
    assert g['quantities'][BASE] > 6
    assert n[BASE].kind == 'assembly'

def test_native_scalar_keeps_its_parent_scope():
    parts,_,_=model_case()
    hand=next(p for p in parts if p['part_number']==HAND)
    assert hand['quantity']==1
    assert hand['quantity_parent_scope']==BASE

def test_purchase_classification_reaches_the_pre_cost_records():
    parts,job,rows=model_case()
    rc.apply_canonical_evidence_to_parts(parts,{},rows,job.assembly_pns,summary={'declared_product':ROOT})
    for p in parts:
        if p['part_number'] in (BASE,HAND):
            assert p['canonical_kind']=='bought_in'
            assert not p['is_assembly_parent']
            assert not p['is_sub_assembly']
            assert p['is_bought_in']

def test_human_quantity_is_not_replaced_by_native_scope():
    from source_precedence import apply_field
    parts,job,rows=model_case()
    hand=next(p for p in parts if p['part_number']==HAND)
    apply_field(hand,'quantity',2,'estimator_confirmed')
    sw.apply_native_to_pre_estimate(parts,job)
    assert hand['quantity']==2

def test_capacity_words_do_not_multiply_a_purchase_quantity():
    root,drawer='50011-00-GA','50011-01-103'
    parts=[{'part_number':root},{'part_number':drawer,'quantity':10},
           {'part_number':'Charging Module x 16 Devices','quantity':3,'is_bought_in':True},
           {'part_number':'Dock PSU - GUESS','quantity':3,'is_bought_in':True}]
    extract={'assemblies':[{'part_number':root,'children':[{'part_number':drawer,'qty':10}]},
        {'part_number':drawer,'children':[{'part_number':p['part_number'],'qty':3} for p in parts[2:]]}]}
    g=rc.build_part_graph(parts,extract,known_assemblies=[root,drawer],declared_product=root)
    purchases=[n for n in g['nodes'] if 'MODULE' in n.part_number or 'PSU' in n.part_number]
    assert len(purchases)==2
    assert all(n.qty_per_unit==30 for n in purchases)

def printed(qty=6):
    return {'part_number':'50009-02-05G', 'quantity':qty, 'page_roles':['bought_in'],
        'source':pc.SOURCE_KEY, 'cost_source':pc.SOURCE_KEY,
        'unit_cost_gbp':15.5, 'unit_total_cost_gbp':15.5,
        'material_estimate':{'cost_method':'bought_in_recognised_price:'+pc.SOURCE_KEY},
        'print_calculator':{'applied':True,'workable':True,'qty_per_unit':2,'order_qty':1,
           'run_cost_per_sheet_gbp':100.,'parts_per_sheet':40,'scrap':.2,'setup_gbp':30.,
           'total_gbp':18.,'setup_share_gbp':15.,'quantity_printed':2}}

@pytest.mark.parametrize('qty,order', [(6,1),(6,2),(1,10),(2,1)])
def test_final_population_has_one_setup_and_no_second_scrap(qty,order):
    before=printed(qty); saved=copy.deepcopy(before)
    result=pc.rebase_applied_price(before,order)
    assert result['unit_cost_gbp']*qty*order == pytest.approx(3*qty*order+30)
    assert result['print_calculator']['quantity_printed']==qty*order
    assert result['material_estimate']['extended_material_cost_gbp']==pytest.approx(result['unit_cost_gbp']*qty)
    assert wb.waste_already_in_price(result)
    assert result==pc.rebase_applied_price(result,order)
    assert before==saved

def test_declined_calculator_and_catalogue_price_not_changed():
    p=printed();p['print_calculator']['applied']=False;p['source']='catalogue'
    assert pc.rebase_applied_price(p,1) is p

@pytest.mark.parametrize('field,value', [('quantity',0),('quantity',float('nan')),('source','catalogue')])
def test_invalid_applied_provenance_or_quantity_fails_closed(field,value):
    p=printed();p[field]=value
    if field=='source':p['cost_source']='catalogue'
    with pytest.raises(ValueError):pc.rebase_applied_price(p,1)

def test_writer_rebases_after_its_quantity_adapter(monkeypatch):
    p=printed(2);pn=p['part_number']
    payload={'nodes':[{'part_number':pn,'kind':'bought_in','qty_per_unit':6}], 'issues':[]}
    monkeypatch.setattr(wb,'canonical_route_payload',lambda s:payload)
    result=wb.canonicalise_part_estimates_for_workbook({'assumed_job_quantity':2},[p])
    line=next(x for x in result if x['part_number']==pn)
    assert line['quantity']==6
    assert line['unit_cost_gbp']*12==pytest.approx(66)
    assert line['print_calculator']['quantity_printed']==12
