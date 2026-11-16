"""The Estimate sheet we write hides its unused slots; nothing moves and nothing is lost.

James Gray, 23 Sep 2026: "removing rows not written to in the estimating s/sheet to compress
it for it to be easier to read from estimating. Not the blank one we use as the source but
the one we create." Review: group and hide rather than delete — the totals sum through fixed
row ranges (M96:M167) — and prove the shortened sheet keeps the same totals and quantity
breaks, and that a line typed into an opened slot still recalculates.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
openpyxl = pytest.importorskip("openpyxl")

import workbook_compact as wc                                        # noqa: E402


def _estimate():
    """The template's shape in miniature: a material block and a labour block, each a title,
    a column header, formula-carrying slots and a total summing a fixed range."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["D6"] = 1
    ws["C9"] = "Standard Materials"
    ws["C10"] = "Bill of Materials (Per Unit)"; ws["K10"] = "Qty Per Unit"
    for r in range(11, 21):
        ws[f"M{r}"] = f"=(J{r}*K{r})*(100%+L{r})"
    ws["C11"] = "11650-02-01M TOP PANEL"; ws["J11"] = 3.6; ws["K11"] = 1; ws["L11"] = 0.04
    ws["C12"] = "PACKAGING"; ws["J12"] = 15; ws["K12"] = 1; ws["L12"] = 0
    ws["C21"] = "Total Material Cost"; ws["M21"] = "=_xlfn.AGGREGATE(9,6,M11:M20)"
    ws["C23"] = "Labour"
    ws["C24"] = "Operation"; ws["H24"] = "Qty Per Unit"
    for r in range(25, 40):
        ws[f"M{r}"] = f"=IF(H{r}=0,0,H{r}*I{r}/$D$6)"
    ws["C25"] = "Fold"; ws["H25"] = 1; ws["I25"] = 40
    ws["C40"] = "Total Labour Cost"; ws["M40"] = "=SUM(M25:M39)"
    ws["M42"] = "=M21+M40"
    return wb


def test_unused_slots_are_hidden_and_everything_else_stays():
    wb = _estimate()
    out = wc.compact_estimate(wb)
    ws = wb["Estimate"]
    hidden = {r for r, d in ws.row_dimensions.items() if d.hidden}
    assert hidden == set(range(13, 21)) | set(range(26, 40)), sorted(hidden)
    assert out["hidden"] == 22
    for r in (9, 10, 11, 12, 21, 23, 24, 25, 40, 42):
        assert r not in hidden, f"row {r} (a title, header, line or total) was hidden"
    # Nothing moved: every formula is where it was.
    assert ws["M40"].value == "=SUM(M25:M39)" and ws["M20"].value.startswith("=(J20")
    assert all(ws.row_dimensions[r].outlineLevel == 1 for r in hidden)


def test_a_slot_with_only_a_quantity_is_kept():
    wb = _estimate()
    wb["Estimate"]["K15"] = 2              # somebody typed a quantity and no description yet
    wc.compact_estimate(wb)
    assert not wb["Estimate"].row_dimensions[15].hidden


def test_it_refuses_on_a_sheet_whose_totals_skip_hidden_rows():
    wb = _estimate()
    wb["Estimate"]["M40"] = "=SUBTOTAL(109,M25:M39)"
    out = wc.compact_estimate(wb)
    assert out["hidden"] == 0 and "ignores hidden rows" in out["refused"]


def test_it_is_idempotent():
    wb = _estimate()
    a = wc.compact_estimate(wb)["hidden"]
    b = wc.compact_estimate(wb)["hidden"]
    assert a == b == 22


def test_the_writer_compacts_the_book_it_writes_and_only_that():
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    call = src.index("_cmp = compact_estimate(wb)")
    save = src.index("wb.save(out_path)")
    assert call < save, "compaction must happen on the output book, before it is saved"
    assert 'getattr(config, "ESTIMATE_COMPACT_UNUSED_SLOTS", True)' in src
    import config
    assert config.ESTIMATE_COMPACT_UNUSED_SLOTS in (True, False)


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
def test_totals_are_unchanged_and_a_line_in_an_opened_slot_counts(tmp_path):
    """Recalculated by a real spreadsheet engine, not asserted from the formulas."""
    def recalc(wb, name):
        src = tmp_path / f"{name}.xlsx"
        wb.save(src)
        outdir = tmp_path / "lo"
        subprocess.run(["soffice", "--headless", "--calc", "--convert-to", "xlsx",
                        "--outdir", str(outdir), str(src)], capture_output=True, timeout=180)
        ws = openpyxl.load_workbook(outdir / f"{name}.xlsx", data_only=True)["Estimate"]
        return [ws[c].value for c in ("M21", "M40", "M42")]

    full = recalc(_estimate(), "full")
    wb = _estimate(); wc.compact_estimate(wb)
    short = recalc(wb, "short")
    assert full == short and full[2], (full, short)

    wb = _estimate(); wc.compact_estimate(wb)
    ws = wb["Estimate"]
    ws["C16"] = "MANUAL LINE"; ws["J16"] = 10; ws["K16"] = 2; ws["L16"] = 0
    manual = recalc(wb, "manual")
    assert manual[0] == pytest.approx(full[0] + 20) and manual[2] == pytest.approx(full[2] + 20)

    wb = _estimate(); wc.compact_estimate(wb); wb["Estimate"]["D6"] = 18
    wbf = _estimate(); wbf["Estimate"]["D6"] = 18
    assert recalc(wb, "short18") == recalc(wbf, "full18")


def test_the_book_opens_on_values_even_when_the_template_shows_formulas():
    """The blank template on the share was saved with Show Formulas selected; the book we
    write must open on the money whatever the template's view was."""
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    view = src.index("_ws.sheet_view.showFormulas = False")
    assert view < src.index("wb.save(out_path)")
    wb = _estimate()
    wb["Estimate"].sheet_view.showFormulas = True        # as the template arrives
    for _ws in wb.worksheets:                            # what the writer does
        _ws.sheet_view.showFormulas = False
    import io
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    assert not openpyxl.load_workbook(buf)["Estimate"].sheet_view.showFormulas


def test_the_book_opens_on_the_estimate_scrolled_to_the_top_left():
    """James Gray, 24 Sep 2026: open on the estimating sheet, page at the top left."""
    import io
    import wb_populate
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    assert src.index('open_on_sheet(wb, cm["estimate_sheet"])') < src.index("wb.save(out_path)")
    wb = _estimate()
    other = wb.create_sheet("Labour", 0)                  # the template saved on another tab,
    wb.active = 0
    other.sheet_view.tabSelected = True
    est = wb["Estimate"]
    est.sheet_view.topLeftCell = "A120"                   # scrolled down the page,
    est.sheet_view.selection[0].activeCell = "M96"
    est.sheet_view.selection[0].sqref = "M96"
    wb_populate.open_on_sheet(wb, "Estimate")
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    back = openpyxl.load_workbook(buf)
    assert back.active.title == "Estimate"
    assert not back["Labour"].sheet_view.tabSelected
    sv = back["Estimate"].sheet_view
    assert sv.topLeftCell == "A1" and sv.selection[0].activeCell == "A1"


def test_a_frozen_heading_stays_frozen_and_the_page_starts_below_it():
    import wb_populate
    wb = _estimate()
    est = wb["Estimate"]
    est.freeze_panes = "A8"
    est.sheet_view.pane.topLeftCell = "A200"
    wb_populate.open_on_sheet(wb, "Estimate")
    assert est.sheet_view.pane.state == "frozen" and est.sheet_view.pane.ySplit == 7
    assert est.sheet_view.pane.topLeftCell == "A8"
