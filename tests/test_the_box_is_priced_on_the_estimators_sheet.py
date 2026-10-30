"""The box is priced on the estimators' own AI BOX CALCULATOR sheet (D-542).

James Gray, 15 Oct 2026: "can we change it ... so that it's reading from the s/sheet and using
the s/sheet for the calculation in case estimating tweak it ... we should make the file a .env
variable."

SDI_BOX_CALCULATOR_XLSX names the sheet. The fixture below is the sheet's own layout and
formulas, cell for cell (14 Oct 2026, tab BRPMA-2-STD3): the engine must read its figures, follow
a change saved into it, refuse a sheet laid out differently (falling back to config, said so),
charge the sheet's own TOTAL where Excel calculated it, and say all of that on the e-mail —
including how the figure reaches the Estimate workbook.
"""
import html as _html
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import box_calculator_sheet as bcs  # noqa: E402
import box_costing  # noqa: E402
import config  # noqa: E402
import estimate_explained as ee  # noqa: E402
from commercial_lines import _box_method_price  # noqa: E402

_NEST = ('=IF(B{r}>0,(INT(IF(D{r}=0,"",IF(D{r}>G{r},"",((G{r}-{trim})/(D{r}+({gap}*2))))))'
         '*INT(IF(C{r}=0,"",IF(C{r}>F{r},"",(F{r}/(C{r}+({gap}*2))))))),"0")')


def _sheet(path, *, sheet_cost=8, setup=55, rate=0.00035, over=20, scrap=0.5, j9=8,
           total="=E3+H3+K10", k10="=SUM(K7:K8)", length_label="Length"):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BRPMA-2-STD3"
    cells = {
        "H1": "Qty", "I1": "TOTAL", "A2": "Stock board", "B2": "Sheet Size", "C2": "Sheet Cost",
        "D2": "Set-up Cost", "E2": "Running Cost", "F2": length_label, "G2": 88, "H2": 120,
        "I2": total, "A3": "BC 150KT", "B3": "2300x3200", "C3": sheet_cost, "D3": setup,
        "E3": f"=SUM(G2+G3+G4)*{rate}", "F3": "Breadth", "G3": 38, "H3": "=D3/H2",
        "F4": "Height", "G4": 1955,
        "A7": "Length/Breadth", "B7": 2, "C7": f"=G2+{over}", "D7": f"=G3+{over}",
        "A8": "Height/Breadth", "B8": 2, "C8": f"=G4+{over}", "D8": "=D7",
        "A9": "Height/Length", "B9": 2, "C9": "=C8", "D9": "=C7",
        "J7": "=C3", "J8": "=C3", "J9": j9, "K10": k10,
    }
    for r in (7, 8, 9):
        cells.update({f"F{r}": 2300, f"G{r}": 3200, f"I{r}": scrap,
                      f"H{r}": _NEST.format(r=r, trim=5, gap=10),
                      f"K{r}": f'=(IF(B{r}=0,"0",SUM((J{r}/H{r})*(100%+I{r}))*B{r}))'})
    for k, v in cells.items():
        ws[k] = v
    wb.save(path)
    return str(path)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    bcs._READ_CACHE.clear()
    bcs._CALC_CACHE.clear()
    monkeypatch.setitem(config.BOX_COSTING, "enabled", True)
    monkeypatch.setitem(config.BOX_COSTING, "formula", "sheet")
    monkeypatch.setitem(config.BOX_CALCULATOR_SHEET, "use_excel", False)
    yield


def _use(monkeypatch, path):
    monkeypatch.setitem(config.BOX_CALCULATOR_SHEET, "path", path)


def _text(h):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def test_the_sheets_own_figures_are_read(tmp_path):
    r = bcs.read_sheet(_sheet(tmp_path / "AI BOX CALCULATOR.xlsx"))
    assert r["ok"] and r["engine_copy_ok"], r.get("problems")
    f = r["figures"]
    assert (f["sheet_cost_gbp"], f["setup_cost_gbp"], f["running_rate_gbp_per_mm"]) == (8, 55, 0.00035)
    assert (f["panel_oversize_mm"], f["nest_gap_mm"], f["sheet_edge_trim_mm"]) == (20, 10, 5)
    assert (f["sheet_length_mm"], f["sheet_width_mm"], f["scrap_fraction"]) == (2300, 3200, 0.5)
    assert f["stock_board"] == "BC 150KT" and r["pairs_in_total"] == 2
    # The ends pair's sheet cost is typed, not linked to C3 — said, not fixed.
    assert any(n.startswith("J9") and "=C3" in n for n in r["notes"]), r["notes"]


def test_with_no_sheet_named_the_config_figures_price_it_and_say_so(monkeypatch):
    _use(monkeypatch, None)
    r = box_costing.price_box(88, 38, 1955, 120)
    assert r["calculation_source"]["kind"] == "config"
    assert "SDI_BOX_CALCULATOR_XLSX is not set" in r["calculation_source"]["reason"]
    assert abs(r["sheet_total_gbp"] - 1.822) < 2e-3


def test_the_sheet_prices_it_and_a_change_saved_into_the_sheet_is_the_next_price(
        monkeypatch, tmp_path):
    path = _sheet(tmp_path / "calc.xlsx")
    _use(monkeypatch, path)
    r = box_costing.price_box(88, 38, 1955, 120)
    assert r["calculation_source"]["kind"] == "sheet_engine"
    assert abs(r["sheet_total_gbp"] - 1.822) < 2e-3            # the sheet's own I2 at 120 off
    # Estimating puts the sheet price up to £10 and saves it.
    bcs._READ_CACHE.clear()
    _sheet(tmp_path / "calc.xlsx", sheet_cost=10)
    os.utime(path, (os.path.getmtime(path) + 5,) * 2)
    r2 = box_costing.price_box(88, 38, 1955, 120)
    assert r2["inputs"]["sheet_cost_gbp"] == 10
    assert r2["sheet_total_gbp"] > r["sheet_total_gbp"]
    # Its TOTAL adding the ends too is followed.
    bcs._READ_CACHE.clear()
    _sheet(tmp_path / "calc.xlsx", k10="=SUM(K7:K9)")
    os.utime(path, (os.path.getmtime(path) + 10,) * 2)
    r3 = box_costing.price_box(88, 38, 1955, 120)
    assert abs(r3["sheet_total_gbp"] - r3["unit_gbp"]) < 1e-9


def test_a_sheet_laid_out_differently_is_refused_by_name_and_config_prices_it(
        monkeypatch, tmp_path):
    _use(monkeypatch, _sheet(tmp_path / "calc.xlsx", length_label="Width"))
    r = box_costing.price_box(88, 38, 1955, 120)
    src = r["calculation_source"]
    assert src["kind"] == "config"
    assert "F2 reads 'Width', expected 'Length'" in src["reason"]
    assert abs(r["sheet_total_gbp"] - 1.822) < 2e-3


def test_a_missing_file_is_said_not_guessed(monkeypatch, tmp_path):
    _use(monkeypatch, str(tmp_path / "nowhere.xlsx"))
    src = box_costing.price_box(88, 38, 1955, 120)["calculation_source"]
    assert src["kind"] == "config" and "not there" in src["reason"]


def test_where_excel_calculated_it_the_sheets_total_is_charged(monkeypatch, tmp_path):
    _use(monkeypatch, _sheet(tmp_path / "calc.xlsx"))

    def fake(read, L, B, H, qs):
        return {q: {"total": 2.5, "running": 0.7283, "setup_share": 55 / q,
                    "pairs": [{"per_sheet": 680, "cost": 0.0353},
                              {"per_sheet": 40, "cost": 0.6},
                              {"per_sheet": 24, "cost": 1.0}]} for q in qs}, ""
    monkeypatch.setattr(bcs, "calculate", fake)
    r = box_costing.price_box(88, 38, 1955, 120)
    src = r["calculation_source"]
    assert src["kind"] == "sheet_excel" and r["sheet_total_gbp"] == 2.5
    assert src["agrees"] is False and abs(src["engine_copy_gbp"] - 1.822) < 2e-3
    assert "calculated by the AI BOX CALCULATOR sheet itself" in r["basis"]


def _order():
    return {"order_quantity": 120,
            "counted_parts": [{"part_number": "X1", "length_mm": 88, "width_mm": 38,
                               "thickness_mm": 1955, "per_assembly": 1}],
            "left_out_parts": []}


def test_the_email_says_where_the_calculation_came_from_and_how_it_reaches_the_workbook(
        monkeypatch, tmp_path):
    _use(monkeypatch, _sheet(tmp_path / "AI BOX CALCULATOR.xlsx"))
    r = _box_method_price(_order())
    assert r["source_name"] == "box_calculator_sheet"
    t = _text(ee.calculator_inputs_html(
        [{"code": "PACKAGING", "calculator_inputs": [r["calculator_inputs"]]}]))
    for want in ("Where the calculation comes from.", "AI BOX CALCULATOR.xlsx",
                 "SDI_BOX_CALCULATOR_XLSX", "On the sheet itself.", "J9",
                 "How it reaches the estimate workbook.", "PACKAGING line",
                 "£218.64 / 120 units = £1.8220", "AI BOX CALCULATOR sheet",
                 "Material Price Break", "change it in the AI BOX CALCULATOR sheet named above"):
        assert want in t, want
    assert t.index("Where the calculation comes from.") < t.index("Step 1 —") \
        < t.index("How it reaches the estimate workbook.")


def test_the_supplier_column_names_the_sheet():
    import price_provenance
    assert price_provenance.source_system_label("box_calculator_sheet") == "AI BOX CALCULATOR sheet"
