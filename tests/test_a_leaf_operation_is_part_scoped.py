"""A leaf's own operation is part-scoped, whatever scope the read stamped on it (D-707).

12693-03 small table, 14:35 book: the read gave the top insert 12693-03-04J one CNC route line
scoped "assembly", and that scope was stamped on every panel. Each panel's own cut then became
an assembly event charged on the panel itself: a row with no board thickness ("MDF", not
"12mm MDF"), outside the shared set-up of panels cut from one board (D-671). The two 12 mm
strip types took 15 minutes of set-up each; the medium, whose read scoped the same cuts to the
part, shared one.

Assembly scope means once per assembly. On a part with no parts of its own, charged on itself,
it can only mean once per part.

Synthetic records and made-up part numbers.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc  # noqa: E402

INSERT, PANEL, STRIP = "J-04J", "J-04J-01", "J-04J-02"


def _parts(panel_scope="assembly"):
    leaf = {"textual_operations": ["cnc_routing"],
            "operation_sources": {"cnc_routing": "llm_full_extract"},
            "operation_scope": {"cnc_routing": panel_scope},
            "normalized_material": "MDF", "parent_assemblies": [INSERT]}
    return [{"part_number": INSERT, "description": "TOP INSERT", "quantity": 1,
             "is_assembly_parent": True, "assembly_children": [PANEL, STRIP],
             "textual_operations": ["assembly"],
             "operation_scope": {"assembly": "assembly"}},
            dict(leaf, part_number=PANEL, description="TOP INSERT PANEL 595 x 595 x 18",
                 quantity=1, normalized_thickness_mm=18.0),
            dict(leaf, part_number=STRIP, description="TOP INSERT STRIP 595 x 76 x 12",
                 quantity=2, normalized_thickness_mm=12.0)]


def _cnc(r):
    return {d["target_id"]: d for d in r["decisions"]
            if d["operation"] == "cnc_routing" and d["status"] == "required"}


def test_a_panels_cut_stamped_assembly_is_charged_part_scoped_on_the_panel():
    r = rc.compile_job_route(_parts(), {})
    cnc = _cnc(r)
    assert set(cnc) == {PANEL, STRIP}
    assert {d["scope"] for d in cnc.values()} == {"part"}
    assert cnc[STRIP]["qty_per_unit"] == 2, "once per strip, two strips a unit"
    said = [i for i in r["issues"] if i.get("code") == "leaf_operation_scoped_as_assembly"]
    assert {i["part_number"] for i in said} == {PANEL, STRIP}
    assert len(said) == 2, "said once per part"


def test_a_cut_the_read_scoped_to_the_part_is_unchanged():
    r = rc.compile_job_route(_parts(panel_scope="part"), {})
    assert {d["scope"] for d in _cnc(r).values()} == {"part"}
    assert not any(i.get("code") == "leaf_operation_scoped_as_assembly" for i in r["issues"])


def test_an_assembly_keeps_its_own_assembly_scope():
    r = rc.compile_job_route(_parts(), {})
    asm = [d for d in r["decisions"] if d["operation"] == "assembly"
           and d["target_id"] == INSERT and d["status"] == "required"]
    assert asm and all(d["scope"] == "assembly" for d in asm)
