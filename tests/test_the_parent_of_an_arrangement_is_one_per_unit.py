"""The module that IS the unit has to say one per quoted unit on its own record.

12349-02 AT 23:56, WITH THE EDGE FIX IN AND THE SHEET STILL WRONG. The general-arrangement row
was divided — the workbook's own BOM block shows `-69-100` at `qty_own 1` carrying the
arrangement note — and the Estimate printed three lids, three covers, twelve screws and eighteen
bumpons. Estimate matched `qty_effective` on every line, so there is no second store. One store,
holding the parent's uncorrected figure, and a correct cascade below it.

The split on that sheet is exact: the general arrangement's OWN leaves were right (the packer at
one, the wood screws at six) and everything under `-69-100` was three times its own cell. So the
module's node is 3 while its row says 1, and the fix is the module's own record.

WHAT THIS FILE DOES AND DOES NOT PROVE, STATED PLAINLY BECAUSE THE LAST FOUR ATTEMPTS DID NOT.

  PROVEN HERE: the precedence behaviour of the correction — which holders it defers to, which
  one it supersedes, and that the runner says which happened.

  NOT PROVEN HERE: that `build_part_graph` yields 3 for this module. FOUR separate fixtures were
  built to reproduce it — the general arrangement as a root, no root at all, a stated
  `parent_part_number`, and a `page_owner` edge — and every one of them produced the CORRECT
  answer of 1. So the code path that produces the 3 on the real record is not known, and no test
  in this file asserts one.

  That matters more than it looks. Four earlier fixes on this defect were "proven" against
  fixtures whose shape I chose, and each was only caught by a real run — the last of them passed
  four tests about a code path the real record does not take. A fixture that cannot reproduce a
  defect cannot witness its fix, and saying so is worth more than a green test that means nothing.
  The graph half of this is proven by the run or not at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import source_precedence as sp                                          # noqa: E402

MODULE = "12349-02-69-100"


def test_the_correction_defers_to_the_model():
    """SUBMITTED, NOT WRITTEN. This pass reads a printed general-arrangement table; it does not
    get to overrule a model that counted instances. If SolidWorks says two, two stands."""
    part = {"part_number": MODULE}
    sp.apply_field(part, "quantity", 2, "solidworks_api")
    assert not sp.apply_field(part, "quantity", 1, "bom_tree")
    assert part["quantity"] == 2


def test_the_correction_defers_to_a_stronger_pdf_reading_and_that_is_the_quorum_case():
    """`drawing_deterministic` at 70 holds against the tree at 60. This is the case where the
    multiple SURVIVES this fix — and it is why the runner names the holder, because the answer
    then is the family quorum (two readings of one PDF are one voice), not this correction."""
    part = {"part_number": MODULE}
    sp.apply_field(part, "quantity", 3, "drawing_deterministic")
    assert not sp.apply_field(part, "quantity", 1, "bom_tree")
    assert part["quantity"] == 3


def test_the_tree_may_supersede_its_own_earlier_reading():
    """THE CASE THAT ACTUALLY OBTAINS, AND IT WOULD HAVE MADE THE FIX A NO-OP.

    The 3 on this record is the tree's OWN, written before it recognised that the general
    arrangement is an arrangement. A plain equal-rank submission is refused — correctly, since two
    readings of equal standing disagreeing is a conflict rather than refinement, and letting the
    later one win would make the answer depend on page order. But one reader revising its own
    figure on something the earlier pass did not know is not that conflict.

    So the stale STAMP is cleared and the corrected figure submitted normally. Nothing is ranked
    up, and what it replaced stays on the record."""
    part = {"part_number": MODULE}
    sp.apply_field(part, "quantity", 3, "bom_tree")
    assert not sp.apply_field(part, "quantity", 1, "bom_tree"), (
        "equal rank is refused, and that refusal is the whole reason the stamp is cleared")
    part["quantity_source"] = ""
    assert sp.apply_field(part, "quantity", 1, "bom_tree")
    assert part["quantity"] == 1
    assert sp.source_of(part, "quantity") == "bom_tree"
    assert any(float(e.get("value")) == 3.0 for e in sp.displaced_values(part, "quantity")
               if e.get("value") is not None), "the figure it replaced is kept, not discarded"


def test_a_module_already_at_one_is_left_entirely_alone():
    """No flag, no displacement, nothing said. The common case is a pack with no arrangement at
    all, and a correction that churns records it agrees with is noise on every other job."""
    part = {"part_number": MODULE}
    sp.apply_field(part, "quantity", 1, "bom_tree")
    before = dict(part)
    assert not sp.apply_field(part, "quantity", 1, "bom_tree")
    assert part["quantity"] == before["quantity"]


def test_the_runner_reports_which_of_those_happened():
    """A SILENT NO-OP LOOKS EXACTLY LIKE THE RUN THAT FAILED. Whether the write lands or is
    refused decides whether the next fix is this one or the family quorum, and I cannot read the
    record from here — so the log has to say, and has to name the holder."""
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8", errors="ignore")
    assert "is the unit — its" in src, "the applied case must announce itself"
    assert "was NOT replaced by 1" in src, "the refused case must announce itself"
    assert "IS WHAT HOLDS IT" in src, "and must name the holder, or the next run is another guess"
