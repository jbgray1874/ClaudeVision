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
    assert f"Box calculator — the PACKAGING line (£{r['order_gbp']:,.2f} for the order)" in t
    for want in ("88 x 38 x 1955 mm", "BC 150KT", "2300 x 3200 mm", "£8.00", "50%",
                 "20 mm", "£55.00",
                 "INT((3200 - 5) / (58 + 20)) = 40", "INT(2300 / (108 + 20)) = 17",
                 "680 panels a sheet", "40 panels a sheet", "24 panels a sheet",
                 "£8.00 / 680 x 1.5 x 2 = £0.0353",
                 "(not in the total charged — see step 6)",
                 "(88 + 38 + 1955) mm x £0.00035 = £0.7283 a carton",
                 "£55.00 / 120 cartons = £0.4583 a carton",
                 "£0.7283 + £0.4583 + £0.0353 + £0.6000 = £1.8220 a carton",
                 "BOX_COSTING"):
        assert want in t, want
    assert f"x 120 cartons = £{r['order_gbp']:,.2f} for the order" in t


def test_anyone_can_follow_it_step_by_step(monkeypatch):
    """D-539: written so an estimator who has never seen the sheet can follow every figure —
    what the calculator is, each step with its numbers, why the ends are left out (with the
    Harley's evidence), what it assumes and how to change it."""
    import config
    monkeypatch.setitem(config.BOX_COSTING, "enabled", True)
    monkeypatch.setitem(config.BOX_COSTING, "formula", "sheet")
    r = _box_method_price(_order())
    t = _text(ee.calculator_inputs_html(
        [{"code": "PACKAGING", "calculator_inputs": [r["calculator_inputs"]]}]))
    heads = ["What it is.", "How the sheet is applied to this drawing.", "The figures it uses."]
    heads += [f"Step {n} —" for n in range(1, 7)]
    heads += ["Why the ends are left out.", "Step 7 —", "At other quantities.",
              "What it assumes.", "How to check or change it."]
    at = [t.index(h) for h in heads]
    assert at == sorted(at), "the explanation reads in order"
    assert config.BOX_COSTING["formula_evidence"] in t
    assert "Adding the ends as well would make the carton £2.8220" in t
    # The quantity breaks are the same sum at each quantity, the job's own quantity among them.
    assert "120 £218.64 £1.8220" in t


def test_no_calculator_no_section():
    assert ee.calculator_inputs_html([{"code": "PACKAGING", "packing_working": "x"}]) == ""
    assert ee.calculator_inputs_html(None) == ""


def test_the_covering_email_places_it_before_the_footer():
    src = (ROOT / "src" / "estimate_explained.py").read_text(encoding="utf-8")
    body = src[src.index("def covering_email("):]
    assert body.index("calculator_inputs_html(_commercial)") < body.index("Produced by SDI")


def test_it_says_how_the_sheet_is_applied_to_the_drawing(monkeypatch):
    """D-540: the sheet needs a box size and a box count; the drawing gives neither directly.
    The e-mail says what was packed and why, which of the drawing's dimensions became the
    box's L, B and H, and how the cartons were counted — and says where the sheet's own
    figures are held (src/config.py, BOX_COSTING)."""
    import config
    monkeypatch.setitem(config.BOX_COSTING, "enabled", True)
    monkeypatch.setitem(config.BOX_COSTING, "formula", "sheet")
    r = _box_method_price(_order())
    ap = r["calculator_inputs"]["applied"]
    assert ap["route"] == "one_part"
    assert [d["box"] for d in ap["dims"]] == ["Length (L)", "Breadth (B)", "Height (H)"]
    assert [d["mm"] for d in ap["dims"]] == [88, 38, 1955]
    t = _text(ee.calculator_inputs_html(
        [{"code": "PACKAGING", "calculator_inputs": [r["calculator_inputs"]]}]))
    assert t.index("How the sheet is applied to this drawing.") < t.index("The figures it uses.")
    for want in ("The part X1", "Height (H) 1955 the part's thickness (its gauge)",
                 "one carton per unit ordered: 120 units = 120 cartons",
                 "src/config.py", "BOX_COSTING"):
        assert want in t, want


def test_an_assembled_product_is_boxed_by_its_drawn_body(monkeypatch):
    import config
    import box_costing
    from commercial_lines import _box_cartons_from_shipment
    monkeypatch.setitem(config.BOX_COSTING, "enabled", True)
    order = {"order_quantity": 1,
             "assembled_unit": {"part_number": "U1", "envelope_mm": [700, 475, 1723],
                                "envelope_source": "the drawing's body dimensions",
                                "basis": "a welded unit, which cannot be flat-packed"},
             "shipment": {"carton_count": 1, "carton_internal_mm": [700, 475, 1723],
                          "ships_assembled": True, "packing_factor": 0.8}}
    r = _box_cartons_from_shipment(order, 1, box_costing, config.BOX_COSTING)
    t = _text(ee.calculator_inputs_html(
        [{"code": "PACKAGING", "calculator_inputs": [r["calculator_inputs"]]}]))
    for want in ("The assembled product U1", "a welded unit, which cannot be flat-packed, so it "
                 "ships assembled",
                 "Length (L) 700 the longer side of the product's footprint",
                 "Height (H) 1723 the product's overall height — the drawing's body dimensions",
                 "1 unit = 1 carton"):
        assert want in t, want
