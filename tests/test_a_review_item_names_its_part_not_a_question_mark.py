"""A review item in the job report names a findable part, not a bare "?".

Section 3 of the HTML job report ("Review items & limitations") showed "?" in its Item column
whenever a flagged part had no part_number (rejected as boilerplate, or derived from an assembly
page). "?" tells the estimator a flag exists but not what it is on — unactionable, the report-side
twin of the "None" blocking-flag gap.

Two halves, tested here:
  * estimator._build_estimate_review_signals now carries a fallback identity (description, source
    file) on each flagged part, not just the part_number;
  * job_report_html._extract_review_items falls back through part_number -> description -> source
    filename before "unidentified", so the Item column always names something.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator as est  # noqa: E402
import job_report_html as jr  # noqa: E402


def test_the_estimator_carries_identity_beyond_the_part_number():
    sig = est._build_estimate_review_signals(
        [{"part_number": None, "description": "TIMBER BACK PANEL", "risk_flags": ["weld_required"]}])
    f = sig["parts_flagged"][0]
    assert f["part_number"] is None
    assert f["description"] == "TIMBER BACK PANEL"      # the handle the report needs


def _labels(summary):
    review = jr._extract_review_items(summary)
    return [fp["part"] for fp in review["flagged_parts"]]


def _summary(flagged):
    return {"estimate_summary": {"estimate_review_signals": {"parts_flagged": flagged}}}


def test_the_report_falls_back_to_description_then_source_then_a_plain_label():
    labels = _labels(_summary([
        {"part_number": None, "description": "TIMBER BACK PANEL", "reasons": []},
        {"part_number": None, "description": None,
         "source_file": "C:/jobs/8352-03-01.dxf", "reasons": []},
        {"part_number": "8352-01-09", "reasons": []},
        {"part_number": None, "reasons": []},
    ]))
    assert labels[0] == "TIMBER BACK PANEL"
    assert labels[1] == "8352-03-01.dxf"          # a path collapses to its filename
    assert labels[2] == "8352-01-09"
    assert labels[3] == "unidentified (no part number)"
    assert "?" not in labels                       # never a bare question mark


def test_a_real_part_number_still_wins():
    assert _labels(_summary([{"part_number": "10575-02-009", "reasons": []}])) == ["10575-02-009"]
