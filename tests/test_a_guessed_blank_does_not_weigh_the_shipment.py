"""The shipment is weighed on the blanks the material was charged on (D-721).

11908-22-GA, 5 Nov 2026: the packing calculation weighed every panel of an oak-laminated MDF
tray at 400 x 350 x 9 mm, 4.73 kg, while the workbook costed each panel at its own DXF size and
the GA states 1.419 kg. Two faults: the record's blank was the last-resort "largest numbers in
the document text" (400 from a border note's "400 GRIT"), and the GA's weight was refused
because the job is declared "11908-22-GA" and the sheet prints "11908-22 GA".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import commercial_lines as cl
from size_reading import stated_product_weight_kg


def _panel(pn, l, w, per):
    return {"part_number": pn, "quantity": per, "normalized_material": "MDF",
            "normalized_thickness_mm": 9.0,
            "blank_length_mm": 400.0, "blank_width_mm": 350.0,
            "blank_length_mm_source": "document_text_largest_numbers",
            "material_estimate": {"blank_length_mm": l, "blank_width_mm": w}}


def _tray():
    return [_panel("T-01J", 340, 290, 1), _panel("T-02J", 350, 28, 2),
            _panel("T-03J", 300, 28, 2)]


def test_each_panel_is_weighed_at_the_blank_it_was_costed_on():
    order = cl.describe_order(_tray(), 1)
    sizes = {p["part_number"]: (p["length_mm"], p["width_mm"]) for p in order["counted_parts"]}
    assert sizes == {"T-01J": (340, 290), "T-02J": (350, 28), "T-03J": (300, 28)}
    assert all(p["blank_from"] == "the blank its material was costed on"
               for p in order["counted_parts"])
    assert order["unit_weight_kg"] < 1.0, "MDF at 9 mm, not five 400 x 350 sheets"


def test_a_measured_blank_on_the_record_is_kept():
    part = _panel("T-01J", 340, 290, 1)
    part["blank_length_mm_source"] = "dxf"
    order = cl.describe_order([part], 1)
    assert (order["counted_parts"][0]["length_mm"], order["counted_parts"][0]["width_mm"]) \
        == (400.0, 350.0)


def _pages():
    return [{"page_number": 1, "pdfplumber_text": "EDITIONS VM TRAY 11908-22 GA WEIGHT: 1419g"},
            {"page_number": 2, "pdfplumber_text": "11908-22-01J WEIGHT: 1085g"}]


def test_the_ga_weight_belongs_to_the_product_however_its_number_is_joined():
    got = stated_product_weight_kg({"declared_product": "11908-22-GA", "pages": _pages()})
    assert got["kg"] == 1.419 and got["verified"] is True


def test_the_envelope_matches_the_product_however_its_number_is_joined():
    env = cl.product_envelope(
        {"declared_product": "11908-22-GA"},
        [{"part_number": "11908-22 GA",
          "product_envelope_mm": {"length": 350, "width": 300, "height": 30}}])
    assert env and env["length"] == 350 and env["of"] == "11908-22 GA"
