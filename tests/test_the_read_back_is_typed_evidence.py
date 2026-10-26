"""The workbook read-back is typed evidence, not parser input (D-579).

A string that looks like a number is not a calculated Excel number — SUM ignores it — so
at the final-charge boundary it is a missing value, never money; an explicitly empty
canonical population is evidence of loss, never permission to revive the pre-canonical
one; a duplicate canonical identity is a finding, never a silent overwrite. From the Codex
stability package of 22 Oct 2026, merged.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import final_charge_contract as c  # noqa: E402

def fixture():
    return {'section_coverage_contract':{'requirements':[{'part':'BASE'}]},
      'manufacturing_writeup':{'parts':[{'part_number':'BASE'}]},
      'estimate_summary':{'canonical_part_estimates':[{'part_number':'BASE','quantity':2}]},
      'workbook_labour':{'rows':[{'workbook_row':151,'engine_operations':['saw'],'part_numbers':['BASE']}]},
      'final_estimate':{'source':'excel_calculated','totals':{'material_gbp':6,'labour_gbp':2},
        'material_rows':[{'part_code':'BASE','qty_per_unit':2,'unit_price_gbp':3,'total_value_gbp':6,'charged_cell':'Estimate!M11'}],
        'labour_rows':[{'workbook_row':151,'part_numbers':'BASE','batch_hours':0.1,'total_value_gbp':2,'charged_cell':'Estimate!M151'}]}}

class Boundary(unittest.TestCase):
    def test_good(self): self.assertTrue(c.audit(fixture())['passed'])
    def test_numeric_strings_are_not_readback_money(self):
        for field in ('total_value_gbp','qty_per_unit','unit_price_gbp'):
            with self.subTest(field=field):
                d=fixture();r=d['final_estimate']['material_rows'][0];r[field]=str(r[field])
                self.assertFalse(c.audit(d)['passed'])
    def test_numeric_string_hours_not_charged(self):
        d=fixture();d['final_estimate']['labour_rows'][0]['batch_hours']='0.1'
        self.assertFalse(c.audit(d)['passed'])
    def test_total_string_not_numeric(self):
        d=fixture();d['final_estimate']['totals']['material_gbp']='6'
        self.assertFalse(c.audit(d)['passed'])
    def test_empty_canonical_does_not_revive_parts(self):
        d=fixture();e=d['estimate_summary'];e['part_estimates']=copy.deepcopy(e['canonical_part_estimates']);e['canonical_part_estimates']=[]
        self.assertFalse(c.audit(d)['passed'])
    def test_duplicate_canonical_fails(self):
        d=fixture();d['estimate_summary']['canonical_part_estimates']*=2
        self.assertIn('canonical_part_identity_missing_or_duplicate',{i['code'] for i in c.audit(d)['issues']})
    def test_no_requirements_is_not_applicable(self):
        d=fixture();d['section_coverage_contract']={};self.assertFalse(c.audit(d)['applicable'])

if __name__=='__main__': unittest.main()
