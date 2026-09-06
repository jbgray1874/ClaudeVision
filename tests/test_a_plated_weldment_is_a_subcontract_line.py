"""A PLATED weldment carries a subcontract plating line, priced on the plated steel mass.

7332-01's Harrods stand is PLATED (title block "PLATED / Harrods 1"). SDI has a powder booth, not
a plate shop, so plating is a SUBCONTRACT line — plated steel mass × a trade £/kg with the
plater's per-batch vat minimum — not a P.Coat booth-labour row (the powder gate already rules
powder out on a plated part) and not the £0 it read before. The rate is an INDICATIVE trade-zinc
figure that stays blocking until a plater quote confirms; a decorative "Harrods" spec is not this
rate, and the review flag says so.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator as e  # noqa: E402
import route_compiler as rc  # noqa: E402


_POLICY = {"gbp_per_kg": 2.50, "vat_minimum_gbp": 95.0, "label": "plating — INDICATIVE"}


# ── the price ────────────────────────────────────────────────────────────────
def test_the_plate_price_is_mass_times_rate_when_the_order_clears_the_vat_min():
    # 8 kg × £2.50 × 6 off = £120 order, over the £95 vat min → per-unit is just 8×2.50 = £20
    unit, note, method = e.plating_unit_price(8.0, 6, _POLICY)
    assert unit == 20.00
    assert method == "subcontract_plating_indicative"
    assert "INDICATIVE" in note and "verify against a plater quote" in note


def test_a_light_short_order_is_floored_at_the_plater_vat_minimum():
    # 2 kg × £2.50 × 2 off = £10 order, under the £95 min → charged £95 / 2 = £47.50/unit
    unit, note, _ = e.plating_unit_price(2.0, 2, _POLICY)
    assert unit == 47.50
    assert "vat minimum" in note


def test_no_rate_or_no_mass_withholds_the_price():
    assert e.plating_unit_price(8.0, 6, {"gbp_per_kg": None})[0] is None
    assert e.plating_unit_price(0.0, 6, _POLICY)[0] is None
    assert "estimator to price" in e.plating_unit_price(0.0, 6, _POLICY)[1]


# ── who is plated ──────────────────────────────────────────────────────────────
def _parts_7332():
    return [
        {"part_number": "7332-01-101", "description": "FRAME WELDMENT",
         "normalized_material": "MILD STEEL", "normalized_finish": "PLATED",
         "is_assembly_parent": True},
        {"part_number": "7332-01-001", "description": "BASE", "normalized_material": "MILD STEEL"},
        {"part_number": "7332-01-002", "description": "LEG", "normalized_material": "MILD STEEL"},
        {"part_number": "7332-01-005", "description": "CHANNEL", "normalized_material": "MILD STEEL"},
        {"part_number": "7332-01-008", "description": "BACK PANEL",
         "normalized_material": "MILD STEEL", "normalized_finish": "PLATED"},
        {"part_number": "7332-01-007", "description": "LENS", "normalized_material": "ACRYLIC",
         "normalized_finish": "PLATED"},  # acrylic — a plater does not plate the lens
    ]


def _summary_7332():
    return {"llm_full_extract": {"assemblies": [
        {"part_number": "7332-01-101", "children": [
            {"part_number": "7332-01-001"}, {"part_number": "7332-01-002"},
            {"part_number": "7332-01-005"}]},
        {"part_number": "7332-01-GA", "children": [
            {"part_number": "7332-01-101"}, {"part_number": "7332-01-007"},
            {"part_number": "7332-01-008"}]},
    ]}}


def test_the_plated_members_are_the_steel_ones_under_the_plated_weldment_plus_plated_leaves():
    members = e.plated_steel_member_pns(_parts_7332(), _summary_7332())
    assert members == {"7332-01-001", "7332-01-002", "7332-01-005", "7332-01-008"}
    assert "7332-01-101" not in members     # the weldment's material lives in its children
    assert "7332-01-007" not in members     # acrylic lens is not plated


def test_a_member_that_states_RAW_is_not_plated_even_under_a_plated_weldment():
    """7332-01's BASE 001 is stated RAW — about 5.3 kg of 5mm steel no plater ever sees.
    Inheriting the weldment's plate down every metal child swept it in and the 12:37 sheet
    charged £20.12 on 8.05 kg; without it the mass is ~2.7 kg and the £95 vat minimum sets the
    line at £15.83. A part that states a recognised finish of its own is not reassigned to its
    parent's; only a member that states NOTHING inherits."""
    parts = _parts_7332()
    for p in parts:
        if p["part_number"] == "7332-01-001":
            p["normalized_finish"] = "RAW"
    members = e.plated_steel_member_pns(parts, _summary_7332())
    assert "7332-01-001" not in members            # RAW base is not plated
    assert "7332-01-008" in members                # stated PLATED still is
    assert "7332-01-002" in members                # states nothing -> inherits the weldment's


def test_the_raw_member_is_what_moved_the_plate_price():
    """The arithmetic that proves the 12:37 £20.12 was the RAW base being charged."""
    pol = {"gbp_per_kg": 2.50, "vat_minimum_gbp": 95.0}
    with_base, _, _ = e.plating_unit_price(8.05, 6, pol)     # base wrongly included
    without_base, _, _ = e.plating_unit_price(2.70, 6, pol)  # base excluded -> vat floor
    assert with_base == 20.12
    assert without_base == 15.83


def test_no_plated_weldment_no_members():
    parts = [{"part_number": "X-1", "normalized_material": "MILD STEEL",
              "normalized_finish": "POWDER COATED", "is_assembly_parent": True}]
    assert e.plated_steel_member_pns(parts, {}) == set()


# ── the priced line, end to end over part_estimates ────────────────────────────
def _pe(pn, mass, qty=1, mat="MILD STEEL"):
    return {"part_number": pn, "quantity": qty,
            "material_estimate": {"unit_material_mass_kg": mass}, "normalized_material": mat}


def test_the_pass_prices_the_placeholder_from_the_members_masses():
    part_estimates = [
        _pe("7332-01-001", 5.0, 1),
        _pe("7332-01-002", 0.5, 2),      # 2 legs → 1.0 kg
        _pe("7332-01-008", 1.0, 1),
        {"part_number": "7332-01-101-PLATE", "quantity": 1, "_plating_placeholder": True,
         "_plating_members": ["7332-01-001", "7332-01-002", "7332-01-008"]},
    ]
    import config
    old = getattr(config, "PLATE_SUBCONTRACT_POLICY", None)
    config.PLATE_SUBCONTRACT_POLICY = _POLICY
    try:
        n = e.apply_subcontract_plating(part_estimates, {}, order_qty=6)
    finally:
        if old is not None:
            config.PLATE_SUBCONTRACT_POLICY = old
    assert n == 1
    plate = next(p for p in part_estimates if p["part_number"] == "7332-01-101-PLATE")
    # mass = 5.0 + 0.5×2 + 1.0 = 7.0 kg → 7.0 × £2.50 = £17.50/unit (order of 6 clears the min)
    assert plate["unit_cost_gbp"] == 17.50
    assert plate["material_estimate"]["unit_material_mass_kg"] == 7.0
    assert plate["material_estimate"]["cost_method"] == "subcontract_plating_indicative"
    assert plate["review_flag"] is True
    assert not plate["_price_explicitly_withheld"]
    assert "zinc" in plate["review_flags"][0].lower()


def test_an_unresolved_mass_leaves_a_named_blocking_gap_not_a_silent_zero():
    part_estimates = [
        {"part_number": "X-PLATE", "quantity": 1, "_plating_placeholder": True,
         "_plating_members": ["MISSING-1"]},   # member not in the list → mass 0
    ]
    import config
    old = getattr(config, "PLATE_SUBCONTRACT_POLICY", None)
    config.PLATE_SUBCONTRACT_POLICY = _POLICY
    try:
        e.apply_subcontract_plating(part_estimates, {}, order_qty=6)
    finally:
        if old is not None:
            config.PLATE_SUBCONTRACT_POLICY = old
    plate = part_estimates[0]
    assert plate["_price_explicitly_withheld"] is True
    assert plate["extended_total_cost_gbp"] == 0.0
    assert plate["material_estimate"]["cost_method"] == "estimator_to_price"


# ── the member list and the parent column are two views of ONE hierarchy ──────
def _real_shape():
    """The shape that broke it: 101's children stated by the EXTRACT (so the parent's own
    assembly_children list is skipped), and 002 reaching 101 only through that stated list."""
    parts = [
        {"part_number": "7332-01-101", "description": "FRAME WELDMENT",
         "normalized_material": "MILD STEEL", "normalized_finish": "PLATED",
         "is_assembly_parent": True},
        {"part_number": "7332-01-001", "description": "BASE", "normalized_material": "MILD STEEL",
         "normalized_finish": "RAW", "quantity": 1,
         "material_estimate": {"unit_material_mass_kg": 5.30}},
        {"part_number": "7332-01-002", "description": "LEG", "normalized_material": "MILD STEEL",
         "quantity": 2, "material_estimate": {"unit_material_mass_kg": 0.773}},
        {"part_number": "7332-01-008", "description": "BACK PANEL",
         "normalized_material": "MILD STEEL", "normalized_finish": "PLATED", "quantity": 1,
         "material_estimate": {"unit_material_mass_kg": 0.88}},
        {"part_number": "7332-01-101-PLATE", "description": "plating",
         "page_roles": ["bought_in"], "quantity": 1,
         "_commercial_placeholder": True, "_plating_placeholder": True,
         # the WRONG list the mint produced, which the pass must correct
         "_plating_members": ["7332-01-008"]},
    ]
    summary = {"llm_full_extract": {"assemblies": [
        {"part_number": "7332-01-101", "children": [
            {"part_number": "7332-01-001"}, {"part_number": "7332-01-002"},
            {"part_number": "7332-01-008"},
            {"part_number": "7332-01-101-PLATE", "qty": 1}]}]}}
    return parts, summary


def test_the_member_list_is_re_derived_from_the_compiled_hierarchy():
    """The mint read the parent's own child list and the LLM extract; 7332's 002 -> 101 edge came
    from neither, so inheritance never fired and the plate named only 008 — the one part that
    states PLATED itself. The pass now re-derives against the compiled graph."""
    parts, summary = _real_shape()
    e.apply_subcontract_plating(parts, summary, 6, parts)
    plate = next(p for p in parts if p["part_number"].endswith("-PLATE"))
    assert plate["_plating_members"] == ["7332-01-002", "7332-01-008"]
    assert "7332-01-001" not in plate["_plating_members"]        # RAW base still excluded
    assert plate["material_estimate"]["unit_material_mass_kg"] == 2.426
    assert plate["unit_cost_gbp"] == 15.83                       # £95 vat floor over 6
    assert "7332-01-002" in plate["description"]                 # named on the sheet line


def test_the_plating_line_has_a_defensible_parent():
    """Zero blockers is not the test — the plate must sit UNDER the weldment it plates. The
    parent's own assembly_children is skipped for a parent the extract already states, so the
    edge has to go where the graph actually reads it."""
    parts, summary = _real_shape()
    graph = rc.build_part_graph(parts, summary["llm_full_extract"])
    plate = next(n for n in graph["nodes"] if n.part_number.endswith("-PLATE"))
    assert plate.parents == ["7332-01-101"]
    assert not [i for i in (graph.get("issues") or [])
                if i.get("code") == "bom_node_disconnected"]


def test_the_config_carries_the_plate_policy():
    import config
    pol = config.PLATE_SUBCONTRACT_POLICY
    assert pol["gbp_per_kg"] == 2.50 and pol["vat_minimum_gbp"] > 0
