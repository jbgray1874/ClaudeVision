"""A cut list keeps its lengths, a weldment keeps its joints, a flat is measured along itself,
a stored length is not money, and a laser off the Sheet Steel block keeps its own time
(D-565, D-566, D-567, D-560 amended, D-569).

The gaps an independent review of the 401918-01-GA 13:10 book reproduced from the run's own
record, each a generic rule in the engine and shown here on synthetic fixtures.
"""
from __future__ import annotations

import importlib.util
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bom_pipeline as bp  # noqa: E402
import invariants  # noqa: E402
import route_compiler as rc  # noqa: E402
from part_identity import mint_uncoded_row_identities  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


# ── D-565: a cut list keeps its lengths under any name the column had ───────────────────

def test_a_length_column_is_read_whatever_it_was_called():
    assert bp._row_length_value(703) == 703.0
    assert bp._row_length_value("703") == 703.0
    assert bp._row_length_value("703 mm") == 703.0
    assert bp._row_length_value("") == 0.0 and bp._row_length_value(None) == 0.0
    assert bp._row_length_value("none") == 0.0


def _rows(length_key):
    rows = [{"part_number": "", "description": "50.00 x 20.00 x 2.00mm TUBE", "quantity": 1,
             "bom_parent": "90001-01-07M", "bom_parent_known": True, length_key: 703},
            {"part_number": "", "description": "50.00 x 20.00 x 2.00mm TUBE", "quantity": 2,
             "bom_parent": "90001-01-07M", "bom_parent_known": True, length_key: "154"}]
    mint_uncoded_row_identities(rows)
    return rows


def test_the_vision_readers_cut_length_mm_reaches_the_frames_stock():
    for key in ("length_mm", "cut_length_mm", "length"):
        frame = {"part_number": "90001-01-07M", "description": "BASE FRAME - WELDMENT",
                 "normalized_material": "MILD STEEL", "quantity": 2, "page_roles": ["detail"]}
        assert bp.apply_stated_cut_list_to_parts([frame], _rows(key)) == 1, key
        assert sorted(frame["section_stock"]["cut_lengths_mm"]) == [154.0, 154.0, 703.0], key


def test_the_reconciler_carries_the_length_under_the_one_name_the_applier_reads():
    src = (ROOT / "src" / "bom_pipeline.py").read_text(encoding="utf-8")
    assert 'for _alt in ("cut_length_mm", "length", "cut_length", "piece_length_mm"):' in src
    assert '_row_out["length_mm"] = _lv' in src


# ── D-560 amended: a stored length is not money ─────────────────────────────────────────

def test_a_memberless_parent_with_a_length_but_no_money_still_blocks():
    job = {"parts": [
        {"part_number": "90001-01-401", "is_assembly_parent": True, "assembly_children": ["90001-01-07M"]},
        {"part_number": "90001-01-07M", "description": "BASE FRAME - WELDMENT", "is_assembly_parent": True,
         "section_stock": {"a": 20, "b": 50, "t": 2, "length_mm": 703}, "quantity": 2}]}
    found = invariants.check_a_memberless_assembly_carries_nothing(job)
    assert found and found[0]["code"] == "memberless_assembly_carries_nothing"
    job["parts"][1]["unit_material_cost_gbp"] = 7.9
    assert invariants.check_a_memberless_assembly_carries_nothing(job) == []


# ── D-566: a weldment inside a welded assembly keeps its own joints ─────────────────────

def _frame_in_a_frame():
    parts = [
        {"part_number": "90001-01-GA", "is_assembly_parent": True, "assembly_children": ["90001-01-201"]},
        {"part_number": "90001-01-201", "description": "FRAME - WELDED ASSEMBLY", "is_assembly_parent": True,
         "assembly_children": ["90001-01-03M", "90001-01-02M"], "quantity": 1,
         "textual_operations": ["welding"], "inferred_operations": ["dress_welds"],
         "weld_symbols": {"fillet": 8}},
        {"part_number": "90001-01-03M", "description": "FRAME - WELDMENT", "is_assembly_parent": True,
         "assembly_children": ["90001-01-03M-CL1", "90001-01-03M-CL2"], "quantity": 1,
         "textual_operations": ["welding"], "inferred_operations": ["dress_welds"],
         "weld_symbols": {"fillet": 3}, "weld_stated_by_finish": True},
        {"part_number": "90001-01-03M-CL1", "cut_list_member_of": "90001-01-03M", "normalized_material": "MILD STEEL",
         "section_stock": {"a": 15, "b": 30, "t": 2, "length_mm": 1164}},
        {"part_number": "90001-01-03M-CL2", "cut_list_member_of": "90001-01-03M", "normalized_material": "MILD STEEL",
         "section_stock": {"a": 15, "b": 30, "t": 2, "length_mm": 1294}},
        {"part_number": "90001-01-02M", "description": "END CAP", "normalized_material": "MILD STEEL",
         "quantity": 2, "textual_operations": ["welding"]},
    ]
    job = {"assemblies": [
        {"part_number": "90001-01-GA", "children": [{"part_number": "90001-01-201", "qty": 1}]},
        {"part_number": "90001-01-201", "children": [{"part_number": "90001-01-03M", "qty": 1},
                                                     {"part_number": "90001-01-02M", "qty": 2}]},
        {"part_number": "90001-01-03M", "children": [{"part_number": "90001-01-03M-CL1", "qty": 1},
                                                     {"part_number": "90001-01-03M-CL2", "qty": 1}]}],
        "routes": [{"operation": "welding", "part_numbers": ["90001-01-03M", "90001-01-02M"],
                    "scope": "assembly", "qty_per_unit": 1}]}
    return parts, job


def test_the_inner_weldments_own_joints_are_charged_beside_the_parents():
    parts, job = _frame_in_a_frame()
    out = rc.compile_job_route(parts, job, known_assemblies=["90001-01-GA", "90001-01-201", "90001-01-03M"])
    welds = {d["target_id"] for d in out["decisions"]
             if d["operation"] == "welding" and d["status"] == "required"}
    assert "90001-01-201" in welds and "90001-01-03M" in welds, welds
    dress = {d["target_id"] for d in out["decisions"]
             if d["operation"] == "dress_welds" and d["status"] == "required"}
    assert "90001-01-03M" in dress


def test_a_cap_with_no_joints_of_its_own_claims_no_second_event():
    """The route names the cap, so the cap has the route's one decision; its own WELDED word
    (no symbols, no pieces) adds nothing beside it. The frame, which has both, adds one."""
    parts, job = _frame_in_a_frame()
    out = rc.compile_job_route(parts, job, known_assemblies=["90001-01-GA", "90001-01-201", "90001-01-03M"])
    by_target = {}
    for d in out["decisions"]:
        if d["operation"] == "welding" and d["status"] == "required":
            by_target.setdefault(d["target_id"], []).append(d["source"])
    assert len(by_target.get("90001-01-02M", [])) == 1
    assert "drawing_notes" in by_target.get("90001-01-03M", [])        # the frame's own joints


# ── D-568: correctly nothing is not missing ─────────────────────────────────────────────

def test_a_line_held_at_nothing_by_decision_is_not_an_unpriced_line():
    src = (ROOT / "src" / "estimate_explained.py").read_text(encoding="utf-8")
    body = src.split("def _reads_as_free(row) -> bool:")[1].split("_unpriced = [r for r in bom if _reads_as_free(r)]")[0]
    assert '.get("firmness") or "") == "nil"' in body and "return False" in body


def test_the_predicate_needs_both_own_evidence_and_pieces():
    g = {"children": {"X": {"X-1", "X-2"}}}
    assert rc._weldment_has_its_own_joints({"weld_symbols": {"fillet": 2}}, "X", g) is True
    assert rc._weldment_has_its_own_joints({"weld_symbols": {"fillet": 2}}, "Y", g) is False
    assert rc._weldment_has_its_own_joints({"description": "FRAME - WELDMENT"}, "Y", g) is False
    assert rc._weldment_has_its_own_joints({"weld_stated_by_finish": True,
                                            "section_stock": {"cut_lengths_mm": [703, 154, 154]}}, "Y", g) is True
    assert rc._weldment_has_its_own_joints({"weld_stated_by_note": "WELD", "description": "BASE FRAME - WELDMENT"},
                                           "Y", g) is True


# ── D-567: a flat drawn at an angle is measured along itself ────────────────────────────

def _dxf():
    spec = importlib.util.spec_from_file_location("dxf_reader_impl", ROOT / "src" / "dxf_reader.py.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rect_points(L, W, angle_deg, n=40):
    a = math.radians(angle_deg)
    xs, ys = [], []
    for i in range(n + 1):
        t = i / n
        for (x, y) in ((t * L, 0.0), (t * L, W), (0.0, t * W), (L, t * W)):
            xs.append(x * math.cos(a) - y * math.sin(a))
            ys.append(x * math.sin(a) + y * math.cos(a))
    return xs, ys


def test_a_rotated_strip_measures_as_the_strip_not_its_shadow():
    d = _dxf()
    xs, ys = _rect_points(369.85, 25.0, 23.0)
    axis_l, axis_w = max(xs) - min(xs), max(ys) - min(ys)
    assert axis_l > 340 and axis_w > 140                              # the misleading drawing-axis box
    ln, wd, ang = d._min_area_rect(xs, ys)
    assert abs(ln - 369.85) < 0.05 and abs(wd - 25.0) < 0.05
    assert abs(ang - 23.0) < 0.5 or abs(ang - 113.0) < 0.5


def test_a_square_on_part_is_unchanged():
    d = _dxf()
    xs, ys = _rect_points(250.0, 44.13, 0.0)
    ln, wd, _ = d._min_area_rect(xs, ys)
    assert abs(ln - 250.0) < 1e-6 and abs(wd - 44.13) < 1e-6
    assert d._min_area_rect([0.0, 1.0], [0.0, 1.0]) is None
    src = (ROOT / "src" / "dxf_reader.py.py").read_text(encoding="utf-8")
    assert "_mar[0] * _mar[1] < 0.9 * blank_length * blank_width" in src     # taken only where material
    assert '"axis_aligned_blank_mm": [blank_length, blank_width]' in src


# ── D-569: a laser off the Sheet Steel block keeps the engine's own time ────────────────

def test_a_laser_group_without_a_calculator_row_takes_the_engines_time_not_the_median():
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    own = src.index('elif (wb_op == "Laser (Metal)" and default_tp')
    median = src.index("elif ((wb_op in _ONE_ROW_PER_JOB or wb_op in _PER_PART_OPS) and default_tp")
    assert own < median, "the engine's time must be tried before the department median"
    seg = src[own:median]
    assert '_rate_basis = "engine_time_model"' in seg
    assert "Laser Rate Calculator has no row for it" in seg
