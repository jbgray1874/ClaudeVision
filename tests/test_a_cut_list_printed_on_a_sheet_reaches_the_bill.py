"""A cut list printed on a part's own sheet reaches the bill, in full, with its cut — or the
book says which sheet's steel is not priced (D-576).

The contract and its proofs as proposed in the Codex review package of 21 Oct 2026, merged:
the rows are read by the engine's own section reader, and a failure is a BLOCKING invariant
on the book rather than a stopped run.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import engine_discoveries  # noqa: E402
import invariants  # noqa: E402
import section_coverage_contract as c  # noqa: E402


def fixture():
    p = {"part_number": "FRAME-X", "description": "WELDMENT", "quantity": 2,
         "is_assembly_parent": True, "canonical_kind": "assembly",
         "normalized_material": "MILD STEEL", "textual_operations": ["welding"],
         "surface_finishes": ["WELDED"],
         "section_stock": {"a": 20, "b": 50, "t": 2, "profile_form": "RHS", "length_mm": 703}}
    page = {"page_number": 3, "source_pdf_name": "test.pdf",
            "page_analysis": {"title_block": {"drawing_numbers": ["FRAME-X"]}},
            "pdfplumber_text": "ITEM DESCRIPTION LENGTH QTY\n"
            "1 50 x 20 x 2mm TUBE 703 1\n2 50 x 20 x 2mm TUBE 154 2\nWEIGHT: 2 kg"}
    return {"manufacturing_writeup": {"parts": [p]}, "pages": [page]}


def cost(length=1011, quantity=2, price=10):
    return {"part_number": "FRAME-X", "quantity": quantity,
            "material_estimate": {"unit_material_cost_gbp": price,
                                  "stock_estimate": {"section_length_mm": length}}}


class ContractTests(unittest.TestCase):
    def test_real_failure_shape_recovers_all_three_lengths(self):
        s = fixture()
        self.assertEqual(c.prepare(s), ["FRAME-X"])
        p = c.parts_of(s)[0]
        self.assertEqual(p["section_stock"]["cut_lengths_mm"], [154, 154, 703])
        self.assertFalse(p["is_assembly_parent"])
        self.assertEqual(p["canonical_kind"], "part")             # the record's vocabulary
        self.assertTrue(p["weldment_from_own_cut_list"])
        self.assertTrue(any("D-576" in str(f) for f in p["review_flags"]))
        self.assertEqual(p["quantity"], 2)
        self.assertEqual(p["textual_operations"], ["welding"])
        self.assertEqual(p["surface_finishes"], ["WELDED"])

    def test_idempotent_and_source_unchanged(self):
        s = fixture(); pages = copy.deepcopy(s["pages"])
        c.prepare(s); first = copy.deepcopy(s)
        self.assertEqual(c.prepare(s), [])
        self.assertEqual(s, first)
        self.assertEqual(s["pages"], pages)

    def test_real_children_prevent_parent_material_double_charge(self):
        s = fixture()
        c.parts_of(s).append({"part_number": "MEMBER", "bom_parent": "FRAME-X"})
        self.assertEqual(c.prepare(s), [])

    def test_multiple_profiles_never_combined(self):
        s = fixture(); s["pages"][0]["pdfplumber_text"] = s["pages"][0]["pdfplumber_text"].replace("154 2", "154 2").replace("2 50 x 20", "2 30 x 30")
        self.assertEqual(c.prepare(s), [])
        self.assertEqual(len(c.capture(s)["requirements"][0]["rows"]), 2)

    def test_no_title_block_no_repair(self):
        s = fixture(); s["pages"][0]["page_analysis"] = {}
        self.assertEqual(c.prepare(s), [])

    def test_reference_page_no_repair(self):
        s = fixture(); s["pages"][0]["document_role"] = "reference"
        self.assertEqual(c.prepare(s), [])

    def test_conflicting_pages_block(self):
        s = fixture(); page = copy.deepcopy(s["pages"][0])
        page["pdfplumber_text"] = page["pdfplumber_text"].replace("703", "999")
        s["pages"].append(page)
        self.assertEqual(c.prepare(s), [])
        c.record_coverage(s, [cost()])
        self.assertFalse(s["section_coverage_result"]["passed"])
        self.assertEqual(s["section_coverage_result"]["issues"][0]["code"], "conflicting_cut_lists")

    def test_bought_part_not_reclassified(self):
        s = fixture(); c.parts_of(s)[0]["is_bought_in"] = True
        self.assertEqual(c.prepare(s), [])

    def test_measured_flat_not_reclassified(self):
        s = fixture(); c.parts_of(s)[0]["dxf_measured_outline"] = True
        self.assertEqual(c.prepare(s), [])

    def test_unpriced_cannot_pass_with_geometry(self):
        s = fixture(); c.prepare(s)
        c.record_coverage(s, [cost(price=0)])
        self.assertFalse(s["section_coverage_result"]["passed"])
        self.assertEqual(s["section_coverage_result"]["issues"][0]["code"],
                         "section_material_coverage_mismatch")

    def test_first_length_only_cannot_pass(self):
        s = fixture(); c.prepare(s)
        issues = c.audit(s, [cost(length=703)])
        self.assertEqual(issues[0]["expected_mm_per_product"], 2022)
        self.assertEqual(issues[0]["priced_mm_per_product"], 1406)

    def test_correct_priced_length_passes(self):
        s = fixture(); c.prepare(s)
        self.assertEqual(c.audit(s, [cost()]), [])

    def test_overcount_is_not_accepted_as_coverage(self):
        s = fixture(); c.prepare(s)
        self.assertTrue(c.audit(s, [cost(length=2022)]))

    def test_graph_quantity_not_local_quantity(self):
        s = fixture(); c.prepare(s)
        s["canonical_route_shadow"] = {"nodes": [{"part_number": "FRAME-X", "qty_per_unit": 2}]}
        issues = c.audit(s, [cost(quantity=1)])
        self.assertTrue(any(i["code"] == "section_material_coverage_mismatch" for i in issues))

    def test_cut_must_survive_compiler(self):
        s = fixture(); c.prepare(s)
        s["canonical_route_shadow"] = {"nodes": [{"part_number": "FRAME-X", "qty_per_unit": 2}], "priced_route_rows": []}
        self.assertEqual(c.audit(s, [cost()])[0]["code"], "section_cut_missing_from_final_route")
        s["canonical_route_shadow"]["priced_route_rows"] = [{"operation": "saw", "target_id": "FRAME-X"}]
        self.assertEqual(c.audit(s, [cost()]), [])

    def test_non_cutlist_job_unchanged(self):
        s = fixture(); s["pages"][0]["pdfplumber_text"] = "Assemble with screws."
        original = copy.deepcopy(c.parts_of(s))
        c.prepare(s)
        self.assertEqual(c.parts_of(s), original)
        self.assertEqual(c.audit(s, []), [])

    def test_invalid_tables_rejected(self):
        for line in ["1 20 x 20 x 12mm TUBE 50 1", "1 20 x 20 x 2mm TUBE 0 1",
                     "1 20 x 20 x 2mm TUBE 50 0", "2 20 x 20 x 2mm TUBE 50 1",
                     "1 20 x 20 x 2mm TUBE ??? 1"]:
            with self.subTest(line=line):
                self.assertIn("error", c.parse_table("ITEM DESCRIPTION LENGTH QTY\n" + line))

    def test_duplicate_pages_do_not_double_requirements(self):
        s = fixture(); s["pages"].append(copy.deepcopy(s["pages"][0]))
        self.assertEqual(len(c.capture(s)["requirements"]), 1)

    def test_estimator_approved_schedule_never_overwritten(self):
        import source_precedence as sp
        s = fixture(); p = c.parts_of(s)[0]
        sp.apply_field(p, "section_stock.cut_lengths_mm", [900], "estimator_confirmed")
        self.assertEqual(c.prepare(s), [])
        self.assertEqual(p["section_stock"]["cut_lengths_mm"], [900])
        self.assertEqual(s["section_coverage_contract"]["issues"][0]["code"], "stronger_section_conflict")

    def test_lost_or_extra_child_length_is_detected(self):
        s = fixture(); parent = c.parts_of(s)[0]
        parent["assembly_children"] = ["CUT-A"]
        c.parts_of(s).append({"part_number": "CUT-A", "cut_list_member_of": "FRAME-X",
                             "section_stock": {"a": 50, "b": 20, "t": 2, "profile_form": "RHS"}})
        c.prepare(s)
        child_cost = cost(); child_cost["part_number"] = "CUT-A"
        self.assertEqual(c.audit(s, [cost(price=0), child_cost]), [])
        child_cost["quantity"] = 1
        self.assertTrue(c.audit(s, [cost(price=0), child_cost]))

    def test_deleted_owner_is_not_ignored(self):
        s = fixture(); c.prepare(s)
        self.assertEqual(c.audit(s, [])[0]["code"], "section_owner_missing_from_costing")



class TheBookSaysSo(unittest.TestCase):
    """The audit's findings reach the book as a BLOCKING invariant, classified as ours."""

    def test_the_invariant_raises_the_audits_findings_blocking(self):
        s = fixture(); c.prepare(s)
        c.record_coverage(s, [cost(length=703)])
        found = invariants.check_a_section_schedule_reaches_the_sheet(s)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["code"], "section_schedule_not_priced")
        self.assertEqual(found[0]["severity"], invariants.BLOCKING)
        self.assertIn("2022 mm of 20x50x2 section a product on the sheet, 1406 mm priced", found[0]["message"])
        self.assertIn("sheet 3", found[0]["message"])

    def test_the_invariant_audits_itself_when_no_hand_off_ran(self):
        s = fixture(); c.prepare(s)
        s["estimate_summary"] = {"canonical_part_estimates": [cost()]}
        self.assertEqual(invariants.check_a_section_schedule_reaches_the_sheet(s), [])
        s["estimate_summary"] = {"canonical_part_estimates": [cost(length=703)]}
        self.assertEqual(invariants.check_a_section_schedule_reaches_the_sheet(s)[0]["code"],
                         "section_schedule_not_priced")

    def test_a_pack_with_no_headed_table_raises_nothing(self):
        s = fixture(); s["pages"][0]["pdfplumber_text"] = "Assemble with screws."
        self.assertEqual(invariants.check_a_section_schedule_reaches_the_sheet(s), [])

    def test_the_check_is_registered_and_the_code_is_ours(self):
        self.assertIn(invariants.check_a_section_schedule_reaches_the_sheet, invariants.CHECKS)
        self.assertIn("section_schedule_not_priced", engine_discoveries._OURS)

    def test_the_rows_are_read_by_the_engines_own_section_reader(self):
        got = c.parse_table("ITEM DESCRIPTION LENGTH QTY\n1 30.00 x 30.00 x 2.00mm TUBE 1220 2\n"
                            "2 50 x 20 x 2mm RHS 154 1")
        self.assertEqual([r["profile"] for r in got["rows"]],
                         [[30.0, 30.0, 2.0, "SHS"], [20.0, 50.0, 2.0, "RHS"]])
        self.assertEqual([r["length_mm"] for r in got["rows"]], [1220.0, 154.0])

    def test_nothing_here_names_a_job(self):
        """The job number lives in the module's docstring and comments, never in its logic."""
        src = (Path(__file__).resolve().parents[1] / "src" / "section_coverage_contract.py").read_text(encoding="utf-8")
        body = src.split('"""', 2)[2]                                   # after the module docstring
        logic = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
        self.assertNotIn("401918", logic)
        self.assertNotIn("07M", logic)

if __name__ == "__main__": unittest.main()
