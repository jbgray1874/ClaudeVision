"""THE TUBE AND PRINT CALCULATORS ARE READ AS ESTIMATING KEEPS THEM (JG, 13 Nov 2026).

"wire in the two new calculators". Each is named by its own setting, as the box calculator
is. Unset, nothing changes. The workbooks built here follow the layout of the two files
uploaded on 13 Nov; no customer data is in them.
"""
import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import print_calculator_sheet as P  # noqa: E402
import tube_calculator_sheet as T  # noqa: E402


def _tube_book(path, head=None):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(head or ["Part", None, "Description 3", "Material Cost", "Cut cost", "Cost per hole",
                       "Cost per Slot", "Cost per Mitre"])
    ws.append(["TUBE84", "30 x 30 x 1.5mm (6.1m)", "ERW SQUARE. 30 x 30 x 1.5mm (6.1m)", 17.5, 0.1, 0.1, 0.15, 0.2])
    ws.append(["TUBE02", "40 x 10 x 1.5mm (6.1m)", "ERW RECT. 40 x 10 x 1.5mm (6.1m)", 16.95, 0.1, 0.18, 0.35, 0.2])
    ws.append(["TUBE99", "no price", "ERW ROUND", None, 0.1, 0.1, 0.1, 0.1])
    wb.save(path); return str(path)


def _print_book(path, scrap=-0.7):
    wb = openpyxl.Workbook(); ws = wb.active
    ws["A1"], ws["C1"], ws["D1"], ws["E1"] = "AI BUDGET COSTING", "Sheet Size", "Set-up Cost", "Run Cost (print & cut)"
    for r, row in enumerate([("3mm White Foamed PVC", "Full colour digital 1 side", "1220x2440mm", 40, 107),
                             ("2mm Display Board", "Full colour digital 1 side", "1220x2440mm", None, 65.22),
                             ("2mm clear PETG", "Solid White and Full colour", "1250x2050mm", None, 173.96)], start=2):
        for c, v in enumerate(row, start=1):
            ws.cell(r, c, v)
    ws["A9"], ws["I9"], ws["I10"] = "Material", "Scrap %", scrap
    wb.save(path); return str(path)


# ── tube ────────────────────────────────────────────────────────────────────────────────
def test_unset_the_tube_calculator_changes_nothing(monkeypatch):
    monkeypatch.delenv("SDI_TUBE_CALCULATOR_XLSX", raising=False)
    existing = [("TUBE84", "ERW SQUARE 30x30x1.5", 20.0, "A Supplier", "EA")]
    rows, said = T.merged_with(existing)
    assert rows is existing and said["used"] is False and "not set" in said["why_not"]


def test_the_calculators_price_takes_its_own_code_and_other_rows_are_kept(tmp_path):
    read = T.read_sheet(_tube_book(tmp_path / "t.xlsx"))
    assert read["ok"] and [r["code"] for r in read["rows"]] == ["TUBE84", "TUBE02"]
    existing = [("TUBE84", "ERW SQUARE 30x30x1.5", 20.0, "A Supplier", "EA"),
                ("RHS-60-30", "RHS 60x30x1.5", 31.0, "A Supplier", "EA")]
    rows, said = T.merged_with(existing, read)
    by = {r[0]: r for r in rows}
    assert by["TUBE84"][2] == 17.5 and by["TUBE84"][3] == "AI Tube calculator"
    assert by["RHS-60-30"][2] == 31.0 and by["TUBE02"][2] == 16.95 and len(rows) == 3
    assert said["used"] and said["replaced"] == ["TUBE84"] and said["added"] == ["TUBE02"]


def test_a_tube_sheet_laid_out_differently_is_refused_not_half_read(tmp_path):
    bad = _tube_book(tmp_path / "t.xlsx", head=["Part", None, "Description", "Cut cost", "Material Cost", "x", "y", "z"])
    read = T.read_sheet(bad)
    assert not read["ok"] and "layout has changed" in read["why"]
    rows, said = T.merged_with([("A", "b", 1.0, "s", "EA")], read)
    assert len(rows) == 1 and said["used"] is False


def test_the_cut_hole_slot_and_mitre_rates_are_read_and_applied_to_nothing(tmp_path):
    read = T.read_sheet(_tube_book(tmp_path / "t.xlsx"))
    got = T.rates_for("tube02", read)
    assert got == {"cut_gbp": 0.1, "hole_gbp": 0.18, "slot_gbp": 0.35, "mitre_gbp": 0.2,
                   "code": "TUBE02", "source": "AI Tube calculator", "applied": False}
    assert T.rates_for("NOPE", read) is None


def test_the_engine_joins_the_calculators_rows_to_its_tube_prices():
    est = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    at = est.index("_tube_calc.merged_with(rows)")
    assert at < est.index('_SECTION_ROWS_CACHE["rows"] = rows', at)


def test_each_rows_stock_length_is_read_from_the_row_and_never_assumed(tmp_path):
    assert T.stated_stock_length_m("ERW SQUARE. 30 x 30 x 1.5mm (6.1m)") == 6.1
    assert T.stated_stock_length_m("ERW ROUND 25.4 x 1.5mm (7.5 m)") == 7.5
    assert T.stated_stock_length_m("ERW RECT. 40 x 10 x 1.5mm") is None, "the 1.5mm gauge is not a length"
    assert T.stated_stock_length_m("TUBE (6.1m) or (3m)") is None, "two lengths is not one"
    wb = openpyxl.load_workbook(_tube_book(tmp_path / "t.xlsx")); ws = wb.active
    ws.append(["TUBE77", "50 x 25 x 1.5mm", "ERW RECT. 50 x 25 x 1.5mm", 22.0, 0.1, 0.1, 0.1, 0.1])
    ws.append(["TUBE78", "20 x 20 (7.5m)", "ERW SQUARE 20 x 20 (7.5m)", 19.0, 0.1, 0.1, 0.1, 0.1])
    wb.save(tmp_path / "t.xlsx")
    read = T.read_sheet(str(tmp_path / "t.xlsx"))
    by = {r["code"]: r for r in read["rows"]}
    assert by["TUBE84"]["stock_length_m"] == 6.1 and by["TUBE78"]["stock_length_m"] == 7.5
    assert by["TUBE77"]["stock_length_m"] is None and by["TUBE77"]["unit"] == "NOT STATED on the row"
    odd = T.rows_without_a_stated_length(read)
    assert [o["code"] for o in odd] == ["TUBE77"]
    existing = [("TUBE77", "ERW RECT 50x25x1.5", 30.0, "A Supplier", "EA")]
    rows, said = T.merged_with(existing, read)
    kept = {r[0]: r for r in rows}
    assert kept["TUBE77"][2] == 30.0 and kept["TUBE77"][3] == "A Supplier", "an unstated unit replaces no price"
    assert said["not_used_no_stated_length"] == ["TUBE77"] and said["stock_lengths_m"] == [6.1, 7.5]


# ── print ───────────────────────────────────────────────────────────────────────────────
def test_the_print_sheet_is_worked_cell_for_cell(tmp_path):
    read = P.read_sheet(_print_book(tmp_path / "p.xlsx"))
    assert read["ok"] and len(read["substrates"]) == 3 and read["scrap"] == -0.7
    got = P.as_the_sheet_works_it(read, "2mm clear PETG", 500, 250, 175)
    # H10: INT((2050-5)/(250+20)) * INT(1250/(500+20)) = 7 * 2 = 14
    assert got["parts_per_sheet"] == 14
    # K10: (173.96/14) * (1 - 0.7) ; I2: 40/175 + K10
    assert got["cost_per_part_gbp"] == pytest.approx(173.96 / 14 * 0.3, abs=1e-4)
    assert got["total_gbp"] == pytest.approx(40 / 175 + 173.96 / 14 * 0.3, abs=1e-4)
    assert got["applied"] is False


def test_what_estimating_has_to_confirm_is_said_not_corrected(tmp_path):
    read = P.read_sheet(_print_book(tmp_path / "p.xlsx"))
    said = P.points_to_confirm(read)
    assert any("-0.7" in s and "30%" in s for s in said)
    assert any("1 of 3 substrates" in s for s in said) and any("one orientation" in s for s in said)
    clean = P.points_to_confirm(P.read_sheet(_print_book(tmp_path / "q.xlsx", scrap=0.1)))
    assert not any("reduction" in s for s in clean)


def test_a_part_that_does_not_fit_or_an_unknown_substrate_is_refused(tmp_path):
    read = P.read_sheet(_print_book(tmp_path / "p.xlsx"))
    assert P.parts_per_sheet(3000, 250, [1250, 2050]) == 0
    assert "does not fit" in P.as_the_sheet_works_it(read, "2mm clear PETG", 3000, 250, 10)["why"]
    assert "not a substrate" in P.as_the_sheet_works_it(read, "Brass", 100, 100, 10)["why"]


def test_unset_the_print_calculator_is_not_read(monkeypatch):
    monkeypatch.delenv("SDI_PRINT_CALCULATOR_XLSX", raising=False)
    read = P.read_sheet()
    assert not read["ok"] and "not set" in read["why"]


def test_the_print_calculator_prices_no_estimate_line_yet():
    for f in ("estimator.py", "commercial_lines.py", "file_scan.py", "wb_populate.py"):
        assert "print_calculator_sheet" not in (ROOT / "src" / f).read_text(encoding="utf-8"), f
