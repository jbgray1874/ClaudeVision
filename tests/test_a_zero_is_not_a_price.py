"""A £0.00 catalogue row is the absence of a price, and it ended the search.

WHAT THE 13 SEP PACK SHOWED. The fastener fix went in, the tests passed, and 12349-02's M4
flange button screw and 3.5x19 wood screw still reached the estimator as "MATERIAL UNPRICED:
enter a unit rate" — while the bumpon on the same bill of materials, coded P/P, priced at 35p
off the market rung. One difference between them explains it: UDEF holds catch-all rows for
FIXING and for ~900 MISC codes, all priced £0.00, and has none for P/P.

The legacy connector's code-seek is `WHERE [Part code] = ?` with no positive-price filter, so
FIXING matched its catch-all row, came back 0.0, and `_resolve_part_system_cost` returned on
the spot because it asked `price is not None`. Everything below was then unreachable FOR
EXACTLY THE LINES THAT NEEDED IT: the PricingService rungs (the new description match against
UDEF, historical quotes, the supplier catalogue, the market fallback) and the DB-free
standard-commodity provisional, which is itself gated on `best_price is None`.

THE RULE: a zero does not end the search. It is remembered and returned only if nothing
better is found, so a line that genuinely had nothing behind it reads exactly as it did
before. Nothing can be overwritten by a worse figure — every later rung returns only a price
above zero.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator                                                        # noqa: E402


def _priced(price, source="udef"):
    return {"selected": {"price": price, "source": source}}


def _run(part, legacy, anchor=None, commodity=None, monkey=None):
    """Drive _resolve_part_system_cost with each rung stubbed, and record what was asked."""
    asked = {"legacy": [], "pricing_service": 0, "commodity": 0}

    def _get_best_price(req):
        asked["legacy"].append(req.part_code)
        return legacy(req.part_code)

    class _PS:
        def _select_anchor_price_source(self, p):
            asked["pricing_service"] += 1
            return anchor or {}

    def _std(part_arg):
        asked["commodity"] += 1
        return commodity

    monkey.setattr(estimator, "get_best_price", _get_best_price)
    monkey.setattr(estimator, "_get_pricing_service", lambda: _PS())
    import pricing_service
    monkey.setattr(pricing_service, "standard_commodity_price", _std)
    return estimator._resolve_part_system_cost(part), asked


FIXING = {"part_number": "FIXING",
          "description": "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK"}


def test_the_catch_all_zero_no_longer_ends_the_search(monkeypatch):
    """The exact 12349-02 line: UDEF answers £0.00 by code, and the chain must go on."""
    out, asked = _run(FIXING, lambda code: _priced(0.0),
                      anchor={"unit_price_gbp": 0.0248, "source": "UDEF",
                              "supplier_name": "FIXING2813 — Supplier"},
                      monkey=monkeypatch)
    assert asked["pricing_service"] == 1, \
        "the £0.00 catch-all row short-circuited the whole PricingService chain"
    assert out["applied_unit_cost"] == 0.0248


def test_the_commodity_provisional_is_reachable_past_a_zero(monkeypatch):
    """The DB-free last resort is gated on best_price being None — a zero blinded it too."""
    out, asked = _run(FIXING, lambda code: _priced(0.0), anchor={},
                      commodity={"unit_price_gbp": 1.20, "source": "standard_commodity",
                                 "source_type": "standard_commodity_provisional",
                                 "confidence": 0.5},
                      monkey=monkeypatch)
    assert asked["commodity"] == 1
    assert out["applied_unit_cost"] == 1.20


def test_a_real_price_still_returns_immediately(monkeypatch):
    """A priced catalogue row is the best answer there is and still wins on the spot."""
    out, asked = _run({"part_number": "FIXING2841", "description": "M6 x 16 SOCKET CAP"},
                      lambda code: _priced(0.04), monkey=monkeypatch)
    assert out["applied_unit_cost"] == 0.04
    assert asked["pricing_service"] == 0, "nothing further should have been asked"


def test_a_zero_survives_as_the_answer_when_nothing_better_exists(monkeypatch):
    """Today's output, unchanged, wherever today's output was all there was."""
    out, asked = _run(FIXING, lambda code: _priced(0.0), anchor={}, commodity=None,
                      monkey=monkeypatch)
    assert out["applied_unit_cost"] == 0.0
    assert asked["pricing_service"] == 1 and asked["commodity"] == 1


def test_a_negative_price_is_not_a_price_either(monkeypatch):
    out, _ = _run(FIXING, lambda code: _priced(-2.0),
                  anchor={"unit_price_gbp": 0.0248, "source": "UDEF"},
                  monkey=monkeypatch)
    assert out["applied_unit_cost"] == 0.0248


def test_the_zero_keeps_its_own_provenance(monkeypatch):
    """The line still says where its nothing came from — a blank with no source behind it
    is the failure this engine already refuses elsewhere."""
    out, _ = _run(FIXING, lambda code: _priced(0.0, source="udef_catch_all"), anchor={},
                  monkey=monkeypatch)
    assert out["result"]["selected"]["source"] == "udef_catch_all"
    assert out["matched_part_code"] == "FIXING"
