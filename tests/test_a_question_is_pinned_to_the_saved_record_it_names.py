"""One question service for the estimating app and the e-mail page, pinned to one saved record
(D-615, D-616).

JG, 1 Nov 2026: "yes, switch it to grok-4.7", then the review of that change: one shared AI
question service for the estimating screen and the e-mail walkthrough, answering from the
selected saved estimate, with five gaps closed before it is reused:

  release status is read from costed_job.release, where saved records keep it;
  incomplete context is disclosed, and the parts a question names are retrieved;
  a missing record stops with "record unavailable", never a model asked with no evidence;
  the selected run, record name and source fields come back with every answer;
  prices are returned from the record directly, and the model explains, never replaces, them.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimate_qa as qa  # noqa: E402


def _line(n, gbp, desc=None, kind="fabricated"):
    return {"part_number": f"12677-01-{n:03d}", "description": desc or f"Bracket {n}",
            "qty_per_unit": 1, "material_label": "1.5 CR4", "kind": kind,
            "charged_unit_gbp": gbp, "charged_ext_gbp": gbp, "charged_cell": f"Estimate!H{n}"}


RECORD = {
    "drawing_number": "12677-01-GA", "customer": "M&S", "requested_order_quantity": 1,
    "final_estimate": {"totals": {"unit_gbp": 421.37, "material_gbp": 250.0,
                                  "labour_gbp": 171.37, "unit_cell": "Estimate!H62"},
                       "labour_rows": [{"operation": f"Op {i}", "total_value_gbp": 30 - i}
                                       for i in range(30)]},
    "costed_job": {
        "run": {"order_qty": 1, "unit_gbp": 421.37},
        "lines": [_line(i, 100 - i) for i in range(1, 60)]
        + [_line(77, 0.5, "Frame tube 25x25", kind="bought_in")],
        "release": {"status": "provisional", "to_confirm": 3, "prices_outstanding": 2,
                    "decisions_open": 1, "reasons": ["2 prices outstanding", "1 decision open"]},
        "decisions_required": [{"kind": "missing_price", "part": "12677-01-077"}],
    },
    "review_flags": ["the frame material is not charged"],
    "release_decision": {"status": "IGNORE-ME"},
}


def _asked(reply="The unit cost is £421.37, mostly material."):
    seen = {"calls": 0}

    def ask(text, **kw):
        seen.update(prompt=text, kw=kw, calls=seen["calls"] + 1)
        return {"answer": reply}
    return seen, ask


def _ask(question, reply="The unit cost is £421.37, mostly material.", **extra):
    seen, ask = _asked(reply)
    got = qa.answer(dict({"question": question, "record": RECORD,
                          "record_name": "12677-01-GA_20261031_record.json",
                          "run_id": "run-7"}, **extra), ask=ask)
    return got, seen


# ── release status ──────────────────────────────────────────────────────────────────────

def test_release_status_comes_from_costed_job_release():
    got, seen = _ask("What is still outstanding before release?")
    known = json.loads(seen["prompt"].split("ESTIMATE FACTS (JSON): ", 1)[1].split("\n\n")[0])
    assert known["release"]["status"] == "provisional" and known["release"]["to_confirm"] == 3
    assert "IGNORE-ME" not in seen["prompt"]
    assert "costed_job.release" in got["sources"] and "release_decision" not in got["sources"]
    assert "Release: provisional; 3 to confirm (2 prices outstanding, 1 decisions open)." \
        in got["recorded"]


def test_an_older_record_without_it_falls_back_to_release_decision():
    old = {"final_estimate": {"totals": {"unit_gbp": 5.0}},
           "release_decision": {"status": "held"}}
    ev = qa.evidence(old, "is it released?")
    assert ev["known"]["release"]["status"] == "held" and "release_decision" in ev["sources"]


# ── incomplete context ──────────────────────────────────────────────────────────────────

def test_a_part_the_question_names_is_sent_even_beyond_the_largest_forty():
    got, seen = _ask("What is 12677-01-077 charged at, and is it bought in?")
    assert '"part": "12677-01-077"' in seen["prompt"]
    assert any(line.startswith("12677-01-077 Frame tube 25x25 [bought_in]: 1 per unit, "
                               "charged £0.50 per finished unit (Estimate!H77)")
               for line in got["recorded"])


def test_what_was_left_out_is_counted_and_said():
    got, seen = _ask("What drives the cost?")
    assert got["coverage"]["parts"] == [40, 60] and got["coverage"]["labour_lines"] == [25, 30]
    assert got["coverage_note"].startswith("Answered from part of the record: 40 of 60 parts, "
                                           "25 of 30 labour lines")
    assert "EVIDENCE: Answered from part of the record" in seen["prompt"]
    assert "say the answer rests on part of the record" in seen["prompt"]


def test_a_record_seen_whole_says_so():
    small = {"final_estimate": {"totals": {"unit_gbp": 5.0}},
             "costed_job": {"lines": [_line(1, 5.0)]}}
    got = qa.answer({"question": "How much?", "record": small}, ask=_asked("£5.00.")[1])
    assert got["coverage_note"] == ""


# ── missing record ──────────────────────────────────────────────────────────────────────

def test_no_record_is_record_unavailable_and_the_model_is_not_asked(tmp_path):
    seen, ask = _asked()
    for payload in ({"records": []}, {"record_path": str(tmp_path / "gone_record.json")},
                    {"record": {"notes": "nothing to answer from"}}):
        got = qa.answer(dict(payload, question="How much?", run_id="run-9"), ask=ask)
        assert got["status"] == "unavailable" and got["answer"].startswith("Record unavailable")
        assert got["run_id"] == "run-9"
    assert seen["calls"] == 0


def test_two_saved_records_for_one_run_is_not_a_guess(tmp_path):
    for n in ("a_record.json", "b_record.json"):
        (tmp_path / n).write_text(json.dumps(RECORD), encoding="utf-8")
    got = qa.answer({"question": "How much?",
                     "records": [str(tmp_path / "a_record.json"), str(tmp_path / "b_record.json")]},
                    ask=_asked()[1])
    assert got["status"] == "unavailable" and "2 saved records belong to this run" in got["answer"]


def test_the_pinned_record_file_wins_over_other_json(tmp_path):
    (tmp_path / "12677-01-GA.json").write_text(json.dumps(
        {"final_estimate": {"totals": {"unit_gbp": 999.0}}}), encoding="utf-8")
    (tmp_path / "12677-01-GA_record.json").write_text(json.dumps(RECORD), encoding="utf-8")
    got = qa.answer({"question": "How much?", "records": [str(tmp_path / "12677-01-GA.json"),
                                                          str(tmp_path / "12677-01-GA_record.json")]},
                    ask=_asked()[1])
    assert got["record_name"] == "12677-01-GA_record.json"
    assert got["recorded"][0].startswith("Unit cost £421.37")


# ── sources ─────────────────────────────────────────────────────────────────────────────

def test_every_answer_names_its_run_record_and_fields():
    got, _ = _ask("How much?")
    assert (got["run_id"], got["record_name"]) == ("run-7", "12677-01-GA_20261031_record.json")
    assert {"final_estimate.totals", "costed_job.lines", "costed_job.release",
            "costed_job.decisions_required", "review_flags"} <= set(got["sources"])
    unavailable = qa.answer({"question": "How much?", "run_id": "run-7",
                             "record_name": "x_record.json", "records": []})
    assert (unavailable["run_id"], unavailable["record_name"]) == ("run-7", "x_record.json")


def test_the_model_that_answered_is_named(monkeypatch):
    import config
    monkeypatch.setattr(config, "XAI_MODEL", "grok-4.7")
    assert _ask("How much?")[0]["model"] == "grok-4.7"


# ── prices ──────────────────────────────────────────────────────────────────────────────

def test_the_unit_price_is_returned_from_the_record_not_the_model():
    got, _ = _ask("What is the unit price?", reply="It is mostly material.")
    assert got["recorded"][0] == "Unit cost £421.37 ex VAT at 1 off, workbook cell Estimate!H62."
    assert got["answer"] == "It is mostly material."


def test_a_figure_the_record_does_not_hold_is_refused():
    got, _ = _ask("What would it cost at 50 off?", reply="At 50 off it would be about £310.00.")
    assert got["refused_figures"] == ["£310.00"]
    assert "£310.00" not in got["recorded"] and "not in this record, so it is not shown" \
        in got["answer"]
    assert got["recorded"][0].startswith("Unit cost £421.37")


def test_figures_the_record_holds_pass_whole_or_to_the_penny():
    got, _ = _ask("How much?", reply="£421.37 a unit, or roughly £421; labour is £171.37.")
    assert got["refused_figures"] == [] and got["answer"].startswith("£421.37 a unit")


def test_the_prompt_forbids_replacing_a_price():
    _, seen = _ask("How much?")
    assert "Never invent or recalculate a price" in seen["prompt"]
    assert "Explain the figures; do not replace them." in seen["prompt"]


def test_the_apps_lookup_goes_with_it_as_the_exact_reading():
    _, seen = _ask("How much?", record_answer="Calculated unit total: £421.37.")
    assert "RECORD LOOKUP (a rule-based reading of the same record, exact): Calculated unit " \
           "total: £421.37." in seen["prompt"]


# ── read-only, and offline ──────────────────────────────────────────────────────────────

def test_asking_writes_nothing(tmp_path):
    rec = tmp_path / "12677-01-GA_record.json"
    rec.write_text(json.dumps(RECORD), encoding="utf-8")
    before = sorted((p.name, p.stat().st_mtime_ns) for p in tmp_path.iterdir())
    qa.answer({"question": "How much?", "record_path": str(rec)}, ask=_asked()[1])
    assert sorted((p.name, p.stat().st_mtime_ns) for p in tmp_path.iterdir()) == before


def test_offline_the_model_is_not_asked_and_the_record_figures_still_come_back():
    got = qa.answer({"question": "How much?", "record": RECORD})
    assert got["status"] == "unavailable" and got["recorded"][0].startswith("Unit cost £421.37")
