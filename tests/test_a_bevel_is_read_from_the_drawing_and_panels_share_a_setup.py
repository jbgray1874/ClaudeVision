"""A bevel is read from the panel's drawing, and the panels of one board share a set-up (D-670).

12203-65-GA, 3 Nov 2026. Each of the box's five panel flats carries its 45 degree bevel's
inner edge as a second outline 10.8 mm in, and the merge read it as a cut-through: the base
became a 13,465 mm2 frame. Sheet 3/3 of the box prints 45 degrees at the panels' edges.

An inset equal to the board thickness proves nothing on its own: a rebate, a pocket or an
opening can sit there too. So the bevel is taken only where the drawing says so (a printed
angle whose run matches the inset, or the word BEVEL, MITRE or CHAMFER with a 45 degree inset)
AND every line inside the outline runs parallel to an outer edge at that one inset. Otherwise
the frame-or-step question stands, and says what else the inset reads as.

12203-66-GA's 20:48 book charged three CNC Joinery set-ups for three panels of one board,
because the read numbered their cutting 10, 20 and 30. Panels of one material and thickness
on that department share one row and one set-up; a second cut of the same panel does not.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bevel_reading as br                                             # noqa: E402
import test_a_box_exported_as_numbered_parts_is_its_panels as box      # noqa: E402

CODE = box.CODE
SIZES = {n: (a, b) for n, a, b in box.PANELS}


def _sheet_pdf(tmp_path, angles_by_panel, name="sheet3.pdf"):
    """A sheet detailing the five panels, each under its balloon with its own sizes and the
    callouts given for it, laid out like 12203-65-01J's sheet 3/3."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=1190, height=842)
    for n in range(1, 6):
        x, y = 60 + (n - 1) * 225, 120
        page.draw_circle((x, y), 14)
        page.insert_text((x - 4, y + 4), str(n), fontsize=12)
        a, b = SIZES[n]
        page.insert_text((x + 40, y + 40), f"{a:.2f}", fontsize=10)
        page.insert_text((x + 40, y + 160), f"{b:.2f}", fontsize=10)
        for k, txt in enumerate(angles_by_panel.get(n, [])):
            page.insert_text((x + 60, y + 90 + 20 * k), txt, fontsize=10)
    path = tmp_path / name
    doc.save(path)
    return [{"page_number": 3, "source_pdf_path": str(path), "source_page_number": 1}]


def _sheets(monkeypatch, by_code):
    """`by_code` maps a part code to its own sheets: a list of page dicts, or text."""
    import detail_page_geometry as dpg

    def fake(part, summary):
        got = by_code.get(str(part.get("part_number") or ""))
        if got is None:
            return []
        return got if isinstance(got, list) else [{"page_number": 3, "text": got}]
    monkeypatch.setattr(dpg, "own_sheets", fake)


ALL_45 = {1: ["45°"], 2: ["12.45°", "45°"], 3: ["45°"], 4: ["45°"], 5: ["45°"]}


def _base(parts):
    return parts[f"{CODE}-05"]


def _subjects(part):
    return [q.get("subject") for q in part.get("manufacturing_questions") or []]


def test_the_panels_own_45_degrees_and_its_flat_agree_so_it_is_solid(tmp_path, monkeypatch):
    parts, _ = box._merge(tmp_path)
    assert "nested_outline_frame_or_step" in _subjects(_base(parts)), "the run's reading"
    _sheets(monkeypatch, {CODE: _sheet_pdf(tmp_path, ALL_45)})
    taken = br.apply_bevel_readings(list(parts.values()), {})
    base = _base(parts)
    assert f"{CODE}-05" in taken
    assert "nested_outline_frame_or_step" not in _subjects(base)
    assert abs(base["dxf_raw_geometry"]["blank_area_mm2"] - 375 * 270) < 1.0
    assert abs(base["dxf_raw_geometry"]["estimated_cut_length_mm"] - 1290) < 0.5
    edges = base["bevelled_edges"]
    assert edges["angle_deg"] == 45.0 and edges["edges"] == 4
    assert abs(edges["length_mm"] - 1290) < 0.5
    assert edges["sheet_of"] == CODE
    assert "balloon 5" in base["bevel_reading"]["evidence_from"]
    flag = next(f for f in base["review_flags"] if f.startswith("BEVEL, NOT A CUT-OUT"))
    assert "second pass over that length" in flag and "not read for bevels" in flag


def test_every_panel_with_its_own_callout_is_read(tmp_path, monkeypatch):
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: _sheet_pdf(tmp_path, ALL_45)})
    taken = br.apply_bevel_readings(list(parts.values()), {})
    assert sorted(taken) == [f"{CODE}-{n:02d}" for n in range(1, 6)]
    assert not parts[CODE].get("bevel_reading"), "the box itself has no flat"


def test_another_panels_45_degrees_is_not_this_panels_evidence(tmp_path, monkeypatch):
    """The sheet prints 45 degrees, but only in panel 3's detail: the base is not bevelled
    on that evidence, and its question stands."""
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: _sheet_pdf(tmp_path, {3: ["45°"]})})
    taken = br.apply_bevel_readings(list(parts.values()), {})
    assert taken == [f"{CODE}-03"]
    base = _base(parts)
    assert base["bevel_reading"]["taken"] is False
    assert "nested_outline_frame_or_step" in _subjects(base)


def test_a_sheet_with_no_balloons_ties_nothing_to_a_panel(tmp_path, monkeypatch):
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: "45° 45° 45° ALL EDGES MITRED"})
    assert br.apply_bevel_readings(list(parts.values()), {}) == []
    assert "no balloon" in _base(parts)["bevel_reading"]["evidence_from"]


def test_without_the_drawings_word_the_question_stands_and_names_the_bevel(tmp_path,
                                                                          monkeypatch):
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: _sheet_pdf(tmp_path, {})})
    assert br.apply_bevel_readings(list(parts.values()), {}) == []
    base = _base(parts)
    q = next(q for q in base["manufacturing_questions"]
             if q["subject"] == "nested_outline_frame_or_step")
    assert "bevel" in q["assumption"] and "not taken" in q["assumption"]
    assert base["bevel_reading"]["taken"] is False
    assert base["dxf_raw_geometry"]["blank_area_mm2"] < 20000, "the area is not changed"


def test_an_angle_whose_run_does_not_match_the_inset_is_not_a_bevel(tmp_path, monkeypatch):
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: _sheet_pdf(tmp_path, {5: ["12.45°"]})})
    assert br.apply_bevel_readings(list(parts.values()), {}) == []


def _own_flat(tmp_path, name, draw):
    import ezdxf
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 0
    draw(doc.modelspace())
    path = tmp_path / name
    doc.saveas(path)
    return path


def _own(path, pn, long_mm):
    return {"part_number": pn, "normalized_thickness_mm": 10.8, "dxf_source_file": str(path),
            "overall_length_mm": long_mm}


def test_an_inset_that_is_not_the_bevels_run_is_a_rebate_question(tmp_path, monkeypatch):
    """45 degrees printed, but the line inside sits 20 mm in on 10.8 mm board."""
    path = _own_flat(tmp_path, "X-01_PART1_10.8mm LAM MDF.DXF",
                     lambda m: (box._rect(m, 0, 0, 375, 270), box._rect(m, 20, 20, 355, 250)))
    part = _own(path, "X-01", 375.0)
    _sheets(monkeypatch, {"X-01": "45°"})
    got = br.read_bevel(part, {}, {"X-01": part})
    assert got and got["taken"] is False


def test_a_genuine_pocket_beside_the_bevel_keeps_the_panel_as_read(tmp_path, monkeypatch):
    """Bevel lines 10.8 mm in AND a pocket further in: not every inner line is the bevel,
    so nothing is reclassified and the pocket is not turned into solid material."""
    def draw(m):
        box._rect(m, 0, 0, 375, 270)
        box._rect(m, 10.8, 10.8, 364.2, 259.2)
        box._rect(m, 100, 80, 200, 150)
    path = _own_flat(tmp_path, "P-01_PART1_10.8mm LAM MDF.DXF", draw)
    part = _own(path, "P-01", 375.0)
    _sheets(monkeypatch, {"P-01": "45°"})
    got = br.read_bevel(part, {}, {"P-01": part})
    assert got and got["taken"] is False


def test_a_hole_beside_the_bevel_is_not_read_away(tmp_path, monkeypatch):
    def draw(m):
        box._rect(m, 0, 0, 375, 270)
        box._rect(m, 10.8, 10.8, 364.2, 259.2)
        m.add_circle((180, 130), 8)
    path = _own_flat(tmp_path, "H-01_PART1_10.8mm LAM MDF.DXF", draw)
    part = _own(path, "H-01", 375.0)
    _sheets(monkeypatch, {"H-01": "45°"})
    assert br.read_bevel(part, {}, {"H-01": part}) is None


def test_the_front_opening_stays_open_when_its_bevel_is_read(tmp_path, monkeypatch):
    """A U-shaped front: its opening is part of the outline, so the solid area is the U's,
    not the bounding rectangle's."""
    u = [(0, 0), (270, 0), (270, 99.1), (220, 99.1), (220, 40), (50, 40), (50, 99.1), (0, 99.1)]

    def draw(m):
        m.add_lwpolyline(u, close=True)
        m.add_line((10.8, 10.8), (259.2, 10.8))
    path = _own_flat(tmp_path, "U-01_PART4_10.8mm LAM MDF.DXF", draw)
    part = _own(path, "U-01", 270.0)
    _sheets(monkeypatch, {"U-01": "45°"})
    got = br.read_bevel(part, {}, {"U-01": part})
    assert got["taken"] is True and got["edges"] == 1
    assert abs(got["outline_area_mm2"] - (270 * 99.1 - 170 * 59.1)) < 1.0


def test_bevel_lines_on_three_edges_count_three_edges(tmp_path, monkeypatch):
    """A side bevelled on its bottom and both ends, its top edge left square for edging."""
    def draw(m):
        box._rect(m, 0, 0, 375, 177.1)
        m.add_line((10.8, 10.8), (364.2, 10.8))
        m.add_line((10.8, 10.8), (10.8, 177.1))
        m.add_line((364.2, 10.8), (364.2, 177.1))
    path = _own_flat(tmp_path, "Y-01_PART1_10.8mm LAM MDF.DXF", draw)
    part = _own(path, "Y-01", 375.0)
    _sheets(monkeypatch, {"Y-01": "45°"})
    got = br.read_bevel(part, {}, {"Y-01": part})
    assert got["taken"] is True and got["edges"] == 3
    assert abs(got["bevelled_edge_mm"] - (375 + 2 * 177.1)) < 0.5


def test_a_line_inside_that_runs_beside_no_edge_is_not_read(tmp_path):
    path = _own_flat(tmp_path, "Z-01_PART1_10.8mm LAM MDF.DXF",
                     lambda m: (box._rect(m, 0, 0, 300, 200), m.add_line((50, 50), (120, 140))))
    assert br.inner_offsets(path, 300.0) is None


def test_the_drawing_export_is_kept_on_the_box_as_evidence(tmp_path):
    parts, report = box._merge(tmp_path)
    assert [Path(p).name for p in parts[CODE]["dxf_drawing_views"]] == [f"{CODE}.dxf"]
    from costed_facts import DXF_REASON_SENTENCES
    s = DXF_REASON_SENTENCES["unnumbered_view_beside_numbered_pieces"]
    assert "kept as evidence" in s and "not cut geometry" in s


# ── a set-up is shared only across a proven nest of the same machining (D-671) ──────────

def _cnc(decision_id, target, sequence):
    return {"decision_id": decision_id, "operation": "cnc_routing", "target_id": target,
            "participants": [target], "status": "required", "scope": "part",
            "sequence": sequence, "qty_per_unit": 1}


def _groups(decisions, estimates, raw=(), order_qty=1):
    import wb_populate as wbp
    summary = {"estimate_summary": {"canonical_route_shadow": {"nodes": [],
                                                               "decisions": decisions}},
               "manufacturing_writeup": {"parts": list(raw)}}
    return [g for g in wbp.canonical_labour_groups(summary, estimates, order_qty).values()
            if g.get("wb_op") == "CNC Joinery"]


def _panel(code, qty=1, pps=40, sheet=(2800, 2070), thickness=13.8):
    se = {"parts_per_sheet": pps, "candidate_sheet_size_mm": list(sheet)} if pps else {}
    return {"part_number": code, "normalized_material": "MFMDF",
            "normalized_thickness_mm": thickness, "quantity": qty,
            "material_estimate": {"stock_estimate": se}}


THREE = [_cnc("d1", "T-01J", 10), _cnc("d2", "T-02J", 20), _cnc("d3", "T-03J", 30)]


def test_panels_of_one_proven_nest_and_one_machining_share_one_setup():
    rows = _groups(THREE, [_panel("T-01J", 2), _panel("T-02J", 2), _panel("T-03J")])
    assert len(rows) == 3, "a row per panel, as the lasers have"
    assert len({g["laser_nest_id"] for g in rows}) == 1
    assert all(g["laser_nest_proven"] for g in rows)
    ev = rows[0]["laser_nest_evidence"]
    assert "of one" in ev and "same machining" in ev and "not read" in ev, ev


def test_same_material_and_thickness_alone_prove_nothing():
    """No nest result: each row keeps its own set-up, and the record says why."""
    rows = _groups(THREE, [_panel("T-01J", pps=0), _panel("T-02J", pps=0), _panel("T-03J", pps=0)])
    assert len(rows) == 3 and not any(g["laser_nest_proven"] for g in rows)
    assert "no nest result" in rows[0]["laser_nest_evidence"]


def test_a_bevelled_panel_is_not_in_a_square_edged_panels_setup():
    raw = [{"part_number": "T-01J", "bevelled_edges": {"angle_deg": 45.0}},
           {"part_number": "T-02J"}]
    rows = _groups(THREE[:2], [_panel("T-01J"), _panel("T-02J")], raw)
    assert len({g["laser_nest_id"] for g in rows}) == 2
    assert {g["setup_signature"] for g in rows} == {"bevel 45", "outline"}


def test_a_panel_with_an_unanswered_inner_feature_keeps_its_own_setup():
    raw = [{"part_number": "T-01J", "manufacturing_questions": [
        {"subject": "nested_outline_frame_or_step"}]}, {"part_number": "T-02J"}]
    rows = _groups(THREE[:2], [_panel("T-01J"), _panel("T-02J")], raw)
    own = next(g for g in rows if "T-01J" in g["targets"])
    assert own["laser_nest_id"] != next(g for g in rows if "T-02J" in g["targets"])["laser_nest_id"]
    assert "inner feature" in own["laser_nest_evidence"]


def test_a_second_cut_of_the_same_panel_is_its_own_setup():
    rows = _groups([_cnc("d1", "T-01J", 10), _cnc("d2", "T-01J", 50)], [_panel("T-01J")])
    assert len(rows) == 2
    later = next(g for g in rows if "d2" in g["decision_ids"])
    assert "further visit" in later["laser_nest_evidence"]


def test_panels_of_another_thickness_are_another_program():
    rows = _groups(THREE[:2], [_panel("T-01J"), _panel("T-02J", thickness=18.0)])
    assert len({g["laser_nest_id"] for g in rows}) == 2


def test_one_cnc_program_may_run_several_sheets():
    """Loading a further sheet of the same stock is not a full new set-up on the CNC."""
    rows = _groups(THREE, [_panel("T-01J", pps=2), _panel("T-02J", pps=2), _panel("T-03J", pps=2)],
                   order_qty=20)
    assert all(g["laser_nest_proven"] for g in rows)
    assert "one program run on" in rows[0]["laser_nest_evidence"]


def test_the_lasers_keep_the_one_sheet_condition():
    import wb_populate as wbp
    dec = [dict(_cnc("d1", "L-01", 10), operation="laser_cutting"),
           dict(_cnc("d2", "L-02", 20), operation="laser_cutting")]
    est = [dict(_panel("L-01", pps=2), normalized_material="MILD STEEL", normalized_thickness_mm=1.5),
           dict(_panel("L-02", pps=2), normalized_material="MILD STEEL", normalized_thickness_mm=1.5)]
    summary = {"estimate_summary": {"canonical_route_shadow": {"nodes": [], "decisions": dec}}}
    rows = [g for g in wbp.canonical_labour_groups(summary, est, 20).values()
            if str(g.get("wb_op") or "").startswith("Laser")]
    assert rows and not any(g["laser_nest_proven"] for g in rows)


def test_the_parts_detail_sheet_is_read_though_its_record_is_bound_to_another(tmp_path):
    """D-679, 12203-65 at 12:19: 01J's record was bound to sheet 2/3, the exploded view with
    the balloons and no sizes beside them; every panel's 45 degrees is on sheet 3/3, titled
    12203-65-01J and bound to nothing. The reader asks every sheet titled with the part's own
    number, and the balloon and the panel's own size still have to agree."""
    import fitz
    parts, _ = box._merge(tmp_path)
    view = tmp_path / "sheet2.pdf"
    doc = fitz.open()
    page = doc.new_page(width=1190, height=842)
    for n in range(1, 6):
        page.draw_circle((900 + 40 * n, 140), 14)
        page.insert_text((896 + 40 * n, 144), str(n), fontsize=12)
    doc.save(view)
    detail = _sheet_pdf(tmp_path, ALL_45)[0]
    titled = {"title_block": {"drawing_numbers": [CODE]}}
    summary = {"pages": [
        {"page_number": 2, "source_pdf_path": str(view), "source_page_number": 1,
         "page_analysis": titled},
        {**detail, "page_analysis": titled}]}
    parts[CODE]["pages"] = [2]
    taken = br.apply_bevel_readings(list(parts.values()), summary)
    assert sorted(taken) == [f"{CODE}-{n:02d}" for n in range(1, 6)], [
        (p, (parts[p].get("bevel_reading") or {}).get("evidence_from")) for p in parts]
    assert "page 3" in parts[f"{CODE}-05"]["bevel_reading"]["evidence_from"]


def test_a_sheet_titled_with_another_number_is_not_the_parts(tmp_path):
    parts, _ = box._merge(tmp_path)
    detail = _sheet_pdf(tmp_path, ALL_45)[0]
    summary = {"pages": [{**detail, "page_analysis": {
        "title_block": {"drawing_numbers": ["99999-01J"]}}}]}
    parts[CODE]["pages"] = []
    assert br.apply_bevel_readings(list(parts.values()), summary) == []


def test_a_reading_not_taken_is_asked_again_and_a_taken_one_is_not(tmp_path, monkeypatch):
    """D-679: a replay of the 12:19 record carries five 'not taken' readings; the current
    reader asks again. A panel already made solid by a taken reading is left alone."""
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: "nothing printed"})
    assert br.apply_bevel_readings(list(parts.values()), {}) == []
    assert parts[f"{CODE}-05"]["bevel_reading"]["taken"] is False
    _sheets(monkeypatch, {CODE: _sheet_pdf(tmp_path, ALL_45)})
    taken = br.apply_bevel_readings(list(parts.values()), {})
    assert sorted(taken) == [f"{CODE}-{n:02d}" for n in range(1, 6)]
    assert br.apply_bevel_readings(list(parts.values()), {}) == [], "taken once, not twice"


def test_the_pre_costing_passes_read_the_bevel(tmp_path, monkeypatch):
    import file_scan
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: _sheet_pdf(tmp_path, ALL_45)})
    summary = {"manufacturing_writeup": {"parts": list(parts.values())}, "pages": []}
    file_scan.pre_costing_passes(summary)
    assert parts[f"{CODE}-05"]["bevel_reading"]["taken"] is True
