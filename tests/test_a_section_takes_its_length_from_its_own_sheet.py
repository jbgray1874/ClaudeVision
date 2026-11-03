"""A section takes its length from its own sheet, and is lent no other part's blank (D-661).

12684-02-GA, 3 Nov 2026 18:11 (engine 90104a3). D-653 and D-657 made the outer frame (1/2" square
steel tube) and the cross bar (10 mm square steel bar) section stock, as their own title blocks
say. The live workbook then charged neither as a section:

  * M06 OUTER FRAME  Sheet Steel row, 39.7 x 30, "DIMS REQUIRED (gauge) - not costed"
  * M07 CROSS BAR    Sheet Steel row, 11 off 39.7 x 30 x 10 mm plate, GBP 2.17

39.7 x 30 is the hook bracket M01's SolidWorks flat. geometry_inference lent it, on the "same
material" tier, to every unsized steel part: the tube, the bar, the arm and the frame assembly
102SA. The section path needs a length, and none reached it: the sheet-blank reader had been the
only thing reading those sheets' figures (1500 beside UNDEVELOPED TUBE, 484.6), and once the parts
were sections it rightly stopped sizing them as sheet. So they fell through to sheet on the
borrowed flat.

The rules under test are generic:
  1. a part that uses no blank of its own (a section, an assembly) is lent none;
  2. a section with no length takes the largest figure printed on its OWN sheet, checked against
     the weight that sheet states: outside the band it is refused and asked; no weight, INDICATIVE;
  3. a figure printed with a leading zero (a phone number, "0116 274 7040") is not a dimension.

The drawings here are synthetic: two sheets printed by the test, not the customer's pack.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

fitz = pytest.importorskip("fitz")

import detail_page_geometry as dpg  # noqa: E402
import estimator as E  # noqa: E402
import geometry_inference as GI  # noqa: E402


@pytest.fixture(autouse=True)
def _no_catalogue(monkeypatch):
    """The section rates under test are the engine's own, not whatever a catalogue holds."""
    monkeypatch.setattr(E, "_lookup_catalogue_tube_price", lambda *a, **k: None)
    monkeypatch.setattr(E, "_lookup_catalogue_section_stock_rate", lambda *a, **k: None)


# Each sheet: (part number, [(text, x, y, rotate)]). A3 landscape, as the pack's sheets are.
# The phone line sits outside the title-block zone, where the real one does.
_PHONE = ("0116 274 7040", 598, 826, 0)
SHEETS = [
    ("T-01-M06", [("500", 274, 210, 0), ("1500", 577, 30, 0), ("UNDEVELOPED TUBE", 560, 50, 0),
                  ("12.7", 300, 400, 0), _PHONE]),
    ("T-01-M07", [("484.6", 447, 360, 0), ("10", 300, 420, 0), _PHONE]),
    ("T-01-M09", [("96", 447, 360, 0), ("10", 300, 420, 0), _PHONE]),
]


@pytest.fixture()
def pack(tmp_path):
    path = tmp_path / "pack.pdf"
    doc = fitz.open()
    for _pn, lines in SHEETS:
        page = doc.new_page(width=1190.55, height=841.89)
        for text, x, y, rot in lines:
            page.insert_text((x, y), text, fontsize=9, rotate=rot)
    doc.save(str(path))
    doc.close()
    weights = {"T-01-M06": ["0.58kg"], "T-01-M07": ["0.37kg"], "T-01-M09": []}
    pages = [{"page_number": i, "source_pdf_path": str(path),
              "page_analysis": {"title_block": {"drawing_numbers": [pn],
                                                "weights": weights[pn]}}}
             for i, (pn, _l) in enumerate(SHEETS, 1)]
    return {"pages": pages}


def _tube(**extra):
    """M06 as the 18:11 record held it: its own sheet's material, no length on any rung."""
    return dict({"part_number": "T-01-M06", "description": "OUTER FRAME", "quantity": 1,
                 "normalized_material": "MILD_STEEL",
                 "material_stated": '1/2" SQUARE STEEL TUBE',
                 "material_stated_source": "own_sheet_title_block", "pages": [1]}, **extra)


def _bar(**extra):
    return dict({"part_number": "T-01-M07", "description": "CROSS BAR", "quantity": 11,
                 "normalized_material": "MILD_STEEL",
                 "material_stated": "10mm SQUARE STEEL BAR",
                 "material_stated_source": "own_sheet_title_block", "pages": [2]}, **extra)


# ── the phone number is not a dimension ─────────────────────────────────────────────────

def test_a_figure_with_a_leading_zero_is_not_read(pack):
    figs = {round(v, 1) for v, _a in dpg.read_sheet_figures(pack["pages"][1])["figures"]}
    assert figs == {484.6, 10.0}, figs
    assert 116.0 not in figs and 274.0 not in figs


# ── 1. no blank is lent to a part that uses none ─────────────────────────────────────────

def _summary_with(*parts):
    return {"manufacturing_writeup": {"parts": list(parts)}}


def _bracket():
    """The hook bracket: a measured flat, the only steel part in the job with one."""
    return {"part_number": "T-01-M01", "description": "ARM BRACKET",
            "normalized_material": "MILD_STEEL", "dxf_augmented": True,
            "normalized_geometry": {"blank_length_mm": 39.72, "blank_width_mm": 30.0}}


def test_the_old_rule_lent_the_brackets_flat_to_a_tube():
    """What 18:11 did, shown on the same inputs with the new gate switched off."""
    tube = _tube()
    orig = dpg.not_cut_from_a_blank
    try:
        dpg.not_cut_from_a_blank = lambda part: False
        GI.infer_missing_geometry(_summary_with(_bracket(), tube))
    finally:
        dpg.not_cut_from_a_blank = orig
    assert tube["normalized_geometry"]["blank_length_mm"] == 39.7
    assert tube["geometry_inference"]["source_part"] == "T-01-M01"


def test_a_section_and_an_assembly_are_lent_no_blank():
    tube, bar = _tube(), _bar()
    frame = {"part_number": "T-01-102SA", "description": "FRAME",
             "normalized_material": "MILD_STEEL", "is_assembly_parent": True}
    got = GI.infer_missing_geometry(_summary_with(_bracket(), tube, bar, frame))
    for part in (tube, bar, frame):
        assert not (part.get("normalized_geometry") or {}).get("blank_length_mm"), part
        assert not part.get("geometry_inferred")
    assert {r["part"] for r in got["refused_no_blank"]} == {"T-01-M06", "T-01-M07",
                                                             "T-01-102SA"}


def test_a_sheet_part_with_no_size_is_still_lent_one():
    """The borrow itself is unchanged for a part cut from a blank."""
    plate = {"part_number": "T-01-M05", "description": "COVER PLATE",
             "normalized_material": "MILD_STEEL"}
    GI.infer_missing_geometry(_summary_with(_bracket(), plate))
    assert plate["normalized_geometry"]["blank_length_mm"] == 39.7


# ── 2. the section's length is its own sheet's ───────────────────────────────────────────

def test_the_tube_and_the_bar_take_the_length_their_own_sheets_print(pack):
    tube, bar = _tube(), _bar()
    done = dpg.apply_section_lengths_from_own_sheets([tube, bar], pack)
    assert done == ["T-01-M06", "T-01-M07"]
    t, b = tube["_section_length_from_own_sheet"], bar["_section_length_from_own_sheet"]
    assert t["length_mm"] == 1500.0 and t["agrees"] is True and t["wall_assumed"] is True
    assert b["length_mm"] == 484.6 and b["agrees"] is True and b["wall_assumed"] is False
    assert abs(b["mass_kg"] - 0.38) < 0.005, "10 x 10 x 484.6 of steel against its 0.37 kg"
    assert any("1500 mm read off its own sheet" in f and "working wall" in f
               for f in tube["review_flags"])


def test_a_short_bar_is_not_given_the_phone_numbers_274(pack):
    short = _bar(part_number="T-01-M09", pages=[3])
    dpg.apply_section_lengths_from_own_sheets([short], pack)
    got = short["_section_length_from_own_sheet"]
    assert got["length_mm"] == 96.0 and got["agrees"] is None, "no weight: INDICATIVE"


def test_a_length_its_weight_contradicts_is_refused_and_asked(pack):
    bar = _bar(stated_weight_kg=2.0)
    pack["pages"][1]["page_analysis"]["title_block"]["weights"] = []
    dpg.apply_section_lengths_from_own_sheets([bar], pack)
    assert not bar.get("_section_length_from_own_sheet")
    assert "NOT taken as its length" in bar["_section_length_refused"]


def test_a_length_a_reader_already_gave_is_kept(pack):
    bar = _bar(section_stock={"a": 10, "b": 10, "length_mm": 480.0})
    assert dpg.apply_section_lengths_from_own_sheets([bar], pack) == []
    assert not bar.get("_section_length_from_own_sheet")


def test_an_assembly_is_not_given_a_section_length(pack):
    frame = _tube(is_assembly_parent=True)
    assert dpg.apply_section_lengths_from_own_sheets([frame], pack) == []


# ── 3. and the money follows: a section, never the Sheet Steel block ─────────────────────

def test_without_a_length_the_bar_fell_through_to_sheet_on_the_borrowed_flat():
    """The 18:11 record exactly: section words, no length, the bracket's flat lent to it."""
    bar = _bar(normalized_thickness_mm=10.0,
               normalized_geometry={"blank_length_mm": 39.7, "blank_width_mm": 30.0,
                                    "_inferred": True,
                                    "blank_length_mm_source": "geometry_inference"})
    me = E.estimate_material(bar)
    assert me.get("stock_form") != "tube", "the gap this build closes"


def test_with_its_own_sheets_length_the_bar_is_costed_as_bar(pack):
    bar = _bar(normalized_thickness_mm=10.0)
    dpg.apply_section_lengths_from_own_sheets([bar], pack)
    me = E.estimate_material(bar)
    se = me["stock_estimate"]
    assert me["stock_form"] == "tube" and me["cost_method"].startswith("section_stock")
    assert se["section_length_source"] == E.SECTION_LENGTH_OWN_SHEET
    assert se["section_length_indicative"] is False, "its own sheet's weight agrees"
    assert me["unit_material_cost_gbp"] > 0


def test_the_tube_is_costed_as_half_inch_tube_on_its_sheets_1500(pack):
    tube = _tube()
    dpg.apply_section_lengths_from_own_sheets([tube], pack)
    me = E.estimate_material(tube)
    assert me["stock_form"] == "tube" and me["cost_method"].startswith("section_stock")
    assert me["stock_estimate"]["section_length_source"] == E.SECTION_LENGTH_OWN_SHEET
    assert abs(float(tube["section_stock"]["a"]) - 12.7) < 0.01


def test_a_length_no_weight_checks_is_priced_indicative(pack):
    short = _bar(part_number="T-01-M09", pages=[3], normalized_thickness_mm=10.0)
    dpg.apply_section_lengths_from_own_sheets([short], pack)
    me = E.estimate_material(short)
    assert me["stock_estimate"]["section_length_indicative"] is True
