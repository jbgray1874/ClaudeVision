"""Harrods 9439-01-04 Table Standing POS Holder, 5 Oct 18:53 book on 2e63a1d (D-397). The
route was mostly the right shape — £277.90 at one off — and three things were the engine's:

* the weld on the frame assembly 101 was charged TWICE: the extract's route named the three
  leaves it joins and resolved to 101, the engine's inference named 101 itself, and two route
  ids made two events, two Weld (CO2) rows at £29.24 — then the second was asked as
  "inferred, not drawn" beside the first, which quoted the sheet;
* 101's own sheet prints "WELD & DRESS" and "TAC WELD UNDERSIDE" and draws no symbol, and
  nothing read the words as the drawing's statement;
* the two A4 GRAPHIC LENSES, each with a detail sheet (PETG, 297 x 212, 2 mm, 151 g), kept
  a bought-in page role for want of a material suffix and were priced from the parts table at
  £1.68 instead of cut on the acrylic laser;
* and the pack-completeness check called 101, the lens and the graphic "drawings this pack
  does not contain" on a seven-sheet PDF whose sheets 2, 6 and 7 are theirs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bought_in_policy as bip                                        # noqa: E402
import invariants                                                     # noqa: E402
import route_compiler as rc                                           # noqa: E402
import weld_symbols as ws                                             # noqa: E402


# ── one joint, one event ─────────────────────────────────────────────────────────────────

def _pack():
    parts = [{"part_number": "H-101", "description": "FRAME ASSEMBLY", "quantity": 1,
              "is_assembly_parent": True, "page_roles": ["assembly"],
              "inferred_operations": ["welding"],
              "operation_sources": {"welding": "inference"}}]
    parts += [{"part_number": p, "description": p, "quantity": 1, "page_roles": ["detail"],
               "normalized_material": "MILD_STEEL", "textual_operations": ["laser_cutting"]}
              for p in ("H-001", "H-002", "H-003")]
    extract = {"assemblies": [{"part_number": "H-101", "children": [
        {"part_number": "H-001", "qty": 1}, {"part_number": "H-002", "qty": 1},
        {"part_number": "H-003", "qty": 2}]}],
        # The extract's two readings of one joint, as the 18:53 run had them: the route that
        # quotes the sheet and names the leaves, and the inferred route that names 101.
        "routes": [{"operation": "welding", "part_numbers": ["H-001", "H-002", "H-003"],
                    "scope": "assembly", "evidence": "TAC WELD", "sequence": 10},
                   {"operation": "welding", "part_numbers": ["H-101"], "scope": "assembly",
                    "inferred": True, "sequence": 10,
                    "notes": "views show TAC WELD and WELD & DRESS callouts"}]}
    return parts, extract


def test_two_readings_of_the_assemblys_weld_are_one_event():
    parts, extract = _pack()
    out = rc.compile_job_route(parts, extract, declared_product="H-101")
    _d = lambda d: d if isinstance(d, dict) else d.__dict__
    welds = [_d(d) for d in out["decisions"]
             if _d(d)["operation"] == "welding" and _d(d)["status"] == rc.REQUIRED]
    assert len(welds) == 1, [(w["target_id"], w["source"], w["participants"]) for w in welds]
    assert welds[0]["target_id"] == "H-101"
    assert set(welds[0]["participants"]) >= {"H-001", "H-002", "H-003"}
    assert welds[0]["source"] != "inference"          # the quoted reading won
    assert any(i.get("code") == "joining_events_merged_on_assembly" for i in out["issues"])


# ── a note on the sheet states the weld ──────────────────────────────────────────────────

def test_the_sheets_own_weld_note_is_the_drawings_statement():
    assert ws.sheet_weld_note("WELD & DRESS SCALE 1 : 1 TAC WELD UNDERSIDE") == \
        {"note": "WELD & DRESS", "dress": True}
    assert ws.sheet_weld_note("TAC WELD UNDERSIDE")["dress"] is False
    assert ws.sheet_weld_note("BAG PRICING HOOK WELDMENT") == {}          # a title
    assert ws.sheet_weld_note("FRAME WELD ASSEMBLY") == {}
    assert ws.sheet_weld_note("") == {}


def test_a_part_whose_sheet_carries_the_note_is_welded_by_the_drawing():
    frame = {"part_number": "H-101", "inferred_operations": ["welding"],
             "operation_sources": {"welding": "inference"}}
    leaf = {"part_number": "H-001"}
    by_part = {"H-101": {"notes": "WELD & DRESS TAC WELD UNDERSIDE", "text": ""},
               "H-001": {"notes": "MILD STEEL RAW 105G", "text": ""}}
    assert ws.apply_sheet_weld_notes([frame, leaf], by_part) == ["H-101"]
    assert "welding" in frame["textual_operations"] and "dress_welds" in frame["textual_operations"]
    assert frame["operation_sources"]["welding"] == "drawing_deterministic"
    assert frame["weld_stated_by_note"] == "WELD & DRESS"
    assert "textual_operations" not in leaf
    ruled = {"part_number": "H-101", "operations_ruled_out": {"welding": "bolted"}}
    assert ws.apply_sheet_weld_notes([ruled], by_part) == []


def test_the_legend_default_is_never_a_note():
    """sheet_weld_facts strips the legend before the note reader sees the lines."""
    from extractor_patterns import strip_specification_legend
    lines = "WELD SPECIFICATION: ALL WELDS TO BE TIG UNLESS STATED MATERIAL: MILD STEEL RAW"
    assert ws.sheet_weld_note(strip_specification_legend(lines)) == {}


# ── a detail sheet of a cut material is a part we make ───────────────────────────────────

def test_a_lens_with_its_own_detail_sheet_is_made_not_bought():
    lens = {"part_number": "H-004", "description": "A4 GRAPHIC LENS",
            "page_roles": ["detail", "bought_in"], "normalized_material": "PETG",
            "normalized_thickness_mm": 2.0, "overall_sizes_mm": ["297", "212"],
            "materials": ["PETG"]}
    assert bip.own_sheet_details_a_cut_part(lens)
    assert bip.bought_in_reason(lens) == ""
    # the same page role on an article with no sheet material of its own stays bought
    article = {"part_number": "H-ACC", "description": "THUMBSCREW", "page_roles": ["bought_in"],
               "normalized_material": "BOUGHT_IN"}
    assert bip.bought_in_reason(article)
    inherited = {"part_number": "H-005", "page_roles": ["detail", "bought_in"],
                 "normalized_material": "MILD_STEEL", "material_inherited_from": "H-GA",
                 "normalized_thickness_mm": 2.0}
    assert not bip.own_sheet_details_a_cut_part(inherited)


# ── a part traced to a sheet of the pack is not a missing drawing ────────────────────────

def test_a_bom_line_traced_to_a_detail_sheet_is_in_the_pack():
    summary = {
        "pages": [{"page_number": 1}, {"page_number": 2}],
        "document_analysis": {"bom_rows": [
            {"part_number": "9439-01-04-101", "description": "A4 FRAME ASSEMBLY", "quantity": 1},
            {"part_number": "9439-01-04-004", "description": "A4 GRAPHIC LENS", "quantity": 2},
            {"part_number": "9439-01-04-009", "description": "A MISSING BRACKET", "quantity": 1},
        ]},
        "parts": [
            {"part_number": "9439-01-04-101", "pages": [2], "page_roles": ["detail"]},
            {"part_number": "9439-01-04-004", "pages": [6], "page_roles": ["detail", "bought_in"]},
            {"part_number": "9439-01-04-009", "pages": [1], "page_roles": ["assembly_bom"]},
        ],
    }
    out = invariants.check_the_pack_contains_the_drawings_its_bom_names(summary)
    missing = {m["part_number"] for v in out for m in ((v.get("detail") or {}).get("missing") or [])}
    assert "9439-01-04-009" in missing
    assert "9439-01-04-101" not in missing and "9439-01-04-004" not in missing
