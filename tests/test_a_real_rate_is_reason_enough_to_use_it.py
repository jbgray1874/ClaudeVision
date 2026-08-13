"""A material with a rate in the catalogue must be able to reach the code that uses it.

11650-04 CAME BACK WITH TWO OF FOUR PANELS COSTING NOTHING.

    11650-04-01A          1250 x 525   6/sheet   GBP 50.02/sheet   GBP 8.67
    11650-04-01A-HANDED   1250 x 525   2/sheet   (no sheet price)  GBP 0.00
    11650-04-03A            420 x 133  78/sheet  GBP 50.02/sheet   GBP 0.67
    11650-04-03A-HANDED     420 x 133  35/sheet  (no sheet price)  GBP 0.00

The job's material fell from GBP 76.66 to GBP 9.36 and the unit price from GBP 101.15 to
GBP 52.29 -- a fall that reads like an improvement and is a job priced at half of nothing.

TWO FAULTS, ONE BRANCH, BOTH MINE.

  THE GATE. The sheet branch was entered when the material was one of six named plastics, or
  when a language model had already returned a GBP/m2 for it. So a material with a REAL rate
  in the customer's own catalogue could not reach the code that would have used it unless an
  LLM happened to guess a price for it first. The two base panels got in on an LLM rate; the
  two handed twins got none, fell through to `no_price`, and were costed at zero. Widening
  the rate lookup from HIPS to every sheet material -- which was the point -- did nothing,
  because the gate in front of it had not moved.

  THE SHAPE. Inside, the live-rate path returned neither `sheet_price_gbp` nor
  `parts_per_sheet`, which are the two fields the workbook's Other Sheet block is filled
  from. A branch that returns a cost the sheet cannot render has not priced anything. While
  HIPS was the only material that could reach it, nothing noticed.

A LIVE CATALOGUE RATE IS THE STRONGEST REASON TO ENTER THIS BRANCH THAT EXISTS. It is asked
first now, and it is part of the condition rather than something discovered after it.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator  # noqa: E402

PETG_RATE = 9.63          # what UDEF actually holds: 37 plain-stock rows at 2mm


@pytest.fixture(autouse=True)
def _catalogue(monkeypatch):
    """A catalogue with a PETG rate and nothing else, so the tests turn on the rate rather
    than on whatever this machine can reach."""
    estimator._SHEET_RATE_CACHE.clear()
    estimator._SHEET_RATE_CACHE[("PETG", 2.0)] = PETG_RATE
    # No LLM. The whole point is that the branch must not depend on one.
    monkeypatch.setattr(estimator, "market_indication_for", lambda part, material: None)
    yield
    estimator._SHEET_RATE_CACHE.clear()


def _panel(pn, material="PETG", thickness=2.0, length=1250.0, width=525.0):
    return estimator.estimate_material({
        "part_number": pn, "normalized_material": material,
        "normalized_thickness_mm": thickness, "quantity": 1,
        "blank_length_mm": length, "blank_width_mm": width,
        "material_estimate": {}, "manufacturing_interpretation": {},
    })


# ── the gate ─────────────────────────────────────────────────────────────────────────

def test_a_catalogue_rate_is_reason_enough_without_a_language_model():
    """PETG is not one of the six named plastics and no LLM is available here. Before this,
    that combination priced the part at nothing."""
    me = _panel("11650-04-01A")
    assert me["cost_method"] == "sheet_rate_live_udef"
    assert me["cost_per_part_gbp"] > 0


def test_the_handed_twin_prices_the_same_as_its_base():
    """THE DEFECT, STATED AS THE TEST. One panel, made twice, must not cost GBP 8.67 and
    GBP 0.00 -- and it did, because only one of them had been guessed at by an LLM."""
    base = _panel("11650-04-01A")
    twin = _panel("11650-04-01A-HANDED")
    assert base["cost_per_part_gbp"] == twin["cost_per_part_gbp"] > 0
    assert base["sheet_price_gbp"] == twin["sheet_price_gbp"]
    assert base["parts_per_sheet"] == twin["parts_per_sheet"]


def test_a_material_with_no_catalogue_rate_is_still_not_invented():
    """The gate widened; it did not open. A material nobody stocks and no LLM priced still
    comes back unpriced, and the invariants still say so."""
    me = _panel("X-1", material="UNOBTAINIUM", thickness=2.0)
    assert me.get("cost_per_part_gbp") in (None, 0, 0.0)
    assert me.get("cost_method") != "sheet_rate_live_udef"


def test_the_rate_is_asked_for_once_per_material_and_gauge(monkeypatch):
    """It is resolved BEFORE the gate now, so every sheet part reaches it. Uncached that
    would be a database round trip per part."""
    calls = []
    real = estimator._resolve_board_sheet_rate_gbp_per_m2

    def counting(material, thickness):
        calls.append((material, thickness))
        return real(material, thickness)

    monkeypatch.setattr(estimator, "_resolve_board_sheet_rate_gbp_per_m2", counting)
    for pn in ("A", "B", "C", "D"):
        _panel(pn)
    assert len(set(calls)) == 1, "the lookup is not keyed the way the cache is"


# ── the shape the workbook is filled from ────────────────────────────────────────────

def test_the_sheet_row_can_actually_be_rendered():
    """The Other Sheet block is filled from `sheet_price_gbp` and `parts_per_sheet`. This
    branch returned neither, so the workbook said "no sheet price -- Cost Per Part will be 0"
    for every part that reached it."""
    me = _panel("11650-04-01A")
    assert me["sheet_price_gbp"] > 0
    assert me["parts_per_sheet"] >= 1
    assert me["stock_estimate"] is not None


def test_the_sheet_price_is_the_rate_across_a_whole_sheet():
    """Not a number chosen to make the part cost come out right. 3050 x 2050 at GBP 9.63/m2
    is GBP 60.21, and an estimator reading the row must find arithmetic they can repeat."""
    me = _panel("11650-04-01A")
    dims = me["stock_estimate"]["candidate_sheet_size_mm"]
    area = (dims[0] * dims[1]) / 1_000_000.0
    assert me["sheet_price_gbp"] == pytest.approx(PETG_RATE * area, abs=0.01)


def test_the_cost_is_still_area_times_rate_and_did_not_change():
    """Rendering the row as a sheet must not silently re-cost the part. The money is area x
    rate x scrap, as it was; what changed is that the sheet can now show its working."""
    me = _panel("11650-04-01A")
    expected = 1.250 * 0.525 * PETG_RATE * 1.04
    assert me["cost_per_part_gbp"] == pytest.approx(round(expected, 2), abs=0.01)


def test_the_nest_comes_from_the_one_function_that_answers_that_question():
    """So it cannot drift from the block it feeds -- the defect that had a plastic panel
    carrying the steel nesting rule on its record while J51 charged it."""
    me = _panel("11650-04-01A")
    assert me["nesting_rule"] == "workbook_other_sheet_J51"
    assert me["stock_estimate"]["nesting_rule"] == me["nesting_rule"]


def test_the_note_names_the_material_it_actually_priced():
    """It said HIPS for every material, because HIPS was once the only one that could get
    here. An estimator reading "HIPS sheet cost" against a PETG panel has been told something
    false about where the money came from."""
    me = _panel("11650-04-01A")
    assert "PETG" in me["note"]
    assert "HIPS" not in me["note"]
    assert "hips" not in str(me["price_source"].get("source_name") or "").lower()


def test_the_price_is_attributed_to_the_catalogue_and_not_to_a_guess():
    """It is a real purchase rate, so it is reproducible and must say so — that is what keeps
    `price_not_reproducible` off the job for these lines, which is the whole commercial point
    of preferring the catalogue to a market estimate."""
    ps = _panel("11650-04-01A")["price_source"]
    assert ps["source_class"] == "catalogue"
    assert ps["reproducible"] is True
    assert "llm" not in str(ps.get("source_name") or "").lower()
    assert ps.get("llm_provider") is None
