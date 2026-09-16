"""£4.50 was written into config, and a price in source control tells nobody when it moves.

    "where do we get the tape price? we can't hard code prices. we can log hourly throughput
     rates but we need to start understanding if these change and why."
                                                            — James Gray, SDI, 15 Sep 2026

He is right and it was mine. config.ROLL_GOODS_CATALOGUE held roll_length_mm AND
roll_price_gbp side by side, as though they were the same kind of fact. They are not:

    how it is SUPPLIED    TAPE113C comes on a 10 metre roll. A packaging fact. It changes
                          when the supplier changes the product and not before, and it is
                          not money. Config is the right home for it.

    what it COSTS         £4.50 a roll. Money. It moves without telling anyone, it cannot
                          go stale visibly from inside a .py file, and the first person to
                          notice is a customer.

SDI ALREADY HAS THE PRICED SOURCE. price_sources.get_best_price runs the rungs — the part
system cost off Access Supply Chain, UDEF by description, historical quotes, the supplier
catalogue, the market fallback last. The tape never asked any of them, because the answer was
already sitting in config.

So the system is asked FIRST; an estimator's stated figure answers only where it cannot, and
says so on the sheet with the name and the date on it. Nothing is invented: a code neither
source can price is WITHHELD, exactly as before.

AND WHERE BOTH ANSWER AND DISAGREE, BOTH ARE REPORTED — which is the half James is actually
asking for. Not a better price: an understanding of when prices move and why. PLAS534 already
has three answers (£45.19 the supplier's, £47.21 ours, £49.55 the system's "migrated from the
old system"), nothing in the engine can say which is right, and choosing one silently is how
the question stops being asked.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                          # noqa: E402
import stated_prices as sp                                             # noqa: E402
from estimator import roll_goods_material                              # noqa: E402

TAPE = "Tape^10975-02-GA EPDM TAPE 25X1MM - TAPE 113C LENGTH: 200.00"


def _tape(qty=3, desc=TAPE):
    return {"part_number": "10975", "description": desc, "quantity": qty}


def _flags(part):
    return " ".join(str(f) for f in part.get("review_flags") or [])


# ── the split ────────────────────────────────────────────────────────────────────────────

def test_the_roll_catalogue_holds_no_money():
    """THE WHOLE POINT. A length is a packaging fact; a price is not."""
    for code, entry in config.ROLL_GOODS_CATALOGUE.items():
        assert "roll_length_mm" in entry, code
        assert "roll_price_gbp" not in entry, (
            f"{code} carries a price in source control — it cannot go stale visibly and "
            f"nobody is told when it moves")


def test_the_stated_price_carries_a_name_and_a_date():
    """A figure with no date cannot be known to be stale, which is the thing being asked
    for. One with no name cannot be disagreed with."""
    for code, entry in config.ESTIMATOR_STATED_PRICES.items():
        assert entry.get("gbp"), code
        assert entry.get("by"), code
        assert entry.get("on"), code


def test_the_system_is_asked_before_the_stated_figure(monkeypatch):
    """The system is the thing that gets updated when a price moves. A figure in config is
    only ever as new as the last person who edited it."""
    monkeypatch.setattr(sp, "system_price",
                        lambda c, d=None: {"gbp": 5.25, "source": "access_supply_chain"})
    out = sp.resolve("TAPE113C", "EPDM tape")
    assert out["gbp"] == 5.25
    assert out["basis"] == "system"
    # THE SYSTEM IS NAMED — in the estimator's words, not the connector's key. The rung
    # itself is handed back separately for callers that must stamp it.
    assert out["source"] == "access_supply_chain"
    assert "Access supply chain" in out["label"]


def test_the_stated_figure_answers_only_when_the_system_cannot(monkeypatch):
    monkeypatch.setattr(sp, "system_price", lambda c, d=None: None)
    out = sp.resolve("TAPE113C", "EPDM tape")
    assert out["gbp"] == 4.50
    assert out["basis"] == "estimator_stated"
    assert "Howard Thurley" in out["label"] and "2026-09-09" in out["label"]
    assert "not a live system price" in out["label"]


def test_a_code_nobody_can_price_is_not_guessed_at(monkeypatch):
    monkeypatch.setattr(sp, "system_price", lambda c, d=None: None)
    out = sp.resolve("NOSUCHCODE99", "something")
    assert out["gbp"] is None and out["basis"] is None


def test_the_code_is_matched_however_it_is_written():
    """"TAPE 113C" in the pack against "TAPE113C" in the register."""
    for spelling in ("TAPE113C", "TAPE 113C", "tape-113c"):
        assert sp.stated(spelling), spelling


# ── the disagreement, which is what he actually asked for ────────────────────────────────

def test_two_sources_that_disagree_are_both_reported(monkeypatch):
    monkeypatch.setattr(sp, "system_price",
                        lambda c, d=None: {"gbp": 6.00, "source": "access_supply_chain"})
    out = sp.resolve("TAPE113C", "EPDM tape")
    assert out["gbp"] == 6.00                     # the system is still used
    d = out["disagreement"]
    assert d and "£6.00" in d and "£4.50" in d
    assert "Howard Thurley" in d and "2026-09-09" in d
    assert "neither outranks the other" in d


def test_a_penny_in_a_pound_is_not_a_disagreement(monkeypatch):
    """Rounding is the same figure typed twice. Ten per cent is two different facts, and a
    review list that cries at both gets skimmed."""
    monkeypatch.setattr(sp, "system_price",
                        lambda c, d=None: {"gbp": 4.502, "source": "system"})
    assert sp.resolve("TAPE113C")["disagreement"] is None


def test_the_line_carries_the_disagreement_onto_the_sheet(monkeypatch):
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price",
                        lambda c, d=None: {"gbp": 6.00, "source": "access_supply_chain"})
    part = _tape()
    roll_goods_material(part)
    f = _flags(part)
    assert "PRICE DISAGREEMENT" in f
    assert "confirm which stands" in f


# ── and none of this broke the number Howard checked ─────────────────────────────────────

def test_the_tape_still_comes_to_howards_twenty_eight_pence():
    part = _tape()
    out = roll_goods_material(part)
    assert round(out["cost_per_part_gbp"] * 3 * 1.04, 4) == 0.2808


def test_the_line_says_where_the_length_came_from_and_where_the_price_did():
    """Two facts, two sources, and an estimator checking the roll price should not have to
    work out which half of the sentence is about money."""
    part = _tape()
    roll_goods_material(part)
    f = _flags(part)
    assert "Roll length:" in f and "Roll price:" in f
    assert "Howard Thurley" in f


def test_a_roll_we_hold_but_cannot_price_is_withheld(monkeypatch):
    """The length alone is not enough, and a zero here would read as free tape."""
    import price_register
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: None)
    # BOTH STATED SOURCES, because there are now two: the register is where a price lives
    # and config is what remains while entries migrate. Emptying one and calling that
    # "nothing priced it" would test a state the engine can no longer be in.
    monkeypatch.setattr(config, "ESTIMATOR_STATED_PRICES", {})
    monkeypatch.setattr(price_register, "_CACHE",
                        {"prices": {}, "problems": [], "path": "(emptied for this test)"})
    part = _tape()
    out = roll_goods_material(part)
    assert out["unit_material_cost_gbp"] is None
    assert out["cost_method"] == "roll_goods_withheld_estimator_to_price"
    assert "nothing priced it" in _flags(part)
