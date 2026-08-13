"""A material the engine RECOGNISES but cannot cost is a vocabulary hole, not a data gap.

11650-05's PETG side panels were reported as "DIMS REQUIRED" — which reads as "the drawing
did not say", and sent the estimator looking for dimensions. The drawing states 1250 high,
510/470 wide, 2.2 thick, and 1326 g. The dimensions were never the blocker.

PETG appeared in NONE of the three material tables: no standard sheet size, no density, no
price per kg. Acrylic, Perspex and Polycarbonate had all three. So perfect blank extraction
would still have produced GBP 0.00, and every hour spent on the extraction would have been
spent on the wrong thing.

THE ENGINE MUST NOT RECOGNISE A MATERIAL IT CANNOT COST WITHOUT SAYING SO. _is_board
classifies PETG, HIPS, ABS, PVC and the rest as plastic sheet and routes them confidently
to Other Sheet Material, where they land in a block that has no way to price them. That
confidence is the defect: a material the engine cannot name is obviously unpriceable, and
one it routes correctly and then cannot cost looks like a measurement problem.

WHAT THIS FILE DOES NOT ASSERT: a price. A rate is a commercial fact SDI owns, and
inventing one would put a number on a quote nobody has agreed to. The gap is reported as an
ENGINE gap instead, which says the job is under-charged and that no estimator input fixes it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                       # noqa: E402
import price_provenance as pp                                       # noqa: E402
from wb_populate import _is_board                                   # noqa: E402
from costed_facts import _PLASTIC_SHEET_TOKENS                      # noqa: E402


def _norm(name):
    return str(name).upper().replace("_", " ").strip()


_SHEETS = {_norm(k) for k in config.STANDARD_SHEET_SIZES_MM}
_DENSITY = {_norm(k) for k in config.MATERIAL_DENSITY_KG_PER_M3}


# ── the live failure ────────────────────────────────────────────────────────────────
def test_petg_is_a_material_the_engine_knows_the_shape_of():
    """Sheet size and density are what turn a weight or a blank into a cost. Without them
    PETG could not be costed by ANY route -- weight, area or nesting."""
    assert "PETG" in _SHEETS, "PETG has no standard sheet size, so it cannot be nested"
    assert config.MATERIAL_DENSITY_KG_PER_M3.get("PETG"), \
        "PETG has no density, so a stated weight cannot become an area and vice versa"


def test_the_density_is_the_real_one():
    """A checkable physical constant, not a placeholder. PETG is 1.27 g/cm3."""
    assert 1250 <= config.MATERIAL_DENSITY_KG_PER_M3["PETG"] <= 1290


# ── the general rule ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("token", sorted(t for t in _PLASTIC_SHEET_TOKENS
                                         if len(t.strip()) > 2))
def test_every_plastic_the_router_recognises_has_a_density(token):
    """The seam. If _is_board says "this is plastic sheet" and routes it, the engine has
    committed to costing it -- and a density is the minimum needed to convert between the
    two things a drawing states (a size and a weight).

    THE TOKEN IS PASSED VERBATIM. "PET " carries a deliberate trailing space so it matches
    "PET SHEET" and not "CARPET" or "COMPETITION"; stripping it for convenience made this
    test assert something _is_board does not promise, and the failure looked like a missing
    density rather than a broken fixture. The lookup is normalised separately."""
    assert _is_board(token), "the fixture is wrong: this token is not routed as plastic"
    name_key = _norm(token)
    known = any(name_key in name or name in name_key for name in _DENSITY)
    assert known, (f"{name_key} is routed to Other Sheet Material and has no density. It will "
                   f"land in a costing block that cannot price it, and the job will report "
                   f"a measurement problem it does not have.")


def test_a_recognised_plastic_without_a_rate_is_an_engine_gap_not_an_estimator_one():
    """The honest handling of the half that is still missing. A rate is commercial and SDI
    owns it; the engine's job is to say loudly that IT cannot price the line."""
    reason = pp.unpriced_reason(pp.NO_VOCABULARY, "PETG has no rate in MATERIAL_PRICE_GBP_PER_KG")
    assert reason["owner"] == "engine"
    assert reason["undercharging"] is True
    assert "UNDER-CHARGED" in pp.describe_unpriced(pp.NO_VOCABULARY)


def test_no_price_has_been_invented_for_the_new_plastics():
    """Guarding my own hand. Adding a plausible-looking rate here would put a number on a
    quote nobody has agreed to and no supplier would honour."""
    for material in ("PETG", "HIPS", "ABS", "PVC", "FOAMEX"):
        assert config.MATERIAL_PRICE_GBP_PER_KG.get(material) is None, (
            f"a rate has been invented for {material}. A price is a commercial fact SDI "
            f"owns -- it must be entered, not guessed.")


def test_the_metals_and_boards_that_already_worked_are_untouched():
    """No existing job may move because of this change."""
    assert config.MATERIAL_PRICE_GBP_PER_KG["MILD STEEL"] == 0.80
    assert config.MATERIAL_PRICE_GBP_PER_KG["ACRYLIC"] == 3.26
    assert config.MATERIAL_DENSITY_KG_PER_M3["ACRYLIC"] == 1190


def test_the_config_says_where_a_rate_goes_when_someone_has_one():
    """A gap with no instructions is a gap that stays open. The comment must name the
    table and show the shape of the line to add."""
    src = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
    block = src[src.index("MATERIAL_PRICE_GBP_PER_KG"):]
    block = block[:block.index("\nWELD_TIME_POLICY")]
    assert "GBP per kg" in block and "PETG" in block


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
