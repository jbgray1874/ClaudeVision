"""The title block describes the drawing, not every row on it.

James Gray, 18 September 2026: "`display_material` is still worthwhile next, to stop bought-in
items such as tape inheriting the assembly's steel material on any output."

A drawing sheet states one material and the engine stamps it onto the parts it found there.
That is right for the fabricated leaves — they ARE that material — and wrong for every
bought-in on the same parts table. 401912-02's bill of materials lists "25.4mm ADHESIVE
MAGNETIC TAPE, L: 450mm" and the record called it MILD STEEL, read off the GA title block,
which states what the DIVIDER is made of. On 0355255 the same line read ACRYLIC.

NOTHING WAS MIS-COSTED BY IT — the tape is priced as a bought-in and never touched the steel
route — and that is exactly why it survived: no total moved, so no check fired. A purchased
line reading as mild steel on a page headed "Drawing quality, sheet by sheet" is the kind of
wrong fact an estimator carries into a conversation with a supplier.

ONE SURFACE ALREADY KNEW. `estimate_explained._material_stated` had the rule and applied it to
one column; the quotation's Material line, the report's part buckets, the workbook's material
column and the SQL export each read `normalized_material` raw. That is the shape this session
has now paid for three times — `fold_count`, `displayed_charge`, and here — so the rule moved
to one fact and every surface asks it.

THIS FILE RENDERS THE DOCUMENTS. A test of `display_material` alone would have passed on every
one of the days the £3.88 was on the page.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from client_quote_html import build_quote_html                          # noqa: E402
from costed_facts import costed_job                                     # noqa: E402
from display_material import (INHERITED, OWN, describes_the_product,    # noqa: E402
                              display_material, material_is_the_parts_own)

_TAPE = {
    "part_number": "10975",
    "description": "25.4mm ADHESIVE MAGNETIC TAPE, L: 450mm",
    "normalized_material": "MILD STEEL",     # the GA title block's reading
    "material_source": "title_block",
    "page_roles": ["bought_in"],
    "quantity": 1,
}
_DIVIDER = {
    "part_number": "401912-02-01M",
    "description": "METAL DIVIDER - TALL",
    "normalized_material": "MILD STEEL",
    "material_source": "title_block",        # its OWN drawing's title block
    "page_roles": ["detail"],
    "quantity": 1,
}


# ── the fact ────────────────────────────────────────────────────────────────────────

def test_the_tape_does_not_wear_the_assemblys_material():
    fact = display_material(_TAPE)
    assert fact["text"] == "— (bought-in)"
    assert fact["basis"] == INHERITED
    assert fact["inherited"] is True
    # The reading is KEPT, so a reader can see what was inherited and from where.
    assert "MILD STEEL" in fact["why"] and "title_block" in fact["why"]


def test_a_fabricated_part_is_untouched():
    """THE RULE IS NARROW ON PURPOSE. A leaf's title block IS its own drawing's title block,
    which is the right source for what it is made of. If this ever fails, the fix has started
    deleting materials from the parts that have them."""
    fact = display_material(_DIVIDER)
    assert fact["text"] == "MILD STEEL"
    assert fact["basis"] == OWN


def test_a_bought_in_with_its_own_drawing_keeps_its_material():
    """Where a bought-in has a detail page, the sheet stating the material is its own."""
    part = dict(_TAPE, page_roles=["bought_in", "detail"])
    assert material_is_the_parts_own(part) is True
    assert display_material(part)["text"] == "MILD STEEL"


def test_a_bought_in_read_from_its_own_parts_table_row_keeps_its_material():
    """The other way a line can speak for itself. Anything else would answer '— (bought-in)'
    to every purchased item ever read correctly."""
    part = dict(_TAPE, normalized_material="EPDM RUBBER", material_source="bom_table")
    assert display_material(part)["text"] == "EPDM RUBBER"


def test_an_estimators_own_rule_is_about_the_part():
    """`override_rule:SOMENAME` — a person wrote it, about this line."""
    part = dict(_TAPE, normalized_material="MAGNETIC RUBBER",
                material_source="override_rule:MAGNETIC_TAPE")
    assert display_material(part)["text"] == "MAGNETIC RUBBER"


def test_roll_goods_say_what_they_are_priced_by():
    part = dict(_TAPE, material_estimate={"stock_form": "roll",
                                          "cost_method": "roll_goods_by_length"})
    assert display_material(part)["text"] == "Roll goods (priced by length)"


def test_a_commercial_line_is_not_made_of_anything():
    assert display_material({"part_number": "PACKAGING"})["text"] == "— (commercial line)"
    assert display_material({"part_number": "7332-01-101-PLATE"})["text"] == \
        "— (subcontract service)"


# ── the documents ───────────────────────────────────────────────────────────────────

def _summary(parts):
    return {
        "job_output_stem": "401912-02",
        "estimate_summary": {
            "estimate_workbook_inputs": {"assumed_job_quantity": 20},
            "part_estimates": parts,
        },
        "manufacturing_writeup": {"parts": parts},
    }


def test_the_quotation_does_not_name_the_tape_as_a_material():
    """THE CUSTOMER'S DOCUMENT. The Material line collected `normalized_material` off every
    line, bought-ins included — at best repeating what a fabricated part already said, at
    worst putting a second material on a quotation for a product made of one."""
    assert describes_the_product(_TAPE) is None
    assert describes_the_product(_DIVIDER) == "MILD STEEL"

    part = dict(_TAPE, normalized_material="ACRYLIC")      # the 0355255 shape
    html = build_quote_html(_summary([_DIVIDER, part]), job_stem="401912-02")
    said = re.sub(r"<[^>]+>", " ", html)
    at = said.index("Material")
    assert "Acrylic" not in said[at:at + 200], said[at:at + 200]


def test_the_costed_record_labels_the_line_for_every_surface_that_reads_it():
    """The workbook's material column, the report's material table and the explanation all
    read `material_label` off the costed line — so one fact reaches three documents."""
    job = costed_job(_summary([_DIVIDER, _TAPE]))
    labels = {l["part_number"]: l.get("material_label") for l in job["lines"]}
    assert labels.get("10975") == "— (bought-in)"
    assert labels.get("401912-02-01M") == "MILD STEEL"


def test_the_report_does_not_count_the_tape_as_a_steel_part():
    """The material streams tell an estimator how many parts of each kind the job has. The
    tape counted as Sheet steel on 401912-02 and Acrylic on 0355255, because the two
    bought-in tests above it catch a prefix and a stock form and this row carried neither."""
    import job_report_html as J
    streams = J._extract_cost_streams(_summary([_DIVIDER, _TAPE]))
    by_name = {s["name"]: s["count"] for s in streams}
    assert by_name.get("Bought-in items") == 1, by_name
    assert by_name.get("Sheet steel", 0) <= 1, by_name


def test_the_drawing_quality_column_says_why_rather_than_a_material():
    """It already did, with its own private copy of the rule. It now asks the shared one."""
    from estimate_explained import _material_stated
    said = _material_stated({"page_roles": ["bought_in"], "materials": ["MILD STEEL"],
                             "material_source": "title_block"})
    assert "purchased" in said and "MILD STEEL" not in said


# ── and the costing is deliberately NOT touched ─────────────────────────────────────

def test_nothing_here_changes_what_a_part_is_costed_as():
    """A REPORTING CHANGE AND A COSTING CHANGE MUST NOT TRAVEL TOGETHER — the rule this
    codebase already wrote down when it named `drawing_notes` without ranking it.

    `wb_populate` reads `normalized_material` to pick a £/kg rate, a sheet size and whether a
    part can be powder coated. Those are costing decisions and they still read the raw field;
    this module changes the LABEL a document prints and nothing else. If somebody ever routes
    the costing through it, the tape stops being priced as a bought-in and this is where that
    should be argued rather than discovered.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "wb_populate.py").read_text(
        encoding="utf-8")
    at = src.index("def _rate_for")  if "def _rate_for" in src else 0
    assert "from display_material import" not in src, (
        "wb_populate now imports the display fact — if that is deliberate, it is a costing "
        "change and needs a parity run, not a commit message")
    assert at >= 0
