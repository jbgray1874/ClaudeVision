r"""
test_the_size_band_reads_the_largest_fabricated_part.py

THE BAND MUST FOLLOW THE BIGGEST THING WE MAKE, NOT THE SMALLEST THING WE BUY.

Assemble/pack and P.Coat throughput are size-banded off the job's largest FABRICATED part
(_apply_size_banded_throughput_by_area). On 11762-02 the wrong part set the band, and two
gates in one loop caused it:

  * stock_form "" was treated as sheet, so a bought-in VINYL graphic with a cutter DXF
    (858 x 72 = 0.0618 m2) voted as a fabricated panel; and
  * "stated_weight" was omitted from the sheet vocabulary, so the 1009 x 364 steel shelf
    (0.367 m2), routed by weight, never entered the max.

The band followed the 0.0618 m2 graphic -> B -> Assemble/pack 30/hr, where the 0.367 m2 shelf
is C -> 20/hr. Pack was ~50% too fast and silently under-costed. P.Coat did NOT move, because
THROUGHPUT_SIZE_BANDS gives it 319/hr for B, C and D alike -- which is exactly why the run
looked like "powder fine, pack light".

The selection is now _largest_fabricated_part_area(parts) -> (area_m2, part_number): only a
part we make votes (bought_in_policy keeps purchased lines out), only through a stock form we
recognise (one vocabulary shared with the Sheet Steel nest routing), and "" is not a vote.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                     # noqa: E402
import bought_in_policy as bip                                    # noqa: E402
from wb_populate import (                                         # noqa: E402
    _largest_fabricated_part_area as largest,
    _FABRICATED_SHEET_STOCK_FORMS as SHEET_FORMS,
)


def _steel_shelf(pn="11762-02-02M", l=1009.49, w=363.91, form="stated_weight"):
    """The shelf as the summary carries it: steel, routed by weight, with a measured blank."""
    return {"part_number": pn, "normalized_material": "MILD STEEL",
            "material_estimate": {"stock_form": form,
                                  "blank_length_mm": l, "blank_width_mm": w}}


def _vinyl_graphic(pn="11762-02-03G", l=858.0, w=72.0):
    """The graphic: bought-in, VINYL, with a cutter DXF blank but empty stock form."""
    return {"part_number": pn, "normalized_material": "VINYL",
            "material_family": "bought_in",
            "material_estimate": {"stock_form": "",
                                  "blank_length_mm": l, "blank_width_mm": w}}


# ── the guard the contract asks for ─────────────────────────────────────────────────
def test_a_steel_shelf_beside_a_vinyl_dxf_bands_on_the_steel():
    """0.37 m2 steel blank + 0.06 m2 vinyl DXF -> the STEEL wins, and it is named."""
    assert bip.is_bought_in(_vinyl_graphic()) is True, "fixture must be bought-in to test the gate"
    assert bip.is_bought_in(_steel_shelf()) is False, "the shelf is fabricated, not purchased"
    area, pn = largest([_vinyl_graphic(), _steel_shelf()])
    assert pn == "11762-02-02M", "the band followed the vinyl graphic, not the steel shelf"
    assert area == pytest.approx(0.3673, abs=1e-3)


def test_order_does_not_matter():
    """max() over the list, so the shelf wins whether it is read first or last."""
    a1, p1 = largest([_steel_shelf(), _vinyl_graphic()])
    a2, p2 = largest([_vinyl_graphic(), _steel_shelf()])
    assert p1 == p2 == "11762-02-02M"
    assert a1 == a2 == pytest.approx(0.3674, abs=1e-3)


# ── gate 1: "" is not a vote ────────────────────────────────────────────────────────
def test_an_empty_stock_form_does_not_vote_even_when_not_bought_in():
    """A part with an unknown stock form and no bought-in signal still must not set a band:
    "" is not sheet. Otherwise any DXF blank with no costed form drives pack and coat speed."""
    unknown = {"part_number": "MYSTERY", "normalized_material": "SOMETHING",
               "material_estimate": {"stock_form": "",
                                     "blank_length_mm": 900, "blank_width_mm": 900}}
    assert bip.is_bought_in(unknown) is False
    area, pn = largest([unknown])
    assert (area, pn) == (0.0, None), '"" was read as sheet again'


def test_empty_is_not_in_the_fabricated_vocabulary():
    assert "" not in SHEET_FORMS
    assert "stated_weight" in SHEET_FORMS, "the weight-routed steel form must count"
    assert {"sheet", "plate", "board"} <= SHEET_FORMS


# ── gate 2: stated_weight steel counts ──────────────────────────────────────────────
def test_steel_routed_by_weight_is_counted():
    """The form the shelf was dropped on. It is steel we cut; it must vote."""
    area, pn = largest([_steel_shelf(form="stated_weight")])
    assert pn == "11762-02-02M" and area == pytest.approx(0.3673, abs=1e-3)


def test_a_plain_sheet_still_counts():
    area, pn = largest([_steel_shelf(form="sheet")])
    assert pn == "11762-02-02M" and area == pytest.approx(0.3673, abs=1e-3)


# ── bought-in never votes, whatever form it carries ─────────────────────────────────
def test_a_bought_in_part_with_a_sheet_form_still_does_not_vote():
    """The make/buy authority wins over the stock form: a purchased panel is not sized here."""
    bought = {"part_number": "BI-PANEL", "normalized_material": "MILD STEEL",
              "material_family": "bought_in",
              "material_estimate": {"stock_form": "sheet",
                                    "blank_length_mm": 2000, "blank_width_mm": 1000}}
    assert bip.is_bought_in(bought) is True
    assert largest([bought]) == (0.0, None)


# ── wire/bar path is unchanged ──────────────────────────────────────────────────────
def test_a_wire_part_contributes_its_cylinder_area():
    wire = {"part_number": "W1", "normalized_material": "MILD STEEL",
            "material_estimate": {"stock_form": "wire", "gauge_mm": 6, "length_mm": 1000}}
    area, pn = largest([wire])
    assert pn == "W1" and area == pytest.approx(3.14159265 * 0.006 * 1.0, abs=1e-6)


def test_no_qualifying_part_returns_zero_and_none():
    assert largest([]) == (0.0, None)
    assert largest([_vinyl_graphic()]) == (0.0, None), "a lone bought-in must not set a band"


# ── the money story: the band the shelf lands in, and why P.Coat did not move ───────
def test_the_labour_block_actually_calls_the_helper_at_the_band_site():
    """THE PAIR-SETTLEMENT MISS, GUARDED. A helper tested in isolation proves nothing if the
    labour block does not call it -- the suite goes green while the live run still bands on the
    wrong part. Assert, from the source, that wb_populate CALLS _largest_fabricated_part_area
    and that the band pick reads the variable it returns, so an edit that orphans the helper
    fails here rather than on a job.
    """
    import ast
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    called = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_largest_fabricated_part_area"
                 for n in ast.walk(tree))
    assert called, "_largest_fabricated_part_area is defined but never called -- band site orphaned"
    # the band pick must read the SAME name the helper's return is bound to
    body = ast.unparse(tree)
    assert "_max_part_area_m2, _max_part_area_pn = _largest_fabricated_part_area(" in body, (
        "the helper's return is not bound to the names the band pick reads")
    assert "_THROUGHPUT_SIZE_BANDS.get(wb_op" in body and "_max_part_area_m2 > 0" in body, (
        "the band pick no longer reads _max_part_area_m2 -- the helper's answer is unused")


def test_the_shelf_lands_in_band_c_and_only_pack_moves():
    """0.367 m2 is band C by config.THROUGHPUT_AREA_EDGES. Pack differs B(30) vs C(20); P.Coat
    is 319 across B/C/D, so the mix-up moved pack and left P.Coat untouched -- the exact shape
    of the scorecard."""
    e1, e2, e3 = config.THROUGHPUT_AREA_EDGES
    a = 0.3673
    band = "A" if a < e1 else "B" if a < e2 else "C" if a < e3 else "D"
    assert band == "C", "the shelf must fall in band C, not the graphic's band B"
    pack = config.THROUGHPUT_SIZE_BANDS["Assemble/pack (Metal)"]
    pcoat = config.THROUGHPUT_SIZE_BANDS["P.Coat"]
    assert pack["B"] != pack["C"], "if pack B and C were equal the bug would have hidden here too"
    assert pcoat["B"] == pcoat["C"] == pcoat["D"], "P.Coat is flat across bands; it never moved"
