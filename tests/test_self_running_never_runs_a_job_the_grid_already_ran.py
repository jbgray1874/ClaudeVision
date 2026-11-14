"""Self-Running never runs a job the grid already ran (JG, 14 Nov 2026).

"the grid shouldn't run jobs that don't meet the criteria for running. this is a bug." Overnight
13-14 Nov, 11896-04-00-GA, 11896-02-01-GA, 11896-01-00-GA and 6364-02 were run again and again.
None of those runs was in the Self-Running ledger, which showed one attempt each for six other
jobs. Three faults let that happen, and each is held here:

  * a ledger that could not be read was handed back EMPTY, then saved over the real one, so
    every row with AICompleted still NO looked as if it had never run;
  * the run was queued BEFORE its attempt was saved, so a failed save left a run with no
    record, and the next read queued it again;
  * nothing asked the services, which keep every run restart-safe, what they had already run.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import live_enquiry_runner as ler  # noqa: E402
import self_running as sr  # noqa: E402


class Portal:
    """A service: queues, answers status, and lists its own runs as GET /api/estimate does."""

    def __init__(self, server="http://localhost:8071", runs=None, on_start=None):
        self.server, self.started, self.runs, self.on_start = server, [], list(runs or []), on_start

    def start(self, body):
        if self.on_start:
            self.on_start(body)
        self.started.append(body["drawing_number"])
        return {"run_id": f"new{len(self.started)}", "output_path": "\\\\share\\AISheets\\x"}

    def status(self, run_id):
        return {"status": "done", "engine_price_gbp": 99.0, "seconds": 60,
                "output_path": "\\\\share\\AISheets\\x", "deliverables": []}

    def recent(self, limit=300):
        return {"runs": list(self.runs)}


class Switch:
    def beat(self, rep):
        return True


def _row(n, drawing, customer="M&S", qty="1, 40"):
    return ler.EnquiryRow(row=n, customer=customer, drawing=drawing, description="RAIL",
                          received=date(2026, 11, 13), ai_check="YES", quantities=qty)


@pytest.fixture
def share(tmp_path, monkeypatch):
    root = tmp_path / "Live Enquiry"
    pack = root / "M&S" / "0360001"
    pack.mkdir(parents=True)
    ga = pack / "0360001-GA.pdf"
    ga.write_bytes(b"%PDF-1.4 rail")
    old = time.time() - 6 * 3600                      # the pack was put there this morning
    os.utime(ga, (old, old))
    monkeypatch.setattr(sr.config, "LIVE_ENQUIRY_COLLECT_FROM_PRODUCTION", False)
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": [_row(5, "0360001")])
    return {"root": root, "ga": ga, "ledger": tmp_path / "ledger.json",
            "workbook": tmp_path / "Live Enquiry.xlsx"}


def _cycle(share, portal, others=()):
    return sr.cycle({"root": share["root"], "ledger": share["ledger"], "workbook": share["workbook"]},
                    portal, Switch(), say=lambda s: None,
                    wait={"poll_seconds": 0, "sleep": lambda s: None}, others=others)


def _service_run(status="done", source="Self-Running", queued=None, run_id="lost1", client="M&S",
                 drawing="0360001", units=1, breaks=(40,)):
    return {"run_id": run_id, "status": status, "source": source, "client": client,
            "drawing_number": drawing, "units": units, "quantity_breaks": list(breaks),
            "queued_at": queued if queued is not None else time.time() - 3600,
            "finished_at": time.time() - 1800 if status in ("done", "error") else None,
            "engine_price_gbp": 412.5 if status == "done" else None, "output_path": "\\\\x",
            "error": "", "deliverables": []}


# ── 1. A LEDGER THAT CANNOT BE READ IS NOT AN EMPTY LEDGER ─────────────────────────────────
def test_a_missing_ledger_is_a_new_one(tmp_path):
    assert ler.load_ledger(tmp_path / "none.json") == ler.new_ledger()


def test_a_ledger_that_cannot_be_read_is_refused_not_read_as_empty(tmp_path):
    bad = tmp_path / "ledger.json"
    bad.write_text("", encoding="utf-8")            # truncated mid-write by something else
    with pytest.raises(ler.LedgerUnreadable):
        ler.load_ledger(bad, pause=0)


def test_a_ledger_held_for_a_moment_is_read_once_it_is_free(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    ler.save_ledger(path, {"schema": ler.LEDGER_SCHEMA, "jobs": {"m&s|1": {"attempts": [{}]}},
                           "quantities": {}})
    real, calls = Path.read_text, {"n": 0}

    def held(self, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(32, "The process cannot access the file")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", held)
    assert "m&s|1" in ler.load_ledger(path, pause=0)["jobs"]


def test_a_cycle_on_an_unreadable_ledger_queues_nothing_and_writes_nothing(share, monkeypatch):
    monkeypatch.setattr(ler, "LEDGER_RETRY_SECONDS", 0)
    share["ledger"].write_text("{\"schema\": \"live_enquiry_ledger.v1\", \"jobs\": {", encoding="utf-8")
    before = share["ledger"].read_bytes()
    portal = Portal()
    with pytest.raises(ler.LedgerUnreadable):
        _cycle(share, portal)
    assert portal.started == [], "a ledger nobody could read must not start every job again"
    assert share["ledger"].read_bytes() == before, "and the real ledger is not saved over"


def test_a_save_waits_out_a_momentary_lock(tmp_path, monkeypatch):
    real, calls = os.replace, {"n": 0}

    def busy(a, b):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real(a, b)

    monkeypatch.setattr(ler.os, "replace", busy)
    ler.save_ledger(tmp_path / "ledger.json", ler.new_ledger(), pause=0)
    assert ler.load_ledger(tmp_path / "ledger.json")["schema"] == ler.LEDGER_SCHEMA


# ── 2. THE ATTEMPT IS WRITTEN BEFORE THE RUN IS ASKED FOR ──────────────────────────────────
def test_the_attempt_is_on_disk_before_the_run_is_asked_for(share):
    seen = {}

    def look(body):
        on_disk = json.loads(share["ledger"].read_text(encoding="utf-8"))
        seen["attempts"] = on_disk["jobs"]["m&s|0360001"]["attempts"]

    portal = Portal(on_start=look)
    _cycle(share, portal)
    assert portal.started == ["0360001"]
    assert [a["status"] for a in seen["attempts"]] == [ler.QUEUEING]
    final = ler.load_ledger(share["ledger"])["jobs"]["m&s|0360001"]["attempts"]
    assert final[-1]["run_id"] == "new1" and final[-1]["status"] == "done"


def test_a_save_lost_after_queueing_does_not_queue_the_job_twice(share, monkeypatch):
    real, calls = ler.save_ledger, {"n": 0}

    def flaky(path, ledger, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:     # the queueing line is saved; the save after the start is lost
            raise PermissionError(5, "Access is denied")
        return real(path, ledger, *a, **k)

    monkeypatch.setattr(ler, "save_ledger", flaky)
    portal = Portal()
    with pytest.raises(PermissionError):
        ler.queue_one(ler.plan([_row(5, "0360001")], ler._sources(share["root"]),
                               ler.load_ledger(share["ledger"]))[0],
                      portal, ler.load_ledger(share["ledger"]), share["ledger"], say=lambda s: None)
    monkeypatch.setattr(ler, "save_ledger", real)
    ledger = ler.load_ledger(share["ledger"])
    decisions = ler.plan([_row(5, "0360001")], ler._sources(share["root"]), ledger)
    assert decisions[0].status == "running", "a run asked for is in progress, not never run"


def test_a_refused_run_leaves_no_queueing_line(share):
    class Refusing(Portal):
        def start(self, body):
            raise ler.PortalError(409, "already queued or running")

    _cycle(share, Refusing())
    attempts = (ler.load_ledger(share["ledger"])["jobs"].get("m&s|0360001") or {}).get("attempts") or []
    assert not [a for a in attempts if a.get("status") == ler.QUEUEING]


# ── 3. THE SERVICES' OWN RECORD OF WHAT RAN ────────────────────────────────────────────────
def test_a_finished_run_missing_from_the_ledger_is_adopted_not_run_again(share):
    portal = Portal(runs=[_service_run("done")])
    out = _cycle(share, portal)
    assert portal.started == [], "the grid already ran it: Self-Running must not run it again"
    assert out["counts"].get("done") == 1
    attempt = ler.load_ledger(share["ledger"])["jobs"]["m&s|0360001"]["attempts"][-1]
    assert attempt["run_id"] == "lost1" and attempt["adopted"]


def test_a_lost_run_still_running_is_followed_not_started_again(share):
    portal = Portal(runs=[_service_run("running")])
    _cycle(share, portal)
    assert portal.started == []
    attempts = ler.load_ledger(share["ledger"])["jobs"]["m&s|0360001"]["attempts"]
    assert [a["run_id"] for a in attempts] == ["lost1"], "the run it found is the one followed"


def test_a_lost_run_on_the_other_service_is_found_there(share):
    here, there = Portal(), Portal("http://localhost:8072", runs=[_service_run("done", run_id="s2")])
    _cycle(share, here, others=[there])
    assert here.started == [] and there.started == []
    attempt = ler.load_ledger(share["ledger"])["jobs"]["m&s|0360001"]["attempts"][-1]
    assert attempt["server"] == "http://localhost:8072"


def test_a_run_from_the_estimating_page_does_not_answer_for_the_sheet(share):
    """Contrast: only Self-Running's own runs stand for its rows. A person's run of the same
    drawing from the page is theirs; the sheet's row still runs, as before."""
    portal = Portal(runs=[_service_run("done", source="Estimating page")])
    _cycle(share, portal)
    assert portal.started == ["0360001"]


def test_a_pack_changed_after_the_lost_run_is_run_again(share):
    """Contrast: the lost run priced the pack as it was. A drawing replaced since then is new
    work, and runs, exactly as a changed pack always has."""
    portal = Portal(runs=[_service_run("done", queued=time.time() - 3600)])
    os.utime(share["ga"], None)                       # touched just now: after that run
    _cycle(share, portal)
    assert portal.started == ["0360001"]


def test_another_customers_run_of_the_same_number_is_not_this_row(share):
    portal = Portal(runs=[_service_run("done", client="Boots")])
    _cycle(share, portal)
    assert portal.started == ["0360001"]


def test_a_queueing_line_no_service_holds_is_held_not_requeued(share):
    ledger = ler.new_ledger()
    ledger["jobs"]["m&s|0360001"] = {"customer": "M&S", "drawing": "0360001", "attempts": [{
        "queued_at": "2026-11-14T01:00:00", "status": ler.QUEUEING, "row": 5,
        "fingerprint": ler.fingerprint([share["ga"]]), "quantities": [1, 40]}]}
    ler.save_ledger(share["ledger"], ledger)
    portal = Portal(runs=[])                          # the services answered: none has it
    out = _cycle(share, portal)
    assert portal.started == []
    assert out["counts"].get("failed") == 1, "said, and left for `retry`, never queued on its own"
