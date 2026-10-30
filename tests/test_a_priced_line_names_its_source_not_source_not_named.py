"""A priced line names its source — the £1.20 clip does not read "source not named".

11762-17's PERFO clip is a class-word bought-in ("STD PART") minted in wb_populate from the
DB-free commodity table at £1.20. Its provenance row carries the engine's own source token,
"standard_commodity_provisional". Two things had to be true for the report's Source column to
say something an estimator can act on:

  1. the minted bought-in has to be IN the AI Price Provenance tab at all — it lives on
     canonical_part_estimates, and the tab writer had been reading the pre-canonical list, so
     the clip carried a price on the sheet and NO provenance row, and the report read that
     absence as "source not named"; and
  2. the raw token has to be said in words — "standard_commodity_provisional" is the machine's
     record, not something to print at an estimator, and "config rate card" (the old fallback)
     claimed a firmness the line does not have.

This pins the report half: the engine token is translated to a readable INDICATIVE phrase and
returned, never "source not named", and never the raw token.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimate_explained as ee  # noqa: E402


def _clip_row():
    # what the report hands _price_source for the clip: a priced class-word BOM line
    return {"code": "STD PART", "text": "STD PART PERFO PLASTIC LOCKING CLIP",
            "price": 1.20, "supplier": ""}


def test_the_commodity_token_is_said_in_words():
    worded = ee._humanise_source("standard_commodity_provisional")
    assert "INDICATIVE" in worded
    assert "standard_commodity_provisional" not in worded          # never the raw token
    # the same phrase whether the tab wrote underscores or a human typed spaces
    assert ee._humanise_source("standard commodity provisional") == worded


def test_the_old_config_rate_card_label_is_gone():
    worded = ee._humanise_source("config rate card")
    assert "config rate card" not in worded.lower()
    assert "INDICATIVE" in worded


def test_the_priced_clip_names_a_source_from_its_provenance_row():
    prov = {"STD PART": {"Price Source": "standard_commodity_provisional",
                         "Supplier": ""}}
    out = ee._price_source(_clip_row(), prov)
    assert "source not named" not in out.lower()
    assert "standard_commodity_provisional" not in out             # not the raw token
    assert "INDICATIVE" in out


def test_a_market_ai_token_is_worded_not_re_wrapped_with_the_raw_token():
    prov = {"BI-BRACKET": {"Price Source": "market_ai_indicative", "Supplier": ""}}
    row = {"code": "BI-BRACKET", "text": "BI-BRACKET STEEL ANGLE", "price": 3.40,
           "supplier": ""}
    out = ee._price_source(row, prov)
    assert "market_ai_indicative" not in out                       # raw token never printed
    assert "market" in out.lower()                                 # still says what it is


def test_a_named_supplier_still_leads_over_the_engine_token():
    # a real catalogue supplier on the row must win over the provenance token
    prov = {"BI-BEARING": {"Price Source": "standard_commodity_provisional",
                           "Supplier": "SKF"}}
    row = {"code": "BI-BEARING", "text": "BI-BEARING", "price": 1.42, "supplier": "SKF"}
    out = ee._price_source(row, prov)
    assert "SKF" in out


def test_an_unlabelled_line_still_says_source_not_named():
    # nothing to translate, nothing on the row — the loud honest answer is unchanged
    prov = {}
    row = {"code": "BI-MYSTERY", "text": "BI-MYSTERY WIDGET", "price": 5.0, "supplier": ""}
    out = ee._price_source(row, prov)
    assert "source not named" in out.lower()
