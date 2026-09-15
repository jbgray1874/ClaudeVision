"""Four different systems, one blank cell, and no way to tell them apart.

    "we just need to ensure that in the estimating s/sheet that the source of the price is
     clear. - estimating, or SDILive UDEF, llm etc"      — James Gray, SDI, 15 Sep 2026

He said it as the PRECONDITION for turning the historical corpus up: ingest thousands of old
estimating workbooks and the sheet fills with prices whose weight nobody can judge, because
the column that should say where a figure came from says nothing at all.

The class `catalogue` means "a row somebody can look it up in again". That is true of all of:

    SDI Live UDEF               what purchasing actually pays against
    a supplier's own file       a list price, no contract behind it
    estimating history          a description match against an old workbook — a RESEMBLANCE
    a figure in this repository somebody typed it, and nobody is told when it moves

Those carry completely different weight and all four rendered as an empty supplier cell.
Worse, empty is also what a perfect UDEF row looks like, so the resemblance and the account
price were typographically identical — which is how 12422-24 put GBP 1.06 on a 3.5x16 wood
screw next to an M6 flange button head at GBP 0.05 from Elite Sourcing.

WHAT IS NOT CHANGING: the warnings. INDICATIVE still means a guess, "verify" still means a
resemblance. Naming the system is a different question from flagging a risk, and answering
one was never a reason to leave the other unasked.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import price_provenance as P                                          # noqa: E402
import wb_populate as W                                               # noqa: E402


def _line(source_name, applied=True):
    return {"part_number": "BI-KNURLEDKNOB", "quantity": 2, "unit_cost_gbp": 1.77,
            "cost_breakdown": {"system_cost": {
                "applied_to_total": applied,
                "source": {"source_name": source_name, "applied": True,
                           "affects_total": applied, "source_rank": 0,
                           "selected": {"source": source_name, "price": 1.77}}}}}


# ── the four systems name themselves ─────────────────────────────────────────────────────

def test_each_rung_is_named_the_way_an_estimator_says_it():
    """The connector keys are written for the code. These are written for the reader."""
    assert P.source_system_label("udef_sqlserver") == "SDI Live UDEF"
    assert P.source_system_label("spreadsheet") == "Estimating spreadsheet"
    assert P.source_system_label("web") == "Web listing"
    assert P.source_system_label("estimator_stated") == "Estimator stated"


def test_the_supplier_column_carries_the_system():
    label, indicative = W._price_origin(_line("udef_sqlserver"))
    assert label == "SDI Live UDEF"
    assert indicative is False, "naming the system is not a warning about it"


def test_a_resemblance_still_says_verify():
    """Naming the system does not soften the flag. Both facts, not one instead of the other."""
    for cls in ("historical_quote", "historical_quote_material_line"):
        assert "verify" in W._ORIGIN_LABELS[cls].lower()


def test_a_guess_is_still_named_a_guess():
    label, indicative = W._price_origin(_line("llm_market_estimate"))
    assert indicative is True
    assert "INDICATIVE" in label


# ── never blank, whatever turns up ───────────────────────────────────────────────────────

def test_a_connector_nobody_has_mapped_yet_still_names_itself():
    """THE WHOLE POINT OF THE OLD BLANK WAS THAT IT COST NOTHING TO LEAVE UNMAPPED. It cost
    a wood screw at a pound. A source added next week is named by the same rule, badly
    formatted at worst — and a badly formatted name is a question somebody asks, where a
    blank cell is a question nobody knows to ask."""
    assert P.source_system_label("some_new_feed") == "Some new feed"
    assert P.source_system_label("Sage_X3") == "Sage x3"


def test_a_fragment_of_a_name_is_not_the_name():
    """TWO SYSTEMS WEAR THE WORD "ACCESS". The `access` connector is a local .mdb file;
    Access Supply Chain is the ERP behind SDILive. A substring match read one as the other
    and would have printed the wrong system's name with complete confidence, which is worse
    than the blank cell this whole change exists to remove."""
    assert P.source_system_label("access") == "Access price file"
    assert P.source_system_label("access_supply_chain") == "Access supply chain"


def test_nothing_asked_is_still_nothing_answered():
    """An empty name is not a system called "". The caller decides what to do with that."""
    assert P.source_system_label("") == ""
    assert P.source_system_label(None) == ""


def test_no_class_renders_silently_any_more():
    assert W._SILENT_ORIGIN_CLASSES == set()
    assert W._ORIGIN_LABELS["catalogue"] is None
    assert W._ORIGIN_LABELS["config"] is None


# ── a named estimator's figure is not a catalogue row ────────────────────────────────────

def test_a_stated_price_classifies_as_config_not_catalogue():
    """Howard gave us GBP 4.50 for a 10 m roll of TAPE113C because nothing else priced it.
    That is a figure in source control — reproducible, never firm — which is precisely what
    `config` means. It fell through to `catalogue` and rendered like an account price."""
    assert P.classify_price_source("estimator_stated") == "config"
    assert P.classify_price_source("udef_sqlserver") == "catalogue"


def test_the_stated_price_names_its_estimator_on_the_sheet():
    label, indicative = W._price_origin(_line("estimator_stated"))
    assert label == "Estimator stated"
    assert indicative is False, "a stated figure repeats; it is not reproducibility that is "\
                                "wrong with it, it is that nobody is told when it moves"


# ── supplier name and system are both facts ──────────────────────────────────────────────

def test_a_supplier_name_no_longer_swallows_the_system():
    """The old rule was `if origin and not supplier` — a supplier name suppressed the origin
    entirely, so "Elite Sourcing" told you who sells the part and nothing about whether the
    figure beside it came off UDEF or off a five-year-old estimate."""
    assert W._supplier_cell("Elite Sourcing", "SDI Live UDEF") == "Elite Sourcing (SDI Live UDEF)"


def test_either_fact_alone_still_renders():
    assert W._supplier_cell("Elite Sourcing", "") == "Elite Sourcing"
    assert W._supplier_cell("", "SDI Live UDEF") == "SDI Live UDEF"
    assert W._supplier_cell(None, None) == ""


def test_it_does_not_say_the_same_thing_twice():
    """A narrow column. "SDI Live UDEF (SDI Live UDEF)" helps nobody."""
    assert W._supplier_cell("SDI Live UDEF", "SDI Live UDEF") == "SDI Live UDEF"
    assert W._supplier_cell("Elite Sourcing via SDI Live UDEF", "SDI Live UDEF") \
        == "Elite Sourcing via SDI Live UDEF"


# ── one module owns the translation ──────────────────────────────────────────────────────

def test_the_sentence_an_estimator_reads_uses_the_same_names():
    """stated_prices wrote "SDI system cost via udef_sqlserver" — a connector key put in
    front of the person deciding whether to trust the number. The sheet, the report and that
    sentence must not call one source three things."""
    import stated_prices
    assert stated_prices._system_name("udef_sqlserver") == "SDI Live UDEF"


def test_resolve_hands_back_the_rung_and_not_only_the_prose():
    """The caller that must STAMP which system priced the line had nothing to stamp but a
    sentence, so it stamped a constant — "roll_goods_catalogue" — whichever way the price
    arrived. That constant is what classified Howard's stated figure as a catalogue row."""
    import stated_prices
    out = stated_prices.resolve("NOTHING-PRICES-THIS-CODE-AT-ALL")
    assert "source" in out, "the rung is part of the answer, not a detail of its wording"
