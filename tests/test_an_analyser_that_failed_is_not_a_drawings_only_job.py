"""The seat was there, the models were there, the analyser ran, it failed — and the estimate
came out looking like an ordinary job that simply has no models.

TWO THINGS THAT LOOK IDENTICAL ON A FINISHED SHEET.

    A job with no SolidWorks seat. The engine uses the model when it is there and the drawings
    when it is not; that is the design, not a degraded mode of it, and `native_models_not_read`
    is deliberately a WARNING for exactly that reason.

    A job whose analyser was INVOKED and FAILED. A licence that has lapsed, a COM dialog left
    open on the desktop, a model that will not open. The models are in the pack, the machine
    was meant to read them, nothing was read, and the estimate was costed from the drawings
    while the geometry it should have used sat unread beside it.

The second is not the ordinary path. It is an estimate missing evidence it was supposed to
have, caused by something a person can go and fix, and at WARNING it reads as the first —
which is how a drawings-only run gets taken for finished work.

BLOCKING ONLY WHEN THE FAILURE ACTUALLY COST US THE GEOMETRY. If an extract was applied, the
run has model geometry and an analyser that could not refresh it is a warning, exactly as
before. And a job with no models cannot reach this at all, whatever the analyser said.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from invariants import BLOCKING, WARNING, check_native_evidence_is_current   # noqa: E402


def _v(sw):
    return check_native_evidence_is_current({"solidworks_native": sw})


def _one(sw, code="native_analyser_failed"):
    return next((v for v in _v(sw) if v["code"] == code), None)


# ── it tried, it failed, and nothing was read ────────────────────────────────────────────

def test_an_analyser_that_failed_with_models_present_blocks():
    v = _one({"found": False, "native_files_present": 19,
              "analyser_error": "the SolidWorks analyser exited 1: no licence available"})
    assert v is not None
    assert v["severity"] == BLOCKING


def test_it_says_how_many_models_went_unread_and_why():
    v = _one({"found": False, "native_files_present": 19,
              "analyser_error": "no licence available"})
    assert "19 SolidWorks model file(s)" in v["message"]
    assert "RUN and FAILED" in v["message"]
    assert "no licence available" in v["message"]


def test_it_says_not_to_treat_the_estimate_as_drawings_only():
    """The whole failure is that the sheet is indistinguishable from a job with no models."""
    v = _one({"found": False, "native_files_present": 3, "analyser_error": "COM error"})
    assert "rather than treating this as a drawings-only job" in v["message"]


# ── the cases that are not this ──────────────────────────────────────────────────────────

def test_a_failure_that_still_had_an_extract_to_use_is_a_warning():
    """The run has model geometry. An analyser that could not refresh it is worth saying and
    is not a missing-evidence defect."""
    v = _one({"found": True, "native_files_present": 19,
              "analyser_error": "the analyser timed out"})
    assert v["severity"] == WARNING
    assert "existing extract was used" in v["message"]


def test_a_job_with_no_models_is_untouched_by_this():
    """12349-02 read from drawings because it had no models in the pack is the ordinary path,
    and a job with none at all cannot be short of model evidence."""
    v = _one({"found": False, "native_files_present": 0,
              "analyser_error": "SolidWorks is not installed on this machine"})
    assert v["severity"] == WARNING


def test_no_analyser_error_raises_nothing_at_all():
    assert _one({"found": False, "native_files_present": 19}) is None


def test_the_seatless_machine_is_still_only_a_warning():
    """No attempt, no error — models present and unread. Unchanged: a machine without a seat
    is normal, and calling it a defect taught people to scroll past red lines."""
    vs = _v({"found": False, "native_files_present": 19,
             "native_present_but_unread": True,
             "reason": "no extract has been generated"})
    unread = next(v for v in vs if v["code"] == "native_models_not_read")
    assert unread["severity"] == WARNING
    assert not any(v["code"] == "native_analyser_failed" for v in vs)
