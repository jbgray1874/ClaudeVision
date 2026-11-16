"""A sawn tube is not cut again on a Tube row (D-541).

The 0356454 large repro rail, 16:58 book: the 25 x 25 box uprights and the 20 x 20 box lower
frame carried a Saw row (cut to length from stock, D-531) AND a Tube row — a laser word on a
tube that the workbook writer remaps to the Tube cut. One length, cut twice. Where every part
on the row is already sawn, the Tube row is not made; a tube nobody saws keeps it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import wb_populate as W  # noqa: E402


def _summary(decisions):
    return {"estimate_summary": {"canonical_route_shadow": {"nodes": [], "decisions": decisions}}}


def _d(did, op, target):
    return {"decision_id": did, "operation": op, "status": "required", "target_id": target,
            "participants": [target], "scope": "part", "qty_per_unit": 1}


def _tube(pn, ops):
    return {"part_number": pn, "quantity": 4, "description": "25X25 BOX UPRIGHTS",
            "normalized_material": "MILD STEEL", "normalized_thickness_mm": 1.5,
            "inferred_operations": list(ops),
            "material_estimate": {"stock_form": "tube"}, "labour_estimate": {}}


def _rows(groups):
    return sorted({str(g.get("wb_op") or g.get("operation") or k[0] if isinstance(k, tuple)
                       else g.get("wb_op")) for k, g in groups.items()})


def _ops_charged(groups):
    out = []
    for g in groups.values():
        out += [str(o).lower() for o in (g.get("engine_ops") or [])]
    return out


def test_a_sawn_tube_gets_the_saw_and_no_tube_cut():
    summary = _summary([_d("d1", "laser_cutting", "J-CPT01"), _d("d2", "saw", "J-CPT01")])
    groups = W.canonical_labour_groups(summary, [_tube("J-CPT01", ["saw"])], 1)
    ops = _ops_charged(groups)
    assert "saw" in ops
    assert "laser_cutting" not in ops, groups


def test_a_tube_nobody_saws_keeps_its_tube_cut():
    summary = _summary([_d("d1", "laser_cutting", "J-CPT01")])
    groups = W.canonical_labour_groups(summary, [_tube("J-CPT01", [])], 1)
    assert "laser_cutting" in _ops_charged(groups)


def test_sawn_is_read_from_the_saw_pieces_or_the_operations():
    est = {"A": {"_saw_cut_list_pieces": [1710.0]}, "B": {"textual_operations": ["saw"]},
           "C": {"inferred_operations": ["welding"]}}
    assert W._sawn_to_length("A", est, {})
    assert W._sawn_to_length("B", est, {})
    assert not W._sawn_to_length("C", est, {})
    assert W._sawn_to_length("C", est, {"C": {"inferred_operations": ["SAW"]}})
