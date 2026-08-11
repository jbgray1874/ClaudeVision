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


def test_the_reference_arm_matches_exactly_and_never_loosely():
    """The whole safety argument rests on this. A reference recovered from a description is a
    guess about which characters are the key; matched with LIKE it could attach a hinge's
    price to a foot. Matched exactly it finds that article number or it finds nothing."""
    anchor = _PRICING[_PRICING.index("def _get_udef_anchor"):_PRICING.index("row = self._fetch_one_with_retry")]
    arm = anchor[anchor.index("for key in supplier_reference.lookup_keys"):]
    assert "LIKE" not in arm.upper(), "the manufacturer-reference arm has acquired a fuzzy match"
    assert "[Part code] = LTRIM(RTRIM(?))" in arm


if __name__ == "__main__":                                            # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
