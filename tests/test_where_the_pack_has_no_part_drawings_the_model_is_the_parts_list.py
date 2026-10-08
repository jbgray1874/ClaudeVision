"""Where the pack has no part drawings, the model is the parts list (D-411).

12675-01: three design-intent sheets, no parts list, no part sheets, and fourteen SolidWorks
files beside them. The drawings mint nothing; the model holds three designs and the bodies they
are built from, with the customer's bags modelled for fit. James Gray, 8 Oct 2026: "we should
be able to BOM and route a lot from this."

One design per book, chosen by what the run was asked for, else the drawing number, else the
GA convention — never by size and never by guess; every body under it a part with the model's
own size, material and count, stamped by the same connector that stamps a drawn part; reference
models set aside and named; the other designs named; and the book labelled a concept take-off on
the report, the sheet and the quote. Where the model cannot answer, the concept read with the
brief is the fallback, and only then the empty book.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.append(str(_ROOT / "src"))

import model_takeoff as mt  # noqa: E402
from source_connectors import solidworks as sw  # noqa: E402

_spec = importlib.util.spec_from_file_location("jrh", _ROOT / "src" / "job_report_html.py")
jrh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jrh)

P = sw.NativePart
GA = "12675-01-GA Stacking Block Model"
BLOCK = "12675-01-Block Model"
V2 = "12675-01-02 Block Model V2"
BAGS = "12675-01-Bag Stack"
SUB = "12675-01-SUB ARM SET"
BAG = "12675-M&S Customer Bag"


def _job() -> sw.NativeJob:
    return sw.NativeJob(
        found=True,
        assembly_pns=[GA, BLOCK, V2, BAGS, SUB],
        meta={"top_assembly": V2, "extract_path": r"\\share\12675-01\_sw_native_extract.json",
              "counts": {"records": 14}},
        part_signals={
            "12675-01-UPRIGHT": P(part_number="12675-01-UPRIGHT", material="MILD STEEL",
                                  section_profile={"a": 30, "b": 30, "t": 2, "profile_form": "SHS",
                                                   "length_mm": 1200}, bbox_mm=[1200, 30, 30], mass_kg=2.1),
            "12675-01-BASE": P(part_number="12675-01-BASE", material="MILD STEEL", is_sheet_metal=True,
                               thickness_mm=5.0, flat_length_mm=300.0, flat_width_mm=300.0,
                               flat_pattern=True, ops_hint=["laser_cutting"], bbox_mm=[300, 300, 5]),
            "12675-01-ARM": P(part_number="12675-01-ARM", material="MILD STEEL",
                              section_profile={"a": 10, "b": 10, "t": 10, "profile_form": "ROUND BAR",
                                               "length_mm": 250}, bbox_mm=[250, 10, 10]),
            BAG: P(part_number=BAG, likely_bought_in=True),
            "12675-01-02 BM V2 MDF Base": P(part_number="12675-01-02 BM V2 MDF Base", material="MDF",
                                            thickness_mm=18.0, bbox_mm=[400, 300, 18]),
            "12675-01-02 BM V2 Stainless": P(part_number="12675-01-02 BM V2 Stainless",
                                             material="STAINLESS STEEL", is_sheet_metal=True,
                                             thickness_mm=5.0, flat_length_mm=400, flat_width_mm=300,
                                             flat_pattern=True, ops_hint=["laser_cutting", "folding"],
                                             bend_count=2),
            "12675-01-Stacking Holder Block": P(part_number="12675-01-Stacking Holder Block",
                                                material="MDF", thickness_mm=18.0, bbox_mm=[400, 300, 18]),
        },
        hierarchy={
            GA: [("12675-01-UPRIGHT", 2), ("12675-01-BASE", 1), (SUB, 1), (BAG, 3),
                 ("12675-01-Stacking Holder Block", 1)],
            SUB: [("12675-01-ARM", 6)],
            BLOCK: [("12675-01-Stacking Holder Block", 1), (BAG, 2)],
            V2: [("12675-01-02 BM V2 MDF Base", 1), ("12675-01-02 BM V2 Stainless", 1), (BAG, 2)],
            BAGS: [(BAG, 5)],
        })


def _summary() -> dict:
    return {"manufacturing_writeup": {"parts": []}, "drawing_number": "12675-01",
            "job_source_pdfs": [{"name": "12675-01-GA Stacking Block Model_Design Intent.PDF"}],
            "estimate_summary": {"estimate_workbook_inputs": {"assumed_job_quantity": 10}},
            "cad_inputs": {}}


# ── the designs in the model ────────────────────────────────────────────────────────────

def test_the_roots_are_the_designs_and_a_stack_of_the_customers_bags_is_not_one():
    roots = mt.roots_of(_job())
    assert set(roots) == {GA, BLOCK, V2}
    assert BAGS not in roots, "an assembly of reference models alone is the customer's goods, not a design"
    assert SUB not in roots, "a sub-assembly is somebody's child"


def test_the_design_is_what_the_run_asked_for_else_the_drawing_number_else_the_ga_convention():
    roots = mt.roots_of(_job())
    chosen, how, others = mt.choose_design(roots, declared=V2, drawing_number="12675-01")
    assert chosen == V2 and "SDI_PRODUCT" in how and set(others) == {GA, BLOCK}
    chosen, how, others = mt.choose_design(roots, drawing_number="12675-01", top_assembly=V2)
    assert chosen == GA and "GA naming convention" in how
    assert set(others) == {BLOCK, V2}
    chosen, how, _ = mt.choose_design([V2], drawing_number="12675-01")
    assert chosen == V2 and "only assembly" in how


def test_two_designs_and_nothing_to_choose_by_is_a_question_not_a_guess():
    chosen, how, others = mt.choose_design([BLOCK, V2], drawing_number="12675-01")
    assert chosen is None
    assert "SDI_PRODUCT" in how and BLOCK in how and V2 in how
    assert set(others) == {BLOCK, V2}


def test_the_extracts_own_choice_is_accepted_only_when_nothing_else_decides_and_said():
    chosen, how, _ = mt.choose_design([BLOCK, V2], drawing_number="12675-01", top_assembly=V2)
    assert chosen == V2 and "the extract itself chose" in how and "confirm" in how


def test_members_are_counted_down_the_tree():
    m = mt.members_of(_job(), GA)
    assert m["12675-01-UPRIGHT"] == 2 and m["12675-01-ARM"] == 6 and m[SUB] == 1
    assert m[BAG] == 3
    assert GA not in m


# ── the take-off ────────────────────────────────────────────────────────────────────────

def test_the_chosen_designs_bodies_become_parts_stamped_by_the_connector():
    s = _summary()
    r = mt.takeoff(s, _job(), drawing_number="12675-01")
    assert not r["why_not"] and r["design"] == GA
    by = {p["part_number"]: p for p in r["parts"]}
    assert set(by) == {GA, "12675-01-UPRIGHT", "12675-01-BASE", SUB, "12675-01-ARM",
                       "12675-01-Stacking Holder Block"}
    root = by[GA]
    assert root["is_assembly_parent"] and root["quantity"] == 1
    assert set(root["assembly_children"]) == {"12675-01-UPRIGHT", "12675-01-BASE", SUB,
                                              "12675-01-Stacking Holder Block"}
    up = by["12675-01-UPRIGHT"]
    assert up["quantity"] == 2 and up["section_stock"]["profile_form"] == "SHS"
    assert up["section_stock"]["length_mm"] == 1200 and "section" in up["page_roles"]
    base = by["12675-01-BASE"]
    assert base["normalized_thickness_mm"] == 5.0
    assert (base["blank_length_mm"], base["blank_width_mm"]) == (300.0, 300.0)
    assert "laser_cutting" in base["textual_operations"]
    assert "MILD" in str(base["normalized_material"]).upper()
    arms = by["12675-01-ARM"]
    assert arms["quantity"] == 6 and arms["section_stock"]["profile_form"] == "ROUND BAR"
    assert by[SUB]["is_assembly_parent"] and by[SUB]["assembly_children"] == ["12675-01-ARM"]
    assert all(p.get("model_takeoff") and p.get("model_takeoff_design") == GA for p in r["parts"])
    assert all(any("CONCEPT TAKE-OFF FROM THE MODEL" in f for f in p.get("review_flags") or [])
               for p in r["parts"])


def test_the_customers_bags_are_set_aside_and_named_never_costed():
    s = _summary()
    r = mt.takeoff(s, _job(), drawing_number="12675-01")
    assert [e["part_number"] for e in r["excluded"]] == [BAG]
    assert "CUSTOMER" in r["excluded"][0]["why"]
    assert BAG not in {p["part_number"] for p in r["parts"]}
    assert BAG in " ".join(s["review_flags"])


def test_the_other_designs_are_named_not_priced():
    s = _summary()
    r = mt.takeoff(s, _job(), drawing_number="12675-01")
    assert set(r["other_designs"]) == {BLOCK, V2}
    assert not any(p["part_number"].startswith("12675-01-02") for p in r["parts"])
    assert "SDI_PRODUCT" in " ".join(s["review_flags"])


def test_the_record_knows_what_this_book_is():
    s = _summary()
    mt.takeoff(s, _job(), drawing_number="12675-01")
    t = s["concept_takeoff"]
    assert t["design"] == GA and t["parts"] == 5 and t["source"] == "solidworks_model"
    assert s["declared_product"] == GA, "the design being priced is the product of this run"
    sn = s["solidworks_native"]
    assert sn["found"] is True and sn["takeoff"] is True and sn["refused_wrong_job"] is False
    assert sn["top_assembly"] == GA


def test_a_declared_product_is_not_overwritten():
    s = _summary()
    s["declared_product"] = V2
    r = mt.takeoff(s, _job(), declared=V2, drawing_number="12675-01")
    assert r["design"] == V2 and s["declared_product"] == V2
    by = {p["part_number"]: p for p in r["parts"]}
    assert "folding" in by["12675-01-02 BM V2 Stainless"]["textual_operations"]
    assert "STAINLESS" in str(by["12675-01-02 BM V2 Stainless"]["normalized_material"]).upper()


def test_no_extract_no_take_off_and_the_reason_is_said():
    s = _summary()
    r = mt.takeoff(s, None, drawing_number="12675-01")
    assert r["parts"] == [] and "no SolidWorks extract" in r["why_not"]
    assert "concept_takeoff" not in s and "declared_product" not in s


def test_a_design_whose_members_are_all_reference_models_is_refused_with_the_names():
    job = sw.NativeJob(found=True, assembly_pns=["12675-01-GA Stand"],
                       part_signals={BAG: P(part_number=BAG)},
                       hierarchy={"12675-01-GA Stand": [(BAG, 4)]}, meta={})
    r = mt.takeoff(_summary(), job, drawing_number="12675-01")
    assert r["parts"] == [] and BAG in r["why_not"] and "reference model" in r["why_not"]
    assert [e["part_number"] for e in r["excluded"]] == [BAG]
    # and a run asked for an assembly that is only the customer's bags is told so, not handed
    # a design nobody asked for
    job2 = _job()
    job2.hierarchy[BLOCK] = [(BAG, 2)]
    r2 = mt.takeoff(_summary(), job2, declared=BLOCK, drawing_number="12675-01")
    assert r2["parts"] == []
    assert BLOCK in r2["why_not"] and "not a design in the model" in r2["why_not"]
    assert GA in r2["why_not"] and V2 in r2["why_not"]


def test_the_reference_words_live_in_config():
    import config
    assert any("CUSTOMER" in w for w in config.REFERENCE_MODEL_NAME_WORDS)
    assert mt.is_reference_model("12675-M&S Customer Bag_Estimated Stakable") == "CUSTOMER"
    assert mt.is_reference_model("12675-01-UPRIGHT") is None
    assert re.search(config.GA_NAME_TOKEN_PATTERN, GA)
    assert not re.search(config.GA_NAME_TOKEN_PATTERN, "12675-01-GAUGE PLATE")


# ── the label on every surface ──────────────────────────────────────────────────────────

def test_the_report_opens_on_the_take_off_label_with_the_design_and_what_was_set_aside():
    s = _summary()
    mt.takeoff(s, _job(), drawing_number="12675-01")
    import html as _html
    html = jrh.build_report_html(s)
    text = _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S))))
    assert "CONCEPT TAKE-OFF FROM THE MODEL — not a drawings estimate" in text
    assert GA in text and BAG in text and BLOCK in text and V2 in text
    assert html.index("CONCEPT TAKE-OFF FROM THE MODEL") < html.index("<h2>Summary</h2>")
    assert "NO PRICE — NOTHING TO COST" not in text, "a book with parts is not an empty book"


def test_a_report_without_a_take_off_has_no_label():
    assert jrh._render_concept_takeoff(_summary()) == ""


def test_the_quote_gate_says_it_is_a_concept_take_off():
    import quote_state as qs
    s = _summary()
    mt.takeoff(s, _job(), drawing_number="12675-01")
    st = qs.quote_state(s)
    assert st["customer_releasable"] is False
    gates = [b["gate"] for b in st["blocking"]]
    assert "concept_takeoff" in gates
    g = next(b for b in st["blocking"] if b["gate"] == "concept_takeoff")
    assert GA in g["what"] and "not a drawings estimate" in g["what"]


def test_the_sheet_carries_the_take_off_banner_beside_the_price_cells():
    openpyxl = pytest.importorskip("openpyxl")
    import wb_populate as wp
    s = _summary()
    mt.takeoff(s, _job(), drawing_number="12675-01")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["F6"] = "Unit Cost"; ws["G6"] = "=M225"
    ws["K231"] = "Sell Price"; ws["M231"] = "=M225/(100%-M229)"
    flags: list = []
    assert wp._write_concept_takeoff_banner(ws, s, flags) is True
    banners = [c.value for row in ws.iter_rows() for c in row
               if isinstance(c.value, str) and c.value.startswith("CONCEPT TAKE-OFF FROM THE MODEL")]
    assert len(banners) == 2 and all(GA in b for b in banners)
    assert wp._write_concept_takeoff_banner(openpyxl.Workbook().active, _summary(), []) is False


# ── the scan: model first, the concept read second, the empty book last ─────────────────

def test_the_scan_keeps_the_jobs_own_unmatched_extract_for_the_take_off():
    src = (_ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "_sw_job_own_unmatched = _sw_job" in src
    assert "_mt.takeoff(summary, _sw_job_own_unmatched," in src
    assert 'summary["manufacturing_writeup"]["parts"].extend(_took["parts"])' in src


def test_the_concept_read_is_the_fallback_and_the_stop_comes_last():
    src = (_ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "_sight_run = _llm_only_run or _design_intent_fallback" in src
    # the guard, the brief-unused flag and the concept read all ask the one name
    assert src.count("_sight_run and (_no_parts") == 3
    assert "_llm_only_run and (_no_parts" not in src, "no site still asks the old question"
    # the design-intent stop is recorded only after both doors, right before costing
    i_stop = src.index('if _di_pending and not summary["manufacturing_writeup"]["parts"]:')
    i_cost = src.index('summary["estimate_summary"] = estimate_document(summary["manufacturing_writeup"]["parts"]')
    assert i_stop < i_cost
