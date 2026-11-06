"""
The ownership is not lost later — it was never recorded.

summarise_document joins every page's BOM region into one string and runs one regex over the
lot. A row therefore arrives with an item number, a code, a description and a quantity, and
no idea which sheet it was printed on. Every later attempt to rebuild the tree is
reconstructing something the FIRST read discarded, which is why each attempt half-worked and
the next drawing surfaced the same class of failure again.

Worse, the dual-path reader that DOES stamp a parent is behind SDI_DUALPATH_BOM and defaults
OFF — "Flag OFF => byte-identical to baseline". So on an ordinary run the parent field the
compiler was taught to read did not exist at all, and the fix would have been a silent no-op
on every real job.

These tests hold the first layer: where each row came from, recorded at the only point it is
still knowable, without changing which rows are read.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import file_scan


def _page(number, drawing, bom_text):
    return {"page_number": number,
            "region_text": {"title_block": f"DWG NO {drawing} REV A" if drawing else "",
                            "bom": bom_text, "notes": "", "revision": ""}}


# One enquiry, two general arrangements, the same fastener on both — the 12392 shape.
PAGES = [
    _page(1, "12392-02-GA",
          "1 12392-02-201 PANEL ASSEMBLY 1  2 FIXING BUTTON HEAD SCREW M4X8 16"),
    _page(2, "12392-04-GA",
          "1 12392-04-01M MOD MOUNT BRACKET 2  2 FIXING BUTTON HEAD SCREW M4X8 4"),
]

ROWS = [
    {"item_number": "1", "part_number": "12392-02-201",
     "description": "PANEL ASSEMBLY", "quantity": 1},
    {"item_number": "2", "part_number": "FIXING",
     "description": "BUTTON HEAD SCREW M4X8", "quantity": 16},
    {"item_number": "1", "part_number": "12392-04-01M",
     "description": "MOD MOUNT BRACKET", "quantity": 2},
    {"item_number": "2", "part_number": "FIXING",
     "description": "BUTTON HEAD SCREW M4X8", "quantity": 4},
]


def test_each_row_is_traced_to_the_sheet_that_printed_it():
    rows = [dict(r) for r in ROWS]
    assert file_scan.attribute_bom_rows_to_source_pages(rows, PAGES) == 4
    assert [r["source_page"] for r in rows] == [1, 1, 2, 2]


def test_two_of_the_same_code_on_two_sheets_get_two_different_owners():
    """The whole point. A fastener listed on the panel GA and again on the bracket GA is two
    lines with two quantities under two owners, and attributing both to the first sheet would
    lose exactly what the attribution exists to keep."""
    rows = [dict(r) for r in ROWS]
    file_scan.attribute_bom_rows_to_source_pages(rows, PAGES)
    fixings = [r for r in rows if r["part_number"] == "FIXING"]
    assert [r["bom_parent"] for r in fixings] == ["12392-02-GA", "12392-04-GA"]
    assert [r["quantity"] for r in fixings] == [16, 4]


def test_the_parent_is_the_drawing_not_the_page():
    rows = [dict(r) for r in ROWS]
    file_scan.attribute_bom_rows_to_source_pages(rows, PAGES)
    assert rows[0]["bom_parent"] == "12392-02-GA"
    assert rows[2]["bom_parent"] == "12392-04-GA"


def test_a_sheet_with_no_readable_title_block_claims_no_owner():
    """Placing a row is not the same as knowing who owns it. A page that does not say which
    drawing it is places its rows and claims nothing — the honest outcome, and the one the
    compiler's refusal is built to expect."""
    rows = [{"part_number": "12392-02-201", "description": "PANEL", "quantity": 1}]
    placed = file_scan.attribute_bom_rows_to_source_pages(
        rows, [_page(1, "", "1 12392-02-201 PANEL 1")])
    assert placed == 1
    assert rows[0]["source_page"] == 1
    assert "bom_parent" not in rows[0]


def test_a_loose_reference_on_the_sheet_is_not_a_drawing_number():
    """The pattern is anchored on DWG NO / DRAWING NO, so a code merely mentioned on the
    sheet cannot be mistaken for the drawing the sheet IS."""
    page = _page(1, "12392-02-GA", "1 12392-02-201 PANEL 1")
    page["region_text"]["title_block"] += " SEE ALSO 12392-04-GA"
    rows = [{"part_number": "12392-02-201", "description": "PANEL", "quantity": 1}]
    file_scan.attribute_bom_rows_to_source_pages(rows, [page])
    assert rows[0]["bom_parent"] == "12392-02-GA"


def test_a_title_block_region_naming_two_drawings_names_none():
    """Where the region genuinely caught two title blocks — a sheet laid out so the zone
    overlaps its neighbour — there is no way to tell which is which from here, and naming
    the wrong one gives every row on the page the wrong owner."""
    page = _page(1, "12392-02-GA", "1 12392-02-201 PANEL 1")
    page["region_text"]["title_block"] += " DWG NO 12392-04-GA REV B"
    rows = [{"part_number": "12392-02-201", "description": "PANEL", "quantity": 1}]
    file_scan.attribute_bom_rows_to_source_pages(rows, [page])
    assert rows[0]["source_page"] == 1, "the row is still placed"
    assert "bom_parent" not in rows[0], "but no owner is claimed"


def test_attribution_never_changes_which_rows_were_read():
    """Additive by construction: the joined-text pass produces exactly the rows it always
    did, and this only says where each came from."""
    rows = [dict(r) for r in ROWS]
    before = [(r["part_number"], r["quantity"]) for r in rows]
    file_scan.attribute_bom_rows_to_source_pages(rows, PAGES)
    assert [(r["part_number"], r["quantity"]) for r in rows] == before
    assert len(rows) == len(ROWS)


def test_a_row_no_sheet_claims_is_left_alone():
    rows = [{"part_number": "SOMETHING-ELSE", "description": "X", "quantity": 1}]
    assert file_scan.attribute_bom_rows_to_source_pages(rows, PAGES) == 0
    assert "source_page" not in rows[0]
    assert "bom_parent" not in rows[0]


def test_no_pages_and_no_rows_are_not_errors():
    assert file_scan.attribute_bom_rows_to_source_pages([], PAGES) == 0
    assert file_scan.attribute_bom_rows_to_source_pages([dict(r) for r in ROWS], []) == 0


# ── and the cross-PDF merge that used to collapse them ──────────────────────────────────

def _merge(rows_by_pdf):
    """merge_job_pdf_summaries over N single-page PDFs, returning the merged BOM rows."""
    from pathlib import Path
    partials = []
    for name, rows in rows_by_pdf:
        partials.append((Path(name), {
            "document_analysis": {"bom_rows": rows}, "pages": [], "page_count": 1,
            "pattern_summary": {}, "manual_review_items": [], "detected_labels": [],
            "geometry_summary": {}, "output_targets": {}, "pdf_metadata": {},
        }))
    merged, _anchor = file_scan.merge_job_pdf_summaries(partials, Path("12392"))
    return merged["document_analysis"]["bom_rows"]


def test_the_cross_pdf_merge_keeps_both_fastener_lines():
    """This kept one row per part number across the whole folder, so an enquiry with two GAs
    lost one of every fastener line both drawings used — quantity and owner — before any
    other pass could see either."""
    out = _merge([
        ("12392-02-GA.pdf", [{"part_number": "FIXING", "description": "SCREW M4X8",
                              "quantity": 16, "bom_parent": "12392-02-GA"}]),
        ("12392-04-GA.pdf", [{"part_number": "FIXING", "description": "SCREW M4X8",
                              "quantity": 4, "bom_parent": "12392-04-GA"}]),
    ])
    fixings = [r for r in out if r["part_number"] == "FIXING"]
    assert len(fixings) == 2, f"a line was merged away across PDFs: {fixings}"
    assert sorted(r["quantity"] for r in fixings) == [4, 16]
    assert {r["bom_parent"] for r in fixings} == {"12392-02-GA", "12392-04-GA"}


def test_the_same_line_in_two_pdfs_still_collapses():
    """A detail sheet repeating its parent's line is one line, not two. Splitting requires
    two recorded parents, here as everywhere else."""
    row = {"part_number": "12392-02-01M", "description": "FACE PANEL", "quantity": 1,
           "bom_parent": "12392-02-201"}
    out = _merge([("12392-02-GA.pdf", [dict(row)]), ("12392-02-201.pdf", [dict(row)])])
    assert len([r for r in out if r["part_number"] == "12392-02-01M"]) == 1


def test_rows_with_no_parent_merge_exactly_as_before():
    """The safety property: with no title block anywhere, the key falls back to the code and
    this behaves identically to the part-number dictionary it replaced."""
    out = _merge([
        ("a.pdf", [{"part_number": "FIXING", "description": "SCREW", "quantity": 16}]),
        ("b.pdf", [{"part_number": "FIXING", "description": "SCREW", "quantity": 4}]),
    ])
    assert len([r for r in out if r["part_number"] == "FIXING"]) == 1


# ── the whole chain, in the shape a default run actually takes ──────────────────────────

def test_the_tree_is_built_from_drawings_alone_with_every_flag_off():
    """THE RUN THAT ACTUALLY HAPPENS. No SDI_DUALPATH_BOM, no LLM extract for the second
    drawing, no native model — just two PDFs in a folder. This is the configuration every
    earlier fix was invisible in, and the one an estimator will use."""
    from route_compiler import build_part_graph

    rows = [dict(r) for r in ROWS]
    file_scan.attribute_bom_rows_to_source_pages(rows, PAGES)
    parts = [{"part_number": c, "description": c, "quantity": 1} for c in
             ("12392-02-GA", "12392-02-201", "12392-04-GA", "12392-04-01M", "FIXING")]

    g = build_part_graph(parts, {}, rows, ["12392-02-GA", "12392-04-GA"])

    assert g["top_assemblies"] == ["12392-02-GA", "12392-04-GA"]
    assert [i["part_number"] for i in g["issues"]] == []
    assert g["parents"]["12392-04-01M"] == {"12392-04-GA"}


def test_a_fastener_both_drawings_use_is_owned_by_both_and_summed():
    """Refusing any child that already had a parent also refused the SECOND BOM line, so the
    panel's 16 screws were an edge and the bracket set's 4 were nothing — and the cascade
    summed 16 where the drawings say 20. Two BOM rows naming two owners are not in conflict."""
    from route_compiler import build_part_graph

    rows = [dict(r) for r in ROWS]
    file_scan.attribute_bom_rows_to_source_pages(rows, PAGES)
    parts = [{"part_number": c, "description": c, "quantity": 1} for c in
             ("12392-02-GA", "12392-02-201", "12392-04-GA", "12392-04-01M", "FIXING")]

    g = build_part_graph(parts, {}, rows, ["12392-02-GA", "12392-04-GA"])
    assert g["parents"]["FIXING"] == {"12392-02-GA", "12392-04-GA"}
    assert g["quantities"]["FIXING"] == 20.0


def test_another_source_still_wins_outright():
    """The refusal that remains. An extract or a model that placed a part is not overruled by
    a BOM row naming a different owner — a wrong parent is worse than a missing one."""
    from route_compiler import build_part_graph

    rows = [{"part_number": "12392-02-201", "description": "PANEL ASSEMBLY", "quantity": 1,
             "bom_parent": "12392-04-GA"}]          # the BOM disagrees with the extract
    extract = {"top_assembly": {"part_number": "12392-02-GA"},
               "assemblies": [{"part_number": "12392-02-GA",
                               "children": [{"part_number": "12392-02-201", "qty": 1}]}]}
    parts = [{"part_number": c, "description": c, "quantity": 1} for c in
             ("12392-02-GA", "12392-02-201", "12392-04-GA")]
    g = build_part_graph(parts, extract, rows, ["12392-02-GA", "12392-04-GA"])
    assert g["parents"]["12392-02-201"] == {"12392-02-GA"}
