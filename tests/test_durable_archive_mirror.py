import errno
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from durable_archive_mirror import Mirror
import tti_concept_batch as B


def test_archive_waits_then_mirrors_without_losing_c(tmp_path,monkeypatch):
    local,shared=tmp_path/'C',tmp_path/'K';shared.parent.mkdir(exist_ok=True)
    sleeps=[];m=Mirror(local,shared,sleep=lambda seconds:sleeps.append(seconds));real=m._publish
    def fail_once(intent,raw):
        if not sleeps:raise OSError(errno.ENETUNREACH,'VPN down')
        assert (local/'row/result.json').read_bytes()==b'priced result'
        real(intent,raw)
    monkeypatch.setattr(m,'_publish',fail_once)
    m.put('row/result.json',b'priced result')
    assert sleeps==[15] and (shared/'row/result.json').read_bytes()==b'priced result'
    assert not list((local/'.pending-shared').glob('*.json'))


def test_stop_during_outage_preserves_intent_and_restart_repairs_only_mirror(tmp_path,monkeypatch):
    local,shared,stop=tmp_path/'C',tmp_path/'K',tmp_path/'STOP'
    shared.mkdir();local.mkdir();(shared/'state.json').write_bytes(b'old');(local/'state.json').write_bytes(b'old')
    def pause(seconds):stop.write_text('stop')
    m=Mirror(local,shared,stop_file=stop,sleep=pause)
    monkeypatch.setattr(m,'_publish',lambda *a:(_ for _ in ()).throw(OSError(errno.ENETDOWN,'VPN down')))
    with pytest.raises(InterruptedError):m.put('state.json',b'new known run ID',immutable=False)
    assert (local/'state.json').read_bytes()==b'new known run ID'
    assert (shared/'state.json').read_bytes()==b'old'
    stop.unlink();Mirror(local,shared).sync()
    assert (shared/'state.json').read_bytes()==b'new known run ID'


def test_different_shared_state_is_never_silently_overwritten(tmp_path,monkeypatch):
    local,shared,stop=tmp_path/'C',tmp_path/'K',tmp_path/'STOP';local.mkdir();shared.mkdir()
    (local/'state.json').write_bytes(b'old');(shared/'state.json').write_bytes(b'another batch')
    with pytest.raises(ValueError,match='conflict'):
        Mirror(local,shared).put('state.json',b'new',immutable=False)
    assert (shared/'state.json').read_bytes()==b'another batch'


def test_immutable_outputs_and_local_intent_hashes_cannot_be_replaced(tmp_path):
    local,shared=tmp_path/'C',tmp_path/'K';m=Mirror(local,shared)
    m.put('result',b'price one')
    with pytest.raises(ValueError):m.put('result',b'price two')
    assert (local/'result').read_bytes()==(shared/'result').read_bytes()==b'price one'


def test_permission_error_is_not_hidden_as_a_vpn_retry(tmp_path,monkeypatch):
    m=Mirror(tmp_path/'C',tmp_path/'K',sleep=lambda s:pytest.fail('must not retry access denied'))
    monkeypatch.setattr(m,'_publish',lambda *a:(_ for _ in ()).throw(PermissionError('access denied')))
    with pytest.raises(PermissionError):m.put('result',b'data')
    assert (tmp_path/'C'/'result').read_bytes()==b'data'


def test_another_shared_writer_lock_is_never_removed(tmp_path):
    local,shared=tmp_path/'C',tmp_path/'K';shared.mkdir()
    lock=shared/'state.json.mirror.lock';lock.write_text('{"token":"other owner"}')
    with pytest.raises(ValueError,match='another shared archive writer'):
        Mirror(local,shared).put('state.json',b'known IDs',immutable=False)
    assert lock.read_text()=='{"token":"other owner"}'
    assert (local/'state.json').read_bytes()==b'known IDs'


@pytest.mark.parametrize('name',['../escape','.pending-shared/overwrite'])
def test_archive_path_traversal_is_refused(tmp_path,name):
    with pytest.raises(ValueError):Mirror(tmp_path/'C',tmp_path/'K').put(name,b'data')


def test_archive_opt_in_retains_original_proof_and_writeback_checks(tmp_path,monkeypatch):
    monkeypatch.setenv('SDI_ESTIMATE_LOCAL_FIRST','1')
    a=B.Archive(tmp_path/'C',tmp_path/'K');a.put('proof.json',b'{"same":"proof"}')
    from tti_concept_proof import same_bytes
    assert same_bytes(a,'proof.json')==b'{"same":"proof"}'
    (tmp_path/'K'/'proof.json').write_bytes(b'changed')
    with pytest.raises(ValueError):same_bytes(a,'proof.json')


def test_uncertain_post_is_never_retried_even_in_local_first_mode(monkeypatch):
    monkeypatch.setenv('SDI_ESTIMATE_LOCAL_FIRST','1');calls=[]
    def fail(*a,**kw):calls.append(a);raise OSError('answer lost')
    monkeypatch.setattr(B.urllib.request,'urlopen',fail)
    with pytest.raises(OSError):B.Client('http://test').start({'drawing_number':'one'})
    assert len(calls)==1


def test_get_collection_retries_without_submitting(monkeypatch):
    monkeypatch.setenv('SDI_ESTIMATE_LOCAL_FIRST','1');calls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self):return b'{"run_id":"abcdef123456"}'
    def get(req,**kw):
        calls.append(req.get_method())
        if len(calls)==1:raise OSError('VPN down')
        return Response()
    monkeypatch.setattr(B.urllib.request,'urlopen',get);monkeypatch.setattr(B.time,'sleep',lambda s:None)
    assert B.Client('http://test').status('abcdef123456')['run_id']=='abcdef123456'
    assert calls==['GET','GET']
