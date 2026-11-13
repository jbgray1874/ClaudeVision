"""A PIECE IS MADE ONCE FOR EVERY ONE OF ITS PART (6364-01 18:24, 13 Nov 2026).

The door is 3 off. Its three flats were priced once each. One bin piece carried no material,
though the bin's own sheet states it. Reviewer: "preserve physical pieces and repeated BOM
occurrences"; "derive blanks, material, thickness ... from evidence".
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import drawing_job_merge as M  # noqa: E402
from source_precedence import apply_field  # noqa: E402


def _part(pn, qty, qsrc, material=None, msrc=None, thk=None, of=None):
    p = {"part_number": pn}
    apply_field(p, "quantity", qty, qsrc)
    if material:
        apply_field(p, "normalized_material", material, msrc)
    if thk:
        p["normalized_thickness_mm"] = thk
    if of:
        p["dxf_minted_piece_of"] = of
    return p


def _job():
    door = _part("T-011", 3, "solidworks_api", "PETG", "drawing_deterministic", 5.0)
    bin_ = _part("T-004", 1, "solidworks_api", "PETG", "drawing_deterministic", 5.0)
    return [door, bin_,
            _part("T-011-5MM", 1, "inference", "PETG", "dxf_filename", 5.0, of="T-011"),
            _part("T-011-3MM", 1, "inference", "PETG", "dxf_filename", 3.0, of="T-011"),
            _part("T-004-01", 1, "inference", of="T-004"),
            _part("T-004-09", 1, "inference", "PETG", "dxf_filename", 3.0, of="T-004"),
            _part("T-020", 2, "bom_tree")]


def _by(parts):
    return {p["part_number"]: p for p in parts}


def test_each_door_piece_is_counted_once_a_door():
    parts = _job(); M.pieces_take_their_parts_count_and_material(parts); by = _by(parts)
    assert by["T-011-5MM"]["quantity"] == 3 and by["T-011-3MM"]["quantity"] == 3
    took = by["T-011-5MM"]["quantity_from_its_part"]
    assert took["part"] == "T-011" and took["part_quantity"] == 3 and took["per_part"] == 1
    from source_precedence import source_of
    assert source_of(by["T-011-5MM"], "quantity") == "bom_tree_per_unit"


def test_a_piece_of_a_one_off_part_stays_one():
    parts = _job(); M.pieces_take_their_parts_count_and_material(parts)
    assert _by(parts)["T-004-09"]["quantity"] == 1 and "quantity_from_its_part" not in _by(parts)["T-004-09"]


def test_a_count_somebody_established_is_left_alone():
    parts = _job()
    counted = _part("T-011-07", 2, "bom_tree", "PETG", "dxf_filename", 5.0, of="T-011")
    parts.append(counted)
    M.pieces_take_their_parts_count_and_material(parts)
    assert counted["quantity"] == 2 and "quantity_from_its_part" not in counted


def test_it_is_applied_once_however_often_it_runs():
    parts = _job()
    M.pieces_take_their_parts_count_and_material(parts)
    assert M.pieces_take_their_parts_count_and_material(parts) == []
    assert _by(parts)["T-011-5MM"]["quantity"] == 3


def test_a_piece_with_no_material_takes_what_its_parts_sheet_states():
    parts = _job(); said = M.pieces_take_their_parts_count_and_material(parts); p = _by(parts)["T-004-01"]
    assert p["normalized_material"] == "PETG" and p["normalized_thickness_mm"] == 5.0
    assert p["material_from_its_part"] == {"part": "T-004", "material": "PETG",
                                           "stated_by": "drawing_deterministic", "thickness_mm": 5.0}
    assert any("Confirm the gauge" in str(f) for f in p["review_flags"])
    assert {"piece": "T-004-01", "of": "T-004", "material": "PETG", "thickness_mm": 5.0} in said


def test_a_piece_that_states_its_own_material_and_gauge_keeps_them():
    parts = _job(); M.pieces_take_their_parts_count_and_material(parts); p = _by(parts)["T-004-09"]
    assert p["normalized_thickness_mm"] == 3.0 and "material_from_its_part" not in p


def test_a_parts_guessed_material_is_not_passed_down():
    parts = [_part("T-030", 1, "bom_tree", "MDF", "inference", 18.0), _part("T-030-01", 1, "inference", of="T-030")]
    M.pieces_take_their_parts_count_and_material(parts)
    assert not parts[1].get("normalized_material")


def test_parts_that_are_not_pieces_are_untouched():
    parts = _job(); before = dict(_by(parts)["T-020"]); M.pieces_take_their_parts_count_and_material(parts)
    assert _by(parts)["T-020"] == before


def test_it_runs_before_anything_is_costed():
    est = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert "pieces_take_their_parts_count_and_material as _pieces" in est
    assert est.index("_inherit(parts)") < est.index("_took = _pieces(parts)")
