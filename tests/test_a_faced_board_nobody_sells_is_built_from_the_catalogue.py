"""A faced board nobody sells is priced as the shop builds it, from SDI Live rows (D-676).

JG, 4 Nov 2026: "we need everything priced." 12203-65's five panels are 10.8 mm MDF faced in
Swiss Krono D4428OV. No catalogue row sells that board, so each panel was "FACED BOARD
UNPRICED". SDI Live holds the laminate in that décor (LAMINATE234, 2600 x 1300 x 0.8 mm D4428
OV) and plain MDF cores, so the board is built: one core sheet at the stocked thickness at or
under (drawn - 2 x facing), the facing sheets that cover it on both faces, adhesive and
laminating time. The money is the catalogue's; the faces, adhesive and laminating time are
house allowances, flagged on every line built this way.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as e                                                  # noqa: E402
from test_the_drawings_product_reference_prices_the_line import _Conn  # noqa: E402

DECOR = "SWISS KRONO OAK D4428OV"
ROWS = {
    # The laminate row as SDI Live writes it (D-679): the sides and the gauge apart.
    "D4428": [("LAMINATE234", "2600 x 1300mm 0.8mm Laminate Ref Swiss Krono Oak Natural D4428 OV",
               85.75),
              ("EDGE0056", "35 x 1mm ABS Edging to match Swiss Krono Oak Natural D4428 OV", 0.65)],
    "LAMINATE": [("LAMINATE001", "LAMINATE WHITE 3050 x 1300 x 0.8mm", 40.0),
                 ("LAMINATE234", "2600 x 1300mm 0.8mm Laminate Ref Swiss Krono Oak Natural "
                                 "D4428 OV", 85.75)],
    "MDF": [("MFMDF007", "9mm white matt MF MDF - 2440 x 1220", 25.0),
            ("MDF09", "MDF 2440 x 1220 x 9mm", 18.0), ("MDF12", "MDF 2440 x 1220 x 12mm", 22.0),
            ("MDF18", "MDF 2440 x 1220 x 18mm", 30.0)],
    "ADHESIVE": [("GLUE05", "CONTACT ADHESIVE 5KG TIN", 40.0),
                 ("GLUE04", "CONTACT ADHESIVE 5 LTR TIN", 35.0),
                 ("GLUE06", "CONTACT ADHESIVE SPRAY GUN NOZZLE", 3.0),
                 ("GLUE07", "CONTACT ADHESIVE (EACH)", 9.0),
                 ("PVA01", "PVA WOOD ADHESIVE 5KG", 12.0)],
}


@pytest.fixture()
def catalogue(monkeypatch):
    import config
    monkeypatch.setattr(config, "get_connection", lambda timeout=20: _Conn(ROWS), raising=False)
    e._SHEET_RATE_CACHE.clear()
    e._SHEET_RATE_ROWS.clear()
    yield
    e._SHEET_RATE_CACHE.clear()
    e._SHEET_RATE_ROWS.clear()


def _panel(t=10.8, colour=DECOR):
    return {"part_number": "BOX-01J-05", "description": "BASE PANEL", "normalized_material": "MDF",
            "normalized_finish": "LAMINATED", "normalized_thickness_mm": t, "quantity": 1,
            "blank_length_mm": 375.0, "blank_width_mm": 270.0, "colours": [colour] if colour else [],
            "dxf_source_file": "BOX-01J_PART5_10.8mm LAM MDF_revA.DXF", "dxf_augmented": True,
            "normalized_geometry": {"blank_length_mm": 375.0, "blank_width_mm": 270.0,
                                    "geometry_source": "dxf_flat_pattern"},
            "textual_operations": ["cnc_routing"]}


def test_the_board_is_built_from_a_core_and_the_drawn_decor(catalogue):
    got = e._constructed_faced_board(_panel(), "MFMDF", 10.8)
    assert got["core_row"]["part_code"] == "MDF09", "9 + 2 x 0.8 = 10.6 under the drawn 10.8"
    assert got["facing_row"]["part_code"] == "LAMINATE234"
    assert got["facing_is_the_drawn_decor"] is True
    c = got["components"]
    assert c["core"] == 18.0 and c["facing"] == 2 * 85.75, "one 2600 x 1300 sheet covers a face"
    area = 2.44 * 1.22
    use = e.config.FACED_BOARD_CONSTRUCTION["adhesive_consumption_per_m2_per_face"]
    assert use["unit"] == "kg"
    assert abs(c["adhesive"] - round(2 * area * use["amount"] * 40.0 / 5, 2)) < 0.01, (
        "the contact adhesive's own tin over its own pack, in the consumption's unit: not the "
        "PVA, not the nozzle, not the row with no pack, not the litre tin")
    a = got["adhesive"]
    assert a["part_code"] == "GLUE05" and a["pack_size"] == 5 and a["pack_unit"] == "kg"
    assert a["consumption_per_m2_per_face"] == use["amount"]
    assert abs(a["quantity_used"] - 2 * area * use["amount"]) < 1e-3
    assert a["allowance_gbp"] == c["adhesive"] and a["read_on"] and a["price_date"] is None
    assert "assembly glue is the Glue row" in a["bonds"]
    assert "GLUE05" in got["note"] and "no price date held" in got["note"]
    assert c["laminating"] > 0
    assert got["sheet_gbp"] == round(sum(c.values()), 2)
    assert got["sheet_mm"] == (2440.0, 1220.0)


def test_the_tray_takes_a_12mm_core(catalogue):
    got = e._constructed_faced_board(_panel(t=13.8), "MFMDF", 13.8)
    assert got["core_row"]["part_code"] == "MDF12"


def test_without_the_drawn_code_the_facing_is_said_to_be_the_catalogues_median(catalogue):
    got = e._constructed_faced_board(_panel(colour=""), "MFMDF", 10.8)
    assert got["facing_is_the_drawn_decor"] is False


def test_no_core_in_the_catalogue_leaves_the_board_unpriced(monkeypatch):
    import config
    rows = {k: v for k, v in ROWS.items() if k != "MDF"}
    monkeypatch.setattr(config, "get_connection", lambda timeout=20: _Conn(rows), raising=False)
    e._SHEET_RATE_CACHE.clear()
    assert e._constructed_faced_board(_panel(), "MFMDF", 10.8) is None


def test_the_panel_is_priced_on_the_built_sheet_and_says_how(catalogue):
    r = e.estimate_part(_panel(), job_quantity=1)
    me = r["material_estimate"]
    assert me["cost_method"] == "board_sheet_yield"
    assert me["unit_material_cost_gbp"] and me["unit_material_cost_gbp"] > 0
    assert me["sheet_price_gbp"] == me["board_construction"]["sheet_gbp"]
    assert "board_constructed_provisional" in me["reliability_flags"]
    flag = next(f for f in r["review_flags"] if f.startswith("FACED BOARD BUILT FROM THE CATALOGUE"))
    assert "LAMINATE234" in flag and "house allowances to confirm" in flag
    assert "The facing is the drawn décor." in flag
    assert "BUILT 10.6 mm AGAINST THE DRAWN 10.8 mm" in flag


def test_a_catalogue_row_for_the_finished_board_wins(catalogue, monkeypatch):
    monkeypatch.setattr(e, "_board_sheet_rate", lambda fam, t: (99.0, "bought as one sheet"))
    r = e.estimate_part(_panel(), job_quantity=1)
    assert "board_construction" not in r["material_estimate"]


def test_the_panels_take_the_boxs_decor(tmp_path):
    import test_a_box_exported_as_numbered_parts_is_its_panels as box
    import drawing_job_merge as d
    parts = [{"part_number": box.CODE, "description": "BOX", "quantity": 1,
              "normalized_material": "MDF", "normalized_finish": "LAMINATED",
              "colours": [DECOR]}]
    out = d.augment_summary_with_dxf({"manufacturing_writeup": {"parts": parts}, "pages": []},
                                     box._pack(tmp_path), reestimate=False)
    by = {p["part_number"]: p for p in out["manufacturing_writeup"]["parts"]}
    assert by[f"{box.CODE}-05"]["colours"] == [DECOR]


def test_no_money_is_held_in_config_for_the_board():
    """'We can't hard code prices' (JG, 15 Sep 2026): config holds quantities and time only."""
    import config
    cfg = config.FACED_BOARD_CONSTRUCTION
    assert not any("gbp" in str(k).lower() for k in cfg), cfg


def _with_adhesive_rows(monkeypatch, glue_rows):
    import config
    rows = dict(ROWS, ADHESIVE=glue_rows)
    monkeypatch.setattr(config, "get_connection", lambda timeout=20: _Conn(rows), raising=False)
    e._SHEET_RATE_CACHE.clear()


def test_a_tin_sold_in_another_unit_is_named_not_converted(monkeypatch):
    _with_adhesive_rows(monkeypatch, [("GLUE04", "CONTACT ADHESIVE 5 LTR TIN", 35.0)])
    got = e._constructed_faced_board(_panel(), "MFMDF", 10.8)
    assert "adhesive" not in got["components"] and got["adhesive_priced"] is False
    assert "GLUE04 (5 L)" in got["adhesive_gap"] and "not converted" in got["adhesive_gap"]
    assert "laminate adhesive NOT PRICED" in got["note"]
    r = e.estimate_part(_panel(), job_quantity=1)
    me = r["material_estimate"]
    assert "board_adhesive_unpriced" in me["reliability_flags"]
    flag = next(f for f in r["review_flags"] if f.startswith("FACED BOARD BUILT FROM THE CATALOGUE"))
    assert "material is incomplete" in flag and "GLUE04" in flag
    e._SHEET_RATE_CACHE.clear()


def test_any_catalogue_glue_is_not_the_laminates_adhesive(monkeypatch):
    _with_adhesive_rows(monkeypatch, [("PVA01", "PVA WOOD ADHESIVE 5KG", 12.0)])
    got = e._constructed_faced_board(_panel(), "MFMDF", 10.8)
    assert got["adhesive_priced"] is False
    assert "no SDI Live row is contact adhesive" in got["adhesive_gap"]
    e._SHEET_RATE_CACHE.clear()


def test_a_faced_board_is_never_taken_for_the_core(catalogue):
    got = e._constructed_faced_board(_panel(), "MFMDF", 10.8)
    assert got["core_row"]["part_code"] == "MDF09", "MF MDF carries the word MDF and is faced"


def test_a_core_far_thinner_than_the_drawn_build_is_not_used(monkeypatch):
    """Only 6 mm and 18 mm plain MDF stocked: 6 + 2 x 0.8 = 7.6 mm is not a 10.8 mm board."""
    import config
    rows = dict(ROWS, MDF=[("MDF06", "MDF 2440 x 1220 x 6mm", 14.0),
                           ("MDF18", "MDF 2440 x 1220 x 18mm", 30.0)])
    monkeypatch.setattr(config, "get_connection", lambda timeout=20: _Conn(rows), raising=False)
    e._SHEET_RATE_CACHE.clear()
    e._SHEET_RATE_ROWS.clear()
    assert e._constructed_faced_board(_panel(), "MFMDF", 10.8) is None
    e._SHEET_RATE_CACHE.clear()
    e._SHEET_RATE_ROWS.clear()


def test_the_decor_read_into_normalized_colour_reaches_the_panels():
    """D-679, 12:19 record: the box held its decor in normalized_colour, which neither the
    reference reader nor the pieces' inheritance read."""
    import drawing_job_merge as d
    import product_reference as pr
    box = {"part_number": "12203-65-01J", "normalized_colour": DECOR}
    panel = {"part_number": "12203-65-01J-05", "dxf_minted_piece_of": "12203-65-01J"}
    assert "D4428OV" in pr.product_reference(box)["codes"]
    assert d.inherit_product_onto_pieces([box, panel]) == ["12203-65-01J-05"]
    assert panel["normalized_colour"] == DECOR
    assert panel["product_reference_inherited_from"] == "12203-65-01J"
    assert e._decor_probe(panel) == {"product_reference": "D4428OV D4428"}
