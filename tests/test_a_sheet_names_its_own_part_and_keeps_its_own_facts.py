"""A sheet names its own part, and that part keeps its own facts (D-657).

12684-02-GA, 3 Nov 2026 16:22 run. The deterministic facts reader read each sheet's drawing number
with segments of at most four characters, so 12684-02-101SA, 102SA and 103SA never matched: each
assembly sheet took the last child code its parts list printed. Page 5 (the frame 102SA) became
M04, page 7 (the framework 103SA) became M07, and their title blocks were rolled up as those
children's own facts:

  * M04 BASEPLATE's own FINISH: SEE ASSEMBLY DRAWING lost to the frame's POWDER COATED - SEMI-GLOSS,
    so it was coated separately from the frame it is welded into (GBP 91.09 at 1 off);
  * M07 CROSS BAR's own MATERIAL: 10mm SQUARE STEEL BAR lost to the framework's STEEL, so it was
    nested as 10 mm plate and lasered as well as sawn;
  * M06 OUTER FRAME's own 1/2" SQUARE STEEL TUBE survived the read and was then folded to a material
    code, its words dropped, so nothing downstream saw a tube.

The arm's sheet is numbered 11934-01-M02, not 12684-02-M02. That stays a separate, unresolved
identity: it is not matched to the arm, and the hook sheet's facts no longer land on the arm.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import drawing_facts as df  # noqa: E402
from source_connectors.llm_full_job import (  # noqa: E402
    apply_full_job_to_pre_estimate, overlay_drawing_facts)


def test_a_five_character_segment_is_a_drawing_number():
    for code in ("12684-02-101SA", "12684-02-102SA", "12693-01-104", "12684-02-M04",
                 "11772-01-09-GA2", "12173-07-2-01M"):
        assert df._RE_DWGNO.fullmatch(code), code


def _page(n, part, material=None, finish=None, pointer=False):
    return {"page": n, "sheet_part": part, "material": material, "finish": finish,
            "finish_pointer": pointer, "weight_g": None, "tube_section": None,
            "cut_length_mm": None, "thickness_mm": None, "colour": None}


# The 12684-02 pack as the fixed reader names its sheets.
PAGES = [
    _page(1, "12684-02-GA", "MILD STEEL [CR4]", "POWDER COATED - SEMI-GLOSS"),
    _page(2, "12684-02-101SA", "MILD STEEL [CR4]", "POWDER COATED - SEMI-GLOSS"),
    _page(4, "11934-01-M02", "MILD STEEL", pointer=True),
    _page(5, "12684-02-102SA", "MILD STEEL [CR4]", "POWDER COATED - SEMI-GLOSS"),
    _page(6, "12684-02-M04", "MILD STEEL", pointer=True),
    _page(7, "12684-02-103SA", "STEEL", pointer=True),
    _page(8, "12684-02-M06", '1/2" SQUARE STEEL TUBE', pointer=True),
    _page(9, "12684-02-M07", "10mm SQUARE STEEL BAR", "RAW"),
]


def test_each_part_keeps_the_facts_its_own_sheet_prints():
    by = df.roll_up_by_part(PAGES)
    assert by["12684-02-M04"].get("finish_pointer") and not by["12684-02-M04"].get("finish")
    assert by["12684-02-M07"]["material"] == "10mm SQUARE STEEL BAR"
    assert by["12684-02-M07"]["finish"] == "RAW"
    assert by["12684-02-M06"]["material"] == '1/2" SQUARE STEEL TUBE'


def test_the_arms_mismatched_sheet_stays_unresolved():
    by = df.roll_up_by_part(PAGES)
    assert "11934-01-M02" in by
    assert "12684-02-M02" not in by, "no other sheet's facts are credited to the arm"


def test_a_pointer_is_not_filled_by_another_page_claiming_the_part():
    by = df.roll_up_by_part([_page(6, "P-M04", "MILD STEEL", pointer=True),
                             _page(5, "P-M04", "MILD STEEL", "POWDER COATED")])
    assert by["P-M04"].get("finish_pointer") and not by["P-M04"].get("finish")


def test_a_section_size_is_not_read_as_a_plate_gauge():
    assert df._names_section_stock("10mm SQUARE STEEL BAR")
    assert not df._names_section_stock("2mm MILD STEEL")


def _job(parts):
    return {"found": True, "source": "llm_full_extract", "parts": parts, "routes": []}


def test_the_own_sheets_see_assembly_beats_a_finish_from_elsewhere():
    job = _job([{"part_number": "12684-02-M04", "finish": "POWDER COATED - SEMI-GLOSS"}])
    overlay_drawing_facts(job, {"by_part": {"12684-02-M04": {"finish_pointer": True,
                                                             "material": "MILD STEEL"}}})
    jp = job["parts"][0]
    assert jp["finish"] == "SEE ASSEMBLY DRAWING"
    assert any("used the printed pointer" in f for f in jp.get("_merge_flags") or [])


def test_the_own_sheets_stock_words_reach_the_part_record():
    job = _job([{"part_number": "12684-02-M06", "material": '1/2" SQUARE STEEL TUBE'},
                {"part_number": "12684-02-M07", "material": "10mm SQUARE STEEL BAR"}])
    overlay_drawing_facts(job, {"by_part": {
        "12684-02-M06": {"material": '1/2" SQUARE STEEL TUBE'},
        "12684-02-M07": {"material": "10mm SQUARE STEEL BAR"}}})
    parts = [{"part_number": "12684-02-M06", "description": "OUTER FRAME",
              "normalized_material": "MILD_STEEL"},
             {"part_number": "12684-02-M07", "description": "CROSS BAR",
              "normalized_material": "MILD_STEEL"}]
    apply_full_job_to_pre_estimate(parts, job)
    assert parts[0]["material_stated"] == '1/2" SQUARE STEEL TUBE'
    assert parts[1]["material_stated"] == "10mm SQUARE STEEL BAR"
    assert parts[0]["material_stated_source"] == "own_sheet_title_block"


def test_and_the_section_reader_sees_them_as_a_tube_and_a_bar():
    from section_profile import stock_in_own_material_words
    tube = stock_in_own_material_words({"material_stated": '1/2" SQUARE STEEL TUBE'})
    bar = stock_in_own_material_words({"material_stated": "10mm SQUARE STEEL BAR"})
    assert tube and abs(float(tube["a"]) - 12.7) < 0.01
    assert bar and float(bar["a"]) == 10.0


def test_words_only_the_model_supplied_are_not_taken_as_the_sheets():
    """Only a material its own sheet's title block printed is kept as stated."""
    job = _job([{"part_number": "X-01M", "material": "10mm SQUARE STEEL BAR"}])
    parts = [{"part_number": "X-01M", "normalized_material": "MILD_STEEL"}]
    apply_full_job_to_pre_estimate(parts, job)
    assert not parts[0].get("material_stated")
