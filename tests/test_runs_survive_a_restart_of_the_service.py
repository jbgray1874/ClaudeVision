"""Queued, running, finished and failed runs survive a restart of the service (D-618).

JG and the review, 1 Nov 2026: estimates should run unattended and "remain accessible", and
restart-safe history "should preserve queued, running, completed and failed jobs, recover
interrupted runner claims, and prevent duplicate estimate emails after recovery". Runs lived
only in memory and the service restarts with every deployment.

A restart here is what it is on the laptop: the routes module imported afresh, with the same
state folder on disk.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_estimate_queue import _check_in, _request, api  # noqa: E402,F401


def _restart(monkeypatch=None):
    sys.modules.pop("estimate_routes", None)
    return importlib.import_module("estimate_routes")


def _queue(er, root, email="james.gray@wearesdi.com", drawing="12677-01-GA"):
    _check_in(er)
    req = _request(er, root, drawing=drawing)
    req.email_to = email
    return er.start(req)["run_id"]


def _finish(er, run_id, runner="rnr-1", status="done"):
    return er.complete(run_id, er.CompleteRequest(
        runner_id=runner, status=status, unit_cost_gbp=421.37,
        deliverables=[{"name": "12677-01-GA.xlsx", "path": "C:\\out\\12677-01-GA.xlsx"}]))


@pytest.fixture()
def mail(api, monkeypatch):
    er, _ = api
    sent = []

    def fake(snapshot, deliverables, recipients, quote, provisional):
        sent.append((snapshot["run_id"], list(recipients)))
        return {"sent": True, "attached": ["12677-01-GA.xlsx"]}
    monkeypatch.setattr(er, "_email_finished_run", fake)
    return sent


# ── each state comes back ───────────────────────────────────────────────────────────────

def test_a_queued_run_comes_back_queued_and_is_claimed(api):
    er, root = api
    run_id = _queue(er, root)
    er = _restart()
    assert er._RUNS[run_id].status == "queued"
    assert "restored and is still queued" in er._RUNS[run_id].log[-1]
    got = _check_in(er)["run"]
    assert got["run_id"] == run_id and got["drawing_number"] == "12677-01-GA"


def test_a_running_run_keeps_its_claim_and_the_runner_carries_on(api, mail):
    er, root = api
    run_id = _queue(er, root)
    assert _check_in(er)["run"]["run_id"] == run_id
    er = _restart()
    run = er._RUNS[run_id]
    assert run.status == "running" and run.runner == "rnr-1"
    # The runner, still working, reports in: no "No such run", and the runner is connected.
    beat = er.progress(run_id, er.ProgressRequest(runner_id="rnr-1", lines=["engine: costing"]))
    assert beat["ok"] is True
    assert er._online_runners(), "a runner mid-job counts as connected again"
    _finish(er, run_id)
    assert er._RUNS[run_id].status == "done"


def test_finished_and_failed_runs_stay_in_the_history_the_page_reads(api, mail):
    er, root = api
    done_id = _queue(er, root)
    _check_in(er)
    _finish(er, done_id)
    failed_id = _queue(er, root, drawing="12678-01-GA")
    _check_in(er)
    _finish(er, failed_id, status="error")
    er = _restart()
    listed = {r["run_id"]: r["status"] for r in er.recent()["runs"]}
    assert listed == {done_id: "done", failed_id: "error"}
    assert er._RUNS[done_id].engine_price_gbp == 421.37
    assert er._RUNS[done_id].deliverables[0]["name"] == "12677-01-GA.xlsx"


def test_a_claim_whose_runner_has_gone_runs_out_after_a_restart(api):
    er, root = api
    run_id = _queue(er, root)
    _check_in(er)
    er._RUNS[run_id].lease_until = time.time() - 1
    er._keep(er._RUNS[run_id])
    er = _restart()
    er.status(run_id)
    assert er._RUNS[run_id].status == "error"
    assert "stopped responding" in er._RUNS[run_id].error


def test_a_runner_restarted_meanwhile_releases_the_claim(api):
    er, root = api
    _check_in(er)
    req = _request(er, root)
    run_id = er.start(req)["run_id"]
    er.claim(er.ClaimRequest(runner_id="rnr-1", hostname="LAPTOP", process="pid-1"))
    er = _restart()
    er.claim(er.ClaimRequest(runner_id="rnr-1", hostname="LAPTOP", process="pid-2"))
    assert er._RUNS[run_id].status == "error"
    assert "was restarted while this job was running" in er._RUNS[run_id].error


# ── the e-mail goes once ────────────────────────────────────────────────────────────────

def test_the_same_finish_reported_twice_sends_one_email(api, mail):
    er, root = api
    run_id = _queue(er, root)
    _check_in(er)
    _finish(er, run_id)
    again = _finish(er, run_id)
    assert again.get("already_recorded") is True
    assert mail == [(run_id, ["james.gray@wearesdi.com"])]


def test_a_finish_reported_again_after_a_restart_sends_no_second_email(api, mail, monkeypatch):
    er, root = api
    run_id = _queue(er, root)
    _check_in(er)
    _finish(er, run_id)
    er = _restart()
    monkeypatch.setattr(er, "_email_finished_run", lambda *a: mail.append(("again",)) or {})
    assert _finish(er, run_id).get("already_recorded") is True
    assert mail == [(run_id, ["james.gray@wearesdi.com"])]


def test_a_restart_in_the_middle_of_sending_never_sends_again(api, monkeypatch):
    er, root = api
    run_id = _queue(er, root)
    _check_in(er)
    run = er._RUNS[run_id]
    run.status, run.email_result = "done", {"sending": True, "at": time.time()}
    run.deliverables = [{"name": "x.xlsx", "path": "C:\\out\\x.xlsx"}]
    run.finished_at = time.time()
    er._keep(run)
    er = _restart()
    restored = er._RUNS[run_id]
    assert restored.email_result["sent"] is False
    assert "not sent again; check the inbox" in restored.email_result["reason"]
    calls = []
    monkeypatch.setattr(er, "_email_finished_run", lambda *a: calls.append(a) or {"sent": True})
    restored.status = "error"            # even a late finish arriving now sends nothing
    _finish(er, run_id)
    assert calls == []


def test_a_late_finish_after_the_claim_ran_out_is_still_filed_and_mailed_once(api, mail):
    er, root = api
    run_id = _queue(er, root)
    _check_in(er)
    er._RUNS[run_id].lease_until = time.time() - 1
    er.status(run_id)
    assert er._RUNS[run_id].status == "error"
    _finish(er, run_id)
    assert er._RUNS[run_id].status == "done"
    assert mail == [(run_id, ["james.gray@wearesdi.com"])]


# ── the files on disk ───────────────────────────────────────────────────────────────────

def test_each_run_is_one_file_written_whole(api):
    er, root = api
    run_id = _queue(er, root)
    folder = er.estimate_history.store_dir()
    assert sorted(p.name for p in folder.iterdir()) == [f"{run_id}.json"]
    body = json.loads((folder / f"{run_id}.json").read_text(encoding="utf-8"))
    assert body["status"] == "queued" and body["drawing_number"] == "12677-01-GA"


def test_a_long_console_is_trimmed_on_disk(api):
    er, root = api
    run_id = _queue(er, root)
    run = er._RUNS[run_id]
    for i in range(1000):
        run.line(f"line {i}")
    er._keep(run)
    body = json.loads((er.estimate_history.store_dir() / f"{run_id}.json").read_text("utf-8"))
    assert len(body["log"]) == er.estimate_history.LOG_KEEP + 1
    assert body["log"][-1] == "line 999" and "earlier line(s)" in body["log"][0]


def test_old_finished_runs_are_pruned_and_live_ones_never(api, monkeypatch):
    er, root = api
    old_id = _queue(er, root)
    live_id = _queue(er, root, drawing="12678-01-GA")
    old = er._RUNS[old_id]
    old.status, old.finished_at = "done", time.time() - 40 * 86400
    er._keep(old)
    er._RUNS[live_id].queued_at = time.time() - 40 * 86400
    er._keep(er._RUNS[live_id])
    er = _restart()
    assert old_id not in er._RUNS and live_id in er._RUNS
    assert not (er.estimate_history.store_dir() / f"{old_id}.json").exists()


def test_a_damaged_file_is_left_and_the_rest_restored(api):
    er, root = api
    run_id = _queue(er, root)
    (er.estimate_history.store_dir() / "broken0001.json").write_text("{not json", "utf-8")
    er = _restart()
    assert run_id in er._RUNS and "broken0001" not in er._RUNS
    assert (er.estimate_history.store_dir() / "broken0001.json").exists()


def test_switched_off_nothing_is_kept(api, monkeypatch):
    er, root = api
    monkeypatch.setenv("SDI_RUN_HISTORY", "0")
    run_id = _queue(er, root)
    assert not er.estimate_history.store_dir().exists()
    er = _restart()
    assert run_id not in er._RUNS
