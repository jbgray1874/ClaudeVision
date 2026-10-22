"""One release status, read everywhere (D-580).

The costed record's release — its draft flag, reasons and decisions — is the authority the
report, the quotation's story pages and the release gate all read; none of them counts for
itself. The workbook's DRAFT cell, written before the checks run and never rewritten after,
says it is a provisional count at workbook population and points at the report. A page
claims "every line sourced" only when the record holds nothing open. A blocked customer
copy stays blocked; the estimator's portal copy stays available; a finding raised after the
workbook was written reaches the report and the quote through the same record.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf  # noqa: E402
import invariants  # noqa: E402
import quote_story  # noqa: E402
from quote_state import CUSTOMER, PORTAL, NotReleasable, quote_state  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _job(*, draft: bool):
    """A costed job as the record holds it: priced lines, and a release the record has
    already decided — a draft with a decision owed, or settled with nothing open. The record
    carries its own release, as a costed record does, so the readers are what is tested here;
    the record's own counting is proven in test_every_count_on_the_page_is_one_count."""
    parts = [{"part_number": "UNIT-01", "description": "SHELF", "quantity": 2, "normalized_material": "MILD_STEEL",
              "unit_total_cost_gbp": 30.0, "unit_material_cost_gbp": 10.0, "concept_kind": "fabricated"}]
    s = {"job_number": "UNIT-GA", "job_output_stem": "UNIT-GA", "customer": "A Customer",
         "assumed_job_quantity": 1, "quantity": 1,
         "estimate_summary": {"part_estimates": [dict(p) for p in parts],
                              "canonical_part_estimates": [dict(p) for p in parts],
                              "assumed_job_quantity": 1},
         "manufacturing_writeup": {"parts": [dict(p) for p in parts]},
         "lines": [], "gaps": {}, "schema": cf.COSTED_JOB_SCHEMA,
         "decisions_required": [], "release": {"draft": False, "outstanding": 0, "reasons": [],
                                               "status": "firm", "checks_ran": True}}
    if draft:
        s["decisions_required"] = [{"part": "UNIT-01", "kind": "manufacturing_decision",
                                    "issue": "weld length not stated"}]
        s["release"] = {"draft": True, "outstanding": 1, "status": "provisional", "checks_ran": True,
                        "reasons": ["1 manufacturing decision(s) open"]}
    return s


def _plain():
    """The same job with no release decided on it: the record counts for itself."""
    s = _job(draft=False)
    for k in ("lines", "gaps", "schema", "decisions_required", "release"):
        s.pop(k, None)
    return s


def test_the_report_and_the_gate_read_the_same_record():
    s = _job(draft=True)
    job = cf.costed_job(s)
    assert job["release"]["draft"] is True
    state = quote_state(s)
    assert state["customer_releasable"] is False
    assert any(b["gate"] == "record_outstanding" for b in state["blocking"])
    # The report's headline count is the record's outstanding summary, not a count of its own.
    src = (ROOT / "src" / "job_report_html.py").read_text(encoding="utf-8")
    assert "s = outstanding_summary(record)" in src
    assert 'f"Estimator review — {s[\'total\']} item(s) to confirm: {s[\'phrase\']}"' in src


def test_the_workbook_cell_says_it_is_a_provisional_count():
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "a provisional count at workbook population — the" in src
    assert "final release status is on the report" in src
    cfs = (ROOT / "src" / "costed_facts.py").read_text(encoding="utf-8")
    assert "a provisional count at workbook population" in cfs
    assert "the report carries the final release status" in cfs


def test_the_story_claims_every_line_sourced_only_when_nothing_is_open():
    assert quote_story._sourced_words({"open_items": 0}) == \
        "Nested sheets, departmental rates and every line sourced."
    assert "every line sourced" not in quote_story._sourced_words({"open_items": 3})
    assert "3 items are being confirmed before the price is final" in quote_story._sourced_words({"open_items": 3})
    assert "every line on the price can be traced back" in quote_story._traced_words({"open_items": 0})
    assert "1 item is still being confirmed" in quote_story._traced_words({"open_items": 1})
    assert "2 items are still being confirmed" in quote_story._traced_words({"open_items": 2})


def test_open_items_are_the_records_not_a_count_of_our_own():
    # A record the engine itself finds settled (every line priced, commercial inputs
    # complete, release authorised) holds nothing open; the fixture is the one the draft
    # test releases to a customer. A record with a decision owed holds one.
    from test_a_draft_is_an_internal_word import _released_job
    assert quote_story.open_items(_released_job()) == 0
    assert quote_story.open_items(_job(draft=True)) >= 1
    src = (ROOT / "src" / "quote_story.py").read_text(encoding="utf-8")
    assert 'facts["open_items"] = open_items(summary)' in src
    assert 'rel = costed_job(summary).get("release") or {}' in src


def test_a_finding_raised_after_the_workbook_reaches_report_and_quote_alike():
    """The record counts for itself; a blocking check then fails after the workbook was
    written. The record becomes a draft with the check first among its decisions, the gate
    holds, the story's open-item count rises — through the one record — and the workbook
    cell, written earlier, had already said it was provisional."""
    s = _plain()
    before = cf.costed_job(s)
    assert not any(d.get("kind") == "consistency_check" for d in before["decisions_required"])
    n_before = quote_story.open_items(s)
    s["invariants"] = {"violations": [invariants._violation(
        "section_schedule_not_priced", invariants.BLOCKING, "a sheet's steel is not priced")],
        "blocking": 1}
    after = cf.costed_job(s)
    assert after["release"]["draft"] is True
    assert any(d.get("kind") == "consistency_check" for d in after["decisions_required"])
    assert quote_state(s)["customer_releasable"] is False
    assert quote_story.open_items(s) > n_before


def test_a_blocked_customer_copy_stays_blocked_and_the_portal_copy_stays():
    import client_quote_html as q
    from quote_state import release_meta_tag
    s = _job(draft=True)
    try:
        q.build_quote_html(s, job_stem="UNIT-GA", audience=CUSTOMER)
        raise AssertionError("a draft was released to a customer")
    except NotReleasable:
        pass
    html = q.build_quote_html(s, job_stem="UNIT-GA")
    assert release_meta_tag(PORTAL) in html and release_meta_tag(CUSTOMER) not in html
