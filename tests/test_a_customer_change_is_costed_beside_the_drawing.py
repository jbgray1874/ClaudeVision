"""Customer changes since the drawings (D-507).

"It happens sometimes and we don't have time to change the drawing pack." An e-mail asks for
2 mm instead of 1.5, stainless instead of mild steel, 250 off instead of 100. The estimator
pastes it; the engine proposes each change with the e-mail's own words; nothing is used without
a tick and a name; a change typed by hand needs a reason; what cannot be changed is asked on the
book; the book shows the drawn value beside the costed one. Never a price.
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

import customer_changes as cc  # noqa: E402
import source_precedence as sp  # noqa: E402

EMAIL = """Hi James,

Thanks for the drawings. Could you re-quote with the side panels in 2mm rather than 1.5mm
please, and we'd now like them in stainless. Also we need 250 off, not 100.
Can you also add a cable hole in the top?

Kind regards,
Sam"""

INDEX = {"parts": [
    {"part": "J-01M", "stated": {"material": "MILD_STEEL", "material_text": "MILD STEEL",
                                 "thickness_mm": 1.5, "finish": "POWDER COATED"}},
    {"part": "J-02M", "stated": {"material": "MILD_STEEL", "thickness_mm": 1.5}},
    {"part": "J-03M", "stated": {"thickness_mm": 3.0}},
], "context": "J-01M SIDE PANEL LH\nJ-02M SIDE PANEL RH\nJ-03M TOP"}


def _reply(changes, questions=()):
    return lambda prompt: json.dumps({"changes": list(changes), "questions": list(questions)})


# ── the read proposes; it never decides ─────────────────────────────────────────────────

def test_the_read_proposes_each_change_with_the_drawn_value_and_the_emails_words():
    out = cc.propose_changes(EMAIL, INDEX, call=_reply([
        {"parts": ["J-01M", "J-02M"], "field": "thickness_mm", "value": 2,
         "quote": "side panels in 2mm rather than 1.5mm"},
        {"parts": ["J-01M", "J-02M"], "field": "material", "value": "stainless",
         "quote": "we'd now like them in stainless"},
        {"parts": [], "field": "order_quantity", "value": 250, "quote": "we need 250 off"},
    ], [{"quote": "add a cable hole in the top", "ask": "a new hole is not a field"}]))
    assert out["status"] == "ok"
    thick = [c for c in out["changes"] if c["field"] == "thickness_mm"]
    assert {c["part"] for c in thick} == {"J-01M", "J-02M"}
    assert all(c["value"] == 2.0 and c["drawing_value"] == 1.5 for c in thick)
    mat = [c for c in out["changes"] if c["field"] == "material"]
    assert all(c["value"] == "STAINLESS_STEEL" for c in mat)
    assert mat[0]["drawing_value"] == "MILD STEEL"
    order = [c for c in out["changes"] if c["field"] == "order_quantity"]
    assert order and order[0]["value"] == 250 and order[0]["part"] == ""
    assert any("cable hole" in q["quote"] for q in out["questions"])
    assert not any(c.get("accepted") for c in out["changes"]), "nothing is ticked by the read"


def test_a_paraphrase_is_not_the_customers_instruction():
    out = cc.propose_changes(EMAIL, INDEX, call=_reply([
        {"parts": ["J-01M"], "field": "thickness_mm", "value": 2,
         "quote": "please make the panels two millimetres"}]))
    assert out["changes"] == []
    assert any("not in the e-mail" in q["ask"] for q in out["questions"])


def test_a_change_with_no_parts_or_an_unknown_field_becomes_a_question():
    out = cc.propose_changes(EMAIL, INDEX, call=_reply([
        {"parts": [], "field": "thickness_mm", "value": 2,
         "quote": "side panels in 2mm rather than 1.5mm"},
        {"parts": ["J-03M"], "field": "hole_count", "value": 1,
         "quote": "add a cable hole in the top"}]))
    assert out["changes"] == []
    asks = " ".join(q["ask"] for q in out["questions"])
    assert "which parts" in asks and "not something this box can change" in asks


def test_a_code_the_drawings_did_not_show_is_proposed_with_a_warning():
    out = cc.propose_changes(EMAIL, INDEX, call=_reply([
        {"parts": ["J-09M"], "field": "thickness_mm", "value": 2,
         "quote": "side panels in 2mm rather than 1.5mm"}]))
    assert out["changes"][0]["not_read_from_pack"] is True


def test_an_unreadable_or_offline_read_says_so_and_proposes_nothing():
    out = cc.propose_changes(EMAIL, INDEX, call=lambda p: "I think they want 2mm")
    assert out["status"] == "unavailable" and out["changes"] == []
    out = cc.propose_changes(EMAIL, INDEX)          # SDI_OFFLINE: no model is called
    assert out["status"] == "unavailable" and "by hand" in out["message"]
    assert cc.propose_changes("  ", INDEX)["status"] == "empty"


def test_the_prompt_carries_the_part_index_the_pack_text_and_the_email():
    p = cc.build_prompt(EMAIL, INDEX)
    assert "J-01M | drawing states: MILD STEEL, 1.5 mm, POWDER COATED" in p
    assert "SIDE PANEL LH" in p and "stainless" in p
    assert "copied character for character" in p


# ── the checks every change passes, from the read, the page and the file ───────────────

@pytest.mark.parametrize("raw, why", [
    ({"part": "J-01M", "field": "thickness_mm", "value": 2, "origin": "manual"}, "reason"),
    ({"part": "J-01M", "field": "material", "value": "unobtainium", "reason": "call"},
     "not a material"),
    ({"part": "J-01M", "field": "finish", "value": "sparkly", "reason": "call"}, "not a finish"),
    ({"part": "J-01M", "field": "size_mm", "value": {"to": 2000}, "reason": "call"},
     "replaces"),
    ({"part": "J-01M", "field": "operation_off", "value": "teleport", "reason": "call"},
     "not an operation"),
    ({"part": "J-01M", "field": "quantity", "value": 2.5, "reason": "call"}, "whole number"),
    ({"part": "", "field": "thickness_mm", "value": 2, "reason": "call"}, "name the part"),
])
def test_a_change_that_cannot_be_costed_is_refused_with_its_reason(raw, why):
    ch, err = cc.clean_change(raw)
    assert ch is None and why in err


def test_a_finish_keeps_its_colour_as_words_and_an_operation_is_a_route_word():
    ch, _ = cc.clean_change({"part": "J-01M", "field": "finish",
                             "value": "powder coat RAL 9005", "reason": "call"})
    assert ch["value"] == "POWDER COATED" and "RAL 9005" in ch["note"]
    for words in ("Powder coat", "powder coating", "POWDER_COATING"):
        ch, _ = cc.clean_change({"part": "J-01M", "field": "operation_off", "value": words,
                                 "reason": "call"})
        assert ch["value"] == "powder_coating", words
    ch, _ = cc.clean_change({"part": "J-01M", "field": "operation_off", "value": "weld",
                             "reason": "call"})
    assert ch["value"] == "welding"


# ── the estimator's ticks become the job's file ─────────────────────────────────────────

def _submitted(**over):
    base = {"accepted_by": "James Gray", "email": EMAIL, "changes": [
        {"part": "J-01M", "field": "thickness_mm", "value": 2, "origin": "email",
         "quote": "side panels in 2mm rather than 1.5mm", "accepted": True},
        {"part": "J-02M", "field": "material", "value": "STAINLESS_STEEL", "origin": "email",
         "quote": "we'd now like them in stainless", "accepted": False},
        {"part": "J-03M", "field": "thickness_mm", "value": 2.5, "origin": "manual",
         "reason": "phone call with Sam, 13 Oct", "accepted": True},
    ], "questions": [{"quote": "add a cable hole in the top", "ask": "price the hole",
                      "keep": True},
                     {"quote": "Kind regards", "ask": "not a request", "keep": False}]}
    base.update(over)
    return base


def test_ticked_changes_are_written_declined_ones_recorded_and_kept_questions_carried():
    data, errors = cc.build_changes_file(_submitted(), "J", today="2026-10-13")
    assert errors == []
    assert [c["part"] for c in data["changes"]] == ["J-01M", "J-03M"]
    assert [d["part"] for d in data["declined"]] == ["J-02M"]
    assert [q["quote"] for q in data["questions"]] == ["add a cable hole in the top"]
    assert data["accepted_by"] == "James Gray" and data["written_by"] == cc.WRITTEN_BY


def test_no_name_or_two_values_for_one_thing_or_a_price_is_refused():
    _, errors = cc.build_changes_file(_submitted(accepted_by=""), "J")
    assert any("accepted_by" in e for e in errors)
    two = _submitted()
    two["changes"].append({"part": "J-01M", "field": "thickness_mm", "value": 3,
                           "origin": "manual", "reason": "another call", "accepted": True})
    _, errors = cc.build_changes_file(two, "J")
    assert any("two different" in e for e in errors)
    priced = _submitted()
    priced["changes"][0]["price_gbp"] = 12.0
    data, errors = cc.build_changes_file(priced, "J")
    assert data == {} and any("REFUSED" in e for e in errors)
    bad = _submitted()
    bad["changes"][2]["reason"] = ""
    _, errors = cc.build_changes_file(bad, "J")
    assert any("reason" in e for e in errors)


def test_the_file_round_trips_and_a_run_without_changes_removes_only_the_portals_file(tmp_path):
    job = tmp_path / "J"
    job.mkdir()
    data, _ = cc.build_changes_file(_submitted(), "J")
    cc.write_changes(job, "J", data)
    path = cc.find_changes_file(job, None, "J-GA")
    assert path == job / "J_customer_changes.json"
    loaded, problems = cc.load_changes(path)
    assert problems == [] and len(loaded["changes"]) == 2
    cc.write_changes(job, "J", None)
    assert not path.exists()
    path.write_text(json.dumps({"accepted_by": "Tony", "changes": [
        {"part": "J-01M", "field": "thickness_mm", "value": 2, "reason": "spec rev C"}]}))
    cc.write_changes(job, "J", None)
    assert path.exists(), "a file a person wrote is never removed"


def test_a_line_the_engine_cannot_use_is_asked_on_the_book(tmp_path):
    path = tmp_path / "J_customer_changes.json"
    path.write_text(json.dumps({"accepted_by": "Tony", "changes": [
        {"part": "J-01M", "field": "operation_off", "value": "teleport", "reason": "call"},
        {"part": "J-01M", "field": "thickness_mm", "value": 2, "reason": "spec rev C"}]}))
    loaded, problems = cc.load_changes(path)
    assert len(loaded["changes"]) == 1 and problems
    parts = _parts()
    cc.apply_customer_changes(parts, loaded, {"drawing_number": "J-GA"})
    assert any("teleport" in q["issue"] for q in parts[0]["manufacturing_questions"])


def test_another_jobs_file_is_never_found(tmp_path):
    (tmp_path / "K_customer_changes.json").write_text("{}")
    assert cc.find_changes_file(tmp_path / "missing", tmp_path / "J.pdf", "J") is None


# ── the engine costs it, above the drawing, and shows both ──────────────────────────────

def _parts():
    p1 = {"part_number": "J-01M"}
    sp.apply_field(p1, "normalized_thickness_mm", 1.5, "dxf_filename")
    p1.setdefault("review_flags", []).append(
        "normalized_thickness_mm: two sources of equal standing disagree — confirm which")
    p2 = {"part_number": "J-02M", "normalized_material": "MILD_STEEL"}
    # A person confirmed the drawn gauge — the customer's change still wins over it.
    sp.apply_field(p2, "normalized_thickness_mm", 1.5, "estimator_confirmed")
    p3 = {"part_number": "J-03M", "blank_length_mm": 1850.0, "blank_width_mm": 610.0,
          "normalized_geometry": {"blank_length_mm": 1850.0, "blank_width_mm": 610.0}}
    root = {"part_number": "J-GA", "is_assembly_parent": True}
    return [root, p1, p2, p3]


def _data(*changes, questions=()):
    return {"accepted_by": "James Gray", "accepted_on": "2026-10-13",
            "changes": list(changes), "questions": list(questions), "path": "x"}


def test_the_change_outranks_the_cut_file_and_a_persons_confirmation_and_shows_both():
    parts = _parts()
    rep = cc.apply_customer_changes(parts, _data(
        {"part": "J-01M", "field": "thickness_mm", "value": 2.0, "origin": "email",
         "quote": "side panels in 2mm rather than 1.5mm"},
        {"part": "J-02M", "field": "thickness_mm", "value": 2.0, "origin": "email",
         "quote": "side panels in 2mm rather than 1.5mm"}), {"drawing_number": "J-GA"})
    assert [a["part"] for a in rep["applied"]] == ["J-01M", "J-02M"]
    for p in parts[1:3]:
        assert p["normalized_thickness_mm"] == 2.0
        assert sp.source_of(p, "normalized_thickness_mm") == cc.SOURCE
        flag = next(f for f in p["review_flags"] if "COSTED AT" in f)
        assert "the drawings: 1.5 mm" in flag and "customer e-mail: 2 mm" in flag
        assert "side panels in 2mm rather than 1.5mm" in flag and "James Gray" in flag
    assert not any("confirm which" in f for f in parts[1]["review_flags"]), \
        "a question the customer has settled is not asked again"


def test_the_ranking_puts_the_customer_above_every_reader_and_person():
    assert sp.rank("customer_change") > sp.rank("estimator_confirmed")
    assert sp.field_rank("customer_change", "normalized_thickness_mm") > \
        sp.field_rank("dxf_filename", "normalized_thickness_mm")
    assert "customer" in sp.display_name("customer_change")
    assert sp.evidence_family("customer_change") == "the customer"


def test_a_code_no_part_carries_is_asked_on_the_book_not_dropped():
    parts = _parts()
    rep = cc.apply_customer_changes(parts, _data(
        {"part": "J-99M", "field": "thickness_mm", "value": 2.0, "origin": "manual",
         "reason": "call with Sam"}), {"drawing_number": "J-GA"})
    assert rep["not_applied"] and rep["questions"] == 1
    q = parts[0]["manufacturing_questions"][0]
    assert "J-99M" in q["issue"] and "did nothing" in q["issue"]


def test_what_the_box_cannot_change_is_a_question_on_the_product():
    parts = _parts()
    cc.apply_customer_changes(parts, _data(questions=[
        {"quote": "add a cable hole in the top", "ask": "price the hole"}]),
        {"drawing_number": "J-GA"})
    assert "cable hole" in parts[0]["manufacturing_questions"][0]["issue"]


def test_a_size_changes_the_blank_side_it_names_or_is_asked():
    parts = _parts()
    rep = cc.apply_customer_changes(parts, _data(
        {"part": "J-03M", "field": "size_mm", "value": {"from": 1850, "to": 2000},
         "origin": "manual", "reason": "revised layout"}), {})
    assert parts[3]["blank_length_mm"] == 2000.0
    assert parts[3]["normalized_geometry"]["blank_length_mm"] == 2000.0
    assert rep["applied"][0]["field"] == "size_mm"
    # A folded part changed across a straight span: the developed side moves by the same mm.
    parts = _parts()
    cc.apply_customer_changes(parts, _data(
        {"part": "J-03M", "field": "size_mm", "value": {"from": 560, "to": 600},
         "origin": "manual", "reason": "deeper shelf"}), {})
    assert parts[3]["blank_width_mm"] == 650.0
    assert any("straight span" in f for f in parts[3]["review_flags"])
    # Nothing near either side: asked, not guessed.
    parts = _parts()
    rep = cc.apply_customer_changes(parts, _data(
        {"part": "J-03M", "field": "size_mm", "value": {"from": 300, "to": 400},
         "origin": "manual", "reason": "?"}), {})
    assert rep["not_applied"] and parts[3]["blank_length_mm"] == 1850.0
    assert parts[3]["manufacturing_questions"]


def test_half_a_blank_is_asked_and_an_operation_and_a_buy_are_stamped_as_the_customers():
    parts = _parts()
    rep = cc.apply_customer_changes(parts, _data(
        {"part": "J-01M", "field": "blank_length_mm", "value": 900.0, "origin": "manual",
         "reason": "call"},
        {"part": "J-01M", "field": "operation_off", "value": "powder_coating",
         "origin": "manual", "reason": "they will paint it"},
        {"part": "J-02M", "field": "make_or_buy", "value": "buy", "origin": "manual",
         "reason": "they supply it"}), {})
    assert any(n["field"] == "blank_length_mm" for n in rep["not_applied"])
    assert parts[1]["_estimator_operations_off"] == ["powder_coating"]
    assert parts[2]["_estimator_make_or_buy"] == "buy"


def test_a_change_the_drawings_already_state_changes_nothing_and_says_so():
    parts = _parts()
    rep = cc.apply_customer_changes(parts, _data(
        {"part": "J-01M", "field": "thickness_mm", "value": 1.5, "origin": "manual",
         "reason": "confirming"}), {})
    assert rep["agreed"] and not rep["applied"]
    assert any("nothing changed" in f for f in parts[1]["review_flags"])


def test_an_order_quantity_that_differs_from_the_run_is_asked():
    parts = _parts()
    rep = cc.apply_customer_changes(parts, _data(
        {"part": "", "field": "order_quantity", "value": 250, "origin": "email",
         "quote": "we need 250 off"}), {"requested_order_quantity": 100})
    assert rep["not_applied"] and "250" in parts[0]["manufacturing_questions"][0]["issue"]
    rep = cc.apply_customer_changes(_parts(), _data(
        {"part": "", "field": "order_quantity", "value": 250, "origin": "email",
         "quote": "we need 250 off"}), {"requested_order_quantity": 250})
    assert rep["applied"] and rep["order_quantity"] == 250


# ── where it is read ────────────────────────────────────────────────────────────────────

def test_the_report_shows_both_values_before_any_figure():
    from job_report_html import _render_customer_changes
    parts = _parts()
    rep = cc.apply_customer_changes(parts, _data(
        {"part": "J-01M", "field": "thickness_mm", "value": 2.0, "origin": "email",
         "quote": "side panels in 2mm rather than 1.5mm"}), {})
    html = _render_customer_changes({"customer_changes": dict(rep, accepted_by="James Gray")})
    assert "Changes the customer asked for since the drawings" in html
    assert "1.5 mm" in html and "2 mm" in html and "COSTED" in html
    assert _render_customer_changes({}) == ""


def test_the_engine_applies_the_file_after_the_answers_file():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    answers = src.index("_ec.apply_estimator_confirmed(")
    changes = src.index("_cc.apply_customer_changes(")
    canon = src.index("apply_canonical_evidence_to_parts(\n")
    assert answers < changes < canon


def test_the_run_checks_the_changes_before_staging_and_writes_them_after():
    src = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
    start = src[src.index("def start(req: EstimateRequest"):]
    check = start.index("build_changes_file(")
    stage = start.index("staging.stage(")
    write = start.index("write_changes(")
    assert check < stage < write
    assert "customer_changes: Optional[Dict[str, Any]] = None" in src
    assert '@router.post("/changes/read")' in src and '@router.post("/changes/check")' in src


def test_the_page_sends_changes_only_when_the_estimator_asks():
    page = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
        encoding="utf-8")
    assert 'id="chgPanel"' in page and 'id="chgUse"' in page and 'id="chgWho"' in page
    assert ("customer_changes: (document.getElementById(\"chgUse\") || {}).checked "
            "? changesSubmitted() : null") in page
