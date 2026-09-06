"""The HTML report is an estimator's working page: decisions before diagnostics.

James, on the 7332-01 report: "too much repetition and conflicting reassurance". It opened
with "structurally sound" and "every consistency check passed" on a job whose plating
membership, leg length and two commercial prices were all still open, and the reader had to
get through pages about the extraction tools to find that out.

Stage B, after the one record (Stage A): the page is Summary → Decisions required → Bill of
materials and hierarchy → Manufacturing route, each read from costed_facts.costed_job, and
then Evidence and diagnostics — everything the report used to be — collapsed under one
heading and opened for print. Nothing there was deleted; it moved below the decisions.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import job_report_html as jr  # noqa: E402
from test_one_costed_record_for_every_deliverable import seventy_three_thirty_two  # noqa: E402


def _page():
    return jr.build_report_html(seventy_three_thirty_two())


def _above_the_fold(html: str) -> str:
    return html.split('<details class="diag">')[0]


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ── the order ─────────────────────────────────────────────────────────────────

def test_the_sections_come_in_the_order_an_estimator_works():
    html = _page()
    marks = ["<h2>Summary</h2>", "<h2>Decisions required</h2>",
             "<h2>Bill of materials and hierarchy</h2>", "<h2>Manufacturing route</h2>",
             '<details class="diag">']
    positions = [html.index(m) for m in marks]
    assert positions == sorted(positions), positions


def test_the_diagnostics_are_collapsed_and_nothing_was_deleted():
    html = _page()
    assert '<details class="diag">' in html and '<details class="diag" open' not in html
    tail = html.split('<details class="diag">')[1]
    for kept in ("Estimate at a glance", "What the engine got right",
                 "Review items &amp; limitations", "Drawing analysis", "Verdict",
                 "How far to trust this number", "Consistency checks",
                 "How each operation was decided"):
        assert kept in tail, f"{kept} is no longer on the page"
    assert "beforeprint" in html, "the diagnostics would print closed"


# ── summary ───────────────────────────────────────────────────────────────────

def test_the_summary_is_the_sheets_money_and_the_release_status():
    top = _text(_above_the_fold(_page()))
    for figure in ("£80.09", "£40.89", "£33.59"):
        assert figure in top
    assert "Not for release" in top
    assert "PACKAGING, DELIVERY" in top
    assert "Diamond polished and plated" in top
    assert "priced on 7332-01-008" in top
    assert "7332-01-001, 7332-01-002, 7332-01-003, 7332-01-004, 7332-01-005" in top


def test_no_generic_reassurance_while_decisions_are_open():
    top = _above_the_fold(_page())
    for claim in ("structurally sound", "every consistency check passed", "completed cleanly",
                  "every check passed"):
        assert claim not in top, claim


# ── decisions ─────────────────────────────────────────────────────────────────

def test_the_decisions_name_the_issue_the_part_the_assumption_and_the_action():
    html = _page()
    section = html.split("<h2>Decisions required</h2>")[1].split("<h2>")[0]
    txt = _text(section)
    assert "PACKAGING carries no price" in txt and "DELIVERY carries no price" in txt
    assert "Which members of 7332-01-101 are plated after welding" in txt
    assert "mass priced on 7332-01-008" in txt
    assert "confirm the plated member list" in txt
    assert "Cut length of 7332-01-002: 1,397 mm" in txt
    assert "transcribed by llm_full_extract" in txt
    assert "£15.83" in txt and "£11.72" in txt
    # worst first: the missing prices lead
    assert txt.index("PACKAGING carries no price") < txt.index("Which members of")


# ── bill of materials and hierarchy ───────────────────────────────────────────

def test_the_bom_is_a_hierarchy_charged_at_the_sheets_figures():
    html = _page()
    section = html.split("<h2>Bill of materials and hierarchy</h2>")[1].split("<h2>Manufacturing")[0]
    assert section.count('<details class="asm"') >= 2, "the assemblies are not expandable"
    frame = section.split("7332-01-101</code>")[1]
    for member in ("7332-01-001", "7332-01-002", "7332-01-005", "7332-01-101-PLATE"):
        assert member in frame
    txt = _text(section)
    assert "£2.82" in txt and "engine £2.02 — not charged" in txt
    assert "15.88 × 15.88 × 1.2 × 1,397 mm" in txt
    assert "read by llm_full_extract" in txt
    assert "SDI section-stock trade rate" in txt
    assert "— (commercial line)" in txt and "— (subcontract service)" in txt
    assert "MILD STEEL" in txt
    assert "£40.89" in txt


# ── manufacturing route ───────────────────────────────────────────────────────

def test_the_route_is_the_priced_rows_with_their_decisions():
    html = _page()
    section = html.split("<h2>Manufacturing route</h2>")[1].split('<details class="diag">')[0]
    txt = _text(section)
    assert "Tubebend" in txt and "TBEN" in txt and "£6.29" in txt
    assert "decision:9e3d96e71416" in txt
    assert "12 rows" in txt and "£33.59" in txt and "they agree" in txt
    assert "Assemble/pack (Acrylic)" in txt and "P/P" in txt


# ── it still says the right thing on the jobs the old tests pinned ────────────

def test_a_job_with_nothing_outstanding_is_not_called_a_draft():
    html = jr.build_report_html({
        "estimate_summary": {"estimate_status": "ok", "part_estimates": [],
                             "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": 29.39}},
        "invariants": {"may_quote_firm": True, "blocking": 0, "unverified": 0,
                       "checks_run": ["a"] * 11, "violations": []},
    })
    top = _above_the_fold(html)
    assert "Not for release" not in top
    assert "Nothing on this estimate is waiting on a person" in top
