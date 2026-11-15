"""A LINE CHARGED NOTHING SAYS THE FIGURE THE ENGINE HOLDS, AND WHY IT IS NOT CHARGED (15 Nov 2026).

12181-00-GA: a timber frame, a dowel block and two plywood pieces were charged £0 with the
question "carries no price ... understated by whatever it is worth ... supply a rate". The
record held engine material figures of £5.90, £12.00 and £3.95 for them, worked from the
model's weight, and the reason they were not charged was that no gauge is stated for the Other
Sheet row to nest on. The question now says the figure, the reason and what to give.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SRC = (ROOT / "src" / "costed_facts.py").read_text(encoding="utf-8")


def _decision(line):
    """The missing-price decision exactly as costed_facts writes it, for one unpriced line."""
    start = SRC.index("    decisions: List[Dict[str, Any]] = []\n    for l in unpriced:")
    end = SRC.index("    # ── WHAT THE TALLY COULD NOT SEE", start)
    block = "\n".join(ln[4:] if ln.startswith("    ") else ln for ln in SRC[start:end].splitlines())
    scope = {"unpriced": [line], "List": list, "Dict": dict, "Any": object}
    exec(block, scope)                                                   # noqa: S102  (the engine's own lines)
    return scope["decisions"][0]


def _line(**over):
    l = {"part_number": "T-100-01J", "kind": "leaf", "block": "other_sheet", "thickness_mm": None,
         "engine_unit_gbp": 5.9, "engine_ext_gbp": 5.9, "review_flags": [],
         "price_origin": {"owner": "engine"}}
    l.update(over)
    return l


def test_the_question_gives_the_engines_figure_the_reason_and_what_to_supply():
    d = _decision(_line())
    assert "charged £0" in d["issue"] and "£5.90" in d["issue"] and "no gauge is stated" in d["issue"]
    assert d["gbp_at_stake"] == 5.9 and "about £5.90" in d["assumption"]
    assert "state the gauge" in d["action"] and "section" in d["action"]


def test_a_line_with_a_gauge_and_a_figure_that_did_not_arrive_is_said_differently():
    d = _decision(_line(thickness_mm=18.0))
    assert "did not reach the charged row" in d["issue"] and "no gauge" not in d["issue"]
    assert d["action"] == "supply a rate or a supplier quote"


def test_a_line_the_engine_has_no_figure_for_reads_as_before():
    d = _decision(_line(engine_unit_gbp=0.0, engine_ext_gbp=0.0))
    assert d["issue"] == "T-100-01J carries no price" and d["gbp_at_stake"] is None
    assert "whatever it is worth" in d["assumption"] and d["action"] == "supply a rate or a supplier quote"
