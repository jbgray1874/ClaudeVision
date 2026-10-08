"""A drawing sheet is read as a drawing, and its bill is held against what the sheet states (D-415).

12675-01, 8 Oct 2026. The model under the V1 GA was one undetailed block, correctly refused
(D-414), and the vision read took the GA sheet alone — under a prompt written for a photograph:
"estimate in mm from visible human-scale cues". The sheet states 600 × 400 with R25 corners, a
1250 body on adjustable feet, 2mm STEEL CONSTRUCTION, POWDER COATED RAL 7021, a CENTRAL SOLID
DIVIDER, 20 x CUSTOMER BAGS at an estimated 1.5 kg, and 67.44 kg. The read returned four posts
1,580 long (the top of the bags), twenty bars (the bag count) 530 long (the bag's width), a
1,250 × 300 divider and two 600 × 40 base bars: about 15 kg of steel against 37 kg of stand.
Nothing after the answer checked it, and it was costed at £242.63 a unit.

Now: the sheet's own printed text goes in with the image under a preamble that makes the
dimensions and notes facts, the goods held not parts and a fitting a line only where it is
drawn; the bill is weighed and measured against the sheet's stated body and weight, put back
once with what broke, and what still disagrees is asked on the unit. A render is read exactly
as before — same prompt, same cache key.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402
import model_takeoff as mt  # noqa: E402

# The words the V1 GA's text layer carries, in the order pdfplumber gives them (abridged).
GA_WORDS = """100 PITCH FOR STACKED BAGS ESTIMATED - TO BE CONFIRMED
1250 16.5 1580 ADJUSTABLE FEET 2mm STEEL CONSTRUCTION WELDED AND FINISHED FLUSH
POWDER COATED - RAL 7021 BLACK GREY 17.82° 400 600 R25 SECTION A-A 2 x STACKS OF 10 BAGS
CENTRAL SOLID DIVIDER 380 556.5 530 662 186.5 ESTIMATED BAG WEIGHT - 1.5kg
20 x CUSTOMER BAGS 67.44kg WEIGHT: SEE PART DRAWINGS MATERIAL: SEE PART DRAWINGS"""

FACTS = {"body_mm": {"height": 1250, "width": 600, "depth": 400},
         "body_basis": "front view 1250 body; plan 600 x 400",
         "material": "MILD STEEL", "thickness_mm": 2, "finish": "POWDER COATED RAL 7021",
         "stated_weight_kg": 67.44, "weight_includes_goods": "yes",
         "goods": "20 customer bags at 1.5 kg", "goods_weight_kg": 30}


def _made(name, l, w, qty=1, ops=("laser_cutting",), t=2, drawn="front view"):
    return {"name": name, "kind": "fabricated", "material_guess": "MILD STEEL",
            "assumed_blank_mm": {"length": l, "width": w, "thickness": t},
            "quantity": qty, "operations": list(ops), "drawn": drawn,
            "why_size": "from the sheet"}


def _feet(drawn="front view, labelled ADJUSTABLE FEET"):
    return {"name": "ADJUSTABLE FOOT", "kind": "bought_in", "quantity": 4,
            "assumed_blank_mm": {"length": 0, "width": 0, "thickness": 0},
            "operations": [], "drawn": drawn}


def _the_1205_bill():
    """What the read returned at £242.63: posts, bars, a divider and base bars, ~15 kg."""
    return {"product": {"name": "BAG STAND"}, "sheet_facts": dict(FACTS),
            "parts": [_made("OUTER VERTICAL POST", 1580, 40, 4),
                      _made("HORIZONTAL BAG SUPPORT", 530, 25, 20),
                      _made("CENTRAL SOLID DIVIDER", 1250, 300),
                      _made("BASE FRAME MEMBER", 600, 40, 2),
                      _feet()]}


def _the_sheets_bill():
    """The stand the sheet draws: four 2 mm faces, a base and the divider, on four feet."""
    return {"product": {"name": "BAG STAND"}, "sheet_facts": dict(FACTS),
            "parts": [_made("FRONT / BACK PANEL", 1250, 600, 2),
                      _made("SIDE PANEL", 1250, 400, 2),
                      _made("BASE", 600, 400),
                      _made("CENTRAL SOLID DIVIDER", 1250, 600, drawn="section A-A"),
                      _feet()]}


# ── the prompt: a render is untouched, a sheet is read as a sheet ─────────────────────────

def test_a_render_keeps_its_prompt_and_its_cache_key():
    """No render pack re-asks the model because of this: the render prompt, its version and
    its cache key are exactly what they were."""
    assert cs.CONCEPT_PROMPT_VERSION == "c4"
    assert hashlib.sha256(cs._PROMPT.encode()).hexdigest()[:12] == cs._PROMPT_FINGERPRINT
    render = cs.concept_prompt_text([b"png"])
    assert "THESE ARE DRAWING SHEETS" not in render
    assert cs._cache_key([b"png"], "m") == cs._cache_key([b"png"], "m", "", sheet=False)
    assert cs._cache_key([b"png"], "m", sheet=True, sheet_words=GA_WORDS) != cs._cache_key([b"png"], "m")


def test_the_sheet_prompt_cannot_change_without_its_version():
    got = hashlib.sha256((cs._SHEET_PREAMBLE + cs._SHEET_TEXT_SECTION
                          + cs._RECHECK_SECTION).encode()).hexdigest()[:12]
    assert got == cs._SHEET_PROMPT_FINGERPRINT, (
        f"the sheet prompt changed. Bump SHEET_PROMPT_VERSION (now {cs.SHEET_PROMPT_VERSION!r}) "
        f"and set _SHEET_PROMPT_FINGERPRINT = {got!r}")


def test_a_sheet_read_is_told_the_sheet_is_the_facts_and_given_its_words():
    text = cs.concept_prompt_text([b"png"], sheet=True, sheet_words=GA_WORDS)
    assert text.startswith("THESE ARE DRAWING SHEETS, NOT PHOTOGRAPHS")
    for rule in ("A DIMENSION ON THE SHEET IS A FACT", "WHAT THE PRODUCT HOLDS IS NOT A PART",
                 "A dimension to the top of the goods\n   is not the height of the product",
                 "A FITTING IS A LINE ONLY WHERE THE SHEET DRAWS OR LABELS IT",
                 '"sheet_facts"', '"drawn"', '"weight_includes_goods"'):
        assert rule in text, rule
    assert "2mm STEEL CONSTRUCTION" in text and "20 x CUSTOMER BAGS" in text
    # The JSON in the preamble is literal braces once formatted, not a format error.
    assert '{"body_mm": {"height": 0' in text
    again = cs.concept_prompt_text([b"png"], sheet=True, sheet_words=GA_WORDS,
                                   recheck="- OUTER VERTICAL POST is sized 1580 × 40 mm")
    assert "DID NOT AGREE WITH WHAT THE SHEET STATES" in again and "1580 × 40" in again


def test_the_sheets_words_come_from_its_own_text_layer(tmp_path):
    import pymupdf

    pdf = tmp_path / "12675-01-GA.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=400)
        page.insert_text((40, 60), "2mm STEEL CONSTRUCTION")
        page.insert_text((40, 90), "WEIGHT: 67.44kg")
        doc.save(str(pdf))
    words = cs.sheet_text([str(pdf)])
    assert "2mm STEEL CONSTRUCTION" in words and "67.44kg" in words
    assert cs.sheet_text([str(tmp_path / "x-ENQUIRY_BRIEF.pdf")]) == ""
    assert len(cs.sheet_text([str(pdf)] * 2000)) <= cs.SHEET_TEXT_MAX_CHARS


# ── the check: the bill weighed and measured against the sheet ───────────────────────────

def test_the_1205_bill_does_not_agree_with_the_sheet():
    check = cs.sheet_check(_the_1205_bill(), GA_WORDS)
    assert check["checked"] and not check["agrees"]
    assert check["net_weight_kg"] == pytest.approx(37.44)
    assert 13 < check["sighted_weight_kg"] < 17
    words = " ".join(check["failures"])
    assert "OUTER VERTICAL POST is sized 1580 × 40 mm, larger than the product body" in words
    assert "parts are missing or undersized" in words and "less 30 kg of 20 customer bags" in words
    assert [b["part"] for b in check["breaches"]] == ["OUTER VERTICAL POST"]


def test_the_stand_the_sheet_draws_agrees_with_it():
    check = cs.sheet_check(_the_sheets_bill(), GA_WORDS)
    assert check["checked"] and check["agrees"], check["failures"]
    assert 1.2 < check["ratio"] < 1.7, "gross blanks weigh more than the finished stand"
    assert "agrees" not in cs.sheet_check_sentence(check)
    assert cs.sheet_check_sentence(check).startswith("CONCEPT BILL CHECKED AGAINST THE SHEET")


def test_a_figure_the_sheet_does_not_print_is_not_checked_against():
    """A depth of 490 the model says the sheet states, and the sheet does not print, is not a
    fact: it is named and left out of the envelope."""
    bill = _the_sheets_bill()
    bill["sheet_facts"] = dict(FACTS, body_mm={"height": 1580, "width": 600, "depth": 490})
    check = cs.sheet_check(bill, GA_WORDS)
    assert "body depth 490" in check["not_on_sheet"]
    assert check["body_mm"]["depth"] == 0.0 and check["body_mm"]["height"] == 1580


def test_a_folded_blank_is_its_unfolded_shape_and_may_exceed_the_body():
    bill = _the_sheets_bill()
    bill["parts"] = [_made("WRAPPED CARCASS", 2000, 1250, ops=("laser_cutting", "folding"))]
    assert not cs.sheet_check(bill, GA_WORDS)["breaches"]


def test_a_sheet_that_states_nothing_is_not_called_sound():
    bill = {"parts": [_made("PANEL", 500, 300)], "sheet_facts": {}}
    check = cs.sheet_check(bill, "")
    assert not check["checked"] and not check["agrees"] and not check["failures"]
    assert cs.sheet_check_sentence(check).startswith("CONCEPT BILL NOT CHECKED")


def test_weight_without_the_goods_split_checks_only_the_heavy_side():
    bill = _the_1205_bill()
    bill["sheet_facts"] = dict(FACTS, weight_includes_goods="not stated", goods_weight_kg=0)
    bill["parts"] = [p for p in bill["parts"] if p["name"] != "OUTER VERTICAL POST"]
    check = cs.sheet_check(bill, GA_WORDS)
    assert check["agrees"], "too light cannot be said when the goods' share is unknown"
    bill["parts"].append(_made("SLAB", 1250, 600, 20))
    assert "more than 2 × the 67.44 kg" in " ".join(cs.sheet_check(bill, GA_WORDS)["failures"])


# ── undrawn fittings are asked, not costed ───────────────────────────────────────────────

def test_a_fitting_the_sheet_does_not_draw_is_set_aside():
    bill = _the_sheets_bill()
    bill["parts"].append(dict(_feet(drawn=""), name="CASTOR"))
    kept, aside = cs.set_aside_undrawn(bill)
    assert [a["name"] for a in aside] == ["CASTOR"]
    assert "ADJUSTABLE FOOT" in [p["name"] for p in kept["parts"]], "a labelled fitting stays"
    # A read that did not answer the sheet's schema says nothing either way: nothing dropped.
    silent = {"parts": [{"name": "CASTOR", "kind": "bought_in", "quantity": 4}]}
    assert cs.set_aside_undrawn(silent) == (silent, [])


def test_a_sheet_that_draws_a_lid_and_no_hinge_asks_rather_than_mints_one():
    answer = {"parts": [_made("LID", 600, 400), _made("BODY PANEL", 600, 1000)]}
    render_parts = cs.parts_from_concept(answer, "JOB")
    assert any(p["description"] == "HINGE" for p in render_parts), "a render still nets the hinge"
    sheet_parts = cs.parts_from_concept(answer, "JOB", sheet=True)
    assert not any(p["description"] == "HINGE" for p in sheet_parts)
    lid = next(p for p in sheet_parts if p["description"] == "LID")
    assert any("draws LID and no hinge" in q["issue"] for q in lid["manufacturing_questions"])
    assert "read off the design-intent sheet" in " ".join(lid["review_flags"])


def test_what_the_check_could_not_settle_is_asked_on_the_unit():
    parts = cs.parts_from_concept(_the_1205_bill(), "JOB", sheet=True)
    unit = cs.unit_assembly_part(parts, _the_1205_bill(), "JOB")
    check = cs.sheet_check(_the_1205_bill(), GA_WORDS)
    n = cs.raise_sheet_questions([unit] + parts, check, [{"name": "CASTOR", "quantity": 4}])
    assert n == 2
    issues = [q["issue"] for q in unit["manufacturing_questions"]]
    assert issues[0].startswith("The sighted bill does not agree with the sheet")
    assert "CASTOR x4 was listed by the read but the sheet does not draw" in issues[1]
    assert cs.raise_sheet_questions([unit] + parts, check, []) == 0, "asked once"


# ── the re-ask: put back once with what broke, the better of two kept ───────────────────

def _sheet_pdf(tmp_path):
    import pymupdf

    pdf = tmp_path / "12675-01-GA.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=400)
        page.insert_text((20, 40), GA_WORDS.replace("\n", " ")[:180])
        page.insert_text((20, 70), "1250 600 400 2mm STEEL CONSTRUCTION 67.44kg 20 x CUSTOMER BAGS")
        doc.save(str(pdf))
    return pdf


def test_a_bill_that_breaks_the_sheet_is_put_back_once_and_the_better_kept(tmp_path, monkeypatch):
    pdf = _sheet_pdf(tmp_path)
    monkeypatch.setattr(cs, "_cache_dir", lambda: tmp_path / "cache")
    asked = []

    def fake(pngs, model, brief="", **kw):
        asked.append(kw)
        return json.dumps(_the_1205_bill() if not kw.get("recheck") else _the_sheets_bill())

    monkeypatch.setattr(cs, "_call_vision_llm", fake)
    out = cs.read_sheet_concept([str(pdf)])
    assert len(asked) == 2 and asked[0]["sheet"] and "1250" in asked[0]["sheet_words"]
    assert "OUTER VERTICAL POST is sized 1580" in asked[1]["recheck"]
    assert out["check"]["agrees"] and out["check"]["second_read_taken"]
    assert out["check"]["first_read_failures"]
    assert "after a second read" in cs.sheet_check_sentence(out["check"])
    # The same pack again replays both answers from the cache: the model is not asked a third time.
    out2 = cs.read_sheet_concept([str(pdf)])
    assert len(asked) == 2 and out2["check"]["agrees"]


def test_a_second_read_that_is_no_better_is_not_taken(tmp_path, monkeypatch):
    pdf = _sheet_pdf(tmp_path)
    monkeypatch.setattr(cs, "_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(cs, "_call_vision_llm",
                        lambda pngs, model, brief="", **kw: json.dumps(_the_1205_bill()))
    out = cs.read_sheet_concept([str(pdf)])
    assert not out["check"]["agrees"] and out["check"]["rechecked"]
    assert out["check"]["second_read_taken"] is False
    assert "did no better" in cs.sheet_check_sentence(out["check"])


# ── the book says what the check found ───────────────────────────────────────────────────

def test_the_take_off_sentence_says_what_the_check_found_and_names_a_brief_only_when_used():
    base = {"source": "vision_concept", "design": "12675-01-GA", "brief_used": False}
    bad = dict(base, sheet_check={"failures": ["the made parts weigh about 14.8 kg as sized"]})
    s = mt.sentence(bad)
    assert "with the enquiry brief" not in s
    assert "The bill does not agree with the sheet: the made parts weigh about 14.8 kg" in s
    assert mt.banner(bad).startswith("CONCEPT READ OF A DESIGN-INTENT SHEET — 12675-01-GA")
    good = dict(base, brief_used=True, sheet_check={"agrees": True, "failures": []})
    assert "with the enquiry brief" in mt.sentence(good) and "and agrees" in mt.sentence(good)


def test_the_report_callout_carries_the_check():
    import job_report_html as jrh

    t = {"source": "vision_concept", "design": "12675-01-GA", "design_title": "GA.PDF",
         "chosen_by": "the GA", "parts": 5, "brief_used": False,
         "sheet_check": {"checked": True, "agrees": False,
                         "failures": ["OUTER VERTICAL POST is sized 1580 × 40 mm"]}}
    html = jrh._render_concept_takeoff({"concept_takeoff": t})
    assert "The bill does not agree with the sheet:" in html and "1580 × 40" in html
    assert "with the enquiry brief" not in html and "off the sheet" in html


def test_the_report_concept_section_says_what_the_sheet_stated():
    import job_report_html as jrh

    concept = {"sheet_read": True, "sheet_facts": FACTS,
               "sheet_check": cs.sheet_check(_the_1205_bill(), GA_WORDS),
               "set_aside_undrawn": [{"name": "CASTOR", "quantity": 4}],
               "assumptions": [{"part_number": "JOB-CPT01", "description": "POST",
                                "field": "blank_length_mm", "value": 1580, "cue": "sheet"}]}
    html = jrh._concept_assumptions_section({"concept_read": concept})
    assert "read off the sheet by the vision model" in html
    assert "1250 × 600 × 400 mm" in html and "67.44 kg" in html
    assert "CONCEPT BILL DOES NOT AGREE WITH THE SHEET" in html
    assert "CASTOR x4" in html


def test_the_scan_reads_a_design_intent_sheet_as_a_sheet():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "_sheet_read = bool(_design_intent_pages)" in src
    assert "concept_scan.read_sheet_concept(_pack, refresh=_fresh, brief=_brief)" in src
    assert "concept_scan.parts_from_concept(_answer, _job_name, sheet=_sheet_read)" in src
    assert "concept_scan.raise_sheet_questions(" in src


# ── D-415c: a lasered or cut-to-length line is a part SDI cuts ───────────────────────────

def test_a_line_whose_route_cuts_it_is_a_part_sdi_cuts():
    import estimate_explained as ee

    assert ee._sdi_cuts("A", {}, {}, {"route_operations": ["laser_cutting", "powder_coating"]})
    assert ee._sdi_cuts("A", {}, {}, {"length": 1580})
    assert ee._sdi_cuts("A", {"A": {"x": 1}}, {}, None)
    assert not ee._sdi_cuts("FOOT", {}, {}, {"route_operations": ["assembly"]})
    rows = ee._missing_drawings(
        [{"code": "JOB-CPT01", "price": 2.0, "qty": 4}, {"code": "FOOT", "price": 11.0, "qty": 4}],
        {}, {}, {},
        record={"JOB-CPT01": {"route_operations": ["laser_cutting"]},
                "FOOT": {"route_operations": []}})
    assert [r["cut"] for r in rows] == [True, False]
