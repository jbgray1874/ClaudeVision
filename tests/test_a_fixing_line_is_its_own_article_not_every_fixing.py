"""Each "FIXING" line in a pack that lists them one by one is its own article (11 Nov 2026).

6364-01: the GA's parts list prints four fixings with DWG NO. "FIXING" (wood screws x40, inserts
x4, cap screws x4, Minifix x8); the rear castor plate's own sheet prints its hank bush "FIXING"
x2, and the weight-plate pack's its tek screw "FIXING" x8. Each "FIXING" child stood for every
article under the code, so all six went under the plate (x2) and the pack as well as the GA:
40 wood screws were costed as 120, the hank bush as 6 instead of 4.

A child still stands for every article where the pack names fewer lines than articles (12312's
one "P/P" over nine purchased lines: test_one_category_code_over_many_articles).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import route_compiler as rc                                       # noqa: E402

GA, PLATE, PACK = "7001-01-000", "7001-01-005", "7001-01-015"
TOP = [("PHILIPS PAN HEAD WOOD SCREW no8x12.70mm", 40), ("M6x12mm THREADED INSERT HEADED", 4),
       ("M10x30mm CAP SCREW BZP", 4), ("MINIFIX S100 FIXINGS", 8)]
ON_PLATE = ("M10x16g HANK BUSH", 2)
ON_PACK = ("HEX HEAD TEK SCREW 4.8x31.75mm", 8)


def _fix(desc, qty):
    return {"part_number": "FIXING", "description": desc, "qty": qty, "is_bought_in": True,
            "material_family": "bought_in"}


def _extract():
    bom = [_fix(d, q) for d, q in TOP] + [_fix(*ON_PLATE), _fix(*ON_PACK)]
    bom += [{"part_number": PLATE, "description": "REAR CASTOR PLATE", "qty": 2},
            {"part_number": PACK, "description": "WEIGHT PLATE PACK", "qty": 1}]
    return {"bom": bom, "assemblies": [
        {"part_number": GA, "children": [{"part_number": PLATE, "qty": 2},
                                         {"part_number": PACK, "qty": 1}]
         + [{"part_number": "FIXING", "qty": q} for _d, q in TOP]},
        {"part_number": PLATE, "children": [{"part_number": "FIXING", "qty": 2}]},
        {"part_number": PACK, "children": [{"part_number": "FIXING", "qty": 8}]}]}


def _rows():
    rows = [dict(_fix(d, q), bom_parent=f"{GA} - BOM", quantity=q) for d, q in TOP]
    rows.append(dict(_fix(*ON_PLATE), bom_parent=PLATE, quantity=2))
    rows.append(dict(_fix(*ON_PACK), bom_parent=PACK, quantity=8))
    return rows


def _fixings_under(bom_rows):
    parts = [{"part_number": GA, "is_assembly_parent": True},
             {"part_number": PLATE, "is_assembly_parent": True},
             {"part_number": PACK, "is_assembly_parent": True}]
    g = rc.build_part_graph(parts, _extract(), bom_rows=bom_rows)
    nodes = {n.part_number: n for n in g["nodes"]}
    return {p: {e.part_number: e.qty for e in nodes[p].children if e.part_number.startswith("FIXING")}
            for p in (GA, PLATE, PACK)}


def _check(kids):
    assert len(kids[PLATE]) == 1 and "HANK" in next(iter(kids[PLATE])), kids[PLATE]
    assert list(kids[PLATE].values()) == [2]
    assert len(kids[PACK]) == 1 and "TEK" in next(iter(kids[PACK])), kids[PACK]
    assert list(kids[PACK].values()) == [8]
    assert not any("HANK" in c or "TEK" in c for c in kids[GA])
    wood = next(c for c in kids[GA] if "PHILIPS" in c)
    assert kids[GA][wood] == 40
    assert not any("PHILIPS" in c for c in list(kids[PLATE]) + list(kids[PACK])), \
        "the GA's wood screws are not the plate's or the pack's"


def test_each_fixing_line_takes_the_article_its_own_parts_list_names():
    _check(_fixings_under(_rows()))


def test_without_parts_list_rows_each_line_takes_the_article_at_its_quantity():
    _check(_fixings_under(None))
