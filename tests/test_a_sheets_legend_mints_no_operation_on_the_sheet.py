"""The standing specification printed on every sheet is a route cue on none of them (D-438).

8188-08-SA04, the acrylic waves sub-assembly: its own title block states no material, finish or
colour, and its notes say BONDED and MAG TAPE TO REAR FOOT. The page-level operation inference
read the whole page — border legend included — and minted powder_coating from "Q195 UP TO 3mm
THICK FOR POWDER COATED STEEL" and "POWDERCOATING: BETWEEN 80 - 120 MICRON". The weld and
material readers had the legend removed since D-394; this one did not. The 17:37 book charged a
P.Coat on the acrylic waves assembly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import extractor_patterns as ep                                       # noqa: E402

_LEGEND = """GENERAL TOLERANCES: FINISH SPECIFICATIONS: THIS DRAWING IS THE PROPERTY OF
LINEAR DIMENSIONS UP TO 120mm +/-0.5mm • POWDERCOATING: BETWEEN 80 - 120 MICRON
OVER 120mm UP TO 1000mm +/-1.0mm THICKNESS COVERAGE MARKS & SPENCER AND MAY NOT BE
WELD SPECIFICATION: • CHROME PLATING: NICKEL LAYER = 8 - 12 MICRON.
• ALL WELDS TO BE TIG UNLESS STATED • BRIGHT ZINC PLATING: 13 - 15 MICRON THICKNESS.
• RESISTANCE WELDING WIRE TO WIRE THE SET DOWN SHOULD BE 20% UNLESS STATED
CHINA MATERIAL SPECIFICATIONS: • Q195 UP TO 3mm THICK FOR POWDER COATED STEEL
• SPCC UP TO 3mm THICK FOR CHROME, ZINC PLATE OR HIGH QUALITY PAINT FINISH
• Q235 OVER 3mm THICK FOR POWDER COATED STEEL • 304 - STAINLESS STEEL
• ALWAYS REMOVE BURRS AND SHARP CORNERS
"""

_WAVES_SHEET = """ITEM NO. PartNo Description QTY.
1 8188-08-014 WAVE LAYER 2 1
2 8188-08-013 WAVE LAYER 3 1
3 8188-08-015 WAVE LAYER 1 1
REAR FOLDED FOOT BUTTS UP AGAINST PANEL BEHIND TO ENSURE CORRECT SPACING.
ALL LAYERS HAVE 25MM FEET. BONDED 17 MAG TAPE TO REAR FOOT
WAVES SUB ASSY MATERIAL: FINISH: COLOUR: WEIGHT: 24419.60g DRAWING No 8188-08-SA04 1:10 H
"""


def test_the_legend_alone_mints_no_coat_on_an_acrylic_sheet():
    s = ep.build_textual_manufacturing_summary(_WAVES_SHEET + _LEGEND)
    assert "powder_coating" not in s["inferred_operations"], s["inferred_operations"]
    assert "welding" not in s["inferred_operations"], s["inferred_operations"]
    assert "glue" in s["inferred_operations"]


def test_the_sheets_own_finish_still_mints_its_coat():
    sheet = _WAVES_SHEET.replace("FINISH: COLOUR:", "FINISH: POWDER COATED - MATT COLOUR: RAL 9005")
    s = ep.build_textual_manufacturing_summary(sheet + _LEGEND)
    assert "powder_coating" in s["inferred_operations"], s["inferred_operations"]


def test_a_sheet_without_the_legend_reads_as_before():
    assert ep.build_textual_manufacturing_summary(_WAVES_SHEET)["inferred_operations"] == \
        ep.build_textual_manufacturing_summary(_WAVES_SHEET + _LEGEND)["inferred_operations"]
