"""Two review-list controls from the 12312-01-GA 13:39 review.

08X, the 3.944 m silicone LED diffuser, sat in the tree as an assembly of four purchased items
— £0 by design — while the AI had priced the diffuser itself at £32.50. And the powder decision
said "both charges stand" beside a sheet carrying one P.Coat row, while the evidence section
called the scope "Sound".
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import costed_facts as cf                                         # noqa: E402


def test_an_assembly_with_its_own_price_is_asked():
    p = {"part_number": "12312-01-08X", "description": "SILICONE LED DIFFUSER, L: 3.944m",
         "is_assembly_parent": True, "assembly_children": ["P/P-X"],
         "system_cost": {"unit_cost_gbp": 32.5}}
    s = {"manufacturing_writeup": {"parts": [p]}, "estimate_summary": {
        "part_estimates": [p], "canonical_route_shadow": {"issues": [], "nodes": [
            {"part_number": "12312-01-08X", "kind": "assembly", "qty_own": 1,
             "qty_per_unit": 1, "qty_trail": []}]}}}
    ds = cf.costed_job(s)["decisions_required"]
    hit = [d for d in ds if d["part"] == "12312-01-08X"]
    assert hit and "£32.50" in hit[0]["issue"] and hit[0]["gbp_at_stake"] == 32.5


def test_an_assembly_without_a_price_of_its_own_is_not_asked():
    p = {"part_number": "A-101", "description": "CASE", "is_assembly_parent": True,
         "assembly_children": ["A-01"]}
    s = {"manufacturing_writeup": {"parts": [p]}, "estimate_summary": {
        "part_estimates": [p], "canonical_route_shadow": {"issues": [], "nodes": [
            {"part_number": "A-101", "kind": "assembly", "qty_own": 1, "qty_per_unit": 1,
             "qty_trail": []}]}}}
    assert not [d for d in cf.costed_job(s)["decisions_required"] if d["part"] == "A-101"]


def test_the_powder_decision_names_the_scope_the_sheet_charges():
    s = {"estimate_summary": {
        "canonical_route_shadow": {"issues": [
            {"code": "powder_scope_mixed_members", "part_number": "12312-01-101",
             "message": "powder is required on 12312-01-101 AND on 12312-01-01M"}]},
        "workbook_labour": {"rows": [
            {"workbook_row": 113, "wb_operation": "P.Coat", "engine_operations": ["powder_coating"],
             "part_numbers": ["12312-01-02M", "12312-01-101", "12312-01-14M"]}]}}}
    d = next(d for d in cf.costed_job(s)["decisions_required"]
             if d["part"] == "12312-01-101")
    assert "12312-01-02M, 12312-01-101, 12312-01-14M" in d["assumption"]
    assert "both" not in d["assumption"] and "choose" in d["action"]


def test_the_report_does_not_call_an_open_scope_sound():
    src = (ROOT / "src" / "job_report_html.py").read_text(encoding="utf-8")
    i = src.index("Powder coating scoped to the right parts")
    assert "powder_scope_mixed_members" in src[i - 1500:i]
