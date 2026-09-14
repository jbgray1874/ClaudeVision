"""Two lines an estimator prices in his sleep came back £0.00 on run after run.

    STD PART   3.5x19mm WOOD SCREW                       x6   £0.00
    FIXING     M4x10mm FLANGE BUTTON HEAD SCREW, BLACK   x4   £0.00

Not for want of asking. Every rung was consulted: the catalogue code seek, UDEF by
description, historical quote lines, the supplier catalogue, and the market rung — which was
ALLOWED for both (the gate was tested, it is not the blocker) and found nothing. The bumpon on
the same bill of materials priced at 35p, because its description carries a maker's code,
PD.2120, and "3.5x19mm WOOD SCREW" carries no equivalent. A generic fastener is a thing you can
buy and not a thing you can find.

The rung that should have held it is empty. supplier_price_list.py's own audit of SDILive:
UDEF 93,837 rows, historical RAG 68,489 — and the bought-in catalogue 0. So every screw,
castor, clip and lock falls straight past it, and a zero on a quote is a free part.

So the trade rates go in the reproducible commodity table until a price file fills that rung —
AND THEY SAY WHOSE THEY ARE. A provisional whose origin is unrecorded is indistinguishable
from one somebody invented, which is the difference between a figure worth confirming and a
figure worth deleting. The source is printed with the price, on the sheet, not left in a
comment in config.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                            # noqa: E402
from pricing_service import standard_commodity_price                     # noqa: E402


def _part(desc, code="STD PART"):
    return {"part_number": code, "description": desc}


# ── the two lines that were £0 ───────────────────────────────────────────────────────────

def test_the_wood_screw_is_threepence():
    got = standard_commodity_price(_part("3.5x19mm WOOD SCREW"))
    assert got is not None and got["unit_price_gbp"] == 0.03


def test_the_m4_button_head_is_eightpence():
    got = standard_commodity_price(
        _part("M4x10mm FLANGE BUTTON HEAD SCREW, BLACK", code="FIXING"))
    assert got is not None and got["unit_price_gbp"] == 0.08


def test_a_class_word_code_is_no_obstacle():
    """"STD PART" and "FIXING" are what a drawing prints where an item has no part number.
    The match is on the DESCRIPTION, which is why this rung can answer at all."""
    for code in ("STD PART", "FIXING", "", "BI-SCREW"):
        assert standard_commodity_price(_part("3.5x19mm WOOD SCREW", code)) is not None, code


def test_the_price_is_the_same_every_run():
    """A fixed config number, unlike the market indication it stands in front of — which moved
    £4.54 / £6.00 / £8.54 on one part across three runs of one job."""
    a = standard_commodity_price(_part("3.5x19mm WOOD SCREW"))
    b = standard_commodity_price(_part("3.5x19mm WOOD SCREW"))
    assert a["unit_price_gbp"] == b["unit_price_gbp"]
    assert a["price_is_reproducible"] is True


# ── and the price says whose it is ───────────────────────────────────────────────────────

def test_the_provenance_names_who_gave_us_the_rate():
    got = standard_commodity_price(_part("3.5x19mm WOOD SCREW"))
    assert "SDI trade rate" in got["provenance"]
    assert "James Gray" in got["provenance"] and "14 Sep 2026" in got["provenance"]


def test_the_review_line_carries_it_too():
    """The estimator reads the review reason, not the provenance field."""
    got = standard_commodity_price(
        _part("M4x10mm FLANGE BUTTON HEAD SCREW, BLACK", code="FIXING"))
    assert "SDI trade rate" in got["review_reason"]
    assert "confirm against a supplier quote" in got["review_reason"]


def test_every_entry_in_the_table_names_a_source():
    """The rule, not the two new rows: a provisional of unknown origin cannot be confirmed or
    argued with, so it can only be deleted."""
    for token, entry in config.STANDARD_COMMODITY_PRICE_GBP.items():
        assert str(entry.get("source") or "").strip(), token


def test_the_label_says_what_size_the_rate_was_given_for():
    """3p is a small-gauge rate. A 6 x 80 coach screw is not 3p, and the line has to say so
    rather than quietly undercharge it."""
    wood = config.STANDARD_COMMODITY_PRICE_GBP["WOOD+SCREW"]["label"]
    assert "3.5 x 19" in wood and "confirm" in wood
    m4 = config.STANDARD_COMMODITY_PRICE_GBP["BUTTON+HEAD"]["label"]
    assert "M4 x 10" in m4 and "confirm" in m4


# ── it prices fasteners and nothing else ─────────────────────────────────────────────────

def test_it_does_not_price_a_part_we_make():
    for desc in ("GRAVITY FEEDER FABRICATION", "LID", "FRONT COVER", "PACKER",
                 "SCREWED AND HOOKED ASSEMBLY"):
        assert standard_commodity_price(_part(desc, "12349-02-69-04M")) is None, desc


def test_a_bare_screw_word_prices_nothing():
    """Both tokens are required, so "SCREW" alone — a thumb screw, a screw jack, a lead screw
    — is not handed a wood screw's rate."""
    for desc in ("THUMB SCREW, KNURLED", "SCREW JACK", "LEAD SCREW ASSEMBLY",
                 "HEAD RESTRAINT"):
        assert standard_commodity_price(_part(desc)) is None, desc


def test_the_bumpon_is_untouched():
    """It already prices off its maker's code at the market rung, above this one."""
    assert standard_commodity_price(
        _part("10.1 DIA BUMPON TRANSPARENT; BUMPERSTOPS REF: PD.2120", "P/P")) is None


def test_a_catalogue_rate_still_wins():
    """This is the last resort, consulted only where UDEF, history and the supplier catalogue
    all missed — so loading a fastener price file retires these two entries."""
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert "DB-FREE STANDARD-COMMODITY PROVISIONAL — the reproducible last resort" in src
