"""A line costed at a quantity its own BOM row does not state is on the review list.

12312-01-GA: the driver, LED tape, power cord and Y-splitter each stated 1 and were costed at 2
(reached through the lighting assembly and again from the GA's table). The workbook column said
so; the review list, which is what an estimator works from, did not.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import costed_facts as cf                                         # noqa: E402

PN = "P/P-LED-POWER-DRIVER-24V"


def _summary(own, eff, trails, note=""):
    return {"estimate_summary": {
        "part_estimates": [{"part_number": PN, "description": "LED POWER DRIVER",
                            "quantity": eff, "page_roles": ["bought_in"]}],
        "canonical_route_shadow": {"issues": [], "nodes": [
            {"part_number": PN, "qty_own": own, "qty_per_unit": eff,
             "qty_trail": trails, "qty_note": note}]}}}


def test_two_routes_to_a_different_count_is_asked():
    job = cf.costed_job(_summary(1, 2, ["GA x1 -> LA x1 -> 08X x1 -> PP x1 = 1",
                                         "GA x1 -> PP x1 = 1"]))
    qc = [d for d in job["decisions_required"] if d["kind"] == "quantity_check"]
    assert len(qc) == 1 and "states 1" in qc[0]["issue"] and "costs 2" in qc[0]["issue"]
    tally = cf.outstanding_summary(job)
    assert "1 quantity check" in str(tally), tally


def test_a_count_multiplied_down_one_route_is_not_asked():
    job = cf.costed_job(_summary(2, 6, ["GA x1 -> SUB x3 -> PP x2 = 6"]))
    assert not [d for d in job["decisions_required"] if d["kind"] == "quantity_check"]


def test_a_matching_count_is_not_asked():
    job = cf.costed_job(_summary(1, 1, ["GA x1 -> PP x1 = 1"]))
    assert not [d for d in job["decisions_required"] if d["kind"] == "quantity_check"]
