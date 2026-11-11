"""TTI: each finished row's spreadsheets and GA PDF are copied to the conference folder, and its AI
cost also reaches the central tracker (JG, 11 Nov 2026).

"save the GA PDF file for each job we run for TTI ... (keep the existing copy of ALL the output
files to where they get saved to now) to K:\\Estimating\\Completed\\Live Enquiries\\completed AI
briefs\\TTI\\TTI_Amsterdam-Conference" and "add the same AICost column to the sharepoint s/sheet
... the central s/sheet".
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import tti_central as tc                                          # noqa: E402
import tti_pricer as tp                                           # noqa: E402
from test_tti_pricer_prices_each_row_and_fills_ai_cost import (   # noqa: E402
    _Portal, _areas, _args, _quiet, _sheet)


def _central(path: Path, rows, with_cost=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Milwaukee"
    heads = ["Item Description", "Drawing Number", "Quantity", "Total Cost £"] + (["AI Cost"] if with_cost else [])
    ws.append(heads)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def test_the_central_row_is_found_by_its_drawing_number_not_its_position():
    grid = [["Item", "Drawing Number", "Qty"], ["Header sign", "TTI-55555", 2], ["Counter", "TTI-10234", 4]]
    p = tc.plan(grid, "TTI-10234", row_hint=7, ref=tp.drawing_ref)
    assert p["row"] == 3 and p["drawing_col"] == 2 and p["cost_col"] is None and p["next_col"] == 4
    assert "no row" in tc.plan(grid, "TTI-99999", 3, tp.drawing_ref)["error"]
    twice = grid + [["Counter again", "TTI-10234", 1]]
    assert tc.plan(twice, "TTI-10234", 4, tp.drawing_ref)["row"] == 4, "the K: row decides between two"
    assert "rows 3, 4" in tc.plan(twice, "TTI-10234", 9, tp.drawing_ref)["error"], "else nothing is written"
    assert "Drawing Number" in tc.plan([["a", "b"]], "X", 1, tp.drawing_ref)["error"]


def test_the_central_sheet_gets_an_ai_cost_column_and_the_cost_on_the_right_row(tmp_path):
    c = _central(tmp_path / "central.xlsx", [["Header sign", "TTI-55555", 2, 10], ["Counter", "TTI-10234", 4, 20]])
    res = tc.write(str(c), "Milwaukee", "TTI-10234", 3, 123.46, tp.drawing_ref)
    assert res["ok"] and "added the AI Cost header" in res["said"]
    ws = openpyxl.load_workbook(c)["Milwaukee"]
    assert ws["E1"].value == "AI Cost" and ws["E3"].value == 123.46 and ws["E2"].value is None
    assert ws["D3"].value == 20, "nothing else moves"
    again = tc.write(str(c), "Milwaukee", "TTI-10234", 3, 120.0, tp.drawing_ref)
    assert again["ok"] and "added" not in again["said"] and openpyxl.load_workbook(c)["Milwaukee"]["E3"].value == 120.0


def test_no_central_sheet_set_writes_nothing():
    assert tc.write("", "Milwaukee", "TTI-10234", 3, 1.0, tp.drawing_ref) == {
        "ok": False, "said": "no central sheet set (SDI_TTI_CENTRAL_SHEET)"}


def test_the_spreadsheets_and_the_ga_pdf_are_copied_and_never_overwritten(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "TTI-10234_20261111_1208.xlsx").write_bytes(b"book")
    (out / "~$TTI-10234_20261111_1208.xlsx").write_bytes(b"lock")
    (out / "report.html").write_text("r")
    ga = tmp_path / "TTI-10234 rev B.pdf"
    ga.write_bytes(b"%PDF ga")
    manifest = {"drawing": "TTI-10234", "revision": "B", "members": [
        {"drawing": "TTI-10234", "revision": "B", "files": [{"path": str(ga), "format": "pdf"}]}]}
    dest = tmp_path / "TTI_Amsterdam-Conference"
    got = tp.copy_to_conference(str(dest), str(out), manifest, "TTI-10234")
    assert got == ["TTI-10234_20261111_1208.xlsx", "TTI-10234_GA_revB.pdf"]
    assert sorted(f.name for f in dest.iterdir()) == ["TTI-10234_20261111_1208.xlsx", "TTI-10234_GA_revB.pdf"]
    again = tp.copy_to_conference(str(dest), str(out), manifest, "TTI-10234")
    assert all("already there" in g for g in again)
    ga.write_bytes(b"%PDF ga, revised and longer")
    third = tp.copy_to_conference(str(dest), str(out), manifest, "TTI-10234")
    assert len(list(dest.iterdir())) == 3 and third[1].startswith("TTI-10234_GA_revB 20"), "beside, not over"
    assert (out / "report.html").exists() and (out / "TTI-10234_20261111_1208.xlsx").exists(), "a copy"
    assert tp.copy_to_conference("none", str(out), manifest, "TTI-10234") == []


def test_a_finished_row_is_copied_and_written_to_the_central_sheet(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    (out / "TTI-10234_book.xlsx").write_bytes(b"book")

    class P(_Portal):
        def status(self, run_id):
            st = super().status(run_id)
            st["output_path"] = str(out)
            return st
    central = _central(tmp_path / "central.xlsx", [["Counter unit", "TTI-10234", 4, 1]])
    dest = tmp_path / "conf"
    status = tmp_path / "s.json"
    rep = tp.run_batch(_args(sheet, rows="3", replace_costs=True, copy_to=str(dest), central_sheet=str(central),
                             sheet_name="Tracker"), portal=P(), status_path=status, sleep=lambda s: None)
    (r,) = rep["rows"]
    assert "TTI-10234_book.xlsx" in r["filed"] and r["central_ok"] and "row 2" in r["central"]
    assert openpyxl.load_workbook(central)["Milwaukee"]["E2"].value == 123.46
    (e,) = tp.load_ledger(tp.ledger_path(sheet, status)).values()
    assert e["central_ok"] and e["filed"]


def test_a_row_priced_before_this_existed_gets_its_copies_and_central_cost_once(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    status = tmp_path / "s.json"
    tp.run_batch(_args(sheet, rows="3", replace_costs=True, copy_to="none", sheet_name="Tracker"),
                 portal=_Portal(), status_path=status, sleep=lambda s: None)
    central = _central(tmp_path / "central.xlsx", [["Counter unit", "TTI-10234", 4, 1]])
    portal = _Portal()
    rep = tp.run_batch(_args(sheet, rows="3", copy_to="none", central_sheet=str(central), sheet_name="Tracker"),
                       portal=portal, status_path=status, sleep=lambda s: None)
    (r,) = rep["rows"]
    assert portal.started == [] and r["central_ok"], "not run again: only the central cost added"
    calls = []
    monkeypatch.setattr(tc, "write", lambda *a, **k: calls.append(a) or {"ok": True, "said": "x"})
    tp.run_batch(_args(sheet, rows="3", copy_to="none", central_sheet=str(central), sheet_name="Tracker"),
                 portal=_Portal(), status_path=status, sleep=lambda s: None)
    assert calls == [], "and only once"
