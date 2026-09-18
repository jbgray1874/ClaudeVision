r"""Two numbers, and neither said what it was. One fold, and nothing said who counted it.

James Gray, 18 September 2026, on the 401912-02 book:

    "Steel provenance conflicts. The workbook correctly charges £3.07 from nested blank
     area, but the report records an engine figure of £3.88 and describes the material as
     weight-based. One authoritative material basis and source must flow through both."

    "Ensure the correct flat DXF supplies the fold evidence/count. why are we getting this
     incorrect ever?"

THE STEEL. Both figures had costed the BLANK. Neither used the 1.7 kg. The whole gap was
the steel rate, which is written in more than one place with different values — a duplicate
the rate audit already lists in its own header: "steel £950/tonne default, £900 on the sheet
that shipped". Three readers of that book, including me, took two bare pounds figures side
by side as a disagreement about METHOD. It was a disagreement about a RATE, and the answer
to it is a ruling from an estimator, not a day spent looking for a costing bug.

Two numbers cannot say that. Two numbers WITH THEIR BASES can, in seconds — and where the
bases turn out to be the same, the reader knows immediately that what they are looking at is
a rate written twice rather than an engine that cannot add up.

THE FOLD. We are not getting it wrong, usually — but the sheet cannot say so. A flat DXF
exported without a bend-line layer carries the outline and nothing else, so the count falls
to the SolidWorks model or a drawing note. That fallback is correct and the engine has to
have it, because plenty of parts have their folds only in a callout. What was missing is the
sentence naming WHICH, and without it a measured fold and an inferred one look identical on
the page: a reader who wants to check has nowhere to start and no reason to think they
should. 401912-02 charged thirty minutes of press-brake set-up on a fold nothing had
counted, and said "layers not provided" four hundred words away from it.

`bend_count_source` has been on the record all along — `_model_measured_zero_bends` reads it
to decide whether a zero was measured or merely absent. It had simply never been said out
loud on the line that spends the money.

NEITHER CHANGE MOVES A PRICE. Both make a number say where it came from.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimation_report  # noqa: E402
import estimator  # noqa: E402

_DIVIDER = {"part_number": "401912-02-01M", "description": "METAL DIVIDER - TALL",
            "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 2.0,
            "blank_length_mm": 460.0, "blank_width_mm": 356.61, "quantity": 1,
            "geometry_source": "dxf_flat_pattern", "textual_operations": ["folding"]}


def _divider(**over):
    return dict(_DIVIDER, **over)


# ── the material basis, named ────────────────────────────────────────────────────────

def test_a_sheet_nested_figure_says_it_is_a_share_of_a_sheet():
    said = estimation_report._material_basis_phrase({
        "cost_method": "workbook_sheet_steel_formula",
        "unit_material_mass_kg": 2.575,
        "stock_estimate": {"parts_per_sheet": 15,
                           "candidate_sheet_size_mm": [2500, 1250]}})
    assert "share of a sheet" in said
    assert "15 per 2500 x 1250" in said, said
    assert "2.575 kg" in said


def test_a_weight_based_figure_says_so_and_they_do_not_read_alike():
    """The distinction three people got wrong on one line. A reader must be able to tell
    these apart at a glance or the two figures stay a mystery."""
    nested = estimation_report._material_basis_phrase({
        "cost_method": "workbook_sheet_steel_formula",
        "stock_estimate": {"parts_per_sheet": 15}})
    weighed = estimation_report._material_basis_phrase({
        "cost_method": "stated_weight_per_kg", "unit_material_mass_kg": 1.7})
    assert "share of a sheet" in nested
    assert "stated weight" in weighed and "per kilogram" in weighed
    assert nested != weighed


def test_the_faced_board_and_researched_bases_are_shares_of_a_sheet_too():
    """MFMDF nested on its own stock, and a researched £/m² — both buy a piece of a sheet,
    and must not read as anything else."""
    for _m in ("board_sheet_yield", "sheet_rate_live_udef", "board_rate_researched"):
        assert "share of a sheet" in estimation_report._material_basis_phrase(
            {"cost_method": _m}), _m


def test_a_bought_in_and_an_unpriced_line_each_say_what_they_are():
    assert "bought-in" in estimation_report._material_basis_phrase(
        {"cost_method": "bought_in_recognised_price:recogniser"})
    assert "unpriced" in estimation_report._material_basis_phrase(
        {"cost_method": "faced_board_unpriced"})


def test_a_record_with_no_method_says_nothing_rather_than_guessing():
    assert estimation_report._material_basis_phrase({}) == ""
    assert estimation_report._material_basis_phrase(None) == ""


def test_the_report_puts_both_bases_beside_both_numbers():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" /
           "estimation_report.py").read_text(encoding="utf-8")
    assert "_eng_basis = _material_basis_phrase(_pe.get(\"material_estimate\"))" in src
    assert "from {_eng_basis}" in src
    # AND THE SENTENCE THAT SAVES THE NEXT READER THE AFTERNOON WE JUST SPENT.
    assert "a rate written in two places, not " in src


# ── the fold, and who counted it ─────────────────────────────────────────────────────

def _timed(part):
    estimator.estimate_process_times(part, quantity=1)
    return " ".join(str(f) for f in part.get("review_flags", []))


def test_a_measured_fold_says_what_measured_it():
    said = _timed(_divider(manufacturing_features={
        "bend_count": 1, "bend_count_source": "solidworks_api"}))
    assert "counted by solidworks_api" in said
    assert "measured, not inferred" in said


def test_a_fold_nothing_looked_at_says_that_plainly():
    """Thirty minutes of press-brake set-up on a count nobody verified."""
    said = _timed(_divider(manufacturing_features={"bend_count": 1}))
    assert "NOTHING THAT CAN SEE THE PART COUNTED THEM" in said


def test_it_explains_why_rather_than_only_that():
    """"Unproven" invites a rerun with the same file. "Your DXF has no bend-line layer"
    invites the one change that would fix it permanently."""
    said = _timed(_divider(manufacturing_features={"bend_count": 1}))
    assert "no bend-line layer" in said
    assert "export bend lines" in said


def test_a_dxf_with_layers_gets_the_shorter_ask():
    """Layers present and still no measured source is a different situation — the export is
    not the thing to change."""
    said = _timed(_divider(
        manufacturing_features={"bend_count": 1},
        normalized_geometry={"layers": ["0", "BENDLINES"]}))
    assert "Confirm the count against the drawing" in said
    assert "export bend lines" not in said


def test_a_part_with_no_fold_is_told_nothing_about_folds():
    """The control. A flag on every part is a flag on none of them."""
    said = _timed(_divider(textual_operations=["laser_cutting"]))
    assert "fold(s) charged" not in said


def test_neither_change_moves_a_price():
    """Both are sentences. If either one could alter a figure it would not be a label."""
    quiet = _divider(manufacturing_features={"bend_count": 1,
                                             "bend_count_source": "solidworks_api"})
    loud = _divider(manufacturing_features={"bend_count": 1})
    a = estimator.estimate_process_times(quiet, quantity=1)
    b = estimator.estimate_process_times(loud, quantity=1)
    assert (a.get("run_times_min_per_unit") or {}).get("folding") == \
           (b.get("run_times_min_per_unit") or {}).get("folding")
    assert (a.get("setup_times_min") or {}).get("folding") == \
           (b.get("setup_times_min") or {}).get("folding")
