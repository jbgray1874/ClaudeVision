r"""
test_a_part_is_sized_from_its_own_detail_sheet.py

THE ENVELOPE WAS NEVER A SIZE. 0359342's parts were bound to their parent's parts list, so
nothing read a dimension off a detail sheet and geometry_inference handed out category defaults:

    350 x 250   PLATE / BASE / TRAY / SHELF / TIER in the name
    400 x 300   PANEL / BACK / FRONT / SIDE / DOOR in the name

Those drove the nest, the laser time and the coated area. Seven of eight board panels nested from
400 x 300 against real printed sizes up to 1680 x 560 — an under-charge of three to nine times on
the board, which is the direction nobody notices. The sizes were on the sheets the whole time.

The acceptance a reviewer set for this work, verbatim: "every fabricated part has sourced
dimensions or an explicit unresolved geometry decision". Both halves are tested here — the parts
that can be sized, and the parts that must refuse to be.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from detail_page_geometry import (                              # noqa: E402
    apply_detail_page_geometry, isolate_dimension_text)


def _page(number: int, length=None, width=None, all_dims=(), text: str = "") -> dict:
    return {
        "page_number": number, "source_pdf_name": "0359342.pdf",
        "source_page_number": number, "normalized_text": text,
        "page_role": {"primary_role": "detail"},
        "page_analysis": {"dimensions": {
            "overall_length_mm": length, "overall_width_mm": width,
            "all_dimensions_mm": list(all_dims)}},
    }


def _part(pn, pages, thickness=None, **over):
    p = {"part_number": pn, "pages": list(pages), "normalized_thickness_mm": thickness,
         "review_flags": []}
    p.update(over)
    return p


def _summary(pages, bom_zero_based=(), owners=None):
    rows = [{"part_number": "any", "bom_sheet": f"0359342.pdf#{i}"} for i in bom_zero_based]
    for parent, index in (owners or {}).items():
        rows.append({"part_number": "child", "bom_sheet": f"0359342.pdf#{index}",
                     "bom_parent": parent})
    return {"pages": list(pages), "document_analysis": {"bom_rows": rows}}


# ── the five parts the reviewer named, with the figures their sheets print ────────────

@pytest.mark.parametrize("pn,page_no,length,width,thickness,expect", [
    # MBY439 mirror plate, p28: "1578.0 ... 188.0 ... 2.0"
    ("MBY439", 28, 1578.0, 188.0, 2.0, (1578.0, 188.0)),
    # MBY435 shelf bracket, p27, from its FLAT PATTERN view: 418.0 x 212.5
    ("MBY435", 27, 418.0, 212.5, 2.0, (418.0, 212.5)),
    # JAE826 shroud back panel, p14: 1680 x 560 x 18 — against a 400 x 300 envelope
    ("JAE826", 14, 1680.0, 560.0, 18.0, (1680.0, 560.0)),
    # JAE832 back panel, p20: 1670 x 546 x 18
    ("JAE832", 20, 1670.0, 546.0, 18.0, (1670.0, 546.0)),
    # JAE833 shelf top, p21: 494 x 199 x 9 — against a 350 x 250 envelope
    ("JAE833", 21, 494.0, 199.0, 9.0, (494.0, 199.0)),
])
def test_a_part_takes_the_blank_its_own_sheet_prints(pn, page_no, length, width,
                                                     thickness, expect):
    summary = _summary([_page(page_no, length, width)])
    part = _part(pn, [page_no], thickness,
                 blank_length_mm=400.0, blank_width_mm=300.0,
                 blank_length_mm_source="geometry_inference")
    assert apply_detail_page_geometry([part], summary) == 1
    assert (part["blank_length_mm"], part["blank_width_mm"]) == expect
    assert part["blank_length_mm_source"] == "pdf_overall_dims"
    record = part["blank_from_detail_page"]
    assert record["page"] == page_no and record["replaced_envelope_mm"] == 400.0
    assert any("from its own detail sheet" in str(f) for f in part["review_flags"])


def test_the_size_is_marked_inferred_not_measured():
    """It is the drawing's printed OVERALL, which describes the finished part — real, and not a
    measurement. It must stay visibly inferred everywhere it lands, and rank below a DXF."""
    import source_precedence as sp

    summary = _summary([_page(21, 494.0, 199.0)])
    part = _part("JAE833", [21], 9.0)
    apply_detail_page_geometry([part], summary)
    assert sp.rank("pdf_overall_dims") < sp.rank("dxf")
    assert sp.rank("pdf_overall_dims") > sp.rank("geometry_inference")
    assert any("confirm before a firm quote" in str(f) for f in part["review_flags"])


# ── and the parts that must refuse to be sized ───────────────────────────────────────

def test_a_measured_blank_is_never_displaced():
    """A DXF flat or a model blank outranks this by design. It is not merely refused by
    arbitration — it is not offered, so a structured job records no displacement at all."""
    summary = _summary([_page(21, 494.0, 199.0)])
    part = _part("7332-01-005", [21], 1.5,
                 blank_length_mm=311.0, blank_width_mm=120.0, blank_length_mm_source="dxf")
    assert apply_detail_page_geometry([part], summary) == 0
    assert part["blank_length_mm"] == 311.0
    assert part["review_flags"] == []


def test_a_part_bound_to_a_parts_list_is_unresolved_not_guessed():
    """A parts list prints the ASSEMBLY's overall size. Taking it would put the whole stand's
    650 x 550 onto a corner block — the exact failure the GA-dimension rule already exists to
    stop — so the part keeps its fallback and the decision is made explicit."""
    summary = _summary([_page(3, 650.0, 550.0)], bom_zero_based=(2,))
    part = _part("JAE824", [3], 18.0)
    assert apply_detail_page_geometry([part], summary) == 0
    assert "blank_length_mm" not in part
    assert any("a parts list" in str(f) and "UNRESOLVED" in str(f)
               for f in part["review_flags"]), part["review_flags"]


def test_an_assembly_may_take_its_own_tables_page():
    """The exemption from part_index carries through: page 25 is MBY433's parts list AND the
    page that defines it, so it is not treated as somebody else's list."""
    summary = _summary([_page(25, 219.6, 24.0)], bom_zero_based=(24,),
                       owners={"MBY433": 24})
    part = _part("MBY433", [25], 2.0)
    assert apply_detail_page_geometry([part], summary) == 1
    assert part["blank_length_mm"] == 219.6


def test_an_ambiguous_binding_is_unresolved():
    """Two bound pages means the binding did not resolve. Picking one would be a guess wearing
    a source name."""
    summary = _summary([_page(9, 638.0, 75.0), _page(10, 502.0, 75.0)])
    part = _part("JAE821", [9, 10], 18.0)
    assert apply_detail_page_geometry([part], summary) == 0
    assert any("no single sheet defines it" in str(f) for f in part["review_flags"])


def test_a_refusal_from_the_credibility_guard_is_carried_in_the_drawings_own_terms():
    """blank_from_drawing_overalls holds the guardrails — both dimensions or nothing, thickness
    required, 10-4000mm, a folded part needs a developed length. Its reason reaches the part."""
    summary = _summary([_page(26, 24.0, None)])          # Ø24 disc: one figure, not a blank
    part = _part("MBY434", [26], 2.0)
    assert apply_detail_page_geometry([part], summary) == 0
    assert any("does not print both" in str(f) for f in part["review_flags"]), \
        part["review_flags"]


def test_a_folded_part_is_refused_without_a_developed_length():
    """A folded part's overall is not its blank — it unfolds longer. MBY435 passes only because
    its sheet prints an explicit FLAT PATTERN."""
    summary = _summary([_page(27, 418.0, 142.0)])
    part = _part("MBY435", [27], 2.0, operations=["folding", "laser_cutting"])
    assert apply_detail_page_geometry([part], summary) == 0
    assert any("folded" in str(f) for f in part["review_flags"])


# ── dimension isolation: the second half of the same defect ──────────────────────────

def test_dimension_text_from_another_part_page_is_dropped():
    """A part accumulates all_dimensions_mm from EVERY page it claims, ungated, and the
    estimator's sizing waterfall reads that list as a last resort. So a correct page selection
    upstream can still produce a wrong blank downstream — which is why this is in the same
    change and not the next one."""
    summary = _summary([
        _page(21, 494.0, 199.0, all_dims=("494.0", "199.0", "9.0")),
        _page(3, 650.0, 550.0, all_dims=("650.0", "550.0", "95.0")),
    ])
    part = _part("JAE833", [21], 9.0,
                 all_dimensions_mm=["494.0", "199.0", "9.0", "650.0", "550.0", "95.0"])
    assert isolate_dimension_text([part], summary) == 1
    assert part["all_dimensions_mm"] == ["494.0", "199.0", "9.0"]
    assert any("not bound to" in str(f) for f in part["review_flags"])


def test_a_clean_dimension_list_is_left_alone():
    summary = _summary([_page(21, 494.0, 199.0, all_dims=("494.0", "199.0"))])
    part = _part("JAE833", [21], 9.0, all_dimensions_mm=["494.0", "199.0"])
    assert isolate_dimension_text([part], summary) == 0
    assert part["review_flags"] == []
