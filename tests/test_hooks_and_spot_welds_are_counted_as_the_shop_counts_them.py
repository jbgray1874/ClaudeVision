"""Hooks and spot welds are counted the way the shop counts them (D-656).

12684-02-GA, 3 Nov 2026 12:45 run. JG, the same day: "spotweld is welds per hour, hooks are 33
pieces".

  * The GA's own sheet carries 33 ISO spot-weld symbols, one per hook, and the reader recorded
    spot_weld_count 33 — but the Spotweld row took the GA's own count and welded once.
  * Two readers each raised a powder event on the hook assembly 12684-02-101SA at 33, and the
    P.Coat row added them to 66 pieces: the bracket and the arm counted apart. A hook goes
    through the booth as one piece.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc  # noqa: E402
from route_compiler import NOT_APPLICABLE, REQUIRED, compile_job_route  # noqa: E402


def _hooks(spot_count=33, hook_qty=33):
    parts = [
        {"part_number": "H-GA", "description": "HOOK UNIT", "quantity": 1,
         "is_assembly_parent": True, "assembly_children": ["H-101SA"],
         "textual_operations": ["spot_welding"],
         "operation_sources": {"spot_welding": "drawing_deterministic"},
         "spot_weld_count": spot_count},
        {"part_number": "H-101SA", "description": "HOOK ASSEMBLY", "quantity": hook_qty,
         "is_assembly_parent": True, "is_sub_assembly": True,
         "assembly_children": ["H-M01", "H-M02"],
         "normalized_finish": "POWDER COATED RAL 7021",
         "surface_finishes": ["POWDER COATED RAL 7021"],
         "textual_operations": ["powder_coating"],
         "operation_scope": {"powder_coating": "assembly"},
         "operation_sources": {"powder_coating": "llm_full_extract"}},
        {"part_number": "H-M01", "description": "ARM BRACKET", "quantity": 1,
         "normalized_material": "MILD_STEEL", "normalized_finish": "SEE ASSEMBLY DRAWING"},
        {"part_number": "H-M02", "description": "ARM", "quantity": 1,
         "normalized_material": "MILD_STEEL"},
    ]
    job = {"assemblies": [
        {"part_number": "H-GA", "children": [{"part_number": "H-101SA", "qty": hook_qty}]},
        {"part_number": "H-101SA", "children": [{"part_number": "H-M01", "qty": 1},
                                                {"part_number": "H-M02", "qty": 1}]}],
        "routes": [{"operation": "powder_coating", "part_numbers": ["H-M01", "H-M02"],
                    "scope": "assembly", "qty_per_unit": hook_qty, "sequence": 70}]}
    return compile_job_route(parts, job, known_assemblies=["H-GA", "H-101SA"])


def _required(out, op):
    return [d for d in out["decisions"] if d["operation"] == op and d["status"] == REQUIRED]


def test_the_ga_is_spot_welded_once_per_symbol_its_sheet_shows():
    spots = _required(_hooks(), "spot_welding")
    assert len(spots) == 1 and float(spots[0]["qty_per_unit"]) == 33.0
    assert "spot weld(s) on its own sheet" in spots[0]["reason"]


def test_a_spot_count_below_the_parts_own_count_changes_nothing():
    """A part with no symbol count, or one already charged at more, stands as it was."""
    spots = _required(_hooks(spot_count=0), "spot_welding")
    assert len(spots) == 1 and float(spots[0]["qty_per_unit"]) == 1.0


def test_the_hook_assembly_is_coated_as_33_pieces():
    coats = [d for d in _required(_hooks(), "powder_coating") if d["target_id"] == "H-101SA"]
    assert len(coats) == 1 and float(coats[0]["qty_per_unit"]) == 33.0


def _decision(did, qty, participants):
    return SimpleNamespace(decision_id=did, operation="powder_coating", status=REQUIRED,
                           target_id="H-101SA", qty_per_unit=qty, participants=participants,
                           reason="", field_provenance={})


def test_two_coat_events_on_one_object_are_one_pass_through_the_booth():
    """The 3 Nov run's shape: two events on the hook assembly, each at 33, summed to 66."""
    a = _decision("decision:0f07", 33.0, ["H-M01", "H-M02"])
    b = _decision("decision:2131", 33.0, ["H-101SA"])
    issues = []
    assert rc._one_coat_event_per_target([a, b], issues) == ["H-101SA"]
    kept = [d for d in (a, b) if d.status == REQUIRED]
    out = [d for d in (a, b) if d.status == NOT_APPLICABLE]
    assert len(kept) == 1 and len(out) == 1
    assert kept[0].qty_per_unit == 33.0, "counted once, never the sum"
    assert kept[0].participants == ["H-101SA", "H-M01", "H-M02"]
    assert "one pass through the booth per H-101SA" in out[0].reason
    assert out[0].field_provenance["status"] == "one_coat_event_per_target"
    assert issues and issues[0]["code"] == "one_coat_event_per_target"


def test_the_higher_count_stands_when_the_two_disagree():
    a = _decision("decision:a", 33.0, ["H-101SA"])
    b = _decision("decision:b", 66.0, ["H-101SA"])
    rc._one_coat_event_per_target([a, b])
    assert b.status == REQUIRED and a.status == NOT_APPLICABLE


def test_one_coat_event_is_left_alone():
    a = _decision("decision:a", 33.0, ["H-101SA"])
    assert rc._one_coat_event_per_target([a]) == [] and a.status == REQUIRED
