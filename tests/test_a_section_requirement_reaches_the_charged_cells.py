"""A section requirement reaches the charged cells of the calculated workbook: one material
row at this quantity, a positive charge whose arithmetic holds, a cutting row with hours on
it, and the saved file's own cached cells agreeing — or the book says which did not (D-578).

The contract and its proofs as proposed in the Codex review package of 21 Oct 2026 (final
charge contract), merged: its findings reach the same BLOCKING invariant as the section
contract's earlier stages, the engine's own classifier loop is exercised as written, and
nothing here names a job.
"""
from __future__ import annotations

import ast
import copy
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import final_charge_contract as c  # noqa: E402


def fixture():
    return {"section_coverage_contract": {"requirements": [{"part": "BASE", "source": {"page": 2}}]},
            "manufacturing_writeup": {"parts": [{"part_number": "BASE"}]},
            "estimate_summary": {"canonical_part_estimates": [{"part_number": "BASE", "quantity": 2,
                                  "material_estimate": {"unit_material_cost_gbp": 3.71}}]},
            "workbook_labour": {"rows": [{"workbook_row":162, "engine_operations":["saw"], "part_numbers":["BASE","OTHER"]}]},
            "final_estimate": {"source": "excel_calculated", "totals": {"material_gbp": 7.42, "labour_gbp": 5},
                "material_rows": [{"part_code": "BASE", "qty_per_unit": 2, "unit_price_gbp": 3.71,
                                   "total_value_gbp": 7.42, "charged_cell": "Estimate!M12"}],
                "labour_rows": [{"workbook_row":162,"part_numbers": "BASE, OTHER", "department": "SAW", "batch_hours": 0.1,
                                 "total_value_gbp": 5, "charged_cell": "Estimate!M162"}]}}


class FinalCharges(unittest.TestCase):
    def setUp(self): self.s = fixture()
    def codes(self): return {i["code"] for i in c.audit(self.s)["issues"]}
    def test_good_charge(self): self.assertTrue(c.audit(self.s)["passed"])
    def test_missing_material_even_with_engine_price(self):
        self.s["final_estimate"]["material_rows"] = []
        self.assertIn("section_material_row_missing_or_duplicate", self.codes())
    def test_zero_charge(self):
        self.s["final_estimate"]["material_rows"][0]["total_value_gbp"] = 0
        self.assertIn("section_material_not_charged", self.codes())
    def test_quantity_lost(self):
        self.s["final_estimate"]["material_rows"][0]["qty_per_unit"] = 1
        self.assertIn("section_charged_quantity_mismatch", self.codes())
    def test_fraction_not_rounded(self):
        self.s["estimate_summary"]["canonical_part_estimates"][0]["quantity"] = 2.192
        self.assertIn("section_charged_quantity_mismatch", self.codes())
    def test_duplicate_material(self):
        self.s["final_estimate"]["material_rows"] *= 2
        self.assertIn("section_material_row_missing_or_duplicate", self.codes())
    def test_no_substring_match(self):
        self.s["final_estimate"]["material_rows"][0]["part_code"] = "BASE-H"
        self.assertIn("section_material_row_missing_or_duplicate", self.codes())
    def test_positive_cell_is_not_enough(self):
        self.s["final_estimate"]["material_rows"][0]["total_value_gbp"] = 1
        self.assertIn("section_charge_arithmetic_mismatch", self.codes())
    def test_no_double_waste(self):
        self.assertTrue(c.audit(self.s)["passed"])
    def test_explicit_scrap(self):
        row = self.s["final_estimate"]["material_rows"][0]
        row.update(scrap_pct=0.04, total_value_gbp=7.42*1.04)
        self.s["final_estimate"]["totals"]["material_gbp"] = row["total_value_gbp"]
        self.assertTrue(c.audit(self.s)["passed"])
    def test_break_price_not_engine_price(self):
        row = self.s["final_estimate"]["material_rows"][0]
        row.update(unit_price_gbp=2, total_value_gbp=4)
        self.s["final_estimate"]["totals"]["material_gbp"] = 4
        self.assertTrue(c.audit(self.s)["passed"])
    def test_missing_cut(self):
        self.s["final_estimate"]["labour_rows"] = []
        self.assertIn("section_cut_not_charged", self.codes())
    def test_wrong_part_cut(self):
        self.s["final_estimate"]["labour_rows"][0]["part_numbers"] = "BASE-H"
        self.assertIn("section_cut_not_charged", self.codes())
    def test_zero_cut_cost(self):
        self.s["final_estimate"]["labour_rows"][0]["total_value_gbp"] = 0
        self.assertIn("section_cut_not_charged", self.codes())
    def test_missing_readback(self):
        self.s.pop("final_estimate")
        self.assertIn("calculated_workbook_missing", self.codes())
    def test_adapter_error(self):
        self.s["final_estimate"]["adapter_problems"] = ["header missing"]
        self.assertIn("workbook_readback_incomplete", self.codes())
    def test_null_not_zero(self):
        self.s["final_estimate"]["material_rows"][0]["total_value_gbp"] = None
        self.assertIn("calculated_value_missing", self.codes())
    def test_nonfinite(self):
        self.s["final_estimate"]["material_rows"][0]["total_value_gbp"] = float('nan')
        self.assertIn("calculated_value_missing", self.codes())
    def test_missing_address(self):
        self.s["final_estimate"]["material_rows"][0].pop("charged_cell")
        self.assertIn("charged_cell_missing_or_repeated", self.codes())
    def test_mismatched_total(self):
        self.s["final_estimate"]["totals"]["material_gbp"] = 0
        self.assertIn("charged_rows_do_not_reconcile", self.codes())
    def test_actual_cell_snapshot(self):
        snap = {"sha256": "x", "cells": {"Estimate!M12": 7.42, "Estimate!M162": 5,
                 'Estimate!C147':'Total Material Cost','Estimate!M147':7.42,
                 'Estimate!C223':'Total Labour Cost','Estimate!M223':5,
                 'Estimate!H12':'BASE','Estimate!K10':'Qty Per Unit','Estimate!K12':2,
                 'Estimate!F162':'BASE, OTHER'}}
        self.assertTrue(c.audit(self.s, snap)["passed"])
        snap["cells"]["Estimate!M12"] = None
        self.assertIn("saved_cell_differs_from_readback", {i["code"] for i in c.audit(self.s, snap)["issues"]})
    def test_missing_file_fails_closed(self):
        self.assertFalse(c.record(self.s, 'not-a-file.xlsx')["passed"])
    def test_cached_pass_not_reused(self):
        self.s["final_charge_result"] = {"passed": True, "issues": []}
        self.assertFalse(c.record(self.s)["passed"])
    def test_no_requirements_no_new_gate(self):
        self.s["section_coverage_contract"] = {}
        self.assertFalse(c.audit(self.s)["applicable"])
    def test_no_mutation(self):
        before = copy.deepcopy(self.s); c.audit(self.s); self.assertEqual(self.s, before)
    def test_text_and_boolean_not_cached_money(self):
        self.assertIsNone(c.cached_number('7.42'))
        self.assertIsNone(c.cached_number(True))
    def test_formula_without_cache_is_not_money(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.xlsx'
            with ZipFile(path,'w') as z:
                z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Estimate" r:id="r1"/></sheets></workbook>')
                z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
                z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><f>2*3</f></c><c r="B1"><f>2*3</f><v>6</v></c><c r="C1" t="e"><v>#VALUE!</v></c></row></sheetData></worksheet>')
            snap=c.snapshot_xlsx(path)
            self.assertIsNone(snap['cells']['Estimate!A1'])
            self.assertEqual(snap['cells']['Estimate!B1'],6)
            self.assertIsNone(c.cached_number(snap['cells']['Estimate!C1']))
    def test_explicit_children(self):
        self.s['manufacturing_writeup']['parts'] = [{"part_number": "MEMBER", "cut_list_member_of": "BASE"}]
        self.s['estimate_summary']['canonical_part_estimates'][0]['part_number'] = 'MEMBER'
        self.s['final_estimate']['material_rows'][0]['part_code'] = 'MEMBER'
        self.s['final_estimate']['labour_rows'][0]['part_numbers'] = 'MEMBER'
        self.s['workbook_labour']['rows'][0]['part_numbers'] = ['MEMBER']
        self.assertTrue(c.audit(self.s)["passed"])


def classify(part, kinds=None, children=False, source=None):
    """Execute the actual classifier loop AST, isolated from COM/network/workbook writes."""
    source = source or ROOT / 'src' / 'wb_populate.py'
    tree = ast.parse(Path(source).read_text(encoding='utf-8'))
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.For) and
                ast.unparse(n.target) == 'pe' and ast.unparse(n.iter) == 'pes' and
                'name_is_assembly' in ast.unparse(n))
    env = dict(pes=[part], summary={}, _canonical_kinds=kinds or {}, re=re,
               _safe=lambda v, *a: c.number(v), STEEL_STOCK_FORMS={'sheet','stated_weight'},
               DROP_CODES={'PACKAGING','DELIVERY'}, bom_parts=[], steel_parts=[],
               board_parts=[], weldment_parts=[], wire_parts=[], excluded=[], flags=[],
               _has_children_to_carry_it=lambda *a: children,
               _line_is_its_own_section_stock=__import__("wb_populate")._line_is_its_own_section_stock,
               _flag=lambda *a: None)
    exec(compile(ast.Module(body=[loop], type_ignores=[]), str(source), 'exec'), env)
    return {k: env[k] for k in ('bom_parts','weldment_parts','excluded')}


class Classifier(unittest.TestCase):
    def part(self):
        return {'part_number':'BASE', 'description':'BASE WELDMENT', 'quantity':2,
                'material_estimate':{'stock_form':'tube','unit_material_cost_gbp':3.71}}
    def test_childless_weldment_goes_to_bom(self):
        self.assertEqual(len(classify(self.part())['bom_parts']),1)
    def test_real_assembly_still_excluded(self):
        self.assertEqual(len(classify(self.part(), {'BASE':'assembly'})['excluded']),1)
    def test_child_rollup_still_excluded(self):
        self.assertEqual(len(classify(self.part(), children=True)['excluded']),1)
    def test_suppression_not_bypassed(self):
        p=self.part();p['material_estimate']['reliability_flags']=['weldment_parent_material_suppressed']
        self.assertEqual(len(classify(p)['weldment_parts']),1)


if __name__ == '__main__': unittest.main()
