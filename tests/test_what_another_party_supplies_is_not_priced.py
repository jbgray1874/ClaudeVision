"""The drawing's own scope note: what another party supplies is listed at £0, not researched.

12312-01-GA Rev B: "display, router and antenna supplied and fitted by Pixel Inspiration UK".
The BOM still lists the Bluefin 49.1" LCD, the Teltonika RUT200 and the puck antenna; priced as
SDI's, the display alone would be a four-figure researched figure on a steel-case job. The case
parts that hold them — the 02M DISPLAY BRACKET, the 05M ROUTER MOUNT PLATE — are SDI's and must
never be caught by the same words.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator                                                     # noqa: E402
from third_party_supply import mark_third_party_supplied, supply_notes  # noqa: E402

NOTE = ("NOTES: 1. ALL DIMENSIONS IN MM. 2. DISPLAY, ROUTER AND ANTENNA SUPPLIED AND "
        "FITTED BY PIXEL INSPIRATION UK. 3. POWDER COAT RAL5005 30% GLOSS.")


def _parts():
    return [
        {"part_number": "20-0129-0365", "description": 'BLUEFIN 49.1" LCD DISPLAY', "page_roles": ["bought_in"]},
        {"part_number": "RUT200", "description": "TELTONIKA RUT200 ROUTER", "page_roles": ["bought_in"]},
        {"part_number": "PUCK", "description": "PUCK ANTENNA", "page_roles": ["bought_in"]},
        {"part_number": "12312-01-02M", "description": "DISPLAY BRACKET"},
        {"part_number": "12312-01-05M", "description": "ROUTER MOUNT PLATE"},
        {"part_number": "FIXING320", "description": "M6 x 15 PEM STUD", "page_roles": ["bought_in"]},
        {"part_number": "LED-TAPE", "description": "LED TAPE 375CM", "page_roles": ["bought_in"]},
    ]


def test_the_note_is_read_with_its_items_and_party():
    notes = supply_notes([NOTE])
    assert len(notes) == 1
    assert notes[0]["party"] == "PIXEL INSPIRATION UK"
    assert set(notes[0]["items"]) == {"DISPLAY", "ROUTER", "ANTENNA"}


def test_the_three_supplied_items_are_marked_and_sdis_parts_are_not():
    parts = _parts()
    marked = mark_third_party_supplied(parts, {"pages": [{"pdfplumber_text": NOTE}]})
    got = {m["part_number"] for m in marked}
    assert got == {"20-0129-0365", "RUT200", "PUCK"}, got
    by = {p["part_number"]: p for p in parts}
    for ours in ("12312-01-02M", "12312-01-05M", "FIXING320", "LED-TAPE"):
        assert not by[ours].get("supplied_by_third_party"), ours


def test_a_supplied_line_costs_nothing_and_asks_no_price(monkeypatch):
    calls = []
    monkeypatch.setattr(estimator, "_resolve_part_system_cost",
                        lambda part: calls.append(part) or {"applied_unit_cost": 999.0, "result": {}})
    p = {"part_number": "20-0129-0365", "description": "BLUEFIN LCD DISPLAY", "quantity": 1,
         "page_roles": ["bought_in"], "supplied_by_third_party": "PIXEL INSPIRATION UK"}
    est = estimator.estimate_part(p, job_quantity=1)
    assert est["unit_total_cost_gbp"] == 0.0 and not calls


def test_it_is_nil_by_design_with_the_party_named():
    import costed_facts as cf
    p = {"part_number": "RUT200", "description": "ROUTER", "supplied_by_third_party": "PIXEL INSPIRATION UK"}
    o = cf._price_origin(p, "bought_in", "bom", 0.0, 0.0, 30, False, row_text="RUT200 ROUTER")
    assert o["firmness"] == cf.NIL and "Pixel Inspiration Uk" in o["label"]


def test_sdi_supplying_it_or_no_note_changes_nothing():
    parts = _parts()
    assert mark_third_party_supplied(parts, {"pages": [{"pdfplumber_text":
                                       "DISPLAY SUPPLIED BY SDI DISPLAYS LTD."}]}) == []
    assert mark_third_party_supplied(_parts(), {"pages": [{"pdfplumber_text": "NOTES: 1. ALL DIMS IN MM."}]}) == []
