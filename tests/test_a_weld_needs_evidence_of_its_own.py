"""12173-02 Card Spinner, 2 Oct 03:17 book on 0906f30 (D-385): three faults left.

1. Weld (CO2) £246.74 + Dress Welds £140.06 at 1 off, almost all on sheet LEAVES whose only
   weld evidence was an inference — the pack's weld specification read for what it is, then
   charged anyway and asked. A leaf under an assembly with no weld evidence of its own is not
   charged; the question stays on the record with nothing charged.
2. The rack and trough GAs (own sheets FINISH: POWDER COATED over RAW members) carried no coat.
3. Robomac on two mirrored sheet hands (04-02M-H, 07-1-02M-H).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf                                             # noqa: E402
import drawing_job_merge as djm                                       # noqa: E402
import route_compiler as rc                                           # noqa: E402
import weld_symbols as ws                                             # noqa: E402


# ── 1. a leaf weld with no evidence of its own ───────────────────────────────────────────

def _d(target, op, source="inference", status=None, scope="part"):
    return NS(target_id=target, operation=op, scope=scope, status=status or rc.REQUIRED,
              source=source, reason="", field_provenance={})


def _graph():
    return {"nodes": [NS(part_number="A-201", kind="assembly"), NS(part_number="A-01M", kind="leaf"),
                      NS(part_number="A-09M", kind="leaf")],
            "parents": {"A-01M": {"A-201"}}}


def test_an_inferred_weld_on_a_leaf_under_an_assembly_is_not_charged():
    ds = [_d("A-01M", "welding"), _d("A-01M", "dress_welds")]
    issues = []
    got = rc._withhold_evidenceless_leaf_welds(ds, _graph(), issues)
    assert got == ["A-01M", "A-01M"]
    assert all(x.status == rc.NOT_APPLICABLE for x in ds)
    assert "the joint is A-201's" in ds[0].reason
    assert ds[0].field_provenance["status"] == "evidenceless_leaf_weld_withheld"
    assert issues and issues[0]["code"] == "evidenceless_leaf_weld_withheld"


def test_a_stated_weld_an_assembly_weld_and_a_parentless_leaf_are_untouched():
    ds = [_d("A-01M", "welding", source="drawing_deterministic"),
          _d("A-201", "welding", scope="assembly"),
          _d("A-201", "welding"),                      # part-scope weld on the assembly itself
          _d("A-09M", "welding")]                      # a leaf nothing holds: D-258 stands
    assert rc._withhold_evidenceless_leaf_welds(ds, _graph(), []) == []
    assert all(x.status == rc.REQUIRED for x in ds)


def test_the_withheld_weld_is_a_question_on_the_record():
    shadow = {"product_root": "A-GA", "decisions": [
        {"target_id": "A-01M", "operation": "welding", "status": "not_applicable",
         "field_provenance": {"status": "evidenceless_leaf_weld_withheld"}},
        {"target_id": "A-01M", "operation": "dress_welds", "status": "not_applicable",
         "field_provenance": {"status": "evidenceless_leaf_weld_withheld"}}]}
    src = {"estimate_summary": {"canonical_route_shadow": shadow,
                                "part_estimates": [{"part_number": "A-01M", "quantity": 1}]}}
    ds = [d for d in cf.costed_job(src).get("decisions_required") or []
          if str(d.get("issue") or "").startswith("Is A-01M welded itself")]
    assert len(ds) == 1
    assert ds[0]["kind"] == "manufacturing_decision"
    assert ds[0]["gbp_at_stake"] is None and "NOT charged" in ds[0]["assumption"]
    assert ds[0]["operations"] == ["dress_welds", "welding"]


# ── 2. an assembly's own FINISH is its coat ──────────────────────────────────────────────

def test_an_assembly_whose_own_sheet_states_powder_is_powder_coated():
    ga = {"part_number": "A-GA", "is_assembly_parent": True, "assembly_children": ["A-01M"]}
    leaf = {"part_number": "A-01M"}
    by = {"A-GA": {"finish": "POWDER COATED - MATT", "text": "A-01M", "counts": {}},
          "A-01M": {"finish": "RAW", "text": "", "counts": {}}}
    assert ws.apply_finish_coats([ga, leaf], by) == ["A-GA"]
    assert "powder_coating" in ga["textual_operations"]
    assert ga["operation_sources"]["powder_coating"] == "drawing_deterministic"
    assert ga["normalized_finish"] == "POWDER COATED - MATT"
    assert "textual_operations" not in leaf                 # a leaf is the readers' business


def test_a_ruled_out_coat_and_a_wet_sprayed_board_assembly():
    ga = {"part_number": "B-GA", "is_sub_assembly": True,
          "operations_ruled_out": {"powder_coating": "plated"}}
    assert ws.apply_finish_coats([ga], {"B-GA": {"finish": "POWDER COATED"}}) == []
    base = {"part_number": "C-01J", "assembly_children": ["C-01J-01"]}
    assert ws.apply_finish_coats([base], {"C-01J": {"finish": "WET SPRAYED - MATT"}}) == ["C-01J"]
    assert base["textual_operations"] == ["wet_spray"]


def test_the_hook_reads_the_coats_after_the_welds():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert src.index("_ws_fin = _ws_finish(") < src.index("apply_finish_coats as _ws_coats")


# ── 3. the opposite hand of a sheet part is not wire-formed ──────────────────────────────

def _pair():
    base = {"part_number": "9999-01-02M", "description": "SIDE PANEL", "quantity": 8,
            "normalized_thickness_mm": 1.5, "normalized_material": "MILD STEEL",
            "textual_operations": ["laser_cutting", "folding"], "dxf_augmented": True,
            "normalized_geometry": {"blank_length_mm": 280.97, "blank_width_mm": 159.24,
                                    "geometry_source": "dxf_flat_pattern"}}
    hand = {"part_number": "9999-01-02M-H", "description": "SIDE PANEL", "quantity": 8,
            "textual_operations": ["wire_forming", "welding"],
            "normalized_geometry": {}}
    return base, hand


def test_a_mirrored_sheet_hand_loses_the_wire_note():
    base, hand = _pair()
    djm.apply_mirror_geometry([base, hand])
    assert "wire_forming" not in hand["textual_operations"]
    assert "wire_forming" in hand["operations_ruled_out"]
    assert "not wire-formed" in hand["operations_ruled_out"]["wire_forming"]


def test_a_hand_of_a_wire_base_keeps_wire_forming():
    # THE BASE'S OWN OP LIST IS NOT THE TEST (D-387): on 12173 every base carried the pack's
    # WIRE TO WIRE note, so a rule reading it never fired. What makes a base wire is its bar
    # schedule, its recognised bar, or its stock form — a sheet base with the note is sheet.
    base, hand = _pair()
    base["textual_operations"] = ["wire_forming"]
    djm.apply_mirror_geometry([base, hand])
    assert "wire_forming" not in hand["textual_operations"]
    base, hand = _pair()
    base["_bar_recognised"] = True
    base["textual_operations"] = ["wire_forming"]
    djm.apply_mirror_geometry([base, hand])
    assert "wire_forming" in hand["textual_operations"]
    assert "operations_ruled_out" not in hand
