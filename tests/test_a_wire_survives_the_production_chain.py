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


def test_an_imperial_fraction_is_refused_by_name():
    part, _ = _build("Mild Steel Wire 3/16in")
    assert part.get("wire_gauge_mm") is None
    assert "imperial fraction" in _flags(part)


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
    assert "not this part's own measured bar" in _flags(part)
    assert "only the material cell calls this part round" in _flags(part), \
        "the refusal must say WHY, or it reads as a lost datum"


def test_a_measured_thickness_may_still_be_the_diameter():
    """The original reasoning survives where it holds: a solid round bar's min bounding box
    really IS its diameter, so a model-measured figure is admissible whatever named the part.
    Refusing this too would discard a genuine fact in the name of caution."""
    part, _ = _build("Mild Steel Wire", thickness=6.0, thickness_source="solidworks_api")
    assert part.get("wire_gauge_mm") == 6.0


def test_a_part_whose_own_name_says_wire_keeps_the_existing_fallback():
    """11762-17-03M "U WIRE": its own name is per-part evidence, and its 8.0 is the model's
    bbox misfiled as a thickness. That reviewed behaviour must not change."""
    rows = [{"part_number": "11762-17-03M", "material_text": "MILD STEEL", "quantity": 1}]
    part = {"part_number": "11762-17-03M", "description": "U WIRE", "pages": [24],
            "materials": ["MILD STEEL"], "page_roles": ["detail"],
            "normalized_thickness_mm": 8.0, "textual_operations": [], "operations": [],
            "review_flags": []}
    summary = {"pages": [{"page_number": 24, "text": "", "page_analysis": {}}],
               "document_analysis": {"bom_rows": rows}}
    out = _apply_post_build_fixes([part], summary)[0]
    assert out.get("wire_gauge_mm") == 8.0
    assert out.get("normalized_thickness_mm") is None


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
