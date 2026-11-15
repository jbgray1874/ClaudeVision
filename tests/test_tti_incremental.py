import copy
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sdi-intelligence-backend'))
from tti_incremental import (Store, ReviewRequired, decisions, plan_row_ids,
                             locate_writeback, snapshot_digest, validate_rows)


def row(n=3, **kw):
    value = dict(row_id=str(uuid.uuid5(uuid.NAMESPACE_URL, 'fixture-'+str(n))), row=n,
                 drawing=f'12345-{n:02d}-GA', quantity=2, description='Frame',
                 previous_feedback='Blue', latest_feedback='Red', revision='A',
                 pack_key='hash-'+str(n), pack_state='ready', pack_safe=True,
                 method='both', client='TTI', cost=None, holds=[], history=None)
    value.update(kw)
    return value


class DecisionTests(unittest.TestCase):
    def test_new_row(self):
        self.assertEqual(decisions([], [row()])[0]['kind'], 'new_row')

    def test_drawing_added_to_existing_row(self):
        old = row(drawing='', pack_state='missing', pack_key='', pack_safe=False)
        self.assertEqual(decisions([old], [row()])[0]['kind'], 'drawing_added')

    def test_pack_arrives_without_cell_change(self):
        old = row(pack_state='missing', pack_key='', pack_safe=False)
        self.assertEqual(decisions([old], [row()])[0]['kind'], 'pack_added')

    def test_unknown_share_not_assumed_missing(self):
        old = row(pack_state='unavailable', pack_key='', pack_safe=False)
        self.assertFalse(decisions([old], [row()])[0]['eligible'])

    def test_unchanged_completed_not_queued(self):
        old = row(history='completed')
        self.assertEqual(decisions([old], [row()])[0]['kind'], 'unchanged_completed')

    def test_changed_feedback_completed_needs_review(self):
        old = row(history='completed')
        result = decisions([old], [row(latest_feedback='Now green')])[0]
        self.assertEqual(result['kind'], 'changed_completed')
        self.assertIn('latest_feedback', result['changed'])
        self.assertFalse(result['eligible'])

    def test_previous_feedback_changes_detected(self):
        self.assertIn('previous_feedback', decisions([row()], [row(previous_feedback='New')])[0]['changed'])

    def test_quantity_revision_and_files_changes(self):
        for key, value in [('quantity', 3), ('revision','B'), ('pack_key','newfilehash')]:
            with self.subTest(key=key):
                result = decisions([row()], [row(**{key:value})])[0]
                self.assertFalse(result['eligible'])
                self.assertIn(key, result['changed'])

    def test_row_move_is_not_change(self):
        a = row()
        b = dict(a, row=99)
        self.assertEqual(snapshot_digest([a]), snapshot_digest([b]))
        self.assertFalse(decisions([a], [b])[0]['eligible'])

    def test_missing_quantity_not_one(self):
        for q in (None,0,True,2.5,'2'):
            self.assertFalse(decisions([], [row(quantity=q)])[0]['eligible'])

    def test_existing_cost_including_zero_not_overwritten(self):
        for cost in (0, 2.3, '0'):
            self.assertFalse(decisions([], [row(cost=cost)])[0]['eligible'])

    def test_queued_unknown_and_failed_not_auto_retried(self):
        for state in ('queued','running','unknown','reserved','failed'):
            self.assertEqual(decisions([row(history=state)], [row()])[0]['kind'], 'held_previous_attempt')

    def test_completed_without_write_never_reestimated(self):
        self.assertFalse(decisions([row(history='completed_pending_write')], [row()])[0]['eligible'])

    def test_new_row_without_pack_held(self):
        self.assertFalse(decisions([], [row(pack_state='missing',pack_safe=False)])[0]['eligible'])

    def test_pack_safe_must_be_explicit_boolean(self):
        self.assertFalse(decisions([], [row(pack_safe='true')])[0]['eligible'])

    def test_deletion_keeps_history(self):
        self.assertEqual(decisions([row(history='completed')], [])[0]['kind'], 'removed')

    def test_same_drawing_different_briefs_not_merged(self):
        rows = [row(), row(4, drawing=row()['drawing'], latest_feedback='Different variant')]
        self.assertTrue(all(not d['eligible'] for d in decisions([], rows)))

    def test_initial_existing_unpriced_not_automatically_new(self):
        self.assertEqual(decisions([row()], [row()])[0]['kind'], 'existing_unpriced')


class IDTests(unittest.TestCase):
    def test_missing_id_rejected(self):
        with self.assertRaises(ReviewRequired):
            validate_rows([row(row_id='')])

    def test_duplicate_id_rejected(self):
        with self.assertRaises(ReviewRequired):
            validate_rows([row(), row(row=9)])

    def test_assign_only_empty_ids(self):
        original = row()
        edits = plan_row_ids([original, row(4,row_id='')])
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]['row'], 4)
        self.assertEqual(original['row_id'], row()['row_id'])

    def test_second_id_pass_is_noop_after_persistence(self):
        r = row(row_id='')
        r['row_id'] = plan_row_ids([r])[0]['row_id']
        self.assertEqual(plan_row_ids([r]), [])

    def test_copied_duplicate_id_is_not_silently_replaced(self):
        with self.assertRaises(ReviewRequired):
            plan_row_ids([row(), row(row=5)])

    def test_writeback_follows_id_after_sort(self):
        self.assertEqual(locate_writeback([row(row=99)], row()), 99)

    def test_writeback_does_not_follow_deleted_row_number(self):
        with self.assertRaises(ReviewRequired):
            locate_writeback([row(5,row=3)], row())

    def test_writeback_rejects_changed_feedback_or_cost(self):
        for changed in (row(latest_feedback='changed'), row(cost=5)):
            with self.assertRaises(ReviewRequired):
                locate_writeback([changed], row())


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'state.sqlite', clock=lambda:1000)
        self.store.initialise('tracker', [], history_reconciled=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_baseline_must_be_explicit_and_reconciled(self):
        with self.assertRaises(ReviewRequired):
            self.store.initialise('other', [row()])

    def test_baseline_cannot_be_silently_reset(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.initialise('tracker', [], history_reconciled=True)

    def test_preview_never_submits(self):
        p = self.store.preview('tracker', [row()])
        self.assertTrue(p['decisions'][0]['eligible'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM active').fetchone()[0], 0)

    def test_exact_selection_two_at_once(self):
        rows = [row(),row(4,pack_safe=False),row(5)]
        p = self.store.preview('tracker', rows)
        submit = Mock(return_value={'task_id':'task'})
        self.store.dispatch(p['plan_id'], rows, submit)
        self.assertEqual({r['row'] for r in submit.call_args.args[0]}, {3,5})
        self.assertEqual(submit.call_args.kwargs['at_once'],2)

    def test_double_click_does_not_double_submit(self):
        p = self.store.preview('tracker', [row()])
        submit = Mock(return_value={'task_id':'task'})
        self.store.dispatch(p['plan_id'], [row()], submit)
        with self.assertRaises(ReviewRequired):
            self.store.dispatch(p['plan_id'], [row()], submit)
        self.assertEqual(submit.call_count,1)

    def test_changed_snapshot_refused_before_submit(self):
        p = self.store.preview('tracker', [row()])
        submit = Mock()
        with self.assertRaises(ReviewRequired):
            self.store.dispatch(p['plan_id'], [row(quantity=3)], submit)
        submit.assert_not_called()

    def test_expired_preview_refused(self):
        p = self.store.preview('tracker', [row()])
        self.store.clock = lambda:2000
        with self.assertRaises(ReviewRequired):
            self.store.dispatch(p['plan_id'], [row()], Mock())

    def test_submission_exception_stays_blocked(self):
        p = self.store.preview('tracker', [row()])
        with self.assertRaises(ReviewRequired):
            self.store.dispatch(p['plan_id'], [row()], Mock(side_effect=TimeoutError()))
        later = self.store.preview('tracker', [row()])
        self.assertFalse(later['decisions'][0]['eligible'])
        with self.assertRaises(ReviewRequired):
            self.store.dispatch(p['plan_id'], [row()], Mock())

    def test_missing_submission_receipt_stays_blocked(self):
        p = self.store.preview('tracker', [row()])
        with self.assertRaises(ReviewRequired):
            self.store.dispatch(p['plan_id'], [row()], Mock(return_value={}))
        self.assertFalse(self.store.preview('tracker',[row()])['decisions'][0]['eligible'])

    def test_two_portals_share_one_claim(self):
        other = Store(self.store.path, clock=lambda:1000)
        p1 = self.store.preview('tracker',[row()])
        p2 = other.preview('tracker',[row()])
        submit = Mock(return_value={'task_id':'task'})
        self.store.dispatch(p1['plan_id'],[row()],submit)
        with self.assertRaises(ReviewRequired):
            other.dispatch(p2['plan_id'],[row()],submit)
        self.assertEqual(submit.call_count,1)

    def test_simultaneous_claims_only_submit_once(self):
        other = Store(self.store.path, clock=lambda:1000)
        plans = [self.store.preview('tracker',[row()]), other.preview('tracker',[row()])]
        barrier = threading.Barrier(2)
        calls, errors = [], []
        def attempt(store, plan):
            barrier.wait()
            try:
                store.dispatch(plan['plan_id'],[row()],
                               lambda selected,**kw: (calls.append(kw) or {'task_id':'task'}))
            except ReviewRequired as exc:
                errors.append(str(exc))
        threads = [threading.Thread(target=attempt,args=(store,plan))
                   for store,plan in zip([self.store,other],plans)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(len(calls),1)
        self.assertEqual(len(errors),1)

    def test_finished_result_prevents_rerun(self):
        p = self.store.preview('tracker',[row()])
        self.store.dispatch(p['plan_id'],[row()],Mock(return_value={'task_id':'task'}))
        self.store.finish(p['plan_id'], {row()['row_id']:{'state':'completed_pending_write','run_id':'run'}})
        self.assertEqual(self.store.preview('tracker',[row()])['decisions'][0]['kind'],'unchanged_completed')

    def test_partial_completion_does_not_release_batch(self):
        rows = [row(),row(4)]
        p = self.store.preview('tracker',rows)
        self.store.dispatch(p['plan_id'],rows,Mock(return_value={'task_id':'task'}))
        with self.assertRaises(ReviewRequired):
            self.store.finish(p['plan_id'],{row()['row_id']:{'state':'completed','run_id':'run'}})
        self.assertTrue(all(not d['eligible'] for d in self.store.preview('tracker',rows)['decisions']))

    def test_confirmed_non_submission_released_but_not_auto_retried(self):
        p = self.store.preview('tracker',[row()])
        with self.assertRaises(ReviewRequired):
            self.store.dispatch(p['plan_id'],[row()],Mock(side_effect=TimeoutError()))
        with self.assertRaises(ReviewRequired):
            self.store.finish(p['plan_id'],{row()['row_id']:{'state':'not_submitted'}})
        self.store.finish(p['plan_id'],{row()['row_id']:{'state':'not_submitted','evidence':'Reviewed task journal: rejected before dispatch'}})
        self.assertEqual(self.store.preview('tracker',[row()])['decisions'][0]['kind'],'held_previous_attempt')


if __name__ == '__main__':
    unittest.main(verbosity=2)
