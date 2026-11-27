"""An operation carries the words it was read from, and a section is cut once (D-586).

The 0351292 midfloor rail's saved record showed four engine failures the slice named:
a strip welded and folded by decisions that said "a note on the drawing" while quoting
nothing; rails and arms priced from stock lengths with no cutting labour because no saw
was NAMED; the supports' powder coat ruled out by a finish field holding several other
parts' rows; and the root assembly's legitimate roll-up reported as two costing defects.

The rules under test are generic: evidence belongs to the row or sheet that printed it,
repeating an operation never promotes it into a drawing instruction, a made member cut
from stock is cut, and a contract that verified nothing says coverage, not acceptance.
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as E  # noqa: E402
import final_charge_contract as fcc  # noqa: E402
import finish_rules as fr  # noqa: E402
import merge_boms as mb  # noqa: E402
import quantity_flow_contract as qfc  # noqa: E402
import route_compiler as rc  # noqa: E402
from extractor_patterns import operation_evidence_in_text  # noqa: E402

_BLOB = ("ROL2021-2468 ROL2021-2468 SEEDWGS-EPCGRAPHITERAL7024SATINFINISH ROL2021-2467 "
         "ROL2021-2467 SEEDWGS-EPCGRAPHITERAL7024SATINFINISH ROL2021-2466 ROL2021-2466 "
         "STAINLESSSTEEL-BRUSHED 3MM ROL2021-2406 ROL2021-2406 STEEL 651.02.909 "
         "651.02.909 MILDSTEEL DIN7991-M3 X 10 STEEL ISO7380-1-M8X16 STEEL,MILD DIN7980-8")


# ── the words travel with the operation ──────────────────────────────────────────────────

class AnInferredOperationQuotesTheSheet(unittest.TestCase):
    def test_a_cue_in_the_text_is_quoted(self):
        ev = operation_evidence_in_text(
            "NOTE: FOLD ALONG DASHED LINE. TIG WELD UNDERSIDE.", ["folding", "welding"])
        self.assertIn("FOLD", ev["folding"])
        self.assertIn("TIG WELD", ev["welding"])

    def test_an_operation_with_no_cue_gets_no_quote(self):
        ev = operation_evidence_in_text("REMOVE ANY SHARP CORNERS AND EDGES",
                                        ["welding", "folding", "deburring"])
        self.assertNotIn("welding", ev)
        self.assertNotIn("folding", ev)
        self.assertIn("deburring", ev)

    def test_the_legend_is_not_evidence(self):
        ev = operation_evidence_in_text(
            "WELD SPECIFICATION: ALL WELDS TO BE TIG UNLESS STATED", ["welding"])
        self.assertNotIn("welding", ev)


def _compile_one(part):
    extract = {"top_assembly": {"part_number": "J-GA"},
               "assemblies": [{"part_number": "J-GA",
                               "children": [{"part_number": part["part_number"], "qty": 1}]}]}
    parts = [{"part_number": "J-GA", "description": "RAIL ASSY"}, part]
    graph = rc.compile_job_route(parts, extract)
    return [d if isinstance(d, dict) else d.__dict__ for d in (graph.get("decisions") or [])]


class AnUnsourcedOperationIsNotANote(unittest.TestCase):
    def _weld_decision(self, part):
        ds = [d for d in _compile_one(part)
              if d.get("operation") == "welding" and d.get("target_id") == part["part_number"]]
        self.assertTrue(ds, "no welding decision compiled")
        return ds[0]

    def test_no_source_and_no_words_is_an_honest_unknown(self):
        d = self._weld_decision({"part_number": "J-06M", "description": "ANTI SCRATCH STRIP",
                                 "textual_operations": ["welding"]})
        self.assertEqual(d.get("source"), "unrecorded")
        self.assertIn("priced, not promoted", str(d.get("reason")))

    def test_the_parts_own_stated_finish_is_evidence_for_its_coat(self):
        ds = [d for d in _compile_one(
            {"part_number": "J-GA2", "description": "DOOR", "quantity": 1,
             "normalized_finish": "POWDER COATED",
             "textual_operations": ["powder_coating"]})
            if d.get("operation") == "powder_coating" and d.get("target_id") == "J-GA2"]
        self.assertTrue(ds)
        self.assertEqual(ds[0].get("source"), "drawing_notes")
        self.assertIn("POWDER COATED", str(ds[0].get("evidence")))

    def test_recorded_words_keep_the_note_and_ride_on_the_decision(self):
        d = self._weld_decision({"part_number": "J-06M", "description": "ANTI SCRATCH STRIP",
                                 "textual_operations": ["welding"],
                                 "operation_evidence": {"welding": "TIG WELD UNDERSIDE"}})
        self.assertEqual(d.get("source"), "drawing_notes")
        self.assertIn("TIG WELD UNDERSIDE", str(d.get("evidence")))

    def test_a_recorded_source_is_untouched(self):
        d = self._weld_decision({"part_number": "J-06M", "description": "ANTI SCRATCH STRIP",
                                 "textual_operations": ["welding"],
                                 "operation_sources": {"welding": "llm_full_extract"}})
        self.assertEqual(d.get("source"), "llm_full_extract")


class AnOperationNameNeverReTriggersItself(unittest.TestCase):
    def test_the_normaliser_infers_from_notes_not_from_op_names(self):
        from json_normaliser import normalise_json
        raw = {"parts": [{"part_number": "J-06M", "process_notes": [],
                          "textual_operations": ["welding"]}]}
        out = normalise_json(raw)
        ops = out["parts"][0]["textual_operations"]
        self.assertEqual(ops, ["welding"], "the op name alone must add nothing")


# ── a finish statement is one part's phrase, not a page ──────────────────────────────────

class AFinishBelongsToTheRowThatPrintedIt(unittest.TestCase):
    def test_a_page_of_rows_is_not_a_stated_finish(self):
        self.assertTrue(fr.holds_drawing_text(_BLOB))
        self.assertEqual(fr.stated_finish({"normalized_finish": _BLOB}), "")

    def test_another_rows_brushed_rules_nothing_out(self):
        self.assertIsNone(fr.finish_contradiction("powder_coating", _BLOB))

    def test_a_legend_heading_states_nothing(self):
        self.assertEqual(fr.stated_finish({"normalized_finish": "SPECIFICATIONS:"}), "")

    def test_a_real_statement_still_reads(self):
        self.assertEqual(fr.stated_finish({"normalized_finish": "Powder Coated RAL 9010"}),
                         "POWDER COATED RAL 9010")
        self.assertIsNotNone(fr.finish_contradiction("powder_coating", "BRUSHED"))

    def test_epc_is_a_powder_statement(self):
        text = "SEE DWGS - EPC GRAPHITE RAL7024 SATIN FINISH"
        self.assertIn("powder", fr.finish_families(text))
        self.assertIsNone(fr.finish_contradiction("powder_coating", text))

    def test_the_census_asks_the_same_reader(self):
        from invariants import _looks_like_raw_drawing_text
        self.assertTrue(_looks_like_raw_drawing_text(_BLOB))
        self.assertFalse(_looks_like_raw_drawing_text("POWDER COATED RAL 9010"))


# ── a made member cut from stock is cut ──────────────────────────────────────────────────

def _section_part(method):
    return {"part_number": "T-01", "description": "RAIL BASE ARM",
            "normalized_material": "MILD STEEL", "materials": ["MILD STEEL"],
            "textual_operations": [],
            "section_stock": {"a": 20.0, "b": 50.0, "t": 2.0, "length_mm": 154.5,
                              "profile_form": "RHS"},
            "_material_cost_method": method,
            "material_estimate": {"stock_form": "tube"},
            "geometry_rollup": {"confidence": {"geometry_reliability": 0.0}}}


class ASectionPricedAsStockIsSawn(unittest.TestCase):
    def test_stock_rate_section_gets_one_cut_as_an_allowance(self):
        part = _section_part("catalogue_section_stock_length_rate")
        E.estimate_process_times(part, 4)
        self.assertEqual(part.get("_saw_cut_list_pieces"), [154.5])
        self.assertEqual((part.get("operation_sources") or {}).get("saw"), "inference")
        self.assertTrue(any("allowance" in str(f) for f in part.get("review_flags") or []))

    def test_a_catalogue_piece_at_its_own_length_is_not_cut_here(self):
        part = _section_part("catalogue_section_price")
        E.estimate_process_times(part, 4)
        self.assertIsNone(part.get("_saw_cut_list_pieces"))


# ── a word is not a code, and an empty cell is not a disagreement ────────────────────────

class AVisionDesignationFillsAWordCodedRow(unittest.TestCase):
    A = {"rows": [{"item_number": 1, "part_ref": "", "description": "Spring Washer",
                   "quantity": 12, "material": "Steel, Mild"}]}

    def test_the_fill_is_agreement(self):
        b = {"rows": [{"item_number": 1, "part_ref": "DIN 7980 - 8",
                       "description": "Spring Washer", "quantity": 12}]}
        rows, _ = mb.reconcile_page(copy.deepcopy(self.A), b, "GA")
        self.assertEqual((rows[0]["part_ref"], rows[0]["source"], rows[0]["flag"]),
                         ("DIN 7980 - 8", "BOTH", ""))
        self.assertEqual(rows[0]["material"], "Steel, Mild")

    def test_a_quantity_disagreement_still_contests(self):
        b = {"rows": [{"item_number": 1, "part_ref": "DIN 7980 - 8",
                       "description": "Spring Washer", "quantity": 6}]}
        rows, _ = mb.reconcile_page(copy.deepcopy(self.A), b, "GA")
        self.assertEqual(rows[0]["source"], "B_OVERRIDE")

    def test_a_different_article_still_contests(self):
        b = {"rows": [{"item_number": 1, "part_ref": "DIN 934 - M10",
                       "description": "Hex Nut", "quantity": 12}]}
        rows, _ = mb.reconcile_page(copy.deepcopy(self.A), b, "GA")
        self.assertNotEqual(rows[0]["source"], "BOTH")


# ── the contracts say coverage, never borrowed acceptance ────────────────────────────────

class TheRootsPriceMayBeItsMembers(unittest.TestCase):
    def _summary(self, with_root_record):
        nodes = [dict(part_number="ROOT", kind="assembly", qty_per_unit=1,
                      qty_by_parent={}, parents=[]),
                 dict(part_number="LEAF", kind="leaf", qty_per_unit=2,
                      qty_by_parent={"ROOT": 2}, parents=["ROOT"])]
        parts = [dict(part_number="LEAF", quantity=2, unit_of_measure="each",
                      bom_parents=[dict(parent="ROOT", qty=2)])]
        if with_root_record:
            parts.insert(0, dict(part_number="ROOT", quantity=1, unit_of_measure="each"))
        return dict(estimate_summary=dict(
            canonical_route_shadow=dict(product_root="ROOT", nodes=nodes),
            canonical_part_estimates=parts))

    def test_a_rolled_up_root_is_a_note_not_two_defects(self):
        got = qfc.audit(self._summary(with_root_record=False))
        codes = [i["code"] for i in got["issues"]]
        self.assertNotIn("canonical_price_record_missing", codes)
        self.assertFalse(any(i["code"] == "quantity_rollup_mismatch"
                             and i.get("part") == "ROOT" for i in got["issues"]))
        self.assertIn("product_price_is_members_rollup",
                      [n["code"] for n in got["notes"]])

    def test_a_root_with_no_priced_member_still_fails(self):
        s = self._summary(with_root_record=False)
        s["estimate_summary"]["canonical_part_estimates"] = []
        codes = [i["code"] for i in qfc.audit(s)["issues"]]
        self.assertIn("canonical_price_record_missing", codes)

    def test_a_priced_root_is_checked_as_before(self):
        got = qfc.audit(self._summary(with_root_record=True))
        self.assertEqual(got["notes"], [])


class NoRequirementsMeansNothingVerified(unittest.TestCase):
    def test_the_result_says_coverage_not_acceptance(self):
        got = fcc.audit({"section_coverage_contract": {}})
        self.assertFalse(got["applicable"])
        self.assertIsNot(got["passed"], True)
        self.assertFalse(got.get("verified"))
        self.assertIn("nothing verified", got["scope"])


if __name__ == "__main__":
    unittest.main()
