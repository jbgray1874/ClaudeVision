"""Offline synthetic workbooks/fake service. Never touch a live workbook or queue."""
import pytest
from test_tti_concept_batch import setup, run, mutate
from test_tti_concept_proof_gate import three_rows
import tti_concept_batch as batch
import tti_concept_inputs as inp
import tti_concept_proof as proof


def lock(path):
    marker=path.parent/('~$'+path.name)
    marker.touch()
    return marker


def test_locked_tracker_prices_every_row_without_touching_workbook_or_lock(tmp_path):
    path,plan,pics,a,api=three_rows(tmp_path)
    marker=lock(path); original=path.read_bytes()
    assert run(plan,pics,a,api)==3
    assert len(api.posts)==3 and marker.exists() and path.read_bytes()==original
    for root in a.roots:
        state=batch.read_json(root/'state.json')
        assert len(state['entries'])==3
        for item in plan['rows']:
            entry=state['entries'][item['reference']]
            assert entry['phase']=='archived' and entry['writeback_pending']
            for name in ('result_record.json','result.xlsx','report.html','price-for-writeback.json'):
                assert (root/item['reference']/'results'/name).exists()
    # Resume still locked: no polling/downloading/repricing an already archived run.
    api.status=lambda *_:pytest.fail('archived run polled')
    api.download=lambda *_:pytest.fail('archived run downloaded again')
    assert run(plan,pics,a,api)==3 and len(api.posts)==3


def test_retry_only_after_close_writes_without_a_service_and_is_idempotent(tmp_path):
    path,plan,pics,a,api=setup(tmp_path)
    marker=lock(path)
    assert run(plan,pics,a,api)==3
    assert batch.retry_writebacks(plan,a)==3
    marker.unlink()
    api.runs.clear()  # Results no longer exist at service: archived results suffice.
    assert batch.retry_writebacks(plan,a)==0
    current,_=inp.read_plan(path)
    assert [r['cost_before'] for r in current['rows'][:2]]==[12.34,12.34]
    assert batch.retry_writebacks(current,a)==0 and len(api.posts)==2


def test_permission_denied_at_write_defers_and_continues(tmp_path):
    _,plan,pics,a,api=three_rows(tmp_path)
    def denied(*_): raise PermissionError('Excel sharing violation')
    assert run(plan,pics,a,api,writer=denied)==3
    assert len(api.posts)==3


@pytest.mark.parametrize('error',[ValueError('source changed'),RuntimeError('bug'),OSError('disk full')])
def test_other_writer_errors_remain_fatal(tmp_path,error):
    _,plan,pics,a,api=three_rows(tmp_path)
    def broken(*_): raise error
    with pytest.raises(type(error),match=str(error)):
        run(plan,pics,a,api,writer=broken)
    assert len(api.posts)==2


def test_shared_archive_permission_error_is_not_treated_as_excel_busy(tmp_path):
    _,plan,pics,a,api=three_rows(tmp_path)
    original=a.put
    def broken(name,*args,**kw):
        if name.endswith('result.xlsx'): raise PermissionError('K denied')
        return original(name,*args,**kw)
    a.put=broken
    with pytest.raises(PermissionError,match='K denied'): run(plan,pics,a,api)
    assert len(api.posts)==2


@pytest.mark.parametrize('change',['row','price','archive','ledger'])
def test_retry_rejects_changed_identity_price_or_evidence(tmp_path,change):
    path,plan,pics,a,api=setup(tmp_path)
    marker=lock(path)
    assert run(plan,pics,a,api)==3
    marker.unlink()
    if change=='row':
        mutate(path,'xl/worksheets/sheet1.xml',lambda b:b.replace(b'Red finish',b'Blue finish'))
    elif change=='price':
        mutate(path,'xl/worksheets/sheet1.xml',lambda b:b.replace(b'<c r="P3" s="0"/>',b'<c r="P3"><v>99</v></c>'))
    elif change=='archive':
        (a.roots[1]/plan['rows'][0]['reference']/'results'/'result.xlsx').write_bytes(b'corrupt')
    else:
        state=batch.read_json(a.roots[0]/'state.json')
        state['entries'][plan['rows'][0]['reference']]['unit_gbp']='999'
        a.state(state)
    with pytest.raises(ValueError): batch.retry_writebacks(plan,a)
    assert len(api.posts)==2


def test_pending_pilot_still_requires_review_then_remainder_can_run_while_locked(tmp_path):
    path,plan,pics,a,api=three_rows(tmp_path)
    marker=lock(path)
    assert run(plan,pics,a,api,selected_rows=[3,4],proof_rows=(3,4))==3
    with pytest.raises(RuntimeError,match='PROOF NOT APPROVED'):
        run(plan,pics,a,api,proof_rows=(3,4))
    assert len(api.posts)==2
    approved=proof.approve_proof(a,plan,(3,4),expected_build='abcdef12')
    assert approved['decision']=='PASS'
    assert run(plan,pics,a,api,proof_rows=(3,4))==3 and len(api.posts)==3
    marker.unlink()
    assert batch.retry_writebacks(plan,a)==0
    state=batch.read_json(a.roots[0]/'state.json')
    assert proof.require_approved_proof(plan,a,state,(3,4),'abcdef12')==approved


def test_pending_proof_missing_workbook_cannot_be_approved(tmp_path):
    path,plan,pics,a,api=three_rows(tmp_path); lock(path)
    assert run(plan,pics,a,api,selected_rows=[3,4],proof_rows=(3,4))==3
    (a.roots[1]/plan['rows'][0]['reference']/'results'/'result.xlsx').unlink()
    with pytest.raises(OSError): proof.approve_proof(a,plan,(3,4))
    assert len(api.posts)==2


@pytest.mark.parametrize('other',['--execute','--approve-proof'])
def test_writeback_only_cannot_be_combined_with_execution_or_approval(other):
    with pytest.raises(SystemExit):
        batch.main(['--sheet','unused.xlsx','--plan-output','unused.json','--writeback-only',other])
