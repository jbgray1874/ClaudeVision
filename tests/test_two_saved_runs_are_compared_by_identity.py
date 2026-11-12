"""Two saved runs are compared by identity, not by row address (D-579).

Stage 2 of the stability programme: parts by canonical code, material rows by code or the
code their description leads with, routes by the writer's stable route_group_id. A row
that moved is not a change; a quantity that kept its fraction is reported as it is; a
missing total is None, not zero; duplicate or missing identities are warnings, never
overwritten. Observed differences only — nothing here says why. From the Codex stability
package of 22 Oct 2026, merged.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from run_comparison import compare  # noqa: E402

def fixture():
    return {'declared_product':'UNIT','requested_order_quantity':1,
            'estimate_summary':{'canonical_part_estimates':[{'part_number':'A','quantity':3.192}]},
            'workbook_labour':{'rows':[{'route_group_id':'stable','workbook_row':151,'part_numbers':['A'],'engine_operations':['saw']}]},
            'final_estimate':{'source':'excel_calculated','totals':{'material_gbp':6.384},
              'material_rows':[{'part_code':'A','qty_per_unit':3.192,'total_value_gbp':6.384,'charged_cell':'Estimate!M11'}],
              'labour_rows':[{'workbook_row':151,'total_value_gbp':2}]}}

class Comparison(unittest.TestCase):
    def test_identical(self): self.assertEqual(compare(fixture(),fixture())['changes'],[])
    def test_row_move_is_not_cost_change(self):
        a=fixture();b=copy.deepcopy(a);b['workbook_labour']['rows'][0]['workbook_row']=160
        b['final_estimate']['labour_rows'][0]['workbook_row']=160
        b['final_estimate']['material_rows'][0]['charged_cell']='Estimate!M99'
        self.assertEqual(compare(a,b)['changes'],[])
    def test_fraction_retained(self):
        a=fixture();b=copy.deepcopy(a);b['estimate_summary']['canonical_part_estimates'][0]['quantity']=3
        c=compare(a,b)['changes'][0];self.assertEqual(c['before'],3.192);self.assertEqual(c['after'],3)
    def test_duplicate_not_overwritten(self):
        a=fixture();a['final_estimate']['material_rows']*=2
        self.assertTrue(compare(a,a)['warnings']['before'])
    def test_empty_canonical_not_replaced(self):
        a=fixture();b=copy.deepcopy(a);b['estimate_summary']['part_estimates']=b['estimate_summary']['canonical_part_estimates']
        b['estimate_summary']['canonical_part_estimates']=[]
        self.assertTrue(any(c['change']=='removed' for c in compare(a,b)['changes']))
    def test_different_quantity(self):
        a=fixture();b=copy.deepcopy(a);b['requested_order_quantity']=150
        self.assertFalse(compare(a,b)['same_order_quantity'])
    def test_missing_total_not_zero(self): self.assertIsNone(compare(fixture(),fixture())['totals']['unit_gbp']['delta'])
    def test_no_mutation(self):
        a=fixture();b=copy.deepcopy(a);compare(a,a);self.assertEqual(a,b)
    def test_missing_route_charge(self):
        a=fixture();a['final_estimate']['labour_rows']=[]
        self.assertTrue(any(w['code']=='route_charge_missing' for w in compare(a,a)['warnings']['before']))
    def test_price_delta(self):
        a=fixture();b=copy.deepcopy(a);b['final_estimate']['totals']['material_gbp']+=7.42
        self.assertAlmostEqual(compare(a,b)['totals']['material_gbp']['delta'],7.42)

if __name__=='__main__':unittest.main()
