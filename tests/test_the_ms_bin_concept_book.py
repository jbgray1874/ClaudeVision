"""M&S clothing-bin concept run (PNG render), 30 Sep 2026 09:38, engine 60a7421.

D-352  18 mm MFMDF noted "GBP 14.00 a square metre, researched" and charged GBP 105.63 a
       2800 x 2070 sheet: the MDF per-kg config rate (1.35 x 750 kg/m3), GBP 18.22 a m2.
D-353  "CNC Joinery … each: CPT01 7/hr …" on a row charging the department's 12/hr.
D-354  Packing and delivery read their placeholder while the 1-off break was empty, even with
       the 350-off break filled.
D-355  Four castors priced at £44 were called "material costs NOTHING … UNDER-CHARGED".
D-356  The banner said "5 market figures" beside 7 failing checks and four sizes read off a picture.
D-357  11:00 re-run: the lid hinge's AI £3.25 read "SDI Live" and sat beside "NOT PRICED — refused".
D-358  Its provenance record still named a config default; and the render-only BOM checks read
       as though a drawing had been misread.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as E  # noqa: E402


def test_the_researched_rate_prices_the_whole_sheet():
    # CPT01 header panel 620 x 380: 0.2356 m2 x GBP 14.00 = GBP 3.2984
    se = {"candidate_sheet_size_mm": [2800, 2070], "parts_per_sheet": 20}
    t = E._researched_sheet_terms({"price_gbp": 3.2984}, 0.2356, se)
    assert t["researched_rate_gbp_per_m2"] == 14.0
    assert t["sheet_price_gbp"] == round(14.0 * 2.8 * 2.07, 2) == 81.14
    assert t["parts_per_sheet"] == 20


def test_unreadable_terms_leave_the_old_path():
    assert E._researched_sheet_terms({"price_gbp": 3.3}, 0, {}) == {}
    assert E._researched_sheet_terms({}, 0.2, {"candidate_sheet_size_mm": [2800, 2070]}) == {}


def test_both_researched_board_branches_carry_the_sheet_terms():
    src = open(os.path.join(ROOT, "src", "estimator.py"), encoding="utf-8").read()
    assert src.count("**_researched_sheet_terms(") == 2


def test_a_grouped_row_says_which_rate_it_charges():
    src = open(os.path.join(ROOT, "src", "wb_populate.py"), encoding="utf-8").read()
    assert '(engine estimate; "' in src and 'f"charged at {throughput:g}/hr)"' in src


def test_the_break_the_order_falls_in_decides_not_the_one_off():
    import wb_populate as W
    f = W.break_or_fallback_formula("Material Price Break", 8, 14.86)
    assert "INDEX('Material Price Break'!D8:N8,MATCH($D$6,'Material Price Break'!$D$4:$N$4,1))" in f
    assert f.endswith("LOOKUP($D$6,'Material Price Break'!$D$4:$N$4,'Material Price Break'!D8:N8))")
    assert W._ours_by_shape(f)


def test_a_bought_castor_is_not_a_free_material():
    import invariants as inv
    castor = {"part_number": "CPT07", "description": "CASTOR", "normalized_material": "NYLON",
              "material_estimate": {}, "quantity": 4,
              "cost_breakdown": {"system_cost": {"unit_cost_gbp": 11.0,
                                                 "applied_to_total": True}}}
    out = inv.check_a_material_we_cannot_price_is_declared(
        {"estimate_summary": {"part_estimates": [castor]}, "parts": [castor]})
    assert not any(v.get("code") == "material_has_no_rate_in_this_engine" for v in out)


def test_the_banner_names_assumed_sizes_and_failing_checks():
    import costed_facts as cf
    job = {"decisions_required": [{"kind": "market_figure", "part": "CASTOR",
                                   "gbp_at_stake": 45.76}],
           "release": {"status": "provisional", "blocking_checks": 7, "sizes_assumed": 4}}
    ph = cf.outstanding_summary(job)["phrase"]
    assert "1 market figure to replace" in ph
    assert "4 sizes assumed from a render" in ph and "7 consistency checks failing" in ph


def test_render_sizes_are_counted_once_per_part():
    import costed_facts as cf
    flag = "CONCEPT: size assumed from the render — confirm 620 x 380 x 18mm before release"
    src = {"estimate_summary": {"part_estimates": [
        {"part_number": "CPT01", "review_flags": [flag]},
        {"part_number": "CPT03", "review_flags": [flag.replace("620", "780")]}]},
        "parts": [{"part_number": "CPT01", "review_flags": [flag]}]}
    assert cf._sizes_assumed_from_a_render(src) == 2


def test_a_rescued_line_is_labelled_by_the_rescue_and_loses_its_refusal():
    import wb_populate as W
    hinge = {"part_number": "CPT06", "description": "LID HINGE", "quantity": 1,
             "material_estimate": {},
             "review_flags": ["CPT06: NOT PRICED — the market research answered £3.50 but "
                              "named makers, not sellers", "sighted as 'metal hinge'"]}
    n = E.apply_last_resort_prices([hinge], lambda pe: 3.25)
    assert n == 1
    assert not any("NOT PRICED —" in f for f in hinge["review_flags"])
    assert "sighted as 'metal hinge'" in hinge["review_flags"]
    # a stale stamp from the failed chain no longer names the supplier
    hinge["cost_breakdown"] = {"system_cost": {"source_name": "config_default_material_rates",
                                               "applied": True, "affects_total": True}}
    label, _ = W._price_origin(hinge)
    assert label == "AI ESTIMATE - INDICATIVE"


def test_the_rescue_writes_its_own_price_source():
    import wb_populate as W
    hinge = {"part_number": "CPT06", "description": "LID HINGE", "quantity": 1,
             "material_estimate": {},
             "cost_breakdown": {"system_cost": {"source_name": "config_default_material_rates",
                                                "applied": True, "affects_total": True}}}

    def look(pe):
        pe["_last_resort_result"] = {"selected": {
            "source": "web_ai_fallback", "price": 3.25,
            "metadata": {"pricing_mode": "llm_market_estimate", "llm_provider": "xai"}}}
        return 3.25
    E.apply_last_resort_prices([hinge], look)
    st = hinge["material_estimate"]["price_source"]
    assert st["source_class"] == "ai_estimate" and st["source_name"] != \
        "config_default_material_rates"
    assert "_last_resort_result" not in hinge
    assert W._price_origin(hinge)[0].endswith("INDICATIVE")


def test_a_rescue_with_no_recorded_answer_is_still_a_market_indication():
    part = {"part_number": "X", "description": "CASTOR", "quantity": 4, "material_estimate": {}}
    E.apply_last_resort_prices([part], lambda pe: 11.0)
    assert part["material_estimate"]["price_source"]["source_class"] == "ai_estimate"


def _render(**extra):
    return dict({"source_format": "image_render"}, **extra)


def test_a_render_run_says_its_parts_are_concept_assumptions_and_still_blocks():
    import invariants as inv
    s = _render(document_analysis={"bom_rows": [], "bom_readers_unread": [
        {"scope": "job", "path": "A", "detail": "disabled by --llm-only"}]})
    out = inv.check_both_bom_readers_ran(s)
    assert out and out[0]["severity"] == inv.BLOCKING
    assert "customer render" in out[0]["message"] and "concept assumptions" in out[0]["message"]


def test_a_drawing_run_keeps_the_old_words():
    import invariants as inv
    s = {"document_analysis": {"bom_rows": [], "bom_readers_unread": [
        {"scope": "job", "path": "A", "detail": "x"}]}}
    assert "read once, not twice" in inv.check_both_bom_readers_ran(s)[0]["message"]


def test_a_sighted_part_is_owned_by_a_concept_assumption_not_a_phantom():
    import invariants as inv
    s = _render(canonical_route_shadow={"mode": "cutover", "decisions": [], "issues": [
        {"code": "bom_node_disconnected", "part_number": "CPT07", "kind": "leaf",
         "description": "CASTOR", "in_raw_records": True, "in_extract": False}]})
    out = [v for v in inv.check_canonical_route_shadow(s)
           if v["code"] == "canonical_route_bom_node_disconnected"]
    assert out and out[0]["severity"] == inv.BLOCKING
    assert "sighted on the customer's render" in out[0]["message"]
    assert "invented downstream" not in out[0]["message"]
