"""A busy Excel is waited for, and when it will not answer, the note says so in plain words.

THE 14:12 M&S PLYWOOD RUN, 30 SEP. The read-back asked Excel for the calculated totals and got
RPC_E_SERVERCALL_RETRYLATER: "The message filter indicated that the application is busy." It
treated that first answer as final. The record lost its totals and the pack went out as
DO NOT SEND. Minutes later the same run's last pass through Excel calculated and saved that
workbook without trouble.

The note that replaced the covering e-mail then made it worse. Its only reason was the
record's internal sentence ("the workbook's accepted row grouping reached this record but its
calculated totals did not…"), and its repair was the #DIV/0! one: "usually a labour row with
no throughput". James Gray: "the e-mail explanation is not great".

D-366:
* A busy answer is retried on the house ladder (2, 4, 8 and 16 s, so five attempts).
  Any other failure is reported on the first attempt.
* The read-back records WHY it came back empty, as a cause code and a plain sentence.
* money_provenance carries both, and the accepted-rows verdict no longer drops the reason.
* The note says what happened, what it means for the figures and what to do for THAT cause.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import money_provenance as mp                                            # noqa: E402
import wep_readback_from_xlsx as wep                                     # noqa: E402
from estimate_explained import do_not_send_note                          # noqa: E402

BUSY = -2147417846          # RPC_E_SERVERCALL_RETRYLATER
REJECTED = -2147418111      # RPC_E_CALL_REJECTED
BUSY_TEXT = "The message filter indicated that the application is busy."


class _ComError(Exception):
    """Shaped like pywintypes.com_error: args (hresult, text, excepinfo, argerror)."""

    def __init__(self, hresult, text="", excepinfo=None):
        super().__init__(hresult, text, excepinfo, None)
        self.hresult = hresult


def _no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    return slept


# ── recognising "busy" ─────────────────────────────────────────────────────────────────────

def test_both_busy_answers_are_recognised():
    assert wep.excel_was_busy(_ComError(BUSY, BUSY_TEXT))
    assert wep.excel_was_busy(_ComError(REJECTED, "Call was rejected by callee."))


def test_busy_carried_in_the_excepinfo_is_recognised():
    """A busy answer that came through a dispatch call carries it as the scode."""
    exc = _ComError(-2147352567, "Exception occurred.",
                    (0, "Microsoft Excel", "busy", None, 0, BUSY))
    assert wep.excel_was_busy(exc)


def test_a_real_fault_is_not_busy():
    assert not wep.excel_was_busy(RuntimeError("Excel COM readback is only supported on Windows."))
    assert not wep.excel_was_busy(_ComError(-2147352567, "Exception occurred."))
    assert not wep.excel_was_busy(ValueError(BUSY))    # the number as a value, not an HRESULT


# ── the retry ladder ────────────────────────────────────────────────────────────────────────

def test_a_busy_excel_is_asked_again_until_it_answers(monkeypatch):
    slept = _no_sleep(monkeypatch)
    calls = []

    def read():
        calls.append(1)
        if len(calls) < 3:
            raise _ComError(BUSY, BUSY_TEXT)
        return {"unit": 243.75}

    result, attempts, waited = wep.with_busy_retry(read, "reading")
    assert result == {"unit": 243.75}
    assert attempts == 3 and slept == [2, 4] and waited == 6


def test_an_excel_that_stays_busy_is_reported_with_how_long_it_was_given(monkeypatch):
    slept = _no_sleep(monkeypatch)

    def read():
        raise _ComError(BUSY, BUSY_TEXT)

    with pytest.raises(wep.ExcelStayedBusy) as info:
        wep.with_busy_retry(read, "reading")
    assert slept == [2, 4, 8, 16]
    assert info.value.attempts == 5 and info.value.waited_s == 30
    assert info.value.message == BUSY_TEXT


def test_a_real_fault_is_not_retried(monkeypatch):
    """Retrying a real fault only delays the report of it."""
    slept = _no_sleep(monkeypatch)
    calls = []

    def read():
        calls.append(1)
        raise ValueError("the sheet is not there")

    with pytest.raises(ValueError):
        wep.with_busy_retry(read, "reading")
    assert len(calls) == 1 and slept == []


# ── the read-back says why it came back empty ─────────────────────────────────────────────

def test_a_read_back_that_stayed_busy_names_the_cause(monkeypatch):
    _no_sleep(monkeypatch)

    def busy(_path, _sheet):
        raise _ComError(BUSY, BUSY_TEXT)

    monkeypatch.setattr(wep, "_read_totals_once", busy)
    assert wep.read_real_totals(Path("book.xlsx")) is None
    fail = wep.last_failure()
    assert fail["cause"] == wep.EXCEL_BUSY
    assert BUSY_TEXT in fail["detail"]
    assert "5 attempts" in fail["detail"] and "30 seconds" in fail["detail"]


def test_a_read_back_that_answers_on_a_later_attempt_leaves_no_failure(monkeypatch):
    _no_sleep(monkeypatch)
    calls = []

    def once(_path, _sheet):
        calls.append(1)
        if len(calls) == 1:
            raise _ComError(BUSY, BUSY_TEXT)
        return {"material": 194.04, "labour": 32.65, "unit": 243.75}

    monkeypatch.setattr(wep, "_read_totals_once", once)
    assert wep.read_real_totals(Path("book.xlsx"))["unit"] == 243.75
    assert wep.last_failure() == {}


def test_a_machine_without_excel_is_named_as_such(monkeypatch):
    def no_excel(_path, _sheet):
        raise RuntimeError("Excel COM readback is only supported on Windows.")

    monkeypatch.setattr(wep, "_read_totals_once", no_excel)
    assert wep.read_real_totals(Path("book.xlsx")) is None
    assert wep.last_failure()["cause"] == wep.EXCEL_UNAVAILABLE


def test_a_blank_price_cell_is_a_fault_in_the_workbook(tmp_path, monkeypatch):
    """Excel answered every question and the price was blank: that one IS the #DIV/0! case."""
    book, record = tmp_path / "book.xlsx", tmp_path / "book.json"
    book.write_bytes(b"")
    record.write_text(json.dumps({"estimate_summary": {}}), encoding="utf-8")

    def no_unit(_path, sheet_name="Estimate"):
        wep._LAST_FAILURE.clear()
        return {"material": 194.04}

    monkeypatch.setattr(wep, "read_real_totals", no_unit)
    assert wep.stamp_real_totals_into_json(str(book), str(record)) is None
    assert wep.last_failure()["cause"] == wep.TOTALS_NOT_CALCULATED


def test_a_missing_workbook_is_named(tmp_path):
    record = tmp_path / "book.json"
    record.write_text("{}", encoding="utf-8")
    assert wep.stamp_real_totals_into_json(str(tmp_path / "gone.xlsx"), str(record)) is None
    assert wep.last_failure()["cause"] == wep.WORKBOOK_MISSING


class _FakeSheet:
    pass


class _FakeBook:
    def Worksheets(self, _name):
        return _FakeSheet()


def _fake_session(monkeypatch, rows):
    monkeypatch.setattr(wep, "_open_xlsx_excel_com",
                        lambda path, prime_sheet=None, read_only=True: (object(), _FakeBook()))
    monkeypatch.setattr(wep, "_close_excel", lambda excel, wb, save=False: None)
    monkeypatch.setattr(wep, "_used_bounds", lambda ws: (300, 20))
    monkeypatch.setattr(wep, "_scan_total", lambda ws, needles, r, c: 100.0)
    monkeypatch.setattr(wep, "read_final_rows", rows)
    monkeypatch.setattr(wep, "read_unit_price_composition", lambda *a, **k: {})


def test_busy_while_reading_the_rows_retries_the_whole_read(monkeypatch):
    """Totals kept without their rows never become a final_estimate, so swallowing a busy
    answer here would still leave the record with no money, just without saying why."""
    def busy_rows(ws, max_col):
        raise _ComError(BUSY, BUSY_TEXT)

    _fake_session(monkeypatch, busy_rows)
    with pytest.raises(_ComError):
        wep._read_totals_once(Path("book.xlsx"), "Estimate")


def test_a_real_fault_reading_the_rows_still_keeps_the_totals(monkeypatch):
    def broken_rows(ws, max_col):
        raise ValueError("header not found")

    _fake_session(monkeypatch, broken_rows)
    out = wep._read_totals_once(Path("book.xlsx"), "Estimate")
    assert out["unit"] == 100.0 and "_final_rows" not in out


class _BusyCells:
    """A sheet whose every cell read is answered busy, as a busy Excel answers."""

    def Cells(self, r, c):
        raise _ComError(BUSY, BUSY_TEXT)

    @property
    def UsedRange(self):
        raise _ComError(BUSY, BUSY_TEXT)


class _OddCell:
    """One cell that cannot be read for a real reason. The rest read as labels."""

    class _C:
        def __init__(self, v):
            self.Value = v

    def Cells(self, r, c):
        if (r, c) == (1, 1):
            raise ValueError("odd cell")
        return self._C("Total Unit Cost Price" if c == 2 else 243.75)


def test_a_busy_excel_mid_scan_is_not_read_as_a_sheet_with_no_totals():
    """Every scan read a failed cell as empty. Busy on every cell, that is a sheet with no
    totals, reported as the workbook's fault. The busy answer is raised to be asked again."""
    with pytest.raises(_ComError):
        wep._scan_total(_BusyCells(), ("total unit cost",), 5, 5)
    with pytest.raises(_ComError):
        wep._used_bounds(_BusyCells())
    with pytest.raises(_ComError):
        wep._header_map(_BusyCells(), 1, {"operation": "operation"}, 5)


def test_one_unreadable_cell_is_still_just_a_blank():
    assert wep._scan_total(_OddCell(), ("total unit cost",), 1, 4) == 243.75


# ── the record keeps the reason ────────────────────────────────────────────────────────────

def _accepted_rows_only() -> dict:
    return {"estimate_summary": {"part_estimates": []},
            "workbook_labour": {"rows": [{"workbook_row": 10}]}}


def test_the_accepted_rows_verdict_keeps_the_reason_and_the_cause():
    detail = f'Excel was busy — it answered "{BUSY_TEXT}" on all 5 attempts, over 30 seconds'
    verdict = mp.describe(_accepted_rows_only(), skip_reason=detail, cause=wep.EXCEL_BUSY)
    assert verdict["state"] == mp.ACCEPTED_ROWS_ONLY
    assert "attributable and money is not" in verdict["why"]
    assert detail in verdict["why"], "the reason was collected and then dropped here"
    assert verdict["cause"] == wep.EXCEL_BUSY
    assert verdict["evidence"]["workbook_stage_cause"] == wep.EXCEL_BUSY


# ── the note ──────────────────────────────────────────────────────────────────────────────

STEM = "bdab4adf-3340-40M&S_20260930_141217"


def _busy_note(recalculated_later=True):
    detail = f'Excel was busy — it answered "{BUSY_TEXT}" on all 5 attempts, over 30 seconds'
    verdict = mp.describe(_accepted_rows_only(), skip_reason=detail, cause=wep.EXCEL_BUSY)
    return do_not_send_note(STEM, verdict["why"], cause=verdict["cause"], detail=detail,
                            recalculated_later=recalculated_later, money_refused=True)


def test_a_busy_excel_is_named_in_the_subject_and_the_body():
    note = _busy_note()
    assert note["subject"] == (f"DO NOT SEND — {STEM}: Excel was busy, so the price was "
                               f"not checked")
    text = note["text"]
    assert BUSY_TEXT in text and "on all 5 attempts, over 30 seconds" in text
    assert "What happened" in text and "What it means" in text and "What to do" in text
    assert "Nothing is known to be wrong with the figures" in text
    assert "Re-run the job" in text and "EXCEL.EXE" in text


def test_a_busy_excel_is_not_sent_looking_for_a_labour_row():
    """The repair for a #DIV/0! is not the repair for a busy Excel."""
    note = _busy_note()
    for body in (note["text"], note["html"]):
        assert "labour row with no throughput" not in body
        assert "#DIV/0!" not in body
        assert "preflight_before_you_send_it" not in body


def test_the_note_says_whether_excel_managed_later_in_the_run():
    assert "a hold-up on the PC, not a fault in the estimate" in _busy_note(True)["text"]
    assert "could not calculate the workbook later in the run either" in \
        _busy_note(False)["text"]
    assert "later in the same run" not in _busy_note(None)["text"]


def test_the_records_own_words_move_to_the_foot():
    text = _busy_note()["text"]
    assert text.index("For the engine team:") > text.index("What to do")
    assert "accepted row grouping" not in text.split("For the engine team:")[0]


def test_a_total_that_did_not_calculate_keeps_the_div0_repair():
    note = do_not_send_note(STEM, "why", cause=wep.TOTALS_NOT_CALCULATED,
                            detail="Excel calculated the workbook, but its Total Unit Cost "
                                   "Price came back blank or as an error (#DIV/0!, #VALUE!)")
    assert "the workbook's total did not calculate" in note["subject"]
    assert "preflight_before_you_send_it" in note["text"]
    assert "labour row with no throughput" in note["text"]


def test_a_machine_without_excel_is_sent_to_the_estimating_pc():
    note = do_not_send_note(STEM, "why", cause=wep.EXCEL_UNAVAILABLE,
                            detail="this machine cannot run Excel (win32com missing)")
    assert "no Excel on this machine" in note["subject"]
    assert "Re-run the job on the estimating PC" in note["text"]


def test_a_quantity_refusal_alone_is_not_called_a_money_fault():
    note = do_not_send_note(STEM, "", quantity_why="the run was asked for 350 off and the "
                            "record was costed at 1 off", money_refused=False)
    assert note["subject"] == f"DO NOT SEND — {STEM}: costed at the wrong quantity"
    assert "Excel" not in note["text"]
    assert "Re-run the job at the quantity that was asked for." in note["text"]


def test_the_html_escapes_the_job_name():
    html = _busy_note()["html"]
    assert "40M&amp;S_20260930" in html and "40M&S_20260930" not in html


# ── wired, or it never runs ──────────────────────────────────────────────────────────────

def test_the_run_carries_the_cause_from_the_read_back_to_the_note():
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8", errors="ignore")
    assert "last_failure as _wep_last_failure" in source
    assert "_mp.stamp(_mp_doc, skip_reason=_mp_skip, cause=_mp_cause)" in source
    assert "_recached_n = _recache(_recache_books)" in source
    assert "_note = _dns_note(Path(xlsx_path).stem, **_dns_args)" in source
    args = source[source.index("_dns_args = {"):][:900]
    for arg in ('"why":', '"cause":', '"detail":', '"quantity_why": _qty_why',
                '"recalculated_later":', '"money_refused": _money_refused'):
        assert arg in args, arg


def test_the_final_refresh_waits_for_a_busy_excel_too():
    source = (ROOT / "src" / "quantity_sweep.py").read_text(encoding="utf-8")
    body = source[source.index("def recache_workbooks"):][:4000]
    assert "with_busy_retry(lambda: _refresh(book)" in body
