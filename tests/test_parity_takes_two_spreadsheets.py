"""Parity has to be reachable by someone holding two spreadsheets.

The comparison has existed for months behind `main.py --estimate-full-parity-report
<summary.json>`. The adoption register says what that cost: nineteen estimates issued and not
one parity bundle produced by anybody but the engineer who wrote the flag. A capability only
its author can invoke is, for every practical purpose, a capability the business does not have.

So these tests are about the DOOR, not the arithmetic — estimate_full_parity_report is tested
elsewhere and is not re-tested here. What is pinned down is that the two things an estimator
actually holds resolve to the two things the report needs, and that when they do not, the
message says which one is wrong and what to do about it.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Loaded by explicit path rather than by prepending src/ to sys.path. Prepending would make the
# ENGINE's config module win over the portal backend's for the rest of the process, and the
# backend's tests would then fail somewhere else entirely, depending on collection order.
_spec = importlib.util.spec_from_file_location(
    "parity_run", _ROOT / "src" / "parity_run.py")
parity_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parity_run)


@pytest.fixture(autouse=True)
def _do_not_leak_the_engine_config():
    """Leave sys.modules exactly as found.

    THERE ARE TWO MODULES CALLED `config` IN THIS REPO — the engine's and the portal
    backend's — and whichever is imported first wins for everything afterwards.
    resolve_ai_summary() imports the engine's to find JSON_DIR, which caches it under the bare
    name 'config'. estimate_routes.py then binds THAT at import time and fails with
    "module 'config' has no attribute 'API_KEY'" — in the backend's own tests, several files
    later, for a reason that has nothing to do with them.

    That is a test leaking state into unrelated tests, which is worse than a failure: it makes
    the suite's result depend on the order it happens to run in. So this file cleans up after
    itself rather than leaving the next file to cope.
    """
    import sys as _sys
    before = {name: _sys.modules.get(name) for name in ("config", "estimate_routes")}
    try:
        yield
    finally:
        for name, mod in before.items():
            if mod is None:
                _sys.modules.pop(name, None)
            else:
                _sys.modules[name] = mod


def test_a_summary_json_is_taken_as_it_stands(tmp_path):
    j = tmp_path / "10575-02.json"
    j.write_text(json.dumps({"estimate_summary": {}}), encoding="utf-8")
    assert parity_run.resolve_ai_summary(j) == j


def test_the_engine_workbook_finds_its_own_summary(tmp_path):
    """The estimator reaches for the spreadsheet they were sent, not for a JSON.

    The engine writes '<stem>_20260818_133037.xlsx' beside '<stem>.json'. If that timestamp is
    not stripped, every workbook fails to find a summary that is sitting right next to it.
    """
    (tmp_path / "10575-02.json").write_text(json.dumps({"estimate_summary": {}}), encoding="utf-8")
    wb = tmp_path / "10575-02_20260818_133037.xlsx"
    wb.write_bytes(b"not really a workbook, but resolution never opens it")

    assert parity_run.resolve_ai_summary(wb) == tmp_path / "10575-02.json"


def test_a_workbook_with_no_summary_says_which_json_it_wanted(tmp_path):
    """A job run on another machine is the common case, and the message has to be actionable.

    'No summary found' leaves an estimator with nothing to do. Naming the file it looked for
    turns it into an errand they can complete.
    """
    wb = tmp_path / "12392-02_20260810_090000.xlsx"
    wb.write_bytes(b"x")
    with pytest.raises(parity_run.ParityInputError) as exc:
        parity_run.resolve_ai_summary(wb)
    msg = str(exc.value)
    assert "12392-02.json" in msg, "the message must name the summary it could not find"
    assert "another machine" in msg, "and say why it might legitimately be absent"


def test_the_old_xls_manual_estimates_are_accepted(tmp_path):
    """Most of the back catalogue is .xls, and the back catalogue is the comparison worth having.

    Refusing it would leave parity able to compare only jobs estimated since the format changed
    — which is to say, almost none of the ones with a manual estimate to compare against.
    """
    old = tmp_path / "1282 Milwaukee.xls"
    old.write_bytes(b"x")
    assert parity_run.check_manual(old) == old


def test_a_pdf_is_refused_as_a_manual_estimate(tmp_path):
    p = tmp_path / "drawing.pdf"
    p.write_bytes(b"x")
    with pytest.raises(parity_run.ParityInputError):
        parity_run.check_manual(p)


def test_a_missing_file_is_named(tmp_path):
    with pytest.raises(parity_run.ParityInputError) as exc:
        parity_run.check_manual(tmp_path / "not-here.xlsx")
    assert "not-here.xlsx" in str(exc.value)


# ── the headline ────────────────────────────────────────────────────────────────────────
#
# THE ONE THING THIS MUST NEVER DO IS SHOW A ZERO IT DOES NOT MEAN. openpyxl cannot calculate,
# so a workbook the engine wrote and nobody has opened has an EMPTY value cache. If that reads
# as £0.00, the card says the manual estimate was zero and the engine was infinitely over — and
# an estimator would act on it.

def test_an_unreadable_total_is_none_and_never_zero():
    headline = parity_run._headline({
        "rollup_unit_cost_comparison": {
            "workbook_unit_cost_cached": None,
            "json_implied_unit_using_workbook_qty": 41.20,
        },
        "workbook_read_mode": "openpyxl",
        "precalculation_note": "openpyxl returns cached values only.",
    })
    assert headline["manual_unit_cost_gbp"] is None
    assert headline["gap_gbp"] is None, "no gap can be computed against a value that is absent"
    assert headline["workbook_read_mode"] == "openpyxl"
    assert headline["precalculation_note"], "the reason it is blank has to travel with the blank"


def test_the_headline_reports_the_engines_verdict_not_its_own():
    """status comes from the bundle, so the card and the bundle cannot disagree.

    Recomputing 'is this a match?' in a second place is how a form ends up saying MATCH over a
    bundle that says FAIL. The thresholds live in config and are applied once, upstream.
    """
    headline = parity_run._headline({
        "rollup_unit_cost_comparison": {
            "workbook_unit_cost_cached": 40.00,
            "json_implied_unit_using_workbook_qty": 41.20,
            "pct_variance": 3.0,
            "status": "warning",
            "workbook_unit_cost_cell": "L105",
        },
        "status_counts": {"money_match": 7, "money_warning": 2, "money_fail": 1,
                          "labour_route_match": 11, "labour_route_issues": 3},
    })
    assert headline["status"] == "warning"
    assert headline["gap_gbp"] == 1.20
    assert headline["pct_variance"] == 3.0
    assert headline["workbook_cell"] == "L105"
    # The counts matter as much as the total: "the headline agrees" is a much weaker claim
    # than "the headline agrees and so do the cells underneath it".
    assert headline["money_fail"] == 1
    assert headline["labour_route_issues"] == 3


def test_a_boolean_is_not_mistaken_for_a_number():
    """True == 1 in Python, and a cell holding TRUE must not price at £1.00."""
    headline = parity_run._headline({
        "rollup_unit_cost_comparison": {
            "workbook_unit_cost_cached": True,
            "json_implied_unit_using_workbook_qty": 41.20,
        },
    })
    assert headline["manual_unit_cost_gbp"] is None
