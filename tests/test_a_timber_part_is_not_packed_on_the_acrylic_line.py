r"""
test_a_timber_part_is_not_packed_on_the_acrylic_line.py

"Assemble/pack (Acrylic) — 3mm MDF"

One labour row that contradicts itself in eight words, and it went out to estimating on
11908-21. _is_board() lumps timber in with acrylic because neither is sheet metal, which is
the right call for choosing a cost stream and the wrong one for naming a DEPARTMENT, so the
acrylic map named the department after a material the part is not.

THE COMMENT THAT KEPT IT THERE. Beside _is_timber stood a note saying the workbook template
has no joinery Assemble/pack, so a timber part has to take the nearest hand rate. That was
not true. sheet_steel_costing.RATE_CARD — read off the sheet's own rate card rows — carries
"Packing Joinery" (PACJ, £28.735) and "Bench Work Joinery" (BENC, £28.735), and
department_codes marks both as titles this engine has already put on a sheet and seen come
back with a live rate. Timber was packed at the acrylic rate, £25.4257, because a comment
said the row did not exist and nobody asked the rate card.

The first test here asks the rate card. It is the one that would have stopped this.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sheet_steel_costing as ssc                                  # noqa: E402
import wb_populate as wb                                           # noqa: E402
from department_codes import CODE_TITLES                           # noqa: E402

SRC = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")


# ── the premise ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,code", [("Packing Joinery", "PACJ"),
                                        ("Bench Work Joinery", "BENC"),
                                        ("CNC Joinery", "CNCJ")])
def test_the_rate_card_has_a_joinery_row_after_all(title, code):
    """The claim the old comment rested on, asked of the rate card instead of a memory."""
    assert title in ssc.RATE_CARD, f"{title} is not on the rate card"
    rate, _setup, dept = ssc.RATE_CARD[title]
    assert dept == code and rate > 0
    assert CODE_TITLES[code] == (title, True), "the two records of this title disagree"


def test_joinery_pack_is_not_the_acrylic_rate():
    """If they were the same number none of this would matter. They are not: every timber
    job so far was packed 11.5% cheap."""
    assert ssc.RATE_CARD["Packing Joinery"][0] != ssc.RATE_CARD["Assemble/pack (Acrylic)"][0]


# ── the mapping ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("op", ["handling", "assembly", "assemble", "packing"])
def test_a_timber_part_packs_on_the_joinery_line(op):
    assert wb._map_operation(op, True, "", "3mm MDF") == "Packing Joinery"
    assert wb._map_operation(op, True, "", "MELAMINE FACED CHIPBOARD") == "Packing Joinery"


@pytest.mark.parametrize("op", ["handling", "assembly", "assemble"])
def test_an_acrylic_part_is_untouched(op):
    """The acrylic line is right for acrylic. This change must not move it."""
    assert wb._map_operation(op, True, "", "5mm ACRYLIC") == "Assemble/pack (Acrylic)"
    assert wb._map_operation(op, True, "", "PERSPEX") == "Assemble/pack (Acrylic)"


@pytest.mark.parametrize("op", ["handling", "assembly", "laser_cutting", "manual"])
def test_a_caller_that_passes_no_material_behaves_exactly_as_before(op):
    """The parameter is optional so every existing call site keeps working. It must give the
    same answer it gave yesterday when nothing is passed — otherwise this is not one change,
    it is a change everywhere the function is called."""
    assert wb._map_operation(op, True, "") == wb.OP_NAME_MAP_ACRYLIC.get(
        op, wb.OP_NAME_MAP.get(op))


def test_a_cut_on_board_goes_to_the_router_not_the_acrylic_laser():
    assert wb._map_operation("laser_cutting", True, "", "9mm MDF") == "CNC Joinery"
    assert wb._map_operation("laser", True, "", "PLYWOOD") == "CNC Joinery"
    assert wb._map_operation("laser_cutting", True, "", "5mm ACRYLIC") == "Laser (Acrylic)"


def test_veneered_acrylic_is_still_acrylic():
    """_is_timber already refuses to claim a laminated acrylic product for joinery. Asserted
    here because this map is now the thing that would get it wrong."""
    assert wb._map_operation("assembly", True, "", "ACRYLIC, MDF BACKED") == \
        "Assemble/pack (Acrylic)"


def test_a_tube_is_still_settled_first():
    """Order matters: the tube remap runs before all of this and must keep doing so."""
    assert wb._map_operation("folding", True, "tube", "MDF") == "Tubebend"


# ── every name it can produce has to be a row the sheet knows ──────────────────

def test_every_joinery_department_is_a_real_rate_card_row():
    """A department name the rate table does not carry LOOKUPs to zero — the line appears on
    the sheet, costs nothing, and is indistinguishable from work nobody found. That is how
    every deburr on every job priced at £0 for months."""
    for op, name in wb.OP_NAME_MAP_JOINERY.items():
        assert name in ssc.RATE_CARD, f"{op} -> {name!r} is not a rate card row"


# ── and it has to be treated as a pack row, not as a new kind of thing ─────────

def _dict_keys_of_literal_containing(marker: str) -> set:
    """The keys of the dict literal in wb_populate that carries `marker`. Read from the AST
    rather than by grep: these tables live inside functions, and a test that matches text
    passes on a line that was typed and deleted again."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if marker in keys:
            return keys
    raise AssertionError(f"no dict literal carries {marker!r}")


def _set_elements_of_literal_containing(marker: str) -> set:
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Set):
            continue
        vals = {e.value for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if marker in vals and "Assemble/pack (Metal)" in vals:
            return vals
    raise AssertionError(f"no set literal carries {marker!r}")


def test_a_timber_job_books_one_pack_row_for_the_job():
    """Metal and acrylic book one pack row per JOB. Left out of those sets, a timber job
    would book one per PART — the exact thing the sets exist to prevent, arriving quietly on
    the first job that used them."""
    src = SRC[SRC.index("_ONE_ROW_PER_JOB = {"):]
    src = src[:src.index("\n\n")]
    assert "Packing Joinery" in src
    assert "Packing Joinery" in _set_elements_of_literal_containing("Weld (CO2)")


def test_the_pack_family_has_three_members_everywhere_it_has_two():
    """Wherever the two pack departments are named together, the third belongs with them."""
    import re
    for m in re.finditer(r'"Assemble/pack \(Metal\)"[^\n]*"Assemble/pack \(Acrylic\)"',
                         SRC):
        line_end = SRC.index("\n", m.end())
        window = SRC[m.start():line_end + 200]
        assert "Packing Joinery" in window, (
            f"the pack family is named at offset {m.start()} without its joinery member")


@pytest.mark.parametrize("name", ["Packing Joinery", "Bench Work Joinery"])
def test_a_joinery_row_has_a_throughput_to_cost_against(name):
    """Without one the engine's own reading stands, and its reading of a hand operation has
    been 0.88 parts an hour — a grouped line billed at twenty-two hours to box a tray."""
    assert name in _dict_keys_of_literal_containing("Assemble/pack (Acrylic)")


@pytest.mark.parametrize("name", ["Packing Joinery", "Bench Work Joinery"])
def test_a_joinery_row_knows_where_it_sits_in_the_route(name):
    assert name in _dict_keys_of_literal_containing("Laser (Metal)")


# ── EVERY PLACE THAT ASKS THE QUESTION ─────────────────────────────────────────
#
# 11908-21 came back reading "Assemble/pack (Acrylic) — 3mm MDF" with this fix already in.
# _map_operation is called from TWO places, and the fix was applied to one of them — the other
# is the CANONICAL ROUTE path, which is the one every current job actually goes through. A
# rule that only one of two callers obeys is not a rule.

def test_every_caller_hands_it_the_material():
    """Structural, by AST: the parameter exists so a timber part can reach the joinery
    departments, and a caller that omits it silently gets the old answer."""
    import ast
    tree = ast.parse(SRC)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_map_operation"]
    assert len(calls) >= 2, "the call sites have moved; this test is looking at the wrong thing"
    for c in calls:
        got = len(c.args) + len(c.keywords)
        assert got >= 4, (
            f"a _map_operation call at line {c.lineno} passes {got} argument(s) and never "
            f"names the material — a timber part there still books on the acrylic line")


def test_the_canonical_route_is_one_of_them():
    """Named explicitly, because it is the path the live jobs take and the one that was
    missed. If this call ever stops passing `material`, the symptom is a label nobody can
    explain on a sheet in front of an estimator."""
    assert "_map_operation(operation, is_acrylic, stock_form, material)" in SRC


def test_the_weld_guard_reaches_the_canonical_route_too():
    """Same two-callers problem, same rule: you cannot weld acrylic on either path."""
    i = SRC.index("_map_operation(operation, is_acrylic, stock_form, material)")
    block = SRC[i:i + 1200]
    assert 'if is_acrylic and not _is_timber(material) and wb_op in ("Weld (CO2)", "Spotweld")' \
        in block
    assert 'wb_op = "Glue"' in block
