"""A material callout is read whole, and its gauge is the part's (27 Nov 2026).

Hotel Chocolat's component sheets print "MATERIAL:1.5mm CR4 SHEET STEEL 2500X1250 (30000128);".
The reader stopped the field at SHEET (taken for "SHEET 1 OF 2"), knew no CR4, and so gave 46
steel sheets no material; one of them took ACRYLIC from its revision note instead. A wrapped
note's "REMOVED" after the callout stripped it, and "2mm PVC EDGING" put 2.0 on 1.5mm parts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extractor_patterns import extract_title_block_fields  # noqa: E402

NOTES = ("2mm PVC EDGING TO RECIEVE A 2mm RADIUS UNLESS OTHERWISE STATED.\n"
         "1mm PVC EDGING OR LAMINATE EDGING TO HAVE THE SHARP EDGES\n")


def _read(text):
    f = extract_title_block_fields(text)
    return f["materials"], f["normalized"]["primary_thickness_mm"]


def test_cold_rolled_and_structural_sheet_steel_are_mild_steel_at_the_callouts_gauge():
    assert _read(NOTES + "MATERIAL:1.5mm CR4 SHEET STEEL 2500X1250 (30000128);\nREMOVED.") == \
        (["MILD STEEL"], 1.5)
    assert _read("MATERIAL:5.0mm S275JR SHEET STEEL CRPO 2500X1250 (30002835);") == (["MILD STEEL"], 5.0)
    assert _read("MATERIAL: 2mm DC01 STEEL") == (["MILD STEEL"], 2.0)


def test_a_wrapped_note_after_the_callout_does_not_remove_the_material():
    text = NOTES + "MATERIAL:1.5mm CR4 SHEET STEEL 2500X1250 (30000128); REMOVED.\nALL MATERIAL ABOVE 5mm"
    assert _read(text) == (["MILD STEEL"], 1.5)


def test_sheet_still_ends_a_field_as_the_sheet_label():
    assert _read("MATERIAL: 18mm MDF SHEET 1 OF 2")[0] == ["MDF"]
    assert _read("MATERIAL: MILD STEEL SHEET: 2")[0] == ["MILD STEEL"]


def test_a_revision_row_never_names_the_parts_material():
    text = ("WOC BOX BASE SPACER\nISSUE DATE TSD No. REMARKS\n"
            "2 22/04/2026 033986 AND WIDTH OF TRAY TO ACCEPT ACRYLIC CAW\n"
            "1 30/03/2026 033855 ORIGINAL RPW")
    assert _read(text)[0] == []
    assert _read("PANEL\nMDF 18mm\nA 01/02/2026 WAS ACRYLIC")[0] == ["MDF"]
