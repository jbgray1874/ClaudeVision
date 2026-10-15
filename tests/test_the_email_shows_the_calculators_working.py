"""AI Estimator Calculator Inputs — the covering e-mail shows each calculator's working (D-538).

James Gray, 15 Oct 2026: "can we change the HTML e-mail explains to have a new section at the
bottom called AI Estimator Calculator Inputs. this will be a new series of improvements. the
first is the boxing work we did. so we show the full details of the calculation for the job
so estimating can check it."

The box calculator's own worked example (88 x 38 x 1955 on BC 150KT at 120 off) is the fixture:
the section must carry the inputs, each pair's cut size and nest (680 / 40 / 24 a sheet), the
running and set-up steps, the formula charged and the order total — the figures price_box
produced, never re-priced.
"""
import html as _html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimate_explained as ee  # noqa: E402
from commercial_lines import _box_method_price  # noqa: E402


def _order(**over):
    o = {"order_quantity": 120,
         "counted_parts": [{"part_number": "X1", "length_mm": 88, "width_mm": 38,
                            "thickness_mm": 1955, "per_assembly": 1}],
         "left_out_parts": []}
    o.update(over)
    return o


def _text(html):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def test_the_box_line_carries_its_inputs_and_every_step(monkeypatch):
    import config
    monkeypatch.setitem(config.BOX_COSTING, "enabled", True)
    monkeypatch.setitem(config.BOX_COSTING, "formula", "sheet")
    r = _box_method_price(_order())
    ci = r["calculator_inputs"]
    assert ci["calculator"] == "box" and ci["box_mm"] == [88, 38, 1955]
    assert ci["inputs"]["sheet_cost_gbp"] == 8.0 and ci["inputs"]["stock_board"] == "BC 150KT"
    assert [p["per_sheet"] for p in ci["panels"]] == [680, 40, 24]
    assert all(p["across"] * p["along"] == p["per_sheet"] for p in ci["panels"])
    assert ci["formula"] == "sheet" and ci["pairs_charged"] == 2
    assert abs(ci["per_carton_gbp"] - 1.822) < 2e-3
    assert ci["order_gbp"] == r["order_gbp"]


def test_the_section_shows_the_working_at_the_bottom_of_the_email(monkeypatch):
    import config
    monkeypatch.setitem(config.BOX_COSTING, "enabled", True)
    monkeypatch.setitem(config.BOX_COSTING, "formula", "sheet")
    r = _box_method_price(_order())
    line = {"code": "PACKAGING", "calculator_inputs": [r["calculator_inputs"]]}
    html = ee.calculator_inputs_html([line, {"code": "DELIVERY"}])
    t = _text(html)
    assert t.startswith("AI Estimator Calculator Inputs")
    assert "Box calculator — packaging · the PACKAGING line" in t
    for want in ("88 x 38 x 1955 mm", "BC 150KT", "2300 x 3200 mm", "£8.00", "50%",
                 "20 mm", "£55.00",
                 "INT((3200 - 5) / (58 + 20)) = 40", "INT(2300 / (108 + 20)) = 17",
                 "680 a sheet", "40 a sheet", "24 a sheet",
                 "no — not in the sheet's total",
                 "(88 + 38 + 1955) x £0.00035 = £0.7283",
                 "£55.00 / 120 carton(s) = £0.4583",
                 "config BOX_COSTING['formula'] = 'sheet'"):
        assert want in t, want
    assert f"x 120 = £{r['order_gbp']:,.2f}" in t


def test_no_calculator_no_section():
    assert ee.calculator_inputs_html([{"code": "PACKAGING", "packing_working": "x"}]) == ""
    assert ee.calculator_inputs_html(None) == ""


def test_the_covering_email_places_it_before_the_footer():
    src = (ROOT / "src" / "estimate_explained.py").read_text(encoding="utf-8")
    body = src[src.index("def covering_email("):]
    assert body.index("calculator_inputs_html(_commercial)") < body.index("Produced by SDI")
