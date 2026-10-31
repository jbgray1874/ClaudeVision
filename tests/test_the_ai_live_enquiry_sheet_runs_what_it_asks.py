"""The AI Live Enquiry sheet runs what it asks for, from the top (D-608).

31 Oct 2026, James: "this s/sheet is read : C:\\ClaudeVision\\chatgptdropoff\\AI-Live-Enquiry.xlsx.
the columns AI Check ( column H ) is then checked. one by one from the top. if it states YES,
and there is a QTY ( column I ) and AICompleted ( column J ) is NO, or N, or Re-Run, we run the
estimate ... we need to look for the drawings in this location : K:\\Estimating\\Completed\\AI
Estimating\\Live Enquiry\\ matching off the customer in Column D with the directory below ...
then a pattern match for the Drawing No. Field F in the name of the folder in the directory
below the client name."

The sheet is still read and never written: what ran is in the runner's ledger. So AICompleted
still says NO after its run, and the ledger is what stops it running again; Re-Run runs it once
per marking.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config  # noqa: E402
import live_enquiry_runner as L  # noqa: E402

# The AI Live Enquiry sheet as it stands: A empty, the header on row 1, H AI CHECK, I QTY,
# J AICompleted, K Estimator.
HEADER = [None, "Enquiry Received", "Account Manager", "Customer", "Job Description",
          "Drawing No.", "Requested Estimate Completion Date", "AI CHECK", "QTY", "AICompleted",
          "Estimator"]


def _line(customer, drawing, qty="1,5,10", done="NO", ai="YES", desc="Editions Footwear Podium",
          due=datetime(2026, 11, 5)):
    return [None, datetime(2026, 10, 30), "Andy Morrans", customer, desc, drawing, due, ai, qty,
            done, "Tony"]


def _rows(*lines):
    return L.rows_from_table([HEADER, [None] * 11, *lines])


def _pack(root: Path, client: str, folder: str, *names: str) -> Path:
    d = root / client / folder
    d.mkdir(parents=True, exist_ok=True)
    for n in names or ("GA.pdf",):
        (d / n).write_bytes(b"%PDF-1.4 " + n.encode())
    return d


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "Live Enquiry"
    r.mkdir()
    return r


def _plan(rows, root, ledger=None):
    ledger = ledger if ledger is not None else {"schema": L.LEDGER_SCHEMA, "jobs": {},
                                                "quantities": {}}
    return L.plan(rows, L._sources(root), ledger), ledger


class _Portal:
    def __init__(self):
        self.started = []

    def start(self, body):
        self.started.append(body["drawing_number"])
        return {"run_id": f"r{len(self.started)}", "output_path": "C:\\out"}

    def status(self, run_id):
        return {"status": "done", "engine_price_gbp": 10.0, "seconds": 1,
                "output_path": "C:\\out", "deliverables": []}


def _run(decisions, ledger, tmp_path):
    return L.run_ready(decisions, _Portal(), ledger, tmp_path / "ledger.json",
                       say=lambda s: None, poll_seconds=0, sleep=lambda s: None)


# ── the sheet ──────────────────────────────────────────────────────────────────────────

def test_the_sheet_is_read_by_its_headers_with_qty_and_aicompleted():
    row = _rows(_line("M&S", "12678-01-GA", qty="1,5,10", done="Re-Run"))[0]
    assert (row.customer, row.drawing, row.ai_check) == ("M&S", "12678-01-GA", "YES")
    assert row.quantities == "1,5,10" and row.ai_completed == "Re-Run"
    assert row.completed_column, "this sheet runs by its own rule"
    assert row.notes == "", "AICompleted is a headed column, not a note"


def test_the_workbook_defaults_to_the_one_james_named():
    if os.getenv("SDI_LIVE_ENQUIRY_WORKBOOK"):
        pytest.skip("SDI_LIVE_ENQUIRY_WORKBOOK is set on this machine and wins")
    assert Path(config.LIVE_ENQUIRY_WORKBOOK) == ROOT / "chatgptdropoff" / "AI-Live-Enquiry.xlsx"


# ── what runs ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("done", ["NO", "No", "N", "n", "Re-Run", "re run", "RERUN", "Re_Run"])
def test_yes_a_qty_and_aicompleted_no_n_or_rerun_runs(root, done):
    _pack(root, "M&S", "12678-01-GA")
    d = _plan(_rows(_line("M&S", "12678-01-GA", done=done)), root)[0][0]
    assert d.status == "ready", d.reason
    assert d.quantities == [1, 5, 10] and d.quantity_source == "the sheet's QTY column"


@pytest.mark.parametrize("done", ["", "YES", "Y", "Done", "Manual"])
def test_any_other_aicompleted_is_not_a_request_to_run(root, done):
    _pack(root, "M&S", "12678-01-GA")
    d = _plan(_rows(_line("M&S", "12678-01-GA", done=done)), root)[0][0]
    assert d.status == "not_asked"
    assert "AICompleted is" in d.reason and "NO, N or Re-Run runs it" in d.reason


def test_ai_check_not_yes_is_not_asked_whatever_aicompleted_says(root):
    _pack(root, "M&S", "12678-01-GA")
    d = _plan(_rows(_line("M&S", "12678-01-GA", ai="", done="NO")), root)[0][0]
    assert d.status == "not_asked" and "AI CHECK" in d.reason


def test_no_qty_on_the_sheet_holds_the_row_and_nothing_else_supplies_one(root):
    """The QTY column is the quantity: a QUANTITIES.txt in the folder or "100 off" in the
    description, which the older sheet accepted, do not count here."""
    _pack(root, "M&S", "12678-01-GA", "GA.pdf", "QUANTITIES.txt")
    (root / "M&S" / "12678-01-GA" / "QUANTITIES.txt").write_text("1,5", encoding="utf-8")
    rows = _rows(_line("M&S", "12678-01-GA", qty="", desc="Podium 100 off"))
    d, ledger = _plan(rows, root)
    ledger["quantities"][L.drawing_key("12678-01-GA")] = [7]
    d = L.plan(rows, L._sources(root), ledger)[0]
    assert d.status == "held" and "no QTY on the sheet" in d.reason


def test_ready_rows_run_from_the_top_of_the_sheet(root, tmp_path):
    """One by one from the top, not by the completion date."""
    for n in ("12678-01-GA", "12684-01-GA", "12676-01-GA2"):
        _pack(root, "M&S", n)
    rows = _rows(_line("M&S", "12678-01-GA", due=datetime(2026, 11, 9)),
                 _line("M&S", "12684-01-GA", due=datetime(2026, 11, 1)),
                 _line("M&S", "12676-01-GA2", due=datetime(2026, 11, 5)))
    decisions, ledger = _plan(rows, root)
    portal = _Portal()
    L.run_ready(decisions, portal, ledger, tmp_path / "ledger.json", say=lambda s: None,
                poll_seconds=0, sleep=lambda s: None)
    assert portal.started == ["12678-01-GA", "12684-01-GA", "12676-01-GA2"]


# ── not run twice, and Re-Run once per marking ─────────────────────────────────────────

def test_no_after_its_run_is_done_not_run_again(root, tmp_path):
    _pack(root, "M&S", "12678-01-GA")
    rows = _rows(_line("M&S", "12678-01-GA", done="NO"))
    decisions, ledger = _plan(rows, root)
    assert len(_run(decisions, ledger, tmp_path)) == 1
    again = L.plan(rows, L._sources(root), ledger)[0]
    assert again.status == "done"
    assert "the sheet is not written" in again.reason and "Re-Run runs it again" in again.reason


def test_rerun_runs_once_per_marking(root, tmp_path):
    _pack(root, "M&S", "12678-01-GA")
    no = _rows(_line("M&S", "12678-01-GA", done="NO"))
    rerun = _rows(_line("M&S", "12678-01-GA", done="Re-Run"))
    decisions, ledger = _plan(no, root)
    _run(decisions, ledger, tmp_path)                                 # first run
    d = L.plan(rerun, L._sources(root), ledger)[0]
    assert d.status == "ready" and d.reason == "Re-Run asked for on the sheet"
    assert len(_run([d], ledger, tmp_path)) == 1                      # the re-run
    assert L.plan(rerun, L._sources(root), ledger)[0].status == "done", \
        "the cell still says Re-Run, and that Re-Run has been answered"
    L.plan(no, L._sources(root), ledger)                              # the cell is changed back
    assert L.plan(rerun, L._sources(root), ledger)[0].status == "ready", \
        "marked Re-Run again, it runs again"


def test_rerun_lets_a_failed_job_go_again(root, tmp_path):
    _pack(root, "M&S", "12678-01-GA")
    rows = _rows(_line("M&S", "12678-01-GA", done="Re-Run"))
    _, ledger = _plan(rows, root)
    job = ledger["jobs"].setdefault(L.job_key(rows[0]), {"customer": "M&S",
                                                          "drawing": "12678-01-GA",
                                                          "attempts": []})
    fp = L.fingerprint(L.pack_files(root / "M&S" / "12678-01-GA"))
    job["attempts"].append({"status": "error", "fingerprint": fp, "quantities": [1, 5, 10],
                            "error": "boom"})
    assert L.plan(rows, L._sources(root), ledger)[0].status == "ready"


# ── the drawings: the customer's folder, then a folder carrying the number ────────────

def test_a_folder_carrying_the_drawing_number_inside_its_name_is_the_pack(root):
    _pack(root, "M&S", "0359974 Editions Footwear Podium 12678-01-GA")
    d = _plan(_rows(_line("M&S", "12678-01-GA")), root)[0][0]
    assert d.status == "ready", d.reason
    assert d.located.folder.name == "0359974 Editions Footwear Podium 12678-01-GA"


def test_a_number_inside_a_longer_number_or_another_drawing_is_not_a_match(root):
    _pack(root, "M&S", "Podium 112678-01-GA")
    _pack(root, "M&S", "Podium 12678-01-02-GA")
    d = _plan(_rows(_line("M&S", "12678-01-GA")), root)[0][0]
    assert d.status == "waiting" and "no 12678-01-GA folder under M&S" in d.reason


def test_two_folders_carrying_the_number_hold_the_row(root):
    _pack(root, "M&S", "0359974 Podium 12678-01-GA")
    _pack(root, "M&S", "Old Podium 12678-01-GA")
    d = _plan(_rows(_line("M&S", "12678-01-GA")), root)[0][0]
    assert d.status == "held" and "leave one" in d.reason


def test_a_folder_named_by_the_number_wins_over_one_carrying_it(root):
    _pack(root, "M&S", "12678-01-GA Podium")
    _pack(root, "M&S", "Copy of 12678-01-GA")
    d = _plan(_rows(_line("M&S", "12678-01-GA")), root)[0][0]
    assert d.status == "ready" and d.located.folder.name == "12678-01-GA Podium"


def test_the_customer_folder_is_matched_from_column_d(root):
    _pack(root, "TTI", "12754-01-GA Gen 5 Wall CDU")
    d = _plan(_rows(_line("TTI", "12754-01-GA", qty="1,364")), root)[0][0]
    assert d.status == "ready" and d.located.client_folder_name == "TTI"
    assert d.quantities == [1, 364]


def test_the_number_inside_is_looked_for_only_under_the_customers_folder(root):
    """At the root, the older layout still needs the exact number to lead the name."""
    _pack(root, "M&S", "unrelated")
    _pack(root, ".", "Copy of 12678-01-GA")
    d = _plan(_rows(_line("M&S", "12678-01-GA")), root)[0][0]
    assert d.status == "waiting"
