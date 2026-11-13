"""THE AI COST GOES UNDER ITS OWN HEADER, FOR THE QUANTITY PRICED (reviewer, 13 Nov 2026).

"Its AiCost header is in column P; the network copy previously used Q. Resolve each
workbook's target by its header, validate drawing and quantity, preserve other cells and
read the saved value back." The two writers that already exist are extended; no third.
"""
import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tti_central as C  # noqa: E402
import tti_pricer as P  # noqa: E402

REF = lambda s: "".join(str(s).split()).upper()  # noqa: E731


def _book(path, cost_header="AiCost", cost_col=16, extra_cost_col=None, other_header_at=None):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Milwaukee"
    ws.cell(1, 12, "Drawing Number"); ws.cell(1, 13, "Notes"); ws.cell(1, 14, "Quantity")
    ws.cell(1, 15, "Budget"); ws.cell(1, 17, "Comments")
    if cost_header:
        ws.cell(1, cost_col, cost_header)
    if extra_cost_col:
        ws.cell(1, extra_cost_col, "AI Cost")
    if other_header_at:
        ws.cell(1, other_header_at[0], other_header_at[1])
    for r, (dwg, qty) in enumerate([("D-100", 5), ("D-200", 3), ("D-300", 10), ("D-300", 25)], start=2):
        ws.cell(r, 12, dwg); ws.cell(r, 14, qty); ws.cell(r, 15, "keep-O"); ws.cell(r, 17, "keep-Q")
    wb.save(path); return str(path)


def _cells(path):
    ws = openpyxl.load_workbook(path)["Milwaukee"]
    return {(r, c): ws.cell(r, c).value for r in range(1, 6) for c in range(1, 19)}


# ── the central sheet ───────────────────────────────────────────────────────────────────
def test_the_header_is_found_however_it_is_spelt_and_wherever_it_sits(tmp_path):
    for n, (head, col) in enumerate([("AiCost", 16), ("AI Cost", 18), ("ai cost", 11)]):
        path = _book(tmp_path / f"b{n}.xlsx", head, col)
        res = C.write(path, "Milwaukee", "D-200", None, 123.45, REF, quantity=3)
        assert res["ok"], res
        assert _cells(path)[(3, col)] == 123.45


def test_only_the_one_cell_changes(tmp_path):
    path = _book(tmp_path / "b.xlsx")
    before = _cells(path)
    assert C.write(path, "Milwaukee", "D-100", None, 88.0, REF, quantity=5)["ok"]
    after = _cells(path)
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {(2, 16)} and after[(2, 15)] == "keep-O" and after[(2, 17)] == "keep-Q"


def test_a_row_for_another_quantity_is_not_written(tmp_path):
    path = _book(tmp_path / "b.xlsx")
    before = _cells(path)
    res = C.write(path, "Milwaukee", "D-200", None, 50.0, REF, quantity=8)
    assert not res["ok"] and "priced at 8 off" in res["said"] and "row 3: 3" in res["said"]
    assert _cells(path) == before


def test_the_quantity_picks_the_row_when_a_drawing_is_on_two(tmp_path):
    path = _book(tmp_path / "b.xlsx")
    assert C.write(path, "Milwaukee", "D-300", None, 9.5, REF, quantity=25)["ok"]
    cells = _cells(path)
    assert cells[(5, 16)] == 9.5 and cells[(4, 16)] is None


def test_without_a_quantity_the_writer_behaves_as_before(tmp_path):
    path = _book(tmp_path / "b.xlsx")
    assert C.write(path, "Milwaukee", "D-100", None, 7.0, REF)["ok"]
    res = C.write(path, "Milwaukee", "D-300", None, 7.0, REF)
    assert not res["ok"] and "rows 4, 5" in res["said"]


# ── the network copy ────────────────────────────────────────────────────────────────────
def _read(path, col):
    return P.read_rows(Path(path), {"drawing": "L", "notes": "M", "thumbs": ["A"], "cost": col, "qty": ""},
                       None, "Milwaukee")


def test_the_network_copys_column_is_found_by_its_header_not_its_letter(tmp_path):
    data = _read(_book(tmp_path / "p.xlsx", "AiCost", 16), "Q")
    assert data["cost_column"] == "P" and "column P is used" in data["cost_column_said"]
    assert _read(_book(tmp_path / "q.xlsx", "AI Cost", 17 + 1), "P")["cost_column"] == "R"
    same = _read(_book(tmp_path / "s.xlsx", "AiCost", 16), "P")
    assert same["cost_column"] == "P" and same["cost_column_said"] == ""


def test_a_cost_is_never_written_under_another_heading(tmp_path):
    path = _book(tmp_path / "p.xlsx", cost_header=None)
    with pytest.raises(SystemExit) as stop:
        _read(path, "O")
    assert "headed 'Budget'" in str(stop.value) and "Nothing is written" in str(stop.value)


def test_an_unheaded_column_named_on_the_command_line_is_still_accepted(tmp_path):
    data = _read(_book(tmp_path / "p.xlsx", cost_header=None), "P")
    assert data["cost_column"] == "P"


def test_two_ai_cost_columns_stop_the_run(tmp_path):
    with pytest.raises(SystemExit) as stop:
        _read(_book(tmp_path / "p.xlsx", "AiCost", 16, extra_cost_col=18), "P")
    assert "2 columns headed AI Cost" in str(stop.value)


def test_the_batch_writes_to_the_column_the_header_names():
    src = (ROOT / "src" / "tti_pricer.py").read_text(encoding="utf-8")
    assert 'args.col_cost = data["cost_column"]' in src
    assert 'cost, drawing_ref, quantity=r.get("quantity"))' in src
