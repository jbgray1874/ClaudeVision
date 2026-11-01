"""The AI estimate against the manual one, line by line (SCRUM-157, D-623).

JG, 1 Nov 2026: the file-by-file parity "will be very old and needing a big upgrade in quality".
The review: distinguish cost from selling price, match quantities and revisions, expose scope,
delivery, installation, overheads and margin; the manual estimate is a comparison, not the
answer.

The manual workbook here is built on the house template's own labels and block headers (the
ones parity_check and the read-back use), and the AI side is a read-back record shaped as the
engine writes it, so both are read by the production readers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

openpyxl = pytest.importorskip("openpyxl")
import parity_compare as pcmp  # noqa: E402

MAN_MAT = 96.40
MAN_LAB = 29.00
MAN_UNIT = round((MAN_MAT + MAN_LAB) / (1 - 0.066) / 0.93, 2)
MAN_SELL = round(MAN_UNIT / (1 - 0.25), 2)


def manual_workbook(path: Path, qty=10, rev="B") -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"

    def put(r, values):
        for col, v in values.items():
            ws[f"{col}{r}"] = v
    put(1, {"A": "Drawing No", "D": "12677-01-GA"})
    put(2, {"A": "Rev", "D": rev})
    put(3, {"A": "Customer", "D": "Acme"})
    put(4, {"A": "Quantity", "D": qty})
    put(6, {"A": "Bill of Materials", "B": "Part Code", "I": "Supplier", "J": "Price",
            "K": "Qty per unit", "L": "Scrap", "M": "Total Value"})
    put(7, {"A": "M6 screws", "B": "BI-SCREW", "J": 0.05, "K": 8, "M": 0.40})
    put(8, {"A": "Delivery to store", "B": "DELIVERY", "M": 40.0})
    put(9, {"A": "Pallet and wrap", "B": "PACK-01", "M": 5.0})
    put(10, {"A": "Bought frame tube", "B": "12677-01-05", "M": 30.0})
    put(12, {"A": "Sheet Steel"})
    put(13, {"A": "Part Description", "D": "Qty per unit", "E": "Part Length", "F": "Part Width",
             "G": "Gauge", "H": "Thickness", "I": "Qty per sheet", "J": "Scrap", "M": "Cost per part"})
    put(14, {"A": "12677-01-01 PANEL", "D": 1, "E": 1250, "F": 525, "G": 1.5, "M": 12.0})
    put(15, {"A": "12677-01-02 BRACKET", "D": 2, "E": 200, "F": 100, "G": 1.5, "M": 1.0})
    put(16, {"A": "12677-01-03 FRAME", "D": 1, "E": 2000, "F": 50, "G": 2.0, "M": 8.0})
    put(17, {"A": "Total Material Cost", "M": MAN_MAT})
    put(19, {"A": "Part No", "B": "Operation", "C": "Part Description", "D": "Dept",
             "E": "Qty per unit", "F": "Rate per hour", "G": "Total hours", "H": "Labour cost",
             "I": "Set up", "M": "Total Value"})
    put(20, {"A": "12677-01-01", "B": "Laser", "D": "LASER", "H": 60, "I": 15, "M": 3.0})
    put(21, {"A": "12677-01-03", "B": "Weld frame", "D": "WELD", "M": 6.0})
    put(22, {"B": "Install on site", "D": "SITE", "M": 20.0})
    put(23, {"A": "Total Labour Cost (Including Downtime)", "M": MAN_LAB})
    put(25, {"A": "Rebate Calculator", "D": 0.066})
    put(26, {"A": "Total Unit Cost Price", "M": MAN_UNIT})
    put(27, {"A": "Margin Applied", "D": 25})
    put(28, {"A": "Sell Price", "M": MAN_SELL})
    wb.save(path)
    return path


AI_ROWS = [
    {"block": "bom", "part_code": "BI-SCREW", "description": "M6 screws", "total_value_gbp": 0.40,
     "qty_per_unit": 8, "charged_cell": "Estimate!M12"},
    {"block": "bom", "part_code": "DELIVERY", "description": "DELIVERY (indicative)",
     "total_value_gbp": 42.50, "charged_cell": "Estimate!M13"},
    {"block": "bom", "part_code": "PACKAGING", "description": "PACKAGING (indicative)",
     "total_value_gbp": 27.50, "charged_cell": "Estimate!M14"},
    {"block": "steel", "description": "12677-01-01 PANEL", "total_value_gbp": 13.0,
     "qty_per_unit": 1, "length_mm": 1260, "width_mm": 525, "gauge": 1.5,
     "charged_cell": "Estimate!M60"},
    {"block": "steel", "description": "12677-01-02 BRACKET", "total_value_gbp": 1.0,
     "qty_per_unit": 4, "charged_cell": "Estimate!M61"},
    {"block": "steel", "description": "12677-01-05 FRAME TUBE", "total_value_gbp": 20.0,
     "qty_per_unit": 1, "charged_cell": "Estimate!M62"},
    {"block": "steel", "description": "12677-01-09 EXTRA PLATE", "total_value_gbp": 2.0,
     "qty_per_unit": 1, "charged_cell": "Estimate!M63"},
]
AI_MAT = round(sum(r["total_value_gbp"] for r in AI_ROWS), 2)
AI_LAB = 9.50
AI_UNIT = round((AI_MAT + AI_LAB) / (1 - 0.066) / 0.93, 2)


def ai_summary(path: Path, qty=10, sweep=None, revision="C") -> Path:
    doc = {
        "drawing_number": "12677-01-GA",
        "estimate_summary": {
            "estimate_workbook_inputs": {"assumed_job_quantity": qty},
            "drawing_revision": revision,
            "workbook_equivalent_pricing": {
                "m107_rebate_fraction": 0.066, "overhead_absorption_factor": 0.93,
                "m109_sell_margin_fraction": 0.0, "l105_total_unit_cost_gbp": AI_UNIT,
                "l111_sell_price_gbp": AI_UNIT},
        },
        "final_estimate": {
            "totals": {"material_gbp": AI_MAT, "labour_gbp": AI_LAB, "unit_gbp": AI_UNIT,
                       "unit_cell": "Estimate!M105"},
            "unit_price_composition": {"rebate_fraction": 0.066, "absorption_divisor": 0.93},
            "material_rows": AI_ROWS,
            "labour_rows": [
                {"part_numbers": "12677-01-01", "operation": "Laser", "department": "LASER",
                 "total_value_gbp": 3.5, "charged_cell": "Estimate!M110"},
                {"part_numbers": "12677-01-03", "operation": "Weld frame", "department": "WELD",
                 "total_value_gbp": 6.0, "charged_cell": "Estimate!M111"}],
        },
    }
    if sweep:
        doc["quantity_sweep"] = {"rows": [{"quantity": q, "unit": u} for q, u in sweep.items()]}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture()
def detail(tmp_path):
    return pcmp.compare(ai_summary(tmp_path / "12677.json"),
                        manual_workbook(tmp_path / "12677-01-GA ISS 2.xlsx"))


# ── each side read, and checked against itself ─────────────────────────────────────────

def test_the_manual_price_chain_is_read_with_its_cells(tmp_path):
    side = pcmp.read_manual(manual_workbook(tmp_path / "m.xlsx"))
    c = side["chain"]
    assert c["material"] == {"value": MAN_MAT, "cell": "M17"}
    assert c["labour"]["value"] == MAN_LAB and c["unit"]["cell"] == "M26"
    assert c["rebate"]["value"] == 0.066 and c["rebate"]["cell"] == "D25"
    assert c["margin"]["value"] == 0.25 and c["margin"]["note"] == "entered as a percentage"
    assert c["sell"]["value"] == MAN_SELL
    assert side["head"]["quantity"]["value"] == 10 and side["head"]["revision"]["value"] == "B"


def test_both_sides_are_checked_against_their_own_totals_first(detail):
    assert detail["manual"]["reconcile"]["balances"] is True
    assert detail["ai"]["reconcile"]["balances"] is True


# ── cost and selling price apart ───────────────────────────────────────────────────────

def test_the_cost_build_up_is_compared_line_by_line_with_cells(detail):
    rows = {r["key"]: r for r in detail["cost_build"]}
    assert list(rows) == ["material", "labour", "overheads", "rebate", "absorption", "unit"]
    assert rows["material"]["manual"] == MAN_MAT and rows["material"]["ai"] == AI_MAT
    assert rows["material"]["delta"] == round(AI_MAT - MAN_MAT, 2)
    assert rows["material"]["manual_cell"] == "M17"
    assert rows["unit"]["manual_cell"] == "M26"
    assert rows["rebate"]["status"] == "match" and rows["absorption"]["status"] == "match"
    assert rows["overheads"]["manual"] == round(MAN_UNIT - MAN_MAT - MAN_LAB, 2)


def test_cost_is_never_compared_with_a_selling_price(detail):
    cost_keys = {r["key"] for r in detail["cost_build"]}
    sell_keys = {r["key"] for r in detail["selling"]}
    assert cost_keys.isdisjoint(sell_keys)
    sell = next(r for r in detail["selling"] if r["key"] == "sell")
    assert sell["manual"] == MAN_SELL and sell["ai"] == AI_UNIT
    margin = next(r for r in detail["selling"] if r["key"] == "margin")
    assert margin["manual"] == 0.25 and margin["ai"] == 0.0
    assert "estimator to set" in margin["note"]


# ── commercial lines ───────────────────────────────────────────────────────────────────

def test_delivery_packaging_and_installation_are_paired_by_kind(detail):
    cats = {c["category"]: c for c in detail["commercial"]["categories"]}
    assert cats["delivery"]["manual"] == 40.0 and cats["delivery"]["ai"] == 42.5
    assert cats["packaging"]["manual"] == 5.0 and cats["packaging"]["ai"] == 27.5
    assert cats["installation"]["presence"] == "manual only"
    assert cats["installation"]["manual_lines"][0]["where"] == "labour"


def test_every_manual_commercial_line_has_a_counterpart_or_says_it_has_none(detail):
    manual_lines = [x for x in detail["commercial"]["lines"] if x["side"] == "manual"]
    assert {x["description"] for x in manual_lines} == {"Delivery to store", "Pallet and wrap",
                                                        "Install on site"}
    install = next(x for x in manual_lines if x["category"] == "installation")
    assert install["note"] == "not in the AI estimate" and install["cell"] == "M22"
    delivery = next(x for x in manual_lines if x["category"] == "delivery")
    assert delivery["counterpart"][0]["cell"] == "M13"


def test_a_fabricated_part_is_never_taken_for_a_commercial_line(tmp_path):
    side = {"blocks": {"bom": [], "tube": [{"code": "BOX-1", "description": "40x40 box section",
                                            "total_value_gbp": 5.0}], "steel": [], "other_sheet": []},
            "labour_rows": []}
    assert pcmp.commercial_lines(side, side)["categories"] == []


# ── scope, part by part ────────────────────────────────────────────────────────────────

def test_parts_on_one_side_only_are_listed(detail):
    parts = {p["code"]: p for p in detail["scope"]["parts"]}
    assert parts["12677-01-09"]["only_on"] == "AI"
    assert parts["12677-01-03"]["only_on"] == "manual"
    assert "DELIVERY" not in parts and "PACK-01" not in parts, "commercial lines are not parts"


def test_made_on_one_side_and_bought_on_the_other_is_flagged(detail):
    p = next(p for p in detail["scope"]["parts"] if p["code"] == "12677-01-05")
    assert p["made_bought_differs"] is True
    assert (p["manual"]["kind"], p["ai"]["kind"]) == ("bought", "made")


def test_a_part_worked_but_not_charged_material_is_flagged(detail):
    """SCRUM-155: the frame was welded on the AI estimate and its material never charged."""
    p = next(p for p in detail["scope"]["parts"] if p["code"] == "12677-01-03")
    assert p["material_not_charged_on"] == "AI"
    assert p["ai"]["labour_gbp"] == 6.0 and p["manual"]["gbp"] == 8.0


def test_quantity_per_unit_and_the_inputs_behind_a_difference_are_shown(detail):
    parts = {p["code"]: p for p in detail["scope"]["parts"]}
    assert parts["12677-01-02"]["qty_differs"] is True
    assert parts["12677-01-01"]["inputs"] == [{"field": "blank length", "manual": 1250.0, "ai": 1260.0}]
    assert parts["12677-01-01"]["manual"]["cells"] == ["M14"]
    assert parts["12677-01-01"]["ai"]["cells"] == ["M60"]
    agreed = parts["BI-SCREW"]
    assert agreed["flagged"] is False and agreed["status"] == "match"


# ── quantities and revisions ───────────────────────────────────────────────────────────

def test_the_same_quantity_is_compared_as_it_stands(detail):
    assert detail["quantity"]["comparable"] is True and detail["quantity"]["compared_at"] == 10


def test_a_different_quantity_is_compared_from_the_runs_sweep(tmp_path):
    d = pcmp.compare(ai_summary(tmp_path / "a.json", qty=5, sweep={5: 300.0, 10: MAN_UNIT + 2}),
                     manual_workbook(tmp_path / "m.xlsx", qty=10))
    unit = next(r for r in d["cost_build"] if r["key"] == "unit")
    assert unit["ai"] == round(MAN_UNIT + 2, 2) and unit["note"] == "AI at 10 off from its quantity sweep"
    assert d["headline"]["compared_at_qty"] == 10


def test_a_quantity_the_run_did_not_price_is_not_like_for_like(tmp_path):
    d = pcmp.compare(ai_summary(tmp_path / "a.json", qty=5),
                     manual_workbook(tmp_path / "m.xlsx", qty=10))
    assert d["quantity"]["comparable"] is False
    assert d["headline"]["status"] == "quantities differ"
    assert "quantities differ" in next(r for r in d["cost_build"] if r["key"] == "material")["note"]
    assert next(r for r in d["selling"] if r["key"] == "sell")["status"] == "quantities differ"


def test_the_sell_price_follows_the_same_quantity_as_the_unit_cost(tmp_path):
    """The AI sell price at the manual's quantity is its swept unit cost over its own margin;
    its sell price at the run's own quantity is never set against the manual's."""
    d = pcmp.compare(ai_summary(tmp_path / "a.json", qty=50, sweep={10: 150.0, 50: 90.0}),
                     manual_workbook(tmp_path / "m.xlsx", qty=10))
    sell = next(r for r in d["selling"] if r["key"] == "sell")
    assert sell["ai"] == 150.0 and sell["manual"] == MAN_SELL      # the AI margin here is 0
    assert sell["note"].startswith("AI at 10 off")
    assert d["headline"]["ai_sell_gbp"] == 150.0
    assert "Sell price at 10 off" in pcmp.render_html(d)


def test_a_different_revision_is_flagged(detail, tmp_path):
    assert detail["revision"]["differs"] is True
    assert (detail["revision"]["manual"], detail["revision"]["ai"]) == ("B", "C")
    same = pcmp.compare(ai_summary(tmp_path / "a.json", revision="Rev B"),
                        manual_workbook(tmp_path / "m.xlsx", rev="B"))
    assert same["revision"]["differs"] is False


# ── the differences and the page ───────────────────────────────────────────────────────

def test_the_structural_differences_lead_and_each_points_at_its_line(detail):
    first = detail["differences"][0]
    assert first["kind"] == "scope" and first.get("structural")
    anchors = {d["anchor"] for d in detail["differences"]}
    assert "part-12677-01-03" in anchors and "commercial-installation" in anchors


def test_the_page_drills_down_from_each_difference_to_its_line(detail):
    page = pcmp.render_html(detail, "12677-01-GA")
    for d in detail["differences"]:
        assert f"href='#{d['anchor']}'" in page
        assert f"id='{d['anchor']}'" in page
    assert "not automatically the right answer" in " ".join(page.split())
    assert "material not charged on the AI estimate" in page
    assert "not in the AI estimate" in page


def test_differences_are_described_not_judged(detail):
    page = pcmp.render_html(detail, "x")
    assert ">differs<" in page or ">close<" in page
    assert ">fail<" not in page and "error" not in page.lower().replace("excel errors", "")


def test_the_command_line_writes_both_files(tmp_path, capsys):
    ai = ai_summary(tmp_path / "12677.json")
    man = manual_workbook(tmp_path / "m.xlsx")
    assert pcmp.main(["--ai", str(ai), "--manual", str(man), "--out-dir", str(tmp_path / "out")]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["detail_html"].endswith("12677.parity.html") and Path(out["detail_json"]).is_file()
