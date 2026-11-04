"""A board part is the pieces its own parts table lists (D-688).

12693-01-04J LARGE TOP INSERT is MDF (its title block prints MRMDF). Its own sheet carries a
parts table of uncoded rows that are sizes and nothing else, read by both table readers under
04J:

    1145 x 1145 x 18 mm   1
    1145 x 210 x 12 mm    2
    725 x 210 x 12 mm     1
    (a blank row)         1

There is no DXF for it. D-669 makes a part the assembly of its numbered flats, and its table
reader only corroborated flats, so with none these rows went nowhere: 04J was costed as ONE
blank on one 18 mm board, and the three 12 mm pieces, their board and their machining were
missing from the price.

A board part with no flat of its own whose table lists two or more such rows, or one row at a
count above one, is now those pieces: each a child of the part, at the row's size, thickness
and count, in the part's own stock and words, taking the part's cutting; the part is costed
through its pieces only. A tube cut list, a single row of one, and a part with flats are left
as they were. Made-up job numbers throughout.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import drawing_job_merge as d                                         # noqa: E402

CODE = "12999-01-04J"
GA = "12999-01-GA"
SHEET = "12999-01 PACK.pdf p.6"


def _row(item, desc, qty, parent=CODE, code=""):
    return {"part_number": code, "description": desc, "quantity": qty, "bom_item_no": item,
            "bom_parent": parent, "bom_parent_known": True, "source_pdf": parent,
            "bom_source": "BOTH", "bom_sheet": SHEET}


def _rows():
    return [_row("1", "1145 x 1145 x 18 mm", 1), _row("2", "1145 x 210 x 12 mm", 2),
            _row("3", "725 x 210 x 12 mm", 1), _row("4", "", 1)]


def _insert(**kw):
    part = {"part_number": CODE, "description": "LARGE TOP INSERT", "quantity": 1,
            "normalized_material": "MDF", "material_text_as_printed": "MRMDF",
            "material_stated": "MRMDF", "normalized_thickness_mm": 18.0,
            "blank_length_mm": 1145.0, "blank_width_mm": 1145.0, "page_roles": ["detail"],
            "textual_operations": ["cnc_routing", "glue"],
            "operation_sources": {"cnc_routing": "llm_full_extract"},
            "operation_evidence": {"cnc_routing": "CNC ROUTE TO PROFILE"}}
    part.update(kw)
    return part


def _minted(part=None, rows=None):
    part = part or _insert()
    rows = _rows() if rows is None else rows
    parts = [part]
    done = d.mint_pieces_listed_on_own_table(parts, rows)
    return done, {p["part_number"]: p for p in parts}, rows


# ── the 04J case ──────────────────────────────────────────────────────────────────────────

def test_three_sized_rows_are_three_pieces_of_the_part():
    done, parts, rows = _minted()
    assert done == [CODE]
    pieces = {pn: p for pn, p in parts.items() if pn != CODE}
    assert sorted(pieces) == [f"{CODE}-01", f"{CODE}-02", f"{CODE}-03"], "the blank row is no piece"
    want = {f"{CODE}-01": (1, 18.0, 1145.0, 1145.0), f"{CODE}-02": (2, 12.0, 1145.0, 210.0),
            f"{CODE}-03": (1, 12.0, 725.0, 210.0)}
    for pn, (qty, thick, length, width) in want.items():
        p = pieces[pn]
        assert p["quantity"] == qty, "the row's count, per part"
        assert p["bom_parents"] == [{"parent": CODE, "qty": qty}]
        assert float(p["normalized_thickness_mm"]) == thick
        assert (p["blank_length_mm"], p["blank_width_mm"]) == (length, width)
        assert p["normalized_geometry"]["blank_length_mm"] == length
        assert p["blank_length_mm_source"] == "drawing_deterministic"


def test_the_pieces_follow_the_d669_conventions():
    _done, parts, _rows_ = _minted()
    box = parts[CODE]
    kids = [f"{CODE}-01", f"{CODE}-02", f"{CODE}-03"]
    assert box["is_assembly_parent"] is True
    assert box["assembly_children"] == kids
    for pn in kids:
        assert parts[pn]["dxf_minted_piece_of"] == CODE, "the field every piece reader reads"
        assert parts[pn]["listed_piece_of"] == CODE, "and says no flat was read"
        assert not parts[pn].get("dxf_path") and not parts[pn].get("dxf_augmented")
    assert [m["costed_as"] for m in box["listed_pieces"]] == kids


def test_each_piece_keeps_the_parts_stock_in_the_parts_words():
    _done, parts, _rows_ = _minted(_insert(normalized_finish="LACQUERED",
                                           colours=["WHITE"]))
    for pn in (f"{CODE}-01", f"{CODE}-02", f"{CODE}-03"):
        p = parts[pn]
        assert p["normalized_material"] == "MDF"
        assert p["material_text_as_printed"] == "MRMDF", "moisture-resistant stays so"
        assert p["material_stated"] == "MRMDF"
        assert p["normalized_finish"] == "LACQUERED"
        assert p["colours"] == ["WHITE"]


def test_the_parts_cutting_is_each_pieces_and_no_longer_the_parts():
    _done, parts, _rows_ = _minted()
    box = parts[CODE]
    assert "cnc_routing" not in box["textual_operations"], "an assembly is not routed"
    assert "glue" in box["textual_operations"], "joining its pieces is the part's own work"
    for pn in (f"{CODE}-01", f"{CODE}-02", f"{CODE}-03"):
        p = parts[pn]
        assert p["textual_operations"] == ["cnc_routing"]
        assert p["operation_sources"] == {"cnc_routing": "llm_full_extract"}
        assert p["operation_evidence"] == {"cnc_routing": "CNC ROUTE TO PROFILE"}
    assert box["operations_moved_to_pieces"]["cnc_routing"] == [
        f"{CODE}-01", f"{CODE}-02", f"{CODE}-03"]


def test_single_blank_work_the_table_cannot_place_is_not_spread_and_is_said():
    _done, parts, _rows_ = _minted(_insert(textual_operations=["cnc_routing", "drilling"]))
    assert parts[CODE]["textual_operations"] == ["drilling"]
    assert all(parts[f"{CODE}-0{n}"]["textual_operations"] == ["cnc_routing"] for n in (1, 2, 3))
    flag = next(f for f in parts[CODE]["review_flags"]
                if f.startswith("PIECES FROM ITS OWN PARTS TABLE"))
    assert "drilling is not given to any piece" in flag and "say which" in flag


def test_a_part_with_no_cutting_gives_none_and_asks():
    _done, parts, _rows_ = _minted(_insert(textual_operations=["glue"], operation_sources={},
                                           operation_evidence={}))
    assert not parts[f"{CODE}-02"]["textual_operations"]
    assert "operations_moved_to_pieces" not in parts[CODE]
    assert any("say how they are cut" in f for f in parts[CODE]["review_flags"])


def test_the_reading_is_said_plainly_on_the_part():
    _done, parts, rows = _minted()
    flag = next(f for f in parts[CODE]["review_flags"]
                if f.startswith("PIECES FROM ITS OWN PARTS TABLE"))
    for words in ("'1145 x 1145 x 18 mm' x1", "'1145 x 210 x 12 mm' x2",
                  "'725 x 210 x 12 mm' x1", SHEET, "both table readers", "MRMDF",
                  "the drawing's own table", "shop should confirm",
                  "costed through its pieces only"):
        assert words in flag, words
    assert any(f.startswith(f"piece of {CODE}: row '1145 x 210 x 12 mm' x2")
               for f in parts[f"{CODE}-02"]["review_flags"])
    assert [r.get("row_role") for r in rows] == ["parent_piece"] * 3 + [None]
    assert [r.get("consumed_as") for r in rows[:3]] == [f"{CODE}-01", f"{CODE}-02", f"{CODE}-03"]


def test_reading_twice_mints_once():
    part = _insert()
    parts, rows = [part], _rows()
    d.mint_pieces_listed_on_own_table(parts, rows)
    assert d.mint_pieces_listed_on_own_table(parts, rows) == []
    assert len(parts) == 4


def test_the_part_is_costed_through_its_pieces_only():
    """The roll-up multiplies each row's count by the part's own, and the part carries no
    blank and no routing of its own."""
    import estimator as E
    import route_compiler as rc
    rows = [_row("1", "LARGE TOP INSERT", 2, GA, CODE)] + _rows()
    ga = {"part_number": GA, "description": "COUNTER", "quantity": 1,
          "is_assembly_parent": True, "assembly_children": [CODE]}
    parts = [ga, _insert(quantity=2)]
    d.mint_pieces_listed_on_own_table(parts, rows)
    g = rc.build_part_graph(parts, {}, rows, known_assemblies=[GA])
    nodes = {n.part_number: n for n in g["nodes"]}
    assert nodes[CODE].kind == "assembly"
    assert {pn: g["quantities"].get(pn) for pn in (f"{CODE}-01", f"{CODE}-02", f"{CODE}-03")} \
        == {f"{CODE}-01": 2, f"{CODE}-02": 4, f"{CODE}-03": 2}
    assert not any(i.get("code") == "not_linked_to_the_product" for i in g.get("issues") or [])

    summary = {"declared_product": GA, "drawing_number": GA,
               "manufacturing_writeup": {"parts": parts},
               "document_analysis": {"bom_rows": rows}, "llm_full_extract": {}, "pages": []}
    es = E.estimate_document(parts, summary=summary)
    by = {pe["part_number"]: pe for pe in es["part_estimates"]}
    box = by[CODE]
    assert float((box.get("material_estimate") or {}).get("cost_per_part_gbp") or 0) == 0.0, \
        "no double material: the part's board is its pieces'"
    assert "cnc_routing" not in ((box.get("process_estimate") or {})
                                 .get("run_times_min_per_unit") or {})
    for pn, thick in ((f"{CODE}-01", 18.0), (f"{CODE}-02", 12.0), (f"{CODE}-03", 12.0)):
        me = by[pn]["material_estimate"]
        assert me["material"] == "MDF" and float(me["thickness_mm"]) == thick
        assert float(me["cost_per_part_gbp"]) > 0
        assert "cnc_routing" in by[pn]["process_estimate"]["run_times_min_per_unit"]
    decisions = {(x.get("operation"), x.get("target_id")): x.get("status")
                 for x in es["canonical_route_shadow"]["decisions"]}
    assert decisions.get(("cnc_routing", f"{CODE}-02")) == "required"
    assert decisions.get(("cnc_routing", CODE)) != "required"


# ── what is left alone ────────────────────────────────────────────────────────────────────

def test_a_tube_cut_list_is_untouched():
    frame = {"part_number": "12999-01-01M", "description": "FRAME", "quantity": 1,
             "normalized_material": "MILD_STEEL", "textual_operations": ["saw", "welding"]}
    rows = [_row("1", "25.00 x 25.00 x 1.50mm TUBE 1000", 2, "12999-01-01M"),
            _row("2", "25.00 x 25.00 x 1.50mm TUBE 500", 2, "12999-01-01M")]
    done, parts, rows = _minted(frame, rows)
    assert done == [] and list(parts) == ["12999-01-01M"]
    assert frame["textual_operations"] == ["saw", "welding"]
    assert not frame.get("is_assembly_parent")
    assert not any(r.get("consumed") for r in rows)


def test_sized_rows_under_a_steel_part_are_not_board_pieces():
    plate = {"part_number": "12999-01-02M", "description": "BASE PLATE", "quantity": 1,
             "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 3.0}
    rows = [_row("1", "300 x 200 x 3 mm", 2, "12999-01-02M"),
            _row("2", "100 x 50 x 3 mm", 1, "12999-01-02M")]
    done, parts, _rows_ = _minted(plate, rows)
    assert done == [] and list(parts) == ["12999-01-02M"]


def test_a_species_alone_is_timber_cut_to_length_not_a_board():
    batten = {"part_number": "12999-01-05J", "description": "FRAME", "quantity": 1,
              "normalized_material": "TIMBER", "material_text_as_printed": "PSE PINE"}
    rows = [_row("1", "1200 x 44 x 44 mm", 2, "12999-01-05J"),
            _row("2", "600 x 44 x 44 mm", 2, "12999-01-05J")]
    done, _parts, _rows_ = _minted(batten, rows)
    assert done == []


def test_a_single_row_of_one_is_the_parts_own_blank():
    shelf = _insert(part_number="12999-01-06J", blank_length_mm=556.0, blank_width_mm=556.0)
    done, parts, rows = _minted(shelf, [_row("1", "556 x 556 x 18 mm", 1, "12999-01-06J"),
                                        _row("2", "EDGING. L:1759mm", 1, "12999-01-06J")])
    assert done == [] and list(parts) == ["12999-01-06J"]
    assert shelf["textual_operations"] == ["cnc_routing", "glue"], "its route is untouched"
    assert not shelf.get("is_assembly_parent") and not shelf.get("assembly_children")
    assert not any(r.get("consumed") for r in rows)


def test_a_single_row_at_a_count_above_one_is_that_many_pieces():
    shelf = _insert(part_number="12999-01-07J")
    done, parts, _rows_ = _minted(shelf, [_row("1", "626 x 626 x 25 mm", 2, "12999-01-07J")])
    assert done == ["12999-01-07J"]
    assert parts["12999-01-07J-01"]["quantity"] == 2


def test_a_row_of_another_table_or_with_a_code_is_not_this_parts_piece():
    rows = [_row("1", "1145 x 1145 x 18 mm", 1, "12999-01-08J"),
            _row("2", "1145 x 210 x 12 mm", 2, "12999-01-08J"),
            _row("3", "725 x 210 x 12 mm", 1, CODE, code="12999-01-104")]
    done, parts, _rows_ = _minted(_insert(), rows)
    assert done == [] and list(parts) == [CODE]


# ── a part with flats of its own ──────────────────────────────────────────────────────────

def _rect(msp, x0, y0, x1, y1):
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)),
                 ((x0, y1), (x0, y0))):
        msp.add_line(a, b)


def test_a_part_with_numbered_flats_keeps_the_d669_reading(tmp_path):
    import ezdxf
    for n, (a, b) in enumerate([(1145.0, 1145.0), (1145.0, 210.0)], start=1):
        doc = ezdxf.new()
        doc.header["$INSUNITS"] = 0
        _rect(doc.modelspace(), 0, 0, a, b)
        doc.saveas(tmp_path / f"{CODE}_PART{n}_12mm MDF_revA.DXF")
    rows = _rows()
    summary = {"manufacturing_writeup": {"parts": [_insert()]}, "pages": [],
               "document_analysis": {"bom_rows": rows}}
    out = d.augment_summary_with_dxf(summary, sorted(tmp_path.glob("*.DXF")), reestimate=False)
    parts = out["manufacturing_writeup"]["parts"]
    before = sorted(p["part_number"] for p in parts)
    assert f"{CODE}-01" in before and f"{CODE}-02" in before, "D-669 split the flats"
    assert d.mint_pieces_listed_on_own_table(parts, rows) == []
    assert sorted(p["part_number"] for p in parts) == before
    assert not any(p.get("listed_piece_of") for p in parts)
    assert not any(r.get("consumed") for r in rows)


def test_a_part_with_its_own_flat_is_untouched():
    flat = _insert(geometry_source="dxf_flat_pattern", dxf_augmented=True,
                   flat_pattern_detected=True)
    done, parts, _rows_ = _minted(flat)
    assert done == [] and list(parts) == [CODE]


# ── the pipeline calls it where the part is final and the pieces can still be costed ─────

def test_the_scan_reads_the_pieces_after_the_table_readers_and_before_the_graph():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    at = src.index("mint_pieces_listed_on_own_table(")
    assert src.index("apply_stated_cut_list_to_parts(") < at, "after the part's row evidence"
    assert at < src.index("apply_detail_page_geometry(_parts_dg"), "before the sheet sizing"
    assert at < src.index("apply_canonical_evidence_to_parts("), "before the canonical graph"
    assert at < src.index("estimate_document(summary[\"manufacturing_writeup\"]")


# ── end to end: the 12 mm pieces reach the Other Sheet Material block at 12 mm ───────────

def _template(path: Path) -> Path:
    """The Estimate sheet's block labels and totals formula at the template's rows (as the
    D-602 fixture writes them)."""
    import openpyxl
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "Estimate"
    for row, text in ((10, "Bill of Materials (Per Unit)"), (51, "Wire"),
                      (52, "Part Description"), (61, "Sheet Steel"), (62, "Part Description"),
                      (82, "Other Sheet Material"), (83, "Part Description"),
                      (92, "Total Material Cost"), (94, "Labour"), (95, "Operation"),
                      (168, "Total Labour Cost (Including  Downtime)")):
        ws.cell(row, 3, text)
    ws.cell(92, 13, "=(SUM(M11:M50)+SUM(M53:M60)+SUM(M63:M81)+SUM(M84:M91)+AF83)")
    book.save(path)
    return path


def test_the_twelve_mm_pieces_land_on_other_sheet_material_at_twelve_mm(tmp_path, monkeypatch):
    import openpyxl
    import estimator as E
    import wb_populate
    parts = [_insert()]
    rows = _rows()
    d.mint_pieces_listed_on_own_table(parts, rows)
    summary = {"declared_product": CODE, "drawing_number": CODE,
               "manufacturing_writeup": {"parts": parts},
               "document_analysis": {"bom_rows": rows}, "llm_full_extract": {}, "pages": [],
               "job_folder": str(tmp_path)}
    summary["estimate_summary"] = E.estimate_document(parts, summary=summary)
    summary["part_estimates"] = summary["estimate_summary"]["part_estimates"]
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(_template(tmp_path / "template.xlsx")))
    monkeypatch.setitem(wb_populate.CELL_MAP, "output_dir", str(tmp_path / "out"))
    out = wb_populate.populate_workbook(summary, "D688")
    assert out, "the workbook writer produced no book"
    ws = openpyxl.load_workbook(out)["Estimate"]
    cm = wb_populate.CELL_MAP
    blocks = {}
    for block in ("bom", "steel", "other_sheet"):
        c = cm[block]
        for r in range(c["first_row"], c["last_row"] + 1):
            desc = str(ws.cell(r, 3).value or "")
            if desc:
                blocks[desc.split()[0]] = (block, r)
    for pn, (qty, thick) in {f"{CODE}-01": (1, 18), f"{CODE}-02": (2, 12),
                             f"{CODE}-03": (1, 12)}.items():
        assert pn in blocks, f"{pn} is not on the sheet"
        block, r = blocks[pn]
        c = cm["other_sheet"]
        assert block == "other_sheet", (pn, block)
        assert float(ws.cell(r, c["col_thick"]).value) == thick
        assert float(ws.cell(r, c["col_qty"]).value) == qty
    assert CODE not in blocks, "the part is not a blank of its own beside its pieces"


@pytest.mark.parametrize("desc", ["1145 x 210 x 12 mm", "1145X210X12MM", "1145 × 210 × 12 mm",
                                  "1145mm x 210mm x 12mm"])
def test_a_pure_size_is_read_however_it_is_spaced(desc):
    assert d._PURE_SIZE_ROW.match(desc)


@pytest.mark.parametrize("desc", ["25.00 x 25.00 x 1.50mm TUBE 1000", "626 x 626",
                                  "18mm MDF, 626 x 626", "EDGING, L: 1979mm", ""])
def test_anything_more_or_less_than_a_size_is_not(desc):
    assert not d._PURE_SIZE_ROW.match(desc)
