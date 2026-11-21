"""Exercise real progress handler without importing production services/dependencies."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import threading
import pytest

ROOT=Path(__file__).resolve().parents[1]

def handler():
    tree=ast.parse((ROOT/'sdi-intelligence-backend/estimate_routes.py').read_text(encoding='utf-8-sig'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='progress')
    node.decorator_list=[]
    # Strip annotations/defaults to isolate actual handler logic from FastAPI.
    node.returns=None
    for a in node.args.args: a.annotation=None
    node.args.defaults=[ast.Constant(None)]
    env={'_LOCK':threading.Lock(),'time':NS(time=lambda:10000),'_check_key':lambda x:None,
         '_RUNS':{},'_RUNNERS':{},'LEASE_SECONDS':180,'_last_progress_save':{},
         '_PROGRESS_SAVE_SECONDS':30,'_keep':lambda r:None,'_host_of':lambda r:'host',
         '_note_compute':lambda *a:None,'_check_the_engine_was_told':lambda *a:None,
         '_note_solidworks_turn':lambda *a:None}
    class HTTPError(Exception):
        def __init__(self,code,text): self.status_code=code; super().__init__(text)
    env['HTTPException']=HTTPError
    env['Runner']=lambda runner_id:NS(runner_id=runner_id,processes={},capabilities=[],hostname='host')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'handler','exec'),env)
    return env

@pytest.mark.parametrize('reported,claimed,expected',[('pid1','pid1','pid1'),('','pid1','pid1'),('','',''),('pid1','','pid1')])
def test_busy_progress_renews_known_identity_not_guesses(reported,claimed,expected):
    env=handler(); run=NS(runner='r',status='running',run_id='abc',claimed_by_process=claimed,
                        runner_capabilities=[],cancel_requested=False)
    env['_RUNS']['abc']=run
    env['progress']('abc',NS(runner_id='r',process=reported,lines=[],compute=None))
    assert env['_RUNNERS']['r'].processes==({expected:10000} if expected else {})

@pytest.mark.parametrize('fault',['wrong_process','wrong_runner','finished'])
def test_invalid_progress_cannot_refresh_or_renew(fault):
    env=handler(); run=NS(runner='r',status='done' if fault=='finished' else 'running',
                         run_id='abc',claimed_by_process='pid1',lease_until=1)
    env['_RUNS']['abc']=run
    with pytest.raises(env['HTTPException']):
        env['progress']('abc',NS(runner_id='other' if fault=='wrong_runner' else 'r',
                               process='pid2' if fault=='wrong_process' else 'pid1',lines=[]))
    assert not env['_RUNNERS'] and run.lease_until==1

def test_other_live_identity_is_not_erased():
    env=handler(); env['_RUNNERS']['r']=NS(processes={'pid2':9999},capabilities=[],hostname='host')
    env['_RUNS']['abc']=NS(runner='r',status='running',run_id='abc',claimed_by_process='pid1',
                          runner_capabilities=[],cancel_requested=False)
    env['progress']('abc',NS(runner_id='r',process='pid1',lines=[],compute=None))
    assert env['_RUNNERS']['r'].processes=={'pid2':9999,'pid1':10000}

def test_runner_passes_stable_claim_identity_to_execute_and_progress():
    tree=ast.parse((ROOT/'tools/runner/sdi_estimate_runner.py').read_text(encoding='utf-8-sig'))
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_execute']
    assert any(any(k.arg=='process_identity' and isinstance(k.value,ast.Name) and k.value.id=='_process' for k in c.keywords) for c in calls)
    execute=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_execute')
    assert any(isinstance(n,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='process' and isinstance(v,ast.Name) and v.id=='process_identity' for k,v in zip(n.keys,n.values)) for n in ast.walk(execute))
