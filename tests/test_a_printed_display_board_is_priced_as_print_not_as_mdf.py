"""A PRINTED DISPLAY BOARD IS PRICED AS PRINT, NOT AS MDF (20 Nov 2026).

12754-01-GA and 12757-00-GA: the drawings state "2 mm printed display board". The engine's
board rule turned every material holding the word BOARD into MDF, so the graphic was costed
as 2 mm MDF: no MDF price at that gauge (material £0) and MDF CNC routing charged in its
place. The print rule never saw it: it looked for "printed" in the finish, notes and
description, not in the material.

JG: "we have the print AI calculator that for any material should give a price".

Now:
  * a print substrate (display board, foam board ...) keeps its name; plain board is still MDF;
  * a material that states print, or is a print substrate by name, makes the part printed;
  * the sheet's row is found with the print words left out ("PRINTED DISPLAY BOARD" is the
    "2mm Display Board" row), and the gauge stated in the material is used when the part
    has none;
  * the line is the calculator's price, and the engine's MDF material and routing go.

The workbook is built here with the calculator's layout and invented figures.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "source_connectors"))

import print_calculator_sheet as sheet  # noqa: E402
import print_costing as pc  # noqa: E402

ROWS = [("3mm White Foamed PVC", "Full colour digital 1 side", "1220x2440mm", 30.0, 100.0),
        ("2mm Display Board", "Full colour digital 1 side", "1220x2440mm", None, 80.0),
        ("2mm White HIPS", "Full colour digital 1 side", "1220x2440mm", None, 90.0),
        ("White Vinyl", "Full colour digital 1 side", "1000x1000mm", None, 60.0)]


def _book(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"], ws["C1"], ws["D1"], ws["E1"] = "AI BUDGET COSTING", "Sheet Size", "Set-up Cost", "Run Cost (print & cut)"
    for n, row in enumerate(ROWS, 2):
        for c, v in enumerate(row, 1):
            ws.cell(n, c).value = v
    ws["A9"], ws["I9"], ws["I10"] = "Material", "Scrap %", 0.1
    path = tmp_path / "print.xlsx"
    wb.save(path)
    return sheet.read_sheet(str(path))


def _graphic(**over):
    p = {"part_number": "T-900-03G", "description": "HEADER GRAPHIC", "quantity": 1,
         "normalized_material": "2MM PRINTED DISPLAY BOARD",
         "materials": ["2MM PRINTED DISPLAY BOARD"], "normalized_thickness_mm": None,
         "normalized_finish": None, "blank_length_mm": 600.0, "blank_width_mm": 300.0}
    p.update(over)
    return p


def _mdf_estimate():
    return {"part_number": "T-900-03G", "unit_total_cost_gbp": 46.47,
            "material_estimate": {"unit_material_cost_gbp": 0.0, "cost_method": "sheet_rate"},
            "labour_estimate": {"total_labour_cost_gbp": 46.47}}


def _cost(line, qty):
    line["unit_total_cost_gbp"] = line["unit_cost_gbp"]
    return line


def _stub(pn, desc, qty):
    return {"part_number": pn, "description": desc, "quantity": qty, "review_flags": []}


def test_a_print_substrate_is_not_collapsed_to_mdf_and_plain_board_still_is():
    import estimator
    import llm_full_job
    for text in ("2MM PRINTED DISPLAY BOARD", "DISPLAY BOARD", "5mm Foam Board"):
        assert estimator._canonical_material_family(text) != "MDF", text
        assert llm_full_job._norm_material(text) != "MDF", text
    # the contrast: a board that is not a print substrate is the MDF it always was
    for text in ("18MM BOARD", "SOFT TOUCH LAMINATE BOARD"):
        assert estimator._canonical_material_family(text) == "MDF", text
        assert llm_full_job._norm_material(text) == "MDF", text


def test_the_material_makes_the_part_printed():
    assert pc.printed_basis(_graphic())["how"] == "stated"
    assert pc.printed_basis(_graphic(normalized_material="DISPLAY BOARD",
                                     materials=["DISPLAY BOARD"]))["how"] == "stated"
    # the contrast: an MDF panel, and a display board stated not printed
    assert pc.printed_basis(_graphic(normalized_material="MDF", materials=["18MM MDF"],
                                     description="SIDE PANEL")) is None
    assert pc.printed_basis(_graphic(normalized_material="DISPLAY BOARD - NOT PRINTED",
                                     materials=[], description="SIDE PANEL")) is None


def test_the_row_is_found_without_the_print_words_and_the_gauge_from_the_material(tmp_path):
    read = _book(tmp_path)
    material, gauge, where = pc.material_and_gauge(_graphic(), read)
    assert gauge == 2.0 and "material" in where
    row, why = pc.substrate_for(read, material, gauge)
    assert row is not None and row["name"] == "2mm Display Board", why
    # a resolved family that names no row gives way to the material as the drawing wrote it
    material, _g, _w = pc.material_and_gauge(
        _graphic(normalized_material="BOUGHT_IN", normalized_thickness_mm=2.0), read)
    assert pc.substrate_for(read, material, 2.0)[0]["name"] == "2mm Display Board"
    # the contrast: at a gauge the sheet does not hold it is not priced, and says why
    row, why = pc.substrate_for(read, "PRINTED DISPLAY BOARD", 5.0)
    assert row is None and "5 mm" in why


def test_the_line_is_the_calculators_price_and_the_mdf_charge_goes(tmp_path):
    read = _book(tmp_path)
    out = pc.settle(_graphic(), _mdf_estimate(), 10, _cost, _stub, read=read)
    rec = out["print_calculator"]
    assert rec["applied"] is True and rec["substrate"] == "2mm Display Board"
    assert out["unit_total_cost_gbp"] > 0 and out["unit_total_cost_gbp"] != 46.47
    assert rec["withdrawn"]["labour_gbp"] == 46.47, "the MDF routing is withdrawn, and said"
    # the contrast: an MDF panel is left exactly as the engine costed it
    plain = pc.settle(_graphic(normalized_material="MDF", materials=["18MM MDF"],
                               normalized_thickness_mm=18.0, description="SIDE PANEL"),
                      _mdf_estimate(), 10, _cost, _stub, read=read)
    assert "print_calculator" not in plain and plain["unit_total_cost_gbp"] == 46.47
