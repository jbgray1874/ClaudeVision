"""A spot-welded assembly is a weldment: one object in the booth, no separate assemble step,
and no weld dressing (D-373).

12527-22 riser, 08:30 book on 92425cf (£14.01). The weldment 12527-22-101 is spot welded by
its own sheet's symbols (D-371). The route compiler counted only ARC welding as making members
one object — and the part's own spelling, "RISER WELMENT", has no "WELD" in it — so 101 read as
a screwed assembly: its coat went to the two members (P.Coat qty 2, £3.46), and it was given an
Assemble/pack event over 01M and 02M that the spot weld already is. Separately, the M&S
"dress all seen welds" standard chained Dress Welds onto 101 from an arc weld the drawing had
ruled out.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from route_compiler import REQUIRED, compile_job_route  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _member(pn):
    return {"part_number": pn, "description": "PANEL", "quantity": 1,
            "normalized_material": "MILD_STEEL", "normalized_finish": "SEE ASSEMBLY",
            "surface_finishes": ["SEE ASSEMBLY"],
            "textual_operations": ["laser_cutting", "folding"]}


def _route(join_op):
    weldment = {"part_number": "R-101", "description": "RISER WELMENT", "quantity": 1,
                "normalized_material": "MILD_STEEL", "normalized_finish": "POWDER COATED",
                "surface_finishes": ["POWDER COATED"],
                "textual_operations": [join_op, "powder_coating"],
                "operation_sources": {join_op: "drawing_deterministic"},
                # As the live record carried it: the coat is the assembly's own stage.
                "operation_scope": {"powder_coating": "assembly"}}
    ga = {"part_number": "R-GA", "description": "RISER", "quantity": 1,
          "textual_operations": []}
    parts = [ga, weldment, _member("R-01M"), _member("R-02M")]
    extract = {"assemblies": [
        {"part_number": "R-GA", "children": [{"part_number": "R-101", "qty": 1}]},
        {"part_number": "R-101", "children": [
            {"part_number": "R-01M", "qty": 1}, {"part_number": "R-02M", "qty": 1}]}],
        "parts": [], "routes": []}
    return compile_job_route(parts, extract)["decisions"]


def _required(decisions, op):
    return {d["target_id"] for d in decisions
            if d["operation"] == op and d["status"] == REQUIRED}


def test_a_spot_welded_assembly_is_coated_as_one_object():
    ds = _route("spot_welding")
    assert _required(ds, "powder_coating") == {"R-101"}


def test_it_is_coated_the_same_way_an_arc_welded_one_is():
    assert _required(_route("spot_welding"), "powder_coating") == \
        _required(_route("welding"), "powder_coating")


def test_the_spot_weld_is_the_joining_step():
    for op in ("spot_welding", "welding"):
        ds = _route(op)
        joined = {d["target_id"] for d in ds if d["operation"] == "assembly"
                  and d["status"] == REQUIRED and d["target_id"] == "R-101"}
        assert not joined, f"{op}: a separate assemble event on the weldment"


def test_dressing_does_not_follow_a_ruled_out_arc_weld():
    src = open(os.path.join(ROOT, "src", "estimator.py"), encoding="utf-8").read()
    block = src.split("NOT AFTER A WELD THE DRAWING RULED OUT")[1][:900]
    assert '_arc_ruled_out = "welding" in (part.get("operations_ruled_out") or {})' in block
    assert "and not _arc_ruled_out" in block


def test_a_line_another_party_supplies_is_accounted_for():
    """The 08:30 book's only "missing price" was the customer's own ticket, on the sheet at £0."""
    import invariants
    payload = {"product_root": "R-GA", "nodes": [
        {"part_number": "R-GA", "children": [{"part_number": "R-03X"}, {"part_number": "R-01M"}]},
        {"part_number": "R-03X", "kind": "leaf", "children": []},
        {"part_number": "R-01M", "kind": "leaf", "children": []}]}
    pes = [{"part_number": "R-01M", "unit_total_cost_gbp": 1.0},
           {"part_number": "R-03X", "supplied_by_third_party": "OTHERS",
            "costing_basis": "supplied_by_third_party", "unit_total_cost_gbp": 0.0}]
    got = invariants._reached_unaccounted_core(
        {"estimate_summary": {"canonical_route_shadow": payload, "part_estimates": pes}})
    assert "R-03X" not in got["unaccounted"]
    pes[1].pop("supplied_by_third_party"); pes[1].pop("costing_basis")
    got = invariants._reached_unaccounted_core(
        {"estimate_summary": {"canonical_route_shadow": payload, "part_estimates": pes}})
    assert "R-03X" in got["unaccounted"]
