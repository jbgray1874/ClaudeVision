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

# NO LIVE ANYTHING. This suite is meant to run in a second with no SolidWorks, no Excel, no
# SQL and no drawings — and it was opening a connection to the production SDILive server
# just by importing learning_engine, which tests its pure functions. A suite that needs the
# production database is not isolated, cannot run in CI, and makes every fixture depend on a
# machine being reachable. Set BEFORE any src import, because the connection was made at
# module import time.
os.environ.setdefault("SDI_OFFLINE", "1")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

_FAILS = []

# Under pytest a failure MUST raise, or pytest reports a green run over a broken engine:
# these helpers only ever appended to a list, so `pytest tests/test_estimating_rules.py`
# passed against every mutation the plain runner caught. The plain runner keeps collecting,
# so it can still report every failure in a test rather than stopping at the first.
_COLLECT_ONLY = False


def _fail(msg: str) -> None:
    _FAILS.append(msg)
    if not _COLLECT_ONLY:
        raise AssertionError(msg)


def eq(actual, expected, what):
    if actual != expected:
        _fail(f"{what}\n      expected: {expected!r}\n      actual:   {actual!r}")


def ok(cond, what):
    if not cond:
        _fail(what)


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
    # 06M already carries a weaker pierce count — the sort of figure a PDF pass leaves
    # behind. The model says nine; the drawing text guessed two.
    for _p in parts:
        if _p["part_number"] == "12120-01-06M":
            _p["manufacturing_features"] = {"pierce_count": 2}
            _p["geometry_rollup"] = {"estimated_pierce_count": 2}
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
    # The model is rank 90 and must SUPERSEDE the weaker count, not merely fill a gap: any
    # earlier positive number, however weak, otherwise locks the stronger evidence out.
    eq(_mf.get("pierce_count_source"), "solidworks_api", "and the source is recorded")
    # This is the field the laser reads. Asserting only on manufacturing_features tests the
    # staging value and says nothing about what the part was actually charged.
    eq((by["12120-01-06M"].get("geometry_rollup") or {}).get("estimated_pierce_count"), 4,
       "the pierce count COSTING reads must carry the native figure, not the PDF's 2")
    ok(any("pierce_count" in str(f) for f in (by["12120-01-06M"].get("review_flags") or [])),
       "replacing a weaker figure is flagged, not done silently")


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
    eq(int(r.get("estimated_hole_count") or r.get("hole_count") or 0), 8,
       f"circles inside a block must be counted (got {r.get('estimated_hole_count')})")
    # Every hole is a pierce, and so is the outer profile. The non-recursive parser never
    # entered the block, reported zero, and the laser's pierce time vanished with it.
    eq(r.get("estimated_pierce_count"), 9, "8 holes plus the outer profile = 9 pierces")


def test_annotation_circles_are_not_holes():
    """hole_diams filtered sub-1mm circles and annotation layers; hole_count then counted
    every circle in the file regardless. The two described different sets, and a symbol
    layer inflated the laser. One filtered list must feed both."""
    try:
        import ezdxf
    except ImportError:
        print("      (skipped: ezdxf not installed)")
        return
    import tempfile
    from pathlib import Path
    from dxf_reader import extract_flat_pattern_data

    d = ezdxf.new(); d.header["$INSUNITS"] = 4
    msp = d.modelspace()
    L, W = 120.0, 60.0
    for a in [(0, 0, L, 0), (L, 0, L, W), (L, W, 0, W), (0, W, 0, 0)]:
        msp.add_line(a[:2], a[2:], dxfattribs={"layer": "SLD-0"})
    for i in range(3):                                    # three real holes
        msp.add_circle((20 + i * 20, W / 2), 3.0, dxfattribs={"layer": "SLD-0"})
    for i in range(5):                                    # weld/finish symbols — not holes
        msp.add_circle((10 + i * 5, 5), 2.0, dxfattribs={"layer": "SYMBOLS(BENCHMARK)"})
    msp.add_circle((60, 50), 0.2, dxfattribs={"layer": "SLD-0"})   # centre mark, not a hole
    path = os.path.join(tempfile.mkdtemp(), "annot.dxf")
    d.saveas(path)

    r = extract_flat_pattern_data(Path(path))
    eq(int(r.get("estimated_hole_count") or r.get("hole_count") or 0), 3,
       "only circles that survive the hole filter may be counted as holes")
    eq(r.get("estimated_pierce_count"), 4, "3 holes plus the outer profile = 4 pierces")
    ok(all(dia >= 1.0 for dia in (r.get("hole_diameters_mm") or [])),
       "hole diameters and hole count must describe the same set of circles")


def test_annotation_layers_are_skipped_by_effective_layer():
    """An entity drawn on layer '0' INSIDE a block sits on the layer its INSERT sits on —
    that is how these exports are written. Reading the entity's own layer returns '0' for
    every one of them, so circles inside a SYMBOLS(BENCHMARK) block passed the skip filter
    untouched and were priced as holes. The outline walk always resolved this; the feature
    walk did not."""
    try:
        import ezdxf
    except ImportError:
        print("      (skipped: ezdxf not installed)")
        return
    import tempfile
    from pathlib import Path
    from dxf_reader import extract_flat_pattern_data

    d = ezdxf.new(); d.header["$INSUNITS"] = 4
    msp = d.modelspace()
    L, W = 120.0, 60.0
    for a in [(0, 0, L, 0), (L, 0, L, W), (L, W, 0, W), (0, W, 0, 0)]:
        msp.add_line(a[:2], a[2:], dxfattribs={"layer": "SLD-0"})
    msp.add_circle((30, 30), 3.0, dxfattribs={"layer": "SLD-0"})       # one real hole
    sym = d.blocks.new(name="WELDSYM")                                  # symbols on layer 0 …
    for i in range(6):
        sym.add_circle((i * 4, 0), 2.0, dxfattribs={"layer": "0"})
    # … placed on an annotation layer. Their effective layer is the INSERT's.
    msp.add_blockref("WELDSYM", (10, 5), dxfattribs={"layer": "SYMBOLS(BENCHMARK)"})
    path = os.path.join(tempfile.mkdtemp(), "inherit.dxf")
    d.saveas(path)

    r = extract_flat_pattern_data(Path(path))
    eq(int(r.get("estimated_hole_count") or r.get("hole_count") or 0), 1,
       "a circle inheriting an annotation layer from its block is not a hole")
    eq(r.get("estimated_pierce_count"), 2, "1 hole plus the outer profile = 2 pierces")


def test_non_circular_cut_outs_are_pierced():
    """A pierce is a closed CONTOUR, not a round hole. Counting circles + 1 prices a slot,
    a rectangular aperture and a D-cut at nothing — and every one of them costs the laser a
    pierce and its own cutting time. Cut-outs arrive in three shapes and all three count: a
    circle, a closed polyline, and a loop assembled from separate lines and arcs."""
    try:
        import ezdxf
    except ImportError:
        print("      (skipped: ezdxf not installed)")
        return
    import tempfile
    from pathlib import Path
    from dxf_reader import extract_flat_pattern_data

    d = ezdxf.new(); d.header["$INSUNITS"] = 4
    msp = d.modelspace()
    L, W = 200.0, 100.0
    for a in [(0, 0, L, 0), (L, 0, L, W), (L, W, 0, W), (0, W, 0, 0)]:
        msp.add_line(a[:2], a[2:], dxfattribs={"layer": "SLD-0"})
    msp.add_circle((30, 50), 5.0, dxfattribs={"layer": "SLD-0"})            # 1: round hole
    msp.add_lwpolyline([(60, 40), (90, 40), (90, 60), (60, 60)],            # 2: rectangular
                       close=True, dxfattribs={"layer": "SLD-0"})
    # 3: a slot with radiused ends — two lines and two arcs, no single closed entity.
    msp.add_line((120, 45), (150, 45), dxfattribs={"layer": "SLD-0"})
    msp.add_line((150, 55), (120, 55), dxfattribs={"layer": "SLD-0"})
    msp.add_arc((150, 50), 5.0, -90, 90, dxfattribs={"layer": "SLD-0"})
    msp.add_arc((120, 50), 5.0, 90, 270, dxfattribs={"layer": "SLD-0"})
    # A drawing frame and title block are closed rectangles too. Counting every closed
    # contour in the file would charge the laser a pierce for the border.
    for box in ([(-50, -50), (260, -50), (260, 160), (-50, 160)],
                [(180, -45), (255, -45), (255, -10), (180, -10)]):
        msp.add_lwpolyline(box, close=True, dxfattribs={"layer": "TITLE_FRAME"})
    path = os.path.join(tempfile.mkdtemp(), "cutouts.dxf")
    d.saveas(path)

    r = extract_flat_pattern_data(Path(path))
    eq(r.get("estimated_pierce_count"), 4,
       "3 cut-outs (round, rectangular, slot) plus the outer profile = 4 pierces")
    eq(r.get("closed_contour_count"), 4, "each closed contour counted once")
    ok(not r.get("pierce_count_incomplete"),
       "every segment chained into a loop — nothing left open to warn about")
    # The outer profile is one of the contours, not an extra on top of them.
    eq(int(r.get("estimated_hole_count") or r.get("hole_count") or 0), 1,
       "only the circle is a HOLE; the slot and aperture are cut-outs, not drilled")


# ── workbook join — job 12120 ────────────────────────────────────────────────────────
def test_labour_rows_join_to_the_parts_that_produced_them():
    """The calculated cost of a labour row must land on the parts that row was grouped
    from. wb_populate used to publish the route record BEFORE the write loop and then
    back-fill sheet rows by matching on DEPARTMENT NAME in insertion order. One department,
    one group — fine. Two gauges of Fold, and the 1.2mm cost lands on the 1.5mm parts (and
    the Laser rows swap with them). 12120 has exactly that shape.

    The invariant: a row's workbook_row, parts and gauge all come off the same group."""
    from wb_populate import build_workbook_labour
    from costed_facts import operations_for_part, part_numbers_with_operation

    # Insertion order deliberately unlike sheet order, and unlike sorted-key order: any
    # implementation that pairs rows to sheet rows positionally will mis-associate.
    groups = {
        "Fold|1.5":  {"wb_op": "Fold",  "engine_ops": ["folding"], "thickness": 1.5,
                      "material": "Mild Steel", "qty": 2, "parts": ["12120-01-04M"],
                      "workbook_row": 44},
        "Laser|1.2": {"wb_op": "Laser", "engine_ops": ["laser_cutting"], "thickness": 1.2,
                      "material": "Mild Steel", "qty": 3, "parts": ["12120-01-01M", "12120-01-06M"],
                      "workbook_row": 41},
        "Fold|1.2":  {"wb_op": "Fold",  "engine_ops": ["folding"], "thickness": 1.2,
                      "material": "Mild Steel", "qty": 3, "parts": ["12120-01-01M", "12120-01-06M"],
                      "workbook_row": 43},
        "Laser|1.5": {"wb_op": "Laser", "engine_ops": ["laser_cutting"], "thickness": 1.5,
                      "material": "Mild Steel", "qty": 2, "parts": ["12120-01-04M"],
                      "workbook_row": 42},
        # Never written to the sheet — must not appear in the route record at all.
        "Weld|-":    {"wb_op": "Weld",  "engine_ops": ["welding"], "thickness": None,
                      "material": "Mild Steel", "qty": 1, "parts": ["12120-01-09M"]},
    }
    rec = build_workbook_labour(groups, ["12120-01-99B"])
    rows = rec["rows"]

    eq([r["workbook_row"] for r in rows], [41, 42, 43, 44], "rows must be in sheet order")
    ok(all(r["wb_operation"] != "Weld" for r in rows),
       "a group with no sheet row was never priced and must not be published as route")
    by_row = {r["workbook_row"]: r for r in rows}
    for g in groups.values():
        if not g.get("workbook_row"):
            continue
        r = by_row[g["workbook_row"]]
        eq((r["wb_operation"], r["thickness_mm"], r["part_numbers"]),
           (g["wb_op"], g["thickness"], g["parts"]),
           f"row {g['workbook_row']}: identity must come off the group that wrote it")
    # The bug was invisible on identity alone until cost was joined on. £30 was booked for
    # the 1.5mm fold; it must not be reported against the 1.2mm parts.
    summary = {
        "workbook_labour": rec,
        "final_estimate": {"schema": "final_estimate.v2", "labour_rows": [
            {"workbook_row": 41, "operation": "Laser", "batch_hours": 0.4, "total_value_gbp": 18.0},
            {"workbook_row": 42, "operation": "Laser", "batch_hours": 0.2, "total_value_gbp": 9.0},
            {"workbook_row": 43, "operation": "Fold",  "batch_hours": 0.5, "total_value_gbp": 22.0},
            {"workbook_row": 44, "operation": "Fold",  "batch_hours": 0.7, "total_value_gbp": 30.0},
        ]},
    }
    from costed_facts import _workbook_rows
    priced = {r["total_value_gbp"]: r["part_numbers"] for r in (_workbook_rows(summary) or [])}
    eq(priced.get(30.0), ["12120-01-04M"], "the 1.5mm fold cost belongs to the 1.5mm part")
    eq(priced.get(22.0), ["12120-01-01M", "12120-01-06M"], "the 1.2mm fold cost belongs to the 1.2mm parts")
    ok("folding" in operations_for_part(summary, "12120-01-04M"),
       "a part in a priced fold group must show folding")
    eq(sorted(part_numbers_with_operation(summary, "folding")),
       ["12120-01-01M", "12120-01-04M", "12120-01-06M"], "every folded part, once")


# ── read-back — job 12120 ────────────────────────────────────────────────────────────
def test_every_material_block_is_read_back_not_just_the_bom():
    """Fabricated material lives in three blocks below the BOM, and each names its value
    column differently — "Cost" on tube, "Cost Per Part" on steel and other-sheet. Reading
    all of them through the BOM's "Total Value" returned rows carrying no value; asking for
    a block named "wire" when CELL_MAP defines "tube" skipped that block entirely, in
    silence. On 12120 the read-back summed to GBP 9.64 of the sheet's own GBP 10.07 total,
    the missing 43p being exactly the fabricated material. A snapshot that will not
    reconcile to its own total is not something an ERP export can be built on."""
    from wb_populate import CELL_MAP
    from wep_readback_from_xlsx import read_final_rows

    class Cell:
        def __init__(self, v): self.Value = v

    class FakeSheet:
        """Only what _read_block touches: .Cells(row, col).Value."""
        def __init__(self, grid): self.grid = grid
        def Cells(self, r, c): return Cell(self.grid.get((r, c)))

    grid = {}

    def block(name, headers, rows):
        b = CELL_MAP[name]
        hr = b["first_row"] - 1
        for c, text in headers.items():
            grid[(hr, c)] = text
        for i, vals in enumerate(rows):
            for c, v in vals.items():
                grid[(b["first_row"] + i, c)] = v

    block("bom",
          {3: "Bill Of Materials", 10: "Price", 11: "Qty Per Unit", 12: "Scrap", 13: "Total Value"},
          [{3: "M6 Pem Stud", 10: 0.12, 11: 4, 13: 9.64}])
    # Value column here is "Cost", not "Total Value".
    block("tube", {3: "Part Description", 5: "Qty Per Unit", 6: "Gauge",
                   7: "Length", 8: "Price Per M", 11: "Cost"},
          [{3: "25x25x1.5 SHS Leg", 5: 2, 6: 1.5, 7: 300.0, 8: 4.10, 11: 0.18}])
    # And "Cost Per Part" here.
    block("steel", {3: "Part Description", 5: "Qty Per Unit", 6: "Part Length",
                    7: "Part Width", 8: "Gauge", 13: "Cost Per Part"},
          [{3: "12120-01-01M", 5: 1, 6: 126.39, 7: 82.2, 8: 1.2, 13: 0.15}])
    block("other_sheet", {3: "Part Description", 4: "Qty Per Unit", 5: "Part Length",
                          6: "Part Width", 7: "Thickness", 13: "Cost Per Part"},
          [{3: "5mm Acrylic Window", 4: 1, 5: 200.0, 6: 100.0, 7: 5.0, 13: 0.10}])

    rows = read_final_rows(FakeSheet(grid), 24).get("material_rows") or []
    got = {r.get("block") for r in rows}
    for name in ("bom", "tube", "steel", "other_sheet"):
        ok(name in got, f"the {name} block must be read back — CELL_MAP defines it")
    for r in rows:
        ok(r.get("total_value_gbp") is not None,
           f"{r.get('block')} row carries no value: its value column was not mapped")
    total = sum(float(r.get("total_value_gbp") or 0) for r in rows)
    eq(round(total, 2), 10.07, "material rows must reconcile to the sheet's own total")


def test_the_resolver_sees_nested_fields_and_explicit_zeros():
    """Two things the connector-local writes kept getting wrong, and the reason they stayed
    brittle: the fields that drive cost do not live at the top of a part record, and zero is
    an answer rather than a gap."""
    from source_precedence import apply_field, source_of, value_of, MISSING

    # Nested. A resolver that only sees top-level keys cannot arbitrate the pierce count.
    p = {}
    ok(apply_field(p, "geometry_rollup.estimated_pierce_count", 9, "solidworks_api"),
       "a nested field must be writable through the resolver")
    eq(p["geometry_rollup"]["estimated_pierce_count"], 9, "written where costing reads it")
    eq(source_of(p, "geometry_rollup.estimated_pierce_count"), "solidworks_api",
       "and its source recorded alongside it, not at the top of the record")
    ok(not apply_field(p, "geometry_rollup.estimated_pierce_count", 2, "llm_extract"),
       "a weaker source must not replace it")
    eq(p["geometry_rollup"]["estimated_pierce_count"], 9, "the stronger value survives")
    ok(any("estimated_pierce_count" in str(f) for f in p.get("review_flags") or []),
       "and the disagreement is recorded, not discarded")

    # Explicit zero. `if cut_out_count:` read the model saying "none" as nobody having
    # looked, which is how a weaker count survived against the strongest source there is.
    z = {}
    ok(apply_field(z, "manufacturing_features.cut_out_count", 0, "solidworks_api"),
       "zero is a value and must be written")
    eq(value_of(z, "manufacturing_features.cut_out_count"), 0, "and readable as zero")
    ok(not apply_field(z, "manufacturing_features.cut_out_count", 4, "llm_extract"),
       "a recorded zero is defended like any other value — it is not an opening")
    eq(value_of({}, "manufacturing_features.cut_out_count"), MISSING,
       "absent is MISSING, which is not the same fact as zero")
    # Empty containers and None really are gaps.
    e = {"normalized_material": ""}
    ok(apply_field(e, "normalized_material", "MILD_STEEL", "inference"),
       "an empty string is a gap anything may fill")


def test_arbitrated_fields_are_not_written_directly():
    """The resolver only protects a datum if every writer goes through it. One direct
    assignment anywhere reintroduces last-writer-wins for that field, silently.

    So the rule is checked on the SOURCE, not just the behaviour: a fixture that exercises
    apply_field proves the resolver works, not that anyone calls it. Reverting a converted
    call site to a direct write passed every behavioural test in this file.

    PARSED, NOT PATTERN-MATCHED. The first version of this guard was a regex, and a regex
    reads text rather than code: it missed single-quoted keys, dict literals, keyword
    arguments, .update(), aliased records and any assignment split over two lines. It was
    already blind to empty_part_record(quantity=...), which is exactly how BOM quantities
    were reaching parts unattributed. The AST sees the shapes themselves.

    This guards the modules already converted. It is not the whole pipeline yet — the
    remaining writers are listed at the end of this file's docstring and each one is a place
    a stronger source can still be overwritten in silence."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src"
    RESOLVER_CLEAN = ["bom_tree.py", "part_index.py", "learning_engine.py",
                      "source_connectors/solidworks.py"]
    ARBITRATED = {"quantity", "normalized_material", "pierce_count",
                  "estimated_pierce_count", "normalized_thickness_mm"}
    # A single record that holds arbitrated evidence. NOT `parts`, which is a collection:
    # `parts[pn] = <record>` inserts a whole record rather than writing a field, while
    # `parts[pn]["quantity"] = x` is still caught by the literal-key rule below.
    RECORDS = {"part", "_part", "p", "_p", "nr", "target", "pe"}
    # Constructors that build a part record: passing an arbitrated field as a keyword sets it
    # with no source, which is a direct write wearing a different hat.
    CONSTRUCTORS = {"empty_part_record", "_empty_part_record"}

    class Guard(ast.NodeVisitor):
        def __init__(self, rel, allowed):
            self.rel, self.allowed, self.hits = rel, allowed, []

        def _report(self, node, what):
            if node.lineno not in self.allowed:
                self.hits.append(f"{self.rel}:{node.lineno}  {what}")

        def _is_record(self, node):
            if isinstance(node, ast.Name):
                return node.id in RECORDS
            if isinstance(node, ast.Subscript):      # parts[pn]["quantity"] = ...
                return self._is_record(node.value)
            if isinstance(node, ast.Attribute):
                return node.attr in RECORDS
            return False

        def visit_Assign(self, node):
            for tgt in node.targets:
                if not isinstance(tgt, ast.Subscript):
                    continue
                key = tgt.slice
                # record["arbitrated"] = ...  (quote style is irrelevant to the parser)
                if isinstance(key, ast.Constant) and key.value in ARBITRATED:
                    self._report(node, f'{ast.unparse(tgt)} = ...')
                # record[<computed>] = ...  — names no field, so the field name cannot be
                # the test. This is how the override rules wrote material.
                elif not isinstance(key, ast.Constant) and self._is_record(tgt.value):
                    self._report(node, f'{ast.unparse(tgt)} = ...  (computed key)')
            self.generic_visit(node)

        def visit_Call(self, node):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            # record.update({"quantity": ...}) / record.update(quantity=...)
            if name == "update" and isinstance(fn, ast.Attribute) and self._is_record(fn.value):
                for kw in node.keywords:
                    if kw.arg in ARBITRATED:
                        self._report(node, f"update({kw.arg}=...)")
                for a in node.args:
                    if isinstance(a, ast.Dict):
                        for k in a.keys:
                            if isinstance(k, ast.Constant) and k.value in ARBITRATED:
                                self._report(node, f"update({{{k.value!r}: ...}})")
            # empty_part_record(quantity=...) — born with a value and no source.
            if name in CONSTRUCTORS:
                for kw in node.keywords:
                    if kw.arg in ARBITRATED and not (
                            isinstance(kw.value, ast.Constant) and kw.value.value is None):
                        self._report(node, f"{name}({kw.arg}=...) with no source")
            self.generic_visit(node)

    offenders = []
    for rel in RESOLVER_CLEAN:
        path = root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        # A deliberate direct write is allowed when the author marked the line.
        allowed = {n for n, line in enumerate(text.splitlines(), 1)
                   if "precedence: direct-write ok" in line}
        g = Guard(rel, allowed)
        g.visit(ast.parse(text))
        offenders.extend(g.hits)
    eq(sorted(offenders), [],
       "these writes bypass the resolver — a stronger source can be overwritten in silence")


def test_agreeing_evidence_upgrades_provenance():
    """A source that CONFIRMS the value already present has told us something real: the datum
    now rests on stronger evidence than it did. Callers used to skip the resolver when the
    numbers matched — "nothing to change" — so the value kept the weaker source's name and a
    later medium-ranked pass could still displace a figure the model had confirmed."""
    from source_precedence import apply_field, source_of
    p = {"quantity": 2, "quantity_source": "bom_tree"}
    changed = apply_field(p, "quantity", 2, "solidworks_api")
    eq(source_of(p, "quantity"), "solidworks_api",
       "agreement from a stronger source must upgrade the recorded source")
    ok(not changed,
       "but the VALUE did not change, and an audit message must not claim it did")
    # And that upgrade is what protects it.
    ok(not apply_field(p, "quantity", 7, "drawing_deterministic"),
       "once the model has confirmed it, a weaker source cannot displace it")
    eq(p["quantity"], 2, "the confirmed value stands")
    # A weaker source agreeing must not DOWNGRADE the provenance.
    q = {"quantity": 2, "quantity_source": "solidworks_api"}
    apply_field(q, "quantity", 2, "llm_extract")
    eq(source_of(q, "quantity"), "solidworks_api", "agreement never weakens provenance")


def test_equal_rank_conflicts_are_never_resolved_by_running_order():
    """Two title-block readings of the same rank disagreeing is not refinement, it is a
    conflict. Letting the later one win made the answer depend on the order pages happened to
    be read in — silently, because the write succeeded so nothing was flagged."""
    from source_precedence import apply_field
    p = {}
    apply_field(p, "normalized_material", "MILD_STEEL", "drawing_deterministic")
    ok(not apply_field(p, "normalized_material", "ALUMINIUM", "drawing_deterministic"),
       "an equal-ranked disagreement must not overwrite")
    eq(p["normalized_material"], "MILD_STEEL", "the first observation is kept")
    ok(any("equal standing" in str(f) for f in p.get("review_flags") or []),
       "and the conflict is flagged for a person, not silently resolved")
    # Confidence is a real reason to prefer the newcomer; page order is not.
    q = {}
    apply_field(q, "normalized_material", "MILD_STEEL", "llm_extract", confidence=0.4)
    ok(apply_field(q, "normalized_material", "ALUMINIUM", "llm_extract", confidence=0.9),
       "a strictly higher confidence at equal rank is a reason, not an accident")
    eq(q["normalized_material"], "ALUMINIUM", "and it wins")


def test_the_knowledge_base_is_not_gated_before_arbitration():
    """A local reliability test refused to offer a knowledge-base correction whenever the
    part already carried anything ranked at or above an override rule — so rank-100 KB data,
    the one signal carrying knowledge the drawing does not, was never offered against a
    rank-50, 70 or 90 value. That inverts the ranking table it exists to serve."""
    from source_precedence import apply_field
    for existing_source in ("override_rule:x", "drawing_deterministic", "solidworks_api"):
        p = {"normalized_material": "MILD_STEEL", "material_source": existing_source}
        ok(apply_field(p, "normalized_material", "ALUMINIUM", "knowledge_base (95%)",
                       confidence=0.95),
           f"a person's correction must outrank {existing_source}")
        eq(p["normalized_material"], "ALUMINIUM", "and be applied")


def test_bom_quantities_are_attributed_when_the_record_is_born():
    """Records were constructed with quantity=<BOM value> and no source, and the apply path
    further on only ran for quantities of None or 1 — so every quantity ABOVE one, which is
    most of them, was never attributed and never protected."""
    from document_builder import _empty_part_record
    from source_precedence import apply_field, source_of
    r = _empty_part_record("X-01", description="d", quantity=None)
    eq(r["quantity"], None, "constructed with no quantity, so it is a gap the resolver fills")
    apply_field(r, "quantity", 4, "bom_tree")
    eq((r["quantity"], source_of(r, "quantity")), (4, "bom_tree"), "attributed at birth")
    ok(not apply_field(r, "quantity", 9, "llm_extract"),
       "and defended from a weaker source thereafter — including when it is above one")


def test_the_rules_suite_touches_no_live_service():
    """The suite opened a connection to the production SDILive server merely by importing
    learning_engine for its pure functions. A suite that needs the production database is not
    isolated, cannot run in CI, and makes every fixture depend on a machine being up."""
    import learning_engine
    eq(os.environ.get("SDI_OFFLINE"), "1", "the suite declares itself offline before importing")
    ok(not learning_engine._DB_AVAILABLE,
       "and the module honours it rather than dialling out at import time")


def test_solidworks_submits_agreement_at_the_call_site():
    """Behavioural, on the real call path. Asserting on apply_field proves the resolver
    upgrades provenance on agreement; it says nothing about whether the connector SUBMITS
    when the values already match. Restoring the `if values differ` guard passed every
    resolver fixture in this file."""
    from source_connectors.solidworks import (normalize_native_extract,
                                              apply_native_to_pre_estimate)
    recs = [
        {"title": "ASM-01", "doctype": 2, "bom": [{"part_number": "AAA-01M", "qty": 2.0}]},
        {"title": "AAA-01M", "doctype": 1, "route_signals": {
            "material": "Mild Steel [CR4]", "is_sheet_metal": True, "bend_count": 1,
            "flat_length_mm": 100.0, "flat_width_mm": 50.0, "thickness_mm": 1.5,
            "bbox_mm": [60.0, 50.0, 20.0]}},
    ]
    job = normalize_native_extract(recs)
    # The engine already has the RIGHT answers, from weaker sources.
    parts = [{"part_number": "AAA-01M",
              "quantity": 2, "quantity_source": "bom_tree",
              "normalized_material": "MILD_STEEL", "material_source": "drawing_deterministic",
              "normalized_thickness_mm": 1.5, "thickness_source": "drawing_deterministic"}]
    apply_native_to_pre_estimate(parts, job)
    p = parts[0]
    eq(p.get("quantity_source"), "solidworks_api",
       "the model confirming a quantity must upgrade its provenance, not skip the resolver")
    eq(p.get("material_source"), "solidworks_api", "same for a confirmed material")
    eq(p.get("thickness_source"), "solidworks_api", "and a confirmed thickness")
    eq((p["quantity"], p["normalized_material"], p["normalized_thickness_mm"]),
       (2, "MILD_STEEL", 1.5), "and none of the values changed")
    # That upgrade is the whole point: the values are now defended.
    from source_precedence import apply_field
    ok(not apply_field(p, "quantity", 9, "drawing_deterministic"),
       "a confirmed quantity is no longer displaceable by a medium-ranked pass")


def test_the_knowledge_base_reaches_the_resolver_at_the_call_site():
    """Behavioural, on the real call path. The local reliability gate sat BEFORE the
    resolver, so a rank-100 correction was never offered at all — and a fixture that calls
    apply_field directly cannot see that, because it starts after the gate."""
    import learning_engine as LE

    class _StubDB:
        def lookup_part(self, pn):
            return {"material": "ALUMINIUM", "thickness_mm": 3.0, "confidence": 0.95}
        def get_active_overrides(self):
            return []
        def fire_override(self, _id):
            pass

    _orig_db, _orig_avail = LE.db, LE._DB_AVAILABLE
    try:
        LE.db, LE._DB_AVAILABLE = _StubDB(), True
        eng = LE.LearningEngine.__new__(LE.LearningEngine)   # no DB work in __init__
        eng._overrides_cache = []
        # A part already carrying a strong, WRONG answer. The old gate refused to offer the
        # knowledge base against anything ranked at or above an override rule.
        summary = {"manufacturing_writeup": {"parts": [
            {"part_number": "AAA-01M", "normalized_material": "MILD_STEEL",
             "material_source": "solidworks_api"}]}}
        eng.pre_scan(summary)
        part = summary["manufacturing_writeup"]["parts"][0]
        eq(part["normalized_material"], "ALUMINIUM",
           "a person's correction outranks the model and must reach the part")
        ok("knowledge_base" in str(part.get("material_source")),
           f"and be attributed to it (got {part.get('material_source')!r})")
    finally:
        LE.db, LE._DB_AVAILABLE = _orig_db, _orig_avail


def test_late_passes_cannot_clobber_the_assembly_quantity():
    """The PDF passes run late and used to write straight to the record. part_index treated a
    quantity of ONE as an empty slot, so a part the model says there is one of was open to
    replacement by whatever a table happened to say."""
    from source_precedence import apply_field
    p = {"part_number": "01M", "quantity": 1, "quantity_source": "solidworks_api"}
    ok(not apply_field(p, "quantity", 4, "bom_tree"),
       "a PDF BOM reading must not displace the assembly the shop builds from")
    eq(p["quantity"], 1, "a quantity of one is a value, not an empty slot")
    # With nothing recorded, the same write is welcome — it is filling a gap, not a fight.
    q = {"part_number": "02M"}
    ok(apply_field(q, "quantity", 4, "bom_tree"), "an unclaimed quantity may be filled")
    eq(q["quantity_source"], "bom_tree", "and the filler is named")


# ── invariants — the checks that make a wrong answer loud ────────────────────────────
def _job(**over):
    """A job that passes every invariant, so each test can break exactly one thing."""
    job = {
        "final_estimate": {
            "schema": "final_estimate.v2",
            "totals": {"material_gbp": 10.07, "labour_gbp": 52.0, "unit_gbp": 62.07},
            "material_rows": [{"workbook_row": 11, "description": "Pem", "total_value_gbp": 9.64},
                              {"workbook_row": 63, "description": "01M", "total_value_gbp": 0.43}],
            "labour_rows": [{"workbook_row": 41, "operation": "Laser", "total_value_gbp": 22.0},
                            {"workbook_row": 43, "operation": "Fold", "total_value_gbp": 30.0}],
            "adapter_problems": [],
        },
        "workbook_labour": {
            "schema": "workbook_labour_rows.v2",
            "rows": [{"workbook_row": 41, "route_group_id": "rg_a", "wb_operation": "Laser",
                      "engine_operations": ["laser_cutting"], "part_numbers": ["01M"]},
                     {"workbook_row": 43, "route_group_id": "rg_b", "wb_operation": "Fold",
                      "engine_operations": ["folding"], "part_numbers": ["01M"]}],
        },
        "part_estimates": [{"part_number": "01M", "operations": ["laser_cutting", "folding"],
                            "normalized_material": "MILD_STEEL", "material_source": "dxf",
                            "quantity": 2, "quantity_source": "solidworks_api",
                            "geometry_source": "dxf_flat_pattern", "dxf_measured_outline": True,
                            "blank_length_mm": 126.39, "blank_length_mm_source": "dxf",
                            "blank_width_mm": 82.2, "blank_area_mm2": 10389.3}],
    }
    for k, v in over.items():
        job[k] = v
    return job


def test_a_clean_job_passes_every_invariant():
    from invariants import check_job
    r = check_job(_job(), write_back=False)
    ok(r["ok"], f"a consistent job must pass: {[v['code'] for v in r['violations']]}")
    eq(r["blocking"], 0, "no blocking violations on a clean job")


def test_rows_must_sum_to_the_workbook_total():
    """The defect this is built from: material rows summed to GBP 9.64 against the sheet's
    own GBP 10.07 and nothing objected. A snapshot that will not reconcile to its own total
    cannot be exported or quoted from."""
    from invariants import check_job
    j = _job()
    j["final_estimate"]["material_rows"] = [{"workbook_row": 11, "total_value_gbp": 9.64}]
    codes = [v["code"] for v in check_job(j, write_back=False)["violations"]]
    ok("material_rows_do_not_sum_to_total" in codes,
       f"a 43p shortfall must be a blocking violation, got {codes}")
    # An Excel error reads back as null. Summing it as zero manufactures agreement out of
    # missing data — the one thing these checks exist to prevent.
    j2 = _job()
    j2["final_estimate"]["labour_rows"] = [{"workbook_row": 41, "total_value_gbp": 52.0},
                                           {"workbook_row": 43, "total_value_gbp": None}]
    codes2 = [v["code"] for v in check_job(j2, write_back=False)["violations"]]
    ok("labour_rows_incomplete" in codes2,
       f"a row that did not calculate is missing data, not zero: {codes2}")


def test_every_priced_row_must_join_exactly_once():
    from invariants import check_job
    j = _job()
    j["final_estimate"]["labour_rows"].append(
        {"workbook_row": 99, "operation": "Weld", "total_value_gbp": 8.0})
    codes = [v["code"] for v in check_job(j, write_back=False)["violations"]]
    ok("priced_row_without_identity" in codes,
       f"a priced row joining to nothing belongs to no parts: {codes}")
    j2 = _job()
    j2["workbook_labour"]["rows"].append(
        {"workbook_row": 41, "route_group_id": "rg_c", "wb_operation": "Laser"})
    codes2 = [v["code"] for v in check_job(j2, write_back=False)["violations"]]
    ok("priced_row_with_ambiguous_identity" in codes2,
       f"one cost must not be reported against two groups: {codes2}")


def test_a_block_that_could_not_be_read_is_a_failure_not_a_footnote():
    """Returning no rows for a missing header is indistinguishable from a block with
    nothing in it, and the two mean opposite things."""
    from invariants import check_job
    j = _job()
    j["final_estimate"]["adapter_problems"] = [
        {"block": "tube", "code": "header_row_not_found", "message": "template moved"}]
    codes = [v["code"] for v in check_job(j, write_back=False)["violations"]]
    ok("workbook_block_not_read" in codes, f"an unread block must block: {codes}")


def test_measured_geometry_must_actually_be_measured():
    """'Measured' unlocks the credibility gate and the blank-allowance skip. A part claiming
    it with no outline is doing all that on the strength of a matched filename."""
    from invariants import check_job
    j = _job()
    j["part_estimates"][0].update({"blank_length_mm": 0, "blank_width_mm": 0,
                                   "blank_area_mm2": 0})
    codes = [v["code"] for v in check_job(j, write_back=False)["violations"]]
    ok("measured_geometry_without_outline" in codes,
       f"an empty measurement must not pass as measured: {codes}")
    # A matched-but-unmeasured file is an honest state and says so in its own name.
    j2 = _job()
    j2["part_estimates"][0].update({"geometry_source": "dxf_matched_no_geometry",
                                    "dxf_measured_outline": False,
                                    "blank_length_mm": 0, "blank_width_mm": 0,
                                    "blank_area_mm2": 0})
    codes2 = [v["code"] for v in check_job(j2, write_back=False)["violations"]]
    ok("measured_geometry_without_outline" not in codes2,
       "a file that says it measured nothing is honest, not a violation")


def test_an_unknown_schema_is_never_read_as_if_known():
    from invariants import check_job
    j = _job()
    j["final_estimate"]["schema"] = "final_estimate.v9"
    codes = [v["code"] for v in check_job(j, write_back=False)["violations"]]
    ok("unknown_schema" in codes,
       f"a contract whose shape may have moved must not be read anyway: {codes}")


def test_a_job_that_was_never_checked_is_not_a_pass():
    """THE FAILURE THIS ALMOST SHIPPED WITH. If the read-back dies — Excel COM falls over, the
    workbook will not open — there is no final_estimate, so every reconciliation check found
    nothing to complain about and the job came back ok: true. Nothing was wrong because
    nothing was looked at, and that is indistinguishable on a console from a job that
    reconciled. A check that could not run must FAIL CLOSED."""
    from invariants import check_job
    r = check_job({"part_estimates": [{"part_number": "01M"}]}, write_back=False)
    ok(r["unverified"] > 0, "checks with no data to read must report themselves unverified")
    ok(not r["verified"], "and the job as a whole is not verified")
    ok(not r["may_quote_firm"],
       "an unverified job must not be quotable as a firm price, whatever `ok` says")
    codes = [v["code"] for v in r["violations"]]
    ok(any(c.endswith("_not_evaluated") for c in codes), f"named as unevaluated: {codes}")

    # And the clean job must still be firm — fail-closed must not mean fail-always.
    ok(check_job(_job(), write_back=False)["may_quote_firm"],
       "a complete, consistent job is still releasable")


def test_the_quote_says_so_when_the_engine_cannot_stand_behind_it():
    """A gate nothing consumes is a log line. The quote was generated unconditionally and
    never read the invariant record, so a job with failing checks produced a document that
    looked exactly like one that passed."""
    from client_quote_html import _invariant_banner
    eq(_invariant_banner({"invariants": {"may_quote_firm": True}}), "",
       "a job that passes carries no banner")
    for job, why in (
        ({}, "no invariant record at all — the checks did not run"),
        ({"invariants": {"may_quote_firm": False, "violations": [
            {"severity": "blocking", "message": "material rows do not sum to the total"}]}},
         "a blocking failure"),
        ({"invariants": {"may_quote_firm": False, "violations": [
            {"severity": "unverified", "message": "read-back did not run"}]}},
         "an unverified job"),
    ):
        b = _invariant_banner(job)
        ok("PROVISIONAL" in b, f"{why} must be stated on the quote itself")
        ok("firm price" in b, f"{why} must say it is not a firm price")


def test_the_rendered_quote_actually_carries_the_banner():
    """Testing _invariant_banner proves the banner builds, not that the quote uses it.
    Blanking the call site passed every other test in this file — the same gap that let a
    reverted apply_field call site go unnoticed. Assert on the rendered document."""
    from client_quote_html import build_quote_html
    failing = {"estimate_summary": {}, "invariants": {"may_quote_firm": False, "violations": [
        {"severity": "blocking", "message": "material rows do not sum to the total"}]}}
    html = build_quote_html(failing, job_stem="TEST-01")
    ok("PROVISIONAL" in html, "the rendered quote must carry the provisional banner")
    ok("firm price" in html, "and must say in words that it is not a firm price")
    clean = {"estimate_summary": {}, "invariants": {"may_quote_firm": True, "violations": []}}
    ok("PROVISIONAL" not in build_quote_html(clean, job_stem="TEST-02"),
       "a job that passes must not be marked provisional")


def test_same_area_is_not_the_same_blank():
    """A 200 x 25 DXF and a 100 x 50 model flat have identical area. On area alone they
    'agree' — but they nest differently, may need a different stock width, and may not fit
    the same machine. Both SIDES have to agree."""
    from geometry_arbitration import arbitrate_flat
    v = arbitrate_flat(200.0, 25.0, 100.0, 50.0)
    ok(not v["agree"], "equal area with different sides is not agreement")
    ok(v["unreconciled"], "and neither measurement is obviously the broken one")
    # Orientation is a drawing convention, not a fact about the part.
    v = arbitrate_flat(82.2, 126.39, 126.39, 82.2)
    ok(v["agree"], "a transposed export is the same blank and must not be flagged")


def test_a_collapsed_polyline_is_not_a_cut_out():
    """A 100 x 0 closed polyline — a line drawn back on itself, which is what a collapsed or
    duplicated edge looks like — spans 100mm on its long side. Testing the LARGER dimension
    passes it straight through as an aperture the laser pierces."""
    try:
        import ezdxf
    except ImportError:
        print("      (skipped: ezdxf not installed)")
        return
    import tempfile
    from pathlib import Path
    from dxf_reader import extract_flat_pattern_data

    d = ezdxf.new(); d.header["$INSUNITS"] = 4
    msp = d.modelspace()
    L, W = 150.0, 80.0
    for a in [(0, 0, L, 0), (L, 0, L, W), (L, W, 0, W), (0, W, 0, 0)]:
        msp.add_line(a[:2], a[2:], dxfattribs={"layer": "SLD-0"})
    msp.add_circle((40, 40), 4.0, dxfattribs={"layer": "SLD-0"})       # one real hole
    # Long, but with no width at all.
    msp.add_lwpolyline([(20, 60), (120, 60), (120, 60), (20, 60)],
                       close=True, dxfattribs={"layer": "SLD-0"})
    path = os.path.join(tempfile.mkdtemp(), "collapsed.dxf")
    d.saveas(path)

    r = extract_flat_pattern_data(Path(path))
    eq(r.get("estimated_pierce_count"), 2,
       "1 hole plus the outer profile = 2; a zero-width loop is not an aperture")


def test_a_readback_that_found_nothing_still_says_why():
    """The condition was "we read some rows", which throws the record away in the one case it
    exists for: every header moved, no block yields rows, and adapter_problems holds the
    explanation. Discarded, that is indistinguishable from a read-back that never ran."""
    from wep_readback_from_xlsx import should_stamp_final_estimate as f
    ok(f({"labour_rows": [{"workbook_row": 41}], "material_rows": [], "adapter_problems": []}),
       "rows were read — stamp it")
    ok(f({"labour_rows": [], "material_rows": [], "adapter_problems": [
        {"block": "steel", "code": "header_row_not_found"}]}),
       "NO rows but a recorded reason is the case this exists for")
    ok(not f({"labour_rows": [], "material_rows": [], "adapter_problems": []}),
       "nothing read and nothing to report is genuinely empty")
    ok(not f(None), "no read-back at all")


def test_a_route_the_sheet_charged_nothing_for():
    """An unmapped department calculates to zero, reconciles perfectly against the total, and
    gives the work away. Rows at zero are skipped as 'not part of the priced job' — but an
    ACCEPTED route row at zero is the opposite: the engine decided this work happens."""
    from invariants import check_job
    j = _job()
    j["final_estimate"]["labour_rows"] = [
        {"workbook_row": 41, "operation": "Laser", "total_value_gbp": 52.0},
        {"workbook_row": 43, "operation": "Fold", "total_value_gbp": 0.0}]
    codes = [v["code"] for v in check_job(j, write_back=False)["violations"]]
    ok("accepted_route_priced_at_zero" in codes,
       f"work the engine routed but the sheet did not charge for must block: {codes}")


def test_geometry_the_engine_could_not_reconcile_blocks_a_firm_price():
    """arbitrate_flat marks an oversized DXF unreconciled, which was the right call — but a
    review flag alone changed nothing, so the 400x300-against-60x34 case could still leave as
    a firm quote."""
    from invariants import check_job
    j = _job()
    j["part_estimates"][0]["flat_unreconciled"] = True
    j["part_estimates"][0]["flat_arbitration"] = {"unreconciled": True, "reason": "much larger"}
    r = check_job(j, write_back=False)
    ok("geometry_unreconciled" in [v["code"] for v in r["violations"]],
       "an unresolved size disagreement must block")
    ok(not r["may_quote_firm"], "and must stop the price being firm")


def test_the_money_tolerance_does_not_scale_with_the_estimate():
    """A 0.5% relative tolerance passes a GBP 50 error on a GBP 10,000 job. The only
    legitimate slack is Excel's per-row rounding, which scales with ROW COUNT."""
    from invariants import _money_agrees
    ok(not _money_agrees(10000.00, 10050.00, 12), "GBP 50 out on a big job is an error")
    ok(_money_agrees(100.00, 100.03, 12), "twelve rows may each round by half a penny")
    ok(not _money_agrees(100.00, 100.50, 2), "two rows cannot account for 50p")


def test_attribution_is_checked_against_the_precedence_contract():
    """The checker invented its own source-field names, so a correctly attributed job warned
    on every part while thickness attribution went unchecked entirely."""
    from invariants import _source_key_for
    eq(_source_key_for("normalized_material"), "material_source",
       "the contract writes material_source, not normalized_material_source")
    eq(_source_key_for("quantity"), "quantity_source", "quantity")
    eq(_source_key_for("normalized_thickness_mm"), "thickness_source",
       "and thickness is normalized_thickness_mm -> thickness_source")


def test_a_broken_check_reports_that_it_verified_nothing():
    """A checker that throws must not read as a clean pass — that is worse than no check."""
    import invariants
    j = _job()
    r = invariants.check_job({"final_estimate": j["final_estimate"],
                              "workbook_labour": "not a dict at all"}, write_back=False)
    ok(isinstance(r["violations"], list), "a malformed job must not crash the checker")
    ok("checks_run" in r and r["checks_run"], "the checks it ran are reported")


# ── geometry arbitration — the 04M rule, keyed on geometry alone ─────────────────────
def test_an_incomplete_dxf_loses_to_the_model():
    """12120's 04M measured 43.00 x 20.04mm from a DXF whose outer profile was not in the
    file, against a model flat of 60.00 x 34.04mm — a quarter of the area, and it was costed.
    A developed blank cannot be SMALLER than the flat it develops: material is consumed going
    round a bend, never created. So a materially smaller DXF is missing geometry.

    The rule is geometric. It knows nothing about 04M, this job, or any part number."""
    from geometry_arbitration import arbitrate_flat, DXF, NATIVE

    v = arbitrate_flat(43.00, 20.04, 60.00, 34.04)
    eq(v["winner"], NATIVE, "an incomplete DXF must not be costed")
    ok(v["dxf_incomplete"], "and must be named as incomplete, not merely 'different'")
    ok("60" in v["reason"] and "43" in v["reason"], "both measurements quoted in the reason")

    # Two honest measurements of the same blank agree, and the DXF stays authoritative.
    v = arbitrate_flat(126.39, 82.2, 126.4, 82.0)
    eq(v["winner"], DXF, "agreement keeps the direct measurement of the file")
    ok(v["agree"] and not v["unreconciled"], "and is not flagged for review")

    # Larger is also a disagreement, but swapping in the model trades one unverified number
    # for another. Keep the DXF, mark it unreconciled, send it to a human.
    v = arbitrate_flat(400.0, 300.0, 60.0, 34.0)
    eq(v["winner"], DXF, "a too-large DXF is still the only direct measurement of the file")
    ok(v["unreconciled"], "but the two are unreconciled and must reach a person")

    # One-sided evidence is not a conflict, and must not be reported as agreement.
    eq(arbitrate_flat(None, None, 60.0, 34.0)["winner"], NATIVE, "model only")
    eq(arbitrate_flat(60.0, 34.0, None, None)["winner"], DXF, "DXF only")
    ok(not arbitrate_flat(None, None, None, None)["agree"],
       "no measurement at all is not agreement")


def test_degenerate_geometry_is_not_a_pierce():
    """Three ways of drawing the same thing must clear the same bar. A microscopic closed
    polyline is a duplicated vertex, not an aperture; a zero-length line chains into a
    self-loop whose one node has degree two, which is exactly the closed-contour test. Both
    invent pierces the laser is then charged for."""
    try:
        import ezdxf
    except ImportError:
        print("      (skipped: ezdxf not installed)")
        return
    import tempfile
    from pathlib import Path
    from dxf_reader import extract_flat_pattern_data

    d = ezdxf.new(); d.header["$INSUNITS"] = 4
    msp = d.modelspace()
    L, W = 150.0, 80.0
    for a in [(0, 0, L, 0), (L, 0, L, W), (L, W, 0, W), (0, W, 0, 0)]:
        msp.add_line(a[:2], a[2:], dxfattribs={"layer": "SLD-0"})
    msp.add_circle((40, 40), 4.0, dxfattribs={"layer": "SLD-0"})          # one real hole
    # A closed polyline spanning microns — a duplicated vertex from the export.
    msp.add_lwpolyline([(70, 40), (70.002, 40), (70.002, 40.002), (70, 40.002)],
                       close=True, dxfattribs={"layer": "SLD-0"})
    for i in range(4):                                                    # zero-length lines
        msp.add_line((100 + i, 40), (100 + i, 40), dxfattribs={"layer": "SLD-0"})
    path = os.path.join(tempfile.mkdtemp(), "degenerate.dxf")
    d.saveas(path)

    r = extract_flat_pattern_data(Path(path))
    eq(r.get("estimated_pierce_count"), 2,
       "1 real hole plus the outer profile = 2; degenerate loops are not apertures")
    eq(r.get("closed_contour_count"), 2, "and they are not contours either")


def test_the_complete_reader_wins_over_the_inflating_one():
    """The two DXF readers are not interchangeable. The flat reader walks topologically —
    blocks exploded, layers inherited, contours closed. The raw reader never enters a block
    and counts every short closed polyline as a pierce whether or not it is the outer
    profile, so it double-counts. Taking max() unconditionally hands the decision to
    whichever reader is more wrong upward.

    The raw figure is used only where the flat walk ADMITS it is incomplete."""
    from drawing_job_merge import _arbitrate_pierces
    v = _arbitrate_pierces({"estimated_pierce_count": 4, "pierce_count_incomplete": False},
                           {"estimated_pierce_count": 9})
    eq(v["value"], 4, "a complete topological walk is the answer, not a floor to be raised")
    ok(not v["uncertain"], "and it is a measurement, recorded as one")

    # An incomplete walk yields a FLOOR. Taking the larger of two unreliable readings is a
    # choice between guesses, and it must be recorded as a choice — value, source and
    # uncertainty kept apart — not laundered into a confident measured number.
    v = _arbitrate_pierces({"estimated_pierce_count": 4, "pierce_count_incomplete": True},
                           {"estimated_pierce_count": 9})
    eq(v["value"], 9, "where the walk could not close its loops, the larger is the floor")
    ok(v["uncertain"], "but it is NOT a measurement and must not be presented as one")
    ok("floor" in str(v.get("note", "")).lower(), "and says so in words a person can read")

    v = _arbitrate_pierces({"estimated_pierce_count": 0, "pierce_count_incomplete": False},
                           {"estimated_pierce_count": 6})
    eq(v["value"], 6, "a reader that saw nothing at all defers to one that saw something")
    ok(v["uncertain"], "the raw parser's known upward bias makes that figure provisional")
    eq(_arbitrate_pierces({}, {}), None, "no evidence is None, never 0")


def test_zero_cut_outs_is_evidence_not_absence():
    """A cut list reporting ZERO cut-outs has said something definite: a plain blank, one
    outer profile, one pierce — and the model is the strongest source there is. Reading 0 as
    'no data' let a weaker PDF count survive against explicit model evidence, which is the
    silent-overwrite failure running the other way."""
    from source_connectors.solidworks import (normalize_native_extract,
                                              apply_native_to_pre_estimate)
    recs = [{"title": "AAA-01M", "doctype": 1, "route_signals": {
        "material": "Mild Steel [CR4]", "is_sheet_metal": True, "bend_count": 1,
        "flat_length_mm": 100.0, "flat_width_mm": 50.0, "thickness_mm": 1.5,
        "cut_out_count": 0, "bbox_mm": [60.0, 50.0, 20.0]}}]
    job = normalize_native_extract(recs)
    parts = [{"part_number": "AAA-01M",
              "manufacturing_features": {"pierce_count": 5},      # a PDF-derived guess
              "geometry_rollup": {"estimated_pierce_count": 5}}]
    apply_native_to_pre_estimate(parts, job)
    eq((parts[0].get("geometry_rollup") or {}).get("estimated_pierce_count"), 1,
       "no cut-outs means one pierce for the outer profile — not the PDF's 5")
    eq((parts[0].get("manufacturing_features") or {}).get("cut_out_count"), 0,
       "and zero is recorded as a value, not left absent")


def test_route_group_id_is_stable_and_distinguishes_gauges():
    """Row numbers move when the template changes; a group's identity does not. Without a
    stable id, two runs of the same job cannot be compared row for row."""
    from wb_populate import route_group_id
    a = route_group_id("Fold", "Mild Steel", 1.2, ["01M", "06M"])
    b = route_group_id("Fold", "Mild Steel", 1.2, ["06M", "01M"])   # order must not matter
    c = route_group_id("Fold", "Mild Steel", 1.5, ["04M"])
    eq(a, b, "the same group must have the same id whatever order its parts arrive in")
    ok(a != c, "two gauges of the same operation are different groups")
    ok(a.startswith("rg_"), "ids are recognisable on sight")


# ── runner ───────────────────────────────────────────────────────────────────────────
def main() -> int:
    global _COLLECT_ONLY
    _COLLECT_ONLY = True          # collect every failure in a test, don't stop at the first
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
