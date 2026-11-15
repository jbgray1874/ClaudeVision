"""A SUPPLIER'S CODE PRINTED AGAINST TWO DIFFERENT ITEMS IS TWO LINES (15 Nov 2026).

Two packs print one maker's article number at two item numbers of one parts list: a machine
screw x12 and the thumb nut that goes on it x12. Keyed on the code there was one record, the
screw. The nut had no line and no price; D-508 asked about it and nothing more. JG: "separate
screw and thumb-nut identities despite their shared code", generic, no drawing-number
exceptions.

The first row keeps the printed code. Each later different item becomes
"<printed code>-<its words>", keeps the code the drawing printed, and gets a record of its own
at its own count. A handed pair, a drawing number at two item numbers, and one article listed
by two different tables are left exactly as they were.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import document_builder as db  # noqa: E402
import part_identity as pi  # noqa: E402
from route_compiler import _bom_stated_edges  # noqa: E402

CODE = "MAKER: 0170311700VR"
SCREW = "PC M5 Mushroom Slotted Machine Screw"
NUT = "Thumb Nut - Plastic Round, for a thread size M5"
NUT_ID = "MAKER: 0170311700VR-THUMB-NUT-PLASTIC-ROUND"


def _row(code, desc, item, qty=12, parent="T-010"):
    return {"part_number": code, "description": desc, "quantity": qty,
            "bom_parent": parent, "source_pdf": parent, "bom_item_no": item}


def _table():
    return [_row(CODE, SCREW, "5"), _row(CODE, NUT, "6")]


def test_the_second_item_takes_an_identity_of_its_own_and_the_first_keeps_the_code():
    assert pi.category_code_identities(_table()) == {1: NUT_ID}
    rows = _table()
    assert pi.split_category_code_rows(rows) == 1
    assert rows[0]["part_number"] == CODE and "printed_code" not in rows[0]
    assert rows[1]["part_number"] == NUT_ID and rows[1]["printed_code"] == CODE


def test_the_nut_gets_a_record_at_its_own_count_and_says_why():
    screw = {"part_number": CODE, "description": SCREW}
    for rows in (_table(), (lambda r: (pi.split_category_code_rows(r), r)[1])(_table())):
        made = db.bought_in_rows_without_records(rows, [screw])
        assert [m["part_number"] for m in made] == [NUT_ID]
        nut = made[0]
        assert nut["description"] == NUT and nut["quantity"] == 12
        assert nut["printed_code"] == CODE and nut["page_roles"] == ["bought_in"]
        assert any("ONE CODE, TWO ITEMS" in f and CODE in f for f in nut["review_flags"])


def test_the_graph_holds_two_edges_at_twelve_each_and_no_clash():
    rows = _table()
    pi.split_category_code_rows(rows)
    clashes, rejected = [], []
    known = {"T-010", CODE, NUT_ID}
    edges = _bom_stated_edges(rows, {}, known, rejected, incompatible=clashes)
    got = {(c, p): q for c, p, q in ((e[0], e[1], e[2]) for e in edges)}
    assert got == {(CODE, "T-010"): 12.0, (NUT_ID, "T-010"): 12.0}
    assert clashes == []


def test_the_nut_is_read_as_a_purchase_not_a_part_we_make():
    import part_code_conventions as pcc
    assert pcc.is_supplier_article(NUT_ID)


# ── WHAT IS LEFT ALONE ─────────────────────────────────────────────────────────────────────
def test_a_handed_pair_under_one_code_stays_one_identity():
    rows = [_row(CODE, "SIDE CLIP LH", "1", 2), _row(CODE, "SIDE CLIP RH", "3", 2)]
    assert pi.category_code_identities(rows) == {}


def test_a_drawing_number_at_two_item_numbers_is_left_to_the_relink_rule():
    rows = [_row("3987-GA", "HOOK SECURITY STOP LOCK - 6mm", "4", 9),
            _row("3987-GA", "POWERTOOL PIN", "7", 10)]
    assert pi.category_code_identities(rows) == {}


def test_one_article_listed_by_two_tables_in_different_words_is_not_split():
    rows = [_row(CODE, SCREW, "5", parent="T-010"), _row(CODE, NUT, "2", parent="T-020")]
    assert pi.category_code_identities(rows) == {}


def test_the_same_row_read_twice_is_not_split():
    rows = [_row(CODE, SCREW, "5"), _row(CODE, NUT, "5")]
    assert pi.category_code_identities(rows) == {}


def test_three_rows_two_of_them_the_same_second_item_share_one_identity():
    rows = _table() + [_row(CODE, "Thumb Nut - Plastic Round M5", "9", 4)]
    assert pi.category_code_identities(rows) == {1: NUT_ID, 2: NUT_ID}
