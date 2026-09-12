"""Detection without refusal is a comment.

WHAT HAPPENED. A pack shipped whose quantities were finally right and whose money was gone —
#DIV/0! through the labour SUM, Subtotal GBP 0.00, "not readable from the sheet" — and the
record already SAID so: money_provenance was stamped `can_evidence_a_price: false` on the
file. The system knew, and sent it anyway, under a covering email that summarised the pack
like any other job's.

Two halves close that, and both are tested here as far as this box can reach them:

* THE REFUSAL — a record that cannot evidence a price gets a DO NOT SEND note in the
  covering email's place and no quote. The workbook still ships to the estimator, because
  repairing it needs the file. do_not_send_note is the note.

* THE CACHE — the read-back's Excel session computed the real totals on every run and then
  closed with SaveChanges=False, so the file on disk kept openpyxl's value-less formulas:
  correct in Excel, blank in every preview, data_only read, and pre-flight scan. The close
  now saves the calculated values (formulas stay live — the estimator asked to SEE them)
  unless the workbook could only be opened read-only. Excel COM does not exist on this box,
  so the save decision is tested against duck-typed fakes; the decision, not Excel, is what
  regressed here.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from estimate_explained import do_not_send_note                          # noqa: E402
from wep_readback_from_xlsx import _close_excel                          # noqa: E402


# ── the refusal note ──────────────────────────────────────────────────────────────────────

def test_the_subject_leads_with_do_not_send():
    note = do_not_send_note("12349-02_20260912", "final_estimate.totals is absent")
    assert note["subject"].startswith("DO NOT SEND — 12349-02_20260912")
    for body in (note["text"], note["html"]):
        assert "final_estimate.totals is absent" in body
        assert "repair" in body.lower()
        assert "Nothing in it should be read as a price" in body


def test_an_empty_reason_still_produces_a_refusal():
    note = do_not_send_note("", "")
    assert note["subject"].startswith("DO NOT SEND")
    assert "cannot evidence a price" in note["text"]


# ── the calculated values survive the close ──────────────────────────────────────────────

class _FakeWorkbook:
    def __init__(self, read_only=False, save_raises=False):
        self.ReadOnly = read_only
        self._save_raises = save_raises
        self.saved = False
        self.closed = False

    def Save(self):
        if self._save_raises:
            raise RuntimeError("disk says no")
        self.saved = True

    def Close(self, SaveChanges=False):
        self.closed = True


class _FakeExcel:
    def __init__(self):
        self.quit = False

    def Quit(self):
        self.quit = True


def test_a_writable_workbook_keeps_its_calculated_values():
    excel, wb = _FakeExcel(), _FakeWorkbook(read_only=False)
    _close_excel(excel, wb, save=True)
    assert wb.saved and wb.closed and excel.quit


def test_a_read_only_fallback_is_not_saved():
    """A locked file was opened read-only so the READ still happened — saving would raise
    or write a copy; it is reported and skipped instead."""
    excel, wb = _FakeExcel(), _FakeWorkbook(read_only=True)
    _close_excel(excel, wb, save=True)
    assert not wb.saved and wb.closed and excel.quit


def test_a_failed_save_never_loses_the_close():
    excel, wb = _FakeExcel(), _FakeWorkbook(save_raises=True)
    _close_excel(excel, wb, save=True)
    assert not wb.saved and wb.closed and excel.quit


def test_the_default_close_still_saves_nothing():
    """Every other COM open in this pipeline keeps its read-only, no-side-effects close."""
    excel, wb = _FakeExcel(), _FakeWorkbook(read_only=False)
    _close_excel(excel, wb)
    assert not wb.saved and wb.closed
