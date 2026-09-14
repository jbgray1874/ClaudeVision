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


# ── and the rate is applied where the part is BORN, not in one branch ────────────────────
#
# THE CALL SITE, WHICH IS THE WHOLE OF WHY THIS KEPT NOT LANDING. The table was consulted in
# estimate_part under records whose `source` is "sdi_bom_code_unpriced". The wood screw and
# the M4 are not those: their line on the sheet reads a bare "MATERIAL UNPRICED: enter a unit
# rate" with none of the price-chain account that branch appends, which is how we know it
# never ran for them. Tests were green and the sheet still shipped £0.00.
#
# _bought_in_part_stub is the one place a purchased part is born — every reader comes through
# it, which is why the manufacturer reference is captured there. A rate we already hold
# belongs in the same place.

from estimator import _bought_in_part_stub                                # noqa: E402


def test_the_wood_screw_is_priced_at_the_moment_it_is_created():
    stub = _bought_in_part_stub("STD PART", "3.5x19mm WOOD SCREW", 6)
    assert stub["unit_cost_gbp"] == 0.03
    assert stub["extended_total_cost_gbp"] == 0.18
    assert stub["source"] == "standard_commodity_provisional"


def test_the_m4_is_too():
    stub = _bought_in_part_stub("FIXING", "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK", 4)
    assert stub["unit_cost_gbp"] == 0.08
    assert stub["extended_total_cost_gbp"] == 0.32


def test_the_new_line_says_whose_rate_it_is():
    stub = _bought_in_part_stub("STD PART", "3.5x19mm WOOD SCREW", 6)
    assert any("SDI trade rate" in str(f) for f in stub["review_flags"])


def test_a_price_the_caller_already_found_is_never_overwritten():
    """LAST RESORT, NOT FIRST. A UDEF or catalogue rate is real evidence; this is a floor."""
    stub = _bought_in_part_stub("FIXING125", "M8 GLIDE WOOD SCREW", 2)
    stub["unit_cost_gbp"] = 1.75           # what the caller would set from the catalogue
    again = _bought_in_part_stub("FIXING125", "M8 GLIDE WOOD SCREW", 2)
    assert again["unit_cost_gbp"] == 0.03, "with no price of its own the floor applies"
    assert stub["unit_cost_gbp"] == 1.75, "a price already found is left alone"


def test_a_part_the_table_does_not_know_is_born_unpriced_as_before():
    stub = _bought_in_part_stub("P/P", "10.1 DIA BUMPON TRANSPARENT; REF: PD.2120", 6)
    assert stub.get("unit_cost_gbp") in (None, 0, 0.0)
    assert stub.get("source") != "standard_commodity_provisional"


def test_the_quantity_is_the_line_s_own():
    for q in (1, 4, 6, 20):
        stub = _bought_in_part_stub("STD PART", "3.5x19mm WOOD SCREW", q)
        assert stub["extended_total_cost_gbp"] == round(0.03 * q, 2), q


# ── and it must never answer for a commercial allowance ──────────────────────────────────
#
# THE REGRESSION THIS PINS, WHICH REACHED A LIVE RUN. PACKAGING and DELIVERY are not bought-in
# components: they are per-order allowances owned by commercial_lines and
# COMMERCIAL_LINE_GBP_PER_ORDER, which is HELD EMPTY BY DECISION until the estimators' own
# figures land. The placeholder reads "Packaging (box / pallet — per-unit share)", the PALLET
# entry matched the word "pallet" inside it, and the line came out at £12.00 — a figure nobody
# had agreed, on the one line the config comment says must stay at an honest zero.

def test_the_packaging_placeholder_is_never_priced_from_the_component_table():
    stub = _bought_in_part_stub(
        "PACKAGING", "Packaging (box / pallet — per-unit share, estimator to price)", 1)
    assert stub.get("unit_cost_gbp") in (None, 0, 0.0)
    assert stub.get("source") != "standard_commodity_provisional"
    assert stub.get("_commercial_line") is True


def test_nor_is_delivery():
    stub = _bought_in_part_stub(
        "DELIVERY", "Delivery (per-unit share of order haulage — estimator to price)", 1)
    assert stub.get("unit_cost_gbp") in (None, 0, 0.0)
    assert stub.get("_commercial_line") is True


def test_a_real_pallet_on_the_bill_of_materials_still_prices():
    """THE EDGE THE GUARD MUST NOT CROSS. A pallet the display is BUILT ON is a component and
    has a provisional; a pallet mentioned in a packaging allowance's placeholder text is not."""
    stub = _bought_in_part_stub("STD PART", "PALLET, 1200x1000", 1)
    assert stub["unit_cost_gbp"] == 12.00
    assert not stub.get("_commercial_line")


def test_the_screws_are_unaffected_by_the_guard():
    assert _bought_in_part_stub("STD PART", "3.5x19mm WOOD SCREW", 6)["unit_cost_gbp"] == 0.03
    assert _bought_in_part_stub(
        "FIXING", "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK", 4)["unit_cost_gbp"] == 0.08
