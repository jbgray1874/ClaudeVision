r"""
test_the_page_that_lists_a_part_is_not_the_page_that_defines_it.py

0359342's parts were bound to their PARENT'S PARTS LIST, not to their own detail sheet.

    MBY434  ->  p25   its detail sheet, carrying "Ø24.0" and "2.0", is p26
    JAE821  ->  p3    its 638 x 75 x 18 is on p9
    JAE828  ->  p4    its 500 x 250 x 12 is on p16
    MBY432  ->  p24   RIGHT — and by accident, see below

Consequence: no part had a drawing to take dimensions from, so geometry_inference handed out
category-default envelopes — 350 x 250 for anything named PLATE/BASE/TRAY, 400 x 300 for
PANEL/SIDE/BACK — and those envelopes then drove the nest, the laser time and the coated area.
Seven of eight board panels nested from 400 x 300 against real sizes up to 1680 x 560. Every
"p.N (detail)" citation in the deliverables pointed at a parts list.

WHY THE MECHANISM NEVER WORKED. Binding is meant to happen when a page's TITLE BLOCK names the
part. None of this pack's codes — MBY434, JAE821, J13092, A61636 — matches the digits-then-
hyphen shape that config.PART_NUMBER_PATTERN, config.DWG_NO_PATTERN,
part_code_conventions.looks_like_a_drawing_number and drawing_facts._RE_DWGNO all require, so
no title block ever yielded one and the claim loop never fired for any part. The same absence
blinds the page-role classifier, which needs part numbers to recognise an assembly: every page
in the pack keeps the "detail" default, parts lists included. The run log shows it plainly —
pages 1, 3, 4, 5, 6 and 25 are BOM tables and every one previews as "Page N (detail)".

So every part fell to the last resort: the first page whose TEXT CONTAINS the code, preferring
"detail" role, then lowest page number. With every role equal that is just "whichever page
mentions it first" — and a part is nearly always listed on its parent's table before its own
sheet arrives. MBY432 came out right only because its sheet (p24) precedes the table that lists
it (p25).

THE FIX USES A FACT THE ENGINE ALREADY HAD. The dual-path BOM reconciler records, per row, the
sheet it read that table off (`bom_sheet`). That is not a guess about what a page looks like —
it is the reader saying which pages ARE parts lists. A page that yielded a BOM table now ranks
below one that did not, so the detail sheet wins wherever both mention the code.

It is a tie-break, never a filter: a part mentioned only on parts lists still binds there, and
says so, because a part with no detail sheet has no measured size either.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import part_index                                                # noqa: E402


def _page(number: int, text: str, role: str = "detail") -> dict:
    return {"page_number": number, "normalized_text": text,
            "page_role": {"primary_role": role}}


def _summary(pages, bom_pages_zero_based=()) -> dict:
    return {
        "pages": list(pages),
        "document_analysis": {"bom_rows": [
            {"part_number": "any", "bom_sheet": f"0359342.pdf#{i}"}
            for i in bom_pages_zero_based]},
    }


# ── the reader that says which pages are parts lists ─────────────────────────────────

def test_the_reconcilers_own_record_names_the_parts_list_pages():
    """bom_sheet is "<pdf>#<0-based index>" and page_number is 1-based. 0359342's tables are on
    pages 1, 3, 4, 5, 6 and 25."""
    s = _summary([], bom_pages_zero_based=(0, 2, 3, 4, 5, 24))
    assert part_index._bom_table_page_numbers(s) == {1, 3, 4, 5, 6, 25}


@pytest.mark.parametrize("summary", [
    {}, {"document_analysis": {}}, {"document_analysis": {"bom_rows": []}},
    {"document_analysis": {"bom_rows": [{"part_number": "X"}]}},          # no sheet recorded
    {"document_analysis": {"bom_rows": [{"bom_sheet": "no-hash"}]}},
    {"document_analysis": {"bom_rows": [{"bom_sheet": "f.pdf#not-a-number"}]}},
])
def test_no_record_is_answered_as_no_information(summary):
    """An empty set means "nothing known", which is why it is a tie-break and not a filter — a
    job whose rows carry no sheet must behave exactly as it did before this existed."""
    assert part_index._bom_table_page_numbers(summary) == set()


# ── the binding itself ───────────────────────────────────────────────────────────────

def _bind(summary: dict, part_number: str):
    """Run only the last-resort binding loop, which is where the defect lived."""
    parts = {part_number: {"part_number": part_number, "pages": [], "page_roles": []}}
    _bom = part_index._bom_table_page_numbers(summary)
    for part in parts.values():
        pn = part["part_number"]
        matching = [p for p in summary["pages"] if pn in (p.get("normalized_text") or "")]
        matching = sorted(matching, key=lambda item: (
            1 if item.get("page_number") in _bom else 0,
            0 if item.get("page_role", {}).get("primary_role") == "detail" else 1,
            item.get("page_number", 9999)))
        if matching:
            part["pages"].append(matching[0]["page_number"])
    return parts[part_number]


def test_the_backplate_binds_to_its_own_sheet_not_the_table_that_lists_it():
    """MBY434: listed on the p25 MBY433 parts list, detailed on p26 where Ø24.0 and 2.0 are
    printed. The old rule took p25 because it comes first."""
    s = _summary([
        _page(25, "ITEM DESCRIPTION PART QTY MBY432 MBY434 Puddle weld on either side"),
        _page(26, "Edition Sunglasses Prong Backplate MBY434 24.0 2.0 Hole Table"),
    ], bom_pages_zero_based=(24,))
    assert _bind(s, "MBY434")["pages"] == [26]


def test_a_panel_binds_past_its_parents_table():
    """JAE821: listed on p3, detailed on p9 with 638 x 75 x 18."""
    s = _summary([
        _page(3, "ITEM DESCRIPTION PART QTY JAE820 JAE821 JAE822 JAE823"),
        _page(9, "Edition Sunglasses Plinth Side JAE821 638.0 75.0 18.0"),
    ], bom_pages_zero_based=(2,))
    assert _bind(s, "JAE821")["pages"] == [9]


def test_the_part_that_was_right_by_accident_is_still_right():
    """MBY432's detail sheet (p24) precedes the table listing it (p25), so lowest-page-number
    already gave the right answer. It must keep giving it — a fix that only moves the cases it
    was aimed at has not proved it understands the rule."""
    s = _summary([
        _page(24, "Edition Sunglasses Prong MBY432 219.6 8.0 Est. Mass 0.09 kg"),
        _page(25, "ITEM DESCRIPTION PART QTY MBY432 MBY434"),
    ], bom_pages_zero_based=(24,))
    assert _bind(s, "MBY432")["pages"] == [24]


def test_a_part_with_no_detail_sheet_still_binds_to_the_list_that_names_it():
    """A TIE-BREAK, NOT A FILTER. Purchased items — a castor, a screw — appear only on parts
    lists. Excluding BOM pages outright would leave them with no page at all, which is worse
    than a page that at least names them."""
    s = _summary([
        _page(3, "ITEM DESCRIPTION PART QTY RM08362 Nylon Plate Swivel Castor"),
    ], bom_pages_zero_based=(2,))
    assert _bind(s, "RM08362")["pages"] == [3]


def test_a_job_whose_rows_carry_no_sheet_behaves_exactly_as_before():
    """The lane-A guarantee for this change: with no bom_sheet recorded the set is empty, the
    new term is constant, and the sort is the old sort."""
    s = _summary([
        _page(3, "ITEM DESCRIPTION PART QTY JAE821"),
        _page(9, "Edition Sunglasses Plinth Side JAE821 638.0 75.0"),
    ])                                            # no bom_pages at all
    assert _bind(s, "JAE821")["pages"] == [3], "old behaviour must be untouched"


def test_a_real_assembly_role_still_outranks_a_detail_on_a_later_page():
    """The role term keeps its meaning underneath the new one. Where the classifier DOES work —
    a structured SDI pack, hyphenated codes — a detail page still beats an assembly page, and
    the BOM term only separates pages the reconciler actually took rows from."""
    s = _summary([
        _page(2, "12392-04-GA assembly view", role="assembly"),
        _page(7, "12392-04 detail 500.0 250.0", role="detail"),
    ])
    assert _bind(s, "12392-04")["pages"] == [7]
