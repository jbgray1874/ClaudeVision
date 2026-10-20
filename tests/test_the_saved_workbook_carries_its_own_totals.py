"""The workbook calculated, and the file it was saved as could not show a single figure.

WHAT THE 13 SEP PACK SHOWED. 823 formula cells on 12349-02's Estimate sheet, and not one
carrying a cached value — including G6, the unit cost the covering email quotes as £121.30.
The sheet is right the moment Excel opens it and blank to everything else: the preview pane,
any data_only read, the pre-flight's own error-cell scan.

TWO FAULTS, STACKED. `recache_workbooks` exists to fix exactly this, and could never have
worked: it opened each file through `_open_xlsx_excel_com`, whose ReadOnly default is right
for the read-back it was written for, and then called Save() on a read-only workbook. It
printed "cache not refreshed" each run and nobody chased it. And its only caller sat inside
the quantity-sweep branch, which most runs never enter — so on a run without a sweep the
baseline was never refreshed at all, and on a run with one it was refreshed mid-stage,
before the explanation tab and AI Provenance were written through openpyxl, each of which
discards Excel's stored results.

So: opened writable, and called once at the END of the workbook stage over every file the
stage wrote. Excel COM does not exist on this box — the open/save decisions are pinned
against duck-typed fakes, because the decisions are what regressed, not Excel.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import quantity_sweep                                                   # noqa: E402
import wep_readback_from_xlsx as wep                                    # noqa: E402


class _Wb:
    def __init__(self, read_only=False):
        self.ReadOnly = read_only
        self.saved = False

    def Save(self):
        if self.ReadOnly:
            raise RuntimeError("cannot save a read-only workbook")
        self.saved = True

    def Close(self, SaveChanges=False):
        pass


class _Excel:
    def __init__(self):
        self.calculated = False

    def CalculateFull(self):
        self.calculated = True

    def Quit(self):
        pass


def _patch(monkeypatch, wb, record):
    def _open(path, prime_sheet=None, read_only=True):
        record.append(read_only)
        return _Excel(), wb
    monkeypatch.setattr(quantity_sweep.sys, "platform", "win32")
    monkeypatch.setattr(wep, "_open_xlsx_excel_com", _open)


def test_the_refresh_opens_the_file_writable(monkeypatch, tmp_path):
    """The whole defect in one assertion: a read-only open can never save."""
    book = tmp_path / "12349-02.xlsx"
    book.write_bytes(b"x")
    wb, asked = _Wb(), []
    _patch(monkeypatch, wb, asked)
    assert quantity_sweep.recache_workbooks([book]) == 1
    assert asked == [False], "the workbook must be opened writable to be saved"
    assert wb.saved


def test_a_file_excel_could_only_open_read_only_is_reported_not_counted(monkeypatch, tmp_path):
    """A workbook open in Excel on someone's desk, or locked: left exactly as written."""
    book = tmp_path / "12349-02.xlsx"
    book.write_bytes(b"x")
    wb, asked = _Wb(read_only=True), []
    _patch(monkeypatch, wb, asked)
    assert quantity_sweep.recache_workbooks([book]) == 0
    assert not wb.saved


def test_missing_files_are_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(quantity_sweep.sys, "platform", "win32")
    assert quantity_sweep.recache_workbooks([tmp_path / "nope.xlsx"]) == 0
    assert quantity_sweep.recache_workbooks([]) == 0


def test_the_read_back_itself_stays_read_only():
    """The read-back is a READ. It runs before three openpyxl saves that would discard
    anything it cached, so opening it writable locks the file and buys nothing."""
    import inspect
    src = inspect.getsource(wep.read_real_totals)
    assert "read_only=False" not in src, \
        "the read-back must not open the workbook writable — the cache is a final pass"


def test_the_refresh_runs_over_every_workbook_the_stage_wrote():
    """The baseline is always in the list and the sweep appends its variants, so a run
    with no sweep still files a workbook that can show its own money."""
    import re
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert re.search(r"_recache_books:\s*List\[str\]\s*=\s*\[str\(xlsx_path\)\]", src), \
        "the baseline workbook must always be queued for the cache refresh"
    assert "_recache(_recache_books)" in src
    # and the call must come after the last openpyxl save of the stage
    assert src.index("add_provenance_sheet") < src.index("_recache(_recache_books)"), \
        "the refresh must run after AI Provenance, or that save strips what it wrote"
