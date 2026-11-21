"""Isolated regression tests: no production settings, shares, jobs or network."""
import ast
import builtins
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'sdi-intelligence-backend'))
import brief_renderer as renderer
import tti_concept_batch as batch
import tti_concept_reconcile as rec
from test_tti_concept_batch import setup, run
from test_a_brief_alone_is_a_pack import staging, er


def test_service_manifest_declares_its_own_renderer():
    text=(ROOT/'sdi-intelligence-backend/requirements.txt').read_text()
    assert 'PyMuPDF>=1.24.3,<2.0' in text


def test_release_checks_service_python_before_push_or_restart():
    text=(ROOT/'tools/start/publish-and-restart.ps1').read_text(encoding='utf-8')
    assert 'sdi-intelligence-backend\\.venv\\Scripts\\python.exe' in text
    assert text.index('Step "service description-only renderer') < text.index('Step "push the portal branch')
    assert '& $servicePython -B' in text and 'tools\\check_service_brief_renderer.py' in text


def test_real_service_route_returns_503_and_creates_no_run(er,monkeypatch,tmp_path):
    from fastapi import HTTPException
    def fail(name): raise ModuleNotFoundError('pymupdf')
    monkeypatch.setattr(renderer.importlib,'import_module',fail)
    old_import=builtins.__import__
    def without_pdf(name,*args,**kw):
        if name=='pymupdf': raise ModuleNotFoundError('pymupdf')
        return old_import(name,*args,**kw)
    monkeypatch.setattr(builtins,'__import__',without_pdf)
    request=er.EstimateRequest(client='TEST',drawing_number='TEST-CONCEPT-01',units=2,
            method='llm',files=[],enquiry_brief='Two panels, 300 x 600 mm.',email_to='')
    with pytest.raises(HTTPException) as err:
        er.start(request,x_sdi_key='portal-key')
    assert err.value.status_code==503 and err.value.detail['accepted'] is False
    assert not er._RUNS and not list((tmp_path/'stage').rglob('*'))


def test_private_actual_failed_description_request_renders_without_submission():
    root=os.getenv('SDI_TTI_FAILED_PROOF_ARCHIVE')
    if not root: pytest.skip('Private actual failed proof archive not supplied')
    root=Path(root); state=batch.read_json(root/'state.json')
    pairs=[(ref,e) for ref,e in state['entries'].items() if e.get('row')==6]
    assert len(pairs)==1
    ref,entry=pairs[0]
    assert entry['phase']=='submitting' and not entry.get('run_id')
    request=batch.read_json(root/ref/'inputs/request.json')
    assert request['units']==2 and request['files']==[] and request['method']=='llm'
    png=renderer.render_brief_png(request['enquiry_brief'])
    assert png.startswith(b'\x89PNG\r\n\x1a\n') and len(png)>1000


@pytest.mark.parametrize('failure',[ModuleNotFoundError('pymupdf'),ImportError('DLL unavailable'),OSError('DLL unavailable')])
def test_dependency_missing_has_actionable_error(failure,monkeypatch):
    def missing(name): raise failure
    monkeypatch.setattr(renderer.importlib,'import_module',missing)
    with pytest.raises(renderer.BriefRendererUnavailable,match='SERVICE virtualenv'):
        renderer.render_brief_png('two panels')


def test_actual_renderer_makes_readable_png():
    import pymupdf
    data=renderer.render_brief_png('Two panels, 300 x 600 mm, quantity 2.')
    assert data.startswith(b'\x89PNG\r\n\x1a\n') and len(data)>1000
    with pymupdf.open(stream=data,filetype='png') as doc:
        assert doc.page_count==1 and doc[0].rect.width>590


def test_missing_dependency_cannot_clear_existing_pack(staging,monkeypatch,tmp_path):
    folder=tmp_path/'existing'; folder.mkdir(); (folder/'keep.pdf').write_bytes(b'original')
    monkeypatch.setattr(staging,'job_folder_for',lambda *a:folder)
    monkeypatch.setattr(renderer,'render_brief_png',lambda text:(_ for _ in ()).throw(renderer.BriefRendererUnavailable('missing SERVICE virtualenv renderer')))
    with pytest.raises(staging.StagingDependencyError):
        staging.stage_brief_only(client='TEST',drawing='TEST-01',brief='description')
    assert list(folder.iterdir())==[folder/'keep.pdf'] and (folder/'keep.pdf').read_bytes()==b'original'


def test_oversized_brief_is_not_silently_empty():
    with pytest.raises(ValueError,match='does not fit'):
        renderer.render_brief_png('many words '*30000)


def test_route_translates_dependency_failure_to_503_before_run_creation():
    # Execute the ACTUAL staging try/except AST, no FastAPI import or startup.
    tree=ast.parse((ROOT/'sdi-intelligence-backend/estimate_routes.py').read_text(encoding='utf-8'))
    start=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='start')
    block=next(n for n in ast.walk(start) if isinstance(n,ast.Try) and
               any(isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and
                   x.func.attr=='stage_brief_only' for statement in n.body for x in ast.walk(statement)))
    class DependencyError(Exception): pass
    class HTTP(Exception):
        def __init__(self,status,detail): self.status_code=status; self.detail=detail
    def fail(**kw): raise DependencyError('missing renderer')
    namespace={'_brief_only':True,'client':'TEST','drawing':'TEST-01',
               'req':types.SimpleNamespace(enquiry_brief='two panels'),
               'HTTPException':HTTP,'staging':types.SimpleNamespace(
                    stage_brief_only=fail,StagingDependencyError=DependencyError,
                    StagingInUse=type('InUse',(Exception,),{}),StagingError=type('StagingError',(Exception,),{}))}
    with pytest.raises(HTTP) as err:
        exec(compile(ast.fix_missing_locations(ast.Module(body=[block],type_ignores=[])),'route-stage','exec'),namespace)
    assert err.value.status_code==503 and err.value.detail['accepted'] is False
    assert err.value.detail['code']=='brief_renderer_unavailable'
    create=next(x for x in ast.walk(start) if isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='Run')
    assert block.lineno<create.lineno


class ReadClient:
    server='test'
    def __init__(self,runs=None): self.runs=runs or []; self.calls=[]
    def request(self,method,path):
        assert method=='GET'; self.calls.append((method,path)); return {'runs':self.runs}


def uncertain(tmp_path):
    path,plan,pics,archive,api=setup(tmp_path,[(3,'Image proof',2,''),(4,'Description proof',3,'')])
    api.fail_post=True
    with pytest.raises(TimeoutError): run(plan,pics,archive,api,selected_rows=[4],proof_rows=(3,4))
    item=plan['rows'][1]
    history=tmp_path/'history'; history.mkdir()
    (history/'old.json').write_text(json.dumps({'run_id':'old000000001','drawing_number':'OTHER','status':'done'}))
    client=ReadClient(); client.server=api.server
    return path,plan,pics,archive,item,history,client


def review(a,item,h,c): return rec.audit(a,item['row'],h,[c])


def test_read_only_audit_preserves_state_and_workbook(tmp_path):
    path,_,_,a,item,h,c=uncertain(tmp_path)
    before=[(r/'state.json').read_bytes() for r in a.roots]; wb=path.read_bytes()
    report=review(a,item,h,c)
    assert not report['matching_runs'] and not report['state_changed'] and report['jobs_submitted']==0
    assert [(r/'state.json').read_bytes() for r in a.roots]==before and path.read_bytes()==wb
    assert all(m=='GET' for m,p in c.calls)


def test_retire_only_after_explicit_ruling_preserves_attempt_and_cannot_unlock_remainder(tmp_path):
    path,plan,pics,a,item,h,c=uncertain(tmp_path); report=review(a,item,h,c)
    before=(a.roots[0]/'state.json').read_bytes(); wb=path.read_bytes()
    result=rec.retire_unaccepted(a,4,h,[c],report,'Verified server traceback: failure BEFORE Run creation.',tmp_path/'claim')
    assert result['jobs_submitted']==0 and path.read_bytes()==wb
    for root in a.roots:
        s=batch.read_json(root/'state.json')
        assert item['reference'] not in s['entries'] and len(s['retired_submissions'])==1
        backup=root/'reconciliation'/report['state_sha256']/'state-before.json'
        assert json.loads(backup.read_bytes())==json.loads(before)
    from test_tti_concept_batch import FakeAPI
    api=FakeAPI()
    # A third row isn't in this fixture, so force a non-pilot selection via different proof IDs.
    with pytest.raises(RuntimeError,match='PROOF NOT APPROVED'):
        run(plan,pics,a,api,proof_rows=(6,12))
    assert not api.posts
    # Only a later explicit selected-proof invocation may send the failed row once.
    assert run(plan,pics,a,api,selected_rows=[4],proof_rows=(3,4))==0
    assert len(api.posts)==1
    current,_=batch.read_plan(path)
    assert run(current,pics,a,api,selected_rows=[4],proof_rows=(3,4))==0 and len(api.posts)==1


@pytest.mark.parametrize('location',['history','service'])
def test_any_existing_run_even_wrong_quantity_blocks_reset(tmp_path,location):
    _,_,_,a,item,h,c=uncertain(tmp_path); reviewed=review(a,item,h,c)
    found={'run_id':'abc123456789','drawing_number':item['reference'],'units':999,'status':'done'}
    if location=='history': (h/'existing.json').write_text(json.dumps(found))
    else: c.runs=[found]
    with pytest.raises(ValueError,match='matching run'):
        rec.retire_unaccepted(a,4,h,[c],reviewed,'Verified server failed before creating a run.',tmp_path/'claim')


@pytest.mark.parametrize('condition',['lock','active','state_changed','request_changed','peer_down','history_corrupt','ck_disagree','no_reason','truncated'])
def test_reconciliation_stops_safely(tmp_path,condition,monkeypatch):
    path,_,_,a,item,h,c=uncertain(tmp_path); reviewed=review(a,item,h,c); claim=tmp_path/'claim'
    reason='Verified server failure before Run creation.'
    if condition=='lock': claim.write_text('another batch')
    if condition=='active': c.runs=[{'run_id':'other0000001','drawing_number':'OTHER','status':'running'}]
    if condition=='state_changed':
        state=batch.read_json(a.roots[0]/'state.json'); state['changed']=True; a.state(state)
    if condition=='request_changed':
        req=batch.read_json(a.roots[0]/item['reference']/'inputs/request.json'); req['units']=999
        a.put(item['reference']+'/inputs/request.json',batch.json_bytes(req),immutable=False)
    if condition=='peer_down': monkeypatch.setattr(c,'request',lambda *args:(_ for _ in ()).throw(OSError('offline')))
    if condition=='history_corrupt': (h/'old.json').write_text('broken')
    if condition=='ck_disagree': (a.roots[1]/'state.json').write_text('{}')
    if condition=='no_reason': reason=''
    if condition=='truncated': monkeypatch.setattr(rec,'LIMIT',1); c.runs=[{'run_id':'other'}]
    before=[(r/'state.json').read_bytes() for r in a.roots]; wb=path.read_bytes()
    with pytest.raises((ValueError,RuntimeError,OSError)):
        rec.retire_unaccepted(a,4,h,[c],reviewed,reason,claim)
    assert [(r/'state.json').read_bytes() for r in a.roots]==before and path.read_bytes()==wb
    if condition=='lock': assert claim.read_text()=='another batch'
