"""A HANDED BOM ROW THE PACK NEVER DREW BECOMES A RECORD OF ITS OWN (D-509).

12665's GA lists 12665-03-01M-H — the side wing built the other way round — and the pack
holds no sheet for it, so no reader ever made it a part record. The 16:41 book charged its
laser (£11.62) and its fold (£20.67), coated it, and carried not a gram of its steel: route
rows come from the BOM graph, material comes from part records, and the missing-price check
can only catch the gap AFTER costing. mirror_provisional_blanks (D-508) was built to fill a
hand's geometry — but it walks the part records, so a hand with no record was invisible to
the very pass written for it.

The fix is minted where the graph proves the row: a BOM-stated leaf, reached under a parent,
whose code mirrors an existing cut part's and which no record answers to, gets a record of
its own — the base's stock at the mirror's gap-fill standing, the row's own quantity, and no
geometry: the mirror pass that runs next fills the blank at provisional standing, labelled
and asked. Everything here is generic: any pack, any code that the mirror conventions
recognise as a hand.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from detail_page_geometry import (PROVISIONAL_SOURCE, mint_missing_hand_records,
                                  mirror_provisional_blanks)


def _base_part(**over):
    part = {
        "part_number": "12665-03-01M",
        "description": "NPI ZONE SIDE WING",
        "quantity": 1,
        "normalized_material": "MILD STEEL",
        "normalized_material_source": "pdf_title_block",
        "normalized_thickness_mm": 1.5,
        "normalized_thickness_mm_source": "pdf_title_block",
        "normalized_finish": "POWDER COATED",
        "normalized_finish_source": "pdf_title_block",
        "normalized_geometry": {},
        "_blank_provisional": {"basis": PROVISIONAL_SOURCE, "length": 1064.8, "width": 324,
                               "working": "formed envelope 1064.8 x 324 mm"},
        "blank_length_mm": 1064.8, "blank_width_mm": 324,
        "blank_length_mm_source": PROVISIONAL_SOURCE,
        "blank_width_mm_source": PROVISIONAL_SOURCE,
    }
    part.update(over)
    return part


def _hand_node(pn="12665-03-01M-H", **over):
    node = {"part_number": pn, "kind": "leaf", "parents": ["12665-03-GA-H"],
            "qty_own": 1.0, "description": "",
            "evidence": {"bom_stated": True, "raw_aliases": []}}
    node.update(over)
    return node


# ── the mint itself ───────────────────────────────────────────────────────────

def test_the_handed_row_becomes_a_record_with_its_bases_stock():
    """THE 16:41 BOOK'S DEFECT. The hand is minted, carries the base's material, gauge and
    finish at the mirror's own gap-fill standing, and says what it is."""
    parts = [_base_part()]
    minted = mint_missing_hand_records(parts, {"nodes": [_hand_node()]})
    assert minted == ["12665-03-01M-H"]
    hand = parts[1]
    assert hand["part_number"] == "12665-03-01M-H"
    assert hand["mirror_of"] == "12665-03-01M"
    assert hand["normalized_material"] == "MILD STEEL"
    assert hand["normalized_thickness_mm"] == 1.5
    assert hand["normalized_finish"] == "POWDER COATED"
    import source_precedence as sp
    assert sp.source_of(hand, "normalized_material") == "mirror_of_provisional"
    assert hand["_minted_hand_record"] is True
    assert hand["quantity"] == 1.0


def test_the_mirror_pass_then_fills_the_blank_from_the_bases_provisional():
    """THE TWO PASSES TOGETHER CLOSE THE GAP: mint, then mirror — the hand ends holding its
    base's provisional blank, labelled mirrored, with a question. This is the exact sequence
    file_scan runs."""
    parts = [_base_part()]
    mint_missing_hand_records(parts, {"nodes": [_hand_node()]})
    filled = mirror_provisional_blanks(parts)
    assert "12665-03-01M-H" in filled
    hand = parts[1]
    assert hand["blank_length_mm"] == 1064.8
    assert hand["blank_width_mm"] == 324
    assert hand["_blank_provisional"].get("mirrored_from") == "12665-03-01M"
    assert any("provisional" in str(q.get("issue", "")).lower()
               for q in hand["manufacturing_questions"])


def test_the_minted_record_asks_rather_than_passing_in_silence():
    parts = [_base_part()]
    mint_missing_hand_records(parts, {"nodes": [_hand_node()]})
    hand = parts[1]
    assert any("minted" in str(q.get("issue", "")) for q in hand["manufacturing_questions"])
    assert any("MINTED" in f for f in hand["review_flags"])


def test_the_rows_own_quantity_is_kept():
    parts = [_base_part()]
    mint_missing_hand_records(parts, {"nodes": [_hand_node(qty_own=3.0)]})
    assert parts[1]["quantity"] == 3.0


def test_the_description_falls_back_to_the_bases_named_as_the_other_hand():
    parts = [_base_part()]
    mint_missing_hand_records(parts, {"nodes": [_hand_node()]})
    assert parts[1]["description"] == "NPI ZONE SIDE WING (opposite hand)"


# ── what is deliberately left alone ──────────────────────────────────────────

def test_a_row_a_record_already_answers_to_is_left_alone():
    """Minting over an existing record would be the duplicate-line bug in reverse."""
    parts = [_base_part(), {"part_number": "12665-03-01M-H ", "quantity": 1}]
    assert mint_missing_hand_records(parts, {"nodes": [_hand_node()]}) == []
    assert len(parts) == 2


def test_a_row_answering_under_an_alias_is_left_alone():
    parts = [_base_part(), {"part_number": "MIRROR12665-03-01M", "quantity": 1}]
    node = _hand_node(evidence={"bom_stated": True,
                                "raw_aliases": ["Mirror12665-03-01M"]})
    assert mint_missing_hand_records(parts, {"nodes": [node]}) == []
    assert len(parts) == 2


def test_a_handed_assembly_code_is_not_minted_as_a_part():
    """12665-03-GA-H mirrors an assembly: its answer is D-505's route mirror, not a blank."""
    parts = [_base_part()]
    assert mint_missing_hand_records(
        parts, {"nodes": [_hand_node(pn="12665-03-GA-H")]}) == []
    assert len(parts) == 1


def test_a_hand_of_an_assembly_record_is_not_minted():
    """A base that is itself an assembly cuts no blank — there is nothing to be the other
    hand OF at part level."""
    parts = [_base_part(is_assembly_parent=True)]
    assert mint_missing_hand_records(parts, {"nodes": [_hand_node()]}) == []
    assert len(parts) == 1


def test_a_code_that_mirrors_nothing_is_not_minted():
    parts = [_base_part()]
    assert mint_missing_hand_records(
        parts, {"nodes": [_hand_node(pn="12665-09-01M")]}) == []
    assert len(parts) == 1


def test_a_row_the_bom_does_not_state_is_not_minted():
    """A name the tree inferred is not a stated row; inventing a record for it would mint
    phantoms from numbering."""
    parts = [_base_part()]
    node = _hand_node(evidence={"bom_stated": False, "raw_aliases": []})
    assert mint_missing_hand_records(parts, {"nodes": [node]}) == []
    assert len(parts) == 1


def test_an_unreached_node_is_not_minted():
    parts = [_base_part()]
    assert mint_missing_hand_records(
        parts, {"nodes": [_hand_node(parents=[])]}) == []
    assert len(parts) == 1


def test_a_bought_in_node_is_not_minted():
    """A bought-in hand is priced as a commercial line, not cut from its base's sheet."""
    parts = [_base_part()]
    assert mint_missing_hand_records(
        parts, {"nodes": [_hand_node(kind="bought_in")]}) == []
    assert len(parts) == 1


def test_a_base_with_no_mirrorable_blank_still_mints_the_record():
    """The record and its stock are worth having even when the base's blank is measured —
    the hand then surfaces as a missing-geometry question instead of vanishing entirely."""
    base = _base_part()
    del base["_blank_provisional"]
    parts = [base]
    minted = mint_missing_hand_records(parts, {"nodes": [_hand_node()]})
    assert minted == ["12665-03-01M-H"]
    assert parts[1]["normalized_material"] == "MILD STEEL"
