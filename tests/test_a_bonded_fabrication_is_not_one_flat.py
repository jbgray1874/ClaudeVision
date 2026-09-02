r"""
test_a_bonded_fabrication_is_not_one_flat.py

SIX OF SEVEN PIECES DROPPED, AND NOTHING ON THE SHEET SAID SO.

12349-02-69-01A is a UV-bonded acrylic fabrication. SDI exports its pieces as

    12349-02-69-01A_-01_2MM_High Impact Acrylic_RevA.DXF     <- a lens
    12349-02-69-01A_-02_3MM_High Impact Acrylic_RevA.DXF     <- a comb
    12349-02-69-01A_-03..-07_5MM_High Impact Acrylic_RevA.DXF <- five 5mm parts

All seven parse to the part number 12349-02-69-01A, which is correct — the `_-0n` is an
export suffix, not a child part number. drawing_job_merge splits several distinct blanks onto
child detail parts when numbered children exist in scope. 01A has none, so it fell to the
other branch:

    chosen = _pick_best_flat(part, paths)
    reason = "distinct_blanks_no_children_in_scope_pick_best"

whose comment reads "these are competing variants for a single leaf part (e.g. a stale
revision left in the folder)". That is right about stale revisions and wrong about this. 01A
came through as one 770 x 135 x 5 strip — £11.43 of material and £1.96 of laser for a bonded
box — and the six that were dropped left no trace anywhere on the estimate, which is what
makes it an under-charge nobody could catch by reading it.

THE TELL WAS IN THE FILENAMES THE ENGINE ALREADY PARSES. A stale revision of a part is the
same part in the same stock: same material, same gauge, a slightly different outline. These
declare 2mm, 3mm and 5mm, and nothing is a revision of itself in a different thickness.

The pick-best behaviour has to survive intact for the case it was written for, or every stale
revision in every job folder becomes a phantom part.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("ezdxf", reason="drawing_job_merge reads DXFs at import")
from drawing_job_merge import flats_are_different_pieces           # noqa: E402


def _p(*names):
    return [Path(n) for n in names]


# ── the case that was broken ───────────────────────────────────────────────────

def test_01As_seven_flats_are_recognised_as_seven_pieces():
    assert flats_are_different_pieces(_p(
        "12349-02-69-01A_-01_2MM_High Impact Acrylic_RevA.DXF",
        "12349-02-69-01A_-02_3MM_High Impact Acrylic_RevA.DXF",
        "12349-02-69-01A_-03_5MM_High Impact Acrylic_RevA.DXF",
        "12349-02-69-01A_-04_5MM_High Impact Acrylic_RevA.DXF",
        "12349-02-69-01A_-05_5MM_High Impact Acrylic_RevA.DXF",
        "12349-02-69-01A_-06_5MM_High Impact Acrylic_RevA.DXF",
        "12349-02-69-01A_-07_5MM_High Impact Acrylic_RevA.DXF",
    )) is True


def test_two_gauges_are_enough():
    """A lens and a comb is already a fabrication. It does not take seven."""
    assert flats_are_different_pieces(_p(
        "12349-02-69-01A_-01_2MM_High Impact Acrylic_RevA.DXF",
        "12349-02-69-01A_-07_5MM_High Impact Acrylic_RevA.DXF")) is True


def test_a_different_material_at_the_same_gauge_is_also_two_pieces():
    assert flats_are_different_pieces(_p(
        "9999-01-01A_-01_5MM_High Impact Acrylic_RevA.DXF",
        "9999-01-01A_-02_5MM_MDF_RevA.DXF")) is True


# ── the behaviour this must not break ──────────────────────────────────────────

def test_a_stale_revision_is_still_one_part():
    """Same stock, different revision letter. Promoting these makes a phantom part out of a
    file somebody forgot to delete, on every job with a tidy-up pending."""
    assert flats_are_different_pieces(_p(
        "1282-01-08_1_2mm_MS_RevA.DXF",
        "1282-01-08_1_2mm_MS_RevB.DXF")) is False


def test_two_flats_of_the_same_stock_are_one_part():
    assert flats_are_different_pieces(_p(
        "12242-01-01M_MS_1_5mm_revD.DXF",
        "12242-01-01M_TEXT_MS_1_5mm_revD.DXF")) is False


def test_one_flat_is_never_two_pieces():
    assert flats_are_different_pieces(_p("1282-01-08_1_2mm_MS_RevA.DXF")) is False


def test_filenames_that_declare_nothing_are_left_to_the_old_rule():
    """No gauge and no material in the name is not evidence of anything. Guessing here would
    promote phantoms off a naming convention we do not recognise."""
    assert flats_are_different_pieces(_p("panel_a.DXF", "panel_b.DXF")) is False


def test_a_flat_that_declares_a_gauge_against_one_that_does_not_is_not_a_split():
    """One reading is not a disagreement."""
    assert flats_are_different_pieces(_p(
        "9999-01-01A_-01_5MM_High Impact Acrylic_RevA.DXF",
        "9999-01-01A_-02.DXF")) is False


def test_the_merge_asks_this_before_falling_back_to_pick_best():
    """Structural: the question has to be asked on the branch where there are no numbered
    children, which is the branch 01A took."""
    import ast
    src = (ROOT / "src" / "drawing_job_merge.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "flats_are_different_pieces" in called, (
        "defined but never asked is the same as not fixed")
