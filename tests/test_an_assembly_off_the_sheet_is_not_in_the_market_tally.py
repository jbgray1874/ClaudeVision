"""12567-01's 17:45 report: £412.09 of market figures to replace, £31 of it the AI's own figures
for the end-header lighting assemblies 12567-02-301 (£22) and 12567-03-301 (£9). Neither is a
line on the Estimate sheet — the tapes, diffusers and driver beneath them are — so the unit
never held that £31. A figure outside the unit is not one to replace (D-306).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import costed_facts as cf  # noqa: E402
from test_one_costed_record_for_every_deliverable import seventy_three_thirty_two  # noqa: E402

_AI = ["AI researched price — xAI Grok LLM - INDICATIVE"]


def _with_lighting_assembly(on_sheet: bool) -> dict:
    s = seventy_three_thirty_two()
    part = {
        "part_number": "7332-01-301", "description": "LIGHTING ASSEMBLY", "quantity": 1,
        "unit_cost_gbp": 22.0, "supplier": "xAI Grok LLM - INDICATIVE",
        "price_source": {"supplier_source": "xAI Grok LLM - INDICATIVE"},
        "material_estimate": {"cost_method": "market_ai_indicative",
                              "unit_material_cost_gbp": 22.0,
                              "extended_material_cost_gbp": 22.0},
        "review_flags": list(_AI)}
    es = s["estimate_summary"]
    es["part_estimates"].append(dict(part))
    es["canonical_part_estimates"].append(dict(part))
    shadow = es["canonical_route_shadow"]
    shadow["nodes"].append({"part_number": "7332-01-301", "kind": "assembly",
                            "qty_per_unit": 1, "parents": ["7332-01-GA"]})
    if on_sheet:
        s["final_estimate"]["material_rows"].append(
            {"block": "bom", "workbook_row": 60, "part_code": "7332-01-301",
             "description": "7332-01-301 LIGHTING ASSEMBLY", "qty_per_unit": 1,
             "supplier": "", "unit_price_gbp": 22.0, "scrap": 0.0,
             "total_value_gbp": 22.0, "charged_cell": "Estimate!M60"})
    return s


def _line(job, pn):
    return next(l for l in job["lines"] if l["part_number"] == pn)


def test_an_off_sheet_assembly_is_not_a_market_figure_to_replace():
    base = cf.costed_job(seventy_three_thirty_two())["gaps"]
    job = cf.costed_job(_with_lighting_assembly(on_sheet=False))
    assert _line(job, "7332-01-301")["price_origin"]["firmness"] == cf.INDICATIVE_MARKET, \
        "the fixture must reach the market class, or this test proves nothing"
    assert "7332-01-301" not in job["gaps"]["indicative_market"]
    assert job["gaps"]["indicative_market_gbp"] == base["indicative_market_gbp"]
    assert not any(d.get("part") == "7332-01-301" and d.get("kind") == "market_figure"
                   for d in job["decisions_required"])


def test_the_same_assembly_charged_on_the_sheet_still_counts():
    base = cf.costed_job(seventy_three_thirty_two())["gaps"]
    job = cf.costed_job(_with_lighting_assembly(on_sheet=True))
    assert "7332-01-301" in job["gaps"]["indicative_market"]
    assert round(job["gaps"]["indicative_market_gbp"] - base["indicative_market_gbp"], 2) == 22.0
