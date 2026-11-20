"""No production identifiers or private records are embedded in these controls."""
import copy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pytest
import part_identity as pi
import route_compiler as rc
from source_connectors import solidworks as sw
from source_connectors.llm_full_job import apply_full_job_to_pre_estimate


@pytest.mark.parametrize('suffix', ['101','01M','GA'])
def test_subassembly_number_is_not_a_job_number_typo(suffix):
    a,b=f'50005-05-{suffix}',f'50005-06-{suffix}'
    assert pi.one_digit_apart(a,b) is None
    assert pi.corroborated_near_code(a,'HOLDER WELD ASSY',
        {b:'HOLDER WELD ASSY'},[a,'50005-05-02M']) is None


def test_leading_job_reference_typo_still_has_its_existing_guarded_repair():
    assert pi.corroborated_near_code('UPC0358131 M7','BASE END CAP',
        {'UPC0358141M7':'BASE END CAP'},['UPC0358141M4'])=='UPC0358141M7'


def test_one_assembly_cannot_take_the_other_assemblys_facts():
    part={'part_number':'50005-05-101','description':'HOLDER WELD ASSY','quantity':1}
    sibling={'part_number':'50005-05-01M','description':'ARM','quantity':1}
    job={'found':True,'parts':[{'part_number':'50005-06-101',
         'description':'HOLDER WELD ASSY','material':'STAINLESS STEEL','thickness_mm':8}],
         'assemblies':[],'bom':[],'routes':[],'drawing_info':{}}
    apply_full_job_to_pre_estimate([part,sibling],job)
    assert not part.get('normalized_thickness_mm')
    assert not any('taken as ONE' in str(x) for x in part.get('review_flags',[]))


def setup_model():
    root,parent='50005-00-GA','50005-02-101'
    cap,wool='50005-05-GA','50005-06-GA'
    capw,woolw='50005-05-101','50005-06-101'
    a,b='50005-05-01M','50005-06-01M'
    hierarchy={root:[(parent,3)],parent:[(cap,3),(wool,3)],
               cap:[(capw,1)],wool:[(woolw,1)],capw:[(a,1)],woolw:[(b,1)]}
    totals={parent:3,cap:6,wool:3,capw:6,woolw:3,a:6,b:3}
    job=sw.NativeJob(found=True,
        bom=[sw.NativeBomRow(part_number=k,quantity=v,is_assembly=k in hierarchy)
             for k,v in totals.items()],hierarchy=hierarchy,
        assembly_pns=list(hierarchy),meta={'top_assembly':root})
    # Missing GA records reproduce assemblies minted AFTER native quantity read.
    parts=[{'part_number':k,'quantity':1,'description':'HOLDER WELD ASSY' if k in (capw,woolw) else k}
           for k in (root,parent,capw,woolw,a,b)]
    extract={'top_assembly':root,'assemblies':[
        {'part_number':root,'children':[{'part_number':parent,'qty':3}]},
        {'part_number':parent,'children':[{'part_number':cap,'qty':6}]},
        {'part_number':cap,'children':[{'part_number':capw,'qty':1}]},
        # AI flattened the wool holder, omitting its weldment and its ownership.
        {'part_number':wool,'children':[{'part_number':b,'qty':1}]}]}
    return parts,job,extract


def test_minted_parents_receive_model_count_and_source_without_reprocessing_overrides():
    parts,job,extract=setup_model()
    parts[1].update(quantity=4,quantity_source='estimator_confirmed')
    sw.apply_native_to_pre_estimate(parts,job)
    sw.apply_native_hierarchy_to_parts(parts,job)
    p={x['part_number']:x for x in parts}
    assert p['50005-05-GA']['quantity']==2
    assert p['50005-05-GA']['quantity_total_per_unit']==6
    assert p['50005-06-GA']['quantity']==1
    assert p['50005-06-GA']['quantity_total_per_unit']==3
    assert p['50005-05-GA']['quantity_source']=='solidworks_api'
    assert p['50005-02-101']['quantity']==4


def test_incomplete_ai_tree_cannot_hide_a_native_product_branch():
    parts,job,extract=setup_model()
    sw.apply_native_to_pre_estimate(parts,job)
    sw.apply_native_hierarchy_to_parts(parts,job)
    def graph():
        return rc.build_part_graph(parts,extract,known_assemblies=job.assembly_pns,
                                   declared_product='50005-00-GA')
    q=graph()['quantities']
    assert {k:q[k] for k in ('50005-05-GA','50005-05-101','50005-06-GA','50005-06-101')}=={
        '50005-05-GA':6,'50005-05-101':6,'50005-06-GA':3,'50005-06-101':3}
    assert q['50005-05-01M']==6 and q['50005-06-01M']==3
    # Applying hierarchy twice neither duplicates records nor changes counts.
    before=copy.deepcopy(q)
    sw.apply_native_hierarchy_to_parts(parts,job)
    assert graph()['quantities']==before
    assert len({p['part_number'] for p in parts})==len(parts)


def test_description_inferred_edges_do_not_gain_native_authority():
    parts,job,extract=setup_model()
    sw.apply_native_to_pre_estimate(parts,job)
    sw.apply_native_hierarchy_to_parts(parts,job)
    for p in parts:
        p['native_assembly_children_source']='inference'
    g=rc.build_part_graph(parts,extract,known_assemblies=job.assembly_pns,
                          declared_product='50005-00-GA')
    assert '50005-06-101' not in g['quantities']
