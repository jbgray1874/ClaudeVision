r"""
test_sdis_own_numbering_says_which_parts_we_buy.py

THE LETTER WAS ON THE PART NUMBER THE WHOLE TIME. NOTHING ASKED UNTIL COSTING.

SDI's numbering says what a line IS: "-M" a part cut in metal, "-A" acrylic, "-T" MDF —
and "-X" a part we BUY. material_suffix has read the first three for a long time. Nothing
read the fourth, so every stage before costing had to guess from page roles.

That guess had no chance on an SDI drawing reference. document_builder's retag, which is
what puts "bought_in" on a commodity listed on an assembly sheet, deliberately skips
anything matching ^\d{3,5}- — written to protect the parts we cut, and it protected the
purchases with them. So the ONLY thing that ever set the role on "12552-01-01X" was
estimator._is_special_bought_in_item, which reads this very letter:

    "Special / bought-in FINISHING items ... These are NOT SDI-fabricated: they carry no
     saw/glue/CNC/laser/weld fab labour"

and then appends "bought_in" to page_roles — at COSTING, after everything that needed it.

WHAT THAT COST. 12552-01-01X is a 62012RS ball bearing, 12x32x10mm. At
geometry_inference its page_roles were ['assembly'], so is_bought_in said False, so the
sibling borrow handed it 12552-01-01M's flat pattern: 650.7 x 178.7 x 1.5mm, CROSS MEMBERS.
With a blank and a steel material it read as sheet metal, took a laser op and 269 seconds,
and was billed on fabrication it can never incur. By the time anything printed the record
the role was on it — so the run agreed with itself, and the sheet said a bearing had a
1.5mm gauge.

The rule already existed. It fired last. This moves the reading to the part number, which
exists from line one, so the one answer serves geometry_inference, the assembly-page guard
and the route compiler alike.

DIRECTION OF THE GUARD. "-M"/"-A"/"-T" must stay MADE. A rule that swept those in would
strip laser and fold from parts SDI cuts — the 12392 failure, which this file already
carries scar tissue for.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geometry_inference as gi  # noqa: E402
import part_code_conventions as pcc  # noqa: E402
from bought_in_policy import is_bought_in, bought_in_reason  # noqa: E402


def test_the_bearing_reads_as_purchased_from_its_number_alone():
    """The record exactly as it stands at file_scan:2810 — no bought_in role yet."""
    bearing = {
        "part_number": "12552-01-01X",
        "description": "62012RS Ball Bearing 12x32x10mm",
        "page_roles": ["assembly"],
    }
    assert is_bought_in(bearing), (
        "12552-01-01X read as a part SDI makes. Its page roles are still ['assembly'] at "
        "this stage — the bought_in tag is not appended until costing — so the part number "
        "is the only thing that can answer, and it ends in SDI's purchased suffix."
    )
    assert "-X" in bought_in_reason(bearing), bought_in_reason(bearing)


def test_the_parts_we_cut_are_untouched():
    """-M, -A and -T are the other half of the same convention and must stay made."""
    for pn, desc in (("12552-01-01M", "CROSS MEMBERS"),
                     ("12552-01-01A", "PLASTIC WASHER"),
                     ("12552-01-01T", "BASE PANEL")):
        part = {"part_number": pn, "description": desc, "page_roles": ["detail"]}
        assert not is_bought_in(part), (
            f"{pn} read as purchased. SDI's suffix says we cut it; classifying it bought-in "
            f"strips its laser and fold, which is the 12392 failure this module exists to "
            f"prevent. Reason given: {bought_in_reason(part)!r}"
        )


def test_the_suffix_is_read_only_after_a_digit():
    """Same shape as material_suffix: a code that merely ends in a letter is left alone."""
    assert pcc.purchased_suffix("12552-01-01X") == "X"
    assert pcc.purchased_suffix("12552-01-02x") == "X"       # case, as the drawing types it
    assert pcc.purchased_suffix("12552-01-01M") == ""
    assert pcc.purchased_suffix("12552-00-GA") == ""         # ends in a letter, not a digit
    assert pcc.purchased_suffix("") == ""
    assert pcc.purchased_suffix(None) == ""


def test_the_purchased_letter_is_not_a_material_letter():
    """The two conventions say opposite things and must not share a pattern.

    base_code strips the material letter. If "X" were folded in, "12552-01-01X" would
    resolve to "12552-01-01" — the same key as the cross member and the washer — and every
    caller that reads a material suffix as "we fabricate this" would be told the wrong thing
    about a purchase.
    """
    assert pcc.material_suffix("12552-01-01X") == ""
    assert pcc.base_code("12552-01-01X")[0] == "12552-01-01X"
    assert pcc.material_suffix("12552-01-01M") == "M"


def test_the_borrow_is_refused_on_the_record_as_it_stands_at_inference():
    """End to end, with the roles the part actually has when the rule runs."""
    cross = {
        "part_number": "12552-01-01M", "description": "CROSS MEMBERS",
        "normalized_material": "MILD STEEL", "page_roles": ["detail"],
        "normalized_geometry": {"blank_length_mm": 650.7, "blank_width_mm": 178.7,
                                "confidence": {"geometry_reliability": 1.0}},
    }
    bearing = {
        "part_number": "12552-01-01X", "description": "62012RS Ball Bearing 12x32x10mm",
        "normalized_material": "MILD_STEEL", "page_roles": ["assembly"],
        "normalized_geometry": {},
    }
    report = gi.infer_missing_geometry({"manufacturing_writeup": {"parts": [cross, bearing]}})

    ng = bearing.get("normalized_geometry") or {}
    assert ng.get("blank_length_mm") is None, (
        f"The bearing took a {ng.get('blank_length_mm')} x {ng.get('blank_width_mm')}mm "
        f"blank. That is 12552-01-01M's flat, and it is what makes the estimator laser-cut "
        f"a ball bearing."
    )
    assert [r["part"] for r in report.get("refused_bought_in", [])] == ["12552-01-01X"]


def test_a_refused_row_with_no_part_number_is_still_nameable():
    """The report must carry the description, or a nameless row prints as "None".

    12552's M5X10mm CAP SCREW reached the run with part_number None and was reported as
    literally "None" — a name nobody can look up on the sheet.
    """
    screw = {
        "part_number": None, "description": "M5X10mm CAP SCREW",
        "page_roles": ["assembly", "bought_in"], "normalized_geometry": {},
    }
    report = gi.infer_missing_geometry({"manufacturing_writeup": {"parts": [screw]}})
    refused = report.get("refused_bought_in") or []
    assert len(refused) == 1 and refused[0].get("description") == "M5X10mm CAP SCREW", (
        f"A refused row must carry something an estimator can find it by: {refused!r}"
    )
