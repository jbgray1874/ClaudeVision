"""The pre-run material step (D-313).

12645's sheets all say PLAIN CARBON STEEL and Dave Wright asked for it to be costed as mild
steel. A reviewer asked for that to be a person's confirmation for the job rather than a new
rule: per part, from controlled lists, a default that never overrides a drawing, a reason for
every override, and never a price. The answers become the job's answers file, which
estimator_confirmed already reads at its own ranks.
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

import estimator_confirmed as ec  # noqa: E402
import material_confirmation as mc  # noqa: E402
import source_precedence as sp  # noqa: E402


def _part(pn, **stated):
    src = {k: f"{pn} sheet" for k in stated if k != "material_text"}
    return {"part": pn, "stated": stated, "sources": src}


# A mixed pack: steel stated, acrylic stated, and one part the drawings say nothing about.
READING = {"parts": [
    _part("A-01M", material="MILD_STEEL", material_text="PLAIN CARBON STEEL",
          thickness_mm=4.0, finish="POWDER COATED"),
    _part("A-02M", material="ACRYLIC", material_text="ACRYLIC", thickness_mm=5.0),
    _part("A-03M"),
]}


def _build(answers):
    return mc.build_answers(READING, dict({"confirmed_by": "Dave Wright"}, **answers), "A",
                            today="2026-09-28")


# ── reading the pack ─────────────────────────────────────────────────────────────────────

def test_the_dxf_name_states_thickness_and_stock():
    d = mc.read_dxf_name("12645-01-01M-4MM MS_REVA.DXF")
    assert d["part"] == "12645-01-01M" and d["thickness_mm"] == 4.0
    assert d["material"] == "MILD_STEEL"
    assert mc.read_dxf_name("12645-02-03M-9.5MM MS_REVA.DXF")["thickness_mm"] == 9.5
    assert mc.read_dxf_name("12645-02GA_REVA.DXF") is None


def test_the_title_block_boxes_are_split_into_material_and_finish():
    assert mc._split_title_blob("PLAIN CARBON STEEL POWDER COATED") == \
        ("PLAIN CARBON STEEL", "POWDER COATED")
    assert mc._split_title_blob("RAW PLAIN CARBON STEEL RAW") == ("PLAIN CARBON STEEL", "RAW")


def test_plain_carbon_steel_is_one_question_with_the_grade_left_open():
    qs = mc.questions({p["part"]: p for p in READING["parts"]})
    assert len(qs) == 1
    q = qs[0]
    assert q["stated"] == "PLAIN CARBON STEEL" and q["engine_reads_as"] == "MILD_STEEL"
    assert q["parts"] == ["A-01M"]
    assert "Mild Steel" in q["ask"] and "grade stays open" in q["ask"]


def test_the_lists_carry_unknown_and_what_the_pack_states():
    v = mc.vocabulary({"parts": [_part("X", thickness_mm=9.5)]})
    for field in ("material", "thickness_mm", "finish"):
        assert v[field][0] == "unknown"
    assert 9.5 in v["thickness_mm"]
    assert "BOUGHT_IN" not in v["material"]


# ── the rules ────────────────────────────────────────────────────────────────────────────

def test_a_default_fills_only_what_the_drawings_leave_unstated():
    data, errors = _build({"default": {"material": "MILD_STEEL", "thickness_mm": 2.0}})
    assert errors == []
    assert "A-02M" not in data["parts"], "the acrylic part must not inherit the steel default"
    assert data["parts"]["A-03M"]["material"] == "MILD_STEEL"
    assert data["parts"]["A-03M"]["basis"] == "inferred"
    assert "A-01M" not in data["parts"]


def test_a_per_part_override_of_a_drawing_needs_a_reason():
    data, errors = _build({"parts": {"A-01M": {"thickness_mm": 5.0}}})
    assert data == {} and any("A-01M" in e and "reason" in e for e in errors)
    data, errors = _build({"parts": {"A-01M": {"thickness_mm": 5.0,
                                                 "reason": "5 mm is what the shop stocks"}}})
    assert errors == []
    entry = data["parts"]["A-01M"]
    assert entry["basis"] == "corrected" and "5 mm is what the shop stocks" in entry["note"]


def test_a_per_part_exception_that_agrees_is_a_confirmation():
    data, errors = _build({"parts": {"A-02M": {"material": "ACRYLIC"}}})
    assert errors == [] and data["parts"]["A-02M"]["basis"] == "read"


def test_the_answered_question_applies_only_to_parts_stating_those_words():
    data, _ = _build({"by_stated_material": {"PLAIN CARBON STEEL": "MILD_STEEL"}})
    assert set(data["parts"]) == {"A-01M"}
    assert "PLAIN CARBON STEEL" in data["parts"]["A-01M"]["read_from"]


def test_unknown_writes_nothing():
    data, errors = _build({"default": {"material": "unknown"},
                           "parts": {"A-03M": {"finish": "unknown"}}})
    assert errors == [] and data["parts"] == {}


@pytest.mark.parametrize("answers", [
    {"parts": {"A-01M": {"price_gbp": 5}}},
    {"default": {"cost": 1}},
    {"parts": {"A-01M": {"material": "MILD_STEEL", "unit_price": 2.0}}},
    {"rate": 4.38},
])
def test_no_price_can_be_saved(answers):
    data, errors = _build(answers)
    assert data == {}
    assert any("REFUSED" in e for e in errors)


def test_only_the_lists_are_accepted_and_a_name_is_required():
    _, errors = _build({"parts": {"A-03M": {"material": "UNOBTAINIUM"}}})
    assert any("not on the list" in e for e in errors)
    _, errors = _build({"parts": {"A-03M": {"thickness_mm": 7.3}}})
    assert any("not on the list" in e for e in errors)
    _, errors = mc.build_answers(READING, {"default": {"material": "MILD_STEEL"}}, "A")
    assert any("confirmed_by" in e for e in errors)


# ── the engine reads what the step writes ────────────────────────────────────────────────

def test_the_file_is_read_and_applied_by_the_engines_own_path(tmp_path):
    data, errors = _build({"default": {"finish": "RAW"},
                           "parts": {"A-01M": {"thickness_mm": 5.0, "reason": "stock"}}})
    assert errors == []
    job = tmp_path / "A"
    job.mkdir()
    mc.write_answers(job, "A", data)
    path = ec.find_corrections_file(job, None, "A")
    loaded, problems = ec.load_corrections(path)
    assert problems == []
    parts = [{"part_number": "A-01M", "normalized_thickness_mm": 4.0},
             {"part_number": "A-03M"}, {"part_number": "A-02M"}]
    report = ec.apply_estimator_confirmed(parts, loaded)
    assert report["unmatched"] == []
    assert parts[0]["normalized_thickness_mm"] == 5.0
    assert sp.source_of(parts[0], "normalized_thickness_mm") == ec.SOURCE
    assert parts[1]["normalized_finish"] == "RAW"
    assert any("Dave Wright" in f for f in parts[0].get("review_flags") or [])


def test_the_engine_accepts_a_finish_and_still_refuses_a_price(tmp_path):
    f = tmp_path / "B_confirmed.json"
    f.write_text(json.dumps({"parts": {"B-1": {"finish": "RAW", "price": 3}}}))
    loaded, problems = ec.load_corrections(f)
    assert loaded["parts"]["B-1"] == {"finish": "RAW"}
    assert any("REFUSED" in p for p in problems)


def test_a_run_without_answers_removes_only_the_portals_own_file(tmp_path):
    job = tmp_path / "A"
    job.mkdir()
    data, _ = _build({"default": {"finish": "RAW"}})
    mc.write_answers(job, "A", data)
    mc.write_answers(job, "A", None)
    assert not (job / "A_confirmed.json").exists()
    (job / "A_confirmed.json").write_text(json.dumps({"parts": {"A-03M": {"finish": "RAW"}}}))
    mc.write_answers(job, "A", None)
    assert (job / "A_confirmed.json").exists(), "a file a person wrote is never removed"


# ── the portal ───────────────────────────────────────────────────────────────────────────

def test_the_run_checks_the_answers_before_staging_and_writes_them_after():
    src = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
    start = src[src.index("def start(req: EstimateRequest"):]
    check = start.index("build_answers(")
    stage = start.index("staging.stage(")
    write = start.index("write_answers(")
    assert check < stage < write
    assert "material_answers: Optional[Dict[str, Any]] = None" in src


def test_the_page_sends_answers_only_when_the_estimator_asks():
    page = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
        encoding="utf-8")
    assert 'id="matUse"' in page
    assert "material_answers: (document.getElementById(\"matUse\") || {}).checked" in page
