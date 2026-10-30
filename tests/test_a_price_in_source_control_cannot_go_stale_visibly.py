"""A price was written into config, and a price in source control tells nobody when it moves.

    "where do we get the tape price? we can't hard code prices. we can log hourly throughput
     rates but we need to start understanding if these change and why."
                                                            — James Gray, SDI, 15 Sep 2026

He is right and it was mine. config.ROLL_GOODS_CATALOGUE held roll_length_mm AND
roll_price_gbp side by side, as though they were the same kind of fact. They are not:

    how it is SUPPLIED    TAPE113C comes on a 10 metre roll. A packaging fact. It changes
                          when the supplier changes the product and not before, and it is
                          not money. Config is the right home for it.

    what it COSTS         money. It moves without telling anyone, it cannot go stale
                          visibly from inside a .py file, and the first person to notice
                          is a customer.

AND THEN THE RULE TIGHTENED. The first fix moved the figure to a dated, attributed
"estimator stated" table — honest, and still a copy. James, 16 Sep: "A number copied from
an estimator's sheet is not a price source, even as a 'reference'. It must not be retained
in the current register, documentation, reports, prompts, tests, or audit payloads." So the
stated table ships EMPTY; SDI's own priced sources (price_sources.get_best_price — Access
Supply Chain, UDEF, supplier catalogue) are the only rungs that answer; and a code nothing
prices is WITHHELD, awaiting price. Every figure below is SYNTHETIC, injected by the test to
prove the mechanism — none is a number off anyone's sheet.

AND WHERE TWO SOURCES ANSWER AND DISAGREE, BOTH ARE REPORTED — which is the half James
actually asked for. Not a better price: an understanding of when prices move and why.
PLAS534 already has three system-side answers, nothing in the engine can say which is
right, and choosing one silently is how the question stops being asked.
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

# Invented figures for the mechanism tests. Nobody's sheet.
SYNTH_SYSTEM = {"gbp": 5.25, "source": "access_supply_chain"}
SYNTH_STATED = {"TAPE113C": {"gbp": 4.80, "unit": "roll", "by": "a test",
                             "on": "2026-01-01",
                             "note": "SYNTHETIC — mechanism test only"}}


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


def test_the_stated_table_ships_empty():
    """A dated, attributed copy of a sheet figure is still a copy. The table exists for a
    genuinely current, identified figure entered the day it is given — and today SDI
    holds none that qualifies, so it holds nothing."""
    assert config.ESTIMATOR_STATED_PRICES == {}


def test_the_system_is_asked_and_its_answer_is_named(monkeypatch):
    """The system is the thing that gets updated when a price moves."""
    monkeypatch.setattr(sp, "system_price", lambda c, d=None: dict(SYNTH_SYSTEM))
    out = sp.resolve("TAPE113C", "EPDM tape")
    assert out["gbp"] == SYNTH_SYSTEM["gbp"]
    assert out["basis"] == "system"
    # THE SYSTEM IS NAMED — in the estimator's words, not the connector's key. The rung
    # itself is handed back separately for callers that must stamp it.
    assert out["source"] == "access_supply_chain"
    assert "Access supply chain" in out["label"]


def test_a_stated_figure_if_one_ever_qualifies_answers_only_when_the_system_cannot(monkeypatch):
    """The mechanism, proven with an invented entry: system first, always."""
    monkeypatch.setattr(sp, "system_price", lambda c, d=None: None)
    monkeypatch.setattr(config, "ESTIMATOR_STATED_PRICES", dict(SYNTH_STATED))
    out = sp.resolve("TAPE113C", "EPDM tape")
    assert out["gbp"] == 4.80
    assert out["basis"] == "estimator_stated"
    assert "not a live system price" in out["label"]


def test_a_code_nobody_can_price_is_not_guessed_at(monkeypatch):
    monkeypatch.setattr(sp, "system_price", lambda c, d=None: None)
    out = sp.resolve("NOSUCHCODE99", "something")
    assert out["gbp"] is None and out["basis"] is None


def test_the_shipped_state_prices_nothing_without_the_system(monkeypatch):
    """With the tables empty by rule and SDI Live silent, resolve answers nothing — the
    line downstream is withheld, awaiting price. This is the state that ships."""
    monkeypatch.setattr(sp, "system_price", lambda c, d=None: None)
    out = sp.resolve("TAPE113C", "EPDM tape")
    assert out["gbp"] is None and out["basis"] is None


def test_the_code_is_matched_however_it_is_written(monkeypatch):
    """"TAPE 113C" in the pack against "TAPE113C" in the register — the SPELLING logic,
    proven on an injected entry."""
    monkeypatch.setattr(config, "ESTIMATOR_STATED_PRICES", dict(SYNTH_STATED))
    for spelling in ("TAPE113C", "TAPE 113C", "tape-113c"):
        assert sp.stated(spelling), spelling


# ── the disagreement, which is what he actually asked for ────────────────────────────────

def test_two_sources_that_disagree_are_both_reported(monkeypatch):
    monkeypatch.setattr(sp, "system_price",
                        lambda c, d=None: {"gbp": 6.00, "source": "access_supply_chain"})
    monkeypatch.setattr(config, "ESTIMATOR_STATED_PRICES", dict(SYNTH_STATED))
    out = sp.resolve("TAPE113C", "EPDM tape")
    assert out["gbp"] == 6.00                     # the system is still used
    d = out["disagreement"]
    assert d and "£6.00" in d and "£4.80" in d
    assert "neither outranks the other" in d


def test_a_penny_in_a_pound_is_not_a_disagreement(monkeypatch):
    """Rounding is the same figure typed twice. Ten per cent is two different facts, and a
    review list that cries at both gets skimmed."""
    monkeypatch.setattr(config, "ESTIMATOR_STATED_PRICES", dict(SYNTH_STATED))
    monkeypatch.setattr(sp, "system_price",
                        lambda c, d=None: {"gbp": 4.802, "source": "system"})
    assert sp.resolve("TAPE113C")["disagreement"] is None


def test_the_line_carries_the_disagreement_onto_the_sheet(monkeypatch):
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price",
                        lambda c, d=None: {"gbp": 6.00, "source": "access_supply_chain"})
    monkeypatch.setattr(config, "ESTIMATOR_STATED_PRICES", dict(SYNTH_STATED))
    part = _tape()
    roll_goods_material(part)
    f = _flags(part)
    assert "PRICE DISAGREEMENT" in f
    assert "confirm which stands" in f


# ── and the line says what each half of its sentence rests on ────────────────────────────

def test_the_line_says_where_the_length_came_from_and_where_the_price_did(monkeypatch):
    """Two facts, two sources, and an estimator checking the roll price should not have to
    work out which half of the sentence is about money."""
    monkeypatch.setattr(sp, "system_price",
                        lambda c, d=None: {"gbp": 5.00, "source": "access_supply_chain"})
    part = _tape()
    roll_goods_material(part)
    f = _flags(part)
    assert "Roll length:" in f and "Roll price:" in f
    assert "Access supply chain" in f


def test_a_roll_we_hold_but_cannot_price_is_withheld(monkeypatch):
    """The length alone is not enough, and a zero here would read as free tape. This is
    the SHIPPED state — no monkeypatched data, just SDI Live silent."""
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: None)
    part = _tape()
    out = roll_goods_material(part)
    assert out["unit_material_cost_gbp"] is None
    assert out["cost_method"] == "roll_goods_withheld_estimator_to_price"
    assert "nothing priced it" in _flags(part)
