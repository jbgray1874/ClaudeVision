"""
test_estimating_rules.py — lock the costing rules against regression.

WHY THIS EXISTS. In one working session, seven of ten commits fixed defects that earlier
commits in the same session had introduced or exposed. Every one was found by a person
reading a diff or a spreadsheet, days or hours after it shipped. Nothing in the repository
would have caught any of them.

Each test below is a defect that reached a real estimate. The number in it is the number the
job actually produced. They are deliberately written against the PURE functions — material
normalisation, thickness selection, route gating, precedence — so the whole suite runs in a
second with no SolidWorks, no Excel, no SQL and no drawings.

Run:
    python tests/test_estimating_rules.py          # plain, no dependencies
    pytest tests/test_estimating_rules.py          # if pytest is installed
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

_FAILS = []


def eq(actual, expected, what):
    if actual != expected:
        _FAILS.append(f"{what}\n      expected: {expected!r}\n      actual:   {actual!r}")


def ok(cond, what):
    if not cond:
        _FAILS.append(what)


# ── material identity — job 0348837 (Horti Crate) ────────────────────────────────────
def test_joinery_part_numbers_are_not_steel():
    """'-J01' was an unconditional return MILD_STEEL ahead of every material check, so the
    Crate's timber panels were routed to laser, weld and powder. J reads as JOINERY."""
    from json_normaliser import normalise_material_for_part as f
    base = {"surface_finishes": [], "textual_operations": [],
            "description": "HORTI CRATE LOWER FRONT PANEL"}
    eq(f({**base, "part_number": "11225-01-J01", "materials": ["FSC PINE"]}),
       "TIMBER", "-J part stated FSC PINE must resolve TIMBER")
    eq(f({**base, "part_number": "11225-01-J08", "materials": ["MR MDF"]}),
       "MDF", "-J part stated MR MDF must resolve MDF")
    # '-M' remains SDI's metal convention, and still wins when nothing contradicts it.
    eq(f({"part_number": "12120-01-01M", "materials": [], "surface_finishes": [],
          "textual_operations": [], "description": ""}),
       "MILD_STEEL", "-M with no stated material stays MILD_STEEL")
    # ...but yields to a stated timber, as the '-SA' rule always did.
    eq(f({"part_number": "12345-01-02M", "materials": ["FSC PINE"], "surface_finishes": [],
          "textual_operations": [], "description": "TIMBER RAIL"}),
       "TIMBER", "-M stated as pine must not stay steel")


def test_species_resolve_to_a_family():
    """The vocabulary knew TIMBER/WOOD/MDF/PLYWOOD — words a title block never uses. It
    states the species, so a stated material resolved to nothing and part-number hints won."""
    from json_normaliser import normalise_material_for_part as f
    b = {"part_number": "X-01", "surface_finishes": [], "textual_operations": [], "description": ""}
    for stated, expect in (("FSC PINE", "TIMBER"), ("PINE", "TIMBER"), ("SPRUCE", "TIMBER"),
                           ("MR MDF", "MDF"), ("MARINE PLY", "PLYWOOD")):
        eq(f({**b, "materials": [stated]}), expect, f"{stated} must resolve {expect}")
    # A veneered board is a board, whatever species is on its face.
    eq(f({**b, "materials": ["OAK VENEER MDF"]}), "OAK_VENEER_MDF",
       "OAK VENEER MDF must not collapse to solid oak")
    # A pine note on a steel part must not flip it.
    eq(f({**b, "materials": ["MILD STEEL"], "description": "PINE PACKER ON MILD STEEL FRAME"}),
       "MILD_STEEL", "a species mentioned alongside steel must not flip the part")


# ── thickness — 0.5mm TIMBER reached the Crate's labour rows ──────────────────────────
def test_board_thickness_floor():
    """0.5mm sheet steel is ordinary stock; 0.5mm timber is not a thing. Sheet board and
    solid timber have different physical minimums, so one floor cannot serve both."""
    from estimator import _safe_thickness_mm as thk
    def t(mat, vals, dxf=""):
        return thk({"normalized_material": mat, "thicknesses_mm": vals, "dxf_source_file": dxf})
    eq(t("TIMBER", [0.5]), None, "0.5mm on timber must be rejected")
    eq(t("MDF", [0.5]), None, "0.5mm on MDF must be rejected")
    eq(t("FSC PINE", [4.0]), None, "4mm solid timber is below the 6mm floor")
    eq(t("MR MDF", [4.0]), 4.0, "4mm MDF is real sheet board and must pass")
    eq(t("OAK VENEER MDF", [4.0]), 4.0, "a veneered board takes the BOARD floor, not timber's")
    eq(t("OAK", [4.0]), None, "solid oak at 4mm takes the timber floor")
    eq(t("TIMBER", [18.0]), 18.0, "a real board gauge passes")
    # Metal and acrylic are untouched.
    eq(t("MILD_STEEL", [0.5]), 0.5, "0.5mm steel is ordinary stock")
    eq(t("ACRYLIC", [3.0]), 3.0, "3mm acrylic passes")
    # Ordering: the tolerance-table strip must run BEFORE the board floor, or the 3.0 that
    # is also part of that table survives and looks like a real 3mm board.
    eq(t("MDF", [0.5, 1.0, 1.5, 2.0, 3.0]), None,
       "a board whose only values ARE the tolerance table has no thickness")
    eq(t("MDF", [0.5, 1.0, 1.5, 2.0, 3.0, 18.0]), 18.0,
       "the real gauge survives the tolerance table")
    eq(t("MILD_STEEL", [0.5, 1.0, 1.5, 2.0, 3.0]), 0.5,
       "for METAL the tolerance values are real gauges and the fallback still applies")


# ── route gating ─────────────────────────────────────────────────────────────────────
def test_timber_is_never_welded():
    """A weld cue in border boilerplate booked Weld (CO2) AND its chained Dress Welds
    against the Crate's timber panels. Both departments from one legend phrase."""
    from estimator import estimate_process_times
    p = {"part_number": "11225-01-J01", "normalized_material": "TIMBER",
         "materials": ["FSC PINE"], "textual_operations": ["welding", "saw", "glue"],
         "normalized_thickness_mm": 18.0, "overall_length_mm": 600, "overall_width_mm": 400,
         "manufacturing_features": {"welding_required": True, "bend_count": 0},
         "risk_flags": ["weld_required"], "geometry_rollup": {}}
    estimate_process_times(p)
    ok("welding" not in (p.get("textual_operations") or []), "weld op removed from timber")
    ok("dress_welds" not in (p.get("textual_operations") or []), "dress not chained onto timber")
    # The SIGNAL must go with the op, or the report tells the estimator to verify weld
    # content on a part whose sheet has no weld line.
    eq(p["manufacturing_features"].get("welding_required"), False, "weld signal cleared")
    ok("weld_required" not in p.get("risk_flags", []), "weld risk flag cleared")

    s = {"part_number": "X-01M", "normalized_material": "MILD_STEEL", "materials": ["MILD STEEL"],
         "textual_operations": ["welding"], "normalized_thickness_mm": 1.5,
         "overall_length_mm": 300, "overall_width_mm": 200,
         "manufacturing_features": {"welding_required": True}, "risk_flags": ["weld_required"],
         "geometry_rollup": {}}
    estimate_process_times(s)
    ok("welding" in (s.get("textual_operations") or []), "steel keeps its weld")
    eq(s["manufacturing_features"].get("welding_required"), True, "steel keeps its weld signal")


def test_measured_flats_get_no_blank_allowance():
    """A DXF or cut-list flat IS the developed blank. The allowance estimates one from
    FORMED dimensions, and adding it to a measured blank inflated 03M from 45x20 to 51x26 —
    47% more material area, on every DXF-backed job."""
    from document_builder import _build_normalized_geometry as g
    def blank(L, W, t, bends, **marks):
        p = {"manufacturing_features": {"bend_count": bends}, "overall_length_mm": L,
             "overall_width_mm": W, "normalized_thickness_mm": t, "angles_deg": []}
        p.update(marks)
        b = g(p)["bounding_box_flat_mm"]
        return (b["length"], b["width"])
    eq(blank(45.0, 20.0, 1.5, 0, flat_pattern_detected=True), (45.0, 20.0),
       "12120-01-03M measured flat must be unchanged")
    eq(blank(126.39, 82.2, 1.5, 2, geometry_source="dxf"), (126.39, 82.2),
       "12120-01-01M measured flat must be unchanged")
    eq(blank(120.0, 80.0, 2.0, 0), (120.0, 80.0),
       "a part with no bends does not develop — formed size IS blank size")
    # PDF-only WITH bends is where the allowance is a genuine estimate, and still applies.
    eq(blank(120.0, 80.0, 2.0, 2), (128.0, 88.0),
       "formed dimensions with bends still take the allowance")


# ── make vs buy ──────────────────────────────────────────────────────────────────────
def test_bought_in_carries_no_fabrication_labour():
    """The UPC sticker was a catalogue line at GBP 1.05 in one path and a null-numbered
    record carrying weld, dress, powder and glue in another. Same item, two identities."""
    from bought_in_policy import (is_bought_in, has_fabrication_evidence,
                                  bought_in_conflict, strip_fabrication_ops)
    sticker = {"part_number": "UPC STICKER; CLEAR", "page_roles": ["bought_in"],
               "textual_operations": ["welding", "dress_welds", "powder_coating",
                                      "glue", "handling"]}
    ok(is_bought_in(sticker), "a bought_in page role classifies")
    strip_fabrication_ops(sticker)
    eq(sticker["textual_operations"], ["handling"],
       "fabrication removed, handling KEPT — we do fit purchased components")

    fab = {"part_number": "12120-01-01M", "dxf_augmented": True,
           "geometry_source": "dxf_flat_pattern",
           "textual_operations": ["laser_cutting", "folding", "handling"]}
    ok(not is_bought_in(fab), "a fabricated part is not bought-in")
    eq(strip_fabrication_ops(fab), [], "a fabricated part keeps its route")

    # A DRAWING is not fabrication evidence — we draw bought-ins to locate them.
    drawn = {"part_number": "BI-KNURLEDKNOB", "dxf_source_file": "BI-KNURLEDKNOB.DXF",
             "geometry_source": "dxf_matched_no_geometry", "dxf_measured_outline": False}
    ok(not has_fabrication_evidence(drawn),
       "a matched-but-unmeasured DXF is not fabrication evidence")
    ok(not bought_in_conflict(drawn), "and must not raise a false make/buy conflict")
    # Nor is an extents fallback, which also sets flat_pattern_detected.
    ok(not has_fabrication_evidence({"flat_pattern_detected": True,
                                     "dxf_measured_outline": False}),
       "the extents fallback is not measured geometry")
    # A genuine conflict IS surfaced.
    ok(bought_in_conflict({"part_number": "BI-BRACKET", "dxf_augmented": True,
                           "geometry_source": "dxf_flat_pattern"}),
       "bought-in identity plus a measured flat must conflict, not auto-resolve")


# ── precedence ───────────────────────────────────────────────────────────────────────
def test_a_weaker_source_cannot_replace_a_stronger_one():
    """The PDF GA-tree pass overwrote quantities from the SolidWorks assembly BOM, and
    knowledge-base rules replaced native material. Both silently."""
    from source_precedence import rank, apply_field
    ok(rank("knowledge_base (92%)") > rank("solidworks_api"),
       "a person outranks the model")
    ok(rank("solidworks_api") > rank("dxf_flat_pattern") > rank("bom_tree") > rank("llm_full_extract"),
       "model > measured DXF > printed table > transcription")
    eq(rank("wibble"), 0, "an unknown source fills gaps only")

    native = {"quantity": 2, "quantity_source": "solidworks_api"}
    ok(not apply_field(native, "quantity", 1, "bom_tree"), "GA tree must not overwrite native qty")
    eq(native["quantity"], 2, "native quantity kept")
    ok(any("NOT applied" in f for f in native.get("review_flags", [])),
       "and the disagreement is recorded, not swallowed")

    weak = {"quantity": 3, "quantity_source": "llm_full_extract"}
    ok(apply_field(weak, "quantity", 5, "bom_tree"), "a stronger source may still correct a weaker one")
    gap = {}
    ok(apply_field(gap, "quantity", 4, "bom_tree"), "anything may fill a gap")

    from learning_engine import _is_reliable_material
    for src in ("solidworks_api", "dxf_flat_pattern", "knowledge_base (90%)"):
        ok(_is_reliable_material({"normalized_material": "MILD_STEEL", "material_source": src}),
           f"{src} must be protected from override rules")


# ── what we describe must be what we priced ──────────────────────────────────────────
def test_deliverables_describe_only_costed_operations():
    """The quote promised powder coating and weld dressing on a lacquered timber crate the
    sheet charges neither for; the report congratulated the engine for powder-coating eight
    timber panels."""
    from costed_facts import (costed_operations, costed_finish_label,
                              part_numbers_with_operation, operations_for_part)
    src = {
        "workbook_labour": {"rows": [
            {"wb_operation": "Assemble/pack (Acrylic)", "engine_operations": ["handling"],
             "part_numbers": ["11225-01-J01"], "workbook_row": 96},
            {"wb_operation": "CNC / Joinery machining", "engine_operations": ["cnc_routing"],
             "part_numbers": ["11225-01-J01"], "workbook_row": 97},
            {"wb_operation": "Spray / Wet Paint", "engine_operations": ["wet_spray"],
             "part_numbers": ["11225-01-J01"], "workbook_row": 98},
            {"wb_operation": "P.Coat", "engine_operations": ["powder_coating"],
             "part_numbers": ["11225-01-J01"], "workbook_row": 99},
        ]},
        "final_estimate": {"labour_rows": [
            {"operation": "Assemble/pack (Acrylic)", "workbook_row": 96, "total_value_gbp": 0.29},
            {"operation": "CNC / Joinery machining", "workbook_row": 97, "total_value_gbp": 10.19},
            {"operation": "Spray / Wet Paint", "workbook_row": 98, "total_value_gbp": 5.87},
            # priced at nothing by the sheet — not part of the job
            {"operation": "P.Coat", "workbook_row": 99, "batch_hours": 2.8, "total_value_gbp": 0.0},
        ]},
        # the PRE-FILTER engine fields still carry powder and weld; they must not win
        "estimate_summary": {"part_estimates": [
            {"part_number": "11225-01-J01", "labour_estimate": {"costs_gbp": {
                "powder_coating": 3.1, "welding": 2.0, "dress_welds": 1.0}}}]},
    }
    ops = sorted(costed_operations(src))
    eq(ops, ["cnc_routing", "handling", "wet_spray"], "only what the sheet charged")
    eq(costed_finish_label(src), "Wet-spray painted", "finish named from what was charged")
    eq(part_numbers_with_operation(src, "powder_coating", "p.coat"), [],
       "a zero-valued powder row means no part is charged powder")
    eq(operations_for_part(src, "11225-01-J01"), ["handling", "cnc_routing", "wet_spray"],
       "per-part view agrees with the job view")


def test_a_department_resolves_to_one_operation_not_every_alias():
    """Calculated rows carry cost but not identity. Falling back to inverting the department
    expanded every synonym, so the quote listed 'Assembly' and 'Assemble', 'Fold' and
    'Folding', 'Weld' and 'Welding'."""
    from costed_facts import costed_operations
    src = {"final_estimate": {"labour_rows": [
        {"operation": "Assemble/pack (Metal)", "workbook_row": 96, "total_value_gbp": 0.36},
        {"operation": "Fold", "workbook_row": 97, "total_value_gbp": 1.55},
        {"operation": "Weld (CO2)", "workbook_row": 98, "total_value_gbp": 1.56},
    ]}}
    ops = sorted(costed_operations(src))
    eq(len(ops), 3, f"one operation per department, got {ops}")
    for pair in (("assemble", "assembly"), ("fold", "folding"), ("weld", "welding")):
        ok(not all(p in ops for p in pair), f"{pair} must not both appear")
    # A legacy row that wrote the DEPARTMENT into engine_operation must still resolve.
    legacy = {"workbook_labour": {"rows": [
        {"wb_operation": "Spray / Wet Paint", "engine_operation": "Spray / Wet Paint",
         "qty_per_unit": 12, "part_numbers": ["J01"]}]}}
    from costed_facts import costed_finish_label
    eq(costed_finish_label(legacy), "Wet-spray painted",
       "a legacy row shape must still resolve, not read as an unknown operation")


# ── SolidWorks native ────────────────────────────────────────────────────────────────
def test_native_bom_and_geometry_rules():
    """Job 12120. GA double-count, the folded-box-as-flat guard, and flag-don't-zero."""
    from source_connectors.solidworks import (normalize_native_extract,
                                              apply_native_to_pre_estimate)
    recs = [
        {"title": "12120-01-GA", "doctype": 2, "bom": [
            {"part_number": "12120-01-103", "qty": 1.0},
            {"part_number": "12120-01-01M", "qty": 2.0},
            {"part_number": "12120-01-05M", "qty": 4.0},
            {"part_number": "M4 Male Grip Knob", "qty": 8.0}]},
        {"title": "12120-01-103", "doctype": 2, "bom": [{"part_number": "12120-01-01M", "qty": 1.0}]},
        {"title": "12120-01-01M", "doctype": 1, "route_signals": {
            "material": "Mild Steel [CR4]", "is_sheet_metal": True, "bend_count": 4,
            "flat_length_mm": 126.39, "flat_width_mm": 82.2, "thickness_mm": 1.5,
            "bbox_mm": [79.0, 64.5, 21.5]}},
        # cut list returning the FOLDED bounding box on a bent part is not a flat pattern
        {"title": "12120-01-09M", "doctype": 1, "route_signals": {
            "material": "Mild Steel [CR4]", "is_sheet_metal": True, "bend_count": 3,
            "flat_length_mm": 100.0, "flat_width_mm": 50.0, "bbox_mm": [100.0, 50.0, 30.0]}},
        # material but no geometry at all — must be flagged, never costed at zero
        {"title": "12120-01-05M", "doctype": 1, "route_signals": {"material": "Mild Steel [CR4]"}},
        {"title": "M4 Male Grip Knob", "doctype": 1, "route_signals": {"likely_bought_in": True}},
        # cut-outs were extracted from the cut list and then discarded before costing
        {"title": "12120-01-06M", "doctype": 1, "route_signals": {
            "material": "Mild Steel [CR4]", "is_sheet_metal": True, "bend_count": 2,
            "flat_length_mm": 96.49, "flat_width_mm": 39.09, "thickness_mm": 1.2,
            "cut_out_count": 3, "bbox_mm": [30.9, 39.09, 35.0]}},
    ]
    job = normalize_native_extract(recs)
    eq({r.part_number: r.quantity for r in job.bom}["12120-01-01M"], 2.0,
       "BOM quantity read from `qty` (reading only `quantity` pinned every row to 1)")
    eq(job.part_signals["12120-01-09M"].flat_length_mm, None,
       "a folded part whose 'flat' equals its bounding box is the FOLDED box, not a blank")
    eq(job.part_signals["12120-01-01M"].flat_length_mm, 126.39,
       "a genuine developed blank, larger than the envelope, survives")

    parts = [{"part_number": p} for p in
             ("12120-01-GA", "12120-01-103", "12120-01-01M", "12120-01-05M",
              "M4 Male Grip Knob", "12120-01-06M")]
    out = apply_native_to_pre_estimate(parts, job)
    by = {p["part_number"]: p for p in parts}
    # The GA is absent from its own BOM; without indexing the assemblies it is costed as a leaf.
    ok(by["12120-01-GA"].get("is_assembly_parent"), "the top assembly is a parent, not a leaf")
    ok(by["12120-01-103"].get("is_assembly_parent"), "a sub-assembly is a parent too")
    eq(by["12120-01-01M"]["blank_length_mm"], 126.39, "native flat applied where no DXF")
    eq(by["12120-01-01M"]["quantity"], 2, "quantity from the full-depth assembly BOM")
    eq(by["12120-01-01M"]["quantity_source"], "solidworks_api",
       "and its SOURCE recorded, so a later pass cannot silently overwrite it")
    ok(by["M4 Male Grip Knob"].get("is_bought_in"), "an imported body with no fab features is bought in")
    ok(by["12120-01-05M"].get("native_material_without_geometry"),
       "material with no geometry is FLAGGED — a GBP 0 line must not read as free")
    ok(out["assembly_parent"] >= 2 and out["bought_in"] >= 1, "counts reported")
    # Cut-outs reach costing: each internal profile needs its own pierce, as does the outer.
    _mf = by["12120-01-06M"].get("manufacturing_features") or {}
    eq(_mf.get("cut_out_count"), 3, "cut-out count must reach the engine, not be discarded")
    eq(_mf.get("pierce_count"), 4, "3 cut-outs plus the outer profile = 4 pierces")


# ── DXF ──────────────────────────────────────────────────────────────────────────────
def test_dxf_blocks_are_exploded():
    """A SolidWorks flat-pattern export wraps the profile in a block. Iterating model space
    alone found one INSERT and no geometry, so the blank came back 0 and the part fell
    through to the drawing's dimension TEXT — 4 of 7 parts on 12120."""
    try:
        import ezdxf
    except ImportError:
        print("      (skipped: ezdxf not installed)")
        return
    import tempfile
    from pathlib import Path
    from dxf_reader import extract_flat_pattern_data

    def build(path, L, W, blocked, holes=0):
        d = ezdxf.new(); d.header["$INSUNITS"] = 4
        msp = d.modelspace()
        pts = [(0, 0, L, 0), (L, 0, L, W), (L, W, 0, W), (0, W, 0, 0)]
        target = d.blocks.new(name="FLAT") if blocked else msp
        for a in pts:
            target.add_line(a[:2], a[2:], dxfattribs={"layer": "0" if blocked else "SLD-0"})
        for i in range(holes):
            target.add_circle((10 + i * 10, W / 2), 2.5, dxfattribs={"layer": "0" if blocked else "SLD-0"})
        if blocked:
            msp.add_blockref("FLAT", (0, 0), dxfattribs={"layer": "SLD-0"})
        d.saveas(path)
        return Path(path)

    tmp = tempfile.mkdtemp()
    for pn, L, W in (("01M", 126.39, 82.2), ("08M", 79.0, 37.79)):
        r = extract_flat_pattern_data(build(os.path.join(tmp, f"{pn}.dxf"), L, W, True))
        eq((r.get("blank_length_mm"), r.get("blank_width_mm")), (max(L, W), min(L, W)),
           f"{pn}: a blocked profile must measure the same as a loose one")
    # Holes inside a block were invisible: 06M reported zero, under-pricing the laser.
    r = extract_flat_pattern_data(build(os.path.join(tmp, "holes.dxf"), 96.49, 39.09, True, holes=8))
    ok(int(r.get("estimated_hole_count") or r.get("hole_count") or 0) >= 8,
       f"circles inside a block must be counted (got {r.get('estimated_hole_count')})")


# ── runner ───────────────────────────────────────────────────────────────────────────
def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    print(f"\n{len(tests)} regression fixture(s) — each locks a defect that reached a real estimate\n")
    errors = 0
    for name, fn in tests:
        before = len(_FAILS)
        try:
            fn()
        except Exception:
            _FAILS.append(f"{name} raised:\n{traceback.format_exc()}")
        new = len(_FAILS) - before
        print(f"  {'FAIL' if new else 'pass'}  {name}")
        for f in _FAILS[before:]:
            print(f"      - {f}")
        errors += new
    print(f"\n{'FAILED' if errors else 'OK'} — {errors} failure(s)\n")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
