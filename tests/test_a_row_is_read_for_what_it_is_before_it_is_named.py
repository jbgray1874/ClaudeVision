"""D-383 — identity, after the adversarial review of D-379, D-380 and D-381 (12173-02 Card
Spinner, M&S).

1. D-381 named every codeless parts-list row with a word of three letters as a bought-in part.
   The two tube frames' own cut lists (12173-03-04M / 05M, "30.00 x 30.00 x 2.00mm TUBE 1532"
   x2, 290, 350) and the rail's section row ("10 x 30 x 1.50mm TUBE", 12173-05-01M) became
   BI-TUBE / BI-3000X3000... lines — tube already costed as the frames' 3,704 mm. A clash kept
   the row's figures ("BI-DOWEL8MMX30MM"), which the shape test then called a real code.
2. The stated-edging reader took EDGE alone with no left boundary (WEDGE, EDGE TRIM ...), and
   wrote "used for the banding" at stamp time, on any parent.
3. Bare MESH ruled a part bought on a word.
4. The catalogue made-part refusal read grade and standard tokens as drawing numbers, FRAME
   anywhere as a made form, refused silently, and let a piece within 10% price another length.
5. The frame's cut list rested only on the LLM's cut_lengths_mm, which could also clobber a
   deterministic reading.
6. D-379's alias flip moved a loose description match onto the printed code's price.
7. The label stripper's protected forms, and engine-derived identities, are pinned.

Synthetic minimal inputs throughout; the job is named only where it is the evidence.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bom_pipeline as bp                                             # noqa: E402
import bought_in_policy as bip                                        # noqa: E402
import document_builder as db                                         # noqa: E402
import edge_banding as eb                                             # noqa: E402
import estimator as e                                                 # noqa: E402
import route_compiler as rc                                           # noqa: E402
import source_precedence as sp                                        # noqa: E402
from part_identity import (is_category_split_identity,               # noqa: E402
                           is_engine_minted_code, is_engine_minted_record,
                           mint_uncoded_row_identities, parts_list_row_role,
                           strip_code_label)


def _row(desc, qty=1, parent="F-01M", code=""):
    return {"part_number": code, "description": desc, "quantity": qty, "bom_parent": parent,
            "bom_parent_known": True}


# ── 1. a codeless row is classified before it is named ──────────────────────────────────

def test_rows_are_classified_before_they_are_named():
    rows = [_row("30.00 x 30.00 x 2.00mm TUBE 1532"), _row("10 x 30 x 1.50mm TUBE"),
            _row("SEE NOTE 3"), _row("WELD ALL ROUND"), _row("POWDER COAT RAL9005"),
            _row("18mm MDF, 626 x 626"), _row("ABS EDGING 22mm WHITE"),
            _row("DOWEL, ø6mm x 20mm", 6), _row("LAZY SUSAN BEARING 300mm")]
    assert mint_uncoded_row_identities(rows) == 2
    assert [r["part_number"] for r in rows[:7]] == [""] * 7
    assert rows[7]["part_number"] == "BI-DOWEL" and rows[8]["part_number"].startswith("BI-")
    assert [r["row_role"] for r in rows[:7]] == [
        "parent_cut_list", "parent_cut_list", "instruction", "instruction", "instruction",
        "parent_material", "parent_banding"]


def test_a_row_that_names_a_thing_stays_a_part():
    for d in ("CHROME HANDLE", "GALVANISED BRACKET", "ACRYLIC LEAFLET HOLDER A4",
              "CAM LOCK ASSEMBLY", "ON/OFF SWITCH", "EDGE TRIM, ALUMINIUM, L: 2400mm",
              "WELDED MESH PANEL 50x50x3", "RAWLPLUG 6mm", "TBC SPACER BLOCK"):
        assert parts_list_row_role(d) == "part", d
    for d in ("TBC", "MILD STEEL", "18mm MR MDF", "WET SPRAY MATT BLACK", "FOLD UP 90°"):
        assert parts_list_row_role(d) != "part", d
    assert parts_list_row_role("626 x 626 x 25 mm") == "parent_size"


def test_a_clash_code_is_ours_by_its_record_not_its_shape():
    two = [_row("DOWEL, ø6mm x 20mm", 6), _row("DOWEL, ø8mm x 30mm", 4, "G-01M")]
    mint_uncoded_row_identities(two)
    assert two[1]["part_number"] == "BI-DOWEL8MMX30MM"
    assert not is_engine_minted_code("BI-DOWEL8MMX30MM")          # the shape cannot tell
    recs = db.bought_in_rows_without_records(two, [])
    assert len(recs) == 2 and all(is_engine_minted_record(r) for r in recs)
    assert all(r["identity_source"] == "uncoded_row" and r["is_bought_in"] for r in recs)


def test_the_explainer_calls_a_minted_clash_code_ours():
    import estimate_explained as ee
    bom_row = {"code": "BI-DOWEL8MMX30MM", "text": "BI-DOWEL8MMX30MM DOWEL", "price": None}
    record = {"BI-DOWEL8MMX30MM": {"part_number": "BI-DOWEL8MMX30MM",
                                   "identity_source": "uncoded_row", "price_origin": {}}}
    said = ee._price_source(bom_row, {}, record=record)
    assert "the one shown is ours" in said and "is a real code" not in said


def test_the_costed_line_carries_who_wrote_the_code():
    import costed_facts as cf
    src = {"estimate_summary": {"part_estimates": [
        {"part_number": "BI-DOWEL8MMX30MM", "quantity": 4, "identity_source": "uncoded_row",
         "description": "DOWEL, ø8mm x 30mm"},
        {"part_number": "FIXING-3.5-X12MM-PAN-HEAD", "quantity": 16, "printed_code": "FIXING",
         "description": "Ø3.5x12mm PAN HEAD SCREW"}]}}
    lines = cf.record_lines(src)
    assert is_engine_minted_record(lines["BI-DOWEL8MMX30MM"])
    assert is_category_split_identity(lines["FIXING-3.5-X12MM-PAN-HEAD"])


def test_what_no_reader_took_is_asked_on_the_parent():
    part = {"part_number": "F-01M", "section_stock": {"a": 40, "b": 40, "t": 3}}
    rows = [_row("18mm MDF, 626 x 626"), _row("TBC"), _row("WELD ALL ROUND"),
            _row("10 x 30 x 1.50mm TUBE")]
    mint_uncoded_row_identities(rows)
    bp.apply_stated_cut_list_to_parts([part], rows)
    assert bp.raise_unread_parts_list_rows([part], rows) == 3
    issues = " | ".join(q["issue"] for q in part["manufacturing_questions"])
    assert "names a material, '18mm MDF, 626 x 626'" in issues
    assert "reads only 'TBC'" in issues and "'10 x 30 x 1.50mm TUBE'" in issues
    assert any("WELD ALL ROUND" in f and "instruction" in f for f in part["review_flags"])
    # asked once, however often the pass runs
    assert bp.raise_unread_parts_list_rows([part], rows) == 0


# ── 2. a banding noun is a whole word, and the sentence is the consumer's ────────────────

def test_edge_alone_is_not_edging():
    for d in ("WEDGE, L: 50mm", "LEDGE SUPPORT, LENGTH 600mm", "EDGE TRIM, ALUMINIUM, L: 2400mm",
              "KNIFE EDGE LED STRIP L: 1200mm", "EDGE LIT ACRYLIC PANEL, L: 600mm",
              "PLEDGE CARD L: 210mm", "EDGE PROTECTOR L=1000MM"):
        assert eb.stated_edging_length_mm(d) is None, d
        assert not eb.is_banding_row(d), d
    for d, mm in (("EDGING, L: 1979mm", 1979), ("EDGING. L:1759mm", 1759),
                  ("ABS EDGING, L=2400mm", 2400), ("2mm ABS EDGING WHITE, L: 2400mm", 2400),
                  ("22 x 2mm EDGING, L: 1979mm", 1979), ("EDGE BANDING 22x2 L: 3000mm", 3000),
                  ("LIPPING L 500mm", 500)):
        assert eb.stated_edging_length_mm(d) == mm, d


def test_an_edge_trim_row_is_a_part_again():
    rows = [_row("EDGE TRIM, ALUMINIUM, L: 2400mm", parent="H-01M")]
    assert mint_uncoded_row_identities(rows) == 1


def test_the_stamp_writes_the_fact_and_no_sentence():
    p = [{"part_number": "B-01J"}]
    rows = [_row("EDGING, L: 500mm", parent="B-01J")]
    assert bp.apply_stated_edging_to_parts(p, rows) == 1
    assert p[0]["stated_banded_length_mm"] == 500
    assert not any("used for the banding" in f for f in p[0].get("review_flags") or [])
    assert rows[0]["consumed"] is True


def test_an_edging_row_with_no_length_says_banded_extent_unknown():
    p = {"part_number": "B-02J",
         "normalized_geometry": {"blank_length_mm": 600, "blank_width_mm": 400}}
    rows = [_row("ABS EDGING 22mm WHITE", parent="B-02J")]
    bp.apply_stated_edging_to_parts([p], rows)
    assert p["stated_banding_rows"] == ["ABS EDGING 22mm WHITE"]
    assert eb.banded_length_mm(p)["basis"] == "banding_stated_extent_unknown"


def test_a_stated_edging_on_a_part_not_banded_is_asked_by_the_estimator():
    p = {"part_number": "S-01M", "description": "PLATE", "normalized_material": "MILD_STEEL",
         "normalized_thickness_mm": 2.0, "stated_banded_length_mm": 500.0,
         "textual_operations": ["laser_cutting"],
         "normalized_geometry": {"blank_length_mm": 300, "blank_width_mm": 200}}
    e.estimate_process_times(p, 1)
    qs = [q["issue"] for q in p.get("manufacturing_questions") or []]
    assert any("states 500 mm of edging on S-01M, which is not edge-banded" in q for q in qs)


def test_a_lengthless_edging_row_on_a_part_not_banded_is_asked_too():
    p = {"part_number": "S-02M", "description": "PLATE", "normalized_material": "MILD_STEEL",
         "normalized_thickness_mm": 2.0, "stated_banding_rows": ["ABS EDGING 22mm WHITE"],
         "textual_operations": ["laser_cutting"],
         "normalized_geometry": {"blank_length_mm": 300, "blank_width_mm": 200}}
    e.estimate_process_times(p, 1)
    assert any("edging ('ABS EDGING 22mm WHITE') on S-02M" in q["issue"]
               for q in p.get("manufacturing_questions") or [])


def test_the_portal_path_runs_every_reader_and_the_question():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    i_cut = src.index("apply_stated_cut_list_to_parts(")
    i_edg = src.index("_n_edg = apply_stated_edging_to_parts(")
    i_ask = src.index("raise_unread_parts_list_rows(\n")
    assert i_cut < i_edg < i_ask
    assert src.index("apply_full_job_to_pre_estimate(_pre_estimate_parts") < i_cut


# ── 3. MESH asks; a compound product word rules ─────────────────────────────────────────

def test_mesh_alone_asks_and_rules_nothing():
    assert bip.purchased_stock_product({"part_number": "X-07M", "description": "MESH GUARD"}) == ""
    p = {"part_number": "X-04M", "description": "LOWER TIER MESH"}
    assert bip.purchased_stock_product(p) == "" and not bip.is_bought_in(p)
    q = bip.make_buy_question(p)
    assert q["word"] == "MESH" and q["ruled"] == ""
    assert bip.purchased_stock_product({"part_number": "X-11T",
                                        "description": "MDF MESH INFILL"}) == ""


def test_a_compound_word_rules_and_asks_unless_the_purchase_is_stated():
    w = {"part_number": "X-09M", "description": "WELDMESH PANEL 50x50x3", "wire_gauge_mm": 3,
         "material_family": "wire"}
    assert bip.purchased_stock_product(w) == "WELDMESH"
    assert bip.make_buy_question(w)["ruled"] == "bought"
    x = {"part_number": "X-10X", "description": "WELDMESH PANEL"}
    assert bip.purchased_stock_product(x) == "WELDMESH" and bip.make_buy_question(x) == {}
    s = {"part_number": "X-12M", "description": "WELDMESH PANEL", "supplier": "A Supplier"}
    assert bip.make_buy_question(s) == {}


def test_bend_callouts_on_its_own_sheet_say_we_form_it():
    own = {"part_number": "X-08M", "description": "WELDMESH GUARD", "drawing_bend_callouts": 2}
    assert bip.purchased_stock_product(own) == ""
    mirrored = {"part_number": "X-08M-H", "description": "WELDMESH GUARD"}
    sp.apply_field(mirrored, "drawing_bend_callouts", 2, "mirror_of_measured")
    assert bip.purchased_stock_product(mirrored) == "WELDMESH"


def test_the_estimator_asks_the_mesh_question_and_keeps_the_route():
    m = {"part_number": "X-04M", "description": "LOWER TIER MESH",
         "normalized_material": "MILD_STEEL",
         "textual_operations": ["wire_forming", "welding", "powder_coating"]}
    e.estimate_process_times(m, 1)
    assert {"wire_forming", "welding"} <= set(m["textual_operations"])
    q = next(q for q in m["manufacturing_questions"] if "bought ready-made" in q["issue"])
    assert "nothing is removed on the word MESH" in q["assumption"]


def test_the_route_gate_leaves_a_mesh_it_cannot_rule():
    from types import SimpleNamespace as NS
    d = NS(target_id="X-04M", operation="laser_cutting", scope="part", status=rc.REQUIRED,
           reason="", field_provenance={})
    rec = {"X-04M": {"part_number": "X-04M", "description": "LOWER TIER MESH",
                     "normalized_material": "MILD_STEEL"}}
    rc._family_gate([d], {}, rec)
    assert d.status == rc.REQUIRED


# ── 4. the catalogue refusal is narrower, said, and the length is exact ─────────────────

def test_grades_standards_and_a_frame_tube_are_stock():
    for c, d in (("ALU2525", "ALU BOX 25x25x2 6063-T6 @ 6000mm"),
                 ("SS2525", "SS 304-2B BOX 25x25x1.5 @ 6000mm"),
                 ("RHS4020", "RHS 40x20x2 S355 EN 10219-2 @ 7500mm"),
                 ("CHS25", "CHS 25.4 x 1.5 BS 6323-4 @ 6000mm"),
                 ("SHS30302", "SHS 30x30x2 FRAME TUBE @ 6000mm")):
        assert e._catalogue_row_is_a_made_part(c, d) == "", d
    assert "drawing number" in e._catalogue_row_is_a_made_part("11248-14", "L FRAME 30x30x2 @ 1395mm")
    assert "names drawing" in e._catalogue_row_is_a_made_part(
        "TUBE0071", "11087-17-08M /Tube Legs 30x30x2 @ 700mm")
    assert "made form" in e._catalogue_row_is_a_made_part("TT99", "SIDE FRAME 30x30x2")


def test_a_refused_row_is_named_and_only_the_exact_length_prices():
    ref = []
    rows = [("ALU3030", "SHS 30x30x2 6063-T6 @ 1532mm", 5.0, "S", "EA"),
            ("11248-14", "L FRAME 30x30x2 @ 1532mm", 9.0, "S", "EA")]
    best = e._select_catalogue_section_row(rows, 30, 30, 2, 1532, "F-01M", refused=ref)
    assert best["part_code"] == "ALU3030"
    assert ref == [{"code": "11248-14", "description": "L FRAME 30x30x2 @ 1532mm",
                    "why": "its code 11248-14 is a drawing number"}]
    assert e._select_catalogue_section_row(rows[:1], 30, 30, 2, 1395, "F-01M") is None
    assert e._select_catalogue_section_row(rows[:1], 30, 30, 2, 1532.6, "F-01M") is not None


def test_the_length_tolerance_is_config(monkeypatch):
    import config
    monkeypatch.setattr(config, "SECTION_CATALOGUE_LENGTH_TOLERANCE_MM", 200.0)
    rows = [("ALU3030", "SHS 30x30x2 @ 1532mm", 5.0, "S", "EA")]
    assert e._select_catalogue_section_row(rows, 30, 30, 2, 1395, "F-01M") is not None


# ── 5. the cut list is read off the part's own table ────────────────────────────────────

def _frame_rows(parent="F-01M"):
    return [_row(f"30.00 x 30.00 x 2.00mm TUBE {L}", parent=parent) for L in (1532, 1532, 290, 350)]


def test_the_parts_table_is_the_cut_list():
    rows = _frame_rows()
    parts = [{"part_number": "F-01M", "stated_weight_g": 5990}]
    assert bp.apply_stated_cut_list_to_parts(parts, rows) == 1
    ss = parts[0]["section_stock"]
    assert sorted(ss["cut_lengths_mm"]) == [290, 350, 1532, 1532]
    assert (ss["a"], ss["b"], ss["t"]) == (30, 30, 2)
    assert e._infer_section_length_mm(parts[0]) == 3704
    assert parts[0]["_section_length_reader_from"] == "drawing_deterministic"
    assert not any("weighs about" in f for f in parts[0].get("review_flags") or [])
    assert all(r["consumed"] is True and r["row_role"] == "parent_cut_list" for r in rows)
    # never minted, and never asked about
    assert mint_uncoded_row_identities(rows) == 0
    assert bp.raise_unread_parts_list_rows(parts, rows) == 0


def test_the_extract_does_not_clobber_the_table():
    from source_connectors import llm_full_job as lj
    parts = [{"part_number": "F-01M"}]
    bp.apply_stated_cut_list_to_parts(parts, _frame_rows())
    job = {"found": True, "parts": [{"part_number": "F-01M", "tube_section": "30x30x2",
                                     "cut_lengths_mm": [1532, 290]}]}
    lj.apply_full_job_to_pre_estimate(parts, job)
    assert sorted(parts[0]["section_stock"]["cut_lengths_mm"]) == [290, 350, 1532, 1532]
    assert e._infer_section_length_mm(parts[0]) == 3704


def test_the_table_disagreeing_with_the_extract_is_said():
    parts = [{"part_number": "F-01M"}]
    sp.apply_field(parts[0], "section_stock.cut_lengths_mm", [1532.0, 290.0], "llm_full_extract")
    bp.apply_stated_cut_list_to_parts(parts, _frame_rows())
    assert any("read 290, 1532 mm — the table is used" in f for f in parts[0]["review_flags"])


def test_a_stronger_cut_list_is_not_overwritten_or_mass_checked():
    parts = [{"part_number": "F-01M", "stated_weight_g": 2500}]
    sp.apply_field(parts[0], "section_stock.cut_lengths_mm", [1000.0, 1000.0], "solidworks_api")
    bp.apply_stated_cut_list_to_parts(parts, _frame_rows())
    assert parts[0]["section_stock"]["cut_lengths_mm"] == [1000.0, 1000.0]
    assert "length_indicative" not in parts[0]["section_stock"]
    assert not any("the table is used" in f for f in parts[0]["review_flags"])


def test_a_cut_list_far_from_the_stated_weight_is_indicative():
    parts = [{"part_number": "F-01M", "stated_weight_g": 2500}]
    bp.apply_stated_cut_list_to_parts(parts, _frame_rows())
    assert parts[0]["section_stock"]["length_indicative"] is True
    assert any("weighs about 6.51 kg" in f for f in parts[0]["review_flags"])


def test_two_sections_under_one_part_are_asked_not_summed():
    rows = [_row("30x30x2 SHS 500", parent="G-01M"),
            _row("40.00 x 20.00 x 2.00mm TUBE 500", parent="G-01M")]
    g = [{"part_number": "G-01M"}]
    assert bp.apply_stated_cut_list_to_parts(g, rows) == 0
    assert "sections" in g[0]["manufacturing_questions"][0]["issue"]
    assert "section_stock" not in g[0]


def test_a_coded_tube_row_is_a_bought_line_not_the_cut_list():
    rows = [_row("ERW RECT. 60 x 30 x 1.5mm TUBE 1125", parent="K-01M", code="SLOTTEDTUBE01")]
    k = [{"part_number": "K-01M"}]
    assert bp.apply_stated_cut_list_to_parts(k, rows) == 0
    assert "section_stock" not in k[0] and not rows[0].get("consumed")


def test_an_assemblys_uncoded_pieces_are_asked_not_costed_on_it():
    rows = _frame_rows("W-101")
    w = [{"part_number": "W-101", "is_assembly_parent": True}]
    assert bp.apply_stated_cut_list_to_parts(w, rows) == 0
    assert "section_stock" not in w[0]
    assert "is an assembly" in w[0]["manufacturing_questions"][0]["issue"]


def test_a_section_row_with_no_length_confirms_the_section_held():
    rail = {"part_number": "R-01M", "section_stock": {"a": 10, "b": 30, "t": 1.5,
                                                       "length_mm": 322}}
    rows = [_row("10 x 30 x 1.50mm TUBE", parent="R-01M")]
    bp.apply_stated_cut_list_to_parts([rail], rows)
    assert rows[0]["consumed"] is True
    assert bp.raise_unread_parts_list_rows([rail], rows) == 0


# ── 6. the alias flip needs the exact same item ─────────────────────────────────────────

def test_a_near_match_is_not_flipped_onto_the_printed_price():
    C = {"LOW068": {"description": "CASTOR WHEEL", "is_bought_in": True, "quantity": 2}}
    M = {"BI-CASTOR": {"description": "50mm BRAKED CASTOR WHEEL", "is_bought_in": True,
                       "quantity": 2}}
    assert rc._raw_identity_aliases(C, M) == {"LOW068": "BI-CASTOR"}
    assert any("may be one item" in f for f in C["LOW068"]["review_flags"])
    assert any("may be one item" in f for f in M["BI-CASTOR"]["review_flags"])


def test_the_same_item_spelled_two_ways_is_flipped():
    s = "Ø3.5x12mm PAN HEAD MULTI-PURPOSE SCREW"
    aliases = rc._raw_identity_aliases(
        {"FIXING0127": {"description": s, "is_bought_in": True, "quantity": 16}},
        {"BI-SCREW": {"description": "Ø3.5x12mm Pan Head Multi Purpose Screw",
                      "is_bought_in": True, "quantity": 16}})
    assert aliases == {"BI-SCREW": "FIXING0127"}
    # a count nobody stated is not a disagreement
    aliases = rc._raw_identity_aliases(
        {"FIXING0127": {"description": s, "is_bought_in": True, "quantity": 16}},
        {"BI-SCREW": {"description": s, "is_bought_in": True}})
    assert aliases == {"BI-SCREW": "FIXING0127"}


def test_different_counts_are_not_one_line():
    s = "Ø3.5x12mm PAN HEAD MULTI-PURPOSE SCREW"
    aliases = rc._raw_identity_aliases(
        {"FIXING0127": {"description": s, "is_bought_in": True, "quantity": 16}},
        {"BI-SCREW": {"description": s, "is_bought_in": True, "quantity": 8}})
    assert aliases == {"FIXING0127": "BI-SCREW"}


def test_a_split_identity_is_recognised_and_worded_as_one():
    rec = {"part_number": "FIXING-3.5-X12MM-PAN-HEAD", "printed_code": "FIXING"}
    assert is_category_split_identity(rec)
    assert not is_category_split_identity({"part_number": "FIXING125", "printed_code": ""})
    import estimate_explained as ee
    said = ee._price_source({"code": "FIXING-3.5-X12MM-PAN-HEAD", "text": "", "price": None},
                            {}, record={"FIXING-3.5-X12MM-PAN-HEAD": dict(rec, price_origin={})})
    assert "printed only the class word 'FIXING'" in said and "is a real code" not in said


# ── 7. the label stripper's protected forms ─────────────────────────────────────────────

def test_codes_joined_by_a_hyphen_keep_their_prefix():
    for c in ("FIXING-125", "PART-01", "ITEM-12", "FIXING-M6-WASHER",
              "FIXING-3.5-X12MM-PAN-HEAD", "FIXING 1180"):
        assert strip_code_label(c) == c, c
    for raw, code in (("VITAL PARTS: LOW068", "LOW068"), ("BOUGHT IN - LOW068", "LOW068"),
                      ("BOUGHT-IN: LOW068", "LOW068"), ("SUPPLIER: ABC123", "ABC123")):
        assert strip_code_label(raw) == code


def test_an_engine_derived_identity_is_never_relabelled():
    import file_scan as fs
    rows = fs._merge_truncated_bom_codes([{"part_number": "FIXING: 3.5-X12",
                                           "printed_code": "FIXING", "description": "X"}])
    assert rows[0]["part_number"] == "FIXING: 3.5-X12"
    rows = fs._merge_truncated_bom_codes([{"part_number": "FIXING: FIXING0127",
                                           "description": "Y"}])
    assert rows[0]["part_number"] == "FIXING0127"
