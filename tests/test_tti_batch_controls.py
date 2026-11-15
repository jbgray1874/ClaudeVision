import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "sdi-intelligence-backend")]
import copy
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from tti_incremental import Store, ReviewRequired
from tti_batch_controls import BatchControls, CAPABILITIES


def row(n, **kw):
    r = dict(row_id=str(uuid.uuid5(uuid.NAMESPACE_URL, 'batch-row-'+str(n))), row=n,
             drawing=f'12181-{n:02d}-GA', quantity=3, description='Own brief',
             previous_feedback='Earlier', latest_feedback='Latest', revision='A',
             pack_key='pack-'+str(n), pack_state='ready', pack_safe=True,
             method='both', client='TTI', cost=None, holds=[], history=None)
    r.update(kw)
    return r


@pytest.fixture
def env(tmp_path):
    class Env:
        def __init__(self):
            self.now = 1000
            self.rows = [row(n) for n in range(3, 15)]
            self.calls = []
            self.store = Store(tmp_path/'shared.sqlite', clock=lambda: self.now)
            self.store.initialise('master', [], history_reconciled=True)
            self.ctl = BatchControls(self.store, snapshot=self.snapshot, submit=self.submit,
                                     enabled=lambda: True, capabilities=CAPABILITIES)
        def snapshot(self, tracker):
            return dict(rows=copy.deepcopy(self.rows), row_id_column='AI Row ID', rows_without_id=0)
        def submit(self, tracker, selected, **kw):
            self.calls.append((tracker, copy.deepcopy(selected), kw))
            return dict(task_id='task-'+kw['request_id'])
        def plan(self, **kw):
            return self.ctl.preview('master', **kw)
        def run(self, plan, **kw):
            return self.ctl.run('master', plan['plan_id'], **kw)
        def finish(self, plan, state='completed'):
            self.store.finish(plan['plan_id'], {r['row_id']: dict(state=state, run_id='run-'+r['row_id'])
                                               for r in plan['selected']})
        def review(self, plan):
            return self.ctl.review('master', plan['plan_id'], outputs_checked=True,
                                   costs_reviewed=True, notes='Filing checked; questions recorded for estimating')
    return Env()


def test_next_five_is_exact_and_in_sheet_order(env):
    env.rows.reverse()
    p = env.plan()
    assert [x['row'] for x in p['selected']] == [3,4,5,6,7]
    env.run(p)
    assert [x['row'] for x in env.calls[0][1]] == [3,4,5,6,7]
    assert env.calls[0][2]['at_once'] == 2
    assert env.calls[0][2]['replace_costs'] is False
    assert set(env.calls[0][2]['expected_inputs']) == {x['row_id'] for x in p['selected']}


def test_start_skips_completed_zero_cost_held_and_missing(env):
    env.rows[1].update(history='completed', run_id='old', cost=0)
    env.rows[2]['cost'] = 0
    env.rows[3]['holds'] = ['Revision conflict']
    env.rows[4].update(pack_state='missing', pack_safe=False)
    p = env.plan(count=3, start_row=4)
    assert [x['row'] for x in p['selected']] == [8,9,10]
    assert {x['row']:x['state'] for x in p['skipped']}[4] == 'completed'


@pytest.mark.parametrize('field,value', [('count',0),('count',51),('count',True),('count',2.5),
                                       ('start_row',0),('start_row',1048577),('start_row','3')])
def test_invalid_limits_do_not_fallback(env, field, value):
    with pytest.raises(ReviewRequired): env.plan(**{field:value})
    assert env.calls == []


def test_fewer_than_requested_and_none_remaining(env):
    assert len(env.plan(count=5, start_row=13)['selected']) == 2
    with pytest.raises(ReviewRequired, match='No eligible'): env.plan(start_row=20)


def test_repeated_drawings_remain_distinct_rows(env):
    env.rows[1]['drawing'] = env.rows[0]['drawing']
    env.rows[1]['latest_feedback'] = 'Different job'
    env.run(env.plan(count=2))
    assert len(env.calls[0][1]) == 2
    assert len({r['row_id'] for r in env.calls[0][1]}) == 2


@pytest.mark.parametrize('state', ['unknown','failed','running','queued','reserved','submitted',
                                  'completed_pending_write','outcome not known','not queued','unrecognised'])
def test_uncertain_or_unreconciled_rows_never_run(env, state):
    env.rows = [row(3, history=state, run_id='prior')]
    assert env.ctl.browse('master')['rows'][0]['state'] == 'held'
    with pytest.raises(ReviewRequired): env.plan()
    with pytest.raises(ReviewRequired): env.plan(mode='rerun',row_ids=[env.rows[0]['row_id']],reason='Fix')


@pytest.mark.parametrize('drawing', ['12748-01-GA','12754-01-GA'])
def test_explicit_drawing_holds(env, drawing):
    env.rows = [row(3, drawing=drawing)]
    with pytest.raises(ReviewRequired): env.plan()


def test_rerun_requires_completed_identity_reason_and_cost_consent(env):
    env.rows = [row(3, history='completed', run_id='previous', cost=0)]
    ids = [env.rows[0]['row_id']]
    with pytest.raises(ReviewRequired): env.plan(mode='rerun',row_ids=ids)
    with pytest.raises(ReviewRequired): env.plan(mode='rerun',row_ids=ids*2,reason='Fix')
    p = env.plan(mode='rerun',row_ids=ids,reason='Fix timber costing')
    with pytest.raises(ReviewRequired): env.run(p)
    env.run(p,confirm_replace=True)
    assert env.calls[0][2]['replace_costs'] is True
    assert env.calls[0][2]['rerun_reason'] == 'Fix timber costing'


def test_no_baseline_no_ids_and_duplicate_ids_refused(env):
    with env.store.connect() as db: db.execute('DELETE FROM baseline')
    with pytest.raises(ReviewRequired, match='baseline'): env.plan()
    env.store.initialise('master', [],history_reconciled=True)
    env.rows[0]['row_id'] = ''
    with pytest.raises(ReviewRequired): env.plan()
    env.rows = [row(3), row(4,row_id=row(3)['row_id'])]
    with pytest.raises(ReviewRequired): env.plan()


@pytest.mark.parametrize('key,value', [('pack_key','changed'),('description','changed'),
                                      ('cost',5),('run_id','new-run'),('holds',['new hold'])])
def test_changed_inputs_invalidate_preview(env, key, value):
    p = env.plan()
    env.rows[0][key] = value
    with pytest.raises(ReviewRequired): env.run(p)
    assert not env.calls


def test_baseline_change_invalidates_preview(env):
    p = env.plan()
    with env.store.connect() as db:
        db.execute('UPDATE baseline SET rows_json=?', (json.dumps([row(3,history='completed',run_id='old')]),))
    with pytest.raises(ReviewRequired, match='history changed'): env.run(p)


def test_sorting_preserves_selected_ids_and_updates_physical_positions(env):
    p = env.plan(count=2)
    env.rows[0]['row'], env.rows[4]['row'] = env.rows[4]['row'], env.rows[0]['row']
    env.run(p)
    assert {r['row_id'] for r in env.calls[0][1]} == {r['row_id'] for r in p['selected']}
    assert [r['row'] for r in env.calls[0][1]] == [4,7]


@pytest.mark.parametrize('age', [901,-1])
def test_preview_expiry_and_clock_rollback(env, age):
    p = env.plan(); env.now += age
    with pytest.raises(ReviewRequired, match='expired'): env.run(p)


def test_double_click_and_two_services_only_submit_once(env):
    p = env.plan()
    other = BatchControls(Store(env.store.path,clock=lambda:env.now), snapshot=env.snapshot,
                          submit=env.submit,enabled=lambda:True,capabilities=CAPABILITIES)
    barrier = threading.Barrier(2)
    def attempt(c):
        barrier.wait()
        try: c.run('master',p['plan_id']); return 'sent'
        except ReviewRequired: return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt,[env.ctl,other]))
    assert sorted(results) == ['refused','sent']
    assert len(env.calls) == 1


@pytest.mark.parametrize('failure', ['exception','no_receipt'])
def test_uncertain_post_retains_reservation_across_reopen(env, failure):
    def submit(*a,**kw):
        if failure == 'exception': raise TimeoutError()
        return {}
    env.ctl.submit = submit
    p = env.plan()
    with pytest.raises(ReviewRequired, match='unknown'): env.run(p)
    reopened = Store(env.store.path)
    assert reopened.active_plan('master')['status'] == 'unknown'
    with pytest.raises(ReviewRequired): env.run(p)
    with pytest.raises(ReviewRequired): env.plan()


def test_review_gate_after_finish_and_durable_review_audit(env):
    p = env.plan(count=1); env.run(p)
    with pytest.raises(ReviewRequired): env.review(p)
    env.finish(p)
    with pytest.raises(ReviewRequired, match='Review'): env.plan()
    with pytest.raises(ReviewRequired): env.ctl.review('master',p['plan_id'],notes='Not enough')
    env.review(p)
    q = env.plan(count=1); env.run(q)
    with env.store.connect() as db:
        audit = json.loads(db.execute('SELECT payload FROM plans WHERE id=?',(p['plan_id'],)).fetchone()[0])
    assert audit['batch_review']['outputs_checked'] is True
    assert audit['batch_review']['notes'].startswith('Filing checked')
    assert q['selected'][0]['row'] == 4


def test_pending_write_cannot_be_acknowledged(env):
    p = env.plan(count=1); env.run(p); env.finish(p,'completed_pending_write')
    with pytest.raises(ReviewRequired, match='Write-back'): env.review(p)


def test_shared_legacy_dispatch_cannot_consume_bounded_plan_or_bypass_review(env):
    p = env.plan(count=1)
    with pytest.raises(ReviewRequired, match='batch-controls'):
        env.store.dispatch(p['plan_id'],env.rows,lambda *a,**k:pytest.fail('sent'))
    env.run(p); env.finish(p)
    old = env.store.preview('master',env.rows)
    with pytest.raises(ReviewRequired, match='review'):
        env.store.dispatch(old['plan_id'],env.rows,lambda *a,**k:pytest.fail('sent'))


def test_rerun_retains_previous_result_history(env):
    old = row(3,history='completed',run_id='previous',cost=42)
    env.rows = [old]
    with env.store.connect() as db:
        db.execute('UPDATE baseline SET rows_json=?',(json.dumps([old]),))
    p = env.plan(mode='rerun',row_ids=[old['row_id']],reason='Correct material')
    env.run(p,confirm_replace=True); env.finish(p)
    assert env.ctl._base('master')[old['row_id']]['previous_results'][0]['run_id'] == 'previous'


def test_disabled_missing_capability_busy_and_wrong_tracker(env):
    p = env.plan()
    env.ctl.enabled=lambda:False
    with pytest.raises(ReviewRequired,match='disabled'): env.run(p)
    env.ctl.enabled=lambda:True; env.ctl.capabilities=frozenset()
    with pytest.raises(ReviewRequired,match='disabled'): env.run(p)
    env.ctl.capabilities=CAPABILITIES; env.ctl.busy=lambda:'active CLI'
    with pytest.raises(ReviewRequired): env.run(p)
    env.ctl.busy=lambda:None
    with pytest.raises(ReviewRequired,match='cross-tracker'): env.ctl.run('different',p['plan_id'])
    assert not env.calls
