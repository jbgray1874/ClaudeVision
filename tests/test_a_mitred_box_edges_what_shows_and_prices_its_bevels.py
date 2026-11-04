"""A mitred box is edged where its edges show, and its bevels are priced (D-677).

JG, 4 Nov 2026: "we need everything priced." 12203-65-01J's sheet calls out "1mm EDGING" on the
box and draws its five panels joined at 45 degree mitres. No edge is named, so no panel had a
banded length and the edging line was never made; and the bevels were "machining the CNC row
must cover" with no time on any row.

  * A mitred edge is a joint and takes no edging. Where a panel's flat and drawing agree on
    which edges are bevelled, its edging is its outline less those edges. A panel with no
    bevel reading is named as not measured, never guessed.
  * A bevelled edge is a second pass with a bevel tool: its length at the bevel feed, added
    after the minimum run, with a tool set-up. House allowances, said on the line.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config                                                          # noqa: E402
import edge_banding as eb                                              # noqa: E402
import estimator as E                                                  # noqa: E402

BOX = "12999-01J"
SLOPE = 382.8                       # the side's sloping top edge, 375 run over 77 rise


def _piece(n, length, width, perimeter=None, bevelled=None):
    p = {"part_number": f"{BOX}-0{n}", "description": "BOX PANEL", "quantity": 1,
         "normalized_material": "MDF", "normalized_finish": "LAMINATED",
         "normalized_thickness_mm": 10.8, "blank_length_mm": length, "blank_width_mm": width,
         "dxf_minted_piece_of": BOX, "dxf_orphan": True, "dxf_augmented": True,
         "colours": ["SWISS KRONO OAK D4428OV"],
         "normalized_geometry": {"blank_length_mm": length, "blank_width_mm": width,
                                 "estimated_cut_length_mm": perimeter or 2 * (length + width),
                                 "geometry_source": "dxf_flat_pattern"},
         "textual_operations": ["cnc_routing"]}
    if perimeter and bevelled:
        p["bevelled_edges"] = {"angle_deg": 45.0, "run_mm": 10.8, "edges": 3,
                               "length_mm": bevelled, "outline_perimeter_mm": perimeter}
    return p


def _box():
    parent = {"part_number": BOX, "description": "SOFT TEXTILE DISPLAY BOX", "quantity": 1,
              "is_assembly_parent": True, "normalized_material": "MDF",
              "assembly_children": [f"{BOX}-0{n}" for n in range(1, 6)],
              "textual_operations": ["edge_banding"], "notes": ["1mm EDGING"]}
    pieces = [
        _piece(1, 375.0, 177.1, 375 + 177.1 + 100 + SLOPE, 375 + 177.1 + 100),   # side
        _piece(2, 375.0, 177.1),                                               # side, unread
        _piece(3, 270.0, 177.1, 2 * (270 + 177.1), 270 + 2 * 177.1),           # back
        _piece(4, 270.0, 99.1, 270 + 2 * 99.1 + 100 + 2 * 66 + 170, 270 + 2 * 99.1),  # U front
        _piece(5, 375.0, 270.0, 2 * (375 + 270), 2 * (375 + 270)),             # base
    ]
    return parent, pieces


def test_each_mitred_piece_is_edged_on_the_edges_that_show():
    parent, pieces = _box()
    got = eb.stamp_exposed_edges_of_mitred_pieces([parent] + pieces)
    by = {p["part_number"]: p for p in pieces}
    assert by[f"{BOX}-01"]["edging_on_exposed_edges"]["mm"] == SLOPE
    assert by[f"{BOX}-03"]["edging_on_exposed_edges"]["mm"] == 270.0
    assert by[f"{BOX}-04"]["edging_on_exposed_edges"]["mm"] == 402.0, "the U and its tops"
    assert "edging_on_exposed_edges" not in by[f"{BOX}-05"], "every base edge is a joint"
    assert got["not_measured"] == [f"{BOX}-02"], "a piece with no bevel reading is named"
    assert by[f"{BOX}-01"]["edging_on_exposed_edges"]["callout"] == "1MM EDGING"


def test_the_banded_length_says_it_is_derived():
    parent, pieces = _box()
    eb.stamp_exposed_edges_of_mitred_pieces([parent] + pieces)
    got = eb.banded_length_mm(pieces[0])
    assert got["mm"] == SLOPE and got["basis"] == "exposed_edges_beside_mitres"
    assert "mitred joint" in got["evidence"] and "confirm" in got["evidence"]


def test_a_box_whose_sheet_says_nothing_of_edging_gets_no_length():
    parent, pieces = _box()
    parent.pop("notes")
    parent["textual_operations"] = []
    got = eb.stamp_exposed_edges_of_mitred_pieces([parent] + pieces)
    assert got == {"measured": [], "not_measured": []}
    assert eb.banded_length_mm(pieces[0])["mm"] is None


def test_the_edging_line_is_made_from_the_edges_that_show():
    parent, pieces = _box()
    parts = [parent] + pieces
    summary = {"declared_product": BOX, "drawing_number": BOX,
               "manufacturing_writeup": {"parts": parts},
               "document_analysis": {"bom_rows": []}, "llm_full_extract": {}, "pages": []}
    E.estimate_document(parts, summary=summary)
    stub = next((p for p in parts if p.get("_edging_line")), None)
    assert stub is not None, "the edging line must mint"
    assert stub["part_number"] != config.FACED_BOARD_EDGING_CODE, (
        "the config spec is white W1001: a line in another decor never carries its code")
    assert stub["part_number"] == "EDGE-ABS-D4428"
    assert "1 mm ABS edging to match SWISS KRONO OAK D4428OV" in stub["description"]
    assert any(f.startswith("EDGING DECOR NOT IN SDI LIVE") for f in stub["review_flags"])
    assert abs(float(stub["quantity"]) - round((SLOPE + 270 + 402) / 1000, 3)) < 1e-9
    assert stub["_edging_basis"] == ["exposed_edges_beside_mitres"]
    assert stub["_edging_for"] == [f"{BOX}-01", f"{BOX}-03", f"{BOX}-04"]
    flag = next(f for f in stub["review_flags"] if f.startswith("EDGING DERIVED, PROVISIONAL"))
    assert f"NOT MEASURED: {BOX}-02" in flag
    assert any("D4428OV" in f for f in stub["review_flags"]), "the decor is said"


def test_the_edging_is_sdi_lives_row_in_the_drawn_decor_and_thickness(monkeypatch):
    """SDI Live holds oak D4428 OV edging at 35 x 1 mm (EDGE0056) and 23 x 2 mm (EDGE0052);
    the box's sheet calls out 1 mm, so the line is EDGE0056."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_the_drawings_product_reference_prices_the_line import _Conn
    rows = {"D4428": [
        ("EDGE0052", "23 x 2mm ABS Edging to match Swiss Krono Oak Natural D4428 OV", 0.48),
        ("EDGE0056", "35 x 1mm ABS Edging to match Swiss Krono Oak Natural D4428 OV", 0.65),
        ("LAMINATE234", "2600 x 1300mm 0.8mm Laminate Ref Swiss Krono Oak Natural D4428 OV",
         85.75)]}
    monkeypatch.setattr(config, "get_connection", lambda timeout=20: _Conn(rows), raising=False)
    E._SHEET_RATE_CACHE.clear()
    parent, pieces = _box()
    parts = [parent] + pieces
    summary = {"declared_product": BOX, "drawing_number": BOX,
               "manufacturing_writeup": {"parts": parts},
               "document_analysis": {"bom_rows": []}, "llm_full_extract": {}, "pages": []}
    E.estimate_document(parts, summary=summary)
    stub = next(p for p in parts if p.get("_edging_line"))
    assert stub["part_number"] == "EDGE0056", "1 mm called out: not the 2 mm row"
    assert stub["description"].startswith("35 x 1mm ABS Edging to match Swiss Krono Oak")
    assert any(f.startswith("EDGING IN THE DRAWN DECOR: EDGE0056") for f in stub["review_flags"])
    assert not any(f.startswith("EDGING DECOR NOT IN SDI LIVE") for f in stub["review_flags"])
    E._SHEET_RATE_CACHE.clear()


def _cnc(r):
    pe = r.get("process_estimate") or {}
    return (float((pe.get("run_times_min_per_unit") or {}).get("cnc_routing") or 0),
            float((pe.get("setup_times_min") or {}).get("cnc_routing") or 0))


def test_the_bevel_is_a_second_pass_on_the_cnc_row():
    rule = config.LABOUR_RULES["cnc_routing"]
    _parent, pieces = _box()
    base = pieces[4]
    plain = dict(base)
    plain.pop("bevelled_edges")
    run0, set0 = _cnc(E.estimate_part(plain, job_quantity=1))
    r = E.estimate_part(base, job_quantity=1)
    run1, set1 = _cnc(r)
    pass_min = 1290.0 * rule["bevel_sec_per_mm"] / 60.0
    assert abs((run1 - run0) - pass_min) < 0.02, (run0, run1, pass_min)
    assert abs((set1 - set0) - rule["bevel_setup_min"]) < 1e-9
    assert base["bevel_machining"]["length_mm"] == 1290.0
    assert any(f.startswith("BEVEL PRICED ON THE CNC ROW, PROVISIONAL")
               for f in r["review_flags"])


def test_the_boxs_edging_time_follows_its_pieces_metres():
    parent, pieces = _box()
    eb.stamp_exposed_edges_of_mitred_pieces([parent] + pieces)
    tot = parent["edging_on_its_pieces"]
    assert abs(tot["mm"] - (SLOPE + 270 + 402)) < 0.05
    assert tot["not_measured"] == [f"{BOX}-02"]
    r = E.estimate_part(parent, job_quantity=1)
    flags = [f for f in r.get("review_flags") or [] if isinstance(f, str)]
    assert not any("MINIMUM RUN" in f for f in flags)
    rule = config.LABOUR_RULES["edge_banding"]
    want = max(rule["min_run_min"] * 60, tot["mm"] * rule["sec_per_mm_edge"]) / 60
    run = float(((r.get("process_estimate") or {}).get("run_times_min_per_unit") or {})
                .get("edge_banding") or 0)
    assert abs(run - round(want, 2)) < 0.02
    assert any(f.startswith("EDGE BANDING TIMED ON ITS PIECES' SHOWING EDGES") for f in flags)


def test_the_piece_costing_tool_reads_a_costed_record(tmp_path, capsys):
    import json
    sys.path.insert(0, str(ROOT / "tools"))
    import show_piece_costing
    parent, pieces = _box()
    parts = [parent] + pieces
    summary = {"declared_product": BOX, "manufacturing_writeup": {"parts": parts},
               "document_analysis": {"bom_rows": []}, "llm_full_extract": {}, "pages": []}
    summary["estimate_summary"] = E.estimate_document(parts, summary=summary)
    path = tmp_path / "record.json"
    path.write_text(json.dumps(summary, default=str))
    assert show_piece_costing.main([str(path), BOX]) == 0
    out = capsys.readouterr().out
    assert f"== {BOX}: 5 piece(s)" in out and "bevel pass: 1290.0 mm" in out
    assert "== edging line(s): 1" in out and "EDGE-ABS-D4428" in out


def _box_as_the_route_leaves_it():
    """12203-65 at 12:19, replayed: the route compiler moved edge_banding off the box into
    removed_operations (an assembly cannot band), and the reader's quote stays in
    operation_evidence. No note on the record says EDGING."""
    parent, pieces = _box()
    parent.pop("notes")
    parent["textual_operations"] = []
    parent["removed_operations"] = ["edge_banding"]
    parent["operation_evidence"] = {"edge_banding": "1mm EDGING"}
    return parent, pieces


def test_an_edging_moved_off_the_box_still_says_the_box_is_edged():
    parent, pieces = _box_as_the_route_leaves_it()
    got = eb.stamp_exposed_edges_of_mitred_pieces([parent] + pieces)
    assert got["measured"] == [f"{BOX}-01", f"{BOX}-03", f"{BOX}-04"]
    assert pieces[0]["edging_on_exposed_edges"]["callout"] == "1MM EDGING"


def test_the_quoted_thickness_picks_the_1mm_oak_row_not_the_2mm(monkeypatch):
    sys.path.insert(0, str(ROOT / "tests"))
    from test_the_drawings_product_reference_prices_the_line import _Conn
    rows = {"D4428": [
        ("EDGE0052", "23 x 2mm ABS Edging to match Swiss Krono Oak Natural D4428 OV", 0.48),
        ("EDGE0056", "35 x 1mm ABS Edging to match Swiss Krono Oak Natural D4428 OV", 0.65)]}
    monkeypatch.setattr(config, "get_connection", lambda timeout=20: _Conn(rows), raising=False)
    E._SHEET_RATE_CACHE.clear()
    parent, pieces = _box_as_the_route_leaves_it()
    parent.pop("operation_evidence")            # the quote is on the reader's route only
    parts = [parent] + pieces
    summary = {"declared_product": BOX, "manufacturing_writeup": {"parts": parts},
               "document_analysis": {"bom_rows": []}, "pages": [],
               "llm_full_extract": {"routes": [{"operation": "edge_banding",
                                                "part_numbers": [BOX],
                                                "evidence": "1mm EDGING"}]}}
    E.estimate_document(parts, summary=summary)
    stub = next(p for p in parts if p.get("_edging_line"))
    assert stub["part_number"] == "EDGE0056"
    assert pieces[0]["edging_on_exposed_edges"]["callout"] == "1MM EDGING"
    E._SHEET_RATE_CACHE.clear()


def _labour_sheet(rate, setup):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(151, 9, rate)
    ws.cell(151, 12, setup)
    return ws


LB = {"col_throughput": 9, "col_setup": 12}


def test_the_bevel_pass_is_in_the_cnc_rows_charged_cells():
    """D-681: the row charges the department's stated 12/hr for the routing; the bevel pass
    is added to it, and the bevel tool's set-up joins the template's own set-up lookup."""
    import wb_populate as wp
    ws = _labour_sheet(12, "=VLOOKUP(C151,Rates,4,0)")
    g = {"workbook_row": 151, "qty": 1, "parts": [f"{BOX}-05"],
         "bevel_pass_min_by_part": {f"{BOX}-05": 0.86}, "bevel_setup_min": 5.0}
    flags = []
    assert wp.charge_bevel_pass(ws, {"k": g}, LB, flags) == [151]
    want = 1.0 / (1.0 / 12 + 0.86 / 60.0)
    assert abs(ws.cell(151, 9).value - round(want, 4)) < 1e-6
    assert ws.cell(151, 12).value == "=(VLOOKUP(C151,Rates,4,0))+5"
    assert g["bevel_pass_charged"]["rate_before_per_hour"] == 12
    assert any(f.startswith("BEVEL PASS CHARGED on row 151") for f in flags)


def test_a_row_without_a_numeric_rate_says_the_bevel_is_not_charged():
    import wb_populate as wp
    ws = _labour_sheet("=W12", "=VLOOKUP(C151,Rates,4,0)")
    g = {"workbook_row": 151, "qty": 1, "bevel_pass_min_by_part": {f"{BOX}-05": 0.86}}
    flags = []
    assert wp.charge_bevel_pass(ws, {"k": g}, LB, flags) == []
    assert "bevel_pass_charged" not in g
    assert any("bevel pass NOT added to row 151" in f for f in flags)


def test_recovering_the_edging_requirement_adds_no_operation_anywhere():
    """The box's edging is read to measure and buy the edging, not to put edge banding back on
    the box or onto its panels: the route's removal stands, and nothing is charged twice."""
    parent, pieces = _box_as_the_route_leaves_it()
    parts = [parent] + pieces
    summary = {"declared_product": BOX, "manufacturing_writeup": {"parts": parts},
               "document_analysis": {"bom_rows": []}, "pages": [],
               "llm_full_extract": {"routes": [{"operation": "edge_banding",
                                                "part_numbers": [BOX],
                                                "evidence": "1mm EDGING"}]}}
    E.estimate_document(parts, summary=summary)
    assert "edge_banding" not in (parent.get("textual_operations") or [])
    assert "edge_banding" in parent["removed_operations"]
    for p in pieces:
        for key in ("textual_operations", "inferred_operations"):
            assert "edge_banding" not in (p.get(key) or []), (p["part_number"], key)
    flag = next(f for p in parts if p.get("_edging_line") for f in p["review_flags"]
                if f.startswith("EDGING DERIVED"))
    assert "No trim waste is included" in flag
