"""AN ASSEMBLY AND THE PART INSIDE IT SHARE A NUMBER AND ARE COUNTED ONCE (6364-01, 12 Nov 2026).

The rear castor plate is an assembly holding a plate part of the same number and two bushes.
The model's bill counts by number: two assemblies and their two plates read as four, and four
plates were costed where the drawing's bill and the model's own tree both say two.
Reviewer: "preserve physical pieces and repeated BOM occurrences ... without losing or
duplicating components."
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import source_connectors.solidworks as sw  # noqa: E402

ASM, PART = sw.SW_ASM, sw.SW_PART


def _records(bill_plate_qty):
    top = {"path": "/p/T-000.SLDASM", "title": "T-000", "doctype": ASM,
           "bom": [{"part_number": "T-005", "qty": bill_plate_qty}, {"part_number": "T-013", "qty": 2},
                   {"part_number": "T-020", "qty": 6}],
           "assembly_edges": [{"parent": "T-000", "child": "T-005", "qty": 2},
                              {"parent": "T-000", "child": "T-013", "qty": 2},
                              {"parent": "T-000", "child": "T-010", "qty": 2}]}
    plate_asm = {"path": "/p/T-005.SLDASM", "title": "T-005", "doctype": ASM, "bom": [],
                 "assembly_edges": [{"parent": "T-005", "child": "T-005", "qty": 1},
                                    {"parent": "T-005", "child": "BUSH", "qty": 2}]}
    sub = {"path": "/p/T-010.SLDASM", "title": "T-010", "doctype": ASM, "bom": [],
           "assembly_edges": [{"parent": "T-010", "child": "T-020", "qty": 3}]}
    return [top, plate_asm, sub,
            {"path": "/p/T-013.SLDPRT", "title": "T-013", "doctype": PART},
            {"path": "/p/T-020.SLDPRT", "title": "T-020", "doctype": PART}]


def _row(job, pn):
    return next(r for r in job.bom if r.part_number == pn)


def test_the_assembly_is_counted_as_the_tree_holds_it():
    job = sw.normalize_native_extract(_records(4))
    plate = _row(job, "T-005")
    assert plate.is_assembly and plate.quantity == 2.0
    assert any("counted 4" in f and "holds 2" in f for f in plate.flags)


def test_a_bill_that_agrees_with_the_tree_is_left_alone():
    job = sw.normalize_native_extract(_records(2))
    assert _row(job, "T-005").quantity == 2.0 and not any("counted" in f for f in _row(job, "T-005").flags)


def test_a_parts_count_from_the_bill_is_never_changed_here():
    # T-020 is a part: 3 in each of 2 sub-assemblies. The bill's 6 stands; so does T-013's 2.
    job = sw.normalize_native_extract(_records(4))
    assert _row(job, "T-020").quantity == 6.0 and _row(job, "T-013").quantity == 2.0


def test_the_tree_multiplies_down_and_survives_a_self_reference():
    tree = {"T-000": [("T-005", 2), ("T-010", 2)], "T-005": [("T-005", 1), ("BUSH", 2)], "T-010": [("T-020", 3)]}
    got = sw.quantities_by_the_tree(tree, "T-000")
    assert got["T-010"] == 2 and got["T-020"] == 6 and got["BUSH"] == 4
    assert sw.quantities_by_the_tree(tree, "") == {} and sw.quantities_by_the_tree({}, "T-000") == {}
