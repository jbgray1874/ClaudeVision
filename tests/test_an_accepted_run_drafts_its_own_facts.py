"""SCRUM-134: a draft of accepted_facts.json is read from the accepted run by the gate's own
readers, so it can never disagree with what the gate will check, and it is never accepted by
the tool itself.

The record here is synthetic test scaffolding, not any job's record: the real records stay on
the laptop and are never committed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "replay"))
sys.path.insert(0, str(ROOT / "tools"))

import costed_facts as cf                                                # noqa: E402
import draft_accepted_facts as daf                                       # noqa: E402
from test_frozen_replays import assert_accepted_structure                # noqa: E402


def _summary() -> dict:
    return {
        "processed_at": "2026-11-05T10:00:00",
        "part_estimates": [
            {"part_number": "S-01", "description": "Panel", "quantity": 2,
             "normalized_material": "STAINLESS_STEEL_304",
             "material_estimate": {"unit_material_cost_gbp": 5.0}},
            {"part_number": "S-02", "description": "Bracket", "quantity": 1,
             "normalized_material": "MILD_STEEL",
             "material_estimate": {"unit_material_cost_gbp": 1.5}},
        ],
        "workbook_labour": {"rows": [
            {"workbook_row": 10, "part_numbers": ["S-01"], "engine_operations": ["laser_cutting"]},
            {"workbook_row": 11, "part_numbers": ["S-01"], "engine_operations": ["laser_cutting"]},
            {"workbook_row": 12, "part_numbers": ["S-02"], "engine_operations": ["folding"]},
        ]},
    }


def test_the_draft_proposes_structure_from_the_record():
    facts = daf.draft(_summary())
    assert facts["bom_identities"] == ["S-01", "S-02"]
    assert facts["quantities"] == {"S-01": 2.0, "S-02": 1.0}
    assert facts["material_charged"] == ["S-01", "S-02"]
    assert facts["materials"]["S-01"] == "STAINLESS_STEEL_304"
    assert facts["no_duplicate_operations"] is True
    # the accepted run charges laser twice on S-01: proposed as a repeat to confirm, not hidden
    assert facts["allowed_repeats"] == {"S-01": ["laser_cutting"]}
    # charged here, so never proposed as forbidden anywhere
    assert "folding" not in facts["forbidden_operations_anywhere"]
    assert "laser_cutting" not in facts["forbidden_operations_anywhere"]
    assert "welding" in facts["forbidden_operations_anywhere"]


def test_a_draft_passes_the_gate_on_the_record_it_was_drawn_from():
    """The property the tool exists for: every pin it proposes holds on the accepted run."""
    summary = _summary()
    facts = daf.draft(summary)
    lines = [l for l in cf.costed_job(summary)["lines"] if isinstance(l, dict)]
    assert_accepted_structure("synthetic", facts, lines, summary=summary)


def test_a_draft_catches_the_duplicate_once_its_exception_is_struck():
    """Striking an allowed repeat in review turns the same record red: the pin is live."""
    summary = _summary()
    facts = daf.draft(summary)
    facts["allowed_repeats"] = {}
    lines = [l for l in cf.costed_job(summary)["lines"] if isinstance(l, dict)]
    with pytest.raises(AssertionError, match="S-01 laser_cutting x2"):
        assert_accepted_structure("synthetic", facts, lines, summary=summary)


def test_the_draft_carries_no_money_and_says_it_is_a_draft():
    facts = daf.draft(_summary())
    assert "DRAFT" in facts["_reviewed"]
    for key in facts:
        if not key.startswith("_"):
            assert "gbp" not in key.lower() and "price" not in key.lower()
    text = json.dumps({k: v for k, v in facts.items() if not k.startswith("_")})
    assert "5.0" not in text and "1.5" not in text


def test_bought_in_and_commercial_lines_carry_no_material_pin():
    summary = _summary()
    summary["part_estimates"].append(
        {"part_number": "S-90", "description": "Castor", "quantity": 4,
         "normalized_material": "BOUGHT_IN", "page_roles": ["bought_in"]})
    facts = daf.draft(summary)
    assert "S-90" in facts["bom_identities"]
    assert "S-90" not in facts["materials"]
    assert "S-90" not in facts["material_charged"]


def test_the_tool_writes_a_draft_and_never_replaces_accepted_facts(tmp_path, monkeypatch):
    src = tmp_path / "accepted_record.json"
    src.write_text(json.dumps(_summary()), encoding="utf-8")
    monkeypatch.setattr(daf, "REPLAY", tmp_path / "replay")
    assert daf.main(["SYNTH-01", "--source", str(src)]) == 0
    draft_file = tmp_path / "replay" / "SYNTH-01" / "accepted_facts.draft.json"
    assert json.loads(draft_file.read_text(encoding="utf-8"))["bom_identities"] == \
        ["S-01", "S-02"]
    assert not (tmp_path / "replay" / "SYNTH-01" / "accepted_facts.json").exists()
    (tmp_path / "replay" / "SYNTH-01" / "accepted_facts.json").write_text("{}", "utf-8")
    assert daf.main(["SYNTH-01", "--source", str(src)]) == 2


def test_a_draft_file_is_never_committed():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "tests/replay/*/accepted_facts.draft.json" in ignore
