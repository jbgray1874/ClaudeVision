"""A DESCRIPTION JOINED TO THE NUMBER BY A HYPHEN IS NOT PART OF THE NUMBER, AND A PACK HOLDS
ONE REVISION OF EACH DRAWING (17 Nov 2026).

Row 40 of the TTI tracker: the GA's PDFs are named "<number>-Universal Table ..._revA.PDF" and
"..._revB.PDF". The number was read as "<number>-UNIVERSAL", so the GA's PDF was not the GA, its
parts list was never read, the pack was one sub-folder of 6 files while the job holds dozens, and
both revisions of the GA came along. JG: "we need to not pull in two PDFs with the same name but
with a revA and revB at the end ... this was a requirement up front."
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pack_resolver as pr  # noqa: E402

GA = "50001-00-01"


def test_a_hyphen_joined_description_is_dropped_and_real_suffixes_are_kept():
    assert pr.drawing_id(f"{GA}-Universal Table Illuminated Top_revB.PDF") == GA
    assert pr.drawing_id("50001-01-01J-WORKTOP.pdf") == "50001-01-01J"
    assert pr.drawing_id("50001-ELECTRICS.pdf") == "50001-ELECTRICS", "a number and one word is a name, kept"
    for name, number in (("11896-01-00-GA.SLDASM", "11896-01-00-GA"), ("12110-01-GA1.pdf", "12110-01-GA1"),
                         ("11671-01-GA17.pdf", "11671-01-GA17"), ("HIN-101-S32EB.pdf", "HIN-101-S32EB"),
                         ("12181-04-04G_FOAMEX_REV A.DXF", "12181-04-04G"), ("TTI-10234 rev B.pdf", "TTI-10234"),
                         ("12773-02-ASSY.SLDASM", "12773-02-ASSY")):
        assert pr.drawing_id(name) == number, name


def _job(tmp: Path):
    tech = tmp / "TTI" / "50001 - Table" / "50001-Technical"
    files = {
        "50001-00 General Assembly": [f"{GA}-Universal Table Illuminated Top_revA.PDF",
                                      f"{GA}-Universal Table Illuminated Top_revB.PDF",
                                      f"{GA}-Universal Table Illuminated Top - DESIGN INTENT.pdf",
                                      f"{GA}.SLDASM", f"{GA}.SLDDRW"],
        "50001-01 Worktop": ["50001-01-01J-WORKTOP_revB.pdf", "50001-01-01J-WORKTOP_revB.dxf",
                             "50001-01-01J-WORKTOP_revA.pdf"],
        "50001-04 Side panels": ["50001-04-01A-SIDE PANEL A_revA.pdf", "50001-04-01A.SLDPRT"],
    }
    rows = []
    for sub, names in files.items():
        d = tech / sub
        d.mkdir(parents=True)
        out = []
        for i, n in enumerate(names):
            p = d / n
            p.write_text(n)
            out.append((p, p.stat().st_size, 1_000_000 + i))
        rows.append((d, out, False))
    # the design-intent sheet is the newest file: read by date alone, it was the one read
    ga_dir = rows[0]
    rows[0] = (ga_dir[0], [(p, s, 2_000_000 if "DESIGN" in p.name else m) for p, s, m in ga_dir[1]], False)
    return rows


def _read(path: Path) -> str:
    if path.name.endswith("_revB.PDF") and path.name.startswith(GA):
        return (f"ITEM DWG NO. DESCRIPTION QTY\n1 50001-01-01J WORKTOP 1\n6 50001-04-01A SIDE PANEL A 2\n"
                f"DWG NO. REVISION: UNIVERSAL TABLE {GA} B\nREVISION TABLE REV DWG NO DESCRIPTION")
    if path.name.endswith("_revA.PDF") and path.name.startswith(GA):
        return f"1 50001-01-01J WORKTOP 1\nUNIVERSAL TABLE {GA} A"
    if "DESIGN INTENT" in path.name:
        return "1 50001-01-01J WORKTOP 1\nUNIVERSAL TABLE 5001-00-01 A"     # its own number mistyped
    return ""


def test_the_ga_is_read_from_its_latest_revision_and_its_parts_are_followed_into_their_folders(tmp_path):
    m = pr.resolve(GA, _job(tmp_path), client="TTI", read_text=_read, area_rank=lambda f: 0)
    assert m["price_ok"] and m["revision"] == "B"
    assert "the GA was matched by its file name; its own text was not read" not in m["assumptions"]
    by = {x["drawing"]: x for x in m["members"]}
    assert {"50001-01-01J", "50001-04-01A"} <= set(by), sorted(by)
    ga = [Path(f["path"]).name for f in by[GA]["files"]]
    assert any(n.endswith("_revB.PDF") for n in ga)
    assert not any(n.endswith("_revA.PDF") for n in ga), "both revisions of the GA were pulled in"
    assert not any("DESIGN INTENT" in n for n in ga), "an untagged PDF rode in beside revision B"
    assert {f"{GA}.SLDASM", f"{GA}.SLDDRW"} <= set(ga), "the models with no revision in their name ride with B"
    worktop = [Path(f["path"]).name for f in by["50001-01-01J"]["files"]]
    assert sorted(worktop) == ["50001-01-01J-WORKTOP_revB.dxf", "50001-01-01J-WORKTOP_revB.pdf"]
