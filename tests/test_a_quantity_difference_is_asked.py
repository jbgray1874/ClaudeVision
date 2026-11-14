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


def test_a_line_counted_once_is_asked_so_a_spare_is_not_lost():
    job = cf.costed_job(_summary(1, 1, ["GA x1 -> LA x1 -> 08X x1 -> PP x1 = 1"],
                                 note="listed on GA's table beside LA, which already holds 1; "
                                      "counted once, through LA"))
    qc = [d for d in job["decisions_required"] if d["kind"] == "quantity_check"]
    assert len(qc) == 1 and "costed once" in qc[0]["issue"]


# ── SEVERAL ROUTES THE MODEL COUNTS TO THE SAME TOTAL (11896-01-00-GA, 14 Nov 2026) ────────
TWO_LEGS = ["GA x1 -> FRAME x1 -> LEG-RH x1 -> PP x2 = 2", "GA x1 -> FRAME x1 -> LEG-LH x1 -> PP x2 = 2"]


def _with_model_count(summary, total, source="solidworks_api"):
    summary["estimate_summary"]["part_estimates"][0].update(
        quantity_total_per_unit=total, quantity_total_per_unit_source=source)
    return summary


def _asked(summary):
    return [d for d in cf.costed_job(summary)["decisions_required"] if d["kind"] == "quantity_check"]


def test_two_routes_the_model_counts_to_the_sheets_total_are_not_asked():
    assert not _asked(_with_model_count(_summary(2, 4, TWO_LEGS), 4))


def test_two_routes_the_model_counts_differently_are_still_asked():
    qc = _asked(_with_model_count(_summary(2, 4, TWO_LEGS), 2))
    assert len(qc) == 1 and "states 2" in qc[0]["issue"] and "costs 4" in qc[0]["issue"]


def test_two_routes_with_no_model_count_are_still_asked():
    assert len(_asked(_summary(2, 4, TWO_LEGS))) == 1


def test_a_total_that_is_not_the_models_own_count_does_not_silence_the_question():
    assert len(_asked(_with_model_count(_summary(2, 4, TWO_LEGS), 4, source="bom_table"))) == 1


def test_a_note_that_a_row_was_dropped_or_added_is_asked_even_when_the_model_agrees():
    s = _with_model_count(_summary(2, 4, TWO_LEGS, note="a table row was added to the cascade"), 4)
    assert len(_asked(s)) == 1
