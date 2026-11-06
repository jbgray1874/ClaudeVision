"""Review of D-379 / D-380 on the 12173-02 Card Spinner: quantity folds and fold settles.

1. THE MODEL'S OTHER HAND. D-379 counted a handed twin with its code when the drawing did not
   list the twin's exact file name. A drawing that lists the hand as "<code> MIR",
   "MIRROR <code>", "Mirror<code>" or by an opposite-hand note made 3 of a pair, and the twin
   sentence was written before the count was tried. Now a hand under any spelling the engine's
   one hand reader knows is listed; the fold needs the drawing's own count (12173-07-2-GA prints
   07-2-02M at items 1 and 3, so 2) or it is asked; and the sentence says what is held.
2. ONE READER, TWO READINGS. bom_tree read one row's 1 and then the table's 2. A reader
   contradicting itself never writes and says so; "outranks" is computed; and the record
   builders read a table's repeated item rows as one total, so the trough's 2 is bom_tree's
   first and only reading.
3. A HAND'S OWN SHEET. settle_mirrored_folds replaced a hand's own sheet fold statement; the
   hand keeps it where the sheet is its own detail sheet, and a difference is asked.
4. CALLOUTS AND A NOTE. Callouts the model confirms beat the note only when the note is the
   de-duplicated angle list; an explicit fold count stands and the callouts are named. The
   callouts are counted off the part's own sheet only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bom_tree                                                       # noqa: E402
import document_builder                                               # noqa: E402
import drawing_job_merge as djm                                       # noqa: E402
import fold_count as fc                                               # noqa: E402
import source_precedence as sp                                        # noqa: E402
from source_connectors.solidworks import (                            # noqa: E402
    NativeBomRow, NativeJob, apply_native_to_pre_estimate)

B = "1234-07-2-02M"
G = "1234-07-2-GA"


# ── 1. the model's other hand ───────────────────────────────────────────────────────────

def _job(parent_qty=None):
    rows = [NativeBomRow(B, 1), NativeBomRow(B + "-H", 1)]
    if parent_qty is not None:
        rows.append(NativeBomRow(G, parent_qty, is_assembly=True))
    return NativeJob(found=True, bom=rows, assembly_pns=[G],
                     hierarchy={G: [(B, 1.0), (B + "-H", 1.0)]})


def _run(hand=None, drawn=None, extra=None, **kw):
    parts = [{"part_number": G, "is_assembly_parent": True},
             {"part_number": B, "quantity": 1, "review_flags": []}]
    if hand:
        parts.append({"part_number": hand, "quantity": 1, "review_flags": []})
    if extra:
        parts[1].update(extra)
    apply_native_to_pre_estimate(parts, _job(), drawn_counts=drawn, **kw)
    return parts


def test_a_hand_listed_under_any_spelling_is_not_counted_twice():
    for hand in (B + " MIR", "MIRROR " + B, "Mirror" + B):
        p = _run(hand)
        assert p[1]["quantity"] + p[2]["quantity"] == 2, hand
        assert not any("other hand" in f for f in p[1]["review_flags"]), hand


def test_a_hand_named_by_its_sheets_note_is_listed():
    parts = [{"part_number": G, "is_assembly_parent": True},
             {"part_number": B, "quantity": 1, "review_flags": []},
             {"part_number": "1234-07-2-09M", "mirror_of": B, "quantity": 1,
              "review_flags": []}]
    apply_native_to_pre_estimate(parts, _job())
    assert parts[1]["quantity"] == 1


def test_the_pair_on_two_item_rows_corroborates_the_fold():
    p = _run(drawn={B: 2})
    assert p[1]["quantity"] == 2
    assert any("counted with this code: 2 per " + G in f for f in p[1]["review_flags"])
    assert not p[1].get("manufacturing_questions")


def test_a_drawing_that_lists_the_code_once_keeps_one_and_asks():
    p = _run(drawn={B: 1})
    assert p[1]["quantity"] == 1
    assert p[1]["quantity_total_per_unit"] == 1
    assert not any("counted with this code" in f for f in p[1]["review_flags"])
    qs = p[1].get("manufacturing_questions") or []
    assert len(qs) == 1 and B + "-H" in qs[0]["issue"] and "confirm the hands" in qs[0]["action"]


def test_a_spelling_no_reader_knows_is_caught_by_the_drawings_count():
    p = _run(B + "-LH", drawn={B: 1})
    assert p[1]["quantity"] + p[2]["quantity"] == 2


def test_without_the_drawings_count_the_twin_folds_as_before():
    p = _run()
    assert p[1]["quantity"] == 2


def test_the_twin_sentence_is_not_said_where_the_count_is_not_held():
    p = _run(extra={"quantity_source": "estimator_confirmed"})
    assert p[1]["quantity"] == 1
    assert not any("counted with this code" in f for f in p[1]["review_flags"])


def test_the_late_pass_sees_a_hand_the_first_pass_already_holds():
    held = [{"part_number": G, "is_assembly_parent": True},
            {"part_number": B + " MIR", "quantity": 1, "solidworks_native": True}]
    missed = [{"part_number": B, "quantity": 1, "review_flags": []}]
    apply_native_to_pre_estimate(missed, _job(), drawn_counts=None,
                                 population=held + missed)
    assert missed[0]["quantity"] == 1


def _row(code, qty, item, table=G):
    return {"part_number": code, "description": "x", "quantity": qty, "bom_item_no": item,
            "source_pdf": table, "bom_parent": table, "source": "BOTH"}


def test_the_drawings_count_is_the_tables_total_per_parent():
    rows = [_row(B, 1, "1"), _row("1234-07-2-01M", 1, "2"), _row(B, 1, "3"), _row(B, 1, "3"),
            _row("1234-03-06M", 8, "2", "1234-03-202"), _row("1234-03-06M", 8, "2", "1234-03-203")]
    got = bom_tree.drawn_counts_by_code(rows)
    assert got[B] == 2 and got["1234-07-2-01M"] == 1 and got["1234-03-06M"] == 8


def test_rows_with_no_table_are_not_added_together():
    rows = [dict(_row(B, 1, "1"), source_pdf=""), dict(_row(B, 1, "3"), source_pdf="")]
    assert [r["quantity"] for r in bom_tree.rows_combined_per_table(rows)] == [1, 1]
    assert B not in bom_tree.drawn_counts_by_code(rows)          # no table, no count


def test_a_code_on_two_unnumbered_rows_of_one_table_is_not_a_count():
    rows = [_row(B, 1, None), _row(B, 1, None)]
    assert B not in bom_tree.drawn_counts_by_code(rows)
    assert _run(drawn=bom_tree.drawn_counts_by_code(rows))[1]["quantity"] == 2   # D-379 fold


# ── 2. one reader, two readings ─────────────────────────────────────────────────────────

def test_a_reader_contradicting_itself_keeps_the_first_and_says_so():
    t = {}
    for v, s in ((1, "solidworks_api"), (1, "bom_tree"), (2, "bom_tree")):
        sp.apply_field(t, "quantity", v, s)
    assert t["quantity"] == 1
    flags = t["review_flags"]
    assert any("bom_tree read both '1' and '2'" in f and "solidworks_api also says" in f
               for f in flags)
    assert not any("although it outranks" in f for f in flags)
    assert t["_self_revisions"]["quantity"] == [{"source": "bom_tree", "from": 1, "to": 2}]


def test_a_lone_reader_is_not_two_sources_of_equal_standing():
    p = {}
    sp.apply_field(p, "quantity", 1, "bom_tree")
    assert sp.apply_field(p, "quantity", 2, "bom_tree") is False
    assert not any("equal standing" in f for f in p["review_flags"])


def test_a_higher_confidence_does_not_let_a_reader_overturn_itself():
    q = {}
    sp.apply_field(q, "normalized_material", "PETG", "dxf_filename", confidence=0.5)
    sp.apply_field(q, "normalized_material", "PETG", "title_block")
    assert sp.apply_field(q, "normalized_material", "ABS", "title_block", confidence=0.9) is False
    assert q["normalized_material"] == "PETG"
    assert any("title_block read both" in f for f in q["review_flags"])


def test_a_reader_that_clears_its_own_stamp_may_correct_itself():
    p = {}
    sp.apply_field(p, "quantity", 3, "bom_tree")
    p["quantity_source"] = ""
    assert sp.apply_field(p, "quantity", 1, "bom_tree") is True
    assert p["quantity"] == 1


def test_one_value_in_two_spellings_is_not_a_contradiction():
    p = {}
    sp.apply_field(p, "normalized_material", "MILD_STEEL", "title_block")
    sp.apply_field(p, "normalized_material", "MILD STEEL", "title_block")
    assert not p.get("review_flags")


def test_outranks_is_said_only_when_it_does():
    weaker = {}
    sp.apply_field(weaker, "quantity", 2, "solidworks_api")
    sp.apply_field(weaker, "quantity", 2, "dxf")
    sp.apply_field(weaker, "quantity", 3, "bom_tree")
    said = [f for f in weaker["review_flags"] if "independent sources say" in f]
    assert said and "although it outranks" not in said[0]
    stronger = {}
    sp.apply_field(stronger, "normalized_material", "PETG", "title_block")
    sp.apply_field(stronger, "normalized_material", "PETG", "dxf_filename")
    sp.apply_field(stronger, "normalized_material", "ABS", "solidworks_api")
    said = [f for f in stronger["review_flags"] if "independent sources say" in f]
    assert said and "although it outranks what is held" in said[0]


def test_the_record_reads_a_tables_pair_once():
    rows = [_row(B, 1, "1"), _row("1234-07-2-01M", 1, "2"), _row(B, 1, "3")]
    parts = document_builder.build_part_index(
        {"document_analysis": {"bom_rows": rows}, "pages": []})
    side = next(p for p in parts if p["part_number"] == B)
    assert side["quantity"] == 2 and side["quantity_source"] == "bom_tree"
    assert not side.get("_displaced") and not side.get("review_flags")


# ── 3. a hand's own sheet ───────────────────────────────────────────────────────────────

_S = {"pages": [{"page_number": 1, "page_role": {"primary_role": "detail"}},
                {"page_number": 15, "page_role": {"primary_role": "assembly"}},
                {"page_number": 16, "page_role": {"primary_role": "detail"}}]}


def _pair(hand_pages, **hand):
    base = {"part_number": "X-02M", "pages": [1], "angles_deg": [90],
            "solidworks_bend_features": 4, "drawing_bend_callouts": 2}
    h = {"part_number": "X-02M-H", "pages": hand_pages,
         "normalized_geometry": {"mirrored_from": "X-02M"}}
    h.update(hand)
    return base, h


def test_a_hand_whose_own_sheet_states_its_folds_keeps_them_and_asks():
    base, hand = _pair([16], fold_count_textual=3)
    assert djm.settle_mirrored_folds([base, hand], _S) == 0
    assert fc.press_brake_folds(hand)["count"] == 3
    qs = hand.get("manufacturing_questions") or []
    assert len(qs) == 1 and "one flat, two readings" in qs[0]["issue"]
    assert "reads 3" in qs[0]["issue"] and "charged 2" in qs[0]["issue"]


def test_a_parts_list_is_not_the_hands_own_sheet():
    base, hand = _pair([15], fold_count_textual=3)
    assert djm.settle_mirrored_folds([base, hand], _S) == 1
    assert fc.press_brake_folds(hand)["count"] == 2


def test_a_sheet_shared_with_the_base_is_the_bases():
    base, hand = _pair([1], angles_deg=[90, 45])
    assert djm.settle_mirrored_folds([base, hand], _S) == 1


def test_an_own_sheet_that_agrees_asks_nothing():
    base, hand = _pair([16], fold_count_textual=2)
    assert djm.settle_mirrored_folds([base, hand], _S) == 0
    assert not hand.get("manufacturing_questions")


def test_without_pages_the_hand_settles_as_d380_ruled():
    base, hand = _pair([16], fold_count_textual=3)
    assert djm.settle_mirrored_folds([base, hand]) == 1


# ── 4. callouts and a note ──────────────────────────────────────────────────────────────

def test_callouts_still_correct_an_angle_list():
    r = fc.press_brake_folds({"angles_deg": [90], "drawing_bend_callouts": 2,
                              "solidworks_bend_features": 4})
    assert (r["count"], r["source"]) == (2, fc.CALLOUTS_AND_MODEL)


def test_an_explicit_fold_count_stands_and_names_the_callouts():
    r = fc.press_brake_folds({"angles_deg": [90], "fold_count_textual": 1,
                              "drawing_bend_callouts": 5, "solidworks_bend_features": 6})
    assert (r["count"], r["source"], r["measured"]) == (1, fc.DRAWING_NOTE, False)
    assert "callouts on its own sheet read 5" in r["disagreement"]
    assert "Confirm" in r["disagreement"]


def test_fold_dimensions_stand_too():
    r = fc.press_brake_folds({"fold_values_mm": [20.0], "drawing_bend_callouts": 3,
                              "solidworks_bend_features": 3})
    assert r["source"] == fc.DRAWING_NOTE and r["count"] == 1


def test_a_measured_charge_the_sheets_callouts_dispute_is_asked():
    r = fc.press_brake_folds({"bend_count_dxf": 2, "drawing_bend_callouts": 3})
    assert r["count"] == 2 and "callouts on its own sheet read 3" in r["disagreement"]
    assert "no confirmation is needed" not in r["disagreement"]


def test_callouts_are_counted_off_the_parts_own_sheet_only():
    parts = [{"part_number": "Y-GA", "pages": [15]},
             {"part_number": "Y-01M", "pages": [1, 15]},
             {"part_number": "Y-02M", "pages": [15]}]
    summary = {"pages": [
        {"page_number": 1, "page_role": {"primary_role": "detail"},
         "pdfplumber_text": "UP 90° R1 DOWN 90° R1"},
        {"page_number": 15, "page_role": {"primary_role": "assembly"},
         "pdfplumber_text": "UP 90° R1 " * 5}]}
    djm.stamp_drawing_bend_callouts(parts, summary)
    assert parts[1]["drawing_bend_callouts"] == 2
    assert "drawing_bend_callouts" not in parts[2]
