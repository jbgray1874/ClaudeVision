"""12173-02 Card Spinner, 17:34 book (D-379): one screw on twice, one trough side, and a
stated row read as not carried.

1. "FIXING-3.5-X12MM-PAN-HEAD" is the code 12173-03-GA prints. "FIXING-" was read as a label
   and stripped, the parts-list edge kept the printed code, and the extract's codeless read
   of the same row was given the stand-in BI-SCREW — so the ×16 screw was on the sheet as
   BI-SCREW and as FIXING-3.5-X12MM-PAN-HEAD. Its ×16 brother, stripped to
   "3.5-X16MM-PAN-HEAD", was charged and then counted "stated and not carried".
2. 12173-07-2-GA prints 12173-07-2-02M on two item rows, one per hand; the model files the
   other hand as 02M-H. The model's 1 by file name, and the reader's own one-row reading,
   were counted as two voices against the table's 2.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                           # noqa: E402
import source_precedence as sp                                        # noqa: E402
from part_identity import strip_code_label                            # noqa: E402
from source_connectors.solidworks import (                            # noqa: E402
    NativeBomRow, NativeJob, apply_native_to_pre_estimate)

SCREW = "Ø3.5x12mm PAN HEAD MULTI-PURPOSE SCREW"


# ── the code is the code ─────────────────────────────────────────────────────────────────

def test_a_hyphen_inside_a_code_is_not_a_label():
    assert strip_code_label("FIXING-3.5-X12MM-PAN-HEAD") == "FIXING-3.5-X12MM-PAN-HEAD"
    assert strip_code_label("FIXING-3.5-X16MM-PAN-HEAD") == "FIXING-3.5-X16MM-PAN-HEAD"


def test_a_label_is_still_a_label():
    assert strip_code_label("VITAL PARTS: LOW068") == "LOW068"
    assert strip_code_label("FIXINGS: FIXING0127") == "FIXING0127"
    assert strip_code_label("BOUGHT IN - LOW068") == "LOW068"
    assert strip_code_label("VITAL PARTS:") == "VITAL PARTS:"


def _screw_graph(record_code):
    parts = [{"part_number": "12173-03-GA", "description": "SPINNER",
              "is_assembly_parent": True,
              "assembly_children": ["FIXING-3.5-X12MM-PAN-HEAD"]},
             {"part_number": record_code, "description": SCREW, "quantity": 16,
              "is_bought_in": True, "page_roles": ["bought_in"]}]
    llm = {"parts": [{"part_number": "BI-SCREW", "description": SCREW, "quantity": 16,
                      "is_bought_in": True}],
           "assemblies": [{"part_number": "12173-03-GA",
                           "children": [{"part_number": "FIXING-3.5-X12MM-PAN-HEAD",
                                         "qty": 16}]}]}
    bom = [{"part_number": "FIXING-3.5-X12MM-PAN-HEAD", "description": SCREW,
            "quantity": 16, "bom_parent": "12173-03-GA"}]
    g = rc.build_part_graph(parts, llm, bom, known_assemblies=["12173-03-GA"])
    return {n.part_number: n for n in g["nodes"]}


def test_one_screw_is_one_line_under_the_code_the_drawing_printed():
    nodes = _screw_graph(strip_code_label("FIXING-3.5-X12MM-PAN-HEAD"))
    screws = [k for k in nodes if k != "12173-03-GA"]
    assert screws == ["FIXING-3.5-X12MM-PAN-HEAD"], screws
    assert "BI-SCREW" in nodes["FIXING-3.5-X12MM-PAN-HEAD"].evidence["raw_aliases"]
    assert [c.part_number for c in nodes["12173-03-GA"].children] == \
        ["FIXING-3.5-X12MM-PAN-HEAD"]


def test_a_stand_in_matched_by_two_printed_codes_is_left_alone():
    aliases = rc._raw_identity_aliases(
        {"FIXING-A": {"description": SCREW, "is_bought_in": True},
         "FIXING-B": {"description": SCREW, "is_bought_in": True}},
        {"BI-SCREW": {"description": SCREW, "is_bought_in": True}})
    assert "BI-SCREW" not in aliases


# ── a reader is not outvoted by itself ───────────────────────────────────────────────────

def test_the_tables_own_revision_is_not_set_aside_by_its_first_reading():
    p = {"part_number": "12173-07-2-02M"}
    sp.apply_field(p, "quantity", 1, "llm_full_extract")
    sp.apply_field(p, "quantity", 1, "bom_tree")
    sp.apply_field(p, "quantity", 1, "dxf")
    sp.apply_field(p, "quantity", 2, "bom_tree")
    assert not any("independent sources say" in f for f in p.get("review_flags") or [])
    assert "bom_tree" not in (p.get("_corroboration") or {}).get("quantity", {}).get(
        "sources", [])


def test_two_other_readers_still_defend_against_one():
    p = {"part_number": "X"}
    sp.apply_field(p, "normalized_material", "PETG", "title_block")
    sp.apply_field(p, "normalized_material", "PETG", "dxf_filename")
    sp.apply_field(p, "normalized_material", "ABS", "solidworks_api")
    assert p["normalized_material"] == "PETG"


# ── the model's other hand ───────────────────────────────────────────────────────────────

def _trough():
    return [
        {"part_number": "12173-07-2-GA", "description": "WRAPPING PAPER TROUGH",
         "quantity": 1, "is_assembly_parent": True, "page_roles": ["assembly"],
         "assembly_children": ["12173-07-2-01M", "12173-07-2-02M"]},
        {"part_number": "12173-07-2-01M", "description": "TROUGH", "quantity": 1,
         "page_roles": ["detail"], "review_flags": []},
        {"part_number": "12173-07-2-02M", "description": "SIDE PANEL", "quantity": 1,
         "page_roles": ["detail"], "review_flags": []},
    ]


def _model(**extra_rows):
    rows = [NativeBomRow(part_number="12173-07-2-01M", quantity=1),
            NativeBomRow(part_number="12173-07-2-02M", quantity=1),
            NativeBomRow(part_number="12173-07-2-02M-H", quantity=1)]
    return NativeJob(found=True, bom=rows, assembly_pns=["12173-07-2-GA"],
                     hierarchy={"12173-07-2-GA": [("12173-07-2-01M", 1.0),
                                                  ("12173-07-2-02M", 1.0),
                                                  ("12173-07-2-02M-H", 1.0)]})


def test_an_unlisted_handed_twin_is_counted_with_its_code():
    parts = _trough()
    apply_native_to_pre_estimate(parts, _model())
    side = parts[2]
    assert side["quantity"] == 2, side.get("review_flags")
    assert side["quantity_total_per_unit"] == 2
    assert any("files the other hand as 12173-07-2-02M-H" in f for f in side["review_flags"])
    assert parts[1]["quantity"] == 1


def test_a_twin_the_drawing_lists_keeps_its_own_line():
    parts = _trough() + [{"part_number": "12173-07-2-02M-H", "description": "SIDE PANEL",
                          "quantity": 1, "page_roles": ["detail"], "review_flags": []}]
    apply_native_to_pre_estimate(parts, _model())
    assert parts[2]["quantity"] == 1
    assert parts[3]["quantity"] == 1
