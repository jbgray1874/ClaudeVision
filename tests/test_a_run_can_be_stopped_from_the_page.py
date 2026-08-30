"""Stop means both halves, or it is not stop.

A RUN COULD NOT BE STOPPED FROM THE PAGE AT ALL. `abandon` existed, but the only way to reach
it was to start a SECOND run, be refused with a 409, and take the release offered inside the
refusal text — which the page scraped a run id out of. So an accidental double-start meant
fifteen minutes of SOLIDWORKS and Excel doing work nobody would read, a queue stacked behind
it, and PowerShell as the only recovery. That happened twice in one afternoon.

AND ABANDONING IS ONLY HALF OF STOPPING. It frees the queue and leaves the engine running: the
runner is a separate process on another machine with no inbound port, so nothing can reach it.
It can only be told something the next time it speaks — which it already does every few
seconds to renew the lease. So the cancellation rides the heartbeat, and the runner does the
killing at its end.

THE 409 IS THE OTHER HALF OF THAT MESSAGE, and it is the one that actually arrives. Abandoning
moves the run out of "running", and the progress endpoint then refuses the post outright — so
by the time a cancel flag could be read, the request carrying it is being rejected. Both
answers mean the same thing to a runner: this run is not yours, stop working on it.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
sys.path.insert(0, str(ROOT / "tools" / "runner"))

PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")
RUNNER_SRC = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")


# ── the service records the intent and answers the heartbeat with it ─────────────────

@pytest.fixture()
def routes():
    import estimate_routes
    estimate_routes._RUNS.clear()
    estimate_routes._RUNNERS.clear()
    return estimate_routes


def _running(routes, run_id="r1", runner="RUNNER-1"):
    run = routes.Run(run_id=run_id, client="Boots", drawing_number="11650-04", units=5,
                     job_folder="J", output_path="O")
    run.status = "running"
    run.runner = runner
    run.lease_until = 9e18
    routes._RUNS[run_id] = run
    routes._RUNNERS[runner] = routes.Runner(runner_id=runner, hostname=runner, run_id=run_id)
    return run


def test_a_heartbeat_carries_no_cancellation_on_an_ordinary_run(routes):
    """The field has to be present and false, not absent. A runner reading `.get("cancel")`
    on a service that never sends the key cannot tell "not cancelled" from "an older service
    that has never heard of stopping"."""
    _running(routes)
    out = routes.progress("r1", routes.ProgressRequest(runner_id="RUNNER-1", lines=[]))
    assert out["cancel"] is False


def test_abandoning_records_that_a_person_asked_for_it(routes):
    """Distinct from the run merely being lost. `cancel_requested` says somebody pressed
    stop; the 409 that follows is also true of a run whose lease simply expired, and the two
    need different words in a log somebody reads the next morning."""
    run = _running(routes)
    routes.abandon("r1")
    assert run.cancel_requested is True
    assert run.status == "error"


def test_the_queue_is_free_the_moment_stop_is_pressed(routes):
    """Not when the runner gets round to noticing. The whole point of stopping is the next
    job, and making it wait for a heartbeat would keep the desktop blocked by work already
    given up on."""
    run = _running(routes)
    routes.abandon("r1")
    assert routes._RUNNERS["RUNNER-1"].run_id == ""
    assert run.finished_at is not None


def test_the_runner_is_refused_the_moment_it_speaks_again(routes):
    """THE MESSAGE THAT ACTUALLY ARRIVES. Once the run is not "running", progress refuses it
    — so the cancel flag never gets read, and the 409 is what tells the runner."""
    _running(routes)
    routes.abandon("r1")
    with pytest.raises(Exception) as exc:
        routes.progress("r1", routes.ProgressRequest(runner_id="RUNNER-1", lines=[]))
    assert getattr(exc.value, "status_code", None) == 409


def test_stopping_something_already_finished_is_refused_not_pretended(routes):
    run = _running(routes)
    run.status = "done"
    with pytest.raises(Exception) as exc:
        routes.abandon("r1")
    assert getattr(exc.value, "status_code", None) == 409


# ── the runner acts on it ────────────────────────────────────────────────────────────

def test_the_runner_treats_a_409_as_a_stop():
    """A runner that only understood an explicit cancel flag would never see one, because the
    request carrying it is the one being refused."""
    assert "resp.status_code == 409" in RUNNER_SRC
    assert "no longer ours" in RUNNER_SRC


def test_the_runner_also_understands_an_explicit_cancel():
    assert '.get("cancel")' in RUNNER_SRC


def test_the_runner_ends_the_engine_rather_than_only_noting_it():
    """Abandoning frees the queue and stops nothing. If the runner does not terminate the
    engine, SOLIDWORKS and Excel carry on driving a desktop for the fifteen minutes the job
    had left, in front of a queue."""
    beat = RUNNER_SRC[RUNNER_SRC.index("def beat("):]
    beat = beat[:beat.index("\n    print(")] if "\n    print(" in beat else beat
    assert "stop_asked" in beat
    assert "proc.terminate()" in beat


def test_the_engine_is_terminated_before_it_is_killed():
    """It holds COM handles on Excel and SOLIDWORKS. Terminate lets it unwind them; an
    orphaned hidden Excel on that desktop is how the NEXT run fails for a reason nobody
    traces back to here."""
    order = RUNNER_SRC.index("proc.terminate()"), RUNNER_SRC.index("proc.kill()")
    assert order[0] < order[1]


def test_the_reason_for_stopping_reaches_the_log():
    """"Stopped from the page" and "the service says this run is no longer ours" are
    different events. A bare boolean would make the second read like the first on a morning
    nobody pressed stop."""
    assert 'stop_asked: str = ""' in RUNNER_SRC
    assert "STOPPING —" in RUNNER_SRC


# ── the page offers it ───────────────────────────────────────────────────────────────

def test_the_page_has_a_stop_control():
    assert 'id="stop"' in PAGE
    assert "stopBtn.onclick" in PAGE


def test_the_stop_control_is_only_offered_while_something_is_running():
    """Pressed against a finished run it would read as having done something."""
    assert "stopBtn.hidden = !running" in PAGE


def test_the_page_knows_which_run_it_would_stop():
    """runId lived inside the start handler, so the moment that handler returned the page no
    longer knew what was running. A run id the page cannot name is a run it cannot stop,
    however many buttons it grows."""
    assert re.search(r"^let runId\s*=\s*null;", PAGE, re.M), (
        "runId must be declared at page scope, not inside the start handler")
    assert PAGE.count("let runId") == 1, "declared twice is declared in the wrong place"


def test_the_page_does_not_promise_an_instant_stop():
    """The runner beats at lease/6 capped to 30s. Saying "stopping now" when it is up to half
    a minute away is how a stop that IS working gets pressed three more times."""
    assert "BEAT_HINT" in PAGE
    assert "not instantly" in PAGE


def test_stopping_asks_first():
    """It throws away fifteen minutes of a SOLIDWORKS seat. That deserves a question."""
    stop = PAGE[PAGE.index("stopBtn.onclick"):]
    stop = stop[:stop.index("runBtn.onclick")]
    # THE CONFIRM MUST GUARD THE CALL, not merely appear near it. A mutant reading
    # `if(false && confirm(...))` passed a test that only asked whether the word was present.
    assert "if(!confirm(" in stop
    assert stop.index("if(!confirm(") < stop.index("abandon"), (
        "the run is abandoned before anybody is asked")


# ── the same button, on the multi-drawing enquiry ────────────────────────────────────

def test_the_enquiry_stop_no_longer_disclaims_what_it_now_does():
    """It read "this does NOT stop the engine — its result will be refused when it reports",
    which was true and honest before the runner could be told anything. Left standing after
    the single-run stop learned to end the engine, it would talk somebody out of pressing the
    button that does the thing they want."""
    stop = PAGE[PAGE.index('$("bStop").onclick'):]
    stop = stop[:stop.index("function watchBatch")]
    assert "does NOT stop the engine" not in stop
    assert "ends the engine" in stop


def test_the_enquiry_stop_says_how_long_it_takes():
    stop = PAGE[PAGE.index('$("bStop").onclick'):]
    stop = stop[:stop.index("function watchBatch")]
    assert "BEAT_HINT" in stop


def test_the_enquiry_stop_reports_what_it_released(routes):
    """A button that appears to do nothing for half a minute is a button somebody presses
    three more times — and on a hundred-drawing enquiry the count is the reassurance."""
    stop = PAGE[PAGE.index('$("bStop").onclick'):]
    stop = stop[:stop.index("function watchBatch")]
    assert "released" in stop
    # THE GUARD, NOT THE WORDS. Asserting the phrase merely appears passes against
    # `if(false){ ... "Could not stop" ... }` — a mutant proved exactly that. The check has to
    # be that a failed response short-circuits BEFORE the success line is written.
    assert "if(!r.ok){" in stop, "a refusal is not distinguished from a success"
    assert stop.index("if(!r.ok){") < stop.index("Stopped —"), (
        "the success message is written before the response is checked")


def test_stopping_a_batch_asks_first():
    stop = PAGE[PAGE.index('$("bStop").onclick'):]
    stop = stop[:stop.index("function watchBatch")]
    assert "if(!confirm(" in stop
    assert stop.index("if(!confirm(") < stop.index("abandon")
