"""12173-02 Card Spinner — review of D-385 (b9463d4), 2 Oct 2026 (D-387).

The three fixes were the right faults; the rules were too strong or too weak:

* Weld. The leaf rule tested the decision's WINNING source, so a weld with drawing evidence of
  its own could be withheld; and it left the Dress Welds derived from a withheld weld
  chargeable ("override_rule" is not "inference"). Every claim and the record are read now;
  dressing follows the weld. A member stated WELDED only by its FINISH field, drawing no weld,
  under a welded assembly, is that assembly's joint — charged once (06-201, not 06-01M too).
* Powder. apply_finish_coats stamped every GA whose sheet named a coat: the top GA over MDF and
  MFC boards and a frame coated on its own sheet (3.111 m² of boards), the rack's parent beside
  its two self-coated sub-GAs. A coat applies where there is something to coat.
* Robomac. The hand rule read the base's op list, which carried the pack's note; it reads what
  the base IS (test_a_weld_needs_evidence_of_its_own).
* Price. A 30x30x2 frame fell to the config £/kg hold while SDI Live lists the profile as stock
  length: the catalogue's stock length of the exact profile is a real £/m.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bought_in_policy as bp                                         # noqa: E402
import costed_facts as cf                                             # noqa: E402
import estimator as e                                                 # noqa: E402
import route_compiler as rc                                           # noqa: E402
import weld_symbols as ws                                             # noqa: E402


# ── 1. weld evidence is every claim and the record, not the winning source ───────────────

def _dec(target, op, source="inference", claims=None, scope="part", status=None):
    return NS(target_id=target, operation=op, scope=scope, status=status or rc.REQUIRED,
              source=source, reason="", field_provenance={}, claims=claims or [])


def _claim(source, status=rc.REQUIRED):
    return {"source": source, "status": status, "reason": ""}


def _graph(records=None, children=None):
    nodes = [NS(part_number="A-201", kind="assembly"), NS(part_number="A-01M", kind="leaf"),
             NS(part_number="A-02M", kind="leaf")]
    return {"nodes": nodes, "parents": {"A-01M": {"A-201"}, "A-02M": {"A-201"}},
            "children": children or {"A-201": {"A-01M": 1, "A-02M": 1}},
            "records": records or {}, "raw": records or {}}


def test_a_weld_with_a_drawing_claim_behind_an_inference_winner_is_kept():
    d = _dec("A-01M", "welding", claims=[_claim("inference"), _claim("drawing_notes")])
    assert rc._withhold_evidenceless_leaf_welds([d], _graph(), []) == []
    assert d.status == rc.REQUIRED


def test_a_weld_the_sheet_draws_is_kept_whatever_the_decision_names():
    rec = {"A-01M": {"part_number": "A-01M", "weld_symbols": {"fillet": 2}}}
    d = _dec("A-01M", "welding")
    dress = _dec("A-01M", "dress_welds", source="override_rule")
    assert rc._withhold_evidenceless_leaf_welds([d, dress], _graph(rec), []) == []
    assert d.status == rc.REQUIRED and dress.status == rc.REQUIRED


def test_a_finish_welded_record_keeps_its_weld():
    rec = {"A-01M": {"part_number": "A-01M", "weld_stated_by_finish": True}}
    d = _dec("A-01M", "welding")
    rc._withhold_evidenceless_leaf_welds([d], _graph(rec), [])
    assert d.status == rc.REQUIRED
    rec = {"A-01M": {"part_number": "A-01M", "normalized_finish": "WELDED"}}
    d = _dec("A-01M", "welding")
    rc._withhold_evidenceless_leaf_welds([d], _graph(rec), [])
    assert d.status == rc.REQUIRED


def test_dressing_follows_the_weld_off_and_on():
    # The derived dressing is override_rule, not inference — D-385 left it chargeable.
    d = _dec("A-01M", "welding")
    dress = _dec("A-01M", "dress_welds", source="override_rule", claims=[_claim("override_rule")])
    issues = []
    got = rc._withhold_evidenceless_leaf_welds([d, dress], _graph(), issues)
    assert got == ["A-01M", "A-01M"]
    assert dress.status == rc.NOT_APPLICABLE and "follows the weld" in dress.reason
    assert dress.field_provenance["status"] == "evidenceless_leaf_weld_withheld"
    assert [i["operation"] for i in issues] == ["welding", "dress_welds"]
    # A dressing with no weld to dress, resting on an inference, dresses nothing.
    lone = _dec("A-02M", "dress_welds")
    rc._withhold_evidenceless_leaf_welds([lone], _graph(), [])
    assert lone.status == rc.NOT_APPLICABLE and "no weld to dress" in lone.reason
    # One with a note of its own is kept.
    noted = _dec("A-02M", "dress_welds", source="drawing_notes")
    rc._withhold_evidenceless_leaf_welds([noted], _graph(), [])
    assert noted.status == rc.REQUIRED


# ── 2. a member's FINISH: WELDED under a welded assembly is the assembly's joint ──────────

def test_a_member_stated_welded_only_by_its_finish_is_welded_at_its_assembly():
    rec = {"A-01M": {"part_number": "A-01M", "weld_stated_by_finish": True,
                     "normalized_finish": "WELDED", "weld_symbols": {}},
           "A-02M": {"part_number": "A-02M", "weld_stated_by_finish": True,
                     "weld_symbols": {"fillet": 2}}}
    asm = _dec("A-201", "welding", source="drawing_deterministic", scope="assembly")
    m1 = _dec("A-01M", "welding", source="drawing_deterministic")
    d1 = _dec("A-01M", "dress_welds", source="override_rule")
    m2 = _dec("A-02M", "welding", source="drawing_deterministic")
    issues = []
    got = rc._member_finish_weld_is_the_assemblys([asm, m1, d1, m2], _graph(rec), issues)
    assert got == ["A-01M"]
    assert m1.status == rc.NOT_APPLICABLE and d1.status == rc.NOT_APPLICABLE
    assert "charged once, on A-201" in m1.reason
    assert m1.field_provenance == {"status": "member_weld_is_the_assemblys", "weld_owner": "A-201"}
    assert m2.status == rc.REQUIRED           # draws its own fillets: a weld of its own (202/203)
    assert asm.status == rc.REQUIRED
    assert issues == [{"code": "member_weld_is_the_assemblys", "part": "A-01M",
                       "owner": "A-201", "finish": "WELDED"}]


def test_without_a_welded_assembly_or_with_a_models_claim_the_member_keeps_its_weld():
    rec = {"A-01M": {"part_number": "A-01M", "weld_stated_by_finish": True}}
    m1 = _dec("A-01M", "welding", source="drawing_deterministic")
    assert rc._member_finish_weld_is_the_assemblys([m1], _graph(rec), []) == []
    asm = _dec("A-201", "welding", scope="assembly")
    m1 = _dec("A-01M", "welding", source="drawing_deterministic",
              claims=[_claim("drawing_deterministic"), _claim("solidworks_api")])
    assert rc._member_finish_weld_is_the_assemblys([asm, m1], _graph(rec), []) == []
    assert m1.status == rc.REQUIRED


def test_apply_finish_welds_marks_the_statement():
    part = {"part_number": "A-01M"}
    ws.apply_finish_welds([part], {"A-01M": {"finish": "WELDED", "text": "", "counts": {}}})
    assert part["weld_stated_by_finish"] is True
    assert part["operation_sources"]["welding"] == "drawing_deterministic"


def test_the_moved_weld_is_a_question_with_nothing_charged():
    prov = {"status": "member_weld_is_the_assemblys", "weld_owner": "A-201"}
    shadow = {"product_root": "A-GA", "decisions": [
        {"target_id": "A-01M", "operation": "welding", "status": "not_applicable",
         "field_provenance": dict(prov)},
        {"target_id": "A-01M", "operation": "dress_welds", "status": "not_applicable",
         "field_provenance": dict(prov)}]}
    src = {"estimate_summary": {"canonical_route_shadow": shadow,
                                "part_estimates": [{"part_number": "A-01M", "quantity": 1}]}}
    ds = [d for d in cf.costed_job(src).get("decisions_required") or []
          if "beyond its joint to A-201" in str(d.get("issue"))]
    assert len(ds) == 1
    assert ds[0]["kind"] == "manufacturing_decision" and ds[0]["gbp_at_stake"] is None
    assert ds[0]["operations"] == ["dress_welds", "welding"]


# ── 3. through the compiler, in the production shape ─────────────────────────────────────

def _sheet(pn, **extra):
    p = {"part_number": pn, "quantity": 1, "normalized_material": "MILD STEEL",
         "normalized_thickness_mm": 1.5, "dxf_augmented": True,
         "normalized_geometry": {"blank_length_mm": 300, "blank_width_mm": 120,
                                 "geometry_source": "dxf_flat_pattern"},
         "textual_operations": ["laser_cutting"]}
    p.update(extra)
    return p


def _hook_assembly():
    """A welded hook assembly (its own fillets); a member stated WELDED by FINISH alone; a member
    with its own fillets; a sheet leaf whose only weld is the pack's inference, dressed too."""
    return [
        {"part_number": "H-201", "quantity": 1, "is_sub_assembly": True,
         "assembly_children": ["H-01M", "H-02M", "H-03M"],
         "textual_operations": ["welding"],
         "operation_sources": {"welding": "drawing_deterministic"},
         "weld_symbols": {"fillet": 3}, "normalized_finish": "POWDER COATED"},
        _sheet("H-01M", textual_operations=["laser_cutting", "welding"],
               operation_sources={"welding": "drawing_deterministic"},
               weld_stated_by_finish=True, normalized_finish="WELDED", weld_symbols={}),
        _sheet("H-02M", textual_operations=["laser_cutting", "welding"],
               operation_sources={"welding": "drawing_deterministic"},
               weld_symbols={"fillet": 2}, normalized_finish="RAW"),
        _sheet("H-03M", inferred_operations=["welding", "dress_welds"],
               operations=["laser_cutting", "welding", "dress_welds"], normalized_finish="RAW"),
    ]


def _decisions(parts, **kw):
    out = rc.compile_job_route(parts, known_assemblies=kw.pop("known", ["H-201"]), **kw)
    return [d if isinstance(d, dict) else d.__dict__ for d in out["decisions"]], out


def _of(ds, target, op):
    hits = [d for d in ds if d["target_id"] == target and d["operation"] == op]
    assert len(hits) == 1, (target, op, hits)
    return hits[0]


def test_the_hook_is_welded_once_and_the_sheet_leaf_is_asked_at_nothing():
    ds, out = _decisions(_hook_assembly())
    assert _of(ds, "H-201", "welding")["status"] == rc.REQUIRED
    moved = _of(ds, "H-01M", "welding")
    assert moved["status"] == rc.NOT_APPLICABLE
    assert moved["field_provenance"]["status"] == "member_weld_is_the_assemblys"
    assert moved["field_provenance"]["weld_owner"] == "H-201"
    assert _of(ds, "H-02M", "welding")["status"] == rc.REQUIRED        # its own fillets
    guessed = _of(ds, "H-03M", "welding")
    assert guessed["status"] == rc.NOT_APPLICABLE
    assert guessed["field_provenance"]["status"] == "evidenceless_leaf_weld_withheld"
    dressed = _of(ds, "H-03M", "dress_welds")
    assert dressed["status"] == rc.NOT_APPLICABLE and "follows the weld" in dressed["reason"]
    codes = [i.get("code") for i in out["issues"]]
    assert "member_weld_is_the_assemblys" in codes and "evidenceless_leaf_weld_withheld" in codes


def _spinner_like():
    """A top GA stated POWDER COATED over two boards, a self-coated frame and a screw; the frame
    holds a RAW steel member. The rack: a parent GA stated POWDER COATED over two sub-GAs each
    stated POWDER COATED on their own sheets, with RAW steel members and a fixing."""
    coat = {"textual_operations": ["powder_coating"],
            "operation_sources": {"powder_coating": "drawing_deterministic"},
            "normalized_finish": "POWDER COATED"}
    return [
        {"part_number": "G-GA", "quantity": 1, "is_assembly_parent": True,
         "assembly_children": ["G-201", "G-01J", "G-03J", "BI-SCREW"], **coat},
        {"part_number": "G-201", "quantity": 1, "is_sub_assembly": True,
         "assembly_children": ["G-04M"], **coat},
        _sheet("G-04M", normalized_finish="RAW"),
        {"part_number": "G-01J", "quantity": 2, "normalized_material": "MDF",
         "normalized_thickness_mm": 25, "textual_operations": ["cnc_routing", "wet_spray"],
         "normalized_geometry": {"blank_length_mm": 626, "blank_width_mm": 626,
                                 "geometry_source": "dxf_flat_pattern"}, "dxf_augmented": True},
        {"part_number": "G-03J", "quantity": 2, "normalized_material": "MFC",
         "normalized_thickness_mm": 18, "textual_operations": ["cnc_routing"],
         "normalized_geometry": {"blank_length_mm": 1470, "blank_width_mm": 288,
                                 "geometry_source": "dxf_flat_pattern"}, "dxf_augmented": True},
        {"part_number": "BI-SCREW", "quantity": 8, "description": "M4 X 12 PAN HEAD SCREW",
         "is_bought_in": True},
        {"part_number": "R-GA", "quantity": 1, "is_assembly_parent": True,
         "assembly_children": ["R-1-GA", "R-2-GA", "BI-SCREW"], **coat},
        {"part_number": "R-1-GA", "quantity": 1, "is_sub_assembly": True,
         "assembly_children": ["R-1-01M"], **coat},
        {"part_number": "R-2-GA", "quantity": 1, "is_sub_assembly": True,
         "assembly_children": ["R-2-01M"], **coat},
        _sheet("R-1-01M", normalized_finish="RAW"),
        _sheet("R-2-01M", normalized_finish="RAW"),
    ]


def test_a_coat_is_charged_where_there_is_something_to_coat():
    ds, out = _decisions(_spinner_like(), known=["G-GA", "G-201", "R-GA", "R-1-GA", "R-2-GA"])
    top = _of(ds, "G-GA", "powder_coating")
    assert top["status"] == rc.NOT_APPLICABLE
    assert top["field_provenance"]["status"] == "coat_with_nothing_to_coat"
    assert "G-01J (MDF, not metal)" in top["reason"] and "G-03J (MFC, not metal)" in top["reason"]
    assert "G-201 (a sub-assembly coated on its own sheet)" in top["reason"]
    assert "BI-SCREW (bought in)" in top["reason"]
    assert _of(ds, "G-201", "powder_coating")["status"] == rc.REQUIRED     # a RAW steel member
    assert _of(ds, "R-GA", "powder_coating")["status"] == rc.NOT_APPLICABLE
    assert _of(ds, "R-1-GA", "powder_coating")["status"] == rc.REQUIRED
    assert _of(ds, "R-2-GA", "powder_coating")["status"] == rc.REQUIRED
    assert [i["part"] for i in out["issues"] if i.get("code") == "coat_with_nothing_to_coat"] \
        == ["G-GA", "R-GA"]


def test_a_sub_assembly_without_a_coat_of_its_own_counts_through_its_members():
    parts = [
        {"part_number": "P-GA", "quantity": 1, "is_assembly_parent": True,
         "assembly_children": ["P-101"], "textual_operations": ["powder_coating"],
         "operation_sources": {"powder_coating": "drawing_deterministic"},
         "normalized_finish": "POWDER COATED"},
        {"part_number": "P-101", "quantity": 1, "is_sub_assembly": True,
         "assembly_children": ["P-01M"]},
        _sheet("P-01M", normalized_finish="RAW"),
    ]
    ds, _ = _decisions(parts, known=["P-GA", "P-101"])
    assert _of(ds, "P-GA", "powder_coating")["status"] == rc.REQUIRED


def test_a_member_repeating_the_products_finish_is_coated_as_the_assembly():
    # 7332-01-101 over its POWDER COATED panel: the panel charges no coat of its own, so the
    # weldment's coat is the only coat — it stands. A member charged on its own line does not.
    parts = [
        {"part_number": "W-101", "quantity": 1, "is_assembly_parent": True,
         "assembly_children": ["W-008"], "textual_operations": ["powder_coating"],
         "operation_sources": {"powder_coating": "drawing_deterministic"},
         "normalized_finish": "POWDER COATED"},
        _sheet("W-008", normalized_finish="POWDER COATED"),
    ]
    ds, _ = _decisions(parts, known=["W-101"])
    assert _of(ds, "W-101", "powder_coating")["status"] == rc.REQUIRED
    # The reader agrees: the panel is something to coat.
    ga = {"part_number": "W-101", "is_assembly_parent": True, "assembly_children": ["W-008"]}
    panel = {"part_number": "W-008", "normalized_material": "MILD STEEL"}
    by = {"W-101": {"finish": "POWDER COATED"}, "W-008": {"finish": "POWDER COATED"}}
    assert ws.apply_finish_coats([ga, panel], by) == ["W-101"]


def test_a_welded_assemblys_coat_is_never_stood_down_on_its_members_account():
    parts = [
        {"part_number": "F-201", "quantity": 1, "is_sub_assembly": True,
         "assembly_children": ["F-04M", "BI-NUT"],
         "textual_operations": ["powder_coating", "welding"],
         "operation_sources": {"powder_coating": "drawing_deterministic",
                               "welding": "drawing_deterministic"},
         "weld_symbols": {"fillet": 2}, "normalized_finish": "POWDER COATED"},
        _sheet("F-04M", textual_operations=["laser_cutting", "powder_coating"],
               operation_sources={"powder_coating": "drawing_deterministic"},
               normalized_finish="POWDER COATED"),
        {"part_number": "BI-NUT", "quantity": 4, "description": "M6 NUT", "is_bought_in": True},
    ]
    ds, _ = _decisions(parts, known=["F-201"])
    assert _of(ds, "F-201", "powder_coating")["status"] != rc.NOT_APPLICABLE \
        or _of(ds, "F-201", "powder_coating")["field_provenance"].get("status") \
        != "coat_with_nothing_to_coat"


# ── 4. the reader stamps a coat only where there is something to coat ─────────────────────

def _spinner_records():
    ga = {"part_number": "G-GA", "is_assembly_parent": True,
          "assembly_children": ["G-201", "G-01J", "G-03J", "BI-SCREW"]}
    frame = {"part_number": "G-201", "is_sub_assembly": True, "assembly_children": ["G-04M"]}
    steel = {"part_number": "G-04M", "normalized_material": "MILD STEEL"}
    mdf = {"part_number": "G-01J", "normalized_material": "MDF"}
    mfc = {"part_number": "G-03J", "normalized_material": "MFC"}
    screw = {"part_number": "BI-SCREW", "is_bought_in": True, "description": "M4 SCREW"}
    by = {"G-GA": {"finish": "POWDER COATED - MATT", "text": "", "counts": {}},
          "G-201": {"finish": "POWDER COATED", "text": "", "counts": {}},
          "G-04M": {"finish": "RAW", "text": "", "counts": {}},
          "G-01J": {"finish": "WET SPRAYED - MATT", "text": "", "counts": {}}}
    return [ga, frame, steel, mdf, mfc, screw], by


def test_the_top_ga_over_boards_and_a_coated_frame_is_not_coated_again():
    parts, by = _spinner_records()
    ga, frame = parts[0], parts[1]
    assert ws.apply_finish_coats(parts, by) == ["G-201"]
    assert "powder_coating" in frame["textual_operations"]
    assert "powder_coating" not in (ga.get("textual_operations") or [])
    why = ga["operations_ruled_out"]["powder_coating"]
    assert why.startswith("nothing on G-GA to coat")
    assert "G-01J (MDF, not metal)" in why and "G-03J (MFC, not metal)" in why
    assert "G-201 (a sub-assembly coated on its own sheet)" in why
    assert "BI-SCREW (bought in)" in why
    assert ga["normalized_finish"] == "POWDER COATED - MATT"      # the stated finish is kept


def test_the_rack_parent_over_two_coated_sub_gas_is_not_coated_again():
    parent = {"part_number": "R-GA", "is_assembly_parent": True,
              "assembly_children": ["R-1-GA", "R-2-GA", "BI-FIX"]}
    s1 = {"part_number": "R-1-GA", "is_sub_assembly": True, "assembly_children": ["R-1-01M"]}
    s2 = {"part_number": "R-2-GA", "is_sub_assembly": True, "assembly_children": ["R-2-01M"]}
    m1 = {"part_number": "R-1-01M", "normalized_material": "MILD STEEL"}
    m2 = {"part_number": "R-2-01M", "normalized_material": "MILD STEEL"}
    fix = {"part_number": "BI-FIX", "is_bought_in": True, "description": "M6 BOLT"}
    by = {"R-GA": {"finish": "POWDER COATED"}, "R-1-GA": {"finish": "POWDER COATED"},
          "R-2-GA": {"finish": "POWDER COATED - MATT"}, "R-1-01M": {"finish": "RAW"},
          "R-2-01M": {"finish": "RAW"}}
    assert sorted(ws.apply_finish_coats([parent, s1, s2, m1, m2, fix], by)) == ["R-1-GA", "R-2-GA"]
    assert "powder_coating" in parent["operations_ruled_out"]
    assert "textual_operations" not in m1                       # leaves are the readers' business


def test_a_wet_sprayed_board_assembly_and_an_assembly_whose_members_are_unseen_are_stamped():
    base = {"part_number": "C-01J", "assembly_children": ["C-01J-01", "C-01J-02"]}
    pieces = [{"part_number": "C-01J-01", "normalized_material": "MDF"},
              {"part_number": "C-01J-02", "normalized_material": "MDF"}]
    assert ws.apply_finish_coats([base] + pieces, {"C-01J": {"finish": "WET SPRAYED - MATT"}}) \
        == ["C-01J"]
    assert base["textual_operations"] == ["wet_spray"]           # a board is sprayed, not ovened
    unseen = {"part_number": "U-GA", "is_assembly_parent": True, "assembly_children": ["U-01M"]}
    assert ws.apply_finish_coats([unseen], {"U-GA": {"finish": "POWDER COATED"}}) == ["U-GA"]


# ── 5. the coated area never includes a board ────────────────────────────────────────────

def test_the_members_area_leaves_the_boards_out():
    asm = {"part_number": "G-GA", "quantity": 1, "textual_operations": ["powder_coating"],
           "assembly_children": ["G-04M", "G-01J"]}
    steel = {"part_number": "G-04M", "quantity": 1, "normalized_material": "MILD STEEL",
             "blank_length_mm": 1000, "blank_width_mm": 500,
             "normalized_geometry": {"blank_length_mm": 1000, "blank_width_mm": 500}}
    board = {"part_number": "G-01J", "quantity": 1, "normalized_material": "MDF",
             "blank_length_mm": 626, "blank_width_mm": 626,
             "normalized_geometry": {"blank_length_mm": 626, "blank_width_mm": 626}}
    assert e.stamp_members_coated_area([asm, steel, board]) == 1
    assert abs(asm["_powder_members_coated_m2"] - 1.0) < 1e-6
    assert asm["_powder_members"] == ["G-04M x1"]
    assert asm["_powder_members_left_out"] == ["G-01J (MDF)"]
    assert "not counted, not metal: G-01J (MDF)" in asm["review_flags"][-1]


# ── 6. a hand that names its base and holds a blank is a measured flat ───────────────────

def test_a_mirrored_hand_is_measured_whatever_its_node_source_is_called():
    hand = {"part_number": "X-02M-H", "dxf_measured_outline": False,
            "normalized_geometry": {"blank_length_mm": 280.97, "blank_width_mm": 159.24,
                                    "geometry_source": "dxf_flat_pattern",
                                    "mirrored_from": "X-02M"}}
    assert bp.has_fabrication_evidence(hand) is True
    bare = {"part_number": "X-03M-H", "dxf_measured_outline": False,
            "normalized_geometry": {"mirrored_from": "X-03M"}}
    assert bp.has_fabrication_evidence(bare) is False


# ── 7. a stock length of the exact profile is a real rate ────────────────────────────────

ROWS = [("11248-14", "L FRAME 30x30x2 TUBE @ 1395mm", 6.70, "Top Tubes", "EA"),
        ("SHS30302-75", "SHS 30 X 30 X 2 X 7500MM", 45.00, "Top Tubes", "EA"),
        ("BOX30302-6", "BOX SECTION 30x30x2 6M", 36.00, "Preferred Tubes Ltd", "EA"),
        ("SHS30302-M", "SHS 30x30x2mm", 6.50, "Steel Co", "M"),
        ("SLOTTEDTUBE01", "ERW RECT. 60 x 30 x 1.5mm @ 1125mm", 3.57, "Preferred Tubes Ltd", "EA")]


def test_the_stock_lengths_of_the_profile_give_one_rate_and_the_made_part_is_refused():
    refused = []
    got = e._select_catalogue_section_stock_rate(ROWS, 30, 30, 2, "F-04M", refused=refused)
    assert got and got["rate_gbp_per_m"] == 6.0                 # median of 6.0, 6.0, 6.5
    assert [r["part_code"] for r in got["rows"]] == ["BOX30302-6", "SHS30302-75", "SHS30302-M"]
    assert got["rows"][0]["catalogue_length_mm"] == 6000 and got["rows"][2]["catalogue_length_mm"] is None
    assert got["suppliers"] == ["Preferred Tubes Ltd", "Steel Co", "Top Tubes"]
    assert [r["code"] for r in refused] == ["11248-14"]
    # A cut piece is not a stock length, and another profile is another item.
    assert e._select_catalogue_section_stock_rate(ROWS, 60, 30, 1.5) is None
    assert e._select_catalogue_section_stock_rate(ROWS[:1], 30, 30, 2, "F-04M") is None


def test_the_frame_is_priced_from_the_stock_length_before_the_config_hold(monkeypatch):
    monkeypatch.setattr(e, "_fetch_catalogue_section_rows", lambda: list(ROWS))
    part = {"part_number": "F-04M", "description": "FRAME", "quantity": 2,
            "normalized_material": "MILD STEEL",
            "section_stock": {"a": 30, "b": 30, "t": 2, "length_mm": 1532,
                              "cut_lengths_mm": [1532, 1532, 290, 350], "profile_form": "SHS"}}
    me = e.estimate_part(part, job_quantity=1)["material_estimate"]
    assert me["cost_method"] == "catalogue_section_stock_length_rate"
    assert me["rate_gbp_per_m"] == 6.0
    assert abs(me["unit_material_cost_gbp"] - round(3.704 * 6.0 * 1.04, 2)) < 0.011
    assert me["waste_included"] is True
    assert [r["part_code"] for r in me["stock_estimate"]["catalogue_rows"]] \
        == ["BOX30302-6", "SHS30302-75", "SHS30302-M"]
    assert me["price_source"]["section_profile_mm"] == {"a": 30, "b": 30, "t": 2}
    assert any("from SDI Live's stock lengths of this profile" in f for f in part["review_flags"])
    assert any("11248-14" in f and "was not used" in f for f in part["review_flags"])


def test_with_no_stock_length_the_config_hold_still_prices_and_says_so(monkeypatch):
    monkeypatch.setattr(e, "_fetch_catalogue_section_rows", lambda: [ROWS[0], ROWS[4]])
    part = {"part_number": "F-04M", "description": "FRAME", "quantity": 1,
            "normalized_material": "MILD STEEL",
            "section_stock": {"a": 30, "b": 30, "t": 2, "length_mm": 1532, "profile_form": "SHS"}}
    me = e.estimate_part(part, job_quantity=1)["material_estimate"]
    assert me["cost_method"] in ("section_stock_config_rate", "section_stock_flat_rate")
