"""12343-01J said EDGED ALL AROUND and the engine heard "EDGED" (D-513).

The drawing answered every question the first book asked. "EDGED ALL AROUND" is a statement
of the whole perimeter; "2S/SL" is the bander's run order; the REAR export holds the bores;
the title block states 5,573 g. None of it reached the costed record: the finish box kept
one word, the note harvester keeps only deburr/weld/tap words, the REAR DXF was set aside
whole as "distinct blanks — pick best", and MFC had no density so the one check on a
PROVISIONAL gauge stood down without a word. So the book flagged the banding a CEILING,
built no edging material line, said "NO hole inventory", and showed no weight comparison —
on a job whose paperwork contained all four answers.

Every fix is a carrier, not a guess: the sheet's own sentence onto the record, the second
view's measured circles into an empty inventory, the stated weight against the proposed
gauge, and the finish box's banding words recognised as the work the route already charges.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ── the harvester: the sheet's sentence survives whole ───────────────────────────────────

def test_the_sheets_banding_sentence_is_harvested_with_its_extent():
    from edge_banding import harvest_banding_statements
    text = ("KD V2 SHELF 1198 x 398. PANEL TO BE EDGED ALL AROUND. "
            "EDGING ORDER 2S/SL. EGGER W980 ST7 PLATINUM WHITE. 600 CENTRES")
    stmts = harvest_banding_statements(text)
    joined = " ".join(stmts)
    assert "EDGED ALL AROUND" in joined
    assert any("2S" in s for s in stmts)


def test_a_bought_trim_is_not_harvested_as_a_banding_statement():
    """"EDGING TRIM, CHROME" names a thing we buy — the same refusal is_banding_row makes."""
    from edge_banding import harvest_banding_statements
    assert harvest_banding_statements("EDGING TRIM, CHROME, L: 1200MM") == []


def test_a_sheet_that_says_nothing_about_edges_harvests_nothing():
    from edge_banding import harvest_banding_statements
    assert harvest_banding_statements(
        "MILD STEEL BRACKET 3MM. POWDER COAT RAL 9005. ALL WELDS TIG") == []


def test_the_bare_order_code_alone_says_the_part_is_banded():
    """"2S/SL" with no other banding word. D-512's pattern read the order code as ONE letter
    per leg, so the exact code 12343-01J writes — two short, then the long SIDES — never
    matched the rule built for it; "S/S" (a stainless shorthand) still says nothing."""
    from edge_banding import banded_length_mm
    part = {"blank_length_mm": 1198.0, "blank_width_mm": 398.0, "notes": ["2S/SL"]}
    assert banded_length_mm(part)["basis"] != "no_evidence"
    steel = {"blank_length_mm": 100.0, "blank_width_mm": 50.0, "notes": ["S/S BRACKET"]}
    assert banded_length_mm(steel)["basis"] == "no_evidence"


def test_the_harvested_statement_resolves_the_banded_length():
    from edge_banding import banded_length_mm
    part = {"part_number": "12399-77J", "blank_length_mm": 1198.0, "blank_width_mm": 398.0,
            "normalized_finish": "EDGED",
            "banding_statements": ["PANEL TO BE EDGED ALL AROUND"]}
    out = banded_length_mm(part)
    assert out["basis"] == "note_all_round"
    assert abs(out["mm"] - 3192.0) < 0.5


# ── the stamp: document build carries the sentence from the detail page ──────────────────

def _page(num, text, role="detail"):
    return {"page_number": num, "page_role": {"primary_role": role},
            "text_preview": text, "region_text": {}}


def test_the_detail_pages_statement_lands_on_the_part_record():
    import document_builder as db
    part = db._empty_part_record("12399-77J")
    part["pages"] = [1]
    part["description"] = "KD V2 SHELF"
    summary = {"pages": [_page(1, "KD V2 SHELF. TO BE EDGED ALL AROUND. EDGING ORDER 2S/SL")]}
    out = db._apply_post_build_fixes([part], summary)
    stmts = out[0].get("banding_statements") or []
    assert any("EDGED ALL AROUND" in s for s in stmts), stmts


def test_an_assembly_pages_note_is_not_stamped_on_every_member():
    """A note stays on the sheet it is written on: a GA's banding sentence names a member
    this pass cannot resolve, so it stamps nothing."""
    import document_builder as db
    part = db._empty_part_record("12399-77J")
    part["pages"] = [1]
    summary = {"pages": [_page(1, "GA NOTES: SHELF EDGED ALL AROUND", role="assembly")]}
    out = db._apply_post_build_fixes([part], summary)
    assert not out[0].get("banding_statements")


# ── the finish box: EDGED is the edging the route charges, not unknown vocabulary ────────

def test_finish_states_banding_knows_its_own_vocabulary():
    from edge_banding import finish_states_banding
    assert finish_states_banding("EDGED")
    assert finish_states_banding("EDGED EDGED")
    assert finish_states_banding("EDGED ALL AROUND")
    assert finish_states_banding("EDGE BANDED 2S/SL")
    assert not finish_states_banding("EDGED & POWDER COATED")
    assert not finish_states_banding("POWDER COATING")
    assert not finish_states_banding("")


def test_an_edged_finish_on_a_banded_route_is_not_an_unknown_finish():
    import invariants as inv
    job = {"manufacturing_writeup": {"parts": [
        {"part_number": "12399-77J", "normalized_finish": "EDGED EDGED",
         "textual_operations": ["cnc_routing", "edge_banding"]}]}}
    codes = [v.get("code") or v.get("name") for v in
             inv.check_a_stated_finish_is_costed(job)]
    assert "stated_finish_not_recognised" not in codes, codes


def test_an_edged_finish_on_a_part_nobody_bands_still_fires():
    """EDGED with no Edge Banding anywhere is still a stated finish going uncharged."""
    import invariants as inv
    job = {"manufacturing_writeup": {"parts": [
        {"part_number": "12399-78M", "normalized_finish": "EDGED",
         "textual_operations": ["laser_cutting"]}]}}
    codes = [v.get("code") or v.get("name") for v in
             inv.check_a_stated_finish_is_costed(job)]
    assert "stated_finish_not_recognised" in codes, codes


# ── the weight: a provisional gauge's one witness is stated, not silent ──────────────────

def _board_with_stated_weight(thickness_source):
    from source_precedence import apply_field
    part = {"part_number": "12399-77J", "description": "KD V2 SHELF",
            "normalized_material": "MFC", "stated_weight_g": 5573.0,
            "normalized_geometry": {"blank_length_mm": 1198.0, "blank_width_mm": 398.0}}
    apply_field(part, "normalized_thickness_mm", 18.0, thickness_source)
    return part


def test_a_board_has_a_weighing_density_and_no_costing_density():
    """The check can weigh a board; nothing can price one by the kilo — the costing table
    stays deliberately board-free (test_estimating_rules holds that precondition)."""
    import config
    assert config.BOARD_WEIGHT_DENSITY_KG_PER_M3.get("MFC")
    assert config.BOARD_WEIGHT_DENSITY_KG_PER_M3.get("CHIPBOARD")
    assert "MFC" not in config.MATERIAL_DENSITY_KG_PER_M3
    assert "CHIPBOARD" not in config.MATERIAL_DENSITY_KG_PER_M3


def test_the_weight_supports_the_provisional_gauge_and_says_so():
    import estimator as E
    note = E._blank_weight_check(_board_with_stated_weight("model_extents_board_gauge"))
    assert note and note.startswith("WEIGHT NOTE:"), note
    assert "PROVISIONAL" in note and "supports the gauge" in note
    assert "5.573" in note


def test_a_stated_gauge_that_weighs_right_stays_silent():
    """The positive sentence is for the gauge this engine PROPOSED; a drawing callout that
    agrees with the weight has nothing to report — the pass stays quiet as it always did."""
    import estimator as E
    assert E._blank_weight_check(_board_with_stated_weight("pdf_title_block")) is None


def test_a_provisional_gauge_the_weight_refutes_still_raises_the_check():
    import estimator as E
    part = _board_with_stated_weight("model_extents_board_gauge")
    part["stated_weight_g"] = 2000.0          # 6.18 kg blank against a stated 2 kg
    note = E._blank_weight_check(part)
    assert note and note.startswith("WEIGHT CHECK:"), note


# ── the second view: its measured circles are the hole inventory ─────────────────────────

def _write_dxf(path, length, width, circles=()):
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (length, 0), (length, width), (0, width)],
                       close=True, dxfattribs={"layer": "0"})
    for (x, y, d) in circles:
        msp.add_circle((x, y), d / 2.0, dxfattribs={"layer": "0"})
    doc.saveas(path)


def test_the_unchosen_views_holes_join_the_parts_inventory(tmp_path):
    import drawing_job_merge as djm
    underside = tmp_path / "12399-77J_UNDERSIDE.DXF"
    rear = tmp_path / "12399-77J_REAR.DXF"
    _write_dxf(str(underside), 1198.0, 398.0)
    _write_dxf(str(rear), 1198.0, 18.0,
               circles=[(100, 9, 8.5), (500, 9, 8.5), (700, 9, 6.5), (1100, 9, 6.5)])
    summary = {"manufacturing_writeup": {"parts": [
        {"part_number": "12399-77J", "description": "KD V2 SHELF",
         "normalized_material": "MFC", "quantity": 1}]}, "pages": []}
    out = djm.augment_summary_with_dxf(summary, [str(underside), str(rear)],
                                       reestimate=False)
    part = out["manufacturing_writeup"]["parts"][0]
    # the blank stays the chosen flat's — the second view never becomes a second blank
    assert abs(float(part.get("overall_length_mm") or 0) - 1198.0) < 1.0
    assert abs(float(part.get("overall_width_mm") or 0) - 398.0) < 1.0
    assert int((part.get("geometry_rollup") or {}).get("estimated_hole_count") or 0) == 4
    inv = part.get("secondary_view_hole_inventory") or {}
    assert inv.get("hole_count") == 4 and any("REAR" in f for f in inv.get("files") or [])
    dias = [float(d) for d in (part.get("hole_sizes_mm") or [])]
    assert 8.5 in dias and 6.5 in dias, dias
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "HOLE INVENTORY FROM A SECOND VIEW" in flags
    report = out.get("dxf_augmentation") or {}
    sv = report.get("secondary_view_holes") or []
    assert sv and sv[0]["hole_count"] == 4


def test_a_flat_that_measured_its_own_holes_is_not_second_guessed(tmp_path):
    """The chosen flat's measured circles ARE the inventory; the second view fills a gap,
    never overwrites a measurement."""
    import drawing_job_merge as djm
    underside = tmp_path / "12399-77J_UNDERSIDE.DXF"
    rear = tmp_path / "12399-77J_REAR.DXF"
    _write_dxf(str(underside), 1198.0, 398.0,
               circles=[(100, 100, 5.0), (300, 100, 5.0)])
    _write_dxf(str(rear), 1198.0, 18.0, circles=[(100, 9, 8.5)])
    summary = {"manufacturing_writeup": {"parts": [
        {"part_number": "12399-77J", "description": "KD V2 SHELF",
         "normalized_material": "MFC", "quantity": 1}]}, "pages": []}
    out = djm.augment_summary_with_dxf(summary, [str(underside), str(rear)],
                                       reestimate=False)
    part = out["manufacturing_writeup"]["parts"][0]
    assert int((part.get("geometry_rollup") or {}).get("estimated_hole_count") or 0) == 2
    assert "secondary_view_hole_inventory" not in part
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "HOLE INVENTORY FROM A SECOND VIEW" not in flags


# ── and the inventory reaches the routing's claim (the D-512 flag, now fed) ──────────────

def test_the_second_views_holes_feed_the_cnc_routing_claim():
    import estimator as E
    part = {"part_number": "12399-77J", "description": "KD V2 SHELF",
            "normalized_material": "MFC", "quantity": 1,
            "normalized_thickness_mm": 18.0,
            "blank_length_mm": 1198.0, "blank_width_mm": 398.0,
            "hole_sizes_mm": [8.5, 6.5],
            "textual_operations": ["cnc_routing"],
            "normalized_geometry": {"estimated_hole_count": 4,
                                    "estimated_cut_length_mm": 3192.0,
                                    "hole_inventory_source":
                                        "secondary DXF view(s): 12399-77J_REAR.DXF"}}
    E.estimate_process_times(part, quantity=1)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "CNC ROUTING COVERS THE BORING" in flags
    assert "4 hole(s)" in flags
