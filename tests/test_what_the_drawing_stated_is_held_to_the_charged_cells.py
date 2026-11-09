"""What the drawing's own text stated is held to the charged cells, as an LLM read is
(SCRUM-194, requirement 2).

0358141's 09:32 record: read_charge_result said "no LLM read was taken, so this contract checked
nothing"; the section contract had no requirement (the pack prints no cut-list table); the
material contract verified nothing. The facts the deterministic reader extracted and linked
were held to no row. Reviewer, 9 Nov 2026: every costing-relevant finding must end used, covered
elsewhere, superseded or excluded with a reason, or flagged unresolved, with the row identified.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "acceptance"))

import drawing_read_ledger as drl  # noqa: E402
import read_charge_contract as rcc  # noqa: E402


def _upright(**extra):
    p = {"part_number": "UPC0358141 M4", "description": "UPRIGHT", "quantity": 2, "pages": [7],
         "materials": ["MILD STEEL"], "page_roles": ["detail"],
         "section_stock": {"a": 30.0, "b": 30.0, "t": 2.0, "length_mm": 1383.0,
                           "length_source": "detail_sheet_overall", "length_printed": "1383 O/A"},
         "textual_operations": ["saw", "tapping", "handling"],
         "operation_sources": {"saw": "inference", "tapping": "drawing_notes"},
         "operation_evidence": {"tapping": "(9x) M3x0.5"},
         "title_block_material": {"printed": "30x30x2mmM S", "material": "MILD STEEL", "page": 7}}
    p.update(extra)
    return p


# ── the ledger ──────────────────────────────────────────────────────────────────────────

def test_the_ledger_holds_what_the_sheet_states_and_not_what_the_engine_inferred():
    led = drl.capture({}, parts=[_upright(), {"part_number": "HAFELE 651.09.302", "quantity": 4,
                                              "page_roles": ["bought_in"], "pages": [2]}])
    kinds = {(i["kind"], i.get("item")) for i in led["items"]}
    assert ("part", None) in kinds and ("quantity", None) in kinds and ("material", None) in kinds
    assert ("section", None) in kinds
    assert ("operation", "tapping") in kinds, "stated on the sheet, with its words"
    assert ("operation", "saw") not in kinds, "the engine's inference is its allowance, not a drawing fact"
    assert all(i.get("record") == "UPC0358141 M4" for i in led["items"])
    tap = next(i for i in led["items"] if i.get("item") == "tapping")
    assert tap["words"] == "(9x) M3x0.5" and tap["page"] == 7 and tap["said_by"] == "drawing_notes"
    mat = next(i for i in led["items"] if i["kind"] == "material")
    assert mat["words"] == "30x30x2mmM S" and mat["as_read"] == "MILD STEEL"
    assert led["parts_read"] == 1 and "drawing_deterministic" in led["read_sources"]


# ── the audit, over that ledger ─────────────────────────────────────────────────────────

def _costed(section_length=1383.0, with_rows=True):
    part = _upright()
    cost = {"part_number": "UPC0358141 M4", "quantity": 2, "normalized_material": "MILD_STEEL",
            "section_stock": {"a": 30.0, "b": 30.0, "t": 2.0, "length_mm": section_length}}
    rows = [_row(154, "Saw", "saw", 13.73, 0.42), _row(155, "Drill (Acrylic)", "tapping", 14.67, 0.5)] \
        if with_rows else []
    return {"manufacturing_writeup": {"parts": [part]},
            "estimate_summary": {"part_estimates": [cost]},
            "final_estimate": {"source": "excel_calculated", "labour_rows": rows,
                               "material_rows": [{"part_code": "UPC0358141 M4", "total_value_gbp": 31.0,
                                                  "qty_per_unit": 2, "charged_cell": "Estimate!M14"}]},
            "workbook_labour": {"rows": rows}}


def _row(n, title, op, value, hours, pn="UPC0358141 M4"):
    return {"workbook_row": n, "operation": title, "title": title, "ops": [op], "engine_operations": [op],
            "part_numbers": [pn], "total_value_gbp": value, "batch_hours": hours,
            "charged_cell": f"Estimate!M{n}"}


def test_a_stated_section_carried_to_the_costed_record_is_carried_and_a_lost_one_holds():
    s = _costed()
    led = drl.capture(s)
    res = rcc.audit(s, None, ledger=led)
    by = {i["id"].split(".", 1)[-1]: i for i in res["items"] if "." in i["id"]}
    assert by["section"]["state"] == rcc.CARRIED, by["section"]
    assert by["quantity"]["state"] == rcc.CARRIED
    lost = _costed(section_length=480.0)
    res2 = rcc.audit(lost, None, ledger=drl.capture(lost))
    sec = next(i for i in res2["items"] if i["id"].endswith(".section"))
    assert sec["state"] == rcc.UNRESOLVED and "no source names the change" in sec["how"]


def test_the_default_audit_still_reads_the_llm_ledger_and_the_record_helper_says_coverage():
    s = _costed()
    assert rcc.audit(s)["applicable"] is False, "no read_ledger: unchanged behaviour"
    r = rcc.record_drawing(s)
    assert r["applicable"] is False and "coverage, not acceptance" in r["scope"]
    s["drawing_ledger"] = drl.capture(s)
    r2 = rcc.record_drawing(s)
    assert r2["ledger"] == "drawing_ledger" and r2["applicable"] is True
    assert s["drawing_charge_result"] is r2


# ── the release invariant ───────────────────────────────────────────────────────────────

def test_an_unresolved_drawing_fact_holds_the_release_under_its_own_code():
    import invariants
    s = _costed(section_length=480.0)
    s["drawing_ledger"] = drl.capture(s)
    out = invariants.check_what_the_drawing_stated_is_accounted_for(s)
    assert out and all(v["code"].startswith("drawing_") for v in out), out
    assert any(v["severity"] == invariants.BLOCKING for v in out)
    assert invariants.check_what_the_drawing_stated_is_accounted_for({"manufacturing_writeup": {}}) == []
    assert "check_what_the_drawing_stated_is_accounted_for" in [
        f.__name__ for f in invariants.ALL_CHECKS] if hasattr(invariants, "ALL_CHECKS") else True


# ── the standalone trace ────────────────────────────────────────────────────────────────

def test_the_trace_tool_reports_a_record_without_a_calculated_workbook_as_not_tested(tmp_path):
    import retention_trace as rt
    rec = tmp_path / "x_record.json"
    rec.write_text(json.dumps({"manufacturing_writeup": {"parts": [_upright()]},
                               "final_estimate": {"source": "engine_estimate"}}), encoding="utf-8")
    t = rt.trace(rec, None)
    assert t["status"] == "NOT TESTED" and "calculated workbook" in t["why"]
    good = tmp_path / "y_record.json"
    good.write_text(json.dumps(_costed()), encoding="utf-8")
    t2 = rt.trace(good, None)
    assert t2["status"].startswith(("PASS", "FAIL")) and t2["ledger_captured_here"]
    assert any(i["state"] == "carried" for i in t2["items"])


# ── costed lines the drawing never stated ───────────────────────────────────────────────

def _lines_record():
    """A costed record with a purchase, a commercial line and a made part the read gave no
    fact of its own (0358141's 09:32 record: M2 priced with nothing of its own read)."""
    s = _costed()
    s["manufacturing_writeup"]["parts"] += [
        {"part_number": "HAFELE 651.09.302", "quantity": 4, "pages": [2], "page_roles": ["bought_in"]},
        {"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP", "quantity": 2,
         "pages": [2], "bound_to_parts_list_page": 2, "page_roles": ["detail"]}]
    s["estimate_summary"]["part_estimates"] += [
        {"part_number": "HAFELE 651.09.302", "quantity": 4, "page_roles": ["bought_in"]},
        {"part_number": "UPC0358141 M2", "quantity": 2, "page_roles": ["detail"]},
        {"part_number": "PACKAGING", "quantity": 1}]
    s["final_estimate"]["material_rows"] += [
        {"part_code": "HAFELE 651.09.302", "total_value_gbp": 12.0, "charged_cell": "Estimate!M11"},
        {"part_code": "UPC0358141 M2", "total_value_gbp": 9.5, "charged_cell": "Estimate!M12"},
        {"part_code": "PACKAGING", "total_value_gbp": 20.0, "charged_cell": "Estimate!M17"}]
    return s


def test_a_purchase_and_a_commercial_line_are_listed_and_an_unread_made_part_holds():
    import invariants
    s = _lines_record()
    led = drl.capture(s)
    assert not any(i["record"] == "UPC0358141 M2" for i in led["items"]), "nothing of its own was read"
    res = rcc.audit(s, None, ledger=led)
    noted = {l["record"]: l["class"] for l in res["lines_noted"]}
    assert noted["HAFELE 651.09.302"] == "listed_purchase" and noted["PACKAGING"] == "shop_standard"
    held = [l for l in res["engine_lines"] if l["holds"]]
    assert [l["record"] for l in held] == ["UPC0358141 M2"] and held[0]["class"] == "unread_made_part"
    codes = [i["code"] for i in res["issues"]]
    assert codes == ["engine_line_unconfirmed"], codes
    s["drawing_ledger"] = led
    out = invariants.check_what_the_drawing_stated_is_accounted_for(s)
    assert any(v["code"] == "drawing_engine_line_unconfirmed" for v in out), out


def test_an_engine_allowance_beside_the_drawings_facts_is_priced_and_named_not_a_hold():
    s = _costed()
    s["workbook_labour"]["rows"].append(_row(163, "Deburr", "deburring", 3.0, 0.1))
    s["final_estimate"]["labour_rows"] = s["workbook_labour"]["rows"]
    res = rcc.audit(s, None, ledger=drl.capture(s))
    assert not any(a.get("holds") for a in res["allowances"])
    assert not any(i["code"] == "engine_allowance_unconfirmed" for i in res["issues"])
    if res.get("allowances_noted"):
        assert all(a.get("basis") is not None for a in res["allowances_noted"])


# ── a finish the sheet states ───────────────────────────────────────────────────────────

def test_a_stated_finish_is_a_ledger_statement_held_to_the_rows_that_put_it_on():
    led = drl.capture({}, parts=[_upright(normalized_finish="BRUSHED 240 GRIT", finish_source="title_block"),
                                 _upright(part_number="UPC0358141 M5", normalized_finish="RAW"),
                                 _upright(part_number="UPC0358141 M6", normalized_finish="POWDER COAT",
                                          finish_source="llm_full_extract")])
    fin = [i for i in led["items"] if i["kind"] == "stated"]
    assert [(i["record"], i["item"]) for i in fin] == [("UPC0358141 M4", "brushed")], fin
    assert fin[0]["page"] == 7 and fin[0]["text"] == "BRUSHED 240 GRIT" and fin[0]["as_read"] == "BRUSHED"
    noisy = drl.capture({}, parts=[_upright(normalized_finish="ES EPCRAL7021DARKGREY30 ,TO RAIL KIDS 1400 X")])
    coat = next(i for i in noisy["items"] if i["kind"] == "stated")
    assert coat["item"] == "coat" and coat["as_read"] == "EPCRAL7021DARKGREY30", "the stated word, not the scrape"
    s = _costed()
    s["manufacturing_writeup"]["parts"][0].update(normalized_finish="BRUSHED 240 GRIT", finish_source="title_block")
    res = rcc.audit(s, None, ledger=drl.capture(s))
    st = next(i for i in res["items"] if i["id"].endswith(".finish"))
    assert st["state"] == rcc.UNRESOLVED and "BRUSHED 240 GRIT stated" in st["how"]
    s["workbook_labour"]["rows"].append(_row(170, "Linish", "linisher", 6.0, 0.2))
    s["final_estimate"]["labour_rows"] = s["workbook_labour"]["rows"]
    res2 = rcc.audit(s, None, ledger=drl.capture(s))
    st2 = next(i for i in res2["items"] if i["id"].endswith(".finish"))
    assert st2["state"] == rcc.CHARGED and st2["cells"] == ["Estimate!M170"], st2
