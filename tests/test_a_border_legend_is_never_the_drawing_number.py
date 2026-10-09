"""A border's legend is never the drawing number, and a pooled pack hands down no gauge (D-421).

8188-08 M&S Hero Header Fishmonger, 9 Oct 2026, run offline on the three PDFs before the
first live run. The M&S border prints its specification list below the drawing-number cell —
"• 6063 - ALUMINIUM FOR EXTRUSION", "• 304 - STAINLESS STEEL" — set a character at a time.
The title-block reader takes the lowest code-shaped token, joined across spaces, and every one
of 17 sheets read "6063-ALUMINIUMFOREXTRUSION": it became the root of the product, the declared
8188-08 resolved to nothing, and the swing stopper Rev G deleted was pulled into the bill. The
GA's own cell, "8188-08_GA", matched no shape for its underscore.

Then the gauges: "20MM MAG TAPE" was read as a 20 mm gauge and, as the pooled pack's only
figure, given to every part; with that gone, the GA's "3MM", "6MM" and "10MM" acrylic notes
made 3 mm the document's gauge for the 18 mm MDF. The pooled document's material came out
TIMBER and the wire frame inherited it. A part sheet's own "3 MATL." was never read.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import _bom_words_reader as wr  # noqa: E402
import extractor_patterns as ep  # noqa: E402


def _w(text, x0, x1, top, h=6.0):
    return {"text": text, "x0": float(x0), "x1": float(x1), "top": float(top),
            "bottom": float(top) + h}


def _chars(text, x0, top, width=3.0, h=6.0):
    """A line laid down a character at a time, the letters touching, words a space apart."""
    out, x = [], float(x0)
    for ch in text:
        if ch == " ":
            x += 2.5
            continue
        out.append(_w(ch, x, x + width, top, h))
        x += width
    return out


def _sheet(cell_text):
    return ([_w("NOTE", 10, 30, 10)]                                  # the page's top
            + [_w(cell_text, 900, 960, 790, 10)]                      # the drawing-number cell
            + [_w("•", 231, 233, 799), _w("6063", 236, 252, 799), _w("-", 254, 256, 799),
               _w("ALUMINIUM", 258, 290, 799), _w("FOR", 292, 302, 799),
               _w("EXTRUSION", 304, 340, 799)]                        # legend, whole words
            + _chars("304 - STAINLESS STEEL", 400, 801))              # legend, letter by letter


def test_the_cell_is_read_and_the_legend_below_it_is_not():
    assert wr._title_block_dwg_no(_sheet("8188-29-002")) == "8188-29-002"


def test_an_underscore_in_the_cell_is_a_separator():
    assert wr._title_block_dwg_no(_sheet("8188-08_GA")) == "8188-08-GA"


def test_a_legend_alone_names_no_drawing():
    words = [_w("NOTE", 10, 30, 10)] + _chars("6063 - ALUMINIUM FOR EXTRUSION", 236, 799)
    assert wr._title_block_dwg_no(words) is None


def test_a_short_designator_still_reads():
    for code in ("12392-02-GA", "9598-02-01M", "8188-08-SA05", "12343-01J"):
        assert wr._title_block_dwg_no([_w("NOTE", 10, 30, 10), _w(code, 900, 960, 790)]) \
            == code


def test_a_tape_width_is_not_a_gauge_and_a_stated_gauge_still_is():
    text = ("20MM MAGTAPE TO BASE FOLD. LASERED 3MM ACRYLIC. 20MM MAG TAPE. "
            "6MM GLUE IN DOWEL. ALL LAYERS HAVE 25MM FEET.")
    assert ep._extract_thickness_fallbacks(text) == ["3"]


def test_matl_is_a_gauge():
    import re
    import config
    found = [a or b for a, b in re.findall(config.THICKNESS_PATTERN, "R5 3 MATL. 2 x 8 X 15",
                                           flags=re.IGNORECASE)]
    assert found == ["3"]


def test_a_document_of_several_gauges_hands_none_down():
    from part_index import document_gauge_to_hand_down
    pooled = {"document_analysis": {"title_block": {"thicknesses_mm": ["3", "10", "6"]},
                                    "primary_fields": {"thickness_mm": 3.0}}}
    single = {"document_analysis": {"title_block": {"thicknesses_mm": ["1.5", "1.50"]},
                                    "primary_fields": {"thickness_mm": 1.5}}}
    assert document_gauge_to_hand_down(pooled) is None
    assert document_gauge_to_hand_down(single) == 1.5


def test_a_document_of_several_materials_hands_none_down():
    from file_scan import _inherit_document_material_to_parts
    mixed = {"title_block": {"materials": ["TIMBER", "ACRYLIC", "MDF"],
                             "normalized": {"primary_material": "TIMBER"}},
             "primary_fields": {"normalized_material": "TIMBER"}}
    part = {"part_number": "8188-08-004", "description": "WIRE WORK MESH FRAME"}
    _inherit_document_material_to_parts([part], mixed)
    assert not part.get("normalized_material") and not part.get("materials")

    one = {"title_block": {"materials": ["MILD STEEL", "MILD STEEL"],
                           "normalized": {"primary_material": "MILD STEEL"}},
           "primary_fields": {"normalized_material": "MILD_STEEL"}}
    part = {"part_number": "1282-03", "description": "BRACKET"}
    _inherit_document_material_to_parts([part], one)
    assert part.get("material_inherited_from") == "document_level"
