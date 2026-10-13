"""The K-Wellness 18:17 book, charge by charge: each thing once, at its own scope (D-495..D-499).

The book came back at £1,433.81 a unit. £830 of it was two test allowances charged on each of
200 units though the brief says testing is "NOT in the unit price"; the Assemble/pack row
charged 165.9 minutes beside an explanation of 82.95; the labels were counted 79 and charged
one; the fold row told the reader a bracket ran at 5807 an hour; and the read's own
construction — brackets WELDED TO the trays, strips "one per shelf" across trays of two sizes,
no fixings named, a "flat" blank the size of the unit's own footprint — reached the rows
unexamined. Each rule here is generic: it reads the records' own words, counts and sources,
never a part code or a job.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import concept_scan as cs                                                # noqa: E402
import config                                                            # noqa: E402

BRIEF = (
    "Assembly, inspection, protective packaging and palletised delivery included. 200 off. "
    "The 5% spares and the design, development,\nprototype and testing costs are NOT in the "
    "unit price - the estimator lists them\nseparately in the response. QR component labels "
    "(20 x 20 mm) are a per-unit requirement: production, application and verification. QC "
    "is batch setup plus sampled and unit checks, not full inspection per unit. Design, "
    "prototypes, testing and documentation are per-order project costs, shown separately.")


# ── D-495: the unit's stated assembly time is charged once ─────────────────────────────

def test_a_stated_time_found_under_the_departments_other_name_is_not_added_twice():
    import wb_populate as W
    hours = {"KW-CPT00": {"handling": 1.3825}}
    claims = {"KW-CPT00": "the per-part handling allowance"}
    ops = {"KW-CPT00": {"handling", "assembly"}}
    g = {"parts": ["KW-CPT00"], "engine_ops": ["assembly"], "run_hours_per_unit": 1.3825,
         "hours_by_part": {"KW-CPT00": {"bh": 0.0, "qty_per_unit": 1, "rh": 1.3825}}}
    h, who = W.stated_row_hours(g, claims, hours, ops)
    assert who == ["KW-CPT00"] and abs(h - 1.3825) < 1e-9, h       # 82.95 min, not 165.9


def test_the_grouping_records_the_share_it_summed_for_the_assemblys_own_time():
    import wb_populate as W
    summary = {"estimate_summary": {"canonical_route_shadow": {"nodes": [], "decisions": [
        {"decision_id": "d1", "operation": "assembly", "status": "required",
         "target_id": "KW-CPT00", "participants": ["KW-CPT01", "KW-CPT02"],
         "scope": "assembly", "qty_per_unit": 1}]}}}
    estimates = [{"part_number": "KW-CPT00", "quantity": 1,
                  "labour_estimate": {"batch_hours": {"handling": 276.75},
                                      "run_hours_per_unit": {"handling": 1.3825}}},
                 {"part_number": "KW-CPT01", "quantity": 6, "labour_estimate": {}},
                 {"part_number": "KW-CPT02", "quantity": 1, "labour_estimate": {}}]
    groups = W.canonical_labour_groups(summary, estimates, 200)
    (g,) = [v for v in groups.values() if v.get("assembly_own_time")]
    assert abs(g["run_hours_per_unit"] - 1.3825) < 1e-9
    assert abs(g["hours_by_part"]["KW-CPT00"]["rh"] - 1.3825) < 1e-9
    h, _ = W.stated_row_hours(g, {"KW-CPT00": "x"}, {"KW-CPT00": {"handling": 1.3825}},
                              {"KW-CPT00": {"handling", "assembly"}})
    assert abs(h - 1.3825) < 1e-9, f"charged {h * 60:.1f} min for 82.95 stated"


# ── D-496: a count the engine worked out is kept ───────────────────────────────────────

def test_a_counted_quantity_over_the_cap_is_kept_and_an_unexplained_one_is_not():
    import estimator as E
    counted = {"part_number": "J-NV01", "quantity": 79,
               "quantity_counted": {"count": 79, "basis": "1 per component × 79 component(s)"}}
    assert E._sanitise_part_quantity(counted) == 79
    assert any(isinstance(f, dict) and f.get("flag") == "quantity_over_cap_kept"
               for f in counted.get("review_flags") or [])
    noise = {"part_number": "J-NV01", "quantity": 79}
    assert E._sanitise_part_quantity(noise) == 1


def test_per_component_labels_carry_their_count_and_its_working():
    (labels,) = cs.consumable_lines(["QR component labels 20x20mm"], "J", pieces_fitted=79)
    assert labels["quantity"] == 79
    assert labels["quantity_counted"]["count"] == 79
    assert "79 component" in labels["quantity_counted"]["basis"]


# ── D-497: a project cost's scope comes from evidence ──────────────────────────────────

def _req(name, scope, requirement="", basis=""):
    return {"name": name, "scope": scope, "requirement": requirement,
            "provisional_gbp": 450.0, "provisional_basis": basis}


def test_the_brief_moves_a_test_the_read_put_on_every_unit_to_the_order():
    (r,) = cs.standards_requirements({"applicable_requirements": [
        _req("BTC topple/tilt/bump tests", "per_unit",
             basis="3 hours test rig + report at UK trade rate")]}, brief=BRIEF)
    assert r["scope"] == "per_order" and r["scope_source"] == "brief"
    assert r["read_scope"] == "per_unit"
    # The brief's own words, quoted — either of its two per-order sentences.
    assert r["scope_basis"].startswith("the brief:")
    assert ("NOT in the unit price" in r["scope_basis"]
            or "per-order project costs" in r["scope_basis"])
    (p,) = cs.project_cost_plan([r], {}, 200)
    assert p["unit_gbp"] == 0.0 and p["order_gbp"] == 450.0
    assert "Scope per order: the brief" in p["flag"]
    (f,) = cs.requirement_flags([r])
    assert "the read had it per unit" in f


def test_a_line_whose_name_says_nothing_is_classed_by_its_allowance_basis():
    """'BTC006/007 custom shelf deflection' names no test; its basis does."""
    (r,) = cs.standards_requirements({"applicable_requirements": [
        _req("BTC006/007 custom shelf deflection", "per_unit",
             basis="2 hours test + report at UK trade rate")]}, brief=BRIEF)
    assert r["scope"] == "per_order"


def test_the_brief_keeps_labels_on_the_unit_and_qc_per_batch_despite_a_negated_per_unit():
    labels, qc = cs.standards_requirements({"applicable_requirements": [
        _req("QR component labels", "per_order"),
        _req("QC inspection", "per_unit")]}, brief=BRIEF)
    assert labels["scope"] == "per_unit" and labels["scope_source"] == "brief"
    # "not full inspection per unit" does not say per unit.
    assert qc["scope"] == "per_batch" and qc["scope_source"] == "brief"


def test_without_the_brief_the_requirements_own_words_decide():
    reqs = cs.standards_requirements({"applicable_requirements": [
        _req("Stability test", "per_unit", requirement="a type test on the design"),
        _req("Weld inspection", "per_order", requirement="each unit is inspected before despatch"),
        _req("Load test", "per_unit", requirement="re-test after any design change"),
        _req("Mystery", "per_unit")]})
    by = {r["name"]: r for r in reqs}
    assert by["Stability test"]["scope"] == "per_order"
    assert by["Weld inspection"]["scope"] == "per_unit"
    assert by["Load test"]["scope"] == "per_order"
    assert "a design change brings it back" in by["Load test"]["scope_basis"]
    # No evidence: the read's call stands, labelled as an assumption to confirm.
    assert by["Mystery"]["scope"] == "per_unit" and by["Mystery"]["scope_source"] == "read"
    assert "assumption to confirm" in by["Mystery"]["scope_basis"]


def test_the_estimators_scope_outranks_everything_and_batches_multiply_a_batch_cost():
    (r,) = cs.standards_requirements({"applicable_requirements": [
        _req("BTC topple/tilt/bump tests", "per_unit")]}, brief=BRIEF)
    (p,) = cs.project_cost_plan([r], {"project_scope": {"topple": "per_unit"}}, 200)
    assert p["unit_gbp"] == 450.0 and "the estimator's answer" in p["flag"]
    (qc,) = cs.standards_requirements({"applicable_requirements": [
        _req("QC inspection", "per_unit")]}, brief=BRIEF)
    (one,) = cs.project_cost_plan([qc], {}, 200)
    assert one["order_gbp"] == 450.0 and "ONE batch is taken at every quantity" in one["flag"]
    (three,) = cs.project_cost_plan([qc], {"project_batches": 3}, 200)
    assert three["order_gbp"] == 1350.0 and "ONE batch" not in three["flag"]
    assert three["batch_size"] == 67 and three["per_batch_gbp"] == 450.0


def test_a_per_batch_cost_is_recounted_at_every_quantity_break():
    (qc,) = cs.standards_requirements({"applicable_requirements": [
        _req("QC inspection", "per_unit")]}, brief=BRIEF)
    (om,) = cs.standards_requirements({"applicable_requirements": [
        dict(_req("O&M manual", "per_order"), provisional_gbp=650.0)]}, brief=BRIEF)
    plan = cs.project_cost_plan([qc, om], {"project_batch_size": 50}, 200)
    pc = {"total_gbp": sum(p["order_gbp"] for p in plan),
          "lines": [{k: p.get(k) for k in ("scope", "state", "order_gbp", "per_batch_gbp",
                                           "batch_size")} for p in plan]}
    assert pc["total_gbp"] == 4 * 450 + 650                       # 200 off = 4 batches of 50
    assert cs.project_costs_at(pc, 1) == 450 + 650                # one batch, the manual once
    assert cs.project_costs_at(pc, 10) == 450 + 650
    assert cs.project_costs_at(pc, 51) == 2 * 450 + 650
    assert cs.project_costs_at(pc, 200) == 4 * 450 + 650
    # No batch size stated: one batch at every quantity, never the order's count reused.
    plan1 = cs.project_cost_plan([qc], {}, 200)
    pc1 = {"lines": [{k: p.get(k) for k in ("scope", "state", "order_gbp", "per_batch_gbp",
                                            "batch_size")} for p in plan1]}
    assert cs.project_costs_at(pc1, 1) == cs.project_costs_at(pc1, 200) == 450


def test_the_quantity_breaks_tab_recalculates_project_costs_per_column(tmp_path):
    import openpyxl
    from quantity_breaks_tab import write_quantity_breaks_tab, SHEET_NAME
    p = tmp_path / "book.xlsx"
    openpyxl.Workbook().save(p)
    pc = {"total_gbp": 2450.0, "lines": [
        {"scope": "per_batch", "state": "provisional", "order_gbp": 1800.0,
         "per_batch_gbp": 450.0, "batch_size": 50},
        {"scope": "per_order", "state": "provisional", "order_gbp": 650.0}]}
    swept = {"rows": [{"quantity": 1, "material": 10, "labour": 5, "unit": 20.0},
                      {"quantity": 10, "material": 10, "labour": 4, "unit": 18.0},
                      {"quantity": 200, "material": 10, "labour": 3, "unit": 16.0}]}
    write_quantity_breaks_tab(p, swept, requested=[200], project_costs=pc)
    ws = openpyxl.load_workbook(p)[SHEET_NAME]
    (row,) = [r for r in range(1, ws.max_row + 1)
              if str(ws.cell(r, 1).value or "").startswith("Project costs £")]
    assert "per batch each batch" in ws.cell(row, 1).value
    assert [ws.cell(row, c).value for c in (2, 3, 4)] == [1100.0, 1100.0, 2450.0]
    assert ws.cell(row + 1, 4).value == round(16.0 * 200 + 2450.0, 2)


def test_a_saved_requirement_without_a_scope_source_is_resolved_from_the_brief():
    (p,) = cs.project_cost_plan([_req("BTC topple/tilt/bump tests", "per_unit")], {}, 200,
                                brief=BRIEF)
    assert p["scope"] == "per_order" and p["unit_gbp"] == 0.0


def test_a_per_order_project_line_is_charged_once_not_unpriced():
    import costed_facts as cf
    import estimator_inputs as ei
    line = {"part_number": "PROJECT-03", "description": "O&M manual",
            "project_cost_line": {"scope": "per_order", "state": "provisional",
                                  "order_gbp": 650.0}}
    o = cf._price_origin(line, "commercial", "bom", 0.0, 0.0, 17, False, row_text="")
    assert o["class"] == "per_order_project" and o["firmness"] == cf.NIL
    assert "£650.00 charged ONCE" in o["label"]
    r = ei.unpriced_reason_for_row(line)
    assert r["category"] == "not_applicable" and "£650.00" in r["detail"]
    # With no figure at all it is still a price to add.
    open_line = dict(line, project_cost_line={"scope": "per_order", "state": "to_price",
                                              "order_gbp": None})
    assert cf._price_origin(open_line, "commercial", "bom", 0.0, 0.0, 17, False,
                            row_text="")["class"] == "unpriced_commercial"


# ── D-498: a shared row's members are shown at their own rates ─────────────────────────

def test_a_members_rate_is_its_own_piece_time_not_inflated_by_its_count():
    import wb_populate as W
    hbp = {"KW-CPT10": {"bh": 1.0333, "qty_per_unit": 30, "rh": 0.005},
           "KW-CPT01": {"bh": 2.0333, "qty_per_unit": 6, "rh": 0.01},
           "LEGACY": {"bh": 2.0, "qty_per_unit": 4}}
    rates = {p: round(r, 1) for p, r, _ in W.member_rates(hbp, 200)}
    assert rates["KW-CPT10"] == 200.0          # was shown as 5807/hr
    assert rates["KW-CPT01"] == 100.0          # was shown as 590/hr
    assert rates["LEGACY"] == 100.0            # batch fallback: order ÷ batch hours, no × count


def test_the_rows_charge_is_unchanged_by_the_shown_rates():
    import wb_populate as W
    summary = {"estimate_summary": {"canonical_route_shadow": {"nodes": [], "decisions": [
        {"decision_id": f"d{i}", "operation": "folding", "status": "required",
         "target_id": pn, "participants": [pn], "scope": "part", "qty_per_unit": q}
        for i, (pn, q) in enumerate((("KW-CPT10", 30), ("KW-CPT01", 6)))]}}}
    est = [{"part_number": pn, "quantity": q, "normalized_thickness_mm": 2.0,
            "material_estimate": {"stock_form": "sheet", "material": "MILD STEEL",
                                  "blank_length_mm": 100, "blank_width_mm": 50},
            "labour_estimate": {"batch_hours": {"folding": bh},
                                "run_hours_per_unit": {"folding": rh}}}
           for pn, q, bh, rh in (("KW-CPT10", 30, 1.0333, 0.005),
                                 ("KW-CPT01", 6, 2.0333, 0.01))]
    groups = W.canonical_labour_groups(summary, est, 200)
    folds = [g for g in groups.values() if "folding" in (g.get("engine_ops") or [])]
    total = sum(g["run_hours_per_unit"] for g in folds)
    assert abs(total - (30 * 0.005 + 6 * 0.01)) < 1e-9      # 0.21 h a unit, as before


# ── D-499: the sighted construction, applied to its own lines ──────────────────────────

LF = ["laser_cutting", "folding", "powder_coating", "handling"]


def _p(name, q, L, W, ops, folds=0, basis="developed", seen="", why="", flange=0):
    return {"name": name, "kind": "fabricated", "quantity": q, "material_guess": "MILD STEEL",
            "assumed_blank_mm": {"length": L, "width": W, "thickness": 1.5},
            "operations": ops, "folds": folds, "blank_basis": basis, "seen": seen,
            "why_size": why, "flange_mm": flange}


def _fsdu(**over):
    parts = [
        _p("CORNER POST", 6, 1500, 80, LF + ["welding"], 2),
        _p("BASE / PLINTH", 1, 500, 500, LF + ["welding"], 4, why="500x500 footprint",
           flange=40),
        _p("TOP CAP", 1, 500, 500, LF, 4, why="500x500 footprint"),
        _p("HEADER", 6, 460, 80, LF, 1),
        _p("FRONT SHELF TRAY", 5, 460, 300, LF, 3),
        _p("SIDE SHELF TRAY (LEFT)", 5, 300, 250, LF, 3),
        _p("SIDE SHELF TRAY (RIGHT)", 5, 300, 250, LF, 3),
        _p("HOOKED BRACKET (WELDED TO TRAY)", 30, 40, 30,
           ["laser_cutting", "welding", "folding"], 1),
        _p("35MM SHELF EDGE STRIP", 15, 460, 35, LF, 1, seen="one per shelf x15 shelves",
           why="length from shelf width"),
    ]
    ans = {"product": {"name": "FSDU", "assumed_overall_mm": {"height": 1500, "width": 500,
                                                             "depth": 500}},
           "parts": parts}
    ans.update(over)
    return ans


def _by(parts):
    return {p["description"] if "STRIP" not in p["description"] else p["part_number"]: p
            for p in parts}


def test_a_piece_welded_to_a_named_host_joins_that_hosts_component_and_its_coat():
    parts = cs.parts_from_concept(_fsdu(), "J")
    br = _by(parts)["HOOKED BRACKET (WELDED TO TRAY)"]
    trays = {p["part_number"] for p in parts if "TRAY" in p["description"]
             and "BRACKET" not in p["description"]}
    assert set(br["welded_to_hosts"]) == trays
    assert set(br["coated_with_host"]) == trays          # hosts coated, bracket not
    assert any("welded to its host" in str(f) for f in br["review_flags"])
    unit = cs.unit_assembly_part(parts, _fsdu(), "J")
    total = sum(int(p["quantity"]) for p in parts)
    assert unit["pieces_fitted"] == total - 30            # the brackets fit with their trays
    assert unit["pieces_joined_to_hosts"] == {br["part_number"]: 30}


def test_a_piece_welded_to_an_uncoated_host_is_not_coated_and_no_host_no_change():
    ans = _fsdu()
    for p in ans["parts"]:
        if "TRAY" in p["name"] and "BRACKET" not in p["name"]:
            p["operations"] = ["laser_cutting", "folding"]
    br = _by(cs.parts_from_concept(ans, "J"))["HOOKED BRACKET (WELDED TO TRAY)"]
    assert br["welded_to_hosts"] and not br.get("coated_with_host")
    ans2 = _fsdu()
    ans2["parts"][7]["name"] = "HOOKED BRACKET (WELDED TO GANTRY)"
    br2 = _by(cs.parts_from_concept(ans2, "J"))["HOOKED BRACKET (WELDED TO GANTRY)"]
    assert not br2.get("welded_to_hosts")


def test_the_powder_area_includes_a_piece_coated_with_its_host_and_no_more():
    import wb_populate as W
    host = {"part_number": "T1", "quantity": 1,
            "material_estimate": {"stock_form": "sheet", "blank_length_mm": 460,
                                  "blank_width_mm": 300, "extended_material_cost_gbp": 2}}
    bracket = {"part_number": "B1", "quantity": 30, "coated_with_host": ["T1"],
               "material_estimate": {"stock_form": "sheet", "blank_length_mm": 40,
                                     "blank_width_mm": 30, "extended_material_cost_gbp": 1}}
    coated = W.route_coated_membership({"T1"})
    with_b = W.coated_sheet_area_m2([host, bracket], coated)
    alone = W.coated_sheet_area_m2([host], coated)
    assert abs((with_b - alone) - 0.04 * 0.03 * 2 * 30) < 1e-9
    nobody = W.route_coated_membership(set())
    assert W.coated_sheet_area_m2([bracket], nobody) == 0.0   # host not coated: no coat


def test_the_part_estimate_carries_the_coat_with_host_mark():
    import estimator as E
    pe = E.estimate_part({"part_number": "B1", "description": "bracket", "quantity": 2,
                          "normalized_material": "MILD STEEL", "normalized_thickness_mm": 2,
                          "blank_length_mm": 40, "blank_width_mm": 30,
                          "coated_with_host": ["T1"]}, job_quantity=10)
    assert pe.get("coated_with_host") == ["T1"]


def test_an_edging_counted_across_hosts_of_different_sizes_is_one_line_per_host():
    parts = cs.parts_from_concept(_fsdu(), "J")
    strips = [p for p in parts if "STRIP" in p["description"]]
    got = sorted((int(p["quantity"]), float(p["blank_length_mm"])) for p in strips)
    assert got == [(5, 300.0), (5, 300.0), (5, 460.0)]
    codes = {p["part_number"] for p in strips}
    assert "J-CPT09" in codes                              # the read's own code is kept
    assert all(p.get("strip_host") for p in strips)
    assert all(any("edging split per host" in str(f) for f in p["review_flags"])
               for p in strips)
    unit = cs.unit_assembly_part(parts, _fsdu(), "J")
    assert sum(int(p["quantity"]) for p in strips) == 15   # never more strips than shelves
    assert unit["pieces_fitted"] == 6 + 1 + 1 + 6 + 15 + 15


def test_an_edging_is_left_as_read_when_the_hosts_do_not_account_for_it():
    ans = _fsdu()
    ans["parts"][8]["quantity"] = 12                     # not the shelves' total
    strips = [p for p in cs.parts_from_concept(ans, "J") if "STRIP" in p["description"]]
    assert [(int(p["quantity"]), p["blank_length_mm"]) for p in strips] == [(12, 460.0)]


def _strips_after_approving(**approve):
    from source_precedence import apply_field, _source_key
    parts = cs.parts_from_concept(_fsdu(), "J")
    base = [p for p in parts if p.get("strip_host") and p["part_number"] == "J-CPT09"][0]
    for field, value in approve.items():
        base.pop(field, None)
        base.pop(_source_key(field), None)
        apply_field(base, field, value, "estimator_confirmed", note="estimator")
    dropped = cs.keep_approved_strip_lines(parts)
    strips = [p for p in parts if "STRIP" in p["description"]]
    return base, dropped, strips


def test_an_approved_count_for_the_whole_line_stands_whole():
    base, dropped, strips = _strips_after_approving(quantity=15)
    assert len(dropped) == 2 and strips == [base]
    assert sum(int(p["quantity"]) for p in strips) == 15        # the full count survives


def test_an_approval_short_of_the_whole_line_never_loses_the_other_hosts_strips():
    for approve in ({"quantity": 5}, {"blank_length_mm": 460.0}):
        base, dropped, strips = _strips_after_approving(**approve)
        assert dropped == [] and len(strips) == 3, approve
        assert sum(int(p["quantity"]) for p in strips) == 15, approve
        assert any("for this host only" in str(f) for f in base["review_flags"]), approve


def test_fixings_are_counted_per_mechanically_fitted_piece_when_the_read_names_none():
    parts = cs.parts_from_concept(_fsdu(), "J")
    mech = cs.mechanically_fitted(parts)
    # Counted: top cap 1, headers 6, strips 15. Welded post and plinth, the welded bracket,
    # and the trays that hang on it are not.
    assert mech["pieces"] == 1 + 6 + 15
    assert "hangs on" in " ".join(mech["excluded"].values())
    assert not cs.read_names_fixings(["QR labels"], parts)
    fx = cs.fixings_allowance_line(parts, "J", 2)
    per = config.CONCEPT_CONSUMABLE_ALLOWANCE["per_piece_fitted"]
    assert fx["quantity"] == per * 22 and fx["quantity_counted"]["count"] == per * 22
    assert fx["part_number"] == "J-NV02" and fx["unit_of_measure"] == "each"
    assert config.CONCEPT_CONSUMABLE_ALLOWANCE["reference_item"] in fx["description"]
    flag = fx["review_flags"][-1]
    assert "Counted:" in flag and "Not counted:" in flag and "Confirm" in flag


def test_handled_labelled_and_fastened_are_three_counts_each_with_its_basis():
    ans = _fsdu()
    ans["parts"].append({"name": "MAGNETIC GRAPHIC SET", "kind": "graphic", "quantity": 1})
    parts = cs.parts_from_concept(ans, "J")
    unit = cs.unit_assembly_part(parts, ans, "J")
    fc = unit["fitting_counts"]
    # Handled: every piece fitted at the unit, the 30 welded brackets with their trays.
    assert fc["handled"]["count"] == 6 + 1 + 1 + 6 + 15 + 15 + 1
    # Labelled: made components only — not the printed graphic, not the welded brackets.
    assert fc["labelled"]["count"] == fc["handled"]["count"] - 1
    # Fastened: never the welded post and plinth, the welded brackets or the hooked trays.
    assert fc["fastened"]["count"] == 1 + 6 + 15
    assert all(fc[k]["basis"] for k in fc)
    assert any("three counts" in str(f) for f in unit["review_flags"])
    (labels,) = cs.consumable_lines(["QR component labels"], "J",
                                    pieces_fitted=fc["handled"]["count"],
                                    components=fc["labelled"]["count"])
    assert labels["quantity"] == fc["labelled"]["count"]
    assert labels["items_to_apply"] == fc["labelled"]["count"]


def test_file_scan_counts_labels_on_labelled_components():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    at = src[src.index("_nv_lines = concept_scan.consumable_lines("):][:600]
    assert 'components=((_unit or {}).get("components_labelled")' in at


def test_a_read_that_names_fixings_gets_no_second_line_and_its_set_counts_fixed_pieces():
    parts = cs.parts_from_concept(_fsdu(), "J")
    assert cs.read_names_fixings(["fixings and fasteners for assembly"], parts)
    (fset,) = cs.consumable_lines(["fixings and fasteners for assembly"], "J",
                                  pieces_fitted=49, fixed_pieces=22)
    per = config.CONCEPT_CONSUMABLE_ALLOWANCE["per_piece_fitted"]
    assert fset["consumable_allowance"]["count"] == per * 22


def test_file_scan_mints_the_fixings_line_and_counts_the_set_on_fixed_pieces():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    at = src[src.index("_mech = concept_scan.mechanically_fitted(_sighted)"):][:1800]
    assert "fixed_pieces=" in at and "read_names_fixings" in at
    assert "fixings_allowance_line" in at
    assert "keep_approved_strip_lines(_sighted)" in src


def test_a_flat_claim_the_size_of_the_footprint_is_priced_with_its_flanges_and_kept():
    parts = _by(cs.parts_from_concept(_fsdu(), "J"))
    plinth, cap = parts["BASE / PLINTH"], parts["TOP CAP"]
    # The read's own 40 mm flange on the plinth; the house allowance on the cap.
    assert (plinth["blank_length_mm"], plinth["blank_width_mm"]) == (580.0, 580.0)
    house = config.CONCEPT_FLANGE_ALLOWANCE_MM
    assert cap["blank_length_mm"] == 500 + 2 * house
    for p in (plinth, cap):
        assert p["concept_read_blank_mm"]["length"] == 500.0    # the read's figure kept
        assert p["concept_blank_basis"] == "finished (by consistency)"
        assert any("CONCEPT CONSISTENCY" in str(f) for f in p["review_flags"])
    assert any("CONCEPT_FLANGE_ALLOWANCE_MM" in str(f) for f in cap["review_flags"])
    # A flat claim that is not the footprint is used as given.
    tray = parts["FRONT SHELF TRAY"]
    assert (tray["blank_length_mm"], tray["blank_width_mm"]) == (460.0, 300.0)
    assert not tray.get("concept_read_blank_mm")


def test_the_flange_allowance_reaches_material_cutting_and_coat_with_its_basis():
    """Not merely a flag: the developed blank is the blank the material is nested on, the
    perimeter the laser cuts (the Sheet Steel row's own length and width, plus any sighted
    cut-out) and the area the powder covers — and the working is on the assumption it sets."""
    import estimator as E
    import wb_populate as W
    ans = _fsdu()
    for p in ans["parts"]:
        if p["name"] == "TOP CAP":
            p["cutouts"] = [{"what": "opening", "count": 1, "length_mm": 200, "width_mm": 110}]
    parts = {p["description"]: p for p in cs.parts_from_concept(ans, "J")}
    plinth, cap = parts["BASE / PLINTH"], parts["TOP CAP"]
    pe = E.estimate_part(dict(plinth), job_quantity=200)
    me = pe["material_estimate"]
    assert (me["blank_length_mm"], me["blank_width_mm"]) == (580.0, 580.0)       # material
    area = W.coated_sheet_area_m2([pe], W.route_coated_membership(None))
    assert abs(area - 0.58 * 0.58 * 2) < 1e-9                                    # coat
    (a,) = [x for x in plinth["concept_assumptions"] if x["file_key"] == "blank_length_mm"]
    assert a["value"] == 580.0 and "40 mm each (the read's flange depth)" in a["cue"]
    house = config.CONCEPT_FLANGE_ALLOWANCE_MM
    side = 500 + 2 * house
    assert cap["manufacturing_features"]["cut_length_mm"] == round(
        2 * (side + side) + 2 * (200 + 110), 1)                                  # cutting
    (c,) = [x for x in cap["concept_assumptions"] if x["file_key"] == "blank_length_mm"]
    assert "CONCEPT_FLANGE_ALLOWANCE_MM" in c["cue"]


def test_a_finished_size_with_no_flange_takes_the_house_allowance_said():
    d = cs.developed_blank({"length": 400, "width": 300}, {"folds": 2, "blank_basis": "finished"})
    house = config.CONCEPT_FLANGE_ALLOWANCE_MM
    assert d["changed"] and d["width"] == 300 + 2 * house
    assert "CONCEPT_FLANGE_ALLOWANCE_MM" in d["working"]
    flat = cs.developed_blank({"length": 400, "width": 300},
                              {"folds": 2, "blank_basis": "developed"},
                              envelope={"width": 500, "depth": 500})
    assert not flat["changed"] and "used as given" in flat["working"]


def test_the_new_vocabulary_lives_in_config_and_holds_no_job():
    for name in ("CONCEPT_FIXING_WORDS", "CONCEPT_FIXING_FREE_WORDS",
                 "CONCEPT_WELDED_TO_WORDS", "CONCEPT_EDGE_STRIP_WORDS"):
        words = getattr(config, name)
        assert words and all(isinstance(w, str) for w in words)
    assert isinstance(config.CONCEPT_FLANGE_ALLOWANCE_MM, (int, float))
    rule = config.PROJECT_SCOPE_EVIDENCE
    assert {"categories", "per_order", "per_batch", "per_unit", "repeat_on_change"} <= set(rule)
    blob = repr([getattr(config, n) for n in (
        "CONCEPT_FIXING_WORDS", "CONCEPT_FIXING_FREE_WORDS", "CONCEPT_WELDED_TO_WORDS",
        "CONCEPT_EDGE_STRIP_WORDS", "PROJECT_SCOPE_EVIDENCE")]).lower()
    for job_word in ("boots", "wellness", "btc", "kwellness"):
        assert job_word not in blob


# ── D-500: the 20:49 book — volume pricing, the read's changes on the book, components named
#    inside another line, and the reviewer's four queued refinements ────────────────────────

def test_a_counted_item_is_asked_its_price_at_the_jobs_volume():
    import indicative_price as ip
    counted = {"description": "QR component label 20x20mm", "quantity": 48,
               "unit_of_measure": "each",
               "quantity_counted": {"count": 48, "basis": "1 per component × 48"}}
    b = ip.research_brief(counted, order_qty=200)
    assert b["volume_needed"] == 9600
    assert "= 9600 in all" in b["ask"] and "never a single-item retail listing" in b["ask"]
    plain = ip.research_brief({"description": "castor 75mm", "quantity": 4}, order_qty=200)
    assert "volume_needed" not in plain and "in all" not in plain["ask"]


def test_the_researcher_is_given_the_lines_count_basis():
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert '"quantity_counted": part.get("quantity_counted"),' in src
    fx = cs.fixings_allowance_line(cs.parts_from_concept(_fsdu(), "J"), "J", 2)
    assert "at this job's volume" in fx["research_description"]


def test_the_reads_changes_are_on_the_book_and_each_dropped_line_is_a_decision():
    flags = cs.change_flags(["added: TRAY x5", "dropped: HOOKED BRACKET (WELDED TO TRAY) x30",
                             "HEADER: count 3 → 6 (no reason given)"],
                            baseline="new interpretation with the previous bill")
    assert flags[0].startswith("CONCEPT READ: new interpretation")
    assert "a different read" in flags[0]
    assert any(f.startswith("CONCEPT READ CHANGED") and "HEADER: count 3 → 6" in f
               and "dropped" not in f for f in flags)
    (drop,) = [f for f in flags if f.startswith("DROPPED FROM THE PREVIOUS READ")]
    assert "HOOKED BRACKET (WELDED TO TRAY) x30" in drop and "material" in drop
    same = cs.change_flags([], baseline="unchanged read reused")
    assert same == ["CONCEPT READ: unchanged read reused — the same read as the previous "
                    "book; differences are the engine's"]
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    at = src[src.index("_unit = concept_scan.unit_assembly_part(_sighted, _answer, _job_name)"):]
    assert "concept_scan.change_flags(" in at[:900]


def test_a_component_named_inside_another_line_is_found_unless_listed_or_a_feature():
    lines = [{"name": "FRONT SHELF TRAY (with welded hooked brackets)"},
             {"name": "TOP CAP with graphic pass-through cut-out"},
             {"name": "SIDE PANEL with welded seams"},
             {"name": "HEADER"}]
    (hit,) = cs.components_named_inside(lines)
    assert hit["component"] == "bracket" and "welded hooked brackets" in hit["phrase"]
    listed = lines + [{"name": "HOOKED BRACKET"}]
    assert cs.components_named_inside(listed) == []


def test_the_sheet_check_puts_the_read_back_naming_the_folded_component():
    ans = {"product": {"name": "FSDU"}, "parts": [
        {"name": "FRONT SHELF TRAY (with welded hooked brackets)", "kind": "fabricated",
         "quantity": 5, "assumed_blank_mm": {"length": 460, "width": 300, "thickness": 1.5}}]}
    chk = cs.sheet_check(ans)
    assert chk["components_inside"] and not chk["agrees"]
    assert any("names welded hooked brackets but no line lists them" in f
               for f in chk["failures"])


def test_a_component_still_folded_in_is_a_question_with_the_previous_line_as_information():
    ans = _fsdu()
    ans["parts"] = [p for p in ans["parts"] if "BRACKET" not in p["name"]]
    for p in ans["parts"]:
        if p["name"] == "FRONT SHELF TRAY":
            p["name"] = "FRONT SHELF TRAY (with welded hooked brackets)"
    parts = cs.parts_from_concept(ans, "J")
    prev = {"parts": [{"name": "HOOKED BRACKET (WELDED TO TRAY)", "quantity": 30,
                       "length": 40, "width": 30}]}
    asked = cs.question_components_inside(parts, prev)
    assert len(asked) == 1
    tray = [p for p in parts if p["description"].startswith("FRONT SHELF TRAY")][0]
    (q,) = tray["manufacturing_questions"]
    text = str(q)
    assert "no line of the bill costs" in text and "not costed" in text
    assert "previous read listed HOOKED BRACKET (WELDED TO TRAY) x30 at 40 × 30 mm" in text
    assert "information only" in text
    assert not any(p["description"].startswith("HOOKED") for p in parts)   # nothing minted
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "concept_scan.question_components_inside(_sighted, _prev_bill)" in src


def test_a_bonded_piece_takes_no_screws_and_hung_pieces_carry_the_retainer_note():
    ans = _fsdu()
    for p in ans["parts"]:
        if "STRIP" in p["name"]:
            p["name"] = "35MM SHELF EDGE STRIP (bonded)"
    parts = cs.parts_from_concept(ans, "J")
    mech = cs.mechanically_fitted(parts)
    assert mech["pieces"] == 1 + 6                       # top cap and headers only
    assert any("bonded" in why for why in mech["excluded"].values())
    fx = cs.fixings_allowance_line(parts, "J", 2)
    assert "retainers or anti-lift clips" in fx["review_flags"][-1]


def test_the_label_scope_states_its_too_small_exception(monkeypatch):
    parts = cs.parts_from_concept(_fsdu(), "J")
    unit = cs.unit_assembly_part(parts, _fsdu(), "J")
    assert "no too-small exception applied" in unit["fitting_counts"]["labelled"]["basis"]
    monkeypatch.setattr(config, "CONCEPT_LABEL_MIN_FACE_MM", 40, raising=False)
    unit2 = cs.unit_assembly_part(parts, _fsdu(), "J")
    assert unit2["components_labelled"] == unit["components_labelled"] - 15   # 35 mm strips
    assert "too small to carry one" in unit2["fitting_counts"]["labelled"]["basis"]


def test_the_quantity_breaks_tab_says_when_one_batch_is_assumed(tmp_path):
    import openpyxl
    from quantity_breaks_tab import write_quantity_breaks_tab, SHEET_NAME
    swept = {"rows": [{"quantity": 1, "material": 10, "labour": 5, "unit": 20.0},
                      {"quantity": 200, "material": 10, "labour": 3, "unit": 16.0}]}

    def _tab(batch_size):
        p = tmp_path / f"b{batch_size}.xlsx"
        openpyxl.Workbook().save(p)
        pc = {"total_gbp": 450.0, "lines": [
            {"code": "PROJECT-05", "scope": "per_batch", "state": "provisional",
             "order_gbp": 450.0, "per_batch_gbp": 450.0, "batch_size": batch_size}]}
        write_quantity_breaks_tab(p, swept, requested=[200], project_costs=pc)
        ws = openpyxl.load_workbook(p)[SHEET_NAME]
        return " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert "ONE batch is taken at every quantity" in _tab(None)
    assert "ONE batch is taken" not in _tab(50)


def test_the_coat_is_net_of_the_openings_cut_through_it():
    import estimator as E
    import wb_populate as W
    g = cs.cutout_geometry({"cutouts": [{"what": "opening", "count": 1, "length_mm": 200,
                                         "width_mm": 110},
                                        {"what": "hole", "count": 4, "length_mm": 10}]})
    assert abs(g["open_area_mm2"] - (200 * 110 + 4 * 3.14159 / 4 * 100)) < 0.2
    ans = _fsdu()
    for p in ans["parts"]:
        if p["name"] == "TOP CAP":
            p["cutouts"] = [{"what": "opening", "count": 1, "length_mm": 200, "width_mm": 110}]
    cap = [p for p in cs.parts_from_concept(ans, "J") if p["description"] == "TOP CAP"][0]
    assert cap["concept_open_area_mm2"] == 22000.0
    pe = E.estimate_part(dict(cap), job_quantity=10)
    assert pe["concept_open_area_mm2"] == 22000.0
    L, Wd = pe["material_estimate"]["blank_length_mm"], pe["material_estimate"]["blank_width_mm"]
    area = W.coated_sheet_area_m2([pe], W.route_coated_membership(None))
    assert abs(area - ((L / 1000) * (Wd / 1000) - 0.022) * 2) < 1e-9
