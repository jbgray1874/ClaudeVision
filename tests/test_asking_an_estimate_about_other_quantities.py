"""A quantity sweep must answer from the sheet, and must not change it.

Four full runs to price 10/25/50/100 is hours of a runner that does one job at a time, to
re-read drawings that do not depend on the quantity at all. The sheet already knows how: the
throughput the engine writes is pieces per hour and carries no quantity, so setting the order
cell and recalculating gives the template's own labour curve.

The two things that make it trustworthy are that it never writes to the estimate it was given,
and that it says out loud what it cannot work out — freight priced at the old quantity, and
bought-ins that do not step down because the price-break lookup was overwritten. A saved
variant is a new file, and it opens on a page that says both.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import quantity_sweep                                                   # noqa: E402


def test_a_machine_with_no_excel_declines_rather_than_raising(tmp_path):
    book = tmp_path / "12552-00.xlsx"
    book.write_bytes(b"not really a workbook")
    assert quantity_sweep.sweep(book, [10, 25]) is None


def test_a_missing_workbook_is_reported_not_raised(tmp_path):
    assert quantity_sweep.sweep(tmp_path / "nothing.xlsx", [10]) is None


def test_it_never_writes_to_the_workbook_it_was_given():
    """Variants are saved to their own files. The estimate itself is never written to.

    An estimate that has gone to an estimator must not come back altered by a question
    somebody asked about it — and a quantity variant that overwrote the original would be the
    worst possible way to find that out.
    """
    source = (SRC / "quantity_sweep.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    in_place = [n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("Save", "SaveCopyAs")]
    assert not in_place, "Save writes to the file we were handed; there is no reason to"

    variant = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_save_variant")
    save_as = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "SaveAs"]
    assert save_as, "the variants have to be written somehow"
    for call in save_as:
        assert any(call is inner for inner in ast.walk(variant)), (
            "SaveAs belongs only in the variant writer, where the destination is a new name")

    assert "with_name(" in ast.get_source_segment(source, variant), (
        "the variant's path is derived from the original's NAME, so it cannot resolve back "
        "to the original file")

    closes = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "Close"]
    assert closes, "the workbook has to be closed or Excel keeps it locked"
    for call in closes:
        assert any(kw.arg == "SaveChanges" and kw.value.value is False
                   for kw in call.keywords), (
            "closed with SaveChanges=False explicitly — the default is to prompt, and a "
            "headless Excel with a dialog open holds the file against the next run")


def test_a_saved_variant_opens_on_a_page_that_says_what_it_is():
    """It looks exactly like a finished estimate. That is the danger."""
    source = (SRC / "quantity_sweep.py").read_text(encoding="utf-8")
    variant = ast.get_source_segment(
        source, next(n for n in ast.walk(ast.parse(source))
                     if isinstance(n, ast.FunctionDef) and n.name == "_save_variant"))
    assert "NOT A QUOTE" in variant
    assert "FREIGHT IS STILL PRICED AT" in variant
    assert "BOUGHT-IN PRICES DID NOT STEP DOWN" in variant
    assert variant.index("ws.Activate()") < variant.index("SaveAs"), (
        "the sheet active at save time is the sheet Excel opens on — the banner has to be "
        "activated BEFORE the save or the file opens on the Estimate tab and the warning is "
        "a page nobody turns to")


def test_the_freight_taken_back_out_is_read_off_the_sheet():
    """A sweep of a 40-off estimate must not subtract a 1-off pallet nobody paid for."""
    result = {"workbook": "x.xlsx", "order_qty_cell": "D6", "baseline_quantity": 40,
              "freight_on_sheet": {"PACKAGING": 4.25, "DELIVERY": 4.25},
              "rows": [{"quantity": 100, "material": 400.0, "labour": 80.0, "unit": 516.13}]}
    assert quantity_sweep.commercial_correction(result)[0]["freight_carried_gbp"] == 8.5


def test_the_order_cell_is_put_back_before_it_closes():
    """Belt and braces over SaveChanges=False: the sheet is left as it was found."""
    source = (SRC / "quantity_sweep.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "sweep")
    assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)]
    assert any(isinstance(a.value, ast.Name) and a.value.id == "original" for a in assigns), (
        "the original quantity is read before the loop and written back after it")


def test_the_order_cell_comes_from_the_populators_own_map():
    """Two records of which cell drives the sheet is one record too many."""
    source = (SRC / "quantity_sweep.py").read_text(encoding="utf-8")
    assert 'CELL_MAP["header"]["order_qty"]' in source


def test_the_freight_correction_travels_through_the_absorption_divisor():
    """Freight sits in material, and material reaches the unit price through the divisor.

    Subtracting it at unit level without dividing would leave the corrected figure wrong by
    the absorption factor — GBP 170 of freight is GBP 182.80 of unit price at 0.93.
    """
    result = {"workbook": "x.xlsx", "order_qty_cell": "D6", "baseline_quantity": 1,
              "rows": [{"quantity": 10, "material": 541.42, "labour": 323.84,
                        "unit": 930.39}]}
    corrected = quantity_sweep.commercial_correction(result, 85.0, 85.0)
    row = corrected[0]
    assert row["freight_carried_gbp"] == 170.0
    # 170 / 0.93 = 182.80, so the corrected unit is 930.39 - 182.80.
    assert abs(row["unit_less_freight"] - 747.59) < 0.02, (
        "the correction has to travel the same path the money did")


def test_it_names_both_things_it_cannot_correct():
    result = {"workbook": "12552-00.xlsx", "order_qty_cell": "D6", "baseline_quantity": 1,
              "rows": [{"quantity": 25, "material": 400.0, "labour": 90.0, "unit": 526.88}]}
    text = quantity_sweep.to_markdown(
        result, quantity_sweep.commercial_correction(result, 85.0, 85.0))
    assert "Packaging and delivery" in text
    assert "do not step down" in text, (
        "the price-break lookup is overwritten with a literal, so bought-ins are flat at "
        "every quantity — silence there overstates the discount available")
    assert "the estimate itself was not written to" in text


def test_a_sweep_with_no_freight_figures_still_reports():
    result = {"workbook": "12552-00.xlsx", "order_qty_cell": "D6", "baseline_quantity": 1,
              "rows": [{"quantity": 10, "material": 400.0, "labour": 120.0, "unit": 559.14}]}
    text = quantity_sweep.to_markdown(result)
    assert "£559.14" in text
    assert "| 10 |" in text
