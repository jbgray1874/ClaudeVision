"""A question in the estimating app is answered by grok-4.7 from the one saved record chosen (D-615).

JG, 1 Nov 2026: "yes, switch it to grok-4.7". The app's "Ask about a saved estimate" box matched
keywords ("cost", "part") against the record and printed a lookup; anything else fell through.
It now hands the exact record it chose, and its own lookup, to the engine's question module,
which asks the configured Grok model and answers from that record alone. Priority from JG the
same day: "questions and walkthroughs pinned to the correct saved estimate".
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimate_qa as qa  # noqa: E402

RECORD = {
    "drawing_number": "12678-01-GA", "customer": "M&S", "requested_order_quantity": 1,
    "final_estimate": {"totals": {"unit_gbp": 538.06, "material_gbp": 300.0,
                                  "labour_gbp": 238.06},
                       "labour_rows": [{"operation": "Weld (CO2)", "total_value_gbp": 90}]},
    "costed_job": {"lines": [{"part_number": "12678-01-003", "description": "Side panel",
                              "qty_per_unit": 2, "material_label": "1.5 CR4",
                              "charged_ext_gbp": 41.2}]},
}


def _asked():
    seen = {}

    def ask(text, **kw):
        seen.update(prompt=text, kw=kw)
        return {"answer": "The side panel 12678-01-003 is charged at £41.20 per unit."}
    return seen, ask


def test_a_record_handed_over_is_the_one_answered_from(tmp_path):
    other = tmp_path / "latest.json"
    other.write_text(json.dumps({"final_estimate": {"totals": {"unit_gbp": 999.0}}}),
                     encoding="utf-8")
    seen, ask = _asked()
    got = qa.answer({"question": "What is the side panel charged at?", "record": RECORD,
                     "records": [str(other)]}, ask=ask)
    assert got["status"] == "answered" and "£41.20" in got["answer"]
    assert '"unit_cost_gbp": 538.06' in seen["prompt"] and "999" not in seen["prompt"]


def test_the_charged_part_list_reaches_the_model():
    known = qa.facts(RECORD, [])
    assert known["parts"] == [{"part": "12678-01-003", "description": "Side panel",
                               "per_unit": 2, "material": "1.5 CR4", "charged_gbp": 41.2}]


def test_the_apps_own_lookup_goes_with_it_as_the_exact_reading():
    seen, ask = _asked()
    qa.answer({"question": "How much?", "record": RECORD,
               "record_answer": "Calculated unit total: £538.06; material £300.00."}, ask=ask)
    assert "RECORD LOOKUP (a rule-based reading of the same record, exact): Calculated unit " \
           "total: £538.06" in seen["prompt"]
    assert "Never invent or recalculate a price" in seen["prompt"]


def test_the_answer_says_which_model_gave_it(monkeypatch):
    import config
    monkeypatch.setattr(config, "XAI_MODEL", "grok-4.7")
    _, ask = _asked()
    assert qa.answer({"question": "How much?", "record": RECORD}, ask=ask)["model"] == "grok-4.7"


def test_no_answer_from_the_model_is_unavailable_not_invented():
    got = qa.answer({"question": "How much?", "record": RECORD}, ask=lambda *a, **k: None)
    assert got["status"] == "unavailable" and "model" not in got


def test_offline_the_module_asks_nobody():
    got = qa.answer({"question": "How much?", "record": RECORD})
    assert got["status"] == "unavailable"
