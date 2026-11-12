"""ONE BRACKET BECAME THREE COSTING RECORDS, AND EVERY CAUSE IS PINNED HERE (D-511).

12340-01M, M&S KD V2 Gondola Shelf Bracket, 13 Oct 2026, £225.12 at one off — of which
£49.92 bought the drawing's own product back ("Shelf Bracket", SDI history, head-word
'bracket'), £31.88 lasered and folded the OBSOLETE number 12341-01M (the revision table's
Rev A row read as the drawing's number, taking the page and a fictitious fold), and the
real bracket was left a DXF orphan. £29.13/bay of assembly labour was computed for a job
with nothing to assemble, and the build banner cried "9 behind" at a checkout that
contained the GitHub tip.

The fixture strings below are VERBATIM from the saved record of that run (the page's
title_block and bom region text) — the reviewer's requirement was the real reader over the
real text, not a synthetic shape.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# The page's title_block region, verbatim from output/json/12340-01M.json (13 Oct, 18:13).
TITLE_BLOCK_TEXT = (
    "R5 R5 19 4 REVISION TABLE REV DRG NO DESCRIPTION DATE BY "
    "A 12341-01M INITIAL RELEASE 12/03/2026 GS "
    "B 12340-01M PART / DRAWING NUMBER CORRECTED 13/05/2026 GS "
    "PROPERTY OF PROJECT DRAWING AND MAY NOT BE KD V2 GONDOLA SHELF BRACKET STORE OF THE "
    "FUTURE REPRODUCED WITHOUT CONSENT. © ALL DIMENSIONS ARE IN mm. DRAWING No SCALE REV "
    "2025 U N L E S S O T H E R W IS E S T A T ED B 1:1 12340-01M D O N O T S C A L E "
    "F R O M D R A W ING. Business Park DATE DRAWN CHECKED UPC 0324925 13/05/2026 GS GARETH 1/1")

# The region carrying the specification block, verbatim from the same record.
SPEC_TEXT = (
    "0 2 R MAX LOADING: WEIGHT: 352g SPECIFICATION: MATERIAL: MILD STEEL [CR4] FINISH: "
    "POWDER COATED COLOUR: RAL9010 - PURE WHITE")


# ── the revision table is history ────────────────────────────────────────────

def test_the_revision_table_reads_as_the_drawings_history():
    from extractor_patterns import parse_revision_table
    t = parse_revision_table(TITLE_BLOCK_TEXT)
    assert [r["rev"] for r in t["rows"]] == ["A", "B"]
    assert t["current_number"] == "12340-01M"
    assert t["current_revision"] == "B"
    assert t["superseded"] == {"12341-01M": "12340-01M"}


def test_a_bare_code_date_run_with_no_table_header_is_not_history():
    from extractor_patterns import parse_revision_table, strip_revision_table
    text = "A 12341-01M INITIAL RELEASE 12/03/2026 GS"      # no REVISION TABLE header
    assert parse_revision_table(text)["rows"] == []
    assert strip_revision_table(text) == text


def test_the_old_number_never_reaches_a_field():
    """THE RUN'S DEFECT, through the real reader over the real text: the drawing number is
    the current one, the superseded number is no part, the finish is clean of the revision
    row's words, and the revision is the letter — not 'DRG NO'."""
    from extractor_patterns import extract_title_block_fields
    tb = extract_title_block_fields(TITLE_BLOCK_TEXT + " " + SPEC_TEXT)
    assert tb["drawing_numbers"] == ["12340-01M"]
    assert "12341-01M" not in tb["part_numbers"]
    assert tb["revisions"][0] == "B"
    assert any("POWDER COAT" in f for f in tb["surface_finishes"])   # lexicon-normalised
    assert not any("INITIAL RELEASE" in f or "12341" in f for f in tb["surface_finishes"])
    assert not any("CORRECTED" in c or "12340-01M" in c for c in tb["colours"])
    assert tb["superseded_numbers"] == {"12341-01M": "12340-01M"}


def test_the_sheet_stays_a_detail_page():
    """The second code the table printed flipped the single bracket's sheet to 'assembly' —
    the role that feeds its title to the prose recogniser. Struck, it is one code, one
    detail sheet."""
    from file_scan import _infer_page_role
    role = _infer_page_role(TITLE_BLOCK_TEXT + " " + SPEC_TEXT + " FLAT PATTERN",
                            "", TITLE_BLOCK_TEXT)
    assert role["primary_role"] == "detail"
    assert "multiple_part_numbers_detected" not in role["signals"]


def test_the_part_number_harvest_drops_the_superseded_number():
    from file_scan import extract_patterns
    ps = extract_patterns(TITLE_BLOCK_TEXT + " " + SPEC_TEXT)
    assert "12340-01M" in ps["part_numbers"]
    assert "12341-01M" not in ps["part_numbers"]


# ── an angle is not a fold ───────────────────────────────────────────────────

def test_an_angle_alone_does_not_mint_folding():
    from extractor_patterns import infer_operations_from_text
    ops = infer_operations_from_text(
        "MILD STEEL BRACKET 90° CORNER R20 R12 FLAT PATTERN LASER",
        material="MILD STEEL", finishes=["POWDER COATED"], has_fold_geometry=False)
    assert "folding" not in ops
    assert "laser_cutting" in ops
    assert "powder_coating" in ops


def test_bend_evidence_still_folds():
    from extractor_patterns import infer_operations_from_text
    assert "folding" in infer_operations_from_text(
        "FOLD UP 90", material="MILD STEEL", has_fold_geometry=False)
    assert "folding" in infer_operations_from_text(
        "MILD STEEL", material="MILD STEEL", has_fold_geometry=True)


# ── the drawing cannot buy its own product ───────────────────────────────────

def test_the_jobs_own_title_words_guard_the_recogniser():
    """GUARD 2 never saw 'SHELF BRACKET': the title lives in the PDF's filename and the
    title block's description, which the token set did not read. Now it does."""
    from estimator import _is_job_identity_desc, _job_identity_tokens
    summary = {
        "source_file": "12340-01M.json",
        "job_source_pdfs": [
            {"name": "0324925_KD V2 Gondola Shelf Bracket_12340-01M_Rev B.pdf"}],
        "document_analysis": {"title_block": {
            "descriptions": ["KD V2 GONDOLA SHELF BRACKET"], "project_titles": []}},
        "declared_product": "12340-01M",
    }
    toks = _job_identity_tokens(summary)
    assert {"GONDOLA", "SHELF", "BRACKET"} <= toks
    assert _is_job_identity_desc("Shelf Bracket", toks)
    assert not _is_job_identity_desc("Piano Hinge 1200mm", toks)


# ── one leaf can be the product ──────────────────────────────────────────────

def test_a_single_part_job_resolves_its_declared_product():
    from route_compiler import build_part_graph
    parts = [{"part_number": "12340-01M", "description": "KD V2 GONDOLA SHELF BRACKET",
              "quantity": 1, "normalized_material": "MILD STEEL",
              "normalized_thickness_mm": 4.0}]
    graph = build_part_graph(parts, {}, [], [], None, declared_product="12340-01M")
    assert graph.get("product_root") == "12340-01M"
    assert not [i for i in (graph.get("issues") or [])
                if isinstance(i, dict) and "not_resolved" in str(i.get("code") or "")]
    # THE PRODUCT BEING ONE PART DOES NOT MAKE THAT PART AN ASSEMBLY. The first run under
    # this rule classified the bracket "assembly" because it was the top of the graph, which
    # ruled its laser not-applicable and refused its blank — powder on air at £121.48.
    node = next(n for n in graph["nodes"] if n.part_number == "12340-01M")
    assert node.kind == "leaf"
    assert not parts[0].get("is_assembly_parent")


def test_the_leaf_product_keeps_its_laser_through_route_compilation():
    """THE 19:10 BOOK'S REGRESSION, replayed on the record's own facts: £121.48 of powder on
    air, because the leaf-resolved product was classed an assembly and its laser ruled
    'assembly parent has no independently measured fabricated leaf'. The compiled route must
    REQUIRE the laser on the leaf, and nothing may call it an assembly."""
    from route_compiler import compile_route_without_pricing
    part = {"part_number": "12340-01M", "description": "KD V2 GONDOLA SHELF BRACKET",
            "quantity": 1, "normalized_material": "MILD STEEL",
            "normalized_thickness_mm": 4.0, "normalized_finish": "POWDER COATING",
            "blank_length_mm": 396.21, "blank_width_mm": 90.0,
            "blank_length_mm_source": "dxf_flat_pattern",
            "blank_width_mm_source": "dxf_flat_pattern",
            "dxf_measured_outline": True, "dxf_augmented": True,
            "dxf_measured_cut_length": 1050.6,
            "operations": ["laser_cutting", "powder_coating", "handling"],
            "normalized_geometry": {"blank_length_mm": 396.21, "blank_width_mm": 90.0,
                                    "estimated_cut_length_mm": 1050.6,
                                    "estimated_pierce_count": 2, "estimated_hole_count": 1},
            "pages": [1], "page_roles": ["detail"]}
    summary = {"declared_product": "12340-01M", "drawing_number": "12340-01M",
               "manufacturing_writeup": {"parts": [part]},
               "document_analysis": {"bom_rows": []}, "llm_full_extract": {}}
    compiled = compile_route_without_pricing(summary)
    by_op = {}
    for d in (compiled.get("decisions") or compiled.get("claims") or []):
        t = d if isinstance(d, dict) else d.__dict__
        if "12340" in str(t.get("target_id") or t.get("part_number") or ""):
            by_op[t.get("operation")] = (t.get("status"), str(t.get("reason") or ""))
    assert by_op.get("laser_cutting", ("", ""))[0] == "required", by_op
    assert "assembly parent" not in by_op.get("laser_cutting", ("", ""))[1]
    assert by_op.get("powder_coating", ("", ""))[0] == "required"
    nodes = [(n if isinstance(n, dict) else n.__dict__) for n in (compiled.get("nodes") or [])]
    assert all(t.get("kind") == "leaf" for t in nodes if t.get("part_number") == "12340-01M")
    assert not part.get("is_assembly_parent")


def test_two_matching_leaves_still_refuse_to_choose():
    from route_compiler import build_part_graph
    parts = [{"part_number": "12340-01M", "quantity": 1},
             {"part_number": "12340-01M REV0", "quantity": 1}]
    graph = build_part_graph(parts, {}, [], [], None, declared_product="12340-01M")
    # ambiguity is not silently resolved: either no product root, or an issue says why
    assert graph.get("product_root") != "12340-01M REV0"


# ── a bay rate needs a bay ───────────────────────────────────────────────────

def test_a_single_made_part_has_no_assembly_scope():
    from pricing_service import PricingService
    one = [{"part_number": "12340-01M", "page_roles": ["detail"]},
           {"part_number": "PACKAGING", "page_roles": ["bought_in"]},
           {"part_number": "DELIVERY", "page_roles": ["bought_in"]},
           {"part_number": "BI-SOMETHING", "page_roles": ["bought_in"]}]
    assert not PricingService.assembly_scope_exists(one)


def test_two_made_parts_or_an_assembly_have_scope():
    from pricing_service import PricingService
    assert PricingService.assembly_scope_exists(
        [{"part_number": "A-01M", "page_roles": ["detail"]},
         {"part_number": "A-02M", "page_roles": ["detail"]}])
    assert PricingService.assembly_scope_exists(
        [{"part_number": "A-GA", "is_assembly_parent": True}])


# ── one material, two spellings, no conflict ─────────────────────────────────

def test_mild_steel_equals_mild_underscore_steel():
    import re
    collapse = lambda s: re.sub(r"[\s_\-]+", " ", s)
    assert collapse("MILD_STEEL") == collapse("MILD STEEL")
