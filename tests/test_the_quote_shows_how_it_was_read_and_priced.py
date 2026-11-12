"""D-504: the quotation's pages after the price — how SDI read the enquiry, and how the price
is built — generated for every job from the run's own record.

James Gray, 13 Oct 2026, of the one-off K-Wellness showcase: "can we massively improve [the
portal quote] so it much more closely represents [it]... it needs to be auto-generated as part
of the general process, with as much detail as possible... two or three pages."

What these hold the document to:

  THE PRICE PAGE IS UNCHANGED, and the pages after it carry the same figure or none. The
  order quantity's column prints the first page's unit and order value to the penny; a sweep
  or a stamped total that disagrees with that figure (an amended sheet, a stale record) is
  not drawn; a page with no price shows no breakdown of one.

  WHAT IS QUOTED IS QUOTED. A blue box holds a line the pack itself contains, verbatim, with
  its page — and a line naming a material the bill does not carry (an earlier design's MDF)
  is not quoted as evidence for a steel price. A topic the pack says nothing about gets no box.

  THE SHEET'S OWN ARITHMETIC. Set-up per unit is the sweep's own reading of the recalculated
  rows (each row's set-up minutes at its department's rate, over the quantity), running work
  the rest of labour, overheads what the unit cell adds; the four add to the unit price.
  "Dress Welds" is dressing, not welding; a route is told in shop order.

  CUSTOMER LANGUAGE. Nothing on these pages names an estimator, an open question or an engine
  field.
"""
from __future__ import annotations

import os
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import client_quote_html                                               # noqa: E402
import quote_story                                                     # noqa: E402

fitz = pytest.importorskip("fitz")


def _pack(tmp_path: Path, pages) -> str:
    """A small enquiry PDF, one block of text per entry — the pack the run read."""
    doc = fitz.open()
    for blocks in pages:
        page = doc.new_page(width=595, height=842)
        y = 60
        for b in blocks:
            page.insert_text((50, y), b, fontsize=10)
            y += 40
    path = tmp_path / "enquiry.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


_PAGES = [
    ["Exploded view", "Front shelf x4", "Side panel x2", "Top cap x1", "Graphic holder x2"],
    ["Project background",
     "An earlier design used an MDF core clad in laminate for the look and feel.",
     "The new unit is made from folded sheet steel where possible."],
    ["Construction", "Shelves are welded to the uprights with hooked brackets."],
    ["Finish", "Powder coated in RAL 9016 traffic white."],
]

_LABOUR = [
    {"operation": "Laser (Metal)", "part_numbers": "UNIT-01", "setup_minutes": 10,
     "dept_rate_gbp_per_hour": 60, "total_value_gbp": 6.0},
    {"operation": "Laser (Metal)", "part_numbers": "UNIT-02", "setup_minutes": 10,
     "dept_rate_gbp_per_hour": 60, "total_value_gbp": 2.0},
    {"operation": "Fold", "part_numbers": "UNIT-01, UNIT-02", "setup_minutes": 30,
     "dept_rate_gbp_per_hour": 40, "total_value_gbp": 8.0},
    {"operation": "Dress Welds", "part_numbers": "UNIT-01", "setup_minutes": 30,
     "dept_rate_gbp_per_hour": 30, "total_value_gbp": 4.0},
    {"operation": "Weld (CO2)", "part_numbers": "UNIT-01", "setup_minutes": 30,
     "dept_rate_gbp_per_hour": 42, "total_value_gbp": 10.0},
    {"operation": "P.Coat", "part_numbers": "UNIT-01, UNIT-02", "setup_minutes": 15,
     "dept_rate_gbp_per_hour": 300, "total_value_gbp": 20.0},
    {"operation": "Assemble/pack (Metal)", "part_numbers": "UNIT-00", "setup_minutes": 15,
     "dept_rate_gbp_per_hour": 28, "total_value_gbp": 12.8},
    {"operation": "Total Labour Cost (Including Downtime)", "total_value_gbp": 62.8},
]

_MATERIAL = [
    {"block": "bom", "description": "UNIT-NV01 Fixings, M6 screw with nut and washer",
     "qty_per_unit": 20, "total_value_gbp": 3.0},
    {"block": "steel", "description": "UNIT-01 FRONT SHELF", "qty_per_unit": 4,
     "length_mm": 500, "width_mm": 300, "gauge": 1.5, "qty_per_sheet": 16,
     "scrap_pct": 0.04, "total_value_gbp": 10.4},
    {"block": "steel", "description": "UNIT-02 SIDE PANEL", "qty_per_unit": 2,
     "length_mm": 1500, "width_mm": 400, "gauge": 2.0, "qty_per_sheet": 4,
     "scrap_pct": 0.04, "total_value_gbp": 20.8},
    {"block": "other_sheet", "description": "Total Material Cost", "total_value_gbp": 50.5},
]

_PARTS = [
    {"part_number": "UNIT-01", "description": "FRONT SHELF", "quantity": 4,
     "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 1.5,
     "concept_kind": "fabricated", "unit_total_cost_gbp": 30.0, "colours": ["RAL 9016"]},
    {"part_number": "UNIT-02", "description": "SIDE PANEL", "quantity": 2,
     "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 2.0,
     "concept_kind": "fabricated", "unit_total_cost_gbp": 25.0},
    {"part_number": "UNIT-NV01", "description": "Fixings, M6 screw with nut and washer",
     "quantity": 20, "concept_kind": "bought_in", "unit_total_cost_gbp": 3.0},
    {"part_number": "PACKAGING", "description": "Packaging", "quantity": 1,
     "_commercial_placeholder": True},
]

UNIT = 120.4987


def _summary(tmp_path: Path, pages=_PAGES, **over):
    s = {
        "job_output_stem": "UNIT-GA",
        "job_source_pdfs": [{"name": "enquiry.pdf", "path": _pack(tmp_path, pages)}],
        "concept_read": {"parts": [{"code": "UNIT-01"}, {"code": "UNIT-02"}]},
        "estimate_summary": {
            "estimate_workbook_inputs": {"assumed_job_quantity": 50},
            "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": UNIT},
            "canonical_part_estimates": [dict(p) for p in _PARTS],
        },
        "final_estimate": {
            "totals": {"unit": UNIT, "material": 50.5, "labour": 62.8,
                       "unit_cell": "Estimate!G6", "unit_cell_value": UNIT},
            "labour_rows": [dict(r) for r in _LABOUR],
            "material_rows": [dict(r) for r in _MATERIAL],
        },
        "quantity_sweep": {"baseline_quantity": 50, "rows": [
            {"quantity": 1, "material": 80.0, "labour": 200.0, "unit": 300.0,
             "setup_per_unit": 140.0, "order_charges_per_unit": 30.0},
            {"quantity": 10, "material": 55.0, "labour": 74.0, "unit": 140.0,
             "setup_per_unit": 14.0, "order_charges_per_unit": 5.0},
            {"quantity": 50, "material": 50.5, "labour": 62.8, "unit": 120.50,
             "setup_per_unit": 2.8, "order_charges_per_unit": 1.0}]},
        "project_costs": {"total_gbp": 900.0, "lines": [
            {"code": "PROJECT-01", "name": "First-off sample inspection", "state": "provisional",
             "order_gbp": 400.0},
            {"code": "PROJECT-02", "name": "Drawing pack", "state": "charged",
             "order_gbp": 500.0},
            {"code": "PROJECT-03", "name": "Testing already in the price",
             "state": "included_elsewhere", "order_gbp": 250.0}]},
    }
    s.update(over)
    return s


def _pages(summary, **kw):
    parts = summary["estimate_summary"]["canonical_part_estimates"]
    args = dict(customer="Acme Retail", product="Shelving unit", job_number="UNIT-GA",
                qty=50, unit_price=UNIT, markup=1.0, basis="", sdi_logo="", cust_header="")
    args.update(kw)
    return quote_story.story_pages(summary, parts, **args)


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


# ── the document ─────────────────────────────────────────────────────────────────────

def test_the_story_pages_follow_the_price_page_which_is_unchanged(tmp_path):
    html = client_quote_html.build_quote_html(_summary(tmp_path), job_stem="UNIT-GA",
                                              customer="Acme Retail")
    assert html.count('<div class="sheet') == 3, "price page + reading page + costing page"
    first = html.split('<div class="sheet qs">')[0]
    assert 'class="price-box"' in first and "What's included" in first
    assert "£120.50" in first and "£6,024.94" in first
    assert html.index('class="price-box"') < html.index("How we read your enquiry") \
        < html.index("From drawing to price")


def test_they_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_story, "_config",
                        types.SimpleNamespace(QUOTE_DOCUMENT={"story_pages": False}))
    html = client_quote_html.build_quote_html(_summary(tmp_path), job_stem="UNIT-GA",
                                              customer="Acme Retail")
    assert html.count('<div class="sheet') == 1


def test_a_run_that_costed_nothing_has_no_story(tmp_path):
    s = _summary(tmp_path)
    s["estimate_summary"]["canonical_part_estimates"] = []
    assert _pages(s) == ("", "")


# ── what is quoted is quoted ─────────────────────────────────────────────────────────

def test_every_quote_is_a_line_of_the_pack_with_its_page(tmp_path):
    s = _summary(tmp_path)
    ev = quote_story.evidence_items(s, quote_story.job_facts(s, _PARTS, 50))
    pack = " ".join(b for page in _PAGES for b in page)
    for e in ev:
        assert e["saw"], f"{e['topic']}: the pack speaks to this topic"
        for piece in e["saw"]["text"].split("” · “"):
            assert piece in pack, f"{e['topic']} quoted words the pack does not contain: {piece}"


def test_a_labelled_view_is_quoted_as_the_parts_list_the_customer_drew(tmp_path):
    s = _summary(tmp_path)
    ev = {e["topic"]: e for e in quote_story.evidence_items(
        s, quote_story.job_facts(s, _PARTS, 50))}
    assert ev["parts"]["saw"]["page"] == 1
    assert "Front shelf x4" in ev["parts"]["saw"]["text"]
    assert "Side panel x2" in ev["parts"]["saw"]["text"]


def test_a_material_the_bill_does_not_carry_is_not_quoted_as_evidence(tmp_path):
    s = _summary(tmp_path)
    ev = {e["topic"]: e for e in quote_story.evidence_items(
        s, quote_story.job_facts(s, _PARTS, 50))}
    assert "MDF" not in ev["material"]["saw"]["text"]
    assert "sheet steel" in ev["material"]["saw"]["text"]


def test_the_joint_quoted_is_the_one_the_bill_charges(tmp_path):
    s = _summary(tmp_path)
    ev = {e["topic"]: e for e in quote_story.evidence_items(
        s, quote_story.job_facts(s, _PARTS, 50))}
    assert "welded" in ev["joints"]["saw"]["text"]
    assert ev["joints"]["saw"]["page"] == 3


def test_a_topic_the_pack_is_silent_on_gets_no_quote_box(tmp_path):
    s = _summary(tmp_path, pages=_PAGES[:3])                  # no finish page
    ev = {e["topic"]: e for e in quote_story.evidence_items(
        s, quote_story.job_facts(s, _PARTS, 50))}
    assert ev["finish"]["saw"] is None
    assert ev["finish"]["concluded"].startswith("Powder coated")


def test_a_label_broken_over_two_blocks_is_one_sentence(tmp_path):
    page = {"blocks": ["Shelf tray would have welded", "or riveted hooked brackets.",
                       "Not separate brackets"]}
    assert quote_story._lines(page) == ["Shelf tray would have welded or riveted hooked brackets.",
                                        "Not separate brackets"]


# ── the sheet's own arithmetic ───────────────────────────────────────────────────────

def test_the_cost_model_reads_the_sheets_setup_and_adds_to_the_unit(tmp_path):
    s = _summary(tmp_path)
    facts = quote_story.job_facts(s, _PARTS, 50)
    model = {m["quantity"]: m for m in quote_story.cost_model(s, facts)}
    assert model[1]["setup"] == pytest.approx(140.0)
    assert model[1]["running"] == pytest.approx(60.0)
    for m in model.values():
        assert m["material"] + m["setup"] + m["running"] + m["overheads"] == \
            pytest.approx(m["unit"], abs=1e-6)


def test_the_order_column_is_the_price_pages_figure_to_the_penny(tmp_path):
    css, html = _pages(_summary(tmp_path))
    t = _text(html)
    assert "£6,024.94" in t, "200 × the sweep's rounded unit would print a different order value"
    assert "£6,025.00" not in t


def test_a_stale_sweep_is_not_drawn_beside_a_different_price(tmp_path):
    s = _summary(tmp_path)
    s["quantity_sweep"]["rows"][2]["unit"] = 131.00          # the sheet was amended since
    css, html = _pages(s)
    t = _text(html)
    assert "£300.00" not in t and "£140.00" not in t, "the stale columns were drawn"
    assert "£120.50" in t, "the stamped totals still agree, so the order quantity is shown"


def test_stamped_figures_that_disagree_draw_no_money_at_all(tmp_path):
    s = _summary(tmp_path)
    s["final_estimate"]["totals"]["unit"] = 150.0
    s["quantity_sweep"]["rows"][2]["unit"] = 150.0
    css, html = _pages(s)
    t = _text(html)
    assert "Set-up spreads" not in t
    # The price page's own figure may be named; nothing the stale record holds may be.
    before = t.split("One-off costs")[0].replace("£120.50", "")
    assert not re.search(r"£\d", before), "money drawn from a stale record"


def test_a_page_with_no_price_shows_no_breakdown_of_one(tmp_path):
    css, html = _pages(_summary(tmp_path), unit_price=None)
    t = _text(html)
    assert "Set-up spreads" not in t and "The workbook's own sum" not in t


def test_dressing_is_not_welding_and_the_route_is_in_shop_order(tmp_path):
    s = _summary(tmp_path)
    facts = quote_story.job_facts(s, _PARTS, 50)
    assert quote_story._dept_label("Dress Welds")[1] == "Dress"
    deps = facts["departments"]
    assert deps.index("Weld") < deps.index("Dress") < deps.index("Powder coat")
    assert not any(str(r.get("operation", "")).startswith("Total") for r in facts["labour"])


def test_the_traced_part_is_the_sheets_own_sum(tmp_path):
    # D-592: the worked example is a line with size, price and route evidence — a measured
    # blank and a charged figure the read-back recorded. Without them there is no example.
    s = _summary(tmp_path)
    assert quote_story.trace_part(s, quote_story.job_facts(s, _PARTS, 50)) is None
    s["final_estimate"]["totals"]["unit_gbp"] = UNIT
    parts = [dict(p) for p in _PARTS]
    for p in parts:
        if p["part_number"] == "UNIT-01":
            p.update(blank_length_mm=500.0, blank_width_mm=300.0,
                     blank_length_mm_source="dxf_flat_pattern")
    s_facts = quote_story.job_facts(s, parts, 50)
    tp = quote_story.trace_part(s, s_facts)
    assert tp["code"] == "UNIT-01", "the part with the longest route through the shop"
    assert tp["each"] * tp["qty"] * (1 + tp["scrap"]) == pytest.approx(tp["value"])
    assert tp["said"]["text"] == "Front shelf x4"


def test_project_costs_are_the_lines_the_order_carries(tmp_path):
    css, html = _pages(_summary(tmp_path))
    t = _text(html)
    assert "First-off sample inspection" in t and "Drawing pack" in t
    assert "Testing already in the price" not in t
    assert "£900.00" in t
    assert "£6,924.94" in t, "the order total with the one-off costs"


def test_commercial_lines_are_not_parts(tmp_path):
    facts = quote_story.job_facts(_summary(tmp_path), _PARTS, 50)
    assert facts["lines"] == 3
    assert {p["part_number"] for p in facts["made"]} == {"UNIT-01", "UNIT-02"}


# ── customer language ────────────────────────────────────────────────────────────────

def test_nothing_internal_reaches_the_pages(tmp_path):
    css, html = _pages(_summary(tmp_path))
    t = _text(html).lower()
    for word in ("estimator", "to confirm", "question", "flag", "review", "not priced",
                 "outstanding", "provisional", "placeholder", "engine"):
        assert not re.search(rf"\b{word}\b", t), f"internal wording on a customer page: {word!r}"


def test_the_customers_pages_are_reproduced_for_them_alone(tmp_path):
    css, html = _pages(_summary(tmp_path))
    assert "data:image/" in html, "the page each quote came from is shown"
    assert "reproduced for Acme Retail only" in html


def test_the_run_keeps_the_quantity_figures_on_its_record():
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert re.search(r'for _carry in \("withheld_price_lines", "quantity_sweep", '
                     r'"project_costs"\)', src), (
        "the quote is generated from the saved record, so the sweep must be carried onto it")


# ── drawing packs ────────────────────────────────────────────────────────────────────

def _drawing_summary(tmp_path):
    s = _summary(tmp_path, pages=[
        ["ITEM DWG NO. DESCRIPTION QTY", "1 UNIT-01 FRONT SHELF 4", "2 UNIT-02 SIDE PANEL 2",
         "CHINA MATERIAL SPECIFICATION: Q195 UP TO 3mm THICK FOR POWDER COATED STEEL",
         "DRAWN BY"],
        ["MATERIAL: MILD STEEL 1.5mm", "FINISH: POWDER COATED RAL 9016",
         "ALL WELDS TO BE TIG UNLESS STATED"],
        ["SHELF CORNERS TO BE WELDED AND DRESSED"]])
    s.pop("concept_read")
    return s


def test_a_drawings_parts_list_is_quoted_by_its_rows(tmp_path):
    s = _drawing_summary(tmp_path)
    ev = {e["topic"]: e for e in quote_story.evidence_items(
        s, quote_story.job_facts(s, _PARTS, 50))}
    assert "1 UNIT-01 FRONT SHELF 4" in ev["parts"]["saw"]["text"]


def test_the_drawing_borders_legend_is_never_quoted_as_this_enquiry(tmp_path):
    s = _drawing_summary(tmp_path)
    ev = quote_story.evidence_items(s, quote_story.job_facts(s, _PARTS, 50))
    quoted = " ".join(e["saw"]["text"] for e in ev if e["saw"])
    assert "Q195" not in quoted and "UNLESS STATED" not in quoted
    assert "SHELF CORNERS TO BE WELDED AND DRESSED" in quoted


def test_drawing_lines_are_the_drawings_not_a_person_and_an_unnamed_customer_is_you(tmp_path):
    css, html = _pages(_drawing_summary(tmp_path), customer="Customer")
    assert "Your drawings · page" in html and "Customer · page" not in html
    assert "reproduced for you only" in html


def test_without_stamped_rows_the_route_still_says_what_is_welded_and_coated(tmp_path):
    s = _summary(tmp_path)
    s["final_estimate"]["labour_rows"] = []
    s["estimate_summary"]["canonical_route_shadow"] = {"decisions": [
        {"operation": "welding", "status": "required", "participants": ["UNIT-01"]},
        {"operation": "powder_coating", "status": "required", "participants": ["UNIT-01"]},
        {"operation": "laser_cutting", "status": "ruled_out", "participants": ["UNIT-02"]}]}
    ev = {e["topic"]: e for e in quote_story.evidence_items(
        s, quote_story.job_facts(s, _PARTS, 50))}
    assert ev["joints"]["concluded"].startswith("Welded")
    assert ev["finish"]["concluded"].startswith("Powder coated")
    assert "£" not in ev["joints"]["bill"], "no row was charged, so no figure is claimed"


# ── D-575: the story counts what the run matched, and a made part's section is material ──

def test_the_story_counts_matched_flats_and_the_model_not_file_names(tmp_path):
    s = _summary(tmp_path)
    assert quote_story.job_facts(s, _PARTS, 50)["dxf"] == 0
    s["dxf_augmentation"] = {"matched": [{"part_number": "UNIT-01", "dxf": "a.dxf"},
                                         {"part_number": "UNIT-02", "dxf": "b.dxf"}],
                             "unmatched_dxf": []}
    s["solidworks_native"] = {"found": True, "counts": {"parts": 5, "assemblies": 2}}
    facts = quote_story.job_facts(s, _PARTS, 50)
    assert facts["dxf"] == 2 and facts["models"] == 7
    s["solidworks_native"] = {"found": False, "native_present_but_unread": True}
    assert quote_story.job_facts(s, _PARTS, 50)["models"] == 0


def test_a_made_parts_section_on_the_bom_block_is_sheet_and_section_material(tmp_path):
    s = _summary(tmp_path)
    parts = [dict(p) for p in _PARTS] + [
        {"part_number": "UNIT-03M-CL1", "description": "15.00 x 30.00 x 2.00mm TUBE 1164", "quantity": 1,
         "normalized_material": "MILD_STEEL", "concept_kind": "fabricated", "unit_total_cost_gbp": 11.36}]
    s["final_estimate"]["material_rows"].insert(0, {
        "block": "bom", "description": "UNIT-03M-CL1  15.00 x 30.00 x 2.00mm TUBE 1164",
        "supplier": "SDI config section rate - verify", "qty_per_unit": 1, "total_value_gbp": 11.36})
    s["estimate_summary"]["canonical_part_estimates"] = [dict(p) for p in parts]
    facts = quote_story.job_facts(s, parts, 50)
    facts["agree"], facts["markup"] = True, 1.0            # as the page builder sets them
    ev = {e["topic"]: e for e in quote_story.evidence_items(s, facts)}
    bill = ev["material"]["bill"]
    # 10.4 + 20.8 sheet, 11.36 section; the bought-in fixings (3.0) stay out.
    assert "£42.56" in bill or "42.56" in bill, bill
