"""A wire with no printed size is sized by the one reading of its own figures its weight allows (D-692).

12693-01-GA, the run of 4 Nov 2026 17:16. Two mild steel wires, four of each in weldment 104:

    05M  TABLE EDGE - WIRE A   its own sheet prints "1100", "0.5", "4", WEIGHT: 0.11,
                               MATERIAL: MILD STEEL WIRE
    06M  TABLE EDGE - WIRE B   "1100", "0.5", "8", WEIGHT: 0.43, MATERIAL: MILD STEEL WIRE

The Ø glyph is not in the text layer, so no reader could call 4 or 8 a diameter, and the document
builder will not take a diameter or a length it cannot warrant. 05M was left unpriced ("the gauge
was never read; the blank size was never measured"), 06M was given a market indication of GBP 2.50
each, and the workbook's Wire block stayed empty. The reviewer: "Neither is demonstrated as a
verified wire-stock calculation."

The weight settles it. Ø4 x 1100 of steel weighs 0.1085 kg against the stated 0.11; Ø8 x 1100
weighs 0.434 against 0.43; every other pairing of those figures is far off (Ø0.5 x 1100 is
0.0017 kg). The rules under test are generic:

  1. a round-stock part with no diameter and/or no length takes the one pairing of the figures on
     its OWN sheet that weighs its stated weight within ±5%, under a source of its own that is not
     a measurement, and says which figures it took and the arithmetic;
  2. two pairings that fit decide nothing and are asked; no stated weight, a sheet part, a page
     that only lists the part, and a diameter some reader already gave are left alone (a known
     diameter lets the rule settle the length only);
  3. the sized wire reaches the workbook's Wire block at its gauge and length, priced by the
     sheet's own wire formula, and a gauge the template's table does not hold is said, not added;
  4. the rate it is priced at, the template's Wire Cost Per Tonne (GBP 1,600/t on the sheet), is
     an undated template allowance: the line, its review flag and its Wire row say so in plain
     words (provisional, no purchasing source or date, confirm with purchasing), and no
     catalogue row (purchasing's nearest is a 4 mm 304 stainless at GBP 20/kg) stands in for it.

Synthetic records and made-up job numbers throughout.
"""
from __future__ import annotations

import copy
import math
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import detail_page_geometry as dpg  # noqa: E402
import source_precedence as sp  # noqa: E402

J = "12999-01"
SOURCE = "own_figures_confirmed_by_stated_weight"


# ── the records ───────────────────────────────────────────────────────────────────────────

def _sheet(page, code, *lines):
    """A sheet titled with its own drawing number, its text layer one printed item per line."""
    return {"page_number": page, "pdfplumber_text": "\n".join(lines),
            "page_analysis": {"title_block": {"drawing_numbers": [code]}}}


def _wire_sheet(page, code, name, size, weight="0.11", extra=()):
    return _sheet(page, code, "1100", "0.5", size, *extra, name, code, f"WEIGHT: {weight}",
                  "MATERIAL: MILD STEEL WIRE", "FINISH: REFER TO SUB ASSEMBLY", "SCALE 1:5",
                  "SHEET 1 OF 1")


def _wire(code, name, page, **extra):
    """A wire as the document builder leaves it when its material says WIRE: on the wire route,
    with no gauge, no length and no stock form of its own."""
    return dict({"part_number": code, "description": name, "quantity": 4, "pages": [page],
                 "materials": ["MILD STEEL WIRE"], "normalized_material": "MILD STEEL WIRE",
                 "page_roles": ["detail"], "manufacturing_interpretation": {"stock_form": "unknown"},
                 "_wire_part_override": True,
                 "textual_operations": ["wire_forming", "welding", "handling"],
                 "operations": ["handling", "welding", "wire_forming"], "review_flags": []},
                **extra)


def _pack():
    sheets = [_wire_sheet(5, f"{J}-05M", "TABLE EDGE - WIRE A", "4", "0.11"),
              _wire_sheet(6, f"{J}-06M", "TABLE EDGE - WIRE B", "8", "0.43")]
    parts = [_wire(f"{J}-05M", "TABLE EDGE - WIRE A", 5),
             _wire(f"{J}-06M", "TABLE EDGE - WIRE B", 6)]
    return parts, {"pages": sheets}


def _flags(part):
    return " | ".join(str(f) for f in (part.get("review_flags") or []))


# ── 1. both wires sized, under a source that is not a measurement ─────────────────────────

def test_the_weight_singles_out_one_pairing_of_each_wires_figures():
    """The arithmetic the rule rests on, at mild steel's 7850 kg/m3."""
    assert dpg.round_stock_mass_kg(4, 1100, 7850) == pytest.approx(0.1085, abs=5e-4)
    assert dpg.round_stock_mass_kg(8, 1100, 7850) == pytest.approx(0.434, abs=5e-4)
    assert dpg.round_stock_mass_kg(0.5, 1100, 7850) == pytest.approx(0.0017, abs=1e-4)


def test_both_wires_are_sized_from_their_own_sheets_by_their_own_weight():
    parts, summary = _pack()
    done = dpg.apply_round_stock_sizes_from_own_weight(parts, summary)
    assert done == [f"{J}-05M", f"{J}-06M"]
    a, b = parts
    for part, gauge in ((a, 4.0), (b, 8.0)):
        assert part["wire_gauge_mm"] == gauge
        assert part["wire_length_mm"] == 1100.0
        assert part["wire_gauge_mm_source"] == SOURCE
        assert part["wire_length_mm_source"] == SOURCE
        assert part["manufacturing_interpretation"]["stock_form"] == "wire"
        assert part["material_estimate"]["stock_form"] == "wire"
        rec = part["round_stock_size_from_own_weight"]
        assert (rec["diameter_mm"], rec["length_mm"], rec["status"]) == (gauge, 1100.0, "settled")
    # Said on the part: the figures taken, the arithmetic, and that it is not a measurement.
    said_a = _flags(a)
    assert "0.5, 4, 1100" in said_a and "page 5" in said_a
    assert "π/4 x 4² x 1100 mm³ = 0.1085 kg" in said_a and "0.11 kg" in said_a
    assert "not measured" in said_a and "within ±5%" in said_a
    assert "no unit" in said_a and "kilograms" in said_a
    assert "0.4340 kg" in _flags(b) and "0.43 kg" in _flags(b)


def test_the_source_is_its_own_and_is_not_a_measurement():
    assert not sp.was_measured(SOURCE)
    assert sp.rank(SOURCE) < sp.rank("drawing_deterministic")
    assert sp.rank(SOURCE) < sp.rank("bom_tree")
    assert sp.rank(SOURCE) > sp.rank("inference")
    assert "weight" in sp.display_name(SOURCE)


def test_a_weight_the_record_already_holds_is_used_and_needs_no_unit_reading():
    sheet = _sheet(5, f"{J}-05M", "1100", "0.5", "4", "TABLE EDGE - WIRE A", "SHEET 1 OF 1")
    part = _wire(f"{J}-05M", "TABLE EDGE - WIRE A", 5, stated_weight_g=108.5)
    assert dpg.apply_round_stock_sizes_from_own_weight([part], {"pages": [sheet]}) == [part["part_number"]]
    assert (part["wire_gauge_mm"], part["wire_length_mm"]) == (4.0, 1100.0)
    assert "the record's stated 0.1085 kg" in _flags(part)
    assert "no unit" not in _flags(part)


# ── 2. what is left alone ─────────────────────────────────────────────────────────────────

def test_two_pairings_that_both_fit_decide_nothing_and_are_asked():
    """Ø4 x 1100 and Ø8 x 275 are the same steel: 4² x 1100 = 8² x 275."""
    sheet = _sheet(5, f"{J}-05M", "1100", "275", "4", "8", "WEIGHT: 0.11", "MILD STEEL WIRE")
    part = _wire(f"{J}-05M", "TABLE EDGE - WIRE A", 5)
    assert dpg.apply_round_stock_sizes_from_own_weight([part], {"pages": [sheet]}) == []
    assert part.get("wire_gauge_mm") is None and part.get("wire_length_mm") is None
    assert part["manufacturing_interpretation"]["stock_form"] == "unknown"
    said = _flags(part)
    assert "2 pairings" in said and "Ø4 x 1100" in said and "Ø8 x 275" in said
    assert "none is taken" in said
    assert any("diameter and cut length" in q["issue"]
               for q in part.get("manufacturing_questions") or [])


def test_a_wire_with_no_stated_weight_is_untouched():
    sheet = _sheet(5, f"{J}-05M", "1100", "0.5", "4", "TABLE EDGE - WIRE A",
                   "MATERIAL: MILD STEEL WIRE")
    part = _wire(f"{J}-05M", "TABLE EDGE - WIRE A", 5)
    before = copy.deepcopy(part)
    assert dpg.apply_round_stock_sizes_from_own_weight([part], {"pages": [sheet]}) == []
    assert part == before


def test_a_sheet_part_is_untouched_whatever_its_figures_weigh():
    sheet = _sheet(7, f"{J}-07M", "1100", "0.5", "4", "TAB", "WEIGHT: 0.11",
                   "MATERIAL: MILD STEEL")
    part = {"part_number": f"{J}-07M", "description": "TAB", "quantity": 20, "pages": [7],
            "normalized_material": "MILD STEEL", "materials": ["MILD STEEL"],
            "normalized_thickness_mm": 1.5, "page_roles": ["detail"],
            "manufacturing_interpretation": {"stock_form": "sheet"}, "review_flags": []}
    before = copy.deepcopy(part)
    assert dpg.apply_round_stock_sizes_from_own_weight([part], {"pages": [sheet]}) == []
    assert part == before


def test_a_page_that_is_not_the_wires_own_sheet_lends_it_nothing():
    """The weldment's sheet lists the wire and prints figures and a weight of its own."""
    sheet = _sheet(4, f"{J}-104", "1100", "0.5", "4", "WEIGHT: 0.11", "WORKTOP WELDMENT")
    part = _wire(f"{J}-05M", "TABLE EDGE - WIRE A", 4)
    before = copy.deepcopy(part)
    assert dpg.apply_round_stock_sizes_from_own_weight([part], {"pages": [sheet]}) == []
    assert part == before


def test_an_explicit_printed_diameter_still_wins():
    """A Ø6 a reader took off a printed callout is kept. At Ø6 no figure on the sheet weighs
    0.11 kg, so the length stays to be stated; Ø4, which would fit, is never substituted."""
    parts, summary = _pack()
    part = parts[0]
    assert sp.apply_field(part, "wire_gauge_mm", 6.0, "drawing_deterministic")
    dpg.apply_round_stock_sizes_from_own_weight([part], summary)
    assert part["wire_gauge_mm"] == 6.0
    assert part["wire_gauge_mm_source"] == "drawing_deterministic"
    assert part.get("wire_length_mm") is None
    assert "at its stated Ø6" in _flags(part) and "still to be stated" in _flags(part)


def test_a_known_diameter_lets_the_weight_settle_the_length_alone():
    sheet = _sheet(5, f"{J}-05M", "1100", "550", "0.5", "4", "WEIGHT: 0.11", "MILD STEEL WIRE")
    part = _wire(f"{J}-05M", "TABLE EDGE - WIRE A", 5)
    assert sp.apply_field(part, "wire_gauge_mm", 4.0, "drawing_deterministic")
    assert dpg.apply_round_stock_sizes_from_own_weight([part], {"pages": [sheet]}) == [part["part_number"]]
    assert part["wire_gauge_mm"] == 4.0
    assert part["wire_gauge_mm_source"] == "drawing_deterministic"
    assert part["wire_length_mm"] == 1100.0
    assert part["wire_length_mm_source"] == SOURCE
    assert "the length alone, at its stated diameter" in _flags(part)


def test_the_drawing_area_is_read_off_the_pdf_and_the_title_block_is_not(tmp_path):
    """With the PDF at hand the figures are the drawing area's. The title block here prints a
    275 and an 8 that, read as a size, would weigh 0.11 kg too and leave the wire ambiguous."""
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "pack.pdf"
    doc = fitz.open()
    page = doc.new_page(width=1190.55, height=841.89)          # A3 landscape
    for text, x, y in (("1100", 400, 200), ("0.5", 300, 330), ("4", 420, 330),
                       ("WEIGHT: 0.11", 900, 700), ("275", 900, 740), ("8", 900, 780)):
        page.insert_text((x, y), text, fontsize=9)
    doc.save(str(path))
    doc.close()
    sheet = {"page_number": 1, "source_pdf_path": str(path),
             "page_analysis": {"title_block": {"drawing_numbers": [f"{J}-05M"]}}}
    part = _wire(f"{J}-05M", "TABLE EDGE - WIRE A", 1)
    assert dpg.apply_round_stock_sizes_from_own_weight([part], {"pages": [sheet]}) == [part["part_number"]]
    assert (part["wire_gauge_mm"], part["wire_length_mm"]) == (4.0, 1100.0)
    assert "drawing area" in _flags(part)


def test_the_scan_sizes_round_stock_after_the_sheet_readers_and_before_costing():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    at = src.index("apply_round_stock_sizes_from_own_weight(_parts_dg")
    assert src.index("apply_wire_callouts_to_parts as _wire_callouts") < at, "after the Ø callouts"
    assert src.index("revalidate_from_own_sheets(_parts_dg") < at, "after its own weight is re-read"
    assert src.index("apply_section_lengths_from_own_sheets(_parts_dg") < at
    assert at < src.index("estimate_document(summary[\"manufacturing_writeup\"]"), "before costing"


# ── 3. the Wire block, priced by the sheet's own wire formula ────────────────────────────

def _template(path: Path, wire_rate=None) -> Path:
    """The Estimate sheet's block labels and totals formula at the template's rows (as the
    D-602 fixture writes them), and its Wire Cost Per Tonne cell where one is given."""
    import openpyxl
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "Estimate"
    if wire_rate is not None:
        ws.cell(3, 11, "Wire Cost Per Tonne")
        ws.cell(3, 12, wire_rate)
    for row, text in ((10, "Bill of Materials (Per Unit)"), (51, "Wire"),
                      (52, "Part Description"), (61, "Sheet Steel"), (62, "Part Description"),
                      (82, "Other Sheet Material"), (83, "Part Description"),
                      (92, "Total Material Cost"), (94, "Labour"), (95, "Operation"),
                      (168, "Total Labour Cost (Including  Downtime)")):
        ws.cell(row, 3, text)
    ws.cell(92, 13, "=(SUM(M11:M50)+SUM(M53:M60)+SUM(M63:M81)+SUM(M84:M91)+AF83)")
    book.save(path)
    return path


def _built(code, name, page):
    """A wire record as the scan builds it, before the document builder's fixes run on it."""
    from document_builder import _empty_part_record
    part = _empty_part_record(code, None, name, 4)
    part.update({"pages": [page], "materials": ["MILD STEEL WIRE"],
                 "normalized_material": "MILD STEEL WIRE", "page_roles": ["detail"]})
    return part


def test_the_two_wires_land_on_the_wire_block_at_their_gauge_and_length(tmp_path, monkeypatch,
                                                                       capsys):
    import openpyxl
    import config
    import estimator as E
    import wb_populate
    from document_builder import _apply_post_build_fixes
    _, summary = _pack()
    parts = _apply_post_build_fixes([_built(f"{J}-05M", "TABLE EDGE - WIRE A", 5),
                                     _built(f"{J}-06M", "TABLE EDGE - WIRE B", 6)], summary)
    # Before this rule, what the builder leaves is not wire stock and carries no size.
    assert all(not p.get("wire_gauge_mm") and not p.get("wire_length_mm") for p in parts)
    assert dpg.apply_round_stock_sizes_from_own_weight(parts, summary) == [f"{J}-05M", f"{J}-06M"]
    # A third wire whose schedule gave it a gauge the template's table does not hold.
    odd = _wire(f"{J}-09M", "SUPPORT WIRE", 9, wire_gauge_mm=7.0, wire_length_mm=500.0,
                manufacturing_interpretation={"stock_form": "wire"})
    parts.append(odd)
    summary = dict(summary, declared_product=f"{J}-GA", drawing_number=f"{J}-GA",
                   manufacturing_writeup={"parts": parts}, document_analysis={"bom_rows": []},
                   llm_full_extract={}, job_folder=str(tmp_path))
    summary["estimate_summary"] = E.estimate_document(parts, summary=summary)
    summary["part_estimates"] = summary["estimate_summary"]["part_estimates"]
    by_pn = {pe["part_number"]: pe for pe in summary["part_estimates"]}

    # The line is the sheet's own wire formula: Wire Cost Per Tonne over the gauge table's metres
    # per tonne, by the length, plus scrap — never a market figure.
    rate = float(config.WORKBOOK_INPUT_DEFAULTS["wire_cost_per_tonne_gbp"])
    scrap = float(config.SCRAP_PERCENTAGE)
    for code, gauge in ((f"{J}-05M", 4.0), (f"{J}-06M", 8.0)):
        me = by_pn[code]["material_estimate"]
        assert me["cost_method"] == "workbook_bar_formula"
        assert (me["stock_form"], me["wire_gauge_mm"], me["wire_length_mm"]) == ("wire", gauge, 1100.0)
        assert me["stock_estimate"]["metres_per_tonne"] == config.WIRE_GAUGE_TABLE[gauge]
        assert me["stock_estimate"]["gauge_source"] == SOURCE
        expect = rate / config.WIRE_GAUGE_TABLE[gauge] / 1000.0 * 1100.0 * (1.0 + scrap)
        assert me["cost_per_part_gbp"] == pytest.approx(expect, abs=1e-4)
        assert "INDICATIVE" not in _flags(by_pn[code])
        assert not by_pn[code].get("material_market_indication")
        # ...and the rate it is priced at is said to be the template's allowance, not a price.
        said = _flags(by_pn[code])
        assert _rate_words(rate) in said
        assert f"Confirm the mild steel wire price for Ø{gauge:g} with purchasing." in said
        assert "wire_rate_is_an_undated_template_allowance" in me["reliability_flags"]
        assert me["rate_provenance"]["purchasing_source"] is None
        assert me["rate_provenance"]["price_date"] is None
        assert me["price_source"]["price_date"] is None, "an allowance has no price date"
        assert me["price_source"]["review_reason"] == me["note"]
        assert "PROVISIONAL" in me["note"]

    monkeypatch.setenv("SDI_WB_TEMPLATE", str(_template(tmp_path / "template.xlsx", 1600)))
    monkeypatch.setitem(wb_populate.CELL_MAP, "output_dir", str(tmp_path / "out"))
    capsys.readouterr()
    out = wb_populate.populate_workbook(summary, "D692")
    printed = capsys.readouterr().out
    assert out, "the workbook writer produced no book"
    ws = openpyxl.load_workbook(out)["Estimate"]
    w = wb_populate.CELL_MAP["tube"]
    rows = {}
    for r in range(w["first_row"], w["last_row"] + 1):
        desc = str(ws.cell(r, w["col_desc"]).value or "")
        if desc:
            rows[desc.split()[0]] = r
    for code, gauge in ((f"{J}-05M", 4.0), (f"{J}-06M", 8.0)):
        assert code in rows, f"{code} is not on the Wire block"
        r = rows[code]
        assert float(ws.cell(r, w["col_gauge"]).value) == gauge
        assert float(ws.cell(r, w["col_length"]).value) == 1100.0
        assert int(ws.cell(r, w["col_qty"]).value) == 4
        assert "is not a gauge in" not in _flags(by_pn[code])
        # The row itself says its rate is provisional, so it never reads as a stock price.
        assert str(ws.cell(r, w["col_desc"]).value).endswith(
            "[PROVISIONAL RATE - CONFIRM WITH PURCHASING]")
    # And the book says it once, at the sheet's own figure.
    assert ("every row is priced from the template's Wire Cost Per Tonne (£1,600/t = £1.60/kg) "
            "— an undated template allowance with no purchasing source and no price date. "
            "PROVISIONAL, not a verified stock price: confirm the mild steel wire price for "
            "Ø4, Ø7, Ø8 with purchasing.") in printed

    # The template's table holds 4 and 8; a 7 it does not hold is said, and no row is invented.
    gauges, _where = wb_populate.template_wire_gauges(ws, w)
    assert 4.0 in gauges and 8.0 in gauges and 7.0 not in gauges
    assert f"{J}-09M" in rows
    said = _flags(by_pn[f"{J}-09M"])
    assert "Ø7 is not a gauge in" in said and "as Ø6 wire" in said
    assert "No gauge row has been added" in said


def _rate_words(rate):
    return (f"PROVISIONAL wire rate: £{rate:,.0f}/t (£{rate / 1000.0:.2f}/kg) is the rate held "
            f"for the estimating template's Wire Cost Per Tonne — an undated template allowance "
            f"with no purchasing source and no price date, not a verified stock price.")


def test_the_wire_rate_is_said_to_be_a_provisional_template_allowance():
    """The reviewer's words, pinned: provisional, the template's wire rate, no purchasing
    source or date, not a verified stock price, confirm with purchasing."""
    import estimator as E
    got = E.wire_rate_is_provisional(1600.0, 4.0, "MILD STEEL WIRE")
    assert got["said"] == (
        "PROVISIONAL wire rate: £1,600/t (£1.60/kg) is the rate held for the estimating "
        "template's Wire Cost Per Tonne — an undated template allowance with no purchasing "
        "source and no price date, not a verified stock price. Confirm the mild steel wire "
        "price for Ø4 with purchasing.")
    assert E.wire_rate_is_provisional(1600.0, 8.0, "MILD_STEEL")["said"].endswith(
        "Confirm the mild steel wire price for Ø8 with purchasing.")


def test_a_stainless_catalogue_row_never_prices_a_mild_steel_wire(monkeypatch):
    """Purchasing's catalogue holds no mild steel Ø4 or Ø8 wire; its nearest row is a 4 mm 304
    stainless at £20/kg. Whatever the catalogue answers, the wire line is priced and stamped at
    the template's wire rate, and names no catalogue row as its source."""
    import config
    import estimator as E
    stainless = {"selected": {"price": 20.0, "unit": "GBP/kg", "source": "sdi_live",
                              "currency": "GBP",
                              "metadata": {"supplier_name": "SDI Live",
                                           "description": "4MM 304 STAINLESS WIRE",
                                           "price_date": "2026-10-01"}}}
    monkeypatch.setattr(E, "_resolve_material_price",
                        lambda *a, **k: {"result": stainless, "applied_price_per_kg": 20.0,
                                         "applied_basis": "GBP_per_kg"})
    parts, summary = _pack()
    dpg.apply_round_stock_sizes_from_own_weight(parts, summary)
    me = E.estimate_material(parts[0])
    rate = float(config.WORKBOOK_INPUT_DEFAULTS["wire_cost_per_tonne_gbp"])
    expect = (rate / config.WIRE_GAUGE_TABLE[4.0] / 1000.0 * 1100.0
              * (1.0 + config.SCRAP_PERCENTAGE))
    assert me["cost_per_part_gbp"] == pytest.approx(expect, abs=1e-4)
    stamp = me["price_source"]
    assert stamp["source_name"] == "config_wire_cost_per_tonne"
    assert "SDI Live" not in str(stamp["supplier_source"])
    assert "STAINLESS" not in str(stamp).upper()
    assert stamp["price_date"] is None


def test_the_gauge_table_is_read_from_the_template_where_its_formula_names_it():
    import openpyxl
    import wb_populate
    ws = openpyxl.Workbook().active
    w = {"first_row": 53, "col_length": 7}
    ws.cell(53, 8, "=LOOKUP(F53,$H$151:$H$153,$I$151:$I$153)")
    for r, (g, mpt) in enumerate(((3, 18020), (4, 10140), (6, 4505)), start=151):
        ws.cell(r, 8, g)
        ws.cell(r, 9, mpt)
    gauges, where = wb_populate.template_wire_gauges(ws, w)
    assert gauges == [3.0, 4.0, 6.0]
    assert "H151:H153" in where
    # With no formula naming it, the engine's copy of the template's table, which holds 4 and 8.
    gauges, where = wb_populate.template_wire_gauges(openpyxl.Workbook().active, w)
    assert 4.0 in gauges and 8.0 in gauges
    assert "config.WIRE_GAUGE_TABLE" in where


def test_the_mass_is_the_solid_round_the_gauge_table_was_built_from():
    """The sheet's metres per tonne ARE the solid round at 7850 kg/m3, so a size the weight chose
    at that density is priced by the same steel the sheet weighs."""
    import config
    for gauge in (4.0, 8.0):
        assert 1000.0 / dpg.round_stock_mass_kg(gauge, 1000.0, 7850) == pytest.approx(
            config.WIRE_GAUGE_TABLE[gauge], rel=1e-3)
    assert math.isclose(dpg.round_stock_mass_kg(2, 1000, 1000), math.pi / 1000, rel_tol=1e-9)
