"""A status report exists as HTML *and* PDF, and can be taken away from either.

JAMES, 16 SEP 2026: "all status reports should be also created in HTML as well as PDF formats
as these are opened in SDI portal. and all downloadable."

Three separate failures were behind that, and this file refuses each of them:

  1. A REPORT WITH ONE FORMAT. The programme status for 27 August and 7 September each had a
     PDF beside it because somebody remembered to print one. Remembering is not a mechanism.
     tools/report_pdf.py is the mechanism and this test is what notices when it was not run.

  2. A PDF THAT NEVER LEAVES THIS MACHINE. Every one of them was matched by `*.pdf` in
     .gitignore, so the whole set existed on one laptop and reached neither the estimating
     laptop nor the server -- which is exactly where the portal reads them from. A report the
     reader cannot open is not a report. The ignore file now carries a narrow exception for
     reports/, and this test asserts the PDFs are actually TRACKED rather than merely present
     on the machine running the suite.

  3. A PAGE WITH NO WAY TO KEEP IT. These are opened from the portal, which serves them
     sandboxed. The download bar resolves the PDF's location at run time -- a sibling file on
     disk or on K:, the same query with a swapped extension through /api/file -- and saves the
     page itself from a Blob, which the portal's `sandbox allow-downloads` permits.

The set is whatever is in reports/, so a report added next month is covered the day it lands
and nobody has to remember to add it here. Files starting with "_" are fragments, not reports.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
BAR_ID = "sdi-dlbar"


def _is_report(p: Path) -> bool:
    if p.name.startswith("_") or p.suffix.lower() not in (".html", ".htm"):
        return False
    head = p.read_text(encoding="utf-8", errors="ignore")[:4000].lower()
    return "<body" in head or "<!doctype" in head


_REPORTS = sorted(p for p in REPORTS.glob("*.htm*") if _is_report(p)) if REPORTS.is_dir() else []
_IDS = [p.stem for p in _REPORTS]


def test_there_are_reports_to_check():
    """A glob that silently matches nothing turns every test below into a pass."""
    assert _REPORTS, f"no status reports found in {REPORTS}"


@pytest.mark.parametrize("report", _REPORTS, ids=_IDS)
def test_every_report_has_a_pdf_twin(report: Path):
    """THE ASSERTION. One command produces it:  python tools/report_pdf.py --all"""
    pdf = report.with_suffix(".pdf")
    assert pdf.is_file(), (
        f"{report.name} has no PDF twin. The portal opens these as both.\n"
        f"    python tools/report_pdf.py --all")
    assert pdf.stat().st_size > 20_000, (
        f"{pdf.name} is {pdf.stat().st_size} bytes — too small to be the printed report")


@pytest.mark.parametrize("report", _REPORTS, ids=_IDS)
def test_every_pdf_is_tracked_so_it_reaches_the_portal(report: Path):
    """PRESENT IS NOT THE SAME AS SHIPPED. `*.pdf` is ignored repo-wide, deliberately —
    output PDFs are noise. The reports are the exception, because the machine that opens
    them is not the machine that made them."""
    pdf = report.with_suffix(".pdf")
    if not pdf.is_file():
        pytest.skip("no PDF twin — the test above is the one reporting that")
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(pdf.relative_to(ROOT))],
                             cwd=ROOT, capture_output=True, text=True)
    assert tracked.returncode == 0, (
        f"{pdf.name} exists here but is NOT tracked, so a pull on the estimating laptop or "
        f"the server does not bring it. .gitignore needs its reports/ exception, and the "
        f"file needs `git add -f` once.")


@pytest.mark.parametrize("report", _REPORTS, ids=_IDS)
def test_every_report_is_a_standalone_document(report: Path):
    """The portal serves these as pages and they are opened from K: directly. A fragment
    renders by the browser's good manners, not by being correct, and it has nowhere to carry
    a charset or a viewport."""
    html = report.read_text(encoding="utf-8")
    low = html.lower()
    assert low.lstrip().startswith("<!doctype"), f"{report.name} has no doctype"
    for needed in ("<html", "<head", "<body", 'charset="utf-8"', "viewport"):
        assert needed in low, f"{report.name} is missing {needed}"


@pytest.mark.parametrize("report", _REPORTS, ids=_IDS)
def test_every_report_can_be_taken_away(report: Path):
    """The download bar, and the three ways a reader reaches these pages."""
    html = report.read_text(encoding="utf-8")
    assert f'id="{BAR_ID}"' in html, (
        f"{report.name} carries no download bar — a reader opening it from the portal has no "
        f"way to keep it. python tools/report_pdf.py --all injects it.")
    assert f'id="{BAR_ID}-pdf"' in html, f"{report.name}: no link to the PDF"
    assert f'id="{BAR_ID}-save"' in html, f"{report.name}: no way to save the page itself"

    # THE PORTAL PATH, which is the one that is easy to get wrong: /api/file?path=<dir>/<name>
    # means a relative href resolves against /api/ and 404s. The bar must rewrite the query.
    assert "path=" in html, (
        f"{report.name}: the bar does not handle the portal's /api/file?path= form, so its "
        f"PDF link is broken exactly where these reports are actually opened")
    assert "createObjectURL" in html, (
        f"{report.name}: 'Save this page' must build the file in the page — the portal serves "
        f"these sandboxed, where that is what is permitted")

    # AND IT MUST NOT PRINT ITSELF INTO THE PDF.
    assert re.search(r"@media\s+print\s*\{\s*#" + BAR_ID, html), (
        f"{report.name}: the bar is not hidden in print, so the PDF contains a control "
        f"pointing at the PDF")


def test_the_tool_that_makes_both_formats_exists_and_is_the_only_recipe():
    """If the page setup lived in whoever's shell history, the set would drift into six
    different margins. One tool, one A4 page setup, one place to change it."""
    tool = ROOT / "tools" / "report_pdf.py"
    assert tool.is_file(), "tools/report_pdf.py is what makes both formats"
    src = tool.read_text(encoding="utf-8")
    assert "PDF_OPTS" in src and "A4" in src, "the page setup must be stated once, in the tool"
    assert "playwright" in src.lower(), "it renders with a real browser, not a converter"
