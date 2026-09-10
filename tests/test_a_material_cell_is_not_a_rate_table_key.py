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

2. A WEIGHT THAT DISPROVES A BLANK PRICES THE MATERIAL AND LEAVES THE SIZE OPEN. The first
   version of this rule rescaled the inferred envelope by sqrt(mass ratio) so laser time and
   powder area would follow the weight. A reviewer killed it before it ran, and rightly: mass
   and thickness give a NET AREA and nothing else — no aspect ratio, and no PERIMETER, which is
   what laser time is bought by. Scaling a fallback rectangle invents proportions from whatever
   the fallback happened to be: a plausible-looking number in place of an obviously wrong one,
   which is the worse of the two failures. So the contradiction is recorded, the material is
   costed from the printed weight, and the geometry stays unresolved until the part's own detail
   page is read.

3. A COSTING BLOCK THAT IS FULL MUST SPILL, NOT SWALLOW — and where the spilled line cannot
   be put on the block's basis, it says so. Two attempts to equalise it failed: the net figure
   silently under-charged, and reproducing the block's formula used the ENGINE's parts-per-sheet
   where the WORKBOOK's cell computes its own, so JAE834 spilled at GBP 0.84 against its
   identical twin inside the block at GBP 1.12. The claim is withdrawn and the gap declared.
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
def test_a_zero_printed_weight_never_becomes_a_size():
    """Fourteen of the sixteen board parts in this pack print Est. Mass 0.00 kg — including a
    1680 x 560 x 18 panel that really weighs about 12.7 kg, because the mass property was
    never evaluated before the pack was published. A weight-driven path handed a hard zero
    must decline it, not rescale a panel to nothing."""
    part = {
        "part_number": "JAE826", "description": "Shroud Back Panel",
        "normalized_material": "MDF", "material": "MDF",
        "normalized_thickness_mm": 18.0, "stated_weight_kg": 0.0, "quantity": 1,
        "blank_length_mm": 400.0, "blank_width_mm": 300.0,
        "review_flags": ["geometry_inferred_provisional"],
    }
    me = estimate_material(part)
    assert part.get("blank_corrected_from_stated_weight") is None
    assert me.get("blank_length_mm") == 400.0
    assert me.get("stock_form") != "stated_weight"



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
def test_every_costing_block_knows_its_own_capacity():
    """The spill reads each block's capacity from CELL_MAP rather than a second copy of the
    row numbers — the drift that produced the silent drop in the first place."""
    import wb_populate
    for key in ("steel", "other_sheet", "tube", "bom"):
        blk = wb_populate.CELL_MAP[key]
        assert blk["last_row"] >= blk["first_row"] >= 1


# ── what a weight may and may not be used for ────────────────────────────────────────

def test_a_weight_that_disproves_a_blank_prices_the_material_and_leaves_the_size_open():
    """MASS AND THICKNESS GIVE A NET AREA. NOTHING ELSE.

    The first version of this fix rescaled the inferred envelope by sqrt(mass ratio) so that
    laser time and powder area would follow the weight. A reviewer killed it before it ran,
    and rightly: a mass gives no aspect ratio and no PERIMETER, and laser time is bought by
    perimeter. Scaling a fallback rectangle produces proportions invented by whatever the
    fallback happened to be — a plausible-looking number in place of an obviously wrong one,
    which is the worse of the two failures.

    So the material is costed from the printed weight, the contradiction is recorded, and the
    geometry stays unresolved until the part's detail page is read.
    """
    part = _backplate()
    me = estimate_material(part)
    # the material IS costed from the weight — that much the evidence supports
    assert me.get("stock_form") == "stated_weight"
    assert me["unit_material_cost_gbp"] * 56 < 5.0
    # ...and no rectangle is invented to stand in for the real blank
    assert "blank_corrected_from_stated_weight" not in part
    assert me["blank_length_mm"] == 350.0 and me["blank_width_mm"] == 250.0
    contradiction = part.get("blank_contradicted_by_stated_weight")
    assert contradiction and contradiction["blank_is_inferred"] is True
    assert contradiction["factor"] > 100
    assert any("provisional and probably" in str(f) for f in part.get("review_flags", [])), \
        part.get("review_flags")
def test_a_guessed_blank_its_own_weight_disproves_blocks_the_estimate():
    """THE VERIFICATION A REVIEWER ASKED FOR, not the assumption that the revert was enough.

    The rescale is gone and the material is costed from the printed weight. Neither of those
    stops the fallback rectangle driving the nest, the cut time and the coated area exactly as
    if somebody had measured it — and a review flag does not stop it either, because those are
    gathered under a heading that opens "none of the following change the arithmetic", which is
    the one thing this does do.

    So it is a BLOCKING consistency check: it reaches the consistency table, the decisions list
    and the banner that says this estimate is not for release. And the action it asks for is the
    right one — read the dimension off the part's detail sheet; there is no rate that fixes it.
    """
    import invariants

    assert invariants.check_a_guessed_blank_its_own_weight_disproves in invariants.CHECKS, \
        "a check nothing runs has verified nothing"

    part = _backplate()
    me = estimate_material(part)
    part["material_estimate"] = me
    found = invariants.check_a_guessed_blank_its_own_weight_disproves({"parts": [part]})
    assert len(found) == 1, found
    assert found[0]["severity"] == invariants.BLOCKING
    assert found[0]["code"] == "guessed_blank_disproved_by_its_own_weight"
    assert "READ THE DIMENSION" in found[0]["message"]
    assert "no rate to enter that fixes this" in found[0]["message"]
    assert found[0]["detail"]["parts"][0]["part_number"] == "MBY434"


def test_a_blank_that_was_read_is_not_reported_as_a_guess():
    """MBY439's 1578 x 188 is a reading, and its lower mass is its apertures. The check is about
    FALLBACK envelopes; reporting a measured part here would be the cry-wolf that gets the whole
    table ignored on the day it is right."""
    import invariants

    part = {
        "part_number": "MBY439", "normalized_material": "Steel,Mild2mm",
        "material": "Steel,Mild2mm", "normalized_thickness_mm": 2.0,
        "stated_weight_kg": 0.82, "quantity": 2,
        "blank_length_mm": 1578.0, "blank_width_mm": 188.0, "review_flags": [],
    }
    estimate_material(part)
    assert part["blank_contradicted_by_stated_weight"]["blank_is_inferred"] is False
    assert invariants.check_a_guessed_blank_its_own_weight_disproves({"parts": [part]}) == []


# ── the overflow boundary: what can and cannot be promised from outside a block ───────

def test_nothing_is_dropped_when_a_costing_block_is_full():
    """The defect that started this: nine board panels for an eight-row block left JAE834 — a
    real 9mm MDF shelf, eight per unit — written nowhere, while the BOM still carried its
    cross-reference line saying "costed in Other Sheet Material below" and the report explained
    the GBP 0.00 as a missing catalogue price. The spill happens BEFORE the cross-reference rows
    are built, so an overflowed part never claims to be costed in a block it is not in."""
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    assert src.index("_spilled_from_blocks") < src.index("_xref_rows: List[Dict[str, Any]] = []")
    assert "del _blk_list[_cap:]" in src
    assert "block full" in src


def test_the_overflow_basis_is_declared_provisional_rather_than_claimed_equivalent():
    """WHAT THE RUN TAUGHT, AND WHY THIS TEST CHANGED.

    An earlier version of this file asserted that identical panels cost the same on either side
    of the boundary, and the code reproduced the block's formula to make that true:
    ROUNDUP(sheet price / parts per sheet, 2) x (1 + scrap). The live run disproved it. The
    formula was right and the INPUTS were not — the engine's parts-per-sheet is not the
    workbook's, so JAE834 spilled at GBP 0.84 against its identical twin JAE833, inside the
    block, at GBP 1.12. A confident label on a number that still moved with the row.

    Parts-per-sheet is computed by the template's own cell. Nothing outside the block can
    reproduce it without reimplementing a nest we would then have to keep in step, so the claim
    is withdrawn: the spilled line carries the engine's NET-PART cost, says so, says it is
    under-stated, and raises it for a person. Visible and wrong beats invisible and wrong.

    The honest fix is a wider block in the template — a change to the workbook, not to this
    writer — and until then this is a declared gap rather than a silent one.
    """
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    assert "PROVISIONAL: this line carries the engine's" in src
    assert "UNDER-stated" in src
    assert "cannot be reproduced out here" in src
    assert '_sbasis = "net_part_provisional"' in src
    # and the run carries the same warning, not only the cell
    assert '_flag(f"{_blk_name} overflow' in src
    # the withdrawn claim must not survive anywhere in the writer
    assert "on the same nested basis" not in src, \
        "the spill must not claim the block's basis it cannot reproduce"
    assert "_math.ceil" not in src, \
        "reproducing the block formula from outside the block was the thing that failed"


# ── a purchased part is not priced by the steel in it ─────────────────────────────────

@pytest.mark.parametrize("pn,desc", [
    ("84756", "M6x20ButtonHeadSocketMachineScrew,BZP"),
    ("R00500", "M8TNut031.00.285"),
    ("RM05057", "M4x10GrubSocketScrew,BZP"),
    ("RM08167", "M8x80CapHeadSocketMachineScrew,BZP"),
])
def test_purchased_hardware_is_never_priced_from_its_scrap_weight(pn, desc):
    """THE DEFECT THIS FIX INTRODUCED, CAUGHT IN THE RUN THAT CONTAINED IT.

    Resolving "MildSteel" to MILD STEEL gave the fasteners a GBP/kg rate they had never had, and
    the stated-weight path then costed them by mass: 0359342's M6 button-head screw and M8 T-nut
    both came out at GBP 0.01 EACH. That is as wrong as the GBP 7.50 it replaced, in the
    direction nobody notices — an obvious over-charge traded for a quiet under-charge, which is
    the one outcome this whole line of work is supposed to avoid.

    A fastener's price is its CATALOGUE price. The steel in it is a rounding error against the
    thread, the plating and the box, so a part the shared bought-in vocabulary recognises as
    purchased hardware is refused a RESOLVED per-kg rate and falls back to the indicative or
    unpriced treatment it had before. The bought-in price book is the real answer; an honest gap
    is the right placeholder for it.
    """
    part = {"part_number": pn, "description": desc}
    assert _price_per_kg_for_material(part, "MildSteel") is None
    assert "material_rate_key_resolved" not in part


def test_a_fabricated_part_still_reaches_the_rate_the_resolver_found():
    """The gate is for PURCHASED hardware only. MBY432 is a made part — a bent wire prong — and
    must keep the mild-steel rate that took it from GBP 698.88 to about GBP 4."""
    part = {"part_number": "MBY432", "description": "Edition Sunglasses Prong"}
    assert _price_per_kg_for_material(part, "Steel, Mild Wire") == \
        config.MATERIAL_PRICE_GBP_PER_KG["MILD STEEL"]


def test_a_hardware_name_that_already_had_a_rate_is_not_changed_by_this_gate():
    """Only the RESOLVED path is gated. A hardware part whose material already carried a rate
    behaves exactly as it did before any of this work — the gate fixes what I broke and does not
    quietly widen into behaviour nobody asked about."""
    part = {"part_number": "84756", "description": "M6x20ButtonHeadSocketMachineScrew,BZP"}
    assert _price_per_kg_for_material(part, "MILD STEEL") == \
        config.MATERIAL_PRICE_GBP_PER_KG["MILD STEEL"]


# ── an hour must be measured before it can be argued about ───────────────────────────

def test_the_stages_that_swallowed_the_hour_are_bracketed():
    """0359342 ran 3,775s and reported 3,002s of it OUTSIDE ANY TIMED PHASE.

    file_scan brackets its own steps, but two whole regions were invisible:

      * folder-as-job — which is how every real job now runs — calls extract_pdf_summary
        directly in scan_folder_job, bypassing the bracket on the single-PDF path. The only
        evidence of those minutes was the runner printing "no output for 130s" three times.
      * everything main() does after the scan: the workbook, the checks, the deliverables.

    run_timing says what to do about it in its own docstring — when the unmeasured row is the
    biggest number in the table, bracket more rather than optimise anything — so this pins
    that the brackets exist and pair. Timing only: no figure on any estimate moves.
    """
    fs = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    mn = (ROOT / "src" / "main.py").read_text(encoding="utf-8")

    # the folder-as-job extraction loop, which is the path every real job takes
    assert 'run_timing.mark("start extract_pdf_summary")' in fs
    assert 'run_timing.mark("done extract_pdf_summary")' in fs
    assert 'run_timing.mark("start merge_job_pdf_summaries")' in fs

    # and main()'s own stages, each opened and closed
    for stage in ("populate_workbook", "invariants", "deliverables"):
        assert f'_time_stage("{stage}", True)' in mn, stage
        assert f'_time_stage("{stage}", False)' in mn, stage


def test_an_unfinished_stage_is_reported_as_a_hang_not_dropped():
    """A step that started and never finished is the most interesting row in the table —
    that is what a hang looks like — so it must be shown, not omitted for being incomplete."""
    import run_timing

    run_timing.reset()
    run_timing.mark("start finished_stage")
    run_timing.mark("done finished_stage")
    run_timing.mark("start hung_stage")
    report = run_timing.report()
    assert "finished_stage" in report
    assert "hung_stage" in report and "STARTED AND NEVER FINISHED" in report
    assert "unmeasured" in report
    run_timing.reset()


def test_timing_never_takes_down_a_run_that_otherwise_finished():
    """Instrumentation that can fail a job is worse than no instrumentation."""
    import main as _main

    _main._time_stage("a stage nobody registered", True)     # must not raise
    _main._time_stage("a stage nobody registered", False)
