"""The drawing states the work; the reader takes it as stated, and nothing else (D-762).

JG, 9 Nov 2026, with the whole 0358141 pack: "the drawing tells us all the operations it
needs. If it states on the drawing, it is needed." A fresh deterministic scan of that PDF read
each member's own sheet (D-758, D-761) and still mis-stated the work:

* the rub strips M2 and M3 were folded: their only angle is the countersink's "6.3 X 90.00°",
  and the scan took any angle for fold geometry (D-511 had closed this for the text rule only);
* their countersinks were missed, and a countersink landed on the bought-in leveller, from
  "M3 x 10mm S/S CSK BOLT" on the parts list it shares;
* the rail M1 had no tapping: "(9x) M3x0.5" is a thread with its pitch, not the word TAP;
* M1's tube length was 480, the plan's depth, where the sheet prints "1394 TUBE" and
  "1170 TUBE" against the tubes themselves.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from extractor_patterns import infer_operations_from_text as infer  # noqa: E402
from extractor_patterns import strip_specification_legend as strip  # noqa: E402
from section_profile import detect_section_stock as section  # noqa: E402


def _ops(text, **kw):
    return sorted(set(infer(strip(text), **kw)) - {"handling"})


def test_a_thread_with_its_pitch_is_a_tapped_hole_and_a_bolt_length_is_not():
    assert "tapping" in _ops("(9x) M3x0.5 TOP FACE")
    assert "tapping" in _ops("4 x M8 x 1.25 THREADED HOLES")
    assert "tapping" not in _ops("M3 x 10mm S S CSK BOLT")
    assert "tapping" not in _ops("M8 x 22 Base Leveller")


def test_a_countersink_angle_is_a_countersink_and_a_csk_bolt_is_a_bolt():
    assert "countersinking" in _ops("(5x) 3.4 THRU n 6.3 X 90.00° w n")
    assert "countersinking" in _ops("CSK HOLES 4 PLACES")
    assert "countersinking" not in _ops("9 M3 x 10mm S S CSK BOLT")
    assert "countersinking" not in _ops("4 x CSK SCREWS SUPPLIED")


def test_an_angle_alone_is_not_fold_geometry_at_scan_time():
    from extractor_patterns import build_textual_manufacturing_summary as scan
    page = scan("LONG RUB STRIP 3mm STAINLESS STEEL (5x) 3.4 THRU 6.3 X 90.00° 1168 O/A",
                )
    assert "folding" not in (page.get("inferred_operations") or [])
    folded = scan("BRACKET 2mm MILD STEEL FOLD UP 90° 2 FOLDS")
    assert "folding" in (folded.get("inferred_operations") or [])


def test_the_figure_labelled_tube_is_the_length_and_several_are_the_pieces():
    one = section("30x30x2mm M/S UPRIGHTS 30 111.85 1383 TUBE 15 30")
    assert one["length_mm"] == 1383.0 and one["length_source"] == "tube_callout"
    many = section("15x30x2mm M/S TOP TUBE 3 480 7.5 O/A 1200 CTS 1394 TUBE BASE VIEW 1170 TUBE")
    assert many["cut_lengths_mm"] == [1170.0, 1394.0] and many["length_mm"] == 2564.0
    assert many["length_source"] == "tube_callouts" and many["pieces_counted_once"]
    plain = section("30 x 60 x 1.50mm TUBE 1125")
    assert plain["length_mm"] == 1125.0
