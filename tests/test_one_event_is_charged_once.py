"""One piece of work is charged once, however many readings describe it (D-685).

12693-01-GA's 4 Nov 17:16 book is a table: a frame weldment 101 (a tube frame 01M and four
plates 02M, with four M8 hank bushes), and a worktop assembly 102 (the worktop weldment 104,
an MDF insert 04J and eight wood inserts). Its Estimate sheet charged the same work more than
once, in three places, and the run's own "BOMs & Routes" tab showed how:

  1. 101 HAD TWO Assemble/pack (Metal) ROWS, each 75/hr with a 15-minute set-up and each
     "general assembly and pack". The tab printed ONE route line for (101, assembly), "times
     decided = 2", and said "charged, but no sheet row carries this decision id". Three
     defects: the extract read the GA's note ("BOLTED TOGETHER FROM UNDERSIDE") as one assembly
     line naming 101 and 102, and the compiler split it into a build of each from its own
     members, so the frame, which its weld builds, took an assemble row on a GA note; every
     reading of an assemble was an event of its own, so two readings were two rows (D-397
     already pools two readings of one JOINT); and the tab looked the line's ids up as one
     joined string, which no row carries. The second 101 row named only the hank bushes, the
     same four the hardware insertion row on 101 already presses.

  2. 01M HAD A WELD ROW OF ITS OWN beside 101's. Not a double charge: 01M's own sheet draws
     four fillets and its own parts table lists its ten tube lengths, so it is welded from its
     pieces before it is welded into 101, and D-566 charges those joints beside the parent's
     on purpose. The defect was the question beside it: it asked whether that line "charges
     it a second time", saying the weld-symbol reading did not settle it, when the reading had.
     A member with no weld evidence of its own is still not charged (D-385); one with a fillet
     but no pieces of its own is still asked.

  3. 04J HAD A Packing Joinery ROW, and 104 an Assemble/pack row, from one inferred line whose
     reason was "the wrap line against the worktop ... this line is the fit, not a second
     fold". It named 104, 04J and the wood inserts, the members of 102, and the same split
     charged an assemble on the weldment 104 and a fitting on the insert. 102's own assembly
     fits both. A weldment's fit-up is its weld (the hierarchy gives a welded sub-assembly no
     assemble of its own), and that line was never about the fit-up.

Every fixture below is synthetic (12999-01); nothing reads a customer's pack.
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts  # noqa: E402
import route_compiler as rc  # noqa: E402
import wb_populate  # noqa: E402

J = "12999-01"
GA, FRAME, TUBE, PLATE = f"{J}-GA", f"{J}-101", f"{J}-01M", f"{J}-02M"
WORKTOP, SKIN_WELD, SKIN, TAB, INSERT = f"{J}-102", f"{J}-104", f"{J}-03M", f"{J}-07M", f"{J}-04J"
BUSH, WOOD, GLIDE, SCREW = "FIX-BUSH", "FIX-WOOD", "FIX-GLIDE", "FIX-SCREW"
ASSEMBLIES = [GA, FRAME, WORKTOP, SKIN_WELD]


def _table(routes):
    """The table's shape: a welded frame and a worktop assembly under one GA."""
    parts = [
        {"part_number": GA, "description": "TABLE", "is_assembly_parent": True,
         "assembly_children": [FRAME, WORKTOP, GLIDE, SCREW]},
        {"part_number": FRAME, "description": "TABLE FRAME WELDMENT", "is_assembly_parent": True,
         "assembly_children": [TUBE, PLATE, BUSH], "normalized_material": "MILD STEEL",
         "textual_operations": ["welding"],
         "operation_sources": {"welding": "drawing_deterministic"}},
        # The tube frame: its own sheet draws four fillets and lists its own tube lengths.
        {"part_number": TUBE, "description": "FRAME TUBE", "normalized_material": "MILD STEEL",
         "weld_symbols": {"fillet": 4}, "weld_symbol_pages": [1],
         "textual_operations": ["welding"],
         "operation_sources": {"welding": "drawing_deterministic"},
         "operation_scope": {"welding": "assembly"},
         "section_stock": {"a": 25, "b": 25, "t": 1.5,
                           "cut_lengths_mm": [1000, 775, 775, 487]}},
        {"part_number": PLATE, "description": "BASE FRAME SIDE", "quantity": 4,
         "normalized_material": "MILD STEEL"},
        {"part_number": BUSH, "description": "M8 HANK BUSH", "quantity": 4, "is_bought_in": True},
        {"part_number": WORKTOP, "description": "WORKTOP ASM", "is_assembly_parent": True,
         "assembly_children": [SKIN_WELD, INSERT, WOOD]},
        {"part_number": SKIN_WELD, "description": "WORKTOP WELDMENT", "is_assembly_parent": True,
         "assembly_children": [SKIN, TAB], "normalized_material": "MILD STEEL"},
        {"part_number": SKIN, "description": "TABLE TOP", "normalized_material": "MILD STEEL"},
        {"part_number": TAB, "description": "EDGE SUPPORT", "quantity": 20,
         "normalized_material": "MILD STEEL"},
        {"part_number": INSERT, "description": "TOP INSERT", "normalized_material": "MDF"},
        {"part_number": WOOD, "description": "M6 WOOD INSERT", "quantity": 8,
         "is_bought_in": True},
        {"part_number": GLIDE, "description": "M8 GLIDE", "quantity": 4, "is_bought_in": True},
        {"part_number": SCREW, "description": "M6 BUTTON HEAD SCREW", "quantity": 8,
         "is_bought_in": True},
    ]
    job = {
        "top_assembly": {"part_number": GA},
        "assemblies": [
            {"part_number": GA, "children": [{"part_number": FRAME, "qty": 1},
                                             {"part_number": WORKTOP, "qty": 1},
                                             {"part_number": GLIDE, "qty": 4},
                                             {"part_number": SCREW, "qty": 8}]},
            {"part_number": FRAME, "children": [{"part_number": TUBE, "qty": 1},
                                                {"part_number": PLATE, "qty": 4},
                                                {"part_number": BUSH, "qty": 4}]},
            {"part_number": WORKTOP, "children": [{"part_number": SKIN_WELD, "qty": 1},
                                                  {"part_number": INSERT, "qty": 1},
                                                  {"part_number": WOOD, "qty": 8}]},
            {"part_number": SKIN_WELD, "children": [{"part_number": SKIN, "qty": 1},
                                                    {"part_number": TAB, "qty": 20}]},
        ],
        "routes": list(routes),
    }
    return parts, job


WELDS = [
    {"operation": "welding", "part_numbers": [TUBE, PLATE], "scope": "assembly", "sequence": 40},
    {"operation": "welding", "part_numbers": [SKIN, TAB], "scope": "assembly",
     "target_id": SKIN_WELD, "sequence": 40},
]
GA_NOTE = {"operation": "assembly", "part_numbers": [FRAME, WORKTOP], "scope": "assembly",
           "sequence": 60, "notes": "GA note: frame and worktop bolted together from underside"}
GA_INFERRED = {"operation": "assembly", "part_numbers": [GLIDE, SCREW], "scope": "assembly",
               "target_id": GA, "sequence": 100, "inferred": True,
               "notes": "one assembly, including pack"}
THE_FIT = {"operation": "assembly", "part_numbers": [SKIN_WELD, INSERT, WOOD],
           "scope": "assembly", "sequence": 92, "inferred": True,
           "notes": "the wrap line against the worktop; this line is the fit, not a second fold"}
BUSHES = {"operation": "assembly", "part_numbers": [BUSH], "scope": "assembly",
          "target_id": FRAME, "sequence": 95, "inferred": True,
          "notes": "the glides need a thread in the frame; booked once for the frame"}


def _compile(routes):
    parts, job = _table(routes)
    return rc.compile_job_route(parts, job, known_assemblies=ASSEMBLIES)


def _required(out, op, target=None):
    return [d for d in out["decisions"] if d["operation"] == op and d["status"] == "required"
            and (target is None or d["target_id"] == target)]


def _codes(out, code):
    return [i for i in out["issues"] if i.get("code") == code]


# ── 1 and 3: an assembly line that names things side by side is where they meet ─────────────

def test_a_line_naming_two_sub_assemblies_is_their_joining_at_the_assembly_that_holds_them():
    out = _compile(WELDS + [GA_NOTE])
    ga = _required(out, "assembly", GA)
    assert len(ga) == 1 and set(ga[0]["participants"]) >= {FRAME, WORKTOP}, ga
    # The welded frame takes no assemble from a note printed on the GA.
    assert _required(out, "assembly", FRAME) == []
    assert _codes(out, "assembly_route_homed_where_its_parts_meet")


def test_the_fit_line_is_the_worktops_assembly_not_the_weldments_or_the_inserts():
    out = _compile(WELDS + [THE_FIT])
    worktop = _required(out, "assembly", WORKTOP)
    assert len(worktop) == 1, worktop
    assert {SKIN_WELD, INSERT, WOOD} <= set(worktop[0]["participants"])
    # The weldment's fit-up is its weld: no assemble of its own from a line about the fit.
    assert _required(out, "assembly", SKIN_WELD) == []
    # And the insert is fitted by the worktop's assembly, not charged a fitting of its own.
    assert _required(out, "assembly", INSERT) == []
    assert _required(out, "assembly", WOOD) == []


def test_a_line_naming_one_assembly_is_still_that_assemblys_build():
    # Unchanged: the substitution of an assembly's members is right when it is named alone.
    out = _compile(WELDS + [{"operation": "assembly", "part_numbers": [WORKTOP],
                             "scope": "assembly", "sequence": 60}])
    worktop = _required(out, "assembly", WORKTOP)
    assert len(worktop) == 1 and set(worktop[0]["participants"]) == {SKIN_WELD, INSERT, WOOD}
    assert _codes(out, "assembly_route_homed_where_its_parts_meet") == []


def test_a_coat_line_still_splits_into_the_objects_in_the_booth():
    # The re-homing is the assemble's. A weldment and a loose part are two objects in the
    # booth, and a coat line naming both keeps a decision on each.
    out = _compile(WELDS + [{"operation": "powder_coating", "part_numbers": [FRAME, INSERT],
                             "scope": "assembly", "sequence": 70}])
    coated = {d["target_id"] for d in out["decisions"] if d["operation"] == "powder_coating"}
    assert {FRAME, INSERT} <= coated, coated
    assert _codes(out, "assembly_route_homed_where_its_parts_meet") == []


# ── 1: two readings of one assemble at one visit are one event ───────────────────────────────

def test_two_readings_of_the_gas_assemble_are_one_event_with_both_kept_as_evidence():
    out = _compile(WELDS + [GA_NOTE, GA_INFERRED])
    ga = _required(out, "assembly", GA)
    assert len(ga) == 1, [(d["decision_id"], d["reason"]) for d in ga]
    # The union of what each reading named, and both readings on the decision.
    assert {FRAME, WORKTOP, GLIDE, SCREW} <= set(ga[0]["participants"])
    assert {c["source"] for c in ga[0]["claims"]} >= {"llm_full_extract", "inference"}
    pools = _codes(out, "assembly_readings_pooled_on_target")
    assert pools and pools[0]["assembly"] == GA and pools[0]["into"] == ga[0]["decision_id"]


def _visits(stop=None):
    """Two readings of the frame's assemble, before and after something else on the frame."""
    routes = WELDS + [
        {"operation": "assembly", "part_numbers": [TUBE, PLATE], "scope": "assembly",
         "target_id": FRAME, "sequence": 50, "notes": "assemble before the coat"},
        {"operation": "assembly", "part_numbers": [TUBE, PLATE], "scope": "assembly",
         "target_id": FRAME, "sequence": 90, "notes": "final assembly after the coat"}]
    if stop:
        routes.append(stop)
    return _compile(routes)


def test_two_visits_with_a_coat_between_them_stay_two():
    out = _visits({"operation": "powder_coating", "part_numbers": [FRAME], "scope": "assembly",
                   "target_id": FRAME, "sequence": 70})
    assert len(_required(out, "assembly", FRAME)) == 2


def test_two_readings_with_nothing_between_them_are_one_visit():
    # The frame's weld is at 40, before both; nothing takes it off the bench between 50 and 90.
    out = _visits()
    assert len(_required(out, "assembly", FRAME)) == 1


def test_a_trip_the_route_does_not_place_keeps_two_readings_apart():
    # The plater trip has no sequence: nothing here can show the two readings are one visit.
    out = _visits({"operation": "plater_pack", "part_numbers": [FRAME], "scope": "part",
                   "target_id": FRAME})
    assert len(_required(out, "assembly", FRAME)) == 2


def test_the_pooled_assemble_is_one_workbook_row_carrying_its_decision_id():
    # Both readings name the GA outright, so before D-685 they were two events and the sheet
    # keyed each assembly-scoped event to a row of its own.
    out = _compile(WELDS + [dict(GA_NOTE, target_id=GA), GA_INFERRED])
    payload = {"nodes": out["nodes"], "decisions": out["decisions"], "issues": out["issues"],
               "top_assembly": GA, "top_assemblies": [GA]}
    summary = {"canonical_route_shadow": payload,
               "estimate_summary": {"canonical_route_shadow": payload}}
    estimates = [{"part_number": pn, "normalized_material": "MILD STEEL", "quantity": 1,
                  "material_estimate": {"material": "MILD STEEL"}}
                 for pn in (GA, FRAME, TUBE, PLATE, WORKTOP, SKIN_WELD, SKIN, TAB)]
    groups = wb_populate.canonical_labour_groups(summary, estimates, 1)
    on_ga = [g for g in groups.values()
             if "assembly" in (g.get("engine_ops") or []) and GA in (g.get("targets") or [])]
    assert len(on_ga) == 1, [g.get("group_key") for g in on_ga]
    assert on_ga[0]["decision_ids"] == [_required(out, "assembly", GA)[0]["decision_id"]]


# ── 1: an inferred assemble naming only what the insertion fits ──────────────────────────────

def test_an_inferred_assemble_of_the_inserted_bushes_on_a_welded_frame_is_the_insertion():
    out = _compile(WELDS + [BUSHES])
    assert _required(out, "hardware_insertion", FRAME), "the bushes are pressed once"
    ruled = [d for d in out["decisions"] if d["operation"] == "assembly"
             and d["target_id"] == FRAME]
    assert ruled and all(d["status"] == "not_applicable" for d in ruled), ruled
    assert "fitted by the hardware insertion" in ruled[0]["reason"]


def test_a_stated_assemble_of_the_bushes_is_left_as_it_is():
    stated = dict(BUSHES)
    stated.pop("inferred")
    out = _compile(WELDS + [stated])
    assert len(_required(out, "assembly", FRAME)) == 1


def test_an_assemble_on_an_assembly_its_weld_does_not_build_is_left_as_it_is():
    # The worktop is not welded: whatever the bushes, its members still have to be put on.
    routes = WELDS + [{"operation": "assembly", "part_numbers": [WOOD], "scope": "assembly",
                       "target_id": WORKTOP, "sequence": 95, "inferred": True}]
    parts, job = _table(routes)
    for p in parts:
        if p["part_number"] == WOOD:
            p["description"] = "M6 PEM STUD"      # pressed, so the BOM raises an insertion
    out = rc.compile_job_route(parts, job, known_assemblies=ASSEMBLIES)
    assert len(_required(out, "assembly", WORKTOP)) == 1


def test_a_weld_the_family_gate_rules_off_builds_nothing():
    # A timber worktop carrying a transcribed weld word: the gate rules the weld off, so the
    # worktop is not "built by its weld", and an assemble naming its inserted studs stands.
    routes = WELDS + [
        {"operation": "assembly", "part_numbers": [WOOD], "scope": "assembly",
         "target_id": WORKTOP, "sequence": 95, "inferred": True},
        {"operation": "hardware_insertion", "part_numbers": [WOOD], "scope": "assembly",
         "target_id": WORKTOP, "sequence": 18}]
    parts, job = _table(routes)
    for p in parts:
        if p["part_number"] == WOOD:
            p["description"] = "M6 PEM STUD"
        if p["part_number"] == WORKTOP:
            p.update({"normalized_material": "MDF", "inferred_operations": ["welding"]})
    out = rc.compile_job_route(parts, job, known_assemblies=ASSEMBLIES)
    assert _required(out, "welding", WORKTOP) == [], "the gate rules the timber weld off"
    assert _required(out, "hardware_insertion", WORKTOP)
    assert len(_required(out, "assembly", WORKTOP)) == 1


def test_a_rehomed_line_takes_the_meeting_assemblys_own_count():
    # "qty 2" counted the frame and the worktop; they are bolted together once per table.
    out = _compile(WELDS + [dict(GA_NOTE, qty_per_unit=2)])
    ga = _required(out, "assembly", GA)
    assert len(ga) == 1 and ga[0]["qty_per_unit"] == 1.0, ga


# ── 2: a member weld is charged on its own evidence, and the question says what was read ─────

def test_a_member_welded_from_its_own_pieces_keeps_its_weld_and_is_not_asked_as_a_repeat():
    out = _compile(WELDS)
    assert _required(out, "welding", FRAME), "the parent's joint stands"
    own = _required(out, "welding", TUBE)
    assert len(own) == 1, "the tube frame's own joints stand beside it (D-566)"
    reason = own[0]["reason"]
    assert "This line is" in reason and "own sheet draws the welds that join them" in reason
    assert "second time" not in reason and "BOTH ARE CHARGED" not in reason
    assert own[0]["field_provenance"]["review"] == "joining_member_is_a_weldment_of_its_own"
    assert not [i for i in _codes(out, "joining_charged_on_assembly_and_member")
                if i.get("member") == TUBE]


def test_a_member_with_a_drawn_weld_but_no_pieces_of_its_own_is_still_asked():
    # No route names the plate, so its own drawn weld is its own event; it holds no pieces, so
    # nothing tells its fillet from the parent's joint, and both are charged and asked.
    parts, job = _table([])
    for p in parts:
        if p["part_number"] == PLATE:
            p.update({"weld_symbols": {"fillet": 2}, "weld_symbol_pages": [1],
                      "textual_operations": ["welding"],
                      "operation_sources": {"welding": "drawing_deterministic"}})
    out = rc.compile_job_route(parts, job, known_assemblies=ASSEMBLIES)
    plate = _required(out, "welding", PLATE)
    assert plate and "BOTH ARE CHARGED" in plate[0]["reason"]
    assert [i for i in _codes(out, "joining_charged_on_assembly_and_member")
            if i.get("member") == PLATE]


def test_a_member_with_no_weld_evidence_of_its_own_is_not_charged_beside_its_parent():
    # D-385, pinned here beside the rest: an inferred weld on a leaf whose own sheet gives none
    # is the parent's joint, charged there.
    parts, job = _table([])
    for p in parts:
        if p["part_number"] == PLATE:
            p.update({"inferred_operations": ["welding"]})
    out = rc.compile_job_route(parts, job, known_assemblies=ASSEMBLIES)
    assert _required(out, "welding", FRAME)
    assert _required(out, "welding", PLATE) == []
    plate = [d for d in out["decisions"] if d["operation"] == "welding"
             and d["target_id"] == PLATE]
    assert plate and f"the joint is {FRAME}'s" in plate[0]["reason"]


def test_the_overlap_check_reads_a_weldment_of_its_own_as_settled():
    shadow = {
        "manufacturing_writeup": {"parts": [{"part_number": "P", "assembly_children": ["C"]}]},
        "canonical_route_shadow": {
            "decisions": [
                {"decision_id": "w0", "operation": "welding", "status": "required",
                 "target_id": "P", "participants": ["C", "S"]},
                {"decision_id": "w1", "operation": "welding", "status": "required",
                 "target_id": "C", "participants": ["C"],
                 "field_provenance": {"review": "joining_member_is_a_weldment_of_its_own"}}],
            "issues": [],
            "priced_route_rows": [{"decision_id": "w0"}, {"decision_id": "w1"}]}}
    assert costed_facts.parent_child_overlaps(shadow) == []
    unsettled = copy.deepcopy(shadow)
    unsettled["canonical_route_shadow"]["decisions"][1]["field_provenance"] = {}
    assert costed_facts.parent_child_overlaps(unsettled), "an unsettled pair is still reported"


# ── 1: the route-to-sheet join reads every decision id on the line ───────────────────────────

def test_a_line_decided_twice_finds_its_rows_by_each_id():
    rows = {"decision:a": {"workbook_row": 167, "part_numbers": [FRAME]},
            "decision:b": {"workbook_row": 183, "part_numbers": [FRAME]}}
    line = {"part_or_assembly": FRAME, "decision_id": "decision:a, decision:b", "charged": "yes"}
    cell, shares, note = wb_populate.route_line_on_the_sheet(line, rows)
    assert cell == "167, 183"
    assert "charged on 2 sheet rows" in note and "no sheet row carries" not in note


def test_a_line_whose_decisions_share_one_row_names_that_row():
    row = {"workbook_row": 165, "part_numbers": [FRAME, TUBE]}
    line = {"part_or_assembly": FRAME, "decision_id": "decision:a, decision:b", "charged": "yes"}
    cell, shares, note = wb_populate.route_line_on_the_sheet(
        line, {"decision:a": row, "decision:b": row})
    assert cell == 165 and shares == TUBE and "tooling SETUP" in note


def test_a_charged_line_with_no_row_still_says_the_join_is_missing():
    line = {"part_or_assembly": FRAME, "decision_id": "decision:z", "charged": "yes"}
    assert "join from the route to the sheet is missing" in \
        wb_populate.route_line_on_the_sheet(line, {})[2]
    line["charged"] = "no"
    assert wb_populate.route_line_on_the_sheet(line, {})[2] == \
        "not charged, so no sheet row is expected"
