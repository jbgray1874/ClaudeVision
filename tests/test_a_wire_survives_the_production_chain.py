r"""
test_a_wire_survives_the_production_chain.py

THE PRODUCTION CHAIN, NOT TWO HELPERS AGREEING.

The first round of tests for the material-as-printed fix proved the wrong thing. They handed
read_material_as_printed()'s output straight to the impossibility helper, and checked the
estimator's SOURCE TEXT for its stock-form vocabulary. That demonstrates the helpers are
compatible with each other. It does not demonstrate that a real part record, built by the
real document builder from a real BOM row, still carries the form by the time the route
compiler and the estimator read it — which is the only claim worth making, because every
defect in this area has lived in the joins.

So this drives the actual chain:

    BOM row  ->  document_builder._apply_post_build_fixes
             ->  route_compiler.compile_job_route
             ->  estimator._part_cost_credibility

and asserts the outcome an estimator would see: wire form, the printed 8 mm diameter, no
sheet laser, no fold, and an explicit decision where the length is not known.

MBY432 on 0359342: "Steel, Mild Wire Ø8mm", a Ø8 x 219.6 solid prong, 56 off, which the
engine classified as sheet and nested as plate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from document_builder import _apply_post_build_fixes                     # noqa: E402
from estimator import _part_cost_credibility                             # noqa: E402
from route_compiler import compile_job_route                             # noqa: E402

PRINTED = "Steel, Mild Wire Ø8mm"


def _build(material_text, *, thickness=None, thickness_source="",
           operations=("laser_cutting", "folding"), part_number="MBY432",
           extra_rows=()):
    """A part through the REAL document-builder pass, from a real BOM row."""
    rows = [{"part_number": part_number, "material_text": material_text,
             "quantity": 56, "description": "Edition Sunglasses Prong"}]
    rows.extend(extra_rows)
    part = {
        "part_number": part_number, "description": "Edition Sunglasses Prong",
        "pages": [24], "materials": [], "page_roles": ["detail"],
        "normalized_thickness_mm": thickness, "thickness_source": thickness_source,
        "textual_operations": list(operations), "operations": [], "review_flags": [],
    }
    summary = {
        "pages": [{"page_number": 24, "text": "", "page_analysis": {}}],
        "document_analysis": {"bom_rows": rows},
    }
    return _apply_post_build_fixes([part], summary)[0], rows


def _flags(part):
    return " | ".join(str(f) for f in (part.get("review_flags") or []))


# ── the chain ─────────────────────────────────────────────────────────────────────────

def test_the_printed_cell_reaches_the_route_compiler_as_a_wire():
    """THE ACCEPTANCE TEST. Real builder, real route compiler, real decisions."""
    part, rows = _build(PRINTED)

    assert (part.get("manufacturing_interpretation") or {}).get("stock_form") == "wire"
    assert part.get("wire_gauge_mm") == 8.0
    assert part.get("normalized_thickness_mm") is None, \
        "a diameter must never be left sitting in the thickness field"

    route = compile_job_route([part], {}, rows)
    by_op = {str(d.get("operation")): d for d in (route.get("decisions") or [])}

    for operation in ("laser_cutting", "folding"):
        assert operation in by_op, f"{operation} should be decided, not silently absent"
        assert by_op[operation].get("status") == "not_applicable"
        assert "not physically possible on stock form 'wire'" in \
            str(by_op[operation].get("reason"))


def test_the_estimator_treats_it_as_linear_stock():
    """The estimator's own credibility gate, called for real — not its source text."""
    part, _ = _build(PRINTED)
    credible, reasons = _part_cost_credibility({}, part)
    assert credible is True and reasons == []


def test_a_sheet_part_from_the_same_pack_keeps_its_laser_and_fold():
    """The guard must not leak. MBY439 is 'Steel, Mild 2mm' and IS lasered and folded."""
    part, rows = _build("Steel, Mild 2mm", part_number="MBY439")
    assert (part.get("manufacturing_interpretation") or {}).get("stock_form") != "wire"

    route = compile_job_route([part], {}, rows)
    statuses = {str(d.get("operation")): d.get("status")
                for d in (route.get("decisions") or [])}
    for operation in ("laser_cutting", "folding"):
        assert statuses.get(operation) != "not_applicable"


# ── the length is a decision, never a silence ─────────────────────────────────────────

def test_an_unknown_wire_length_is_stated_as_a_decision():
    """On a linear part the LENGTH IS THE MONEY, and unset was silent. An absent figure and
    a figure of zero look identical in a total."""
    part, _ = _build(PRINTED)
    assert not part.get("wire_length_mm")
    assert "LENGTH is not known" in _flags(part)
    assert "priced per metre" in _flags(part)


# ── the actual material calculation, not the credibility gate ─────────────────────────

def test_the_material_cost_is_computed_on_the_bar_not_a_nested_blank():
    """_part_cost_credibility says the part is ALLOWED the linear path. It does not price it.
    This drives estimator.estimate_material — the real calculation — and checks the figures
    an estimator would see on the sheet."""
    from estimator import estimate_material
    part, _ = _build(PRINTED)
    part["wire_length_mm"] = 219.6          # printed on MBY432's own detail sheet, page 24
    part["quantity"] = 56

    costed = estimate_material(part)
    assert costed["stock_form"] == "wire"
    assert costed["cost_method"] == "workbook_bar_formula", \
        "a wire must not be priced by a sheet nest"
    assert costed["thickness_mm"] is None, "a diameter is not a thickness"
    assert costed["blank_length_mm"] == 219.6
    assert costed["blank_area_m2"] is None, "a bar has no blank area to nest"


def test_the_computed_mass_agrees_with_the_mass_the_drawing_prints():
    """THE INDEPENDENT CHECK. Ø8 x 219.6 of mild steel computes to 0.0867 kg. MBY432's title
    block prints 'Est. Mass (Kg) 0.09 kg' — a figure this engine never reads, arrived at by
    SolidWorks from the solid. Two independent routes to the same number is the strongest
    evidence available that the part is now on the right basis.

    For scale: nested as 350 x 250 x 2 mm plate — the category default it used to get — the
    same part carries about 1.37 kg, roughly sixteen times its own printed mass, 56 off.
    """
    from estimator import estimate_material
    part, _ = _build(PRINTED)
    part["wire_length_mm"] = 219.6
    part["quantity"] = 56

    mass = estimate_material(part)["unit_material_mass_kg"]
    assert mass == pytest.approx(0.0867, abs=0.002)
    assert mass == pytest.approx(0.09, abs=0.005), \
        "must agree with the 0.09 kg the drawing prints"


def test_the_pack_alone_still_does_not_supply_mby432_a_length():
    """THE ACCEPTANCE BOUNDARY, HALF OF IT UNCHANGED.

    Nothing the engine READS off this pack yields 219.6: wire_length_mm is written only by a
    bar/wire schedule, MBY432's sheet has none, and no length is inferred from a drawing
    outline. That remains true and is asserted here so it cannot be assumed away — an
    extractor that starts finding the figure should replace this test, not silently pass it.
    """
    part, _ = _build(PRINTED)
    assert part.get("wire_length_mm") is None


def test_a_confirmed_length_reaches_costing_and_the_mass_the_drawing_prints(tmp_path):
    """THE OTHER HALF, NOW CLOSED — and closed by an AUDITED route, not a better guess.

    Handing 219.6 straight to estimate_material proved arithmetic, not plumbing. This drives
    the whole path a real run takes: a confirmations file beside the job, discovered, parsed,
    stamped at estimator_confirmed rank, through to the material calculation.

    The figure is a person's reading of the printed sheet and is recorded as one. What makes
    it safe is not that it is right — it is that it is attributable, outranked by nothing,
    and visible on the part.
    """
    import json
    import estimator_confirmed as ec
    from estimator import estimate_material

    (tmp_path / "0359342_estimator_dimensions.json").write_text(json.dumps({
        "confirmed_by": "J Gray", "confirmed_on": "2026-09-10",
        "parts": {"MBY432": {"wire_length_mm": 219.6,
                             "read_from": "page 24, printed overall 219.6"}}}),
        encoding="utf-8")

    found = ec.find_corrections_file(tmp_path, None, "0359342")
    assert found is not None
    data, problems = ec.load_corrections(found)
    assert not problems

    part, _ = _build(PRINTED)
    part["quantity"] = 56
    assert part.get("wire_length_mm") is None, "the pack supplies none — that is the premise"

    report = ec.apply_estimator_confirmed([part], data)
    assert report["stamped"] == 1 and not report["unmatched"]
    assert part["wire_length_mm"] == 219.6

    costed = estimate_material(part)
    assert costed["cost_method"] == "workbook_bar_formula", \
        "with a length it must leave the assumed-band path"
    assert costed["blank_length_mm"] == 219.6
    assert costed["unit_material_mass_kg"] == pytest.approx(0.09, abs=0.005), \
        "and land on the mass the title block prints"


def test_a_part_cannot_be_both_a_blank_and_a_bar(tmp_path):
    """Stating both sets means the file describes two different parts under one code, and at
    rank 100 the field order would decide which stock it is bought as."""
    import json
    import estimator_confirmed as ec
    path = tmp_path / "estimator_dimensions.json"
    path.write_text(json.dumps({"parts": {"A": {
        "blank_length_mm": 10, "blank_width_mm": 5, "wire_length_mm": 100}}}),
        encoding="utf-8")
    data, problems = ec.load_corrections(path)
    assert any("one or the other" in p for p in problems)
    assert not data["parts"].get("A", {}).get("wire_length_mm")
    assert not data["parts"].get("A", {}).get("blank_length_mm")


def test_without_a_length_the_line_says_the_length_was_assumed():
    """The estimator assumes a band and marks it — the costing is right. What was missing is
    that nothing made anyone ANSWER it; see the decision test below."""
    from estimator import estimate_material
    part, _ = _build(PRINTED)
    part["quantity"] = 56
    costed = estimate_material(part)
    assert "assumed_length" in costed["cost_method"]
    assert costed["blank_length_mm"] != 219.6


def test_the_missing_length_becomes_a_decision_in_the_deliverable():
    """A REVIEW FLAG IS NOT A DECISION. Decisions are built explicitly in costed_facts and are
    what an estimator is actually asked to answer; a flag sits in a ledger. On 0359342 the
    assumed 900 mm band against a printed 219.6 is four times the mass, 56 off — defensible
    as an assumption, indefensible as an unasked question."""
    from costed_facts import costed_job
    from estimator import estimate_material
    part, _ = _build(PRINTED)
    part["quantity"] = 56
    part["material_estimate"] = estimate_material(part)

    # job_parts() joins the canonical estimate list to the writeup record for the same part,
    # so a realistic source carries both — that join is where the provenance lives.
    facts = costed_job({"manufacturing_writeup": {"parts": [part]},
                        "estimate_summary": {"part_estimates": [part]}})
    decisions = [d for d in (facts.get("decisions_required") or [])
                 if "Cut length" in str(d.get("issue"))]
    assert decisions, "the unknown length must reach the estimator as a decision"
    decision = decisions[0]
    assert decision["kind"] == "manufacturing_decision"
    assert decision["owner"] == "estimator"
    assert "length is the money" in decision["issue"]
    assert "detail sheet" in decision["action"]


# ── units and conflicts ───────────────────────────────────────────────────────────────

def test_an_imperial_diameter_is_converted_not_read_as_millimetres():
    """Ø0.25in read as 0.25 mm is a 25x under-read straight into wire mass."""
    part, _ = _build('Mild Steel Wire Ø0.25"')
    assert part.get("wire_gauge_mm") == pytest.approx(6.35)


def test_two_different_diameters_produce_a_decision_not_the_first_one():
    """Picking silently between Ø8 and Ø10 is 56% out on mass and invisible."""
    part, _ = _build("Mild Steel Wire Ø8mm / Ø10mm")
    assert part.get("wire_gauge_mm") is None
    assert "more than one diameter" in _flags(part)
    assert "8 mm" in _flags(part) and "10 mm" in _flags(part), \
        "both readings must be retained, not just the refusal"


@pytest.mark.parametrize("printed,expected", [
    ('Mild Steel Wire Ø3/16in', 4.7625),
    ('Mild Steel Wire 3/16in DIA', 4.7625),
    ('Mild Steel Wire Ø1/4in', 6.35),
    ('Mild Steel Wire 1/2" DIA', 12.7),
])
def test_an_imperial_fraction_is_converted_not_part_matched(printed, expected):
    """These returned 3.0, 406.4 (the DENOMINATOR times 25.4), 1.0 and 50.8 — silently. The
    decimal patterns were matching INSIDE the fraction, and the refusal branch sat in an elif
    that never ran. Fractions are read first now, and their spans masked before any decimal
    pattern is allowed to look."""
    part, _ = _build(printed)
    assert part.get("wire_gauge_mm") == pytest.approx(expected)


@pytest.mark.parametrize("printed,expected", [
    ('Mild Steel Wire Ø1 1/2in', 38.1),
    ('Mild Steel Wire Ø2 3/4in', 69.85),
    ('Mild Steel Wire 1 1/2in DIA', 38.1),
    ('Mild Steel Wire Ø1-1/2in', 38.1),
])
def test_a_mixed_number_is_one_diameter_not_two(printed, expected):
    """Masking only the fractional half left the whole number for the decimal parser:
    "Ø1 1/2in" returned 1.0 mm instead of 38.1, "Ø2 3/4in" returned 2.0, and "1 1/2in DIA"
    reported "more than one diameter" — a wrong diagnosis on a drawing stating exactly one.
    Both "1 1/2" and "1-1/2" are written by drawing offices."""
    part, _ = _build(printed)
    assert part.get("wire_gauge_mm") == pytest.approx(expected)
    assert "more than one diameter" not in _flags(part), \
        "a mixed number must not be diagnosed as a conflict"


def test_a_fraction_with_no_unit_is_refused_and_says_why():
    """3/16 is 4.76 mm as inches and 0.19 mm as millimetres — a factor of 25.4 on diameter
    and 645 on mass. Not guessed."""
    part, _ = _build("Mild Steel Wire Ø3/16")
    assert part.get("wire_gauge_mm") is None
    assert "fraction with no unit" in _flags(part)


def test_a_fraction_not_marked_as_a_diameter_is_not_assumed_to_be_one():
    part, _ = _build("Mild Steel Wire 3/16in")
    assert part.get("wire_gauge_mm") is None
    assert "not marked as a diameter" in _flags(part)


def test_conflicting_bom_rows_do_not_resolve_by_table_order():
    """Agreeing rows corroborate; disagreeing rows are a decision, and BOTH are kept."""
    part, _ = _build(
        PRINTED,
        extra_rows=({"part_number": "MBY432", "material_text": "CR4, 2mm",
                     "quantity": 56},))
    assert part.get("material_text_as_printed_candidates") == [PRINTED, "CR4, 2mm"]
    assert "readings disagree" in _flags(part)
    assert (part.get("manufacturing_interpretation") or {}).get("stock_form") != "wire", \
        "a conflicting cell must not classify the part at all"


def test_a_description_cannot_settle_a_diameter_the_material_cell_leaves_open():
    """The conflict guard protected the thickness fallback and nothing else, so a diameter
    read off the DESCRIPTION walked past it: "WIRE Ø6" against a cell reading "Ø8mm / Ø10mm"
    produced a gauge of 6 on a record that simultaneously said none was used. Two answers on
    one line, and the wrong one was costed."""
    rows = [{"part_number": "P1", "material_text": "Mild Steel Wire Ø8mm / Ø10mm",
             "quantity": 1}]
    part = {"part_number": "P1", "description": "WIRE Ø6", "pages": [24], "materials": [],
            "page_roles": ["detail"], "textual_operations": [], "operations": [],
            "review_flags": []}
    summary = {"pages": [{"page_number": 24, "text": "", "page_analysis": {}}],
               "document_analysis": {"bom_rows": rows}}
    out = _apply_post_build_fixes([part], summary)[0]
    assert out.get("wire_gauge_mm") is None
    assert "not resolved by a third reading" in " | ".join(out.get("review_flags") or [])


def test_two_sources_stating_different_diameters_cancel():
    """A diameter is one physical fact. Agreeing sources corroborate; disagreeing ones
    cancel — whichever field supplied them."""
    rows = [{"part_number": "P1", "material_text": "Mild Steel Wire Ø8mm", "quantity": 1}]
    part = {"part_number": "P1", "description": "WIRE Ø6", "pages": [24], "materials": [],
            "page_roles": ["detail"], "textual_operations": [], "operations": [],
            "review_flags": []}
    summary = {"pages": [{"page_number": 24, "text": "", "page_analysis": {}}],
               "document_analysis": {"bom_rows": rows}}
    out = _apply_post_build_fixes([part], summary)[0]
    assert out.get("wire_gauge_mm") is None
    assert "different diameters" in " | ".join(out.get("review_flags") or [])


def test_two_sources_stating_the_same_diameter_corroborate():
    rows = [{"part_number": "P1", "material_text": "Mild Steel Wire Ø8mm", "quantity": 1}]
    part = {"part_number": "P1", "description": "WIRE Ø8", "pages": [24], "materials": [],
            "page_roles": ["detail"], "textual_operations": [], "operations": [],
            "review_flags": []}
    summary = {"pages": [{"page_number": 24, "text": "", "page_analysis": {}}],
               "document_analysis": {"bom_rows": rows}}
    out = _apply_post_build_fixes([part], summary)[0]
    assert out.get("wire_gauge_mm") == 8.0


def test_two_materials_the_lexicon_cannot_place_are_not_thereby_the_same():
    """Both normalise to None, and comparing rows on that None made a solid-surface tray and
    a mirror read as corroborating readings of one stock. Where the book has no answer, the
    cell's own words are the identity."""
    part, _ = _build("Corian, 6mm",
                     extra_rows=({"part_number": "MBY432", "material_text": "Mirror, 6mm",
                                  "quantity": 1},))
    assert "readings disagree" in _flags(part)


def test_a_stated_diameter_and_an_absent_one_are_not_equivalent():
    """Absent and conflicting both surfaced as None, so a row stating no diameter matched a
    row stating two irreconcilable ones."""
    part, _ = _build("Mild Steel Wire",
                     extra_rows=({"part_number": "MBY432",
                                  "material_text": "Mild Steel Wire Ø8mm / Ø10mm",
                                  "quantity": 1},))
    assert "readings disagree" in _flags(part)


def test_rows_that_agree_still_classify():
    """Duplicate agreeing rows are corroboration, not a conflict."""
    part, _ = _build(
        PRINTED,
        extra_rows=({"part_number": "MBY432", "material_text": PRINTED, "quantity": 56},))
    assert (part.get("manufacturing_interpretation") or {}).get("stock_form") == "wire"
    assert "readings disagree" not in _flags(part)


# ── the fallback the review flagged ───────────────────────────────────────────────────

def test_an_inherited_thickness_never_becomes_a_diameter():
    """0359342 stamped ONE document-level figure onto two dozen parts. A cell that merely
    says "wire" with no Ø must not turn that note into a bar diameter — on wire the gauge
    IS the mass, and an invented gauge would arrive wearing a measurement's provenance."""
    part, _ = _build("Mild Steel Wire", thickness=6.0,
                     thickness_source="drawing_deterministic")
    assert part.get("wire_gauge_mm") is None
    assert "NOT read as a diameter" in _flags(part)
    assert "drawing_deterministic" in _flags(part), \
        "the refused source must be named, or the refusal reads as a lost datum"


def test_a_measured_thickness_may_still_be_the_diameter():
    """The original reasoning survives where it holds: a solid round bar's min bounding box
    really IS its diameter, so a model-measured figure is admissible whatever named the part.
    Refusing this too would discard a genuine fact in the name of caution."""
    part, _ = _build("Mild Steel Wire", thickness=6.0, thickness_source="solidworks_api")
    assert part.get("wire_gauge_mm") == 6.0


def test_a_name_establishes_the_form_but_never_the_gauge():
    """WITHDRAWN IN REVIEW, and worth recording as such.

    An earlier version of this test asserted that 11762-17-03M "U WIRE" keeps its 8.0 as a
    diameter because its own name says round. That inference was wrong: a name establishes
    the part's FORM and says nothing about where an unstamped thickness came from. The
    min-bounding-box argument is a claim about GEOMETRY and only a model or a DXF can support
    it. I had reached for it to keep an existing fixture green, which is not evidence.

    So the part is still WIRE — that part was always right — but its gauge is now asked for.
    """
    rows = [{"part_number": "11762-17-03M", "material_text": "MILD STEEL", "quantity": 1}]
    part = {"part_number": "11762-17-03M", "description": "U WIRE", "pages": [24],
            "materials": ["MILD STEEL"], "page_roles": ["detail"],
            "normalized_thickness_mm": 8.0, "textual_operations": [], "operations": [],
            "review_flags": []}
    summary = {"pages": [{"page_number": 24, "text": "", "page_analysis": {}}],
               "document_analysis": {"bom_rows": rows}}
    out = _apply_post_build_fixes([part], summary)[0]
    assert (out.get("manufacturing_interpretation") or {}).get("stock_form") == "wire", \
        "the form was never in doubt"
    assert out.get("wire_gauge_mm") is None, "an unstamped thickness is not a measured diameter"
    assert "NOT read as a diameter" in " | ".join(out.get("review_flags") or [])


def test_a_contested_diameter_is_never_settled_by_the_thickness_field():
    """Falling through to the thickness because `_dia is None` would let the fallback quietly
    resolve a conflict the reader deliberately refused to resolve — Ø8 against Ø10 decided by
    a gauge field. A contested figure is not an absent one."""
    part, _ = _build("Mild Steel Wire Ø8mm / Ø10mm", thickness=8.0,
                     thickness_source="solidworks_api")
    assert part.get("wire_gauge_mm") is None
    assert "contested figure is not an absent one" in _flags(part)


def test_a_document_level_figure_is_refused_even_for_a_named_wire():
    """Belt and braces: the name warrant does not rescue an inherited figure."""
    rows = [{"part_number": "Z9", "material_text": "MILD STEEL", "quantity": 1}]
    part = {"part_number": "Z9", "description": "U WIRE", "pages": [24],
            "materials": ["MILD STEEL"], "page_roles": ["detail"],
            "normalized_thickness_mm": 6.0, "material_inherited_from": "document_level",
            "textual_operations": [], "operations": [], "review_flags": []}
    summary = {"pages": [{"page_number": 24, "text": "", "page_analysis": {}}],
               "document_analysis": {"bom_rows": rows}}
    out = _apply_post_build_fixes([part], summary)[0]
    assert out.get("wire_gauge_mm") is None
    assert "document-level figure" in " | ".join(out.get("review_flags") or [])
