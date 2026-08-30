"""The manufacturer's own number is read, kept, and looked up ON.

11650's purchased parts are named on the sheet the way the supplier names them: "ESSENTRA
FOOT-466122", "246.41.745", "KSM4----N3--5A0". Those numbers are the supplier's primary key
and every one of them was read and thrown away. The bought-in recogniser minted its own code
instead --

    code_guess = "BI-" + re.sub(r"[^A-Z0-9]", "", phrase.upper())[:18]

-- and BI-BINDINGSCREW is a key that exists nowhere: not in UDEF, not in any price file, not
at any supplier. The exact-match arm of every lookup therefore missed BY CONSTRUCTION, on
every run, and the feet and knobs and catches came out at GBP 0.00 while the number that
would have priced them sat unread in the description they were printed in.

WHAT MAKES THE MATCHING RULES AFFORDABLE. Everything recognised here is used for EXACT
lookups only. A false candidate costs one query that returns nothing; a missed one costs a
real price. That asymmetry is the design, and the tests below hold both ends of it: the
shapes are recognised generously, and the things that merely LOOK like references -- every
dimension, count, revision and price on a drawing -- are refused.

THE RULES ARE SHAPES AND CONTEXTS, NEVER NAMES. Nothing here knows a supplier, a job or a
prefix learned from one drawing. That is the whole test: a supplier nobody has bought from
yet must be read correctly on the first job that names them.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import supplier_reference as sr                                       # noqa: E402


def _refs(text, **kw):
    return [(r["reference"], r["convention"]) for r in sr.find_references(text, **kw)]


def _found(text, **kw):
    return [r for r, _ in _refs(text, **kw)]


# ── the conventions, on the real spellings ──────────────────────────────────────────
@pytest.mark.parametrize("text,expected,convention", [
    # A number printed beside the word for what it is. The reference is only recoverable by
    # looking INSIDE the token, and looking inside was the whole of what was missing.
    ("ESSENTRA FOOT-466122", "466122", sr.BARE),
    # Häfele and most European article numbers. Unmistakable at three groups; see below for
    # why two is refused.
    ("HINGE 246.41.745 NICKEL", "246.41.745", sr.DOTTED),
    # A configurator pads its unset options with dashes -- MISUMI, Festo, SMC all do it.
    ("SLIDE KSM4----N3--5A0", "KSM4----N3--5A0", sr.CONFIGURED),
    # A short alpha prefix over a serial.
    ("DWG491667 CATCH", "DWG491667", sr.PREFIXED),
])
def test_each_convention_is_read_off_the_text_it_appears_in(text, expected, convention):
    assert _refs(text) == [(expected, convention)]


def test_a_reference_the_drawing_labels_needs_no_shape_at_all():
    """The strongest evidence a sheet can offer is saying so. Held to the five-digit floor
    built for UNLABELLED digit runs, "PART No. 4661" would be refused -- which is the engine
    ignoring the clearest statement available to it."""
    assert _refs("PART No. 4661 BINDING SCREW") == [("4661", sr.DECLARED)]


@pytest.mark.parametrize("label", ["PART No.", "Part Number", "MPN", "Order code",
                                   "Cat No:", "Article No.", "Supplier ref", "P/N"])
def test_the_label_is_recognised_however_the_drawing_punctuates_it(label):
    """A drawing punctuates this differently every time and it is the same fact each time.
    Matching the literal string would make recognition depend on a full stop."""
    assert _found(f"{label} 4661 SCREW") == ["4661"]


def test_two_references_in_one_description_are_both_kept():
    assert _found("CATCH 246.41.745 AND FOOT-466122") == ["246.41.745", "466122"]


def test_the_strongest_evidence_is_offered_first():
    """lookup_keys tries these in order, so the order IS which query runs first."""
    out = sr.find_references("PART No. 999111 SEE ALSO DWG491667")
    assert [r["convention"] for r in out] == [sr.DECLARED, sr.PREFIXED]
    assert out[0]["rank"] > out[1]["rank"]


# ── everything on a drawing that is a number and is not a part number ───────────────
# This is where the module earns its keep. A sheet is mostly digits, and every one of these
# would become a lookup key under a rule that read shape alone.
@pytest.mark.parametrize("text", [
    "1200 X 600 X 2MM PETG",          # a blank size
    "PANEL 12500 X 2500",             # a size big enough to clear the digit floor
    "12000MM LENGTH",                 # a dimension carrying its unit
    "QTY 25000 OFF",                  # a count
    "REV 12345",                      # a revision
    "TOLERANCE 0.15",                 # a tolerance
    "PRICE £12500",                   # money
    "SHEET 202512",                   # a year-month stamp reads as a six-digit serial
    "BOLT M6 X 25 BZP",               # a thread and a length
    "BINDING SCREW BZP",              # no number at all
    "PART No. 1200 MM",               # LABELLED, and still a dimension
])
def test_a_number_doing_something_else_is_not_a_reference(text):
    assert _refs(text) == [], f"{text!r} yielded a lookup key"


def test_two_dotted_groups_are_a_decimal_and_are_refused():
    """"246.41.745" is unmistakable. "246.41" is a number, and there is no way to tell it from
    one -- accepting it would read every price, thickness and tolerance as an article number.
    Three groups is the line, and it is drawn here so it cannot drift.

    THE CASE HAS TO CARRY ENOUGH DIGITS TO REACH THE GROUP RULE. Asserted first on "246.41",
    this passed against a mutant that accepted two groups -- because five digits fails the
    length floor before the group count is ever consulted, so the test was green for a reason
    that had nothing to do with what it claimed to check. A two-group number long enough to
    clear the floor is the only shape that actually asks the question, and a total or a weight
    on a sheet is exactly that shape."""
    assert _found("TOTAL 12345.67") == []
    assert _found("HINGE 246.41.745") == ["246.41.745"]


def test_a_dotted_reference_still_has_to_be_long_enough_to_be_one():
    """Three groups of one digit is a paragraph number, a scale or a date, not an article."""
    assert _found("SEE 1.2.3") == []


def test_an_unlabelled_four_digit_run_is_below_the_floor():
    """Four-digit runs are years, counts, drawing sizes and -- above all -- millimetres, which
    appear on every sheet in the building. Five is where catalogue numbers start. The context
    guards catch the ones that carry a unit or a cue word; the floor catches the rest, and
    "1250" beside a word the unit list does not know is exactly the rest."""
    assert _found("SHELF AT 1250 HEIGHT") == []
    assert _found("SHELF AT 12507 HEIGHT") == ["12507"]


def test_the_label_lowers_the_length_floor_and_waives_nothing_else():
    """A digit run is the one shape that collides with a dimension, and it collides whatever
    word sits in front of it. If the label waived the measurement guard, "PART No. 1200 MM"
    would become a lookup key -- and worse, a plausible one."""
    assert _found("PART No. 4661 SCREW") == ["4661"]         # floor lowered
    assert _found("PART No. 4661 MM") == []                  # guard still applied


def test_a_dimension_is_refused_from_both_ends():
    """A multiplier sits on either side of the number it bounds, so "12500 X 2500" is one
    dimension read from two directions. A rule that looks only backwards passes the first
    number and only the second."""
    assert _found("12500 X 2500") == []
    assert _found("2500 X 12500") == []


# ── our own numbering is never a supplier's ─────────────────────────────────────────
def test_an_sdi_drawing_number_is_never_offered_as_a_supplier_key():
    """Offering one would send SDI's own part numbers to a supplier. Asked of the WHOLE token
    before any splitting, because 11650-04-01A only looks like a drawing number while it is
    still in one piece -- split on its dashes it is a five-digit "serial" and two counts."""
    assert _found("11650-04-01A SIDE PANEL") == []
    assert _found("11650-04-01A-HANDED") == []


@pytest.mark.parametrize("code", ["FIXING125", "ELECTRICS001", "VINYL76", "SUBPLAS72"])
def test_sdis_own_catalogue_codes_are_not_manufacturer_references(code):
    """These are keys this engine already holds and routes elsewhere. Reading them as
    manufacturer references would key the lookup on the wrong catalogue."""
    assert _found(f"{code} SOMETHING") == []


def test_a_short_prefix_over_a_long_serial_still_gets_through():
    """DWG491667 satisfies the SDI catalogue shape too -- alpha run, then digits, exactly as
    ELECTRICS001 does. The prefixed convention is the NARROWER claim (two to four letters,
    four or more digits), so where both match it decides. Ordering the two tests the other way
    round silently drops every reference of this shape."""
    assert _found("DWG491667") == ["DWG491667"]
    assert _found("ELECTRICS001") == []


def test_the_jobs_own_part_numbers_are_excluded_when_offered():
    assert _found("SEE 466122", known_part_numbers=["466122"]) == []
    assert _found("SEE 466122", known_part_numbers=["11650-01"]) == ["466122"]


def test_a_configured_code_is_not_shredded_into_its_options():
    """Looking inside a token is a SECOND pass, run only when the whole token means nothing.
    Run first, it would break KSM4----N3--5A0 into three fragments and lose the code."""
    assert _found("KSM4----N3--5A0") == ["KSM4----N3--5A0"]


# ── a key we invented is not a key anybody else has ─────────────────────────────────
def test_a_minted_key_says_it_was_minted():
    assert sr.is_synthesised_key(sr.synthesise_key("binding screw"))
    assert not sr.is_synthesised_key("466122")
    assert not sr.is_synthesised_key("FIXING125")


def test_minting_is_stable_and_bounded():
    """The code is a dictionary key across readers within a run; if it moved, the dedup that
    stops a part being recognised twice would stop working."""
    assert sr.synthesise_key("Binding Screw") == sr.synthesise_key("BINDING SCREW")
    assert len(sr.synthesise_key("a" * 90)) == len(sr.SYNTHESISED_KEY_PREFIX) + 18


def test_a_real_code_is_tried_first_and_a_minted_one_last():
    """THE WHOLE CHANGE, IN ONE ASSERTION. A code read off a drawing is the best key there
    is and a code minted here is the worst, and until now they were the same field and were
    tried the same way."""
    minted = {"part_number": sr.synthesise_key("binding screw"),
              "supplier_references": [{"reference": "466122"}]}
    assert sr.lookup_keys(minted)[0] == "466122"
    assert sr.lookup_keys(minted)[-1] == minted["part_number"]

    real = {"part_number": "FIXING125", "supplier_references": [{"reference": "466122"}]}
    assert sr.lookup_keys(real) == ["FIXING125", "466122"]


def test_a_part_with_nothing_at_all_yields_no_keys():
    assert sr.lookup_keys({}) == []


def test_the_report_can_tell_the_two_kinds_of_nothing_apart():
    """"No price found" hides two different problems. One of them is ours."""
    tried = sr.describe_keys({"part_number": "BI-X", "supplier_references": [{"reference": "466122"}]})
    none_found = sr.describe_keys({"part_number": sr.synthesise_key("binding screw")})
    assert "466122" in tried
    assert "synthesised" in none_found and "no manufacturer reference" in none_found


# ── attached where a purchased part is BORN, not per reader ─────────────────────────
def test_attaching_reads_the_description_and_records_the_minting():
    part = sr.attach_references({"part_number": sr.synthesise_key("essentra foot"),
                                 "description": "ESSENTRA FOOT-466122"})
    assert [r["reference"] for r in part["supplier_references"]] == ["466122"]
    assert part["part_number_is_synthesised"] is True


def test_a_reference_already_recorded_is_never_overwritten():
    """A reference off a supplier's own feed outranks anything recovered from a description,
    and the recovery runs later than the feed."""
    part = sr.attach_references({"part_number": "X", "description": "FOOT-466122",
                                 "supplier_references": [{"reference": "AUTHORITATIVE"}]})
    assert [r["reference"] for r in part["supplier_references"]] == ["AUTHORITATIVE"]


def test_a_real_part_number_is_not_re_read_as_a_reference_to_itself():
    part = sr.attach_references({"part_number": "FIXING125", "description": "POP RIVET"})
    assert not part.get("supplier_references")
    assert part["part_number_is_synthesised"] is False


# ── the wiring. built is not wired, and this codebase keeps proving it ──────────────
_RECOGNISER = Path(sr.__file__).with_name("bought_in_recogniser.py").read_text(encoding="utf-8")
_ESTIMATOR = Path(sr.__file__).with_name("estimator.py").read_text(encoding="utf-8")
_PRICING = Path(sr.__file__).with_name("pricing_service.py").read_text(encoding="utf-8")


def _calls(source: str, name: str) -> int:
    """Call sites of `name`, counted in the PARSED module rather than its text.

    A guard that greps raw text fails on the comment explaining the thing it forbids -- this
    repository has been caught by that four times. Asking the syntax tree cannot be fooled by
    prose, and cannot be satisfied by prose either.
    """
    found = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        label = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if label == name:
            found += 1
    return found


def test_the_recogniser_mints_through_the_module_that_can_answer_for_it():
    """The prefix used to be written inline, which made it a spelling rather than a fact:
    nothing downstream could ask whether a part number had been read or invented."""
    assert _calls(_RECOGNISER, "synthesise_key") >= 1
    tree = ast.parse(_RECOGNISER)
    inline = [n for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and n.value == sr.SYNTHESISED_KEY_PREFIX]
    assert not inline, "the minting prefix is still written literally in the recogniser"


def test_every_bought_in_reader_inherits_the_capture():
    """Four readers find purchased parts -- the catalogue layer, the prose recogniser, the
    note scan and the BOM rows -- and all four build the part through one stub. Capturing per
    reader is how three of them would have gone on discarding the reference."""
    assert _calls(_ESTIMATOR, "attach_references") >= 1
    stub = next(n for n in ast.walk(ast.parse(_ESTIMATOR))
                if isinstance(n, ast.FunctionDef) and n.name == "_bought_in_part_stub")
    assert _calls(ast.unparse(stub), "attach_references") == 1, \
        "the capture is not inside the stub builder, so a reader that skips it loses the key"


def test_the_price_lookup_actually_asks_for_the_reference():
    """CORRECT EVIDENCE WITH NO READER IS THE DEFECT THIS ENGINE KEEPS REPEATING. Capturing
    466122 and continuing to query BI-BINDINGSCREW would leave every symptom exactly where it
    was, with a new field in the JSON to suggest otherwise."""
    assert _calls(_PRICING, "lookup_keys") >= 1


# THE CODE, NOT THE PROSE ABOUT THE CODE. Every guard below reads the PARSED body of
# _get_udef_anchor. ast.unparse drops comments entirely, so a paragraph explaining why a
# fuzzy match would be dangerous can no longer satisfy -- or trip -- a check looking for one.
# This file was written the other way first and the LIKE-refusing guard failed on its own
# explanation of the LIKE it permits. That is the fifth time this repository has been caught
# by the same trap, and it is the last place it can happen here.
_ANCHOR_NODE = next(n for n in ast.walk(ast.parse(_PRICING))
                    if isinstance(n, ast.FunctionDef) and n.name == "_get_udef_anchor")
_ANCHOR = ast.unparse(_ANCHOR_NODE)
_UDEF_QUERIES = [n.value for n in ast.walk(_ANCHOR_NODE)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and "FROM dbo.UDEF" in n.value]


def _sole_query(*needles):
    hits = [q for q in _UDEF_QUERIES if all(n in q for n in needles)]
    assert len(hits) == 1, f"expected exactly one query matching {needles}, found {len(hits)}"
    return hits[0]


def test_the_reference_arm_matches_exactly_and_never_loosely():
    """The whole safety argument for the exact arm rests on this. A reference recovered from a
    description is a guess about which characters are the key; matched with LIKE against a
    part code it could attach a hinge's price to a foot. Matched exactly it finds that article
    number or it finds nothing."""
    arm = _sole_query("[Part code] = LTRIM(RTRIM(?)) AND")
    assert "LIKE" not in arm.upper(), "the manufacturer-reference arm has acquired a fuzzy match"


# ── and the estimator can SEE which of the two kinds of nothing they have ───────────
# A supplier_references field that appears only in the JSON is the same defect this engine
# keeps repeating: correct evidence with no reader.
import job_report_html as jrh                                        # noqa: E402


def _job(parts):
    return {"estimate_summary": {"part_estimates": [
        sr.attach_references({"part_number": pn, "description": d, "quantity": 1})
        for pn, d in parts]}}


def test_the_report_names_the_key_each_purchased_line_was_looked_up_by():
    html = jrh._purchased_key_section(_job([
        (sr.synthesise_key("essentra foot"), "ESSENTRA FOOT-466122"),
        (sr.synthesise_key("hafele catch"), "CATCH 246.41.745")]))
    assert "466122" in html and "246.41.745" in html
    assert "dotted_catalogue" in html


def test_a_line_with_no_reference_is_listed_first_and_named_as_ours():
    """The one an estimator must act on, and the one no catalogue can ever fix. A minted key
    is not in any supplier's system, so that line cannot be priced by lookup however good the
    catalogue gets -- and a report that buries it below the ones that worked hides the only
    finding on the page that requires a person."""
    html = jrh._purchased_key_section(_job([
        (sr.synthesise_key("essentra foot"), "ESSENTRA FOOT-466122"),
        (sr.synthesise_key("binding screw"), "BINDING SCREW BZP")]))
    assert html.index("BI-BINDINGSCREW") < html.index("BI-ESSENTRAFOOT"), \
        "the line with no real key is not listed first"
    assert "1 of 2 purchased line(s)" in html
    assert "minted here" in html


def test_the_section_says_so_when_every_line_has_a_real_key():
    """Not silence. A section that vanishes when everything is fine reads as a section that
    failed to run, and this repository has been caught by that distinction repeatedly."""
    html = jrh._purchased_key_section(_job([
        (sr.synthesise_key("essentra foot"), "ESSENTRA FOOT-466122")]))
    assert "Every purchased line carries a manufacturer reference" in html


def test_a_job_with_no_purchased_parts_renders_nothing():
    """Distinct from the case above: there is genuinely no question to answer here, and a
    heading over an empty table on a fabrication-only job is noise."""
    assert jrh._purchased_key_section(_job([("11650-01-01M", "SIDE PANEL")])) == ""


def test_the_section_is_wired_into_the_report_and_not_merely_defined():
    body = ast.unparse(next(n for n in ast.walk(ast.parse(
        Path(jrh.__file__).read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef) and n.name == "_render_verdict"))
    assert "_purchased_key_section" in body, \
        "the section is defined and never called -- built is not wired, again"


# ── a word the text extractor glued onto a code ─────────────────────────────────────
def test_a_word_run_into_a_code_by_the_extractor_is_trimmed_off():
    """11650's BOM cell reads "KSM6----N5--5A0Knob Diameter 19.1 mm" -- the code and the next
    word arrive with no space between them, which is ordinary in extracted PDF text where a
    cell wraps. Every other convention here is a whole-token match and is immune; the
    configured form is recognised by SEARCHING for a double dash, so it swallowed the tail
    and produced a key no supplier has ever published."""
    out = sr.find_references("M6 KNURLED KNOB | KSM6----N5--5A0Knob Diameter 19.1 mm")
    assert [r["reference"] for r in out] == ["KSM6----N5--5A0"]
    assert out[0]["raw_token"] == "KSM6----N5--5A0KNOB", "the trim hid what it removed"


def test_a_code_that_legitimately_ends_in_digits_is_left_alone():
    out = sr.find_references("SLIDE KSM4----N3--5A0")
    assert [r["reference"] for r in out] == ["KSM4----N3--5A0"]
    assert "raw_token" not in out[0]


# ── two lines, one article ──────────────────────────────────────────────────────────
# The cabinet BOM carries the Essentra levelling foot twice, and each line's description
# names the OTHER line's key. Priced without this, the job buys four feet and pays for two
# it never orders -- a visible GBP 0.46 gap turned into a hidden GBP 0.46 over-charge.
_CABINET_BOM = [
    ("ESSENTRA FOOT-466122", "FIXING1081-M8, 25MM FOOT, 25MM THREAD", None),
    ("FIXING1659", "M6 KNURLED KNOB | KSM6----N5--5A0Knob Diameter 19.1 mm", 0.27),
    ("FIXING1081", "Essentra Ref. 466122 - Leveling Foot - Black25.0 mm Threads, M8", 0.22),
    ("FIXING", "Nylon Washer", 0.66),
    ("FIXINGTBC", "M4 KNURLED KNOB [ESSENTRA: KSM4----N3--5A0]", None),
    ("MAG CATCH", "HAFELE 246.41.745", None),
    ("STD PART", "M4 THREADED PEM STUD (LENGTH: 18mm)", None),
]


def _bom():
    return [sr.attach_references({"part_number": pn, "description": d, "quantity": 2,
                                  "unit_cost_gbp": p}) for pn, d, p in _CABINET_BOM]


def test_the_same_article_named_twice_is_found_on_the_real_bom():
    rows = _bom()
    groups = [[rows[i]["part_number"] for i in g] for g in sr.same_article_groups(rows)]
    assert groups == [["ESSENTRA FOOT-466122", "FIXING1081"]]


def test_the_two_knurled_knobs_are_not_the_same_part():
    """THE FAILURE THIS RULE MUST NOT HAVE. M4 and M6 sit beside each other on this sheet:
    same supplier, same words, GBP 0.00 and GBP 0.27. Merging on family or description would
    price the M4 at the M6's rate and nobody would ever see it. An article NUMBER is an
    identity; a description is not."""
    rows = _bom()
    merged = {frozenset(rows[i]["part_number"] for i in g) for g in sr.same_article_groups(rows)}
    assert not any({"FIXING1659", "FIXINGTBC"} <= m for m in merged)


def test_a_bare_stem_does_not_swallow_every_line_that_starts_with_it():
    """"FIXING1081-M8" contains the characters of FIXING1081 and also of FIXING, which is a
    different part on the same sheet -- a nylon washer at GBP 0.66. Substring matching would
    merge every FIXING line on every job into one."""
    rows = _bom()
    for g in sr.same_article_groups(rows):
        assert "FIXING" not in [rows[i]["part_number"] for i in g]


def test_a_part_number_that_is_an_english_word_is_not_hunted_for_in_prose():
    """THE DIRECTION THAT DELETES MONEY. This rule zeroes a line, so a false merge removes
    real cost rather than merely adding noise -- and SDI's own BOM carries POWDER, PACKAGING,
    DELIVERY and FIXING as part numbers. A description reading "PACKAGING FOAM INSERT 50MM"
    contains the word PACKAGING for reasons that have nothing to do with identity; merged on
    it, the foam insert and the packaging share become one line and GBP 1.20 disappears.

    A digit is what separates a code from a word. FIXING1081 is a key; FIXING is a noun."""
    rows = [{"part_number": "PACKAGING", "description": "Packaging (box / pallet share)"},
            {"part_number": "FIXING2000", "description": "PACKAGING FOAM INSERT 50MM"},
            {"part_number": "POWDER", "description": "Powder - from coated surface area"},
            {"part_number": "DELIVERY", "description": "Delivery share of order haulage"}]
    assert sr.same_article_groups(rows) == []


def test_a_real_code_inside_a_description_still_groups():
    """The narrowing must not take the case it was built for with it.

    AND THIS IS THE CASE THAT EXPOSED THE RULE AS DECORATIVE. "FIXING1081-M8, 25MM FOOT"
    tokenises greedily to FIXING1081-M8, which matches no part number anywhere -- so this
    rule had never once fired. It looked correct because the real BOM pair ALSO shares the
    reference 466122, and the shared-reference path was quietly doing all the work."""
    rows = [{"part_number": "FIXING1081", "description": "Levelling foot M8"},
            {"part_number": "ESSENTRA FOOT", "description": "FIXING1081-M8, 25MM FOOT"}]
    assert sr.same_article_groups(rows) == [[0, 1]]


def test_a_part_number_that_is_a_bare_number_is_not_hunted_for_either():
    """A five-digit part number searched through prose finds every dimension on the sheet --
    and, worse, finds its own job number inside every drawing code that starts with it. The
    letter is what makes a string a code rather than a quantity."""
    rows = [{"part_number": "11650", "description": "JOB"},
            {"part_number": "X9", "description": "SEE 11650-01-01M FOR DETAIL"}]
    assert sr.same_article_groups(rows) == []


def test_lines_with_no_reference_never_group():
    """Two lines that say nothing about their identity are not thereby the same part. This is
    the direction that silently deletes money, so it is asserted rather than assumed."""
    rows = [{"part_number": "A", "description": "BRACKET"},
            {"part_number": "B", "description": "BRACKET"}]
    assert sr.same_article_groups(rows) == []


def test_a_single_line_is_not_a_group():
    assert sr.same_article_groups([{"part_number": "A", "description": "FOOT-466122"}]) == []


def test_three_lines_naming_one_article_form_one_group():
    rows = [{"part_number": "A", "description": "FOOT-466122"},
            {"part_number": "B", "description": "Essentra Ref. 466122"},
            {"part_number": "C", "description": "PART No. 466122 FOOT"}]
    assert sr.same_article_groups(rows) == [[0, 1, 2]]


# ── the writer keeps the money on one line and says so on the other ─────────────────
_WB = Path(sr.__file__).with_name("wb_populate.py").read_text(encoding="utf-8")


def test_the_bom_writer_deduplicates_before_it_writes():
    """Order is the whole safety argument. Dedup after the rows are written changes nothing;
    dedup after pricing double-counts once and then corrects a number nobody re-reads."""
    assert "same_article_groups(bom_parts)" in _WB
    assert _WB.index("same_article_groups(bom_parts)") < _WB.index('row = b["first_row"]')


def test_the_duplicate_line_survives_at_zero_rather_than_disappearing():
    """The drawing really does name the part twice. A line that vanishes between the BOM an
    estimator reads and the sheet they check is how trust in the sheet goes -- so the line
    stays, at zero, naming where its money went."""
    block = _WB[_WB.index("same_article_groups(bom_parts)"):_WB.index('row = b["first_row"]')]
    assert '_dup["unit_cost_gbp"] = 0.0' in block
    assert "_duplicate_of" in block
    assert "del " not in block and ".pop(" not in block and ".remove(" not in block, \
        "the duplicate line is being removed rather than zeroed"


def test_the_priced_line_is_the_one_that_keeps_the_money():
    block = _WB[_WB.index("same_article_groups(bom_parts)"):_WB.index('row = b["first_row"]')]
    assert "_priced[0] if _priced else _grp[0]" in block, \
        "the kept line is not chosen by which one actually carries a price"


def test_the_estimator_is_told_to_check_the_quantity():
    """Two lines naming one article is USUALLY a duplicate and is occasionally a genuine
    mis-numbering of two different fittings. The engine cannot tell those apart, so it says
    what it did and asks -- rather than quietly halving a quantity that was right."""
    assert "CHECK THE QUANTITY" in _WB


# ── the catalogue join that makes the dedup necessary ───────────────────────────────
def test_the_lookup_reads_the_reference_out_of_the_catalogue_description():
    """UDEF's [Part code] is SDI's own code, so the exact arm cannot fire until a supplier
    price file is loaded. The reference is already in the table though -- FIXING1081 reads
    "Essentra Ref. 466122" -- which is exactly what 11650's unpriced "ESSENTRA FOOT-466122"
    line carries. GBP 0.22 a foot, in the catalogue, unreachable because nobody looked at the
    text."""
    _sole_query("u.[Description] LIKE", "TOP 2")


def test_the_description_join_prices_nothing_when_two_rows_match():
    """LIKE is only safe here because exactly one row may match. "Specific" is a judgement;
    "unique" is a fact, and the fact is what decides. Two matches is an ambiguity nobody in
    this process can resolve, and the house rule for that is to price nothing and say so
    rather than pick the dearer."""
    assert "TOP 2" in _sole_query("u.[Description] LIKE", "TOP 2"), \
        "the query cannot detect a second match"
    assert "if len(rows) != 1:" in _ANCHOR


def test_a_short_key_is_never_used_for_a_description_search():
    """A three-character string appears inside a thousand descriptions. The unique-match rule
    would usually refuse those anyway -- but 'usually' is how a two-character key eventually
    finds exactly one row and prices a foot as a light fitting."""
    assert "len(key) < 5" in _ANCHOR


def test_a_minted_key_is_never_sent_to_the_catalogue_at_all():
    """BI-BINDINGSCREW as a LIKE pattern is not merely useless, it is the one key guaranteed
    to match nothing -- and sending it costs a query on every unpriced line on every job."""
    assert "is_synthesised_key(key)" in _ANCHOR


# ── and it does not land on the estimator's checklist ───────────────────────────────
import estimator_inputs as ei                                        # noqa: E402


def test_a_duplicate_line_is_not_an_outstanding_estimator_input():
    """THE SAME FAILURE THROUGH A DIFFERENT DOOR. Job 11350 listed six outstanding inputs and
    two were "enter a unit rate" for parts the Sheet Steel block had already costed on the
    same sheet -- asking for the double-count back. Two lines of noise in six is enough to
    make a person stop reading, and what gets lost is the packaging and the fixings that were
    real. A duplicate article at GBP 0.00 is exactly that shape of nothing."""
    dup = {"part_number": "ESSENTRA FOOT-466122", "description": "FOOT",
           "_duplicate_of": "FIXING1081"}
    assert ei.canonical_pricing_status(dup, 0.0) == ei.NOT_APPLICABLE


def test_an_ordinary_unpriced_line_is_still_asked_for():
    """The narrowness matters as much as the rule: excuse one row too many and the list stops
    being a list."""
    real = {"part_number": "MAG CATCH", "description": "HAFELE 246.41.745"}
    assert ei.canonical_pricing_status(real, 0.0) == ei.UNPRICED
    assert ei.input_note_for_line(real)["kind"] == ei.MATERIAL_UNPRICED


def test_the_duplicate_explains_itself_on_the_row_the_sheet_actually_prints():
    """WRITTEN WHERE THIS ROW CAN REACH, AND THE FIRST ATTEMPT WAS NOT.

    The sentence went into input_note_for_line to begin with, and that function is only
    called for rows whose status is UNPRICED. A duplicate is NOT_APPLICABLE -- deliberately,
    so it stays off the checklist -- so the explanation sat in a branch this row can never
    enter. The unit test passed, because it called the function directly and proved only that
    the function worked.

    A blank cell reads as a free part. A blank cell whose reason lives somewhere unreachable
    reads exactly the same. So the assertion is on the DESCRIPTION the writer mutates, which
    is the field the sheet prints, and it is taken from the source of the dedup block itself.
    """
    block = _WB[_WB.index("same_article_groups(bom_parts)"):_WB.index('row = b["first_row"]')]
    assert '_dup["description"]' in block, \
        "the duplicate's explanation is not on the field the sheet prints"
    assert "SAME ARTICLE AS" in block


def test_the_writer_records_no_field_that_nothing_reads():
    """_no_price_reason was set here and read by no consumer on any path -- the same
    built-is-not-wired shape as the note above, in the same eight lines. A field written for
    a reader that does not exist is indistinguishable, in a JSON dump, from one that is being
    honoured."""
    block = _WB[_WB.index("same_article_groups(bom_parts)"):_WB.index('row = b["first_row"]')]
    written = set(re.findall(r'_dup\["(_[a-z_]+)"\]', block))
    src = "\n".join(Path(sr.__file__).with_name(m).read_text(encoding="utf-8")
                    for m in ("wb_populate.py", "estimator_inputs.py", "job_report_html.py",
                              "invariants.py", "estimator.py"))
    for field in written:
        readers = len(re.findall(rf'get\(\s*["\']{field}["\']', src))
        assert readers >= 1, f'{field} is written by the dedup block and read by nothing'


if __name__ == "__main__":                                            # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
