"""A material the engine can cost must be a material the engine can read off a filename.

`material_from_dxf_filename` KNEW HIPS, ACRYLIC, POLYCARBONATE, MDF AND THE STEELS — AND NOT
PETG, AND NOT ABS. 11650-04's exports are named `11650-04-01A_2MM PETG_REVG`, and it returned
the gauge and no material at all.

WHAT THAT COST. Three commits of arbitration rested on this one reading. The filename was
promoted to real evidence so a quorum could outvote a lone SolidWorks property; the quorum
went on counting ONE source, because the only other reading of PETG was the title block and
this one had submitted nothing. The companion rule that keeps material and gauge together
found no corroboration to act on. The pair-level rule found the hands agreeing on ABS and had
nothing to settle. Every one of those rules was correct and none of them could fire, because
the vocabulary could not say the word.

A PRIVATE LIST OF MATERIALS BESIDE THE ENGINE'S OWN IS THE DUAL-PATH DEFECT, spelled in nouns
instead of numbers — and the silent kind: a material nobody names reads exactly like a filename
that named nothing. `costed_facts` already holds the vocabulary that decides which materials
are costed as sheet at all. A second list here could only drift from it.

SO THE GUARD IS THE POINT, NOT THE TWO WORDS. Adding a material to `costed_facts` must teach
this reader too, and the suite fails until it does.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cad_inputs  # noqa: E402
import costed_facts  # noqa: E402
from drawing_job_merge import material_from_dxf_filename as material_of  # noqa: E402
from drawing_job_merge import thickness_mm_from_dxf_filename as gauge_of  # noqa: E402


# ── the regression ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expect", [
    ("11650-04-01A_2MM PETG_REVG.DXF", "PETG"),
    ("11650-04-03A_2MM ABS.DXF", "ABS"),
])
def test_the_materials_this_job_is_made_of_are_read_from_the_export(name, expect):
    assert material_of(Path(name)) == expect


def test_the_export_yields_a_whole_stock_key_not_half_of_one():
    """It returned the gauge and no material, which is worse than returning nothing: half a
    reading submits a gauge that argues with the model while the material it belonged to never
    arrives to explain it."""
    p = Path("11650-04-01A_2MM PETG_REVG.DXF")
    assert material_of(p) == "PETG" and gauge_of(p) == 2.0


# ── the guard that makes it inheritable ──────────────────────────────────────────────

def _vocabulary():
    return [t.strip() for t in
            costed_facts._PLASTIC_SHEET_TOKENS + costed_facts._BOARD_TIMBER_TOKENS
            if len(t.strip()) >= 3]


def test_every_material_the_engine_costs_as_sheet_can_be_read_off_a_filename():
    """THE WHOLE POINT OF THIS FILE. Not "PETG works now" — that is one word. A material the
    engine will happily cost and cannot recognise in the name of the file it is cut from is a
    silent half-reading waiting to happen, and this is how the next one is caught at the commit
    that introduces it rather than on a live job."""
    unreadable = [tok for tok in _vocabulary()
                  if material_of(Path(f"11650-01-01_2MM {tok}_REVA.DXF")) is None]
    assert not unreadable, (
        "these materials are costed as sheet but cannot be read from a filename, so an export "
        "named after one submits a gauge and no material: " + ", ".join(unreadable))


def test_the_reader_does_not_answer_when_no_material_is_named():
    """The guard above must not be satisfiable by returning something for everything. A name
    that states no material has to come back empty, or every flat in the job inherits whatever
    the fallback happened to match first."""
    assert material_of(Path("11650-04-01A_REVG.DXF")) is None
    assert material_of(Path("bracket 17.dxf")) is None


def test_a_material_is_a_whole_word_not_a_fragment_of_a_part_code():
    """`ABS` inside `ABSORBER` is not a statement about stock — the same trap the catalogue
    lookup already guards with a word-boundary check on SQL LIKE results."""
    assert material_of(Path("11650-04-ABSORBER-01_REVA.DXF")) is None


def test_a_shorter_token_cannot_answer_for_a_longer_one():
    """The vocabulary holds both `PET` and `PETG`. The word boundary is what keeps them apart
    — not the order they are tried in — so `2MM PETG` must never come back as PET however the
    list is iterated."""
    assert material_of(Path("11650-04-01A_2MM PETG_REVG.DXF")) == "PETG"


def test_the_explicit_patterns_still_win_where_they_disambiguate():
    """The ordered list exists for what only it can do: abbreviations, and HIPS before ACRYLIC
    so `1MM HIPS` is not answered as acrylic. The fallback is asked second and must not have
    reordered any of that."""
    assert material_of(Path("11650-01_1MM HIPS.DXF")) == "HIPS"
    assert material_of(Path("11650-01_2MM MS_flat.dxf")) == "MILD STEEL"
    assert material_of(Path("11650-01_3MM PERSPEX.dxf")) == "ACRYLIC"


# ── what an unopened DWG appears to be ───────────────────────────────────────────────

@pytest.mark.parametrize("name,expect", [
    ("11650-04-01A_2MM PETG_REVG.DWG", "flat"),
    ("11650-00-05_2MM MS_flat.dwg", "flat"),
    ("AC0706-02_BOOTS_GA-REVG.DWG", "general_arrangement"),
    ("11650-04-SA01_ASSEMBLY.DWG", "general_arrangement"),
    ("11650-04_SHOP ELEVATION.DWG", "general_arrangement"),
    ("scan 17.DWG", "unknown"),
])
def test_a_dwg_is_classed_by_what_the_drawing_office_called_it(name, expect):
    assert cad_inputs.dwg_class(name) == expect


def test_a_general_arrangement_is_not_read_as_a_flat_because_it_names_a_material():
    """The explicit word beats the inferred pair. A GA sheet that happens to carry a material
    and a gauge in its name is still a GA, and converting it would add nothing."""
    assert cad_inputs.dwg_class("11650-04_2MM PETG_GA-REVG.DWG") == "general_arrangement"


def test_a_part_code_that_merely_contains_ga_is_not_a_general_arrangement():
    """Whole words. `GASKET` starts with the same two letters and says nothing about the kind
    of drawing — read as a GA it would tell somebody a measured flat was not worth converting,
    which is the one wrong answer this triage can give."""
    assert cad_inputs.dwg_class("11650-04_GASKET_2MM PETG.DWG") == "flat"


def test_a_material_without_a_gauge_is_not_yet_a_flat():
    """A flat is named with the stock it is cut from — the material AND the gauge. A name that
    carries only one half has not made that statement, and calling it a flat would send
    somebody after a converter for a drawing that may be an assembly."""
    assert cad_inputs.dwg_class("PETG-PANEL.DWG") == "unknown"


def test_classifying_never_raises_on_anything_a_folder_can_contain():
    for junk in ("", "   ", "..", "no-extension", "—.dwg"):
        assert cad_inputs.dwg_class(junk) in {"flat", "general_arrangement", "unknown"}


# ── and the flag says which kind, because that decides whether to chase a converter ──

def _flag(names):
    import invariants
    out = invariants.check_every_cad_file_was_used(
        {"cad_inputs": {"present": True, "unread": list(names)}})
    return out[0]["message"] if out else ""


def test_unread_flat_patterns_are_named_as_worth_converting():
    msg = _flag(["11650-04-01A_2MM PETG_REVG.DWG", "11650-04-03A_2MM ABS.DWG"])
    assert "FLAT PATTERNS" in msg
    assert "worth converting" in msg


def test_unread_general_arrangements_say_converting_them_adds_nothing():
    """The message that would have saved an afternoon. Two GAs of a job already read as PDF
    are not two missing measurements, and a flag that cannot tell the difference sends
    somebody hunting an installer for no gain."""
    msg = _flag(["AC0706-02_BOOTS_GA-REVG.DWG", "AC0706-01_BOOTS_GA-REVG.DWG"])
    assert "would add nothing" in msg
    assert "FLAT PATTERNS" not in msg


def test_a_folder_with_both_leads_on_the_flats():
    msg = _flag(["AC0706-02_GA-REVG.DWG", "11650-04-01A_2MM PETG_REVG.DWG"])
    assert "1 of those are named as FLAT PATTERNS" in msg
