r"""Geometry measures an edge. Only the drawing knows the edge takes ABS.

James Gray, 18 September 2026, on Tony Ford's 11908-21 review:

    "The engine should derive banded metres from the drawing/DXF, not ask Tony to type a
     length already shown by the design... identify the banded edges from a DXF layer, edge
     callout, note, hatch, or detail; measure only those edges.

     We must not use the whole visible perimeter by default: Tony's own 5 m shows that only
     selected exposed edges are banded. Geometry can measure an edge precisely, but cannot
     know it needs ABS unless the drawing marks it."

THE NUMBER THAT MADE THIS NECESSARY. The old behaviour measured 2*(L+W) of every faced part
and offered it as "the drawn edge metreage". On a 390 x 390 tray at 2 off that is 3.12 m a
unit before anything else is counted — and Tony's whole job is 5 m. The perimeter is always
computable and is almost never the answer, which is the most dangerous combination a
default can have: it looks like a measurement.

So the two questions are kept apart, and the second one is the drawing's to answer:

    HOW LONG IS THIS EDGE      geometry, to the millimetre, needing nobody's opinion
    DOES IT TAKE ABS           a design decision, recorded on a layer, a note or a callout

No evidence, no length. What was looked for is named, so an estimator can tell "this part
is not banded" from "we could not find the note".
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from edge_banding import banded_length_mm, layer_means_edging  # noqa: E402

# Tony's tray: 390 x 390, so a perimeter of 1.56 m a part.
_TRAY = {"part_number": "11908-21-01J", "blank_length_mm": 390.0,
         "blank_width_mm": 390.0, "quantity": 2}


def _tray(**over):
    return dict(_TRAY, **over)


# ── the refusal, which is the point ──────────────────────────────────────────────────

def test_a_faced_part_with_no_marking_gets_no_banded_length():
    out = banded_length_mm(_tray())
    assert out["mm"] is None, "the perimeter was offered as the banded length"
    assert out["basis"] == "no_evidence"


def test_the_perimeter_is_reported_as_a_ceiling_and_never_as_the_answer():
    """It is useful — it shows the scale — and it is not a length anybody banded."""
    out = banded_length_mm(_tray())
    assert out["drawn_perimeter_mm"] == 1560.0
    assert out["mm"] is None


def test_the_refusal_names_what_it_looked_for():
    """So an estimator can tell "not banded" from "we could not find the note"."""
    out = banded_length_mm(_tray())
    assert "EDGEBAND" in out["evidence"]
    assert "note" in out["evidence"].lower()


# ── 1 · a layer of its own is measured directly ──────────────────────────────────────

def test_a_dxf_edging_layer_is_the_answer():
    """The drawing office drew exactly the edges that take ABS, so their length IS it."""
    out = banded_length_mm(_tray(normalized_geometry={
        "length_mm_by_layer": {"EDGEBAND": 780.0, "SLD-0": 4820.0, "HIDDEN": 300.0}}))
    assert out["mm"] == 780.0
    assert out["basis"] == "dxf_edge_layer"
    assert "EDGEBAND" in out["evidence"]


def test_the_other_layers_are_not_counted():
    """The cut profile is on SLD-0 and is most of the length. Counting it would be the
    perimeter mistake wearing a layer name."""
    out = banded_length_mm(_tray(normalized_geometry={
        "length_mm_by_layer": {"EDGING": 500.0, "SLD-0": 9999.0}}))
    assert out["mm"] == 500.0


def test_a_layer_name_is_matched_on_its_letters():
    """EDGE-BAND, EDGE_BANDING and EDGEBAND are one layer. A rule that fails on an
    underscore did nothing — the same fault that made an operations ruling silent."""
    for name in ("EDGEBAND", "EDGE-BAND", "EDGE_BANDING", "Edge Banding", "ABS-EDGE",
                 "LIPPING", "edge tape"):
        assert layer_means_edging(name), name
    for name in ("SLD-0", "HIDDEN", "BENDLINES", "DIMENSIONS", "", None):
        assert not layer_means_edging(name), name


# ── 2 · a note that names the edges ──────────────────────────────────────────────────

def test_all_round_is_a_statement_not_a_default():
    """The distinction the whole module rests on: the perimeter is the right answer when
    the drawing SAYS so, and the wrong one when nobody said anything."""
    out = banded_length_mm(_tray(description="TRAY, ABS EDGE BANDED ALL ROUND"))
    assert out["mm"] == 1560.0
    assert out["basis"] == "note_all_round"
    assert "stated" in out["evidence"] and "assumed" in out["evidence"]


def test_two_long_edges_measures_two_long_edges():
    out = banded_length_mm({"blank_length_mm": 600.0, "blank_width_mm": 300.0,
                            "description": "SHELF, ABS EDGING TWO LONG EDGES"})
    assert out["mm"] == 1200.0, out
    assert out["basis"] == "note_named_edges"


def test_a_front_edge_is_one_long_edge():
    out = banded_length_mm({"blank_length_mm": 600.0, "blank_width_mm": 300.0,
                            "description": "SHELF, ABS EDGE TO FRONT EDGE"})
    assert out["mm"] == 600.0


def test_the_long_side_is_the_long_side_whichever_way_it_was_drawn():
    """A blank entered 300 x 600 is the same shelf as 600 x 300."""
    a = banded_length_mm({"blank_length_mm": 600.0, "blank_width_mm": 300.0,
                          "description": "ABS EDGING BOTH LONG EDGES"})
    b = banded_length_mm({"blank_length_mm": 300.0, "blank_width_mm": 600.0,
                          "description": "ABS EDGING BOTH LONG EDGES"})
    assert a["mm"] == b["mm"] == 1200.0


def test_a_note_in_the_drawing_texts_counts_as_much_as_the_description():
    out = banded_length_mm(_tray(
        normalized_geometry={"texts": ["SCALE 1:2", "ABS EDGE BANDED ALL ROUND"]}))
    assert out["mm"] == 1560.0


# ── 3 · banding stated, extent unknown: raised, not measured ─────────────────────────

def test_visible_edges_is_named_but_not_measurable():
    """"Visible edges" says banding happens and not how much. Guessing the extent is the
    original fault; the line is raised instead."""
    out = banded_length_mm(_tray(description="TRAY, ABS EDGING TO VISIBLE EDGES"))
    assert out["mm"] is None
    assert out["basis"] == "banding_stated_extent_unknown"


def test_a_bare_mention_of_edging_does_not_produce_a_length():
    out = banded_length_mm(_tray(description="TRAY, ABS EDGED"))
    assert out["mm"] is None
    assert out["basis"] == "banding_stated_extent_unknown"
    assert "ceiling" in out["evidence"]


# ── and the word has to be about BANDING ─────────────────────────────────────────────

def test_the_word_edge_alone_is_not_an_instruction():
    """"EDGE OF PLINTH" is a location, not a banding note."""
    out = banded_length_mm(_tray(description="TRAY SITS TO EDGE OF PLINTH ALL ROUND"))
    assert out["mm"] is None, out
    assert out["basis"] == "no_evidence"


# ── and the writer uses it ───────────────────────────────────────────────────────────

def test_the_workbook_asks_the_reader_rather_than_measuring_the_perimeter():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "wb_populate.py"
           ).read_text(encoding="utf-8")
    assert "from edge_banding import banded_length_mm as _banded_of" in src
    assert "_edge_m = round(_banded_mm / 1000.0, 2)" in src, (
        "the edging metreage must come from the banded edges, not from 2*(L+W)")
    assert "2.0 * (float(_l) + float(_w)) / 1000.0" not in src, (
        "the perimeter default is back")


def test_the_line_says_which_of_the_two_states_it_is_in():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "wb_populate.py"
           ).read_text(encoding="utf-8")
    assert "EDGING NOT ESTABLISHED" in src
    assert "measured from the edges the" in src
    assert "ceiling" in src
