r"""
test_a_handed_pair_is_one_part_made_twice.py

IT CANNOT BE TWO MATERIALS.

11650-04's side panels, off the first real run of that job:

    11650-04-01A         SIDE PANEL  1250 x 525 x 2  6/sheet  GBP 175.01/sheet  GBP 30.34
    11650-04-01A-HANDED  SIDE PANEL  1250 x 525 x 2  6/sheet  GBP 114.98/sheet  GBP 19.93

The same panel, mirrored, costed as two different materials 52% apart. The labour rows said
it out loud too -- "Laser (Acrylic) - 2.2mm ABS (11650-04-01A)" beside "Laser (Acrylic) -
2mm PETG (11650-04-01A-HANDED)". Both are LLM market rates for materials this engine holds
no price for, so the two guesses landed a long way apart on a part made twice from one sheet.

WHY THE GEOMETRY WAS RIGHT AND THE MATERIAL WAS NOT. apply_mirror_geometry already gives a
mirrored part the flat pattern of the part it mirrors -- which is why both sides had
identical blanks and identical parts-per-sheet. Material and gauge were in neither inherit
list, so each side was left to read its own, and a HANDED record derived from assembly pages
has almost nothing to read: the base got ABS from the SolidWorks model, the handed twin got
PETG off assembly-page text.

SUBMITTED AT mirror_of_measured (75), AND NOT GAP-FILLED. Gap-filling would have changed
nothing here, because the handed part's material was not missing -- it was a different
answer from thinner evidence. Submitting it unconditionally hands the argument to the
resolver, which is the only thing that should settle it: the handed part's own DXF (80) or
model (90) still wins, and assembly-page text (70) no longer invents a second material for a
part that has none of its own.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import drawing_job_merge as djm  # noqa: E402
import source_precedence as sp  # noqa: E402


def _pair(handed_material=None, handed_source=None, handed_thickness=None):
    """The 11650-04 shape: a measured base and a handed twin off assembly pages.

    THE SOURCE KEYS ARE THE REAL ONES. source_precedence._SOURCE_FIELDS maps
    normalized_material to "material_source" and normalized_thickness_mm to
    "thickness_source" — not "<field>_source". The first version of this fixture invented
    the latter, so the resolver saw the twin's material with NO source at all, rank 0, and
    every assertion below would have passed with precedence completely broken. This file's
    own subject is a rule that never fired; a fixture that cannot tell would be the same
    mistake one level up.
    """
    base = {
        "part_number": "11650-04-01A", "description": "SIDE PANEL",
        "normalized_material": "ABS", "material_source": "solidworks_api",
        "normalized_thickness_mm": 2.2, "thickness_source": "solidworks_api",
        "blank_length_mm": 1250.0, "blank_width_mm": 525.0,
        "normalized_geometry": {"blank_length_mm": 1250.0, "blank_width_mm": 525.0,
                                "geometry_source": "solidworks_api",
                                "geometry_confidence": 0.95},
    }
    twin = {"part_number": "11650-04-01A-HANDED", "description": "SIDE PANEL",
            "mirror_hand": "HANDED", "normalized_geometry": {}}
    if handed_material is not None:
        twin["normalized_material"] = handed_material
        twin["material_source"] = handed_source
    if handed_thickness is not None:
        twin["normalized_thickness_mm"] = handed_thickness
        twin["thickness_source"] = handed_source
    return base, twin


def _mirror(base, twin):
    djm.apply_mirror_geometry([base, twin])
    return twin


# ── the defect, in the shape it actually arrived in ─────────────────────────────────
def test_assembly_page_text_no_longer_invents_a_second_material():
    """The live case. Drawing/assembly text is rank 70; an inherited reading is 75."""
    base, twin = _pair(handed_material="PETG", handed_source="drawing_deterministic")
    _mirror(base, twin)
    assert twin["normalized_material"] == "ABS", (
        "the handed panel is still a different material from the panel it mirrors")
    assert twin["normalized_thickness_mm"] == 2.2


def test_a_handed_part_with_nothing_of_its_own_inherits_both():
    base, twin = _pair()
    _mirror(base, twin)
    assert twin["normalized_material"] == "ABS"
    assert twin["normalized_thickness_mm"] == 2.2


@pytest.mark.parametrize("source", ["dxf", "dxf_flat_pattern", "solidworks_api",
                                    "estimator_confirmed"])
def test_a_real_reading_on_the_handed_part_still_wins(source):
    """AN INHERITED VALUE IS NOT A MEASUREMENT. If the handed part has been measured, or an
    estimator has ruled on it, that beats what its twin is made of — a genuinely different
    material on one hand of a pair is unusual but it is not impossible, and the engine must
    not overrule somebody who looked."""
    base, twin = _pair(handed_material="POLYCARBONATE", handed_source=source,
                       handed_thickness=3.0)
    _mirror(base, twin)
    assert twin["normalized_material"] == "POLYCARBONATE", (
        f"a reading from {source} was overwritten by an inherited one")
    assert twin["normalized_thickness_mm"] == 3.0


def test_the_inherited_value_is_ranked_below_a_measurement_and_above_text():
    """The whole design in two comparisons. If mirror_of_measured ever outranks a DXF, an
    inherited guess starts beating a measured fact on every handed job at once."""
    assert sp.rank("mirror_of_measured") < sp.rank("dxf")
    assert sp.rank("mirror_of_measured") < sp.rank("solidworks_api")
    assert sp.rank("mirror_of_measured") > sp.rank("drawing_deterministic")
    assert sp.rank("mirror_of_measured") > sp.rank("inference")


def test_it_says_where_the_material_came_from():
    """A datum with no source cannot be argued with, and arbitration cannot defend what it
    cannot attribute."""
    base, twin = _pair(handed_material="PETG", handed_source="drawing_deterministic")
    _mirror(base, twin)
    assert twin.get("material_source") == "mirror_of_measured"


def test_a_base_with_no_material_does_not_erase_the_twins():
    """Inheriting nothing is not inheriting a blank. A base that was never read must not
    take the handed part's own answer away."""
    base, twin = _pair(handed_material="PETG", handed_source="drawing_deterministic")
    base.pop("normalized_material")
    base.pop("normalized_thickness_mm")
    _mirror(base, twin)
    assert twin["normalized_material"] == "PETG"


def test_the_geometry_inheritance_still_works():
    """It was already right, and it is what makes the pair share a blank and a nest. A
    change to the material path must not disturb it."""
    base, twin = _pair()
    _mirror(base, twin)
    assert twin["normalized_geometry"]["blank_length_mm"] == 1250.0
    assert twin["normalized_geometry"]["geometry_source"] == "mirror_of_measured"
    assert twin["normalized_geometry"]["mirrored_from"] == "11650-04-01A"


def test_an_unrelated_part_is_not_given_anybody_elses_material():
    """The mirror rules key on the pair. A part that mirrors nothing must be left alone —
    handing it a neighbour's material would be a far worse defect than the one being fixed."""
    base, twin = _pair()
    other = {"part_number": "11650-04-99X", "description": "BRACKET",
             "normalized_material": "MILD STEEL",
             "material_source": "drawing_deterministic",
             "normalized_geometry": {}}
    djm.apply_mirror_geometry([base, twin, other])
    assert other["normalized_material"] == "MILD STEEL"


# ── the rule that had never fired ───────────────────────────────────────────────────
def test_a_handed_part_does_not_shadow_its_own_base_in_the_index():
    """THE REASON NONE OF THE ABOVE WAS HAPPENING AT ALL.

    apply_mirror_geometry indexed the parts with normalize_part_code, which STRIPS the hand
    suffix: "11650-04-01A-HANDED" normalises to "11650-04-01A", the same key as its base. In
    a dict comprehension the twin therefore overwrote the base, the lookup returned the twin
    itself, `base is part` was true, and the whole rule quietly did nothing.

    So the handed panels inherited no geometry, no cut length, no hole count and no material
    — every one of them re-read from assembly pages — and nothing anywhere said so.

    It survived because it works for the other two spellings. "11350-01-02 MIR" and
    "Mirror11350-01-02" do not collapse onto their bases, so the rule demonstrably worked on
    the job it was written for while being a no-op on every "-HANDED" pack since.

    Two questions, one helper: "are these the same article" wants the hand stripped, and
    "index these parts under their own numbers" must not have it stripped.
    """
    from part_identity import normalize_part_code
    assert normalize_part_code("11650-04-01A-HANDED") == normalize_part_code("11650-04-01A"), (
        "the premise has changed — normalize_part_code no longer strips the hand, so this "
        "test is describing a collapse that can no longer happen")

    base, twin = _pair(handed_material="PETG", handed_source="drawing_deterministic")
    filled = djm.apply_mirror_geometry([base, twin])
    assert filled, "the mirror rule did not fire for a -HANDED part"


@pytest.mark.parametrize("twin_pn", ["11650-04-01A-HANDED", "11650-04-01A MIR",
                                     "Mirror11650-04-01A", "11650-04-01A-MIRRORED"])
def test_every_spelling_of_a_mirror_behaves_the_same(twin_pn):
    """The three conventions are one fact written three ways — SolidWorks writes
    "Mirror<code>", the GA writes "<code> MIR", and this pack writes "-HANDED". A rule that
    works for two of them and silently skips the third is worse than one that works for
    none, because the two that work are the evidence nobody looks past."""
    base, twin = _pair(handed_material="PETG", handed_source="drawing_deterministic")
    twin["part_number"] = twin_pn
    djm.apply_mirror_geometry([base, twin])
    assert twin["normalized_material"] == "ABS", f"{twin_pn} did not inherit"
    assert twin["normalized_geometry"].get("mirrored_from") == "11650-04-01A"


def test_a_part_that_is_its_own_base_is_left_alone():
    """The guard that was doing all the work by accident. It must still hold on its own
    terms: nothing mirrors itself."""
    solo = {"part_number": "11650-04-01A", "normalized_material": "ABS",
            "material_source": "solidworks_api", "normalized_geometry": {}}
    assert djm.apply_mirror_geometry([solo]) == []


def test_the_index_and_its_lookup_use_one_key_function():
    """AN INDEX AND ITS LOOKUP MUST AGREE, and this defect is what disagreement looks like.

    The index was built with normalize_part_code while the lookup asked with a base code
    whose hand had already been stripped — so the two agreed for every base and disagreed
    for every twin, and nothing in the code said they were supposed to match. Changing one
    was a local edit with a non-local consequence.

    One named function now, called by both, so they cannot drift apart again by accident.
    Asserted structurally because the failure mode is structural: two expressions where
    there should be one.
    """
    import ast as _ast
    src = (ROOT / "src" / "drawing_job_merge.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)
    fn = next(n for n in _ast.walk(tree)
              if isinstance(n, _ast.FunctionDef) and n.name == "apply_mirror_geometry")
    calls = [_ast.unparse(n.func) for n in _ast.walk(fn) if isinstance(n, _ast.Call)]
    assert calls.count("_own_number_key") == 2, (
        f"the index and the lookup should both key through _own_number_key; found "
        f"{calls.count('_own_number_key')} call(s)")
    assert "_normalize_part_key" not in calls, (
        "normalize_part_code strips the hand, so a twin would shadow its own base again")

    # And the property that makes it correct, not just consistent.
    assert djm._own_number_key("11650-04-01A-HANDED") != djm._own_number_key("11650-04-01A")


def test_the_resolver_refuses_an_empty_value_on_its_own():
    """WHERE THE REAL PROTECTION LIVES. apply_mirror_geometry guards each field with
    `if not _is_blank(base.get(...))`, and removing that guard changes nothing — because
    apply_field already refuses to write an empty value. Worth pinning here rather than
    trusting a guard that no test can distinguish from its absence: if apply_field ever
    starts accepting None, a base that was never read would erase its twin's material on
    every handed job, and the mirror guard alone is not what stops that."""
    part = {"normalized_material": "PETG", "material_source": "drawing_deterministic"}
    for empty in (None, "", [], {}):
        assert sp.apply_field(part, "normalized_material", empty, "solidworks_api") is False
    assert part["normalized_material"] == "PETG"
