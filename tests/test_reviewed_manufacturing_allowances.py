import copy
import pytest
from reviewed_manufacturing_allowances import add
from route_compiler import compile_route_without_pricing

def fixture():
    summary={'declared_product':'B.12345','manufacturing_writeup':{'parts':[
        {'part_number':'B.12345','quantity':1,'description':'counter carcase'}]},'pages':[]}
    decision={'schema':'estimating_allowances.v1','drawing':'B.12345','members':[
        {'parent':'B.12345','description':'Provisional folded stainless skin','material':'STAINLESS_STEEL',
         'length_mm':1360,'width_mm':1360,'thickness_mm':1.5,'qty':2,'folds':4,
         'operations':['laser_cutting','folding','welding','dress_welds','polishing'],
         'basis':'1200 square top plus four 80 mm returns. 1.5 mm gauge assumed for budgeting.'}]}
    return summary,decision

def test_material_and_fabrication_allowances_are_real_route_inputs_not_just_notes():
    s,d=fixture()
    assert add(s,d)==['B.12345-ALW01']
    p=s['manufacturing_writeup']['parts'][1]
    assert p['quantity']==2 and p['blank_length_mm']==1360 and p['normalized_thickness_mm']==1.5
    route=compile_route_without_pricing(s)
    required={x['operation'] for x in route['decisions'] if x['status']=='required'
              and (x.get('target_id')=='B.12345-ALW01' or 'B.12345-ALW01' in x.get('participants',[]))}
    assert {'laser_cutting','folding','welding','dress_welds','polishing'}<=required
    assert route['mode']=='uncosted' and route['priced_route_rows']==[]
    assert add(s,d)==[]

def test_allowances_never_duplicate_an_existing_cut_list_or_another_job():
    s,d=fixture()
    s['manufacturing_writeup']['parts'].append({'part_number':'drawn-panel','bom_parent':'B.12345'})
    with pytest.raises(ValueError,match='already has component detail'):add(s,d)
    s,d=fixture();d['drawing']='B.99999'
    with pytest.raises(ValueError,match='does not match'):add(s,d)
    s,d=fixture();s['manufacturing_writeup']['parts'][0]['supplied_by_third_party']=True
    with pytest.raises(ValueError,match='by-others'):add(s,d)


def test_joinery_allowance_carries_edging_and_joinery_work_without_becoming_a_measured_cut_list():
    s,d=fixture();m=d['members'][0]
    m.update(material='MDF',thickness_mm=18,folds=0,
        operations=['cnc_routing','hole_machining','edge_banding','glue','assembly'],
        edge_basis='all four edges allowed provisionally; confirm visible edges',
        cutouts=[{'what':'hole','count':4,'length_mm':5,'width_mm':5}])
    add(s,d)
    p=s['manufacturing_writeup']['parts'][1]
    assert p['concept_banded_edges']==m['edge_basis']
    assert p['manufacturing_features']['hole_count']==4
    route=compile_route_without_pricing(s)
    required={x['operation'] for x in route['decisions'] if x['status']=='required'}
    assert {'cnc_routing','edge_banding','glue','assembly'}<=required
    assert p['provisional_allowance']['basis']==m['basis']

@pytest.mark.parametrize('field,value',[('basis',''),('qty',float('nan')),('operations',['made_up']),('folds',0)])
def test_incomplete_allowance_decisions_are_not_silently_partly_applied(field,value):
    s,d=fixture();before=copy.deepcopy(s)
    bad=copy.deepcopy(d['members'][0]);bad[field]=value;d['members'].append(bad)
    with pytest.raises(ValueError):add(s,d)
    assert s==before
