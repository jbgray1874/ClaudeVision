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
SHEET_3 = ("GRAIN DIRECTION 375.00 45° 10.80 270.00 45° 12.45° 177.10 99.10 "
           "SWISS KRONO OAK D4428OV LAMINATED MDF")


def _sheets(monkeypatch, text_by_code):
    """The parent's own sheet carries `text`; a minted panel has none of its own."""
    import detail_page_geometry as dpg

    def fake(part, summary):
        pn = str(part.get("part_number") or "")
        t = text_by_code.get(pn)
        return [{"page_number": 3, "text": t}] if t is not None else []
    monkeypatch.setattr(dpg, "own_sheets", fake)


def _base(parts):
    return parts[f"{CODE}-05"]


def _subjects(part):
    return [q.get("subject") for q in part.get("manufacturing_questions") or []]


def test_the_sheets_45_degrees_and_the_flat_agree_so_the_panel_is_solid(tmp_path, monkeypatch):
    parts, _ = box._merge(tmp_path)
    assert "nested_outline_frame_or_step" in _subjects(_base(parts)), "the run's reading"
    _sheets(monkeypatch, {CODE: SHEET_3})
    taken = br.apply_bevel_readings(list(parts.values()), {})
    base = _base(parts)
    assert f"{CODE}-05" in taken
    assert "nested_outline_frame_or_step" not in _subjects(base)
    assert abs(base["dxf_raw_geometry"]["blank_area_mm2"] - 375 * 270) < 1.0
    assert abs(base["dxf_raw_geometry"]["estimated_cut_length_mm"] - 1290) < 0.5
    edges = base["bevelled_edges"]
    assert edges["angle_deg"] == 45.0 and edges["edges"] == 4
    assert abs(edges["length_mm"] - 1290) < 0.5
    assert edges["sheet_of"] == CODE, "read off the box's own sheet, which details its panels"
    flag = next(f for f in base["review_flags"] if f.startswith("BEVEL, NOT A CUT-OUT"))
    assert "No bevel rate is configured" in flag and "not read for bevels" in flag


def test_the_reading_is_the_same_for_every_panel_with_inner_lines(tmp_path, monkeypatch):
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: SHEET_3})
    taken = br.apply_bevel_readings(list(parts.values()), {})
    assert sorted(taken) == [f"{CODE}-{n:02d}" for n in range(1, 6)]
    assert not parts[CODE].get("bevel_reading"), "the box itself has no flat"


def test_without_the_drawings_word_the_question_stands_and_names_the_bevel(tmp_path,
                                                                          monkeypatch):
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: "GRAIN DIRECTION 375.00 270.00 LAMINATED MDF"})
    assert br.apply_bevel_readings(list(parts.values()), {}) == []
    base = _base(parts)
    q = next(q for q in base["manufacturing_questions"]
             if q["subject"] == "nested_outline_frame_or_step")
    assert "bevel" in q["assumption"] and "not taken" in q["assumption"]
    assert base["bevel_reading"]["taken"] is False
    assert base["dxf_raw_geometry"]["blank_area_mm2"] < 20000, "the area is not changed"


def test_an_angle_whose_run_does_not_match_the_inset_is_not_a_bevel(tmp_path, monkeypatch):
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: "12.45° SLOPE"})
    assert br.apply_bevel_readings(list(parts.values()), {}) == []


def test_an_inset_that_is_not_the_bevels_run_is_a_rebate_question(tmp_path, monkeypatch):
    """The sheet prints 45 degrees, but the line inside sits 20 mm in on a 10.8 mm board:
    a rebate or a pocket, not that bevel."""
    import ezdxf
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 0
    msp = doc.modelspace()
    box._rect(msp, 0, 0, 375, 270)
    box._rect(msp, 20, 20, 355, 250)
    path = tmp_path / "X-01_PART1_10.8mm LAM MDF.DXF"
    doc.saveas(path)
    part = {"part_number": "X-01", "normalized_thickness_mm": 10.8, "dxf_source_file": str(path),
            "overall_length_mm": 375.0}
    _sheets(monkeypatch, {"X-01": "45°"})
    got = br.read_bevel(part, {}, {"X-01": part})
    assert got and got["taken"] is False


def test_a_mitre_word_with_no_angle_reads_45_degrees_when_the_inset_is_the_thickness(
        tmp_path, monkeypatch):
    parts, _ = box._merge(tmp_path)
    _sheets(monkeypatch, {CODE: "ALL EDGES MITRED"})
    taken = br.apply_bevel_readings(list(parts.values()), {})
    assert f"{CODE}-05" in taken
    assert "MITRED" in _base(parts)["bevelled_edges"]["evidence"]


def test_bevel_lines_on_three_edges_count_three_edges(tmp_path, monkeypatch):
    """A side bevelled on its bottom and both ends, its top edge left square for edging."""
    import ezdxf
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 0
    msp = doc.modelspace()
    box._rect(msp, 0, 0, 375, 177.1)
    msp.add_line((10.8, 10.8), (364.2, 10.8))
    msp.add_line((10.8, 10.8), (10.8, 177.1))
    msp.add_line((364.2, 10.8), (364.2, 177.1))
    path = tmp_path / "Y-01_PART1_10.8mm LAM MDF.DXF"
    doc.saveas(path)
    part = {"part_number": "Y-01", "normalized_thickness_mm": 10.8, "dxf_source_file": str(path),
            "overall_length_mm": 375.0}
    _sheets(monkeypatch, {"Y-01": "45°"})
    got = br.read_bevel(part, {}, {"Y-01": part})
    assert got["taken"] is True and got["edges"] == 3
    assert abs(got["bevelled_edge_mm"] - (375 + 2 * 177.1)) < 0.5


def test_a_line_inside_that_runs_beside_no_edge_is_not_read(tmp_path):
    import ezdxf
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 0
    msp = doc.modelspace()
    box._rect(msp, 0, 0, 300, 200)
    msp.add_line((50, 50), (120, 140))
    path = tmp_path / "Z-01_PART1_10.8mm LAM MDF.DXF"
    doc.saveas(path)
    assert br.inner_offsets(path, 300.0) is None


def test_the_drawing_export_is_kept_on_the_box_as_evidence(tmp_path):
    parts, report = box._merge(tmp_path)
    assert [Path(p).name for p in parts[CODE]["dxf_drawing_views"]] == [f"{CODE}.dxf"]
    from costed_facts import DXF_REASON_SENTENCES
    s = DXF_REASON_SENTENCES["unnumbered_view_beside_numbered_pieces"]
    assert "kept as evidence" in s and "not cut geometry" in s


# ── one board, one program, one set-up ────────────────────────────────────────────────

def _cnc(decision_id, target, sequence):
    return {"decision_id": decision_id, "operation": "cnc_routing", "target_id": target,
            "participants": [target], "status": "required", "scope": "part",
            "sequence": sequence, "qty_per_unit": 1}


def _groups(decisions, estimates):
    import wb_populate as wbp
    summary = {"estimate_summary": {"canonical_route_shadow": {"nodes": [],
                                                               "decisions": decisions}}}
    return [g for g in wbp.canonical_labour_groups(summary, estimates, 1).values()
            if g.get("wb_op") == "CNC Joinery"]


def _panel(code, qty=1):
    return {"part_number": code, "normalized_material": "MFMDF", "normalized_thickness_mm": 13.8,
            "quantity": qty}


def test_three_panels_of_one_board_take_one_cnc_row_and_one_setup():
    rows = _groups([_cnc("d1", "T-01J", 10), _cnc("d2", "T-02J", 20), _cnc("d3", "T-03J", 30)],
                   [_panel("T-01J", 2), _panel("T-02J", 2), _panel("T-03J")])
    assert len(rows) == 1, [g["group_key"] for g in rows]
    assert set(rows[0]["targets"]) == {"T-01J", "T-02J", "T-03J"}
    assert set(rows[0]["decision_ids"]) == {"d1", "d2", "d3"}


def test_a_second_cut_of_the_same_panel_keeps_its_own_row():
    rows = _groups([_cnc("d1", "T-01J", 10), _cnc("d2", "T-01J", 50)], [_panel("T-01J")])
    assert len(rows) == 2


def test_panels_of_another_thickness_are_another_program():
    other = dict(_panel("T-02J"), normalized_thickness_mm=18.0)
    rows = _groups([_cnc("d1", "T-01J", 10), _cnc("d2", "T-02J", 20)], [_panel("T-01J"), other])
    assert len(rows) == 2
