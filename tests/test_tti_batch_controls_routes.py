import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "sdi-intelligence-backend")]
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from tti_batch_controls_routes import make_router
from tti_incremental import ReviewRequired


@pytest.fixture
def client():
    class Controls:
        calls = []
        def browse(self, tracker): return {'rows':[], 'enabled':False}
        def preview(self, tracker, **kw):
            self.calls.append((tracker,kw))
            return {'at_once':2,'runnable':False,'selected':[]}
        def run(self, tracker, **kw): raise ReviewRequired('Pricing disabled')
        def review(self, tracker, **kw): raise ReviewRequired('Not reconciled')
    def key(k):
        if k != 'test-only': raise HTTPException(401,'Key required')
    app=FastAPI()
    app.include_router(make_router(Controls(),check_key=key),prefix='/api/estimate')
    return TestClient(app)


def post(client, action, body):
    return client.post('/api/estimate/tti/batches/'+action,json=body,headers={'X-SDI-Key':'test-only'})


def test_auth_and_tracker_allowlist(client):
    assert client.post('/api/estimate/tti/batches/rows',json={}).status_code == 401
    assert post(client,'rows',{'tracker_id':'unconfigured'}).status_code == 400
    assert post(client,'rows',{}).json()['enabled'] is False


@pytest.mark.parametrize('body', [{'count':0},{'count':51},{'count':True},{'count':2.5},
                                {'count':'5'},{'at_once':3},{'mode':'all'},{'start_row':0},
                                {'row_ids':['a']*51}])
def test_invalid_input_rejected_before_controls(client,body):
    assert post(client,'preview',body).status_code == 422


def test_valid_preview_is_two_runners_and_disabled(client):
    assert post(client,'preview',{'count':5,'start_row':3}).json() == {'at_once':2,'runnable':False,'selected':[]}


def test_run_and_review_fail_closed(client):
    assert post(client,'run',{'plan_id':'test'}).status_code == 409
    assert post(client,'run',{'plan_id':'test','confirm_replace':'yes'}).status_code == 422
    assert post(client,'review',{'plan_id':'test','outputs_checked':True,'costs_reviewed':True,'notes':'Review'}).status_code == 409
