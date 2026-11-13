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


def test_the_parts_gauge_is_not_passed_on_where_its_pieces_state_their_own():
    # the bin's sheet prints one gauge; its panels are 5 mm and 3 mm by their own files
    parts = _job() + [_part("T-004-08", 1, "inference", "PETG", "dxf_filename", 5.0, of="T-004")]
    M.pieces_take_their_parts_count_and_material(parts); p = _by(parts)["T-004-01"]
    assert p["normalized_material"] == "PETG" and not p.get("normalized_thickness_mm")
    assert "3, 5 mm" in p["material_from_its_part"]["gauge_not_taken"]


def test_a_piece_with_no_material_takes_what_its_parts_sheet_states():
    parts = [q for q in _job() if q["part_number"] != "T-004-09"]; said = M.pieces_take_their_parts_count_and_material(parts); p = _by(parts)["T-004-01"]
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
    assert est.index("_inherit(parts)") < est.index("_took = _pieces(parts, ")



# ── the part's own table says how many of each piece (12424-02-GA 14:34, 11 Nov 2026) ────
# The reader captured eight panels (2, 1, 2 and 3 by size) and four were costed.
def _insert():
    panel = lambda n, l, w: dict(_part(f"T-01A-0{n}", 1, "inference", "ACRYLIC", "dxf_filename", 3.0, of="T-01A"),
                                 overall_length_mm=l, overall_width_mm=w)  # noqa: E731
    return [_part("T-01A", 1, "solidworks_api", "ACRYLIC", "drawing_deterministic", 3.0),
            panel(1, 290.0, 260.0), panel(2, 358.0, 264.0), panel(3, 358.0, 290.0), panel(4, 293.0, 260.0)]


def _table(parent="T-01A"):
    row = lambda i, d, q: {"part_number": "", "description": d, "quantity": q,  # noqa: E731
                           "bom_parent": parent, "bom_item_no": str(i)}
    return [{"part_number": "T-01A", "description": "INSERT", "quantity": 1, "bom_parent": "T-GA"},
            row(1, "290 x 260 x 3 mm", 2), row(2, "358 x 264 x 3 mm", 1),
            row(3, "358 x 290 x 3 mm", 2), row(4, "293 x 260 x 3 mm", 3)]


def test_all_eight_panels_reach_costing():
    parts = _insert(); M.pieces_take_their_parts_count_and_material(parts, _table()); by = _by(parts)
    assert [by[f"T-01A-0{n}"]["quantity"] for n in (1, 2, 3, 4)] == [2, 1, 2, 3]
    assert sum(by[f"T-01A-0{n}"]["quantity"] for n in (1, 2, 3, 4)) == 8
    took = by["T-01A-04"]["quantity_from_its_part"]
    assert took["per_part"] == 3 and "293 x 260 x 3 mm" in took["basis"] and "item 4" in took["basis"]


def test_the_tables_count_is_multiplied_by_the_parts_own():
    parts = _insert(); parts[0] = _part("T-01A", 5, "solidworks_api", "ACRYLIC", "drawing_deterministic", 3.0)
    M.pieces_take_their_parts_count_and_material(parts, _table())
    assert _by(parts)["T-01A-01"]["quantity"] == 10 and _by(parts)["T-01A-02"]["quantity"] == 5


def test_a_row_that_fits_two_pieces_gives_neither_its_count():
    parts = _insert(); parts[4]["overall_length_mm"] = 290.0      # now two 290 x 260 panels
    M.pieces_take_their_parts_count_and_material(parts, _table()); by = _by(parts)
    assert by["T-01A-01"]["quantity"] == 1 and by["T-01A-04"]["quantity"] == 1
    assert by["T-01A-03"]["quantity"] == 2


def test_another_parts_table_and_a_coded_row_are_not_used():
    parts = _insert()
    M.pieces_take_their_parts_count_and_material(parts, _table(parent="T-99"))
    assert all(_by(parts)[f"T-01A-0{n}"]["quantity"] == 1 for n in (1, 2, 3, 4))
    coded = [dict(r, part_number="T-55") if r.get("bom_item_no") else r for r in _table()]
    parts = _insert(); M.pieces_take_their_parts_count_and_material(parts, coded)
    assert all(_by(parts)[f"T-01A-0{n}"]["quantity"] == 1 for n in (1, 2, 3, 4))


def test_a_gauge_that_differs_is_not_the_same_row():
    parts = _insert(); parts[1]["normalized_thickness_mm"] = 5.0
    M.pieces_take_their_parts_count_and_material(parts, _table())
    assert _by(parts)["T-01A-01"]["quantity"] == 1
