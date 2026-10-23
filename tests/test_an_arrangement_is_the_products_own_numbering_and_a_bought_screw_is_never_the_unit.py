"""A general arrangement's quantities are divided only on positive evidence — the codes it
shows N times are numbered as the product is — and a bought article is never the unit; a
customer's drawing number may open with letters; a hole callout is not a size; a figure
leads its line; a developed flat that weighs several times its part is refused; a section is
cut to length, not from a blank; and the sheet's printed rows are held against the graph
(D-584).

M&S 0351292 on 22 Oct 2026: the pack's numbering (ROL2021-…) failed the engine's
drawing-number shape on every reader at once. The words reader parsed no rows; the
arrangement rule saw no structure on the GA and took "651.02.909 x6" — six Hafele feet — for
six arrangements, dividing every fastener on the sheet by six; and the detail-sheet size
reader took "Ø7 X 90°" for a 90 x 7 blank while the general-notes block put 400, 304, 120
and 80 on every page. Nothing here names a job; the codes are the customer's numbering
shape and standard fastener designations.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bom_tree as bt  # noqa: E402
import part_code_conventions as pcc  # noqa: E402
import detail_page_geometry as dg  # noqa: E402
import extractor_patterns as ep  # noqa: E402
import quantity_flow_contract as qfc  # noqa: E402

GA = "ROL2021-2465-00"
RAIL, BASE, SUPPORT = "ROL2021-2466", "ROL2021-2467", "ROL2021-2468"


def rows_like_the_rail():
    """The GA's table and the three sub-assembly tables, as the readers keep them: one row
    per printed line, parent = the sheet whose table lists it."""
    out = [dict(part_number=c, quantity=q, source_pdf=GA, bom_parent=GA, item_number=i)
           for i, (c, q) in enumerate([(SUPPORT, 2), (BASE, 1), (RAIL, 1), ("ROL2021-2406", 1),
                                       ("651.02.909", 6), ("DIN 7991 - M3 x 10", 6),
                                       ("ISO 7380-1 - M8 x 16", 12), ("DIN 7980 - 8", 12)], 1)]
    for parent, lines in ((RAIL, [("ROL2021-2416", 4), ("ROL2021-2405", 1), ("ROL2021-2404", 1),
                                  ("ROL2021-2402", 2), ("ROL2021-2367", 2), ("DIN 934 - M10", 2)]),
                          (BASE, [("ROL2021-2410", 2), ("ROL2021-2400", 1)]),
                          (SUPPORT, [("ROL2021-2424", 1), ("ROL2021-2408", 2), ("ROL2021-2407", 2),
                                     ("DIN 934 - M10", 2)])):
        out += [dict(part_number=c, quantity=q, source_pdf=parent, bom_parent=parent, item_number=i)
                for i, (c, q) in enumerate(lines, 1)]
    return out


class ACustomersNumberingMayOpenWithLetters(unittest.TestCase):
    def test_the_shape_admits_a_short_letter_prefix_and_refuses_a_designation(self):
        for ok in ("ROL2021-2465-00", "ROL2021-2466", "12349-02-69-100", "1282-GA", "3886-GA-C", "12527-22-GA"):
            self.assertTrue(pcc.looks_like_a_drawing_number(ok), ok)
        for no in ("DIN7991-M3X10", "ISO7380-1-M8X16", "RAL7024-SATIN", "M8X16-BZP", "651.02.909",
                   "600-CENTRES", "1-WIDE", "FIXING49", "KC-MS40C", "ABCDE123-01"):
            self.assertFalse(pcc.looks_like_a_drawing_number(no), no)

    def test_a_supplier_article_is_known_for_what_it_is(self):
        for art in ("651.02.909", "DIN 7991 - M3 x 10", "ISO 7380-1 - M8 x 16", "DIN 934 - M10", "RAL7024-SATIN"):
            self.assertTrue(pcc.is_supplier_article(art), art)
            self.assertEqual(pcc.drawing_family(art), "")
        for made in ("ROL2021-2466", "12349-02-69-100", "FIXING49"):
            self.assertFalse(pcc.is_supplier_article(made), made)
        self.assertEqual(pcc.drawing_family("ROL2021-2466"), "ROL2021")
        self.assertEqual(pcc.drawing_family("12349-02-69-100"), "12349")
        self.assertEqual(bt._family("651.02.909"), "")
        self.assertEqual(bt._family("ROL2021-2468"), "ROL2021")
        self.assertEqual(bt._family("1455-C-101"), "1455")


class AnArrangementIsTheProductsOwnNumbering(unittest.TestCase):
    def test_six_feet_on_the_general_arrangement_are_six_feet(self):
        out = bt.resolve_effective_quantities(rows_like_the_rail(), main_ga=GA)
        self.assertEqual(out["install_context"], {})
        self.assertIn("NOT recognised", out["install_context_decision"])
        eff = out["effective"]
        expected = {"651.02.909": 6, "DIN7980-8": 12, "DIN7991-M3X10": 6, "ISO7380-1-M8X16": 12,
                    "DIN934-M10": 6, "ROL2021-2407": 4, "ROL2021-2408": 4, "ROL2021-2424": 2,
                    "ROL2021-2410": 2, "ROL2021-2416": 4, "ROL2021-2402": 2, "ROL2021-2367": 2}
        for code, n in expected.items():
            self.assertEqual(eff.get(code), n, code)

    def test_a_foreign_family_shown_six_times_is_components_not_arrangements(self):
        rows = [dict(part_number=c, quantity=q, source_pdf=GA, bom_parent=GA)
                for c, q in [("651.02.909", 6), ("RAIL-SUB", 1)]]
        rows.append(dict(part_number="ROL2021-2416", quantity=4, source_pdf=RAIL, bom_parent=RAIL))
        decision = bt.install_context_decision(rows, GA)
        self.assertIn("NOT recognised", decision)
        self.assertEqual(bt.install_context_codes(rows, GA), set())

    def test_the_products_own_module_shown_three_times_is_still_an_arrangement(self):
        ga = "12349-02-69-GA"
        rows = [dict(part_number="12349-02-69-100", quantity=3, source_pdf=ga, bom_parent=ga),
                dict(part_number="12349-02-69-03M", quantity=1, source_pdf="12349-02-69-100", bom_parent="12349-02-69-100")]
        self.assertIn("RECOGNISED", bt.install_context_decision(rows, ga))
        self.assertEqual(bt.install_context_codes(rows, ga), {"12349-02-69-100"})

    def test_without_the_arrangements_own_numbering_the_rule_declines_and_asks(self):
        rows = [dict(part_number="12349-02-69-100", quantity=3, source_pdf="GA.pdf"),
                dict(part_number="FIXING", quantity=4, source_pdf="GA.pdf")]
        decision = bt.install_context_decision(rows, "GA.pdf")
        self.assertIn("NOT recognised", decision)
        self.assertIn("name the unit being quoted", decision)

    def test_a_bay_is_still_a_bay(self):
        rows = [dict(part_number="1448-GA", quantity=2, source_pdf="BAY.pdf"),
                dict(part_number="3886-GA", quantity=2, source_pdf="BAY.pdf")]
        self.assertIn("more than one number family", bt.install_context_decision(rows, "BAY.pdf"))


class AHoleCalloutIsNotASizeAndACommaIsADecimal(unittest.TestCase):
    def test_a_countersink_and_a_counterbore_give_no_blank(self):
        strip = ep.classify_dimensions("Ø3,5 ⌵ Ø7 X 90° (x6) 1293 18,5 253 12 STAINLESS STEEL - BRUSHED 3 mm")
        self.assertNotIn("7 x 90", " ".join(strip["overall_sizes_mm"]))
        self.assertNotIn("90 x 7", " ".join(strip["overall_sizes_mm"]))
        angle = ep.classify_dimensions("Ø9 ⌵3 (x3) 250 115 51 22 MILD STEEL - RAW 3 mm")
        self.assertEqual(angle["overall_sizes_mm"], [])
        bore = ep.classify_dimensions("Ø11 ⌵2 (x2) 703 MILD STEEL RECT TUBE - RAW 50X20X2MM")
        self.assertEqual(bore["overall_sizes_mm"], [])
        thread = ep.classify_dimensions("M8 x 16 BUTTON HEAD")
        self.assertEqual(thread["overall_sizes_mm"], [])
        self.assertIn("1154 x 450", ep.classify_dimensions("BASE PLATE 1154 x 450 mm")["overall_sizes_mm"])

    def test_a_decimal_comma_is_read(self):
        d = ep.classify_dimensions("1435,2 x 25 mm FLAT 2 mm")
        self.assertIn("1435.2 x 25", d["overall_sizes_mm"])
        self.assertTrue(dg._NUMBER_WORD.fullmatch("208,9"))
        self.assertTrue(dg._NUMBER_WORD.fullmatch("1435,2"))


def _sheet(lines, rotated=()):
    """A one-page PDF with these text lines: horizontal ones, and `rotated` printed at 90°."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    y = 80
    for text in lines:
        page.insert_text((60, y), text, fontsize=11)
        y += 22
    x = 420
    for text in rotated:
        page.insert_text((x, 300), text, fontsize=11, rotate=90)
        x += 30
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    doc.save(path)
    doc.close()
    return {"source_pdf_path": path, "page_number": 1}


class AFigureLeadsItsLineAndADevelopedFlatIsTheNetBlank(unittest.TestCase):
    def test_the_general_notes_put_no_figure_on_the_sheet(self):
        page = _sheet(["1154", "SPECIFICATION IS 400 GRIT FINAL POLISH.",
                       "• POWDERCOATING: BETWEEN 80 - 120 MICRON", "• 304 - STAINLESS STEEL",
                       "SE-555 93 Jönköping, Sweden", "1192 TUBE LENGTH", "258 259 259"],
                     rotated=["450"])
        try:
            figs = dg.read_sheet_figures(page)["figures"]
        finally:
            os.unlink(page["source_pdf_path"])
        values = sorted(v for v, _a in figs)
        self.assertEqual(values, [258.0, 259.0, 259.0, 450.0, 1154.0, 1192.0])
        self.assertIn((450.0, "v"), figs)

    def test_the_base_plate_is_sized_and_the_folded_view_does_not_size_the_flat(self):
        plate = _sheet(["1154", "R225"], rotated=["450"])
        down = _sheet(["FLAT PATTERN IS FOR REFERENCE ONLY", "703", "1151,2", "1435,2", "FLAT PATTERN"],
                      rotated=["208,9"])
        try:
            p = {"part_number": "PLATE", "pages": [1], "normalized_thickness_mm": 2,
                 "normalized_material": "MILD STEEL", "stated_weight_kg": 7.5}
            b = dg.provisional_blank_from_sheets(p, [plate])
            self.assertIsNotNone(b)
            self.assertEqual((b["length"], b["width"], b["developed"]), (1154.0, 450.0, False))
            d = {"part_number": "DOWN", "pages": [1], "normalized_thickness_mm": 2,
                 "normalized_material": "MILD STEEL", "stated_weight_kg": 0.6}
            self.assertIsNone(dg.provisional_blank_from_sheets(d, [down]))
            self.assertIn("flat pattern", d["_provisional_blank_refused"])
        finally:
            os.unlink(plate["source_pdf_path"])
            os.unlink(down["source_pdf_path"])


class ASectionIsCutToLengthNotFromABlank(unittest.TestCase):
    def test_a_tube_row_takes_no_sheet_blank(self):
        rail = {"part_number": "ROL2021-2424", "description": "UNIVERSAL MIDFLOOR 1200 RAIL BASE CROSS RAIL",
                "material": "MILD STEEL RECT TUBE - RAW", "dimension": "50X20X2MM"}
        self.assertTrue(dg.not_cut_from_a_blank(rail))
        plate = {"part_number": "ROL2021-2400", "description": "UNIVERSAL MIDFLOOR 1200 RAIL BASE PLATE",
                 "material": "MILD STEEL - RAW", "dimension": "2 mm", "is_assembly_parent": False}
        self.assertFalse(dg.not_cut_from_a_blank(plate))
        costed = {"part_number": "X", "material_estimate": {"stock_form": "tube"}}
        self.assertTrue(dg.not_cut_from_a_blank(costed))


class ThePrintedRowsAreHeldAgainstTheGraph(unittest.TestCase):
    def _summary(self, divided=False, evidence=False, recognised=False, edge_qty=12):
        rows = rows_like_the_rail()
        iso = next(r for r in rows if r["part_number"].startswith("ISO"))
        if divided:
            iso["quantity_as_printed"], iso["quantity"] = 12, 2
            if evidence:
                iso["quantity_evidence"] = {"general_arrangement": GA, "divided_by": 6}
        parts = [{"part_number": "ISO 7380-1 - M8 x 16", "quantity": iso["quantity"],
                  "bom_parents": [{"parent": GA, "qty": edge_qty}]},
                 {"part_number": "DIN 934 - M10", "quantity": 6,
                  "bom_parents": [{"parent": RAIL, "qty": 2}, {"parent": SUPPORT, "qty": 2}]}]
        return {"document_analysis": {"bom_rows": rows},
                "install_context": {"recognised": recognised, "codes": [], "n": 6 if recognised else 1},
                "estimate_summary": {"canonical_part_estimates": parts,
                                     "canonical_route_shadow": {"product_root": GA, "nodes": []}}}

    def test_a_divided_row_without_evidence_is_a_finding_and_blocks(self):
        from invariants import BLOCKING, CHECKS, check_a_printed_quantity_is_not_divided_without_evidence as check
        from engine_discoveries import _OURS
        s = self._summary(divided=True)
        codes = {i["code"] for i in qfc.printed_rows_audit(s)["issues"]}
        self.assertIn("printed_quantity_divided_without_evidence", codes)
        out = check(s)
        self.assertEqual(out[0]["code"], "printed_quantity_divided_without_evidence")
        self.assertEqual(out[0]["severity"], BLOCKING)
        self.assertIn(check, CHECKS)
        self.assertIn("printed_quantity_divided_without_evidence", _OURS)

    def test_a_row_divided_on_recognised_evidence_passes(self):
        from invariants import check_a_printed_quantity_is_not_divided_without_evidence as check
        s = self._summary(divided=True, evidence=True, recognised=True, edge_qty=2)
        self.assertEqual(check(s), [])
        self.assertNotIn("printed_quantity_divided_without_evidence",
                         {i["code"] for i in qfc.printed_rows_audit(s)["issues"]})

    def test_the_canonical_edge_must_be_the_printed_local_quantity(self):
        s = self._summary(edge_qty=2)
        issues = qfc.printed_rows_audit(s)["issues"]
        self.assertIn(("local_edge_disagrees_with_printed_row", "ISO7380-1-M8X16"),
                      {(i["code"], i["part"]) for i in issues})
        clean = qfc.printed_rows_audit(self._summary(edge_qty=12))
        self.assertEqual(clean["issues"], [])

    def test_a_shared_child_is_two_edges_and_a_reread_row_is_one(self):
        s = self._summary()
        rows = s["document_analysis"]["bom_rows"]
        rows.append(dict(rows[-1]))                      # the same row, read again
        trace = {(t["parent"], t["child"]): t for t in qfc.printed_rows_audit(s)["trace"]}
        self.assertEqual(trace[(RAIL, "DIN934-M10")]["printed_local"], 2)
        self.assertEqual(trace[(SUPPORT, "DIN934-M10")]["printed_local"], 2)
        self.assertEqual(qfc.printed_rows_audit(s)["issues"], [])


class ACutLengthIsADimensionNotTheNextNumberOnThePage(unittest.TestCase):
    def test_a_drawing_number_a_date_and_a_tolerance_note_are_not_lengths(self):
        import section_profile as sp
        row = sp.detect_section_stock("UNIVERSAL MIDFLOOR 1200 RAIL ASSY BASE RAIL MILD STEEL RECT TUBE - RAW "
                                      "30X20X2MM ROL2021-2405 ROL2021-2405")
        self.assertEqual((row["a"], row["b"], row["t"]), (20.0, 30.0, 2.0))
        self.assertIsNone(row["length_mm"])            # 2021 is the drawing number, 1200 the name
        sheet = sp.detect_section_stock("MILD STEEL SQ TUBE - RAW 30 X 30 X 2MM UNIT WEIGHT: 2.4 kg "
                                        "OVER 120mm UP TO 1000mm ±1.0mm DATE 27/09/2021 COPYRIGHT "
                                        "M&S PLC 2008 SCALE 1 : 8 1395 30")
        self.assertEqual(sheet["length_mm"], 1395.0)   # not 120, not 2021, not 2008
        named = sp.detect_section_stock("1290MM T ARM MILD STEEL RECT TUBE - RAW 30X15X2MM")
        self.assertIsNone(named["length_mm"])          # the name says 1290; the sheet says 1294

    def test_the_canonical_forms_still_read(self):
        import section_profile as sp
        for text, length in (("30 x 60 x 1.50mm TUBE 1125", 1125.0), ("15.00 x 30.00 x 2.00mm TUBE 1164", 1164.0),
                             ("SHS 30x30x2mm @ 1395mm", 1395.0), ("30 x 60 x 1.50mm TUBE 1125MM LONG", 1125.0),
                             ("60.0 EXT  30.0 EXT  1.5 WALL 1072.0 EXT", 1072.0)):
            self.assertEqual(sp.detect_section_stock(text)["length_mm"], length, text)

    def test_a_shared_pages_profile_needs_the_parts_own_row_and_the_length_is_the_sheets_figure(self):
        text = (ROOT / "src" / "document_builder.py").read_text(encoding="utf-8")
        # The guard's whole block, from its first predicate to where the section is applied
        # — a fixed character window broke the day the guard grew (D-587).
        guard = text.index("_row_says_sheet")
        block = text[guard:text.index('part["section_stock"] = _sec', guard) + 40]
        self.assertIn("NOT applied", block)
        self.assertIn("read_sheet_figures", block)
        self.assertIn('"detail_sheet_figure"', block)
        # Fourth tranche: the part's own detail sheet refuses a shared profile without a
        # row, and one detail sheet is enough for the figure path.
        self.assertIn("_own_detail_silent", block)
        self.assertIn("if len(_detail_pages) == 1:", block)
        self.assertNotIn("if len(_detail_pages) == 1 and len(page_nums) == 1:", text)
        # D-587: a callout naming another part is that part's; a bought article takes none.
        self.assertIn("_names_another", block)
        self.assertIn("_bought_line", block)

    def test_a_designation_a_range_and_a_decimal_comma_are_read_as_they_are(self):
        import section_profile as sp
        self.assertEqual(sp.detect_section_stock("• 304 - STAINLESS STEEL 30X30X2MM TUBE 1395")["length_mm"], 1395.0)
        self.assertEqual(sp.detect_section_stock("30X30X2MM TUBE BETWEEN 80 - 120 MICRON 1395")["length_mm"], 1395.0)
        self.assertEqual(sp.detect_section_stock("MILD STEEL RECT TUBE - RAW 50X20X2MM 154,5 50")["length_mm"], 154.5)
        self.assertEqual(sp.detect_section_stock("30X30X2MM TUBE 1125 - 2 OFF")["length_mm"], 1125.0)


class APartsListMaySitAboveItsHeader(unittest.TestCase):
    """The reviewer on the rerun: "two agreed rows and 18 recovered by vision — the words
    reader parsing no rows on page 9". On the real GA the header was found and every row
    parsed, but the reader walked only the band BELOW the header, and this template prints
    the list above it, numbered upward. The band above is read bottom-up where the band
    below is empty; the dimension column is its own cell; PART NO and DRAWING printing the
    same number are one code."""

    def _page(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=842, height=595)
        cols = {"pos": 40, "qty": 65, "desc": 100, "mat": 290, "dim": 480, "part": 580, "dwg": 700}
        rows = [(8, 2, "BASE SUPPORT", "SEE DWGS - EPC GRAPHITE", "", "ROL2021-2468"),
                (7, 1, "BASE", "SEE DWGS - EPC GRAPHITE", "", "ROL2021-2467"),
                (6, 1, "RAIL", "SEE DWGS - EPC GRAPHITE", "", "ROL2021-2466"),
                (5, 1, "ANTI SCRATCH STRIP", "STAINLESS - BRUSHED", "3 mm", "ROL2021-2406"),
                (4, 6, "ADJUSTING SCREW HAFELE", "STEEL", "", "651.02.909"),
                (3, 2, "UPRIGHT", "MS SQ TUBE - RAW", "30X30X2MM", "ROL2021-2402")]
        y = 300
        for pos, qty, desc, mat, dim, code in rows:
            for key, text in (("pos", str(pos)), ("qty", str(qty)), ("desc", desc), ("mat", mat),
                              ("dim", dim), ("part", code), ("dwg", code)):
                if text:
                    page.insert_text((cols[key], y), text, fontsize=8)
            y += 14
        for key, text in (("pos", "POS"), ("qty", "QTY"), ("desc", "DESCRIPTION"), ("mat", "MATERIAL"),
                          ("dim", "DIMENSION"), ("part", "PART NO"), ("dwg", "DRAWING")):
            page.insert_text((cols[key], y), text, fontsize=8)
        page.insert_text((580, 560), "DRAWING No", fontsize=8)
        page.insert_text((580, 575), "ROL2021-2465-00", fontsize=9)
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        doc.save(path)
        doc.close()
        return path

    def test_the_rows_above_the_header_are_read_bottom_up(self):
        import pdfplumber
        import _bom_words_reader as wr
        path = self._page()
        try:
            with pdfplumber.open(path) as doc:
                out = wr.read_bom_from_page(doc.pages[0])
        finally:
            os.unlink(path)
        self.assertIsNotNone(out)
        self.assertEqual(out["parent"], "ROL2021-2465-00")
        got = {(r["item_number"], r.get("part_number") or r.get("part_ref"), r["quantity"], r.get("dimension"))
               for r in out["rows"]}
        self.assertIn(("8", "ROL2021-2468", 2, None), got)
        self.assertIn(("3", "ROL2021-2402", 2, "30X30X2MM"), got)
        self.assertIn(("5", "ROL2021-2406", 1, "3 mm"), got)
        self.assertEqual(len(out["rows"]), 6)
        # The customer's numbering is a drawing reference here as everywhere (the reader's
        # private digit-led regex had called the rail and the supports bought-in), and a
        # supplier article keeps its whole designation — never a bare "DIN".
        kinds = {r.get("part_number") or r.get("part_ref"): r["kind"] for r in out["rows"]}
        self.assertEqual(kinds["ROL2021-2468"], "drawing_ref")
        self.assertEqual(kinds["651.02.909"], "bought_in")

    def test_a_designation_is_read_whole_and_a_bare_prefix_is_no_code(self):
        from bom_table_extractor import _classify_part_ref
        self.assertEqual(_classify_part_ref("ROL2021-2466"), ("drawing_ref", "ROL2021-2466"))
        self.assertEqual(_classify_part_ref("12349-02-69-100")[0], "drawing_ref")
        self.assertEqual(_classify_part_ref("DIN 7991 - M3 x 10"), ("bought_in", "DIN 7991 - M3 x 10"))
        self.assertEqual(_classify_part_ref("DIN"), ("bought_in", ""))
        self.assertEqual(_classify_part_ref("ISO"), ("bought_in", ""))
        self.assertEqual(_classify_part_ref("Clinch Nut"), ("bought_in", "Clinch Nut"))
        self.assertEqual(_classify_part_ref("FIXING49"), ("bought_in", "FIXING49"))

    def test_the_general_arrangement_is_the_sheet_no_other_sheet_lists(self):
        rows = [dict(part_number=c, quantity=q, source_pdf=BASE, bom_parent=BASE)
                for c, q in [("ROL2021-2400", 1), ("ROL2021-2410", 2)]]
        rows += [r for r in rows_like_the_rail() if r["source_pdf"] == GA]
        out = bt.resolve_effective_quantities(rows)
        self.assertEqual(out["main_ga"], GA)      # not the base, whose rows were read first


class AChargedIdentityIsWholeAndChargedOnce(unittest.TestCase):
    def test_a_bare_prefix_and_a_double_charge_block_and_distinct_standards_do_not(self):
        from invariants import BLOCKING, CHECKS, check_a_charged_identity_is_whole_and_charged_once as check
        from engine_discoveries import _OURS
        bad = {"final_estimate": {"material_rows": [
            {"part_code": "ISO", "description": "Hexagon Socket Button Head Screw", "total_value_gbp": 124.8},
            {"part_code": "ISO7380-1-M8X16", "description": "Hexagon Socket Button Head Screw", "total_value_gbp": 1.87},
            {"part_code": "DIN", "description": "Hex Nut", "total_value_gbp": 3.09}]}}
        out = check(bad)
        self.assertEqual(out[0]["code"], "charged_identity_collision")
        self.assertEqual(out[0]["severity"], BLOCKING)
        self.assertIn("'ISO'", out[0]["message"])
        self.assertIn("'DIN'", out[0]["message"])
        good = {"final_estimate": {"material_rows": [
            {"part_code": "DIN7980-8", "description": "Spring Washer", "total_value_gbp": 1.12},
            {"part_code": "DIN7991-M3 X 10", "description": "Countersunk Screw", "total_value_gbp": 0.56},
            {"part_code": "DIN934-M10", "description": "Hex Nut", "total_value_gbp": 0.56},
            {"part_code": "ISO7380-1-M8X16", "description": "Button Head Screw", "total_value_gbp": 1.87},
            {"part_code": "ROL2021-2402", "description": "UPRIGHT", "total_value_gbp": 37.2}]}}
        self.assertEqual(check(good), [])
        self.assertIn(check, CHECKS)
        self.assertIn("charged_identity_collision", _OURS)


class TheRunResolvesWhatThePageAccepted(unittest.TestCase):
    def test_the_packs_reference_names_the_root_before_not_resolved(self):
        text = (ROOT / "src" / "route_compiler.py").read_text(encoding="utf-8")
        alias = text.index("product_is_the_packs_reference")
        unresolved = text.index('"code": "declared_product_not_resolved"')
        self.assertLess(alias, unresolved)
        self.assertIn("product_sheets", text[alias - 2500:alias])


if __name__ == "__main__":
    unittest.main()
