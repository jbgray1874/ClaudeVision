"""Parity must not report a comparison it made as one it could not make.

On 10575-02 the card said:

    Unit costs could not both be read — the workbook was read via xlrd. A sheet nobody has
    opened in Excel holds no calculated values. Tick Resolve formulas through Excel and run
    it again.

Both halves were wrong, and the bundle sitting behind the message proved it:

  * the money-cell row for M117 had read BOTH sides — AI £168.03 against manual £832.80,
    pct_variance 395.6, status "fail";
  * the file was read by xlrd, which returns the values already computed in a binary .xls,
    so the Excel checkbox could not have changed anything. The card's own help text says so.

A parity report that finds a four-hundred-percent gap and then describes itself as unreadable
is worse than one that fails outright — the estimator closes it believing there is nothing to
see. The headline read the rollup comparison and nothing else; where that is absent, the money
cells hold the answer.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.append(str(_ROOT / "src"))
_spec = importlib.util.spec_from_file_location("pr", _ROOT / "src" / "parity_run.py")
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)


# The bundle 10575-02 actually produced, trimmed to what _headline reads.
THE_BUNDLE = {
    "workbook_read_mode": "xlrd",
    "precalculation_note": "Values from binary .xls via xlrd (computed results in the file).",
    "rollup_unit_cost_comparison": None,
    "status_counts": {"money_match": 1, "money_warning": 0, "money_fail": 4,
                      "labour_route_match": 0, "labour_route_issues": 0},
    "money_cell_comparisons": [
        {"cell": "D6", "label": "Reference order quantity",
         "json_numeric": 1.0, "workbook_cached_numeric": 1.0,
         "pct_variance": 0.0, "status": "match"},
        {"cell": "M69", "label": "Material subtotal",
         "json_numeric": 109.6524, "workbook_cached_numeric": 288.922744,
         "pct_variance": 163.4897, "status": "fail"},
        {"cell": "M117", "label": "Unit manufacturing cost (L)",
         "json_numeric": 168.0274, "workbook_cached_numeric": 832.7994148989436,
         "pct_variance": 395.6331, "status": "fail"},
    ],
}


def test_the_unit_costs_are_reported_not_declared_unreadable():
    h = pr._headline(THE_BUNDLE)
    assert h["ai_unit_cost_gbp"] == pytest.approx(168.0274)
    assert h["manual_unit_cost_gbp"] == pytest.approx(832.7994, abs=1e-3)


def test_the_gap_is_the_one_an_estimator_would_compute():
    h = pr._headline(THE_BUNDLE)
    assert h["gap_gbp"] == pytest.approx(-664.77, abs=0.01)


def test_the_verdict_comes_from_the_row_not_from_a_guess():
    """The bundle's own status, so the card and the file cannot disagree."""
    h = pr._headline(THE_BUNDLE)
    assert h["status"] == "fail"
    assert h["pct_variance"] == pytest.approx(395.6331)
    assert h["workbook_cell"] == "M117"


def test_the_rollup_still_wins_when_it_exists():
    """The fallback must not quietly take over from the comparison built for the job."""
    b = dict(THE_BUNDLE)
    b["rollup_unit_cost_comparison"] = {
        "workbook_unit_cost_cached": 500.0,
        "json_implied_unit_using_workbook_qty": 450.0,
        "status": "warning", "pct_variance": 10.0, "workbook_unit_cost_cell": "M105"}
    h = pr._headline(b)
    assert h["manual_unit_cost_gbp"] == 500.0
    assert h["ai_unit_cost_gbp"] == 450.0
    assert h["workbook_cell"] == "M105"


def test_a_genuinely_unreadable_workbook_still_reports_nothing():
    """The original protection has to survive. An empty value cache is not a £0 estimate, and
    inventing a number from a half-read row would be the one unforgivable outcome here."""
    b = dict(THE_BUNDLE)
    b["rollup_unit_cost_comparison"] = None
    b["money_cell_comparisons"] = [
        {"cell": "M117", "label": "Unit manufacturing cost (L)",
         "json_numeric": 168.03, "workbook_cached_numeric": None,
         "pct_variance": None, "status": "review"}]
    h = pr._headline(b)
    assert h["ai_unit_cost_gbp"] is None or h["manual_unit_cost_gbp"] is None
    assert h["gap_gbp"] is None


def test_a_subtotal_row_is_not_mistaken_for_a_unit_cost():
    """Material subtotal also has both sides populated and is not the headline figure."""
    b = dict(THE_BUNDLE)
    b["money_cell_comparisons"] = [r for r in THE_BUNDLE["money_cell_comparisons"]
                                   if r["cell"] != "M117"]
    h = pr._headline(b)
    assert h["ai_unit_cost_gbp"] is None, "a subtotal was reported as the unit cost"


# ── the CSV the page is told to fetch must be servable ─────────────────────────────────

def test_csv_is_servable_by_default():
    """The parity route returns bundle_csv_url pointing at /api/file and the card renders it
    as a button. Leaving .csv off the allowlist made the service refuse a link it had just
    handed out: 'Extension .csv is not served'."""
    src = (_ROOT / "sdi-intelligence-backend" / "config.py").read_text(encoding="utf-8")
    at = src.index('_opt("SDI_ALLOWED_EXTENSIONS"')
    assert ".csv" in src[at:src.index(")", at)], "the default extension list must include .csv"


# ── the report a person reads must actually be written ─────────────────────────────────

def test_run_parity_writes_the_html_report():
    """parity_report_html has existed all along — the job report imports its tables — but
    nothing wrote the standalone page, so this route produced a JSON nobody reads and a CSV
    that needs Excel. The renderer was there; the call was not."""
    src = (_ROOT / "src" / "parity_run.py").read_text(encoding="utf-8")
    assert "from parity_report_html import generate_report_files" in src
    assert '"bundle_html"' in src


def test_the_html_failing_cannot_lose_the_comparison():
    """The bundle is the record. A template fault in the report must not cost a comparison
    that was just computed successfully, so the call is failure-isolated."""
    src = (_ROOT / "src" / "parity_run.py").read_text(encoding="utf-8")
    at = src.index("from parity_report_html import generate_report_files")
    block = src[at - 200:at + 500]
    assert "try:" in block and "except Exception" in block


def test_the_route_hands_back_a_url_for_it():
    src = (_ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
    assert "bundle_html_url" in src


def test_the_page_offers_the_html_first():
    """Leading with the JSON or CSV sends an estimator into a 2,000-line file to answer
    'why did these two differ'."""
    page = (_ROOT / "sdi-intelligence-backend"
            / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
    at = page.index("bundle_html_url")
    assert at < page.index("bundle_json_url"), "the readable report must be listed first"
