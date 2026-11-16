"""The parity report must not contradict, or quietly discard, the bundle it renders.

The first readable parity report on 10575-02 got two things wrong and left four out:

  * Section 4 printed "They are not misses" as a hardcoded sentence over four lines the
    reconciliation had classified `genuine_miss` — one of them 20KGMOQ, the £12.50 of powder
    the engine costed at nothing. The most important line in the comparison was presented as
    nothing to worry about.
  * The Var column took the bundle's `pct_variance`, a magnitude measured against the ENGINE
    with no direction, and printed it beside a Δ measured the other way: `-£179.27` and
    `+163.5%` on the same row. Read at a glance, the engine looked 163% over when it was 62%
    under.
  * Costs, review reasons, powder and the £0 parts were all in the bundle and none reached
    the page.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.append(str(_ROOT / "src"))
_spec = importlib.util.spec_from_file_location("prh", _ROOT / "src" / "parity_report_html.py")
prh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prh)


def _money(**kw):
    return dict(section="money_cell", **kw)


BUNDLE = {
    "workbook_path": r"\\x\10575-02-GA (Rev D) Cordless Vacuum Display - V2.xls",
    "workbook_read_mode": "xlrd",
    "rollup_unit_cost_comparison": None,
    "workbook_cell_D6_quantity": 1.0,
    "money_cell_comparisons": [
        _money(cell="M69", label="Material subtotal", json_numeric=109.6524,
               workbook_cached_numeric=288.922744, pct_variance=163.4897, status="fail"),
        _money(cell="M117", label="Unit manufacturing cost (L)", json_numeric=168.0274,
               workbook_cached_numeric=832.7994, pct_variance=395.6331, status="fail"),
    ],
    "labour_route_comparisons": [],
    "bom_set_reconciliation": {
        "matched_count": 0, "matched": [],
        "manual_only": [
            {"code": "20KGMOQ", "description": "Powder - MN250F 610 Matt Black",
             "manual_cost_gbp": 12.4959, "category": "genuine_miss",
             "issue": "the engine should have produced this"},
            {"code": "1449-PEGPANEL", "description": "Peg panel",
             "manual_cost_gbp": 40.0, "category": "naming"},
        ],
        "ai_only": [
            {"code": "FIXING591", "description": "BE2030 -10 FRAGRANCE CABINET -TEST TRAY SCREW",
             "ai_cost_gbp": 3.76, "kind": "bought_in"},
        ],
    },
    "status_counts": {"money_match": 1, "money_fail": 2,
                      "labour_route_match": 0, "labour_route_issues": 0},
    "estimate_provenance": {
        "powder_coating_summary": {"powder_total_gbp": 0.0},
        "estimate_review_signals": {"parts_flagged": [
            {"part_number": "ANDREW-14", "reasons": [
                {"code": "risk_flag", "detail": "large_flat"},
                {"code": "low_part_confidence", "detail": 0.38}]},
        ]},
        "parts_for_demo": [
            {"part_number": "10575-01-101", "description": "VERSION 1 - BACK WELDED ASSEMBLY",
             "unit_total_cost_gbp": 0.0,
             "material_price": {"supplier_display": "weldment_parent_material_in_children"},
             "database_system_cost": {"supplier_name": "system_cost_not_found"}},
            {"part_number": "10575-02-009", "description": "V2 - BACK PANEL GRAPHIC",
             "unit_total_cost_gbp": 38.04, "material_price": {}, "database_system_cost": {}},
        ],
    },
}


@pytest.fixture(scope="module")
def page():
    return prh.generate_parity_html(BUNDLE)


# ── the sentence that contradicted the data ────────────────────────────────────────────

def test_a_genuine_miss_is_not_described_as_not_a_miss(page):
    assert "They are not misses" not in page
    assert "should have produced" in page


def test_the_miss_is_named_with_its_cost(page):
    assert "20KGMOQ" in page and "£12.50" in page


def test_a_naming_difference_is_still_separated_from_a_miss(page):
    """The original sentence was right about SOME lines. Losing that distinction would trade
    one wrong blanket statement for another."""
    assert "Naming differences" in page
    assert "1449-PEGPANEL" in page


def test_the_engine_only_lines_carry_their_cost(page):
    """A line on the engine estimate and not the manual is only actionable with money on it —
    FIXING591 is a Fragrance Coffret part costed onto a Dyson job."""
    assert "FIXING591" in page and "£3.76" in page


# ── the column that pointed the wrong way ──────────────────────────────────────────────

def test_the_variance_agrees_in_sign_with_the_delta(page):
    """-£179.27 beside +163.5% was the defect. Both must now say the engine is under."""
    assert "-62.0%" in page, "material variance should read as the engine being under"
    assert "+163.5%" not in page


def test_the_header_says_which_way_round_it_is(page):
    assert "Var vs manual" in page


def test_the_percentage_is_computed_from_the_same_pair_as_the_delta():
    rows = [{"label": "X", "engine": 50.0, "manual": 200.0, "pct": 300.0, "status": "fail"}]
    out = prh._section_table(rows)
    assert "-£150.00" in out and "-75.0%" in out, "the bundle's own 300% must not be printed here"


def test_a_zero_manual_does_not_produce_a_percentage():
    """A percentage of nothing says nothing, and dividing by it would raise."""
    rows = [{"label": "X", "engine": 50.0, "manual": 0.0, "pct": None, "status": "fail"}]
    out = prh._section_table(rows)
    assert "£50.00" in out


# ── what was in the bundle and not on the page ─────────────────────────────────────────

def test_the_flagged_parts_are_named_not_counted(page):
    assert "ANDREW-14" in page
    assert "confidence 0.38" in page


def test_a_reason_code_is_rendered_in_words(page):
    """`large_flat` means nothing to an estimator; it is the tell for a drawing border read as
    a part, which is exactly the ANDREW-14 fault."""
    assert "one large flat panel" in page
    assert ">large_flat<" not in page


def test_the_section_survives_a_bundle_with_no_tally():
    """Keying the whole section off `flagged_part_count` dropped the parts when only the list
    was present."""
    assert "flagged_part_count" not in str(BUNDLE["estimate_provenance"]["estimate_review_signals"])
    assert "ANDREW-14" in prh.generate_parity_html(BUNDLE)


def test_powder_is_quantified_rather_than_hinted(page):
    """The route table said "Powder Coating — manual only", which is a hint. The engine's own
    zero against the manual's figure is a finding."""
    assert "Powder coating: engine £0.00" in page
    assert "£12.50" in page


def test_parts_costing_nothing_are_named(page):
    """This is where an incomplete pack shows up as money — a BOM line whose drawing was never
    supplied reaches the estimate at £0 and sums into a total that reads as finished."""
    assert "costing nothing" in page
    assert "10575-01-101" in page


def test_a_priced_part_is_not_listed_as_unpriced(page):
    body = page[page.index("costing nothing"):]
    assert "10575-02-009" not in body[:body.index("</table>")]


# ── nothing regressed ──────────────────────────────────────────────────────────────────

def test_the_headline_figures_still_render(page):
    assert "£168.03" in page and "£832.80" in page and "-£664.77" in page


def test_a_bundle_with_none_of_the_new_blocks_still_renders():
    """Every new section is additive. A bundle from before any of this must not fail."""
    thin = {k: BUNDLE[k] for k in ("workbook_path", "money_cell_comparisons",
                                   "labour_route_comparisons", "status_counts")}
    thin["bom_set_reconciliation"] = {}
    out = prh.generate_parity_html(thin)
    assert "Parity Diagnostic" in out and "£168.03" in out
