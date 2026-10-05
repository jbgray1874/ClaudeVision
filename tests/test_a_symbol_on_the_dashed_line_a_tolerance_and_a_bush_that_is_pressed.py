"""12696-01 Bag Pricing Hook, 5 Oct 14:36 book on 169f792 (D-392). The route was right — one
weld, its dress and the powder on 101, the brackets lasered and folded raw, the PETG strip on
the acrylic side, the fasteners one line each — and five readings were wrong:

* the weldment's two fillet symbols sit on the dashed identification line (an other-side
  weld, ISO 2553) and the reader looked only on the reference line: "unclassified", so the
  weld reached the book as an inference to be asked about, not a drawn weld;
* "+/-1.0mm THICKNESS" — the border's tolerance beside the coating paragraph — read as a
  1 mm gauge on every sheet, and the fallback scan took "+/-0.5mm ... +/-2.0mm" too;
* FIXING 297 priced from the catalogue's "HANK BUSH M5 x 18G - HEXAGON" while the drawing
  says ROUND, and the book showed only the catalogue's words;
* the weldment's powder, read off its own title block, recorded as rank-20 "inference"
  because the page inference had added the op first;
* the hank bush was fitted by nobody: the pressed-fastener words did not include it, and
  they lived in the compiler, not in config;
* 01M's 102.7 x 76 blank at 2 mm weighs 0.12 kg against WEIGHT: 0.06kg on its sheet, which
  1 mm fits exactly, and nothing read the weight.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config                                                         # noqa: E402
import estimator                                                      # noqa: E402
import extractor_patterns as ep                                       # noqa: E402
import route_compiler as rc                                           # noqa: E402
import weld_symbols as ws                                             # noqa: E402


def _ln(x0, y0, x1, y1, dash=None):
    """A pdfplumber-style line: x0<=x1, top<=bottom, with the stroke's true ends in pts."""
    return {"x0": min(x0, x1), "x1": max(x0, x1), "top": min(y0, y1), "bottom": max(y0, y1),
            "dash": dash, "pts": [(x0, y0), (x1, y1)]}


def _sheet_two_callout(dx=0.0, dy=0.0):
    """12696-01-101's callout at (504, 535), as pdfplumber reports it, shifted by dx, dy."""
    return [
        _ln(496.2 + dx, 535.0 + dy, 511.7 + dx, 535.0 + dy),                     # reference line
        _ln(496.2 + dx, 535.0 + dy, 480.0 + dx, 520.0 + dy),                     # leader to its end
        _ln(496.2 + dx, 537.7 + dy, 511.7 + dx, 537.7 + dy, dash=([3.6, 1.8], 2.14)),  # identification line
        _ln(501.6 + dx, 537.8 + dy, 506.3 + dx, 537.8 + dy),                     # triangle base ON the dashed line
        _ln(501.6 + dx, 537.8 + dy, 501.6 + dx, 543.1 + dy),                     # vertical leg
        _ln(506.3 + dx, 537.8 + dy, 501.6 + dx, 543.1 + dy),                     # hypotenuse
    ]


# ── the fillet on the identification line ────────────────────────────────────────────────

def test_a_fillet_drawn_on_the_identification_line_is_a_fillet():
    lines = _sheet_two_callout() + _sheet_two_callout(52.1, 115.9)
    found = ws.read_weld_symbols(lines, [])
    assert [s["kind"] for s in found] == ["fillet", "fillet"]
    assert all(s["identification_line"] for s in found)
    assert ws.arc_weld_symbols(ws.count_by_kind(found)) == 2


def test_a_fillet_on_the_reference_line_still_reads():
    lines = [
        _ln(100, 200, 140, 200), _ln(100, 200, 90, 190),
        _ln(100, 203, 140, 203, dash=([3.6, 1.8], 0)),
        _ln(115, 200, 120, 200), _ln(115, 200, 115, 194.8), _ln(120, 200, 115, 194.8),
    ]
    assert [s["kind"] for s in ws.read_weld_symbols(lines, [])] == ["fillet"]


# ── a tolerance is not a gauge ────────────────────────────────────────────────────────────

def test_the_borders_tolerance_beside_the_coating_paragraph_is_not_a_gauge():
    border = ("OVER 120mm UP TO 1000mm +/-1.0mm THICKNESS COVERAGE OVER 1000mm UP TO 2000mm "
              "+/-1.5mm OVER 2000mm UP TO 4000mm +/-2.0mm ANGLES +/-0.5 DEG")
    assert ep._extract_thickness_fallbacks(border) == []
    assert not ep.extract_title_block_fields(border).get("thicknesses_mm")
    stated = border + "  MATERIAL: 2mm MILD STEEL  FINISH: RAW"
    assert ep.extract_title_block_fields(stated).get("thicknesses_mm") == ["2"]
    assert ep.extract_title_block_fields("PLATE 3mm THK, ±0.5mm").get("thicknesses_mm") == ["3"]


# ── the code matched, the words differ ────────────────────────────────────────────────────

def test_a_catalogue_row_whose_words_differ_from_the_drawings_is_named():
    assert estimator._catalogue_words_disagree(
        "M5 x18G ROUND HANK BUSH", "HANK BUSH M5 x 18G - HEXAGON") == "ROUND v HEXAGON"
    # the catalogue merely saying more is not a disagreement; nor is word order
    assert estimator._catalogue_words_disagree(
        "M5 x 10MM - FLAT THUMBSCREW", "THUMBSCREW FLAT M5 X 10 BLACK") == ""
    assert estimator._catalogue_words_disagree("", "HANK BUSH") == ""


def test_the_priced_bush_carries_the_drawings_words_beside_the_catalogues(monkeypatch):
    monkeypatch.setattr(estimator, "_lookup_udef_exact_code",
                        lambda code: {"description": "HANK BUSH M5 x 18G - HEXAGON",
                                      "unit_price_gbp": 0.11, "supplier": "Elite"})
    rows = [{"part_number": "FIXING 297", "description": "M5 x18G ROUND HANK BUSH", "quantity": 1}]
    found = estimator._recognise_sdi_coded_bought_in("FIXING 297 M5 x18G ROUND HANK BUSH", set(),
                                                     bom_rows=rows)
    assert len(found) == 1
    flags = " ".join(found[0].get("review_flags") or [])
    assert "CODE MATCHED, WORDS DIFFER" in flags and "ROUND v HEXAGON" in flags
    assert found[0]["drawing_description"] == "M5 x18G ROUND HANK BUSH"
    assert found[0]["unit_cost_gbp"] == 0.11                      # the price is the code's


# ── the sheet's own coat outranks the page inference ─────────────────────────────────────

def test_a_coat_the_page_inferred_is_restated_by_the_sheets_finish():
    weldment = {"part_number": "X-101", "is_assembly_parent": True,
                "assembly_children": ["X-01M", "X-02M"],
                "textual_operations": ["welding", "powder_coating"],
                "operation_sources": {"powder_coating": "inference"}}
    m1 = {"part_number": "X-01M", "owning_assembly": "X-101", "normalized_material": "MILD_STEEL"}
    m2 = {"part_number": "X-02M", "owning_assembly": "X-101", "normalized_material": "MILD_STEEL"}
    by_part = {"X-101": {"finish": "POWDER COATED", "pages": [2]},
               "X-01M": {"finish": "RAW"}, "X-02M": {"finish": "RAW"}}
    stated = ws.apply_finish_coats([weldment, m1, m2], by_part)
    assert stated == ["X-101"]
    assert weldment["operation_sources"]["powder_coating"] == "drawing_deterministic"
    assert weldment["textual_operations"].count("powder_coating") == 1


# ── a hank bush is pressed in ─────────────────────────────────────────────────────────────

def test_a_hank_bush_is_a_pressed_fastener_and_the_words_live_in_config():
    assert "HANK BUSH" in config.HARDWARE_INSERTION_WORDS
    assert rc.is_pressed_fastener("FIXING 297 M5 x18G ROUND HANK BUSH")
    assert rc.is_pressed_fastener("FIXING49 M6 THINSHEET THREADED INSERT")
    assert not rc.is_pressed_fastener("ACCU-SKTT-M5-10-A1-BL M5 x 10MM - FLAT THUMBSCREW")


# ── the weight check ──────────────────────────────────────────────────────────────────────

def test_a_blank_that_weighs_twice_its_sheets_weight_names_the_gauge_the_weight_fits():
    part = {"part_number": "X-01M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 2.0, "stated_weight_g": 60.0,
            "normalized_geometry": {"blank_length_mm": 102.7, "blank_width_mm": 76.0}}
    msg = estimator._blank_weight_check(part)
    assert msg and "weighs 0.123 kg" in msg and "states 0.060 kg" in msg and "fits 0.98 mm" in msg
    # 02M at 2 mm weighs what its sheet says: nothing to say
    ok = {"part_number": "X-02M", "normalized_material": "MILD_STEEL",
          "normalized_thickness_mm": 2.0, "stated_weight_g": 40.0,
          "normalized_geometry": {"blank_length_mm": 98.14, "blank_width_mm": 25.0}}
    assert estimator._blank_weight_check(ok) is None
    # no stated weight, no check
    assert estimator._blank_weight_check({"normalized_thickness_mm": 2.0,
                                          "normalized_geometry": {"blank_length_mm": 100, "blank_width_mm": 50}}) is None


# ── the fold sentence says when the model agrees ─────────────────────────────────────────

def test_the_model_agreeing_with_the_charged_fold_count_is_said():
    assert estimator._model_bends_agree({"solidworks_bend_features": 1}, 1)
    assert not estimator._model_bends_agree({"solidworks_bend_features": 3}, 2)
    assert not estimator._model_bends_agree({}, 1)
