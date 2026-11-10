"""The drawing's parts list decides what a model read counts (JG, 10 Nov 2026).

The 12674-01-GA comparison of the two model readers found three faults, each fixed generically:

  * THE DOCUMENT MANAGER COUNTED A DISPLAY MODEL. The GA assembly held 24 of another job's
    assembly, placed for show, and 6 bought-in plinth feet; neither file was in the pack.
    SolidWorks suppresses a component it cannot find and counted neither; the Document Manager
    counts what was saved and counted both. The GA drawing's parts list names the feet and not
    the display model, and is now the rule: a component it names nowhere, and that neither sits
    under a listed assembly nor holds a listed part, is not counted, and is said.
  * A TYPED MATERIAL THAT NAMES NO MATERIAL. 07J's Material property said "SHELF". A typed value
    is the designer's spec, so it outranked the applied MDF. Now a typed value must read as a
    material, in both readers; one that does not is set aside and said.
  * SOLIDWORKS READ NO PARTS LIST. Its table filter kept table type 3, the revision table, and
    so skipped the parts list. The table's shape now decides, as in the Document Manager.

Everything runs through fake COM objects, on Linux.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "solidworks"))
sys.path.insert(0, str(ROOT / "tests"))

import sw_docmgr_analyse as dm                                    # noqa: E402
import sw_native_analyse as swa                                   # noqa: E402
from test_a_docmgr_extract_backs_up_solidworks import (           # noqa: E402
    KEY, FakeApp, FakeComponent, FakeConfig, FakeDoc, FakeFactory, FakeTable)

GA_ROWS = [["ITEM NO.", "PART NUMBER", "DESCRIPTION", "QTY."],
           ["1", "12345-01-101SA", "TABLE FRAME", "1"],
           ["2", "12345-01-01J", "TOP", "1"],
           ["3", "12345-01-02J", "SHELF", "2"],
           ["4", "HAFELE: 637.30.904", "PLINTH ADJUSTING FOOT", "6"]]


def _job(tmp_path, rows=GA_ROWS, shelf_material=("MDF", "")):
    folder = tmp_path / "12345-01-GA"
    folder.mkdir()
    top, shelf = folder / "12345-01-01J.SLDPRT", folder / "12345-01-02J.SLDPRT"
    sub, ga, drw = (folder / "12345-01-101SA.SLDASM", folder / "12345-01-GA.SLDASM",
                    folder / "12345-01-GA.SLDDRW")
    for p in (top, shelf, sub, ga, drw):
        p.write_bytes(b"\x00SLDFILE")
    foot = folder / "PLINTH ADJUSTING FOOT 637.30.904.SLDPRT"            # not in the pack
    show = folder / "54321-02-GA.SLDASM"                                 # not in the pack
    docs = {
        str(top): FakeDoc(props={"Description": ("TOP", ""), "Material": ("MDF", "")}),
        str(shelf): FakeDoc(props={"Description": ("SHELF", ""), "Material": shelf_material}),
        str(sub): FakeDoc(config=FakeConfig(components=[
            FakeComponent(top), FakeComponent(shelf), FakeComponent(shelf)])),
        str(ga): FakeDoc(config=FakeConfig(
            components=[FakeComponent(sub)] + [FakeComponent(foot) for _ in range(6)]
            + [FakeComponent(show) for _ in range(24)])),
        str(drw): FakeDoc(tables={"Bill of Materials1": FakeTable(rows)}, refs=[ga]),
    }
    return folder, FakeApp(docs)


@pytest.fixture()
def read(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(dm.KEY_ENV, KEY)

    def _read(**kw):
        folder, app = _job(tmp_path, **kw)
        out = tmp_path / "out.json"
        assert dm.main([str(folder), "--out", str(out)], class_factory=FakeFactory(app)) == 0
        import json
        recs = json.loads(out.read_text(encoding="utf-8"))["records"]
        return {Path(r["path"]).name: r for r in recs}, capsys.readouterr().out
    return _read


def _bom(rec):
    return {ln["part_number"]: ln["qty"] for ln in rec["bom"]}


def test_a_display_model_the_parts_list_does_not_name_is_not_counted_and_is_said(read):
    recs, printed = read()
    ga = recs["12345-01-GA.SLDASM"]
    assert "54321-02-GA" not in _bom(ga)
    assert ga["excluded_components"] == [
        {"part_number": "54321-02-GA", "qty": 24.0,
         "reason": "not on 12345-01-GA.SLDDRW's parts list, and not under or above anything "
                   "it lists"}]
    assert not any(e["child"] == "54321-02-GA" for e in ga["assembly_edges"])
    assert "54321-02-GA x24 not counted" in printed


def test_a_bought_in_part_the_list_names_by_its_catalogue_number_is_kept(read):
    recs, _ = read()
    assert _bom(recs["12345-01-GA.SLDASM"])["PLINTH ADJUSTING FOOT 637.30.904"] == 6.0


def test_everything_under_a_listed_assembly_is_kept(read):
    bom = _bom(read()[0]["12345-01-GA.SLDASM"])
    assert bom["12345-01-101SA"] == 1.0 and bom["12345-01-01J"] == 1.0
    assert bom["12345-01-02J"] == 2.0


def test_a_parts_only_list_keeps_the_assembly_above_its_parts(read):
    rows = [GA_ROWS[0], GA_ROWS[2], GA_ROWS[3], GA_ROWS[4]]          # no 101SA row
    bom = _bom(read(rows=rows)[0]["12345-01-GA.SLDASM"])
    assert "12345-01-101SA" in bom and "54321-02-GA" not in bom


def test_a_list_that_cannot_be_matched_to_the_model_excludes_nothing_and_says_so(read):
    rows = [["ITEM NO.", "PART NUMBER", "QTY."], ["1", "A", "1"], ["2", "B", "1"],
            ["3", "C", "1"]]
    recs, _ = read(rows=rows)
    ga = recs["12345-01-GA.SLDASM"]
    assert _bom(ga)["54321-02-GA"] == 24.0
    assert "excluded_components" not in ga
    assert any("could not be matched" in n for n in ga["notes"])


def test_a_typed_material_that_names_no_material_is_set_aside_in_the_document_manager(read):
    recs, _ = read(shelf_material=("SHELF", ""))
    rs = recs["12345-01-02J.SLDPRT"]["route_signals"]
    assert rs["material"] == ""
    assert any("'SHELF', which names no material" in n for n in rs["notes"])


def test_a_typed_material_that_does_name_one_is_still_the_spec(read):
    recs, _ = read(shelf_material=("18mm MFC", ""))
    rs = recs["12345-01-02J.SLDPRT"]["route_signals"]
    assert (rs["material"], rs["material_source"]) == ("18mm MFC", "custom_property")


def test_solidworks_takes_the_applied_material_over_a_typed_part_name():
    assert swa._material_and_source({"Material": "SHELF"}, "MDF") == ("MDF", "applied_library")
    assert swa._material_and_source({"Material": "SHELF"}, "") == ("", "")
    assert swa._material_and_source({"Grade": "S275"}, "x") == ("S275", "custom_property")


@pytest.mark.parametrize("text", ["MDF", "Steel", "Plain Carbon Steel", "6082 T6", "S275",
                                  "18mm MFC", "AISI 304", "Glass", "Corian", "Birch Ply",
                                  "Polyethylene foam", "1.4301", "Zintec 1.2mm"])
def test_materials_read_as_materials(text):
    assert swa.reads_as_material(text)


@pytest.mark.parametrize("text", ["SHELF", "PANEL", "BRACKET", "TOP", "12674-01-07J",
                                  "Material <not specified>", ""])
def test_part_names_and_blanks_do_not(text):
    assert not swa.reads_as_material(text)


# ── SolidWorks: the parts list is read whatever its table-type number ──────────────────

class _SwTable:
    def __init__(self, rows, kind):
        self._rows, self.Type = rows, kind
        self.RowCount, self.ColumnCount = len(rows), len(rows[0])
        self.Title = f"t{kind}"

    def Text(self, r, c):
        return self._rows[r][c]


class _SwView:
    def __init__(self, tables):
        self._tables = tables

    def GetTableAnnotations(self):
        return tuple(self._tables)


class _SwDrawing:
    def __init__(self, sheets):
        self._sheets = sheets

    def GetViews(self):
        return tuple(tuple(v) for v in self._sheets)


REV = [["REV", "DESCRIPTION", "DATE", "APPROVED"], ["A", "FIRST ISSUE", "01/11/26", "JG"]]


def test_solidworks_reads_the_parts_list_and_not_the_revision_table():
    sheet1 = [_SwView([_SwTable(REV, 3)])]
    sheet2 = [_SwView([_SwTable(GA_ROWS, 2)]), _SwView([])]
    lines = swa.drawing_bom_tables(_SwDrawing([sheet1, sheet2]))
    assert [(ln.part_number, ln.qty) for ln in lines] == [
        ("12345-01-01J", 1.0), ("12345-01-02J", 2.0), ("12345-01-101SA", 1.0),
        ("HAFELE: 637.30.904", 6.0)]


def test_a_table_found_twice_is_read_once():
    t = _SwTable(GA_ROWS, 2)
    lines = swa.drawing_bom_tables(_SwDrawing([[_SwView([t]), _SwView([t])]]))
    assert len(lines) == 4


def test_both_readers_read_a_table_the_same_way():
    rows = [["No.", "Description", "Qty"], ["12345-01-01J", "TOP", "2"]]
    assert [(b.part_number, b.qty) for b in swa.bom_lines_from_rows(rows)] == \
        [(b.part_number, b.qty) for b in dm.bom_from_table_rows(rows)] == [("12345-01-01J", 2.0)]
    assert swa.bom_lines_from_rows(REV) == []
