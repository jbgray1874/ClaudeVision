""""Is it getting quieter" becomes a number, or it stays an opinion.

IT HAS BEEN ANSWERED BY IMPRESSION, ON ONE DRAWING, FOR A WEEK — and it is the only question
that decides whether estimating adopts this tool.

THE DISTINCTION IS NOT SEVERITY. A BLOCKING flag saying "this material has no rate in the
catalogue" is the engine working perfectly: it read the pack, priced what it could, and put in
front of a person the one thing only a person can settle. A WARNING saying "this part appears
in the raw records and not in the extract, so it was invented downstream" is the engine
confessing. One is Tim's list and a mature system produces MORE of them. The other is ours and
must trend to zero.

ONE QUESTION PER CODE: would a PERFECT engine, reading this same pack, still raise it?

AND AN UNCLASSIFIED CODE COUNTS AS OURS. Every metric dies the same way — the inconvenient
thing quietly stops being counted. A new check nobody classified inflates the number it would
otherwise disappear from, which is the only pressure that keeps the table honest.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import engine_discoveries as ed  # noqa: E402

# 11650-04's own flags, as the last run produced them. Not invented for the test: this is the
# job the whole week was spent on, and it is the baseline the next pack is measured against.
SIDE_PANEL_RUN = [
    {"code": "short_run_pays_for_sheet_it_does_not_use"},
    {"code": "material_has_no_rate_in_this_engine"},
    {"code": "material_priced_from_a_lower_ranked_reading"},
    {"code": "two_sources_disagree_about_the_gauge"},
    {"code": "unpriced_line_says_why"},
    {"code": "finish_field_holds_drawing_text"},
    {"code": "stated_finish_not_costed"},
    {"code": "operation_named_but_not_priced"},
    {"code": "datum_written_without_source"},
    {"code": "native_top_assembly_ambiguous"},
    {"code": "price_not_reproducible"},
    {"code": "canonical_route_bom_node_disconnected"},
    {"code": "price_not_firm"},
    {"code": "cad_files_not_read"},
    {"code": "bom_page_not_read_by_both"},
]


# ── the split ────────────────────────────────────────────────────────────────────────

def test_a_missing_rate_is_not_an_engine_defect():
    """The commonest confusion, and the one that makes the number useless if it is wrong. A
    price this business has not decided is not a bug; the engine did its whole job."""
    # "commerce" NOW, NOT "drawing". The point of the test is unchanged and is asserted
    # first: it is not the engine's fault. What changed is that "not ours" split by WHO fixes
    # it — a rate is a row in SDILive and the drawing office cannot add one.
    assert ed.classify("material_has_no_rate_in_this_engine") != "engine"
    assert ed.classify("material_has_no_rate_in_this_engine") == "commerce"
    assert ed.classify("price_not_reproducible") != "engine"
    assert ed.classify("price_not_reproducible") == "commerce"


def test_a_pack_disagreeing_with_itself_is_not_an_engine_defect():
    """The model says 2.2 and the export says 2MM. A perfect engine reports exactly that."""
    # "estimator": the pack caused it, but nobody in the drawing office can settle it and no
    # database holds the answer. Somebody with the job open decides which gauge it is.
    assert ed.classify("two_sources_disagree_about_the_gauge") != "engine"
    assert ed.classify("two_sources_disagree_about_the_gauge") == "estimator"
    assert ed.classify("handed_pair_disagrees") != "engine"
    assert ed.classify("handed_pair_disagrees") == "estimator"
    assert ed.classify("cad_files_not_read") == "drawing"


def test_an_invented_part_is_ours():
    """"It appears in the raw part records and NOT in the extract, so it was invented
    downstream of the drawing read" — that sentence is a confession."""
    assert ed.classify("canonical_route_bom_node_disconnected") == "engine"
    assert ed.classify("datum_written_without_source") == "engine"
    assert ed.classify("material_priced_from_a_lower_ranked_reading") == "engine"


def test_a_declared_assumption_is_neither():
    """A number the engine chose, said so, and named the lever for. Counting it as a defect
    punishes honesty; counting it as clean hides a figure nobody has agreed."""
    assert ed.classify("powder_quantity_is_an_assumption") == "assumption"
    assert ed.classify("throughput_floor_applied") == "assumption"


def test_a_check_that_could_not_run_is_counted_apart():
    """Neither clean nor a discovery. Folding it into either is how seven unverified checks
    came to read as a quiet job."""
    assert ed.classify("totals_reconcile_not_evaluated") == "unverified"


def test_a_code_nobody_classified_counts_as_ours():
    """THE PROPERTY THAT KEEPS THIS HONEST. A new check added without a decision inflates the
    engine number rather than vanishing from it — otherwise the table rots the first time
    somebody is in a hurry."""
    assert ed.classify("some_check_invented_next_tuesday") == "engine"
    assert ed.classify("") == "engine"


# ── the number, on the job the week was spent on ─────────────────────────────────────

def test_the_side_panel_baseline_is_recorded_not_guessed():
    """The measurement only means something against a number somebody wrote down. This is
    11650-04 as it actually ran, and it is what the next pack is compared with."""
    c = ed.count(SIDE_PANEL_RUN)
    assert c["engine_discoveries"] == 7, c["engine_codes"]
    assert c["drawing_and_commercial"] == 8, c["drawing_codes"]
    assert set(c["engine_codes"]) == {
        "canonical_route_bom_node_disconnected",
        "datum_written_without_source",
        "finish_field_holds_drawing_text",
        "material_priced_from_a_lower_ranked_reading",
        "native_top_assembly_ambiguous",
        "operation_named_but_not_priced",
        "unpriced_line_says_why",
    }


def test_the_codes_are_named_and_not_only_counted():
    """"Three engine discoveries" is a score. "bom_node_disconnected,
    datum_written_without_source, finish_field_holds_drawing_text" is a morning's work."""
    c = ed.count(SIDE_PANEL_RUN)
    assert "canonical_route_bom_node_disconnected" in c["engine_codes"]
    assert len(c["engine_codes"]) == c["engine_discoveries"]


def test_a_clean_pack_says_so_plainly():
    line = ed.one_line(ed.count([{"code": "material_has_no_rate_in_this_engine"}]))
    assert "nothing on this pack was the engine's fault" in line


def test_a_pack_with_discoveries_names_them_in_the_line():
    line = ed.one_line(ed.count(SIDE_PANEL_RUN))
    assert "7 engine discovery" in line and "canonical_route_bom_node_disconnected" in line


def test_no_violations_at_all_is_not_an_error():
    c = ed.count([])
    assert c["engine_discoveries"] == 0 and c["drawing_and_commercial"] == 0


def test_bare_strings_are_accepted_as_well_as_records():
    """Callers hold violations in both shapes, and a metric that only reads one of them
    measures half the job."""
    assert ed.count(["datum_written_without_source"])["engine_discoveries"] == 1


# ── the table cannot quietly rot ─────────────────────────────────────────────────────

def test_no_code_is_classified_twice():
    """A code in both tables answers whichever question is asked first, which is how a metric
    starts reporting what somebody hoped rather than what happened."""
    assert not (ed._NOT_OURS & ed._OURS)
    assert not (ed._ASSUMPTIONS & ed._OURS)
    assert not (ed._ASSUMPTIONS & ed._NOT_OURS)


def test_every_code_the_engine_can_raise_is_classified():
    """THE ONE THAT MAKES THIS A MEASUREMENT RATHER THAN A SAMPLE. Invariant codes live in
    invariants.py; any that this table has never heard of are counted as ours by default,
    which is safe — but they should be DECIDED, and this names them so they can be."""
    inv = open(os.path.join(os.path.dirname(__file__), "..", "src", "invariants.py"),
               encoding="utf-8").read()
    import re
    codes = set(re.findall(r'_violation\(\s*\n?\s*["\']([a-z0-9_]+)["\']', inv))
    assert len(codes) > 20, f"only {len(codes)} codes found — the scan is not reading them"
    known = ed._NOT_OURS | ed._OURS | ed._ASSUMPTIONS
    undecided = sorted(c for c in codes
                       if c not in known and not c.endswith("_not_evaluated"))
    # Held as a count rather than an assertion of zero: classifying eighty checks in one pass
    # would be guessing, and a guessed table is worse than an honest backlog. The number must
    # not GROW, which is what this pins.
    assert len(undecided) <= 60, (
        "unclassified invariant codes have grown; decide the new ones rather than letting "
        "them default to 'ours': " + ", ".join(undecided[:12]))
