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
    assert "not cut geometry" in DXF_REASON_SENTENCES["unnumbered_view_beside_numbered_pieces"]


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


# ── the panels hang on the box, and the product reaches them (D-674) ───────────────────────
#
# 12203-65-GA's 4 Nov 09:55 run: the five panels were minted and then set aside, "Not linked to
# 12203-65-GA, so not priced". The box lists them as its children and each names the box.

def _product(tmp_path):
    parts, _ = _merge(tmp_path)
    plist = [{"part_number": "12203-65-GA", "description": "SOFT TEXTILE BOX",
              "is_assembly_parent": True, "assembly_children": [CODE]}] + list(parts.values())
    return parts, plist


def test_the_box_names_its_panels_and_each_panel_names_the_box(tmp_path):
    parts, _ = _merge(tmp_path)
    panels = {f"{CODE}-{n:02d}" for n, _a, _b in PANELS}
    assert set(parts[CODE]["assembly_children"]) == panels
    for pn in panels:
        assert parts[pn]["dxf_minted_piece_of"] == CODE
        assert parts[pn]["normalized_finish"] == "LAMINATED", "the box's sheet states its face"
        assert parts[pn]["normalized_finish_inherited_from"] == CODE


def test_the_product_reaches_every_panel_once(tmp_path):
    import route_compiler as rc
    _parts, plist = _product(tmp_path)
    g = rc.build_part_graph(plist, {}, [], known_assemblies=["12203-65-GA"])
    nodes = {n.part_number: n for n in g["nodes"]}
    for n, _a, _b in PANELS:
        pn = f"{CODE}-{n:02d}"
        assert pn in nodes, f"{pn} was set aside"
        assert CODE in nodes[pn].parents
        assert g["quantities"].get(pn) == 1, "one of each panel per box, carried once"
    assert not any(i.get("code") == "not_linked_to_the_product"
                   for i in g.get("issues") or []), g.get("issues")


def test_a_parent_the_extract_states_still_takes_its_panels(tmp_path):
    import route_compiler as rc
    _parts, plist = _product(tmp_path)
    llm = {"assemblies": [{"part_number": "12203-65-GA",
                           "children": [{"part_number": CODE, "qty": 1}]},
                          {"part_number": CODE,
                           "children": [{"part_number": "BUMPERSTOPS", "qty": 4}]}]}
    g = rc.build_part_graph(plist, llm, [], known_assemblies=["12203-65-GA"])
    nodes = {n.part_number: n for n in g["nodes"]}
    assert CODE in nodes[f"{CODE}-05"].parents


# ── only the unit that ships is packed (D-674) ─────────────────────────────────────────────
#
# The 09:55 book charged Packing Joinery twice: on the box 01J ("fitting the bumpers to the
# box", read as an assembly) and on the GA (the top assembly). The box is bench-fitted.

def _decision(did, op, target, scope="part", seq=None):
    return {"decision_id": did, "operation": op, "target_id": target, "participants": [target],
            "status": "required", "scope": scope, "sequence": seq, "qty_per_unit": 1}


def _joinery_groups(decisions, top=("12203-65-GA",)):
    import wb_populate as wbp
    payload = {"nodes": [], "decisions": decisions, "top_assemblies": list(top),
               "top_assembly": top[0] if top else ""}
    est = [{"part_number": pn, "normalized_material": "MDF", "normalized_thickness_mm": 10.8,
            "quantity": 1} for pn in ("12203-65-GA", CODE)]
    return list(wbp.canonical_labour_groups(
        {"estimate_summary": {"canonical_route_shadow": payload}}, est, 1).values())


def test_the_box_inside_the_product_is_not_packed_on_its_own():
    groups = _joinery_groups([
        _decision("fit", "assembly", CODE, "assembly", 50),
        _decision("pack", "assembly", "12203-65-GA", "assembly", 90),
        _decision("b1", "bench_work", CODE), _decision("b2", "bench_work", "12203-65-GA")])
    packs = [g for g in groups if g["wb_op"] == "Packing Joinery"]
    assert [g["decision_ids"] for g in packs] == [["pack"]], "packed once, as the GA"
    bench = [g for g in groups if g["wb_op"] == "Bench Work Joinery"]
    assert any("fit" in g["decision_ids"] for g in bench), "the fitting is the bench's"
    assert any("not a packing of its own" in s for g in bench for s in g.get("fitting_covered", []))


def test_a_sub_assembly_nothing_bench_fits_keeps_its_row():
    groups = _joinery_groups([
        _decision("fit", "assembly", CODE, "assembly", 50),
        _decision("pack", "assembly", "12203-65-GA", "assembly", 90)])
    assert sum(1 for g in groups if g["wb_op"] == "Packing Joinery") == 2, \
        "nothing else charges its fitting, so it is not removed"
