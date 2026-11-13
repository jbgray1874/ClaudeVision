"""11896-08-01-GA (10 Nov 2026, 10:31 book): the edging line said 24.659 m a unit and charged 49.318 m.

The line is minted with the product's metres, every banded piece counted. It is then hung under
the part it bands, and the graph multiplies a child's quantity by its parent's count. Two main
panels (SA01 x2 on the GA, one panel each) doubled the metres a second time. Each banded part
now takes the metres of ONE of its pieces, so the graph's own count adds back to the product's
metres. Synthetic records; no job's files.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator                                                         # noqa: E402
import route_compiler as rc                                              # noqa: E402


def _panel(pn, size, qty):
    return {"part_number": pn, "normalized_material": "MFMDF", "_laminate_in_board": True,
            "normalized_thickness_mm": 9.0, "blank_length_mm": size, "blank_width_mm": size,
            "normalized_colour": "WHITE", "quantity": qty,
            "edging_route_words": [f"{size + 2:g} EDGED"]}


def _summary(parts):
    return {"declared_product": "T-GA", "drawing_number": "T-GA",
            "manufacturing_writeup": {"parts": parts},
            "document_analysis": {"bom_rows": []}, "llm_full_extract": {}, "pages": []}


def test_the_line_carries_one_pieces_metres_under_each_part_it_bands():
    parts = [_panel("T-01J", 298.0, 2), _panel("T-02J", 271.0, 1)]
    estimator.estimate_document(parts, summary=_summary(parts))
    line = next(p for p in parts if p.get("_edging_line"))
    assert line["quantity"] == pytest.approx(2 * 1.192 + 1.084), "the product's metres"
    assert line["bom_parents"] == [{"parent": "T-01J", "qty": pytest.approx(1.192)},
                                   {"parent": "T-02J", "qty": pytest.approx(1.084)}]


def test_the_graph_rolls_the_edging_to_the_products_metres_not_twice():
    parts = [{"part_number": "T-GA", "is_assembly_parent": True, "quantity": 1},
             {"part_number": "T-SA01", "is_assembly_parent": True, "quantity": 2},
             {"part_number": "T-01J", "quantity": 2, "normalized_material": "MDF"},
             {"part_number": "EDGE0036", "quantity": 24.659, "is_bought_in": True,
              "unit_of_measure": "m", "_edging_line": True, "_edging_for": ["T-01J"],
              "bom_parent": "T-01J", "bom_parents": [{"parent": "T-01J", "qty": 12.3295}]}]
    rows = [{"part_number": "T-SA01", "quantity": 2, "bom_parent": "T-GA"},
            {"part_number": "T-01J", "quantity": 1, "bom_parent": "T-SA01"}]
    g = rc.build_part_graph(parts, bom_rows=rows, declared_product="T-GA")
    assert g["quantities"]["T-01J"] == pytest.approx(2.0)
    assert g["quantities"]["EDGE0036"] == pytest.approx(24.659)
