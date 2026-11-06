"""The carton is sized to the declared product's own model, never a sub-assembly's (D-735).

12002-02-GA, 6 Nov 2026 12:13 book: the carton was sized 447 x 386 x 10 mm, the arm
sub-assembly's box, for an assembled stand on a 300 mm disc base. The extract held two roots,
12002-02-102 SA and 12002-02-GA; the top-assembly pick, which exists to choose a BOM, took the
arm by its match to the drawings' codes, and packing used the top assembly's box. The product's
size is the product's own model's box: packing now reads the declared product's entry first,
and a top assembly the model shows as another assembly's child is never the product.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

_STAND = [300.0, 300.0, 520.0]          # the assembled stand: its disc base and its height
_ARM = [447.0, 386.0, 10.0]             # the arm sub-assembly


def _summary(**sw):
    return {"declared_product": "12002-02-GA", "solidworks_native": sw}


def test_the_declared_products_own_box_wins_over_the_chosen_top_assembly():
    from commercial_lines import product_envelope
    env = product_envelope(_summary(
        top_assembly="12002-02-102 SA", top_assembly_bbox_mm=_ARM,
        assembly_bbox_mm={"12002-02-GA": _STAND, "12002-02-102 SA": _ARM},
        sub_assemblies=[]))
    assert (env["length"], env["width"], env["height"]) == (520.0, 300.0, 300.0)
    assert env["of"] == "12002-02-GA"
    assert "SolidWorks model of 12002-02-GA" in env["source"]


def test_the_products_box_is_found_however_its_number_is_spaced():
    from commercial_lines import product_envelope
    env = product_envelope(_summary(
        top_assembly="12002-02-102 SA", top_assembly_bbox_mm=_ARM,
        assembly_bbox_mm={"12002-02 GA": _STAND, "12002-02-102 SA": _ARM}))
    assert env["of"] == "12002-02 GA" and env["length"] == 520.0


def test_a_top_assembly_that_is_another_assemblys_child_is_never_the_product():
    """No box for the declared product, and the top assembly is somebody's child: its box is
    not the product's, so the stated overall answers, or nothing does."""
    from commercial_lines import product_envelope
    sw = dict(top_assembly="12002-02-102 SA", top_assembly_bbox_mm=_ARM,
              assembly_bbox_mm={"12002-02-102 SA": _ARM},
              sub_assemblies=["12002-02-102 SA"])
    assert product_envelope(_summary(**sw)) is None
    env = product_envelope(_summary(**sw),
                           [{"part_number": "12002-02-GA", "overall_size_mm": "300 x 300 x 520"}])
    assert (env["length"], env["width"], env["height"]) == (520.0, 300.0, 300.0)
    assert "stated" in env["source"]


def test_a_root_top_assembly_still_gives_the_box_when_the_product_has_none_of_its_own():
    """The D-551 case is unchanged: the top assembly is the GA, and nothing else names it."""
    from commercial_lines import product_envelope
    env = product_envelope({"solidworks_native": {"top_assembly": "401918-01-GA",
                                                   "top_assembly_bbox_mm": [1298.0, 1438.2, 450.0],
                                                   "sub_assemblies": ["401918-01-02 SA"]}})
    assert (env["length"], env["width"], env["height"]) == (1438.2, 1298.0, 450.0)


def test_the_extract_records_every_assemblys_box_and_which_are_children():
    from source_connectors.solidworks import SW_ASM, SW_PART, normalize_native_extract
    records = [
        {"doctype": SW_ASM, "title": "12002-02-GA", "assembly_part_number": "12002-02-GA",
         "bbox_mm": _STAND, "bom": [{"part_number": "12002-02-101 SA"}],
         "assembly_edges": [{"parent": "12002-02-GA", "child": "12002-02-101 SA"}]},
        {"doctype": SW_ASM, "title": "12002-02-101 SA", "assembly_part_number": "12002-02-101 SA",
         "bbox_mm": [300.0, 300.0, 3.0], "bom": [{"part_number": "12002-02-M01"}],
         "assembly_edges": [{"parent": "12002-02-101 SA", "child": "12002-02-M01"}]},
        {"doctype": SW_ASM, "title": "12002-02-102 SA", "assembly_part_number": "12002-02-102 SA",
         "bbox_mm": _ARM, "bom": [{"part_number": "12002-02-M04"}]},
        {"doctype": SW_PART, "title": "12002-02-M01", "bbox_mm": [300.0, 300.0, 3.0]},
    ]
    job = normalize_native_extract(records)
    assert job.meta["assembly_bbox_mm"] == {"12002-02-GA": _STAND,
                                            "12002-02-101 SA": [300.0, 300.0, 3.0],
                                            "12002-02-102 SA": _ARM}
    # 101 SA is the GA's child; a part is never listed; 102 SA owns nothing and is nobody's.
    assert job.meta["sub_assemblies"] == ["12002-02-101 SA"]


def test_the_scan_summary_carries_both():
    fs = (Path(__file__).resolve().parents[1] / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert '"assembly_bbox_mm": _sw_job.meta.get("assembly_bbox_mm")' in fs
    assert '"sub_assemblies": _sw_job.meta.get("sub_assemblies")' in fs
