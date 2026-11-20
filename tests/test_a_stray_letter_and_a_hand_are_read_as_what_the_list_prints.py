"""A STRAY LETTER IS NOT A NEW PART, AND A HAND IS NOT THE SAME PART (20 Nov 2026).

Both from 12133-00-GA's parts list (reviewer, 20 Nov 2026):

  1. Item 28 prints 12133-04-01M "1130x489 SHELF TOP" x2. The text layer read 12133-04-01ME,
     which went on as a part with no drawing beside the 01M its own GA lists. A code that is
     another row's code plus ONE letter, with the same description, and with no drawing or
     other row of its own, is that row's part. A genuine suffix letter is left alone.

  2. Item 13 is 12133-02-01X x6 and item 14 "12133-02-01X - HANDED" x6, two purchases. The
     code key dropped "-HANDED" as description bleed, so the two hands were one record and the
     handed line took the base's count (8, not 6). A hand word stays in the key; bleed such as
     "-WALL" is still trimmed.

Invented numbers throughout.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "source_connectors"))

import bom_pipeline as bp  # noqa: E402
from part_identity import normalize_part_code  # noqa: E402


def _row(code, desc, qty, parent, item):
    return {"part_number": code, "description": desc, "quantity": qty, "bom_parent": parent,
            "source_pdf": parent, "bom_item_no": item}


# ── 1. one stray letter ──────────────────────────────────────────────────────────────────

def test_a_code_with_one_stray_letter_is_the_listed_part_and_is_said():
    rows = [_row("50001-04-01ME", "1130x489 SHELF TOP", 2, "50001-00-GA", "28"),
            _row("50001-04-01M", "1130x489 SHELF TOP", 1, "50001-04-GA", "2")]
    found = bp.reconcile_one_stray_letter(rows, ["/x/50001-04-GA_SHELF_REV A.PDF"])
    assert [r["part_number"] for r in rows] == ["50001-04-01M", "50001-04-01M"]
    assert rows[0]["quantity"] == 2, "the count printed on the line is kept"
    assert rows[0]["bom_also_read_as"][0]["part_number"] == "50001-04-01ME"
    assert found and found[0]["code"] == "bom_code_one_stray_letter"


def test_a_genuine_suffix_letter_is_left_alone():
    # a different description: two parts
    rows = [_row("50001-04-01MA", "SHELF TOP - WIDE", 2, "50001-00-GA", "28"),
            _row("50001-04-01M", "1130x489 SHELF TOP", 1, "50001-04-GA", "2")]
    assert not bp.reconcile_one_stray_letter(rows, [])
    assert rows[0]["part_number"] == "50001-04-01MA"
    # the same description, but the longer code has a drawing of its own
    rows = [_row("50001-04-01MA", "1130x489 SHELF TOP", 2, "50001-00-GA", "28"),
            _row("50001-04-01M", "1130x489 SHELF TOP", 1, "50001-04-GA", "2")]
    assert not bp.reconcile_one_stray_letter(rows, ["/x/50001-04-01MA_SHELF_REV A.PDF"])
    assert rows[0]["part_number"] == "50001-04-01MA"
    # nothing to be a stray letter of
    rows = [_row("50001-04-01ME", "1130x489 SHELF TOP", 2, "50001-00-GA", "28")]
    assert not bp.reconcile_one_stray_letter(rows, [])
    assert rows[0]["part_number"] == "50001-04-01ME"


# ── 2. a hand ────────────────────────────────────────────────────────────────────────────

def test_a_handed_code_keeps_its_hand_and_bleed_is_still_trimmed():
    assert normalize_part_code("50001-02-01X - HANDED") == "50001-02-01X-HANDED"
    assert normalize_part_code("50001-02-01X-LEFT") == "50001-02-01X-LEFT"
    assert normalize_part_code("50001-02-01X") == "50001-02-01X"
    # the contrast: words that are bleed still go
    assert normalize_part_code("50001-04-01A-WALL") == "50001-04-01A"


def test_each_hand_keeps_its_own_printed_count():
    import llm_full_job
    job = {"bom": [
        {"part_number": "50001-02-01X", "qty": 6, "source": "explicit_bom_table"},
        {"part_number": "50001-02-01X - HANDED", "qty": 6, "source": "explicit_bom_table"},
        {"part_number": "50001-02-101", "qty": 3, "source": "explicit_bom_table"}],
        "assemblies": [{"part_number": "50001-02-101",
                        "children": [{"part_number": "50001-02-01X", "qty": 2}]}]}
    q = llm_full_job._rollup_quantities(job)
    assert q["50001-02-01X-HANDED"] == 6, q
    assert q["50001-02-01X"] == 6, q
