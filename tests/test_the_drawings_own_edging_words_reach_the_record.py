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


# ── the estimate-time carrier: the pages stamp the parts where the money is (D-514) ──────

def _detail_page(code, text):
    return {"page_number": 1, "page_role": {"primary_role": "detail"},
            "text_preview": text, "region_text": {"notes": text},
            "page_analysis": {"title_block": {"drawing_numbers": [code]}}}


def test_the_estimate_time_stamp_reads_the_saved_pages():
    """The 09:36 record held the statement in its own page text and the costed part still
    arrived without it. The estimate-time pass reads the pages AS SAVED, so a replay of
    the record stamps the same statement the document build should have."""
    from edge_banding import stamp_banding_statements_from_pages, banded_length_mm
    part = {"part_number": "12399-77J", "blank_length_mm": 1198.0, "blank_width_mm": 398.0}
    summary = {"pages": [_detail_page(
        "12399-77J", "EDGED ALL AROUND EDGING ORDER: 2S/SL C B SECTION A-A 10")]}
    assert stamp_banding_statements_from_pages([part], summary) == 1
    out = banded_length_mm(part)
    assert out["basis"] == "note_all_round" and abs(out["mm"] - 3192.0) < 0.5


def test_the_stamp_fills_only_a_gap_and_only_the_named_part():
    from edge_banding import stamp_banding_statements_from_pages
    held = {"part_number": "12399-77J", "banding_statements": ["EDGED TWO LONG EDGES"]}
    other = {"part_number": "12399-78M"}
    summary = {"pages": [_detail_page("12399-77J", "EDGED ALL AROUND")]}
    assert stamp_banding_statements_from_pages([held, other], summary) == 0
    assert held["banding_statements"] == ["EDGED TWO LONG EDGES"]
    assert "banding_statements" not in other


def test_an_assembly_page_stamps_nothing_at_estimate_time():
    from edge_banding import stamp_banding_statements_from_pages
    part = {"part_number": "12399-77J"}
    page = _detail_page("12399-77J", "EDGED ALL AROUND")
    page["page_role"] = {"primary_role": "assembly"}
    assert stamp_banding_statements_from_pages([part], {"pages": [page]}) == 0


# ── the reference is named: a model's mass is not "the sheet's stated" (D-514) ───────────

def test_the_weight_note_names_the_models_mass_and_the_sheets_own_figure():
    """The 09:36 book said "against the stated 5.496 kg" — the MODEL's mass, presented as
    drawing corroboration while the sheet prints 5.573 kg. The reference keeps its name and
    the sheet's differing figure rides beside it."""
    import estimator as E
    from source_precedence import apply_field
    part = {"part_number": "12399-77J", "description": "KD V2 SHELF",
            "normalized_material": "MFC",
            "stated_weight_g": 5496.0, "stated_weight_source": "solidworks_model_mass",
            "weights": ["5573g"],
            "normalized_geometry": {"blank_length_mm": 1198.0, "blank_width_mm": 398.0}}
    apply_field(part, "normalized_thickness_mm", 18.0, "model_extents_board_gauge")
    note = E._blank_weight_check(part)
    assert note and "the model's 5.496 kg" in note, note
    assert "the sheet itself prints 5.573 kg" in note, note
    assert "the sheet's stated 5.496" not in note


def test_a_sheets_own_weight_keeps_its_plain_name():
    import estimator as E
    from source_precedence import apply_field
    part = {"part_number": "12399-77J", "description": "KD V2 SHELF",
            "normalized_material": "MFC", "stated_weight_g": 5573.0,
            "normalized_geometry": {"blank_length_mm": 1198.0, "blank_width_mm": 398.0}}
    apply_field(part, "normalized_thickness_mm", 18.0, "model_extents_board_gauge")
    note = E._blank_weight_check(part)
    assert note and "the sheet's stated 5.573 kg" in note, note
    assert "the sheet itself prints" not in note


def test_the_sw_extract_stamps_whose_mass_it_wrote():
    from source_connectors import solidworks as sw
    part = _board_part()
    sw.apply_native_to_pre_estimate(
        [part], _native_job_mass(mass_kg=5.496))
    assert float(part.get("stated_weight_g") or 0) == 5496.0
    assert part.get("stated_weight_source") == "solidworks_model_mass"


def _native_job_mass(**kw):
    from source_connectors import solidworks as sw
    nat = sw.NativePart(part_number="12399-77J", **kw)
    return sw.NativeJob(part_signals={"12399-77J": nat}, found=True,
                        meta={"extract_path": "test"})


def _board_part(**over):
    part = {"part_number": "12399-77J", "description": "KD V2 SHELF",
            "normalized_material": "MFC", "quantity": 1}
    part.update(over)
    return part


# ── the routing's claim matches its evidence (D-514) ─────────────────────────────────────

def test_a_second_view_inventory_is_not_called_a_program():
    import estimator as E
    part = _board_part(normalized_thickness_mm=18.0,
                       blank_length_mm=1198.0, blank_width_mm=398.0,
                       hole_sizes_mm=[6.5],
                       secondary_view_hole_inventory={
                           "files": ["12399-77J_REAR.DXF"], "hole_count": 2,
                           "hole_diameters_mm": [6.5]},
                       textual_operations=["cnc_routing"],
                       normalized_geometry={"estimated_hole_count": 2,
                                            "estimated_cut_length_mm": 3192.0})
    E.estimate_process_times(part, quantity=1)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "measured on a second view" in flags and "12399-77J_REAR.DXF" in flags
    assert "not a demonstrated program" in flags
    assert "are in the program" not in flags


def test_the_costed_flats_own_holes_still_read_as_the_program():
    import estimator as E
    part = _board_part(normalized_thickness_mm=18.0,
                       blank_length_mm=1198.0, blank_width_mm=398.0,
                       hole_sizes_mm=[8.5, 6.5],
                       textual_operations=["cnc_routing"],
                       normalized_geometry={"estimated_hole_count": 4,
                                            "estimated_cut_length_mm": 3192.0})
    E.estimate_process_times(part, quantity=1)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "are in the program" in flags


# ── D-515: the saved record itself, replayed ─────────────────────────────────────────────
#
# The probe on the live 12343-01J record showed the D-513 stamp HAD fired and survived —
# and banded_length_mm still returned extent-unknown: _interpret_part rebuilds
# normalized_geometry with the blank under bounding_box_flat_mm, blank_length_mm is gone,
# and the ALL AROUND branch cannot state a perimeter it cannot see. These fixtures are the
# saved record's own shapes, verbatim from the probe output.

_SAVED_STATEMENTS = [
    '1198 A A 893 493 1194 2 EDGED ALL AROUND EDGING ORDER: 2S/SL 163 B C',
    'N: MATERIAL: MFC REVISION TABLE FINISH: EDGED REV DRG NO DESCRIPTION DATE BY COLOUR:',
    '3G SPECIFICATION: MATERIAL: MFC FINISH: EDGED COLOUR: EGGER: W980 ST7   PLATINUM WHIT',
    'ED UPC 0324926 18/03/2026 GS GARETH 1/1 EDGED ALL AROUND EDGING ORDER: 2S/SL C B SECT',
]

def _saved_record_part(**over):
    part = {"part_number": "12399-77J", "description": "KD V2 SHELF", "quantity": 1,
            "normalized_material": "MFC",
            "textual_operations": ["cnc_routing", "edge_banding"],
            "banding_statements": list(_SAVED_STATEMENTS),
            "normalized_geometry": {
                "stock_form": "sheet", "profile_type": "flat",
                "bounding_box_flat_mm": {"length": 1198.0, "width": 398.0, "height": 18.0},
                "bounding_box_formed_mm": {"length": 1198.0, "width": 398.0, "height": None},
                "developed_length_mm": 1198.0, "developed_width_mm": 398.0}}
    part.update(over)
    return part


def test_the_saved_records_own_shape_resolves_the_all_round_statement():
    from edge_banding import banded_length_mm
    out = banded_length_mm(_saved_record_part())
    assert out["basis"] == "note_all_round", out
    assert abs(out["mm"] - 3192.0) < 0.5


def test_a_record_with_no_blank_in_any_spelling_still_refuses_an_extent():
    from edge_banding import banded_length_mm
    part = _saved_record_part(normalized_geometry={})
    out = banded_length_mm(part)
    assert out["mm"] is None and out["basis"] == "banding_stated_extent_unknown"


# ── D-515: the drawing's bore callouts survive as evidence ───────────────────────────────

def test_the_callouts_the_text_layer_keeps_are_read():
    """The Ø and depth glyphs are CAD symbols and die in extraction — 12343-01J's text says
    "2 x 8 11" and "2 x 6.5 10". The shape is read; sizes and sheet dims are not."""
    from extractor_patterns import extract_stated_bore_callouts
    text = ("SECTION A-A 2 x 8 11 296.5 5 5 296.5 299 600 - CENTRES 299 "
            "2 x 6.5 10 81 DETAIL B SCALE 1 : 1 KD V2 SHELF 1198 X 400 SHEET 2800 x 2070")
    calls = extract_stated_bore_callouts(text)
    assert {(c["count"], c["diameter_mm"], c["depth_mm"]) for c in calls} == \
        {(2.0, 8.0, 11.0), (2.0, 6.5, 10.0)}, calls


def test_a_repeated_callout_is_one_statement():
    from extractor_patterns import extract_stated_bore_callouts
    assert len(extract_stated_bore_callouts("2 x 6.5 10 ... 2 x 6.5 10")) == 1


def test_the_detail_page_stamps_the_callouts_on_the_part():
    import document_builder as db
    part = db._empty_part_record("12399-77J")
    part["pages"] = [1]
    summary = {"pages": [_page(1, "SECTION A-A 2 x 8 11 AND 2 x 6.5 10")]}
    out = db._apply_post_build_fixes([part], summary)
    calls = out[0].get("stated_bore_callouts") or []
    assert sum(c["count"] for c in calls) == 4, calls


def test_stated_bores_beyond_the_inventory_are_said_on_the_routing():
    import estimator as E
    part = _saved_record_part(
        hole_sizes_mm=[6.5],
        stated_bore_callouts=[{"count": 2.0, "diameter_mm": 8.0, "depth_mm": 11.0},
                              {"count": 2.0, "diameter_mm": 6.5, "depth_mm": 10.0}],
        normalized_geometry={"estimated_hole_count": 2,
                             "estimated_cut_length_mm": 3192.0,
                             "bounding_box_flat_mm": {"length": 1198.0, "width": 398.0}})
    E.estimate_process_times(part, quantity=1)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "STATED BORES EXCEED THE RECORDED INVENTORY" in flags
    assert "state 4 bore(s)" in flags and "the record holds 2" in flags


# ── D-516: the minted edging line is generated work, not an unlinked stranger ────────────

def _scope_payload():
    return {"product_root": "12399-77J",
            "nodes": [{"part_number": "12399-77J", "evidence": {}}]}


def _edging_pe(**over):
    import config
    pe = {"part_number": config.FACED_BOARD_EDGING_CODE, "_edging_line": True,
          "_edging_for": ["12399-77J"], "quantity": 3.192,
          "extended_total_cost_gbp": 0.0}
    pe.update(over)
    return pe


def test_the_edging_line_survives_the_product_scope_on_its_provenance():
    """The 11:22 book minted EDGE23X1ABS at 3.192 m and then set it aside: "Not linked to
    12399-77J, so not priced". The line is kept because the parts whose banded lengths
    created it (_edging_for) are IN the graph — not by any blanket exemption."""
    import config
    import route_compiler as rc
    pes = [{"part_number": "12399-77J", "extended_total_cost_gbp": 5.0},
           _edging_pe(),
           {"part_number": "STRAY-99X", "extended_total_cost_gbp": 9.0}]
    rc.set_aside_late_lines(pes, _scope_payload(), {})
    kept = {p["part_number"] for p in pes}
    assert config.FACED_BOARD_EDGING_CODE in kept, kept
    assert "STRAY-99X" not in kept, "the scope rule must still set aside a real stranger"


def test_edging_of_an_excluded_part_is_still_excluded():
    """The same code could band a part this product does not contain: metres measured only
    on out-of-scope parts have no claim, and a line with no provenance at all has none."""
    import config
    import route_compiler as rc
    pes = [{"part_number": "12399-77J", "extended_total_cost_gbp": 5.0},
           _edging_pe(_edging_for=["99999-OTHER"])]
    rc.set_aside_late_lines(pes, _scope_payload(), {})
    assert config.FACED_BOARD_EDGING_CODE not in {p["part_number"] for p in pes}
    pes2 = [{"part_number": "12399-77J", "extended_total_cost_gbp": 5.0},
            _edging_pe(_edging_for=[])]
    rc.set_aside_late_lines(pes2, _scope_payload(), {})
    assert config.FACED_BOARD_EDGING_CODE not in {p["part_number"] for p in pes2}


def test_mixed_provenance_is_kept_and_flagged_to_reduce():
    import config
    import route_compiler as rc
    pes = [{"part_number": "12399-77J", "extended_total_cost_gbp": 5.0},
           _edging_pe(_edging_for=["12399-77J", "99999-OTHER"])]
    rc.set_aside_late_lines(pes, _scope_payload(), {})
    line = next(p for p in pes
                if p["part_number"] == config.FACED_BOARD_EDGING_CODE)
    flags = " ".join(str(f) for f in line.get("review_flags") or [])
    assert "EDGING METRES INCLUDE EXCLUDED PARTS" in flags


def test_the_config_code_alone_exempts_nothing():
    import config
    import route_compiler as rc
    assert not rc._is_generated_line(config.FACED_BOARD_EDGING_CODE, {})


def test_the_minted_stub_carries_its_provenance():
    """estimate_document's edging block stamps _edging_for with the parts whose banded
    lengths created the line — the fact the scope rule validates."""
    import inspect
    import estimator as E
    src = inspect.getsource(E.estimate_document)
    assert '_stub["_edging_for"]' in src


# ── D-516: the estimate-time carrier stamps the bore callouts too ─────────────────────────

def test_the_estimate_time_carrier_stamps_the_bore_callouts():
    """The 11:22 book proved the build-time stamp does not reliably reach the costed record:
    banding survived only through the estimate-time carrier, and the bores — same text, no
    carrier — arrived nowhere. One carrier, both statements."""
    from edge_banding import stamp_banding_statements_from_pages
    part = {"part_number": "12399-77J"}
    summary = {"pages": [_detail_page(
        "12399-77J", "EDGED ALL AROUND SECTION A-A 2 x 8 11 AND 2 x 6.5 10")]}
    assert stamp_banding_statements_from_pages([part], summary) == 1
    calls = part.get("stated_bore_callouts") or []
    assert sum(c["count"] for c in calls) == 4, calls
    assert part.get("banding_statements")


def test_existing_callouts_are_not_overwritten_by_the_carrier():
    from edge_banding import stamp_banding_statements_from_pages
    part = {"part_number": "12399-77J",
            "banding_statements": ["EDGED ALL AROUND"],
            "stated_bore_callouts": [{"count": 2.0, "diameter_mm": 5.0, "depth_mm": 8.0}]}
    summary = {"pages": [_detail_page("12399-77J", "EDGED ALL AROUND 2 x 8 11")]}
    assert stamp_banding_statements_from_pages([part], summary) == 0
    assert part["stated_bore_callouts"][0]["diameter_mm"] == 5.0


# ── D-515: the acceptance checks catch missing work ──────────────────────────────────────

def test_a_banded_part_with_known_metres_and_no_edging_line_is_a_violation():
    import invariants as inv
    job = {"manufacturing_writeup": {"parts": [_saved_record_part()]}}
    codes = [v.get("code") or v.get("name") for v in
             inv.check_a_banded_board_buys_its_edging(job)]
    assert "edging_material_missing" in codes, codes


def test_the_edging_line_on_the_bill_satisfies_the_check():
    import invariants as inv
    import config
    job = {"manufacturing_writeup": {"parts": [
        _saved_record_part(),
        {"part_number": config.FACED_BOARD_EDGING_CODE, "_edging_line": True,
         "description": "ABS edging — 3.192 m a unit", "quantity": 3.192}]}}
    assert inv.check_a_banded_board_buys_its_edging(job) == []


def test_an_unresolved_extent_is_a_question_not_this_violation():
    """The CEILING question owns the unresolved case; this check fires only on KNOWN metres."""
    import invariants as inv
    part = _saved_record_part(banding_statements=["EDGED"], normalized_geometry={})
    job = {"manufacturing_writeup": {"parts": [part]}}
    assert inv.check_a_banded_board_buys_its_edging(job) == []


def test_four_stated_bores_with_two_recorded_is_a_violation():
    import invariants as inv
    part = _saved_record_part(
        hole_sizes_mm=[6.5],
        stated_bore_callouts=[{"count": 2.0, "diameter_mm": 8.0, "depth_mm": 11.0},
                              {"count": 2.0, "diameter_mm": 6.5, "depth_mm": 10.0}],
        normalized_geometry={"estimated_hole_count": 2})
    job = {"manufacturing_writeup": {"parts": [part]}}
    found = inv.check_stated_bores_reach_the_inventory(job)
    assert [v.get("code") or v.get("name") for v in found] == ["stated_bores_not_in_inventory"]


def test_a_full_inventory_satisfies_the_boring_check():
    import invariants as inv
    part = _saved_record_part(
        hole_sizes_mm=[8.0, 6.5],
        stated_bore_callouts=[{"count": 2.0, "diameter_mm": 8.0, "depth_mm": 11.0},
                              {"count": 2.0, "diameter_mm": 6.5, "depth_mm": 10.0}],
        normalized_geometry={"estimated_hole_count": 4})
    job = {"manufacturing_writeup": {"parts": [part]}}
    assert inv.check_stated_bores_reach_the_inventory(job) == []


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
