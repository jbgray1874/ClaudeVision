"""THE LIVE LIBRARY SEARCH IS ONLY FOR ANOTHER JOB'S DRAWINGS (20 Nov 2026).

Row 31 of the TTI tracker was held: the GA's own frame tube had no file of its own (its drawing
is a sheet inside the wall-panel PDF), so the new live library search was asked for it. That
search walks every non-job folder of the Design area; over the VPN it did not finish in 300 s
and the row was held "pack not checked". The job's own folders were already listed live, so a
share-wide search for the job's own number can find nothing more. Made-up numbers below.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pack_resolver as pr  # noqa: E402


class LiveLike:
    """A live library lookup: it has sheet_files, and records every drawing asked for."""
    def __init__(self, found=None):
        self.asked, self.found, self.evidence = [], found or {}, []

    def __call__(self, drawing):
        self.asked.append(drawing)
        return self.found.get(drawing, [])

    def sheet_files(self, drawing):
        return []


def _job(tmp: Path):
    tech = tmp / "TTI" / "50006 - Booth" / "50006-Technical"
    tech.mkdir(parents=True)
    rows = []
    for i, n in enumerate(("50006-01-GA.pdf", "50006-01-03A.pdf")):
        p = tech / n
        p.write_text(n)
        rows.append((p, p.stat().st_size, 1_000_000 + i))
    return [(tech, rows, False)]


def _read(path: Path) -> str:
    if path.stem == "50006-01-GA":
        return ("ITEM DWG NO. DESCRIPTION QTY\n1 50006-01-03A PANEL 2\n2 50006-02-02M FRAME TUBE 1\n"
                "3 4100-GA EUROHOOK 8\nBOOTH 50006-01-GA A")
    return ""


def test_the_jobs_own_part_is_not_searched_for_across_the_share(tmp_path):
    lib = tmp_path / "Library" / "4100-GA.pdf"
    lib.parent.mkdir(parents=True)
    lib.write_text("x")
    live = LiveLike(found={"4100-GA": [(lib, 1, 1_000_500)]})
    m = pr.resolve("50006-01-GA", _job(tmp_path), client="TTI", read_text=_read,
                   area_rank=lambda f: 0, lookup=live)
    assert "50006-02-02M" not in live.asked, "the job's own part went to the share-wide search"
    assert "4100-GA" in live.asked, "another job's drawing must still be searched for"
    assert "4100-GA" in {x["drawing"] for x in m["members"]}
    assert "50006-02-02M" in m["missing"], "the job's own part with no drawing is still said to be missing"


def test_an_index_lookup_is_still_asked_for_the_jobs_own_part(tmp_path):
    """THE CONTROL: the drawing index (a plain callable, no live walk) is fast and still used."""
    asked = []

    def index_lookup(d):
        asked.append(d)
        return []
    pr.resolve("50006-01-GA", _job(tmp_path), client="TTI", read_text=_read, area_rank=lambda f: 0,
               lookup=index_lookup)
    assert "50006-02-02M" in asked
