"""A TUBE'S OWN ROUND STOCK LINE IS ITS CUT LIST, NOT A CHILD PART (20 Nov 2026).

12110-01-GA1, run d95c7b140e6a: the side fixing tube 12110-02-05M (42 off) and the pin tube
12110-05-12M each print their stock on their own sheet as "12.7mm DIA x 1.2mm WALL 50". No
section path read that spelling, so the row was minted a bought-in child ("BI-WALL"), the tube
became an assembly of it, its material went to nil ("an assembly's material is its members'")
and it carried a weldment's 30 min weld and 20 min dressing allowance, every one of the 42.

A diameter marked as one (DIA, Ø, OD) times a wall marked as one (WALL, WT, THK), or beside a
hollow word, is now read as a round section like any a x b x t callout: the row is the tube's
cut list and the tube keeps its own stock. Dowels and screws sized "ø6 x 20" are still parts.
Invented numbers.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bom_pipeline as bp  # noqa: E402
from part_identity import mint_uncoded_row_identities, parts_list_row_role  # noqa: E402
from section_profile import detect_section_stock  # noqa: E402


def test_the_round_callouts_read_as_a_section_with_their_length():
    for text, d, t, length in (("12.7mm DIA x 1.2mm WALL 50", 12.7, 1.2, 50.0),
                               ("Ø16 x 1.5mm TUBE 300", 16.0, 1.5, 300.0),
                               ("DIA 25 x 2 CHS 600", 25.0, 2.0, 600.0)):
        s = detect_section_stock(text)
        assert s and s["detection_path"] == "canonical_profile", text
        assert (s["a"], s["t"], s["length_mm"], s["profile_form"]) == (d, t, length, "CHS"), s
        assert parts_list_row_role(text) == "parent_cut_list", text


def test_a_dowel_or_a_screw_sized_by_diameter_is_still_a_part():
    for text in ("6mm DIA x 20mm DOWEL", "DOWEL, ø6mm x 20mm", "M6 x 20 DIA SCREW"):
        assert parts_list_row_role(text) == "part", text
    # and the square tube callout reads as it always did
    s = detect_section_stock("30.00 x 30.00 x 2.00mm TUBE 1532")
    assert s["profile_form"] == "SHS" and s["length_mm"] == 1532.0


def test_the_row_is_not_minted_and_becomes_the_tubes_own_stock():
    row = {"part_number": "", "description": "12.7mm DIA x 1.2mm WALL 50", "quantity": 1,
           "bom_parent": "50003-02-05M", "source_pdf": "50003-02-05M", "bom_parent_known": True,
           "bom_item_no": "1"}
    mint_uncoded_row_identities([row])
    assert not row["part_number"], "a stock line is not a part"
    assert row["row_role"] == "parent_cut_list"
    tube = {"part_number": "50003-02-05M", "description": "SIDE FIXING TUBE", "quantity": 6,
            "normalized_material": "MILD_STEEL", "review_flags": []}
    assert bp.apply_stated_cut_list_to_parts([tube], [row]) == 1
    ss = tube["section_stock"]
    assert (ss["a"], ss["t"], ss["length_mm"]) == (12.7, 1.2, 50.0), ss
    assert row.get("consumed") is True
