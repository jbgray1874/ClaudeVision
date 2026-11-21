"""A GA WHOSE PDFs ARE ONLY IN ITS ARCHIVE IS READ FROM THERE, AND SAID (18 Nov 2026).

Row 139 of the TTI tracker, 12132-01-GA: the job's Technical folder holds the SolidWorks drawing,
assembly and parts, and every PDF of the GA (REV A and REV B) sits in its Archive sub-folder. The
archive was used only when no current copy existed, so the pack went out with no PDF and the engine
stopped at once with "No drawing files found", twice. The GA's newest-revision PDF is now taken
from the job's own archive, with a warning that the SolidWorks drawing may be later.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pack_resolver as pr  # noqa: E402

GA = "50002-01-GA"


def _job(tmp: Path, archive_pdfs: bool = True, current_pdf: bool = False, current_drawing: str = "50002-01-GA.SLDDRW"):
    tech = tmp / "TTI" / "50002 - Display (Test 2026)" / "50002-Technical"
    arch = tech / "50002-Archive"
    tech.mkdir(parents=True)
    arch.mkdir()
    cur = [current_drawing, "50002-01-GA.SLDASM", "50002-01-02A.SLDPRT", "50002-01-10M.SLDPRT"]
    if current_pdf:
        cur.append("50002-01-GA_REV C.pdf")
    old = ["50002-01 GA_STAND_REV A.pdf", "50002-01 GA_STAND_REV B.pdf", "50002-01 GA_revA TEST 2026.dwg"]
    if not archive_pdfs:
        old = [n for n in old if not n.endswith(".pdf")]
    rows = []
    for d, names, is_arch in ((tech, cur, False), (arch, old, True)):
        out = []
        for i, n in enumerate(names):
            p = d / n
            p.write_text(n)
            out.append((p, p.stat().st_size, 1_000_000 + i))
        rows.append((d, out, is_arch))
    return rows


def _read(path: Path) -> str:
    rev = "B" if "REV B" in path.name else ("C" if "REV C" in path.name else "A")
    return f"ITEM DWG NO. DESCRIPTION QTY\n1 50002-01-02A PANEL 1\nDISPLAY STAND {GA} {rev}"


def _ga_files(m):
    return [Path(f["path"]).name for x in m["members"] if x["drawing"] == GA for f in x["files"]]


def test_the_newest_pdf_in_the_archive_goes_with_the_pack_and_is_said(tmp_path):
    m = pr.resolve(GA, _job(tmp_path), client="TTI", read_text=_read, area_rank=lambda f: 0)
    names = _ga_files(m)
    assert "50002-01 GA_STAND_REV B.pdf" in names, names
    assert "50002-01 GA_STAND_REV A.pdf" not in names, "one revision of the GA only"
    assert m["revision"] == "B"
    assert m["selected_folder"].endswith("50002-Technical"), "the current folder is still the pack's home"
    said = " ".join(m["assumptions"])
    assert "taken from the archive folder" in said and "may be a later revision" in said


def test_a_current_pdf_is_used_and_the_archive_is_left_alone(tmp_path):
    m = pr.resolve(GA, _job(tmp_path, current_pdf=True), client="TTI", read_text=_read,
                   area_rank=lambda f: 0)
    names = _ga_files(m)
    assert "50002-01-GA_REV C.pdf" in names
    assert not any("STAND_REV" in n for n in names)
    assert "taken from the archive folder" not in " ".join(m["assumptions"])


def test_with_no_pdf_anywhere_nothing_is_invented(tmp_path):
    m = pr.resolve(GA, _job(tmp_path, archive_pdfs=False), client="TTI", read_text=_read,
                   area_rank=lambda f: 0)
    assert not any(n.lower().endswith(".pdf") for n in _ga_files(m))
    assert "taken from the archive folder" not in " ".join(m["assumptions"])


def test_a_part_whose_pdf_is_only_in_another_folder_of_the_job_is_taken_from_there(tmp_path):
    """JG: "or any folder under technical if they exist ... if none exist in the main folder but in
    any one of the others it extracts them"."""
    rows = _job(tmp_path)
    tech = rows[0][0]
    other = tech / "PDF issue"                       # not an archive: any folder of the job
    other.mkdir()
    out = []
    for i, n in enumerate(("50002-01-02A_PANEL_REV A.pdf", "50002-01-02A_PANEL_REV B.pdf")):
        p = other / n
        p.write_text(n)
        out.append((p, p.stat().st_size, 1_000_000 + i))
    rows.append((other, out, False))
    m = pr.resolve(GA, rows, client="TTI", read_text=_read, area_rank=lambda f: 0)
    part = [Path(f["path"]).name for x in m["members"] if x["drawing"] == "50002-01-02A" for f in x["files"]]
    assert "50002-01-02A_PANEL_REV B.pdf" in part and "50002-01-02A_PANEL_REV A.pdf" not in part, part


def test_a_part_whose_pdf_is_only_in_the_archive_is_taken_from_there_and_said(tmp_path):
    rows = _job(tmp_path)
    arch_dir, arch_files, _a = rows[1]
    p = arch_dir / "50002-01-02A_PANEL_REV B.pdf"
    p.write_text("x")
    rows[1] = (arch_dir, arch_files + [(p, p.stat().st_size, 1_000_900)], True)
    m = pr.resolve(GA, rows, client="TTI", read_text=_read, area_rank=lambda f: 0)
    part = [Path(f["path"]).name for x in m["members"] if x["drawing"] == "50002-01-02A" for f in x["files"]]
    assert "50002-01-02A_PANEL_REV B.pdf" in part, part
    assert any("taken from other folders of the job" in a and "50002-01-02A" in a for a in m["assumptions"])


def test_the_ga_from_another_ordinary_folder_of_the_job_when_the_main_folder_has_none(tmp_path):
    rows = _job(tmp_path, archive_pdfs=False)
    other = rows[0][0] / "Issued"
    other.mkdir()
    p = other / "50002-01 GA_STAND_REV B.pdf"
    p.write_text("x")
    rows.append((other, [(p, p.stat().st_size, 1_000_500)], False))
    m = pr.resolve(GA, rows, client="TTI", read_text=_read, area_rank=lambda f: 0)
    assert "50002-01 GA_STAND_REV B.pdf" in _ga_files(m)


def test_a_pdf_from_the_archive_never_verifies_the_pack(tmp_path):
    """21 Nov 2026: the archive's title block proved the number, and the pack was called
    "verified" on a PDF that is not the current drawing."""
    m = pr.resolve(GA, _job(tmp_path), client="TTI", read_text=_read, area_rank=lambda f: 0)
    assert m["status"] == "provisional" and m["identity"] == "named"
    assert m["ga_pdf_source"]["archive"] is True and m["ga_pdf_source"]["revision"] == "B"
    assert m["price_ok"] is True, "it is still priced, as a provisional pack"


def test_a_pdf_in_the_current_folder_can_still_verify_the_pack(tmp_path):
    m = pr.resolve(GA, _job(tmp_path, current_pdf=True), client="TTI", read_text=_read,
                   area_rank=lambda f: 0)
    assert m["identity"] == "verified" and "ga_pdf_source" not in m


def test_a_current_drawing_that_names_a_later_revision_makes_the_pdf_superseded(tmp_path):
    m = pr.resolve(GA, _job(tmp_path, current_drawing="50002-01-GA_REV C.SLDDRW"), client="TTI",
                   read_text=_read, area_rank=lambda f: 0)
    src = m["ga_pdf_source"]
    assert src["superseded"] is True and src["current_revision"] == "C" and src["revision"] == "B"
    said = " ".join(m["assumptions"])
    assert "SUPERSEDED revision B" in said and "revision C" in said and "may be a later revision" not in said
    assert m["status"] == "provisional"


def test_a_current_drawing_at_the_same_revision_is_not_called_superseded(tmp_path):
    m = pr.resolve(GA, _job(tmp_path, current_drawing="50002-01-GA_REV B.SLDDRW"), client="TTI",
                   read_text=_read, area_rank=lambda f: 0)
    assert m["ga_pdf_source"]["superseded"] is False
    assert "SUPERSEDED" not in " ".join(m["assumptions"])


def test_a_current_drawing_that_names_no_revision_is_only_a_may_be(tmp_path):
    m = pr.resolve(GA, _job(tmp_path), client="TTI", read_text=_read, area_rank=lambda f: 0)
    assert m["ga_pdf_source"]["superseded"] is False and m["ga_pdf_source"]["current_revision"] == ""
    assert "may be a later revision" in " ".join(m["assumptions"])
