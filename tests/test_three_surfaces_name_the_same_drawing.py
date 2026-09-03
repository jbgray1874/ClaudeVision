r"""
test_three_surfaces_name_the_same_drawing.py

"Is the AI Provenance also up to date, and in line with the e-mail and html report run?"

The FACTS were in line already: the Estimate sheet, the AI Provenance tab, the Decision
Report and the covering note all read costed_facts off one JSON, stamped after the read-back.
That is why the totals agree.

The DRAWING was not. All three surfaces named the KIND of evidence — "the drawing",
"dxf_flat_pattern" — and in a pack of eleven sheets that names none of them. Section 9 and the
covering note now name the file; this pins the third surface to the same reader, because three
implementations of "which drawing did this come from" is three chances to disagree.

AND THE VARIANTS. The provenance sheet was added AFTER the quantity sweep saved the four
variant workbooks, so _qty50 through _qty500 carried the AI Explanation tab and no AI
Provenance sheet at all — which reads as a sheet that failed rather than one written a minute
too late.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REPORT = (ROOT / "src" / "estimation_report.py").read_text(encoding="utf-8")
MAIN = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
JOBHTML = (ROOT / "src" / "job_report_html.py").read_text(encoding="utf-8")


# ── one reader, three surfaces ────────────────────────────────────────────────

@pytest.mark.parametrize("src,where", [
    (REPORT, "the AI Provenance tab"),
    (JOBHTML, "section 9 of the report"),
])
def test_the_surface_uses_the_covering_notes_own_reader(src, where):
    assert "from estimate_explained import _sources_of as _srcof" in src, (
        f"{where} rolls its own answer to 'which drawing did this come from'")


def test_the_helpers_exist_under_those_names():
    """Private names. A rename leaves every one of these columns silently empty."""
    import estimate_explained as ee
    for name in ("_sources_of", "_pack_files", "_page_index"):
        assert hasattr(ee, name)


def test_the_provenance_tab_has_the_column():
    assert '("Which drawing files and pages", 44)' in REPORT


def test_the_column_is_written_on_every_row():
    assert 'cell(row, 16, p.get("drawing_files") or "—"' in REPORT


def test_nothing_else_still_writes_to_that_column():
    """Inserting a column shifts everything after it. The 'Not priced' cell used to be 16 and
    would have been overwritten in silence — the row would look right and one column would be
    the wrong one."""
    import re
    hits = sorted({int(m.group(1)) for m in re.finditer(r"cell\(row, (1[4-9]),", REPORT)})
    assert hits == [14, 15, 16, 17], f"columns written on a part row: {hits}"


def test_a_bought_in_says_it_has_no_drawing():
    assert "bought in — no drawing of its own" in REPORT


def test_the_reader_failing_does_not_take_the_sheet_down():
    i = REPORT.index("from estimate_explained import _sources_of as _srcof")
    block = REPORT[i - 400:i + 900]
    assert "except Exception" in block
    assert "_srcof, _pack, _pages = None, [], {}" in block


# ── and it has to reach the variant workbooks ─────────────────────────────────

def test_the_provenance_sheet_is_written_before_the_variants_are_saved():
    """THE FAULT. quantity_sweep does SaveAs on this workbook, so anything added after it
    lands on the baseline and on none of the four variants."""
    prov = MAIN.index("add_provenance_sheet(_wb, summary, _scan_meta)")
    sweep = MAIN.index("from quantity_sweep import sweep as _sweep")
    assert prov < sweep, "the variants will not carry the AI Provenance sheet"


def test_it_is_still_written_after_the_read_back():
    """It states what Excel calculated and reconciles against it. Written before the
    read-back it has nothing to reconcile with and falls back to engine-only figures."""
    stamp = MAIN.index("from wep_readback_from_xlsx import stamp_real_totals_into_json")
    prov = MAIN.index("add_provenance_sheet(_wb, summary, _scan_meta)")
    assert stamp < prov


def test_the_sheet_is_written_exactly_once():
    tree = ast.parse(MAIN)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "add_provenance_sheet"]
    assert len(calls) == 1, "moving the block left a copy behind"
