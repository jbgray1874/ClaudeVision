"""Packaging and delivery priced for the whole order fall as the order quantity rises.

11650-06, 24 Sep 2026: packaging £55 and delivery £85 for the order, written on the Estimate
as £27.50 and £42.50 a unit at 2 off — as literals. The Material Price Break tab beside them
held £3.06 and £4.72 at 18 off, and nothing read it: the 18-off unit carried the 2-off
freight, about £62 too much. The sheet's lookup was written only for a line the packing
METHOD priced; a researched or house per-order figure got the literal.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from material_price_break import _price_at                           # noqa: E402

_SRC = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")


def test_any_line_with_an_order_figure_reads_the_break_table():
    i = _SRC.index("EVERY PER-ORDER LINE, NOT ONLY THE ONE THE PACKING METHOD PRICED")
    block = _SRC[i:i + 2500]
    assert '_cl_rec.get("order_gbp_at_breaks") or' in block
    assert '_safe(_cl_rec.get("order_gbp"))' in block
    assert "LOOKUP($D$6," in block


def test_the_break_row_divides_the_order_by_each_quantity():
    line = {"order_gbp": 55.0}
    assert _price_at(line, 2) == pytest.approx(27.5)
    assert _price_at(line, 18) == pytest.approx(55 / 18, abs=1e-4)


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
def test_the_sheet_formula_reads_the_18_off_figure(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    est = wb.active
    est.title = "Estimate"
    mpb = wb.create_sheet("Material Price Break")
    qtys = [1, 2] + [18] * 9
    for i, q in enumerate(qtys):
        mpb.cell(4, 4 + i, q)
        mpb.cell(14, 4 + i, round(55 / q, 5))
    est["D6"] = 18
    # the formula wb_populate writes for sheet row 20 (row_offset -6 -> break row 14)
    est["J20"] = ("=IF('Material Price Break'!D14=\"\",27.5,"
                  "LOOKUP($D$6,'Material Price Break'!$D$4:$N$4,"
                  "'Material Price Break'!D14:N14))")
    src = tmp_path / "f.xlsx"
    wb.save(src)
    subprocess.run(["soffice", "--headless", "--calc", "--convert-to", "xlsx", "--outdir",
                    str(tmp_path / "lo"), str(src)], capture_output=True, timeout=180)
    got = openpyxl.load_workbook(tmp_path / "lo" / "f.xlsx", data_only=True)["Estimate"]["J20"]
    assert got.value == pytest.approx(55 / 18, abs=1e-3)
