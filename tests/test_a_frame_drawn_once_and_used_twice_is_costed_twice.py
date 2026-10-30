"""A frame drawn once and used twice is costed twice, a weldment with no members is a part,
and a member finished another way is not in the case's booth (D-556, D-557, D-558).

401918-01-GA, 21 Oct 2026 11:14 book — the first book after the seven fixes of 20 Oct landed:
the GA's powder was charged over the brushed stainless rub strip; 401918-01-07M, the base
frame weldment the model lists as an assembly, went on the bill with no material and no saw;
and Weld (CO2) on the ×2 base frame assembly was charged once beside a dressing charged twice.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bom_pipeline as bp  # noqa: E402
import estimator as e  # noqa: E402
import route_compiler as rc  # noqa: E402
from part_identity import mint_uncoded_row_identities  # noqa: E402


# ── D-556: a member finished another way is not in the case's booth ────────────────────

def _case():
    return [
        {"part_number": "401918-01-GA", "description": "1200 RAIL", "is_assembly_parent": True,
         "assembly_children": ["401918-01-01M", "401918-01-05M", "401918-01-02M"],
         "quantity": 1, "textual_operations": ["powder_coating"],
         "normalized_finish": "POWDER COATED", "normalized_material": "MILD STEEL"},
        {"part_number": "401918-01-01M", "description": "RUB STRIP", "quantity": 1,
         "normalized_material": "STAINLESS STEEL", "normalized_finish": "BRUSHED",
         "surface_finishes": ["BRUSHED"], "blank_length_mm": 1293.0, "blank_width_mm": 13.0},
        {"part_number": "401918-01-05M", "description": "BASE PANEL", "quantity": 1,
         "normalized_material": "MILD STEEL", "blank_length_mm": 1154.0, "blank_width_mm": 497.21},
        {"part_number": "401918-01-02M", "description": "END CAP", "quantity": 2,
         "normalized_material": "MILD STEEL", "normalized_finish": "RAW",
         "blank_length_mm": 60.0, "blank_width_mm": 15.0},
    ]


def test_a_brushed_member_is_left_out_of_the_cases_powder_area():
    parts = _case()
    assert e.stamp_members_coated_area(parts) == 1
    ga = parts[0]
    expected = (1154.0 * 497.21 * 2 + 60.0 * 15.0 * 2 * 2) / 1e6      # the panel and two RAW caps
    assert abs(ga["_powder_members_coated_m2"] - expected) < 1e-6
    assert "401918-01-01M" not in " ".join(ga["_powder_members"])
    assert any(s.startswith("401918-01-01M (its own sheet states Brushed") for s in ga["_powder_members_left_out"])
    assert "brushed finish, not the case's coat" in " ".join(ga["_powder_members_left_out"])


def test_a_silent_a_raw_and_a_pointing_member_are_still_coated_as_the_case():
    parts = _case()
    parts[1]["normalized_finish"] = "SEE ASSEMBLY DRAWING"           # a pointer states nothing
    parts[1]["surface_finishes"] = ["SEE ASSEMBLY DRAWING"]
    e.stamp_members_coated_area(parts)
    assert "401918-01-01M x1" in parts[0]["_powder_members"]
    assert not parts[0].get("_powder_members_left_out")


def test_a_finish_the_document_filled_in_is_not_the_members_own():
    parts = _case()
    parts[1]["finish_inherited_from"] = "document"                    # the GA's words, not page 5's
    e.stamp_members_coated_area(parts)
    assert "401918-01-01M x1" in parts[0]["_powder_members"]


# ── D-557: a weldment with no members but its own pieces is a part ─────────────────────

def _row(desc, qty=1, parent="401918-01-07M"):
    return {"part_number": "", "description": desc, "quantity": qty, "bom_parent": parent,
            "bom_parent_known": True}


def _page_11_rows():
    rows = [_row("50.00 x 20.00 x 2.00mm TUBE 703", 1), _row("50.00 x 20.00 x 2.00mm TUBE 451", 2)]
    mint_uncoded_row_identities(rows)
    return rows


def test_a_weldment_the_model_calls_an_assembly_takes_its_own_cut_list():
    frame = {"part_number": "401918-01-07M", "description": "BASE FRAME - WELDMENT",
             "is_assembly_parent": True, "is_sub_assembly": True, "page_roles": ["detail"],
             "normalized_material": "MILD STEEL", "quantity": 2}
    rows = _page_11_rows()
    assert bp.apply_stated_cut_list_to_parts([frame], rows) == 1
    ss = frame["section_stock"]
    assert (ss["a"], ss["b"], ss["t"]) == (20.0, 50.0, 2.0)
    assert sorted(ss["cut_lengths_mm"]) == [451.0, 451.0, 703.0]
    assert all(r["consumed"] for r in rows)
    assert any("costed as a weldment cut from those pieces (D-557)" in f for f in frame["review_flags"])


def test_an_assembly_with_coded_members_still_has_its_pieces_asked_not_costed():
    asm = {"part_number": "401918-01-07M", "description": "BASE FRAME - WELDMENT",
           "is_assembly_parent": True, "page_roles": ["detail"],
           "assembly_children": ["401918-01-08M"]}
    bracket = {"part_number": "401918-01-08M", "description": "BRACKET"}
    assert bp.apply_stated_cut_list_to_parts([asm, bracket], _page_11_rows()) == 0
    assert "section_stock" not in asm
    assert "is an assembly" in asm["manufacturing_questions"][0]["issue"]


def test_a_child_the_model_names_but_the_bill_does_not_hold_is_not_a_member():
    """The model's tree can name a weldment's cut-list bodies as children; nothing on the bill
    answers to them, so nothing carries the tube — the 13:10 book, after D-557's first cut."""
    frame = {"part_number": "401918-01-07M", "description": "BASE FRAME - WELDMENT",
             "is_assembly_parent": True, "is_sub_assembly": True, "page_roles": ["detail"],
             "assembly_children": ["TUBE 50x20x2 - 703", "TUBE 50x20x2 - 451"],
             "normalized_material": "MILD STEEL", "quantity": 2}
    assert bp.apply_stated_cut_list_to_parts([frame], _page_11_rows()) == 1
    assert sorted(frame["section_stock"]["cut_lengths_mm"]) == [451.0, 451.0, 703.0]


def test_a_bare_assembly_record_with_uncoded_pieces_is_still_asked():
    """The D-383 fixture: nothing says this assembly is a weldment drawn on its own sheet."""
    w = {"part_number": "W-101", "is_assembly_parent": True}
    rows = [_row("30.00 x 30.00 x 2.00mm TUBE 1532", 2, "W-101"), _row("30.00 x 30.00 x 2.00mm TUBE 290", 1, "W-101")]
    mint_uncoded_row_identities(rows)
    assert bp.apply_stated_cut_list_to_parts([w], rows) == 0
    assert "section_stock" not in w


# ── D-558: an assembly-level operation happens at least once per instance of its target ──

def test_the_floor_is_the_targets_multiplicity_and_a_stated_count_above_it_stands():
    q = {"401918-01-401": 2.0, "401918-01-GA": 1.0}
    assert rc.at_least_once_per_instance(1, "401918-01-401", q, "assembly") == (2.0, True)
    assert rc.at_least_once_per_instance(3, "401918-01-401", q, "assembly") == (3, False)
    assert rc.at_least_once_per_instance(1, "401918-01-GA", q, "assembly") == (1, False)
    assert rc.at_least_once_per_instance(1, "401918-01-401", q, "part") == (1, False)
    assert rc.at_least_once_per_instance(None, "401918-01-401", q, "assembly") == (None, False)


def _rail(route_qty=1):
    parts = [
        {"part_number": "401918-01-GA", "description": "1200 RAIL", "is_assembly_parent": True,
         "assembly_children": ["401918-01-401", "401918-01-01M"], "quantity": 1},
        {"part_number": "401918-01-401", "description": "BASE FRAME - WELDED ASSEMBLY",
         "is_assembly_parent": True, "is_sub_assembly": True,
         "assembly_children": ["401918-01-07M", "401918-01-08M"], "quantity": 2,
         "textual_operations": ["welding"], "operation_scope": {"welding": "assembly"},
         "operation_qty_per_unit": {"welding": route_qty},
         "operation_sources": {"welding": "llm_full_extract"}},
        {"part_number": "401918-01-07M", "description": "BASE FRAME - WELDMENT",
         "normalized_material": "MILD STEEL", "quantity": 2},
        {"part_number": "401918-01-08M", "description": "BASE FRAME - BRACKET",
         "normalized_material": "MILD STEEL", "quantity": 4, "normalized_thickness_mm": 3.0},
        {"part_number": "401918-01-01M", "description": "RUB STRIP",
         "normalized_material": "STAINLESS STEEL", "quantity": 1},
    ]
    job = {"assemblies": [
        {"part_number": "401918-01-GA", "children": [{"part_number": "401918-01-401", "qty": 2},
                                                     {"part_number": "401918-01-01M", "qty": 1}]},
        {"part_number": "401918-01-401", "children": [{"part_number": "401918-01-07M", "qty": 1},
                                                      {"part_number": "401918-01-08M", "qty": 2}]}],
        "routes": [{"operation": "welding", "part_numbers": ["401918-01-401"], "scope": "assembly",
                    "qty_per_unit": route_qty, "sequence": 20}]}
    return parts, job


def _weld(out):
    return [d for d in out["decisions"]
            if d["operation"] == "welding" and d["status"] == "required"
            and d["target_id"] == "401918-01-401"]


def test_the_weld_on_a_frame_used_twice_is_charged_twice():
    parts, job = _rail(route_qty=1)
    out = rc.compile_job_route(parts, job, known_assemblies=["401918-01-GA", "401918-01-401"])
    welds = _weld(out)
    assert welds and all(d["qty_per_unit"] == 2.0 for d in welds), welds


def test_a_model_that_already_counted_both_frames_is_not_doubled():
    parts, job = _rail(route_qty=2)
    out = rc.compile_job_route(parts, job, known_assemblies=["401918-01-GA", "401918-01-401"])
    welds = _weld(out)
    assert welds and all(float(d["qty_per_unit"]) == 2.0 for d in welds), welds
