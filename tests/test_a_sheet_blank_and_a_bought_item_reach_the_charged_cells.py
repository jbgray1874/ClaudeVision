"""A sheet blank and a bought item reach the charged cells of the calculated workbook, a
quantity is multiplied along its own edges once, and a unit is a stated thing (D-582).

The contract and its proofs as proposed in the Codex review package of 22 Oct 2026 (accuracy
contracts), merged on the engine's terms: the commercial exclusion reads the engine's own
`commercial_line` flag, the rollout mode lives in config with an environment override, the
findings reach one BLOCKING invariant beside the section check, and nothing here names a job.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import material_charge_contract as mcc  # noqa: E402
import quantity_flow_contract as qfc  # noqa: E402
from quantity_flow_contract import convert  # noqa: E402

audit = mcc.audit
quantity_audit = qfc.audit


def fixture():
    nodes = [dict(part_number="ROOT", kind="assembly", qty_per_unit=1, qty_by_parent={}, parents=[]),
             dict(part_number="SUB", kind="assembly", qty_per_unit=2, qty_by_parent={"ROOT": 2}, parents=["ROOT"]),
             dict(part_number="SHEET", kind="leaf", qty_per_unit=4, qty_by_parent={"SUB": 4}, parents=["SUB"]),
             dict(part_number="BOLT", kind="bought_in", qty_per_unit=6,
                  qty_by_parent={"ROOT": 2, "SUB": 4}, parents=["ROOT", "SUB"])]
    parts = [dict(part_number=n["part_number"], quantity=n["qty_per_unit"], unit_of_measure="each")
             for n in nodes]
    parts[1]["bom_parents"] = [dict(parent="ROOT", qty=2)]
    parts[2]["bom_parents"] = [dict(parent="SUB", qty=2)]
    parts[3]["bom_parents"] = [dict(parent="ROOT", qty=2), dict(parent="SUB", qty=2)]
    parts[2]["material_estimate"] = dict(stock_form="sheet", blank_length_mm=100,
                                         blank_width_mm=50, thickness_mm=2)
    parts[3]["purchase_basis"] = dict(required_unit="each", price_unit="pack",
                                      units_per_purchase=100, price_gbp=20, rounding="proportional")
    rows = [dict(part_code="SHEET", description="SHEET panel", block="steel", qty_per_unit=4,
                 length_mm=100, width_mm=50, gauge=2, qty_per_sheet=100,
                 sheet_length_mm=1000, sheet_width_mm=500, sheet_price_gbp=40,
                 sheet_charge_policy="fractional_sheet", scrap_pct=.04, total_value_gbp=1.664,
                 charged_cell="Estimate!M10"),
            dict(part_code="BOLT", description="BOLT", block="bom", qty_per_unit=6,
                 unit_price_gbp=.2, scrap_pct=.04, total_value_gbp=1.248, charged_cell="Estimate!M11")]
    d = dict(estimate_summary=dict(canonical_route_shadow=dict(product_root="ROOT", nodes=nodes),
                                   canonical_part_estimates=parts),
             final_estimate=dict(source="excel_calculated", material_rows=rows,
                                 totals=dict(material_gbp=2.912)))
    cells = {}
    for i, r in enumerate(rows, 10):
        r["evidence_cells"] = {}
        for j, field in enumerate(("part_code", "qty_per_unit"), 1):
            addr = f"Estimate!{chr(64 + j)}{i}"
            r["evidence_cells"][field] = addr
            cells[addr] = r[field]
        cells[r["charged_cell"]] = r["total_value_gbp"]
    return d, dict(cells=cells, sha256="synthetic")


class AQuantityIsMultipliedOnceAlongItsOwnEdges(unittest.TestCase):
    def test_the_compiler_says_what_its_two_quantities_are(self):
        from dataclasses import fields
        from route_compiler import PartNode
        defaults = {f.name: f.default for f in fields(PartNode)}
        self.assertEqual(defaults["qty_per_unit_basis"], "per_finished_product")
        self.assertEqual(defaults["qty_by_parent_basis"], "rolled_contribution_per_finished_product")

    def test_a_rolled_contribution_is_not_multiplied_by_its_parent_again(self):
        d, _ = fixture()
        trace = {r["part"]: r for r in quantity_audit(d)["trace"]}
        self.assertEqual(trace["BOLT"]["rolled_per_product"], 6)
        self.assertEqual(trace["SHEET"]["rolled_per_product"], 4)

    def test_a_child_under_two_parents_is_the_sum_of_its_paths(self):
        d, _ = fixture()
        self.assertTrue(quantity_audit(d)["passed"], quantity_audit(d))

    def test_a_continuous_quantity_keeps_its_fraction(self):
        self.assertEqual(convert(3192, "mm", "m"), 3.192)
        self.assertEqual(convert(.5, "m", "m"), .5)

    def test_a_pack_is_not_each(self):
        self.assertEqual(convert(6, "each", "pack", 100), .06)
        with self.assertRaises(ValueError):
            convert(6, "each", "pack")

    def test_incompatible_units_are_refused(self):
        for a, b in [("m", "kg"), ("m2", "m"), ("unknown", "each")]:
            with self.assertRaises(ValueError):
                convert(1, a, b)

    def test_numeric_text_a_bool_nan_and_a_negative_are_not_quantities(self):
        for q in ("3", True, float("nan"), -1):
            with self.assertRaises(ValueError):
                convert(q, "m", "m")

    def test_each_way_the_graph_can_be_broken_is_a_finding(self):
        cases = [
            ("quantity_rollup_mismatch", lambda d: d["estimate_summary"]["canonical_part_estimates"][2].update(quantity=8)),
            ("quantity_parent_missing", lambda d: d["estimate_summary"]["canonical_part_estimates"][2].update(bom_parents=[dict(parent="MISSING", qty=2)])),
            ("quantity_cycle", lambda d: d["estimate_summary"]["canonical_part_estimates"][1].update(bom_parents=[dict(parent="SHEET", qty=2)])),
            ("canonical_price_record_missing", lambda d: d["estimate_summary"].update(canonical_part_estimates=[])),
            ("duplicate_or_missing_identity", lambda d: d["estimate_summary"]["canonical_part_estimates"].append(copy.deepcopy(d["estimate_summary"]["canonical_part_estimates"][2]))),
            ("parent_edge_disagreement", lambda d: d["estimate_summary"]["canonical_route_shadow"]["nodes"][2].update(parents=[])),
            ("quantity_unit_unknown", lambda d: d["estimate_summary"]["canonical_part_estimates"][3].update(unit_of_measure="mystery"))]
        for code, mutate in cases:
            with self.subTest(code=code):
                d, _ = fixture()
                mutate(d)
                self.assertIn(code, {i["code"] for i in quantity_audit(d)["issues"]})

    def test_half_of_an_each_is_a_finding(self):
        d, _ = fixture()
        d["estimate_summary"]["canonical_part_estimates"][3]["quantity"] = .5
        self.assertIn("fractional_discrete_quantity", {i["code"] for i in quantity_audit(d)["issues"]})

    def test_an_empty_canonical_population_is_a_finding_not_a_fallback(self):
        d, _ = fixture()
        d["estimate_summary"]["part_estimates"] = d["estimate_summary"]["canonical_part_estimates"]
        d["estimate_summary"]["canonical_part_estimates"] = []
        self.assertIn("canonical_price_record_missing", {i["code"] for i in quantity_audit(d)["issues"]})

    def test_a_commercial_line_is_not_an_occurrence_in_the_product(self):
        """A packaging stub outside the graph is not a record outside the graph."""
        d, s = fixture()
        d["estimate_summary"]["canonical_part_estimates"].append(
            dict(part_number="PACKAGING", quantity=1, commercial_line={"code": "PACKAGING"}))
        self.assertTrue(quantity_audit(d)["passed"], quantity_audit(d)["issues"])
        self.assertTrue(audit(d, s)["passed"], audit(d, s))


class ACommercialLineIsReadByItsOwnerWhateverMarkItsMintLeft(unittest.TestCase):
    """The stub is minted on more than one path and each leaves its own mark: the component
    guard's `_commercial_line = True`, the priced `commercial_line` dict, the placeholder marks.
    One reader in commercial_lines knows them all; the contracts and the two line classifiers
    ask it rather than testing one key each."""

    PACKAGING_GUARD = dict(part_number="PACKAGING", quantity=1, _commercial_line=True,
                           description="Packaging (box / pallet — per-unit share)")
    PACKAGING_PRICED = dict(part_number="PACKAGING", quantity=1,
                            commercial_line={"code": "PACKAGING", "unit_gbp": 2.1})
    DELIVERY_EXCLUDED = dict(part_number="DELIVERY", quantity=1, unit_cost_gbp=0.0,
                             commercial_line={"code": "DELIVERY", "state": "excluded", "unit_gbp": 0.0})
    PLACEHOLDER = dict(part_number="DELIVERY", quantity=1, source="commercial_placeholder")
    PLACEHOLDER_MARK = dict(part_number="DELIVERY", quantity=1, _commercial_placeholder=True)
    BOUGHT = dict(part_number="FIXING1", quantity=6, is_bought_in=True,
                  description="M8 bolt, supplied on a pallet of 500")

    def test_every_mark_is_commercial_and_a_bought_item_is_not(self):
        from commercial_lines import is_commercial_line
        for rec in (self.PACKAGING_GUARD, self.PACKAGING_PRICED, self.DELIVERY_EXCLUDED,
                    self.PLACEHOLDER, self.PLACEHOLDER_MARK):
            with self.subTest(rec=rec):
                self.assertTrue(is_commercial_line(rec))
                self.assertTrue(qfc.is_commercial(rec))
        self.assertFalse(is_commercial_line(self.BOUGHT))       # the word "pallet" is not the test
        self.assertFalse(is_commercial_line({"commercial_line": {}}))
        self.assertFalse(is_commercial_line({"_commercial_line": "yes"}))
        self.assertFalse(is_commercial_line(None))

    def test_the_contracts_exclude_each_shape_and_still_audit_the_bought_item(self):
        for stub in (self.PACKAGING_GUARD, self.PACKAGING_PRICED, self.DELIVERY_EXCLUDED, self.PLACEHOLDER):
            with self.subTest(stub=stub["part_number"], marks=sorted(k for k in stub if "commercial" in k or k == "source")):
                d, s = fixture()
                parts = d["estimate_summary"]["canonical_part_estimates"]
                nodes = d["estimate_summary"]["canonical_route_shadow"]["nodes"]
                parts.append(copy.deepcopy(stub))
                # Hung on the graph as a bought-in by a reader that did not know better: the
                # contract still must not demand a charged row for it or an edge to the root.
                nodes.append(dict(part_number=stub["part_number"], kind="bought_in", qty_per_unit=1,
                                  qty_by_parent={}, parents=[]))
                result = audit(d, s)
                self.assertTrue(result["passed"], result["issues"] + result["unverified"])
                self.assertNotIn(stub["part_number"], {t["part"] for t in result["trace"]})
                self.assertIn("BOLT", {t["part"] for t in result["trace"]})
        # And the ordinary bought item IS audited: take its row away and the contract says so.
        d, s = fixture()
        d["final_estimate"]["material_rows"].pop(1)
        self.assertIn(("material_row_missing_or_duplicate", "BOLT"),
                      {(i["code"], i["part"]) for i in audit(d, s)["issues"]})

    def test_the_line_classifiers_ask_the_same_reader(self):
        from costed_facts import _line_kind
        from display_material import _kind_from_part as _kind_of
        for rec in (self.PACKAGING_GUARD, self.DELIVERY_EXCLUDED, self.PLACEHOLDER):
            with self.subTest(rec=rec["part_number"], marks=[k for k in rec if "commercial" in k or k == "source"]):
                self.assertEqual(_line_kind(dict(rec, part_number="X-LINE"), None), "commercial")
                self.assertEqual(_kind_of(dict(rec, part_number="X-LINE")), "commercial")
        self.assertNotEqual(_line_kind(self.BOUGHT, None), "commercial")


class ASheetBlankAndABoughtItemReachTheChargedCells(unittest.TestCase):
    def test_a_complete_record_passes_and_is_left_as_it_was(self):
        d, s = fixture()
        before = copy.deepcopy(d)
        self.assertTrue(audit(d, s)["passed"], audit(d, s))
        self.assertEqual(d, before)

    def test_each_way_a_sheet_row_can_be_wrong_is_a_mismatch(self):
        cases = [("material_row_missing_or_duplicate", lambda rows: rows.pop(0)),
                 ("material_row_missing_or_duplicate", lambda rows: rows.append(copy.deepcopy(rows[0]))),
                 ("sheet_gauge_mismatch", lambda rows: rows[0].update(gauge=3)),
                 ("sheet_blank_mismatch", lambda rows: rows[0].update(length_mm=200)),
                 ("sheet_yield_invalid", lambda rows: rows[0].update(qty_per_sheet=0)),
                 ("sheet_yield_exceeds_geometric_capacity", lambda rows: rows[0].update(qty_per_sheet=101)),
                 ("sheet_charge_arithmetic_mismatch", lambda rows: rows[0].update(total_value_gbp=2)),
                 ("material_quantity_mismatch", lambda rows: rows[0].update(qty_per_unit=8)),
                 ("sheet_written_to_wrong_block", lambda rows: rows[0].update(block="bom"))]
        for code, mutate in cases:
            with self.subTest(code=code):
                d, s = fixture()
                mutate(d["final_estimate"]["material_rows"])
                self.assertIn(code, {i["code"] for i in audit(d, s)["issues"]})

    def test_a_rotated_blank_is_the_same_blank(self):
        d, s = fixture()
        d["final_estimate"]["material_rows"][0].update(length_mm=50, width_mm=100)
        self.assertNotIn("sheet_blank_mismatch", {i["code"] for i in audit(d, s)["issues"]})

    def test_each_way_a_bought_row_can_be_wrong_is_a_finding(self):
        cases = [("purchase_rate_conversion_mismatch", lambda r: r.update(unit_price_gbp=20)),
                 ("bought_charge_arithmetic_mismatch", lambda r: r.update(total_value_gbp=20)),
                 ("material_not_charged", lambda r: r.update(total_value_gbp=0)),
                 ("material_quantity_mismatch", lambda r: r.update(qty_per_unit=12)),
                 ("material_total_unverified", lambda r: r.update(total_value_gbp="1.248"))]
        for code, mutate in cases:
            with self.subTest(code=code):
                d, s = fixture()
                mutate(d["final_estimate"]["material_rows"][1])
                result = audit(d, s)
                self.assertIn(code, {i["code"] for i in result["issues"] + result["unverified"]})

    def test_a_bought_item_needs_no_cutting_row(self):
        d, s = fixture()
        d["final_estimate"]["labour_rows"] = []
        self.assertTrue(audit(d, s)["passed"], audit(d, s))

    def test_a_missing_purchase_basis_is_unverified_not_each(self):
        d, s = fixture()
        del d["estimate_summary"]["canonical_part_estimates"][3]["purchase_basis"]
        result = audit(d, s)
        self.assertFalse(result["passed"])
        self.assertIn("purchase_unit_basis_missing", {i["code"] for i in result["unverified"]})
        self.assertNotIn("purchase_unit_basis_missing", {i["code"] for i in result["issues"]})

    def test_a_missing_sheet_price_is_not_recovered_from_the_charge(self):
        d, s = fixture()
        del d["final_estimate"]["material_rows"][0]["sheet_price_gbp"]
        result = audit(d, s)
        self.assertFalse(result["passed"])
        self.assertIn("sheet_price_basis_missing", {i["code"] for i in result["unverified"]})
        self.assertNotIn("sheet_charge_arithmetic_mismatch", {i["code"] for i in result["issues"]})

    def test_an_unstated_sheet_charge_policy_is_not_guessed(self):
        d, s = fixture()
        del d["final_estimate"]["material_rows"][0]["sheet_charge_policy"]
        self.assertIn("sheet_charge_policy_missing", {i["code"] for i in audit(d, s)["unverified"]})

    def test_a_saved_cell_that_disagrees_with_the_read_back_is_a_mismatch(self):
        d, s = fixture()
        s["cells"]["Estimate!B10"] = 400
        self.assertIn("saved_material_input_mismatch", {i["code"] for i in audit(d, s)["issues"]})

    def test_no_saved_workbook_is_not_a_pass(self):
        d, _ = fixture()
        result = audit(d)
        self.assertFalse(result["passed"])
        self.assertIn("saved_workbook_not_verified", {i["code"] for i in result["unverified"]})


class TheModeIsConfigsWordAndTheReleaseIsHeldOnlyWhenEnforced(unittest.TestCase):
    def test_the_shipped_mode_is_shadow(self):
        from config import ACCURACY_CONTRACT
        self.assertEqual(ACCURACY_CONTRACT["mode"], "shadow")
        with patch.dict(os.environ, {"SDI_ACCURACY_CONTRACT_MODE": ""}):
            self.assertEqual(mcc.mode(), "shadow")

    def test_the_environment_overrides_config_on_one_machine(self):
        with patch.dict(os.environ, {"SDI_ACCURACY_CONTRACT_MODE": "Enforce"}):
            self.assertEqual(mcc.mode(), "enforce")

    def test_a_misspelt_mode_is_enforce_with_a_finding(self):
        d, s = fixture()
        with patch.dict(os.environ, {"SDI_ACCURACY_CONTRACT_MODE": "shadwo"}):
            result = mcc.record(d)
        self.assertEqual(result["mode"], "enforce")
        self.assertIn("invalid_accuracy_contract_mode", {i["code"] for i in result["issues"]})

    def test_shadow_records_the_result_and_raises_nothing(self):
        from invariants import check_a_sheet_blank_and_a_bought_item_reach_the_charged_cells as check
        d, _ = fixture()
        with patch.dict(os.environ, {"SDI_ACCURACY_CONTRACT_MODE": "shadow"}):
            result = mcc.record(d)
            self.assertIs(d["material_charge_result"], result)
            self.assertFalse(result["passed"])             # no workbook: unverified, recorded
            self.assertEqual(check(d), [])
            self.assertEqual(check({}), [])

    def test_enforce_holds_the_release_through_the_existing_gate(self):
        from invariants import BLOCKING, check_a_sheet_blank_and_a_bought_item_reach_the_charged_cells as check
        held = dict(mode="enforce", passed=False, unverified=[],
                    issues=[dict(part="SHEET", code="material_row_missing_or_duplicate", count=0, category="sheet")])
        with patch.dict(os.environ, {"SDI_ACCURACY_CONTRACT_MODE": "enforce"}):
            out = check({"material_charge_result": held})
            self.assertEqual(out[0]["code"], "material_quantity_charge_unverified")
            self.assertEqual(out[0]["severity"], BLOCKING)
            self.assertIn("SHEET", out[0]["message"])
            # A check that did not run is not a pass.
            self.assertEqual(check({})[0]["code"], "material_quantity_charge_unverified")
            # Unverified evidence holds the release too — that is what enforce means.
            gaps = dict(mode="enforce", passed=False, issues=[],
                        unverified=[dict(part="BOLT", code="purchase_unit_basis_missing")])
            self.assertTrue(check({"material_charge_result": gaps}))
            clean = dict(mode="enforce", passed=True, issues=[], unverified=[])
            self.assertEqual(check({"material_charge_result": clean}), [])

    def test_the_finding_is_the_engines_own(self):
        from engine_discoveries import _OURS
        from invariants import CHECKS, check_a_sheet_blank_and_a_bought_item_reach_the_charged_cells as check
        self.assertIn("material_quantity_charge_unverified", _OURS)
        self.assertIn(check, CHECKS)

    def test_the_contract_is_run_in_main_after_the_final_charge_check(self):
        text = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
        fc = text.index("from final_charge_contract import record")
        mc = text.index("from material_charge_contract import record")
        inv = text.index("_inv = _check_job(_target)")
        self.assertLess(fc, mc)
        self.assertLess(mc, inv)

    def test_the_read_back_carries_the_sheet_price_headers_and_the_evidence_cells(self):
        import wep_readback_from_xlsx as rb
        self.assertEqual(rb._SHEET_HEADER_KEYS["cost per sheet"], "sheet_price_gbp")
        self.assertEqual(rb._SHEET_HEADER_KEYS["sheet length"], "sheet_length_mm")
        self.assertEqual(rb._SHEET_HEADER_KEYS["sheet width"], "sheet_width_mm")
        text = Path(rb.__file__).read_text(encoding="utf-8")
        self.assertIn('row["evidence_cells"]', text)

    def test_the_service_does_not_import_the_contract(self):
        """Engine-only modules stay off the server push list; the runner spawns main per job."""
        ps1 = (ROOT / "tools" / "start" / "push-to-server.ps1").read_text(encoding="utf-8")
        self.assertNotIn("material_charge_contract", ps1)
        self.assertNotIn("quantity_flow_contract", ps1)


if __name__ == "__main__":
    unittest.main()
