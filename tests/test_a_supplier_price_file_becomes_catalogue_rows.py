"""Reading twenty-four suppliers' price files into one shape, without inventing a price.

WHY THERE IS A TOOL AT ALL. The audit against SDILive measured the hole:

    3. Bought-in catalogue            0 rows          0 priced

Rung 3 of the pricing chain is empty, so every screw, castor, lock and clip falls past it to
text-matched history or to a model — which is why fixings come back at £0 or with a number that
moves between runs. A survey of the twenty-four suppliers SDI actually buys from found no APIs and
two portals; everyone else emails a file. So the fix is a reader, not an integration.

THE TWO THINGS THAT WOULD DO REAL DAMAGE, and neither is about happy paths.

A PRICE THAT IS NOT A NUMBER. "POA", a dash, a blank, "on application" — every one becomes 0.0
through a lazy float() in a try/except, and a zero in this table is a free part on a quote. This
codebase has been here twice already: powder costed at £0.00 on a powder-coated job, and a 60-inch
monitor showing £0.00 in a lookup because the catalogue row had never been priced. Rejected by
name, counted, never coerced.

THE UNIT, WHICH IS THE ONE I GOT WRONG FIRST. Eagle's file has no unit column. Its price column is
headed "Price per m2" and its descriptions read "ABS sheet white textured". The first version fell
back to the description, matched the word "sheet" — the PRODUCT, not the unit — and loaded a
per-square-metre price as a per-sheet price. On a 2500 x 1250 board that is a threefold
under-charge on every line, and nothing downstream would have questioned it. The order is now
explicit column, then the price column's own heading, then the description as a flagged guess.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import supplier_price_list as spl  # noqa: E402


def _xlsx(tmp_path, name, rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    p = tmp_path / name
    wb.save(str(p))
    return p


# A file shaped like Elite's: preamble, our codes, and three rows that must not be priced.
_ELITE = [
    ["ELITE SOURCING SOLUTIONS LTD"], [], ["Net price file - August 2026"], [],
    ["SDI Part No", "Supplier Code", "Description", "UOM", "Net Price", "Pack Qty"],
    ["FIXING1081", "ES-4466", "M6 x 16 socket cap screw, BZP", "each", "0.0412", 100],
    ["FIXING513", "ES-9912", "4.0 x 10.0mm dome rivet, black anodised", "each", "£0.0231", 500],
    ["VINYL76", "ES-7781", "Adhesive cable clip", "each", "POA", 250],
    ["FIXING41", "ES-2210", "M6x16.0mm button head screw BZP", "each", "0.00", 100],
    [None, None, None, None, None, None],
    ["LOCK22", "ES-3311", "Cam lock 20mm, keyed alike", "each", "3.85", 1],
]

# Shaped like Eagle's: no unit column, the unit lives in the price heading, "sheet" is the product.
_EAGLE = [
    ["Eagle Plastics Ltd — ABS / HIPS schedule"], ["Effective 01/09/2026"], [],
    ["Product Code", "Product Description", "Thickness", "Sheet Length", "Sheet Width",
     "Price per m2", "Valid From"],
    ["ABS-1.5-WH", "ABS sheet white textured", "1.5mm", "2500", "1250", "8.42", "01/09/2026"],
    ["HIPS-2.0-BK", "HIPS sheet black", "2mm", "2440", "1220", "11.20", "01/09/2026"],
]


# ── the unit, which is where the money goes ────────────────────────────────────

def test_the_price_heading_beats_the_product_name(tmp_path):
    """THE BUG THIS FILE MOSTLY EXISTS FOR. "Price per m2" over "ABS sheet white"."""
    rows = spl.parse(_xlsx(tmp_path, "eagle.xlsx", _EAGLE), "Eagle Plastics")["rows"]
    assert rows, "nothing parsed"
    assert all(r["unit"] == "m2" for r in rows), (
        "a per-m2 price loaded as per-sheet is a 3x under-charge on a 2500x1250 board")


def test_an_explicit_unit_column_beats_everything():
    assert spl.parse_unit("kg", "steel sheet", "Price per m2")[0] == "kg"


def test_a_unit_taken_from_the_description_says_it_was_a_guess():
    """Flagged, because it is the one thing worth eyeballing before --commit."""
    unit, whence = spl.parse_unit(None, "ABS sheet white textured", "Price")
    assert unit == "sheet"
    assert "GUESS" in whence


def test_a_unit_from_a_column_or_heading_is_not_flagged():
    assert "GUESS" not in spl.parse_unit("each", "", "")[1]
    assert "GUESS" not in spl.parse_unit(None, "", "Net £/kg")[1]


def test_nothing_anywhere_falls_back_to_each_quietly():
    unit, whence = spl.parse_unit(None, "widget", "Price")
    assert unit == "ea" and whence == "assumed"


def test_the_report_shouts_about_a_guessed_unit(tmp_path):
    rows = [["Code", "Description", "Price"], ["A1", "MDF sheet 18mm", "22.40"]]
    out = spl.report(spl.parse(_xlsx(tmp_path, "g.xlsx", rows), "Lawcris"))
    assert "unit guessed" in out
    assert "3x under-charge" in out or "3x under" in out


# ── a price that is not a number ───────────────────────────────────────────────

@pytest.mark.parametrize("value", ["POA", "on application", "TBC", "-", "", "call", "n/a", None])
def test_an_absence_is_refused_rather_than_zeroed(value):
    with pytest.raises(spl.RowRejected):
        spl.parse_price(value)


def test_a_zero_is_refused_because_nothing_is_free():
    with pytest.raises(spl.RowRejected):
        spl.parse_price(0)
    with pytest.raises(spl.RowRejected):
        spl.parse_price("0.00")


@pytest.mark.parametrize("value,want", [
    ("0.0412", 0.0412), ("£0.0231", 0.0231), ("£1,827.60", 1827.60),
    (3.85, 3.85), ("8.42 each", 8.42), (" 12.50 ", 12.50),
])
def test_a_real_price_survives_its_formatting(value, want):
    assert spl.parse_price(value) == pytest.approx(want)


def test_every_rejection_carries_its_reason(tmp_path):
    parsed = spl.parse(_xlsx(tmp_path, "elite.xlsx", _ELITE), "Elite Sourcing")
    assert len(parsed["rejected"]) == 2
    why = " ".join(r["why"] for r in parsed["rejected"])
    assert "POA" in why and "0.0" in why
    assert all(r["text"] for r in parsed["rejected"]), "a reject with no identity is unactionable"


def test_a_blank_spacer_row_is_not_reported_as_a_rejection(tmp_path):
    """Otherwise every file arrives with a reject count nobody can reconcile."""
    parsed = spl.parse(_xlsx(tmp_path, "elite.xlsx", _ELITE), "Elite Sourcing")
    assert len(parsed["rows"]) == 3
    assert len(parsed["rejected"]) == 2                        # not 3 — the blank row is skipped


# ── our code is the one that matches a drawing ─────────────────────────────────

def test_our_part_code_is_preferred_over_the_suppliers(tmp_path):
    """Elite quote on SDI's codes and that is the easiest match in the programme — the drawing
    says FIXING1081 and so does the price file. A "normalise the SKUs" pass would throw it away."""
    rows = spl.parse(_xlsx(tmp_path, "elite.xlsx", _ELITE), "Elite Sourcing")["rows"]
    assert spl.match_key(rows[0]) == "FIXING1081"
    assert rows[0]["their_sku"] == "ES-4466", "the supplier's code is kept beside ours, not instead"


def test_the_suppliers_code_is_used_when_that_is_all_there_is(tmp_path):
    rows = spl.parse(_xlsx(tmp_path, "eagle.xlsx", _EAGLE), "Eagle Plastics")["rows"]
    assert spl.match_key(rows[0]) == "ABS-1.5-WH"
    assert rows[0]["our_sku"] is None


def test_the_report_says_whether_anything_will_match_a_drawing(tmp_path):
    out = spl.report(spl.parse(_xlsx(tmp_path, "elite.xlsx", _ELITE), "Elite Sourcing"))
    assert "OUR part code" in out


# ── finding the header under the letterhead ────────────────────────────────────

def test_the_header_is_found_under_a_letterhead(tmp_path):
    parsed = spl.parse(_xlsx(tmp_path, "elite.xlsx", _ELITE), "Elite Sourcing")
    assert parsed["header_row"] == 4, "row 1 is the company name, not the column headings"


def test_net_price_is_taken_in_preference_to_list_price(tmp_path):
    """Paying list when a net was offered is a silent over-charge on every line."""
    rows = [["Code", "Description", "List Price", "Net Price"],
            ["A1", "Cam lock", "6.20", "3.85"]]
    parsed = spl.parse(_xlsx(tmp_path, "n.xlsx", rows), "X")
    assert parsed["rows"][0]["net_gbp"] == pytest.approx(3.85)


def test_a_file_with_no_price_column_is_refused_with_the_fix(tmp_path):
    rows = [["Code", "Description"], ["A1", "Cam lock"]]
    parsed = spl.parse(_xlsx(tmp_path, "np.xlsx", rows), "X")
    assert parsed["error"] and "--map" in parsed["error"]


def test_a_price_with_no_identity_is_refused(tmp_path):
    """A column of numbers is not a price list."""
    rows = [["Price"], ["3.85"]]
    assert spl.parse(_xlsx(tmp_path, "id.xlsx", rows), "X")["error"]


def test_a_column_override_wins_over_the_sniffer(tmp_path):
    rows = [["A", "B", "C"], ["X1", "Widget", "9.99"]]
    parsed = spl.parse(_xlsx(tmp_path, "o.xlsx", rows), "X",
                       overrides={"their_sku": 0, "description": 1, "net_gbp": 2})
    assert parsed["rows"][0]["net_gbp"] == pytest.approx(9.99)


# ── the shape, and what it must not become ─────────────────────────────────────

def test_every_row_carries_the_whole_canonical_shape(tmp_path):
    rows = spl.parse(_xlsx(tmp_path, "eagle.xlsx", _EAGLE), "Eagle Plastics")["rows"]
    for field in spl.FIELDS:
        assert field in rows[0], f"{field} is missing from the row shape"


def test_sheet_dimensions_and_thickness_survive(tmp_path):
    r = spl.parse(_xlsx(tmp_path, "eagle.xlsx", _EAGLE), "Eagle Plastics")["rows"][0]
    assert r["thickness_mm"] == 1.5 and r["sheet_l_mm"] == 2500 and r["sheet_w_mm"] == 1250


def test_the_source_file_is_recorded_on_every_row(tmp_path):
    """Provenance. When a price is queried in six months the question is which file it came from."""
    rows = spl.parse(_xlsx(tmp_path, "eagle.xlsx", _EAGLE), "Eagle Plastics")["rows"]
    assert all(r["source_file"] == "eagle.xlsx" for r in rows)


def test_the_suppliers_own_date_is_used_when_they_give_one(tmp_path):
    r = spl.parse(_xlsx(tmp_path, "eagle.xlsx", _EAGLE), "Eagle Plastics")["rows"][0]
    assert r["valid_from"] == "2026-09-01", "their effective date, not the day we loaded it"


def test_nothing_is_written_without_being_asked(tmp_path):
    """Dry run by default. A price file loaded by accident moves money on live quotes."""
    src = (_ROOT / "src" / "supplier_price_list.py").read_text(encoding="utf-8")
    at = src.index('ap.add_argument("--commit"')
    assert "default is a dry run" in src[at:at + 200]
    assert "if not args.commit:" in src


def test_the_versioning_is_delegated_rather_than_reimplemented():
    """catalogue_loader already closes the old row and inserts the new one only when the price
    moved. Two implementations of that would diverge on the first edge case."""
    src = (_ROOT / "src" / "supplier_price_list.py").read_text(encoding="utf-8")
    assert "catalogue_loader" in src and "upsert_catalogue" in src
    assert "INSERT INTO" not in src.upper(), "it has grown its own writer"


def test_it_does_not_touch_udef():
    """This loads rung 3. UDEF is the spine and a contract price still beats a list price."""
    src = (_ROOT / "src" / "supplier_price_list.py").read_text(encoding="utf-8")
    assert "UDEF_PARTS_TABLE_FOR_ESTIMATING" not in src
