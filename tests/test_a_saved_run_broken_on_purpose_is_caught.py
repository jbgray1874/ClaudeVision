"""A saved run broken on purpose is caught, every way it is broken (D-579).

Stage 1 of the stability programme: the mutation probe takes a passing, applicable baseline
— a saved record and its calculated workbook — and breaks each traced section line nine
ways in memory (material row removed, zeroed, duplicated, re-identified, quantity changed,
cached value missing or text, cut removed, cut hours zeroed), expecting the named finding
each time and changing nothing on disk. A baseline that does not pass, or has nothing to
trace, is no proof at all. From the Codex stability package of 22 Oct 2026, merged.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "diagnose"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

import exercise_final_charge_contract as probe  # noqa: E402
from test_the_read_back_is_typed_evidence import fixture, c  # noqa: E402

def snapshot():
    return {'sha256':'test','cells':{'Estimate!M11':6,'Estimate!M151':2,
      'Estimate!C147':'Total Material Cost','Estimate!M147':6,
      'Estimate!C223':'Total Labour Cost','Estimate!M223':2,
      'Estimate!H11':'BASE','Estimate!K10':'Qty Per Unit','Estimate!K11':2,
      'Estimate!F151':'BASE'}}

class Mutations(unittest.TestCase):
    def test_all_cases_and_no_mutation(self):
        d,s=fixture(),snapshot(); original=copy.deepcopy((d,s))
        out=probe.exercise(c,d,s)
        self.assertTrue(out['passed']); self.assertEqual(len(out['cases']),9)
        self.assertEqual((d,s),original)
    def test_no_requirements_not_a_proof(self):
        d=fixture();d['section_coverage_contract']={}
        self.assertFalse(probe.exercise(c,d,snapshot())['passed'])
    def test_bad_baseline_not_a_proof(self):
        s=snapshot();s['cells']['Estimate!M11']=0
        out=probe.exercise(c,fixture(),s)
        self.assertFalse(out['passed']);self.assertEqual(out['cases'],[])

if __name__=='__main__': unittest.main()
