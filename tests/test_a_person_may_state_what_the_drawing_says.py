r"""
test_a_person_may_state_what_the_drawing_says.py

THE TOP OF THE RANKING WAS A DOOR WITH NO HANDLE ON THE OUTSIDE.

source_precedence has ranked `estimator_confirmed` at 100 — above the model, above a measured
DXF — since it was written, on the stated reasoning that "an estimator correcting a part is the
one signal that carries knowledge the drawing does not". Nothing in the codebase ever wrote
that source. The only way to state a fact the readers could not extract was to change code.

0359342 is the bill for that. Its parts bound to their parent's parts list instead of their own
detail sheet, so geometry_inference issued category defaults — 400 x 300 to anything named
PANEL — and those envelopes drove the nest, the laser and the coated area. The printed sizes
were on the sheets throughout: JAE826 1680 x 560, JAE832 1670 x 546, MBY439 1578 x 188. Costing
a 1680 x 560 panel as 400 x 300 is an UNDER-charge of about nine times on that panel's board,
and an under-charge is the one error that never comes back as a complaint.

Two attempts to teach the extractor to read these sheets failed — the figures are printed, but
choosing which pair is the overall is a view-and-direction problem the flat text layer does not
carry. A person reads the sheet in ten seconds. These tests cover the door that lets them, and
in particular the four ways it could be dangerous:

  * it must BEAT the guess (or it is decoration),
  * it must REFUSE a price (or it becomes a channel for invented money),
  * it must REFUSE half a rectangle (or it re-creates the defaulting it exists to end),
  * it must SHOUT when a code matches nothing (or it silently does nothing and is trusted).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import source_precedence as sp                                        # noqa: E402
from estimator_confirmed import (                                     # noqa: E402
    apply_estimator_confirmed,
    find_corrections_file,
    load_corrections,
)


def _write(tmp_path: Path, payload: dict, name: str = "estimator_dimensions.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _confirmed(**parts) -> dict:
    return {"confirmed_by": "J Gray", "confirmed_on": "2026-09-10",
            "parts": parts, "path": "test"}


# ── it must beat the guess ────────────────────────────────────────────────────────────

def test_a_confirmed_size_displaces_the_category_default():
    """JAE826's real 1680 x 560 must replace the 400 x 300 envelope geometry_inference issued.

    This is the whole purpose. If the guess survived, the panel would still nest at a ninth of
    its area and the quote would still be too low.
    """
    part = {"part_number": "JAE826"}
    sp.apply_field(part, "blank_length_mm", 400.0, "inference")
    sp.apply_field(part, "blank_width_mm", 300.0, "inference")

    report = apply_estimator_confirmed(
        [part], _confirmed(JAE826={"blank_length_mm": 1680, "blank_width_mm": 560,
                                   "thickness_mm": 18, "material": "MDF",
                                   "read_from": "page 14, printed overall"}))

    assert part["blank_length_mm"] == 1680
    assert part["blank_width_mm"] == 560
    assert part["normalized_thickness_mm"] == 18
    assert report["stamped"] == 1
    # and it says so on its own record, naming the person and the sheet
    flags = " ".join(part["review_flags"])
    assert "J Gray" in flags and "page 14" in flags


def test_a_dxf_beats_a_figure_read_off_the_drawing():
    """WITHDRAWN AND REVERSED, on the business rule: the DXF and the model are authoritative.

    This test used to assert the opposite — that a figure typed into the confirmations file
    outranked a measured DXF, on the reasoning that a person holding the drawing can see a
    stale export. The reasoning was fine; the rank was applied to the wrong ACT. Reading an
    overall off a PDF is not overturning a flat pattern, it is reading the same drawing the
    engine read. The DXF is the file the laser cuts from, so where they disagree it wins.

    Overruling the CAD is a different, deliberate claim — see the 'corrected' basis below.
    """
    part = {"part_number": "MBY439"}
    sp.apply_field(part, "blank_length_mm", 900.0, "dxf")

    apply_estimator_confirmed(
        [part], _confirmed(MBY439={"blank_length_mm": 1578, "blank_width_mm": 188}))

    assert part["blank_length_mm"] == 900.0, "the measured flat stands"
    displaced = (part.get("_displaced") or {}).get("blank_length_mm") or []
    assert any(d.get("value") == 1578 and not d.get("applied") for d in displaced), \
        "and the reading that lost is recorded, not discarded"


def test_a_deliberate_correction_does_overrule_the_cad():
    """The escape hatch, claimed on purpose and argued for. An estimator who knows the DXF is
    a superseded revision says so, and rank 100 is theirs."""
    part = {"part_number": "MBY439"}
    sp.apply_field(part, "blank_length_mm", 900.0, "dxf")

    apply_estimator_confirmed([part], {"confirmed_by": "J Gray", "parts": {"MBY439": {
        "blank_length_mm": 1578, "blank_width_mm": 188, "basis": "corrected",
        "read_from": "the DXF in the folder is Rev J; the pack issued is Rev 4"}}})

    assert part["blank_length_mm"] == 1578
    assert sp.source_of(part, "blank_length_mm") == "estimator_confirmed"
    assert "OVERRULING the CAD files" in " ".join(part["review_flags"])


def test_a_correction_without_a_reason_is_refused(tmp_path: Path):
    """This is the one basis that beats a measurement, so it must say why the files are wrong."""
    path = _write(tmp_path, {"parts": {"A": {"blank_length_mm": 10, "blank_width_mm": 5,
                                             "basis": "corrected"}}})
    data, problems = load_corrections(path)
    assert any("OUTRANKS the DXF" in p for p in problems)
    assert not data["parts"].get("A", {}).get("blank_length_mm")


def test_a_read_figure_still_beats_every_machine_reading_of_the_same_sheet():
    """72 sits above the deterministic title-block read (70) and the machine's own overall
    read (65): a person looking at the sheet beats a parser looking at the sheet."""
    part = {"part_number": "JAE826"}
    sp.apply_field(part, "blank_length_mm", 9.9, "drawing_deterministic")
    apply_estimator_confirmed(
        [part], _confirmed(JAE826={"blank_length_mm": 1680, "blank_width_mm": 560}))
    assert part["blank_length_mm"] == 1680
    assert sp.source_of(part, "blank_length_mm") == "estimator_read_drawing"


def test_nothing_weaker_can_take_it_back():
    """Once confirmed, a later inference pass must not overwrite it — that is what rank means."""
    part = {"part_number": "JAE832"}
    apply_estimator_confirmed(
        [part], _confirmed(JAE832={"blank_length_mm": 1670, "blank_width_mm": 546}))

    assert sp.apply_field(part, "blank_length_mm", 350.0, "inference") is False
    assert part["blank_length_mm"] == 1670


# ── price it, and say what you assumed ────────────────────────────────────────────────

def test_an_inference_is_priced_but_does_not_wear_a_readings_rank():
    """THE CORRECTION THAT MATTERS MOST HERE.

    The first version of this file took readings only, so anything a drawing did not print
    had to be left out — and six parts of 0359342 were, including a thermoformed Corian tray
    whose sheet gives the FINISHED size and no flat pattern. That was wrong. A drawing pack
    is never perfect; an estimate with holes cannot be quoted from, and a hole is not more
    honest than a stated assumption, only less useful. An estimator can overturn an
    assumption they can see; they can do nothing with a blank.

    So an inference IS priced — and at rank 45, not 100, so any measurement displaces it.
    """
    part = {"part_number": "JAE823"}
    sp.apply_field(part, "blank_length_mm", 400.0, "inference")   # a category default

    apply_estimator_confirmed([part], {
        "confirmed_by": "J Gray", "parts": {"JAE823": {
            "blank_length_mm": 888, "blank_width_mm": 788, "basis": "inferred",
            "read_from": "650 + 2x95 sides + 2x24 returns, off the section on page 11"}}})

    assert part["blank_length_mm"] == 888, "it must beat the category default it replaces"
    assert sp.source_of(part, "blank_length_mm") == "estimator_inferred"
    flags = " ".join(part["review_flags"])
    assert "INFERRED" in flags and "does not print this figure" in flags
    assert "650 + 2x95" in flags, "the working must travel with the figure"


def test_a_measurement_displaces_an_inference_and_a_reading_alike():
    """The whole point of two ranks. 45 loses to a DXF; 100 does not."""
    inferred = {"part_number": "A"}
    sp.apply_field(inferred, "blank_length_mm", 999.0, "dxf")
    apply_estimator_confirmed([inferred], {"parts": {"A": {
        "blank_length_mm": 888, "blank_width_mm": 788, "basis": "inferred",
        "read_from": "worked out from the section"}}})
    assert inferred["blank_length_mm"] == 999.0, "a measurement beats an inference"

    # ...and so does a reading, since the DXF is what the laser cuts from. The three bases
    # are ordered corrected (100) > read (72) > inferred (45), with every measurement
    # sitting between the first and the second.
    read = {"part_number": "A"}
    sp.apply_field(read, "blank_length_mm", 999.0, "dxf")
    apply_estimator_confirmed([read], {"parts": {"A": {
        "blank_length_mm": 1680, "blank_width_mm": 560}}})
    assert read["blank_length_mm"] == 999.0, "a DXF beats a sheet reading too"
    assert sp.rank("estimator_confirmed") > sp.rank("dxf") > sp.rank("estimator_read_drawing") \
        > sp.rank("estimator_inferred")


def test_an_inference_without_its_working_is_refused(tmp_path: Path):
    """A number with no stated reasoning is a guess wearing a person's authority, which is
    the one thing this file must never launder."""
    path = _write(tmp_path, {"parts": {"JAE823": {
        "blank_length_mm": 888, "blank_width_mm": 788, "basis": "inferred"}}})
    data, problems = load_corrections(path)
    assert any("no reasoning is given" in p for p in problems)
    assert not data["parts"].get("JAE823", {}).get("blank_length_mm")


def test_a_reading_needs_no_working():
    """Only an inference has to argue for itself; a printed figure speaks for itself."""
    part = {"part_number": "JAE826"}
    apply_estimator_confirmed([part], {"parts": {"JAE826": {
        "blank_length_mm": 1680, "blank_width_mm": 560}}})
    assert part["blank_length_mm"] == 1680
    assert sp.source_of(part, "blank_length_mm") == "estimator_read_drawing"


def test_an_unknown_basis_is_refused_rather_than_silently_treated_as_read(tmp_path: Path):
    path = _write(tmp_path, {"parts": {"A": {"blank_length_mm": 10, "blank_width_mm": 5,
                                             "basis": "probably"}}})
    _data, problems = load_corrections(path)
    assert any("basis" in p and "not understood" in p for p in problems)


# ── it must refuse a price ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["price", "cost", "rate", "unit_price", "material_cost"])
def test_a_price_is_refused_by_name_and_explained(tmp_path: Path, key: str):
    """A rate typed here would be indistinguishable in the output from one the engine sourced.

    The standing rule of this codebase is that no price is invented. This file states what the
    DRAWING says. Refusing quietly would be nearly as bad as accepting: the writer has to be
    told, or they will believe the job was costed from their figure.
    """
    path = _write(tmp_path, {"parts": {"MBY432": {"blank_length_mm": 219.6,
                                                  "blank_width_mm": 8.0,
                                                  key: 12.00}}})
    data, problems = load_corrections(path)

    assert key not in data["parts"]["MBY432"], "a price must never reach the part record"
    assert any(key in p and "REFUSED" in p for p in problems), \
        "the refusal must be reported, not silent"
    # the legitimate fields on the same line still land
    assert data["parts"]["MBY432"]["blank_length_mm"] == 219.6


# ── it must refuse half a rectangle ───────────────────────────────────────────────────

def test_a_length_without_a_width_is_not_a_blank(tmp_path: Path):
    """Both dimensions or neither — the same guardrail blank_credibility applies to readers.

    Accepting a lone length would leave the width to a category default, which is precisely the
    defaulting this feature exists to end, only now wearing rank 100.
    """
    path = _write(tmp_path, {"parts": {"JAE821": {"blank_length_mm": 638}}})
    data, problems = load_corrections(path)

    assert "JAE821" not in data["parts"] or "blank_length_mm" not in data["parts"]["JAE821"]
    assert any("blank_width_mm" in p and "missing" in p for p in problems)


def test_both_dimensions_together_are_accepted(tmp_path: Path):
    path = _write(tmp_path, {"parts": {"JAE821": {"blank_length_mm": 638,
                                                  "blank_width_mm": 75}}})
    data, problems = load_corrections(path)
    assert data["parts"]["JAE821"]["blank_length_mm"] == 638
    assert data["parts"]["JAE821"]["blank_width_mm"] == 75
    assert not problems


# ── it must shout when a code matches nothing ─────────────────────────────────────────

def test_a_code_matching_no_part_is_reported_not_swallowed():
    """A typo'd code that silently does nothing is how this feature gets trusted for free.

    The operator believes the job is being costed from their figures. If JAE8266 quietly
    matches nothing, the panel keeps its 400 x 300 envelope and the quote goes out low with a
    confirmations file sitting next to it that appears to have handled it.
    """
    parts = [{"part_number": "JAE826"}]
    report = apply_estimator_confirmed(
        parts, _confirmed(JAE8266={"blank_length_mm": 1680, "blank_width_mm": 560}))

    assert report["unmatched"] == ["JAE8266"]
    assert report["stamped"] == 0


def test_an_unreadable_field_is_reported(tmp_path: Path):
    path = _write(tmp_path, {"parts": {"JAE826": {"blank_length_mm": "one thousand",
                                                  "blank_width_mm": 560}}})
    _data, problems = load_corrections(path)
    assert any("not a positive number" in p for p in problems)


def test_an_unknown_field_name_is_reported(tmp_path: Path):
    path = _write(tmp_path, {"parts": {"JAE826": {"lenght_mm": 1680}}})
    _data, problems = load_corrections(path)
    assert any("lenght_mm" in p for p in problems)


# ── file discovery ───────────────────────────────────────────────────────────────────

def test_a_job_specific_file_wins_over_the_generic_one(tmp_path: Path):
    """A folder holding more than one job must not have one file quietly govern them all."""
    _write(tmp_path, {"parts": {"A": {"blank_length_mm": 1, "blank_width_mm": 1}}},
           "estimator_dimensions.json")
    _write(tmp_path, {"parts": {"B": {"blank_length_mm": 2, "blank_width_mm": 2}}},
           "0359342_estimator_dimensions.json")

    found = find_corrections_file(tmp_path, None, "0359342")
    assert found is not None and found.name == "0359342_estimator_dimensions.json"


def test_no_file_is_the_normal_case(tmp_path: Path):
    assert find_corrections_file(tmp_path, None, "0359342") is None


def test_a_malformed_file_reports_rather_than_raising(tmp_path: Path):
    path = tmp_path / "estimator_dimensions.json"
    path.write_text("{not json", encoding="utf-8")
    data, problems = load_corrections(path)
    assert data == {} and problems and "could not be read" in problems[0]


def test_quantity_is_a_whole_number(tmp_path: Path):
    path = _write(tmp_path, {"parts": {"MBY433": {"quantity": 27.5}}})
    _data, problems = load_corrections(path)
    assert any("whole number" in p for p in problems)


def test_a_confirmed_quantity_lands_on_the_part():
    """56 prong assemblies, not 28: the back-panel assembly that carries them is itself qty 2."""
    part = {"part_number": "MBY433", "quantity": 28}
    apply_estimator_confirmed([part], _confirmed(MBY433={"quantity": 56}))
    assert part["quantity"] == 56


# ── a lamination is one component made of several materials ───────────────────────────

def test_every_declared_layer_reaches_the_price():
    """JAE827 IS THE CASE, and my own note on it was the defect.

    "Flexi MDF 6mm and 9mm" is a curved corner laminated from two boards. The part record
    holds one material and one thickness, so only one could ever be priced — and when I wrote
    the assumption I priced the 9mm and NOTED that the 6mm was excluded. Writing an omission
    down does not make it a decision; it records that money is missing. An explanation must
    never legitimise an exclusion.
    """
    from estimator import estimate_material, _price_declared_material_layers

    part = {"part_number": "JAE827", "quantity": 2, "review_flags": []}
    apply_estimator_confirmed([part], {"confirmed_by": "J Gray", "parts": {"JAE827": {
        "blank_length_mm": 250, "blank_width_mm": 320, "thickness_mm": 9, "material": "MDF",
        "basis": "inferred", "read_from": "100 + 100 legs plus a quarter-arc at R49",
        "layers": [
            {"material": "MDF", "thickness_mm": 9, "blank_length_mm": 250,
             "blank_width_mm": 320, "note": "outer skin"},
            {"material": "MDF", "thickness_mm": 6, "blank_length_mm": 250,
             "blank_width_mm": 320, "note": "inner skin"}]}}})

    assert len(part["material_layers"]) == 2

    primary = estimate_material(part)
    both = _price_declared_material_layers(part, primary)
    assert both["unit_material_cost_gbp"] > primary["unit_material_cost_gbp"], \
        "the second lamination is bought and must be charged"
    assert len(both["material_layers_priced"]) == 1, "one extra layer beyond the primary"
    assert both["material_layers_priced"][0]["thickness_mm"] == 6

    flags = " ".join(part["review_flags"])
    assert "BONDING" in flags, \
        "the labour the engine cannot model must be named, not left to read as included"


def test_a_declared_layer_that_never_reached_the_price_is_blocking():
    """Silent in every other view: the line has a material, a size and a plausible cost, and
    nothing about it reads as incomplete. The estimate's own record is what proves it."""
    from invariants import BLOCKING, check_every_declared_material_layer_is_priced, CHECKS

    assert check_every_declared_material_layer_is_priced in CHECKS, \
        "an unregistered check runs nowhere"

    # The COSTED record, which is what invariants._parts walks — material_layers has to
    # cross the costing boundary or the check finds the answer and never the question.
    summary = {"estimate_summary": {"part_estimates": [{
        "part_number": "JAE827", "quantity": 2,
        "material_layers": [{"material": "MDF", "thickness_mm": 9},
                            {"material": "MDF", "thickness_mm": 6}],
        "material_estimate": {"unit_material_cost_gbp": 0.76},   # only the primary
    }]}}
    hits = check_every_declared_material_layer_is_priced(summary)
    assert hits and hits[0]["severity"] == BLOCKING
    assert "only 1 of 2 layers were costed at all" in hits[0]["message"]


def test_a_lamination_that_is_fully_priced_does_not_fire():
    from invariants import check_every_declared_material_layer_is_priced
    summary = {"estimate_summary": {"part_estimates": [{
        "part_number": "JAE827",
        "material_layers": [{"material": "MDF", "thickness_mm": 9},
                            {"material": "MDF", "thickness_mm": 6}],
        "material_estimate": {"unit_material_cost_gbp": 1.27,
                              "material_layers_priced": [{"layer": 2, "priced": True}],
                              "material_layers_primary_matches": True,
                              "material_layers_reach_workbook": True},
    }]}}
    assert check_every_declared_material_layer_is_priced(summary) == []


def test_a_layer_without_a_material_or_gauge_cannot_be_priced_so_is_refused(tmp_path: Path):
    path = _write(tmp_path, {"parts": {"A": {"layers": [
        {"material": "MDF", "thickness_mm": 9}, {"note": "the other one"}]}}})
    _data, problems = load_corrections(path)
    assert any("needs at least a material and a thickness_mm" in p for p in problems)


def test_one_layer_is_not_a_lamination(tmp_path: Path):
    path = _write(tmp_path, {"parts": {"A": {
        "layers": [{"material": "MDF", "thickness_mm": 9}]}}})
    _data, problems = load_corrections(path)
    assert any("fewer than two usable layers" in p for p in problems)


def test_the_layer_declaration_crosses_the_costing_boundary():
    """A check that cannot see what it is checking is worse than no check — it reports CLEAR.

    material_estimate crossed into the costed record carrying material_layers_priced, and the
    DECLARATION of what layers exist did not, so the invariant would have found the answer and
    never the question: len(layers) < 2, short-circuit, silent pass. Asserted against the
    estimator's own record-builder so the two cannot drift apart.
    """
    source = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert '"material_layers": part.get("material_layers")' in source, \
        "the layer declaration must travel with the money it explains"


def test_a_layer_that_returned_no_price_is_not_counted_as_priced():
    """COUNTING RECORDS IS NOT COUNTING PRICES. The first version appended an entry whichever
    way the pricing went and substituted £0 for a miss, so a layer that cost NOTHING still
    counted as one of N — and the check answered "yes" by tallying its own failures."""
    from invariants import BLOCKING, check_every_declared_material_layer_is_priced
    summary = {"estimate_summary": {"part_estimates": [{
        "part_number": "X",
        "material_layers": [{"material": "MDF", "thickness_mm": 9},
                            {"material": "Corian", "thickness_mm": 6}],
        "material_estimate": {
            "material_layers_priced": [{"layer": 2, "priced": False,
                                        "unit_material_cost_gbp": 0.0}],
            "material_layers_primary_matches": True,
            "material_layers_reach_workbook": True},
    }]}}
    hits = check_every_declared_material_layer_is_priced(summary)
    assert hits and hits[0]["severity"] == BLOCKING
    assert "costs nothing was not bought" in hits[0]["message"]


def test_the_primary_layer_is_checked_against_what_was_actually_priced():
    """CAD precedence can move the part's material or gauge after the layers were declared.
    Then the board counted as layer 1 is not the board that was declared: one priced twice,
    another not at all, and every count still balancing."""
    from estimator import estimate_material, _price_declared_material_layers
    part = {"part_number": "X", "quantity": 1, "normalized_material": "MDF",
            "normalized_thickness_mm": 12.0,          # a DXF displaced the confirmed 9mm
            "blank_length_mm": 250.0, "blank_width_mm": 320.0, "review_flags": [],
            "material_layers": [{"material": "MDF", "thickness_mm": 9},
                                {"material": "MDF", "thickness_mm": 6}]}
    costed = _price_declared_material_layers(part, estimate_material(part))
    assert costed["material_layers_primary_matches"] is False

    from invariants import check_every_declared_material_layer_is_priced
    hits = check_every_declared_material_layer_is_priced(
        {"estimate_summary": {"part_estimates": [dict(part, material_estimate=costed)]}})
    assert hits and any("no longer matches the first declared layer" in r
                        for r in hits[0]["detail"]["parts"][0]["reasons"])


def test_the_workbook_gap_is_blocking_until_the_writer_carries_the_layers():
    """THE ONE THAT MATTERS TO THE CUSTOMER'S NUMBER.

    _price_declared_material_layers raises unit_material_cost_gbp; the Other Sheet and Sheet
    Steel writers do not read it. They take material_estimate.sheet_price_gbp and let the
    WORKBOOK recompute cost-per-part from sheet price over parts-per-sheet, using
    unit_material_cost_gbp only as a fallback when no sheet price exists. So on the ordinary
    board path the extra layer's money is computed and then dropped on the way to the sheet
    the customer is quoted from.

    A second board is a second sheet consumption and needs its own workbook ROW. Until that
    writer exists this is BLOCKING, because the one thing worse than a missing layer is a
    missing layer that reports CLEAR.
    """
    from estimator import estimate_material, _price_declared_material_layers
    from invariants import BLOCKING, check_every_declared_material_layer_is_priced
    part = {"part_number": "JAE827", "quantity": 2, "normalized_material": "MDF",
            "normalized_thickness_mm": 9.0, "blank_length_mm": 250.0,
            "blank_width_mm": 320.0, "review_flags": [],
            "material_layers": [{"material": "MDF", "thickness_mm": 9},
                                {"material": "MDF", "thickness_mm": 6}]}
    costed = _price_declared_material_layers(part, estimate_material(part))
    assert costed["material_layers_reach_workbook"] is False, \
        "flip this to True only when the sheet writers emit a row per layer"

    hits = check_every_declared_material_layer_is_priced(
        {"estimate_summary": {"part_estimates": [dict(part, material_estimate=costed)]}})
    assert hits and hits[0]["severity"] == BLOCKING
    assert "does not reach the workbook" in hits[0]["message"]
