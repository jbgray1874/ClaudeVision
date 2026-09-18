"""The phantom 792 x 760.3 — two parts' dimensions, from two pages, assembled into one blank.

0355255's blank check reported, twice, and was hunted three times:

    blank check: DXF flat 792 x 760.3mm is 377% of the model flat

NEITHER NUMBER IS WRONG AND NEITHER CAME FROM THE DXF. Reading the pack:

    page 1   the ACRYLIC L-STAND. MATERIAL: ACRYLIC, WEIGHT: 381g, and 760.3 among its
             dimensions. The DXF agrees with it exactly — 760.252 x 210, two bend lines,
             2mm, cut length 1937mm.
    page 2   the GRAPHIC. MATERIAL: PAPER, WEIGHT: 3g, and 792 x 210. A different part.

`source_precedence` writes one FIELD at a time and each wins its own arbitration, so
`blank_length_mm` could be taken from whichever reading won for length while
`blank_width_mm` came from whichever won for width. The 377% is arithmetic on a pair that
was never measured off anything.

WHY IT SURVIVED THREE FIXES. Every one of them was to the DXF reader — `_is_flat_pattern`
gained the DIMENSION rule, `merge_dxf_into_scan_json` learned to consult the claim, and
`drawing_export_reason` has refused this GA since 11350. All three work, and all three are
verified below against the real files. The DXF was never involved: `_dxf_blank_mm` answers
the general question "what is this part's developed blank" and its one caller prints the
answer as "DXF flat", so a PDF-page reading came back wearing a citation that sent three
people to the wrong module.

A WRONG CITATION IS WORSE THAN NO FIGURE. An unsourced number invites checking; a cited one
stops it. That is the same lesson as £321.88 and the same lesson as the fold count's
"counted by dxf_bendlines_layer" on a figure the DXF did not produce.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from document_builder import flat_blank_mm                             # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
GA = FIXTURES / "0355255 - A4 Table Top Graphic Holder - 10975_REV B.DXF"
FLAT = FIXTURES / "1097502A01_2mm_ACRY_Rev_B.DXF"


# ── the pair ────────────────────────────────────────────────────────────────────────

def test_a_blank_from_two_readers_is_not_a_blank():
    """THE PHANTOM, IN ONE ASSERTION. 792 won the length arbitration off page 2's paper
    graphic; 760.3 won the width off page 1's acrylic L-stand. Neither reader measured the
    pair, so there is no pair."""
    part = {
        "blank_length_mm": 792.0, "blank_length_mm_source": "pdf_overall_dims",
        "blank_width_mm": 760.3, "blank_width_mm_source": "dxf_flat_pattern",
    }
    assert flat_blank_mm(part) == (None, None)


def test_a_blank_from_one_reader_is_kept():
    """The control. A guard that refuses every blank is not a guard."""
    part = {
        "blank_length_mm": 760.252, "blank_length_mm_source": "dxf_flat_pattern",
        "blank_width_mm": 210.0, "blank_width_mm_source": "dxf_flat_pattern",
    }
    assert flat_blank_mm(part) == (760.252, 210.0)


def test_an_unstamped_record_is_left_alone():
    """NARROW ON PURPOSE. Where nothing recorded a source — a legacy record, or a reader
    older than the stamps — the pair is taken as it always was. Refusing it would throw away
    every blank the engine holds rather than the ones it assembled."""
    assert flat_blank_mm({"blank_length_mm": 300.0, "blank_width_mm": 200.0}) == (300.0, 200.0)


def test_the_dxfs_own_geometry_is_unaffected():
    """`normalized_geometry` is written whole by one reader, so it is answered before any of
    this — the shape the DXF path actually produces must not change."""
    part = {"normalized_geometry": {"blank_length_mm": 760.252, "blank_width_mm": 210.0}}
    assert flat_blank_mm(part) == (760.252, 210.0)


# ── and the citation ────────────────────────────────────────────────────────────────

def test_a_blank_that_is_not_the_dxfs_is_not_reported_as_the_dxfs():
    """The one caller prints "DXF flat {l} x {w}mm" in every sentence it produces."""
    from source_connectors.solidworks import _dxf_blank_mm
    pdf_sized = {
        "blank_length_mm": 792.0, "blank_length_mm_source": "pdf_overall_dims",
        "blank_width_mm": 210.0, "blank_width_mm_source": "pdf_overall_dims",
        "dxf_augmented": True,
    }
    assert _dxf_blank_mm(pdf_sized) == (None, None)


def test_a_part_with_no_dxf_at_all_offers_no_dxf_blank():
    from source_connectors.solidworks import _dxf_blank_mm
    assert _dxf_blank_mm({"blank_length_mm": 300.0, "blank_width_mm": 200.0}) == (None, None)


def test_the_dxfs_own_blank_still_reaches_the_arbitration():
    """The control again — the cross-check this pair exists for must still happen."""
    from source_connectors.solidworks import _dxf_blank_mm
    part = {"dxf_augmented": True,
            "normalized_geometry": {"blank_length_mm": 760.252, "blank_width_mm": 210.0}}
    assert _dxf_blank_mm(part) == (760.252, 210.0)


def test_the_arbitration_says_no_dxf_rather_than_inventing_a_disagreement():
    """What an estimator reads instead of the phantom. It is true, and it is the sentence
    that would have ended the hunt on the first reading."""
    from geometry_arbitration import arbitrate_flat
    said = arbitrate_flat(None, None, 760.252, 210.0)["reason"]
    assert "no DXF blank could be measured" in said
    assert "792" not in said


# ── the pack itself ─────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not GA.is_file() or not FLAT.is_file(), reason="pack not in fixtures")
def test_the_three_earlier_fixes_all_work_on_the_real_files():
    """THE POINT OF RECORDING THIS. Three fixes went into the DXF reader for a defect the DXF
    reader never had. They are correct and they stay; this asserts they do their job, so the
    next person reading the register does not go back to them a fourth time."""
    ezdxf = pytest.importorskip("ezdxf")                             # noqa: F841
    from drawing_job_merge import drawing_export_reason
    from dxf_reader import extract_flat_pattern_data

    assert "dimension" in (drawing_export_reason(GA) or "").lower(), \
        "the GA sheet must still be refused as a drawing"
    assert extract_flat_pattern_data(GA).get("flat_pattern_detected") is False

    assert drawing_export_reason(FLAT) is None, "the real flat must still be accepted"
    flat = extract_flat_pattern_data(FLAT)
    assert flat.get("flat_pattern_detected") is True
    # The DXF's own answer, which was right all along and is neither of the phantom's numbers.
    assert round(flat["blank_length_mm"], 1) == 760.3
    assert round(flat["blank_width_mm"], 1) == 210.0


# ── and the pack's other line: does everything enter the pipeline? ──────────────────

def test_a_printed_line_is_not_assumed_to_be_free():
    """0355255's SECOND part, and the second thing found by reading the pack.

    PAPER and PRINTED_PAPER sat in a set beside BOUGHT_IN and took its rule with them, so a
    printed line short-circuited to £0.00 `customer_supplied` BEFORE reaching a single pricing
    rung. The GRAPHIC is 792 x 210, MATERIAL: PAPER, WEIGHT: 3g, "COLOUR: CLIENT ARTWORK —
    SEE PRINT SPEC".

    The ARTWORK is the client's. Whether SDI prints it, buys the print, or receives it
    finished is a commercial fact about the job, and the word PAPER is evidence of none of
    the three.

    BOUGHT_IN keeps its meaning: that material has been normalised to "the customer supplies
    this", which is a decision somebody made about the line. A material name is not a
    decision.
    """
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "estimator.py").read_text(
        encoding="utf-8")
    at = src.index("BOUGHT_IN MEANS THE CUSTOMER SUPPLIES IT")
    window = src[at:at + 1800]
    gate = re.search(r'normalized_material.*?\.upper\(\) in \{([^}]*)\}', window)
    assert gate, "the customer-supplied gate moved — check what it now keys on"
    assert "PAPER" not in gate.group(1), \
        "a printed line is short-circuited to £0 again, before any pricing rung"
    assert "BOUGHT_IN" in gate.group(1), \
        "BOUGHT_IN is the stated rule and must keep its meaning"
