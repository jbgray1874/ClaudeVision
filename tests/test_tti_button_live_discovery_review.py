"""Review-package regressions: real resolver and filesystem, no CAD share or live service.

PDF text is injected so the fixture needs no commercial CAD/PDF reader. Folder enumeration,
member selection, fingerprinting, workbook parsing and durable reservations use real code.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'sdi-intelligence-backend')]
import drawing_index as di
import pack_resolver as pr
import tti_tracker_source as source
import tti_changes as changes
from tti_incremental import Store, ReviewRequired, decisions


def row(n=3, **kw):
    result = dict(row_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f'review-{n}')), row=n,
                  drawing=f'12181-0{n}-GA', quantity=3, description='Demo',
                  previous_feedback='', latest_feedback='', revision='A', pack_key='old',
                  pack_state='ready', pack_safe=True, method='both', client='TTI',
                  cost=None, holds=[], history=None)
    result.update(kw)
    return result


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.design = self.root / 'Design' / 'TTI'
        self.proto = self.root / 'Prototype' / 'TTI'
        self.design.mkdir(parents=True)
        self.proto.mkdir(parents=True)
        self.areas = [('Design', self.design), ('Prototype', self.proto)]
        self.addCleanup(pr.forget_job_folders)
        # Any accidental use of the persistent index fails the test immediately.
        for name in ('load', 'db_lookup', 'db_rows_for', 'build_db'):
            guard = patch.object(di, name, side_effect=AssertionError('Index access forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def file(self, root, name, body='drawing fixture'):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding='utf8')
        return p

    def design_pack(self):
        folder = self.design / '12181 - Demo' / '12181-Technical'
        self.file(folder, '12181-00-GA_REV A.PDF')
        self.file(folder, '12181-00-GA.SLDASM')
        self.file(folder / '12181-01 Frame', '12181-01-01J.SLDPRT')
        self.file(folder / '12181-01 Frame', '12181-01-01J.DXF')
        return folder

    def lookup(self):
        return source.live_pack_lookup(areas=self.areas,
                                      read_text=lambda p: '12181-00-GA REV A 12181-01-01J')

    def test_real_resolver_finds_design_models_and_parts_without_any_index(self):
        folder = self.design_pack()
        self.file(self.proto / 'Rome 2026' / '12181 - Demo', '12181-00-GA_REV A.PDF')
        got = self.lookup()('12181-00-GA')
        self.assertEqual(got['state'], 'ready', got)
        self.assertEqual(got['evidence']['selected_folder'], str(folder))
        names = {Path(f['path']).suffix for f in got['evidence']['files']}
        self.assertTrue({'.sldasm', '.sldprt', '.pdf', '.dxf'} <= names)
        self.assertIn('Design: 1 folder(s)', got['evidence']['looked'])

    def test_newer_prototype_revision_holds_instead_of_silently_using_design(self):
        self.design_pack()
        self.file(self.proto / 'Rome 2026' / '12181 - Demo', '12181-00-GA_REV B.PDF')
        got = self.lookup()('12181-00-GA')
        self.assertEqual(got['state'], 'held')
        self.assertIn('revision B', ' '.join(got['holds']))

    def test_prototype_is_allowed_only_after_design_was_read(self):
        self.file(self.design / '12181 - Demo', '12181-99-GA.PDF')
        folder = self.proto / 'Rome 2026' / '12181 - Demo'
        self.file(folder, '12181-00-GA_REV A.PDF')
        got = self.lookup()('12181-00-GA')
        self.assertEqual(got['state'], 'ready')
        self.assertEqual(got['evidence']['selected_folder'], str(folder))
        self.assertIn('holds NO file named for the drawing', got['evidence']['looked'])

    def test_unreadable_design_holds_even_with_prototype_pack(self):
        self.file(self.proto / '12181 - Demo', '12181-00-GA.PDF')
        self.design.rmdir()
        got = self.lookup()('12181-00-GA')
        self.assertEqual(got['state'], 'held')
        self.assertIn('Design', got['holds'][0])
        self.assertEqual(got['key'], '')

    def test_timeout_is_a_hold_not_a_missing_pack(self):
        with patch.object(pr, 'rows_for_job_now', side_effect=pr.PackCheckStalled('share timed out')):
            got = self.lookup()('12181-00-GA')
        self.assertEqual(got['state'], 'held')
        self.assertIn('timed out', got['holds'][0])

    def test_unrelated_job_prefix_is_not_selected(self):
        self.design_pack()
        got = self.lookup()('1218-00-GA')
        self.assertEqual(got['state'], 'missing')

    def test_changed_child_file_changes_pack_key_even_if_ga_is_unchanged(self):
        folder = self.design_pack()
        a = self.lookup()('12181-00-GA')
        child = folder / '12181-01 Frame' / '12181-01-01J.SLDPRT'
        child.write_text('changed part, same GA', encoding='utf8')
        b = self.lookup()('12181-00-GA')
        self.assertNotEqual(a['key'], b['key'])

    def test_next_snapshot_sees_new_job_folder_and_new_drawings(self):
        a = self.lookup()('12181-00-GA')
        self.design_pack()
        b = self.lookup()('12181-00-GA')
        self.assertEqual(a['state'], 'missing')
        self.assertEqual(b['state'], 'ready')

    def test_same_snapshot_reuses_discovery_but_does_not_return_mutable_cache(self):
        self.design_pack()
        lookup = self.lookup()
        with patch.object(pr, 'rows_for_job_now', wraps=pr.rows_for_job_now) as call:
            a = lookup('12181-00-GA')
            a['holds'].append('test mutation')
            b = lookup('12181-00-GA')
        self.assertEqual(call.call_count, 1)
        self.assertEqual(b['holds'], [])

    def test_no_cad_file_is_changed_by_discovery(self):
        self.design_pack()
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.lookup()('12181-00-GA')
        after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_conflicting_manifest_is_held(self):
        m = dict(status='ambiguous', price_ok=False, conflicts=['same revision differs'],
                 question='Which copy?', members=[])
        got = source.resolved_pack(m, 'looked live')
        self.assertEqual(got['state'], 'held')
        self.assertEqual(got['holds'], ['Which copy?'])

    def test_pack_key_is_independent_of_member_order_and_scan_time(self):
        self.design_pack()
        folders, said, first = pr.rows_for_job_now('12181-00-GA', self.areas)
        m = pr.resolve('12181-00-GA', folders, client='TTI', read_text=lambda p: '12181-00-GA REV A',
                       area_rank=lambda p: 0 if str(p) in first else 1)
        a = source.resolved_pack(m, said)
        m['members'].reverse()
        m['resolved_at'] = 'different time'
        b = source.resolved_pack(m, 'different timing')
        self.assertEqual(a['key'], b['key'])

    def test_file_list_compatibility_detects_changes_within_a_minute(self):
        self.assertNotEqual(source.pack_of([('a.pdf', 10, 6000.1)]),
                            source.pack_of([('a.pdf', 10, 6000.2)]))

    def test_real_workbook_rows_use_live_pack_and_preserve_ids_and_feedback(self):
        import openpyxl
        self.design_pack()
        book = openpyxl.Workbook()
        ws = book.active
        ws.title = 'Milwaukee'
        ws.append(['Description', 'Quantity', 'Drawing Number', 'Previous Feedback',
                   'Latest Feedback', 'AI Cost', 'AI Row ID'])
        ident = str(uuid.uuid4())
        ws.append(['Demo', 3, '12181-00-GA', 'old note', 'new note', None, ident])
        path = self.root / 'tracker.xlsx'
        book.save(path)
        before = path.read_bytes()
        got = source.tracker_rows(path, 'Milwaukee', pack_lookup=self.lookup())['rows'][0]
        self.assertEqual((got['row_id'], got['quantity']), (ident, 3))
        self.assertEqual((got['previous_feedback'], got['latest_feedback']), ('old note', 'new note'))
        self.assertTrue(got['pack_safe'])
        self.assertEqual(got['revision'], 'A')
        self.assertEqual(path.read_bytes(), before)

    def test_held_out_drawing_does_not_start_a_pack_search(self):
        import openpyxl
        book = openpyxl.Workbook()
        ws = book.active
        ws.append(['Description', 'Quantity', 'Drawing Number', 'AI Cost', 'AI Row ID',
                   'Previous Feedback', 'Latest Feedback'])
        ws.append(['Held', 3, '12748-01-GA', None, str(uuid.uuid4()), '', ''])
        path = self.root / 'held.xlsx'
        book.save(path)
        got = source.tracker_rows(path, hold_out=['12748-01-GA'],
                                  pack_lookup=lambda d: self.fail('held drawing was searched'))['rows'][0]
        self.assertFalse(got['pack_safe'])
        self.assertTrue(any('SDI_TTI_HOLD_OUT' in h for h in got['holds']))

    def test_requested_revision_must_match_selected_pack(self):
        import openpyxl
        self.design_pack()
        book = openpyxl.Workbook()
        ws = book.active
        ws.append(['Description', 'Quantity', 'Drawing Number', 'AI Cost', 'AI Row ID',
                   'Previous Feedback', 'Latest Feedback'])
        ws.append(['Demo', 3, '12181-00-GA REV B', None, str(uuid.uuid4()), '', ''])
        path = self.root / 'revision.xlsx'
        book.save(path)
        got = source.tracker_rows(path, pack_lookup=self.lookup())['rows'][0]
        self.assertFalse(got['pack_safe'])
        self.assertTrue(any('revision B' in h and 'revision is A' in h for h in got['holds']))

    def test_main_uses_live_reader_not_index_lookup(self):
        path = self.root / 'snapshot.xlsx'
        path.write_bytes(b'placeholder')
        out = self.root / 'result.json'
        with patch.object(source, 'snapshot', return_value=path), \
             patch.object(source, 'live_pack_lookup', return_value=lambda d: {}) as provider, \
             patch.object(source, 'tracker_rows', return_value={'rows': []}) as reader:
            code = source.main(['--master', str(path), '--json-out', str(out)])
        self.assertEqual(code, 0)
        provider.assert_called_once_with(client='TTI')
        self.assertIn('pack_lookup', reader.call_args.kwargs)
        self.assertIn('no index', json.loads(out.read_text())['discovery'])


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state.sqlite')
        self.old = row()
        self.new = row(4)
        self.store.initialise('master', [self.old], history_reconciled=True)
        self.plan = self.store.preview('master', [self.old, self.new])
        self.store.dispatch(self.plan['plan_id'], [self.old, self.new],
                            lambda *a, **k: {'task_id': changes.task_id_for(self.plan['plan_id'])})

    def reconcile(self, status):
        return changes.make_reconcile(self.store, lambda tid: status, lambda: None)('master')

    def assert_held(self):
        self.assertIsNotNone(self.store.active_plan('master'))
        p = self.store.preview('master', [self.old, self.new])
        self.assertFalse(any(d['eligible'] for d in p['decisions']))

    def test_timed_out_post_without_run_id_keeps_reservation(self):
        message = self.reconcile({'finished': 'now', 'rows': [
            {'row': 4, 'state': 'not queued', 'why': 'portal did not answer (timed out)'}]})
        self.assertIn('uncertain', message)
        self.assert_held()

    def test_missing_status_and_dead_batch_are_not_proof_of_non_submission(self):
        self.assertIn('reservation stays held', self.reconcile(None))
        self.assert_held()

    def test_running_job_is_not_recorded_as_failed_when_batch_exits(self):
        self.reconcile({'finished': 'now', 'rows': [{'row': 4, 'state': 'running', 'run_id': 'accepted'}]})
        self.assert_held()

    def test_timeout_with_run_id_still_needs_reconciliation(self):
        self.reconcile({'finished': 'now', 'rows': [{'row': 4, 'state': 'timeout', 'run_id': 'accepted'}]})
        self.assert_held()

    def test_success_without_tracker_write_is_pending_write_not_new_work(self):
        message = self.reconcile({'finished': 'now', 'rows': [
            {'row': 4, 'state': 'done', 'run_id': 'accepted', 'unit_cost': 12.0}]})
        self.assertIn('1 of 1', message)
        self.assertIsNone(self.store.active_plan('master'))
        p = self.store.preview('master', [self.old, self.new])
        self.assertFalse(any(d['eligible'] for d in p['decisions']))

    def test_explicit_pre_submission_hold_can_release_with_evidence(self):
        self.reconcile({'finished': 'now', 'rows': [{'row': 4, 'state': 'needs drawing', 'why': 'not found'}]})
        self.assertIsNone(self.store.active_plan('master'))
        p = self.store.preview('master', [self.old, self.new])
        self.assertFalse(any(d['eligible'] for d in p['decisions']))

    def test_run_switch_remains_off(self):
        self.assertFalse(changes.run_enabled({}))


if __name__ == '__main__':
    unittest.main()
