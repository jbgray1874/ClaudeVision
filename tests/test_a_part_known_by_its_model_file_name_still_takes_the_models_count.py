"""A PART KNOWN BY ITS MODEL FILE'S NAME STILL TAKES THE MODEL'S COUNT (15 Nov 2026).

One job's bill prints two mirrors as "<code>.SLDPRT1". The model's assembly list and its
parent edges name the same parts "<code>", two in the product, one per upright. Keyed as
printed, each mirror found no row in the assembly list: it was flagged "in NO assembly BOM —
a fixture, jig or setup part", took no count from the model, and the table's three per
upright was charged, six where the model holds two.

The extension and SolidWorks' copy number are not part of the number. A part that really is
in no assembly is still flagged.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from source_connectors.solidworks import (                            # noqa: E402
    NativeBomRow, NativeJob, _pn_key, apply_native_to_pre_estimate)

TOP, UPRIGHT, MIRROR, BLOCK = "T-GA", "T-201", "T-203", "T-204"


def _job():
    rows = [NativeBomRow(UPRIGHT, 2, is_assembly=True), NativeBomRow(MIRROR, 2),
            NativeBomRow(BLOCK, 2)]
    return NativeJob(found=True, bom=rows, assembly_pns=[TOP, UPRIGHT],
                     hierarchy={TOP: [(UPRIGHT, 2.0)],
                                UPRIGHT: [(MIRROR, 1.0), (BLOCK, 1.0)]})


def _parts(mirror_code):
    return [
        {"part_number": TOP, "quantity": 1, "is_assembly_parent": True,
         "assembly_children": [UPRIGHT], "page_roles": ["assembly"]},
        {"part_number": UPRIGHT, "quantity": 2, "is_assembly_parent": True,
         "is_sub_assembly": True, "assembly_children": [mirror_code, BLOCK],
         "page_roles": ["assembly"]},
        {"part_number": mirror_code, "description": "UPRIGHT MIRROR", "quantity": 3,
         "page_roles": ["detail"], "review_flags": []},
        {"part_number": BLOCK, "description": "FIXING BLOCK", "quantity": 1,
         "page_roles": ["detail"], "review_flags": []},
    ]


def _mirror(parts):
    return parts[2]


def test_the_key_drops_a_model_file_extension_and_copy_number():
    assert _pn_key("T-203.SLDPRT1") == _pn_key("t-203") == "T-203"
    assert _pn_key("T-203.sldasm") == "T-203"
    assert _pn_key("HAFELE 651.09.302") == "HAFELE651.09.302", "a dotted article number is kept"


def test_a_mirror_printed_as_its_file_name_takes_one_per_upright_from_the_model():
    parts = _parts(MIRROR + ".SLDPRT1")
    out = apply_native_to_pre_estimate(parts, _job())
    m = _mirror(parts)
    assert m["quantity"] == 1, m.get("review_flags")
    assert not m.get("not_in_assembly_bom")
    assert not out.get("not_in_bom_parts")
    assert not any("NO assembly BOM" in str(f) for f in m.get("review_flags") or [])


def test_the_same_mirror_printed_plainly_is_counted_the_same():
    parts = _parts(MIRROR)
    apply_native_to_pre_estimate(parts, _job())
    assert _mirror(parts)["quantity"] == 1


def test_a_part_that_is_in_no_assembly_is_still_flagged():
    parts = _parts(MIRROR) + [{"part_number": "T-JIG", "description": "SETUP BLOCK",
                               "quantity": 1, "page_roles": ["detail"], "review_flags": []}]
    job = _job()
    from source_connectors.solidworks import NativePart
    try:
        job.part_signals["T-JIG"] = NativePart(part_number="T-JIG")
    except TypeError:
        job.part_signals["T-JIG"] = NativePart("T-JIG")
    out = apply_native_to_pre_estimate(parts, job)
    assert parts[-1].get("not_in_assembly_bom") is True
    assert out.get("not_in_bom_parts") == ["T-JIG"]
