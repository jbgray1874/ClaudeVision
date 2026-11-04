"""A board keeps its grade and its décor in the price, or the line says they are not in it (D-693).

12693-01-04J LARGE TOP INSERT. Its own sheet prints MATERIAL: MRMDF and COLOUR: EGGER: U999 ST2:
a moisture-resistant MDF in Egger's décor U999, texture ST2. Its pieces (1145 x 1145 x 18 and
three 12 mm pieces, D-688) were priced from a generic 18 mm MDF sheet at £38.49. A reviewer: "A
generic £38.49 MDF sheet rate does not establish that the required moisture-resistant board and
surface specification are included ... not an assumption that every décor means applied
laminate."

Why: config maps MR MDF to MDF and lists MR, FR and EXT among the qualifier words the
catalogue sheet-rate search ignores, so the grade was gone before SDI Live was asked; and the
product reference was probed one token at a time, so U999 alone matched U999 in any texture.
"MDF" is inside "MRMDF", so even the class-rate question (D-598q) stayed silent.

SDI Live on 4 Nov held no priced MR MDF board (only a 9 mm T&G MR MDF primed row at £0.00), and
U999 only as PM and PT boards, an MFC in U999 ST2 at £0.00 and a U999 ST2 laminate: nothing that
is the specified board.

The rule, generic: a grade the drawing states (MR, FR, exterior, in any common spelling) travels
with the part and must be on the catalogue row; a décor named with its texture (U999 ST2) is the
product only on a row carrying both, and the décor in another texture is a near miss; a row
naming another board is not this one. Where nothing answers to the whole specification, the rung
order is unchanged and the figure is said for what it is: the line keeps the specified board,
names what is NOT in its figure, is provisional, and asks purchasing for the board. No laminate
is invented for a décor, and a board with no grade and no paired décor is priced exactly as
before. Made-up job numbers throughout; the catalogue rows are synthetic, shaped like SDI Live's.
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

import board_specification as bs                                     # noqa: E402
import costed_facts as cf                                             # noqa: E402
import estimator as e                                                 # noqa: E402
import product_reference as pr                                        # noqa: E402

DECOR = "EGGER U999 ST2"

# SDI Live's U999 and MR rows on 4 Nov, as shapes (code, description, cost per).
LIVE_4_NOV = [
    ("BONDED MDF 029", "18mm MDF 3050 x 1220mm U999 PM Black 1 side, white balancer", 250.00),
    ("BONDED MDF 031", "2440 x 1220 x 18mm Eco Board bonded Egger U999 PM Both Sides", 307.34),
    ("BONDED MDF 058", "2745 x 1220 x 18mm MDF Egger U999 PT Black BOTH sides", 325.00),
    ("MFMDF033", "19mm 2800 x 2070 Egger U999 PT Black Top Matt", 124.00),
    ("MFC025", "18mm MFC 2800 x 2070 Black TexturedU999 ST2 Egger", 0.00),
    ("LAMINATE135", "3050 x 1310 x 0.8mm - Egger U999 ST2 Black Textured Laminate", 38.70),
    ("MDFS42", "3050 x 1220 x 9mm T&G MR MDF Boards Primed", 0.00),
]
PLAIN_MDF = [("MDF18", "MDF 2440 x 1220 x 18mm", 38.49), ("MDF12", "MDF 2440 x 1220 x 12mm", 30.10)]


class _Cur:
    """SDI Live's query as the resolver asks it: [System cost per] > 0 AND [Description] LIKE ?"""

    def __init__(self, rows):
        self._all, self.rows = rows, []

    def execute(self, sql, params):
        tok = str(params[0]).strip("%").upper()
        self.rows = [r for r in self._all if tok in r[1].upper() and float(r[2]) > 0]

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows):
        self._c = _Cur(rows)

    def cursor(self):
        return self._c

    def close(self):
        pass


def _clear():
    for cache in (e._SHEET_RATE_CACHE, e._SHEET_RATE_ROWS, e._SHEET_RATE_META,
                  e._RESEARCHED_BOARD_RATE_CACHE):
        cache.clear()


@pytest.fixture()
def live(monkeypatch):
    """Point the resolver at a synthetic SDI Live; returns a setter for its rows."""
    import config
    held = {"rows": []}
    monkeypatch.setattr(config, "get_connection",
                        lambda timeout=20: _Conn(held["rows"]), raising=False)
    monkeypatch.setattr(e, "market_indication_for", lambda part, material: None)
    _clear()

    def _set(rows):
        _clear()
        held["rows"] = list(rows)
    yield _set
    _clear()


def _piece(pn="12999-01-04J-01", t=18.0, length=1145.0, width=1145.0, qty=1, *,
           printed="MRMDF", colour=DECOR):
    p = {"part_number": pn, "description": "LARGE TOP INSERT", "normalized_material": "MDF",
         "normalized_thickness_mm": t, "quantity": qty,
         "blank_length_mm": length, "blank_width_mm": width,
         "normalized_geometry": {"blank_length_mm": length, "blank_width_mm": width,
                                 "geometry_source": "own_parts_table_size"},
         "textual_operations": ["cnc_routing"]}
    if printed:
        p["material_text_as_printed"] = printed
        p["material_stated"] = printed
    if colour:
        p["colours"] = [colour]
    return p


def _sheet_rate(rows, part, t=18.0, material="MDF"):
    return e._resolve_board_sheet_rate_gbp_per_m2(material, t, part)


# ── reading the specification ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("printed", ["MRMDF", "MR MDF", "18mm MR MDF", "M.R. MDF",
                                     "MOISTURE RESISTANT MDF", "Moisture-Resistant MDF",
                                     "MDF MR"])
def test_a_moisture_resistant_grade_is_read_in_any_common_spelling(printed):
    g = bs.board_grade({"normalized_material": "MDF", "material_stated": printed}, "MDF")
    assert [x["code"] for x in g] == ["MR"], printed


@pytest.mark.parametrize("printed", ["FR MDF", "FRMDF", "FIRE RETARDANT MDF", "F.R. MDF"])
def test_a_fire_retardant_grade_is_read_likewise(printed):
    g = bs.board_grade({"normalized_material": "MDF", "material_stated": printed}, "MDF")
    assert [x["code"] for x in g] == ["FR"], printed


def test_no_grade_is_read_where_none_is_stated_or_the_part_is_not_a_board():
    assert bs.board_grade({"normalized_material": "MDF", "material_stated": "MDF"}, "MDF") == []
    # FR ABS is a plastic's grade; a grade is read only on a board.
    assert bs.board_grade({"normalized_material": "ABS", "material_stated": "FR ABS"}, "ABS") == []
    # Words naming another material say nothing about this board.
    assert bs.board_grade({"normalized_material": "MDF", "materials": ["MDF", "FR ABS"]},
                          "MDF") == []
    # FRAME, EXTRA and MRS are not grades.
    assert bs.grades_in("MDF FRAME EXTRA MRS") == []


def test_the_decor_and_its_texture_are_read_as_one_product():
    part = _piece()
    assert pr.decor_textures(part) == [{"decor": "U999", "texture": "ST2",
                                        "as_printed": DECOR}]
    # Asked by the décor code alone: ST2 alone answers for every décor in ST2, and EGGER for
    # every décor Egger makes. The row the code finds must then carry the texture as well.
    assert pr.reference_probes(part) == ["U999"]


def test_a_reference_with_no_texture_is_probed_as_before():
    ref = {"colours": ["UNILIN MINNESOTA OAK WARM NATURAL 0H440 MINNESOTA OAK (Z5L)"]}
    assert pr.decor_textures(ref) == []
    assert pr.reference_probes(ref) == ["0H440", "Z5L", "MINNESOTA", "UNILIN", "OAK"]
    assert pr.decor_textures({"product_reference": "D4428OV D4428"}) == []


def test_the_specification_is_the_grade_the_decor_and_the_board():
    spec = bs.specification(_piece(), "MDF")
    assert [g["code"] for g in spec["grades"]] == ["MR"]
    assert [(d["decor"], d["texture"]) for d in spec["decors"]] == [("U999", "ST2")]
    assert spec["substrate"] == "MDF"
    assert bs.specified_board(spec, 18) == "18 mm MRMDF, EGGER U999 ST2"
    assert bs.specification(_piece(printed=None, colour=None), "MDF") is None


# ── judging a catalogue row ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("desc", ["MR MDF 2440 x 1220 x 18mm", "MRMDF 2440 x 1220 x 18mm",
                                  "M.R. MDF 2440 x 1220 x 18mm",
                                  "Moisture Resistant MDF 2440 x 1220 x 18mm",
                                  "3050 x 1220 x 9mm T&G MR MDF Boards Primed"])
def test_a_row_states_the_grade_in_any_common_spelling(desc):
    spec = bs.specification(_piece(colour=None), "MDF")
    assert bs.judge_row(spec, desc)["grade_ok"], desc


def test_a_row_without_the_grade_or_with_another_is_not_the_graded_board():
    spec = bs.specification(_piece(colour=None), "MDF")
    for desc in ("MDF 2440 x 1220 x 18mm", "FR MDF 2440 x 1220 x 18mm"):
        assert not bs.judge_row(spec, desc)["grade_ok"], desc


def test_u999_st2_is_the_product_and_u999_pm_is_a_near_miss():
    spec = bs.specification(_piece(), "MDF")
    st2 = bs.judge_row(spec, "MR MDF Egger U999 ST2 2440 x 1220 x 18mm")
    assert st2["decor_ok"] and st2["grade_ok"] and st2["substrate_ok"]
    assert bs.judge_row(spec, "MR MDF U999ST2 2440 x 1220 x 18mm")["decor_ok"], "glued"
    pm = bs.judge_row(spec, LIVE_4_NOV[1][1])
    assert pm["decor"] == "U999" and not pm["decor_ok"] and pm["row_texture"] == "PM"
    assert bs.near_miss(spec, LIVE_4_NOV[1][1], 18, 18) == "U999 in PM, not ST2; not MR"
    # Whole words: TexturedU999 is not U999, and ST22 is not ST2.
    assert bs.judge_row(spec, LIVE_4_NOV[4][1])["decor"] is None
    assert not bs.judge_row(spec, "MR MDF U999 ST22 2440 x 1220 x 18mm")["decor_ok"]
    # The décor on another board is not this board.
    mfc = bs.judge_row(spec, "MR MFC U999 ST2 2800 x 2070 x 18mm")
    assert mfc["decor_ok"] and not mfc["substrate_ok"]


# ── the catalogue search ─────────────────────────────────────────────────────────────────

def test_the_mr_grade_is_required_of_the_row_that_prices_it(live):
    live(PLAIN_MDF + [("MRMDF18", "MR MDF 2440 x 1220 x 18mm", 45.00)])
    got = _sheet_rate(None, _piece(colour=None))
    assert [r["part_code"] for r in got["rows"]] == ["MRMDF18"]
    assert got["specification_match"] is True and got["specification_missing"] == []
    assert abs(got["rate_gbp_per_m2"] - 45.00 / (2.44 * 1.22)) < 0.01


def test_a_glued_mrmdf_row_is_read(live):
    live(PLAIN_MDF + [("MRMDF18", "MRMDF 2440 x 1220 x 18mm", 45.00)])
    got = _sheet_rate(None, _piece(colour=None))
    assert [r["part_code"] for r in got["rows"]] == ["MRMDF18"]


def test_with_no_mr_row_the_plain_rate_is_carried_and_the_grade_is_said_missing(live):
    live(PLAIN_MDF)
    got = _sheet_rate(None, _piece(colour=None))
    assert [r["part_code"] for r in got["rows"]] == ["MDF18"]
    assert got["specification_match"] is False
    assert [m["code"] for m in got["specification_missing"]] == ["MR"]


def test_u999_st2_is_found_and_u999_pm_is_not_called_the_product(live):
    exact = ("MRU999", "MR MDF Egger U999 ST2 2440 x 1220 x 18mm", 150.00)  # above the plain cap
    pm = ("U999PM", "MR MDF Egger U999 PM 2440 x 1220 x 18mm", 50.00)
    live(PLAIN_MDF + [pm, exact])
    got = _sheet_rate(None, _piece())
    assert [r["part_code"] for r in got["rows"]] == ["MRU999"], "the exact board, at its price"
    assert got["product_reference_match"] is True and got["specification_match"] is True

    live(PLAIN_MDF + [pm])
    got = _sheet_rate(None, _piece())
    # PM is not ST2: not the product, and not a plain member of the family either, though it
    # is MR and under the plain-stock cap. The class answers, and the gap is said.
    assert [r["part_code"] for r in got["rows"]] == ["MDF18"]
    assert got["product_reference_match"] is False
    assert [m["part"] for m in got["specification_missing"]] == ["grade", "decor", "texture"]
    assert any(n.startswith("U999PM") and "U999 in PM, not ST2" in n for n in got["near_misses"])


def test_the_cached_second_piece_says_what_the_first_said(live):
    live(LIVE_4_NOV + PLAIN_MDF)
    first = _sheet_rate(None, _piece("12999-01-04J-02", 12.0, 1145, 210), t=12.0)
    second = _sheet_rate(None, _piece("12999-01-04J-03", 12.0, 725, 210), t=12.0)
    assert "cached" in second["basis"]
    for k in ("material_token", "product_reference_match", "specification_missing"):
        assert second[k] == first[k], k
    assert second["product_reference_match"] is False


# ── the 04J case: nothing in SDI Live is the specified board ────────────────────────────────

def test_nothing_matches_so_the_gap_is_stated_on_the_line(live):
    live(LIVE_4_NOV + PLAIN_MDF)
    part = _piece()
    r = e.estimate_part(part, job_quantity=1)
    me = r["material_estimate"]
    # The rung order is unchanged: SDI Live's MDF row carries the figure ...
    assert me["cost_method"] == "sheet_rate_live_udef"
    assert me["sheet_price_gbp"] == pytest.approx(38.49, abs=0.01)
    assert me["catalogue_product_match"] is False
    # ... the specified material stays on the line ...
    assert me["specified_board"] == "18 mm MRMDF, EGGER U999 ST2"
    assert part["material_text_as_printed"] == "MRMDF"
    # ... and what is NOT in the figure is said, part by part.
    assert me["specification_not_in_price"] == [
        "the MR (moisture resistant) grade", "the U999 décor", "the ST2 texture"]
    assert "specification_not_in_price" in me["reliability_flags"]
    assert "NOT in this figure" in me["note"]
    flag = next(f for f in r["review_flags"]
                if str(f).startswith("SPECIFICATION NOT IN THE PRICE"))
    assert "18 mm MRMDF, EGGER U999 ST2" in flag and "MDF18" in flag
    q = [x for x in r["manufacturing_questions"]
         if x.get("subject") == "board_specification_not_in_price"]
    assert len(q) == 1 and q[0]["action"].startswith("Purchasing: price 18 mm MRMDF, EGGER U999")
    assert "U999 in PM, not ST2" in q[0]["action"] and "U999 in PT, not ST2" in q[0]["action"]
    # Asked once, however many passes cost the part.
    e.estimate_material(part)
    assert len([x for x in part["manufacturing_questions"]
                if x.get("subject") == "board_specification_not_in_price"]) == 1
    # The class-rate question (D-598q) is not asked beside it.
    assert not any(x.get("subject") == "catalogue_class_rate"
                   for x in part["manufacturing_questions"])


def test_the_line_is_provisional_not_firm(live):
    live(LIVE_4_NOV + PLAIN_MDF)
    r = e.estimate_part(_piece(), job_quantity=1)
    o = cf._price_origin(r, "leaf", "other_sheet", 10.0, 10.0, 84, False)
    assert o["firmness"] == cf.INDICATIVE_HOUSE and o["class"] == "board_specification_gap"
    assert "NOT the specified 18 mm MRMDF, EGGER U999 ST2" in o["label"]
    assert "the MR (moisture resistant) grade, the U999 décor and the ST2 texture" in o["label"]
    status = cf.charge_status({"price_origin": o, "charged_ext_gbp": 10.0}, r)
    assert status["status"] == cf.PROVISIONAL


def test_a_board_priced_below_the_catalogue_says_so_too(live):
    """SDI Live holds no MDF at the gauge: the config £/kg rate prices it, and says what it is."""
    live([])
    r = e.estimate_part(_piece("12999-01-04J-02", 12.0, 1145, 210), job_quantity=1)
    me = r["material_estimate"]
    assert me["cost_method"] == "mass_times_price_per_kg" and me["cost_per_part_gbp"] > 0
    assert me["specification_not_in_price"][0] == "the MR (moisture resistant) grade"
    assert "the config MDF rate" in me["specification_line_note"]
    assert cf._price_origin(r, "leaf", "other_sheet", 5.0, 5.0, 85, False)["firmness"] \
        == cf.INDICATIVE_HOUSE


def test_no_laminate_is_invented_for_a_decor(live):
    """A décor is a stated requirement, not a construction: plain MRMDF named in U999 ST2 is
    not promoted to a faced board, and the faced-board builder does not run."""
    live(LIVE_4_NOV + PLAIN_MDF)
    part = _piece()
    me = e.estimate_part(part, job_quantity=1)["material_estimate"]
    assert "board_construction" not in me and not part.get("_laminate_in_board")
    assert me.get("costing_material_family") == "MDF"
    live([])
    part = _piece()
    me = e.estimate_part(part, job_quantity=1)["material_estimate"]
    assert me["cost_method"] == "mass_times_price_per_kg"
    assert not any("FACED BOARD" in str(f) for f in part.get("review_flags") or [])


def test_a_laminated_board_still_takes_its_facing_in_the_drawn_texture(live):
    """The faced-board builder (D-676) asks for the décor by the same probe: the U999 ST2
    laminate is the drawn décor; a U999 PM laminate would not be."""
    core = [("MDF15", "MDF 2440 x 1220 x 15mm", 34.0)]
    live(LIVE_4_NOV + core)
    panel = dict(_piece(t=16.6, printed=None), normalized_finish="LAMINATED")
    got = e._constructed_faced_board(panel, "MFMDF", 16.6)
    assert got["facing_row"]["part_code"] == "LAMINATE135" and got["facing_is_the_drawn_decor"]
    live([("LAMPM", "3050 x 1310 x 0.8mm - Egger U999 PM Black Laminate", 38.70),
          ("LAMWHITE", "LAMINATE WHITE 3050 x 1300 x 0.8mm", 30.0)] + core)
    got = e._constructed_faced_board(panel, "MFMDF", 16.6)
    # Before D-693 the U999 probe called LAMPM the drawn décor. It may still be the catalogue's
    # median laminate, and is then said to be the class, never the décor.
    assert got["facing_is_the_drawn_decor"] is False


# ── a board with no grade and no décor is priced exactly as before ─────────────────────────

@pytest.mark.parametrize("printed", [None, "MDF"])
def test_plain_mdf_is_unchanged(live, printed):
    rows = PLAIN_MDF + [("MRMDF18", "MR MDF 2440 x 1220 x 18mm", 45.00)]
    live(rows)
    part = _piece(printed=printed, colour=None)
    got = _sheet_rate(None, part)
    old = e._plain_stock_rows(rows, "MDF", 18.0)
    assert [r["part_code"] for r in got["rows"]] == [r["part_code"] for r in old], \
        "every MDF row, as before"
    assert not any(k.startswith("specification") or k == "near_misses" for k in got)
    assert set(e._SHEET_RATE_CACHE) == ({("MDF", 18.0)} if printed is None
                                        else {("MDF", 18.0, "MDF")}), "the same key as before"
    r = e.estimate_part(part, job_quantity=1)
    me = r["material_estimate"]
    assert not any(k.startswith("specification") or k == "specified_board" for k in me)
    assert not any(x.get("subject") == "board_specification_not_in_price"
                   for x in r.get("manufacturing_questions") or [])
    assert cf._price_origin(r, "leaf", "other_sheet", 10.0, 10.0, 84, False)["firmness"] \
        == cf.FIRM


def test_the_fr_grade_is_required_likewise(live):
    live(PLAIN_MDF + [("MRMDF18", "MR MDF 2440 x 1220 x 18mm", 45.00),
                      ("FRMDF18", "FIRE RETARDANT MDF 2440 x 1220 x 18mm", 60.00)])
    part = _piece(printed="FR MDF", colour=None)
    got = _sheet_rate(None, part)
    assert [r["part_code"] for r in got["rows"]] == ["FRMDF18"], "not the MR row, not plain"
    live(PLAIN_MDF + [("MRMDF18", "MR MDF 2440 x 1220 x 18mm", 45.00)])
    r = e.estimate_part(_piece(printed="FR MDF", colour=None), job_quantity=1)
    me = r["material_estimate"]
    assert me["specification_not_in_price"] == ["the FR (fire retardant) grade"]
    assert me["specified_board"] == "18 mm FR MDF"


# ── on the Estimate sheet ─────────────────────────────────────────────────────────────────

def test_the_board_row_on_the_sheet_names_the_specified_board(live, tmp_path, monkeypatch):
    import openpyxl
    import wb_populate
    from test_a_board_part_is_the_pieces_its_own_table_lists import _template
    live(LIVE_4_NOV + PLAIN_MDF)
    parts = [_piece()]
    summary = {"declared_product": "12999-01-04J", "drawing_number": "12999-01-04J",
               "manufacturing_writeup": {"parts": parts}, "document_analysis": {"bom_rows": []},
               "llm_full_extract": {}, "pages": [], "job_folder": str(tmp_path)}
    summary["estimate_summary"] = e.estimate_document(parts, summary=summary)
    summary["part_estimates"] = summary["estimate_summary"]["part_estimates"]
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(_template(tmp_path / "template.xlsx")))
    monkeypatch.setitem(wb_populate.CELL_MAP, "output_dir", str(tmp_path / "out"))
    out = wb_populate.populate_workbook(summary, "D693")
    assert out
    ws = openpyxl.load_workbook(out)["Estimate"]
    c = wb_populate.CELL_MAP["other_sheet"]
    descs = [str(ws.cell(r, c["col_desc"]).value or "")
             for r in range(c["first_row"], c["last_row"] + 1)]
    row = next(d for d in descs if d.startswith("12999-01-04J-01"))
    assert "SPECIFIED 18 mm MRMDF, EGGER U999 ST2" in row
    assert "the MR (moisture resistant) grade, the U999 décor and the ST2 texture are NOT in " \
           "this figure" in row
