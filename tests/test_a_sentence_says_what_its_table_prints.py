"""A sentence says what the table beside it prints (D-700).

12693-01, 5 Nov 10:44. Two lines in the outputs read as more certain than their own figures:

1. The quote said "running work holds at £173.25 because the work in each unit does not
   change", over a table showing running work £173.22 at 1 off and £173.25 at 50 off.
   "Holds" now only where both columns print the same figure. A small move is said as one,
   and a large move is not called unchanged at all.
2. The AI price check said "1 item(s) ... TICKET HOLDER_2274" and its detail line then
   listed that code six times in two spellings, ending "count=6". The count is the items,
   as the headline says; the six price records are kept for tracing and their number is
   said as what it is.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("SDI_OFFLINE", "1")

import invariants  # noqa: E402
import price_provenance as pp  # noqa: E402
from test_the_quote_shows_how_it_was_read_and_priced import _pages, _summary, _text  # noqa: E402


# ── 1. the quote's running-work sentence ─────────────────────────────────────────────

def _with_running(tmp_path, run_lo, run_hi):
    """Running work is labour less set-up: 1 off has 140 set-up, 50 off has 2.8. The 50 off
    column stays at 60.00 running, the price page's own figure, or the page draws no money."""
    s = _summary(tmp_path)
    rows = s["quantity_sweep"]["rows"]
    rows[0]["labour"] = 140.0 + run_lo
    rows[0]["unit"] = rows[0]["material"] + rows[0]["labour"] + 20.0
    rows[-1]["labour"] = 2.8 + run_hi
    rows[-1]["unit"] = rows[-1]["material"] + rows[-1]["labour"] + 7.2
    return s


def _sentence(tmp_path, run_lo, run_hi):
    s = _with_running(tmp_path, run_lo, run_hi)
    unit = s["quantity_sweep"]["rows"][-1]["unit"]
    _css, html = _pages(s, unit_price=unit)
    t = _text(html)
    at = t.index("At 1 off,")
    end = re.compile(r"\.(?!\d)").search(t, t.index("while", at))
    return t[at:end.end()]


def test_equal_columns_hold(tmp_path):
    said = _sentence(tmp_path, 60.0, 60.0)
    assert "running work holds at £60.00" in said
    assert "does not change" in said


def test_a_few_pence_is_named_as_a_move_not_a_hold(tmp_path):
    said = _sentence(tmp_path, 59.97, 60.0)
    assert "holds at" not in said
    assert "barely moves, from £59.97 to £60.00" in said


def test_a_real_change_is_not_called_unchanged(tmp_path):
    said = _sentence(tmp_path, 80.0, 60.0)
    assert "running work goes from £80.00 to £60.00" in said
    assert "does not change" not in said and "holds at" not in said


# ── 2. the AI price check's count ────────────────────────────────────────────────────

def _job_with_one_item_in_two_spellings():
    """Six price records of one ticket holder, three spelt with spaces and three without."""
    stamp = {"schema": pp.PRICE_SOURCE_SCHEMA, "source_class": "ai_estimate",
             "source_name": "llm_market", "applied": True,
             "selected": {"price": 1.5, "source": "llm_market"}}
    spaced, squashed = ("0327590-A-LINE 78X78MM TICKET HOLDER_2274",
                        "0327590-A-LINE78X78MMTICKETHOLDER_2274")
    return {"estimate_summary": {"part_estimates": [
        {"matched_part_code": c,
         "cost_breakdown": {"system_cost": {"applied_to_total": True, "source": dict(stamp)}}}
        for c in (spaced, squashed, squashed, spaced, squashed, spaced)]}}


def test_the_count_is_the_items_and_the_records_are_said_as_records():
    out = invariants.check_prices_are_reproducible(_job_with_one_item_in_two_spellings())
    assert len(out) == 1
    d = out[0]["detail"]
    assert out[0]["message"].startswith("1 item(s)")
    assert d["parts"] == ["0327590-A-LINE 78X78MM TICKET HOLDER_2274"]
    assert d["count"] == 1, "the detail's count contradicts the headline's one item"
    assert d["price_records"] == 6
    assert [ln["part"] for ln in d["lines"]] == ["0327590-A-LINE 78X78MM TICKET HOLDER_2274"], \
        "the report prints a check's lines one by one: six records read as six items"
    assert d["lines"][0]["reason"] == "6 price records"
