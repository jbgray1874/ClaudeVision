"""A price the engine finds for a purchased line reaches the sheet as that line's price.

12567-01-GA, the 13:14 book of 27 Sep 2026: nine bought-in lines carried a found figure —
MAGNET21's UDEF row at £0.35, eight P/P articles' market figures — and every cell was £0. The
first fix (D-289) made the estimator's candidate flag ask the make/buy authority, and an
end-to-end trace then showed the flag was never what priced the cell:

  * the workbook back-derived a bought-in's price as unit total less labour — the buy plus a
    fitting uplift less the handling already booked — and never read the applied figure;
  * a family code with no flag on its record compiled as a LEAF, whose branch reads material
    only, so its catalogue price was unreachable by construction;
  * the PricingService anchor path dropped the cache's reproducibility mark, so a held market
    figure still stamped as unrepeatable;
  * a record appended after estimate_document was never costed at all;
  * the settle note asserted a classification reason it had not checked.

D-293..D-297. Each test drives the real function with a record shaped like the one the book
carried, not a fixture invented to pass.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as est  # noqa: E402
import price_provenance as pp  # noqa: E402
import route_compiler as rc  # noqa: E402
import wb_populate as wb  # noqa: E402
from estimator_inputs import input_note_for_line  # noqa: E402


def _udef_result(code, price):
    return {"result": {"selected": {"source": "UDEF_PARTS_TABLE_FOR_ESTIMATING", "price": price,
                                    "unit": "each", "confidence": 0.9,
                                    "evidence": {}, "metadata": {}}},
            "applied_unit_cost": price, "matched_part_code": code}


MAGNET = {"part_number": "MAGNET21", "description": "NEODYMIUM BAR MAGNET 50x10x1.50mm - ADHESIVE BACKED",
          "quantity": 4, "page_roles": ["assembly"], "geometry_inferred": True,
          "normalized_material": "MILD_STEEL", "material_inherited_from": "document_level"}


# ── D-293: the sheet reads the applied buy price ──────────────────────────────────────────

def test_the_bom_column_takes_the_applied_buy_not_a_back_derivation():
    pe = {"part_number": "MAGNET21", "quantity": 4, "unit_total_cost_gbp": 1.39,
          "labour_estimate": {"costs_gbp": {"handling": 0.42}},
          "cost_breakdown": {"system_cost": {"unit_cost_gbp": 0.35, "applied_to_total": True,
                                             "source": {"schema": "price_source.v1", "applied": True}}}}
    price, chain = wb._bom_line_price_traced(pe)
    assert price == 0.35, (price, chain)
    assert any("applied_to_total=True -> taken" in s for s in chain)


def test_a_pressed_insert_cheaper_than_its_handling_is_still_priced():
    """buy £0.12, handling £0.42: the back-derivation went negative, the line read UNPRICED
    and the reconcile then flipped the stamp — the 13:14 sentence reproduced after D-289."""
    pe = {"part_number": "BI-PEMSTUD", "quantity": 4, "unit_total_cost_gbp": 0.12,
          "labour_estimate": {"costs_gbp": {"handling": 0.42}},
          "cost_breakdown": {"system_cost": {"unit_cost_gbp": 0.12, "applied_to_total": True,
                                             "source": {"applied": True}}}}
    assert wb._bom_line_price_traced(pe)[0] == 0.12


def test_a_leaf_still_never_reads_the_buy_and_a_refusal_still_refuses():
    leaf = {"part_number": "12567-02-04M", "_canonical_kind": "leaf", "quantity": 2,
            "cost_breakdown": {"system_cost": {"unit_cost_gbp": 9.73, "applied_to_total": True}}}
    assert wb._bom_line_price_traced(leaf)[0] is None
    refused = {"part_number": "11650-05-02M", "quantity": 2, "unit_cost_gbp": 9.73,
               "cost_breakdown": {"system_cost": {"unit_cost_gbp": 9.73, "applied_to_total": False,
                                                  "source": {"applied": True}}}}
    assert wb._bom_line_price_traced(refused)[0] is None


def test_estimate_part_writes_the_buy_where_the_material_is_read(monkeypatch):
    """End to end: the record the book carried, a UDEF hit, and the price the sheet reads."""
    monkeypatch.setattr(est, "_resolve_part_system_cost", lambda p: _udef_result("MAGNET21", 0.35))
    pe = est.estimate_part(dict(MAGNET), job_quantity=163)
    sc = pe["cost_breakdown"]["system_cost"]
    assert sc["applied_to_total"] is True and sc["unit_cost_gbp"] == 0.35
    me = pe["material_estimate"]
    assert me["unit_material_cost_gbp"] == 0.35 and me["cost_per_part_gbp"] == 0.35
    assert abs(me["extended_material_cost_gbp"] - 0.35 * 4) < 1e-6
    assert me["cost_method"] == "bought_in_unit_price"
    assert wb._bom_line_price_traced(pe)[0] == 0.35
    assert pp.stamp_affects_total(sc["source"])


def test_the_authority_does_not_promote_a_parent_or_a_conflict():
    """Review of D-289: a parent's money is its children's, and a make/buy conflict is flagged,
    not resolved by whichever rule ran last."""
    parent = {"part_number": "12567-02-301", "description": "DIFFUSER ASSEMBLY", "quantity": 1,
              "page_roles": ["bought_in"], "geometry_inferred": True,
              "assembly_children": ["12567-02-08X", "12567-02-11X"]}
    assert est._bought_in_candidate_for(parent, False, parent["description"]) is False
    conflict = dict(MAGNET, flat_pattern_detected=True, geometry_source="dxf",
                    dxf_measured_outline=True, is_bought_in=True)
    conflict.pop("geometry_inferred")
    # the old test: a measured flat with operations beyond handling is not a candidate
    assert est._bought_in_candidate_for(conflict, False, conflict["description"]) is False


def test_only_a_negative_fold_ruling_rewrites_the_flag():
    graph = {"decisions": [
        {"operation": "folding", "status": "unverified", "target_id": "A"},
        {"operation": "folding", "status": "ruled_out", "target_id": "B", "reason": "stated finish rules it out"}]}
    a = {"part_number": "A", "review_flags": ["3 fold(s) charged, counted by the drawing"]}
    b = {"part_number": "B", "review_flags": ["3 fold(s) charged, counted by the drawing"]}
    assert est._reword_folds_the_route_rules_off(graph, [a, b]) == 1
    assert a["review_flags"][0].startswith("3 fold(s) charged")
    assert b["review_flags"][0].startswith("3 fold(s) counted on this line and NOT charged")


# ── D-294: the graph asks the make/buy authority ──────────────────────────────────────────

def test_a_family_code_with_no_flag_compiles_as_bought_in():
    assert rc._bought_in_record(dict(MAGNET)) is True
    measured = dict(MAGNET, flat_pattern_detected=True, geometry_source="dxf",
                    dxf_measured_outline=True)
    assert rc._bought_in_record(measured) is False, "a measured flat of its own still means we cut it"


def test_a_record_less_class_coded_row_compiles_as_bought_in_not_leaf():
    parts = [{"part_number": "12567-02-GA", "description": "END HEADER"}]
    extract = {"top_assembly": {"part_number": "12567-02-GA"},
               "assemblies": [{"part_number": "12567-02-GA", "children": [
                   {"part_number": "P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM", "qty": 2}]}]}
    g = rc.build_part_graph(parts, extract)
    nodes = {n.part_number: n for n in g["nodes"]}
    assert nodes["P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM"].kind == "bought_in"


# ── D-295: the anchor path carries the cache's verdict ────────────────────────────────────

class _AnchorStub:
    def _select_anchor_price_source(self, part):
        return {"source": "web_ai_fallback", "source_type": "web_ai_fallback",
                "unit_price_gbp": 1.15, "confidence": 0.4, "review_flag": True,
                "review_reason": "indicative", "provenance": "Web/AI fallback",
                "supplier_name": "xAI Grok LLM - INDICATIVE", "item_priced": "JST Y splitter, one",
                "price_is_reproducible": True, "llm_provider": "xai"}


def test_a_cached_market_figure_from_the_anchor_path_stamps_reproducible(monkeypatch):
    monkeypatch.setattr(est, "_PRICING_SERVICE_SINGLETON", _AnchorStub())
    monkeypatch.setattr(est, "get_best_price", lambda req, **kw: {"selected": None, "candidates": [],
                                                                    "audit_trail": []})
    result = est._resolve_part_system_cost({"part_number": "P/P-JST-Y-SPLITTER",
                                            "description": "JST Y Splitter", "quantity": 3,
                                            "is_bought_in": True, "page_roles": ["bought_in"]})
    assert result["applied_unit_cost"] == 1.15
    stamp = est._build_price_source_metadata(result["result"], fallback_source="x", applied=True,
                                             affects_total=True)
    assert pp.stamp_source_class(stamp) == "ai_estimate"
    assert pp.stamp_is_reproducible(stamp) is True


# ── D-296: a record appended after the estimate is costed ─────────────────────────────────

def test_a_late_added_record_is_costed_in_place(monkeypatch):
    raw = {"part_number": "P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM",
           "description": "10x3mm EPDM CLOSED CELL TAPE, LENGTH: 1230mm", "quantity": 2,
           "page_roles": ["bought_in"], "is_bought_in": True, "printed_code": "P/P",
           "bom_parent": "12567-02-GA", "bom_parents": [{"parent": "12567-02-GA", "qty": 2}],
           "review_flags": ["Added from dual-path BOM table read"]}
    costed_already = {"part_number": "MAGNET21", "cost_breakdown": {"system_cost": {}}}
    summary = {"assumed_job_quantity": 163,
               "estimate_summary": {"part_estimates": [costed_already, raw]}}
    seen = {}

    def _fake_estimate_part(part, job_quantity=None):
        seen["qty"] = job_quantity
        return {"part_number": part["part_number"], "quantity": part.get("quantity"),
                "cost_breakdown": {"system_cost": {"unit_cost_gbp": 0.9, "applied_to_total": True}},
                "review_flags": ["priced from the market"]}
    monkeypatch.setattr(est, "estimate_part", _fake_estimate_part)
    assert est.cost_uncosted_bought_in_records(summary) == 1
    pes = summary["estimate_summary"]["part_estimates"]
    assert pes[0] is costed_already, "a record already costed is left alone"
    new = pes[1]
    assert seen["qty"] == 163
    assert new["cost_breakdown"]["system_cost"]["unit_cost_gbp"] == 0.9
    assert new["bom_parent"] == "12567-02-GA" and new["printed_code"] == "P/P"
    assert new["review_flags"] == ["Added from dual-path BOM table read", "priced from the market"]


# ── D-297: the note reads its reason off the record ───────────────────────────────────────

def _declined(**extra):
    part = {"part_number": "MAGNET21", "description": "NEODYMIUM BAR MAGNET", "quantity": 4,
            "page_roles": ["bought_in"], "is_bought_in": True,
            "cost_breakdown": {"system_cost": {"unit_cost_gbp": 0.35, "applied_to_total": False,
                                               "matched_part_code": "MAGNET21",
                                               "source": {"schema": "price_source.v1",
                                                          "source": "udef_sqlserver",
                                                          "applied": True}}}}
    part.update(extra)
    return part


def test_the_note_prints_the_sheets_own_reason_when_it_recorded_one():
    part = _declined()
    part["cost_breakdown"]["system_cost"]["source"]["withheld_reason"] = (
        "the sheet wrote no price on this line; the figure the record holds did not reach the total")
    note = input_note_for_line(part)["note"]
    assert "the sheet wrote no price on this line" in note
    assert "did not classify" not in note


def test_the_note_says_the_route_called_it_a_cut_part_when_it_did():
    note = input_note_for_line(_declined(_canonical_kind="leaf"))["note"]
    assert "compiled this part as one we cut" in note


def test_the_note_calls_a_refused_bought_in_an_engine_fault_not_a_classification():
    note = input_note_for_line(_declined())["note"]
    assert "engine fault to trace" in note
    assert "did not classify" not in note


def test_the_classification_sentence_survives_only_where_the_authority_agrees():
    part = _declined(part_number="12567-02-04M", description="MOUNTING FOOT", is_bought_in=False,
                     page_roles=["detail"])
    note = input_note_for_line(part)["note"]
    assert "did not classify this part as a bought-in" in note


# ── D-302: a late record honours the drawing's "supplied by others" note ──────────────────

def test_a_late_record_the_drawing_says_another_party_supplies_is_not_costed(monkeypatch):
    """15:33 book: the display and antenna, minted after estimate_document, were researched
    and charged while the router — same note, a record in time — stayed at £0."""
    display = {"part_number": 'BLUEFIN 49.1" LCD DISPLAY, 20-0129-0365',
               "description": 'BLUEFIN 49.1" LCD DISPLAY, 20-0129-0365', "quantity": 1,
               "page_roles": ["bought_in"], "is_bought_in": True}
    summary = {"assumed_job_quantity": 163,
               "pages": [{"pdfplumber_text": "NOTE 3. DISPLAY, ROUTER AND ANTENNA SUPPLIED AND "
                                             "FITTED BY PIXEL INSPIRATION UK."}],
               "estimate_summary": {"part_estimates": [display]}}
    monkeypatch.setattr(est, "_resolve_part_system_cost",
                        lambda p: (_ for _ in ()).throw(AssertionError("must not be priced")))
    assert est.cost_uncosted_bought_in_records(summary) == 1
    pe = summary["estimate_summary"]["part_estimates"][0]
    assert pe.get("supplied_by_third_party")
    assert (pe.get("unit_total_cost_gbp") or 0) == 0
    assert summary["third_party_supplied"][0]["item"]
