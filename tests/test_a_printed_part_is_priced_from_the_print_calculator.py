"""A printed part is priced from the AI Print calculator, once, and says so (JG, 15 Nov 2026).

"AI Print calculator: the setting points at it. Costing does not call it yet." -- "well it
should. next code release put this in. estimating have been waiting for this."

The rules under test (src/print_costing.py):
  * a part is printed when its own finish, note or description states print; a part only
    named a graphic is asked about, not charged;
  * the substrate is the sheet's row for the part's material and gauge: one row or none;
  * the size is the part's measured one, never a provisional blank;
  * one price: a part with its own catalogue price keeps it; where the calculator prices the
    part the engine's own material and cutting are withdrawn;
  * the sheet is worked as it stands, and each point it leaves open is a question.

The workbook is built here with the calculator's layout and invented figures. Estimating's own
workbook is never in the repository.
"""
import html as _html
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import print_calculator_sheet as sheet  # noqa: E402
import print_costing as pc  # noqa: E402

SETUP, SCRAP = 30.0, 0.1
ROWS = [("3mm White Foamed PVC", "Full colour digital 1 side", "1220x2440mm", SETUP, 100.0),
        ("2mm Clear PETG", "Full colour digital 1 side", "1250x2050mm", None, 150.0),
        ("White Vinyl", "Full colour digital 1 side", "1000x1000mm", None, 60.0),
        ("Mag Vinyl", "Full colour digital 1 side", "10000x1000mm", None, 800.0)]


def _book(tmp_path, scrap=SCRAP):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"], ws["C1"], ws["D1"], ws["E1"] = "AI BUDGET COSTING", "Sheet Size", "Set-up Cost", "Run Cost (print & cut)"
    for n, row in enumerate(ROWS, 2):
        for c, v in enumerate(row, 1):
            ws.cell(n, c).value = v
    ws["A9"], ws["I9"], ws["I10"] = "Material", "Scrap %", scrap
    path = tmp_path / "print.xlsx"
    wb.save(path)
    return sheet.read_sheet(str(path))


def _part(**over):
    p = {"part_number": "T-100-01", "description": "HEADER PANEL", "quantity": 2,
         "normalized_material": "PVC", "normalized_thickness_mm": 3.0,
         "normalized_finish": "PRINTED - SEE PRINT SPEC", "blank_length_mm": 500.0,
         "blank_width_mm": 250.0, "pages": [4], "page_roles": ["detail"]}
    p.update(over)
    return p


def _estimate(**over):
    e = {"part_number": "T-100-01", "unit_total_cost_gbp": 4.0,
         "material_estimate": {"unit_material_cost_gbp": 3.0, "cost_method": "sheet_rate"},
         "labour_estimate": {"total_labour_cost_gbp": 1.0}}
    e.update(over)
    return e


def _cost(line, qty):
    line["unit_total_cost_gbp"] = line["unit_cost_gbp"]
    return line


def _stub(pn, desc, qty):
    return {"part_number": pn, "description": desc, "quantity": qty, "page_roles": ["bought_in"],
            "review_flags": []}


def _expected(length, width, sheet_l, sheet_w, run, printed):
    across = int((sheet_w - 5) / (width + 20))
    along = int(sheet_l / (length + 20))
    per = across * along
    return per, run / per * (1 + SCRAP) + SETUP / printed


# ── what counts as printed ───────────────────────────────────────────────────────────────

def test_a_part_is_printed_when_its_own_evidence_states_print():
    assert pc.printed_basis(_part())["how"] == "stated"
    assert pc.printed_basis(_part(normalized_finish=None, process_notes=["DIGITALLY PRINTED 1 SIDE"]))["how"] == "stated"
    # named a graphic and nothing states print: asked, not charged
    assert pc.printed_basis(_part(normalized_finish="SCRAPED EDGES", description="GRAPHIC LENS"))["how"] == "named"
    # the contrast: a painted panel, and a note that says it is NOT printed
    assert pc.printed_basis(_part(normalized_finish="POWDER COATED")) is None
    assert pc.printed_basis(_part(normalized_finish="NOT PRINTED")) is None
    assert pc.printed_basis(_part(is_assembly_parent=True)) is None


# ── the substrate is one row of the sheet, or none ───────────────────────────────────────

def test_the_substrate_is_the_sheets_row_for_the_material_and_the_gauge(tmp_path):
    read = _book(tmp_path)
    row, why = pc.substrate_for(read, "PVC", 3.0)
    assert row["name"] == "3mm White Foamed PVC" and why == ""
    # the same material at a gauge the sheet does not hold prices nothing, and says so
    row, why = pc.substrate_for(read, "PVC", 5.0)
    assert row is None and "3mm White Foamed PVC" in why and "5 mm" in why
    # a material that fits two rows is not guessed between
    row, why = pc.substrate_for(read, "VINYL", None)
    assert row is None and "2 rows" in why
    assert pc.substrate_for(read, "MAG VINYL", None)[0]["name"] == "Mag Vinyl"
    assert pc.substrate_for(read, "CARD+MAG TAPE", None)[0] is None


# ── the calculator's price, once ─────────────────────────────────────────────────────────

def test_a_stated_printed_part_takes_the_sheets_total_and_loses_the_engines_own(tmp_path):
    read = _book(tmp_path)
    out = pc.settle(_part(), _estimate(), 10, _cost, _stub, read=read)
    per, total = _expected(500, 250, 1220, 2440, 100.0, printed=20)
    rec = out["print_calculator"]
    assert rec["applied"] and rec["provisional"] and rec["parts_per_sheet"] == per
    assert rec["total_gbp"] == pytest.approx(total, abs=1e-3)
    assert out["unit_total_cost_gbp"] == pytest.approx(round(total, 2))
    assert out["source"] == pc.SOURCE_KEY and out["supplier"] == sheet.SOURCE
    # ONE PRICE: the engine's own material and labour are named as withdrawn, not added
    assert rec["withdrawn"] == {"material_gbp": 3.0, "labour_gbp": 1.0, "material_method": "sheet_rate"}
    asked = [q["issue"] for q in out["manufacturing_questions"]]
    assert any("print & cut" in a for a in asked)
    # every point the sheet leaves open is a question, none is corrected
    for point in sheet.points_to_confirm(read):
        assert any(point in a for a in asked)
    assert any("PROVISIONAL" in f for f in out["review_flags"])


def test_a_part_with_its_own_catalogue_price_keeps_it(tmp_path):
    est = _estimate(material_estimate={
        "unit_material_cost_gbp": 7.74,
        "price_source": {"source_class": "catalogue", "source_note": "its own row"}})
    out = pc.settle(_part(), est, 10, _cost, _stub, read=_book(tmp_path))
    assert out is est and out["unit_total_cost_gbp"] == 4.0
    assert out["print_calculator"]["applied"] is False
    assert "own catalogue row" in out["print_calculator"]["why_not"]


def test_a_part_only_named_a_graphic_is_asked_about_and_not_charged(tmp_path):
    part = _part(normalized_finish="SCRAPED EDGES", description="GRAPHIC LENS")
    out = pc.settle(part, _estimate(), 10, _cost, _stub, read=_book(tmp_path))
    assert out["unit_total_cost_gbp"] == 4.0 and out["print_calculator"]["applied"] is False
    q = out["manufacturing_questions"][0]
    assert "is it printed?" in q["issue"] and "it would be" in q["assumption"]


@pytest.mark.parametrize("change, said", [
    ({"normalized_material": "ACRYLIC"}, "not a substrate"),
    ({"blank_length_mm": None, "blank_width_mm": None}, "no measured length and width"),
    ({"geometry_provisional": True}, "provisional"),
    ({"blank_length_mm_source": "printed_extents_provisional"}, "no measured length and width"),
    ({"blank_length_mm": 3000.0, "blank_width_mm": 2600.0}, "does not fit"),
])
def test_what_the_sheet_cannot_price_keeps_its_price_and_says_why(tmp_path, change, said):
    out = pc.settle(_part(**change), _estimate(), 10, _cost, _stub, read=_book(tmp_path))
    assert out["unit_total_cost_gbp"] == 4.0, "the price it had stands"
    assert said in out["print_calculator"]["why_not"]
    assert any("no print cost is in its price" in q["issue"] for q in out["manufacturing_questions"])
    assert any("No print is in this line" in f for f in out["review_flags"])


def test_a_part_too_long_for_the_sheets_lay_is_worked_turned_and_asked(tmp_path):
    # 1240 long does not fit the 1220 the sheet calls Length; turned, it does
    out = pc.settle(_part(blank_length_mm=1240.0, blank_width_mm=400.0), _estimate(), 10,
                    _cost, _stub, read=_book(tmp_path))
    rec = out["print_calculator"]
    assert rec["applied"] and rec["turned"] and rec["length_mm"] == 400.0
    assert any("worked turned" in q["issue"] for q in out["manufacturing_questions"])


def test_no_calculator_named_changes_nothing():
    est = _estimate()
    out = pc.settle(_part(), est, 10, _cost, _stub,
                    read={"ok": False, "path": None, "why": "SDI_PRINT_CALCULATOR_XLSX is not set"})
    assert out is est and "print_calculator" not in out and "manufacturing_questions" not in out


def test_an_unprinted_part_is_never_touched(tmp_path):
    est = _estimate()
    out = pc.settle(_part(normalized_finish="POWDER COATED"), est, 10, _cost, _stub, read=_book(tmp_path))
    assert out is est and "print_calculator" not in out


# ── through the engine's own part costing ────────────────────────────────────────────────

def test_the_engine_costs_a_printed_part_from_the_sheet_and_a_plain_one_as_before(tmp_path, monkeypatch):
    read = _book(tmp_path)
    monkeypatch.setenv("SDI_PRINT_CALCULATOR_XLSX", read["path"])
    pc._READ_CACHE.clear()
    import estimator
    out = estimator.estimate_part(_part(), job_quantity=10)
    _per, total = _expected(500, 250, 1220, 2440, 100.0, printed=20)
    assert out["costing_basis"] == "bought_in_recognised_price:ai_print_calculator"
    assert out["unit_total_cost_gbp"] == pytest.approx(round(total, 2))
    assert out["print_calculator"]["applied"] is True
    assert out["labour_estimate"]["extended_labour_cost_gbp"] == 0.0, "no cutting on top of print & cut"
    plain = estimator.estimate_part(_part(normalized_finish="POWDER COATED"), job_quantity=10)
    assert "print_calculator" not in plain
    assert str(plain.get("costing_basis") or "") != "bought_in_recognised_price:ai_print_calculator"
    pc._READ_CACHE.clear()


# ── the e-mail's calculator section ──────────────────────────────────────────────────────

def _text(html):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def test_the_print_block_sits_below_the_box_block_and_shows_every_step(tmp_path, monkeypatch):
    import config
    import estimate_explained as ee
    from commercial_lines import _box_method_price
    monkeypatch.setitem(config.BOX_COSTING, "enabled", True)
    monkeypatch.setitem(config.BOX_COSTING, "formula", "sheet")
    box = _box_method_price({"order_quantity": 120, "left_out_parts": [], "counted_parts": [
        {"part_number": "X1", "length_mm": 88, "width_mm": 38, "thickness_mm": 1955, "per_assembly": 1}]})
    priced = pc.settle(_part(), _estimate(), 10, _cost, _stub, read=_book(tmp_path))
    held = pc.settle(_part(part_number="T-100-02", normalized_material="ACRYLIC"), _estimate(), 10,
                     _cost, _stub, read=_book(tmp_path))
    doc = {"estimate_summary": {"part_estimates": [priced, held, {"part_number": "PLAIN"}]}}
    lines = ee.part_calculator_lines(doc)
    assert [ln["code"] for ln in lines] == ["PRINT"] and len(lines[0]["calculator_inputs"]) == 2
    t = _text(ee.calculator_inputs_html(
        [{"code": "PACKAGING", "calculator_inputs": [box["calculator_inputs"]]}] + lines))
    assert t.index("Box calculator") < t.index("Print calculator — 1 printed part priced")
    rec = priced["print_calculator"]
    assert f"{rec['parts_per_sheet']} to a sheet" in t and "These prices are provisional" in t
    assert "Step 3. The set-up, shared over the parts printed" in t and "20 printed" in t
    assert "material £3.00 each and labour £1.00 each" in t
    assert "Not priced by the print calculator" in t and "T-100-02" in t and "not a substrate" in t
    # no printed part, no print block
    assert "Print calculator" not in _text(ee.calculator_inputs_html(
        [{"code": "PACKAGING", "calculator_inputs": [box["calculator_inputs"]]}]))


def test_the_tube_block_lists_the_lines_priced_from_the_tube_sheet_and_only_those():
    import estimate_explained as ee
    tube = {"part_number": "T-200-01", "description": "UPRIGHT", "quantity": 1,
            "material_estimate": {
                "supplier": "AI Tube calculator", "rate_gbp_per_m": 2.0, "unit_material_cost_gbp": 5.2,
                "waste_factor_applied": 1.04,
                "stock_estimate": {"section_length_mm": 2500.0, "catalogue_rows": [
                    {"part_code": "STOCK1", "description": "RECT 60 x 30 (6m)", "unit_price_gbp": 12.0,
                     "supplier": "AI Tube calculator", "catalogue_length_mm": 6000.0}]}}}
    other = {"part_number": "T-200-02", "material_estimate": {
        "supplier": "Somebody Steel", "stock_estimate": {"catalogue_rows": [
            {"part_code": "Z", "supplier": "Somebody Steel"}]}}}
    lines = ee.part_calculator_lines({"estimate_summary": {"part_estimates": [tube, other]}})
    assert [ln["code"] for ln in lines] == ["TUBE"]
    t = _text(ee.calculator_inputs_html(lines))
    assert "Tube calculator — 1 line priced" in t and "T-200-01" in t and "STOCK1" in t
    assert "2.500 m" in t and "£5.20" in t and "T-200-02" not in t
    assert ee.part_calculator_lines({"estimate_summary": {"part_estimates": [other]}}) == []
