"""The AI Provenance summary scores READING and PRICING separately — no more "0 HIGH / 22 LOW".

The old summary took each part's WEAKEST field and banded it. On an estimate the weakest field is
almost always the price — "NOT YET PRICED, estimator to enter a figure" — a normal, expected state.
So a part whose material, thickness and geometry were ALL measured off the SolidWorks model was
counted LOW because nobody had typed its rate yet, and a fully-read job reported "0 HIGH / 22 LOW",
reading as an engine failure when the engine had done its job.

reading_and_pricing_counts scores the engine's READING (material identity, thickness, geometry) on
its own, and reports PRICING as what it is — priced vs awaiting the estimator's rate.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from estimation_report import reading_and_pricing_counts as rp  # noqa: E402


def _part(mat="measured", thk="measured", geo="measured", price="unknown", route="reported"):
    return {"fields": [
        {"field": "material identity", "status": mat},
        {"field": "thickness", "status": thk},
        {"field": "geometry", "status": geo},
        {"field": "route", "status": route},
        {"field": "material price", "status": price},
    ]}


def test_a_fully_read_but_unpriced_part_reads_high_not_low():
    """THE FIX. Material/thickness/geometry all measured, price pending -> a MEASURED read and a
    line AWAITING a rate, never 'LOW'."""
    out = rp([_part(price="unknown")])
    assert out["read_high"] == 1
    assert out["read_low"] == 0
    assert out["pending"] == 1 and out["priced"] == 0


def test_pricing_is_counted_apart_from_reading():
    parts = [
        _part(price="unknown"),                       # read high, pending
        _part(price="reported"),                      # read high, priced
        _part(mat="assumed", geo="unknown", price="unknown"),  # read low, pending
    ]
    out = rp(parts)
    assert out["read_high"] == 2 and out["read_low"] == 1
    assert out["priced"] == 1 and out["pending"] == 2


def test_route_does_not_drag_a_measured_read_down():
    """Route is a decision (usually BOM-reported), not a physical read — it must not pull a part
    that was measured off the model out of the 'measured' bucket."""
    out = rp([_part(route="unknown", price="reported")])
    assert out["read_high"] == 1


def test_an_indicative_price_still_counts_as_priced_not_pending():
    """Only a total absence of a figure (UNKNOWN) is 'awaiting a rate'; an indicative/assumed
    price is a figure, so the line is priced (flagged elsewhere), not pending."""
    out = rp([_part(price="assumed")])
    assert out["priced"] == 1 and out["pending"] == 0


def test_empty_is_all_zero():
    assert rp([]) == {"read_high": 0, "read_med": 0, "read_low": 0, "priced": 0, "pending": 0}
