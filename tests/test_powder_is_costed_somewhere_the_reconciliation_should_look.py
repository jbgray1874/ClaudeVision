"""A cost the engine carries per part must not be reported as a cost the engine forgot.

The third of the 10575-02 faults, and the one whose diagnosis was wrong before this test existed.

The parity bundle recorded `20KGMOQ` — "Powder - MN250F 610 Matt Black", £12.50 — as
`category: "genuine_miss"`, with the issue "the engine should have produced this. Investigate."
It was read, reasonably, as £12.50 of powder the engine had costed at nothing.

IT IS NOT MISSING. `sheet_steel_costing.powder_total_cost()` computes powder material as
`kg × price` and `estimator.py` carries `powder_material_gbp` per part and rolls it up. The engine
costs the powder. It just does not emit a catalogue LINE called 20KGMOQ, because it prices powder
by mass inside each part's breakdown rather than buying it as a bought-in item.

So the manual has one discrete row and the engine has the same money spread across parts. The
reconciliation matches on catalogue code, finds no counterpart, and falls through to its default.

    if _OUT_OF_SCOPE_RE.search(description):  ->  out_of_scope
    return {"category": "genuine_miss", ...}   <- everything else

Two categories, and powder is in neither. It is not logistics the estimator adds at quote time,
and it is not something the engine forgot. It is a THIRD thing: costed by the engine, structured
differently.

WHY THIS MATTERS MORE THAN £12.50. A false "genuine miss" is worse than a silent one. It sends an
estimator hunting for money that is already in the total, and — if anybody had "fixed" it by adding
the line — it would have double-charged powder on every coated job. The instruction to
"Investigate" was doing real harm precisely because it was confident.

The corroborating detail, which is what made this worth checking rather than fixing:
`POWDER_PRICE_GBP_PER_KG = 12.50`, and the manual line is £12.50. The manual row is the powder's
per-kilogram price, coded to record that it arrives in a 20 kg minimum order.

WHAT THIS FIX DOES NOT DO. It does not assert the two numbers agree — they may well not, and a
genuine powder under-charge would still be worth finding. It changes the report from "the engine
should have produced this" to "the engine carries this as powder_material_gbp; compare there" —
which is what a person needs in order to check.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "efpr", _ROOT / "src" / "estimate_full_parity_report.py")
efpr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(efpr)


# ── WHAT THE FIRST VERSION OF THIS FIX GOT WRONG ──────────────────────────────
#
# It checked only the DESCRIPTION: powder is costed by mass, therefore any powder line is
# "costed elsewhere". Then the 10575-02 run was actually opened:
#
#     "powder_material_gbp": 0.0
#     "powder_labour_gbp":   0.0
#     "powder_total_gbp":    0.0
#
# Powder really was free, on a powder-coated job. The reclassification had printed "the engine
# carries this as powder_material_gbp" over the top of a genuine fault — replacing a false alarm
# with a false all-clear, which is the worse of the two by a distance. A false alarm wastes an
# hour; a false all-clear ships a wrong estimate.
#
# So the third category now has to be EARNED. The claim "we cost this elsewhere" is checked
# against the engine's own number before it is made.

_ENGINE_COSTED_POWDER = {"estimate_summary": {"totals": {"powder_material_gbp": 37.50}}}
_ENGINE_FREE_POWDER = {"estimate_summary": {"totals": {"powder_material_gbp": 0.0,
                                                       "powder_total_gbp": 0.0}}}


def test_a_zero_is_a_genuine_miss_however_it_is_spelled():
    """The 10575-02 fault. This is the assertion that would have caught my own bad fix."""
    got = efpr._classify_manual_only("Powder - MN250F 610 Matt Black", _ENGINE_FREE_POWDER)
    assert got["category"] == "genuine_miss", (
        "the engine costed powder at zero on a coated job and the report called it "
        "'costed elsewhere' — a false all-clear over a real gap")


def test_the_zero_is_named_in_the_issue():
    got = efpr._classify_manual_only("Powder - MN250F", _ENGINE_FREE_POWDER)
    assert "ZERO" in got["issue"] or "0.00" in got["issue"]


def test_powder_the_engine_really_did_cost_is_not_a_miss():
    """The other half. When the engine HAS the money, saying it is missing sends somebody
    hunting for a cost that is already in the total."""
    got = efpr._classify_manual_only("Powder - MN250F", _ENGINE_COSTED_POWDER)
    assert got["category"] == "costed_elsewhere"
    assert "37.50" in got["issue"], "the reader needs the number to compare against"


def test_with_no_summary_at_all_it_assumes_nothing():
    """Absent evidence is not evidence of costing. Defaulting the other way is how the first
    version of this went wrong."""
    assert efpr._classify_manual_only("Powder - MN250F")["category"] == "genuine_miss"


@pytest.mark.parametrize("desc", [
    "Powder - MN250F 610 Matt Black",
    "POWDER COAT RAL 9005",
    "Powder coating - satin white",
    "20KGMOQ Powder",
])
def test_every_way_powder_is_written_is_checked_the_same(desc):
    assert efpr._classify_manual_only(desc, _ENGINE_COSTED_POWDER)["category"] == "costed_elsewhere"
    assert efpr._classify_manual_only(desc, _ENGINE_FREE_POWDER)["category"] == "genuine_miss"


def test_the_engine_total_is_found_wherever_it_sits():
    """Walked, not looked up by path — the rollup has moved once already, and a lookup that
    silently reads None is exactly how a zero gets called 'costed elsewhere'."""
    assert efpr._engine_carries({"a": {"b": [{"powder_material_gbp": 12.5}]}},
                                "powder_material_gbp") == 12.5
    assert efpr._engine_carries({"nothing": 1}, "powder_material_gbp") == 0.0


# ── The categories that must not move ──────────────────────────────────────────

@pytest.mark.parametrize("desc", [
    "Delivery to site", "Euro pallet", "Misc packaging", "Carriage", "Artic overhang",
])
def test_logistics_is_still_out_of_scope(desc):
    assert efpr._classify_manual_only(desc, _ENGINE_COSTED_POWDER)["category"] == "out_of_scope"


@pytest.mark.parametrize("desc", [
    "M6 x 20 socket cap screw", "Acrylic panel 3mm", "LED driver 24V",
])
def test_a_real_miss_is_still_a_real_miss(desc):
    """The default has to keep working. This category exists to find engine faults and
    narrowing it wrongly would hide them."""
    assert efpr._classify_manual_only(desc)["category"] == "genuine_miss"


def test_the_miss_count_does_not_count_the_new_category():
    """genuine_miss_count is the number the report leads on. It must mean what it says."""
    src = (_ROOT / "src" / "estimate_full_parity_report.py").read_text(encoding="utf-8")
    at = src.index("genuine_miss_count")
    line = src[at:src.index("\n", at)]
    assert 'category") == "genuine_miss"' in line, (
        "the count must filter on the genuine_miss category exactly, not on 'not out_of_scope'")


def test_an_empty_description_is_not_quietly_reclassified():
    assert efpr._classify_manual_only("")["category"] == "genuine_miss"
    assert efpr._classify_manual_only(None)["category"] == "genuine_miss"


# ── And the report has to show it as its own thing ─────────────────────────────
#
# Classifying correctly is only half of it. The HTML split manual-only lines into "misses" and
# "everything else", and called everything else a NAMING DIFFERENCE — so logistics the estimator
# adds at quote time, and now powder, both read as the two estimates spelling a part differently.
# Three unrelated situations presented as one.

_html_spec = importlib.util.spec_from_file_location(
    "prh", _ROOT / "src" / "parity_report_html.py")
prh = importlib.util.module_from_spec(_html_spec)
_html_spec.loader.exec_module(prh)


_RECON = {
    "manual_only": [
        {"code": "20KGMOQ", "description": "Powder - MN250F 610 Matt Black",
         "manual_cost_gbp": 12.50, "category": "costed_elsewhere",
         "issue": "The engine costs powder by mass per part (powder_material_gbp)."},
        {"code": "DELIVERY", "description": "Delivery to site",
         "manual_cost_gbp": 180.0, "category": "out_of_scope",
         "issue": "Logistics / packaging."},
        {"code": "LED-DRV", "description": "LED driver 24V",
         "manual_cost_gbp": 42.0, "category": "genuine_miss",
         "issue": "the engine should have produced this."},
    ],
    "ai_only": [],
}


def test_powder_is_not_filed_under_naming_differences():
    page = prh._unmatched_section(_RECON)
    at = page.index("20KGMOQ")
    heading = page.rfind("<h3>", 0, at)
    assert "Naming differences" not in page[heading:at], (
        "powder was presented as the two estimates using different names for the same part")


def test_powder_gets_a_heading_that_says_it_is_not_missing():
    page = prh._unmatched_section(_RECON)
    assert "not missing" in page.lower() or "different shape" in page.lower()


def test_the_engine_field_reaches_the_page():
    """Without the field name the reader cannot check, and 'it is elsewhere' is just a shrug."""
    assert "powder_material_gbp" in prh._unmatched_section(_RECON)


def test_logistics_gets_its_own_heading_too():
    page = prh._unmatched_section(_RECON)
    assert "Out of scope" in page
    at = page.index("DELIVERY")
    heading = page.rfind("<h3>", 0, at)
    assert "Naming differences" not in page[heading:at]


def test_the_real_miss_still_leads():
    """The genuine miss is the thing worth acting on and must stay at the top of the section."""
    page = prh._unmatched_section(_RECON)
    assert page.index("LED-DRV") < page.index("20KGMOQ")
    assert "£42" in page


def test_all_three_costs_are_shown():
    page = prh._unmatched_section(_RECON)
    for money in ("£12.50", "£180", "£42"):
        assert money in page, f"{money} was not shown"
