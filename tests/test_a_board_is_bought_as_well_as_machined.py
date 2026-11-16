"""12343-01J was machined and edged and nobody bought the board (D-512).

An 18 mm MFC shelf, 1198 × 398: the model carried the box 1198 × 18 × 398, but a board has
no sheet-metal cut list and the analyser's gauge window is a sheet-METAL window (0.4–12 mm),
so the record reached costing with no thickness — and with no gauge there was no kg, no
sheet price, no weight check, and £71.04 of labour and carriage on a board charged £0. The
drawing's "EDGED ALL AROUND" was read as extent-unknown because the vocabulary knew only
"ALL ROUND"; the edging-order code "2S/SL" registered as nothing; the £4.25 provisional
material allowance was computed and then shown "not charged"; and the decor text minted
phantom part codes ("ST7-PLATINUM", "600-CENTRES") whose missing-drawing questions nobody
could answer.

Every fix is generic and narrow, per the review that demanded safeguards: the bounding-box
minimum is a LABELLED FALLBACK for a verified flat board, never a universal rule.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _native_job(**part_kw):
    from source_connectors import solidworks as sw
    nat = sw.NativePart(part_number="12343-01J", **part_kw)
    return sw.NativeJob(part_signals={"12343-01J": nat}, found=True,
                        meta={"extract_path": "test"})


def _board_part(**over):
    part = {"part_number": "12343-01J", "description": "KD V2 SHELF",
            "normalized_material": "MFC", "quantity": 1}
    part.update(over)
    return part


# ── the board's gauge from the model's smallest extent, as a labelled fallback ──

def test_a_flat_boards_gauge_comes_from_the_models_smallest_extent():
    from source_connectors import solidworks as sw
    from source_precedence import source_of
    part = _board_part()
    sw.apply_native_to_pre_estimate([part], _native_job(bbox_mm=[1198.0, 18.0, 398.0]))
    assert part["normalized_thickness_mm"] == 18.0
    assert source_of(part, "normalized_thickness_mm") == "model_extents_board_gauge"
    assert any("SMALLEST EXTENT" in str(f) for f in part.get("review_flags") or [])
    assert any("smallest extent" in str(q.get("issue", ""))
               for q in part.get("manufacturing_questions") or [])


def test_a_steel_part_is_never_given_a_bbox_gauge():
    """The smallest side of a machined steel block is not a gauge — the board rule must not
    leak into metal, where the sheet-metal window already rules."""
    from source_connectors import solidworks as sw
    part = _board_part(normalized_material="MILD STEEL")
    sw.apply_native_to_pre_estimate([part], _native_job(bbox_mm=[1198.0, 18.0, 398.0]))
    assert not part.get("normalized_thickness_mm")


def test_a_shaped_board_is_not_a_plate():
    """A block whose smallest side is not clearly its gauge (80 against 200) is a shaped
    component — the fallback refuses it."""
    from source_connectors import solidworks as sw
    part = _board_part()
    sw.apply_native_to_pre_estimate([part], _native_job(bbox_mm=[300.0, 80.0, 200.0]))
    assert not part.get("normalized_thickness_mm")


def test_an_assembly_is_not_given_a_gauge():
    from source_connectors import solidworks as sw
    part = _board_part(is_assembly_parent=True)
    sw.apply_native_to_pre_estimate([part], _native_job(bbox_mm=[1198.0, 18.0, 398.0]))
    assert not part.get("normalized_thickness_mm")


def test_a_stated_gauge_outranks_the_fallback():
    """The fallback enters at provisional rank: a drawing callout submitted afterwards
    displaces it, so a stated gauge always wins however the readers are ordered."""
    from source_connectors import solidworks as sw
    from source_precedence import apply_field, source_of
    part = _board_part()
    sw.apply_native_to_pre_estimate([part], _native_job(bbox_mm=[1198.0, 18.0, 398.0]))
    assert part["normalized_thickness_mm"] == 18.0
    apply_field(part, "normalized_thickness_mm", 15.0, "pdf_title_block")
    assert part["normalized_thickness_mm"] == 15.0
    assert source_of(part, "normalized_thickness_mm") == "pdf_title_block"


# ── the drawing's own words about the edges ──────────────────────────────────

def test_edged_all_around_is_a_statement_of_the_whole_perimeter():
    from edge_banding import banded_length_mm
    part = _board_part(blank_length_mm=1198.0, blank_width_mm=398.0,
                       notes=["EDGED ALL AROUND"])
    out = banded_length_mm(part)
    assert out["basis"] == "note_all_round"
    assert abs(out["mm"] - 3192.0) < 0.5


def test_an_edging_order_code_says_the_part_is_banded():
    """"2S/SL" is the bander's run order — a drawing that writes one has decided the part
    is banded, even with no other banding word."""
    from edge_banding import banded_length_mm
    part = _board_part(blank_length_mm=1198.0, blank_width_mm=398.0,
                       notes=["EDGING ORDER 2S/SL"])
    out = banded_length_mm(part)
    assert out["basis"] != "no_evidence"


# ── the allowance reaches the charged row ────────────────────────────────────

def test_a_board_allowance_lands_in_the_sheet_row_fields():
    """£4.25 computed and shown 'not charged' is worse than either charging or refusing:
    on a board part the allowance writes the row's own fields (one part, one-part sheet)
    so the workbook charges what the engine says, still flagged NON-FIRM."""
    import estimator as E
    pe = {"part_number": "12343-01J", "description": "KD V2 SHELF",
          "normalized_material": "MFC", "quantity": 1,
          "operations": ["cnc_joinery", "edge_banding"],
          "material_estimate": {}, "extended_total_cost_gbp": 0,
          "_made_part_material_allowance": True}
    n = E.apply_last_resort_prices([pe], lambda _pe: 4.25)
    assert n == 1
    me = pe["material_estimate"]
    assert me["material_allowance_only"] is True
    assert abs(float(me["sheet_price_gbp"]) - 4.25) < 0.01
    assert me["parts_per_sheet"] == 1


def test_a_steel_allowance_does_not_write_sheet_row_fields():
    import estimator as E
    pe = {"part_number": "12399-01M", "description": "BRACKET",
          "normalized_material": "MILD STEEL", "quantity": 1,
          "operations": ["laser_cutting"],
          "material_estimate": {}, "extended_total_cost_gbp": 0,
          "_made_part_material_allowance": True}
    E.apply_last_resort_prices([pe], lambda _pe: 4.25)
    assert "sheet_price_gbp" not in pe["material_estimate"]


# ── prose that happens to carry a hyphen is not a part ───────────────────────

def test_a_decor_or_spacing_tail_is_not_a_code():
    from extractor_patterns import _looks_like_part_number
    from part_code_conventions import looks_like_a_drawing_number
    assert not _looks_like_part_number("ST7-PLATINUM")
    assert not looks_like_a_drawing_number("600-CENTRES")
    # real codes keep passing — the rule reads the TAIL, not the shape
    assert _looks_like_part_number("12343-01J")
    assert looks_like_a_drawing_number("12173-02-GA")
    assert looks_like_a_drawing_number("12340-01M")


# ── the routing's claim about the holes carries its inventory ────────────────

def test_cnc_routing_names_the_holes_it_covers():
    import estimator as E
    part = _board_part(normalized_thickness_mm=18.0,
                       blank_length_mm=1198.0, blank_width_mm=398.0,
                       hole_sizes_mm=[8.5, 6.5],
                       textual_operations=["cnc_routing"],
                       normalized_geometry={"estimated_hole_count": 4,
                                            "estimated_cut_length_mm": 3192.0})
    E.estimate_process_times(part, quantity=1)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "CNC ROUTING COVERS THE BORING" in flags
    assert "4 hole(s)" in flags and "8.5" in flags and "6.5" in flags


def test_cnc_routing_says_when_it_has_no_hole_inventory():
    import estimator as E
    part = _board_part(normalized_thickness_mm=18.0,
                       blank_length_mm=1198.0, blank_width_mm=398.0,
                       normalized_geometry={"estimated_cut_length_mm": 3192.0},
                       textual_operations=["cnc_routing"])
    E.estimate_process_times(part, quantity=1)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "NO hole inventory" in flags
