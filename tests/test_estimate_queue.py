"""The queue between the web service and the runner.

The service no longer runs anything. It holds the page, the queue and the run
history; a runner on a machine with a SOLIDWORKS seat and an interactive session
polls for work, does it, and reports back.

Three things about that split can fail in ways nobody sees, and each has a test
here because each looks like success from the outside:

  * a job queued when no runner is connected sits there for ever, and a queue
    nobody drains is indistinguishable from working
  * a runner that sleeps mid-run leaves the job "running" and an estimator
    watching a spinner that will never stop
  * two runners taking the same job would drive two Excel automations at one
    estimate and file half a set from each

    python -m pytest tests/test_estimate_queue.py -q
"""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """The routes module with a stub config — config.py wants a real .env, and
    the queue needs only the key and the readable roots."""
    stub = types.ModuleType("config")
    stub.API_KEY = ""
    stub.FILE_ROOTS = [str(tmp_path)]
    monkeypatch.setitem(sys.modules, "config", stub)
    monkeypatch.syspath_prepend(str(BACKEND))
    for name in list(sys.modules):
        if name == "estimate_routes":
            del sys.modules[name]
    er = pytest.importorskip("estimate_routes",
                             reason="fastapi/pydantic not installed in this environment")
    er._RUNS.clear(); er._RUNNERS.clear()
    (tmp_path / "job").mkdir(exist_ok=True)
    return er, tmp_path


def _request(er, tmp_path, units=10, client="Boots", drawing="12422-24"):
    return er.EstimateRequest(client=client, drawing_number=drawing, units=units,
                              job_folder=str(tmp_path / "job"),
                              output_root=str(tmp_path / "share"))


def _check_in(er, runner_id="rnr-1", host="LAPTOP"):
    return er.claim(er.ClaimRequest(runner_id=runner_id, hostname=host))


# ── no runner ────────────────────────────────────────────────────────────────
def test_a_job_is_refused_when_no_runner_is_connected(api, tmp_path):
    """A queue nobody is draining looks exactly like a system that is working,
    right up until somebody goes looking for the estimate. Refuse loudly."""
    er, _ = api
    with pytest.raises(er.HTTPException) as exc:
        er.start(_request(er, tmp_path))
    assert exc.value.status_code == 503
    assert "runner" in exc.value.detail.lower()
    assert not er._RUNS, "nothing should be queued when there is nothing to run it"


def test_a_runner_that_stopped_polling_is_not_online(api, tmp_path):
    """Checked in once an hour ago is not the same as here now."""
    er, _ = api
    _check_in(er)
    er._RUNNERS["rnr-1"].last_seen = time.time() - er.RUNNER_ONLINE_SECONDS - 5
    assert er._online_runners() == []
    with pytest.raises(er.HTTPException) as exc:
        er.start(_request(er, tmp_path))
    assert exc.value.status_code == 503


# ── the ordinary path ────────────────────────────────────────────────────────
def test_queue_claim_progress_complete(api, tmp_path):
    er, _ = api
    _check_in(er)
    started = er.start(_request(er, tmp_path))
    run_id = started["run_id"]
    assert er._RUNS[run_id].status == "queued"

    got = _check_in(er)["run"]
    assert got["run_id"] == run_id
    assert got["output_path"] == started["output_path"], (
        "the runner must file where the SERVER decided, not where it fancies")
    assert er._RUNS[run_id].status == "running"

    er.progress(run_id, er.ProgressRequest(runner_id="rnr-1", lines=["[cad] reading"]))
    assert "[cad] reading" in er._RUNS[run_id].log

    er.complete(run_id, er.CompleteRequest(
        runner_id="rnr-1", status="done",
        deliverables=[{"name": "x.xlsx", "path": str(tmp_path / "x.xlsx")}]))
    run = er._RUNS[run_id]
    assert run.status == "done" and run.finished_at
    assert run.deliverables[0]["name"] == "x.xlsx"
    assert er._RUNNERS["rnr-1"].run_id == "", "the runner must be free again"


def test_only_one_run_at_a_time(api, tmp_path):
    """Two concurrent COM automations against one desktop is not a supported
    thing to do, whatever folders they write to."""
    er, _ = api
    _check_in(er)
    er.start(_request(er, tmp_path))
    _check_in(er)                                     # claims it
    with pytest.raises(er.HTTPException) as exc:
        er.start(_request(er, tmp_path, drawing="99999"))
    assert exc.value.status_code == 409


def test_a_second_runner_cannot_start_a_second_run(api, tmp_path):
    """TWO QUEUED JOBS IS THE CASE THAT MATTERS, and the obvious version of this
    test cannot produce it. Queue one, claim it, and a second runner finds an
    empty queue whether the guard exists or not — so the test passes for the
    wrong reason and proves nothing.

    Two CAN be queued: start() only refuses while a run is RUNNING, and a job
    that is merely queued does not block the next one. So queue two before
    anyone claims, and the second runner has something to take."""
    er, _ = api
    _check_in(er, "rnr-1")
    a = er.start(_request(er, tmp_path, drawing="12422-24"))["run_id"]
    b = er.start(_request(er, tmp_path, drawing="11350"))["run_id"]
    assert er._RUNS[a].status == er._RUNS[b].status == "queued"

    assert _check_in(er, "rnr-1")["run"]["run_id"] == a, "oldest first"
    assert _check_in(er, "rnr-2", "DESKTOP")["run"] is None, (
        "a second runner took a job while one was already running — that is two "
        "Excel automations against one estimate and half a deliverable set from each")
    assert er._RUNS[b].status == "queued", "job B must wait, not be lost"


def test_the_queue_drains_in_order(api, tmp_path):
    """Whoever pressed the button first gets their estimate first."""
    er, _ = api
    _check_in(er, "rnr-1")
    a = er.start(_request(er, tmp_path, drawing="AAA"))["run_id"]
    b = er.start(_request(er, tmp_path, drawing="BBB"))["run_id"]

    assert _check_in(er, "rnr-1")["run"]["run_id"] == a
    er.complete(a, er.CompleteRequest(runner_id="rnr-1", status="done"))
    assert _check_in(er, "rnr-1")["run"]["run_id"] == b


def test_a_stranger_cannot_report_on_someone_elses_run(api, tmp_path):
    er, _ = api
    _check_in(er, "rnr-1")
    run_id = er.start(_request(er, tmp_path))["run_id"]
    _check_in(er, "rnr-1")
    for call in (lambda: er.progress(run_id, er.ProgressRequest(runner_id="rnr-2")),
                 lambda: er.complete(run_id, er.CompleteRequest(runner_id="rnr-2",
                                                                status="done"))):
        with pytest.raises(er.HTTPException) as exc:
            call()
        assert exc.value.status_code == 409


# ── the failure that would otherwise be silent ───────────────────────────────
def test_a_sleeping_runner_fails_the_run_rather_than_hanging_it(api, tmp_path):
    """Lid closed, VPN dropped, process killed. Without a lease the run stays
    "running" for ever and the estimator watches a spinner that never stops."""
    er, _ = api
    _check_in(er)
    run_id = er.start(_request(er, tmp_path))["run_id"]
    _check_in(er)
    assert er._RUNS[run_id].status == "running"

    er._RUNS[run_id].lease_until = time.time() - 1          # the runner went quiet
    state = er.status(run_id)

    assert state["status"] == "error"
    assert "stopped responding" in state["error"]
    assert "Nothing was filed" in state["error"], "it must say what did NOT happen"
    assert er._RUNNERS["rnr-1"].run_id == "", "the runner must not stay marked busy"


def test_a_working_runner_keeps_its_lease(api, tmp_path):
    """The heartbeat rides on the log posts, so the lease is renewed by the act
    of working rather than by a timer that could outlive a wedged run."""
    er, _ = api
    _check_in(er)
    run_id = er.start(_request(er, tmp_path))["run_id"]
    _check_in(er)
    er._RUNS[run_id].lease_until = time.time() + 0.5

    er.progress(run_id, er.ProgressRequest(runner_id="rnr-1", lines=["still going"]))
    assert er._RUNS[run_id].lease_until > time.time() + er.LEASE_SECONDS - 5
    assert er.status(run_id)["status"] == "running"


# ── what the page needs to know ──────────────────────────────────────────────
def test_the_page_can_see_whether_anything_is_connected(api, tmp_path):
    er, _ = api
    assert er.runners()["online"] == 0
    _check_in(er, "rnr-1", "LAPTOP-JG")
    seen = er.runners()
    assert seen["online"] == 1
    assert seen["runners"][0]["hostname"] == "LAPTOP-JG"


def test_the_job_folder_must_be_inside_a_readable_root(api, tmp_path):
    er, _ = api
    _check_in(er)
    req = er.EstimateRequest(client="Boots", drawing_number="12422-24", units=10,
                             job_folder=r"C:\somewhere\else")
    with pytest.raises(er.HTTPException) as exc:
        er.start(req)
    assert exc.value.status_code == 403


def test_the_run_folder_names_the_quantity(api):
    """Two estimates of one drawing at different quantities are different
    estimates, and the quantity is the one thing a timestamp cannot tell you."""
    er, _ = api
    at = 1_760_000_000.0
    assert er.run_folder_name(at, 10) != er.run_folder_name(at, 180)
    assert "(10 off)" in er.run_folder_name(at, 10)
    assert "(180 off)" in er.run_folder_name(at, 180)


# ── the log filter ───────────────────────────────────────────────────────────
def test_only_the_quiet_poll_is_hidden_from_the_log(monkeypatch):
    """A runner polls every five seconds and hiding that keeps the console usable.
    Hiding anything else would hide the thing somebody is looking for."""
    import logging
    monkeypatch.syspath_prepend(str(BACKEND))
    from log_filters import QuietPolling
    f = QuietPolling()

    def access(path, status):
        r = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s", None, None)
        r.args = ("127.0.0.1:1", "POST", path, "1.1", status)
        return r

    # hidden: the heartbeat, having done nothing
    assert not f.filter(access("/api/estimate/runner/claim", 200))
    assert not f.filter(access("/api/estimate/runners", 200))

    # kept: everything that went wrong, and everything that happened
    assert f.filter(access("/api/estimate/runner/claim", 401)), "a rejected runner must show"
    assert f.filter(access("/api/estimate/runner/claim", 500)), "a broken runner must show"
    assert f.filter(access("/api/estimate", 200)), "a queued job must show"
    assert f.filter(access("/api/estimate/abc123/complete", 200)), "a finished run must show"
    assert f.filter(access("/api/files?path=x", 200)), "browsing must show"

    # a record that is not an access log is not ours to judge
    other = logging.LogRecord("uvicorn.error", logging.ERROR, "", 0, "boom", None, None)
    assert f.filter(other)
