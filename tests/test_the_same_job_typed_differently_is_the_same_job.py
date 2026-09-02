"""Two runs of one job must collide, however the client's name was typed.

The staged folder is <root>\\<client>\\<drawing> and it is CLEARED before it is filled, so a
second run of the same job while the first is still reading it deletes the drawings underneath
the engine. The guard against that compared the client exactly — and the folder it names lives
on Windows, where paths are case-insensitive. "Fanatics" and "fanatics" were one folder and two
jobs, and the second quietly destroyed the first.

Reached by nothing more than typing the customer's name differently an hour later, which is
what happens when somebody else re-queues the job.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"))

import estimate_routes                                                   # noqa: E402


@pytest.fixture(autouse=True)
def _empty_registry():
    estimate_routes._RUNS.clear()
    yield
    estimate_routes._RUNS.clear()


def _queue(client: str, drawing: str, status: str = "running") -> estimate_routes.Run:
    run = estimate_routes.Run(run_id=f"r{len(estimate_routes._RUNS)}", client=client,
                              drawing_number=drawing, units=1, job_folder="",
                              output_path="", status=status)
    estimate_routes._RUNS[run.run_id] = run
    return run


@pytest.mark.parametrize("typed", ["fanatics", "FANATICS", "FaNaTiCs", " Fanatics "])
def test_the_client_typed_any_way_collides_with_the_run_holding_the_folder(typed):
    live = _queue("Fanatics", "12349-02-69-GA")
    assert estimate_routes._active_run_for(typed, "12349-02-69-GA") is live, (
        "the staged folder is the same folder on a case-insensitive filesystem, so this is "
        "the same job and running it now would clear the drawings the first run is reading")


@pytest.mark.parametrize("typed", ["12349-02-69-ga", "12349-02-69-GA "])
def test_the_drawing_number_too(typed):
    live = _queue("Fanatics", "12349-02-69-GA")
    assert estimate_routes._active_run_for("Fanatics", typed) is live


def test_a_genuinely_different_job_still_queues_behind_rather_than_being_refused():
    """A hundred-drawing enquiry is a hundred different folders and must stay submittable."""
    _queue("Fanatics", "12349-02-69-GA")
    assert estimate_routes._active_run_for("Fanatics", "12552-00") is None
    assert estimate_routes._active_run_for("Boots", "12349-02-69-GA") is None


def test_a_finished_run_does_not_hold_the_folder():
    """The clearing is only destructive while something is reading it."""
    _queue("Fanatics", "12349-02-69-GA", status="done")
    assert estimate_routes._active_run_for("fanatics", "12349-02-69-GA") is None


def test_the_comparison_errs_towards_refusing():
    """A false match costs a message saying wait; a miss costs a corrupted estimate that
    looks entirely ordinary. Blank names must not silently match everything, though."""
    _queue("", "")
    assert estimate_routes._active_run_for("Fanatics", "12349") is None
