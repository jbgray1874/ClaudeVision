"""A question names the operation it asks about; a bench counts the pieces it fits (D-701).

12693-02 (the medium tiered table), 5 Nov 12:39:

1. "Welding of 12693-02-01M: timed as one joint" said £49.10 rides on it. £49.10 is the tube's
   material; 01M's weld row is £25.06. D-698 priced a question from its operation's rows when
   the question named its operation, and only the TIG-rate question did. The question writer
   now takes the operations, and every question about one operation names it at source:
   welding, cutting, rolling, folding, polishing. A question about the part itself (its blank,
   size, section or cut length) still carries the part's line, because all of it follows.
2. 04J's own parts table lists five pieces in three rows (1 + 2 + 2), and the bench allowance
   fitted "3 part(s)" in 6 minutes. It counted child records, not pieces. Where the pieces
   come from the part's own table, each row's count is how many are fitted.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf  # noqa: E402
import estimator as est  # noqa: E402
import source_precedence as sp  # noqa: E402


# ── 1. the question writer and the money beside it ───────────────────────────────────

def test_the_writer_records_the_operations():
    part = {"part_number": "T-01M"}
    assert sp.raise_manufacturing_question(part, "Welding of T-01M: timed as one joint",
                                           "a", "b", "test", operations=["welding"])
    assert part["manufacturing_questions"][0]["operations"] == ["welding"]


def test_a_question_asked_again_gains_the_operation_it_lacked():
    part = {"part_number": "T-01M"}
    sp.raise_manufacturing_question(part, "Q", "a", "b", "first pass")
    assert "operations" not in part["manufacturing_questions"][0]
    assert not sp.raise_manufacturing_question(part, "Q", "a", "b", "second", operations=["welding"])
    assert part["manufacturing_questions"][0]["operations"] == ["welding"]
    assert len(part["manufacturing_questions"]) == 1


def test_without_operations_the_question_is_as_before():
    part = {"part_number": "T-01M"}
    sp.raise_manufacturing_question(part, "Blank of T-01M", "a", "b", "test")
    assert set(part["manufacturing_questions"][0]) == {"issue", "assumption", "action", "source"}


def _job(part, rows, line_gbp=49.10):
    return {"estimate_summary": {
        "part_estimates": [{"part_number": part["part_number"], "quantity": 1,
                            "material_estimate": {"extended_material_cost_gbp": line_gbp},
                            "line_total_gbp": line_gbp}],
        "canonical_route_shadow": {"decisions": []},
        "final_estimate": {"labour_rows": [
            {"operation": d, "total_value_gbp": v, "workbook_row": n} for n, d, v, _ in rows]},
        "workbook_labour": {"rows": [
            {"workbook_row": n, "engine_operations": [e], "part_numbers": [part["part_number"]]}
            for n, _, _, e in rows]}},
        "manufacturing_writeup": {"parts": [part]}}


def test_the_weld_timing_question_is_worth_the_weld_row_not_the_tube():
    part = {"part_number": "T-01M", "description": "FRAME TUBE"}
    sp.raise_manufacturing_question(part, "Welding of T-01M: timed as one joint",
                                    "the holes are read off the lines", "give the weld length",
                                    "estimator.estimate_process_times", operations=["welding"])
    src = _job(part, [(164, "Weld (CO2)", 25.06, "welding"), (153, "Saw", 13.29, "saw")])
    rows = [d for d in cf.costed_job(src)["decisions_required"]
            if "timed as one joint" in str(d.get("issue"))]
    assert len(rows) == 1
    assert rows[0]["gbp_at_stake"] == 25.06, "the tube's material is not what rides on a weld time"


def _source_of(path: str) -> str:
    return (ROOT / "src" / path).read_text(encoding="utf-8")


def _call_after(text: str, marker: str, span: int = 900) -> str:
    at = text.index(marker)
    return text[at:at + span]


def test_every_single_operation_question_names_its_operation_at_source():
    """The weld-timing, cutting, rolling, fold-count and polishing questions each name their
    operation where they are raised, so none falls back to the part's whole line."""
    cases = [
        ("estimator.py", 'f"Welding of {_pn_w}: timed as one joint"', '"welding"'),
        ("detail_page_geometry.py", "f\"Cutting of {pn}: {_read} read off the drawing's lines", '"laser_cutting"'),
        ("detail_page_geometry.py", 'f"Cutting of {pn}: internal features unread"', '"laser_cutting"'),
        ("detail_page_geometry.py", 'f"Rolling of {pn}: R{r:g} from its own sheet"', '"rolling"'),
        ("drawing_job_merge.py", "(f\"fold count of {hand.get('part_number')}", '"folding"'),
        ("concept_scan.py", 'f"Polishing of {pn}: {polish}"', '"polishing"'),
        ("weld_symbols.py", "_issue = f\"Weld rate:", '"welding"'),
    ]
    for path, marker, op in cases:
        call = _call_after(_source_of(path), marker, 1200)
        assert re.search(r"operations=\[[^\]]*" + re.escape(op), call), (path, marker)


# ── 2. the bench counts pieces ───────────────────────────────────────────────────────

def _board_asm(listed=None):
    p = {"part_number": "T-04J", "normalized_material": "MDF", "normalized_thickness_mm": 18.0,
         "quantity": 1, "is_assembly_parent": True,
         "assembly_children": ["T-04J-01", "T-04J-02", "T-04J-03"]}
    if listed is not None:
        p["listed_pieces"] = listed
    return p


def _bench_minutes(part):
    est.estimate_part(part)
    flag = next(f for f in part["review_flags"] if f.startswith("bench fitting:"))
    return float(re.match(r"bench fitting: ([\d.]+) min", flag).group(1)), flag


def test_pieces_from_its_own_table_are_counted_by_their_rows_counts():
    mins, flag = _bench_minutes(_board_asm([{"row": "845 x 845 x 18 mm", "qty": 1},
                                            {"row": "845 x 112 x 12 mm", "qty": 2},
                                            {"row": "621 x 112 x 12 mm", "qty": 2}]))
    assert mins == 10.0
    assert "5 pieces in 3 rows of its own parts table" in flag


def test_without_a_table_the_child_records_are_counted_as_before():
    mins, flag = _bench_minutes(_board_asm())
    assert mins == 6.0
    assert "3 children" in flag
