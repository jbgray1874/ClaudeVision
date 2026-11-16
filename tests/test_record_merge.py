"""Two readings of one line must be merged field by field, not settled by picking one.

Every one of these asserts against a field the WINNING record does not hold. That is the
whole failure: the winner looks complete, so a test that only checks the winner's own
columns passes on the broken code and on the fixed code alike.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from record_merge import merge_records                              # noqa: E402
from source_precedence import source_of                             # noqa: E402


def test_the_loser_fills_a_gap_the_winner_left_blank():
    winner = {"item_number": "3", "part_ref": "12392-02-01M", "quantity": 2}
    loser = {"item_number": "3", "part_ref": "12392-02-01M", "quantity": 2,
             "description": "BACK PANEL"}

    notes = merge_records(winner, loser, winner_source="bom_tree",
                          loser_source="llm_extract")

    assert winner["description"] == "BACK PANEL"
    assert source_of(winner, "description") == "llm_extract", \
        "a filled gap must be stamped with the source that filled it, not the winner's"
    assert any("description" in n for n in notes), \
        "filling six columns silently is indistinguishable from filling none"


def test_a_weaker_reading_never_displaces_a_stronger_one():
    winner = {"part_ref": "12392-02-01M", "material": "MILD STEEL"}
    loser = {"part_ref": "12392-02-01M", "material": "CARD"}

    notes = merge_records(winner, loser, winner_source="bom_tree",
                          loser_source="llm_extract")

    assert winner["material"] == "MILD STEEL"
    assert source_of(winner, "material") == "bom_tree"
    assert any("disagree" in n for n in notes), \
        "a conflict that is resolved and not recorded is a conflict nobody can audit"


def test_a_stronger_reading_does_displace_a_weaker_one():
    winner = {"part_ref": "X", "normalized_thickness_mm": 1.5}
    loser = {"part_ref": "X", "normalized_thickness_mm": 2.0}

    merge_records(winner, loser, winner_source="llm_extract",
                  loser_source="solidworks_api")

    assert winner["normalized_thickness_mm"] == 2.0
    assert source_of(winner, "normalized_thickness_mm") == "solidworks_api"


def test_a_decided_field_is_never_re_decided_by_rank():
    """Vision winning the code on conflict is a rule chosen on purpose, against rank.

    Without `decided`, precedence would hand the field straight back to the
    deterministic reader and reverse it — silently, because the write succeeds.
    """
    winner = {"item_number": "5", "part_ref": "BI-BOLTBZP", "quantity": 8}
    loser = {"item_number": "5", "part_ref": "BI-BOLT", "quantity": 4}

    notes = merge_records(winner, loser, winner_source="llm_extract",
                          loser_source="bom_tree", decided=("part_ref", "quantity"))

    assert winner["part_ref"] == "BI-BOLTBZP"
    assert winner["quantity"] == 8
    assert any("decided by the reconciliation rule" in n for n in notes)


def test_agreement_upgrades_provenance_rather_than_leaving_the_weaker_name():
    winner = {"part_ref": "X", "quantity": 4}
    merge_records(winner, {"quantity": 4}, winner_source="llm_extract",
                  loser_source="solidworks_api")
    assert source_of(winner, "quantity") == "solidworks_api", \
        "two sources agreeing means the datum now rests on the stronger one"


def test_a_recorded_zero_is_a_value_and_is_defended():
    winner = {"part_ref": "X", "bend_count": 0}
    merge_records(winner, {"bend_count": 3}, winner_source="solidworks_api",
                  loser_source="llm_extract")
    assert winner["bend_count"] == 0, \
        "'the model says none' and 'nobody looked' must never resolve the same way"


def test_the_merges_own_bookkeeping_does_not_travel():
    winner = {"part_ref": "X", "source": "BOTH", "sheet": "1", "flag": ""}
    loser = {"part_ref": "X", "source": "B_RECOVERED", "sheet": "4",
             "flag": "LLM-recovered"}

    merge_records(winner, loser, winner_source="bom_tree", loser_source="llm_extract")

    assert winner["source"] == "BOTH"
    assert winner["sheet"] == "1"
    assert winner["flag"] == "", \
        "one reading's audit trail must not be reported as the other's"


def test_a_source_stamp_cannot_travel_without_the_value_that_earned_it():
    winner = {"part_ref": "X"}
    loser = {"material_source": "solidworks_api"}

    merge_records(winner, loser, winner_source="bom_tree", loser_source="llm_extract")

    assert "material_source" not in winner, \
        "a record stamped with a source for a value it does not hold is a false claim"


# ── the wiring, not the rule ────────────────────────────────────────────────────────
# Each of these fails if merge_records is removed from the call site, and passes on the
# rule alone. A merge that exists and is never called is the defect this codebase keeps
# reproducing.

def test_dual_path_reconcile_keeps_what_only_vision_read():
    import merge_boms

    a = {"parent": "12392-02", "rows": [
        {"item_number": "1", "part_ref": "12392-02-01M", "quantity": 2}]}
    b = {"parent": "12392-02", "rows": [
        {"item_number": "1", "part_ref": "12392-02-01M", "quantity": 2,
         "description": "BACK PANEL"}]}

    rows, _findings = merge_boms.reconcile_page(a, b, "12392-02")

    assert len(rows) == 1
    assert rows[0]["source"] == "BOTH"
    assert rows[0].get("description") == "BACK PANEL", \
        "the readers agreed on the line, so vision's description was discarded unflagged"


def test_dual_path_override_keeps_what_only_the_text_layer_read():
    import merge_boms

    a = {"parent": "P", "rows": [
        {"item_number": "1", "part_ref": "BI-BOLT", "quantity": 4,
         "material": "BZP STEEL"}]}
    b = {"parent": "P", "rows": [
        {"item_number": "1", "part_ref": "BI-BOLTBZP", "quantity": 8}]}

    rows, _findings = merge_boms.reconcile_page(a, b, "P")

    assert rows[0]["source"] == "B_OVERRIDE"
    assert rows[0]["part_ref"] == "BI-BOLTBZP", "vision wins the code, by the locked rule"
    assert rows[0]["quantity"] == 8
    assert rows[0].get("material") == "BZP STEEL", \
        "losing the code contest must not cost the row every other column"


def test_a_line_repeated_on_a_second_sheet_is_read_not_merely_noted():
    import merge_boms

    pages = [
        {"label": "12392-02", "parent_known": True, "sheet": "sheet 1", "rows": [
            {"item_number": "2", "part_number": "12392-02-03M", "quantity": 1}]},
        {"label": "12392-02", "parent_known": True, "sheet": "sheet 2", "rows": [
            {"item_number": "2", "part_number": "12392-02-03M", "quantity": 1,
             "description": "SIDE PANEL LH"}]},
    ]

    parents, _findings = merge_boms.merge_pages_into_parents(pages)

    rows = parents[0]["rows"]
    assert len(rows) == 1, "one line seen twice must not be costed twice"
    assert "sheet 2" in rows[0]["also_on_sheets"]
    assert rows[0].get("description") == "SIDE PANEL LH", \
        "the second sheet printed the column the first clipped, and it was never read"


def test_a_bom_line_on_two_drawings_takes_the_quantity_from_whichever_printed_it():
    import file_scan

    winner = {"part_number": "BI-BOLTBZP", "description": "M6 BOLT BZP",
              "source_pdf": "12392-01-GA.pdf"}
    loser = {"part_number": "BI-BOLTBZP", "description": "M6 BOLT BZP",
             "quantity": 12, "source_pdf": "12392-04-GA.pdf"}

    file_scan._merge_bom_rows(winner, loser)

    assert winner["quantity"] == 12, \
        "the primary drawing wins the row; that is no reason to keep its blank column"
    assert winner["source_pdf"] == "12392-01-GA.pdf", \
        "source_pdf names which drawing this row was taken from"


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
