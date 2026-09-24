"""12633-00, the Avanti display chiller shelf: the GA record went through the book as
"12633-00-GA (Bottle Support)", and the AI pricer researched a £3.25 price for a bottle
support under the GA's code.

Two defects led there. The pack carries "12633-00-GA Display Chiller Shelf_revB.DXF", the GA
drawing exported whole. The GA-sheet filter knew "-GA_", "-GA-" and "-GA." but not "-GA " with
a space after it, so the export was taken for a flat and promoted as an orphan part. The orphan
was then named with the LONGEST description on any BOM row sharing the job number, and among
the 12633 rows that was "Bottle Support".

A GA export is not a flat, and an orphan flat is named for itself: its own BOM row, else the
words in its own filename, never a sibling's.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import drawing_job_merge as djm  # noqa: E402

_FX = os.path.join(os.path.dirname(__file__), "fixtures")

_SIBLINGS = [
    {"part_number": "12633-01-GA", "description": "Wine Lifter"},
    {"part_number": "12633-01-01P", "description": "Base"},
    {"part_number": "12633-01-02P", "description": "Bottle Support"},
    {"part_number": "12633-01-03P", "description": "Front Foot"},
]


def _summary(parts=None, bom_rows=None):
    return {"manufacturing_writeup": {"parts": [dict(p) for p in (parts or _SIBLINGS)]},
            "document_analysis": {"bom_rows": [dict(r) for r in (bom_rows or _SIBLINGS)]}}


def test_a_ga_drawing_export_with_a_space_after_the_code_is_not_a_flat():
    assert djm.is_ignored_ga_dxf(Path("12633-00-GA Display Chiller Shelf_revB.DXF"))
    assert djm.is_ignored_ga_dxf(Path("12633-00-GA.DXF"))
    assert not djm.is_ignored_ga_dxf(Path("12633-01-02P - BOTTLE SUPPORT - 5MM PMMA.DXF"))
    assert not djm.is_flat_part_dxf(Path("12633-00-GA Display Chiller Shelf_revB.DXF"))


def test_an_orphan_is_not_named_after_the_longest_sibling():
    part = djm._create_orphan_dxf_part(
        _summary(), "12633-01-04P", Path("12633-01-04P - STOP - 5MM PMMA.DXF"))
    assert part["description"] == "STOP"


def test_an_orphan_takes_its_own_bom_row_first():
    rows = _SIBLINGS + [{"part_number": "12633-01-04P", "description": "Bottle Stop"}]
    part = djm._create_orphan_dxf_part(
        _summary(bom_rows=rows), "12633-01-04P", Path("12633-01-04P - STOP - 5MM PMMA.DXF"))
    assert part["description"] == "Bottle Stop"


def test_the_filename_words_lose_the_code_revision_gauge_and_material():
    name = djm._description_from_dxf_name
    assert name(Path("12633-00-GA Display Chiller Shelf_revB.DXF"), "12633-00-GA") \
        == "Display Chiller Shelf"
    assert name(Path("12633-01-02P - BOTTLE SUPPORT - 5MM PMMA.DXF"), "12633-01-02P") \
        == "BOTTLE SUPPORT"
    assert name(Path("11650-04-01A_2MM PETG_REVG.DXF"), "11650-04-01A") == ""


def test_a_filename_with_no_words_falls_back_to_the_code():
    part = djm._create_orphan_dxf_part(
        _summary(), "12633-01-04P", Path("12633-01-04P_5MM PMMA_REVA.DXF"))
    assert part["description"] == "12633-01-04P"


def test_end_to_end_the_ga_export_is_skipped_and_an_orphan_keeps_its_own_name(tmp_path):
    export = tmp_path / "12633-00-GA Display Chiller Shelf_revB.DXF"
    shutil.copy(os.path.join(_FX, "0355255 - A4 Table Top Graphic Holder - 10975_REV B.DXF"),
                export)
    orphan = tmp_path / "12633-01-04P - STOP - 5MM PMMA.DXF"
    shutil.copy(os.path.join(_FX, "1097502A01_2mm_ACRY_Rev_B.DXF"), orphan)
    out = djm.augment_summary_with_dxf(_summary(), [str(export), str(orphan)])
    report = out.get("dxf_augmentation") or {}
    assert any(s.get("reason") == "ga_dxf_ignored" and "12633-00-GA" in s.get("path", "")
               for s in report.get("skipped", [])), report.get("skipped")
    parts = {p["part_number"]: p for p in out["manufacturing_writeup"]["parts"]}
    assert "12633-00-GA" not in parts
    assert parts["12633-01-04P"]["description"] == "STOP"
    assert parts["12633-01-02P"]["description"] == "Bottle Support"
