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


# ── nor is a part number a description ───────────────────────────────────────────────────
#
# The 12:16 book filled the Description box with "10975-02-GA" — the assembly's own code,
# under a label an estimator asked for so he could tell at a glance WHAT a sheet was for
# when requoting. The number is already in the box beside it. The older guard compared the
# description against the drawing NUMBER and let this through, because "10975-02-GA" and
# "10975-02" are not equal strings — they are one fact in two spellings, which is exactly
# the case worth catching.

def test_a_part_number_is_not_a_description():
    from client_quote_html import _reads_as_a_code
    for code in ("10975-02-GA", "7332-01-001", "0355255", "11908-21", "12349-02-69-GA"):
        assert _reads_as_a_code(code), code


def test_a_product_name_with_a_number_in_it_survives():
    """The separator is required, or the pattern chops any run of letters into code-sized
    pieces and "600mm Shelf" reads as a part number."""
    from client_quote_html import _reads_as_a_code
    for name in ("600mm Shelf", "A4 Table Top Graphic Holder", "Type 2 Bracket",
                 "GRAVITY FEEDER MODULES", "L-STAND", "BASE"):
        assert not _reads_as_a_code(name), name


def test_the_pack_filename_names_the_unit_when_no_record_can():
    """Howard's pack knows what it is. Refusing the code-shaped title lets the stem
    fallback — which was always there — finally have its turn."""
    from client_quote_html import _drawing_identity
    summary = {
        "llm_full_extract": {"drawing_info": {"drawing_number": "10975-02",
                                              "revision": "B"}},
        "estimate_summary": {"canonical_route_shadow": {
            "top_assemblies": ["10975-02-GA"], "top_assembly": "10975-02-GA",
            "nodes": [{"part_number": "10975-02-GA", "description": "10975-02-GA"}]}}}
    num, rev, title = _drawing_identity(
        summary, "0355255 - A4 Table Top Graphic Holder - 10975_REV B.pdf")
    assert (num, rev) == ("10975-02", "Rev B")
    assert title == "A4 Table Top Graphic Holder", title


def test_the_office_half_of_a_pack_name_is_trimmed_from_both_ends():
    """Tony's pack brackets the product with filing: job number and role in front, revision
    behind. Only whole tokens at the ENDS come off."""
    from client_quote_html import _drawing_identity
    _, _, title = _drawing_identity(
        {"llm_full_extract": {"drawing_info": {"drawing_number": "11908-21"}}},
        "0359967_-_11908-21-GA_-_Rev_A_Sunglsses_Tray_Large_Colour_Core.pdf")
    assert title == "Sunglsses Tray Large Colour Core", title


def test_a_word_inside_the_name_is_never_trimmed():
    from client_quote_html import _drawing_identity
    _, _, title = _drawing_identity({}, "11350-BootsLadderRackCommsBar")
    assert title == "Boots Ladder Rack Comms Bar", title


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


# ── a stale market stamp cannot mask the stated method ───────────────────────────────────

def test_cost_source_always_joins_the_witness_pool():
    """The 11:19 report called Howard's stated method "an AI market indication" three
    sections after the sheet said "Stated method + SDI Live": the stub carried BOTH the
    stated cost_source and a stale market stamp on its material_estimate, and the
    or-chain let the stale stamp mask the stub's own classification."""
    from costed_facts import _price_origin, INDICATIVE_HOUSE
    pkg = {"part_number": "PACKAGING", "_commercial_placeholder": True,
           "cost_source": "stated_method_system_priced",
           "material_estimate": {"cost_method": "market_ai_indicative"}}
    origin = _price_origin(pkg, "commercial", None, 1.91, 1.91, None, False)
    assert origin["class"] == "stated_method", origin
    assert origin["firmness"] == INDICATIVE_HOUSE


# ── the early quantity probe cannot cross-pollinate jobs ─────────────────────────────────

def _folder(tmp_path, pdfs, answers):
    for n in pdfs:
        (tmp_path / n).write_text("x")
    for n in answers:
        (tmp_path / n).write_text("{}")
    return tmp_path


def test_one_job_one_file_is_consulted(tmp_path):
    from file_scan import _answers_file_for_order_qty
    d = _folder(tmp_path, ["0355255_GA_10975_REV_B.PDF"], ["10975-02_confirmed.json"])
    f = _answers_file_for_order_qty(d, d / "0355255_GA_10975_REV_B.PDF")
    assert f is not None and f.name == "10975-02_confirmed.json"


def test_several_jobs_one_file_is_refused_without_a_name_match(tmp_path):
    """The 16 Sep review's exact hazard: one file in a folder of several jobs would
    apply its order quantity to every job before their drawing numbers are known."""
    from file_scan import _answers_file_for_order_qty
    d = _folder(tmp_path, ["11111-01_GA.pdf", "22222-01_GA.pdf"],
                ["33333-01_confirmed.json"])
    assert _answers_file_for_order_qty(d, d / "11111-01_GA.pdf") is None


def test_a_positive_name_match_earns_trust_in_a_shared_folder(tmp_path):
    from file_scan import _answers_file_for_order_qty
    d = _folder(tmp_path, ["12349-02-69-GA_RevA.pdf", "99999-01_GA.pdf"],
                ["12349-02_confirmed.json"])
    f = _answers_file_for_order_qty(d, d / "12349-02-69-GA_RevA.pdf")
    assert f is not None and f.name == "12349-02_confirmed.json"


def test_two_answers_files_are_never_guessed_between(tmp_path):
    from file_scan import _answers_file_for_order_qty
    d = _folder(tmp_path, ["a.pdf"], ["one_confirmed.json", "two_confirmed.json"])
    assert _answers_file_for_order_qty(d, d / "a.pdf") is None
