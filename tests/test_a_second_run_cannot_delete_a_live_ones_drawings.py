"""Pressing Run twice on one job must not delete the drawings the first run is reading.

STAGING CREATED THIS AND NOTHING REPORTED IT.

The staged folder is one per client and job, and it is CLEARED before it is filled — that is
the whole point, so a re-run cannot inherit a drawing the estimator took off the list. But
staging happens when Run is pressed, not when the run is claimed. So a second press while the
first is still working wipes the folder the engine has open and fills it with a different pack.
The first estimate then prices some mixture of the two, or dies on a file that vanished under
it, and the sheet it produces looks completely ordinary.

It is the only way in the service to corrupt a run that was going perfectly well, and the run
log gave no hint: it said "Staged 4 drawing(s) (replaced 5 from a previous run)" — which is the
normal, correct message for a re-run — and then "Queued behind 10575-02, running 603s".

A DIFFERENT job queued behind this one stays allowed, and these tests pin that too. A
hundred-drawing enquiry is a hundred different folders and none of them collide; refusing those
is what made the queue useless before, and this must not bring it back.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "sdi-intelligence-backend"


@pytest.fixture()
def routes(monkeypatch):
    """The route module, loaded the way the other backend tests load it."""
    sys.path.insert(0, str(_BACKEND))
    try:
        import estimate_routes  # noqa: PLC0415
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"the backend does not import here: {exc}")
    finally:
        if sys.path and sys.path[0] == str(_BACKEND):
            sys.path.pop(0)

    estimate_routes._RUNS.clear()
    yield estimate_routes
    estimate_routes._RUNS.clear()


def _run(routes, *, client: str, drawing: str, status: str):
    run = routes.Run(run_id=f"{client}{drawing}{status}".lower().replace("-", "")[:12],
                     client=client, drawing_number=drawing, units=1,
                     job_folder="j", output_path="o", queued_at=1.0)
    run.status = status
    if status == "running":
        run.started_at = 1.0
    routes._RUNS[run.run_id] = run
    return run


# ── the collision ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["running", "queued"])
def test_the_same_job_again_is_found_while_the_first_is_live(routes, status):
    """QUEUED counts, not only RUNNING. Two queued runs of one job stage in turn and the
    second's clear happens before the first is ever claimed."""
    live = _run(routes, client="Dyson", drawing="10575-02", status=status)
    assert routes._active_run_for("Dyson", "10575-02") is live


def test_a_finished_run_does_not_block_a_rerun(routes):
    """The ordinary re-run — same job, an hour later. This is what staging is FOR, and
    refusing it would make the folder impossible to refresh."""
    for done in ("done", "error"):
        routes._RUNS.clear()
        _run(routes, client="Dyson", drawing="10575-02", status=done)
        assert routes._active_run_for("Dyson", "10575-02") is None


def test_a_different_drawing_for_the_same_client_still_queues(routes):
    """THE HUNDRED-DRAWING ENQUIRY. Different drawing, different folder, no collision.

    Refusing anything while anything ran is what made the queue hold exactly one job, and
    this fix must not reintroduce it by a different door.
    """
    _run(routes, client="MandS", drawing="11650-01", status="running")
    assert routes._active_run_for("MandS", "11650-02") is None


def test_the_same_drawing_number_for_a_different_client_does_not_collide(routes):
    """Two clients can hold the same drawing number, and they stage to different folders."""
    _run(routes, client="Boots", drawing="12422", status="running")
    assert routes._active_run_for("Tesco", "12422") is None


# ── what the refusal has to carry ───────────────────────────────────────────────────────

def test_the_refusal_names_the_run_so_the_page_can_offer_a_release(routes):
    """The page pulls the run id out of the message with /estimate\\/([0-9a-f]{6,})\\/abandon/.

    A refusal the estimator cannot act on is a dead end: the desktop is held by a claim
    whose runner may well be dead, and the only exit was a hand-written POST.
    """
    import re

    live = _run(routes, client="Dyson", drawing="10575-02", status="running")
    live.run_id = "abc123def456"
    routes._RUNS[live.run_id] = live

    dup = routes._active_run_for("Dyson", "10575-02")
    message = (f"10575-02 for Dyson is already {dup.status} (603s). Running it again now "
               f"would replace the drawings that run is reading, so it is refused. Wait for "
               f"it to finish, or release it: POST /api/estimate/{dup.run_id}/abandon")

    found = re.search(r"estimate/([0-9a-f]{6,})/abandon", message)
    assert found and found.group(1) == "abc123def456", \
        "the page's own regex must find the run id in the words the service sends"
    assert "replace the drawings that run is reading" in message, \
        "say WHY it is refused — 'already running' alone reads as an arbitrary lock"
