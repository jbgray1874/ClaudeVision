"""The header an estimator asked for, naming the wrong thing.

    "Could you add description/date/drawing number at top please (easier to trace back when
     requoting same job in future)"               — Timothy Wilkes, SDI estimating, 12 Sep

It was added, and on 7332-01 — a Harrods A3 signage stand — it came out as:

    Description    BASE

BASE is 7332-01-001, a laser-cut back panel. The resolver's last fallback takes the shortest
part number the job owns that carries a description, and on that pack the shortest is a leaf.

FOR THE PURPOSE HE GAVE, A WRONG DESCRIPTION IS WORSE THAN AN EMPTY BOX. An empty box sends
him to the drawing; "BASE" tells him this sheet is for a back panel, and he finds out it is
not only after opening the pack he was trying to avoid opening. The box exists to save that
trip.

THE RULE IS STRUCTURAL, NOT A LIST OF WORDS. A record may name the unit only if things hang
off it: flagged as an assembly, or its part number is the stem of other parts in this pack.
No vocabulary of "BASE", "LID", "CAP" to keep up to date, and it holds on packs nobody has
seen yet:

    12349-02-69    owns -04M, -03M-01, -08J    keeps "GRAVITY FEEDER MODULES"
    7332-01-001    owns nothing                 refused

Where no assembly can say what the unit is, nothing is written — the rule everywhere else in
this resolver. The number, the revision, the client and the date still identify the job, and
none of them can be wrong.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from client_quote_html import _drawing_identity                         # noqa: E402


def _described(parts, stem):
    """What the Description box ends up holding.

    _drawing_identity falls through to the cleaned folder stem, and write_job_identity_header
    refuses a description that is only the drawing number — "a number repeated under a
    Description label is noise wearing a label". So the header's answer is the resolver's,
    minus that. Asserted the way the sheet sees it rather than the way the function does."""
    num, _rev, desc = _drawing_identity(_summary(parts), stem)
    desc = str(desc or "").strip()
    return "" if desc == str(num or "").strip() else desc


def _summary(parts):
    return {"estimate_summary": {"part_estimates": parts}}


def _p(pn, desc, **over):
    rec = {"part_number": pn, "description": desc}
    rec.update(over)
    return rec


# ── 7332-01: the case that named a back panel ────────────────────────────────────────────

SEVEN_THREE_THREE_TWO = [
    _p("7332-01-001", "BASE"),
    _p("7332-01-003", "STRAP"),
    _p("7332-01-004", "CAP"),
    _p("7332-01-007", "LENS"),
    _p("7332-01-008", "BACK PANEL"),
]


def test_a_leaf_part_never_names_the_job():
    desc = _described(SEVEN_THREE_THREE_TWO, "7332-01")
    assert desc != "BASE"
    assert desc == "", f"nothing owns anything on this pack, so nothing is claimed: {desc!r}"


def test_the_shortest_number_no_longer_wins_by_itself():
    """That was the whole rule before, and it is what elected a back panel."""
    parts = list(SEVEN_THREE_THREE_TWO)
    assert _described(parts, "7332-01") not in {p["description"] for p in parts}


def test_an_assembly_on_the_same_pack_is_taken():
    """Add a real weldment parent and it is allowed to speak — it is an assembly, and the
    refusal is about leaves, not about being strict for its own sake."""
    parts = list(SEVEN_THREE_THREE_TWO) + [
        _p("7332-01-101", "FRAME WELDMENT", is_assembly_parent=True)]
    assert _described(parts, "7332-01") == "FRAME WELDMENT"


# ── 12349-02: the case that must not regress ─────────────────────────────────────────────

TWELVE_THREE_FOUR_NINE = [
    _p("12349-02-69", "GRAVITY FEEDER MODULES"),
    _p("12349-02-69-04M", "LID"),
    _p("12349-02-69-03M-01", "GRAVITY FEEDER FABRICATION"),
    _p("12349-02-69-08J", "PACKER"),
]


def test_a_parent_that_owns_other_parts_still_names_the_job():
    """12349-02-69 carries no assembly flag on its record — it qualifies because -04M,
    -03M-01 and -08J hang off its number. That is why the rule is structural."""
    assert _described(TWELVE_THREE_FOUR_NINE, "12349-02") == "GRAVITY FEEDER MODULES"


def test_ownership_is_by_part_boundary_not_by_characters():
    """A number that merely starts with the same characters is not a child of it —
    12349-02-690 is a different part from a child of 12349-02-69."""
    parts = [_p("12349-02-69", "GRAVITY FEEDER MODULES"),
             _p("12349-02-690", "SOMETHING ELSE")]
    assert _described(parts, "12349-02") == "", "nothing hangs off it, so it names nothing"


def test_the_lid_does_not_win_when_the_parent_is_missing():
    parts = [p for p in TWELVE_THREE_FOUR_NINE if p["part_number"] != "12349-02-69"]
    assert _described(parts, "12349-02") != "LID"


def test_one_owned_record_is_not_a_guess():
    """THE OTHER SIDE OF THE RULE, and the first cut got it wrong — it refused this too, and
    a job whose graph gave no root lost its description altogether.

    The refusal is about CHOOSING BETWEEN SIBLINGS. 7332-01 owns six flat parts and picking
    the shortest of six equals is arbitrary: BASE won, and STRAP or CAP were as good a
    guess. One candidate is not a guess."""
    assert _described([_p("12349-02-69", "GRAVITY FEEDER MODULES")],
                      "12349-02") == "GRAVITY FEEDER MODULES"


def test_six_flat_siblings_are_a_guess_and_are_refused():
    """The same rule from the other end — this is 7332-01 exactly."""
    assert _described(SEVEN_THREE_THREE_TWO, "7332-01") == ""


# ── and nothing invented ─────────────────────────────────────────────────────────────────

def test_an_empty_pack_claims_nothing():
    assert _described([], "7332-01") == ""


def test_the_reason_is_written_where_the_refusal_happens():
    src = (ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
    assert "A LEAF PART'S DESCRIPTION IS NEVER THE NAME OF THE PRODUCT" in src
    assert "Description    BASE" in src
