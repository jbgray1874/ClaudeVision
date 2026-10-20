r"""
test_a_job_costed_with_no_price_source.py

THE MOST EXPENSIVE THING THIS ENGINE COULD DO QUIETLY, and it did it.

PricingService opens its connection in __init__, so an unreachable SDILive -- a dropped VPN,
a stopped SQL service, a rotated login -- raises there. estimator._get_pricing_service caught
that with a bare `except Exception`, set a module flag, and returned None. Not a word.

None is also what it returns when pricing is deliberately off. So every catalogue lookup and
every purchase-history lookup took the no-service branch and produced no price; the run
completed, the workbook calculated, the read-back stamped, the reports were written, and the
unit cost came out LOW -- with nothing on the console, nothing in the sheet and nothing in the
invariants saying the primary price source had never been asked a single question.

An estimate produced that way is indistinguishable from a correct one. It is the same shape as
native_folder_unreachable, where "I could not look" read downstream as "there is nothing
there", and it gets the same answer: SAY SO, RECORD IT, AND BLOCK.

The real occurrence: 11650 was re-run while the VPN was down and the profiler had just failed
against 10.0.0.200 with the same OperationalError.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import invariants          # noqa: E402
from invariants import BLOCKING, UNVERIFIED  # noqa: E402


# ── the estimator says so, once, and remembers why ──────────────────────────────────
@pytest.fixture
def estimator_with_no_service(monkeypatch, capsys):
    import estimator
    monkeypatch.setattr(estimator, "_PRICING_SERVICE_SINGLETON", None)
    monkeypatch.setattr(estimator, "_PRICING_SERVICE_FAILED", False)
    monkeypatch.setattr(estimator, "_PRICING_SERVICE_ERROR", None)
    monkeypatch.delenv("SDI_OFFLINE", raising=False)

    class _Boom:
        def __init__(self, *_a, **_k):
            raise OSError("08001 Login timeout expired — 10.0.0.200 not accessible")

    import pricing_service
    monkeypatch.setattr(pricing_service, "PricingService", _Boom)
    capsys.readouterr()          # discard anything already buffered
    return estimator


def test_an_unreachable_price_source_is_announced_not_swallowed(estimator_with_no_service, capsys):
    est = estimator_with_no_service
    assert est._get_pricing_service() is None, "a service that would not open must not be used"
    said = capsys.readouterr().out
    assert "COULD NOT BE REACHED" in said, (
        "the price source failed silently. A run costed with no price source produces a LOW "
        "unit cost that reads exactly like a correct one -- that is what this must stop.")
    assert "10.0.0.200" in said, "say WHAT failed, or nobody can act on it"
    assert "MISSING, not zero" in said, (
        "the distinction is the whole point: absent prices are not nil prices")


def test_the_reason_survives_for_the_reports_and_the_checks(estimator_with_no_service):
    """Scrollback is not a record. The runner discards it and the estimate outlives it."""
    est = estimator_with_no_service
    assert est.pricing_source_failure() is None, "nothing has failed yet"
    est._get_pricing_service()
    why = est.pricing_source_failure()
    assert why and "10.0.0.200" in why


def test_a_reachable_service_says_nothing(monkeypatch, capsys):
    """The message must be earned. Printed on a healthy run it stops being read."""
    import estimator, pricing_service
    monkeypatch.setattr(estimator, "_PRICING_SERVICE_SINGLETON", None)
    monkeypatch.setattr(estimator, "_PRICING_SERVICE_FAILED", False)
    monkeypatch.setattr(estimator, "_PRICING_SERVICE_ERROR", None)
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.setattr(pricing_service, "PricingService", lambda *_a, **_k: object())
    capsys.readouterr()
    assert estimator._get_pricing_service() is not None
    assert "COULD NOT BE REACHED" not in capsys.readouterr().out
    assert estimator.pricing_source_failure() is None


# ── and the check that refuses to let the number leave ──────────────────────────────
def test_a_job_costed_with_no_price_source_is_blocking():
    out = invariants.check_the_price_source_was_reached(
        {"price_source_unreachable": "OperationalError: 08001 login timeout"})
    assert len(out) == 1
    v = out[0]
    assert v["severity"] == BLOCKING, (
        "a warning is not enough. The figure is low by an unknown amount and the only safe "
        "action is to re-run, so this must stop the estimate being treated as firm.")
    assert "MISSING, not" in v["message"], "absent is not nil, and the message must say so"
    assert "re-run" in v["message"].lower(), "say what to DO about it"


def test_a_job_that_reached_the_price_source_raises_nothing():
    assert invariants.check_the_price_source_was_reached({"estimate_summary": {}}) == []


def test_an_unreadable_summary_is_unverified_not_a_pass():
    """Fail closed, like every other check in that module. A guard that goes green when its
    input vanishes is worse than no guard, because it gets quoted as evidence."""
    out = invariants.check_the_price_source_was_reached(None)
    assert out and out[0]["severity"] == UNVERIFIED


def test_the_check_actually_runs_on_every_job():
    """Built is not wired. This module has shipped checks nothing ever called."""
    assert invariants.check_the_price_source_was_reached in invariants.CHECKS


# ── the stamp, exercised rather than grepped ────────────────────────────────────────
def test_the_outage_reaches_both_the_summary_and_the_saved_json(
        estimator_with_no_service, tmp_path):
    """The invariants prefer the JSON on disk -- it is the one carrying final_estimate -- and
    fall back to the in-memory summary when it cannot be read. Stamping one leaves the other
    reporting a clean job."""
    est = estimator_with_no_service
    est._get_pricing_service()
    jp = tmp_path / "job.json"
    jp.write_text('{"estimate_summary": {"unit_cost": 12.3}}', encoding="utf-8")
    summary = {"estimate_summary": {}}

    assert est.stamp_price_source_status(summary, jp)

    import json as _json
    doc = _json.loads(jp.read_text(encoding="utf-8"))
    assert "10.0.0.200" in summary["price_source_unreachable"], "the summary was not stamped"
    assert "10.0.0.200" in doc["price_source_unreachable"], "the saved JSON was not stamped"
    assert doc["estimate_summary"]["unit_cost"] == 12.3, "the stamp destroyed the estimate"
    # And the check the engine actually runs must now fire on both of them.
    assert invariants.check_the_price_source_was_reached(summary)
    assert invariants.check_the_price_source_was_reached(doc)


def test_a_healthy_run_stamps_nothing(monkeypatch, tmp_path):
    """An absent key is what a good job looks like. Writing "reached: yes" onto every job
    would make the check depend on a field older jobs do not have."""
    import estimator
    monkeypatch.setattr(estimator, "_PRICING_SERVICE_ERROR", None)
    summary = {}
    assert estimator.stamp_price_source_status(summary, None) is None
    assert summary == {}


def test_an_unwritable_json_still_leaves_the_summary_stamped(estimator_with_no_service,
                                                             tmp_path, capsys):
    """Losing the estimate because the outage could not be written down would be worse than
    the outage. But going quiet puts the job back to looking clean, so it must be said."""
    est = estimator_with_no_service
    est._get_pricing_service()
    jp = tmp_path / "broken.json"
    jp.write_text("{ this is not json", encoding="utf-8")
    summary = {}
    capsys.readouterr()
    assert est.stamp_price_source_status(summary, jp)
    assert "price_source_unreachable" in summary
    assert "could not be written" in capsys.readouterr().out


def test_the_price_source_is_tested_before_any_drawing_is_parsed():
    """TWENTY MINUTES, AND A QUESTION THAT MIGHT NEVER BE ASKED.

    PricingService is built lazily, so an unreachable SDILive surfaced somewhere in the
    middle of costing -- after every drawing had been parsed -- and only if something asked
    for a price at all. A job could finish having never established whether the source it
    was meant to price from was even there. Probe first, fail in seconds.
    """
    import ast
    body = ast.unparse(ast.parse((ROOT / "src" / "main.py").read_text(encoding="utf-8")))
    assert "_probe_price_source" in body, "main never tests the price source up front"
    assert body.index("_probe_price_source") < body.index("scan_folder_job("), (
        "the price source is probed after the job has been scanned, which is the twenty "
        "minutes this exists to save")


def test_the_elevation_banner_does_not_promise_a_closed_list():
    """run-job.ps1 warned that elevation affects SOLIDWORKS and not Excel, and stopped --
    which reads as "those are the two things". It never mentioned the database, and 11650
    was run all week from an elevated console where TCP to SQL timed out while the same test
    from a normal console succeeded instantly. The banner is part of why nobody looked."""
    body = (ROOT / "run-job.ps1").read_text(encoding="utf-8-sig", errors="replace")
    start = body.index("this console is ELEVATED")
    banner = body[start:start + 3000]
    assert "DATABASE MAY BE AFFECTED" in banner, (
        "the elevation banner still enumerates Excel and SOLIDWORKS as though that were the "
        "whole list. It is not, and the omission was the database.")
    assert "Do not assume" in banner, \
        "the banner should send the reader to the run's own report, not to another prediction"


def test_main_stamps_the_outage_before_the_checks_read_it():
    """Ordering is the whole mechanism: PricingService is built lazily during costing, so the
    answer does not exist until estimating has finished -- and the checks read the stamped
    document, so the stamp has to land first."""
    import ast
    body = ast.unparse(ast.parse((ROOT / "src" / "main.py").read_text(encoding="utf-8")))
    assert "stamp_price_source_status" in body, "main never records whether pricing worked"
    assert body.index("stamp_price_source_status") < body.index("from invariants import check_job"), \
        "the outage is stamped after the invariants have already read the job"
