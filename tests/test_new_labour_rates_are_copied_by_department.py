"""New labour rates are copied into the AI template by department, and the engine reads them
from the template the book is built from (D-704).

James Ryan, 3 Nov 2026: "Blank estimate sheet attached with updated labour rates to start
using with immediate effect ... factor these new rates (see I115 to I146) into the AI system."
His blank and the AI template are different files: the AI template's rate block sits lower
(rows 235-266). tools/rates/apply_labour_rates.py copies the rates across by label and code,
never by row, refuses a mismatch, keeps a backup and checks the read-back. And the engine's own
rate card now reads the AI template first, so the book's charged rows and the engine's own
figures come from one card.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "rates"))
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import apply_labour_rates as alr  # noqa: E402
import config  # noqa: E402

CARD_2026 = [("Assemble/pack (Metal)", 28.5588, "PACM", 15), ("Fold", 40.4703, "FOLD", 30),
             ("Laser (Metal)", 68.1868, "LASM", 10), ("Weld (CO2)", 41.7716, "WELD", 30)]
CARD_2027 = [("Assemble/pack (Metal)", 29.5882, "PACM", 15), ("Fold", 41.4404, "FOLD", 30),
             ("Laser (Metal)", 77.2934, "LASM", 10), ("Weld (CO2)", 43.6386, "WELD", 30)]


def _book(path: Path, rows, header_row: int, extra_after=True):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["J3"], ws["L3"] = "Wire Cost Per Tonne = ", 1600
    ws.cell(header_row, 8).value, ws.cell(header_row, 9).value = "Labour", "Rate"
    ws.cell(header_row, 10).value, ws.cell(header_row, 11).value = "Dept", "Set Up"
    for n, (label, rate, code, setup) in enumerate(rows, start=header_row + 1):
        ws.cell(n, 8).value, ws.cell(n, 9).value = label, rate
        ws.cell(n, 10).value, ws.cell(n, 11).value = code, setup
    if extra_after:            # the wire gauge table below the block: a numeric J ends it
        g = header_row + len(rows) + 4
        ws.cell(g, 8).value, ws.cell(g, 9).value, ws.cell(g, 10).value = "Gauge", "Metres", "Price"
        ws.cell(g + 1, 8).value, ws.cell(g + 1, 9).value, ws.cell(g + 1, 10).value = 4, 10140, 0.158
    wb.save(path)
    return path


@pytest.fixture
def pair(tmp_path):
    src = _book(tmp_path / "Blank Estimate Sheet 2027.xlsx", CARD_2027, 114)
    tpl = _book(tmp_path / "Blank Estimate Sheet  WB 2026.xlsx", CARD_2026, 234)
    return src, tpl


def _rates(path: Path):
    ws = openpyxl.load_workbook(path, data_only=True)["Estimate"]
    return {ws.cell(r, 10).value: ws.cell(r, 9).value for r in range(235, 239)}


def test_rates_are_copied_by_department_into_the_templates_own_rows(pair):
    src, tpl = pair
    changes = alr.run(src, tpl, "openpyxl", dry_run=False, say=lambda s: None, stamp="T")
    assert {c.code for c in changes} == {"PACM", "FOLD", "LASM", "WELD"}
    assert _rates(tpl) == {"PACM": 29.5882, "FOLD": 41.4404, "LASM": 77.2934, "WELD": 43.6386}
    ws = openpyxl.load_workbook(tpl)["Estimate"]
    assert ws["L3"].value == 1600, "nothing outside the rate column changes"
    assert [ws.cell(r, 11).value for r in range(235, 239)] == [15, 30, 10, 30]


def test_a_backup_is_kept_beside_the_template(pair):
    src, tpl = pair
    alr.run(src, tpl, "openpyxl", dry_run=False, say=lambda s: None, stamp="T")
    backup = tpl.with_name("Blank Estimate Sheet  WB 2026 (before labour rates T).xlsx")
    assert backup.is_file() and _rates(backup)["LASM"] == 68.1868


def test_a_dry_run_writes_nothing(pair):
    src, tpl = pair
    changes = alr.run(src, tpl, "openpyxl", dry_run=True, say=lambda s: None)
    assert len(changes) == 4 and _rates(tpl)["LASM"] == 68.1868
    assert not list(tpl.parent.glob("*before labour rates*"))


def test_a_department_missing_from_the_source_changes_nothing(tmp_path):
    src = _book(tmp_path / "src.xlsx", CARD_2027[:3], 114)
    tpl = _book(tmp_path / "tpl.xlsx", CARD_2026, 234)
    with pytest.raises(alr.RateError, match="Weld"):
        alr.run(src, tpl, "openpyxl", dry_run=False, say=lambda s: None)
    assert _rates(tpl)["LASM"] == 68.1868


def test_a_code_that_disagrees_changes_nothing(tmp_path):
    wrong = [r if r[2] != "FOLD" else ("Fold", 41.44, "FOLX", 30) for r in CARD_2027]
    src = _book(tmp_path / "src.xlsx", wrong, 114)
    tpl = _book(tmp_path / "tpl.xlsx", CARD_2026, 234)
    with pytest.raises(alr.RateError, match="FOLX"):
        alr.run(src, tpl, "openpyxl", dry_run=False, say=lambda s: None)


def test_an_implausible_rate_changes_nothing(tmp_path):
    bad = [r if r[2] != "LASM" else ("Laser (Metal)", 7729.34, "LASM", 10) for r in CARD_2027]
    src = _book(tmp_path / "src.xlsx", bad, 114)
    tpl = _book(tmp_path / "tpl.xlsx", CARD_2026, 234)
    with pytest.raises(alr.RateError, match="outside"):
        alr.run(src, tpl, "openpyxl", dry_run=False, say=lambda s: None)


def test_a_set_up_that_differs_is_reported_not_copied(tmp_path):
    src_rows = [r if r[2] != "WELD" else ("Weld (CO2)", 43.6386, "WELD", 45) for r in CARD_2027]
    src = _book(tmp_path / "src.xlsx", src_rows, 114)
    tpl = _book(tmp_path / "tpl.xlsx", CARD_2026, 234)
    said = []
    alr.run(src, tpl, "openpyxl", dry_run=False, say=said.append, stamp="T")
    assert any("set-up" in s and "NOT copied" in s for s in said)
    ws = openpyxl.load_workbook(tpl)["Estimate"]
    assert ws.cell(238, 11).value == 30


def test_the_engine_reads_its_rate_card_from_the_template_the_book_is_built_from(pair,
                                                                                monkeypatch):
    src, tpl = pair
    alr.run(src, tpl, "openpyxl", dry_run=False, say=lambda s: None, stamp="T")
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(tpl))
    monkeypatch.setattr(config, "AI_ESTIMATE_XLSX_TEMPLATE",
                        _book(tpl.parent / "local 2026 copy.xlsx", CARD_2026, 114))
    card, source = config.read_template_rate_card()
    assert card["laser_cutting"] == 77.2934, "the AI template's card, not the local copy's"
    assert "WB 2026" in source


def test_without_the_ai_template_the_local_copy_still_serves(pair, monkeypatch, tmp_path):
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(tmp_path / "absent.xlsx"))
    monkeypatch.setattr(config, "AI_ESTIMATE_XLSX_TEMPLATE",
                        _book(tmp_path / "local.xlsx", CARD_2027, 114))
    card, _ = config.read_template_rate_card()
    assert card["welding"] == 43.6386


def test_the_fallback_card_is_the_2027_card():
    assert config.HOURLY_RATES_GBP["laser_cutting"] == 77.29
    assert config.HOURLY_RATES_GBP["welding"] == 43.64
    assert config.HOURLY_RATES_GBP["powder_coating"] == 362.52


def test_one_template_path_in_config_populate_and_the_runner():
    import sdi_estimate_runner as runner
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    populate = re.search(r'"template_path": r"([^"]+)"', src).group(1)
    assert config.WB_TEMPLATE_DEFAULT == populate == runner.WB_TEMPLATE_DEFAULT
