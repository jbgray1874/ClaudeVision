"""A member of a weldment is finished with the weldment (D-686).

12693-01-GA, a table, 4 Nov 2026 17:16 run. The worktop weldment 12693-01-104 is a 1.5 mm skin
(03M), two sets of mild steel wires (05M and 06M, 4 of each) and twenty small tabs (07M), welded
together, and its own sheet states LIGHT AGED ZINC PLATED WITH WAXED. The frame weldment 101 is
powder coated, and its sheet and the GA say so. The book then did two things wrong:

  * 05M and 06M each carried a required powder_coating decision, charged on the P.Coat row with
    101 (the row covered "12693-01-101, 12693-01-05M, 12693-01-06M", qty 9). The route table
    gave the reason as "textual_operations on existing part record — no reader recorded a
    source or the drawing's words for it", decided from "unrecorded". The engine's own finish
    note had said the powder was NOT applied to the worktop weldment.
  * The plating line read "12693-01-104 plating — ... plated members: 12693-01-03M,
    12693-01-07M". The wires had dropped out of the weldment they are welded into.

WHERE THE COAT CAME FROM. document_builder's wire route added powder_coating to every wire part
when "POWDER" appeared ANYWHERE in the pack — here the frame's sheet and the GA's page 2 — and
recorded no source and no words. Each wire's own sheet says REFER TO SUB ASSEMBLY, which names
no finish, so no gate weighed the coat against anything and it was charged.

WHY THEY LEFT THE PLATING. Both wires are members of the plated weldment by the member rule,
but 05M's length was never read and 06M was priced at market with no weight, so neither had a
mass, and the plating line's member list kept only members with a mass, silently.

THE RULE. A member of a weldment is finished with it: its finish is the weldment's unless its
own sheet states a different one. A finishing decision on a member, contradicted by the
weldment's stated finish and with no recorded source of its own, is not charged; the member is
in the weldment's finish, and for a plate that means in the plating line's members. What
stays: a member whose own sheet states its own finish, a coat a reader quoted or a person
confirmed, a part in no weldment, and the D-683 refusal to price a decorative zinc on the
trade card.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config                                                         # noqa: E402
import document_builder as db                                         # noqa: E402
import estimator as e                                                 # noqa: E402
import finish_rules as fr                                             # noqa: E402
import route_compiler as rc                                           # noqa: E402

J = "12999-01"
PLATED = "LIGHT AGED ZINC PLATED WITH WAXED"
UNSOURCED_WIRE_OPS = ["wire_forming", "welding", "powder_coating", "handling"]


def _rec(pn, desc, finish=None, **over):
    rec = {"part_number": f"{J}-{pn}", "description": desc, "normalized_material": "MILD STEEL"}
    if finish is not None:
        rec["normalized_finish"] = finish
    rec.update(over)
    return rec


def _table(**changes):
    """The 12693-01 shape, from minimal records: a powder-coated frame weldment 101 holding a
    tube 01M, and a plated worktop weldment 104 holding a skin 03M and two wires 05M and 06M.
    Each weldment's weld is read off its own sheet; each wire carries the wire route's
    unsourced powder coat."""
    parts = {
        "101": _rec("101", "FRAME WELDMENT", "POWDER COATED - SEMI-GLOSS",
                    is_assembly_parent=True, textual_operations=["welding", "powder_coating"],
                    operation_sources={"welding": "drawing_notes",
                                       "powder_coating": "llm_full_extract"},
                    operation_evidence={"welding": "WELD ALL ROUND"}),
        "01M": _rec("01M", "FRAME TUBE", "SEE WELDMENT"),
        "104": _rec("104", "WORKTOP WELDMENT", PLATED, is_assembly_parent=True,
                    textual_operations=["welding"],
                    operation_sources={"welding": "drawing_notes"},
                    operation_evidence={"welding": "WELD ALL ROUND"}),
        "03M": _rec("03M", "LARGE TABLE TOP", "SEE WELDMENT"),
        "05M": _rec("05M", "TABLE EDGE - WIRE A", "REFER TO SUB ASSEMBLY",
                    textual_operations=list(UNSOURCED_WIRE_OPS)),
        "06M": _rec("06M", "TABLE EDGE - WIRE B", "REFER TO SUB ASSEMBLY",
                    textual_operations=list(UNSOURCED_WIRE_OPS)),
    }
    for pn, over in changes.items():
        if over is None:
            parts.pop(pn, None)
        else:
            parts[pn].update(over)
    extract = {
        "top_assembly": {"part_number": f"{J}-GA"},
        "assemblies": [
            {"part_number": f"{J}-GA", "children": [{"part_number": f"{J}-101", "qty": 1},
                                                    {"part_number": f"{J}-104", "qty": 1}]},
            {"part_number": f"{J}-101", "children": [{"part_number": f"{J}-01M", "qty": 4}]},
            {"part_number": f"{J}-104", "children": [{"part_number": f"{J}-03M", "qty": 1},
                                                     {"part_number": f"{J}-05M", "qty": 4},
                                                     {"part_number": f"{J}-06M", "qty": 4}]},
        ]}
    return list(parts.values()), extract


def _coats(parts, extract):
    """{target: decision} for every powder coat the compiled route decides."""
    graph = rc.compile_job_route(parts, extract)
    out = {}
    for d in graph.get("decisions") or []:
        d = d if isinstance(d, dict) else d.__dict__
        if d.get("operation") == "powder_coating":
            out[str(d.get("target_id"))] = d
    return out, graph


# ── the route: the wires' coat is the weldment's to decide ─────────────────────────────

def test_an_unsourced_coat_on_a_member_of_a_plated_weldment_is_not_charged():
    coats, graph = _coats(*_table())
    for wire in ("05M", "06M"):
        d = coats[f"{J}-{wire}"]
        assert d["status"] == rc.NOT_APPLICABLE, wire
        # The reason says whose finish it is and what that finish is, so the estimator can
        # check it against the weldment's sheet.
        assert f"welded into {J}-104" in d["reason"]
        assert PLATED in d["reason"] and "plate, not powder coating" in d["reason"]
        assert d["field_provenance"]["finish_owner"] == f"{J}-104"
    assert {i["part"] for i in graph["issues"]
            if i.get("code") == "member_finished_with_its_weldment"} == {f"{J}-05M", f"{J}-06M"}


def test_the_powder_coated_frame_keeps_its_coat():
    """The frame's own sheet states powder; nothing about the worktop touches it."""
    coats, _ = _coats(*_table())
    assert coats[f"{J}-101"]["status"] == rc.REQUIRED


def test_a_coat_the_weldment_shares_is_not_taken_off_its_member():
    """01M says SEE WELDMENT inside the powder-coated frame. An unsourced powder coat on it
    agrees with its weldment, so this rule has nothing to say about it."""
    parts, extract = _table(**{"01M": {"textual_operations": ["powder_coating"]}})
    coats, _ = _coats(parts, extract)
    assert coats[f"{J}-01M"]["status"] == rc.REQUIRED


def test_a_member_whose_own_sheet_states_its_own_finish_keeps_it():
    parts, extract = _table(**{"05M": {"normalized_finish": "POWDER COATED MATT BLACK"}})
    coats, _ = _coats(parts, extract)
    assert coats[f"{J}-05M"]["status"] == rc.REQUIRED
    assert coats[f"{J}-06M"]["status"] == rc.NOT_APPLICABLE


def test_a_coat_a_reader_recorded_for_the_member_stands():
    """A route that names the wire, or the wire's own words quoted, is evidence about THIS
    member, and the weldment's sheet is not evidence against it."""
    parts, extract = _table(**{
        "05M": {"operation_sources": {"powder_coating": "llm_full_extract"}},
        "06M": {"operation_evidence": {"powder_coating": "POWDER COAT AFTER WELDING"}}})
    coats, _ = _coats(parts, extract)
    assert coats[f"{J}-05M"]["status"] == rc.REQUIRED
    assert coats[f"{J}-06M"]["status"] == rc.REQUIRED


def test_the_documents_coat_stamped_on_a_member_is_the_documents():
    """The estimator's title-block stamp writes the GA's coat onto a member that states no
    finish: drawing_deterministic, with the record marked finish_inherited_from. That is the
    GA's word, not the member's sheet, and a plated weldment's member does not take it."""
    parts, extract = _table(**{"03M": {
        "inferred_operations": ["powder_coating"],
        "operation_sources": {"powder_coating": "drawing_deterministic"},
        "surface_finishes": ["POWDER COATED MATTE BLACK"],
        "finish_inherited_from": "document_level"}})
    coats, _ = _coats(parts, extract)
    assert coats[f"{J}-03M"]["status"] == rc.NOT_APPLICABLE


def test_a_part_in_no_weldment_is_untouched():
    """A loose wire in the pack, held by no weldment, keeps the coat it was given."""
    parts, extract = _table()
    parts.append(_rec("09M", "LOOSE WIRE HOOK", "REFER TO SUB ASSEMBLY",
                      textual_operations=list(UNSOURCED_WIRE_OPS)))
    extract["assemblies"][0]["children"].append({"part_number": f"{J}-09M", "qty": 2})
    coats, _ = _coats(parts, extract)
    assert coats[f"{J}-09M"]["status"] == rc.REQUIRED


def test_a_member_of_an_assembly_nobody_welds_is_untouched():
    """Bolted members are finished one by one. Without a weld, and without WELDMENT in its
    name, the plated assembly is not a weldment and decides nothing for its members."""
    parts, extract = _table(**{"104": {"description": "WORKTOP ASSEMBLY",
                                       "textual_operations": [], "operation_sources": {},
                                       "operation_evidence": {}}})
    coats, _ = _coats(parts, extract)
    assert coats[f"{J}-05M"]["status"] == rc.REQUIRED


def test_a_sheet_that_names_a_weldment_makes_it_one():
    """A weldment whose weld did not reach the graph is still a weldment by its own name."""
    parts, extract = _table(**{"104": {"textual_operations": [], "operation_sources": {},
                                       "operation_evidence": {}}})
    coats, _ = _coats(parts, extract)
    assert coats[f"{J}-05M"]["status"] == rc.NOT_APPLICABLE


def test_a_sub_weldment_that_states_no_finish_is_finished_with_its_parent():
    """The wires welded into an edge frame that says SEE WELDMENT, welded into the plated
    worktop: the edge frame goes in the tank with the worktop, so its wires do too."""
    parts, extract = _table()
    parts.append(_rec("108", "EDGE FRAME WELDMENT", "SEE WELDMENT", is_assembly_parent=True))
    extract["assemblies"][2]["children"] = [
        {"part_number": f"{J}-03M", "qty": 1}, {"part_number": f"{J}-108", "qty": 1}]
    extract["assemblies"].append({"part_number": f"{J}-108", "children": [
        {"part_number": f"{J}-05M", "qty": 4}, {"part_number": f"{J}-06M", "qty": 4}]})
    coats, _ = _coats(parts, extract)
    assert coats[f"{J}-05M"]["status"] == rc.NOT_APPLICABLE
    assert f"welded into {J}-104" in coats[f"{J}-05M"]["reason"]


# ── the rule itself ────────────────────────────────────────────────────────────────────

def test_the_rule_reads_the_members_sheet_first():
    why = fr.finished_with_its_weldment("powder_coating", "REFER TO SUB ASSEMBLY",
                                        f"{J}-104", PLATED, member=f"{J}-05M")
    assert why and "plate, not powder coating" in why
    # Nothing stated is the same as a pointer.
    assert fr.finished_with_its_weldment("powder_coating", "", f"{J}-104", PLATED)
    # A member that states its own finish, or states only how it is made, is decided by its
    # own sheet (finish_contradiction), never by the weldment's.
    for own in ("POWDER COATED", "RAW", "FINISH: WELDED"):
        assert fr.finished_with_its_weldment("powder_coating", own, f"{J}-104", PLATED) is None
    # A finish that agrees, an operation that is not a finish, or a weldment that states
    # nothing: no ruling.
    assert fr.finished_with_its_weldment("powder_coating", "", f"{J}-101",
                                         "POWDER COATED - SEMI-GLOSS") is None
    assert fr.finished_with_its_weldment("welding", "", f"{J}-104", PLATED) is None
    assert fr.finished_with_its_weldment("powder_coating", "", f"{J}-104", "") is None


# ── the wire route: the wire's own sheet is quoted, the pack's word is not its own ──────

def _wire(own_text, other_text):
    # An earlier reader already gave the wire an operation, so the zero-geometry note reader
    # (which quotes what it infers) stands aside and the wire route alone decides the coat.
    part = db._empty_part_record(part_number=f"{J}-05M", description="TABLE EDGE - WIRE A")
    part.update({"pages": [5], "page_roles": ["detail"], "materials": ["MILD STEEL WIRE"],
                 "textual_operations": ["wire_forming"]})
    summary = {"pages": [
        {"page_number": 4, "pdfplumber_text": other_text,
         "page_role": {"primary_role": "detail"}},
        {"page_number": 5, "pdfplumber_text": own_text,
         "page_role": {"primary_role": "detail"}}]}
    return db._apply_post_build_fixes([part], summary)[0]


def test_a_coat_read_off_another_sheet_carries_no_source_of_the_wires_own():
    """The frame's POWDER COATED is on page 4; the wire's own sheet says REFER TO SUB
    ASSEMBLY. The coat is still added for a wire in no weldment, and it must not be dressed as
    this wire's reading, or a plated weldment could never claim the wire."""
    p = _wire("TABLE EDGE - WIRE A MILD STEEL WIRE 4.00 DIA FINISH: REFER TO SUB ASSEMBLY",
              f"{J}-101 FRAME WELDMENT FINISH: POWDER COATED - SEMI-GLOSS")
    assert "powder_coating" in p["textual_operations"]
    assert "powder_coating" not in (p.get("operation_sources") or {})
    assert "powder_coating" not in (p.get("operation_evidence") or {})


def test_a_coat_on_the_wires_own_sheet_carries_its_words():
    p = _wire("TABLE EDGE - WIRE A MILD STEEL WIRE 4.00 DIA FINISH: POWDER COATED BLACK",
              f"{J}-104 WORKTOP WELDMENT FINISH: {PLATED}")
    assert "powder_coating" in p["textual_operations"]
    assert p["operation_sources"]["powder_coating"] == "drawing_notes"
    assert p["operation_evidence"]["powder_coating"] == "POWDER COATED"


# ── the plating line: every metal member of the plated weldment is counted ─────────────

def _estimates(finish_104=PLATED):
    """The costed side of the worktop: the skin and the tabs resolved a mass, the wires did
    not (05M unpriced, 06M at a market price with no weight)."""
    parts = [
        _rec("104", "WORKTOP WELDMENT", finish_104, is_assembly_parent=True, quantity=1),
        _rec("03M", "LARGE TABLE TOP", "SEE WELDMENT", quantity=1,
             material_estimate={"unit_material_mass_kg": 18.0}),
        _rec("05M", "TABLE EDGE - WIRE A", "REFER TO SUB ASSEMBLY", quantity=4,
             material_estimate={"unit_material_mass_kg": None}),
        _rec("06M", "TABLE EDGE - WIRE B", "REFER TO SUB ASSEMBLY", quantity=4,
             material_estimate={"cost_method": "web_ai_price"}),
        _rec("07M", "TABLE EDGE - SUPPORT", "REFER TO SUB ASSEMBLY", quantity=20,
             material_estimate={"unit_material_mass_kg": 0.015}),
        {"part_number": f"{J}-104-PLATE", "description": f"{J}-104 plating",
         "page_roles": ["bought_in"], "quantity": 1, "_commercial_placeholder": True,
         "_plating_placeholder": True, "_plating_weldment": f"{J}-104",
         "_plating_members": [f"{J}-03M", f"{J}-07M"]},
    ]
    summary = {"llm_full_extract": {"assemblies": [{"part_number": f"{J}-104", "children": [
        {"part_number": f"{J}-{c}"} for c in ("03M", "05M", "06M", "07M")]}]}}
    return parts, summary


def _plate(parts, summary, policy=None):
    old = getattr(config, "PLATE_SUBCONTRACT_POLICY", None)
    if policy is not None:
        config.PLATE_SUBCONTRACT_POLICY = policy
    try:
        e.apply_subcontract_plating(parts, summary, 1, parts)
    finally:
        config.PLATE_SUBCONTRACT_POLICY = old
    return next(p for p in parts if p["part_number"].endswith("-PLATE"))


def test_the_wires_are_members_of_the_plated_weldment():
    parts, summary = _estimates()
    assert e.plated_steel_member_pns(parts, summary) >= {
        f"{J}-03M", f"{J}-05M", f"{J}-06M", f"{J}-07M"}


def test_a_member_with_no_mass_is_named_on_the_plating_line_not_dropped():
    parts, summary = _estimates("ZINC PLATED")          # the trade card prices on the mass
    plate = _plate(parts, summary, {"gbp_per_kg": 2.50, "vat_minimum_gbp": 95.0})
    wires = [f"{J}-05M", f"{J}-06M"]
    assert plate["_plating_members_unmassed"] == wires
    assert plate["_plating_members_costed"] == [f"{J}-03M", f"{J}-07M"]
    # Named on the sheet line itself, among the plated members.
    desc = plate["description"]
    members = desc.split(" — plated members: ")[1]
    for pn in (f"{J}-03M", f"{J}-05M", f"{J}-06M", f"{J}-07M"):
        assert pn in members
    assert f"no mass resolved, not in the plated weight: {', '.join(wires)}" in desc
    # The weight priced is what was resolved, and the line says it is short.
    assert plate["material_estimate"]["unit_material_mass_kg"] == 18.3
    assert "NO MASS resolved" in plate["review_flags"][0]
    assert "short by theirs" in plate["review_flags"][0]


def test_the_decorative_zinc_is_still_not_priced_on_the_trade_card():
    """D-683 is kept: the worktop's aged and waxed zinc is not the zinc card, and the line
    asks for the finisher's quote. Who goes in the tank is a separate question, and the
    wires are on the line either way."""
    parts, summary = _estimates()
    plate = _plate(parts, summary)
    assert plate["material_estimate"]["cost_method"] == "subcontract_plating_quote_needed"
    assert plate["_price_explicitly_withheld"] is True
    for pn in (f"{J}-05M", f"{J}-06M"):
        assert pn in plate["description"].split(" — plated members: ")[1]


def test_a_document_finish_does_not_take_a_member_out_of_the_plating():
    """The GA's POWDER COATED, stamped onto the skin because it states no finish of its own,
    is not the skin's own detail: the skin stays a plated member and is not 'excluded, own
    detail differs'."""
    parts, summary = _estimates()
    skin = next(p for p in parts if p["part_number"] == f"{J}-03M")
    skin.update({"surface_finishes": ["POWDER COATED MATTE BLACK"],
                 "finish_inherited_from": "document_level"})
    del skin["normalized_finish"]
    assert f"{J}-03M" in e.plated_steel_member_pns(parts, summary)
    assert f"{J}-03M" not in e.plated_members_deferred_to_their_own_finish(parts, summary)


def test_a_member_whose_own_detail_states_powder_is_still_deferred():
    """Its own sheet is evidence: the D-595 exclusion with the member named stands."""
    parts, summary = _estimates()
    next(p for p in parts if p["part_number"] == f"{J}-05M")["normalized_finish"] = \
        "POWDER COATED BLACK"
    assert f"{J}-05M" not in e.plated_steel_member_pns(parts, summary)
    assert f"{J}-05M" in e.plated_members_deferred_to_their_own_finish(parts, summary)
