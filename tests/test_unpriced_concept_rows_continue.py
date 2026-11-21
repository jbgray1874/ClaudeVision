import ast
import importlib.util
from pathlib import Path
import sys
from typing import Any
import pytest

ROOT=Path(__file__).resolve().parents[1]
REPO=Path(r'C:\ClaudeVision') if not (ROOT/'src/tti_concept_inputs.py').exists() else ROOT
sys.path.insert(0,str(REPO/'src'))
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
b=load('unpriced_batch',ROOT/'src/tti_concept_batch.py')
h=load('concept_fixture',REPO/'tests/test_tti_concept_batch.py'); h.batch=b

def test_empty_price_is_held_while_other_rows_finish_and_never_resent(tmp_path):
    path,plan,pics,a,api=h.setup(tmp_path,[(3,'Unpriced',1,''),(4,'Good',1,''),(5,'Next',1,'')])
    start=api.start
    def submit(body):
        r=start(body)
        if len(api.posts)==1: api.runs[r['run_id']]['engine_price_gbp']=None
        return r
    api.start=submit
    assert b.run_batch(plan,pics,a,api,'abcdef12',sleep=lambda _:None)==4
    state=b.read_json(a.roots[0]/'state.json')
    assert [state['entries'][i['reference']]['phase'] for i in plan['rows']]==['held','done','done']
    current,_=h.inp.read_plan(path)
    assert [i['cost_before'] for i in current['rows']]==[None,12.34,12.34]
    assert len(api.posts)==3
    assert b.run_batch(current,pics,a,api,'abcdef12',sleep=lambda _:None)==4
    assert len(api.posts)==3
    for root in a.roots:
        assert (root/plan['rows'][0]['reference']/'unpriced/000000000001/HOLD.json').exists()

@pytest.mark.parametrize('price',[None,0,-1,True,'NaN','Infinity','garbage'])
def test_invalid_prices_are_not_zero_or_written(price):
    with pytest.raises(b.UnpricedResult):
        b.checked_price({'client':'TTI','drawing_number':'ref','units':1,'status':'done','price_validated':True,'engine_price_gbp':price},{'reference':'ref','quantity':1})

def test_changed_identity_remains_a_fatal_fault():
    with pytest.raises(ValueError) as e:
        b.checked_price({'client':'Other'},{'reference':'ref','quantity':1})
    assert not isinstance(e.value,b.UnpricedResult)

def test_archive_failure_is_not_downgraded_to_a_hold(tmp_path):
    _,plan,pics,a,api=h.setup(tmp_path,[(3,'Unpriced',1,'')]); start=api.start
    def submit(body):
        r=start(body); api.runs[r['run_id']]['engine_price_gbp']=None; return r
    api.start=submit
    api.download=lambda *a:(_ for _ in ()).throw(OSError('K unavailable'))
    with pytest.raises(OSError): b.run_batch(plan,pics,a,api,'abcdef12',sleep=lambda _:None)
    assert b.read_json(a.roots[0]/'state.json')['entries'][plan['rows'][0]['reference']]['phase']=='running'

def validated():
    t=ast.parse((ROOT/'sdi-intelligence-backend/estimate_routes.py').read_text(encoding='utf-8-sig'))
    f=next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='price_is_validated')
    env={'Any':Any}; exec(compile(ast.Module(body=[f],type_ignores=[]),'validation','exec'),env)
    return env['price_is_validated']

@pytest.mark.parametrize('price,expected',[(None,False),(0,False),(-1,False),(True,False),('NaN',False),('Infinity',False),(583.59,True)])
def test_service_cannot_call_an_empty_workbook_price_validated(price,expected):
    assert validated()('done','',[{'name':'estimate.xlsx'}],price) is expected

def test_auth_failure_is_sanitized_and_same_images_and_brief_are_sent(monkeypatch):
    v=load('vision_test',ROOT/'src/vision_fallback.py'); seen=[]
    class Auth(Exception): status_code=401
    class Provider:
        def model(self): return 'test'
        def ask_image(self,prompt,images):
            seen.append((prompt,images)); raise Auth('secret-value-that-must-not-be-logged')
    monkeypatch.setattr(v,'_openai',lambda:Provider())
    log=[]
    with pytest.raises(RuntimeError,match='authentication failed') as exc:
        v.ask('all row details',[b'image1',b'image2'],'concept','xAI failed',say=log.append)
    assert seen==[('all row details',[b'image1',b'image2'])]
    assert 'secret-value' not in str(exc.value) and all('secret-value' not in x for x in log)
