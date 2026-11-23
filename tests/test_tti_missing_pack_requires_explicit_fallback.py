from argparse import Namespace
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import tti_pricer as tp

@pytest.mark.parametrize('drawing',['12806-00-GA','12802-00-GA1','12802-00-GA2','12803-00-GA'])
def test_four_real_references_do_not_silently_become_concepts(drawing):
    assert tp.drawing_pack_required(drawing,None,Namespace())

def test_only_explicit_fallback_can_permit_a_named_drawing_without_pack():
    args=Namespace(allow_drawing_reference_fallback=True,drawings_only=False)
    assert not tp.drawing_pack_required('12806-00-GA',None,args)

def test_drawings_only_cannot_be_overridden_by_fallback_switch():
    args=Namespace(allow_drawing_reference_fallback=True,drawings_only=True)
    assert tp.drawing_pack_required('12806-00-GA',None,args)

def test_real_manifest_does_not_trigger_missing_pack_guard():
    assert not tp.drawing_pack_required('12806-00-GA',{'status':'provisional'},Namespace())

def test_description_only_rows_keep_existing_concept_route():
    assert not tp.drawing_pack_required('',None,Namespace())

def test_explicit_authorisation_is_exposed_and_off_by_default():
    parser=tp.build_parser()
    assert not parser.parse_args(['--sheet','fixture.xlsx']).allow_drawing_reference_fallback
    assert parser.parse_args(['--sheet','fixture.xlsx','--allow-drawing-reference-fallback']).allow_drawing_reference_fallback

def test_failed_direct_lookup_keeps_its_reason(monkeypatch):
    import pack_resolver
    monkeypatch.setattr(tp,'_DIRECT',[True])
    monkeypatch.setattr(pack_resolver,'rows_for_job_now',lambda *a:([], 'Design: job exists, no exact drawing; Prototype: no folder', set()))
    assert tp.pack_for('12806-00-GA',[],'TTI')==({},None)
    assert 'Design: job exists' in tp._PACK_LOOKUP_NOTES['12806-00-GA']

@pytest.mark.parametrize('existing_cost',[None,413.74])
def test_real_batch_holds_missing_pack_without_post_write_or_history_change(tmp_path,monkeypatch,existing_cost):
    from copy import deepcopy
    drawing='12802-00-GA1'
    row={'row':43,'drawing':drawing,'drawing_cell':drawing,'quantity':2,
         'description':'Demo station','notes':'','feedbacks':[], 'pictures':[], 'cost_before':existing_cost}
    data={'rows':[row],'sheet':'Milwaukee','header_row':1,'header':{}}
    old={'43':{'row':43,'drawing':drawing,'state':'done','run_id':'retained-run',
               'unit_cost':413.74,'written':'P43=413.74'}} if existing_cost else {}
    before=deepcopy(old)
    args=tp.build_parser().parse_args(['--sheet',str(tmp_path/'fixture.xlsx'),'--rows','43'])
    monkeypatch.setattr(tp,'read_rows',lambda *a,**k:data)
    monkeypatch.setattr(tp,'batch_roots',lambda:(tmp_path,tmp_path))
    monkeypatch.setattr(tp,'inputs_root',lambda:tmp_path/'inputs')
    monkeypatch.setattr(tp,'load_ledgers',lambda *a:(old,[]))
    monkeypatch.setattr(tp,'pack_for',lambda *a:({},None))
    monkeypatch.setattr(tp,'find_drawings',lambda *a:{})
    monkeypatch.setattr(tp,'SheetWriter',lambda *a:Namespace(how='test-no-writes',backup=None))
    class NoPosts:
        def start(self,*a,**k):raise AssertionError('must not submit')
    result=tp.run_batch(args,portal=NoPosts(),status_path=tmp_path/'status.json',sleep=lambda _:None)
    assert result['rows'][0]['state']=='needs drawing'
    assert result['rows'][0]['kind']=='not priced (drawing pack unresolved)'
    assert old==before
    assert not (tmp_path/'fixture.xlsx').exists(), 'no workbook write'
