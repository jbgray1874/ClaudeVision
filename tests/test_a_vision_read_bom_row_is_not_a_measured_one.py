"""Every BOM quantity was stamped as measured, including on a run where nothing measured.

WHAT JAMES CHALLENGED. Told that section 9's "the drawing" labels were the deterministic text
read, he pushed back in four words: "It WAS an LLM ONLY run."

He was right that something was mislabelled and wrong about which column. Material and
thickness genuinely do come off the drawing's own text layer — `extract_with_pdfplumber` is
called unconditionally in `extract_pdf_summary`, and `SDI_LLM_ONLY` is read in exactly one
production place, `merge_boms`, where it disables Path A: the deterministic **BOM reader**, not
the text reader. So "the drawing" against material and thickness is accurate.

THE QUANTITY COLUMN IS WHERE IT WAS FALSE. Every BOM quantity was stamped `bom_tree` — rank 60,
and a member of MEASURED_SOURCES, so reports print it with no reasoned-value mark and
arbitration treats it as a table that was read rather than a picture of one that was looked at.

On an LLM-only run that is false for EVERY row on the job. Path A is off, so
`document_analysis.bom_rows` is the vision model's reading and nothing else. It reached section
9 as "the bill of materials", unmarked, on all twenty-five parts — the report telling an
estimator that a language model's reading of a table was measured.

AND IT IS WRONG ON A FULL RUN TOO, more quietly. Any row vision RECOVERED (the deterministic
reader missed it) or OVERRODE carries the same stamp. Those are precisely the rows where
corroboration did not happen, which makes them precisely the rows the mark exists for.

THE ANSWER WAS ALREADY ON THE ROW AND WAS BEING DISCARDED. reconcile_page stamps every row it
emits — BOTH, A_ONLY, B_RECOVERED, B_OVERRIDE — and part_index replaced all four with one
constant. Nothing new is derived here; a recorded fact is read instead of overwritten, which is
the same correction the geometry-source columns needed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import part_index as pi                                                # noqa: E402
import source_precedence as sp                                        # noqa: E402


@pytest.mark.parametrize("reader,expect", [
    ("BOTH", "bom_tree"),
    ("A_ONLY", "bom_tree"),
    ("B_RECOVERED", "llm_extract"),
    ("B_OVERRIDE", "llm_extract"),
])
def test_the_row_is_attributed_to_the_reader_that_saw_it(reader, expect):
    assert pi._bom_row_source({"source": reader}) == expect


def test_a_vision_only_row_is_not_reported_as_measured():
    """THE WHOLE POINT. was_measured is what section 9 asks before deciding whether to print
    the reasoned-value mark, and what tells an estimator a number can be held against a
    document."""
    assert not sp.was_measured(pi._bom_row_source({"source": "B_RECOVERED"}))
    assert sp.was_measured(pi._bom_row_source({"source": "BOTH"}))


def test_a_corroborated_row_keeps_its_standing():
    """The fix must not sweep in the rows that DID have two readers agree. A BOM both readers
    saw is the strongest BOM evidence this engine produces and demoting it would be the
    opposite error."""
    assert sp.rank(pi._bom_row_source({"source": "BOTH"})) > sp.rank(
        pi._bom_row_source({"source": "B_OVERRIDE"}))


def test_an_unstamped_row_keeps_todays_behaviour():
    """Rows from an older summary, or any path that does not run through reconcile_page, carry
    no source. Guessing "vision" there would demote real deterministic reads on every historical
    job re-rendered from JSON."""
    assert pi._bom_row_source({}) == "bom_tree"
    assert pi._bom_row_source({"source": None}) == "bom_tree"
    assert pi._bom_row_source({"source": "something_new"}) == "bom_tree"


def test_both_places_that_submit_a_bom_quantity_attribute_it_the_same_way():
    """One part's quantity at rank 60 and another's at 40, for the same kind of row, is a
    difference no reader could account for. Stated against the source because the two call
    sites are two hundred lines apart and the second was the one that kept the constant."""
    src = (ROOT / "src" / "part_index.py").read_text(encoding="utf-8")
    code = re.sub(r"#[^\n]*", " ", re.sub(r'"""(?:.|\n)*?"""', " ", src))
    # A fixed window rather than a paren match: the argument is `row.get("quantity")`, so a
    # non-greedy [^)]*? stops at the INNER bracket and never reaches the source argument —
    # which made this guard pass on the very call site it exists to check.
    submissions = [code[m.start():m.start() + 200]
                   for m in re.finditer(r'apply_field\(\s*[^;\n]*?"quantity"', code)]
    assert len(submissions) >= 2, "the quantity call sites moved; this guard needs updating"
    bom_submissions = [s for s in submissions if "drawing_deterministic" not in s]
    assert bom_submissions, "no BOM-sourced quantity submission found"
    for s in bom_submissions:
        assert "_bom_row_source(" in s, (
            "a BOM quantity is still being stamped with a constant instead of the reader that "
            f"saw the row: {s.strip()[:90]}")


def test_the_reader_names_come_from_merge_boms_and_not_from_memory():
    """The four values are merge_boms' own vocabulary. If it grows a fifth, this mapping has to
    learn it rather than silently calling it measured."""
    merged = (ROOT / "src" / "merge_boms.py").read_text(encoding="utf-8")
    stamped = set(re.findall(r'\["source"\]\s*=\s*"([A-Z_]+)"', merged))
    assert stamped, "merge_boms no longer stamps a reader on its rows"
    unknown = stamped - set(pi._BOM_ROW_READER)
    assert not unknown, (
        f"merge_boms emits reader(s) {sorted(unknown)} that part_index does not know, so they "
        f"fall through to bom_tree and are reported as measured")
