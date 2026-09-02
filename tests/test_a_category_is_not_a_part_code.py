"""FIXING names a drawer. FIXING41 names a screw. Only one of them is a key.

WHAT AN ESTIMATOR BROUGHT, which is the best kind of bug report. Tim can find FIXING41, FIXING513
and FIXING1122 in the parts master. He cannot find FIXING. Looking at the M&S till podia BOM
(402179-01-GA) shows why:

    29  FIXING            M6x16.0mm SOCKET CAP SCREW, BZP         16
    30  SPRING WASHER     M6 SPRING WASHER                        16
    31  FIXING41          M6x16.0mm BUTTON HEAD SCREW; BZP        12
    32  FIXING513         4.0x10.0mm DOME RIVET, BLACK ANODIZED   51
    33  FIXING1122        4.0x10.0mm C/SUNK RIVET, ALU            14

Rows 31 to 33 carry real SDI codes — they exist in the parts master and Elite Sourcing quote
against them by name, which is exactly why an estimator can find those and not row 29. Rows 29 and
30 carry the word for what the thing IS. The identity of those lines is entirely in the
description, and there is no code to look up because SDI never minted one.

WHY THAT IS DANGEROUS AND NOT MERELY UNHELPFUL. A category word is a PREFIX of every real code in
its family, and at six characters it clears every length guard that exists to stop short keys being
looked up. So it reaches the catalogue looking like an identifier. The worst case is not a miss:

    _get_udef_anchor tries `WHERE [Part code] = 'FIXING'` FIRST, exactly, taking one row.

If the parts master holds any row coded literally FIXING — a catch-all, which is precisely the
sort of row a parts master accumulates — then every generic fixing line on every drawing prices at
that one figure. A socket cap screw, a button head and an aluminium rivet all costed the same, and
none of them flagged, because from the engine's point of view an exact code match is the strongest
evidence there is.

The ambiguity rules that protect the description path (TOP 2, refuse if two match) do not protect
the exact-code path, because an exact match is never ambiguous. It is just wrong.

WHAT THE FIX DOES. Refuses the category AS A CODE, which routes the line to description matching —
where "M6x16.0mm SOCKET CAP SCREW, BZP" is a far better key than "FIXING" ever was. It does not
invent a price and it does not suppress the line. Same shape as is_cross_reference_note: a value
that looks like an answer, is not one, and must be removed rather than believed.

DELIBERATELY NARROW. A false positive costs a real code refused and a part unpriced, so a code is
only a category when it is a known class word with nothing distinguishing after it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from part_code_conventions import is_category_not_a_code  # noqa: E402
from supplier_reference import lookup_keys  # noqa: E402


# ── the five rows off the M&S drawing ──────────────────────────────────────────

@pytest.mark.parametrize("code", ["FIXING", "SPRING WASHER"])
def test_the_two_rows_tim_could_not_find_are_categories(code):
    assert is_category_not_a_code(code)


@pytest.mark.parametrize("code", ["FIXING41", "FIXING513", "FIXING1122"])
def test_the_three_rows_he_could_find_are_codes(code):
    """These exist in the parts master and Elite quote against them. Refusing one would take a
    priced line and make it unpriceable — the opposite error, and worse."""
    assert not is_category_not_a_code(code)


def test_a_category_yields_no_lookup_key_at_all():
    """THE ASSERTION. Nothing asks the catalogue about "FIXING"."""
    assert lookup_keys({"part_number": "FIXING",
                        "description": "M6x16.0mm SOCKET CAP SCREW, BZP"}) == []


def test_a_real_code_is_still_the_first_key():
    keys = lookup_keys({"part_number": "FIXING41",
                        "description": "M6x16.0mm BUTTON HEAD SCREW; BZP"})
    assert keys[0] == "FIXING41"


def test_a_category_is_not_re_added_by_the_last_resort_append():
    """lookup_keys appends the part's own code at the END as a last resort. A minted key is a
    bad key; a category word is a WRONG one, because it can match something specific."""
    keys = lookup_keys({"part_number": "SPRING WASHER", "description": "M6 SPRING WASHER",
                        "supplier_references": [{"reference": "DIN127-M6"}]})
    assert "SPRING WASHER" not in keys
    assert "DIN127-M6" in keys, "a real manufacturer reference on the same line must survive"


# ── the shape of the rule ──────────────────────────────────────────────────────

@pytest.mark.parametrize("code,is_cat", [
    ("FIXING", True), ("FIXINGS", True), ("fixing", True),
    ("FIXING41", False), ("FIXING1", False), ("FIXING1122", False),
    ("ELECTRICS", True), ("ELECTRICS2", False),
    ("SPRING WASHER", True), ("SPRINGWASHER", True), ("SPRING-WASHER", True),
    ("MISC", True), ("STD PART", True),
    ("10575-02", False), ("TP-1113", False), ("402179-01-GA", False),
    ("246.41.745", False),
])
def test_the_line_between_a_class_and_an_identifier(code, is_cat):
    assert is_category_not_a_code(code) is is_cat


def test_it_compares_on_the_bare_form():
    """A CAD text extractor re-spaces these unpredictably and the same cell comes back
    differently from two readers, which is what bare_code exists for."""
    for spelling in ("SPRING WASHER", "SPRING-WASHER", "spring washer", "SpringWasher"):
        assert is_category_not_a_code(spelling), spelling


def test_a_blank_is_not_a_category():
    """Absent and generic are different facts. A blank code is handled elsewhere and must not be
    swept up here."""
    assert not is_category_not_a_code("")
    assert not is_category_not_a_code(None)


def test_a_long_real_code_containing_a_class_word_survives():
    """Containment is not the rule — equality on the bare form is. Otherwise every code with
    SCREW or CABLE in it would be refused."""
    for code in ("SCREW-M6-16-BZP", "CABLE-5M-BLK", "FIXING-KIT-22"):
        assert not is_category_not_a_code(code), code


# ── the rule lives in one place ────────────────────────────────────────────────

def test_the_guard_is_at_the_one_function_that_decides_what_a_part_is_looked_up_by():
    """Applied at three call sites it would be applied at two. lookup_keys is the choke point."""
    src = (_ROOT / "src" / "supplier_reference.py").read_text(encoding="utf-8")
    at = src.index("def lookup_keys(")
    body = src[at:src.index("def describe_keys(")]
    assert body.count("_is_category(") == 2, (
        "both the leading and the last-resort append must be guarded — the second one puts the "
        "code back at the end of the list")


def test_the_vocabulary_is_narrow_enough_to_be_safe():
    """Every entry has to be a word SDI genuinely uses as a class in the code column. Adding a
    word that is also a real code prefix would refuse real parts."""
    from part_code_conventions import _CATEGORY_CODES
    assert "FIXING" in _CATEGORY_CODES and "ELECTRICS" in _CATEGORY_CODES
    for entry in _CATEGORY_CODES:
        # THE REASON, NOT A PROXY FOR IT. This asserted isalpha(), whose stated purpose is
        # "carries digits". A digit is what makes a token look like a real code — FIXING41
        # names a screw a buyer can order — and isalpha() also refuses a separator, which
        # carries none of that risk. SDI's own shorthand "P/P" is a class word with a slash
        # in it, and the guard was refusing it for a reason that did not apply to it.
        assert not any(c.isdigit() for c in entry), (
            f"{entry!r} carries digits — that makes it look like a real code")
        assert entry == entry.upper(), f"{entry!r} is compared against the bare (upper) form"
        # A separator is allowed; anything longer than one is a description, not a class.
        assert sum(1 for c in entry if not c.isalnum()) <= 1, (
            f"{entry!r} looks like a description rather than a class word")
