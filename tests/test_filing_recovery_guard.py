import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sdi-intelligence-backend'))
from filing_recovery import may_recover


@pytest.mark.parametrize('changes,expected',[
    ({},True),({'status':'running'},False),({'status':'done'},False),
    ({'lease_expired':False},False),({'cancel_requested':True},False),
    ({'stopped_by_hand':True},False),({'instruction_refused':True},False)])
def test_only_lease_expiry_can_recover(changes,expected):
    fields=dict(status='error',lease_expired=True,cancel_requested=False,stopped_by_hand=False,instruction_refused=False)
    fields.update(changes)
    assert may_recover(SimpleNamespace(**fields)) is expected


def test_guard_is_enforced_in_real_completion_before_status_or_money_changes():
    source=(ROOT/'sdi-intelligence-backend/estimate_routes.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='complete')
    body=ast.get_source_segment(source,node)
    assert body.index('run.runner != req.runner_id') < body.index('req.recover_expired_run')
    assert body.index('req.recover_expired_run') < body.index('run.status = "done"')
    assert 'run.cancel_requested or run.stopped_by_hand or run.instruction_refused' in body


def test_real_completion_recovery_guard_rejects_manual_stop_and_invalid_expiry():
    # Execute the actual two guard statements from the endpoint without importing FastAPI
    # or running a service. Ownership and delivery identity are exercised by runner tests.
    source=(ROOT/'sdi-intelligence-backend/estimate_routes.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='complete')
    guards=[n for n in ast.walk(fn) if isinstance(n,ast.If)
            and (ast.unparse(n.test).startswith('req.local_first_delivery')
                 or ast.unparse(n.test).startswith('req.recover_expired_run'))]
    code=compile(ast.fix_missing_locations(ast.Module(body=guards,type_ignores=[])),'real-completion-guard','exec')
    class Refused(Exception):pass
    req=SimpleNamespace(local_first_delivery=True,recover_expired_run=True)
    for changes in [dict(cancel_requested=True),dict(stopped_by_hand=True),dict(instruction_refused=True),dict(lease_expired=False)]:
        fields=dict(status='error',lease_expired=True,cancel_requested=False,stopped_by_hand=False,instruction_refused=False)
        fields.update(changes)
        with pytest.raises(Refused):
            exec(code,dict(req=req,run=SimpleNamespace(**fields),may_recover_filing=may_recover,HTTPException=Refused))
    exec(code,dict(req=req,run=SimpleNamespace(status='error',lease_expired=True,cancel_requested=False,
        stopped_by_hand=False,instruction_refused=False),may_recover_filing=may_recover,HTTPException=Refused))


def test_real_lease_expiry_sets_and_persists_recovery_provenance():
    source=(ROOT/'sdi-intelligence-backend/estimate_routes.py').read_text(encoding='utf-8')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_expire_dead_claims')
    code=compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'actual-lease-expiry','exec')
    logs=[];saved=[]
    run=SimpleNamespace(status='running',lease_until=999,runner='r',lease_expired=False,line=logs.append)
    scope=dict(time=SimpleNamespace(time=lambda:1000),_RUNS={'id':run},_RUNNERS={},
               LEASE_SECONDS=900,_keep=lambda value:saved.append(value.lease_expired))
    exec(code,scope);scope['_expire_dead_claims']()
    assert run.status=='error' and run.lease_expired and saved==[True]
    assert 'do not re-run blindly' in logs[0]
