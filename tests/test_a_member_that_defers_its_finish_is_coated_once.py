"""A member that defers its finish to a coated assembly is coated there, once (D-654).

12684-02-GA, 3 Nov 2026 12:45 run: three P.Coat rows, GBP 358.93 at 1 off (SCRUM-104/105/136).
The frame 102SA is a weldment, so its coat is a booth stage; its baseplate, framework and outer
frame all print SEE ASSEMBLY DRAWING and were coated again on a row of their own, inside the
frame already being coated. The hook assembly 101SA's coat lists its bracket among the parts it
covers, and the bracket was coated a second time beside it. Row 164 was nothing but those
second coats: GBP 143.89 at 1 off, GBP 63.93 a unit at 10 off.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from route_compiler import NOT_APPLICABLE, REQUIRED, compile_job_route  # noqa: E402


def _part(pn, desc, finish, ops, **extra):
    rec = {"part_number": pn, "description": desc, "quantity": 1,
           "normalized_material": "MILD_STEEL", "normalized_finish": finish,
           "surface_finishes": [finish] if finish else [], "textual_operations": list(ops)}
    rec.update(extra)
    return rec


def _welded(pn, desc, finish, scope_assembly=True):
    return _part(pn, desc, finish, ["welding", "powder_coating"],
                 operation_sources={"welding": "drawing_deterministic"},
                 operation_scope={"powder_coating": "assembly"} if scope_assembly else {})


def _pack():
    parts = [
        _part("T-GA", "TABLETOP HOOK UNIT", "POWDER COATED RAL 7021", ["powder_coating"]),
        _part("T-101SA", "HOOK ASSEMBLY", "POWDER COATED RAL 7021", ["powder_coating"],
              operation_scope={"powder_coating": "assembly"}),
        _part("T-M01", "ARM BRACKET", "SEE ASSEMBLY DRAWING", ["laser_cutting", "folding"]),
        _part("T-M02", "ARM", "", []),
        _welded("T-102SA", "FRAME", "POWDER COATED RAL 7021"),
        _part("T-M04", "BASEPLATE", "SEE ASSEMBLY DRAWING", ["laser_cutting", "powder_coating"]),
        _welded("T-103SA", "FRAMEWORK", "SEE ASSEMBLY DRAWING"),
        _part("T-M06", "OUTER FRAME", "SEE ASSEMBLY DRAWING", ["tube_cut"]),
        _part("T-M07", "CROSS BAR", "RAW", ["saw"]),
    ]
    extract = {"assemblies": [
        {"part_number": "T-GA", "children": [{"part_number": "T-101SA", "qty": 33},
                                             {"part_number": "T-102SA", "qty": 1}]},
        {"part_number": "T-101SA", "children": [{"part_number": "T-M01", "qty": 1},
                                                {"part_number": "T-M02", "qty": 1}]},
        {"part_number": "T-102SA", "children": [{"part_number": "T-M04", "qty": 1},
                                                {"part_number": "T-103SA", "qty": 1}]},
        {"part_number": "T-103SA", "children": [{"part_number": "T-M06", "qty": 1},
                                                {"part_number": "T-M07", "qty": 11}]}],
        "parts": [], "routes": []}
    return compile_job_route(parts, extract)


def _powder(route, status=REQUIRED):
    return {d["target_id"]: d for d in route["decisions"]
            if d["operation"] == "powder_coating" and d["status"] == status}


def test_the_frame_is_coated_once_as_the_weldment():
    coated = _powder(_pack())
    assert "T-102SA" in coated
    for member in ("T-M04", "T-103SA", "T-M06"):
        assert member not in coated, f"{member} coated again inside the coated weldment"


def test_the_bracket_is_coated_once_with_its_hook():
    coated = _powder(_pack())
    assert "T-101SA" in coated and "T-M01" not in coated


def test_exactly_one_coat_per_object_in_the_booth():
    assert set(_powder(_pack())) == {"T-101SA", "T-102SA"}


def test_the_ruled_out_coat_says_why_and_how_to_put_it_back():
    out = _powder(_pack(), NOT_APPLICABLE)
    m04 = out["T-M04"]["reason"]
    assert "coated once, as part of T-102SA" in m04 and "welded stage" in m04
    assert "put this row back" in m04
    assert "coated once, as part of T-101SA" in out["T-M01"]["reason"]


def test_the_raw_cross_bar_is_never_coated():
    assert "T-M07" not in _powder(_pack())


def test_a_member_whose_own_sheet_states_its_coat_keeps_it():
    """Only "see assembly" defers. A member that states its own coat may be coated on its own."""
    parts = [
        _welded("S-101", "FRAME", "POWDER COATED"),
        _part("S-01M", "PANEL", "POWDER COATED RAL 9005", ["laser_cutting", "powder_coating"],
              operation_sources={"powder_coating": "drawing_deterministic"}),
    ]
    extract = {"assemblies": [{"part_number": "S-101",
                               "children": [{"part_number": "S-01M", "qty": 1}]}],
               "parts": [], "routes": []}
    coated = _powder(compile_job_route(parts, extract))
    assert "S-01M" in coated
