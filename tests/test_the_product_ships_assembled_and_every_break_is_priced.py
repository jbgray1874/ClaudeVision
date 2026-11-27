"""The product ships assembled, every break the run asks for is priced, and a sub-assembly's
leaves carry its own count (D-550, D-551, D-552).

401918-01-GA, the 1200 rail, 20 Oct 2026 book: PACKAGING was one researched pallet at £95, and
the 150-off column divided that one pallet by 150 (63p a rail); the rail was packed as loose
parts because nothing said it ships assembled; and, read from the PDF alone, the two base frames'
members came out at 1 and 2 where the rail needs 2 and 4.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")


# ── D-550: the run's own breaks ───────────────────────────────────────────────

def test_the_runs_breaks_join_the_standard_ones(monkeypatch):
    from commercial_lines import break_quantities
    monkeypatch.setenv("SDI_QUANTITY_BREAKS", "150, 7,x")
    out = break_quantities(3, extra=[40])
    assert {1, 3, 7, 40, 150, 1000} <= set(out)
    assert out == sorted(out)


def test_a_variant_takes_the_order_figure_priced_at_its_own_quantity():
    from quantity_sweep import _reprice_freight

    class _Cell:
        def __init__(self, v=None):
            self.Value = v

    class _WS:
        def __init__(self):
            self.cells = {(3, 8): _Cell("PACKAGING"), (3, 10): _Cell(95.0)}

        def Cells(self, r, c):
            return self.cells.setdefault((r, c), _Cell())

    ws = _WS()
    out = _reprice_freight(ws, 5, 150, {"PACKAGING": 95.0}, {"PACKAGING": {150: 4800.0}})
    assert out == {"PACKAGING": 32.0}          # 150 boxes at £32, not one pallet over 150
    ws2 = _WS()
    assert _reprice_freight(ws2, 5, 150, {"PACKAGING": 95.0}, None) == {"PACKAGING": 0.63}


def test_main_hands_the_breaks_down():
    src = (Path(__file__).resolve().parents[1] / "src" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ["SDI_QUANTITY_BREAKS"]' in src
    assert "order_freight_at=_order_freight_at or None" in src


# ── D-551: the product ships assembled ────────────────────────────────────────

def _rail_parts():
    return [
        {"part_number": "401918-01-05M", "description": "BASE PANEL", "quantity": 1,
         "normalized_material": "MILD STEEL", "normalized_thickness_mm": 2.0,
         "blank_length_mm": 1154.0, "blank_width_mm": 497.2},
        {"part_number": "401918-01-08M", "description": "BRACKET", "quantity": 4,
         "normalized_material": "MILD STEEL", "normalized_thickness_mm": 3.0,
         "blank_length_mm": 250.0, "blank_width_mm": 44.1},
    ]


def test_the_models_top_assembly_envelope_is_the_products():
    from commercial_lines import product_envelope
    env = product_envelope({"solidworks_native": {"top_assembly": "401918-01-GA",
                                                   "top_assembly_bbox_mm": [1298.0, 1438.2, 450.0]}})
    assert (env["length"], env["width"], env["height"]) == (1438.2, 1298.0, 450.0)
    assert env["of"] == "401918-01-GA" and "bounding box" in env["source"]


def test_a_stated_overall_on_the_products_record_serves_without_a_model():
    from commercial_lines import product_envelope
    env = product_envelope({"declared_product": "401918-01-GA"},
                           [{"part_number": "401918-01-GA", "overall_size_mm": "1298 x 450 x 1438"},
                            {"part_number": "401918-01-05M", "overall_size_mm": "1154 x 450 x 27"}])
    assert (env["length"], env["width"], env["height"]) == (1438.0, 1298.0, 450.0)
    assert product_envelope({"declared_product": "401918-01-GA"}, _rail_parts()) is None


def test_with_an_envelope_the_order_is_one_pack_per_unit_by_policy(monkeypatch):
    import config
    from commercial_lines import describe_order
    monkeypatch.setattr(config, "PACKAGING_POLICY",
                        {"ships_assembled_default": True, "stated_by": "James Gray",
                         "stated_on": "20 Oct 2026"}, raising=False)
    env = {"length": 1438.0, "width": 1298.0, "height": 450.0,
           "source": "the SolidWorks top assembly's bounding box", "of": "401918-01-GA"}
    order = describe_order(_rail_parts(), 150, envelope=env)
    au = order.get("assembled_unit") or {}
    assert au.get("envelope_mm") == [1438.0, 1298.0, 450.0]
    assert "packing policy" in au.get("basis", "")
    plan = order.get("shipment") or {}
    assert plan.get("ships_assembled") is True
    assert plan.get("carton_count") == 150
    assert plan.get("carton_internal_mm") == [1438.0, 1298.0, 450.0]


def test_without_the_policy_an_unwelded_product_packs_loose(monkeypatch):
    import config
    from commercial_lines import describe_order
    monkeypatch.setattr(config, "PACKAGING_POLICY", {"ships_assembled_default": False},
                        raising=False)
    env = {"length": 1438.0, "width": 1298.0, "height": 450.0, "of": "401918-01-GA"}
    order = describe_order(_rail_parts(), 150, envelope=env)
    assert "assembled_unit" not in order


def test_the_box_is_priced_around_the_assembled_product_at_every_break(monkeypatch):
    import config
    import commercial_lines as cl
    monkeypatch.setattr(config, "PACKAGING_POLICY", {"ships_assembled_default": True},
                        raising=False)
    monkeypatch.setenv("SDI_QUANTITY_BREAKS", "150")
    env = {"length": 1438.0, "width": 1298.0, "height": 450.0,
           "source": "the SolidWorks top assembly's bounding box", "of": "401918-01-GA"}
    order = cl.describe_order(_rail_parts(), 1, envelope=env)
    box = cl._box_method_price(order)
    assert box and box.get("applied"), box
    assert box["calculator_inputs"]["applied"]["route"] == "assembled"
    at = box["order_gbp_at_breaks"]
    assert 150 in at and at[150] > at[1]            # 150 boxes cost more than one
    assert at[150] / 150 < at[1]                    # and less each: set-up spreads


def test_the_extract_keeps_the_top_assemblys_box():
    src = (Path(__file__).resolve().parents[1] / "src" / "source_connectors" / "solidworks.py"
           ).read_text(encoding="utf-8")
    assert 'job.meta["top_assembly_bbox_mm"]' in src
    fs = (Path(__file__).resolve().parents[1] / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert '"top_assembly_bbox_mm": _sw_job.meta.get("top_assembly_bbox_mm")' in fs


# ── D-552: a sub-assembly's leaves carry its own count ────────────────────────

def _rail_rows():
    def r(pn, parent, q):
        return {"part_number": pn, "source_pdf": parent, "bom_parent": parent, "quantity": q}
    return [
        r("401918-01-01M", "401918-01-GA", 1), r("401918-01-201", "401918-01-GA", 1),
        r("401918-01-301", "401918-01-GA", 1), r("401918-01-401", "401918-01-GA", 2),
        r("FIXING125", "401918-01-GA", 6),
        r("401918-01-03M", "401918-01-201", 1), r("401918-01-02M", "401918-01-201", 2),
        r("FIXING105", "401918-01-201", 2),
        r("401918-01-05M", "401918-01-301", 1), r("401918-01-06M", "401918-01-301", 4),
        r("401918-01-07M", "401918-01-401", 1), r("401918-01-08M", "401918-01-401", 2),
        r("FIXING105", "401918-01-401", 2),
        r("401918-01-03M-CL3", "401918-01-03M", 2),
    ]


def test_a_base_frame_used_twice_doubles_its_members():
    from bom_tree import resolve_effective_quantities
    eff = resolve_effective_quantities(_rail_rows())["effective"]
    assert eff["401918-01-07M"] == 2 and eff["401918-01-08M"] == 4
    assert eff["401918-01-05M"] == 1 and eff["401918-01-06M"] == 4
    assert eff["401918-01-02M"] == 2
    assert eff["401918-01-03M-CL3"] == 2            # 03M x1 under 201 x1
    assert eff["FIXING125"] == 6
    assert eff["FIXING105"] == 6                    # 2 under 201 (x1) + 2 under each 401 (x2)


def test_the_named_unit_still_counts_as_one():
    """One of the thing you ran (12349-02): the GA shows three of the named module and its
    leaves are per module, not per wall — unchanged by D-552."""
    from bom_tree import resolve_effective_quantities
    rows = [
        {"part_number": "12349-02-69-100", "source_pdf": "GA", "quantity": 3},
        {"part_number": "12349-02-69-03M", "source_pdf": "12349-02-69-100", "quantity": 2},
    ]
    eff = resolve_effective_quantities(rows, unit_assembly="12349-02-69-100")["effective"]
    assert eff["12349-02-69-03M"] == 2
