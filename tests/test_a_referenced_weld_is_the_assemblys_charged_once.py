"""A weld the assembly's own sheet references is charged at the assembly, once (D-759).

JG, 9 Nov 2026, on D-757 (a weld legend never welds a part by itself): "if a weld is referenced,
I'd say we need to add welding." Reviewer, the same day: a general weld-process note "does not
establish a weld on every member"; genuine frame joints are kept and charged once. A metal
assembly whose own sheet states a weld process, built from metal parts, with nothing else
saying how it is joined, takes one welding event priced as an inference with its reason; no
member is charged; whatever already claims, rules out or charges a weld on it stands.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from route_compiler import compile_job_route  # noqa: E402

_MIG = "ALL WELDS TO BE MIG UNLESS STATED"


def _parts(frame_extra=None, member_material="MILD STEEL", member_family="tube"):
    frame = {"part_number": "F1", "description": "FRAME", "quantity": 1,
             "materials": ["MILD STEEL"], "process_notes": [_MIG]}
    frame.update(frame_extra or {})
    return [frame] + [
        {"part_number": pn, "description": d, "quantity": 2, "materials": [member_material],
         "material_family": member_family}
        for pn, d in (("F1-01", "UPRIGHT"), ("F1-02", "RAIL"))]


def _compile(parts, routes=()):
    extract = {"assemblies": [{"part_number": "F1", "children": [
        {"part_number": "F1-01", "qty": 2}, {"part_number": "F1-02", "qty": 2}]}],
        "parts": [], "routes": list(routes)}
    return compile_job_route(parts, extract)


def _welds(graph):
    return [d for d in graph["decisions"] if d["operation"] == "welding"
            and d["status"] == "required"]


def test_a_steel_frame_whose_sheet_references_welding_is_welded_once_at_the_frame():
    welds = _welds(_compile(_parts()))
    assert [w["target_id"] for w in welds] == ["F1"], welds
    w = welds[0]
    assert w["scope"] == "assembly" and w["source"] == "inference"
    assert "own sheet references welding" in w["reason"] and "MIG" in w["reason"]
    assert set(w["participants"]) == {"F1-01", "F1-02"}


def test_a_weld_already_claimed_on_the_frame_is_not_charged_again():
    route = {"operation": "welding", "part_numbers": ["F1"], "inferred": False,
             "evidence": "WELD ALL ROUND", "scope": "assembly"}
    assert len(_welds(_compile(_parts(), routes=[route]))) == 1


def test_no_reference_no_metal_build_or_a_ruling_adds_nothing():
    assert not _welds(_compile(_parts({"process_notes": []})))
    assert not _welds(_compile(_parts(member_material="MDF", member_family="timber")))
    assert not _welds(_compile(_parts({"operations_ruled_out": {"welding": "estimator: the frame is bolted"}})))
