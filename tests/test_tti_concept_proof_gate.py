"""Additional integration guards. Fake service only; no live runs or deployments."""
import json
from pathlib import Path
import sys
from xml.sax.saxutils import escape

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from test_tti_concept_batch import fixture,mutate,setup,FakeAPI,run
import tti_concept_batch as batch
import tti_concept_inputs as inp
import tti_concept_proof as proof


@pytest.mark.parametrize('switch',['--assume-missing-quantity-one','--blank-quantity-as-one'])
def test_both_quantity_switches_are_identical_and_default_proof_is_6_12(switch):
    a=batch.argument_parser().parse_args(['--sheet','tracker.xlsx','--plan-output','plan.json',switch])
    assert a.assume_missing_quantity_one and a.proof_rows=='6,12'
    assert not a.execute and not a.approve_proof


@pytest.mark.parametrize('value',['TBC','unknown count','four','#VALUE!','#N/A','#DIV/0!','NaN','Infinity'])
def test_unreadable_quantity_is_one_with_explicit_source_and_reason(tmp_path,value):
    path=fixture(tmp_path/'b.xlsx',rows=[(3,'Assumed',2,'')])
    mutate(path,'xl/worksheets/sheet1.xml',lambda b:b.replace(b'<c r="N3"><v>2</v></c>',
        f'<c r="N3" t="inlineStr"><is><t>{escape(value)}</t></is></c>'.encode()))
    strict,_=inp.read_plan(path)
    assert strict['rows'][0]['state']=='held: quantity'
    plan,pics=inp.read_plan(path,assume_missing_quantity_one=True)
    item=plan['rows'][0]
    assert item['quantity']==1 and item['source_quantity']==value and item['quantity_assumed']
    assert item['quantity_assumption_reason'] and 'QUANTITY ASSUMPTION' in item['brief']
    assert value in item['brief']
    archive=batch.Archive(tmp_path/'C',tmp_path/'K'); api=FakeAPI()
    assert run(plan,pics,archive,api)==0
    assert api.posts[0]['units']==1
    new,_=inp.read_plan(path,assume_missing_quantity_one=True)
    assert new['rows'][0]['source_quantity']==value  # Never overwrite N.
    audit=batch.read_json(archive.roots[0]/item['reference']/'results'/'price-for-writeback.json')
    assert audit['quantity_assumption_reason']==item['quantity_assumption_reason']


def test_real_excel_error_type_is_one_not_silently_zero(tmp_path):
    path=fixture(tmp_path/'b.xlsx',rows=[(3,'Assumed',2,'')])
    mutate(path,'xl/worksheets/sheet1.xml',lambda b:b.replace(b'<c r="N3"><v>2</v></c>',b'<c r="N3" t="e"><v>#VALUE!</v></c>'))
    plan,_=inp.read_plan(path,assume_missing_quantity_one=True)
    assert plan['rows'][0]['quantity']==1 and plan['rows'][0]['source_quantity']=='#VALUE!'


@pytest.mark.parametrize('value',[-1,1.5])
def test_readable_wrong_numeric_count_still_held(tmp_path,value):
    path=fixture(tmp_path/'b.xlsx',rows=[(3,'Invalid count',value,'')])
    plan,_=inp.read_plan(path,assume_missing_quantity_one=True)
    assert plan['rows'][0]['state']=='held: quantity' and not plan['rows'][0]['quantity_assumed']


def three_rows(tmp_path):
    return setup(tmp_path,[(3,'Image pilot',2,''),(4,'Description pilot',3,''),(5,'Remaining',4,'')])


def pilot(tmp_path):
    path,plan,pics,archive,api=three_rows(tmp_path)
    assert run(plan,pics,archive,api,selected_rows=[3,4],proof_rows=(3,4))==0
    return path,plan,pics,archive,api


def test_full_batch_cannot_start_without_proof(tmp_path):
    _,plan,pics,archive,api=three_rows(tmp_path)
    with pytest.raises(RuntimeError,match='PROOF NOT APPROVED'): run(plan,pics,archive,api,proof_rows=(3,4))
    assert not api.posts


def test_proof_exit_zero_is_not_approval(tmp_path):
    _,plan,pics,archive,api=pilot(tmp_path)
    with pytest.raises(RuntimeError,match='PROOF NOT APPROVED'): run(plan,pics,archive,api,proof_rows=(3,4))
    assert len(api.posts)==2


def test_explicit_review_after_all_checks_allows_only_remainder(tmp_path):
    path,plan,pics,archive,api=pilot(tmp_path)
    current,_=inp.read_plan(path)
    report=proof.approve_proof(archive,current,(3,4))
    assert report['decision']=='PASS' and len(api.posts)==2
    assert run(current,pics,archive,api,proof_rows=(3,4))==0
    assert len(api.posts)==3  # The two pilot runs are NOT repeated.
    again,_=inp.read_plan(path)
    assert run(again,pics,archive,api,proof_rows=(3,4))==0 and len(api.posts)==3


def test_arbitrary_pass_marker_cannot_unlock_remainder(tmp_path):
    _,plan,pics,archive,api=pilot(tmp_path)
    archive.put(proof.APPROVAL,b'{"decision":"PASS"}')
    with pytest.raises(RuntimeError,match='PROOF NOT APPROVED'): run(plan,pics,archive,api,proof_rows=(3,4))
    assert len(api.posts)==2


@pytest.mark.parametrize('fault',['image','record','workbook','cost','row','one_root_approval','wrong_run','failed_proof'])
def test_tampered_missing_stale_or_failed_evidence_cannot_start_remainder(tmp_path,fault):
    path,plan,pics,archive,api=pilot(tmp_path)
    proof.approve_proof(archive,plan,(3,4))
    first=plan['rows'][0]; base=archive.roots[0]/first['reference']
    if fault=='image': next((base/'inputs').glob('*.png')).write_bytes(b'wrong picture')
    elif fault=='record': (base/'results'/'result_record.json').write_text('{"quantity":999}')
    elif fault=='workbook': (base/'results'/'result.xlsx').unlink()
    elif fault=='cost': mutate(path,'xl/worksheets/sheet1.xml',lambda b:b.replace(b'<v>12.34</v>',b'<v>9.99</v>'))
    elif fault=='row': mutate(path,'xl/worksheets/sheet1.xml',lambda b:b.replace(b'Image pilot',b'Different fixture'))
    elif fault=='one_root_approval': (archive.roots[1]/proof.APPROVAL).unlink()
    elif fault in ('wrong_run','failed_proof'):
        state=batch.read_json(archive.roots[0]/'state.json')
        state['entries'][first['reference']].update({'run_id':'a'*12} if fault=='wrong_run' else {'phase':'held'})
        archive.state(state)
    with pytest.raises((RuntimeError,ValueError)):
        run(plan,pics,archive,api,proof_rows=(3,4))
    assert len(api.posts)==2


def test_cannot_approve_failed_or_incomplete_pilot(tmp_path):
    _,plan,pics,archive,api=three_rows(tmp_path); api.failure=True
    assert run(plan,pics,archive,api,selected_rows=[3,4],proof_rows=(3,4))==4, 'the failed pilots are held, not a crash'
    with pytest.raises(ValueError): proof.approve_proof(archive,plan,(3,4))
    assert not (archive.roots[0]/proof.APPROVAL).exists()


def test_approval_checks_image_and_description_types(tmp_path):
    path,plan,pics,archive,api=setup(tmp_path,[(3,'One',2,''),(4,'Description',3,''),(5,'Description2',4,'')])
    assert run(plan,pics,archive,api,selected_rows=[4,5])==0
    with pytest.raises(ValueError,match='one image row'): proof.approve_proof(archive,plan,(4,5))


def test_approval_mode_cannot_be_combined_with_execution(tmp_path):
    with pytest.raises(SystemExit) as exc:
        batch.main(['--sheet','never-open.xlsx','--plan-output',str(tmp_path/'plan.json'),'--approve-proof','--execute'])
    assert exc.value.code==2


def test_cli_execute_always_supplies_proof_gate(tmp_path,monkeypatch):
    path=fixture(tmp_path/'b.xlsx')
    monkeypatch.setitem(sys.modules,'dotenv',type('D',(),{'load_dotenv':staticmethod(lambda *a,**k:None)}))
    monkeypatch.setattr(batch.subprocess,'check_output',lambda args,**kw:'abcdef12' if 'rev-parse' in args else '')
    # Test only argument plumbing; no real network/share/claim or service is touched.
    monkeypatch.setattr(batch.Path,'is_dir',lambda self:True)
    from contextlib import nullcontext
    monkeypatch.setattr(batch,'exclusive_claim',lambda *a:nullcontext())
    seen={}
    def capture(*a,**kw): seen.update(kw); return 0
    monkeypatch.setattr(batch,'run_batch',capture)
    assert batch.main(['--sheet',str(path),'--plan-output',str(tmp_path/'plan.json'),
                       '--execute','--shared-root',r'\\test\share','--expected-build','abcdef12',
                       '--blank-quantity-as-one'])==0
    assert seen['proof_rows']==(6,12)


def test_approval_for_old_build_does_not_unlock_new_build(tmp_path):
    _,plan,pics,archive,api=pilot(tmp_path)
    proof.approve_proof(archive,plan,(3,4),expected_build='abcdef12')
    api.runners=lambda:[{'online':True,'runner_id':str(i),'build':'12345678','process_count':1,'conflict':False} for i in (1,2)]
    with pytest.raises(RuntimeError,match='requested build'):
        batch.run_batch(plan,pics,archive,api,'12345678',proof_rows=(3,4),sleep=lambda _:None)
    assert len(api.posts)==2
