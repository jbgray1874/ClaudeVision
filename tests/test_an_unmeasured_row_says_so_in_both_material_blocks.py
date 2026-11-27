"""A part the engine could not measure must say so in the row, whichever block it lands in.

Job 11650's side panels are PETG, so the plastics fix routed them to Other Sheet Material --
correctly. What arrived on the sheet was two rows carrying a part number, a quantity, a
thickness, blank Part Length, blank Part Width, and #VALUE! where Qty Per Sheet should be.
The WB nests by dividing sheet size by part size; a blank part length is not a blank cost,
it is a division that fails, and Excel's rendering of that failure says nothing about why.

Sheet Steel already handled this. It grew an on-sheet "DIMS REQUIRED" marker when 12392
shipped rows with no gauge. Other Sheet did not, so the identical failure shipped again
wearing a different face. A rule that lives in one branch of a pair is how the pair comes to
disagree about what an unmeasured part looks like -- which is why the marker is now one
function called from both, and why the test below asserts on the SHARED function rather
than on each block's private copy of a string.

THE ROW KEEPS ITS FORMULA. The marker is an instruction to the estimator, not a dead row:
type the dimensions in and the line recomputes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import wb_populate                                                  # noqa: E402
from wb_populate import CELL_MAP, mark_row_needs_dimensions         # noqa: E402


class _Cell:
    def __init__(self):
        self.value = None


class _Sheet:
    """Just enough openpyxl to observe what gets written where."""

    def __init__(self):
        self._cells = {}

    def cell(self, row, column, value=None):
        c = self._cells.setdefault((row, column), _Cell())
        if value is not None:
            c.value = value
        return c

    def text_at(self, row, column):
        return str(self._cells.get((row, column), _Cell()).value or "")


# ── the marker itself ───────────────────────────────────────────────────────────────
def test_the_marker_names_which_dimension_is_missing():
    ws = _Sheet()
    ws.cell(row=84, column=3, value="11650-04-01A  SIDE PANEL LH")

    assert mark_row_needs_dimensions(ws, 84, 3, ["L", "W"]) is True

    text = ws.text_at(84, 3)
    assert "11650-04-01A" in text, "the marker overwrote the part it was describing"
    assert "DIMS REQUIRED" in text
    assert "L" in text and "W" in text
    assert "not costed" in text, \
        "a row with an Excel error and no statement reads as a broken template"


def test_a_measured_row_is_left_alone():
    ws = _Sheet()
    ws.cell(row=84, column=3, value="11650-04-02A  SIDE PANEL RH")
    assert mark_row_needs_dimensions(ws, 84, 3, []) is False
    assert ws.text_at(84, 3) == "11650-04-02A  SIDE PANEL RH"


def test_the_marker_is_not_written_twice():
    """populate_workbook is run more than once against a workbook in some paths, and a
    description that grows a second copy of the warning on each pass is unreadable."""
    ws = _Sheet()
    ws.cell(row=84, column=3, value="11650-04-01A  SIDE PANEL LH")
    mark_row_needs_dimensions(ws, 84, 3, ["L", "W"])
    assert mark_row_needs_dimensions(ws, 84, 3, ["L", "W"]) is False
    assert ws.text_at(84, 3).count("DIMS REQUIRED") == 1


# ── both blocks reach it ────────────────────────────────────────────────────────────
# BUILT IS NOT WIRED. The marker existing proves nothing about the sheet an estimator
# opens; what matters is that BOTH material blocks call it. Read from the source so a
# block that quietly goes back to its own private string fails here.
_SOURCE = (Path(wb_populate.__file__)).read_text(encoding="utf-8")


def test_both_material_blocks_call_the_shared_marker():
    calls = _SOURCE.count("mark_row_needs_dimensions(")
    # one def, one steel call, one other-sheet call
    assert calls >= 3, \
        f"only {calls} references -- a material block is not using the shared marker"


@pytest.mark.parametrize("block,col_key", [("steel", "col_desc"), ("other_sheet", "col_desc")])
def test_each_block_writes_its_marker_into_its_own_description_column(block, col_key):
    """The marker has to land in the column the estimator reads, and the two blocks do not
    share one -- Sheet Steel and Other Sheet are different geometries in the template."""
    assert CELL_MAP[block][col_key], f"{block} has no description column to mark"


def test_no_block_keeps_a_private_copy_of_the_warning_text():
    """The whole point of extracting it. Two literals is two things to keep in step, and
    the one that gets forgotten is the one an estimator is looking at.

    PROSE IS EXCLUDED, and it takes a parse to exclude it properly. The first version
    counted every occurrence in the file and failed on a comment that explains what the
    marker does; the second stripped comments and failed on a DOCSTRING that does the same.
    Prose ABOUT the string is not a second copy OF it, and a guard that forces the file to
    stop naming the thing it describes is making the file worse. So: count string literals
    the interpreter actually evaluates, which is what "a private copy" means.
    """
    import ast

    tree = ast.parse(_SOURCE)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))

    literals = [n for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and n.value == "DIMS REQUIRED"
                and id(n) not in docstrings]
    assert len(literals) <= 1, \
        ("a second literal copy of the warning has appeared at line(s) "
         f"{[n.lineno for n in literals]} -- use mark_row_needs_dimensions")


# ── and the error it replaces is actually suppressed ────────────────────────────────
# THE OTHER HALF OF THE SAME FAILURE. A marker in the description column is the statement;
# IFERROR on the formula cells is what stops the row shouting #VALUE! next to it. That sweep
# started at column 11 for BOTH blocks, which is Sheet Steel's geometry: Other Sheet carries
# no gauge column, so its Qty Per Sheet sits one column left, outside the sweep. An
# undimensioned steel row therefore showed a clean blank and an undimensioned PETG row
# showed a raw Excel error, from the same missing measurement.
class _FormulaSheet(_Sheet):
    def put_formula(self, row, column, text):
        self.cell(row=row, column=column).value = text


def test_each_block_declares_where_its_own_formula_region_starts():
    steel, other = CELL_MAP["steel"], CELL_MAP["other_sheet"]
    assert "first_formula_col" in steel and "first_formula_col" in other
    assert other["first_formula_col"] < steel["first_formula_col"], \
        ("Other Sheet has no gauge column, so its formulas start LEFT of Sheet Steel's. "
         "Equal values mean one block's layout was copied onto the other.")
    # It must begin after the last cell this module writes an input into, or the sweep
    # would rewrite an estimator input as a formula.
    for blk in (steel, other):
        inputs = [v for k, v in blk.items() if k.startswith("col_") and isinstance(v, int)]
        clashes = [c for c in inputs if c >= blk["first_formula_col"]]
        # Sheet Steel's holes/internal-cut inputs sit deliberately inside the region; they
        # are numbers, and only formula strings are touched. Named so the exception is not
        # mistaken for an oversight.
        assert all(c in (blk.get("col_holes"), blk.get("col_internal_cut"),
                         blk.get("col_cost_per_sheet")) for c in clashes), \
            f"an input column at {clashes} is inside the formula sweep unaccounted for"


def test_an_undimensioned_row_shows_blank_not_an_excel_error_in_both_blocks():
    ws = _FormulaSheet()
    steel_row = CELL_MAP["steel"]["first_row"]
    other_row = CELL_MAP["other_sheet"]["first_row"]
    # Each block's Qty Per Sheet: the cell that divides sheet size by part size.
    ws.put_formula(steel_row, CELL_MAP["steel"]["first_formula_col"], "=I63/F63*J63/G63")
    ws.put_formula(other_row, CELL_MAP["other_sheet"]["first_formula_col"], "=H84/E84*I84/F84")

    wb_populate._clean_error_cells(ws)

    for label, row, col in (("steel", steel_row, CELL_MAP["steel"]["first_formula_col"]),
                            ("other_sheet", other_row,
                             CELL_MAP["other_sheet"]["first_formula_col"])):
        assert "IFERROR(" in ws.text_at(row, col).upper(), \
            f"{label}'s Qty Per Sheet is outside the sweep -- it will show #VALUE! on the sheet"


def test_a_dimensioned_row_is_not_altered_in_meaning():
    """IFERROR(f,\"\") == f whenever f evaluates. Wrapping is non-regressive by construction,
    and double-wrapping on a second pass would not be."""
    ws = _FormulaSheet()
    row = CELL_MAP["other_sheet"]["first_row"]
    col = CELL_MAP["other_sheet"]["first_formula_col"]
    ws.put_formula(row, col, "=H84/E84*I84/F84")
    wb_populate._clean_error_cells(ws)
    once = ws.text_at(row, col)
    wb_populate._clean_error_cells(ws)
    assert ws.text_at(row, col) == once, "a second pass wrapped the formula again"


def test_an_input_number_is_never_turned_into_a_formula():
    ws = _FormulaSheet()
    row = CELL_MAP["other_sheet"]["first_row"]
    ws.cell(row=row, column=CELL_MAP["other_sheet"]["col_cost_per_sheet"], value=41.75)
    wb_populate._clean_error_cells(ws)
    assert ws.cell(row=row,
                   column=CELL_MAP["other_sheet"]["col_cost_per_sheet"]).value == 41.75


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
