"""A DRAWING THAT IS A PAGE OF A PDF IN THE PACK IS IN THE PACK (20 Nov 2026).

12110-01-GA1: the frame tube has no file of its own; its sheet is a page of the wall-panel PDF.
The page was recognised, yet the tube was still counted missing and left out of the embedded
pages, so the pack's record (and the e-mail) said a drawing that was in the pack was absent.
Made-up numbers below.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pack_resolver as pr  # noqa: E402


def _job(tmp: Path):
    tech = tmp / "TTI" / "50007 - Booth" / "50007-Technical"
    tech.mkdir(parents=True)
    rows = []
    for i, n in enumerate(("50007-01-GA.pdf", "50007-02-GA Wall Panel.pdf")):
        p = tech / n
        p.write_text(n)
        rows.append((p, p.stat().st_size, 1_000_000 + i))
    return [(tech, rows, False)]


def _read(path: Path):
    if path.stem == "50007-01-GA":
        return pr.DrawingText("ITEM DWG NO. DESCRIPTION QTY\n1 50007-02-GA WALL PANEL 7\nBOOTH 50007-01-GA A")
    if path.stem.startswith("50007-02-GA"):
        # the wall panel's PDF: its own page, and a page that is the frame tube's sheet
        return pr.DrawingText("ITEM DWG NO. DESCRIPTION QTY\n1 50007-02-02M FRAME TUBE 1\nWALL PANEL 50007-02-GA A",
                              page_drawings={"50007-02-02M": []})
    return pr.DrawingText("")


def test_a_page_inside_a_pdf_in_the_pack_is_listed_and_not_missing(tmp_path):
    m = pr.resolve("50007-01-GA", _job(tmp_path), client="TTI", read_text=_read, area_rank=lambda f: 0)
    assert "50007-02-02M" not in m["missing"], m["missing"]
    assert m["embedded_drawing_pages"].get("50007-02-02M") == "50007-02-GA"
    files = [Path(f["path"]).name for x in m["members"] for f in x["files"]]
    assert "50007-02-GA Wall Panel.pdf" in files, "the PDF holding the page must go with the pack"


def test_a_part_with_no_file_and_no_page_is_still_missing(tmp_path):
    """THE CONTROL: without the page, the part is missing, as before."""
    def read(path):
        t = _read(path)
        return pr.DrawingText(str(t)) if path.stem.startswith("50007-02-GA") else t
    m = pr.resolve("50007-01-GA", _job(tmp_path), client="TTI", read_text=read, area_rank=lambda f: 0)
    assert "50007-02-02M" in m["missing"]
