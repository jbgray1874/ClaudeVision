"""Pack-size check (17 Nov 2026): each drawing's own PDF says the catalogue's pack quantity, or the
row is flagged. Offline: the drawing areas are folders made here, a PDF's text is given, and the
catalogue is a workbook made here."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pack_size_check as P  # noqa: E402


# ── what a drawing says ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, want", [
    ("NOTES:\n1. SUPPLIED IN PACK OF 45", [45]),
    ("PACK\nOF 10   A4 PORTRAIT", [10]),
    ("25 PER PACK", [25]),
    ("QTY PER PACK: 50", [50]),
    ("PACK QTY 5", [5]),
    ("10 PACK", [10]),
    ("PACKS OF 10 ... 10 PER PACK", [10, 10]),
    ("MATERIAL 3MM ACRYLIC   QTY 1   SCALE 1:2", []),
    ("PACKAGING: BUBBLE WRAP", []),
])
def test_the_pack_quantity_a_drawing_states(text, want):
    assert [q for q, _w in P.packs_stated(text)] == want


def test_the_drawings_own_words_are_quoted():
    (q, words), = P.packs_stated("TICKET HOLDER 78 X 78  SUPPLIED AS PACK OF 25  REV C")
    assert q == 25 and "PACK OF 25" in words


@pytest.mark.parametrize("sheet, stated, result", [
    (10, [(10, "PACK OF 10")], "Matches"),
    (1, [], "Matches"),                                        # no pack stated: a pack of 1
    (5, [(10, "PACK OF 10")], "MISMATCH"),
    (45, [], "CHECK: no pack on drawing"),
    (10, [(10, "a"), (45, "b")], "CHECK: several on drawing"),
    (None, [(10, "a")], "CHECK: sheet quantity is not a number"),
])
def test_judging_a_row(sheet, stated, result):
    assert P.judge(sheet, stated)[0] == result


def test_the_catalogue_is_checked_against_itself():
    # 17 Nov: a drawing is "PACK OF 10", UPC "(10)", and the pack column says 5
    assert "PACK OF 10" in P.sheet_own_check(5, "PACK OF 10 - A5 FREESTANDING", "1000005(10)")
    assert "UPC ends (5)" in P.sheet_own_check(10, "PACK OF 10 - 78 x 78 TICKET HOLDER", "1000004(5)")
    assert P.sheet_own_check(10, "PACK OF 10 - A4", "1000001(10)") == ""
    assert P.sheet_own_check(1, "FREEZER DIVIDER", "1000006") == ""


def test_quantities_read_from_cells():
    assert [P.as_qty(v) for v in (10, 10.0, "25", " 5 ", "TBC", None, 0, 2.5)] == [10, 10, 25, 5, None, None, None, None]


# ── finding the drawing, on real folders ────────────────────────────────────────────────

def _areas(tmp_path):
    design = tmp_path / "Design"
    files = {
        "Client A/4101 - Graphic Holder/4101-Technical/4101_A4 PORT_RevB.pdf": "",
        "Client A/4101 - Graphic Holder/4101-Technical/4101_A4 PORT_RevA.pdf": "",
        "Client A/4102 - Ticket Holder/4102-GA_RevC.pdf": "",
        "Client A/4102 - Ticket Holder/Archive/4102-GA_RevA.pdf": "",
        "Client A/20001 - Stand/20001-01-GA_revB.pdf": "",
        "Client A/20001 - Stand/20001-02-GA_revA.pdf": "",
        "Client A/20001 - Stand/20001-02-GA.SLDDRW": "",
        "Client A/4103 - Freestanding/Old/4103_A5.pdf": "",
        "Client A/20002 - Tall/20002-01.dwg": "",
        "Other/12345 - Unrelated/12345-GA.pdf": "",
    }
    for rel in files:
        p = design / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4 stand-in")
    return design


TEXT = {
    "4101_A4 PORT_RevB.pdf": "4101 A4 PORTRAIT GRAPHIC HOLDER  PACK OF 10  REV B",
    "4101_A4 PORT_RevA.pdf": "4101 A4 PORTRAIT GRAPHIC HOLDER  PACK OF 45  REV A",
    "4102-GA_RevC.pdf": "4102-GA TICKET HOLDER  25 PER PACK",
    "20001-01-GA_revB.pdf": "20001-01-GA LIPARI TALL",
    "20001-02-GA_revA.pdf": "",                                     # a scan: no text
    "4103_A5.pdf": "4103 A5 FREESTANDING  PACK OF 10",
}


def _check(tmp_path, drawing, qty):
    design = _areas(tmp_path)
    folders = {str(design): P.walk_job_folders(design, say=lambda *_a: None)}
    return P.check_drawing(drawing, qty, folders, read_text=lambda p: TEXT.get(Path(p).name, ""))


def test_the_latest_revision_is_read(tmp_path):
    r = _check(tmp_path, "4101", 10)
    assert r["result"] == "Matches" and r["file"].endswith("4101_A4 PORT_RevB.pdf")


def test_a_bare_job_number_reads_its_ga_and_says_so(tmp_path):
    r = _check(tmp_path, "4102", 10)
    assert r["result"] == "MISMATCH" and r["on_drawing"] == "25"
    assert "read its GA, 4102-GA" in r["note"] and "Archive" not in r["file"]


def test_no_pack_on_the_drawing_is_a_pack_of_one(tmp_path):
    assert _check(tmp_path, "20001-01-GA", 1)["result"] == "Matches"
    assert _check(tmp_path, "20001-01-GA", 5)["result"] == "CHECK: no pack on drawing"


def test_a_scan_is_said_never_guessed(tmp_path):
    assert _check(tmp_path, "20001-02-GA", 1)["result"] == "Drawing not readable"


def test_what_cannot_be_found_is_said(tmp_path):
    assert "no folder for job 7777" in _check(tmp_path, "7777-GA", 1)["note"]
    r = _check(tmp_path, "20002-01", 1)                               # only a DWG
    assert r["result"] == "Drawing not found" and "no PDF named for 20002-01" in r["note"]


def test_archive_folders_are_left_out_of_the_job_list(tmp_path):
    design = _areas(tmp_path)
    names = [Path(f).name for f in P.walk_job_folders(design, say=lambda *_a: None)]
    assert "4102 - Ticket Holder" in names and "12345 - Unrelated" in names
    assert not any("Archive" in f for f in P.walk_job_folders(design, say=lambda *_a: None))


# ── the report ──────────────────────────────────────────────────────────────────────────

HEAD = ["Current Stock", "List Type", "Status", "UPC - Number", "Description", "SDI Drawing Number",
        "Weight", "Place", "Store Max Grab", "QTY per pack\nTO CONFIRM", "Total units"]


def _catalogue(path):
    import openpyxl
    wb = openpyxl.Workbook()
    a = wb.active
    a.title = "A - Auto Replenish (OPEX)"
    a.append(HEAD)
    a.append(["45 packs", "A", "Current", "1000001(10)", "PACK OF 10 - A4 PORT", 4101, 333, "SDI", 1, 10, 200])
    a.append(["", "A", "Current", "1000004(5)", "PACK OF 10 - TICKET HOLDER", 4102, 16, "SDI", 4, 10, 100])
    a.append(["", "A", "Current", "1000005(10)", "PACK OF 10 - A5", 4103, 10, "SDI", 1, 5, 100])
    b = wb.create_sheet("B - Approved (CAPEX)")
    b.append(HEAD)
    b.append(["0", "B", "Current", "1000002(1)", "Stand tall", "20001-01-GA", "N/A", "SDI", 1, 1, 20])
    b.append(["0", "B", "Current", "1000003(1)", "Stand short", "20002-01", "N/A", "SDI", 1, 1, 20])
    c = wb.create_sheet("C- Discontinued")
    c.append(HEAD)
    c.append(["", "C", "Gone", "1", "not checked", "4101", "", "", 1, 99, 1])
    wb.save(path)


def test_the_report_is_a_new_workbook_and_the_catalogue_is_untouched(tmp_path):
    import openpyxl
    sheet = tmp_path / "Master Catalogue.xlsx"
    _catalogue(sheet)
    before = sheet.read_bytes()
    design = _areas(tmp_path)
    folders = {str(design): P.walk_job_folders(design, say=lambda *_a: None)}
    res = P.run(sheet, ["A", "B"], [design], tmp_path / "out", say=lambda *_a: None, folders=folders,
                read_text=lambda p: TEXT.get(Path(p).name, ""))
    assert sheet.read_bytes() == before
    assert res["rows"] == 5 and res["own"] == 2                       # tab C is not read
    wb = openpyxl.load_workbook(res["report"])
    a = wb["A - Auto Replenish (OPEX)"]
    col = {a.cell(1, c).value: c for c in range(1, a.max_column + 1)}
    assert col["Pack check: result"] == len(HEAD) + 1                 # after the last column, nothing moved
    got = {a.cell(r, 6).value: a.cell(r, col["Pack check: result"]).value for r in range(2, 5)}
    assert got == {4101: "Matches", 4102: "MISMATCH", 4103: "MISMATCH"}
    assert "PACK OF 10" in a.cell(4, col["Sheet's own check"]).value
    b = wb["B - Approved (CAPEX)"]
    assert [b.cell(r, len(HEAD) + 1).value for r in (2, 3)] == ["Matches", "Drawing not found"]
    summary = wb["Pack check"]
    assert summary["A4"].value == "MISMATCH" and summary["B4"].value == 2
    assert wb["C- Discontinued"].max_column == len(HEAD)              # left as it was


def test_a_missing_tab_stops_before_anything_is_written(tmp_path):
    sheet = tmp_path / "c.xlsx"
    _catalogue(sheet)
    with pytest.raises(SystemExit, match="no tab whose name starts with 'Z'"):
        P.run(sheet, ["A", "Z"], [tmp_path], tmp_path / "out", say=lambda *_a: None, folders={})
    assert not (tmp_path / "out").exists()
