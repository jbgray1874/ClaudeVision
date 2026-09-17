r"""A confirmed production substitution reaches the gauge column, or it changed nothing.

James, from the 7332-01 six-off book:

    Estimate!H67 is 0.9 and M67 costs from it
    "Write the recorded 1.0 mm production substitution into the sheet-material output
     before the workbook is populated."

Howard ruled it on 15 September: "0.9mm Steel Production use 1mm in Lieu." It went in as
D-068, `apply_production_substitutions` recorded it on the part and pushed 1.0 through
`source_precedence` onto `normalized_thickness_mm` at rank 95, above every reading.

AND THE SHEET STILL SHOWED 0.9, WITH NOTHING ON THE ROW TO SAY WHY NOT.

The same wrong-record shape as the tube-bend ruling, one field over. The substitution was
recorded on the RAW part; the Sheet Steel block writes its gauge from the COSTED part
estimate; and `production_substitution` was never copied across the costing boundary. Its
only route to the sheet was whichever normalised thickness happened to survive onto the
costed record, with the material estimate's own thickness sitting behind it as a fallback.
A fact that is right, recorded, and unreachable is a fact that did nothing.

So the recorded ruling travels with the costed record, and the writer asks IT rather than
re-deriving a gauge and hoping. Two tests matter here and they are different in kind: that
the substitution survives the costing boundary at all, and that the cell then changes.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config             # noqa: E402
import estimator          # noqa: E402


def _drawn_at(gauge_mm: float) -> dict:
    """A plain steel part drawn at the gauge given, with nothing else to argue about."""
    return {
        "part_number": "7332-01-008",
        "description": "BRACKET",
        "normalized_material": "MILD STEEL",
        "normalized_thickness_mm": gauge_mm,
        "quantity": 1,
    }


# ── the rule itself ──────────────────────────────────────────────────────────────────

def test_the_rule_is_confirmed_and_says_which_gauge_replaces_which():
    rules = config.PRODUCTION_MATERIAL_SUBSTITUTIONS
    rule = next(r for r in (rules.values() if isinstance(rules, dict) else rules)
                if str((r or {}).get("rule_id") or "") == "steel_0.9_to_1.0"
                or "0.9" in str((r or {}).get("rule_id") or ""))
    assert rule["substitute_mm"] == 1.0
    assert str(rule["status"]).lower() == "confirmed", (
        "an unconfirmed rule costs AS DRAWN and only raises a flag — the whole behaviour "
        "under test depends on this one being ruled")


def test_a_drawn_09_is_recorded_as_costed_at_10():
    part = _drawn_at(0.9)
    estimator.apply_production_substitutions(part)
    sub = part.get("production_substitution")
    assert sub, "nothing was recorded, so nothing can travel"
    assert sub["drawn_thickness_mm"] == 0.9
    assert sub["costed_thickness_mm"] == 1.0
    assert part["normalized_thickness_mm"] == 1.0
    assert part["drawn_thickness_mm"] == 0.9, "what the drawing says is not thrown away"


def test_a_gauge_with_no_rule_is_left_exactly_alone():
    """The control. A substitution that fires on everything is not a substitution."""
    part = _drawn_at(1.5)
    estimator.apply_production_substitutions(part)
    assert part.get("production_substitution") is None
    assert part["normalized_thickness_mm"] == 1.5


def test_an_estimator_confirmed_gauge_outranks_the_production_rule():
    """A person's ruling beats a standing rule, and the row says the rule stood down."""
    import source_precedence
    part = _drawn_at(0.9)
    source_precedence.apply_field(part, "normalized_thickness_mm", 0.9,
                                  "estimator_confirmed")
    estimator.apply_production_substitutions(part)
    assert part.get("production_substitution") is None
    assert part["normalized_thickness_mm"] == 0.9
    assert any("stood down" in str(f) for f in part.get("review_flags") or [])


# ── across the costing boundary, which is where it was being lost ────────────────────

def test_the_costed_record_carries_the_substitution():
    """Its only route to the sheet used to be a normalised value that may have come from
    anywhere. The ruling itself now crosses the boundary."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    assert '"production_substitution": (dict(part["production_substitution"])' in src
    assert '"drawn_thickness_mm": part.get("drawn_thickness_mm"),' in src


# ── and the cell changes ─────────────────────────────────────────────────────────────

def test_the_sheet_steel_writer_costs_from_what_production_buys():
    """H67 is the gauge cell of the fifth Sheet Steel row. Whatever gauge reached the
    costed record, a confirmed substitution replaces it and the run says so."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "wb_populate.py"
           ).read_text(encoding="utf-8")
    start = src.index('_sub_rec = pe.get("production_substitution")')
    block = src[start:start + 1400]
    assert "gauge = _costed" in block, "the cell is not actually changed"
    assert "What production buys is what the row costs from." in block, (
        "a gauge that silently differs from the drawing is worse than the bug — the row "
        "has to say a substitution was applied and who ruled it")
    # The replacement must happen BEFORE the cell is written, not after.
    assert start < src.index('column=s["col_gauge"]'), "the gauge is written before it is corrected"


def test_the_gauge_column_is_H_on_the_steel_block():
    """H67 only means anything if column H is still the gauge. The template shifts its
    blocks as they grow, so this is the link between James's cell and our column."""
    import wb_populate
    steel = wb_populate.CELL_MAP["steel"]
    assert steel["col_gauge"] == 8, "column H"
    assert steel["first_row"] <= 67 <= steel["last_row"], (
        "row 67 is inside the Sheet Steel block")
