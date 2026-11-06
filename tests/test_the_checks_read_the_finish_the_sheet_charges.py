"""The consistency checks and the finish rules read the record the sheet charges.

12173-02 Card Spinner (M&S), 1 Oct 17:34 book, section 13 "Consistency checks":

  * stated_finish_not_costed said 12173-03-01J / -02J (WET SPRAYED - MATT) were charged
    nothing, beside Wet Spray rows 216 / 217 charging exactly those parts;
  * stated_finish_not_recognised called FINISH: WELDED "a finish this engine has no vocabulary
    for" on five parts every one of which sits on a Weld (CO2) row;
  * 12173-03-01J was nested and cut at 3 mm — the tolerance table's 3 — beside its own flag
    "Thickness left unset; confirm the board gauge";
  * ten "UNOWNED" rows asked who deburrs and wire-forms the weldments whose members' own rows
    charge that work, and the mirrored hand of an unreconciled blank was not counted;
  * twenty operation_charged_on_a_parent_and_its_child rows read "could not be run" for a check
    that ran, pooling one event's participants into "two charges".

And from the estimator's brief: powder on the steel parents only (RAW members, WELDED members
and sheetless mirrored hands are not coated beside them), and the round MDF plate measured as
the circle its DXF draws, sprayed on the one face its sheet names.

Every input below is synthetic and minimal; job facts appear only in these comments.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bought_in_policy                                             # noqa: E402
import costed_facts                                                 # noqa: E402
import engine_discoveries                                           # noqa: E402
import estimator                                                    # noqa: E402
import finish_rules                                                 # noqa: E402
import invariants                                                   # noqa: E402
import route_compiler                                               # noqa: E402
import weld_symbols                                                 # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────────────────
def _job(parts, rows, nodes=()):
    """A finished job: write-up parts, the calculated sheet rows and the accepted rows that
    say which engine operations and parts each sheet row is."""
    return {
        "manufacturing_writeup": {"parts": list(parts)},
        "estimate_summary": {
            "final_estimate": {"labour_rows": [
                {"workbook_row": n, "operation": w, "total_value_gbp": 15.0,
                 "qty_per_unit": 1} for n, w, _ops, _pns in rows]},
            "workbook_labour": {"rows": [
                {"workbook_row": n, "wb_operation": w, "engine_operations": list(ops),
                 "part_numbers": list(pns)} for n, w, ops, pns in rows]},
            "canonical_route_shadow": {"nodes": list(nodes)},
        },
    }


def _codes(out):
    return [v["code"] for v in out]


SPRAY = "Wet Spray", ["wet_spray"]
WELD = "Weld (CO2)", ["welding"]
SPOT = "Spotweld", ["spot_welding"]
PCOAT = "P.Coat", ["powder_coating"]


# ── 3.0: a charged wet spray is not "supplied free" ──────────────────────────────────────
def test_a_charged_spray_is_not_called_free():
    for finish in ("WET SPRAYED - MATT", "LACQUERED"):
        s = _job([{"part_number": "A-01J", "normalized_finish": finish}],
                 [(216, *SPRAY, ["A-01J"])])
        assert _codes(invariants.check_a_stated_finish_is_costed(s)) == [], finish


def test_a_spray_row_on_another_part_does_not_cover_this_one():
    s = _job([{"part_number": "A-01J", "normalized_finish": "WET SPRAYED - MATT"}],
             [(216, *SPRAY, ["B-02J"])])
    assert _codes(invariants.check_a_stated_finish_is_costed(s)) == ["stated_finish_not_costed"]


def test_a_spray_row_with_no_parts_named_is_not_coverage():
    s = _job([{"part_number": "A-01J", "normalized_finish": "WET SPRAYED - MATT"}],
             [(216, *SPRAY, [])])
    assert _codes(invariants.check_a_stated_finish_is_costed(s)) == ["stated_finish_not_costed"]


def test_a_vinyl_beside_a_charged_spray_still_fires():
    s = _job([{"part_number": "A-01J", "normalized_finish": "WET SPRAYED - MATT, VINYL WRAPPED"}],
             [(216, *SPRAY, ["A-01J"])])
    out = invariants.check_a_stated_finish_is_costed(s)
    assert _codes(out) == ["stated_finish_not_costed"]
    assert out[0]["detail"]["parts"][0]["words"] == ["VINYL", "WRAP"]
    # the costable finishes are computed from the departments, so wet spray is named
    assert "wet spray" in out[0]["message"] and "supplied free" in out[0]["message"]


def test_a_spray_row_on_the_assembly_covers_its_member():
    s = _job([{"part_number": "A-01J", "normalized_finish": "WET SPRAYED"}],
             [(216, *SPRAY, ["A-GA"])],
             nodes=[{"part_number": "A-01J", "parents": ["A-GA"]},
                    {"part_number": "A-GA", "parents": []}])
    assert invariants.check_a_stated_finish_is_costed(s) == []


def test_a_recognised_family_the_rows_charge_is_not_unrecognised():
    # VARNISHED is wet spray to the gates but no word in the census's list.
    s = _job([{"part_number": "A-01J", "normalized_finish": "VARNISHED"}],
             [(216, *SPRAY, ["A-01J"])])
    assert invariants.check_a_stated_finish_is_costed(s) == []


def test_a_costable_word_with_no_row_still_skips_the_unknown_bucket():
    s = _job([{"part_number": "A-01M", "normalized_finish": "POWDER COATED"}], [])
    assert invariants.check_a_stated_finish_is_costed(s) == []


def test_charged_finish_families_reads_the_part_join():
    s = _job([], [(216, *SPRAY, ["A-01J"]), (193, *PCOAT, ["A-201"])])
    assert costed_facts.charged_finish_families(s, "A-01J") == {"wet_spray"}
    assert costed_facts.charged_finish_families(s, "A-05M", ["A-201"]) == {"powder"}
    assert costed_facts.charged_finish_families(s, "A-05M") == set()


# ── 3.1: WELDED is how a part is made, not an unknown finish ─────────────────────────────
def test_welded_is_a_weld_not_an_unknown_finish():
    def run(finish, rows):
        return _codes(invariants.check_a_stated_finish_is_costed(
            _job([{"part_number": "F-202", "normalized_finish": finish}], rows)))
    assert run("WELDED", [(180, *WELD, ["F-202"])]) == []
    assert run("WELDED WELDED", [(180, *WELD, ["F-202"])]) == []
    assert run("SPOT WELDED", [(181, *SPOT, ["F-202"])]) == []          # no stray "SPOT"
    assert run("WELDED & POWDER COATED", [(180, *WELD, ["F-202"]),
                                          (193, *PCOAT, ["F-202"])]) == []
    assert run("FINISH: WELDED - MATT", [(180, *WELD, ["F-202"])]) == []


def test_a_weld_on_the_assembly_covers_its_members_statement():
    s = _job([{"part_number": "F-06M", "normalized_finish": "WELDED"}],
             [(180, *WELD, ["F-202"])],
             nodes=[{"part_number": "F-06M", "parents": ["F-202"]}])
    assert invariants.check_a_stated_finish_is_costed(s) == []


def test_a_stated_weld_nobody_charges_is_asked_once():
    s = _job([{"part_number": "F-202", "normalized_finish": "WELDED"}],
             [(193, *PCOAT, ["F-202"])])
    out = invariants.check_a_stated_finish_is_costed(s)
    assert _codes(out) == ["stated_process_not_charged"]
    assert out[0]["severity"] == invariants.WARNING
    # On the part's own op list, check_no_unpriced_operations_named owns the question.
    s2 = _job([{"part_number": "F-202", "normalized_finish": "WELDED",
                "textual_operations": ["welding"]}], [(193, *PCOAT, ["F-202"])])
    assert invariants.check_a_stated_finish_is_costed(s2) == []


def test_the_powder_beside_a_statement_is_still_checked():
    s = _job([{"part_number": "F-202", "normalized_finish": "WELDED & SPRAY PAINTED"}],
             [(180, *WELD, ["F-202"])])
    assert _codes(invariants.check_a_stated_finish_is_costed(s)) == ["stated_finish_not_costed"]


def test_a_bought_welded_mesh_is_not_asked():
    s = _job([{"part_number": "M-04M", "normalized_finish": "WELDED",
               "description": "WELDED MESH PANEL"}], [])
    assert invariants.check_a_stated_finish_is_costed(s) == []


def test_the_weld_reader_shares_the_vocabulary():
    assert weld_symbols._says_welded("FINISH: WELDED")
    assert not weld_symbols._says_welded("WELDMENT")
    assert not weld_symbols._says_welded("SPOT WELDED")      # a Spotweld row discharges it
    hits, rest = finish_rules.process_statements("SPOT WELDED")
    assert set(hits) == {"SPOT WELDED"} and rest == ""


def test_a_finish_field_that_only_states_a_process_states_no_coat():
    assert finish_rules.states_only_a_process("WELDED")
    assert finish_rules.states_only_a_process("FINISH: WELDED - MATT")
    assert not finish_rules.states_only_a_process("WELDED & POWDER COATED")
    assert not finish_rules.states_only_a_process("WELDMENT")
    assert finish_rules.finish_contradiction("powder_coating", "WELDED")
    assert finish_rules.finish_contradiction("powder_coating", "WELDED & POWDER COATED") is None
    assert finish_rules.finish_contradiction("welding", "WELDED") is None
    # the family reader itself is unchanged, so the plating census reads as before
    assert finish_rules.finish_families("WELDED") == set()


def test_the_new_codes_are_the_estimators():
    assert engine_discoveries.classify("stated_process_not_charged") == "estimator"
    assert engine_discoveries.classify(
        "operation_charged_on_a_parent_and_its_child") == "estimator"


# ── 3.3: a board floor is never charged as the gauge ─────────────────────────────────────
def _t(lst, **kw):
    p = {"normalized_material": "MDF", "thicknesses_mm": list(lst), **kw}
    return estimator._safe_thickness_mm(p), p.get("review_flags") or []


def test_a_board_floor_is_never_charged_as_the_gauge():
    v, fl = _t([1.0, 3.0], normalized_thickness_mm=1.0)
    assert v is None
    assert sum("left unset" in f for f in fl) == 1


def test_a_real_board_gauge_beats_table_text_in_any_order():
    assert _t([3.0, 18.0])[0] == 18.0 and _t([18.0, 3.0])[0] == 18.0
    assert _t([1.0, 3.0, 25.0])[0] == 25.0


def test_a_kept_gauge_is_not_called_unset():
    v, fl = _t([1.0, 18.0], normalized_thickness_mm=1.0)
    assert v == 18.0 and not any("left unset" in f for f in fl)


def test_a_lone_three_mm_board_and_metal_are_unchanged():
    assert _t([3.0])[0] == 3.0
    assert estimator._safe_thickness_mm(
        {"normalized_material": "MILD STEEL", "thicknesses_mm": [1.0, 3.0]}) == 1.0


def test_a_dxf_filename_gauge_still_wins():
    assert _t([1.0, 3.0], dxf_source_file="X-1_25mm MDF.DXF")[0] == 25.0


def test_the_gauge_charged_says_which_reading_gave_it():
    p = {"part_number": "B-09J", "description": "PANEL", "normalized_material": "MDF",
         "normalized_thickness_mm": 1.0, "thickness_source": "drawing_deterministic",
         "thicknesses_mm": [1.0, 18.0], "quantity": 1,
         "overall_length_mm": 600, "overall_width_mm": 400}
    e = estimator.estimate_part(p, job_quantity=1)
    assert e["normalized_thickness_mm"] == 18.0
    assert e["thickness_source"] == "thicknesses_mm_list"
    shown = (e.get("_displaced") or {}).get("normalized_thickness_mm") or []
    assert any(d.get("value") == 1.0 and not d.get("applied") for d in shown)


def test_a_board_with_no_gauge_is_not_priced_and_asks_for_the_gauge():
    p = {"part_number": "B-01J", "description": "BASE", "normalized_material": "MDF",
         "normalized_thickness_mm": 1.0, "thickness_source": "drawing_deterministic",
         "thicknesses_mm": [1.0, 3.0], "quantity": 1,
         "overall_length_mm": 630, "overall_width_mm": 630}
    e = estimator.estimate_part(p, job_quantity=1)
    assert e["normalized_thickness_mm"] is None
    assert (e.get("material_estimate") or {}).get("unit_material_cost_gbp") is None
    ds = [d for d in costed_facts.costed_job({"estimate_summary": {"part_estimates": [e]}})
          ["decisions_required"] if d["part"] == "B-01J"]
    assert len(ds) == 1 and ds[0]["kind"] == "missing_price"
    assert ds[0]["action"].startswith("confirm the board gauge")


# ── 3.4: leaf-only work stranded on an assembly, and the mirrored hand's blank ───────────
def test_a_stranded_leaf_op_is_ruled_out_only_where_members_carry_it():
    parts = [{"part_number": "A-201", "quantity": 1, "is_sub_assembly": True,
              "assembly_children": ["A-04M", "A-06M"],
              "operations": ["deburring", "wire_forming", "laser_cutting"],
              "textual_operations": ["edge_banding"]},
             {"part_number": "A-04M", "quantity": 1,
              "textual_operations": ["deburring", "laser_cutting"]},
             {"part_number": "A-06M", "quantity": 1, "textual_operations": ["deburring"]}]
    g = route_compiler.compile_job_route(parts, known_assemblies=["A-201"])
    by = {d["operation"]: d for d in g["decisions"] if d["target_id"] == "A-201"}
    assert by["deburring"]["status"] == "not_applicable"
    assert "A-04M" in by["deburring"]["reason"]
    assert by["wire_forming"]["status"] == "unverified"        # still the one question
    assert by["edge_banding"]["status"] == "required"          # a drawing note, untouched
    assert by["laser_cutting"]["status"] == "not_applicable"   # unchanged


def test_a_member_on_the_robomac_carries_wire_forming():
    parts = [{"part_number": "A-201", "quantity": 1, "is_sub_assembly": True,
              "assembly_children": ["A-06M"], "operations": ["wire_forming"]},
             {"part_number": "A-06M", "quantity": 1, "textual_operations": ["robomac"]}]
    g = route_compiler.compile_job_route(parts, known_assemblies=["A-201"])
    wf = [d for d in g["decisions"] if d["target_id"] == "A-201"
          and d["operation"] == "wire_forming"]
    assert wf and wf[0]["status"] == "not_applicable" and "A-06M" in wf[0]["reason"]


def test_a_mirrored_hand_of_an_unreconciled_blank_is_counted():
    s = {"parts": [
        {"part_number": "P-02M", "flat_unreconciled": True,
         "flat_arbitration": {"unreconciled": True}},
        {"part_number": "P-02M-H",
         "normalized_geometry": {"mirrored_from": "P-02M", "blank_length_mm": 280.97,
                                 "blank_width_mm": 159.24}}]}
    v = [x for x in invariants.check_geometry_is_reconciled(s)
         if x["code"] == "geometry_unreconciled"][0]
    assert v["detail"]["count"] == 2
    assert "P-02M" in v["detail"]["parts"][1]["reason"]


# ── 3.5: an overlap is two events, it is asked, and it is not "could not be run" ─────────
def _shadow_job(decs, issues=(), extra_parts=()):
    parts = [{"part_number": "P", "assembly_children": ["C"]},
             {"part_number": "C", "assembly_children": ["L1", "L2"]}, *extra_parts]
    return {"manufacturing_writeup": {"parts": parts},
            "canonical_route_shadow": {
                "decisions": list(decs), "issues": list(issues),
                "priced_route_rows": [{"decision_id": d["decision_id"]} for d in decs]}}


_chk = invariants.check_an_operation_is_not_charged_on_a_parent_and_its_child


def test_one_event_with_its_members_is_not_two_charges():
    assert _chk(_shadow_job([
        {"decision_id": "d2", "operation": "welding", "status": "required",
         "target_id": "C", "participants": ["C", "L1", "L2"]}])) == []


def test_nested_assembly_events_are_levels():
    assert _chk(_shadow_job([
        {"decision_id": "a1", "operation": "assembly", "status": "required",
         "target_id": "P", "participants": ["C"]},
        {"decision_id": "a2", "operation": "assembly", "status": "required",
         "target_id": "C", "participants": ["L1"]}])) == []


def test_a_coat_on_a_parent_and_its_child_still_fires_with_its_own_ids():
    v = _chk(_shadow_job([
        {"decision_id": "x0", "operation": "folding", "status": "required",
         "target_id": "L2", "participants": ["L2"]},
        {"decision_id": "d1", "operation": "powder_coating", "status": "required",
         "target_id": "C", "participants": ["C"]},
        {"decision_id": "d2", "operation": "powder_coating", "status": "required",
         "target_id": "L1", "participants": ["L1"]}]))
    assert len(v) == 1 and v[0]["severity"] == invariants.WARNING
    assert set(v[0]["detail"]["decision_ids"]) == {"d1", "d2"}
    assert v[0]["detail"]["assembly"] == "C" and v[0]["detail"]["descendants"] == ["L1"]


def test_the_nearest_charged_ancestor_is_the_question():
    v = _chk(_shadow_job([
        {"decision_id": "w0", "operation": "welding", "status": "required",
         "target_id": "P", "participants": ["P", "C"]},
        {"decision_id": "w1", "operation": "welding", "status": "required",
         "target_id": "C", "participants": ["C"]},
        {"decision_id": "w2", "operation": "welding", "status": "required",
         "target_id": "L1", "participants": ["L1"]}]))
    pairs = {(x["detail"]["assembly"], tuple(x["detail"]["descendants"])) for x in v}
    assert pairs == {("P", ("C",)), ("C", ("L1",))}         # never P-and-L1 on top


def test_two_drawn_welds_are_settled_by_the_drawings():
    assert _chk(_shadow_job([
        {"decision_id": "w0", "operation": "welding", "status": "required",
         "target_id": "P", "participants": ["P", "C"]},
        {"decision_id": "w1", "operation": "welding", "status": "required",
         "target_id": "C", "participants": ["C"],
         "field_provenance": {"review": "joining_on_assembly_and_member_both_drawn"}}])) == []


def test_an_overlap_is_a_warning_not_could_not_be_run():
    s = _shadow_job([
        {"decision_id": "d1", "operation": "powder_coating", "status": "required",
         "target_id": "C", "participants": ["C"]},
        {"decision_id": "d2", "operation": "powder_coating", "status": "required",
         "target_id": "L1", "participants": ["L1"]}])
    res = invariants.check_job(s, write_back=False)
    mine = [x for x in res["violations"]
            if x["code"] == "operation_charged_on_a_parent_and_its_child"]
    assert mine and all(x["severity"] == invariants.WARNING for x in mine)


def test_an_unasked_overlap_becomes_one_decision():
    s = _shadow_job([
        {"decision_id": "d1", "operation": "powder_coating", "status": "required",
         "target_id": "C", "participants": ["C"]},
        {"decision_id": "d2", "operation": "powder_coating", "status": "required",
         "target_id": "L1", "participants": ["L1"]}])
    ds = [d for d in costed_facts.costed_job(s)["decisions_required"]
          if "powder coating is charged on C" in str(d.get("issue"))]
    assert len(ds) == 1 and ds[0]["kind"] == "manufacturing_decision"
    assert "d1" in ds[0]["assumption"] and "d2" in ds[0]["assumption"]


def test_a_joining_overlap_becomes_one_decision_whatever_ops_it_names():
    s = _shadow_job([
        {"decision_id": "w1", "operation": "welding", "status": "required",
         "target_id": "C", "participants": ["C", "L1"]},
        {"decision_id": "w2", "operation": "welding", "status": "required",
         "target_id": "L1", "participants": ["L1"]}],
        issues=[{"code": "joining_charged_on_assembly_and_member", "assembly": "C",
                 "member": "L1", "operation": "welding"},
                {"code": "joining_charged_on_assembly_and_member", "assembly": "C",
                 "member": "L1", "operation": "dress_welds"}])
    ds = [d for d in costed_facts.costed_job(s)["decisions_required"]
          if str(d.get("part")) == "L1" or "on C" in str(d.get("issue"))]
    assert len(ds) == 1, ds
    assert "again on its member L1" in ds[0]["issue"]
    # and the invariant names it as asked by the compiler's question
    v = _chk(s)
    assert v and v[0]["detail"]["asked_by"] == "joining_charged_on_assembly_and_member"


def test_no_tree_no_opinion():
    assert costed_facts.parent_child_overlaps({"canonical_route_shadow": {"decisions": [
        {"operation": "P.Coat", "participants": ["A", "B"]}]}}) is None


# ── 3.2: the numbered layers' parent, and the edging its own parts list states ───────────
def test_two_numbered_layers_make_their_base_a_parent(tmp_path):
    import ezdxf
    import drawing_job_merge as djm
    for n in ("90001-03-01J-1_25mm MDF_revA.DXF", "90001-03-01J-2_25mm MDF_revA.DXF"):
        doc = ezdxf.new()
        doc.modelspace().add_lwpolyline([(0, 0), (626, 0), (626, 626), (0, 626)], close=True)
        doc.saveas(tmp_path / n)
    parts = [{"part_number": k, "description": "X", "quantity": 1}
             for k in ("90001-03-01J", "90001-03-201")]
    out = djm.augment_summary_with_dxf({"manufacturing_writeup": {"parts": parts},
                                        "pages": []}, sorted(tmp_path.glob("*.DXF")),
                                       reestimate=False)
    got = {p["part_number"]: p for p in out["manufacturing_writeup"]["parts"]}
    assert got["90001-03-01J"].get("is_assembly_parent") is True
    assert not got["90001-03-201"].get("geometry_source")


def test_a_stated_edging_on_an_assembly_survives_the_leaf_strip_and_is_asked():
    p = {"part_number": "B-01J", "is_assembly_parent": True,
         "textual_operations": ["cnc_routing", "edge_banding"],
         "stated_banded_length_mm": 1979.0}
    assert bought_in_policy.strip_leaf_operations(p) == ["cnc_routing"]
    assert p["textual_operations"] == ["edge_banding"]
    qs = p.get("manufacturing_questions") or []
    assert len(qs) == 1 and "1979" in qs[0]["issue"]
    assert qs[0]["charged_operations"] == ["edge_banding"]
    # without a stated length the strip is unchanged
    q = {"part_number": "B-02", "is_assembly_parent": True, "textual_operations": ["edge_banding"]}
    assert bought_in_policy.strip_leaf_operations(q) == ["edge_banding"]


# ── brief: powder on the parents whose own sheets state it ───────────────────────────────
def _pocket():
    return [
        {"part_number": "90001-04-201", "quantity": 1, "is_sub_assembly": True,
         "assembly_children": ["90001-04-01M", "90001-04-02M", "90001-04-02M-H"],
         "normalized_finish": "POWDER COATED - MATT", "description": "POCKET WELDMENT",
         "textual_operations": ["powder_coating", "welding"]},
        {"part_number": "90001-04-01M", "quantity": 1, "normalized_finish": "WELDED",
         "textual_operations": ["powder_coating", "welding"]},
        {"part_number": "90001-04-02M", "quantity": 1, "normalized_finish": "RAW",
         "textual_operations": ["powder_coating", "folding"]},
        {"part_number": "90001-04-02M-H", "quantity": 1,
         "textual_operations": ["powder_coating", "folding"]},
    ]


def test_the_parent_is_coated_and_its_raw_welded_and_handed_members_are_not():
    g = route_compiler.compile_job_route(_pocket(), known_assemblies=["90001-04-201"])
    pw = {d["target_id"]: d for d in g["decisions"] if d["operation"] == "powder_coating"}
    assert pw["90001-04-201"]["status"] == "required"
    for member in ("90001-04-01M", "90001-04-02M", "90001-04-02M-H"):
        assert pw[member]["status"] == "not_applicable", member
    # the hand says whose sheet ruled it
    assert "90001-04-02M's sheet" in pw["90001-04-02M-H"]["reason"]
    assert not [i for i in g["issues"] if i.get("code") == "powder_scope_mixed_members"]


def test_a_hand_takes_no_finish_its_base_does_not_state():
    recs = {"Q-02M": {"part_number": "Q-02M", "normalized_finish": "RAW"},
            "Q-03M": {"part_number": "Q-03M"}}
    assert finish_rules.own_or_mirror_finish({"part_number": "Q-02M-H"}, recs.get) == "RAW"
    assert finish_rules.own_or_mirror_finish({"part_number": "Q-03M-H"}, recs.get) == ""
    # a hand that states its own finish keeps it
    assert finish_rules.own_or_mirror_finish(
        {"part_number": "Q-02M-H", "normalized_finish": "POWDER COATED"},
        recs.get) == "POWDER COATED"


def test_a_bought_stock_product_keeps_only_a_coat_its_own_sheet_states():
    mesh = {"part_number": "M-04M", "description": "WELDED MESH PANEL",
            "normalized_finish": "WELDED"}
    assert not bought_in_policy.keeps_its_coat(mesh, "powder_coating")
    mesh["normalized_finish"] = "POWDER COATED"
    assert bought_in_policy.keeps_its_coat(mesh, "powder_coating")


def test_the_coat_scope_decision_names_what_the_row_charges_of_its_scope():
    s = {"estimate_summary": {
        "canonical_route_shadow": {"issues": [
            {"code": "powder_scope_mixed_members", "part_number": "K-201",
             "coated_members": ["K-02M-H"], "uncoated_members": ["K-02M"],
             "message": "powder is required on K-201 AND on K-02M-H"}]},
        "workbook_labour": {"rows": [
            {"workbook_row": 193, "wb_operation": "P.Coat",
             "engine_operations": ["powder_coating"],
             "part_numbers": ["K-201", "K-02M-H", "Z-101", "Z-201"]}]}}}
    d = next(d for d in costed_facts.costed_job(s)["decisions_required"]
             if d["part"] == "K-201")
    head, _, rest = d["assumption"].partition("(")
    assert "193" in head and "K-201" in head and "K-02M-H" in head
    assert "Z-101" not in head and "Z-101" in rest   # the row's other parts, not the scope


# ── brief: the round board is measured as its circle, sprayed on its stated face ─────────
def _disc_dxf(path, insert=True):
    import ezdxf
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    if insert:
        blk = doc.blocks.new("PART")
        blk.add_circle((0, 0), 278.0, dxfattribs={"layer": "0"})
        for x, y in ((100, 0), (-100, 0), (0, 100), (0, -100)):
            blk.add_circle((x, y), 3.0, dxfattribs={"layer": "0"})
        doc.modelspace().add_blockref("PART", (300, 300), dxfattribs={"layer": "0"})
    else:
        doc.modelspace().add_circle((0, 0), 278.0, dxfattribs={"layer": "0"})
    doc.saveas(path)
    return path


def test_a_disc_in_a_block_is_measured_as_its_circle(tmp_path):
    import dxf_reader
    f = _disc_dxf(tmp_path / "D-02J_18mm MDF_revA.DXF")
    d = dxf_reader.extract_flat_pattern_data(f)
    assert d["flat_pattern_detected"] is True
    assert (d["blank_length_mm"], d["blank_width_mm"]) == (556.0, 556.0)   # what it nests in
    assert abs(d["perimeter_mm"] - math.pi * 556.0) < 0.05                 # the edge it has
    holes = 4 * math.pi * 3.0 ** 2
    assert abs(d["blank_area_mm2"] - (math.pi * 278.0 ** 2 - holes)) < 1.0
    assert d["hole_count"] == 4                     # the rim is not a hole
    assert d["outline_shape"] == "circle" and d["outline_diameter_mm"] == 556.0


def test_a_square_plate_is_not_read_as_a_disc(tmp_path):
    import dxf_reader
    import ezdxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)], close=True)
    msp.add_circle((50, 50), 5.0)
    doc.saveas(tmp_path / "S-01M_2mm MS.DXF")
    d = dxf_reader.extract_flat_pattern_data(tmp_path / "S-01M_2mm MS.DXF")
    assert not d.get("outline_shape") and d["hole_count"] == 1


def test_the_disc_reaches_the_part_and_the_finish_and_edge_follow_it(tmp_path):
    import drawing_job_merge as djm
    import edge_banding
    _disc_dxf(tmp_path / "90001-03-02J_18mm MDF_revA.DXF")
    parts = [{"part_number": "90001-03-02J", "description": "PLATE", "quantity": 1}]
    out = djm.augment_summary_with_dxf({"manufacturing_writeup": {"parts": parts},
                                        "pages": []}, sorted(tmp_path.glob("*.DXF")),
                                       reestimate=False)
    p = out["manufacturing_writeup"]["parts"][0]
    ng = p["normalized_geometry"]
    assert p["geometry_source"] == "dxf_flat_pattern"
    assert ng["outline_shape"] == "circle" and ng["outline_diameter_mm"] == 556.0
    # the drawn edge is the circumference, not the square's perimeter
    assert abs(edge_banding.banded_length_mm(p)["drawn_perimeter_mm"]
               - round(math.pi * 556.0, 1)) < 0.05
    # the sprayed face is the circle, and a note naming one face sprays one face
    both, det = estimator._powder_coated_area_m2(p, 556.0, 556.0)
    assert abs(both - 2 * math.pi * 0.278 ** 2) < 1e-4 and det["coated_face_shape"] == "circle"
    p["process_notes"] = ["PAINTED TOP FACE"]
    one, det1 = estimator._powder_coated_area_m2(p, 556.0, 556.0)
    assert abs(one - math.pi * 0.278 ** 2) < 1e-4
    assert det1["coated_faces_reason"] == "finish_note_names_one_face"


def test_a_face_note_is_read_only_when_it_names_one_face():
    assert finish_rules.names_one_face("PAINTED TOP FACE")
    assert finish_rules.names_one_face("TOP FACE ONLY")
    assert not finish_rules.names_one_face("PAINTED FACES/AREA")
    assert not finish_rules.names_one_face("SLOTTED FACE")
    import extractor_patterns
    notes = extractor_patterns.extract_process_notes("PAINTED TOP FACE")
    assert any("PAINTED TOP FACE" in n.upper() for n in notes["note_snippets"])
    assert "finish_one_face" not in notes["operations_from_notes"]
