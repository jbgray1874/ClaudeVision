"""tools/check_split_pieces.py proves a split where the money is, and keeps structure apart from
completeness (D-671 review, 4 Nov 2026).

A structurally correct five-panel workbook can still be an incomplete estimate: the boards
unpriced, the bevels' machining unpriced, the edging charged as labour with no material. The
checker passes the structure only where the sizes, quantities, hands and set-ups are justified,
and fails the completeness while any of those remain.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_split_pieces.py"
CODE = "B-01J"
SIZES = [(375, 177.1), (375, 177.1), (270, 177.1), (270, 99.1), (375, 270)]


def _flats(tmp_path):
    import ezdxf
    out = {}
    for n, (a, b) in enumerate(SIZES, start=1):
        pts = [(0, 0), (a, 0), (a, b), (0, b)]
        if n in (1, 2):                       # the two sloping sides, mirror images
            pts = [(0, 0), (a, 0), (a, b), (0, 100.0)] if n == 1 else \
                  [(0, 0), (a, 0), (a, 100.0), (0, b)]
        doc = ezdxf.new()
        doc.modelspace().add_lwpolyline(pts, close=True)
        path = tmp_path / f"{CODE}_PART{n}_10.8mm LAM MDF.DXF"
        doc.saveas(path)
        out[n] = str(path)
    return out


def _record(tmp_path, nest_proven=True, shared=True, bevel=True):
    flats = _flats(tmp_path)
    parts = [{"part_number": CODE, "is_assembly_parent": True,
              "textual_operations": ["edge_banding"],
              "review_flags": ["EDGE BANDING AT THE MINIMUM RUN: ..."]}]
    rows = []
    for n, (a, b) in enumerate(SIZES, start=1):
        pn = f"{CODE}-{n:02d}"
        p = {"part_number": pn, "overall_length_mm": a, "overall_width_mm": b,
             "normalized_thickness_mm": 10.8, "quantity": 1, "dxf_orphan": {"path": flats[n]}}
        if bevel:
            p["bevelled_edges"] = {"angle_deg": 45.0, "length_mm": 2 * (a + b)}
            p["bevel_reading"] = {"taken": True, "angle_deg": 45.0, "edges": 4,
                                  "bevelled_edge_mm": 2 * (a + b),
                                  "evidence_from": f"balloon {n}'s own detail"}
        parts.append(p)
        rows.append({"workbook_row": 150 + n, "laser_nest_id": "CNC Joinery|MFMDF|10.8|bevel 45",
                     "laser_nest_proven": nest_proven,
                     "laser_nest_evidence": "the whole order takes 0.10 of one sheet",
                     **({"setup_share": "1/5"} if shared else {})})
    rec = {"manufacturing_writeup": {"parts": parts}, "workbook_labour": {"rows": rows}}
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(rec))
    return path


def _book(tmp_path, setup_each=3.0, board_price=0.0):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws.cell(10, 3, "Other Sheet Material")
    for n, (a, b) in enumerate(SIZES, start=1):
        r = 11 + n
        for c, v in zip(range(3, 14), [f"{CODE}-{n:02d}  PANEL", 1, a, b, 10.8, 2800, 2070, 40,
                                       0.04, None, board_price]):
            ws.cell(r, c, v)
    ws.cell(18, 3, "Total Material Cost")
    ws.cell(149, 3, "Labour")
    for n in range(1, 6):
        r = 150 + n
        for c, v in zip(range(3, 14), ["CNC Joinery", "10.8mm MFMDF", None, f"{CODE}-{n:02d}",
                                       "CNCJ", 1, 12, 0.13, 64.07, setup_each, 8.5]):
            ws.cell(r, c, v)
    for c, v in zip(range(3, 14), ["Edge Banding", "10.8mm MFMDF", None, CODE, "EDGE", 1, 12,
                                   0.58, 39.03, 30, 22.77]):
        ws.cell(156, c, v)
    path = tmp_path / "book.xlsx"
    wb.save(path)
    return path


def _run(*args):
    p = subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True,
                       text=True, cwd=str(ROOT))
    return p.returncode, p.stdout


ARGS = ["--sizes", ",".join(f"{a}x{b}" for a, b in SIZES), "--qty", "1,1,1,1,1",
        "--handed", "1+2"]


def test_a_right_split_passes_structure_and_still_fails_completeness(tmp_path):
    code, out = _run(_record(tmp_path), _book(tmp_path), CODE, *ARGS)
    assert "structure PASS" in out, out
    assert "estimate INCOMPLETE" in out and code == 1
    assert "no board price" in out
    assert "machining not priced" in out
    assert "no edging material is charged" in out
    assert "edging length not proven" in out
    assert "are mirror outlines" in out
    assert "share ONE set-up" in out and "justified by" in out


def test_a_wrong_size_fails_structure(tmp_path):
    bad = ARGS[:]
    bad[1] = bad[1].replace("270x99.1", "270x120")
    _code, out = _run(_record(tmp_path), _book(tmp_path), CODE, *bad)
    assert "structure NOT PROVEN" in out and "against the drawing's 270 x 120" in out


def test_an_unproven_nest_keeping_a_setup_per_row_is_justified_not_failed(tmp_path):
    _code, out = _run(_record(tmp_path, nest_proven=False, shared=False),
                      _book(tmp_path, setup_each=15.0), CODE, *ARGS)
    assert "unproven, so each of 5 rows keeps its own set-up" in out
    assert "structure PASS" in out


def test_an_unproven_nest_with_a_divided_setup_fails(tmp_path):
    _code, out = _run(_record(tmp_path, nest_proven=False, shared=True), _book(tmp_path),
                      CODE, *ARGS)
    assert "unproven yet its set-up was divided" in out and "structure NOT PROVEN" in out


def test_sizes_not_given_are_not_verified_rather_than_passed(tmp_path):
    _code, out = _run(_record(tmp_path), _book(tmp_path), CODE)
    assert "NOT VERIFIED" in out and "structure NOT PROVEN" in out


def test_identical_sides_are_not_a_handed_pair(tmp_path):
    rec = _record(tmp_path)
    data = json.loads(rec.read_text())
    second = next(p for p in data["manufacturing_writeup"]["parts"]
                  if p["part_number"] == f"{CODE}-02")
    first = next(p for p in data["manufacturing_writeup"]["parts"]
                 if p["part_number"] == f"{CODE}-01")
    second["dxf_orphan"] = dict(first["dxf_orphan"])
    rec.write_text(json.dumps(data))
    _code, out = _run(rec, _book(tmp_path), CODE, *ARGS)
    assert "are identical outlines" in out and "structure NOT PROVEN" in out


def test_an_unsplit_part_is_never_reported_complete(tmp_path):
    rec = tmp_path / "unsplit.json"
    rec.write_text(json.dumps({"manufacturing_writeup": {"parts": [
        {"part_number": CODE, "overall_length_mm": 375, "overall_width_mm": 270}]}}))
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws.cell(10, 3, "Other Sheet Material")
    for c, v in zip(range(3, 14), [f"{CODE}  BOX", 1, 375, 270, 10.8, 2800, 2070, 49, 0.04,
                                   None, 0]):
        ws.cell(12, c, v)                     # under the caption and its header row
    ws.cell(13, 3, "Total Material Cost")
    book = tmp_path / "unsplit.xlsx"
    wb.save(book)
    code, out = _run(rec, book, CODE, *ARGS)
    assert code == 1 and "estimate INCOMPLETE" in out and "own material row has no price" in out


def test_a_cnc_row_that_carries_the_bevel_pass_prices_the_bevel(tmp_path):
    """D-677: the bevel is timed on the CNC row that cuts the panel; the row's record names the
    minutes it includes for each panel, and that is the bevel's machining priced."""
    path = _record(tmp_path)
    rec = json.loads(path.read_text())
    for row in rec["workbook_labour"]["rows"]:
        n = row["workbook_row"] - 150
        row["bevel_pass_min_by_part"] = {f"{CODE}-{n:02d}": 0.86}
    rec["manufacturing_writeup"]["parts"][0]["review_flags"] = [
        "EDGE BANDING TIMED ON ITS PIECES' SHOWING EDGES, PROVISIONAL: 1.4 m"]
    path.write_text(json.dumps(rec))
    book = _book(tmp_path, board_price=4.2)
    import openpyxl
    wb = openpyxl.load_workbook(book)
    ws = wb["Estimate"]
    ws.cell(19, 3, "Bill of Materials")
    for c, v in zip(range(3, 14), ["EDGE23X1ABS  ABS edging", 1.437, None, None, None, None,
                                   None, None, None, None, 0.62]):
        ws.cell(21, c, v)                     # row 20 is the block's header row
    ws.cell(22, 3, "Total Bill of Materials")
    wb.save(book)
    code, out = _run(path, book, CODE, *ARGS)
    assert "machining not priced" not in out, out
    assert "includes " + f"{CODE}-01's bevel pass" in out
    assert "edging length not proven" not in out
    assert "no edging material is charged" not in out
