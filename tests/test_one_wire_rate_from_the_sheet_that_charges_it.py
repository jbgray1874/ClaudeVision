"""One wire rate, from the sheet that charges it (D-697).

12693-01-GA's 22:06 report said each wire was "priced at the config rate £1500/t", while the
workbook template's own Wire Cost Per Tonne cell holds £1,600 and the Wire rows charge at
that. The estimate read the rate from config on every wire path, and its scan of the shop
rates never included the template the workbook is built from. The estimate now reads the
template's cell where it can, says so on the line, and uses the config figure only where the
template cannot be read, saying that instead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator  # noqa: E402


def _template(tmp_path, wire=1600):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["J3"], ws["L3"] = "Wire Cost Per Tonne = ", wire
    ws["J5"], ws["L5"] = "Sheet Steel Cost Per Tonne =", 900
    ws["C6"], ws["D6"] = "Quantity", 1
    path = tmp_path / "template.xlsx"
    wb.save(path)
    return path


@pytest.fixture(autouse=True)
def _fresh_cache():
    estimator._WIRE_RATE_BY_TEMPLATE.clear()
    yield
    estimator._WIRE_RATE_BY_TEMPLATE.clear()


def test_the_templates_cell_is_the_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(_template(tmp_path)))
    assert estimator.wire_rate_per_tonne() == (1600.0, "template")


def test_no_readable_template_falls_back_to_config_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(tmp_path / "missing.xlsx"))
    rate, source = estimator.wire_rate_per_tonne()
    assert source == "config"
    assert rate == float(estimator.config.WORKBOOK_INPUT_DEFAULTS["wire_cost_per_tonne_gbp"])


def _wire():
    return {"part_number": "12999-01-05M", "description": "TABLE EDGE - WIRE A",
            "normalized_material": "MILD_STEEL", "wire_gauge_mm": 4.0, "wire_length_mm": 1100.0,
            "_bar_recognised": True, "stock_form": "wire",
            "manufacturing_interpretation": {"stock_form": "wire", "wire_gauge_mm": 4.0},
            "textual_operations": ["saw"], "quantity": 4}


def test_the_wire_line_charges_and_states_the_templates_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(_template(tmp_path)))
    part = _wire()
    pe = estimator.estimate_part(part, job_quantity=1)
    unit = (pe.get("material_estimate") or {}).get("unit_material_cost_gbp")
    # £1,600/t over Ø4's 10,140 m/t, 1100 mm, 4% scrap
    assert unit == pytest.approx(1600 / 10140 / 1000 * 1100 * 1.04, rel=1e-3)
    said = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "£1,500" not in said and "config rate" not in said
    assert "£1,600" in said


def test_with_no_template_the_line_says_the_template_was_not_read(tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(tmp_path / "missing.xlsx"))
    part = _wire()
    estimator.estimate_part(part, job_quantity=1)
    said = " ".join(str(f) for f in part.get("review_flags") or [])
    if "wire priced" in said:
        assert "was not read" in said
