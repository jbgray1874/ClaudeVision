"""A figure held for a question is shown on the line and kept out of the unit (D-430).

8188-08, 9 Oct: fourteen magnets printed "50mm x 10mm x 2m" were priced as two-metre magnets,
£706.16 of a £1,814.22 unit. D-427 put a question under the line and left the money in. A
question beneath a charged figure is not the same as holding the money.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf                                             # noqa: E402
import wb_populate as wp                                              # noqa: E402

_HOLD = {"reason": "the printed size 50mm x 10mm x 2m mixes m and mm",
         "source": "extractor_patterns.size_mixing_units"}


def test_a_held_line_shows_its_figure_and_charges_nothing():
    pe = {"part_number": "KINGDOM", "_price_held": _HOLD}
    h = wp.held_line(pe, 48.5, 14)
    assert h["unit_gbp"] == 48.5 and h["ext_gbp"] == 679.0
    assert h["note"].startswith("HELD £48.50 a unit, £679.00 at 14")
    assert "not in the unit cost" in h["note"] and "mixes m and mm" in h["note"]


def test_a_line_with_nothing_held_prices_as_before():
    assert wp.held_line({"part_number": "PSA1999C"}, 1.85, 7) is None
    assert wp.held_line({"part_number": "KINGDOM", "_price_held": _HOLD}, None, 14) is None


def test_the_report_calls_a_held_line_held_not_a_market_figure():
    part = {"part_number": "KINGDOM", "_price_held": _HOLD,
            "material_estimate": {"cost_method": "market_research",
                                  "price_source": {"source_name": "xAI Grok LLM"}}}
    o = cf._price_origin(part, "bought_in", None, None, 48.5, None, False,
                         row_text="[AI ESTIMATE - INDICATIVE, NOT A QUOTE]")
    assert o["class"] == "held_for_question" and o["firmness"] == cf.UNPRICED
    assert "HELD out of the unit cost" in o["label"] and "£48.50" in o["label"]
