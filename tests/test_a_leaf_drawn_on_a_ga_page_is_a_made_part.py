"""A leaf drawn on a page of the GA's own PDF is a made part on the quote (D-668).

12203-66-GA's 20:48 quote: the three laminated MDF panels are each drawn on a page of the
GA's own PDF, so each page's role read "assembly". The canonical graph classed every panel
a leaf and the workbook costed all three, yet the customer's walkthrough said "We concluded
0 parts SDI makes (0 pieces a unit) and 1 bought in" and "No made parts — every line is
bought in." The quote's assembly test fell through to the page role although the graph had
spoken. The page's role decides only where the graph said nothing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import quote_story as qs  # noqa: E402


def _panel(code, qty, **extra):
    rec = {"part_number": code, "description": "TABLE TOP TRAY - PANEL", "quantity": qty,
           "normalized_material": "MDF", "normalized_thickness_mm": 13.8,
           "page_roles": ["assembly"]}
    rec.update(extra)
    return rec


def test_a_leaf_on_an_assembly_page_is_not_an_assembly():
    assert not qs._is_assembly(_panel("12203-66-01J", 2, _canonical_kind="leaf"))


def test_the_graphs_assembly_word_still_stands():
    assert qs._is_assembly(_panel("12203-66-GA", 1, _canonical_kind="assembly"))


def test_a_costed_blank_is_a_made_parts_where_the_graph_said_nothing():
    rec = _panel("12203-66-02J", 2, material_estimate={"blank_length_mm": 375.0,
                                                       "blank_width_mm": 49.0})
    assert not qs._is_assembly(rec)


def test_with_no_graph_word_and_no_blank_the_page_role_still_decides():
    assert qs._is_assembly(_panel("X-SUB", 1))


def test_the_tray_quote_counts_its_five_made_pieces():
    parts = [_panel("12203-66-01J", 2, _canonical_kind="leaf"),
             _panel("12203-66-02J", 2, _canonical_kind="leaf"),
             _panel("12203-66-03J", 1, _canonical_kind="leaf"),
             {"part_number": "FIXING405", "description": "6.4mm DIA BUMPON TRANSPARENT",
              "quantity": 4, "is_bought_in": True, "_canonical_kind": "bought_in",
              "page_roles": ["assembly", "bought_in"]},
             {"part_number": "12203-66-GA", "description": "TABLETOP TRAY", "quantity": 1,
              "_canonical_kind": "assembly", "page_roles": ["assembly"]}]
    facts = qs.job_facts({}, parts, 1)
    assert len(facts["made"]) == 3
    assert facts["made_pieces"] == 5
    assert len(facts["bought"]) == 1
    assert facts["lines"] == 4
    assert list(facts["by_material"]) == ["MDF 13.8 mm"]


def test_a_boards_initials_stay_capitals():
    assert qs._material_name({"normalized_material": "MDF"}) == "MDF"
    assert qs._material_name({"normalized_material": "MILD_STEEL"}) == "Mild Steel"
    assert qs._material_name({"normalized_material": "OAK VENEERED MFMDF"}) == "Oak Veneered MFMDF"
    assert qs._name_case("MDF", lower=True) == "MDF"
    assert qs._name_case("STAINLESS STEEL", lower=True) == "stainless steel"
