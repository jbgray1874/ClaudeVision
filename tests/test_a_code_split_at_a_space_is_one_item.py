"""A code cut short at a space on one sheet is the same item, not a second one (D-687).

12693-01-GA is a two-sheet general arrangement that prints the same parts table on both
sheets. Item 6 is a 78x78mm ticket holder, qty 16, whose drawing number runs on past a space
("... 78x78mm Ticket Holder_2274"). Every other item of the two sheets merged into one line.
This one came out as two parts-list rows and two estimate lines:

    sheet 1   the whole code, its own description, qty 16, read by BOTH readers. Priced.
    sheet 2   the code stopped at the space, "Ticket Holder_2274" pushed to the FRONT of the
              description, qty 16, read by BOTH readers. "MATERIAL UNPRICED: enter a unit
              rate", counted in the book's prices to add, flagged UNKNOWN MATERIAL.

The parent merge (merge_boms.merge_pages_into_parents) matched the two rows by item number,
compared their codes, found them unequal and kept both as "the sheets disagree". They do not
disagree: they are one printed row cut in two different places. The short code is a prefix of
the whole one, and the rest of the whole code is exactly the text the short row carries at the
front of its description, followed by exactly the whole row's own description.

The rule is that structural identity and nothing looser. Two items that only share a prefix
(a family member, FIXING12 beside FIXING125) keep their own lines.

Every code here is made up.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import bom_and_route_extract  # noqa: E402
import bom_pipeline  # noqa: E402
import document_builder  # noqa: E402
import estimator  # noqa: E402
import merge_boms  # noqa: E402
from part_identity import same_row_code_cut_at_a_space  # noqa: E402

GA = "9999-01-GA"
SHEET_1, SHEET_2 = "9999-01-GA.pdf#0", "9999-01-GA.pdf#1"

# The made-up stand-in for item 6: one row, read whole on one sheet and cut at a space on the
# other, the cut-off words pushed to the front of the description.
WHOLE = ("0412345-B-Rail 60x60mm Price Clip_3315", "B RAIL 60x60mm PRICE CLIP")
CUT = ("0412345-B-Rail 60x60mm", "Price Clip_3315 B RAIL 60x60mm PRICE CLIP")


def _row(item, code, desc, qty):
    # The shape reconcile_page hands the parent merge: both readers agreed on this sheet.
    return {"item_number": str(item), "part_ref": code, "part_number": "",
            "description": desc, "quantity": qty, "source": "BOTH",
            "confidence": "HIGH", "flag": ""}


def _page(sheet, rows, label=GA):
    return {"label": label, "parent_known": True, "sheet": sheet, "rows": rows,
            "findings": []}


def _two_sheets(first, second, qty_first=16, qty_second=16, item=6):
    return [_page(SHEET_1, [_row(item, *first, qty_first)]),
            _page(SHEET_2, [_row(item, *second, qty_second)])]


def _codes(parents):
    return sorted(r["part_ref"] for p in parents for r in p["rows"])


# ---------------------------------------------------------------------------
# The job's case: one line, the whole code
# ---------------------------------------------------------------------------
def test_the_two_sheets_readings_are_one_line_under_the_whole_code():
    parents, findings = merge_boms.merge_pages_into_parents(_two_sheets(WHOLE, CUT))

    rows = parents[0]["rows"]
    assert len(rows) == 1, "one printed row cut in two places is one line"
    assert rows[0]["part_ref"] == WHOLE[0]
    assert rows[0]["description"] == WHOLE[1], \
        "the description is the whole reading's, without the cut-off code in front of it"
    assert rows[0]["quantity"] == 16, "two readings of one line, not two lines to add"
    # Nothing disagreed, so nothing may say so: the row was read by both readers on each sheet.
    assert not rows[0].get("flag")
    assert not any("the sheets disagree" in f for f in findings)


def test_the_whole_code_is_kept_whichever_sheet_is_read_first():
    # The line takes its place from the first sheet read; its code from the reading that
    # did not cut it. Here the cut reading arrives first.
    parents, _ = merge_boms.merge_pages_into_parents(_two_sheets(CUT, WHOLE))

    rows = parents[0]["rows"]
    assert len(rows) == 1
    assert rows[0]["part_ref"] == WHOLE[0]
    assert rows[0]["description"] == WHOLE[1]
    assert rows[0]["sheet"] == SHEET_1 and rows[0]["also_on_sheets"] == [SHEET_2]


def test_neither_reading_is_lost():
    parents, findings = merge_boms.merge_pages_into_parents(_two_sheets(WHOLE, CUT))

    row = parents[0]["rows"][0]
    assert row["also_on_sheets"] == [SHEET_2]
    assert row["also_read_as"] == [{"part_ref": CUT[0], "description": CUT[1],
                                    "quantity": 16, "sheet": SHEET_2, "source": "BOTH"}]
    # The finding names both spellings, so the fold can be checked against the drawing.
    said = " ".join(findings)
    assert CUT[0] in said and WHOLE[0] in said and "cut short at a space" in said


def test_the_line_reaches_the_estimate_once(monkeypatch):
    """Through the flatten, the record builder and the estimate: one line, qty 16."""
    pages = _two_sheets(WHOLE, CUT)
    parents, findings = merge_boms.merge_pages_into_parents(pages)

    def _reconciled(pdf_paths, **_kw):
        return {"pages": pages, "parents": parents, "findings": findings, "counts": {},
                "pdf_paths": list(pdf_paths), "a_count": 2, "b_count": 2, "unread": [],
                "vision_calls": {}}

    monkeypatch.setattr(merge_boms, "reconcile_job", _reconciled)
    rows = bom_pipeline.reconciled_bom_rows_for_job(pdfs=["9999-01-GA.pdf"])["rows"]

    assert [r["part_number"] for r in rows] == ["0412345-B-RAIL60X60MMPRICECLIP_3315"]
    assert rows[0]["bom_also_on_sheets"] == [SHEET_2]
    assert rows[0]["bom_also_read_as"][0]["part_ref"] == CUT[0]
    # A corroborated line stays corroborated: a flag here would report it as uncorroborated.
    assert not rows[0]["bom_flag"]

    sheet = bom_and_route_extract.bom_sheet({"document_analysis": {"bom_rows": rows}})
    assert len(sheet) == 1 and sheet[0]["appears_on_n_rows"] == 1

    parts = document_builder.bought_in_rows_without_records(rows, [])
    lines = estimator.estimate_document(parts, None)["part_estimates"]
    assert [(e["part_number"], e["quantity"]) for e in lines] == \
        [("0412345-B-RAIL60X60MMPRICECLIP_3315", 16)]


def test_the_rule_reads_the_text_not_the_spacing():
    assert same_row_code_cut_at_a_space(*WHOLE, *CUT)
    # The roles are not interchangeable: the cut reading is not the whole one.
    assert not same_row_code_cut_at_a_space(*CUT, *WHOLE)
    # Case, hyphens and underscores are how two readers spell one cell differently.
    assert same_row_code_cut_at_a_space("0412345-b-rail 60X60MM price-clip 3315",
                                        "b rail 60x60mm price clip",
                                        "0412345 B RAIL 60x60mm",
                                        "PRICE CLIP_3315 B-RAIL 60x60mm PRICE CLIP")


# ---------------------------------------------------------------------------
# Two items stay two items
# ---------------------------------------------------------------------------
def test_a_family_member_with_its_own_words_stays_two_lines():
    # 1234-01A is a different part from 1234-01. Its extra "A" is not text from the other
    # row's description, so nothing says the two are one row.
    pair = (("1234-01A", "SIDE PANEL LH"), ("1234-01", "SIDE PANEL"))
    assert not same_row_code_cut_at_a_space(*pair[0], *pair[1])

    parents, findings = merge_boms.merge_pages_into_parents(
        _two_sheets(pair[0], pair[1], qty_first=1, qty_second=1))
    assert _codes(parents) == ["1234-01", "1234-01A"]
    assert any("the sheets disagree" in f for f in findings), \
        "two codes at one item number are still put to a person"


def test_fixing12_and_fixing125_stay_two_items():
    # The remainder "5" is not text from FIXING12's description: not with the same words...
    assert not same_row_code_cut_at_a_space("FIXING125", "M5 x 12mm SCREW",
                                            "FIXING12", "M5 x 12mm SCREW")
    # ...and not when the description merely opens with a 5. A split at a space moves whole
    # words; "5mm" is one word, and the "5" of it was never part of a code.
    assert not same_row_code_cut_at_a_space("FIXING125", "mm RIVET",
                                            "FIXING12", "5mm RIVET")

    parents, _ = merge_boms.merge_pages_into_parents(
        _two_sheets(("FIXING125", "M5 x 12mm SCREW"), ("FIXING12", "M5 x 12mm SCREW"),
                    qty_first=8, qty_second=8))
    assert _codes(parents) == ["FIXING12", "FIXING125"]


def test_a_different_count_is_not_shown_to_be_one_line():
    parents, findings = merge_boms.merge_pages_into_parents(
        _two_sheets(WHOLE, CUT, qty_first=16, qty_second=8))
    assert _codes(parents) == sorted([WHOLE[0], CUT[0]])
    assert any("the sheets disagree" in f for f in findings)


def test_one_parents_line_never_takes_another_parents():
    # The same code under two assemblies is two occurrences; this rule never crosses parents.
    pages = [_page(SHEET_1, [_row(6, *WHOLE, 16)], label="9999-01-GA"),
             _page("9999-02-GA.pdf#0", [_row(6, *CUT, 16)], label="9999-02-GA")]
    parents, _ = merge_boms.merge_pages_into_parents(pages)
    assert len(parents) == 2
    assert {p["label"]: [r["part_ref"] for r in p["rows"]] for p in parents} == \
        {"9999-01-GA": [WHOLE[0]], "9999-02-GA": [CUT[0]]}


def test_two_rows_of_one_sheet_are_not_this_merges_to_fold():
    # Two rows at one item number on ONE sheet are reconcile_page's verdict on that sheet
    # (two readers, two lines); this merge only folds what two sheets printed.
    parents, _ = merge_boms.merge_pages_into_parents(
        [_page(SHEET_1, [_row(6, *WHOLE, 16), _row(6, *CUT, 16)])])
    assert _codes(parents) == sorted([WHOLE[0], CUT[0]])


def test_a_whole_row_read_into_the_code_cell_is_left_to_its_own_rule():
    # A "whole" reading with no description of its own is the row read as one cell, where
    # the SHORT code is the real one (same_row_read_as_one_cell, D-443). Not this rule.
    assert not same_row_code_cut_at_a_space("FIXING M6x12mm THREADED INSERT", "",
                                            "FIXING M6x12mm", "THREADED INSERT")


def test_a_class_word_is_not_a_code_to_cut():
    # A class word or a placeholder in the code column, with a word of the description glued
    # on, is not a fuller code: there was no code there to cut.
    assert not same_row_code_cut_at_a_space("FIXING125", "M6 SCREW", "FIXING", "125 M6 SCREW")
    assert not same_row_code_cut_at_a_space("P/P LED", "DRIVER", "P/P", "LED DRIVER")
    assert not same_row_code_cut_at_a_space("TBC 77", "BRACKET", "TBC", "77 BRACKET")
