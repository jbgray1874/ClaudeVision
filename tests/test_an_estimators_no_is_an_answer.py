"""Two ways a settled answer kept reading as an open question — Tony's 11908-21 review.

"Delivery is not required ( I think you are removing this)" — and the sheet still said
"NOT YET PRICED: enter the per-unit figure" on every run. Not removed: RECORDED. The
line stays at a deliberate £0 naming whose call it was, and comes off the outstanding
list for good.

And the quotation went out headed "QTY FILL ANY OPEN GAPS ON CORNERS WITH MATCHING WAX"
— a drawing note the extractor filed as the title, printed as the PRODUCT NAME on a
customer document. A product name names a thing; an instruction commands one.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")


# ── delivery not required is a decision, recorded through the answers file ──────────────

def test_the_answers_file_carries_the_exclusion():
    import estimator_confirmed as ec
    out, problems = ec._read_decisions(
        {"estimator_decisions": {"commercial_excluded": ["delivery"]}}, "x")
    assert out.get("commercial_excluded") == ["DELIVERY"], (out, problems)
    assert not problems


def test_an_unknown_line_code_is_reported_not_swallowed():
    import estimator_confirmed as ec
    out, problems = ec._read_decisions(
        {"estimator_decisions": {"commercial_excluded": ["POSTAGE"]}}, "x")
    assert "commercial_excluded" not in out
    assert any("POSTAGE" in p for p in problems)


def test_an_excluded_line_is_nil_by_design_everywhere():
    from costed_facts import _price_origin
    from estimator_inputs import unpriced_reason_for_row
    line = {"part_number": "DELIVERY", "_commercial_placeholder": True,
            "_commercial_excluded": True}
    origin = _price_origin(line, "commercial", None, None, 0.0, None, False)
    assert origin["firmness"] == "nil" and origin["owner"] == "nobody", origin
    assert "NOT REQUIRED" in origin["label"]
    reason = unpriced_reason_for_row(line)
    assert reason["owner"] == "nobody"
    assert "EXCLUDED" in reason["detail"]


def test_a_plain_held_line_still_asks():
    from costed_facts import _price_origin
    line = {"part_number": "DELIVERY", "_commercial_placeholder": True}
    origin = _price_origin(line, "commercial", None, None, 0.0, None, False)
    assert origin["firmness"] == "unpriced", "no decision means the question stands"


# ── a drawing note is not a product name ─────────────────────────────────────────────────

def test_the_wax_note_is_not_a_title():
    from client_quote_html import _reads_as_an_instruction
    assert _reads_as_an_instruction(
        "QTY FILL ANY OPEN GAPS ON CORNERS WITH MATCHING WAX")
    assert _reads_as_an_instruction("DO NOT SCALE FROM DRAWING")
    assert _reads_as_an_instruction("Refer to individual component drawings")


def test_real_product_names_pass():
    from client_quote_html import _reads_as_an_instruction
    for name in ("Sunglasses Tray Large Colour Core",
                 "A4 Table-Top Graphic Holder",
                 "CHECKOUT DIVIDER — LARGE"):   # a product that merely CONTAINS a verb-word
        assert not _reads_as_an_instruction(name), name


# ── the generic manual bucket names its work ─────────────────────────────────────────────

def test_the_manual_row_says_what_the_hands_are_doing():
    """"Manual labour (Acrylic) — 2mm ACRYLIC (10975-02-A01)" gave Howard nothing to
    judge his PACP overlap question against. The row now states the compiler's own work
    (SCRAPED EDGES minted a deburr) and claims nothing about whose department owns it —
    that call is his."""
    from wb_populate import labour_row_description
    rd = labour_row_description("Manual labour (Acrylic)", "ACRYLIC", 2.0,
                                ["10975-02-A01"], work_ops=["deburr",
                                                            "manual_labour_acrylic"])
    assert "[edge scraping / deburr]" in rd, rd


def test_a_specific_operation_row_is_untouched():
    from wb_populate import labour_row_description
    rd = labour_row_description("Linebend", "ACRYLIC", 2.0, ["10975-02-A01"],
                                bends=2, work_ops=["folding"])
    assert "[" not in rd, "only the generic manual bucket needs its work naming"
