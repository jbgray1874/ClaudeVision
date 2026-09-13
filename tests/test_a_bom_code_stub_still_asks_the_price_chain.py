"""The two screws an estimator can price in his sleep, unpriced on run after run.

12349-02's `FIXING  M4x10mm FLANGE BUTTON HEAD SCREW, BLACK` and `STD PART  3.5x19mm WOOD
SCREW` came back "MATERIAL UNPRICED: enter a unit rate" on the 13 Sep evening run — with the
catch-all-zero fix already in the build, which had opened the road for exactly these lines.
The bumpon on the same bill of materials, coded `P/P`, went down the chain and priced at 35p.

WHY, AND IT IS THE THIRD LAYER OF ONE DEFECT. A line the bought-in recogniser flags
`sdi_bom_code_unpriced` returns from `estimate_part` BEFORE `_resolve_part_system_cost` is
called at all. The commodity table was lifted up into that branch once, for the same reason
and with the same words — "this stub short-circuits estimate_part BEFORE
_resolve_part_system_cost, so the commodity table there is never reached and the line shipped
as £0". It is not the only thing past that return: UDEF matched on the DESCRIPTION, the
historical quote lines, the supplier catalogue and the market rung are all down there. P/P is
not flagged this way, which is the whole difference between 35p and a blank.

THE RULE: ask the chain before giving up. A miss changes nothing — the £0/None pass-through
is untouched — so this can only turn a blank into a priced line, never the reverse. And a
line priced on its description says so, because the code column still holds a class word and
nobody should have to guess which item was matched.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator                                                        # noqa: E402


def _stub_part(**over):
    """A bought-in line as the recogniser hands it over: class word, real description."""
    part = {
        "part_number": "FIXING",
        "description": "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK",
        "quantity": 4,
        "source": "sdi_bom_code_unpriced",
    }
    part.update(over)
    return part


def _chain_returns(monkeypatch, price, source="UDEF_PARTS_TABLE_FOR_ESTIMATING"):
    def _fake(part):
        return {"result": {"selected": {"price": price, "source": source,
                                        "provenance": f"{source}: FIXING2813"}},
                "applied_unit_cost": price,
                "matched_part_code": "FIXING2813"}
    monkeypatch.setattr(estimator, "_resolve_part_system_cost", _fake)


def _cost(part, monkeypatch):
    """estimate_part, with the commodity table silent so only the chain can answer."""
    import pricing_service
    monkeypatch.setattr(pricing_service, "standard_commodity_price", lambda p: None)
    return estimator.estimate_part(dict(part), job_quantity=7)


def test_the_m4_screw_prices_off_the_chain(monkeypatch):
    """The line that has been blank on every pack so far."""
    _chain_returns(monkeypatch, 0.0248)
    out = _cost(_stub_part(), monkeypatch)
    assert out["unit_total_cost_gbp"] == 0.02
    assert out["material_estimate"]["cost_method"].startswith(
        "bom_code_priced_by_description:")


def test_the_line_says_it_was_matched_on_its_description(monkeypatch):
    """The code cell still reads FIXING, so the sheet has to name what was matched."""
    _chain_returns(monkeypatch, 0.0248)
    out = _cost(_stub_part(), monkeypatch)
    assert out.get("matched_part_code") == "FIXING2813"
    assert any("priced on its DESCRIPTION" in str(f) for f in out.get("review_flags") or [])


def test_the_wood_screw_too(monkeypatch):
    _chain_returns(monkeypatch, 0.008)
    out = _cost(_stub_part(part_number="STD PART",
                           description="3.5x19mm WOOD SCREW", quantity=6), monkeypatch)
    assert out["unit_total_cost_gbp"] == 0.01


def test_a_chain_miss_leaves_the_line_exactly_as_it_was(monkeypatch):
    """The honest 'estimator to price' pass-through is untouched — this can only add."""
    _chain_returns(monkeypatch, None)
    out = _cost(_stub_part(), monkeypatch)
    assert out["unit_total_cost_gbp"] is None
    assert out["costing_basis"] == "sdi_bom_code_estimator_to_price"


def test_a_zero_from_the_chain_is_not_a_price_here_either(monkeypatch):
    """The catch-all £0.00 row must not turn a flagged line into a costed one."""
    _chain_returns(monkeypatch, 0.0)
    out = _cost(_stub_part(), monkeypatch)
    assert out["costing_basis"] == "sdi_bom_code_estimator_to_price"


def test_a_chain_that_throws_never_breaks_the_costing(monkeypatch):
    def _boom(part):
        raise RuntimeError("no database on this box")
    monkeypatch.setattr(estimator, "_resolve_part_system_cost", _boom)
    out = _cost(_stub_part(), monkeypatch)
    assert out["costing_basis"] == "sdi_bom_code_estimator_to_price"


def test_the_commodity_table_still_wins_when_it_has_an_answer(monkeypatch):
    """A pallet keeps its fixed config figure — that fix stays in front of this one."""
    import pricing_service
    monkeypatch.setattr(pricing_service, "standard_commodity_price",
                        lambda p: {"unit_price_gbp": 1.20, "review_reason": "provisional"})
    _chain_returns(monkeypatch, 9.99)
    out = estimator.estimate_part(
        _stub_part(part_number="STD PART", description="PERFO PLASTIC LOCKING CLIP",
                   quantity=1), job_quantity=7)
    assert out["unit_total_cost_gbp"] == 1.20
    assert out["costing_basis"] == "standard_commodity_provisional"
