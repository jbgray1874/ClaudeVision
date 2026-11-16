"""THE TRACKER WRITE NEVER LEAVES AN EXCEL HOLDING THE FILE (16 Nov 2026).

Every cost write since Saturday 20:13 failed. Try 1 met "Call was rejected by callee" while Excel
was still opening the tracker; the exception left that Excel alive with the workbook open; every
later try started another Excel, which opened the file read-only and could not save. Twenty-four
estimates finished with their costs only in the ledger.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tti_pricer as tp  # noqa: E402

BUSY = -2147418111


class ComError(Exception):
    def __init__(self, hresult):
        super().__init__(hresult, "Call was rejected by callee.", None, None)
        self.hresult = hresult


class Excel:
    made = []

    def __init__(self, busy=2, read_only=False):
        self.busy, self.read_only, self.saved, self.quit, self.value = busy, read_only, 0, False, None
        self.Hwnd = 1234
        Excel.made.append(self)

    def _call(self):
        if self.busy:
            self.busy -= 1
            raise ComError(BUSY)

    @property
    def Workbooks(self):
        xl = self

        class Books:
            def Open(self, path, *a):
                xl._call()
                return Book(xl)
        return Books()

    def Quit(self):
        self.quit = True


class Book:
    def __init__(self, xl):
        self.xl = xl

    @property
    def ReadOnly(self):
        return self.xl.read_only

    def Worksheets(self, name):
        xl = self.xl

        class Sheet:
            def Cells(self, r, c):
                xl._call()

                class Cell:
                    def __setattr__(self, k, v):
                        xl.value = v
                return Cell()
        return Sheet()

    def Save(self):
        self.xl._call()
        self.xl.saved += 1

    def Close(self, SaveChanges=False):
        pass


@pytest.fixture
def excel(monkeypatch):
    Excel.made = []
    ended = []
    made = {"next": dict(busy=2)}
    client = types.SimpleNamespace(DispatchEx=lambda name: Excel(**made["next"]))
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(sys.modules, "win32process", types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, 4242)))
    monkeypatch.setattr(tp.SheetWriter, "_end", staticmethod(lambda pid, wait_s=10.0: ended.append(pid)))
    monkeypatch.setattr(tp.SheetWriter, "BUSY_WAIT_S", 0)
    monkeypatch.setattr(tp.SheetWriter, "EXCEL_WAIT_S", 0)
    return made, ended


def test_a_busy_excel_is_waited_out_in_the_same_excel_and_then_ended(excel, tmp_path):
    made, ended = excel
    w = tp.SheetWriter(tmp_path / "t.xlsx", "Milwaukee", "P")
    w.write(3, 451.94)
    assert len(Excel.made) == 1, "a second Excel was started while the first was only busy"
    xl = Excel.made[0]
    assert xl.value == 451.94 and xl.saved == 1 and xl.quit and ended == [4242]


def test_a_workbook_opened_read_only_is_refused_at_once_and_its_excel_is_ended(excel, tmp_path):
    made, ended = excel
    made["next"] = dict(busy=0, read_only=True)
    w = tp.SheetWriter(tmp_path / "t.xlsx", "Milwaukee", "P")
    with pytest.raises(OSError, match="open somewhere else"):
        w.write(3, 451.94)
    assert all(x.saved == 0 for x in Excel.made) and ended == [4242] * len(Excel.made)


def test_an_error_that_is_not_busy_is_not_waited_on_and_its_excel_is_still_ended(excel, tmp_path, monkeypatch):
    made, ended = excel
    made["next"] = dict(busy=0)
    monkeypatch.setattr(Book, "Save", lambda self: (_ for _ in ()).throw(ComError(-2147352567)))
    monkeypatch.setattr(tp.SheetWriter, "EXCEL_TRIES", 1)
    w = tp.SheetWriter(tmp_path / "t.xlsx", "Milwaukee", "P")
    with pytest.raises(OSError):
        w.write(3, 1.0)
    assert len(Excel.made) == 1 and ended == [4242] and Excel.made[0].quit
