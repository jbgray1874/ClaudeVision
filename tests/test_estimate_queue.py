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


# ── the page and the service must agree about one fact ───────────────────────
def test_the_runner_listing_says_what_it_is_busy_with(api, tmp_path):
    """A RUNNER MID-ESTIMATE MUST NOT READ "READY".

    The page rendered "· ready" whenever a runner was online and nothing was QUEUED. It
    never looked at run_id, which this endpoint already returned and which is precisely
    "this runner is mid-estimate". So a runner 67 seconds into 11650-00 said ready, the
    button was pressed, and the service refused with "An estimate is already running".

    Two screens disagreeing about one fact leaves whoever is standing there to work out
    which one is lying. The listing now carries what the run IS, in the same words the 409
    uses, so the page can say it without inventing anything.
    """
    er, _ = api
    _check_in(er)
    er.start(_request(er, tmp_path, drawing="11650-00"))
    _check_in(er)                                     # claims it — now running

    listed = er.runners()
    entry = listed["runners"][0]
    assert entry["running"], "a runner driving a live estimate is reported as idle"
    assert entry["running"]["drawing_number"] == "11650-00"
    assert entry["running"]["client"] == "Boots"
    assert entry["running"]["seconds"] >= 0
    assert listed["busy"] == 1


def test_an_idle_runner_is_not_reported_as_busy(api, tmp_path):
    """The other direction. Reporting a free machine as busy would stop work being sent
    to a runner that is sitting there, and the fix for that looks like a broken queue."""
    er, _ = api
    _check_in(er)
    listed = er.runners()
    assert listed["runners"][0]["running"] is None
    assert listed["busy"] == 0


def test_a_finished_run_frees_the_listing_too(api, tmp_path):
    """The stale-lock shape: a run that completed while the listing still names it would
    read busy for ever, and nobody would press the button again."""
    er, _ = api
    _check_in(er)
    run_id = er.start(_request(er, tmp_path, drawing="11650-00"))["run_id"]
    _check_in(er)
    er.complete(run_id, er.CompleteRequest(runner_id="rnr-1", status="done"))
    listed = er.runners()
    assert listed["busy"] == 0 and listed["runners"][0]["running"] is None


def test_a_runner_that_died_mid_run_is_not_reported_busy_for_ever(api, tmp_path):
    """A lease that ran out means the machine stopped talking. The run is failed with a
    reason, and the listing must stop claiming it is working on something."""
    er, _ = api
    _check_in(er)
    run_id = er.start(_request(er, tmp_path, drawing="11650-00"))["run_id"]
    _check_in(er)
    er._RUNS[run_id].lease_until = time.time() - 1
    listed = er.runners()
    assert er._RUNS[run_id].status == "error"
    assert listed["busy"] == 0 and listed["runners"][0]["running"] is None


def test_the_page_reads_running_and_not_just_online(api):
    """THE PAGE, NOT THE ENDPOINT. Serving the fact and never rendering it is the defect
    this replaced -- run_id was in the payload the whole time and the page ignored it."""
    page = (BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
    assert "x.running" in page, (
        "the page still decides 'ready' without asking what the runner is running")
    assert "busy —" in page, "there is no wording for a busy runner to render"


def test_a_dangling_run_id_is_not_described_as_a_live_estimate(api, tmp_path):
    """Every terminal path clears the runner's run_id today, so this state cannot be
    reached through the endpoints — which is exactly why it is constructed here. The
    listing describes what a runner is DOING, and a stale id pointing at a finished run
    would have it describing an estimate that ended. Remove the status check and this is
    the only thing that notices."""
    er, _ = api
    _check_in(er)
    run_id = er.start(_request(er, tmp_path, drawing="11650-00"))["run_id"]
    _check_in(er)
    er.complete(run_id, er.CompleteRequest(runner_id="rnr-1", status="done"))
    er._RUNNERS["rnr-1"].run_id = run_id              # the dangling pointer
    listed = er.runners()
    assert listed["runners"][0]["running"] is None, (
        "the listing reported a finished run as a live estimate")
    assert listed["busy"] == 0


# ── releasing a claim a human knows is dead ──────────────────────────────────
def test_a_stuck_claim_can_be_released_without_waiting_out_the_lease(api, tmp_path):
    """THE REASON THE LEASE WAS TOO SHORT.

    Three minutes was not a judgement about how long a runner can be quiet — it was the
    only way to unstick a queue, so it had to be short. It was far too short for a job
    whose expensive phase drives Excel over COM and prints nothing, and it killed four
    healthy runs of 11650 in one morning at 180s, 181s, 180s and 180s.

    With a release the operator can use, the lease can be as long as real work needs.
    """
    er, _ = api
    _check_in(er)
    run_id = er.start(_request(er, tmp_path, drawing="11650-00"))["run_id"]
    _check_in(er)
    assert er._RUNS[run_id].status == "running"

    er.abandon(run_id)
    assert er._RUNS[run_id].status == "error"
    assert er._RUNNERS["rnr-1"].run_id == "", "the runner is still holding the claim"
    assert er._busy_runner() is None, "the queue is still blocked"

    # And the whole point: the next job goes straight through.
    er.start(_request(er, tmp_path, drawing="11350"))


def test_releasing_says_it_did_not_stop_the_engine(api, tmp_path):
    """The runner is another process on another machine. Claiming to have cancelled it
    would have somebody walk away from a SOLIDWORKS session that is still running."""
    er, _ = api
    _check_in(er)
    run_id = er.start(_request(er, tmp_path))["run_id"]
    _check_in(er)
    er.abandon(run_id)
    assert "still working" in (er._RUNS[run_id].error or "")


def test_a_queued_run_can_be_released_too(api, tmp_path):
    er, _ = api
    _check_in(er)
    run_id = er.start(_request(er, tmp_path))["run_id"]
    assert er.abandon(run_id)["was"] == "queued"
    assert _check_in(er)["run"] is None, "a released job was still handed to a runner"


def test_a_finished_run_is_not_released_again(api, tmp_path):
    er, _ = api
    _check_in(er)
    run_id = er.start(_request(er, tmp_path))["run_id"]
    _check_in(er)
    er.complete(run_id, er.CompleteRequest(runner_id="rnr-1", status="done"))
    with pytest.raises(er.HTTPException) as exc:
        er.abandon(run_id)
    assert exc.value.status_code == 409


def test_the_refusal_tells_you_how_to_release_it(api, tmp_path):
    """A 409 that names the problem and not the remedy is how somebody loses a morning."""
    er, _ = api
    _check_in(er)
    run_id = er.start(_request(er, tmp_path, drawing="11650-00"))["run_id"]
    _check_in(er)
    with pytest.raises(er.HTTPException) as exc:
        er.start(_request(er, tmp_path, drawing="99999"))
    assert "abandon" in exc.value.detail and run_id in exc.value.detail


def test_the_lease_is_long_enough_for_a_real_estimate(api):
    """A lease is a bet on how long a WORKING runner can be silent. 11650's quiet phase
    alone exceeded three minutes, and the engine's own runs take several. Expiring early
    destroys finished work; expiring late blocks a queue that can now be released by hand.
    The two errors are not symmetric."""
    er, _ = api
    assert er.LEASE_SECONDS >= 600, (
        f"a {er.LEASE_SECONDS}s lease is shorter than the quiet phase of a real pack, and "
        f"the run it kills is one that was working")


def test_the_page_offers_the_release_the_refusal_names(api):
    """THE PAGE, NOT THE ENDPOINT. A remedy that only exists as a URL in an error string is
    a remedy nobody uses at nine in the morning with a queue stuck."""
    page = (BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
    assert "/abandon" in page, "the page never offers to release a stuck run"
    assert "r.status === 409" in page, (
        "the page does not recognise the refusal, so it cannot offer anything")


def test_the_run_id_in_the_refusal_is_what_the_page_looks_for(api, tmp_path):
    """The page digs the run id out of the 409 text with a regex. If the message stops
    carrying a matching id the button appears to work and releases nothing — so pull the
    real message through the real pattern rather than trusting both ends separately."""
    import re
    er, _ = api
    _check_in(er)
    er.start(_request(er, tmp_path, drawing="11650-00"))
    _check_in(er)
    with pytest.raises(er.HTTPException) as exc:
        er.start(_request(er, tmp_path, drawing="99999"))

    page = (BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
    pattern = re.search(r"detail\.match\(/(.+?)/\)", page).group(1).replace("\\/", "/")
    found = re.search(pattern, exc.value.detail)
    assert found, (f"the page's pattern {pattern!r} finds no run id in the service's own "
                   f"refusal:\n  {exc.value.detail}")
    assert er._RUNS.get(found.group(1)) is not None, "it matched something that is not a run"
