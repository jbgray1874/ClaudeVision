"""D-595: what the read and the brief state reaches the record, the price or the decisions list.

0320730's book priced a polished nickel-chrome hook bar with no finish and its quote said the
parts were "supplied as made"; the brief's TIG became CO2 without a sentence; a ticket holder
the bar only receives was bought as a set of six; four M6 screws were bought for a welded bar;
and the tube's drilled hole was charged nowhere. Every one of those was the engine, not the
model. The rule now: preserve what was stated, record every change, and put the material ones
on the decisions list — never a silent drop, never a purchase on no evidence.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402
import config  # noqa: E402
import estimator as e  # noqa: E402
import source_precedence as sp  # noqa: E402

BRIEF = ("1200mm Hook in Bar, 1000 off. One welded assembly per finished bar.\n"
         "Brackets: 2 per bar, 3mm sheet steel, TIG welded down both sides to the tube.\n"
         "Fit 2 chrome end caps per finished bar, drawing reference CA070092; verify the "
         "supplier match.\n"
         "Dress and polish with 160, 240, 320 and 400 grit, surface pitting minimal. Finish: "
         "polished chrome, nickel 15 to 20 micron, chrome 0.3 to 0.5 micron.")
PLATE = "Finish: polished chrome, nickel 15 to 20 micron, chrome 0.3 to 0.5 micron"
POLISH = "Dress and polish with 160, 240, 320 and 400 grit, surface pitting minimal"


def _bar(**over):
    parts = [
        {"name": "MAIN TUBE", "kind": "fabricated", "quantity": 1, "material_guess": "MILD STEEL",
         "assumed_blank_mm": {"length": 1192, "width": 30, "thickness": 1.5},
         "operations": ["saw", "hole_machining", "deburring", "handling"]},
        {"name": "HOOK BRACKET", "kind": "fabricated", "quantity": 2, "material_guess": "MILD STEEL",
         "assumed_blank_mm": {"length": 90, "width": 49, "thickness": 3},
         "operations": ["laser_cutting", "deburring", "plating", "electropolish"]},
        {"name": "CHROME END CAP", "kind": "bought_in", "quantity": 2,
         "material_guess": "CHROME PLATED METAL"},
    ]
    ans = {"product": {"name": "HOOK BAR"}, "parts": parts,
           "unit_operations": ["welding", "assembly", "handling", "xero_fit_check"]}
    ans.update(over)
    return ans


def _built(answer=None):
    answer = answer or _bar()
    parts = cs.parts_from_concept(answer, "B")
    unit = cs.unit_assembly_part(parts, answer, "B")
    return answer, parts, unit


def _questions(rec):
    return [str(q.get("issue")) for q in (rec.get("manufacturing_questions") or [])]


# ── the finish, as stated ──────────────────────────────────────────────────────────────────

def test_the_finish_line_is_told_from_a_bought_parts_chrome():
    st = cs.stated_finish({}, BRIEF)
    assert st["plate"] == PLATE and st["plate_source"] == "the enquiry brief"
    assert st["polish"] == POLISH
    assert not cs.stated_finish({}, "Fit 2 chrome end caps per finished bar").get("plate")


def test_the_stated_plate_reaches_the_welded_unit_and_its_polish_is_asked():
    answer, parts, unit = _built()
    changes = cs.carry_stated_finish(unit, parts, answer, BRIEF)
    assert unit["normalized_finish"] == PLATE
    assert sp.source_of(unit, "normalized_finish") == "enquiry_brief"
    assert unit["surface_preparation"] == POLISH
    assert any(q.startswith(f"Polishing of {unit['part_number']}") for q in _questions(unit))
    assert all("plating" not in cs._record_ops(p) for p in parts + [unit]), \
        "plating is the finish on the plating line, not a labour row"
    assert {c["kind"] for c in changes} >= {"carried", "converted", "asked"}


def test_bought_parts_are_not_members_of_the_plating():
    answer, parts, unit = _built()
    cs.carry_stated_finish(unit, parts, answer, BRIEF)
    members = e.plated_steel_member_pns(parts + [unit], {})
    made = {p["part_number"] for p in parts if p.get("concept_kind") == "fabricated"}
    caps = {p["part_number"] for p in parts if p.get("concept_kind") == "bought_in"}
    assert made <= members and not (caps & members)


def test_a_nickel_chrome_spec_is_stated_and_asked_not_priced_on_the_zinc_card():
    unit, note, method = e.plating_unit_price(2.0, 1000, config.PLATE_SUBCONTRACT_POLICY, PLATE)
    assert unit is None and method == "subcontract_plating_quote_needed"
    assert "STATED, NOT PRICED" in note and "nickel/chrome" in note
    zinc, _n, zm = e.plating_unit_price(2.0, 1000, config.PLATE_SUBCONTRACT_POLICY, "ZINC PLATED")
    assert zinc and zm == "subcontract_plating_indicative"


# ── the weld process ───────────────────────────────────────────────────────────────────────

def test_the_briefs_tig_reaches_the_weld_and_its_rate_gap_is_asked():
    answer, parts, unit = _built()
    changes = cs.carry_weld_process(unit, parts, answer, BRIEF)
    assert unit["weld_process_stated"]["process"] == "TIG"
    assert unit["weld_process_stated"]["source"] == "enquiry_brief"
    assert "Weld rate: TIG welding is stated, and the rate card has no TIG rate" in _questions(unit)
    assert changes and changes[0]["item"] == "weld process: TIG"


def test_a_process_the_arc_row_is_for_raises_no_rate_gap():
    answer, parts, unit = _built()
    cs.carry_weld_process(unit, parts, answer, "Brackets MIG welded to the tube")
    assert unit["weld_process_stated"]["process"] == "MIG"
    assert not any(q.startswith("Weld rate") for q in _questions(unit))


def test_the_tig_rate_gap_is_one_decision_however_many_parts_state_it():
    from weld_symbols import weld_rate_gap_question
    a = {"part_number": "A", "weld_process_stated": {"process": "TIG"}}
    b = {"part_number": "B", "weld_process_stated": {"process": "TIG"}}
    weld_rate_gap_question(a), weld_rate_gap_question(b)
    assert _questions(a) == _questions(b), "same words, so the decisions list merges them"


def test_the_weld_row_names_the_brief_as_the_source_of_the_process():
    from wb_populate import weld_process_note
    note = weld_process_note("Weld (CO2)", ["B-CPT00"], {"B-CPT00": {"weld_process_stated": {
        "process": "TIG", "source": "enquiry_brief"}}})
    assert "TIG per the enquiry brief" in note and "Weld (CO2)" in note


# ── nothing bought on no evidence ──────────────────────────────────────────────────────────

def test_a_thing_the_product_receives_is_not_a_consumable():
    cons, ship, unknown = cs.split_not_visible(
        ["ticket holder inserted in central hole", "fixings and fasteners", "M6 screws",
         "threaded inserts", "pallet"])
    assert cons == ["fixings and fasteners", "M6 screws", "threaded inserts"]
    assert unknown == ["ticket holder inserted in central hole"] and ship == ["pallet"]


def test_a_metal_piece_of_a_welded_unit_is_welded_not_screwed():
    _a, parts, _u = _built()
    tube = next(p for p in parts if p["description"] == "MAIN TUBE")
    assert tube["part_number"] in cs.mechanically_fitted(parts)["counted"]
    welded = cs.mechanically_fitted(parts, unit_welded=True)
    assert tube["part_number"] not in welded["counted"]
    assert "welded into it" in welded["excluded"][tube["part_number"]]


def test_the_scan_asks_for_unnamed_fixings_rather_than_buying_them():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    at = src[src.index("THE FIXINGS THE READ DID NOT NAME ARE ASKED"):][:2400]
    assert "fixings_allowance_line" not in at and "asked, not bought" in at


# ── work the engine cannot charge is asked; work charged elsewhere is not ──────────────────

def test_work_the_engine_cannot_charge_is_asked_and_work_charged_elsewhere_is_not():
    answer, parts, _u = _built()
    bracket = next(p for p in parts if p["description"] == "HOOK BRACKET")
    tube = next(p for p in parts if p["description"] == "MAIN TUBE")
    assert any("cannot charge: electropolish" in q for q in _questions(bracket))
    assert not any("cannot charge" in q for q in _questions(tube)), "handling is charged elsewhere"
    assert cs.dropped_unit_operations(answer) == ["xero_fit_check"]


# ── a hole only a named cut can cover ──────────────────────────────────────────────────────

def test_a_drilled_hole_on_a_sawn_section_keeps_its_operation():
    tube = {"part_number": "T-1", "description": "MAIN TUBE", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "quantity": 1,
            "section_stock": {"a": 30, "b": 15, "t": 1.5, "profile_form": "OVAL",
                              "length_mm": 1192},
            "textual_operations": ["saw", "hole_machining"],
            "geometry_rollup": {"estimated_hole_count": 1}}
    out = e.estimate_process_times(tube)
    assert "hole_machining" in out["setup_times_min"]
    assert any(f.startswith("DRILLED") for f in tube.get("review_flags") or [])


def test_a_sheet_parts_holes_stay_with_its_laser():
    plate = {"part_number": "P-1", "description": "BRACKET", "normalized_material": "MILD_STEEL",
             "normalized_thickness_mm": 3, "quantity": 1, "blank_length_mm": 90,
             "blank_width_mm": 49, "textual_operations": ["laser_cutting", "hole_machining"],
             "geometry_rollup": {"estimated_cut_length_mm": 300, "estimated_hole_count": 1}}
    out = e.estimate_process_times(plate)
    assert "hole_machining" not in out["setup_times_min"] and "laser_cutting" in out["setup_times_min"]


# ── the quote does not call a stated finish absent ─────────────────────────────────────────

def test_a_stated_finish_is_never_called_supplied_as_made(tmp_path):
    import quote_story
    sys.path.insert(0, str(ROOT / "tests"))
    import test_the_quote_shows_how_it_was_read_and_priced as tq
    s = tq._summary(tmp_path)
    parts = [dict(p) for p in tq._PARTS]
    facts = quote_story.job_facts(s, parts, 50)
    facts["parts_by_dept"] = {}

    def _finish_card():
        return next(i for i in quote_story.evidence_items(s, facts) if i["topic"] == "finish")
    assert "supplied as made" in _finish_card()["concluded"], "nothing stated: as made"
    s["manufacturing_writeup"] = {"parts": [{"part_number": "UNIT-00",
                                             "normalized_finish": PLATE}]}
    card = _finish_card()
    assert "supplied as made" not in card["concluded"]
    assert "not yet priced" in card["concluded"] and "nickel" in card["concluded"]
    s["manufacturing_writeup"] = {"parts": [{"part_number": "UNIT-00",
                                             "normalized_finish": "RAW"}]}
    assert "supplied as made" in _finish_card()["concluded"], "RAW is a stated bare finish"


# ── THE ACCEPTANCE CHAIN: the read to the workbook's line list ─────────────────────────────
#
# The reviewer's three conditions, held on the list the sheet is written from, through the
# run's own costing, graph and workbook gate: adding the plating keeps every member and its
# quantity; the drilled hole keeps its machining; nothing the product only receives is bought.
# A seven-digit job number, because the drawing-number grammar does not cover one — that is
# how the plating line read as two BOM rows zipped and took the bar's parts down with it.

STEM7 = "1234567"


def _read_as_returned():
    return {"product": {"name": "HOOK BAR"}, "unit_operations": ["assembly", "welding"],
            "parts": [
                {"name": "MAIN TUBE", "kind": "fabricated", "quantity": 1,
                 "material_guess": "MILD STEEL",
                 "assumed_blank_mm": {"length": 1192, "width": 30, "thickness": 1.5},
                 "operations": ["saw", "hole_machining", "deburring"]},
                {"name": "HOOK BRACKET", "kind": "fabricated", "quantity": 2,
                 "material_guess": "MILD STEEL",
                 "assumed_blank_mm": {"length": 90, "width": 49, "thickness": 3},
                 "operations": ["laser_cutting", "deburring"]},
                {"name": "CHROME END CAP", "kind": "bought_in", "quantity": 2,
                 "material_guess": "CHROME PLATED METAL"},
                {"name": "IDENTIFICATION LABEL", "kind": "bought_in", "quantity": 1,
                 "material_guess": "PLASTIC FILM"}],
            "not_visible": ["ticket holder inserted in central hole", "mounting strip"]}


def _to_the_workbook(brief):
    import file_scan
    import wb_populate as wb
    from route_compiler import refresh_canonical_route_after_reconciliation
    answer = _read_as_returned()
    parts = cs.parts_from_concept(answer, STEM7, brief=brief)
    unit = cs.unit_assembly_part(parts, answer, STEM7)
    cs.carry_stated_finish(unit, parts, answer, brief)
    cs.carry_weld_process(unit, parts, answer, brief)
    recs = [unit] + parts
    s = {"declared_product": STEM7, "manufacturing_writeup": {"parts": recs},
         "document_analysis": {"bom_rows": []}, "llm_full_extract": {}, "pages": [],
         "assumed_job_quantity": 1}
    file_scan.pre_costing_passes(s)
    s["estimate_summary"] = e.estimate_document(recs, summary=s)
    refresh_canonical_route_after_reconciliation(s)
    pes = list(s["estimate_summary"]["part_estimates"])
    assert wb.canonical_route_cutover_enabled(s)
    return answer, parts, pes, wb.canonicalise_part_estimates_for_workbook(s, pes)


def _lines_of_the_read(lines):
    return {(str(l.get("description")), float(l.get("quantity") or 0)) for l in lines
            if str(l.get("part_number") or "").startswith(STEM7 + "-CPT")
            and not str(l.get("part_number")).endswith("-PLATE")}


def test_adding_the_plating_keeps_every_member_and_its_quantity_on_the_workbook():
    _a, _p, _pes, bare = _to_the_workbook("")
    _a, _p, _pes, plated = _to_the_workbook(BRIEF)
    assert _lines_of_the_read(plated) == _lines_of_the_read(bare)
    assert {d for d, _q in _lines_of_the_read(plated)} >= {
        "MAIN TUBE", "HOOK BRACKET", "CHROME END CAP", "IDENTIFICATION LABEL"}
    assert ("HOOK BRACKET", 2.0) in _lines_of_the_read(plated)
    plate = [l for l in plated if str(l.get("part_number")).endswith("-PLATE")]
    assert len(plate) == 1 and "STATED, NOT PRICED" in plate[0]["description"]
    assert not any(str(l.get("part_number")).endswith("-PLATE") for l in bare)


def test_every_line_the_read_returned_reaches_the_workbook_at_its_quantity():
    answer, _p, _pes, lines = _to_the_workbook(BRIEF)
    got = _lines_of_the_read(lines)
    for p in answer["parts"]:
        assert (p["name"], float(p["quantity"])) in got, f"{p['name']} lost or changed"


def test_the_tubes_drilled_hole_keeps_its_machining_to_the_workbook():
    _a, _p, pes, lines = _to_the_workbook(BRIEF)
    tube = next(l for l in lines if l.get("description") == "MAIN TUBE")
    assert (tube["process_estimate"]["times_min"].get("hole_machining") or 0) > 0


def test_nothing_the_product_only_receives_becomes_a_purchase():
    answer, parts, _pes, lines = _to_the_workbook(BRIEF)
    words = " ".join(str(l.get("description") or "").lower() for l in lines)
    assert not any(w in words for w in ("ticket holder", "fixing", "screw", "mounting strip"))
    cons, _ship, unknown = cs.split_not_visible(answer["not_visible"])
    assert cons == [] and len(unknown) == 2, "both are asked, neither is a consumable"
    assert cs.mechanically_fitted(parts, unit_welded=True)["pieces"] == 0, \
        "a welded bar has no hand-fitted piece to buy fixings for"


# ── a saved read replays with no model call ────────────────────────────────────────────────

def test_a_saved_read_is_replayed_by_name_and_a_missing_one_is_refused(tmp_path, monkeypatch):
    import json
    saved = tmp_path / "read.json"
    saved.write_text(json.dumps({"raw_response": json.dumps(_read_as_returned())}),
                     encoding="utf-8")
    monkeypatch.setenv(cs.CONCEPT_REPLAY_ENV, str(saved))
    got = cs.replayed_read()
    assert got["parsed"]["parts"][0]["name"] == "MAIN TUBE" and got["read_key"] == "read"
    record = tmp_path / "job.json"
    record.write_text(json.dumps({"concept_read": {"raw_response": got["raw_response"],
                                                   "read_key": "abc"}}), encoding="utf-8")
    monkeypatch.setenv(cs.CONCEPT_REPLAY_ENV, str(record))
    assert cs.replayed_read()["read_key"] == "abc", "a run record that kept its read replays"
    monkeypatch.setenv(cs.CONCEPT_REPLAY_ENV, str(tmp_path / "missing.json"))
    with pytest.raises(cs.ConceptUnavailable):
        cs.replayed_read()
    monkeypatch.delenv(cs.CONCEPT_REPLAY_ENV)
    assert cs.replayed_read() is None


# ── the read kept, and the panel can say it ────────────────────────────────────────────────

def test_the_raw_answer_and_the_changes_are_kept_on_the_record():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "raw_response=str(_read.get(\"raw_response\")" in src
    assert "read_changes=list(_transfer)" in src


def test_the_member_schedule_panel_takes_plating_and_polishing():
    import accepted_construction as ac
    assert {"plating", "polishing"} <= set(ac.OPERATIONS)
    assert {"plating", "polishing"} <= set(cs.SIGHTABLE_OPERATIONS)
