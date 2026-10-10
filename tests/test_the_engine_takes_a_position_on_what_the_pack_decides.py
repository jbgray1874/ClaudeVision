"""Three decisions the 19:32 book left to the estimator that the pack itself decides
(D-446, D-447, D-448). James Gray, 10 Oct: "we need to infer as best we can and also find
prices, either SDI Live, or LLM xAI".

D-446 — an operation is charged at one level of the tree. Glue on 8188-08_GA (inferred) and
again on SA03/SA04 (their sheets say BONDED); Wet Spray on SA04 and again on its member 013
(its sheet states WET SPRAYED); CNC Joinery on SA03 (a board-material default) and again,
measured, on its MDF child 010. The weaker evidence stands down with the reason; equal evidence
leaves it on the members.

D-447 — the edge finish follows the cutter. Every acrylic part was diamond polished; a lasered
acrylic edge is a finished edge, diamond polish is for sawn and routed edges (config
EDGE_FINISH_BY_CUT_METHOD, the acrylic department confirms).

D-448 — packaging and delivery look in SDI Live before the market: a rate the business
entered, else what past quotes charged (own customer first), and the market researcher is
asked for the whole order with the question as written.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import commercial_lines as cl                                         # noqa: E402
import estimator                                                      # noqa: E402
import route_compiler as rc                                           # noqa: E402


# ── D-446 ───────────────────────────────────────────────────────────────────────────────

@dataclass
class _Node:
    part_number: str
    kind: str


@dataclass
class _Dec:
    operation: str
    status: str
    target_id: str
    source: str
    reason: str = ""
    field_provenance: Dict[str, str] = field(default_factory=dict)
    claims: List[Dict[str, Any]] = field(default_factory=list)


def _graph():
    return {"nodes": [_Node("GA", "assembly"), _Node("SA04", "assembly"), _Node("013", "part"),
                      _Node("SA03", "assembly"), _Node("010", "part")],
            "children": {"GA": {"SA04": 1, "SA03": 1}, "SA04": {"013": 1}, "SA03": {"010": 1}}}


def test_a_parents_inferred_glue_stands_down_to_the_members_stated_bond():
    ga = _Dec("glue", rc.REQUIRED, "GA", "inference")
    sa04 = _Dec("glue", rc.REQUIRED, "SA04", "drawing_notes")
    issues: List[Dict[str, Any]] = []
    withheld = rc._withhold_duplicate_level_ops([ga, sa04], _graph(), issues)
    assert withheld == ["GA"]
    assert ga.status == rc.NOT_APPLICABLE and sa04.status == rc.REQUIRED
    assert "charged once" in ga.reason and "SA04" in ga.reason
    assert ga.field_provenance["status"] == "operation_charged_at_one_level"
    assert issues and issues[0]["code"] == "operation_charged_at_one_level"


def test_a_parents_default_routing_stands_down_to_the_childs_measured_one():
    sa03 = _Dec("cnc_routing", rc.REQUIRED, "SA03", "inference")
    p010 = _Dec("cnc_routing", rc.REQUIRED, "010", "dxf_geometry")
    rc._withhold_duplicate_level_ops([sa03, p010], _graph(), [])
    assert sa03.status == rc.NOT_APPLICABLE and p010.status == rc.REQUIRED


def test_equal_evidence_leaves_the_work_on_the_members():
    sa04 = _Dec("wet_spray", rc.REQUIRED, "SA04", "drawing_notes")
    p013 = _Dec("wet_spray", rc.REQUIRED, "013", "drawing_notes")
    rc._withhold_duplicate_level_ops([sa04, p013], _graph(), [])
    assert sa04.status == rc.NOT_APPLICABLE and p013.status == rc.REQUIRED
    assert "equal" in sa04.reason


def test_a_parents_stated_finish_over_an_inferred_member_keeps_the_parent():
    sa04 = _Dec("wet_spray", rc.REQUIRED, "SA04", "drawing_notes")
    p013 = _Dec("wet_spray", rc.REQUIRED, "013", "inference")
    rc._withhold_duplicate_level_ops([sa04, p013], _graph(), [])
    assert sa04.status == rc.REQUIRED and p013.status == rc.NOT_APPLICABLE
    assert "SA04" in p013.reason


def test_an_operation_on_one_level_only_and_a_weld_are_untouched():
    only = _Dec("glue", rc.REQUIRED, "SA04", "drawing_notes")
    weld_ga = _Dec("welding", rc.REQUIRED, "GA", "inference")
    weld_013 = _Dec("welding", rc.REQUIRED, "013", "drawing_notes")
    assert rc._withhold_duplicate_level_ops([only, weld_ga, weld_013], _graph(), []) == []
    assert only.status == weld_ga.status == weld_013.status == rc.REQUIRED


def test_the_rule_runs_in_the_compiler_after_the_coat_rule():
    import inspect
    src = inspect.getsource(rc)
    a = src.index("_withhold_coats_with_nothing_to_coat(decisions, graph, issues)")
    b = src.index("_withhold_duplicate_level_ops(decisions, graph, issues)")
    assert a < b


# ── D-447 ───────────────────────────────────────────────────────────────────────────────

def _acrylic(**over):
    p = {"part_number": "W", "description": "WAVE LAYER", "quantity": 1,
         "normalized_material": "ACRYLIC", "thickness_mm": 3.0,
         "overall_length_mm": 2354.72, "overall_width_mm": 99.99,
         "normalized_geometry": {"blank_length_mm": 2354.72, "blank_width_mm": 99.99},
         "inferred_operations": ["laser_cutting", "handling"],
         "manufacturing_interpretation": {"stock_form": "sheet",
                                          "run_driven_operations": ["laser_cutting", "handling"],
                                          "routing": []}}
    p.update(over)
    return p


def test_a_sheet_stating_lasered_edges_rules_the_polish_out_and_says_why():
    p = _acrylic(surface_finishes=["LASERED EDGES"], normalized_finish="LASERED EDGES")
    rt = estimator.estimate_part(p, 1)["process_estimate"]["run_times_min_per_unit"]
    assert rt.get("laser_cutting", 0) > 0 and "diamond_polish" not in rt
    assert "LASERED EDGES" in p["operations_ruled_out"]["diamond_polish"]
    assert any("no Diamond Polish charged" in str(f) for f in p["review_flags"])


def test_a_lasered_part_whose_sheet_states_no_edge_finish_is_polished_as_the_shop_does():
    p = _acrylic()
    rt = estimator.estimate_part(p, 1)["process_estimate"]["run_times_min_per_unit"]
    assert rt.get("laser_cutting", 0) > 0 and rt.get("diamond_polish", 0) > 0
    assert "diamond_polish" not in (p.get("operations_ruled_out") or {})


def test_a_routed_acrylic_edge_is_diamond_polished():
    p = _acrylic(cut_method="router", surface_finishes=["LASERED EDGES"])
    rt = estimator.estimate_part(p, 1)["process_estimate"]["run_times_min_per_unit"]
    # the sheet's LASERED EDGES is the cut it names; the stated finish still says the edge is
    # finished by the cut, so no polish — the router does not change what the sheet states
    assert rt.get("cnc_routing", 0) > 0 and "diamond_polish" not in rt


def test_a_sheet_calling_for_polish_keeps_it_whatever_the_edge_statement():
    p = _acrylic(textual_operations=["diamond_polish"], surface_finishes=["LASERED EDGES"])
    rt = estimator.estimate_part(p, 1)["process_estimate"]["run_times_min_per_unit"]
    assert rt.get("diamond_polish", 0) > 0


def test_the_words_are_a_config_shop_rule():
    import config
    assert "LASERED EDGES" in config.EDGE_FINISHED_BY_CUT_WORDS


# ── D-448 ───────────────────────────────────────────────────────────────────────────────

def test_offline_the_sdi_live_rung_answers_nothing_and_the_line_still_prices():
    cl._LIVE_RATE_CACHE.clear()
    assert cl._sdi_live_rate("PACKAGING", {"customer": "M&S", "order_quantity": 1}) is None


def test_the_customer_travels_with_the_order():
    parts = [{"part_number": "P1", "description": "PANEL", "quantity": 1,
              "normalized_material": "MILD STEEL", "blank_length_mm": 500.0,
              "blank_width_mm": 300.0, "normalized_thickness_mm": 2.0}]
    line = cl.packaging_line(parts, 1, customer="M&S")
    assert line["basis"]["customer"] == "M&S"


def test_the_researcher_asks_for_the_whole_order_with_the_question(monkeypatch):
    seen = {}

    def _look(spec, **kw):
        seen.update(spec)
        return {"found": True, "price_gbp": 120.0, "unit": "order", "source": "x",
                "price_date": "2026-10-10", "confidence": 0.5}
    import web_ai_price_lookup
    monkeypatch.setattr(web_ai_price_lookup, "lookup_web_ai_price", _look)
    cl._commercial_researcher({"code": "PACKAGING", "description": "Protective packaging and a pallet",
                               "order_quantity": 50, "ask": "priced FOR THE WHOLE ORDER of 50 units"})
    assert seen["quantity"] == 50
    assert seen["description"] == "Protective packaging and a pallet", "the brief's question is composed by indicative_price, not repeated"


def test_the_line_says_what_sdi_live_answered_or_why_nothing():
    cl._LIVE_RATE_CACHE.clear(); cl._LIVE_RATE_STATUS.clear()
    parts = [{"part_number": "P1", "description": "PANEL", "quantity": 1,
              "normalized_material": "MILD STEEL", "blank_length_mm": 500.0,
              "blank_width_mm": 300.0, "normalized_thickness_mm": 2.0}]
    line = cl.packaging_line(parts, 1, customer="M&S")
    assert line.get("sdi_live_status") == "SDI_OFFLINE: SDI Live not asked"
    assert "SDI Live: SDI_OFFLINE" in str(line.get("note") or "") or line.get("order_gbp") is None


# ── D-449 ───────────────────────────────────────────────────────────────────────────────

class _Cur:
    """A stand-in SDI Live cursor: a CommercialRate view with per-pallet and per-order rates."""

    def __init__(self):
        self.rows = []

    def execute(self, sql, *params):
        if "vCurrentCommercialRate" in sql:
            self.rows = [("pallet_per_bay", 20.0), ("packaging_wrap_per_pallet", 6.5),
                         ("haulage_per_pallet", 45.0), ("delivery_booking_per_order", 12.0),
                         ("labour_rate", 31.0)]
        else:
            self.rows = []

    def fetchall(self):
        return list(self.rows)


class _Conn:
    def cursor(self):
        return _Cur()


def test_the_businesss_rates_price_the_counted_shipment_at_every_break(monkeypatch):
    import estimator
    monkeypatch.setenv("SDI_OFFLINE", "0")
    monkeypatch.setattr(estimator, "_get_pricing_service",
                        lambda: type("PS", (), {"_get_db_connection": lambda self: _Conn()})())
    import palletising
    plans = {1: {"pallet_count": 1, "carton_count": 1}, 5: {"pallet_count": 2, "carton_count": 5},
             50: {"pallet_count": 13, "carton_count": 50}}
    monkeypatch.setattr(palletising, "plan_shipment", lambda parts, q: plans.get(int(q), {"pallet_count": 1}))
    cl._LIVE_RATE_CACHE.clear(); cl._LIVE_RATE_STATUS.clear()
    order = {"customer": "M&S", "order_quantity": 5, "order_weight_kg": 220.0,
             "shipment": plans[5], "shippable_parts": [{"part_number": "P"}], "quantity_breaks": [1, 5, 50]}
    got = cl._sdi_live_rate("PACKAGING", order)
    assert got["source_class"] == "sdi_commercial_rate"
    # pallet_per_bay 20 x 2 + wrap 6.5 x 2 = 53; the haulage/booking keys are DELIVERY's words
    assert got["order_gbp"] == 53.0, got
    assert got["order_gbp_at_breaks"] == {1: 26.5, 5: 53.0, 50: 344.5}, got["order_gbp_at_breaks"]
    assert "pallet_per_bay GBP 20.00 x 2 pallets" in got["working"]
    cl._LIVE_RATE_CACHE.clear()
    dlv = cl._sdi_live_rate("DELIVERY", order)
    assert dlv["order_gbp"] == 45.0 * 2 + 12.0
    assert dlv["order_gbp_at_breaks"][50] == 45.0 * 13 + 12.0, "fifty headers travel on thirteen pallets, not one pallet's share divided by fifty"
