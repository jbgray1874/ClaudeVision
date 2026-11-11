"""Ask about this comparison (D-628).

JG, 2 Nov 2026: questions beside the parity report and its spoken explanation, through the
existing text and voice interface. The answer uses that exact saved comparison, names parts,
cells and figures as it holds them, distinguishes a confirmed difference from an unresolved
assumption, never assumes the manual estimate is right, invents no price and changes nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

pytest.importorskip("openpyxl")
import estimate_qa as qa  # noqa: E402
import parity_compare as pcmp  # noqa: E402
from test_parity_compares_line_by_line import ai_summary, manual_workbook  # noqa: E402


@pytest.fixture()
def detail(tmp_path):
    return pcmp.compare(ai_summary(tmp_path / "a.json", qty=50, sweep={10: 150.0, 50: 90.0}),
                        manual_workbook(tmp_path / "m.xlsx", qty=10))


def _canned(text):
    def ask(prompt, **kw):
        ask.prompt = prompt
        return {"answer": text}
    return ask


def test_the_answer_is_pinned_to_the_saved_comparison(detail):
    ask = _canned("Delivery is £42.50 on the AI estimate against £40.00 on the manual sheet.")
    out = qa.answer({"question": "Are delivery and installation included on both?",
                     "comparison": detail, "comparison_name": "x.parity_detail.json"}, ask=ask)
    assert out["status"] == "answered" and out["refused_figures"] == []
    assert out["record_name"] == "x.parity_detail.json"
    assert any("Unit cost: AI" in r for r in out["recorded"])
    assert any("Sell price, kept apart from cost" in r for r in out["recorded"])


def test_the_rules_travel_in_the_prompt(detail):
    ask = _canned("fine")
    qa.answer({"question": "What should the estimator check first?", "comparison": detail},
              ask=ask)
    p = ask.prompt
    assert "NEVER treat the manual estimate as automatically" in p
    assert "CONFIRMED difference" in p and "UNRESOLVED" in p
    assert "authorises nothing" in p and "Never invent or recalculate a price" in p


def test_a_figure_the_comparison_does_not_hold_is_refused(detail):
    out = qa.answer({"question": "why", "comparison": detail},
                    ask=_canned("It is roughly £999.99 of hidden cost."))
    assert out["refused_figures"] == ["£999.99"]
    assert "not in this comparison" in out["answer"]


def test_a_record_that_is_not_a_comparison_is_refused(tmp_path):
    run_record = tmp_path / "12677_record.json"
    run_record.write_text(json.dumps({"final_estimate": {"totals": {"unit_gbp": 1}}}),
                          encoding="utf-8")
    out = qa.answer({"question": "why", "comparison_path": str(run_record)}, ask=_canned("x"))
    assert out["status"] == "unavailable"
    assert "not a saved line-by-line comparison" in out["answer"]


def test_no_model_still_returns_the_comparisons_own_figures(detail):
    out = qa.answer({"question": "why", "comparison": detail}, ask=lambda p, **k: None)
    assert out["status"] == "unavailable" and out["recorded"]
    assert "No answer came back from the model" in out["answer"]


def test_the_question_names_a_part_and_its_row_travels(detail):
    ask = _canned("fine")
    qa.answer({"question": "Has 12677-01-09 been missed?", "comparison": detail}, ask=ask)
    assert "12677-01-09" in ask.prompt
