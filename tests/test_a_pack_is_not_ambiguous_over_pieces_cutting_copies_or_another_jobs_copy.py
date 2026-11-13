"""The TTI tracker's full dry run (11 Nov 2026): 23 of 76 rows with drawings stopped as "ambiguous",
and one matched a file in another customer's folder. Four of those causes were the resolver's.

* A part exported as numbered pieces (01J_PART1 .. 01J_PART5, D-669) read as five copies claiming one
  revision.
* A job's cutting copies in a sub-folder (Cutters, CNC) read as rival issues of the same revision.
  The issued file sits beside the member's own PDF.
* 11203-01-GA in 11437's folder, where that job reused it, read as a rival to 11203's own copy.
* A GA's 2D and 3D CAD folders (PDF in one, model in the other) read as two different issues.
* 12775 matched a file under an M&S folder. On the TTI tracker that is asked, not priced.

Synthetic folder rows; no job's files.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pack_resolver as pr  # noqa: E402

SHARE = Path("/share/Design/Customers April 08 Onwards")


def _f(folder: Path, name: str, size: int = 100, mtime: float = 1000.0):
    return (folder / name, size, mtime)


def _read(drawing: str, refs=()):
    def read(path: Path) -> str:
        if path.name.upper().startswith(drawing):
            return f"DRAWING No {drawing} REV A\n" + "\n".join(refs)
        return ""
    return read


def test_a_parts_numbered_pieces_are_pieces_not_rival_copies():
    tech = SHARE / "TTi" / "12734 - Saw Display" / "12734-Technical"
    files = [_f(tech, "12734-01-GA_REV A.pdf"), _f(tech, "12734-01-01J_REV A.pdf")]
    files += [_f(tech, f"12734-01-01J_PART{i}_18mm MDF_REV A.DXF", 100 + i) for i in range(1, 6)]
    m = pr.resolve("12734-01-GA", [(tech, files, False)], client="TTI",
                   read_text=_read("12734-01-GA", ["12734-01-01J"]))
    assert not m["conflicts"], m["conflicts"]
    j = next(x for x in m["members"] if x["drawing"] == "12734-01-01J")
    assert sum(1 for f in j["files"] if f["format"] == "dxf") == 5


def test_a_cutting_copy_away_from_the_pdf_is_left_out_and_said():
    tech = SHARE / "TTi" / "12164 - Gravel Pit" / "12164-Technical"
    cut = tech / "12164-Cutters"
    rows = [(tech, [_f(tech, "12164-00-GA_REV A.pdf"), _f(tech, "12164-01-01J_REV A.pdf"),
                    _f(tech, "12164-01-01J_18mm MDF_REV A.DXF", 500)], False),
            (cut, [_f(cut, "12164-01-01J_18mm MDF_REV A.DXF", 777)], False)]
    m = pr.resolve("12164-00-GA", rows, client="TTI", read_text=_read("12164-00-GA", ["12164-01-01J"]))
    assert not m["conflicts"], m["conflicts"]
    j = next(x for x in m["members"] if x["drawing"] == "12164-01-01J")
    assert [f["path"] for f in j["files"] if f["format"] == "dxf"] == [
        str(tech / "12164-01-01J_18mm MDF_REV A.DXF")]
    assert any("12164-Cutters" in a and "beside the PDF" in a for a in m["assumptions"])


def test_two_different_files_in_one_folder_are_still_asked():
    tech = SHARE / "TTi" / "12164 - Gravel Pit" / "12164-Technical"
    rows = [(tech, [_f(tech, "12164-00-GA_REV A.pdf"), _f(tech, "12164-01-01J_REV A.pdf"),
                    _f(tech, "12164-01-01J_18mm MDF_REV A.DXF", 500),
                    _f(tech, "12164-01-01J_18mm MDF copy_REV A.DXF", 777)], False)]
    m = pr.resolve("12164-00-GA", rows, client="TTI", read_text=_read("12164-00-GA", ["12164-01-01J"]))
    assert m["status"] == "ambiguous" and "12164-01-01J" in m["question"]


def test_another_jobs_reused_copy_does_not_rival_the_jobs_own():
    own = SHARE / "TTi" / "11203 - QUIK-LOK Holder" / "11203-Technical"
    other = SHARE / "TTi" / "11437 - Milw Quik-Lok Holder" / "11437-Technical" / "11437-Data"
    rows = [(own, [_f(own, "11203-01-GA_REV B.pdf", 100)], False),
            (other, [_f(other, "11203-01-GA_REV B.pdf", 222)], False)]
    m = pr.resolve("11203-01-GA", rows, client="TTI", read_text=_read("11203-01-GA"))
    assert not m["conflicts"], m["conflicts"]
    assert m["selected_folder"] == str(own)
    assert any("11437-Data" in a and "another job's folder" in a for a in m["assumptions"])


def test_a_pdf_folder_and_a_model_folder_are_one_issue():
    job = SHARE / "TTi" / "12754_Gen 5 Wall CDU"
    two, three = job / "2D CAD", job / "3D CAD"
    rows = [(two, [_f(two, "12754-01-GA_REV A.pdf", 300)], False),
            (three, [_f(three, "12754-01-GA.SLDASM", 900), _f(three, "12754-01-GA_REV A.SLDDRW", 400)], False)]
    m = pr.resolve("12754-01-GA", rows, client="TTI", read_text=_read("12754-01-GA"))
    assert not m["conflicts"], m["conflicts"]


def test_a_pack_only_under_another_customer_is_asked_on_the_client_tracker():
    ms = SHARE / "M&S" / "2045 - Magazine FSU" / "2045-Visuals and Renders"
    rows = [(ms, [_f(ms, "12775_render_REV 01.pdf")], False)]
    m = pr.resolve("12775", rows, client="TTI", read_text=_read("12775"), client_folders_only=True)
    assert m["status"] == "ambiguous" and not m["price_ok"]
    assert "outside the TTI folders" in m["question"]
    loose = pr.resolve("12775", rows, client="TTI", read_text=_read("12775"))
    assert loose["status"] != "ambiguous", "other callers spell the client their own way: not asked"


def test_the_clients_copy_wins_over_another_customers():
    tti = SHARE / "TTi" / "12766 - Fridge Trough" / "12766-Technical"
    ssp = SHARE / "SSP" / "12766 - Fridge Trough" / "12766-Technical"
    rows = [(tti, [_f(tti, "12766-01-GA_REV A.pdf", 100)], False),
            (ssp, [_f(ssp, "12766-01-GA_REV A.pdf", 200)], False)]
    m = pr.resolve("12766-01-GA", rows, client="TTI", read_text=_read("12766-01-GA"))
    assert m["selected_folder"] == str(tti) and not m["conflicts"]


def test_the_piece_reading_matches_the_engines():
    import importlib
    names = ["12203-65-01J_PART5_10.8mm LAM MDF_revA.DXF", "9439-01A_-07_5MM ACRYLIC.DXF",
             "12734-01-01J_18mm MDF_REV A.DXF", "PART3_bracket.dxf"]
    djm = importlib.import_module("drawing_job_merge")
    for n in names:
        assert pr.piece_number(n) == djm.member_number_from_filename(Path(n)), n


def test_a_family_part_outside_the_jobs_folders_is_looked_up_across_the_index():
    """11896-04-00-GA (11 Nov 2026): its pack came out as the GA alone; a part of its own family
    that was not in the job's folders of the same area was never looked for anywhere else."""
    tech = SHARE / "TTi" / "11896 - Training Centre" / "11896-Technical" / "11896-04-00-GA"
    elsewhere = Path("/share/Prototype/TTi/Bays/11896-04-01")
    part = (elsewhere / "11896-04-01-01M_1.5mm MS_RevG.DXF", 100, 1000.0)
    old = (Path("/share/Prototype/TTi/Bays/OLD") / "11896-04-01-01M_RevA.DXF", 100, 900.0)
    rows = [(tech, [_f(tech, "11896-04-00-GA_Starter Bay_RevG.pdf")], False)]
    m = pr.resolve("11896-04-00-GA", rows, client="TTI",
                   read_text=_read("11896-04-00-GA", ["11896-04-01-01M"]),
                   lookup=lambda d: [part, old] if d == "11896-04-01-01M" else [])
    by = {x["drawing"]: x for x in m["members"]}
    assert "11896-04-01-01M" in by and not m["missing"]
    assert [f["path"] for f in by["11896-04-01-01M"]["files"]] == [str(part[0])], "never an archive copy"
    assert "11896-04-01-01M" not in m["library"], "the job's own part is not a library part"


# ── a part's NAMED pieces are not rival copies (the real share, 12 Nov 2026) ─────────────────
def test_named_pieces_of_one_part_are_pieces_not_rival_copies():
    tech = SHARE / "TTi" / "11896 - Training Centre" / "11896-Technical" / "11896-02-01 Speakers"
    files = [_f(tech, "11896-02-01-GA_REV F.pdf"), _f(tech, "11896-02-01-03J_REV F.pdf")]
    files += [_f(tech, f"11896-02-01-03J_{n}_MDF_18.0mm_REV F.DXF", 200 + i)
              for i, n in enumerate(("BASE", "LHS", "REAR", "RHS", "RIB", "TOP"))]
    m = pr.resolve("11896-02-01-GA", [(tech, files, False)], client="TTI",
                   read_text=_read("11896-02-01-GA", ["11896-02-01-03J"]))
    assert not m["conflicts"], m["conflicts"]
    part = next(x for x in m["members"] if x["drawing"] == "11896-02-01-03J")
    assert sum(1 for f in part["files"] if f["format"] == "dxf") == 6


def test_pieces_named_with_a_space_or_a_longer_name_are_still_pieces():
    assert pr.piece_key("6364-01-004-LOCK COVER_3mm PETG_revR.DXF") != pr.piece_key("6364-01-004-lock plate_5mm PETG_revR.DXF")
    assert pr.piece_key("6364-02-001-LEFT END_18mm MFC_revW.DXF") != pr.piece_key("6364-02-001-LEFT END LIP_18mm MFC_revW.DXF")
    assert pr.piece_key("X-01J_PART1_18mm_REV A.DXF") != pr.piece_key("X-01J_PART2_18mm_REV A.DXF")


def test_the_same_piece_twice_is_still_a_rival_copy_and_is_asked():
    assert pr.piece_key("X-01J_BASE_18mm_REV F.DXF") == pr.piece_key("x-01j_base_18mm_rev F - Copy.dxf")
    assert pr.piece_key("X-01J_BASE_18mm_REV F.DXF") == pr.piece_key("X-01J_BASE_18mm_REV F (2).DXF")
    tech = SHARE / "TTi" / "12164 - Stand" / "12164-Technical"
    files = [_f(tech, "12164-00-GA_REV A.pdf"), _f(tech, "12164-01-01J_REV A.pdf"),
             _f(tech, "12164-01-01J_BASE_18mm_REV A.DXF", 100),
             _f(tech, "12164-01-01J_BASE_18mm_REV A (2).DXF", 999)]
    m = pr.resolve("12164-00-GA", [(tech, files, False)], client="TTI",
                   read_text=_read("12164-00-GA", ["12164-01-01J"]))
    assert m["conflicts"], "two different files of the same piece at one revision are asked about"
