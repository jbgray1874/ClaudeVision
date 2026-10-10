"""Three faults the 8188-08 13:23 live book (build c94daf0, 8975038) still carried (D-452).

1. The M6 insert charged twice for the fifth book. The workbook's own provenance showed the
   route listing BOTH "FIXING M6X12MM" and "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE"
   (no description, from the vision model's assembly children) under SA03, and the workbook's
   canonicalisation minting a priced line for that second node — after every part-record fix.
2. Packaging and delivery came from twelve past M&S quote lines in SDI Live (median £10.00 and
   £10.06 a unit) — the report still called them AI market figures, and the per-unit figure was
   written as one order figure, so fifty headers carried £0.20 each.
3. 8188-08-013's weight check blamed the stated 3 mm gauge ("fits 260 mm") when its blank,
   2190 x 17, was never measured (cut length only).
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import commercial_lines as cl                                         # noqa: E402
import costed_facts as cf                                             # noqa: E402
import estimator                                                      # noqa: E402
import wb_populate as wp                                              # noqa: E402


def test_the_workbook_mint_asks_the_wrapped_cell_rule_and_folds_its_population():
    src = inspect.getsource(wp.canonicalise_part_estimates_for_workbook)
    assert "same_row_read_as_one_cell" in src, "the mint must ask the rule where the line is born"
    assert "fold_one_cell_duplicates" in src, "two population lines read from one row must fold"


def test_the_population_fold_merges_the_two_insert_lines():
    from part_identity import fold_one_cell_duplicates
    pop = [{"part_number": "FIXING M6X12MM", "description": "THREADED INSERT, HEADED HEX DRIVE", "quantity": 4},
           {"part_number": "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE", "description": "", "quantity": 4}]
    assert fold_one_cell_duplicates(pop) == [("FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE", "FIXING M6X12MM")]
    assert len(pop) == 1


def test_an_sdi_live_commercial_figure_is_classed_as_sdis_not_the_markets():
    part = {"part_number": "PACKAGING", "_commercial_placeholder": True, "cost_source": "sdi_live_commercial",
            "price_source": {"source_name": "SDI Live history: 12 quote line(s), same customer"}}
    origin = cf._price_origin(part, "commercial", "bom", 10.0, 10.0, 19, False,
                              row_text="Packaging (box / pallet — per-unit share, SDI Live figure — confirm)")
    assert origin["class"] == "sdi_live_commercial" and origin["firmness"] == cf.INDICATIVE_HOUSE
    assert "SDI Live's own figure" in origin["label"]


def test_a_per_unit_history_figure_is_held_per_unit_at_every_break():
    src = inspect.getsource(cl._sdi_live_rate)
    assert '"order_gbp_at_breaks": {q: round(median * q, 2)' in src
    assert "a per-unit share on those quotes, held per" in src


def test_an_unmeasured_blank_is_questioned_before_a_stated_gauge():
    part = {"part_number": "W-013", "description": "WAVE LAYER 3", "normalized_material": "ACRYLIC",
            "normalized_thickness_mm": 3.0, "_costed_blank_mm": [2190.34, 17.0], "stated_weight_kg": 11.731}
    note = estimator._blank_weight_check(part)
    assert note and "blank is the first suspect, not the gauge" in note
    assert "2190.34 x 227 mm" in note and "priced on 2190.34 x 17 until then" in note
    estimator.estimate_process_times(part, quantity=1)
    issues = [str(q.get("issue")) for q in part.get("manufacturing_questions") or []]
    assert any(i.startswith("Blank of W-013") for i in issues), issues
    assert not any(i.startswith("Gauge of W-013") for i in issues)


def test_a_measured_outline_that_still_will_not_weigh_keeps_the_gauge_question():
    part = {"part_number": "P-1", "description": "PANEL", "normalized_material": "ACRYLIC",
            "normalized_thickness_mm": 3.0, "_costed_blank_mm": [500.0, 300.0],
            "blank_area_mm2": 140000.0, "stated_weight_kg": 9.0}
    note = estimator._blank_weight_check(part)
    assert note and note.startswith("WEIGHT CHECK:") and "first suspect" not in note


def test_a_figure_quoted_per_order_is_not_taken_as_a_per_pallet_rate(monkeypatch):
    monkeypatch.setattr(cl, "_commercial_researcher", lambda brief: {
        "price_gbp": 84.0, "unit": "order", "source": "a tariff"})
    order = {"order_quantity": 7, "shipment": {"pallet_count": 3, "carton_count": None, "flags": []}}
    assert cl._counted_shipment_price("DELIVERY", order) is None
