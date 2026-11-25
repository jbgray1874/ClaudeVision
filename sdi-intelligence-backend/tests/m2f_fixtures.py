"""Monday2Friday test fixture: a synthetic tracker that copies the real layout with invented values.

Imported by the test_m2f_* modules rather than living in conftest.py, so it cannot
affect any other test in this folder."""
import sys
from pathlib import Path

import openpyxl
import pytest
from openpyxl.styles import PatternFill
from openpyxl.styles.colors import Color

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from m2f.tracker_import import theme_palette  # noqa: E402


def _solid(rgb=None, theme=None):
    colour = Color(rgb="FF" + rgb) if rgb else Color(theme=theme)
    return PatternFill(fill_type="solid", fgColor=colour)


@pytest.fixture
def tracker(tmp_path):
    # Learn the default theme colours openpyxl writes, so the legend can use the
    # RGB of theme colour 9 while a forecast cell uses the theme reference.
    probe = tmp_path / "probe.xlsx"
    openpyxl.Workbook().save(probe)
    accent = theme_palette(openpyxl.load_workbook(probe))[9]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Current -Boots"
    for cell, word, fill in (("K1", "Risk", _solid("FF0000")), ("L1", "TBC ", _solid("FFFF00")),
                             ("M1", "Confirmed", _solid(accent)), ("N1", "Invoiced", _solid("5B9BD5"))):
        ws[cell] = word
        ws[cell].fill = fill
    for col, header in zip("ABCDEFGH", ["Project", "PM", "PO", "OCT", "NOV", "DEC", "JAN FY27", "FEB FY27"]):
        ws[f"{col}2"] = header

    ws["A3"], ws["B3"], ws["C3"] = "Alpha display", "Conor", 4100000001
    ws["D3"], ws["D3"].fill = 100, _solid("FF0000")
    ws["G3"], ws["G3"].fill = 50, _solid(theme=9)               # theme green = Confirmed

    ws["A4"], ws["B4"] = "Beta fixtures", "conor / Chloe M"
    ws["E4"], ws["E4"].fill = "£1,200.50", _solid("FFFF00")   # text amount, TBC
    ws.row_dimensions[4].hidden = True

    ws["A5"] = 12345                                           # named only by a number
    ws["F5"], ws["F5"].fill = 300, _solid("00B0F0")            # colour not on the legend

    ws["A6"], ws["H6"] = "Gamma order", "loade"                # unreadable amount
    ws["D7"] = 999                                             # value on an unnamed row

    ws["D10"], ws["E10"], ws["F10"] = "=SUM(D3:D9)", "=SUM(E3:E9)", "=SUM(F3:F4)"  # F5 outside
    ws["J20"] = "=SUM(D3:H5)"      # BUK rows 3-5
    ws["J21"] = "=SUM(D6:H9)"      # Sigma rows 6-9
    ws["J22"] = "=SUM(D10:H10)"    # across a total row whose G10, H10 are empty

    ft = wb.create_sheet("Forcasting Total")
    ft["A1"], ft["B1"], ft["C1"] = "FY26", "Budgeted", "Tracker"
    ft["A2"], ft["C2"] = "Oct FY26", "=SUM('Current -Boots'!D10)"
    ft["A3"], ft["C3"] = "Nov FY26", "=SUM('Current -Boots'!E10)"
    ft["A4"], ft["C4"] = "Dec FY26", "=SUM('Current -Boots'!F10)"
    ft["A5"], ft["C5"] = "Jan FY27", "=SUM('Current -Boots'!D20)"  # empty cell, Oct column
    ft["A6"], ft["C6"] = "Feb FY27", 777                            # typed total
    ft["A7"] = "Totals"
    ft["M8"], ft["O8"] = "BUK", "='Current -Boots'!J20"
    ft["M9"], ft["O9"] = "Sigma ", "='Current -Boots'!J21"
    ft["M10"], ft["O10"] = "BOPS", "='Current -Boots'!J22"

    wb.create_sheet("Complete")
    path = tmp_path / "tracker.xlsx"
    wb.save(path)
    return path
