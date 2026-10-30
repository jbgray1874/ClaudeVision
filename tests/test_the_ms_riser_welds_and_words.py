"""12527-22-GA riser, second pass (D-371): the weld the drawing states by symbol, and three
sentences that contradicted the sheet.

1. Sheet 2 (12527-22-101) carries four ISO 2553 spot-weld callouts — leader, solid reference
   line, dashed identification line, circle centred on the reference line — and no text. The
   book charged Weld (CO2) and Dress Welds and said "no weld note or symbol on the drawing".
2. The gauge decision said the rail was "nested and cut at 0.9 mm" beside a sheet costing 1 mm
   under the shop's 0.9-to-1.0 rule.
3. Packing declined because "no part was measured"; both flats were measured from DXFs.
4. The header read RISER WELMENT: M&S file their sheets "<UPC>_<title>_<number>_REV A", and the
   file-name reader wanted the number first.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import weld_symbols as ws                                  # noqa: E402
import costed_facts as cf                                  # noqa: E402
from product_identity import drawing_of_file, title_from_files  # noqa: E402

WB_SRC = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
FS_SRC = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")


def _line(x0, y0, x1, y1, dash=None):
    return {"x0": min(x0, x1), "x1": max(x0, x1), "top": min(y0, y1), "bottom": max(y0, y1),
            "pts": [(x0, y0), (x1, y1)], "dash": dash}


def _circle(cx, cy, d):
    import math
    pts = [(cx + d / 2 * math.cos(a / 20 * 2 * math.pi), cy + d / 2 * math.sin(a / 20 * 2 * math.pi))
           for a in range(21)]
    return {"x0": cx - d / 2, "x1": cx + d / 2, "top": cy - d / 2, "bottom": cy + d / 2,
            "pts": pts}


def _callout(x, y, with_id=True):
    """The riser's own geometry, in points: reference 15.7 long, id line 2.8 below, leader up."""
    lines = [_line(x, y, x + 15.7, y), _line(x + 15.7, y, x + 25.3, y - 66.3)]
    if with_id:
        lines.append(_line(x, y + 2.8, x + 15.7, y + 2.8, dash=([3.6, 1.8], 2.064)))
    return lines


# ── the reader ───────────────────────────────────────────────────────────────────────────

def test_a_circle_on_the_reference_line_is_a_spot_weld():
    lines = _callout(658.0, 315.1)
    got = ws.read_weld_symbols(lines, [_circle(665.9, 315.1, 4.7)])
    assert [g["kind"] for g in got] == ["spot"]
    assert got[0]["identification_line"] is True


def test_four_callouts_count_four():
    lines, curves = [], []
    for i in range(4):
        lines += _callout(658.0 + 60 * i, 315.1 + 35 * i)
        curves.append(_circle(665.9 + 60 * i, 315.1 + 35 * i, 4.7))
    assert ws.count_by_kind(ws.read_weld_symbols(lines, curves)) == {"spot": 4}


def test_an_aws_callout_without_the_dashed_line_still_reads():
    got = ws.read_weld_symbols(_callout(100, 100, with_id=False), [_circle(107.9, 100, 4.7)])
    assert [g["kind"] for g in got] == ["spot"]


def test_a_line_meeting_a_line_is_not_a_callout():
    """A dimension or a corner: no symbol and no ISO identification line."""
    assert ws.read_weld_symbols(_callout(100, 100, with_id=False), []) == []


def test_a_circle_off_the_line_is_not_a_spot():
    got = ws.read_weld_symbols(_callout(100, 100), [_circle(107.9, 106.0, 4.7)])
    assert [g["kind"] for g in got] == ["unclassified"]


def test_a_triangle_on_the_line_is_a_fillet():
    tri = {"x0": 104, "x1": 110, "top": 94, "bottom": 100,
           "pts": [(104, 100), (110, 100), (104, 94), (104, 100)]}
    got = ws.read_weld_symbols(_callout(100, 100), [tri])
    assert [g["kind"] for g in got] == ["fillet"]


def test_spot_only_ignores_unnamed_callouts_but_not_arc_welds():
    assert ws.only_spot_welds({"spot": 4}) == 4
    assert ws.only_spot_welds({"spot": 4, "unclassified": 3}) == 4
    assert ws.only_spot_welds({"spot": 4, "fillet": 1}) == 0
    assert ws.only_spot_welds({"fillet": 2}) == 0


# ── what it does to the parts ────────────────────────────────────────────────────────────

def _riser():
    return [{"part_number": "12527-22-101", "textual_operations": ["welding", "powder_coating"]},
            {"part_number": "12527-22-01M", "textual_operations": ["laser_cutting", "welding"]},
            {"part_number": "12527-22-02M", "textual_operations": ["laser_cutting", "welding"]},
            {"part_number": "12527-22-03X", "textual_operations": []}]


BY_PART = {"12527-22-101": {"counts": {"spot": 4}, "pages": [2],
                            "text": "12527-22-02MRISER12527-22-01MTICKETRAIL12527-22-101"}}


def test_the_weldment_is_spot_welded_and_the_arc_weld_ruled_out():
    parts = _riser()
    assert ws.apply_to_parts(parts, BY_PART) == ["12527-22-101"]
    w = parts[0]
    assert "spot_welding" in w["textual_operations"] and "welding" not in w["textual_operations"]
    assert w["operation_sources"]["spot_welding"] == "drawing_deterministic"
    assert w["operation_ruling_sources"]["welding"] == "drawing_deterministic"
    assert "4 ISO spot-weld symbol" in w["operations_ruled_out"]["welding"]
    assert w["spot_weld_count"] == 4


def test_the_members_its_sheet_lists_lose_the_arc_weld_and_the_dressing():
    parts = _riser()
    ws.apply_to_parts(parts, BY_PART)
    for m in parts[1:3]:
        assert set(m["operations_ruled_out"]) == {"welding", "dress_welds"}
        assert "joined into 12527-22-101 by spot welds" in m["operations_ruled_out"]["welding"]
    assert "operations_ruled_out" not in parts[3]          # not on the weldment's sheet


def test_a_member_whose_own_sheet_names_an_arc_weld_keeps_it():
    parts = _riser()
    by = dict(BY_PART, **{"12527-22-01M": {"counts": {"fillet": 1}, "pages": [3], "text": ""}})
    ws.apply_to_parts(parts, by)
    assert "operations_ruled_out" not in parts[1]
    assert "welding" in parts[2]["operations_ruled_out"]


def test_a_sheet_with_an_arc_weld_is_left_alone():
    parts = _riser()
    by = {"12527-22-101": {"counts": {"spot": 2, "fillet": 1}, "pages": [2], "text": ""}}
    assert ws.apply_to_parts(parts, by) == []
    assert "welding" in parts[0]["textual_operations"]
    assert parts[0]["weld_symbols"] == {"spot": 2, "fillet": 1}


def test_it_runs_before_any_reader_that_adds_an_operation():
    hook = FS_SRC.index("WELD SYMBOLS ON A PART'S OWN SHEET")
    assert hook < FS_SRC.index("Whole-document LLM extract — DRIVE")


def test_the_engines_own_spot_weld_name_reaches_the_spotweld_row():
    assert '"spot_welding":   "Spotweld"' in WB_SRC


def test_an_assemblys_cut_path_is_not_its_hanging_length():
    import wb_populate as wb
    asm = {"normalized_geometry": {"cut_length_mm": 6168.21}}
    assert wb._part_long_length_mm(asm) is None
    tube = {"material_estimate": {"stock_form": "tube", "cut_length_mm": 845.0}}
    assert wb._part_long_length_mm(tube) == 845.0


# ── the three sentences ──────────────────────────────────────────────────────────────────

def _rail(**extra):
    part = {"part_number": "12527-22-01M", "normalized_thickness_mm": 0.9,
            "_displaced": {"normalized_thickness_mm": [
                {"value": 1.0, "source": "drawing_deterministic", "applied": False}]}}
    part.update(extra)
    return part


def test_without_the_rule_two_gauges_are_still_a_question():
    assert cf.thickness_conflict(_rail()) is not None


def test_the_production_rule_is_not_raised_as_two_readers_disagreeing():
    rule = {"rule_id": "steel_0.9_to_1.0", "drawn_thickness_mm": 0.9,
            "costed_thickness_mm": 1.0}
    assert cf.thickness_conflict(_rail(production_substitution=rule)) is None


def test_a_third_gauge_is_still_raised_against_the_gauge_in_force():
    rule = {"drawn_thickness_mm": 0.9, "costed_thickness_mm": 1.0}
    part = _rail(production_substitution=rule)
    part["_displaced"]["normalized_thickness_mm"].append(
        {"value": 1.5, "source": "dxf", "applied": False})
    got = cf.thickness_conflict(part)
    assert got is not None
    assert "1 mm was kept (production_substitution) against 1.5 mm from dxf" in got["issue"]
    assert "nested and cut at 1 mm" in got["assumption"]


def test_a_measured_flat_under_the_geometry_record_counts_for_packing():
    from commercial_lines import describe_order
    parts = [{"part_number": "12527-22-02M", "normalized_thickness_mm": 1.0,
              "normalized_material": "MILD STEEL",
              "normalized_geometry": {"blank_length_mm": 264.36, "blank_width_mm": 250.0}}]
    out = describe_order(parts, 72)
    assert out["parts_measured"] == 1
    assert out["counted_parts"][0]["length_mm"] == 264.36


def test_an_ms_file_name_names_its_drawing_and_title():
    d = drawing_of_file("0359887_TSE FOOTWEAR RISER_12527-22-GA_REV A.pdf")
    assert (d["number"], d["title"], d["revision"], d["is_assembly"]) == (
        "12527-22-GA", "TSE FOOTWEAR RISER", "A", True)
    assert title_from_files("12527-22-GA", [
        r"\\sdi-dc01\shared\M&S\12527-22\0359887_TSE FOOTWEAR RISER_12527-22-GA_REV A.pdf"
    ]) == "TSE FOOTWEAR RISER"


def test_number_first_names_are_read_as_before():
    assert drawing_of_file("11650-06-GA COFFRET HOSPITAL KIT_REVB.PDF")["title"] == \
        "COFFRET HOSPITAL KIT"
    assert drawing_of_file("12527-22-01M_0.9mm MS_REV A.DXF")["number"] == "12527-22-01M"
    assert drawing_of_file("Quote_000S104206.pdf") == {}
