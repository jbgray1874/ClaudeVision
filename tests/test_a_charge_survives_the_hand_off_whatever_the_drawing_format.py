"""Same downstream protections for every reader; deliberately broken hand-offs.

Format labels exercise reader independence, not end-to-end CAD/PDF extraction.
From the reviewer's all-formats package of 24 Oct (D-598d); runs under the project suite.
"""
import ast
import copy
import math
from pathlib import Path
import unittest

import supplier_reference as sr
from charge_transfer_policy import preserve_run_rate, quantity_charge_coverage


class Identity(unittest.TestCase):
    def test_service_cannot_become_its_member_for_any_reader(self):
        for fmt in ('pdf_text', 'pdf_image', 'dxf', 'step', 'solidworks', 'llm', 'mixed'):
            for marker in ({'line_kind': 'service'}, {'_plating_placeholder': True},
                           {'commercial_line': {'code': 'SERVICE'}}, {'_commercial_line': True},
                           {'_plater_freight': True}):
                with self.subTest(fmt=fmt, marker=marker):
                    rows = [{'part_number': 'MEMBER123', 'description': 'Tube', 'source_format': fmt},
                            {'part_number': 'SERVICE456', 'description': 'MEMBER123 plating',
                             'source_format': fmt, **marker}]
                    self.assertEqual(sr.same_article_groups(rows), [])

    def test_relationship_is_not_an_alias(self):
        for phrase in ('Weld to MEMBER123', 'Fits MEMBER123', 'Plate MEMBER123', 'For MEMBER123'):
            self.assertEqual(sr.same_article_groups([
                {'part_number': 'MEMBER123'}, {'part_number': 'OTHER123', 'description': phrase}]), [])

    def test_empty_references_do_not_merge(self):
        self.assertEqual(sr.same_article_groups([
            {'part_number': 'A', 'supplier_references': [{'reference': ''}]},
            {'part_number': 'B', 'supplier_references': [{'reference': ''}]}]), [])

    def test_explicit_article_and_legacy_leading_alias_survive(self):
        self.assertEqual(sr.same_article_groups([
            {'part_number': 'FIXING1081'},
            {'part_number': 'FOOT', 'description': 'FIXING1081-M8 foot'}]), [[0, 1]])
        rows = [{'part_number': p, 'supplier_references': [{'reference': 'CA123456'}]} for p in ('A','B')]
        self.assertEqual(sr.same_article_groups(rows), [[0, 1]])

    def test_indices_are_not_shifted_by_bad_rows(self):
        rows = [None, {'part_number': 'A', 'supplier_references': [{'reference': 'CA123456'}]},
                {'part_number': 'B', 'supplier_references': [{'reference': 'CA123456'}]}]
        self.assertEqual(sr.same_article_groups(rows), [[1, 2]])


class Timing(unittest.TestCase):
    def test_valid_fast_and_slow_times_survive(self):
        for quantity, seconds in ((1, 8), (2, 16), (1, 2400)):
            hours = seconds / 3600
            self.assertTrue(preserve_run_rate(quantity, hours, quantity/hours))

    def test_unknown_batch_or_invalid_time_is_not_promoted(self):
        for bad in (None, True, 0, -1, '0.1', math.inf, math.nan):
            self.assertFalse(preserve_run_rate(1, bad, 30))
        self.assertFalse(preserve_run_rate(1, 8/3600, 30))

    def test_actual_writer_branch_preserves_and_flags(self):
        # Execute the real writer conditional, not a duplicate of its decisions.
        tree = ast.parse(Path(sr.__file__).with_name('wb_populate.py').read_text(encoding='utf-8'))
        branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                      and ast.unparse(n.test) == 'default_tp and wb_op in _STATED_THROUGHPUT_ROWS')
        for stated in (False, True):
            flags, inputs = [], []
            env = dict(default_tp=30, wb_op='Any department', _STATED_THROUGHPUT_ROWS={'Any department'} if stated else set(),
                       _derived=450., _qty=1, _rhpu=8/3600, throughput=450.,
                       _THROUGHPUT_CEILING_MULTIPLIER=5, _THROUGHPUT_FLOOR_DIVISOR=5,
                       _flag=lambda text, sink: sink.append(text), flags=flags, _inputs=inputs,
                       g={'parts': ['MEMBER123']}, row=100)
            exec(compile(ast.Module(body=[branch], type_ignores=[]), '<writer branch>', 'exec'), env)
            self.assertEqual(env['throughput'], 30 if stated else 450)
            self.assertEqual(bool(inputs), not stated)


class BreakCoverage(unittest.TestCase):
    def fixtures(self):
        req = [{'part_id': 'SHEET-A', 'qty_per_product': 2}]
        snapshots = {str(q): {'calculated': True, 'workbook_sha256': 'paired-hash', 'rows': [
            {'part_id': 'SHEET-A', 'qty_per_product': 2, 'basis': 'per_finished_product',
             'charged_cell': 'Estimate!M93', 'charge_gbp_per_product': .54}]} for q in (1,1000)}
        return req, snapshots

    def test_sheet_outside_bom_table_can_be_charged(self):
        req, snapshots = self.fixtures()
        self.assertTrue(quantity_charge_coverage(req, snapshots, [1,1000])['passed'])

    def test_missing_duplicate_wrong_quantity_and_zero_never_pass(self):
        for mutation in ('missing', 'duplicate', 'order_quantity', 'zero', 'text', 'unpaired'):
            req, snapshots = self.fixtures()
            snap = snapshots['1000']; row = snap['rows'][0]
            if mutation == 'missing': snap['rows'] = []
            if mutation == 'duplicate': snap['rows'].append(copy.deepcopy(row))
            if mutation == 'order_quantity': row['qty_per_product'] = 2000
            if mutation == 'zero': row['charge_gbp_per_product'] = 0
            if mutation == 'text': row['charge_gbp_per_product'] = '0.54'
            if mutation == 'unpaired': snap.pop('workbook_sha256')
            self.assertFalse(quantity_charge_coverage(req, snapshots, [1,1000])['passed'], mutation)

    def test_missing_population_or_snapshot_is_not_success(self):
        self.assertFalse(quantity_charge_coverage([], {}, [1])['passed'])
        req, _ = self.fixtures()
        self.assertFalse(quantity_charge_coverage(req, {}, [1,1000])['passed'])

    def test_table_placement_is_explicitly_not_charge_acceptance(self):
        from openpyxl import Workbook
        from material_price_break import write_price_breaks
        wb = Workbook(); wb.active.title = 'Estimate'; wb.create_sheet('Material Price Break')
        result = write_price_breaks(wb, [{'sheet_row':93, 'code':'SHEET-A', 'unit_gbp':.27}], [1,1000])
        self.assertEqual(result['coverage'][0]['status'], 'not_in_price_table')
        self.assertFalse(result['coverage'][0]['charge_verified'])


if __name__ == '__main__':
    unittest.main()
