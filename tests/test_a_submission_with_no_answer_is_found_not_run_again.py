"""A submission the service accepted but never answered is found, not run again (14 Nov 2026).

The Self-Running batch of five. Three things happened in twenty minutes:

  * 16:26:44 "cycle failed: IndexError: list index out of range". 6364-02 had been picked up
    already running after a watcher restart. Its decision carried no quantities, the line that
    reports a finished job read the first of them, and the cycle died as the job finished.
  * The next cycle took 6364-02's Re-run request, which was still in the ledger, and submitted
    it. The submission timed out while the service staged the pack. The service accepted it.
    The watcher took its provisional line off as if it had been refused, kept the Re-run
    request, stopped dispatching, and waited twenty minutes with a runner free.
  * 6364-01 was refused because its staged folder was held open, and the log said "already
    queued or running on the portal", so nobody looked for the open file.

JG: "there is a free slot and jobs still sitting requested but just sitting there".
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
    """A service. `answers` decides what a submission gets back: "ok", "lost" (accepted, and
    the answer never arrives), "nothing" (not accepted, no answer), or an HTTP refusal."""

    def __init__(self, answers=("ok",), server="http://localhost:8071"):
        self.server, self.answers, self.asked, self.runs = server, list(answers), [], []
        self.still_running = 0          # how many status calls answer "running" before "done"

    def start(self, body):
        how = self.answers[min(len(self.asked), len(self.answers) - 1)]
        self.asked.append(body["drawing_number"])
        if isinstance(how, tuple):
            raise ler.PortalError(*how)
        if how == "nothing":
            raise ler.PortalError(0, "the portal did not answer (timed out)")
        run_id = f"run{len(self.asked)}"
        self.runs.append({"run_id": run_id, "status": "running", "source": "Self-Running",
                          "client": body.get("client") or "M&S",
                          "drawing_number": body["drawing_number"],
                          "units": body.get("units") or 1,
                          "quantity_breaks": list(body.get("quantity_breaks") or []),
                          "queued_at": time.time(), "finished_at": None,
                          "engine_price_gbp": None, "output_path": "\\\\x", "error": "",
                          "deliverables": []})
        if how == "lost":
            raise ler.PortalError(0, "the portal did not answer (timed out)")
        return {"run_id": run_id, "output_path": "\\\\share\\AISheets\\x"}

    def status(self, run_id):
        if self.still_running > 0:
            self.still_running -= 1
            return {"status": "running", "seconds": 30, "deliverables": []}
        return {"status": "done", "engine_price_gbp": 99.0, "seconds": 60,
                "output_path": "\\\\share\\AISheets\\x", "deliverables": []}

    def recent(self, limit=300):
        return {"runs": list(self.runs)}


class Switch:
    def beat(self, rep):
        return True


def _row(n, drawing, qty="1, 40"):
    return ler.EnquiryRow(row=n, customer="M&S", drawing=drawing, description="RAIL",
                          received=date(2026, 11, 13), ai_check="YES", quantities=qty)


@pytest.fixture
def share(tmp_path, monkeypatch):
    root = tmp_path / "Live Enquiry"
    for number in ("0360001", "0360002"):
        pack = root / "M&S" / number
        pack.mkdir(parents=True)
        ga = pack / f"{number}-GA.pdf"
        ga.write_bytes(b"%PDF-1.4 rail " + number.encode())
        old = time.time() - 6 * 3600
        os.utime(ga, (old, old))
    monkeypatch.setattr(sr.config, "LIVE_ENQUIRY_COLLECT_FROM_PRODUCTION", False)
    monkeypatch.setattr(sr.config, "SELF_RUNNING_AT_ONCE", 2)
    rows = [_row(5, "0360001")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": list(rows))
    return {"root": root, "ledger": tmp_path / "ledger.json", "rows": rows,
            "workbook": tmp_path / "Live Enquiry.xlsx"}


def _cycle(share, portal, said=None):
    return sr.cycle({"root": share["root"], "ledger": share["ledger"], "workbook": share["workbook"]},
                    portal, Switch(), say=(said.append if said is not None else (lambda s: None)),
                    wait={"poll_seconds": 0, "sleep": lambda s: None}, others=[portal])


def _job(share, drawing="0360001"):
    ledger = json.loads(share["ledger"].read_text(encoding="utf-8"))
    return ledger["jobs"][f"m&s|{drawing}"]


def _ask_again_on_the_page(share, drawing="0360001"):
    ledger = ler.load_ledger(share["ledger"])
    ledger["jobs"][f"m&s|{drawing}"].update(page_rerun=time.time(), retry=True)
    ler.save_ledger(share["ledger"], ledger)


# ── 1. THE REPORT OF A FINISHED JOB NEVER FAILS THE CYCLE ──────────────────────────────────
def test_a_job_picked_up_running_with_no_quantities_of_its_own_finishes_cleanly(share):
    portal = Portal()
    _cycle(share, portal)                                  # runs once, normally
    ledger = ler.load_ledger(share["ledger"])
    ledger["jobs"]["m&s|0360001"]["attempts"][-1].update(status="running", finished_at=None)
    ler.save_ledger(share["ledger"], ledger)
    share["rows"][0] = _row(5, "0360001", qty="")          # the row now decides with no quantities
    ledger = ler.load_ledger(share["ledger"])
    ledger["quantities"] = {}
    ler.save_ledger(share["ledger"], ledger)
    said = []
    portal.still_running = 1                               # running when the cycle picks it up
    _cycle(share, portal, said)                            # raised IndexError before
    assert _job(share)["attempts"][-1]["status"] == "done"
    assert any("0360001: done" in s and "at 1 off" in s for s in said), said


def test_the_quantity_in_the_report_is_the_attempts_own_then_the_decisions_then_none():
    d = ler.Decision(_row(5, "0360001"), "running", "x")
    assert ler.at_first_quantity(d, {"quantities": [5, 10]}) == " at 5 off"
    d.quantities = [3]
    assert ler.at_first_quantity(d, {}) == " at 3 off"
    assert ler.at_first_quantity(ler.Decision(_row(5, "0360001"), "running", "x"), {}) == ""


# ── 2. NOT ANSWERED IS NOT REFUSED ─────────────────────────────────────────────────────────
def test_a_submission_accepted_without_an_answer_is_waited_on_and_never_sent_twice(share):
    portal = Portal(answers=("ok",))
    _cycle(share, portal)
    _ask_again_on_the_page(share)
    portal.answers = ["lost"]
    said = []
    _cycle(share, portal, said)
    job = _job(share)
    assert portal.asked.count("0360001") == 2, "the Re-run was submitted once"
    assert [a["status"] for a in job["attempts"]] == ["done", "done"]
    assert job["attempts"][-1]["run_id"] == "run2", "the accepted run is the one recorded"
    assert "page_rerun" not in job and "retry" not in job, "the Re-run was used, once"
    assert any("holds it as run run2" in s for s in said), said
    _cycle(share, portal)
    _cycle(share, portal)
    assert portal.asked.count("0360001") == 2, "the job was run again after its Re-run was used"


def test_a_free_slot_is_filled_while_the_found_run_is_waited_on(share):
    share["rows"].append(_row(6, "0360002"))
    portal = Portal(answers=("lost", "ok"))
    _cycle(share, portal)
    assert portal.asked == ["0360001", "0360002"], "the second job was left waiting"
    assert _job(share, "0360002")["attempts"][-1]["status"] == "done"


def test_a_submission_nobody_holds_stays_in_progress_and_nothing_else_is_queued(share):
    share["rows"].append(_row(6, "0360002"))
    portal = Portal(answers=("nothing",))
    said = []
    out = _cycle(share, portal, said)
    assert portal.asked == ["0360001"], "more was queued on a service that is not answering"
    last = _job(share)["attempts"][-1]
    assert last["status"] == ler.QUEUEING and "timed out" in last["unanswered"]
    assert out["look_again_soon"] is True, "the next read was left for the full wait"
    # The service did take it after all: the next read finds it instead of sending it again.
    portal.runs.append({"run_id": "late1", "status": "done", "source": "Self-Running",
                        "client": "M&S", "drawing_number": "0360001", "units": 1,
                        "quantity_breaks": [40], "queued_at": time.time(),
                        "finished_at": time.time(), "engine_price_gbp": 412.5,
                        "output_path": "\\\\x", "error": "", "deliverables": []})
    portal.answers = ["ok"]
    _cycle(share, portal)
    assert portal.asked.count("0360001") == 1, "a job the service already ran was sent again"
    assert _job(share)["attempts"][-1]["run_id"] == "late1"


def test_a_submission_never_answered_and_never_found_is_held_not_sent_again(share, monkeypatch):
    """Reviewer: "Timeouts must never cause blind resubmission." """
    portal = Portal(answers=("ok",))
    _cycle(share, portal)
    _ask_again_on_the_page(share)
    portal.answers = ["nothing"]
    _cycle(share, portal)
    assert portal.asked.count("0360001") == 2
    monkeypatch.setattr(ler, "QUEUEING_GRACE_SECONDS", -1)      # the grace has passed
    portal.answers = ["ok"]
    said = []
    for _ in range(3):
        _cycle(share, portal, said)
    assert portal.asked.count("0360001") == 2, "an unanswered submission was sent again unasked"
    job = _job(share)
    assert job["attempts"][-1]["status"] == "error" and job["attempts"][-1]["unanswered_given_up"]
    assert "page_rerun" not in job and "retry" not in job
    assert any("HELD" in s for s in said) and any("not sent again on its own" in s for s in said), said
    # A person asking again is what sends it.
    _ask_again_on_the_page(share)
    _cycle(share, portal)
    assert portal.asked.count("0360001") == 3


def test_a_refusal_still_takes_the_provisional_line_off(share):
    portal = Portal(answers=((400, "the pack has no drawing"),))
    _cycle(share, portal)
    statuses = [a["status"] for a in _job(share)["attempts"]]
    assert ler.QUEUEING not in statuses and statuses == ["error"], statuses


# ── 3. A FOUND RUN ANSWERS ONLY THE REQUEST IT CAME AFTER ──────────────────────────────────
def test_an_older_run_found_on_a_service_does_not_use_up_a_newer_re_run():
    row = _row(5, "0360001")
    job = {"page_rerun": time.time(), "retry": True}
    ler._request_answered_by(job, row, time.time() - 3600, was_asked_for_here=False)
    assert "page_rerun" in job, "a run from an hour before the Re-run was taken as its answer"
    ler._request_answered_by(job, row, time.time(), was_asked_for_here=False)
    assert "page_rerun" not in job and "retry" not in job


# ── 4. A JOB NOT STARTED SAYS WHY, IN THE SERVICE'S OWN WORDS ──────────────────────────────
def test_a_job_the_service_would_not_start_gives_the_services_reason(share):
    why = ("The staged pack for 0360001 (X:\\staged\\0360001) is still open in another "
           "program, so it cannot be replaced: 0360001-GA.pdf.")
    portal = Portal(answers=((409, why),))
    said = []
    out = _cycle(share, portal, said)
    assert any("0360001: not started" in s and "0360001-GA.pdf" in s for s in said), said
    assert not any("already queued or running" in s for s in said)
    assert out["not_started"] and "still open in another program" in out["not_started"][0]


def test_a_second_job_is_still_started_when_the_first_is_not(share):
    share["rows"].append(_row(6, "0360002"))
    portal = Portal(answers=((409, "its staged folder is held open"), "ok"))
    _cycle(share, portal)
    assert portal.asked == ["0360001", "0360002"]
    assert _job(share, "0360002")["attempts"][-1]["status"] == "done"
