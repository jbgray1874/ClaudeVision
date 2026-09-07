"""Four views, one job: the workbook tabs, the covering e-mail, the HTML report and the quote
state the same facts about the same run.

James: "does all the four areas show consistency in terms of accuracy and content, even if the
views are different?" Stage A made them read one record; this file is the proof that they do,
fact by fact, on a run shaped like 7332-01 of 6 September 17:17. Each surface may say less —
the quote is customer-facing and names no gap — but nothing a surface says may differ from
what another says, and a fact the reader acts on (a decision, the finish, the release) must be
on every internal surface.

The workbook here is built from the fixture's own read-back rows, so the e-mail and the
Explanation tab read exactly the BOM the JSON records — the replay James asked for, offline.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

openpyxl = pytest.importorskip("openpyxl", reason="the e-mail and the Explanation read a workbook")

import client_quote_html as q  # noqa: E402
import costed_facts as cf  # noqa: E402
import estimate_explained as ee  # noqa: E402
import estimation_report as er  # noqa: E402
import job_report_html as jr  # noqa: E402
import wb_populate as W  # noqa: E402
from test_one_costed_record_for_every_deliverable import seventy_three_thirty_two  # noqa: E402


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@pytest.fixture(scope="module")
def surfaces(tmp_path_factory):
    d = tmp_path_factory.mktemp("job")
    job = seventy_three_thirty_two()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["D6"] = 6
    ws["C9"] = "Bill of Materials (Per Unit)"
    ws["H9"] = "Part code"
    r = 10
    for m in job["final_estimate"]["material_rows"]:
        if m["block"] != "bom":
            continue
        ws.cell(r, 3, m["description"])
        ws.cell(r, 8, m["part_code"])
        ws.cell(r, 10, m["unit_price_gbp"])
        ws.cell(r, 11, m["qty_per_unit"])
        r += 1
    # No AI Material Detail and no AI Price Provenance tab: the workbook no longer carries
    # them, and the e-mail and the Explanation read those rows from the run JSON.
    wb.create_sheet("Canonical Route")
    xlsx = d / "7332-01_20260906_171743.xlsx"
    wb.save(xlsx)
    jp = d / "7332-01.json"
    jp.write_text(json.dumps(job), encoding="utf-8")
    note = ee.covering_email(xlsx, jp, deliverables=["7332-01.xlsx"])
    return {
        "record": cf.costed_job(job),
        "explanation": ee.build(xlsx, jp),
        "email": note["text"],
        "subject": note["subject"],
        "report": _text(jr.build_report_html(job)),
        "quote": _text(q.build_quote_html(job, job_stem="7332-01")),
        "provenance": {p["part_number"]: p for p in er.build_provenance(job)},
        "price_provenance": {x[0]: x for x in W._price_provenance_rows(job)},
    }


INTERNAL = ("explanation", "email", "report")


# ── the money ─────────────────────────────────────────────────────────────────

def test_one_unit_cost_on_every_surface(surfaces):
    for name in INTERNAL + ("quote",):
        assert "£80.09" in surfaces[name], name


def test_material_and_labour_agree_on_every_internal_surface(surfaces):
    for name in INTERNAL:
        assert "£40.89" in surfaces[name] and "£33.59" in surfaces[name], name


def test_the_charged_acrylic_is_the_same_figure_everywhere(surfaces):
    for name in INTERNAL:
        assert "£2.82" in surfaces[name], name
    assert surfaces["provenance"]["7332-01-007"]["extended_cost"] == 2.82
    # the engine's £2.02 survives only beside the words that say it is not charged
    for name in INTERNAL:
        for m in re.finditer(r"2\.02", surfaces[name]):
            window = surfaces[name][m.start() - 80: m.end() + 80].lower()
            assert ("not charged" in window or "engine" in window), (name, window)


# ── the gaps ──────────────────────────────────────────────────────────────────

def test_the_two_unpriced_lines_are_the_same_two_on_every_internal_surface(surfaces):
    assert surfaces["record"]["gaps"]["unpriced"] == ["PACKAGING", "DELIVERY"]
    for name in INTERNAL:
        assert "PACKAGING" in surfaces[name] and "DELIVERY" in surfaces[name], name
    assert "Packaging and delivery not included" in surfaces["quote"]


def test_the_indicative_money_is_one_number_and_one_class(surfaces):
    for name in INTERNAL:
        s = surfaces[name]
        assert "£16.63" in s, name
        assert "£16.03" not in s, name
        # Saying "no line rests on an AI market indication" is the right sentence; calling
        # a line one is the defect. Drop the negation, then nothing may remain.
        s = s.replace("No line rests on an AI market indication", "")
        assert "AI market indication" not in s, name
        assert "market indications" not in s, name
    assert "market indication" not in surfaces["quote"].lower()


def test_the_leg_names_its_source_on_every_tab_and_the_report(surfaces):
    for name in ("explanation", "email", "report"):
        assert "section-stock trade rate" in surfaces[name], name
    assert "section-stock trade rate" in surfaces["provenance"]["7332-01-002"]["rate_basis"]
    assert "section-stock trade rate" in surfaces["price_provenance"]["7332-01-002"][3]
    assert "not named" not in surfaces["price_provenance"]["7332-01-002"][3]


def test_the_leg_length_is_one_number(surfaces):
    assert surfaces["provenance"]["7332-01-002"]["cut_length_mm"] == 1397.0
    assert surfaces["provenance"]["7332-01-002"]["operations"] == "tubebend"
    for name in INTERNAL:
        assert "1,397" in surfaces[name], name
        assert "9,106" not in surfaces[name] and "9106" not in surfaces[name], name


# ── the decisions ─────────────────────────────────────────────────────────────

def test_the_plating_decision_and_its_members_are_on_every_internal_surface(surfaces):
    for name in INTERNAL:
        s = surfaces[name]
        assert "7332-01-008" in s, name
        assert "7332-01-001, 7332-01-002, 7332-01-003, 7332-01-004, 7332-01-005" in s, name
        assert "plated after welding" in s, name


def test_the_leg_length_decision_is_on_every_internal_surface(surfaces):
    for name in INTERNAL:
        assert "Cut length of 7332-01-002" in surfaces[name], name
        assert "llm_full_extract" in surfaces[name], name


def test_the_finish_charged_is_the_same_words_everywhere(surfaces):
    for name in INTERNAL + ("quote",):
        assert "iamond polished and plated" in surfaces[name], name


def test_the_release_status_agrees(surfaces):
    """ONE TALLY, ONE PHRASE, FOUR SURFACES. On the 12:10 run of 7332-01 the same five
    open items were counted three different ways: banner 3, table 5, explanation 4+1,
    quote 2+1, e-mail 2+2+1. Every surface now prints outstanding_summary's phrase, so
    the counts cannot drift again."""
    rel = surfaces["record"]["release"]
    assert rel["draft"] and rel["outstanding"] == 4
    phrase = ("2 prices missing + 2 manufacturing decisions "
              "+ 2 indicative rates to verify")
    assert "PROVISIONAL" in surfaces["subject"]
    assert f"To settle: {phrase}." in surfaces["subject"]
    assert f"Not for release — 6 to settle: {phrase}" in surfaces["report"]
    assert f"DRAFT — not for issue · {phrase}" in surfaces["quote"]
    assert f"No — 6 to settle: {phrase}." in surfaces["explanation"]


# ── what must NOT be on any surface ───────────────────────────────────────────

def test_no_surface_carries_the_old_contradictions(surfaces):
    for name in INTERNAL + ("quote",):
        s = surfaces[name]
        assert "Powder / scrap" not in s, name
        assert not re.search(r"PACKAGING[^|\n]{0,120}MILD STEEL", s), name
        assert "structurally sound" not in s, name
        assert "every consistency check passed:" not in s, name
