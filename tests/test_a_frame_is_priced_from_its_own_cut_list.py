"""12173-02 Card Spinner, 17:34 book (D-380): the two tube frames 12173-03-04M / 05M were
each priced as UDEF row 11248-14 "L FRAME 30x30x2 @ 1395mm" — another job's made frame,
matched on its section and a length within 10% of the longest piece (1,532 mm). Each frame
is cut 1,532 x2 + 290 + 350 = 3,704 mm of 30x30x2 tube.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as e                                                 # noqa: E402
from source_connectors import llm_full_job as lj                      # noqa: E402

ROWS = [("11248-14", "L FRAME 30x30x2 TUBE @ 1395mm", 6.70, "Top Tubes", "EA"),
        ("SLOTTEDTUBE01", "ERW RECT. 60 x 30 x 1.5mm @ 1125mm", 3.57, "Preferred Tubes Ltd",
         "EA")]


def test_another_jobs_frame_never_prices_this_one():
    assert e._select_catalogue_section_row(ROWS, 30, 30, 2, 1532, "12173-03-04M") is None
    assert e._select_catalogue_section_row(ROWS, 30, 30, 2, 1395, "12173-03-04M") is None


def test_the_exact_item_and_a_stock_cut_piece_still_price():
    got = e._select_catalogue_section_row(ROWS, 30, 30, 2, 1395, "11248-14")
    assert got and got["part_code"] == "11248-14"
    got = e._select_catalogue_section_row(ROWS, 60, 30, 1.5, 1125)
    assert got and got["part_code"] == "SLOTTEDTUBE01"


def test_what_makes_a_row_a_made_part():
    assert "drawing number" in e._catalogue_row_is_a_made_part("11248-14", "TUBE 30x30x2")
    assert "made form" in e._catalogue_row_is_a_made_part("TT99", "SIDE FRAME 30x30x2")
    assert "names drawing" in e._catalogue_row_is_a_made_part("TT98", "TUBE FOR 9900-01-02M")
    assert e._catalogue_row_is_a_made_part("SLOTTEDTUBE02",
                                           "ERW RECT. 60 x 30 x 1.5mm @ 1072mm") == ""


def test_a_cut_list_is_the_length():
    p = {"part_number": "12173-03-04M",
         "section_stock": {"a": 30, "b": 30, "t": 2, "length_mm": 1532,
                           "cut_lengths_mm": [1532, 1532, 290, 350]}}
    assert e._infer_section_length_mm(p) == 3704
    assert p["_section_length_reader"] == "cut_list_sum"
    one = {"section_stock": {"a": 30, "b": 30, "t": 2, "length_mm": 1532}}
    assert e._infer_section_length_mm(one) == 1532


def test_the_extract_carries_every_piece_onto_the_section():
    src = (ROOT / "src" / "llm_full_extract.py").read_text(encoding="utf-8")
    assert '"cut_lengths_mm": []' in src and "one number per piece" in src
    assert '"cut_lengths_mm": row.get("cut_lengths_mm") or None' in src
    js = (ROOT / "src" / "source_connectors" / "llm_full_job.py").read_text(encoding="utf-8")
    # D-383: the pieces are submitted through source_precedence, field by field, so a cut
    # list read off the part's own table is never clobbered by the transcription.
    assert '_fields.append(("cut_lengths_mm", _pieces))' in js
    assert lj is not None
