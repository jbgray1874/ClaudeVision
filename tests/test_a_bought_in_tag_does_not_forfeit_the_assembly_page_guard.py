r"""
test_a_bought_in_tag_does_not_forfeit_the_assembly_page_guard.py

THE TAG THAT SAID "NO FABRICATION" WAS THE TAG THAT LET THE FABRICATION IN.

_apply_post_build_fixes holds a guard for parts that were never measured and appear only on
a shared sheet: zero geometry reliability, assembly-only page roles. The page text belongs to
the whole drawing, not to that line, so the guard skips the text-inference block below it and
leaves the line with no operations.

The guard tested `all(r == "assembly")`. A part carrying BOTH "assembly" and "bought_in"
failed that test and fell straight through into the inference — and "bought_in" is the
strongest statement the record can make that a line needs no fabrication at all. Worse, the
retag block INSIDE the guard adds that tag itself, so the guard could undo its own work:
retag a commodity as bought_in on one pass, and it loses the protection on the next.

12552-01-01X paid for it. A 62012RS ball bearing, page_roles ['assembly', 'bought_in'],
geometry reliability 0.0 — nothing about it was ever measured, its own materials list empty —
took the text of the SHARED assembly page it is listed on. That page describes a laser-cut
mild steel drawer, so the bearing came out of the run carrying a laser_cutting op:

    Part: 12552-01-01X
      Description: 62012RS Ball Bearing 12x32x10mm
      Materials: None
      Operations: laser_cutting          <-- from a neighbour's sheet
      Geometry source: pdf  reliability: 0.0
      Unit estimate: 1.84    Extended estimate: 14.71

Zero geometry means nothing on this line was measured. Roles that are only assembly and/or
bought_in mean every word of that page belongs to something else. Neither fact is new; what
is new is that holding both no longer forfeits the protection either one earns on its own.

THE OTHER DIRECTION IS THE POINT OF THE SECOND TEST. A "detail" role means the part has a
sheet OF ITS OWN, and that sheet's text IS about this part — so a detail line still takes the
inference path even when it is also tagged bought_in. 12552-01-02X (CONCRETE SLAB,
['detail', 'bought_in']) is that case, and it must keep behaving exactly as it does now.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import document_builder  # noqa: E402
from document_builder import _apply_post_build_fixes  # noqa: E402


# The words that put a laser on the bearing: a real assembly sheet's callouts, describing
# every part on the drawing except the one we are asking about.
ASSEMBLY_PAGE_TEXT = (
    "SMALL DRAWER BODY ASSEMBLY. MATERIAL: MILD STEEL 1.5mm. "
    "LASER CUT AND FOLD TO PROFILE. DEBURR ALL EDGES. POWDER COATED BLACK. "
    "ITEM 7  12552-01-01X  62012RS Ball Bearing 12x32x10mm  QTY 8"
)


def _summary(page_number: int, text: str, role: str) -> dict:
    return {
        "pages": [
            {
                "page_number": page_number,
                "pdfplumber_text": text,
                "text_preview": text,
                "page_role": {"primary_role": role},
            }
        ]
    }


def _part(part_number: str, description: str, page_roles: list, page: int) -> dict:
    """A record shaped like the one the engine actually built for the bearing.

    geometry_rollup carries the zero reliability verbatim: nothing on this line was measured,
    which is the precondition the guard exists for.
    """
    return {
        "part_number": part_number,
        "description": description,
        "pages": [page],
        "page_roles": list(page_roles),
        "materials": [],
        "surface_finishes": [],
        "textual_operations": [],
        "geometry_rollup": {"confidence": {"geometry_reliability": 0.0}},
    }


def _ops(part: dict) -> list:
    return [str(o).strip().lower() for o in (part.get("textual_operations") or [])]


@pytest.mark.skipif(
    document_builder._infer_ops_from_text is None,
    reason="extractor_patterns.infer_operations_from_text is not importable in this tree; "
           "_apply_post_build_fixes returns early and there is nothing to guard.",
)
def test_the_bearing_takes_no_operations_from_the_page_it_is_listed_on():
    """12552-01-01X: assembly + bought_in, nothing measured, so the page text is not its own."""
    bearing = _part(
        "12552-01-01X",
        "62012RS Ball Bearing 12x32x10mm",
        ["assembly", "bought_in"],
        page=2,
    )
    _apply_post_build_fixes([bearing], _summary(2, ASSEMBLY_PAGE_TEXT, "assembly"))

    ops = _ops(bearing)
    assert "laser_cutting" not in ops, (
        f"A ball bearing came off an assembly page with {ops!r}. The page describes the "
        f"drawer it sits in, not the bearing; nothing about this line was ever measured."
    )
    assert not ops, (
        f"An unmeasured bought-in on a shared sheet should carry no operations at all, "
        f"got {ops!r}."
    )


@pytest.mark.skipif(
    document_builder._infer_ops_from_text is None,
    reason="extractor_patterns.infer_operations_from_text is not importable in this tree.",
)
def test_an_assembly_only_line_is_still_guarded_without_the_bought_in_tag():
    """The case the guard already covered. Widening the role test must not narrow it."""
    sub = _part("12552-02-SA09", "TRAY SUB ASSEMBLY", ["assembly"], page=2)
    _apply_post_build_fixes([sub], _summary(2, ASSEMBLY_PAGE_TEXT, "assembly"))
    assert not _ops(sub), (
        f"The assembly-only case regressed: {_ops(sub)!r}. This is the behaviour the guard "
        f"has always had and the change was only meant to add to it."
    )


@pytest.mark.skipif(
    document_builder._infer_ops_from_text is None,
    reason="extractor_patterns.infer_operations_from_text is not importable in this tree.",
)
def test_a_detail_sheet_is_still_read_even_when_the_line_is_bought_in():
    """A "detail" role means the part has a sheet of its own, and that sheet is about it.

    12552-01-02X, the concrete slab, is ['detail', 'bought_in'] and reaches the inference
    today. The guard must not swallow it — its costing was correct on the last run and this
    change is not licensed to move it.
    """
    slab = _part("12552-01-02X", "CONCRETE SLAB", ["detail", "bought_in"], page=11)
    detail_text = (
        "CONCRETE SLAB. MATERIAL: CONCRETE. 600 x 600 x 20mm. "
        "LASER CUT PROFILE TO SUIT. DEBURR ALL EDGES."
    )
    _apply_post_build_fixes([slab], _summary(11, detail_text, "detail"))

    # The assertion is on the PATH, not on which ops the recogniser happens to return:
    # a detail line is still handed its own sheet. Pinning the op list here would make this
    # test a second opinion on infer_operations_from_text, which it is not.
    assert slab.get("page_roles") == ["detail", "bought_in"], (
        "A detail line must not be retagged by the assembly-page guard; it did not take "
        "that branch before this change and must not take it now."
    )
