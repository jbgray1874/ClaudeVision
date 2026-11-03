"""A box exported as PART1..PART5 is five panels, not one blank (D-669).

12203-65-GA's 20:57 run: the drawing balloons five panels under the one code 12203-65-01J,
two sloping sides, a back, a cut-out front and a base, and the drawing office exported each as
"12203-65-01J_PART<n>_10.8mm LAM MDF_revA.DXF". The merge knew SDI's two other spellings of a
member number ("_-07_" and "-01J-1") but not this one, so the five flats read as five outlines
of one part: the base (PART5, 375 x 270) was costed as the whole box and PART1..PART4 were set
aside as "a different view of a part whose flat was costed from another export".

Beside them sat "12203-65-01J.dxf", the export of the part's drawing: no piece number and no
stock in its name. Its balloons were read as 26 holes on the box. Beside numbered pieces such
a file is a view of the whole part and is set aside, said, and never costed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import drawing_job_merge as d                                         # noqa: E402

CODE = "12203-65-01J"
# (piece, long, short) as drawn on sheet 3/3; each flat carries its 45 degree bevel line
# 10.8 mm inside its outline, as the SolidWorks export does.
PANELS = [(1, 375.0, 177.1), (2, 375.0, 177.1), (3, 270.0, 177.1), (4, 270.0, 99.1),
          (5, 375.0, 270.0)]


def _rect(msp, x0, y0, x1, y1):
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)),
                 ((x0, y1), (x0, y0))):
        msp.add_line(a, b)


def _pack(tmp_path, with_view=True):
    import ezdxf
    for n, a, b in PANELS:
        doc = ezdxf.new()
        doc.header["$INSUNITS"] = 0          # the real exports carry none: mm from the name
        msp = doc.modelspace()
        _rect(msp, 0, 0, a, b)
        _rect(msp, 10.8, 10.8, a - 10.8, b - 10.8)
        doc.saveas(tmp_path / f"{CODE}_PART{n}_10.8mm LAM MDF_revA.DXF")
    if with_view:
        doc = ezdxf.new()
        msp = doc.modelspace()
        _rect(msp, 0, 0, 1189, 841)
        for i in range(26):
            msp.add_circle((100 + 40 * i, 400), 6 + (i % 4))
        doc.saveas(tmp_path / f"{CODE}.dxf")
    return sorted(p for p in tmp_path.iterdir() if p.suffix.lower() == ".dxf")


def _merge(tmp_path, **kw):
    parts = [{"part_number": CODE, "description": "SOFT TEXTILE DISPLAY BOX", "quantity": 1,
              "normalized_material": "MDF", "normalized_finish": "LAMINATED"}]
    out = d.augment_summary_with_dxf({"manufacturing_writeup": {"parts": parts}, "pages": []},
                                     _pack(tmp_path, **kw), reestimate=False)
    return ({p["part_number"]: p for p in out["manufacturing_writeup"]["parts"]},
            out.get("dxf_augmentation") or {})


def test_the_piece_word_and_its_number_is_a_member_number():
    assert d.member_number_from_filename(Path(f"{CODE}_PART5_10.8mm LAM MDF_revA.DXF")) == "5"
    assert d._member_suffix_of_flat(Path(f"{CODE}_PART5_10.8mm LAM MDF_revA.DXF")) == "5"
    assert d.member_number_from_filename(Path(f"{CODE}_PIECE 2_18mm MDF.DXF")) == "2"
    # Not a piece number: a code spelt with the word itself, a word with no number.
    assert d.member_number_from_filename(Path("PART5_2mm_MS.DXF")) == ""
    assert d.member_number_from_filename(Path(f"{CODE}_PART_10.8mm LAM MDF.DXF")) == ""
    assert d._member_suffix_of_flat(Path(f"{CODE}_10.8mm LAM MDF_revA.DXF")) is None


def test_five_numbered_flats_are_five_panels_each_at_its_own_size(tmp_path):
    parts, report = _merge(tmp_path)
    pieces = {f"{CODE}-{n:02d}": (a, b) for n, a, b in PANELS}
    assert set(pieces) <= set(parts), sorted(parts)
    for code, (a, b) in pieces.items():
        rec = parts[code]
        dims = sorted((float(rec.get("overall_length_mm") or 0),
                       float(rec.get("overall_width_mm") or 0)), reverse=True)
        assert rec["geometry_source"] == "dxf_flat_pattern"
        assert float(rec["normalized_thickness_mm"]) == 10.8
        assert abs(dims[0] - a) < 1.0 and abs(dims[1] - b) < 1.0, (code, dims)
    assert parts[CODE].get("is_assembly_parent") is True, "the box is the assembly of its panels"
    assert not any(a.get("reason") == "distinct_blanks_no_children_in_scope_pick_best"
                   for a in report.get("ambiguous_dxf") or [])


def test_the_two_handed_sides_are_both_costed(tmp_path):
    """PART1 and PART2 share an outline; the numbers keep them two panels."""
    parts, _ = _merge(tmp_path)
    assert f"{CODE}-01" in parts and f"{CODE}-02" in parts


def test_the_parts_own_drawing_export_is_set_aside_not_a_sixth_panel(tmp_path):
    parts, report = _merge(tmp_path)
    assert f"{CODE}-06" not in parts
    assert not any(str(p).endswith("-6") or "-DXF" in str(p) for p in parts)
    skipped = [s for s in report.get("skipped") or []
               if s.get("reason") == "unnumbered_view_beside_numbered_pieces"]
    assert [Path(s["path"]).name for s in skipped] == [f"{CODE}.dxf"]
    assert not parts[CODE].get("hole_sizes_mm"), "its balloons are not the box's holes"


def test_the_report_names_the_set_aside_view():
    from costed_facts import DXF_REASON_SENTENCES
    assert "not costed" in DXF_REASON_SENTENCES["unnumbered_view_beside_numbered_pieces"]


def test_without_the_view_the_five_panels_still_stand(tmp_path):
    parts, _ = _merge(tmp_path, with_view=False)
    assert {f"{CODE}-{n:02d}" for n, _a, _b in PANELS} <= set(parts)


# ── the box's own edging is not lost when the box becomes the assembly of its panels ──────

def _job(op="edge_banding"):
    return {"found": True, "parts": [], "routes": [
        {"operation": op, "part_numbers": [CODE], "evidence": "1mm EDGING", "sequence": 20}]}


def test_edging_called_out_on_the_box_stays_on_the_box(tmp_path):
    from source_connectors import llm_full_job as lj
    parts, _ = _merge(tmp_path)
    plist = list(parts.values())
    lj.apply_full_job_to_pre_estimate(plist, _job())
    box = parts[CODE]
    assert "edge_banding" in (box.get("textual_operations") or [])
    assert any("kept on" in f and "no piece carries it" in f for f in box["review_flags"])


def test_cutting_called_out_on_the_box_is_still_its_pieces(tmp_path):
    from source_connectors import llm_full_job as lj
    parts, _ = _merge(tmp_path)
    lj.apply_full_job_to_pre_estimate(list(parts.values()), _job("cnc_routing"))
    assert "cnc_routing" not in (parts[CODE].get("textual_operations") or [])


def test_edging_a_piece_already_carries_is_not_put_on_the_box_too(tmp_path):
    from source_connectors import llm_full_job as lj
    parts, _ = _merge(tmp_path)
    parts[f"{CODE}-01"]["textual_operations"] = ["edge_banding"]
    lj.apply_full_job_to_pre_estimate(list(parts.values()), _job())
    assert "edge_banding" not in (parts[CODE].get("textual_operations") or [])
