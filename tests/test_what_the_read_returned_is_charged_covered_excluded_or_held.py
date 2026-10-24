"""D-596: every item a read returned ends charged, covered by a named charge, excluded by a
person with a reason, or unresolved with the release held — on the calculated workbook, not an
intermediate list. Every charge no read item explains is an engine allowance, listed apart;
one calibrated on another product holds the release until confirmed for this job.

The calculated rows here are shaped on a real hook-bar book's: its material block carries the
part code, its sheet-steel block leads the description with it, its labour rows name the part
and the operation. A seven-digit job number, as that job had. Nothing here names a job.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402
import invariants  # noqa: E402
import read_charge_contract as rcc  # noqa: E402

STEM = "1234567"
U, T, B, C, L = (f"{STEM}-CPT0{n}" for n in range(5))
BRIEF = ("1200mm Hook in Bar, 1000 off. One welded assembly per finished bar.\n"
         "Brackets: 2 per bar, 3mm sheet steel, TIG welded down both sides to the tube.\n"
         "Dress and polish with 160, 240, 320 and 400 grit, surface pitting minimal. Finish: "
         "polished chrome, nickel 15 to 20 micron, chrome 0.3 to 0.5 micron.")


def _answer():
    return {"product": {"name": "HOOK BAR"}, "unit_operations": ["assembly", "welding"],
            "parts": [
                {"name": "MAIN TUBE", "kind": "fabricated", "quantity": 1,
                 "material_guess": "MILD STEEL",
                 "assumed_blank_mm": {"length": 1192, "width": 30, "thickness": 1.5},
                 "operations": ["saw", "hole_machining", "deburring"],
                 "cutouts": [{"what": "hole", "count": 1, "length_mm": 5, "width_mm": 5}]},
                {"name": "HOOK BRACKET", "kind": "fabricated", "quantity": 2,
                 "material_guess": "MILD STEEL",
                 "assumed_blank_mm": {"length": 90, "width": 49, "thickness": 3},
                 "operations": ["laser_cutting", "deburring"]},
                {"name": "CHROME END CAP", "kind": "bought_in", "quantity": 2,
                 "material_guess": "CHROME PLATED METAL"},
                {"name": "IDENTIFICATION LABEL", "kind": "bought_in", "quantity": 1,
                 "material_guess": "PLASTIC FILM"}],
            "not_visible": ["ticket holder inserted in central hole"]}


def _records(answer=None, brief=BRIEF):
    answer = answer or _answer()
    parts = cs.parts_from_concept(answer, STEM, brief=brief)
    unit = cs.unit_assembly_part(parts, answer, STEM)
    cs.carry_stated_finish(unit, parts, answer, brief)
    cs.carry_weld_process(unit, parts, answer, brief)
    return answer, unit, parts


def _lab(row, ops, pn, hours, value, title, qty=1, rate=None):
    return ({"workbook_row": row, "engine_operations": ops, "part_numbers": [pn]},
            dict({"workbook_row": row, "part_numbers": pn, "batch_hours": hours,
                  "total_value_gbp": value, "charged_cell": f"Estimate!M{row}",
                  "operation": title, "qty_per_unit": qty},
                 **({"dept_rate_gbp_per_hour": rate} if rate else {})))


def _book(*, hole_row=True, plate_gbp=0.0, plating=True, allowances=True, bought_extras=False,
          answer=None, brief=BRIEF):
    """The hook bar costed and calculated. `bought_extras`: the 17:15 shape, a ticket holder
    and screws bought on their own lines."""
    answer, unit, parts = _records(answer, brief)
    recs = [unit] + parts
    if bought_extras:
        recs += [{"part_number": f"{STEM}-NV01", "description": "ticket holder inserted in central hole",
                  "concept": True, "concept_kind": "bought_in", "concept_not_visible": True},
                 {"part_number": f"{STEM}-NV02", "description": "Fixings allowance — M6 screw",
                  "concept": True, "concept_kind": "bought_in", "concept_not_visible": True,
                  "fixings_allowance": True}]
    labs = [_lab(151, ["laser_cutting"], B, .1693, 11.54, "Laser (Metal)", 2),
            _lab(152, ["saw"], T, .1917, 6.11, "Saw"),
            _lab(153, ["deburring"], T, .2583, 8.05, "Manual labour (Metal)"),
            _lab(154, ["deburring"], B, .2667, 8.31, "Manual labour (Metal)", 2),
            _lab(155, ["welding"], U, .6, 25.06, "Weld (CO2)"),
            _lab(156, ["dress_welds"], U, .5667, 16.25, "Dress Welds"),
            _lab(157, ["assembly", "handling"], U, .33, 9.42, "Assemble/pack (Metal)")]
    if hole_row:
        labs.append(_lab(158, ["hole_machining"], T, .1, 3.2, "Drill"))
    if allowances:
        labs += [_lab(159, ["brush_before_plate"], U, .6667, 80.0, "Brush before plate",
                      rate=31.18),
                 _lab(160, ["plater_pack", "plater_final_pack"], U, .2, 5.7, "Plater pack",
                      rate=28.56)]
    mats = [{"part_code": T, "qty_per_unit": 1, "total_value_gbp": 7.02, "charged_cell": "Estimate!M11"},
            {"part_code": C, "qty_per_unit": 2, "total_value_gbp": 1.976, "charged_cell": "Estimate!M12"},
            {"part_code": L, "qty_per_unit": 1, "total_value_gbp": 0.1248, "charged_cell": "Estimate!M13"},
            {"part_code": "PACKAGING", "qty_per_unit": 1, "total_value_gbp": 56.19,
             "charged_cell": "Estimate!M16"},
            {"description": f"{B}  HOOK BRACKET", "qty_per_unit": 2, "total_value_gbp": 0.2704,
             "charged_cell": "Estimate!M93"}]
    costs = [{"part_number": T, "quantity": 1, "normalized_material": "MILD STEEL"},
             {"part_number": B, "quantity": 2},
             {"part_number": C, "quantity": 2}, {"part_number": L, "quantity": 1},
             {"part_number": U, "quantity": 1, "process_estimate": {"run_times_min_per_unit": {
                 "brush_before_plate": 40.0, "plater_pack": 4.0, "plater_final_pack": 8.0,
                 "handling": 0.8, "dress_welds": 8.0, "welding": 12.0}}},
             {"part_number": "PACKAGING", "quantity": 1}]
    if plating:
        mats.append({"part_code": f"{U}-PLATE", "qty_per_unit": 1, "total_value_gbp": plate_gbp,
                     "charged_cell": "Estimate!M18"})
        costs.append({"part_number": f"{U}-PLATE", "quantity": 1, "_plating_placeholder": True,
                      "_plating_members": [T, B], "_plating_weldment": U})
    if bought_extras:
        mats += [{"part_code": f"{STEM}-NV01", "qty_per_unit": 1, "total_value_gbp": 9.88,
                  "charged_cell": "Estimate!M14"},
                 {"part_code": f"{STEM}-NV02", "qty_per_unit": 4, "total_value_gbp": 0.3328,
                  "charged_cell": "Estimate!M15"}]
        costs += [{"part_number": f"{STEM}-NV01", "quantity": 1},
                  {"part_number": f"{STEM}-NV02", "quantity": 4}]
    ledger = rcc.capture(answer, records=recs, raw_response=json.dumps(answer), read_key="k",
                         brief=brief)
    return {"read_ledger": ledger, "manufacturing_writeup": {"parts": recs},
            "estimate_summary": {"canonical_part_estimates": costs},
            "workbook_labour": {"rows": [a for a, _b in labs]},
            "final_estimate": {"source": "excel_calculated", "material_rows": mats,
                               "labour_rows": [b for _a, b in labs]},
            "requested_order_quantity": 1}


@pytest.fixture(autouse=True)
def _breaks(monkeypatch):
    monkeypatch.setenv("SDI_QUANTITY_BREAKS", "1000")


def _state(result, item_id):
    return next(e for e in result["items"] if e["id"] == item_id)["state"]


def _codes(summary):
    return {v["code"] for v in invariants.check_what_the_read_returned_is_accounted_for(summary)}


# ── the ledger: every item of the read has an identity ─────────────────────────────────────

def test_every_part_quantity_material_size_feature_and_operation_has_an_identity():
    led = _book()["read_ledger"]
    ids = {i["id"] for i in led["items"]}
    assert {"R1", "R1.quantity", "R1.material", "R1.size", "R1.op.saw", "R1.op.hole_machining",
            "R1.op.deburring", "R1.cutout1", "R2", "R2.op.laser_cutting", "R3", "R4",
            "U.op.assembly", "U.op.welding", "NV1", "S.finish", "S.polish",
            "S.weld_process"} <= ids
    tube = next(i for i in led["items"] if i["id"] == "R1")
    assert tube["record"] == T and tube["as_read"]["name"] == "MAIN TUBE"
    assert next(i for i in led["items"] if i["id"] == "S.finish")["said_by"] == "the enquiry brief"


def test_the_raw_answer_is_kept_whole_and_its_hash_is_on_the_ledger():
    s = _book()
    raw = json.dumps(_answer())
    import hashlib
    assert s["read_ledger"]["raw_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert 'raw_response=str(_read.get("raw_response") or ""),' in src, "not cut to a length"
    assert "[:60000]" not in src[src.index("WHOLE, NOT CUT (D-596)"):][:400]


def test_a_line_set_aside_or_appended_before_numbering_still_links_to_its_record():
    answer = _answer()
    answer["parts"].insert(0, {"name": "UNDRAWN HINGE", "kind": "bought_in", "quantity": 2,
                               "drawn": ""})
    kept, aside = cs.set_aside_undrawn(answer)
    _a, unit, parts = _records(kept)
    led = rcc.capture(answer, records=[unit] + parts, brief=BRIEF, set_aside=aside)
    by = {i["id"]: i for i in led["items"]}
    assert by["R1"]["record"] == "" and "set aside at the read" in by["R1"]["set_aside"]
    assert by["R2"]["record"] == T, "the tube is the read's second line and the first record"


# ── the final states, on the calculated rows ───────────────────────────────────────────────

def test_on_this_build_the_tube_hole_is_charged_and_the_parts_at_their_quantities():
    r = rcc.audit(_book())
    for item in ("R1", "R2", "R3", "R4", "R1.op.saw", "R1.op.hole_machining", "R2.op.laser_cutting",
                 "U.op.welding", "U.op.assembly"):
        assert _state(r, item) == rcc.CHARGED, item
    assert _state(r, "R2.quantity") == rcc.CARRIED and _state(r, "R1.cutout1") == rcc.COVERED


def test_the_1715_shape_is_held_for_the_lost_hole_the_finish_and_the_purchases():
    r = rcc.audit(_book(hole_row=False, plating=False, allowances=False, bought_extras=True))
    assert _state(r, "R1.op.hole_machining") == rcc.UNRESOLVED, "a sawn tube's hole charged nowhere"
    assert _state(r, "S.finish") == rcc.UNRESOLVED and _state(r, "S.polish") == rcc.UNRESOLVED
    nv1 = next(e for e in r["items"] if e["id"] == "NV1")
    assert nv1["state"] == rcc.UNRESOLVED and "no supply-scope evidence" in nv1["how"]
    fixings = next(l for l in r["engine_lines"] if l["record"] == f"{STEM}-NV02")
    assert fixings["class"] == "inferred_purchase" and fixings["holds"]
    assert {"read_item_unresolved", "engine_line_unconfirmed"} <= _codes(dict(_book(
        hole_row=False, plating=False, allowances=False, bought_extras=True),
        read_charge_result=r))


def test_unpriced_plating_holds_the_release():
    s = _book(plate_gbp=0.0)
    r = rcc.audit(s)
    assert _state(r, "S.finish") == rcc.UNRESOLVED
    assert "plater's price is awaited" in next(e for e in r["items"] if e["id"] == "S.finish")["how"]
    s["read_charge_result"] = r
    viol = invariants.check_what_the_read_returned_is_accounted_for(s)
    assert any(v["code"] == "read_item_unresolved" and v["severity"] == invariants.BLOCKING
               and "S.finish" in v["message"] for v in viol)


def test_priced_plating_covers_the_stated_finish():
    r = rcc.audit(_book(plate_gbp=120.0))
    assert _state(r, "S.finish") == rcc.COVERED


def test_brushing_does_not_satisfy_a_stated_polishing_sequence():
    r = rcc.audit(_book(plate_gbp=120.0))
    polish = next(e for e in r["items"] if e["id"] == "S.polish")
    assert polish["state"] == rcc.UNRESOLVED and "brushing" in polish["how"]


def test_the_tig_the_brief_states_is_held_while_it_rides_the_co2_rate():
    r = rcc.audit(_book())
    assert _state(r, "S.weld_process") == rcc.UNRESOLVED
    s = _book(brief=BRIEF.replace("TIG", "MIG"))
    assert _state(rcc.audit(s), "S.weld_process") == rcc.COVERED


# ── engine allowances, apart ───────────────────────────────────────────────────────────────

def test_allowances_calibrated_on_another_product_hold_with_their_hours():
    r = rcc.audit(_book())
    held = {a["operation"]: a for a in r["allowances"] if a["holds"]}
    assert set(held) == {"brush_before_plate", "plater_pack", "plater_final_pack"}
    assert held["brush_before_plate"]["minutes_per_product"] == 40.0
    total = sum(a["hours_at"]["1000"] for a in held.values())
    assert round(total, 1) == 866.7, "40 + 4 + 8 minutes a unit at 1,000 off"
    disclosed = {a["operation"]: a["class"] for a in r["allowances"] if not a["holds"]}
    assert disclosed == {"dress_welds": "derived", "handling": "shop_standard"}


def test_a_held_allowance_says_its_minutes_and_hours_on_the_decisions_list():
    s = _book()
    s["read_charge_result"] = rcc.audit(s)
    viol = [v for v in invariants.check_what_the_read_returned_is_accounted_for(s)
            if v["code"] == "engine_allowance_unconfirmed"]
    brush = next(v for v in viol if v["detail"]["operation"] == "brush_before_plate")
    assert "40 min a unit" in brush["message"] and "666.7 h at 1,000 off" in brush["message"]
    assert brush["detail"]["target_id"] == U


def test_dressing_with_no_charged_weld_is_unclassified_and_holds():
    s = _book()
    rows = s["final_estimate"]["labour_rows"]
    s["final_estimate"]["labour_rows"] = [r for r in rows if r["workbook_row"] != 155]
    r = rcc.audit(s)
    dress = next(a for a in r["allowances"] if a["operation"] == "dress_welds")
    assert dress["class"] == "unclassified" and dress["holds"]


# ── a person's ruling, with its reason ─────────────────────────────────────────────────────

def _ruled(s, rulings):
    s["estimator_decisions"] = {"read_rulings": rulings, "decided_by": "the estimator"}
    return s


def test_rulings_with_reasons_resolve_items_and_confirm_allowances():
    s = _ruled(_book(plate_gbp=120.0), {
        "NV1": {"ruling": "excluded", "reason": "the customer fits the ticket holder"},
        "S.polish": {"ruling": "covered", "reason": "the dress row includes the grits",
                     "covered_by": "dress_welds"},
        "S.weld_process": {"ruling": "covered", "reason": "TIG at the arc row, agreed",
                           "covered_by": "welding"},
        "allowance:brush_before_plate": {"ruling": "confirmed", "reason": "production: 15 min"},
        "allowance:plater_pack": {"ruling": "confirmed", "reason": "same packer"},
        "allowance:plater_final_pack": {"ruling": "confirmed", "reason": "same packer"}})
    r = rcc.audit(s)
    assert _state(r, "NV1") == rcc.EXCLUDED and _state(r, "S.polish") == rcc.COVERED
    assert not any(a["holds"] for a in r["allowances"])
    assert r["passed"], r["issues"]
    s["read_charge_result"] = r
    assert invariants.check_what_the_read_returned_is_accounted_for(s) == []


def test_a_covered_ruling_must_name_a_charge_the_sheet_carries():
    s = _ruled(_book(), {"S.polish": {"ruling": "covered", "reason": "linished",
                                      "covered_by": "linisher"}})
    assert _state(rcc.audit(s), "S.polish") == rcc.UNRESOLVED


def test_a_covered_ruling_on_another_parts_charge_does_not_cover():
    """Review of D-596: a reason does not make a cover. The tube's hole ruled covered by the
    laser, which cuts only the brackets, explains a missing charge away — it stays held."""
    s = _ruled(_book(hole_row=False), {"R1.op.hole_machining": {
        "ruling": "covered", "reason": "lasered", "covered_by": "laser_cutting"}})
    e = next(e for e in rcc.audit(s)["items"] if e["id"] == "R1.op.hole_machining")
    assert e["state"] == rcc.UNRESOLVED and "charged only on" in e["how"] and B in e["how"]


def test_a_covered_ruling_at_the_wrong_quantity_does_not_cover():
    s = _ruled(_book(), {"R2.op.deburring": {"ruling": "covered", "reason": "lasered clean",
                                             "covered_by": "laser_cutting"}})
    next(r for r in s["final_estimate"]["labour_rows"] if r["workbook_row"] == 151)["qty_per_unit"] = 1
    e = next(e for e in rcc.audit(s)["items"] if e["id"] == "R2.op.deburring")
    assert e["state"] == rcc.UNRESOLVED and "1 against 2" in e["how"]


def test_a_cover_named_by_a_held_allowance_does_not_release_the_allowance():
    s = _ruled(_book(plate_gbp=120.0), {"S.polish": {
        "ruling": "covered", "reason": "brushing includes the grits",
        "covered_by": "brush_before_plate"}})
    r = rcc.audit(s)
    assert _state(r, "S.polish") == rcc.COVERED
    brush = next(a for a in r["allowances"] if a["operation"] == "brush_before_plate")
    assert brush["holds"], "the covering charge still needs its own confirmation"


def test_the_held_allowances_are_costed_apart_from_the_supported_unit_cost():
    s = _book()
    s["final_estimate"]["totals"] = {"unit_gbp": 177.72}
    s["quantity_sweep"] = {"rows": [{"quantity": 1, "unit": 177.72},
                                    {"quantity": 1000, "unit": 61.0}]}
    held = rcc.audit(s)["held_allowances"]
    assert held["operations"] == ["brush_before_plate", "plater_final_pack", "plater_pack"]
    assert held["gbp_per_unit"] == round(40 / 60 * 31.18 + 4 / 60 * 28.56 + 8 / 60 * 28.56, 2)
    assert held["unit_excluding_held_gbp"] == round(177.72 - held["gbp_per_unit"], 2)
    at_1000 = next(b for b in held["at_breaks"] if b["quantity"] == 1000)
    assert at_1000["unit_excluding_held_gbp"] == round(61.0 - held["gbp_per_unit"], 2)
    assert held["hours_at"]["1000"] == 866.7


def test_the_release_says_what_rests_on_held_allowances_and_the_supported_cost():
    import costed_facts
    s = _book()
    s["final_estimate"]["totals"] = {"unit_gbp": 177.72}
    s["read_charge_result"] = rcc.audit(s)
    rel = costed_facts.costed_job(s)["release"]
    said = " ".join(rel["reasons"])
    assert "rests on engine allowances not confirmed" in said and "Not a budget" in said
    assert "866.7 h at 1,000 off" in said
    assert rel["held_allowances_gbp_per_unit"] == s["read_charge_result"]["held_allowances"]["gbp_per_unit"]
    assert rel["unit_excluding_held_gbp"] == s["read_charge_result"]["held_allowances"]["unit_excluding_held_gbp"]


def test_a_held_allowance_row_carries_its_cost():
    s = _book()
    s["read_charge_result"] = rcc.audit(s)
    brush = next(v for v in invariants.check_what_the_read_returned_is_accounted_for(s)
                 if v["code"] == "engine_allowance_unconfirmed"
                 and v["detail"]["operation"] == "brush_before_plate")
    assert "£20.79 a unit" in brush["message"]


def test_the_digest_keeps_the_raw_words_whole_and_where_they_live(tmp_path):
    """Review of D-596b: a key and a hash cannot prove a faithful extraction — the original
    response travels with the digest, unchanged, with the place its immutable copy lives."""
    sys.path.insert(0, str(ROOT / "tools"))
    import evidence_digest
    import hashlib
    s = _book()
    raw = json.dumps(_answer())
    s["concept_read"] = {"raw_response": raw, "read_key": "k"}
    s["read_charge_result"] = rcc.audit(s)
    s["filler"] = ["page text"] * 20000
    record = tmp_path / "job.json"
    record.write_text(json.dumps(s), encoding="utf-8")
    assert evidence_digest.main(["--record", str(record), "--out", str(tmp_path)]) == 0
    d = json.loads((tmp_path / "job_digest.json").read_text(encoding="utf-8"))
    cr = d["concept_read"]
    assert cr["raw_response"] == raw and cr["raw_chars"] == len(raw)
    assert cr["raw_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert cr["raw_evidence"]["cache_entry"] == "cache/vision_concept/k.json"
    assert cr["raw_evidence"]["ledger_raw_sha256"] == cr["raw_sha256"]
    assert d["read_charge_result"]["counts"] and d["final_estimate"]["labour_rows"]
    assert "filler" not in d
    assert (tmp_path / "job_digest.json").stat().st_size < record.stat().st_size / 3


def test_the_subtotal_is_not_called_supported_and_the_unresolved_work_is_said():
    import costed_facts
    s = _book()
    s["final_estimate"]["totals"] = {"unit_gbp": 177.72}
    s["read_charge_result"] = rcc.audit(s)
    said = " ".join(costed_facts.costed_job(s)["release"]["reasons"])
    assert "priced subtotal excluding them" in said and "supports" not in said
    n = len(s["read_charge_result"]["held_allowances"]["unresolved_work"])
    assert n and f"{n} item(s) of required work are unresolved and priced in neither" in said


def test_the_audit_tool_says_a_missing_file_instead_of_failing(tmp_path, capsys):
    sys.path.insert(0, str(ROOT / "tools"))
    import read_ledger_audit as tool
    record = tmp_path / "job.json"
    record.write_text("{}", encoding="utf-8")
    assert tool.main(["--record", str(record), "--xlsx", str(tmp_path / "missing.xlsx")]) == 2
    assert "The workbook is not there" in capsys.readouterr().out


# ── found on the real 17:15 record (D-596d) ────────────────────────────────────────────────

def test_a_size_is_taken_from_the_sentence_that_names_the_item_not_the_whole_line():
    """The brief was one line: the label's words and the tube's '30 x 15 x 1.5mm' sat on it
    together, and the label was described and researched at the tube's size."""
    one_line = ("Hook bar, 1000 off. Tube: 30 x 15 x 1.5mm flat-sided oval tube, cut 1192mm. "
                "Fit one transparent identification label to the front face.")
    assert cs.stated_item_size("TRANSPARENT IDENTIFICATION LABEL", one_line) is None
    assert cs.stated_item_size("UPC ID PLATE", "7. one UPC ID plate (20 x 10 mm), bought in") \
        == [20.0, 10.0]
    assert cs.stated_item_size("ID LABEL", "Fit an ID label 30 x 15mm to the face.") == [30.0, 15.0]


def test_the_weld_process_is_captured_from_the_words_not_from_the_records():
    """A ledger that took TIG from the records the transfer wrote could not list a TIG the
    transfer lost — the 17:15 audit showed no S.weld_process at all."""
    answer = _answer()
    parts = cs.parts_from_concept(answer, STEM, brief=BRIEF)
    unit = cs.unit_assembly_part(parts, answer, STEM)
    led = rcc.capture(answer, records=[unit] + parts, brief=BRIEF)
    weld = next(i for i in led["items"] if i["id"] == "S.weld_process")
    assert weld["process"] == "TIG" and weld["said_by"] == "the enquiry brief"
    assert not any(isinstance(r.get("weld_process_stated"), dict) for r in [unit] + parts), \
        "no record carries it, and the ledger still lists it"


def test_a_record_the_engine_renamed_still_links_and_the_change_is_shown():
    s = _book()
    for p in s["manufacturing_writeup"]["parts"]:
        p.pop("read_fingerprint", None), p.pop("read_origin", None)
        if p["part_number"] == L:
            p["description"] = "IDENTIFICATION LABEL 30 x 15 x 1.5 MM"
    s["read_ledger"] = rcc.capture(_answer(), records=s["manufacturing_writeup"]["parts"],
                                   brief=BRIEF)
    r = rcc.audit(s)
    label = next(e for e in r["items"] if e["id"] == "R4")
    assert label["state"] == rcc.CHARGED and label["record"] == L
    assert label["renamed_to"] == "IDENTIFICATION LABEL 30 x 15 x 1.5 MM"
    assert "not the read's name" in label["how"]
    assert not any(l["record"] == L for l in r["engine_lines"])


def test_the_answers_file_refuses_a_ruling_without_a_reason():
    import estimator_confirmed as ec
    out, problems = ec._read_decisions({"estimator_decisions": {"read_rulings": {
        "NV1": {"ruling": "excluded"},
        "S.polish": {"ruling": "covered", "reason": "x"},
        "allowance:brush_before_plate": {"ruling": "excluded", "reason": "x"},
        "R1.op.saw": {"ruling": "confirmed", "reason": "x"},
        "NV2": {"ruling": "excluded", "reason": "customer supplies it"}}}}, "f.json")
    assert set(out["read_rulings"]) == {"NV2"}
    assert len(problems) == 4


# ── corrections stay visible; a change nobody names holds ──────────────────────────────────

def test_a_quantity_corrected_by_a_named_source_keeps_both_values():
    s = _book()
    rec = next(p for p in s["manufacturing_writeup"]["parts"] if p["part_number"] == B)
    from source_precedence import apply_field
    apply_field(rec, "quantity", 3, "enquiry_brief")
    next(c for c in s["estimate_summary"]["canonical_part_estimates"]
         if c["part_number"] == B)["quantity"] = 3
    next(m for m in s["final_estimate"]["material_rows"]
         if "HOOK BRACKET" in str(m.get("description")))["qty_per_unit"] = 3
    e = next(e for e in rcc.audit(s)["items"] if e["id"] == "R2.quantity")
    assert e["state"] == rcc.CORRECTED and e["corrected"] == {"from": 2, "to": 3,
                                                              "by": "enquiry_brief"}


def test_a_quantity_the_sheet_charges_differently_holds():
    s = _book()
    next(m for m in s["final_estimate"]["material_rows"] if m.get("part_code") == C)["qty_per_unit"] = 1
    assert _state(rcc.audit(s), "R3.quantity") == rcc.UNRESOLVED


# ── the saved file, and checks that did not run ────────────────────────────────────────────

def test_a_saved_cell_that_disagrees_with_the_readback_holds():
    s = _book()
    snap = {"sha256": "x", "cells": {"Estimate!M11": 7.02, "Estimate!H11": T,
                                     "Estimate!M152": 6.11, "Estimate!F152": T}}
    r = rcc.audit(s, snap)
    assert _state(r, "R1") == rcc.CHARGED and _state(r, "R1.op.saw") == rcc.CHARGED
    snap["cells"]["Estimate!M11"] = 0.0
    assert _state(rcc.audit(s, snap), "R1") == rcc.UNRESOLVED


def test_no_calculated_workbook_leaves_every_item_of_work_unresolved():
    s = _book()
    s.pop("final_estimate")
    r = rcc.audit(s)
    work = [e for e in r["items"] if e["kind"] in ("part", "operation", "unit_operation")]
    assert work and all(e["state"] == rcc.UNRESOLVED for e in work)
    assert "read_charge_unverified" in _codes(s)


def test_a_ledger_that_was_not_captured_holds_and_no_read_is_not_a_finding():
    s = _book()
    s["read_ledger"] = {"schema": rcc.LEDGER_SCHEMA, "items": [], "error": "boom"}
    assert "read_charge_unverified" in _codes(s)
    s.pop("read_ledger")
    assert _codes(s) == set()
    assert rcc.audit(s)["applicable"] is False and rcc.audit(s)["passed"] is None


def test_the_audit_mutates_nothing_and_record_fails_closed_without_a_workbook():
    s = _book()
    before = copy.deepcopy(s)
    rcc.audit(s)
    assert s == before
    res = rcc.record(s)
    assert res["passed"] is False
    assert any(i["code"] == "final_workbook_not_verified" for i in res["issues"])


def test_the_contract_runs_after_excel_beside_the_other_charge_contracts():
    main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    at = main.index("_record_material_charges(_target, xlsx_path)")
    assert main.index("_record_read_charges(_target, xlsx_path)") > at
    assert main.index("_record_read_charges(_target, xlsx_path)") < main.index("_inv = _check_job(_target)")
    assert invariants.check_what_the_read_returned_is_accounted_for in invariants.CHECKS


def test_the_polish_question_no_longer_says_brushing_charges_it():
    answer, unit, parts = _records()
    q = next(q for q in unit["manufacturing_questions"] if str(q.get("issue")).startswith("Polishing"))
    assert "NOT in the price" in q["assumption"] and "does not satisfy" in q["assumption"]


def test_the_saved_run_tool_audits_a_record_from_before_the_ledger(tmp_path):
    s = _book(hole_row=False, plating=False, allowances=False, bought_extras=True)
    for p in s["manufacturing_writeup"]["parts"]:
        p.pop("read_fingerprint", None), p.pop("read_origin", None)
    raw = json.dumps(_answer())
    s.pop("read_ledger")
    s["concept_read"] = {"raw_response": raw, "read_key": "abc"}
    record = tmp_path / "job.json"
    record.write_text(json.dumps(s), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "tools"))
    import read_ledger_audit as tool
    assert tool.main(["--record", str(record), "--breaks", "1000",
                      "--out", str(tmp_path)]) == 1, "held, not passed"
    out = json.loads((tmp_path / "job_read_ledger.json").read_text(encoding="utf-8"))
    states = {e["id"]: e["state"] for e in out["result"]["items"]}
    assert states["R1"] == rcc.CHARGED, "linked by name with no fingerprint"
    assert states["R1.op.hole_machining"] == rcc.UNRESOLVED


# ── D-596e: a source ID, a size its component's, TIG held to its rate, a print set opened ──

def _old(s):
    """The records as a run from before the read ID and the fingerprint saved them."""
    for p in s["manufacturing_writeup"]["parts"]:
        for k in ("read_id", "read_fingerprint", "read_origin"):
            p.pop(k, None)
    return s


def test_a_record_carries_its_read_lines_source_id_and_links_by_it():
    answer = _answer()
    answer["parts"].insert(0, {"name": "UNDRAWN HINGE", "kind": "bought_in", "quantity": 2,
                               "drawn": ""})
    kept, aside = cs.set_aside_undrawn(answer)
    parts = cs.parts_from_concept(kept, STEM, brief=BRIEF, source_answer=answer)
    tube = next(p for p in parts if p["part_number"] == T)
    assert tube["read_id"] == f"R2:{rcc.fingerprint(answer['parts'][1])}", \
        "its place in the read as returned, not in the copy with the hinge set aside"
    led = rcc.capture(answer, records=parts, brief=BRIEF, set_aside=aside)
    r2 = next(i for i in led["items"] if i["id"] == "R2")
    assert r2["record"] == T and r2["link"] == "read_id"


def test_a_changed_description_does_not_break_a_read_id_link():
    s = _book()
    label = next(p for p in s["manufacturing_writeup"]["parts"] if p["part_number"] == L)
    label["description"] = "CLEAR TAG, RESEARCHED"
    s["read_ledger"] = rcc.capture(_answer(), records=s["manufacturing_writeup"]["parts"],
                                   brief=BRIEF)
    e = next(e for e in rcc.audit(s)["items"] if e["id"] == "R4")
    assert e["state"] == rcc.CHARGED and e["record"] == L and e["link"] == "read_id"
    assert e["renamed_to"] == "CLEAR TAG, RESEARCHED", "the change stays visible"


def test_two_lines_that_read_alike_each_link_to_their_own_record_by_id():
    answer = _answer()
    answer["parts"].append(dict(answer["parts"][2]))          # a second, identical end-cap line
    parts = cs.parts_from_concept(answer, STEM, brief=BRIEF)
    led = rcc.capture(answer, records=parts, brief=BRIEF)
    by = {i["id"]: i for i in led["items"] if i["kind"] == "part"}
    assert by["R3"]["record"] != by["R5"]["record"] and by["R3"]["record"] and by["R5"]["record"]
    assert by["R3"]["link"] == by["R5"]["link"] == "read_id"


def test_old_records_that_read_alike_stay_unlinked_and_are_named():
    """Two read lines and two records answer to one name, and nothing on a record from before
    the read ID says which line it was: neither line is linked by guess."""
    answer = _answer()
    answer["parts"].append(dict(answer["parts"][2], quantity=4))   # END CAP again, another count
    s = _old(_book(answer=answer))
    s["read_ledger"] = rcc.capture(answer, records=s["manufacturing_writeup"]["parts"], brief=BRIEF)
    r = rcc.audit(s)
    for rid in ("R3", "R5"):
        e = next(e for e in r["items"] if e["id"] == rid)
        assert e["state"] == rcc.UNRESOLVED and e["record"] == "" and e["link"] == "ambiguous"
        assert "not linked" in e["how"] and "answer to this name" in e["how"]
    caps = [l for l in r["engine_lines"] if l["record"] in (C, f"{STEM}-CPT05")]
    assert caps and all(l["class"] == "unclassified" and l["holds"] for l in caps)
    assert all("linked to none" in l["basis"] for l in caps)


def test_old_records_with_similar_names_link_only_where_the_match_is_unique():
    lines = [("R1", {"name": "LABEL"}), ("R2", {"name": "LABEL HOLDER"})]
    old = [{"part_number": "X-CPT01", "description": "LABEL HOLDER", "concept_kind": "bought_in"},
           {"part_number": "X-CPT02", "description": "LABEL 30 x 15 MM", "concept_kind": "bought_in"}]
    links = rcc._link_records(lines, old)
    assert links["R1"]["record"]["part_number"] == "X-CPT02" and links["R1"]["link"] == "name"
    assert links["R2"]["record"]["part_number"] == "X-CPT01"
    # A name the record only starts with, followed by words that are not a size, is no link.
    links = rcc._link_records([("R1", {"name": "LABEL"})], old[:1])
    assert "R1" not in links


def test_a_size_belongs_to_the_component_it_stands_beside():
    assert cs.stated_item_size("ID LABEL", "30 × 15 tube with an ID label fitted") is None
    assert cs.stated_item_size(
        "TRANSPARENT IDENTIFICATION LABEL",
        "30 x 15 x 1.5mm flat-sided oval tube with a transparent identification label fitted") is None
    assert cs.stated_item_size("ID LABEL", "ID label, 30 x 15 tube") is None, "the tube's section"
    assert cs.stated_item_size("UPC ID PLATE", "one UPC ID plate (20 x 10 mm), bought in") == [20, 10]
    assert cs.stated_item_size("UPC ID PLATE", "a 20 x 10 mm UPC ID plate") == [20, 10]


def test_a_label_in_the_tubes_sentence_is_not_named_or_researched_at_the_tubes_size():
    brief = ("Hook bar, 1000 off. 30 x 15 x 1.5mm flat-sided oval tube with a transparent "
             "identification label fitted. Brackets TIG welded to the tube.")
    answer = _answer()
    answer["parts"][3]["name"] = "TRANSPARENT IDENTIFICATION LABEL"
    label = next(p for p in cs.parts_from_concept(answer, STEM, brief=brief)
                 if p["part_number"] == L)
    assert label["description"] == "TRANSPARENT IDENTIFICATION LABEL"
    assert not label.get("concept_stated_size_mm")
    plate = dict(answer["parts"][3], name="UPC ID PLATE")
    answer["parts"][3] = plate
    rec = next(p for p in cs.parts_from_concept(answer, STEM, brief=brief + " One UPC ID plate "
                                                "(20 x 10 mm), bought in.") if p["part_number"] == L)
    assert rec["description"] == "UPC ID PLATE 20 x 10 MM" and rec["concept_stated_size_mm"] == [20, 10]


def _weld_row(s):
    return next(r for r in s["final_estimate"]["labour_rows"] if r["workbook_row"] == 155)


def test_a_generic_co2_charge_leaves_a_stated_tig_unresolved():
    s = _book()
    row = _weld_row(s)
    row["dept_rate_gbp_per_hour"] = 41.77
    # The row's DESCRIPTION names the stated TIG beside the rate it rides on (D-393); that is
    # not a TIG rate, and it must not read as one.
    row["description"] = ("Weld (CO2) [TIG per the enquiry brief; charged at the Weld (CO2) "
                          "rate, the card's one arc-weld row — confirm]")
    e = next(e for e in rcc.audit(s)["items"] if e["id"] == "S.weld_process")
    assert e["state"] == rcc.UNRESOLVED
    assert "'Weld (CO2)' (£41.77/h)" in e["how"] and "a CO2/MIG rate, not a TIG rate" in e["how"]


def test_an_evidenced_tig_charge_satisfies_a_stated_tig():
    s = _book()
    s["final_estimate"]["labour_rows"] = [dict(r, operation="Weld (TIG)", dept_rate_gbp_per_hour=48.0)
                                          if r["workbook_row"] == 155 else r
                                          for r in s["final_estimate"]["labour_rows"]]
    e = next(e for e in rcc.audit(s)["items"] if e["id"] == "S.weld_process")
    assert e["state"] == rcc.COVERED and "'Weld (TIG)' (£48.00/h) is a TIG rate" in e["how"]


def test_a_shared_mig_tig_row_is_evidence_for_neither():
    s = _book()
    _weld_row(s)["operation"] = "Welding (MIG/TIG)"
    assert _state(rcc.audit(s), "S.weld_process") == rcc.UNRESOLVED
    assert rcc._rate_processes({"title": "Welding (MIG/TIG)", "ops": {"welding"}}) == set()
    assert rcc._rate_processes({"title": "Weld (CO2)", "ops": {"welding"}}) == {"CO2", "MIG"}


def _with_print_set(text, answer=None):
    answer = answer or _answer()
    answer["print_sets"] = [text]
    return answer


def test_a_print_set_that_describes_the_label_stays_open_and_names_it():
    answer = _with_print_set("identification label printed with the part number")
    s = _book(answer=answer)
    e = next(e for e in rcc.audit(s)["items"] if e["id"] == "PS1")
    assert e["state"] == rcc.UNRESOLVED and e["relates_to"] == ["R4"]
    assert "R4 'IDENTIFICATION LABEL'" in e["how"] and "separate printing or application" in e["how"]
    # A priced graphic line elsewhere does not settle what this print set is.
    s["manufacturing_writeup"]["parts"].append({"part_number": f"{STEM}-CPT09",
                                                "concept_kind": "graphic", "concept": True})
    s["final_estimate"]["material_rows"].append({"part_code": f"{STEM}-CPT09", "qty_per_unit": 1,
                                                 "total_value_gbp": 4.0, "charged_cell": "Estimate!M19"})
    assert _state(rcc.audit(s), "PS1") == rcc.UNRESOLVED


def test_shared_coverage_of_a_print_set_is_a_ruling_on_a_priced_line():
    s = _ruled(_book(answer=_with_print_set("identification label printed with the part number")),
               {"PS1": {"ruling": "covered", "covered_by": L,
                        "reason": "the label is bought printed; one line carries both"}})
    e = next(e for e in rcc.audit(s)["items"] if e["id"] == "PS1")
    assert e["state"] == rcc.COVERED and "one line carries both" in e["how"]
    next(m for m in s["final_estimate"]["material_rows"] if m.get("part_code") == L)[
        "total_value_gbp"] = 0.0
    assert _state(rcc.audit(s), "PS1") == rcc.UNRESOLVED, "an unpriced line covers nothing"


def test_the_1715_book_after_d596e_clears_the_false_finding_and_keeps_the_real_ones():
    """The old book's shape: records from before the read ID, the label renamed with the tube's
    size, TIG named only in the CO2 row's description, no hole row, no plating line, a ticket
    holder and four screws bought, and a print set that describes the label.

    Before: R4 'no record' (a false missing label) and no weld-process item at all.
    After: the label links by name with the rename shown; TIG fails against the CO2 rate; the
    hole, the finish, the purchases and the print set stay held."""
    answer = _with_print_set("identification label printed with the part number")
    s = _old(_book(answer=answer, hole_row=False, plating=False, allowances=False,
                   bought_extras=True))
    next(p for p in s["manufacturing_writeup"]["parts"] if p["part_number"] == L)[
        "description"] = "IDENTIFICATION LABEL 30 x 15 x 1.5 MM"
    _weld_row(s)["description"] = "Weld (CO2) [TIG per the enquiry brief; charged at the Weld (CO2) rate]"
    s["read_ledger"] = rcc.capture(answer, records=s["manufacturing_writeup"]["parts"], brief=BRIEF)
    r = rcc.audit(s)
    by = {e["id"]: e for e in r["items"]}
    assert by["R4"]["state"] == rcc.CHARGED and by["R4"]["link"] == "name"
    assert by["R4"]["renamed_to"] == "IDENTIFICATION LABEL 30 x 15 x 1.5 MM"
    assert by["S.weld_process"]["state"] == rcc.UNRESOLVED and "not a TIG rate" in by["S.weld_process"]["how"]
    assert by["R1.op.hole_machining"]["state"] == rcc.UNRESOLVED
    assert by["S.finish"]["state"] == rcc.UNRESOLVED and by["S.polish"]["state"] == rcc.UNRESOLVED
    assert by["NV1"]["state"] == rcc.UNRESOLVED and "no supply-scope evidence" in by["NV1"]["how"]
    assert next(l for l in r["engine_lines"] if l["record"] == f"{STEM}-NV02")["holds"]
    assert by["PS1"]["state"] == rcc.UNRESOLVED and by["PS1"]["relates_to"] == ["R4"]
    assert not r["passed"]
