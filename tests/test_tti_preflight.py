"""Synthetic regression tests; no service, live tracker or network calls."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import tti_preflight as p

HEADERS = ['Description', 'Drawing Number', 'Quantity', 'Previous Feedback', 'Latest Feedback - 11/11', 'AiCost']


def values(**changes):
    row = ['Frame', '12345-01-GA', 2, 'Keep blue', 'Use red instead', None]
    for key, val in changes.items():
        row[int(key)] = val
    return [HEADERS[:], row]


def one(data=None):
    return p.rows_from_values(data or values())[0][0]


def good_pack():
    return {'state': 'resolved', 'manifest': {'price_ok': True, 'complete': True,
            'references_read': True, 'identity': 'verified', 'revision': 'A'}}


class TrackerTests(unittest.TestCase):
    def test_positive_integer_quantities(self):
        for raw in (1, 3.0, '12', '12.0'):
            with self.subTest(raw=raw):
                self.assertEqual(p.positive_quantity(raw), int(float(raw)))

    def test_invalid_quantities_are_not_guessed(self):
        for raw in (None, '', 0, -1, 2.5, 'two', 'NaN', 'Infinity', True, '=2+2'):
            with self.subTest(raw=raw):
                self.assertIsNone(p.positive_quantity(raw))

    def test_both_feedbacks_remain_separate_in_brief(self):
        r = one()
        self.assertIn('Previous Feedback:\nKeep blue', r['brief'])
        self.assertIn('Latest Feedback - 11/11:\nUse red instead', r['brief'])

    def test_reordered_columns(self):
        rows = values()
        order = [4, 0, 5, 2, 1, 3]
        r = one([[line[i] for i in order] for line in rows])
        self.assertEqual(r['quantity'], 2)
        self.assertIn('Use red instead', r['brief'])

    def test_missing_feedback_header_fails(self):
        rows = values()
        rows[0][4] = 'Other'
        with self.assertRaises(ValueError):
            p.rows_from_values(rows)

    def test_duplicate_feedback_header_fails(self):
        rows = values()
        rows[0].append('Previous Feedback')
        with self.assertRaises(ValueError):
            p.rows_from_values(rows)

    def test_duplicate_cost_header_fails(self):
        rows = values()
        rows[0].append('AI Cost')
        with self.assertRaises(ValueError):
            p.rows_from_values(rows)

    def test_repeated_headers_are_not_jobs(self):
        rows = values() + [HEADERS[:], [None] * 6]
        self.assertEqual(len(p.rows_from_values(rows)[0]), 1)

    def test_missing_drawing_remains_visible(self):
        r = one(values(**{'1': None}))
        self.assertEqual(r['drawing'], '')
        self.assertTrue(r['holds'])

    def test_multiple_drawing_references_held(self):
        r = one(values(**{'1': '12345-01-GA / 12345-02-GA'}))
        self.assertEqual(len(r['references']), 2)
        self.assertTrue(r['holds'])

    def test_bare_job_number_held(self):
        self.assertTrue(one(values(**{'1': '12345'}))['holds'])

    def test_revision_and_full_scope_preserved(self):
        r = one(values(**{'1': '12345-01-GA REV A (larger graphics)'}))
        self.assertEqual(r['drawing'], '12345-01-GA')
        self.assertIn('(larger graphics)', r['brief'])

    def test_changed_latest_feedback_changes_input_key(self):
        self.assertNotEqual(one()['input_key'], one(values(**{'4': 'Use green'}))['input_key'])

    def test_duplicate_identical_rows_held(self):
        rows = values()
        rows.append(rows[1][:])
        result = p.rows_from_values(rows)[0]
        self.assertTrue(all('Duplicate' in r['holds'][0] for r in result))

    def test_conflicting_feedback_not_silently_deduplicated(self):
        rows = values() + [values(**{'4': 'Different instruction'})[1]]
        result = p.rows_from_values(rows)[0]
        self.assertEqual(len(result), 2)
        self.assertTrue(all(any('Conflicting' in h for h in r['holds']) for r in result))

    def test_different_quantity_grouping_requires_review(self):
        rows = values() + [values(**{'2': 5})[1]]
        self.assertTrue(all(r['holds'] for r in p.rows_from_values(rows)[0]))

    def test_existing_zero_cost_is_not_blank(self):
        self.assertTrue(one(values(**{'5': 0}))['holds'])

    def test_formula_quantity_not_fresh_proof(self):
        result = p.rows_from_values(values(), values(**{'2': '=1+1'}))[0][0]
        self.assertTrue(any('formula-derived quantity' in h for h in result['holds']))

    def test_formula_feedback_held(self):
        r = p.rows_from_values(values(), values(**{'4': '=Sheet2!A1'}))[0][0]
        self.assertTrue(any('feedback' in h for h in r['holds']))

    def test_error_in_feedback_held(self):
        self.assertTrue(one(values(**{'4': '#VALUE!'}))['holds'])

    def test_risks_are_evidence_tagged_not_invented(self):
        risks = p.risk_signals([('Latest Feedback', 'Mirror, steel, welding')])
        self.assertEqual({r['source'] for r in risks}, {'Latest Feedback'})
        self.assertEqual(len(risks), 3)


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.row = one()
        self.row['pack'] = good_pack()

    def test_clean_case_only_candidate_not_approved(self):
        self.assertEqual(p.classify(self.row), 'candidate_for_pilot')

    def test_no_live_check_never_ready(self):
        self.row['pack'] = {'state': 'not_checked'}
        self.assertEqual(p.classify(self.row), 'unchecked')

    def test_price_ok_alone_does_not_prove_complete(self):
        self.row['pack']['manifest']['complete'] = False
        self.assertEqual(p.classify(self.row), 'review_incomplete_pack')

    def test_unread_children_override_complete_flag(self):
        self.row['pack']['manifest']['unread_assemblies'] = ['12345-01-SA01']
        self.assertEqual(p.classify(self.row), 'review_incomplete_pack')

    def test_conflicting_configurations_hold(self):
        self.row['pack']['manifest']['configurations_unconfirmed'] = True
        self.assertEqual(p.classify(self.row), 'hold')

    def test_revision_mismatch_hold(self):
        self.row['drawing_cell'] += ' REV B'
        self.assertEqual(p.classify(self.row), 'hold')
        self.assertTrue(any('revision B' in x for x in p.reasons_for(self.row)))

    def test_risk_flag_requires_review(self):
        self.row['risk_signals'] = p.risk_signals([('feedback', 'welded')])
        self.assertEqual(p.classify(self.row), 'review')


class IOTests(unittest.TestCase):
    def test_index_open_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'index # one.sqlite'
            c = sqlite3.connect(db)
            c.execute('create table meta(k text, v text)')
            c.execute('create table folders(id integer, path text, archive integer)')
            c.execute('create table files(folder integer, name text, size integer, mtime real, did text)')
            c.execute('insert into folders values(1, ?, 0)', ('some folder',))
            c.execute("insert into files values(1,'12345-01-GA.pdf',12,1,'12345-01-GA')")
            c.commit()
            c.close()
            before = p.file_sha256(db)
            matches, _ = p.index_inventory(db, ['12345-01-GA'])
            self.assertEqual(len(matches['12345-01-GA']), 1)
            c = p.open_index(db)
            with self.assertRaises(sqlite3.OperationalError):
                c.execute("insert into meta values('a','b')")
            c.close()
            self.assertEqual(before, p.file_sha256(db))

    def test_missing_index_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'missing.sqlite'
            with self.assertRaises(sqlite3.OperationalError):
                p.open_index(db)
            self.assertFalse(db.exists())

    def test_timeout_is_not_a_pack_success(self):
        with patch.object(p.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 1)):
            result = p.bounded_resolve('.', '.', '12345-01-GA', 'TTI', 1)
        self.assertEqual(result['state'], 'timeout')

    def test_failed_worker_is_reported(self):
        with patch.object(p.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1, stdout='', stderr='denied')):
            self.assertEqual(p.bounded_resolve('.', '.', '12345-01-GA', 'TTI', 1)['state'], 'error')

    def test_malformed_worker_output_is_reported(self):
        with patch.object(p.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout='not json', stderr='')):
            self.assertEqual(p.bounded_resolve('.', '.', '12345-01-GA', 'TTI', 1)['state'], 'error')

    def test_wrong_worker_schema_is_reported(self):
        with patch.object(p.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout='[]', stderr='')):
            self.assertEqual(p.bounded_resolve('.', '.', '12345-01-GA', 'TTI', 1)['state'], 'error')

    def test_worker_resolves_and_checks_selected_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / '12345-01-GA.pdf'
            f.write_bytes(b'synthetic fixture, not a real PDF')
            st = f.stat()
            rows = [(Path(tmp), [(f, st.st_size, st.st_mtime)], False)]
            di = types.SimpleNamespace(db_rows_for=lambda db,d: rows, live_rows=lambda *a,**kw: rows,
                                       db_lookup=lambda db,d: [])
            manifest = good_pack()['manifest']
            manifest['members'] = [{'files': [{'path':str(f), 'size':st.st_size, 'mtime':st.st_mtime}]}]
            pr = types.SimpleNamespace(_same=lambda a,b:a==b, drawing_id=lambda n:'12345-01-GA',
                                       resolve=lambda *a,**kw:manifest)
            with patch.dict(sys.modules, {'drawing_index':di, 'pack_resolver':pr}):
                result = p.worker_resolve('.', 'index', '12345-01-GA', 'TTI')
                self.assertEqual(result['state'], 'resolved')
                self.assertEqual(result['selected_file_count'], 1)
                manifest['members'][0]['files'][0]['size'] += 1
                changed = p.worker_resolve('.', 'index', '12345-01-GA', 'TTI')
                self.assertEqual(changed['state'], 'unavailable')

    def test_csv_formula_injection_escaped(self):
        for value in ('=1+1', ' +1', '@SUM(A1)', '-2'):
            self.assertTrue(p.safe_csv(value).startswith("'"))
        self.assertEqual(p.safe_csv('12345-01-GA'), '12345-01-GA')

    def test_reports_never_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = one()
            r['status'] = p.classify(r)
            report = {'summary': {}, 'rows': [r]}
            p.write_report(report, tmp)
            before = p.file_sha256(Path(tmp) / 'preflight.json')
            with self.assertRaises(FileExistsError):
                p.write_report(report, tmp)
            self.assertEqual(before, p.file_sha256(Path(tmp) / 'preflight.json'))

    def test_workbook_opened_readonly_no_save(self):
        class Sheet:
            max_row, max_column, title = 2, 6, 'Milwaukee'
            def iter_rows(self, **kwargs):
                return iter(values())
        class Book:
            active = Sheet()
            def close(self):
                pass
        with patch('openpyxl.load_workbook', return_value=Book()) as load:
            rows, meta = p.read_tracker('synthetic.xlsx')
        self.assertEqual(len(rows), 1)
        self.assertEqual(load.call_count, 2)
        self.assertTrue(all(c.kwargs['read_only'] for c in load.call_args_list))
        self.assertEqual([c.kwargs['data_only'] for c in load.call_args_list], [True, False])

    def test_worker_denied_share_is_unavailable(self):
        di = types.SimpleNamespace(db_rows_for=lambda db,d: [(Path('folder'), [(Path('12345-01-GA.pdf'),1,1)],False)],
                                   live_rows=lambda *a,**kw: (_ for _ in ()).throw(PermissionError()))
        pr = types.SimpleNamespace(_same=lambda a,b:a==b, drawing_id=lambda name: '12345-01-GA')
        with patch.dict(sys.modules, {'drawing_index': di, 'pack_resolver': pr}):
            result = p.worker_resolve('.', 'index', '12345-01-GA', 'TTI')
        self.assertEqual(result['state'], 'unavailable')


if __name__ == '__main__':
    unittest.main(verbosity=2)


class ResolverManifestShapeTests(unittest.TestCase):
    """The file fields the real resolver gives (15 Nov 2026).

    pack_resolver's manifest lists each file with `modified` (ISO, to the minute) and
    `fingerprint`, and no `mtime`. The worker read `mtime`; on the live share 41 of 76 packs
    reached their files and failed with KeyError, and none was validated."""

    def test_the_manifest_the_resolver_builds_has_modified_and_no_mtime(self):
        import inspect
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import pack_resolver
        source = inspect.getsource(pack_resolver)
        self.assertIn('"modified": datetime.fromtimestamp(m).isoformat(timespec="minutes")', source)

    def test_a_file_listed_by_modified_minute_is_unchanged(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'T-01-GA.pdf'
            f.write_bytes(b'%PDF-1.4 x')
            st = f.stat()
            listed = {'path': str(f), 'size': st.st_size, 'fingerprint': 'sha1:x',
                      'modified': datetime.fromtimestamp(st.st_mtime).isoformat(timespec='minutes')}
            self.assertTrue(p.same_time(st.st_mtime, listed))
            self.assertFalse(p.same_time(st.st_mtime + 3600, listed))

    def test_a_raw_mtime_is_still_compared_and_a_listing_with_neither_is_not_called_changed(self):
        self.assertTrue(p.same_time(1000.2, {'mtime': 1000.0}))
        self.assertFalse(p.same_time(1900.0, {'mtime': 1000.0}))
        self.assertTrue(p.same_time(1000.0, {'size': 3}))
