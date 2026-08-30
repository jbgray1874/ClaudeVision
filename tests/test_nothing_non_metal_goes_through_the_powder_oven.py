"""Powder cures at 180-200 C. Nothing non-metal survives it, whatever the material is called.

11650's side-panel sheet booked GBP 0.97 of powder -- the only material money on it -- while
the same run's log said "nothing in this job carries a POWDER finish". The parts are PETG.

The rule was already written down correctly, in prose, in stock_form_rules: NOTHING NON-METAL
GOES THROUGH THE POWDER OVEN. It was implemented as a list of eleven material names, and PETG
was not one of them. wb_populate then kept TWO MORE private sets of five plastics each,
compared by EXACT equality, so "PETG OR PC" -- the string the drawing actually carries -- did
not match any of the three.

Enumerating the members of a physical class is how the twelfth member gets billed for an oven
it would melt in. The class is now asked as a class, once, in one place.

THE EXPENSIVE FAILURE IS THE OTHER DIRECTION. A metal wrongly classed as plastic loses its
powder line silently, and powder is real money on nearly every steel job here. So a material
that names a metal is metal, checked first, and the metal cases below are the reason the
matching is token-aware rather than substring: wb_populate already learned that COLD ROLLED
STEEL and ANNEALED STAINLESS both contain "LED".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import stock_form_rules as sfr                                      # noqa: E402
from wb_populate import part_cannot_be_powder_coated                # noqa: E402


def _part(material, stock_form="sheet"):
    return {"normalized_material": material,
            "material_estimate": {"stock_form": stock_form, "material": material}}


# ── the live failure ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("material", ["PETG", "PETG OR PC", "PET"])
def test_petg_does_not_go_through_the_oven(material):
    assert part_cannot_be_powder_coated(_part(material)), \
        "PETG booked coated area on a sheet whose finish resolver said nothing is coated"


# ── the class, not the list ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("material", [
    # plastics named in full
    "ACRYLIC", "HIGH IMPACT ACRYLIC", "PERSPEX", "POLYCARBONATE", "POLYPROPYLENE",
    "POLYSTYRENE", "POLYETHYLENE", "NYLON", "ACETAL", "DELRIN", "FOAMEX", "CORREX",
    # plastics named by code -- the ones a substring match cannot safely catch
    "PMMA", "ABS", "PVC", "HIPS", "HDPE", "LDPE", "UHMW", "PP", "PC",
    # board
    "MDF", "MFC", "MELAMINE FACED CHIPBOARD", "PLYWOOD", "HARDBOARD", "TIMBER",
    "OAK", "BIRCH PLYWOOD",
    # and the spellings a real drawing carries
    "PETG 3MM", "3MM ACRYLIC CLEAR", "MDF 18MM", "ABS BLACK",
])
def test_a_non_metal_cannot_be_powder_coated(material):
    assert part_cannot_be_powder_coated(_part(material)), \
        f"{material} would contribute coated area and book powder it cannot take"


# ── the direction that costs money ──────────────────────────────────────────────────
@pytest.mark.parametrize("material", [
    "MILD STEEL", "MILD STEEL [CR4]", "MILD STEEL 1.5MM", "STAINLESS STEEL",
    "ALUMINIUM", "ALUMINUM", "GALVANISED STEEL", "ZINTEC", "BRASS", "COPPER",
    "BRONZE", "CAST IRON", "CR4",
    # the trap. Both contain "LED", which is a non-metal keyword elsewhere in this codebase.
    "COLD ROLLED STEEL", "HOT ROLLED MILD STEEL", "ANNEALED STAINLESS",
    # steel with a plastic finish on it is still steel, and it still goes in the booth
    "PLASTIC COATED STEEL", "NYLON COATED STEEL WIRE",
])
def test_a_metal_is_never_ruled_out_of_the_booth(material):
    assert not part_cannot_be_powder_coated(_part(material)), \
        f"{material} lost its powder line -- a silent under-charge on every steel job"


def test_a_metal_wins_over_any_plastic_word_in_the_same_string():
    """Checked first and deliberately: the reclassification that loses money is the one
    where a coating vocabulary reaches a metal."""
    assert sfr.non_metal_reason("PLASTIC COATED STEEL") is None
    assert sfr.non_metal_reason("PLASTIC") == "PLASTIC"


def test_an_unstated_material_is_not_declared_non_metal():
    """Absence of a material is not evidence of plastic. A blank must not silently delete
    a powder line the job may really need -- that decision belongs to the finish resolver."""
    assert sfr.non_metal_reason("") is None
    assert sfr.non_metal_reason(None) is None
    assert not part_cannot_be_powder_coated(_part(""))


# ── short codes must not match inside longer words ──────────────────────────────────
@pytest.mark.parametrize("material", [
    "SHOCK ABSORBER BRACKET",   # contains ABS
    "CARPET RAIL",              # contains PET
    "COMPETITION SIGN",         # contains PET
    "PUNCHED PANEL",            # contains PU
    "COPPER PIPE",              # contains PP
])
def test_a_code_buried_in_a_longer_word_is_not_a_material(material):
    assert sfr.non_metal_reason(material) is None, \
        "a two-to-four letter code matched as a substring, not as a word"


# ── one owner ───────────────────────────────────────────────────────────────────────
def test_no_module_keeps_a_private_plastics_set_for_this():
    """A private copy of a rule that exists elsewhere is how two readers of one job come to
    disagree about what it says -- which is literally what happened: the powder OPERATION
    was correctly refused and the powder MATERIAL was billed anyway."""
    import wb_populate
    src = Path(wb_populate.__file__).read_text(encoding="utf-8")
    assert "_ACRYLIC_NEVER_POWDER" not in src, \
        "wb_populate has grown its own plastics list again"


def test_the_reason_says_why_and_not_merely_no():
    """An operation removed with no stated cause is indistinguishable from one that was
    never read."""
    why = sfr.impossibility_reason("powder_coating", "sheet", "PETG")
    assert why and "180-200 C" in why and "petg" in why.lower()


def test_the_rule_is_reached_through_the_shared_entry_point():
    """Built is not wired. non_metal_reason answering correctly proves nothing about the
    route compiler, which asks is_impossible_operation."""
    assert sfr.is_impossible_operation("powder_coating", "sheet", "PETG")
    assert not sfr.is_impossible_operation("powder_coating", "sheet", "MILD STEEL")


def test_non_coating_impossibilities_still_hold():
    """The oven rule moved; the rest of the table did not. A punch press shatters acrylic
    whatever the coating rule now says."""
    assert sfr.is_impossible_operation("punch", "sheet", "acrylic")
    assert sfr.is_impossible_operation("laser", "wire", "mild steel"), \
        "the stock-form table was disturbed by a material-table change"


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
