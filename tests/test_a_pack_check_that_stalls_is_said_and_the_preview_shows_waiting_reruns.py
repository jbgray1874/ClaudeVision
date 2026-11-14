"""A pack check that stalls is said, and the preview shows the re-runs waiting (JG, 14 Nov 2026).

Five Re-run requests were waiting on the page: 6364-01, 6364-02, 12424-02-GA, 12674-01-GA and
12674-02-GA. Self-Running goes back on only after its preview shows exactly which jobs would
start. The preview (--dry-run) printed one line and then sat silent until it was stopped by
hand: it was reading one pack file from the share, with no file named, no time shown and no
limit. And had it finished, it would not have shown the five requests, because only the
watcher's beat hears them and a preview does not beat.

  * a pack file's read names the file and the time while it runs, and gives up at a limit;
  * a job whose pack could not be checked is held with that reason, never queued, and never
    taken as unchanged on its size and date;
  * the preview reads the requests waiting on the page without taking them;
  * a request for a job the ledger no longer holds is kept, not dropped.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import live_enquiry_runner as ler  # noqa: E402
import pack_resolver as pr  # noqa: E402
import self_running as sr  # noqa: E402
import tti_pricer as tp  # noqa: E402


# ── 1. THE FILE READ ───────────────────────────────────────────────────────────────────────
def _slow_open(monkeypatch, release: threading.Event):
    real = open

    class _Slow:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.fh.close()

        def read(self, n=-1):
            release.wait(5)                      # the share has stopped answering
            return self.fh.read(n)

    monkeypatch.setattr("builtins.open", lambda p, mode="r", *a, **k: (
        _Slow(real(p, mode, *a, **k)) if mode == "rb" and str(p).endswith("GA.pdf")
        else real(p, mode, *a, **k)))


def test_a_read_that_stalls_names_the_file_and_stops_at_the_limit(tmp_path, monkeypatch):
    ga = tmp_path / "9000-01-GA.pdf"
    ga.write_bytes(b"%PDF-1.4 ga")
    release, said = threading.Event(), []
    _slow_open(monkeypatch, release)
    monkeypatch.setattr(pr, "PACK_READ_SAY_SECONDS", 0.05)
    with pytest.raises(pr.PackCheckStalled) as stalled:
        pr.fingerprint(ga, ga.stat().st_size, ga.stat().st_mtime, budget=0.3, say=said.append)
    release.set()
    assert "9000-01-GA.pdf" in str(stalled.value) and str(tmp_path) in str(stalled.value)
    assert said and "still reading 9000-01-GA.pdf" in said[0], "silence is what was wrong"


def test_a_file_that_reads_is_fingerprinted_by_its_bytes_as_before(tmp_path):
    """Contrast: nothing changes for a share that answers."""
    import hashlib
    ga = tmp_path / "9000-01-GA.pdf"
    ga.write_bytes(b"%PDF-1.4 ga")
    assert pr.fingerprint(ga, ga.stat().st_size, ga.stat().st_mtime) == \
        "sha1:" + hashlib.sha1(b"%PDF-1.4 ga").hexdigest()
    assert pr.fingerprint(ga, 30 * 1024 * 1024, 1000.0) == f"stat:{30 * 1024 * 1024}:1000"


# ── 2. THE JOB IS HELD, NOT QUEUED AND NOT TAKEN AS UNCHANGED ──────────────────────────────
def _row(n, drawing, customer="M&S", qty="1, 40", ai_check="YES"):
    return ler.EnquiryRow(row=n, customer=customer, drawing=drawing, description="RAIL",
                          received=date(2026, 11, 13), ai_check=ai_check, quantities=qty)


def test_a_job_whose_pack_could_not_be_checked_is_held_with_the_file_named(tmp_path, monkeypatch):
    root = tmp_path / "Live Enquiry"
    root.mkdir()

    def stalled(*a, **k):
        raise pr.PackCheckStalled("9000-01-GA.pdf (2.0 MB, in W:\\Design) did not finish reading "
                                  "in 120 s: the share is slow or stalled")

    monkeypatch.setattr(pr, "resolve", stalled)
    share = ler.DesignShare(root, folders=lambda: [(tmp_path, [], False)])
    got = share.find(_row(5, "9000-01-GA"))
    assert got.status == "held" and "9000-01-GA.pdf" in got.reason
    assert "could not be checked" in got.reason and "Nothing is queued" in got.reason


def test_the_tracker_batch_holds_that_row_and_goes_on_to_the_next(tmp_path, monkeypatch):
    """The other caller of the same check: a stalled pack holds its row, the batch carries on."""
    import test_tti_pricer_prices_each_row_and_fills_ai_cost as t
    sheet = t._sheet(tmp_path)
    t._areas(tmp_path, monkeypatch)

    def stalled(drawing, listings, client):
        raise pr.PackCheckStalled(f"{drawing}.pdf did not finish reading in 120 s")

    monkeypatch.setattr(tp, "pack_for", stalled)
    rep = tp.run_batch(t._args(sheet, dry_run=True), portal=None, status_path=tmp_path / "s.json")
    by_row = {r["row"]: r for r in rep["rows"]}
    assert by_row[3]["state"] == "held: pack not checked" and "did not finish reading" in by_row[3]["why"]
    assert by_row[6]["state"] != "held: pack not checked", "a row with no drawing is not affected"
    assert rep.get("finished")


# ── 3. THE PREVIEW AND THE RE-RUNS WAITING ON THE PAGE ─────────────────────────────────────
class Portal:
    def __init__(self, runs=(), waiting=()):
        self.server, self.started = "http://localhost:8071", []
        self.runs, self.waiting, self.beats = list(runs), list(waiting), 0

    def start(self, body):
        self.started.append(body["drawing_number"])
        return {"run_id": f"new{len(self.started)}", "output_path": "\\\\share\\x"}

    def status(self, run_id):
        return {"status": "done", "engine_price_gbp": 99.0, "seconds": 60,
                "output_path": "\\\\share\\x", "deliverables": []}

    def recent(self, limit=300):
        return {"runs": list(self.runs)}

    def self_running_view(self):
        return {"enabled": False, "rerun_pending": list(self.waiting)}

    def self_running(self, report):                       # the beat TAKES what is waiting
        self.beats += 1
        got, self.waiting = self.waiting, []
        return {"enabled": True, "rerun": got}


class Silent:
    """What --dry-run uses for the switch: it never beats, so it takes nothing."""

    def beat(self, rep):
        return True


def _done_run(drawing="0360001", client="M&S"):
    return {"run_id": "lost1", "status": "done", "source": "Self-Running", "client": client,
            "drawing_number": drawing, "units": 1, "quantity_breaks": [40],
            "queued_at": time.time() - 3600, "finished_at": time.time() - 1800,
            "engine_price_gbp": 412.5, "output_path": "\\\\x", "error": "", "deliverables": []}


@pytest.fixture
def share(tmp_path, monkeypatch):
    root = tmp_path / "Live Enquiry"
    for drawing in ("0360001", "0360002"):
        (root / "M&S" / drawing).mkdir(parents=True)
        ga = root / "M&S" / drawing / f"{drawing}-GA.pdf"
        ga.write_bytes(b"%PDF-1.4 rail")
        os.utime(ga, (time.time() - 6 * 3600,) * 2)
    monkeypatch.setattr(sr.config, "LIVE_ENQUIRY_COLLECT_FROM_PRODUCTION", False)
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": [_row(5, "0360001"), _row(6, "0360002")])
    return {"root": root, "ledger": tmp_path / "ledger.json", "workbook": tmp_path / "Live Enquiry.xlsx"}


def _settings(share):
    return {"root": share["root"], "ledger": share["ledger"], "workbook": share["workbook"]}


def test_the_preview_shows_a_waiting_rerun_as_ready_and_leaves_it_waiting(share):
    """Both jobs already ran. One has a Re-run waiting. The preview must show exactly that one
    as ready, start nothing, write nothing and take nothing."""
    ask = {"drawing": "0360001", "customer": "M&S", "by": "JG", "at": "2026-11-14T10:00:00"}
    portal = Portal(runs=[_done_run("0360001"), dict(_done_run("0360002"), run_id="lost2")],
                    waiting=[ask])
    said = []
    out = sr.cycle(_settings(share), portal, Silent(), dry_run=True, say=said.append)
    assert out["counts"].get("ready") == 1 and out["counts"].get("done") == 1
    assert portal.started == [] and portal.beats == 0, "a preview does not beat: a beat takes the requests"
    assert portal.waiting == [ask], "still waiting for the watcher"
    assert not share["ledger"].exists(), "a preview writes nothing"
    text = "\n".join(said)
    assert "1 Re-run request(s) waiting on the page: 0360001" in text
    assert "checking row 5: 0360001" in text and "checking row 6: 0360002" in text


def test_a_rerun_for_a_job_the_ledger_lost_is_run_once_not_dropped(share):
    """The ledger holds nothing for the job; a service holds its finished run; a Re-run is
    waiting. The live cycle runs it once: the request finds the job, and the adopted run does
    not read as 'already done' over a person's Re-run."""
    ask = {"drawing": "0360001", "customer": "M&S", "by": "JG", "at": "2026-11-14T10:00:00"}
    portal = Portal(runs=[_done_run("0360001"), dict(_done_run("0360002"), run_id="lost2")],
                    waiting=[ask])
    switch = sr.Switch(portal, say=lambda s: None)
    switch.beat({})                                       # the watcher's beat hears the request
    sr.cycle(_settings(share), portal, switch, say=lambda s: None,
             wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert portal.started == ["0360001"], "the asked-for job once; the other, already run, not at all"
    job = ler.load_ledger(share["ledger"])["jobs"]["m&s|0360001"]
    assert [a["run_id"] for a in job["attempts"]] == ["lost1", "new1"] and not job.get("page_rerun")
    sr.cycle(_settings(share), portal, switch, say=lambda s: None,
             wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert portal.started == ["0360001"], "and not again on the next read"


def test_with_nothing_waiting_the_preview_starts_nothing_that_already_ran(share):
    """Contrast: no request, both already run on the services: nothing is ready."""
    portal = Portal(runs=[_done_run("0360001"), dict(_done_run("0360002"), run_id="lost2")])
    out = sr.cycle(_settings(share), portal, Silent(), dry_run=True, say=lambda s: None)
    assert out["counts"].get("ready", 0) == 0 and out["counts"].get("done") == 2
