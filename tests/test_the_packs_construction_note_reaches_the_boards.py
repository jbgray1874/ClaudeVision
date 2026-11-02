"""The pack's GENERAL CONSTRUCTION note reaches the boards it describes (SCRUM-179).

12678-01-GA prints "GENERAL CONSTRUCTION MDF - LAMINATED CLEAF TARANTA FD10" on the GA,
once, for the whole product — and the estimate carried none of it. The parts table has
no material column, so the title block's WOOD became TIMBER on every board; the laminate
reached no field any reader looks at; four laminated boards priced as raw board at raw
sheet money; EDGE sat at zero hours on a retail podium faced on every visible side.

THE RULES PINNED HERE:
- the note is read off the pack's own pages, cut at the next spec heading;
- it REFINES a bare family word (WOOD, TIMBER, nothing) and never contradicts a part's
  own stated material;
- its words ride on the made boards as construction_note_laminate, where the faced-board
  promotion cites the sentence as evidence and prices the pre-faced board;
- an assembly and a bought-in take nothing from it, exactly as the edging rule keeps an
  assembly page's note off its members;
- a laminate the promotion cannot place becomes an estimator question, never raw-board
  money in silence.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import construction_note as cn  # noqa: E402
import estimator  # noqa: E402

NOTE_TEXT = ("GENERAL CONSTRUCTION MDF - LAMINATED CLEAF TARANTA FD10 "
             "FIXED SHELVES GLUED IN PLACE WITH STEEL SUPPORT")


def _summary():
    return {"pages": [
        {"page_number": 1, "pypdf_text": "SECTION B-B DETAIL C SCALE 1:3"},
        {"page_number": 2, "pypdf_text": NOTE_TEXT},
    ]}


# ── reading the note ─────────────────────────────────────────────────────────────────

def test_the_note_is_read_and_cut_at_the_next_heading():
    note = cn.read(_summary())
    assert note is not None
    assert note["text"] == "MDF - LAMINATED CLEAF TARANTA FD10"
    assert note["board"] == "MDF"
    assert note["laminated"] is True
    assert note["where"] == "page 2"


def test_a_pack_without_the_note_reads_none():
    assert cn.read({"pages": [{"pypdf_text": "MATERIAL: SEE PART DRAWINGS"}]}) is None
    assert cn.read(None) is None


# ── applying it to the parts ─────────────────────────────────────────────────────────

def test_the_note_refines_the_bare_family_word_and_carries_the_laminate():
    note = cn.read(_summary())
    part = {"part_number": "12678-01-02J", "description": "SPINE",
            "normalized_material": "TIMBER"}
    touched = cn.apply(note, [part])
    assert touched == ["12678-01-02J"]
    assert part["normalized_material"] == "MDF"
    assert part["construction_note_laminate"] == "MDF - LAMINATED CLEAF TARANTA FD10"
    assert any("general construction note" in f for f in part["review_flags"])


def test_a_parts_own_stated_material_is_never_contradicted():
    note = cn.read(_summary())
    oak = {"part_number": "P-OAK", "normalized_material": "OAK"}
    ply = {"part_number": "P-PLY", "normalized_material": "PLYWOOD"}
    cn.apply(note, [oak, ply])
    assert oak["normalized_material"] == "OAK"
    assert "construction_note_laminate" not in oak
    # A stated board keeps its board, but the laminate still describes it.
    assert ply["normalized_material"] == "PLYWOOD"
    assert ply["construction_note_laminate"]


def test_an_assembly_and_a_bought_in_take_nothing_from_the_note():
    note = cn.read(_summary())
    ga = {"part_number": "12678-01-GA", "is_assembly_parent": True,
          "normalized_material": "TIMBER"}
    nut = {"part_number": "FIXING28", "description": "M6 HEX NUT",
           "normalized_material": "", "is_bought_in": True}
    assert cn.apply(note, [ga, nut]) == []
    assert ga["normalized_material"] == "TIMBER"
    assert "construction_note_laminate" not in nut


# ── the promotion cites the note ─────────────────────────────────────────────────────

def test_the_promotion_prices_the_pre_faced_board_on_the_notes_evidence():
    note = cn.read(_summary())
    part = {"part_number": "12093-24-06J", "description": "SHELF",
            "normalized_material": "TIMBER"}
    cn.apply(note, [part])
    family, why = estimator._faced_board_promotion(part, part["normalized_material"])
    assert family == "MFMDF"
    assert "general construction note" in why
    assert "CLEAF" in why.upper()


def test_plain_mdf_without_any_evidence_stays_plain():
    family, why = estimator._faced_board_promotion(
        {"part_number": "P", "description": "PANEL"}, "MDF")
    assert family is None and why == ""


# ── wired, not merely built ──────────────────────────────────────────────────────────

def test_the_scan_applies_the_note_before_costing_and_the_sheet_asks_about_the_edges():
    scan = open(os.path.join(os.path.dirname(__file__), "..", "src", "file_scan.py"),
                encoding="utf-8").read()
    # IN pre_costing_passes, not the summary sections: a material that arrives after the
    # price is a note, not a material (the D-433 lesson, relearned here on day one).
    seg = scan[scan.index("def pre_costing_passes"):scan.index("def _finalize_scan_summary")]
    assert "import construction_note as _cnote" in seg
    assert '_cnote.apply(_note, summary["manufacturing_writeup"]["parts"])' in seg
    wb = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
              encoding="utf-8").read()
    # The edging ask reads BOTH material lists: a laminated panel with a blank sits in
    # board_parts, and an ask scoped to bom_parts never fired on the parts that get banded.
    i = wb.index("_lam_parts = [p for p in")
    assert "board_parts" in wb[i:i + 120]
    est = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
               encoding="utf-8").read()
    # A laminate the promotion cannot place is asked, never silently raw board.
    assert "construction_note.unpriced_laminate" in est
