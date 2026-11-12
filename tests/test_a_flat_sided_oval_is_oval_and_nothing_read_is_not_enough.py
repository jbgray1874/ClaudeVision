"""D-594: a flat-sided oval is read as an oval; an estimate nothing was read for is not enough.

A hook-in bar's sheet names its tube "30x15x1.5MM TH'K FSO TUBE" — FSO is a flat-sided oval —
and the a x b x t reading alone cannot tell it from a rectangle, so it would have been weighed
and priced as 30 x 15 RHS. The same pack's drawing page carries no text layer: read without
the image reading, nothing came back, and the record said "Data sufficiency OK" and
"every required line is priced or ruled" — true only because there were no lines.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from section_profile import detect_section_stock, section_kg_per_m  # noqa: E402


# ── a named oval is an oval ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["30x15x1.5MM TH'K FSO TUBE (AS SPEC)", "30X15X1.5 FSO",
                                  "30X15X1.5 F.S.O.", "40 X 20 X 1.5 FLAT SIDED OVAL TUBE",
                                  "40 x 20 x 1.5 flat-sided oval tube"])
def test_a_flat_sided_oval_reads_as_an_oval_and_says_flat_sided(text):
    got = detect_section_stock(text)
    assert got and got["profile_form"] == "OVAL"
    assert got["oval_shape"] == "flat_sided"


def test_the_hook_bars_tube_keeps_its_size():
    got = detect_section_stock("30x15x1.5MM TH'K FSO TUBE (AS SPEC)")
    assert (got["a"], got["b"], got["t"]) == (15.0, 30.0, 1.5)


def test_a_plain_oval_is_an_oval_without_the_flat_sided_mark():
    got = detect_section_stock("40 x 20 x 2 OVAL TUBE 900")
    assert got["profile_form"] == "OVAL" and "oval_shape" not in got
    assert got["length_mm"] == 900.0


@pytest.mark.parametrize("text", ["30 x 15 x 1.5 RHS", "PROFSOME 30x15x1.5 TUBE"])
def test_a_rectangle_stays_a_rectangle(text):
    assert detect_section_stock(text)["profile_form"] == "RHS"


def test_an_oval_word_without_a_section_size_is_not_a_section():
    assert detect_section_stock("FSO 1192 LONG") is None


def test_an_oval_weighs_less_than_the_rectangle_of_the_same_numbers():
    assert section_kg_per_m(15, 30, 1.5, "OVAL") < section_kg_per_m(15, 30, 1.5, "RHS")


def test_the_concept_read_names_fso_an_oval_tube():
    import concept_scan as cs
    assert cs._stock_form_in_words("30 x 15 FSO tube, chrome") == "oval_tube"
    assert cs._stock_form_in_words("F.S.O. 30x15") == "oval_tube"


# ── nothing read is not enough ─────────────────────────────────────────────────────────────

def test_no_line_is_not_every_line_answered():
    from release_gate import assess_release
    got = assess_release([])
    assert got["releasable"] is False and got["nothing_read"] is True
    assert "nothing was read" in got["headline"]
    assert "image reading" in got["what_to_do"]


def test_one_priced_line_is_still_releasable():
    from release_gate import assess_release
    got = assess_release([{"code": "P-1", "description": "PANEL", "price_gbp": 12.5,
                           "required": True}])
    assert got["releasable"] is True and not got.get("nothing_read")
    assert got["headline"] == "every required line is priced or ruled"


def test_an_estimate_with_no_part_is_provisional_and_says_why():
    import estimator as e
    got = e._assess_estimate_data_sufficiency([], [], 0.0)
    assert got["status"] == "provisional" and got["provisional"] is True
    assert "nothing was read" in got["message"]
    assert "no text layer" in got["provisional_reason"]
    assert got["releasable"] is False and got["credible_cost_ratio"] == 0.0


def test_a_bought_in_only_estimate_is_not_nothing_read():
    import estimator as e
    line = {"part_number": "BI-1", "description": "End cap", "extended_total_cost_gbp": 4.0,
            "material_estimate": {"applied_unit_price_gbp": 0.4}}
    got = e._assess_estimate_data_sufficiency([], [line], 4.0)
    assert "nothing was read" not in got["message"]
    assert got["release"].get("nothing_read") is not True


def test_nothing_read_is_declared_so_the_invariant_holds():
    import estimator as e
    from invariants import check_low_confidence_is_declared
    ds = e._assess_estimate_data_sufficiency([], [], 0.0)
    assert check_low_confidence_is_declared({"data_sufficiency": ds}) == []


# ── a flat-sided oval is weighed, coated, bought and priced as one ─────────────────────────

def _stadium_kg_per_m(major, minor, t, density=7850.0):
    import math
    def area(M, m):
        return (M - m) * m + math.pi * (m / 2.0) ** 2
    return (area(major, minor) - area(major - 2 * t, minor - 2 * t)) * 1e-6 * density


def test_a_flat_sided_oval_is_a_stadium_round_its_outside_and_in_its_steel():
    from section_profile import section_form, section_outer_perimeter_mm
    st = detect_section_stock("30x15x1.5MM TH'K FSO TUBE (AS SPEC)")
    form = section_form(st)
    assert st["profile_form"] == "OVAL" and form != "OVAL", "stored OVAL, weighed as a stadium"
    assert section_outer_perimeter_mm(st["a"], st["b"], form) == pytest.approx(77.12, abs=0.05)
    assert section_kg_per_m(st["a"], st["b"], st["t"], form) == pytest.approx(
        _stadium_kg_per_m(30, 15, 1.5), rel=0.01)


def test_a_plain_oval_keeps_the_ellipse():
    from section_profile import section_form, section_outer_perimeter_mm
    st = detect_section_stock("30 x 15 x 1.5 OVAL TUBE")
    assert section_form(st) == "OVAL"
    assert section_outer_perimeter_mm(st["a"], st["b"], section_form(st)) == pytest.approx(72.66, abs=0.05)


def test_the_section_is_said_in_purchasing_words():
    from section_profile import section_description
    assert section_description(detect_section_stock("30x15x1.5MM TH'K FSO TUBE")) == \
        "30 x 15 x 1.5 flat-sided oval (FSO) tube"
    assert section_description(detect_section_stock("40 x 20 x 2 OVAL TUBE")) == "40 x 20 x 2 oval tube"
    assert section_description(detect_section_stock("30 x 15 x 1.5 RHS")) == "30 x 15 x 1.5 RHS"


def _fso_part():
    st = dict(detect_section_stock("30x15x1.5MM TH'K FSO TUBE"), length_mm=1192.0)
    return {"part_number": "T-1", "description": "HOOK BAR TUBE", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "quantity": 1, "section_stock": st}


def test_the_costed_line_weighs_the_stadium_and_is_never_called_rhs():
    import estimator as e
    part = _fso_part()
    me = e.estimate_material(part)
    assert me["stock_estimate"]["kg_per_m"] == pytest.approx(_stadium_kg_per_m(30, 15, 1.5), rel=0.01)
    assert me["unit_material_cost_gbp"] and me["unit_material_cost_gbp"] > 0, "priced, never £0"
    assert me["section_description"] == "30 x 15 x 1.5 flat-sided oval (FSO) tube"
    said = " ".join(part.get("review_flags") or []) + " " + str(me)
    assert "RHS" not in said and "box section" not in said.lower()


def test_no_flat_sided_oval_rate_is_said_on_the_line():
    import estimator as e
    part = _fso_part()
    e.estimate_material(part)
    assert any(f.startswith("no flat-sided oval rate: priced on") and f.rstrip().endswith("FSO price")
               for f in part.get("review_flags") or [])


def test_the_coat_goes_round_the_stadium():
    import estimator as e
    part = _fso_part()
    assert e._section_outer_area_m2(part) == pytest.approx(0.07712 * 1.192, rel=0.01)


def test_a_concept_read_fso_is_weighed_as_a_stadium():
    import concept_scan as cs
    p = {"kind": "fabricated", "name": "30 x 15 x 1.5 FSO tube bar", "material_guess": "mild steel",
         "stock": {"form": "oval tube", "section_mm": [30, 15], "wall_mm": 1.5, "length_mm": 1192}}
    s = cs.resolve_stock(p)
    assert s["profile_form"] == "OVAL" and s["oval_shape"] == "flat_sided"
    assert cs.stock_mass_kg(p, 7850.0, s) == pytest.approx(_stadium_kg_per_m(30, 15, 1.5) * 1.192, rel=0.01)


def test_the_bill_line_says_flat_sided_oval():
    from wb_populate import section_words_on_line
    me = {"section_description": "30 x 15 x 1.5 flat-sided oval (FSO) tube"}
    line = section_words_on_line("T-1  HOOK BAR TUBE", me)
    assert line.endswith("30 x 15 x 1.5 flat-sided oval (FSO) tube")
    assert section_words_on_line("T-1  30X15 OVAL TUBE", me) == "T-1  30X15 OVAL TUBE"
    assert section_words_on_line("P-1  RAIL", {"section_description": "50 x 20 x 2 RHS"}) == "P-1  RAIL"


def test_a_cut_list_row_naming_fso_keeps_the_flat_sided_shape():
    import bom_pipeline as bp
    from part_identity import mint_uncoded_row_identities
    frame = {"part_number": "HB-1", "description": "HOOK BAR - WELDMENT", "page_roles": ["detail"],
             "normalized_material": "MILD STEEL", "quantity": 1}
    rows = [{"part_number": "", "description": "30x15x1.5MM FSO TUBE 1192", "quantity": 1,
             "bom_parent": "HB-1", "bom_parent_known": True}]
    mint_uncoded_row_identities(rows)
    assert bp.apply_stated_cut_list_to_parts([frame], rows) == 1
    ss = frame["section_stock"]
    assert ss["profile_form"] == "OVAL" and ss["oval_shape"] == "flat_sided"
    assert (ss["a"], ss["b"], ss["t"]) == (15.0, 30.0, 1.5)


# ── the member-schedule panel's rows, through the concept stock builder ────────────────────

def _panel_row(**kw):
    row = {"name": "Hook bar tube", "kind": "fabricated", "quantity": 1, "material": "mild steel",
           "form": "oval_tube", "section": "30 x 15", "wall": 1.5, "length": 1192,
           "operations": ["saw"]}
    row.update(kw)
    return row


@pytest.mark.parametrize("kw", [{"note": "FSO tube as spec"}, {"name": "FSO hook bar tube"},
                                {"sighted": "flat-sided oval, chrome"}])
def test_a_panel_row_naming_fso_is_weighed_as_a_stadium(kw):
    import accepted_construction as ac
    import concept_scan as cs
    parts, errors = ac.parts_from_rows([_panel_row(**kw)])
    assert not errors, errors
    s = cs.resolve_stock(parts[0])
    assert s["profile_form"] == "OVAL" and s.get("oval_shape") == "flat_sided"
    assert cs.stock_mass_kg(parts[0], 7850.0, s) == pytest.approx(
        _stadium_kg_per_m(30, 15, 1.5) * 1.192, rel=0.01)


def test_a_plain_oval_tube_row_stays_an_ellipse():
    import accepted_construction as ac
    import concept_scan as cs
    parts, errors = ac.parts_from_rows([_panel_row()])
    assert not errors, errors
    s = cs.resolve_stock(parts[0])
    assert s["profile_form"] == "OVAL" and "oval_shape" not in s
