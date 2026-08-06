"""A bill of materials belongs to a drawing, not to a sheet.

The reconciler produced one BOM per PAGE. A parts list that continues onto a second
sheet therefore arrived as two half-BOMs, and a fixings table repeated on a detail sheet
for the fitter's convenience arrived as double the fixings.

Within one parent's BOM the item number is unique — that is what an item number is for —
so it is the thing that says whether two rows on two sheets are one line or two.

Rows under DIFFERENT parents are never folded together, no matter how equal their codes.
One code legitimately appears in several assemblies, and collapsing those is how a part
used twice becomes a part used once.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import bom_pipeline  # noqa: E402
import merge_boms  # noqa: E402


def _row(item, code, desc="PANEL", qty=1):
    return {"item_number": str(item), "part_ref": code, "part_number": code,
            "description": desc, "quantity": qty, "source": "BOTH",
            "confidence": "HIGH", "flag": ""}


def _page(label, rows, sheet=None, known=True):
    return {"label": label, "rows": rows, "sheet": sheet or f"{label}.pdf#0",
            "parent_known": known, "findings": []}


def _codes(parent):
    return [r.get("part_ref") for r in parent["rows"]]


# ---------------------------------------------------------------------------
# One drawing, several sheets
# ---------------------------------------------------------------------------
def test_a_continuation_sheet_finishes_a_list_rather_than_starting_a_second():
    parents, findings = merge_boms.merge_pages_into_parents([
        _page("1282-GA", [_row(1, "1282-01"), _row(2, "1282-02")], sheet="s1"),
        _page("1282-GA", [_row(3, "1282-03"), _row(4, "1282-04")], sheet="s2"),
    ])
    assert len(parents) == 1, "one drawing, one bill of materials"
    assert _codes(parents[0]) == ["1282-01", "1282-02", "1282-03", "1282-04"]
    assert parents[0]["sheets"] == ["s1", "s2"]
    assert any("read from 2 sheets" in f for f in findings)


def test_a_fixings_table_repeated_on_a_detail_is_not_double_the_fixings():
    parents, _ = merge_boms.merge_pages_into_parents([
        _page("1282-GA", [_row(7, "FIXING236", "M6 SCREW", qty=20)], sheet="ga"),
        _page("1282-GA", [_row(7, "FIXING236", "M6 SCREW", qty=20)], sheet="detail"),
    ])
    assert len(parents[0]["rows"]) == 1, "the same item number is the same line"
    assert parents[0]["rows"][0]["quantity"] == 20
    assert parents[0]["rows"][0]["also_on_sheets"] == ["detail"]


def test_hyphen_and_space_variants_of_one_code_are_the_same_line():
    """Two readers, or two sheets, spell a code differently. That is not two parts."""
    parents, _ = merge_boms.merge_pages_into_parents([
        _page("1282-GA", [_row(3, "1455-C-GA")], sheet="s1"),
        _page("1282-GA", [_row(3, "1455-C GA")], sheet="s2"),
    ])
    assert len(parents[0]["rows"]) == 1


def test_sheets_that_disagree_about_an_item_keep_both_and_say_so():
    """Dropping either loses a real part to tidy up a conflict. A phantom is visible in
    the total and gets challenged; a missing part is silent."""
    parents, findings = merge_boms.merge_pages_into_parents([
        _page("1282-GA", [_row(5, "1282-05")], sheet="s1"),
        _page("1282-GA", [_row(5, "1282-99")], sheet="s2"),
    ])
    assert sorted(_codes(parents[0])) == ["1282-05", "1282-99"]
    assert any("the sheets disagree" in f for f in findings)
    assert any("disagree" in (r.get("flag") or "") for r in parents[0]["rows"])


# ---------------------------------------------------------------------------
# Different drawings stay different
# ---------------------------------------------------------------------------
def test_one_code_under_two_parents_stays_two_lines():
    """The global part-number deduplication this system has already been bitten by."""
    parents, _ = merge_boms.merge_pages_into_parents([
        _page("12392-02", [_row(1, "FIXING236", qty=4)]),
        _page("12392-04", [_row(1, "FIXING236", qty=16)]),
    ])
    assert len(parents) == 2
    assert sum(len(p["rows"]) for p in parents) == 2
    assert sorted(r["quantity"] for p in parents for r in p["rows"]) == [4, 16]


def test_the_same_item_number_under_two_parents_is_not_a_conflict():
    """Item numbers restart at 1 in every BOM. They identify a line WITHIN a parent."""
    parents, findings = merge_boms.merge_pages_into_parents([
        _page("12392-02", [_row(1, "12392-02-01M")]),
        _page("12392-04", [_row(1, "12392-04-01M")]),
    ])
    assert len(parents) == 2
    assert not any("disagree" in f for f in findings)


def test_a_row_with_no_item_number_is_kept_not_folded():
    """A thin or unnumbered row cannot be matched by item, and dropping it to be safe
    would lose a real part."""
    parents, _ = merge_boms.merge_pages_into_parents([
        _page("1282-GA", [_row("", "BI-BOLTBZP"), _row("", "BI-BOLTBZP")]),
    ])
    assert len(parents[0]["rows"]) == 2


# ---------------------------------------------------------------------------
# A page that cannot name its drawing
# ---------------------------------------------------------------------------
def test_a_placeholder_parent_never_overrides_a_real_one():
    parents, _ = merge_boms.merge_pages_into_parents([
        _page("job.pdf#2", [_row(9, "1282-09")], sheet="job.pdf#2", known=False),
        _page("1282-GA", [_row(1, "1282-01")], sheet="job.pdf#0"),
    ])
    labels = {p["label"] for p in parents}
    assert "job.pdf#2" in labels, "an unnamed sheet still groups its own rows"
    assert "1282-GA" in labels


def test_an_unnamed_sheets_rows_are_marked_as_having_no_real_parent():
    parents, _ = merge_boms.merge_pages_into_parents([
        _page("job.pdf#2", [_row(9, "1282-09")], known=False),
    ])
    assert parents[0]["parent_known"] is False


def test_the_flag_reaches_the_rows_the_pipeline_emits(monkeypatch):
    """bom_parent_known must survive the flattening, or downstream cannot tell a drawing
    number from a file-and-page placeholder by anything but the shape of the string."""
    monkeypatch.setattr(bom_pipeline, "__name__", bom_pipeline.__name__)
    import merge_boms as mb

    def _fake_reconcile(pdf_paths, **_kw):
        return {"pages": [], "parents": [
            {"label": "1282-GA", "parent_known": True, "sheets": ["a"],
             "rows": [dict(_row(1, "1282-01"), sheet="a")]},
            {"label": "job.pdf#2", "parent_known": False, "sheets": ["job.pdf#2"],
             "rows": [dict(_row(1, "1282-09"), sheet="job.pdf#2")]},
        ], "findings": [], "counts": {}, "pdf_paths": list(pdf_paths),
            "a_count": 1, "b_count": 1, "unread": [], "vision_calls": {}}

    monkeypatch.setattr(mb, "reconcile_job", _fake_reconcile)
    monkeypatch.setattr(mb, "find_pdfs", lambda _d: ["x.pdf"])
    out = bom_pipeline.reconciled_bom_rows_for_job(pdfs=["x.pdf"])

    known = {r["part_number"]: r["bom_parent_known"] for r in out["rows"]}
    assert known == {"1282-01": True, "1282-09": False}


def test_an_older_result_without_parents_still_flattens(monkeypatch):
    """The fallback to pages. A reconcile result built before this change, or by hand,
    must not silently produce nothing."""
    import merge_boms as mb

    def _fake_reconcile(pdf_paths, **_kw):
        return {"pages": [{"label": "1282-GA", "rows": [_row(1, "1282-01")]}],
                "findings": [], "counts": {}, "pdf_paths": list(pdf_paths),
                "a_count": 1, "b_count": 1, "unread": []}

    monkeypatch.setattr(mb, "reconcile_job", _fake_reconcile)
    out = bom_pipeline.reconciled_bom_rows_for_job(pdfs=["x.pdf"])
    assert [r["part_number"] for r in out["rows"]] == ["1282-01"]
    assert out["rows"][0]["bom_parent_known"] is True
