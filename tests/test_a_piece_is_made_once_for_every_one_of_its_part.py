"""A PIECE IS MADE ONCE FOR EVERY ONE OF ITS PART, AND THE PART GRAPH DOES THE MULTIPLYING.

13 Nov 2026: one bin piece carried no material, though the bin's own sheet states it, and the
12424-02-GA insert's own table lists its panels 2, 1, 2 and 3 by size.

14 Nov 2026, CORRECTED. The first version of these tests asserted that a door piece's own
count became the door's 3 ("three flats priced once each"). That was a misreading: the part
graph already charged each door piece 3, door x3 -> piece x1. With 3 written into the piece,
the graph took it as per door and 6364-02's door pieces were charged 9 each. Those assertions
are replaced, not loosened: every count here is now checked where it is charged, the part
graph's figure per finished product, and the old 9 is pinned as the failure it was.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import drawing_job_merge as M  # noqa: E402
import route_compiler as RC  # noqa: E402
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
    # every piece is listed under its part, as the DXF merge leaves it
    door["assembly_children"] = ["T-011-5MM", "T-011-3MM"]
    bin_["assembly_children"] = ["T-004-01", "T-004-09"]
    return [door, bin_,
            _part("T-011-5MM", 1, "inference", "PETG", "dxf_filename", 5.0, of="T-011"),
            _part("T-011-3MM", 1, "inference", "PETG", "dxf_filename", 3.0, of="T-011"),
            _part("T-004-01", 1, "inference", of="T-004"),
            _part("T-004-09", 1, "inference", "PETG", "dxf_filename", 3.0, of="T-004"),
            _part("T-020", 2, "bom_tree")]


def _by(parts):
    return {p["part_number"]: p for p in parts}


def _charged(parts, bom_rows=None, top="T-GA"):
    """What the workbook costs: the part graph's count per finished product."""
    import contextlib
    import io
    ga = _part(top, 1, "drawing_deterministic")
    ga["assembly_children"] = [p["part_number"] for p in parts
                               if not p.get("dxf_minted_piece_of")]
    with contextlib.redirect_stdout(io.StringIO()):
        g = RC.build_part_graph([ga] + parts, {}, bom_rows or [])
    return {k: v for k, v in (g.get("quantities") or {}).items()}


def test_each_door_piece_is_charged_once_a_door_not_three_times_a_door():
    """6364-02, 13 Nov: three doors, each piece charged 9. The charge is 3."""
    parts = _job(); M.pieces_take_their_parts_count_and_material(parts)
    charged = _charged(parts)
    assert charged["T-011-5MM"] == 3 and charged["T-011-3MM"] == 3
    assert _by(parts)["T-011-5MM"]["quantity"] == 1, "a piece's own count is per one door"
    assert "quantity_from_its_part" not in _by(parts)["T-011-5MM"]


def test_the_rule_as_first_released_is_the_nine_it_charged():
    """The failure itself, kept: a piece holding its part's count is multiplied again."""
    parts = _job()
    for pn in ("T-011-5MM", "T-011-3MM"):
        apply_field(_by(parts)[pn], "quantity", 3, "bom_tree_per_unit")
    assert _charged(parts)["T-011-5MM"] == 9


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
    parts = _insert()
    first = M.pieces_take_their_parts_count_and_material(parts, _table())
    assert first and M.pieces_take_their_parts_count_and_material(parts, _table()) == []
    assert _charged(parts, _table())["T-01A-04"] == 3


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
    insert = _part("T-01A", 1, "solidworks_api", "ACRYLIC", "drawing_deterministic", 3.0)
    insert["assembly_children"] = [f"T-01A-0{n}" for n in (1, 2, 3, 4)]
    return [insert,
            panel(1, 290.0, 260.0), panel(2, 358.0, 264.0), panel(3, 358.0, 290.0), panel(4, 293.0, 260.0)]


def _table(parent="T-01A"):
    row = lambda i, d, q: {"part_number": "", "description": d, "quantity": q,  # noqa: E731
                           "bom_parent": parent, "bom_item_no": str(i)}
    return [{"part_number": "T-01A", "description": "INSERT", "quantity": 1, "bom_parent": "T-GA"},
            row(1, "290 x 260 x 3 mm", 2), row(2, "358 x 264 x 3 mm", 1),
            row(3, "358 x 290 x 3 mm", 2), row(4, "293 x 260 x 3 mm", 3)]


def test_all_eight_panels_reach_costing():
    parts = _insert(); M.pieces_take_their_parts_count_and_material(parts, _table()); by = _by(parts)
    charged = _charged(parts, _table())
    assert [charged[f"T-01A-0{n}"] for n in (1, 2, 3, 4)] == [2, 1, 2, 3]
    assert sum(charged[f"T-01A-0{n}"] for n in (1, 2, 3, 4)) == 8
    took = by["T-01A-04"]["quantity_from_its_part"]
    assert took["per_part"] == 3 and "293 x 260 x 3 mm" in took["basis"] and "item 4" in took["basis"]
    assert "the part graph multiplies" in took["basis"]


def test_the_tables_count_is_multiplied_by_the_parts_own_once():
    """Five inserts: 10 of the 2-off panel and 5 of the 1-off, charged. Not 50 and 25."""
    parts = _insert()
    five = _part("T-01A", 5, "solidworks_api", "ACRYLIC", "drawing_deterministic", 3.0)
    five["assembly_children"] = parts[0]["assembly_children"]
    parts[0] = five
    M.pieces_take_their_parts_count_and_material(parts, _table())
    assert _by(parts)["T-01A-01"]["quantity"] == 2, "the piece holds its count per insert"
    charged = _charged(parts, _table())
    assert charged["T-01A-01"] == 10 and charged["T-01A-02"] == 5 and charged["T-01A-04"] == 15


def test_a_piece_not_under_its_part_is_not_given_a_count_the_graph_would_not_multiply():
    parts = _insert(); parts[0]["assembly_children"] = ["T-01A-02", "T-01A-03", "T-01A-04"]
    M.pieces_take_their_parts_count_and_material(parts, _table())
    assert _by(parts)["T-01A-01"]["quantity"] == 1 and "quantity_from_its_part" not in _by(parts)["T-01A-01"]
    assert _by(parts)["T-01A-04"]["quantity"] == 3


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
