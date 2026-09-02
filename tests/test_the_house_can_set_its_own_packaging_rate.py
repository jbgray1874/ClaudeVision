r"""
test_the_house_can_set_its_own_packaging_rate.py

THE LEVER THE CODE DOCUMENTS AND CONFIG DID NOT HAVE.

commercial_lines prices packaging and delivery on a ladder — a figure the business has
entered, then a market/LLM indication, then an explicit nil. The first rung reads
`config.COMMERCIAL_LINE_GBP_PER_ORDER`, and its own note tells an estimator to "put a
per-order figure in config.COMMERCIAL_LINE_GBP_PER_ORDER['PACKAGING'] and every job carries
it."

That setting was never defined. `getattr(config, ..., {})` returned an empty dict on every
job, so the catalogue rung could not fire and BOTH lines fell through to an AI indication
every single time — not because nobody at SDI has a figure, but because there was nowhere to
put one. On 12552 they were £85.00 + £85.00 against a £930.39 unit at 1 off: 18% of the
quote resting on two numbers that move between runs.

The setting is empty on purpose. A figure invented in config would be worse than the
indication it replaced, because it would carry no "check me" flag.

AND THE DIVISOR IS THE POINT. Both are asked for the WHOLE ORDER and divided by the
quantity, so the per-unit figure falls as the order rises. "AI market indication" said
neither that nor how to stop it being an indication.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                      # noqa: E402
import estimate_explained as ee                                    # noqa: E402

commercial_lines = pytest.importorskip("commercial_lines")


# ── the setting exists, so the ladder's first rung can fire ────────────────────

def test_the_setting_the_code_tells_people_to_edit_exists():
    assert hasattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER"), (
        "commercial_lines names this in its own note; without it the catalogue rung is a "
        "permanent no-op and every job goes to the AI")
    assert isinstance(config.COMMERCIAL_LINE_GBP_PER_ORDER, dict)


def test_it_ships_empty_so_nothing_is_invented():
    """An invented house rate would be worse than the indication it replaced: it would carry
    no flag, and nobody would ever check it."""
    assert not config.COMMERCIAL_LINE_GBP_PER_ORDER


@pytest.mark.parametrize("key", ["PACKAGING", "DELIVERY"])
def test_a_house_rate_beats_the_market_ask(monkeypatch, key):
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {key: 85.0}, raising=False)
    monkeypatch.setattr(commercial_lines, "_ask_market",
                        lambda *a, **k: pytest.fail("the market was asked despite a held rate"))
    assert commercial_lines._held_rate(key) == 85.0


def test_the_order_figure_is_divided_by_the_order_quantity(monkeypatch):
    """£85 for the order is £85 at 1 off and £8.50 at 10 — which is the whole reason these
    two lines dominate a small order and vanish on a large one."""
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {"PACKAGING": 85.0},
                        raising=False)
    line = commercial_lines._line("PACKAGING", {"order_quantity": 10}, "boxes", "PACKAGING")
    assert line["order_gbp"] == 85.0
    assert line["unit_gbp"] == 8.50


def test_a_held_rate_is_reported_as_a_catalogue_price_not_an_indication(monkeypatch):
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {"DELIVERY": 120.0},
                        raising=False)
    line = commercial_lines._line("DELIVERY", {"order_quantity": 4}, "haulage", "DELIVERY")
    assert line["price_source"]["source_class"] == "catalogue"
    assert line["price_source"]["reproducible"] is True
    assert line["estimator_input_required"] is False


# ── what the note says about them while they are still indications ─────────────

def _src(row):
    return ee._price_source(row, {}, {})


@pytest.mark.parametrize("code", ["PACKAGING", "DELIVERY"])
def test_the_note_says_it_is_an_order_figure_and_names_the_divisor(code):
    got = _src({"code": code, "price": 25.0, "supplier": "market_indication",
                "text": f"{code} for the whole order of 7, divided per unit."})
    assert "WHOLE ORDER of 7" in got and "÷ 7 per unit" in got


@pytest.mark.parametrize("code", ["PACKAGING", "DELIVERY"])
def test_the_note_says_how_to_stop_it_being_an_indication(code):
    got = _src({"code": code, "price": 25.0, "supplier": "market_indication",
                "text": f"{code} for the whole order of 7"})
    assert "COMMERCIAL_LINE_GBP_PER_ORDER" in got


def test_it_still_says_this_is_not_a_quote():
    got = _src({"code": "PACKAGING", "price": 25.0, "supplier": "market_indication",
                "text": "PACKAGING for the whole order of 7"})
    assert "NOT A QUOTE" in got


def test_a_commercial_line_with_no_stated_order_says_so_rather_than_guessing():
    """The divisor is read back out of the line's own sentence, which is the only place it
    survives into the workbook. Guessing it from the header quantity would be the same
    number today and would diverge silently the moment a line is priced for a batch."""
    got = _src({"code": "DELIVERY", "price": 12.0, "supplier": "market_indication",
                "text": "Delivery"})
    assert "divided per unit" in got and "÷" not in got


def test_an_ordinary_bought_in_indication_is_unaffected():
    got = _src({"code": "01-02X", "price": 85.62, "supplier": "xAI market indication",
                "text": "CONCRETE SLAB"})
    assert "NOT A QUOTE, replace it" in got and "WHOLE ORDER" not in got
