r"""
test_the_material_as_printed_states_its_stock_form.py

A PRINTED MATERIAL CELL STATES MORE THAN ONE THING.

0359342's MBY432 says, in the material column of its own drawing:

    "Steel, Mild Wire Ø8mm"
     \_________/ \__/ \___/
      material   form   Ø

Three facts. The engine kept one of them, and not even reliably:

  * normalise_material() is an ordered SUBSTRING lookup keyed "MILD STEEL", and M&S write
    the surname first — "Steel, Mild". So the material was in the book all along and
    normalised to None. "Steel, Mild 2mm" (MBY439) lost its material the same way.
  * part["materials"] is only populated `if part.get("normalized_material")`, so a None
    left the list EMPTY.
  * the wire test read that empty list, hunting for the word "WIRE" inside a material NAME.

So a Ø8 x 219.6 solid prong, 56 off, was classified as sheet: nested as plate, and carrying
a laser and a fold that a solid bar can never incur.

THE FIX THAT ONLY REPAIRS NORMALISATION IS NOT A FIX. Normalising "Steel, Mild Wire Ø8mm"
to MILD_STEEL is right for the RATE and DESTROYS the word the classifier was looking for —
the rate resolves, the routing stays broken, and it looks fixed. So the facts are read once
and kept apart, and each consumer takes the one it needs:

    material    -> the rate table
    stock_form  -> the route
    diameter    -> the gauge, never a sheet thickness
    text        -> preserved always, so an unrecognised material is still evidence

These tests therefore run the CHAIN — printed cell -> stock form -> route -> costing basis —
not merely normalise_material() returning a value. Length is deliberately not in it: a cell
states the section, never how much of it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from json_normaliser import normalise_material, read_material_as_printed   # noqa: E402
from stock_form_rules import impossibility_reason, is_impossible_operation  # noqa: E402

MBY432 = "Steel, Mild Wire Ø8mm"
MBY439 = "Steel, Mild 2mm"


# ── 1. the surname-first form resolves, and only adds answers ─────────────────────────

@pytest.mark.parametrize("printed,expected", [
    (MBY432, "MILD_STEEL"),
    (MBY439, "MILD_STEEL"),
    ("Steel, Mild Wire Dia 8mm", "MILD_STEEL"),
])
def test_a_material_written_surname_first_still_resolves(printed, expected):
    assert normalise_material(printed) == expected


@pytest.mark.parametrize("printed,expected", [
    ("Mild Steel", "MILD_STEEL"),
    ("CR4, 2mm", "MILD_STEEL"),
    ("MDF, 18mm", "MDF"),
    ("2mm ACRYLIC", "ACRYLIC"),
    ("Plywood, Birch 18mm", "PLYWOOD"),
])
def test_the_word_order_pass_never_changes_an_answer_the_lexicon_already_gives(printed, expected):
    """Safe by construction: it runs only when the direct pass found nothing."""
    assert normalise_material(printed) == expected


@pytest.mark.parametrize("printed", ["Corian, 6mm", "Mirror, 6mm", "Lamainate Edging",
                                     "Vinyl, Clear - Black Print"])
def test_a_material_the_book_does_not_hold_stays_unresolved(printed):
    """A genuine gap must stay a gap. Guessing the nearest entry is how a Corian tray gets
    priced as board — the lexicon is missing these, and that is an estimator's question."""
    assert normalise_material(printed) is None


# ── 2. the facts are kept apart ───────────────────────────────────────────────────────

def test_the_printed_cell_yields_material_form_and_diameter_separately():
    read = read_material_as_printed(MBY432)
    assert read["material"] == "MILD_STEEL"      # for the rate
    assert read["stock_form"] == "wire"          # for the route
    assert read["diameter_mm"] == 8.0            # the gauge
    assert read["text"] == MBY432                # preserved verbatim


def test_an_unrecognised_material_keeps_its_text():
    """None must not erase evidence — the cell still says Corian and someone must act on it."""
    read = read_material_as_printed("Corian, 6mm")
    assert read["material"] is None
    assert read["text"] == "Corian, 6mm"


def test_a_gauge_is_not_a_diameter():
    """MBY439 is 2mm sheet steel. Nothing about it is round, and no diameter may be invented."""
    read = read_material_as_printed(MBY439)
    assert read["material"] == "MILD_STEEL"
    assert read["stock_form"] != "wire"
    assert read["diameter_mm"] is None


def test_a_cell_that_names_no_section_does_not_imply_sheet():
    """Inventing 'sheet' here would re-create the category default this exists to remove."""
    assert read_material_as_printed("CR4, 2mm")["stock_form"] == ""


@pytest.mark.parametrize("printed,form", [
    ("25x25x2 Mild Steel Tube", "tube"),
    ("Mild Steel Bar Ø12", "wire"),
    ("Steel Flat Bar 25x3", "sheet"),
    ("WIRE MESH GALV", ""),
])
def test_the_form_vocabulary_is_read_from_the_cell(printed, form):
    """A bare BAR needs a diameter to count as round; WIRE MESH is a section, not a wire."""
    assert read_material_as_printed(printed)["stock_form"] == form


# ── 3. the chain: printed cell -> route ───────────────────────────────────────────────

def test_the_printed_cell_makes_the_sheet_operations_impossible():
    """THE ACCEPTANCE TEST. Not 'normalise_material returned something' — the operations a
    solid Ø8 bar cannot have must actually be refused, with a reason an estimator can read.

    stock_form_rules has always known this. It only ever needed to be told the form.
    """
    form = read_material_as_printed(MBY432)["stock_form"]
    assert form == "wire"

    for operation in ("laser_cutting", "laser", "fold", "folding",
                      "punch", "linebend", "guillotine"):
        assert is_impossible_operation(operation, form), \
            f"{operation} must be refused on a solid wire"
        assert "no flat blank" in impossibility_reason(operation, form)


def test_the_operations_a_wire_does_have_survive():
    """Weld and dress are not impossible on wire — MBY433 is 56 puddle-welded prongs, and a
    rule that stripped those would replace an over-charge with an under-charge."""
    form = read_material_as_printed(MBY432)["stock_form"]
    for operation in ("welding", "weld", "robomac", "dress_welds", "assembly"):
        assert not is_impossible_operation(operation, form), \
            f"{operation} is real work on a wire part and must survive"


def test_the_same_operations_stay_possible_on_the_sheet_part():
    """The guard must not leak onto MBY439, which is 2mm sheet and IS lasered and folded."""
    form = read_material_as_printed(MBY439)["stock_form"]
    for operation in ("laser_cutting", "fold", "punch"):
        assert not is_impossible_operation(operation, form)


# ── 4. the chain: printed cell -> costing basis ───────────────────────────────────────

def test_the_costing_basis_reads_the_stock_form_not_the_material_name():
    """estimator's linear-stock test keys on stock_form, so once the form is set the part
    prices per length instead of nesting as plate. Asserted against the estimator's OWN
    vocabulary so the two cannot drift apart."""
    import estimator
    source = Path(estimator.__file__).read_text(encoding="utf-8")
    assert '_LINEAR_STOCK = {"wire", "bar", "tube", "section", "profile", "extrusion", "rod"}' \
        in source, "the linear-stock vocabulary moved — this chain needs rechecking"
    assert read_material_as_printed(MBY432)["stock_form"] in {
        "wire", "bar", "tube", "section", "profile", "extrusion", "rod"}


def test_a_diameter_is_never_handed_on_as_a_thickness():
    """The misread that priced a Ø8 prong as 8mm plate. A diameter is reported only for a
    round section, so nothing downstream can read it as a gauge."""
    for printed in (MBY439, "CR4, 2mm", "MDF, 18mm", "Steel Flat Bar 25x3"):
        assert read_material_as_printed(printed)["diameter_mm"] is None
