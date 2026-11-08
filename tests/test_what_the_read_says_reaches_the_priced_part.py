"""What the read says reaches the part that is priced, or the loss is said (D-749).

0358141, 7 Nov 2026 22:17. The whole-pack read had the upright as 30 x 30 x 2 at 1,383 mm, the
end caps as 3 mm plate and the rub strips as 3 mm brushed stainless, each under the spelling its
own sheet prints ("UPC0358141M4"). The priced parts came from the parts list ("UPC0358141 M4").
The join compared text, so not one fact reached a priced part, and nothing said so: the sheet
priced 1,400 mm of 30 x 15 tube for the upright and three caps, and a plastic strip.

The cap M7 is a second case: the parts list prints its drawing number one digit wrong
("UPC0358131 M7"). Joined only when the digit is in the drawing number its siblings share and
the descriptions agree, and always written on the part for a person to confirm.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import invariants as iv  # noqa: E402
import part_identity as pid  # noqa: E402
from llm_full_extract import merge_inference  # noqa: E402
from source_connectors.llm_full_job import apply_full_job_to_pre_estimate  # noqa: E402


def _priced(pn, desc):
    return {"part_number": pn, "description": desc, "quantity": 2}


def _job(parts, routes=()):
    return {"found": True, "parts": list(parts), "routes": list(routes), "assemblies": [],
            "bom": [], "drawing_info": {}}


# ── the read's facts reach the priced part, whatever the spelling ───────────────────────

def test_the_reads_section_and_length_reach_the_part_the_parts_list_spells_with_a_space():
    m4 = _priced("UPC0358141 M4", "UPRIGHT")
    out = apply_full_job_to_pre_estimate([m4], _job([{
        "part_number": "UPC0358141M4", "description": "UPRIGHT", "material": "MILD STEEL",
        "material_family": "tube", "tube_section": "30x30x2", "cut_length_mm": 1383}]))
    ss = m4.get("section_stock") or {}
    assert (ss.get("a"), ss.get("b"), ss.get("t"), ss.get("length_mm")) == (30.0, 30.0, 2.0, 1383.0)
    assert out["unmatched"] == []


def test_two_spellings_of_one_part_in_the_read_are_combined_not_one_lost():
    m2 = _priced("UPC0358141 M2", "LONG RUB STRIP")
    apply_full_job_to_pre_estimate([m2], _job([
        {"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP"},           # parts list
        {"part_number": "UPC0358141M2", "description": "LONG RUB STRIP",             # own sheet
         "material": "STAINLESS STEEL", "thickness_mm": 3, "material_family": "sheet"}]))
    assert "STAINLESS" in str(m2.get("normalized_material")).upper()
    assert m2.get("normalized_thickness_mm") == 3


def test_a_route_named_as_the_sheet_spells_the_part_reaches_it():
    m4 = _priced("UPC0358141 M4", "UPRIGHT")
    out = apply_full_job_to_pre_estimate([m4], _job(
        [{"part_number": "UPC0358141M4", "description": "UPRIGHT"}],
        routes=[{"operation": "drilling", "part_numbers": ["UPC0358141M4"],
                 "evidence": "4 x 8.5 THRU"}]))
    assert out["operations"] >= 1


# ── one digit apart: joined only when corroborated, and always said ─────────────────────

def test_a_cap_whose_listed_number_is_one_digit_wrong_takes_its_own_sheets_facts_and_says_so():
    m7 = _priced("UPC0358131 M7", "BASE END CAP")
    m6 = _priced("UPC0358141 M6", "O A RAIL END")
    m4 = _priced("UPC0358141 M4", "UPRIGHT")
    out = apply_full_job_to_pre_estimate([m7, m6, m4], _job([
        {"part_number": "UPC0358141M7", "description": "BASE END CAP", "material": "MILD STEEL",
         "thickness_mm": 3, "material_family": "sheet"}]))
    assert m7.get("normalized_thickness_mm") == 3
    assert any("one digit apart" in str(f) for f in m7.get("review_flags") or [])
    assert not m6.get("normalized_thickness_mm")             # the item number is never bridged
    assert out["unmatched"] == []


def test_one_digit_apart_never_crosses_the_item_number_or_goes_uncorroborated():
    assert pid.one_digit_apart("UPC0358131 M7", "UPC0358141M7") == 8
    assert pid.one_digit_apart("UPC0358141 M6", "UPC0358141M7") is None
    assert pid.one_digit_apart("12002-02-GA", "12002-03-GA") is None
    cands = {"UPC0358131 M7": "BASE END CAP"}
    assert pid.corroborated_near_code("UPC0358141M7", "BASE END CAP", cands,
                                      ["UPC0358141 M4", "UPC0358131 M7"]) == "UPC0358131 M7"
    assert pid.corroborated_near_code("UPC0358141M7", "UPRIGHT", cands,
                                      ["UPC0358141 M4"]) is None           # descriptions differ
    assert pid.corroborated_near_code("UPC0358141M7", "BASE END CAP", cands,
                                      ["UPC0358131 M7"]) is None           # no sibling agrees


def test_a_sheet_one_digit_from_its_listed_part_binds_to_it_in_the_part_index():
    from document_builder import build_part_index
    rows = [{"part_number": "UPC0358141 M4", "description": "UPRIGHT", "quantity": 2,
             "source": "BOTH"},
            {"part_number": "UPC0358131 M7", "description": "BASE END CAP", "quantity": 4,
             "source": "BOTH"}]
    sheet = {"page_number": 9, "page_role": {"primary_role": "detail"},
             "pattern_summary": {"part_numbers": []}, "geometry_summary": {},
             "normalized_text": "UPC0358141M7BASEENDCAP3MM",
             "page_analysis": {"title_block": {"drawing_numbers": ["UPC0358141M7"],
                                               "descriptions": ["BASE END CAP"],
                                               "thicknesses_mm": ["3"]}}}
    parts = build_part_index({"pages": [sheet], "document_analysis": {"bom_rows": rows}})
    named = {p["part_number"]: p for p in parts}
    assert "UPC0358141M7" not in named
    m7 = named["UPC0358131 M7"]
    assert 9 in m7["pages"] and m7.get("quantity") == 4
    assert any("one digit apart" in str(f) for f in m7.get("review_flags") or [])


# ── what reaches nothing is said, and holds the release ─────────────────────────────────

def test_a_part_the_read_described_that_reaches_nothing_is_named_and_holds_the_release():
    out = apply_full_job_to_pre_estimate([_priced("A-01", "PANEL")], _job([
        {"part_number": "ZZ-99", "description": "UPRIGHT", "tube_section": "30x30x2",
         "cut_length_mm": 1383}]))
    assert [u["part_number"] for u in out["unmatched"]] == ["ZZ-99"]
    v = iv.check_what_the_read_said_reaches_a_priced_part({"llm_full_extract": {"counts": out}})
    assert v and v[0]["code"] == "read_facts_reached_no_priced_part"
    assert v[0]["severity"] == iv.BLOCKING and "ZZ-99" in v[0]["message"]
    assert iv.check_what_the_read_said_reaches_a_priced_part({"llm_full_extract": {"counts": {}}}) == []


def test_the_inference_fills_the_part_the_transcription_spelt_differently():
    job = {"parts": [{"part_number": "UPC0358141 M4", "description": "UPRIGHT"}], "routes": []}
    counts = merge_inference(job, {"parts": [{"part_number": "UPC0358141M4",
                                              "material": "MILD STEEL"}], "routes": []})
    assert counts["parts_added"] == 0 and job["parts"][0]["material"] == "MILD STEEL"


def test_the_run_log_and_the_release_check_are_wired():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "part(s) the read described reached " in src and '_c.get("unmatched")' in src
    assert iv.check_what_the_read_said_reaches_a_priced_part in iv.CHECKS
