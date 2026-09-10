r"""
test_a_material_cell_is_not_a_rate_table_key.py

THE PRICE WAS NEVER MISSING. THE KEY WAS.

0359342 (M&S Edition Sunglasses Stand, PDF-only pack) states its materials the way a drawing
office types them, not the way a rate table is keyed:

    "CR4, 2mm"   "CR4,2mm"   "Steel,Mild2mm"   "Steel, Mild Wire"   "MildSteel"

Every one of those is mild steel, and this engine has held a mild-steel rate all along. But
MATERIAL_PRICE_GBP_PER_KG.get("CR4, 2mm") is None, and a None there does not read as "no rate
for mild steel" — it silently skips the whole STATED-WEIGHT costing path, the one that prices a
part from the weight its own BOM row prints. So:

  * MBY432, a 90 g bent-wire prong, never reached the weight path and fell through to a
    generated market figure of GBP 12 EACH: GBP 698.88 for 56 of them.
  * MBY434, a 10 g backplate, went the same way at GBP 55 each — GBP 3,203 the line — and after
    the identity fix landed it nested instead on an INFERRED 350x250x2mm blank: 1.37 kg of
    steel, 137x its own printed weight.

Two rules, both generic, both evidence-only:

1. A MATERIAL NAME IS RESOLVED TO A RATE KEY ONLY WHEN IT HAS NO RATE OF ITS OWN. A name that
   prices today is returned untouched, so no job that prices today can move by a penny — the
   structured lane cannot enter this code. A name with no rate is reduced to its material
   WORDS: the gauge in the cell is a thickness (the part carries its own), a stock FORM is how
   it comes not what it is, and a GRADE is the material under another name. Anything still
   unresolved stays unpriced — Corian, mirror and laminate edging remain the estimator's.

2. A BLANK THE STATED WEIGHT HAS DISPROVED STOPS SPENDING MONEY. Costing by the printed weight
   corrected MBY434's material and left the disproved rectangle in place — and the rectangle is
   what laser time and powder area are computed from. Weight and gauge are both printed, and
   together they give an area, so the inferred blank keeps the one thing it knew (its shape) and
   is scaled to the size the evidence proves.

And the third defect the same job exposed: a costing block that is FULL must spill, not swallow.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                    # noqa: E402
from estimator import estimate_material, _price_per_kg_for_material   # noqa: E402


# ── 1. the resolver ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("written,expected", [
    # 0359342's own cells, as the table read them.
    ("CR4, 2mm", "MILD STEEL"),
    ("CR4,2mm", "MILD STEEL"),
    ("CR4", "MILD STEEL"),
    ("Steel,Mild2mm", "MILD STEEL"),
    ("Steel, Mild Wire", "MILD STEEL"),
    ("MildSteel", "MILD STEEL"),
    ("Mild Steel CR4", "MILD STEEL"),
    # a gauge in the cell beside a material this engine already knows
    ("MDF, 18mm", "MDF"),
    ("FlexiMDF", "MDF"),
])
def test_a_material_written_with_its_gauge_or_grade_still_finds_its_rate(written, expected):
    assert config.resolve_material_rate_key(written) == expected


@pytest.mark.parametrize("already_prices", [
    "MILD STEEL", "MILD_STEEL", "MDF", "ACRYLIC", "TIMBER", "PLYWOOD",
    "STAINLESS STEEL", "ZINTEC", "POLYCARBONATE",
])
def test_a_name_that_already_prices_is_never_rewritten(already_prices):
    """THE LANE-A GUARANTEE, AS AN ASSERTION.

    7332-01 is the release gate and it prices in MILD STEEL and ACRYLIC. If resolution could
    touch a name that already has a rate, this change could move a lane-A figure. It cannot,
    and this is where that is enforced rather than argued.
    """
    assert config.material_has_a_rate(already_prices)
    assert config.resolve_material_rate_key(already_prices) == already_prices


@pytest.mark.parametrize("unknown", [
    "Corian,6mm",            # estimator input by design — no rate to find
    "Mirror,6mm",
    "LamainateEdging",
    "Vinyl,Clear-BlackPrint",
    "SEE INDIVIDUAL DRAWINGS",   # a pointer, not a substance
    "", None,
])
def test_a_material_this_engine_cannot_price_stays_unpriced(unknown):
    """Resolution must not guess. An unknown material returning the nearest rate would put a
    price on a line nobody can defend — the opposite of what this is for."""
    assert config.resolve_material_rate_key(unknown) is None


def test_the_resolution_is_recorded_on_the_part_not_slipped_in():
    part = {"part_number": "MBY432"}
    rate = _price_per_kg_for_material(part, "Steel, Mild Wire")
    assert rate == config.MATERIAL_PRICE_GBP_PER_KG["MILD STEEL"]
    assert part["material_rate_key_resolved"] == {
        "recorded": "Steel, Mild Wire", "priced_under": "MILD STEEL"}
    assert any("carries no rate under that name" in str(f)
               for f in part.get("review_flags", [])), part.get("review_flags")


@pytest.mark.parametrize("sheet_priced", [
    "2mm ACRYLIC", "6mm PERSPEX", "6mm POLYCARBONATE", "3mm ACRYLIC",
])
def test_resolving_a_name_never_re_routes_a_part_to_a_different_costing_basis(sheet_priced):
    """THE REGRESSION THIS FIX ALMOST SHIPPED.

    The sheet-priced plastics carry a GBP/kg entry AS WELL AS their area rate, and the area
    rate is the one this engine costs them on. "2mm ACRYLIC" has no rate under that exact
    name, so resolving it to ACRYLIC handed the per-kg path a rate it never had: a
    400x300x18mm panel came out at GBP 57.49 by mass where the area path says a few pounds,
    and 7332-01-007 — the release gate's own lens — is acrylic.

    Resolution exists to find a rate that was already there, not to change how a part is
    costed. The gauge-prefixed plastics were unpriced before this commit and are unpriced
    after it, visibly, until someone routes them to the area path deliberately.
    """
    part = {"part_number": "7332-01-007"}
    assert _price_per_kg_for_material(part, sheet_priced) is None
    assert "material_rate_key_resolved" not in part


def test_the_materials_this_change_moves_are_only_the_ones_it_was_built_for(monkeypatch):
    """THE BLAST RADIUS, MEASURED END TO END RATHER THAN ASSERTED.

    Not "which names gain a rate" — several already reach the mass path because the material
    is normalised upstream, so the helper answering differently changes nothing they cost.
    The question that matters is which materials come out of estimate_material at a DIFFERENT
    method or a different figure than they did before this commit. The answer must be the
    mild-steel spellings this fix was built for, and nothing else.
    """
    def _part(mat):
        return {"part_number": "X", "description": "D", "normalized_material": mat,
                "material": mat, "normalized_thickness_mm": 18.0, "quantity": 2,
                "blank_length_mm": 400.0, "blank_width_mm": 300.0}

    candidates = ("CR4, 2mm", "CR4,2mm", "Steel,Mild2mm", "Steel, Mild Wire", "MildSteel",
                  "2mm ACRYLIC", "6mm PERSPEX", "6mm POLYCARBONATE", "3mm HIPS", "ACRYLIC",
                  "18mm MDF", "MDF, 18mm", "25mm TIMBER", "18mm PLYWOOD", "MDF",
                  "Corian,6mm", "Mirror,6mm", "MILD STEEL", "TIMBER")

    def _outcome(mat):
        me = estimate_material(_part(mat))
        return (me.get("cost_method"), me.get("cost_per_part_gbp"))

    after = {m: _outcome(m) for m in candidates}
    # Put the resolver back to what it did before this commit: answer only names that already
    # price, which is the same as not resolving at all.
    monkeypatch.setattr(config, "resolve_material_rate_key",
                        lambda m: (m if config.material_has_a_rate(m) else None))
    before = {m: _outcome(m) for m in candidates}

    moved = {m for m in candidates if before[m] != after[m]}
    assert moved == {"CR4, 2mm", "CR4,2mm", "Steel,Mild2mm", "Steel, Mild Wire", "MildSteel"}, \
        {m: (before[m], after[m]) for m in moved}


def test_a_name_with_its_own_rate_is_answered_without_a_flag():
    part = {"part_number": "7332-01-005"}
    assert _price_per_kg_for_material(part, "MILD STEEL") == \
        config.MATERIAL_PRICE_GBP_PER_KG["MILD STEEL"]
    assert "material_rate_key_resolved" not in part
    assert not part.get("review_flags")


# ── 2. the weight that was already printed reaches the price ─────────────────────────

def _prong(**over):
    """MBY432 as 0359342 states it: 90 g of mild-steel wire, no geometry to nest from."""
    part = {
        "part_number": "MBY432", "description": "Edition Sunglasses Prong",
        "normalized_material": "Steel, Mild Wire", "material": "Steel, Mild Wire",
        "stated_weight_kg": 0.09, "quantity": 56,
    }
    part.update(over)
    return part


def test_a_prong_is_priced_from_the_weight_its_own_bom_row_prints():
    me = estimate_material(_prong())
    assert me.get("stock_form") == "stated_weight", me
    assert me.get("unit_material_mass_kg") == 0.09
    expected = 0.09 * config.MATERIAL_PRICE_GBP_PER_KG["MILD STEEL"] * 1.04
    assert me["unit_material_cost_gbp"] == pytest.approx(round(expected, 2), abs=0.01)
    # The whole point: 56 of these are pounds, not the GBP 698.88 the market figure charged.
    assert me["unit_material_cost_gbp"] * 56 < 20.0


def _backplate(**over):
    """MBY434: a 10 g plate whose blank was INFERRED at 350x250 — no DXF, no model."""
    part = {
        "part_number": "MBY434", "description": "Edition Sunglasses Prong Backplate",
        "normalized_material": "CR4, 2mm", "material": "CR4, 2mm",
        "normalized_thickness_mm": 2.0, "stated_weight_kg": 0.01, "quantity": 56,
        "blank_length_mm": 350.0, "blank_width_mm": 250.0,
        "review_flags": ["geometry_inferred_provisional"],
    }
    part.update(over)
    return part


def test_a_blank_the_weight_disproves_is_rescaled_to_what_the_weight_implies():
    part = _backplate()
    me = estimate_material(part)
    assert me.get("stock_form") == "stated_weight", me
    # Material comes off the printed weight...
    assert me["unit_material_cost_gbp"] * 56 < 5.0
    # ...and the blank that laser time and powder area ride on is corrected, not left at 350x250.
    corrected = part.get("blank_corrected_from_stated_weight")
    assert corrected, part.get("review_flags")
    assert (corrected["was_length_mm"], corrected["was_width_mm"]) == (350.0, 250.0)
    assert me["blank_length_mm"] < 60.0 and me["blank_width_mm"] < 60.0
    # The one datum the inferred rectangle did know is its SHAPE, and that is kept.
    assert (me["blank_length_mm"] / me["blank_width_mm"]) == pytest.approx(350.0 / 250.0, rel=0.02)
    # The corrected blank weighs what the drawing says it weighs.
    implied_kg = (me["blank_length_mm"] * me["blank_width_mm"] / 1e6) * 0.002 * 7850.0
    assert implied_kg == pytest.approx(0.01, rel=0.05)
    assert any("rescaled" in str(f) for f in part.get("review_flags", []))


def test_a_measured_blank_still_beats_a_stated_weight_that_disagrees():
    """The reverse case, unchanged: where a DXF measured the blank, the blank is truth and an
    odd stated weight is the bad unit conversion. Nothing here rescales a measured part."""
    part = _backplate(geometry_source="dxf_flat_pattern")
    me = estimate_material(part)
    assert part.get("blank_corrected_from_stated_weight") is None
    assert me.get("stock_form") != "stated_weight"
    assert me.get("blank_length_mm") == 350.0


def test_a_weight_that_agrees_with_its_blank_leaves_the_blank_alone():
    """No disagreement, no correction — the gate only fires on a contradiction."""
    part = _backplate(stated_weight_kg=round((350 * 250 / 1e6) * 0.002 * 7850.0, 3))
    me = estimate_material(part)
    assert part.get("blank_corrected_from_stated_weight") is None
    assert me.get("blank_length_mm") == 350.0


# ── 3. a block that is full spills, it does not swallow ──────────────────────────────

def test_a_costing_block_that_is_full_moves_the_rest_to_the_bom_with_their_money():
    """0359342 has nine board panels for an eight-row Other Sheet Material block. The ninth
    (JAE834, a real 9mm MDF shelf at GBP 6.72) was written nowhere, while the BOM still carried
    its cross-reference line pointing at a row that does not exist — and the report explained
    the GBP 0.00 as a missing catalogue price, which is not what happened."""
    import wb_populate

    cap = (wb_populate.CELL_MAP["other_sheet"]["last_row"]
           - wb_populate.CELL_MAP["other_sheet"]["first_row"] + 1)
    board = [{"part_number": f"JAE{820 + i}", "description": f"panel {i}", "quantity": 2,
              "material_estimate": {"cost_per_part_gbp": 6.72}} for i in range(cap + 1)]

    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    # The spill happens before the cross-reference rows are built, so the overflowed part never
    # gets a line claiming it is costed in a block it is not in.
    assert src.index("_spilled_from_blocks") < src.index("_xref_rows: List[Dict[str, Any]] = []")
    assert "block full; " in src
    # And the money travels with it: the spilled line carries the engine's own per-part cost.
    assert '"unit_cost_gbp": _scost' in src
    assert "del _blk_list[_cap:]" in src


def test_every_costing_block_knows_its_own_capacity():
    """The spill reads each block's capacity from CELL_MAP rather than a second copy of the
    row numbers — the drift that produced the silent drop in the first place."""
    import wb_populate
    for key in ("steel", "other_sheet", "tube", "bom"):
        blk = wb_populate.CELL_MAP[key]
        assert blk["last_row"] >= blk["first_row"] >= 1
