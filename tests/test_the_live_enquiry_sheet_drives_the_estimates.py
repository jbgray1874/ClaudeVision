"""The Live Enquiry sheet drives the AI estimates, one after another (D-420).

9 Oct 2026, James: "this is the sheet we need to drive off an automated ai estimate one after
the other. The inputs should come from K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry.
There will be a client name to match off and a drawing folder below that. To start with there
will be a drawing pack; beyond this the process will automate the looking up of drawings from
the design area."

A row is a job: Customer names a folder under the Live Enquiry root, Drawing No. a folder under
that, and the files directly in it are the pack. A ready row is queued through the portal as a
person queues it, and the next only when it has finished. A row that cannot run says why and
who moves it; nothing is matched "nearly", no quantity is guessed, and the workbook is read and
never written.
"""
from __future__ import annotations

import io
import json
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

# The real sheet's shape: column A empty, the header on row 2, J a note with no header.
HEADER = [None, "Enquiry Received ", "Account Manager", "Customer", "Job Description",
          "Drawing No.", "Requested Estimate Completion Date ", "AI CHECK", "Estimator", None]


def _line(customer, drawing, desc="", ai="YES", due=datetime(2026, 10, 12), note=None,
          estimator="Tony"):
    return [None, datetime(2026, 10, 7), "India Fenton", customer, desc, drawing, due, ai,
            estimator, note]


def _table(*lines):
    return [[None] * 10, HEADER, *lines]


def _pack(root: Path, client: str, folder: str, *names: str) -> Path:
    d = root / client / folder
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_bytes(b"%PDF-1.4 " + n.encode())
    return d


class FakePortal:
    """The portal as the page sees it: a run is queued, runs, and finishes."""

    def __init__(self, price=123.45, refuse=None, finish_after=2):
        self.calls, self.bodies, self.price = [], [], price
        self.refuse, self.finish_after, self.polls = refuse, finish_after, {}

    def start(self, body):
        self.calls.append(("start", body["drawing_number"]))
        if self.refuse:
            raise self.refuse
        # one after another: nothing is queued while another of ours is still going
        assert all(n >= self.finish_after for n in self.polls.values())
        rid = f"r{len(self.bodies) + 1}"
        self.bodies.append(body)
        self.polls[rid] = 0
        return {"run_id": rid, "output_path": f"\\\\share\\AISheets\\{body['drawing_number']}"}

    def status(self, run_id):
        self.calls.append(("status", run_id))
        self.polls[run_id] += 1
        if self.polls[run_id] >= self.finish_after:
            return {"status": "done", "engine_price_gbp": self.price, "seconds": 600,
                    "output_path": f"\\\\share\\AISheets\\{run_id}", "deliverables": []}
        return {"status": "running"}


def _wait():
    return {"poll_seconds": 0, "sleep": lambda s: None}


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "Live Enquiry"
    r.mkdir()
    return r


@pytest.fixture
def ledger(tmp_path):
    return L.load_ledger(tmp_path / "ledger.json")


def _decide(rows, root, ledger):
    return {d.row.drawing: d for d in L.plan(rows, [L.LiveEnquiryShare(root)], ledger)}


# ── the sheet ─────────────────────────────────────────────────────────────────────────
def test_the_sheet_is_read_by_its_headers_and_an_unheaded_cell_is_a_note():
    rows = L.rows_from_table(_table(
        _line("Avanti", "12633-01-GA", "Wine lifter", note="Manual Estimate Complete 22/09/2026"),
        [None] * 10,
        _line("M&S", "12630-01-GA", "1200mm Plinth", ai=None, due=None, note="WAIT FOR DRAWINGS"),
    ))
    assert [(r.row, r.customer, r.drawing, r.ai_check) for r in rows] == [
        (3, "Avanti", "12633-01-GA", "YES"), (5, "M&S", "12630-01-GA", "")]
    assert rows[0].notes == "Manual Estimate Complete 22/09/2026"
    assert rows[0].due.isoformat() == "2026-10-12" and rows[1].due is None
    assert rows[0].estimator == "Tony" and rows[0].description == "Wine lifter"


def test_a_row_not_asked_held_by_its_note_or_not_one_drawing_never_runs(root, ledger):
    _pack(root, "M&S", "12630-01-GA", "12630-01-GA.pdf")
    rows = L.rows_from_table(_table(
        _line("TTI", "12665-01-GA", ai=None),
        _line("M&S", "12630-01-GA", note="WAIT FOR DRAWINGS"),
        _line("Boots", "various"),
        _line("M&S", "N/A"),
        _line("M&S", "12340-01M + 12343-01J"),
    ))
    got = {d.row.row: d for d in L.plan(rows, [L.LiveEnquiryShare(root)], ledger)}
    assert got[3].status == "not_asked"
    assert got[4].status == "held" and "WAIT FOR DRAWINGS" in got[4].reason
    assert got[5].status == "held" and "not one drawing" in got[5].reason
    assert got[6].status == "held"
    assert got[7].status == "held" and "more than one drawing" in got[7].reason


# ── the share ─────────────────────────────────────────────────────────────────────────
def test_customer_and_drawing_folders_are_matched_by_name(root, ledger):
    _pack(root, "M&S", "8188-08", "0348503_8188-08-GA_REV_H.PDF")
    _pack(root, "Avanti", "12633-01-GA Wine lifter", "12633-01-GA.pdf")
    _pack(root, "TTi", "9848-00", "9848-00-GA1.pdf")
    rows = L.rows_from_table(_table(
        _line("m & s", "8188-08_GA", "Fishmonger 1/5/10/50 off"),
        _line("Avanti", "12633-01-GA", "Wine lifter 50 off"),
        _line("TTI", "9848-00-GA1", "LHS Engraver 25 off"),
    ))
    got = _decide(rows, root, ledger)
    assert got["8188-08_GA"].status == "ready"
    assert got["8188-08_GA"].located.folder == root / "M&S" / "8188-08"
    assert got["8188-08_GA"].located.client_folder_name == "M&S"
    assert got["12633-01-GA"].located.folder.name == "12633-01-GA Wine lifter"
    assert got["9848-00-GA1"].located.folder == root / "TTi" / "9848-00"


def test_a_customer_finds_its_folder_by_name_however_it_is_spelt(root, ledger):
    """No alias list (D-423): FANATICS PARIS finds Fanatics, M & S finds M&S, Boots UK Ltd
    finds Boots; a folder named for a pack is never a customer."""
    _pack(root, "Fanatics", "12349-02-74-102", "a.pdf")
    _pack(root, "M&S", "12340-01M", "b.pdf")
    _pack(root, "Boots", "9000-01", "c.pdf")
    _pack(root, "12633-00-GA-Avanti", ".", "d.pdf")
    rows = L.rows_from_table(_table(_line("FANATICS PARIS", "12349-02-74-102", "10 off"),
                                    _line("m and s", "12340-01M", "10 off"),
                                    _line("Boots UK Ltd", "9000-01", "10 off"),
                                    _line("Avanti", "12633-03-GA", "10 off")))
    got = _decide(rows, root, ledger)
    assert got["12349-02-74-102"].status == "ready"
    assert got["12349-02-74-102"].located.client_folder_name == "Fanatics"
    assert got["12340-01M"].status == "ready" and got["9000-01"].status == "ready"
    assert got["12633-03-GA"].status == "waiting"      # the 12633-00 pack is not "Avanti"


def test_two_folders_that_could_be_the_customer_hold_the_row(root, ledger):
    _pack(root, "TTi Milwaukee", "12665-01-GA", "a.pdf")
    _pack(root, "TTi Ryobi", "12665-01-GA", "b.pdf")
    rows = L.rows_from_table(_table(_line("TTI", "12665-01-GA", "10 off")))
    d = _decide(rows, root, ledger)["12665-01-GA"]
    assert d.status == "held" and "TTi Milwaukee" in d.reason and "TTi Ryobi" in d.reason


def test_the_same_name_wins_over_a_longer_one(root, ledger):
    _pack(root, "Fanatics", "1-01", "a.pdf")
    _pack(root, "Fanatics Paris", "12349-02-74-102", "b.pdf")
    rows = L.rows_from_table(_table(_line("FANATICS PARIS", "12349-02-74-102", "10 off")))
    assert _decide(rows, root, ledger)["12349-02-74-102"].located.client_folder_name \
        == "Fanatics Paris"
    assert not L._one_leads_the_other(["FANATIC", "SPORT"], ["FANATIC", "PARI"])


def test_no_folder_or_no_drawings_waits_and_two_folders_that_fit_hold(root, ledger):
    _pack(root, "M&S", "12340-01M")                                   # empty yet
    nested = _pack(root, "M&S", "12343-01J")
    _pack(nested, "old issue", ".", "12343-01J-revA.pdf")             # only in a sub-folder
    _pack(root, "Avanti", "12633-02-GA", "a.pdf")
    _pack(root, "Avanti", "12633-02 Beer Plinth", "b.pdf")
    rows = L.rows_from_table(_table(
        _line("M&S", "12340-01M", "5 off"), _line("M&S", "12343-01J", "5 off"),
        _line("M&S", "12517-00-GA", "5 off"), _line("Avanti", "12633-02-GA", "5 off"),
        _line("Hoar Cross Hall", "9000-01", "5 off")))
    got = _decide(rows, root, ledger)
    assert got["12340-01M"].status == "waiting" and "no drawings" in got["12340-01M"].reason
    assert got["12343-01J"].status == "waiting"                        # sub-folders not read
    assert got["12517-00-GA"].status == "waiting" and "no 12517-00-GA folder" in \
        got["12517-00-GA"].reason
    assert got["12633-02-GA"].status == "held" and "2 folders" in got["12633-02-GA"].reason
    assert got["9000-01"].status == "waiting"


def test_the_design_area_finds_nothing_until_its_endpoint_is_given(root, ledger):
    rows = L.rows_from_table(_table(_line("M&S", "12517-00-GA", "5 off")))
    assert L.DesignArea("").find(rows[0]) is None
    d = L.locate(rows[0], [L.LiveEnquiryShare(root), L.DesignArea("http://design/api")])
    assert d.status == "waiting"


# ── quantities ────────────────────────────────────────────────────────────────────────
def test_no_quantity_stated_holds_the_row_and_each_source_is_named(root, ledger):
    _pack(root, "M&S", "8188-08", "ga.pdf")
    rows = L.rows_from_table(_table(_line("M&S", "8188-08", "Hero header")))
    d = _decide(rows, root, ledger)["8188-08"]
    assert d.status == "held" and "no quantity stated" in d.reason

    (root / "M&S" / "8188-08" / "QUANTITIES.txt").write_text("1, 5, 10, 50\n")
    d = _decide(rows, root, ledger)["8188-08"]
    assert d.status == "ready" and d.quantities == [1, 5, 10, 50]
    assert "QUANTITIES.txt" in d.quantity_source

    ledger["quantities"][L.drawing_key("8188-08-GA")] = [10, 50]
    d = _decide(rows, root, ledger)["8188-08"]
    assert d.quantities == [10, 50] and "console" in d.quantity_source


def test_the_run_quantity_is_the_first_and_the_rest_are_breaks(root, ledger):
    _pack(root, "M&S", "8188-08", "ga.pdf")
    rows = L.rows_from_table(_table(_line("M&S", "8188-08", "Hero header")))
    ledger["quantities"]["8188-08"] = [1, 5, 10, 50]
    d = _decide(rows, root, ledger)["8188-08"]
    body = L.request_body(d)
    assert body["units"] == 1 and body["quantity_breaks"] == [5, 10, 50]
    assert body["client"] == "M&S" and body["drawing_number"] == "8188-08"
    assert body["job_folder"] == str(root / "M&S" / "8188-08")
    assert body["method"] == "both" and body["email_quote"] is False


# ── one after another, and the ledger ────────────────────────────────────────────────
def test_ready_rows_run_one_after_another_and_are_not_run_twice(root, tmp_path, ledger):
    _pack(root, "M&S", "12340-01M", "a.pdf")
    _pack(root, "M&S", "12343-01J", "b.pdf")
    rows = L.rows_from_table(_table(
        _line("M&S", "12343-01J", "Shelf 20 off", due=datetime(2026, 10, 14)),
        _line("M&S", "12340-01M", "Shelf Bracket 40 off", due=datetime(2026, 10, 12))))
    portal, path, said = FakePortal(), tmp_path / "ledger.json", []
    decisions = L.plan(rows, [L.LiveEnquiryShare(root)], ledger)
    done = L.run_ready(decisions, portal, ledger, path, say=said.append, **_wait())
    assert [b["drawing_number"] for b in portal.bodies] == ["12340-01M", "12343-01J"]  # due first
    assert [a["status"] for a in done] == ["done", "done"]
    assert any("£123.45" in s for s in said)
    saved = L.load_ledger(path)
    assert saved["jobs"][L.job_key(rows[1])]["attempts"][0]["engine_price_gbp"] == 123.45

    again = _decide(rows, root, saved)
    assert again["12340-01M"].status == "done" and again["12343-01J"].status == "done"


def test_a_new_revision_or_new_quantities_make_a_done_job_ready_again(root, tmp_path, ledger):
    folder = _pack(root, "M&S", "12340-01M", "a.pdf")
    rows = L.rows_from_table(_table(_line("M&S", "12340-01M", "40 off")))
    L.run_ready(L.plan(rows, [L.LiveEnquiryShare(root)], ledger), FakePortal(), ledger,
                tmp_path / "l.json", say=lambda s: None, **_wait())
    assert _decide(rows, root, ledger)["12340-01M"].status == "done"
    (folder / "12340-01M_REVB.pdf").write_bytes(b"%PDF new")
    d = _decide(rows, root, ledger)["12340-01M"]
    assert d.status == "ready" and "pack has changed" in d.reason
    L.run_ready([d], FakePortal(), ledger, tmp_path / "l.json", say=lambda s: None, **_wait())
    ledger["quantities"]["12340-01M"] = [40, 100]
    d = _decide(rows, root, ledger)["12340-01M"]
    assert d.status == "ready" and "quantities have changed" in d.reason


def test_a_failed_run_waits_for_retry(root, tmp_path, ledger, monkeypatch):
    monkeypatch.setattr(config, "LIVE_ENQUIRY_MAX_ATTEMPTS", 1)
    _pack(root, "M&S", "12340-01M", "a.pdf")
    rows = L.rows_from_table(_table(_line("M&S", "12340-01M", "40 off")))
    portal = FakePortal()
    portal.status = lambda rid: {"status": "error", "error": "Excel is busy"}
    L.run_ready(L.plan(rows, [L.LiveEnquiryShare(root)], ledger), portal, ledger,
                tmp_path / "l.json", say=lambda s: None, **_wait())
    d = _decide(rows, root, ledger)["12340-01M"]
    assert d.status == "failed" and "Excel is busy" in d.reason and "retry" in d.reason
    ledger["jobs"][L.job_key(rows[0])]["retry"] = True
    assert _decide(rows, root, ledger)["12340-01M"].status == "ready"


def test_no_runner_stops_the_cycle_and_a_job_already_on_the_portal_is_left(root, tmp_path,
                                                                             ledger):
    _pack(root, "M&S", "12340-01M", "a.pdf")
    _pack(root, "M&S", "12343-01J", "b.pdf")
    rows = L.rows_from_table(_table(_line("M&S", "12340-01M", "40 off"),
                                    _line("M&S", "12343-01J", "20 off")))
    decisions = L.plan(rows, [L.LiveEnquiryShare(root)], ledger)
    p = FakePortal(refuse=L.PortalError(503, "No estimating runner is connected"))
    said = []
    L.run_ready(decisions, p, ledger, tmp_path / "l.json", say=said.append, **_wait())
    assert len(p.calls) == 1 and "stopped" in said[-1]
    assert not ledger["jobs"]                                   # nothing recorded as failed
    p = FakePortal(refuse=L.PortalError(409, "already running"))
    L.run_ready(decisions, p, ledger, tmp_path / "l.json", say=lambda s: None, **_wait())
    assert len(p.calls) == 2 and not ledger["jobs"]


def test_a_refused_run_is_recorded_with_the_portals_reason(root, tmp_path, ledger):
    _pack(root, "M&S", "12340-01M", "a.pdf")
    rows = L.rows_from_table(_table(_line("M&S", "12340-01M", "40 off")))
    p = FakePortal(refuse=L.PortalError(403, "outside the shares this service may read"))
    L.run_ready(L.plan(rows, [L.LiveEnquiryShare(root)], ledger), p, ledger,
                tmp_path / "l.json", say=lambda s: None, **_wait())
    a = ledger["jobs"][L.job_key(rows[0])]["attempts"][0]
    assert a["status"] == "error" and "outside the shares" in a["error"]


def test_jobs_run_by_hand_before_the_runner_are_baselined_until_their_pack_changes(
        root, ledger):
    folder = _pack(root, "Avanti", "12633-01-GA", "a.pdf")
    rows = L.rows_from_table(_table(_line("Avanti", "12633-01-GA", "Wine lifter 50 off"),
                                    _line("TTI", "12665-01-GA", ai=None)))
    assert L.baseline(rows, [L.LiveEnquiryShare(root)], ledger) == ["12633-01-GA"]
    assert _decide(rows, root, ledger)["12633-01-GA"].status == "done"
    (folder / "b.pdf").write_bytes(b"%PDF")
    assert _decide(rows, root, ledger)["12633-01-GA"].status == "ready"


# ── the workbook is theirs ────────────────────────────────────────────────────────────
def test_the_workbook_is_read_and_never_written(tmp_path, root, ledger):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for line in _table(_line("M&S", "12340-01M", "40 off")):
        ws.append(line)
    path = tmp_path / "Live Enquiry.xlsx"
    wb.save(path)
    before = (path.read_bytes(), path.stat().st_mtime)
    rows = L.read_sheet(path)
    assert [(r.customer, r.drawing) for r in rows] == [("M&S", "12340-01M")]
    out = L.write_status(L.plan(rows, [L.LiveEnquiryShare(root)], ledger),
                         tmp_path / "ledger.json")
    assert (path.read_bytes(), path.stat().st_mtime) == before
    assert out.name == "live_enquiry_status.csv" and "12340-01M" in out.read_text("utf-8-sig")


def test_a_password_protected_workbook_says_what_it_needs(tmp_path, monkeypatch):
    monkeypatch.delenv("SDI_LIVE_ENQUIRY_PASSWORD", raising=False)
    path = tmp_path / "Live Enquiry.xlsx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    with pytest.raises(RuntimeError, match="SDI_LIVE_ENQUIRY_PASSWORD"):
        L.read_sheet(path)


def test_one_runner_at_a_time(tmp_path):
    path = tmp_path / "ledger.json"
    assert L.take_lock(path)
    (tmp_path / "live_enquiry.lock").write_text(f"{os.getpid() + 1} {__import__('time').time()}")
    assert not L.take_lock(path)
    (tmp_path / "live_enquiry.lock").write_text(f"{os.getpid() + 1} 0")      # long gone
    assert L.take_lock(path)


def test_the_portal_client_speaks_the_pages_api():
    """POST /api/estimate and GET /api/estimate/{id} with the key header; a refusal comes back
    with the portal's own words and status."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    seen = []

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers.get("X-SDI-Key"), body["drawing_number"]))
            if body["drawing_number"] == "busy":
                return self._send(503, {"detail": "No estimating runner is connected"})
            self._send(200, {"run_id": "abc123", "output_path": "\\\\share\\out"})

        def do_GET(self):
            seen.append((self.path, self.headers.get("X-SDI-Key"), None))
            self._send(200, {"status": "done", "engine_price_gbp": 9.5})

    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        portal = L.Portal(f"http://127.0.0.1:{server.server_port}", api_key="k", timeout=5)
        assert portal.start({"drawing_number": "8188-08"})["run_id"] == "abc123"
        assert portal.status("abc123")["engine_price_gbp"] == 9.5
        with pytest.raises(L.PortalError) as err:
            portal.start({"drawing_number": "busy"})
        assert err.value.status == 503 and "No estimating runner" in err.value.message
    finally:
        server.shutdown()
    assert seen[0] == ("/api/estimate", "k", "8188-08")
    assert seen[1][:2] == ("/api/estimate/abc123", "k")


# ── the share as it is today (9 Oct scan) ─────────────────────────────────────────────
def test_an_older_pack_at_the_root_is_found_by_its_exact_number(root, ledger):
    """The first live scan: Avanti's packs sit at the root, named by drawing number —
    "12633-10-GA-AvantiConsumableHolderandChillerDisplay" — not under an Avanti folder."""
    _pack(root, "12633-10-GA-AvantiConsumableHolderandChillerDisplay", ".", "12633-10-GA.pdf")
    _pack(root, "12633-10-02-GA Bracket", ".", "x.pdf")            # another drawing
    _pack(root, "12120-01-GA- DIGITAL TICKETING BRACKET", ".", "y.pdf")
    rows = L.rows_from_table(_table(_line("Avanti", "12633-10-GA", "Consumable holder 50 off"),
                                    _line("M&S", "12120-01-GA", "10 off")))
    got = _decide(rows, root, ledger)
    d = got["12633-10-GA"]
    assert d.status == "ready" and d.located.folder.name.startswith("12633-10-GA-Avanti")
    assert "at the root" in d.located.reason
    assert L.request_body(d)["client"] == "Avanti"
    assert got["12120-01-GA"].status == "ready"


def test_a_digit_after_the_number_is_another_drawing():
    assert L.names_the_drawing("12633-10-GA-Avanti", "12633-10")
    assert L.names_the_drawing("1282 - Milwaukee Wall Bay", "1282")
    assert not L.names_the_drawing("12633-10-02-GA", "12633-10")
    assert not L.names_the_drawing("12633-100-GA", "12633-10")
    assert not L.names_the_drawing("Avanti", "12633-10")


def test_the_customer_folder_wins_over_the_root(root, ledger):
    _pack(root, "M&S", "8188-08", "ga.pdf")
    _pack(root, "8188-08 old copy", ".", "old.pdf")
    rows = L.rows_from_table(_table(_line("M&S", "8188-08", "10 off")))
    d = _decide(rows, root, ledger)["8188-08"]
    assert d.located.folder == root / "M&S" / "8188-08" and "at the root" not in d.reason


def test_a_named_baseline_marks_a_job_whose_pack_is_not_found(root, ledger):
    rows = L.rows_from_table(_table(_line("Avanti", "12633-01-GA", "Wine lifter 50 off"),
                                    _line("Avanti", "12633-02-GA", "Beer plinth 50 off")))
    assert L.baseline(rows, [L.LiveEnquiryShare(root)], ledger) == []      # unnamed: needs a pack
    assert L.baseline(rows, [L.LiveEnquiryShare(root)], ledger, ["12633-01-GA"]) == ["12633-01-GA"]
    got = _decide(rows, root, ledger)
    assert got["12633-01-GA"].status == "done" and got["12633-02-GA"].status == "waiting"
