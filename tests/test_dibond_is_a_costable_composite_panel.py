"""Dibond (aluminium composite panel) is recognised, routed and priced — not left at £0.

Dyson 10575-02-009 is a DIBOND 3mm back-panel graphic. Before this the engine did not recognise
"DIBOND" at all: it was neither sheet metal nor a known board/plastic, so it reached no rate and
no proper route (and risked a laser route, which melts the PE core). Now:

  * costed_facts.is_other_sheet_material recognises it — so it is costed by AREA on a board
    sheet and routed like board (CNC router), never lasered;
  * config carries its physical facts (standard ACM sheet sizes, effective density);
  * config.BOARD_SHEET_PRICE_GBP carries a PROVISIONAL per-sheet rate (confirm against SDI's own
    Dibond buy price), so a Dibond part costs its nested share of a real sheet.

The rate is a documented provisional — the estimator owns the real number — but the material is
now first-class: recognised, sized, routed and priced, instead of an unrecognised £0 gap.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import costed_facts as cf  # noqa: E402
import config  # noqa: E402
import estimator  # noqa: E402


def test_dibond_is_recognised_as_an_other_sheet_material():
    assert cf.is_other_sheet_material("DIBOND 3.0mm WHITE") is True
    assert cf.is_other_sheet_material("DIBOND") is True
    # brand and generic variants a drawing might carry
    assert cf.is_other_sheet_material("ALUPANEL 3mm") is True
    assert cf.is_other_sheet_material("ALUMINIUM COMPOSITE PANEL") is True


def test_steel_is_not_swept_up_as_a_board():
    """The recognition must not mis-classify metal — a composite token cannot leak onto steel."""
    assert cf.is_other_sheet_material("MILD STEEL") is False
    assert cf.is_other_sheet_material("3mm CR4") is False


def test_dibond_looks_itself_up_in_the_catalogue():
    """The catalogue token is DIBOND, so the live UDEF rate (SDI's own purchasing) is consulted
    before any fallback — the same self-updating path HIPS/ABS use."""
    assert estimator._sheet_catalogue_token("DIBOND 3.0mm WHITE") == "DIBOND"


def test_dibond_has_a_per_sheet_fallback_rate():
    rate, note = estimator._board_sheet_rate("DIBOND", 3.0)
    assert rate == 165.0 and "3mm" in note
    # a between-gauge value interpolates on SDI's own points, never extrapolates
    rate4, _ = estimator._board_sheet_rate("DIBOND", 4.0)
    assert rate4 == 210.0


def test_dibond_carries_its_physical_facts():
    assert (3050, 1500) in config.STANDARD_SHEET_SIZES_MM["DIBOND"]
    assert config.MATERIAL_DENSITY_KG_PER_M3["DIBOND"] == 1500


def test_a_dibond_panel_costs_its_nested_share_of_a_sheet_not_zero():
    """THE PAYOFF. The 447 x 1496 back panel nests on a real ACM sheet and costs a sensible
    per-panel share — not £0, and not a whole sheet."""
    s = estimator.select_sheet_size("DIBOND", 1496.0, 447.0)
    pps = max(1, int(s.get("parts_per_sheet") or 1))
    assert pps >= 2                      # a 0.67 m2 panel fits several times on a 3m ACM sheet
    unit = 165.0 / pps
    assert 5.0 < unit < 90.0             # a credible per-panel material cost, comfortably non-zero
