"""A weldment the drawing plates does not keep an inferred powder line.

7332-01-101 is PLATED (Harrods 1). Its back panel 008 correctly dropped powder — the drawing
states PLATED, which is plate, not powder coating. But the weldment PARENT carries no finish of
its own (the drawing states it once for the whole object), so stated_finish(101) was empty and an
INFERRED powder on the parent was never contradicted — a £15.92 P.Coat row on a plated stand.

weldment_finish_for_gate lets the parent inherit its members' agreed finish, so the plate reads
through to the parent and the powder is ruled out on 101 exactly as it is on 008.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import route_compiler as rc  # noqa: E402
from finish_rules import finish_contradiction  # noqa: E402


def _graph(children, finishes):
    return {
        "children": {"101": set(children)},
        "records": {pn: {"normalized_finish": f} for pn, f in finishes.items()},
    }


def test_a_plated_weldment_inherits_plate_from_its_members():
    # 101 has no finish of its own; members: 001 raw-then-plated, 008 PLATED, 002 raw
    g = _graph(["001", "008", "002"],
               {"101": "", "001": "RAW", "008": "PLATED", "002": "RAW"})
    finish = rc.weldment_finish_for_gate(g["records"]["101"], "101", g)
    assert finish == "PLATED"
    # and that inherited finish rules out an inferred powder on the parent
    assert finish_contradiction("powder_coating", finish)  # non-None => ruled out


def test_a_raw_only_weldment_keeps_powder():
    """No stated plate anywhere → the parent's finish stays empty → powder is NOT contradicted."""
    g = _graph(["001", "002"], {"101": "", "001": "RAW", "002": "RAW"})
    finish = rc.weldment_finish_for_gate(g["records"]["101"], "101", g)
    assert finish == ""
    assert finish_contradiction("powder_coating", finish) is None


def test_a_powder_weldment_is_untouched():
    g = _graph(["001"], {"101": "", "001": "POWDER COATED"})
    finish = rc.weldment_finish_for_gate(g["records"]["101"], "101", g)
    # members are powder → not inherited as a contradiction; powder survives
    assert finish_contradiction("powder_coating", finish) is None


def test_a_mixed_finish_weldment_is_not_collapsed():
    """Plate on one member, lacquer on another → ambiguous → do not rule powder out."""
    g = _graph(["001", "007"], {"101": "", "001": "PLATED", "007": "LACQUERED"})
    finish = rc.weldment_finish_for_gate(g["records"]["101"], "101", g)
    assert finish == ""


def test_a_part_that_states_its_own_finish_is_returned_as_is():
    g = _graph([], {"008": "PLATED"})
    assert rc.weldment_finish_for_gate({"normalized_finish": "PLATED"}, "008", g) == "PLATED"


# END-TO-END: the powder on 101 is an ASSEMBLY-scope claim. A finish gate that only looked at
# scope 'part' left it charged (£15.92) while the leaf 008 correctly dropped it. The gate now
# rules out an assembly-scope finish claim too.

def _compile_plated_weldment(finish, powder_scope="assembly"):
    return {d["operation"] + "@" + d["target_id"]: d for d in rc.compile_job_route(
        [{"part_number": "7332-01-101", "description": "FRAME WELDMENT",
          "normalized_finish": finish, "is_assembly_parent": True,
          "assembly_children": ["7332-01-008"]},
         {"part_number": "7332-01-008", "description": "BACK PANEL",
          "normalized_finish": finish}],
        {"assemblies": [{"part_number": "7332-01-101",
                         "children": [{"part_number": "7332-01-008", "qty": 1}]}],
         "bom": [{"part_number": "7332-01-101", "qty": 1, "type": "fabricated"},
                 {"part_number": "7332-01-008", "qty": 1, "type": "fabricated"}],
         "routes": [{"operation": "powder_coating", "part_numbers": ["7332-01-101"],
                     "scope": powder_scope, "target_id": "7332-01-101"}]})["decisions"]}


def test_assembly_scope_powder_on_a_plated_weldment_is_ruled_out():
    d = _compile_plated_weldment("PLATED")
    dec = d.get("powder_coating@7332-01-101")
    assert dec is not None and dec["status"] == "not_applicable"
    assert "plate" in str(dec.get("reason") or "").lower()


def test_assembly_scope_powder_on_a_powder_weldment_stands():
    d = _compile_plated_weldment("POWDER COATED")
    dec = d.get("powder_coating@7332-01-101")
    assert dec is not None and dec["status"] != "not_applicable"
