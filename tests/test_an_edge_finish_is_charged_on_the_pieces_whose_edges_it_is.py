"""An edge finish is charged on the pieces whose edges it is (JG and the reviewer, 14 Nov 2026).

12424-02-GA, 13 Nov 23:44: "polishing is charged at 9, listing the parent assembly plus its
eight pieces. That needs checking for duplicated work." The insert's own sheet reads FINISH:
POLISHED EDGES. That became Diamond Polish on the insert, timed at 31.7 minutes from 15.9 m of
line work on its assembly drawing: £17.48. Each of its eight acrylic panels was also polished
on its own outline by the acrylic route, as every acrylic part is. An assembly has no edges
apart from its pieces'. The one-level rule (D-446) never looked at polishing, so both stood.

Now, where an assembly and its members both carry an edge finish (config
EDGE_FINISH_OPERATIONS), the members keep it, each on its own outline, whatever the strength
of the evidence on either side. The assembly's statement of the finish is recorded as the
members' evidence. The assembly's row stands down with its reason and is not charged.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc  # noqa: E402


def _part(pn, **over):
    d = {"part_number": pn, "description": pn, "quantity": 1,
         "normalized_material": "ACRYLIC", "thickness_mm": 3.0}
    d.update(over)
    return d


def _panel(pn, qty=1, polished=True):
    ops = ["laser_cutting"] + (["diamond_polish"] if polished else [])
    return _part(pn, quantity=qty, inferred_operations=ops,
                 operation_sources={o: "acrylic_route_rule" for o in ops})


def _insert(*children, op="diamond_polish", evidence="FINISH: POLISHED EDGES"):
    return _part("100-01A", assembly_children=list(children), textual_operations=[op, "glue"],
                 operation_sources={op: "drawing_notes", "glue": "inference"},
                 operation_evidence={op: evidence}, finish="POLISHED EDGES")


def _compile(parts):
    top = _part("100-GA", assembly_children=["100-01A"], inferred_operations=["handling"],
                operation_sources={"handling": "inference"})
    with contextlib.redirect_stdout(io.StringIO()):
        return rc.compile_job_route([top] + list(parts), {})


def _status(graph, op):
    out = {}
    for d in graph["decisions"]:
        d = d if isinstance(d, dict) else d.__dict__
        if d.get("operation") == op:
            out[d.get("target_id")] = d
    return out


def _labour(pn, **costs):
    return {"part_number": pn, "labour_estimate": {"costs_gbp": dict(costs)}}


def test_the_insert_stands_down_and_each_panel_keeps_its_polish():
    graph = _compile([_insert("100-01A-01", "100-01A-02"),
                      _panel("100-01A-01", qty=2), _panel("100-01A-02")])
    polish = _status(graph, "diamond_polish")
    assert polish["100-01A"]["status"] == rc.NOT_APPLICABLE
    assert polish["100-01A-01"]["status"] == polish["100-01A-02"]["status"] == rc.REQUIRED
    assert "edge finish" in polish["100-01A"]["reason"] and "put back" in polish["100-01A"]["reason"]
    # the insert's sheet is the panels' evidence now, said on each
    assert "100-01A" in polish["100-01A-01"]["reason"]
    assert "POLISHED EDGES" in polish["100-01A-01"]["reason"]


def test_the_charged_rows_are_the_panels_only():
    """What the workbook is built from in cutover: the required decisions' priced rows. The
    insert's £17.48 is no longer one of them; it is flagged as a cost the route rules out."""
    graph = _compile([_insert("100-01A-01", "100-01A-02"),
                      _panel("100-01A-01", qty=2), _panel("100-01A-02")])
    priced = rc.project_priced_route(graph, [
        _labour("100-01A", diamond_polish=17.48, glue=14.14),
        _labour("100-01A-01", diamond_polish=5.67, laser_cutting=2.44),
        _labour("100-01A-02", diamond_polish=5.67, laser_cutting=2.48)])
    rows = [r for r in priced["priced_route_rows"] if r.get("operation") == "diamond_polish"]
    assert sorted(r["target_id"] for r in rows) == ["100-01A-01", "100-01A-02"]
    assert sum(r.get("legacy_cost_gbp") or 0 for r in rows) == 11.34
    ruled = [i for i in priced["issues"] if i.get("code") == "forbidden_decision_priced"
             and i.get("operation") == "diamond_polish"]
    assert [(i["part_number"], i["legacy_cost_gbp"]) for i in ruled] == [("100-01A", 17.48)]


def test_an_assembly_whose_pieces_carry_no_polish_keeps_its_own():
    """Contrast: nothing below is polished, so the assembly's stated finish is the only
    charge for it, and it stands."""
    graph = _compile([_insert("100-01A-01", "100-01A-02"),
                      _panel("100-01A-01", polished=False), _panel("100-01A-02", polished=False)])
    assert _status(graph, "diamond_polish")["100-01A"]["status"] == rc.REQUIRED


def test_other_one_level_operations_still_go_by_the_stronger_evidence():
    """Contrast: a stated wet spray on an assembly over an inferred one on its member keeps
    the assembly's (D-446). Only an edge finish is placed on the pieces whatever the evidence."""
    from dataclasses import dataclass, field
    from typing import Any, Dict, List

    @dataclass
    class _Node:
        part_number: str
        kind: str

    @dataclass
    class _Dec:
        operation: str
        status: str
        target_id: str
        source: str
        reason: str = ""
        evidence: str = ""
        field_provenance: Dict[str, str] = field(default_factory=dict)
        claims: List[Dict[str, Any]] = field(default_factory=list)

    graph = {"nodes": [_Node("SA", "assembly"), _Node("P", "part")], "children": {"SA": {"P": 1}}}
    spray_sa = _Dec("wet_spray", rc.REQUIRED, "SA", "drawing_notes")
    spray_p = _Dec("wet_spray", rc.REQUIRED, "P", "inference")
    polish_sa = _Dec("diamond_polish", rc.REQUIRED, "SA", "drawing_notes", evidence="POLISHED EDGES")
    polish_p = _Dec("diamond_polish", rc.REQUIRED, "P", "acrylic_route_rule")
    rc._withhold_duplicate_level_ops([spray_sa, spray_p, polish_sa, polish_p], graph, [])
    assert spray_sa.status == rc.REQUIRED and spray_p.status == rc.NOT_APPLICABLE
    assert polish_sa.status == rc.NOT_APPLICABLE and polish_p.status == rc.REQUIRED


def test_the_edge_finishes_are_a_setting_not_a_list_in_the_rule():
    import config
    assert "diamond_polish" in config.EDGE_FINISH_OPERATIONS
    assert "diamond_polish" not in config.ONE_LEVEL_OPERATIONS
