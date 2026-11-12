"""Three ways the resolver left a pack short and said nothing (laptop output, 12 Nov 2026).

* 11896-04-00-GA has no PDF of its own; its drawing is three sheets, -GA-01, -GA-02, -GA-03. None
  was read ("0 drawing PDF(s) read"), no part it calls for was gathered, and the pack of GA-level
  files alone was reported "drawings complete".
* 12773-01-GA calls for the lower body, filed as "12773-02 GA.SLDASM". The assembly word stands
  apart from its number, the file read as drawing "12773-02", and the lower body was never
  gathered: the estimate priced a lower-body assembly with no members.
* "Complete" was claimed whenever no reference was missing, including when no parts list was read.

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


def _texts(by_start):
    def read(path: Path) -> str:
        for start, text in by_start.items():
            if path.name.upper().startswith(start.upper()):
                return text
        return ""
    return read


def _wall_bay():
    tech = SHARE / "TTi" / "11896 - Training Centre" / "11896-Technical" / "11896-04 - Generic Wall Bay"
    gas = tech / "11896-04-00 - GAs"
    parts = tech / "11896-04-01 - Back Panel"
    rows = [
        (gas, [_f(gas, "11896-04-00-GA.SLDASM"), _f(gas, "11896-04-00-GA.SLDDRW"),
               _f(gas, "11896-04-00-BAY.SLDASM")]
              + [_f(gas, f"11896-04-00-GA-0{i}_RevG.{e}") for i in (1, 2, 3) for e in ("pdf", "dwg")], False),
        (parts, [_f(parts, "11896-04-01-01M_1.2mm MS_RevB.pdf"), _f(parts, "11896-04-01-01M_1.2mm MS_RevB.DXF"),
                 _f(parts, "11896-04-01-02M_RevA.pdf")], False),
    ]
    return rows


def test_a_ga_issued_as_numbered_sheets_is_read_from_its_sheets():
    read = _texts({"11896-04-00-GA-01": "SHEET 1 OF 3  11896-04-00-GA  REV G\n1  11896-04-01-01M  BACK PANEL  2",
                   "11896-04-00-GA-02": "SHEET 2 OF 3  11896-04-00-GA\n2  11896-04-01-02M  SHELF  4\n3  11896-04-01-09M  BRACKET 1",
                   "11896-04-00-GA-03": "SHEET 3 OF 3  11896-04-00-GA"})
    m = pr.resolve("11896-04-00-GA", _wall_bay(), client="TTI", read_text=read)
    ids = {x["drawing"] for x in m["members"]}
    assert {"11896-04-01-01M", "11896-04-01-02M"} <= ids, ids
    assert m["references_read"] and m["sheets_read"] == ["11896-04-00-GA-01", "11896-04-00-GA-02", "11896-04-00-GA-03"]
    assert m["missing"] == ["11896-04-01-09M"] and m["complete"] is False
    back = next(x for x in m["members"] if x["drawing"] == "11896-04-01-01M")
    assert back["parent"] == "11896-04-00-GA" and back["referenced_by_ga"]
    # a sheet is not a part the GA is missing or references
    assert not any(x.startswith("11896-04-00-GA-0") for x in m["missing"])


def test_a_ga_nobody_read_is_not_called_complete():
    m = pr.resolve("11896-04-00-GA", _wall_bay(), client="TTI", read_text=lambda p: "")
    assert m["references_read"] is False and m["complete"] is False
    assert m["status"] == "provisional"
    assert any("parts list was NOT READ" in a for a in m["assumptions"])


def test_an_assembly_word_apart_from_its_number_is_that_assembly():
    assert pr.drawing_id("12773-02 GA.SLDASM") == "12773-02-GA"
    assert pr.drawing_id("12773-02 GA_revA.pdf") == "12773-02-GA"
    assert pr.drawing_id("12002-02-101 SA.SLDASM") == "12002-02-101-SA"
    # unchanged readings
    assert pr.drawing_id("12773-01-GA.SLDASM") == "12773-01-GA"
    assert pr.drawing_id("11896-01-01-02M_1.2mm MS_RevE.pdf") == "11896-01-01-02M"
    assert pr.drawing_id("0359829_12674-01-GA_Smart Shirt Table_revB.PDF") == "12674-01-GA"
    assert pr.drawing_id("12773-02-101 SHELF PANEL.SLDPRT") == "12773-02-101"
    assert pr.drawing_id("12164-00 GA NOTES.pdf") == "12164-00-GA"


def test_the_lower_body_the_ga_calls_for_is_gathered_with_its_parts():
    tech = SHARE / "M&S" / "12773 - Modular Unit" / "12773-Technical"
    ga = tech / "12773-01 General Assembly"
    lower = tech / "12773-02 Lower Body"
    rows = [
        (ga, [_f(ga, "0360297_Two Part Unit_12773-01-GA.PDF"), _f(ga, "12773-01-GA.SLDASM")], False),
        (lower, [_f(lower, "12773-02 GA.SLDASM"), _f(lower, "12773-02 GA.pdf"),
                 _f(lower, "12773-02-201.SLDPRT"), _f(lower, "12773-02-202.SLDPRT")], False),
    ]
    read = _texts({"0360297": "12773-01-GA REV A\n1  12773-02 GA  LOWER BODY GA  1\n2  12773-03-101  UPPER BODY GA 1",
                   "12773-02 GA": "12773-02GA\n1 12773-02-201 UPRIGHT 2\n2 12773-02-202 MIRROR 2"})
    m = pr.resolve("12773-01-GA", rows, client="M&S", read_text=read)
    by = {x["drawing"]: x for x in m["members"]}
    assert "12773-02-GA" in by and {f["format"] for f in by["12773-02-GA"]["files"]} == {"sldasm", "pdf"}
    assert by["12773-02-201"]["parent"] == "12773-02-GA" and by["12773-02-202"]["parent"] == "12773-02-GA"
    assert "12773-03-101" in m["missing"]


def test_a_glued_assembly_word_in_a_parts_list_is_the_same_reference():
    got = pr.read_drawing(Path("x.pdf"), "12773-01-GA", lambda p: "12773-02GA LOWER\n12773-03 SA UPPER\n2400-1200 SHEET")
    assert "12773-02GA" in got["references"] and "12773-03-SA" in got["references"]
    assert pr.spellings("12773-02GA") == ["12773-02GA", "12773-02-GA"]
    assert pr.spellings("12674-01-101-SA") == ["12674-01-101-SA", "12674-01-101SA"]
    assert pr.spellings("12674-01-01J") == ["12674-01-01J"]


def test_a_glued_assembly_file_is_not_a_missing_reference():
    """12674-01-GA on the real share, 12 Nov 2026: "INCOMPLETE: 12674-01-101-SA not found" while
    12674-01-101SA.SLDASM sat in the pack."""
    tech = SHARE / "M&S" / "12674 - Table" / "12674-Technical" / "12674-01 Single"
    rows = [(tech, [_f(tech, "0359829_12674-01-GA_Table_revB.PDF"), _f(tech, "12674-01-GA.SLDASM"),
                    _f(tech, "12674-01-101SA.SLDASM"), _f(tech, "12674-01-01J.SLDPRT")], False)]
    for printed in ("12674-01-101SA", "12674-01-101 SA", "12674-01-101-SA"):
        read = _texts({"0359829": f"12674-01-GA REV B\n1 {printed} BASE ASSY 1\n2 12674-01-01J TOP 1"})
        m = pr.resolve("12674-01-GA", rows, client="M&S", read_text=read)
        assert m["missing"] == [], (printed, m["missing"])
        assert "12674-01-101SA" in {x["drawing"] for x in m["members"]}, printed


def test_sheets_that_say_so_are_one_drawing_and_others_are_asked_about():
    one = _texts({"11896-04-00-GA-01": "SHEET 1 OF 2 11896-04-00-GA\n11896-04-01-01M",
                  "11896-04-00-GA-02": "SHEET 2 OF 2 11896-04-00-GA\n11896-04-01-02M",
                  "11896-04-00-GA-03": "SHEET 2 OF 2 11896-04-00-GA\n11896-04-01-02M"})
    m = pr.resolve("11896-04-00-GA", _wall_bay(), client="TTI", read_text=one)
    assert not m.get("configurations_unconfirmed")
    assert m["sheet_references"]["11896-04-00-GA-01"] == ["11896-04-01-01M"]

    variants = _texts({"11896-04-00-GA-01": "WALL BAY TYPE A 11896-04-00-GA\n11896-04-01-01M",
                       "11896-04-00-GA-02": "WALL BAY TYPE B 11896-04-00-GA\n11896-04-01-02M",
                       "11896-04-00-GA-03": "WALL BAY TYPE C 11896-04-00-GA\n11896-04-01-01M\n11896-04-01-02M"})
    m = pr.resolve("11896-04-00-GA", _wall_bay(), client="TTI", read_text=variants)
    assert m["configurations_unconfirmed"] is True and m["status"] == "provisional"
    assert any("alternative configurations" in a for a in m["assumptions"])
    assert {"11896-04-01-01M", "11896-04-01-02M"} <= {x["drawing"] for x in m["members"]}


def test_a_file_with_no_drawing_number_in_its_name_is_assigned_by_its_text_or_listed():
    tech = SHARE / "TTi" / "11896 - Training Centre" / "11896-Technical" / "11896-04 - Generic Wall Bay"
    gas = tech / "11896-04-00 - GAs"
    parts = tech / "11896-04-01 - Back Panel"
    rows = [
        (gas, [_f(gas, "11896-04-00-GA_RevA.pdf"), _f(gas, "11896-04-00-GA.SLDASM")], False),
        (parts, [_f(parts, "11896-04-01-01M_RevB.SLDPRT"),
                 _f(parts, "Back panel flat pattern.pdf", 222),
                 _f(parts, "Back panel flat.DXF", 333),
                 _f(parts, "Supplier leaflet.pdf", 444),
                 _f(parts, "11999-01-02M_other job.pdf", 555)], False),
        (parts / "ARCHIVE", [_f(parts / "ARCHIVE", "Old back panel.pdf", 666)], True),
    ]
    read = _texts({"11896-04-00-GA": "11896-04-00-GA REV A\n1 11896-04-01-01M BACK PANEL 2",
                   "Back panel flat pattern": "FLAT PATTERN  DRG No 11896-04-01-01M  1.2 MS\nUSED ON 11896-04-00-GA",
                   "Supplier leaflet": "CASTORS AND FEET CATALOGUE"})
    m = pr.resolve("11896-04-00-GA", rows, client="TTI", read_text=read)
    back = next(x for x in m["members"] if x["drawing"] == "11896-04-01-01M")
    assert {Path(f["path"]).name for f in back["files"]} == {"11896-04-01-01M_RevB.SLDPRT", "Back panel flat pattern.pdf"}
    assert [Path(a["path"]).name for a in m["assigned_by_text"]] == ["Back panel flat pattern.pdf"]
    un = {Path(u["path"]).name for u in m["unassigned_files"]}
    assert un == {"Back panel flat.DXF", "Supplier leaflet.pdf"}
    assert [o["drawing"] for o in m["other_drawings_in_folders"]] == ["11999-01-02M"]
    assert "11999-01-02M" not in {x["drawing"] for x in m["members"]}
    assert not any("Old back panel" in str(v) for v in (m["unassigned_files"], m["assigned_by_text"]))
    assert any("NOT in the pack" in a for a in m["assumptions"])
