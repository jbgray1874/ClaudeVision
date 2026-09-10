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


def test_a_confirmed_size_outranks_even_a_measured_dxf():
    """Rank 100 beats rank 80 — deliberately, and the displacement is still recorded.

    This asymmetry is the point of the rank: a DXF can be of the wrong revision, and a person
    holding the drawing is the only source that can say so.
    """
    part = {"part_number": "MBY439"}
    sp.apply_field(part, "blank_length_mm", 900.0, "dxf")

    apply_estimator_confirmed(
        [part], _confirmed(MBY439={"blank_length_mm": 1578, "blank_width_mm": 188}))

    assert part["blank_length_mm"] == 1578
    displaced = (part.get("_displaced") or {}).get("blank_length_mm") or []
    assert any(d.get("value") == 900.0 for d in displaced), \
        "the DXF figure must be recorded as displaced, not vanish"


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


def test_a_measurement_displaces_an_inference_but_not_a_reading():
    """The whole point of two ranks. 45 loses to a DXF; 100 does not."""
    inferred = {"part_number": "A"}
    sp.apply_field(inferred, "blank_length_mm", 999.0, "dxf")
    apply_estimator_confirmed([inferred], {"parts": {"A": {
        "blank_length_mm": 888, "blank_width_mm": 788, "basis": "inferred",
        "read_from": "worked out from the section"}}})
    assert inferred["blank_length_mm"] == 999.0, "a measurement beats an inference"

    read = {"part_number": "A"}
    sp.apply_field(read, "blank_length_mm", 999.0, "dxf")
    apply_estimator_confirmed([read], {"parts": {"A": {
        "blank_length_mm": 1680, "blank_width_mm": 560}}})
    assert read["blank_length_mm"] == 1680, "a reading off the sheet still outranks it"


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
    assert sp.source_of(part, "blank_length_mm") == "estimator_confirmed"


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
