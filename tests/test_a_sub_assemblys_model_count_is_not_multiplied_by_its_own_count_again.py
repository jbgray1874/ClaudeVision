"""A SUB-ASSEMBLY THE MODEL'S BOM DOES NOT LIST IS NOT TAKEN AS THE TOP (20 Nov 2026).

12110-01-GA1, a booth of 7 wall sections, each with one wall frame. The model counts 7 wall
frames in the whole booth, but listed no total for the wall section itself, and a parent with
no total was taken as 1: so "7 in the whole booth" became "7 per wall section" and was
multiplied by the 7 wall sections again. 49 frames, then 343 frame tubes, 2,058 fixing tubes,
3,088 welds and a unit cost of about £112,000 against a few thousand.

Made-up part numbers; the shape of the booth is kept.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                           # noqa: E402
from source_connectors.solidworks import (                            # noqa: E402
    NativeBomRow, NativeJob, apply_native_to_pre_estimate)


def _parts():
    return [
        {"part_number": "50003-01-GA1", "description": "BOOTH", "quantity": 1,
         "is_assembly_parent": True, "assembly_children": ["50003-02-GA"], "page_roles": ["assembly"]},
        {"part_number": "50003-02-GA", "description": "WALL SECTION", "quantity": 7,
         "is_sub_assembly": True, "is_assembly_parent": True,
         "assembly_children": ["50003-02-201"], "page_roles": ["assembly"]},
        {"part_number": "50003-02-201", "description": "WALL FRAME ASM", "quantity": 1,
         "is_sub_assembly": True, "is_assembly_parent": True,
         "assembly_children": ["50003-02-02M"], "page_roles": ["assembly"]},
        {"part_number": "50003-02-02M", "description": "FRAME TUBE", "quantity": 1,
         "normalized_material": "MILD STEEL", "page_roles": ["detail"], "review_flags": []},
    ]


def _model(list_the_wall_section: bool = False):
    bom = [NativeBomRow(part_number="50003-02-201", quantity=7, is_assembly=True),
           NativeBomRow(part_number="50003-02-02M", quantity=7)]
    if list_the_wall_section:
        bom.insert(0, NativeBomRow(part_number="50003-02-GA", quantity=7, is_assembly=True))
    return NativeJob(
        found=True, bom=bom,
        assembly_pns=["50003-01-GA1", "50003-02-GA", "50003-02-201"],
        hierarchy={"50003-01-GA1": [("50003-02-GA", 1.0)] * 7,
                   "50003-02-GA": [("50003-02-201", 1.0)],
                   "50003-02-201": [("50003-02-02M", 1.0)]})


def _rec(parts, pn):
    return next(p for p in parts if p["part_number"] == pn)


def test_one_frame_per_wall_section_seven_in_the_booth_not_forty_nine():
    parts = _parts()
    apply_native_to_pre_estimate(parts, _model())
    assert _rec(parts, "50003-02-201")["quantity"] == 1, \
        "the booth's 7 frames were written as 7 per wall section"
    graph = rc.build_part_graph(parts)
    assert graph["quantities"].get("50003-02-201") == 7
    assert graph["quantities"].get("50003-02-02M") == 7, "the tubes under the frame multiply too"


def test_where_the_model_lists_the_wall_sections_total_it_divides_as_before():
    """THE CONTROL: with the wall section's own total of 7, 7 / 7 = 1 per wall section."""
    parts = _parts()
    apply_native_to_pre_estimate(parts, _model(list_the_wall_section=True))
    assert _rec(parts, "50003-02-201")["quantity"] == 1
    assert rc.build_part_graph(parts)["quantities"].get("50003-02-201") == 7


def test_a_part_directly_under_the_top_still_takes_the_models_count():
    """The top assembly is still taken as one: 3 panels in the product under the GA are 3."""
    parts = [{"part_number": "50004-01-GA", "description": "STAND", "quantity": 1,
              "is_assembly_parent": True, "assembly_children": ["50004-01-03A"], "page_roles": ["assembly"]},
             {"part_number": "50004-01-03A", "description": "PANEL", "quantity": 1,
              "normalized_material": "PETG", "page_roles": ["detail"], "review_flags": []}]
    job = NativeJob(found=True, bom=[NativeBomRow(part_number="50004-01-03A", quantity=3)],
                    assembly_pns=["50004-01-GA"],
                    hierarchy={"50004-01-GA": [("50004-01-03A", 3.0)]})
    apply_native_to_pre_estimate(parts, job)
    assert _rec(parts, "50004-01-03A")["quantity"] == 3
