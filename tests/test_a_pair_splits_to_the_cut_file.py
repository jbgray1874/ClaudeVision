"""A handed pair that splits one-for-one is priced from the cut file, with the conflict kept.

THE POLICY, STATED AS TESTS. On a bare 1-vs-1 — one hand's material read from the exported flat
the CNC is driven from, the other's from a bare model property — the readings are level on
count but not on authority. The laser cuts the DXF, not the SolidWorks library material (which
is often a stale default), so the export wins the WHOLE stock key, both hands price the same,
and the disagreement is raised as a loud proviso rather than left as two materials on one
article. Every part gets a price; the conflict stays visible; the pair is not firm until it is
confirmed.

AND THE LIMIT OF IT. When BOTH sides rest on the cut file, or NEITHER does, the tie is genuine
and nothing is invented — a person settles it. The rule breaks a tie only when exactly one side
is the manufacturing export.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import drawing_job_merge as merge  # noqa: E402
import source_precedence as sp  # noqa: E402
import invariants  # noqa: E402
import engine_discoveries  # noqa: E402
import estimating_review  # noqa: E402

MAT, GAUGE = "normalized_material", "normalized_thickness_mm"


def _from(pn, readings):
    p = {"part_number": pn}
    for field, value, source in readings:
        sp.apply_field(p, field, value, source)
    return p


# ── the policy ───────────────────────────────────────────────────────────────────────

def test_the_export_wins_a_one_for_one_split_against_the_model():
    """The whole point: model-only ABS vs cut-file PETG, level on count, priced PETG for both."""
    base = _from("20A", [(MAT, "ABS", "solidworks_api"), (GAUGE, 2.0, "solidworks_api")])
    hand = _from("20A-HANDED", [(MAT, "PETG", "dxf_filename"), (GAUGE, 2.0, "dxf")])
    out = merge.settle_handed_pairs([base, hand])
    assert base[MAT] == hand[MAT] == "PETG", "the pair was not priced from the cut file"
    assert out and out[0]["outcome"] == "settled_on_cut_file"


def test_the_whole_stock_key_moves_to_the_export():
    """Material AND gauge come from the export, so the pair reaches one stock key — not PETG
    from one hand and 2.2mm from the other."""
    base = _from("22A", [(MAT, "ABS", "solidworks_api"), (GAUGE, 2.2, "solidworks_api")])
    hand = _from("22A-HANDED", [(MAT, "PETG", "dxf_filename"), (GAUGE, 2.0, "dxf")])
    merge.settle_handed_pairs([base, hand])
    assert (base[MAT], base[GAUGE]) == (hand[MAT], hand[GAUGE]) == ("PETG", 2.0)


def test_the_conflict_is_kept_visible_not_erased():
    """A price is rendered, but the pack disagreed and that must survive: the model's reading is
    logged as displaced and a proviso flag names both readings."""
    base = _from("23A", [(MAT, "ABS", "solidworks_api"), (GAUGE, 2.0, "solidworks_api")])
    hand = _from("23A-HANDED", [(MAT, "PETG", "dxf_filename"), (GAUGE, 2.0, "dxf")])
    merge.settle_handed_pairs([base, hand])
    displaced = {str(e.get("value")) for e in sp.displaced_values(base, MAT)}
    assert "ABS" in displaced, "the model's reading was erased rather than kept as a proviso"
    assert any("PRICED ON THE CUT FILE" in f for f in base.get("review_flags", []))


def test_the_hand_that_won_keeps_its_own_export_provenance():
    """Only the loser records that it took the pair's answer; the winner reached the key on its
    own export and keeps it, or the stock key traces to nothing."""
    base = _from("24A", [(MAT, "ABS", "solidworks_api"), (GAUGE, 2.0, "solidworks_api")])
    hand = _from("24A-HANDED", [(MAT, "PETG", "dxf_filename"), (GAUGE, 2.0, "dxf")])
    merge.settle_handed_pairs([base, hand])
    assert sp.source_of(hand, MAT) == "dxf_filename"
    assert sp.source_of(base, MAT) == "mirror_of_measured"


# ── the limit of it ──────────────────────────────────────────────────────────────────

def test_two_models_are_still_undecided():
    """Neither side rests on the cut file, so the tie is genuine and nothing is invented."""
    base = _from("25A", [(MAT, "ABS", "solidworks_api"), (GAUGE, 2.0, "solidworks_api")])
    hand = _from("25A-HANDED", [(MAT, "PETG", "solidworks_api"), (GAUGE, 2.0, "solidworks_api")])
    out = merge.settle_handed_pairs([base, hand])
    assert out and out[0]["outcome"] == "undecided"
    assert base[MAT] == "ABS" and hand[MAT] == "PETG"


def test_two_different_cut_files_are_a_real_disagreement():
    """When BOTH hands read their material off an export and the exports disagree, that is a
    genuine drawing conflict — one export names PETG, the other ABS, and picking one would hide
    it. Left undecided for a person."""
    base = _from("26A", [(MAT, "ABS", "dxf_filename"), (GAUGE, 2.0, "dxf_filename")])
    hand = _from("26A-HANDED", [(MAT, "PETG", "dxf_filename"), (GAUGE, 2.0, "dxf_filename")])
    out = merge.settle_handed_pairs([base, hand])
    assert out and out[0]["outcome"] == "undecided", "two disagreeing exports were not left alone"
    assert base[MAT] == "ABS" and hand[MAT] == "PETG"


# ── the proviso reaches the estimator ────────────────────────────────────────────────

def test_the_invariant_raises_the_proviso_as_a_warning():
    """A price stands, so it is a WARNING not a block — but it is surfaced, with both readings,
    so an estimator confirms the material before quoting firm."""
    base = _from("27A", [(MAT, "ABS", "solidworks_api"), (GAUGE, 2.0, "solidworks_api")])
    hand = _from("27A-HANDED", [(MAT, "PETG", "dxf_filename"), (GAUGE, 2.0, "dxf")])
    merge.settle_handed_pairs([base, hand])
    summary = {"parts": [base, hand]}
    vios = invariants.check_a_handed_pair_priced_on_the_cut_file(summary)
    assert len(vios) == 1
    v = vios[0]
    assert v["code"] == "handed_pair_settled_on_cut_file"
    assert v["severity"] == invariants.WARNING
    assert "PETG" in v["message"] and "ABS" in v["message"]


def test_the_proviso_is_a_drawing_problem_not_the_engines_fault():
    """The engine read the pack correctly and priced it; the pack disagreed with itself. So the
    code counts as the drawing's, not an engine discovery, and lands in the confirm-or-overwrite
    bucket rather than the broken-inputs one."""
    # Not the engine's — the point of this test — and specifically the estimator's: the two
    # hands read different materials and the cut file broke the tie, so somebody confirms the
    # material before it goes out firm. No file from the drawing office settles that.
    assert engine_discoveries.classify("handed_pair_settled_on_cut_file") != "engine"
    assert engine_discoveries.classify("handed_pair_settled_on_cut_file") == "estimator"
    line = estimating_review._line({"code": "handed_pair_settled_on_cut_file",
                                    "severity": "warning", "message": "x"})
    assert line["bucket"] == estimating_review.CONFIRM


def test_a_pair_settled_by_weight_of_evidence_is_not_a_cut_file_proviso():
    """The proviso is ONLY for the even split broken by the export. A pair settled because one
    side had MORE readings is a firmer decision and must not raise this flag."""
    base = _from("28A", [(MAT, "ABS", "solidworks_api"),
                         (MAT, "PETG", "drawing_deterministic"),
                         (MAT, "PETG", "dxf_filename"), (GAUGE, 2.0, "solidworks_api")])
    hand = _from("28A-HANDED", [(MAT, "ABS", "solidworks_api"), (GAUGE, 2.0, "solidworks_api")])
    merge.settle_handed_pairs([base, hand])
    summary = {"parts": [base, hand]}
    assert invariants.check_a_handed_pair_priced_on_the_cut_file(summary) == []
