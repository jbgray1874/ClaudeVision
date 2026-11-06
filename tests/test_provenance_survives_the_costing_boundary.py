"""A fact that crosses into the costed record brings its source with it, and a mirror that
declines says why.

TWO FINDINGS FROM ONE DIAGNOSTIC RUN ON 11650-04, both of the same family: the record was asked
a question it could have answered and returned an absence instead.

  (1) estimate_part builds a PROJECTION of the raw part, copying selected keys. It copied
      normalized_material and normalized_thickness_mm and left material_source, thickness_source,
      quantity_source and _displaced behind. So every reader past the costing boundary is
      provenance-blind: the diagnostic printed "(no source recorded)" for material, gauge and
      quantity on all four side panels, while the RAW records carried mirror_of_measured, a DXF
      reading, and a recorded refusal between them.

      This is the THIRD AND FOURTH time a fact has stopped at that boundary. geometry_rollup and
      page_roles are both in the same return statement, each with its own comment about a reader
      that asked the costed record a question only the raw record could answer. Those cost a
      laser rate and a dropped bought-in line. This one cost a round of diagnosis aimed at a
      mirror rule that had, in fact, fired and written its provenance down.

  (2) apply_mirror_geometry refuses to inherit from a base that was never measured — correctly,
      because doing so would launder a guess into geometry at rank 75. It refused with a bare
      `continue`. So a hand the rule DECLINED was indistinguishable on the record from a hand
      the rule never saw, and the only honest thing that could be said about 11650-04-03A-HANDED
      was "either it never fired, or it fired and recorded nothing". Those two readings lead
      opposite ways.

ONE WRITER PER FACT is not achieved by writing it once. It is achieved by the one record every
downstream reader consults carrying it.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import drawing_job_merge as djm  # noqa: E402
import estimator  # noqa: E402
import source_precedence as sp  # noqa: E402


def _raw_part(**over):
    part = {
        "part_number": "11650-04-01A",
        "description": "SIDE PANEL",
        "quantity": 2,
        "normalized_material": "ABS",
        "material_source": "solidworks_api",
        "normalized_thickness_mm": 2.2,
        "thickness_source": "title_block",
        "quantity_source": "bom_tree",
        "page_roles": ["detail"],
        "normalized_geometry": {},
        "manufacturing_interpretation": {},
        "material_estimate": {},
        "_displaced": {"normalized_material": [
            {"value": "PETG", "source": "title_block"},
            {"value": "PETG", "source": "drawing_deterministic"},
        ]},
    }
    part.update(over)
    return part


# ── (1) provenance crosses the costing boundary ─────────────────────────────────────

def test_every_arbitrated_fact_crosses_costing_with_its_source():
    """Driven off the resolver, not a list typed into the test — a fourth arbitrated field
    must fail here rather than cross the boundary as a value with no source and read as a
    guess."""
    costed = estimator.estimate_part(_raw_part())
    for field, source_key in sp._SOURCE_FIELDS.items():
        assert costed.get(source_key), (
            f"{field} reached the costed record and {source_key} did not — every reader past "
            f"this point sees the value and cannot tell a model from a guess")


def test_the_source_that_crosses_is_the_source_that_was_recorded():
    """A key that is present but wrong is worse than absent: it reads as attribution."""
    costed = estimator.estimate_part(_raw_part())
    assert costed["material_source"] == "solidworks_api"
    assert costed["thickness_source"] == "title_block"
    assert costed["quantity_source"] == "bom_tree"
    assert sp.rank(costed["material_source"]) == 90


def test_what_the_winner_beat_crosses_too():
    """_displaced is the entire evidence base for asking whether independent lower-ranked
    sources agreed against a lone higher-ranked one — the door's ABS-over-polycarbonate, the
    side panel's ABS-over-PETG. Left behind, that question can be asked before costing and
    never explained after."""
    costed = estimator.estimate_part(_raw_part())
    against = sp.corroboration_against(costed, "normalized_material")
    assert against["count"] == 2
    assert against["value"] == "PETG"
    assert against["sources"] == ["drawing_deterministic", "title_block"]


def test_a_part_with_no_provenance_gains_no_invented_provenance():
    """The copy must not manufacture keys. An empty source key is attribution to nobody, and
    a reader cannot tell it from a source it does not recognise."""
    bare = _raw_part()
    for key in ("material_source", "thickness_source", "quantity_source", "_displaced"):
        bare.pop(key, None)
    costed = estimator.estimate_part(bare)
    for key in ("material_source", "thickness_source", "quantity_source", "_displaced"):
        assert key not in costed, f"{key} was invented on a record that never had one"


def test_the_costed_record_can_be_asked_the_same_question_as_the_raw_one():
    """THE POINT. Not that the keys exist, but that the shared resolver gives the same answer
    on both records — that is what "one record every reader consults" means."""
    raw = _raw_part()
    costed = estimator.estimate_part(raw)
    for field in sp._SOURCE_FIELDS:
        assert sp.source_of(costed, field) == sp.source_of(raw, field), field


def test_the_document_records_the_build_that_wrote_it():
    """TESTED ON THE WRITER, NOT THE READER. The diagnostic's own tests hand it a stamp and
    check it reads it — which passes perfectly while the engine writes none, and the question
    "which build produced this estimate" stays unanswerable on every real run.
    """
    doc = estimator.estimate_document([_raw_part()], {})
    stamp = doc.get("engine_build")
    assert isinstance(stamp, dict), "no build stamp on the estimate this engine just wrote"
    assert stamp.get("known") is True and stamp.get("commit")
    assert set(stamp) >= {"commit", "branch", "dirty", "subject", "known"}


# ── (2) a refused mirror says why ────────────────────────────────────────────────────

def _pair(base_over=None, twin_over=None):
    base = {
        "part_number": "11650-04-03A",
        "page_roles": ["detail"],
        "normalized_geometry": dict(base_over or {}),
    }
    twin = {"part_number": "11650-04-03A-HANDED", "page_roles": ["assembly"],
            "normalized_geometry": {}}
    twin.update(twin_over or {})
    return base, twin


def _refusal(part):
    return " ".join(str(f) for f in (part.get("review_flags") or []))


def test_a_base_nobody_measured_is_refused_and_the_refusal_is_on_the_record():
    """The rule is RIGHT to refuse: inheriting geometry whose own source is weaker than a DXF
    would turn that reading into measured geometry at rank 75. The defect was refusing in
    silence."""
    base, twin = _pair(base_over={"geometry_source": "llm_extract",
                                  "blank_length_mm": 420.0, "blank_width_mm": 133.0})
    djm.apply_mirror_geometry([base, twin])
    assert "MIRROR NOT APPLIED" in _refusal(twin)
    assert "llm_extract" in _refusal(twin)
    # The machine-readable record has to carry the SAME reason as the sentence. A generic
    # marker beside a specific flag is two answers to one question, which is the family this
    # whole file is about.
    assert "llm_extract" in twin["_mirror_refused"]["11650-04-03A"]


def test_the_machine_readable_refusal_says_the_same_thing_as_the_flag():
    """Three refusals, three remedies, and a downstream reader must be able to tell them apart
    without parsing English."""
    reasons = set()
    for base_over in ({"geometry_source": "llm_extract", "blank_length_mm": 420.0,
                       "blank_width_mm": 133.0},
                      {"geometry_source": "dxf_flat_pattern"}):
        base, twin = _pair(base_over=base_over)
        djm.apply_mirror_geometry([base, twin])
        reason = twin["_mirror_refused"]["11650-04-03A"]
        assert reason in _refusal(twin), "the record and the flag give different reasons"
        reasons.add(reason)
    base, twin = _pair()
    djm.apply_mirror_geometry([twin])
    reasons.add(twin["_mirror_refused"]["11650-04-03A"])
    assert len(reasons) == 3, "the three refusals are indistinguishable to a reader"


def test_a_base_that_is_not_in_the_pack_is_named_as_the_reason():
    base, twin = _pair()
    djm.apply_mirror_geometry([twin])  # base absent from the job entirely
    assert "MIRROR NOT APPLIED" in _refusal(twin)
    assert "no part numbered 11650-04-03A is in this job" in _refusal(twin)


def test_a_measured_base_with_no_developed_size_says_that_and_not_something_else():
    """Three refusals, three different remedies: export the base, add the drawing, or develop
    the flat. A single generic 'not applied' would send the estimator after the wrong one."""
    base, twin = _pair(base_over={"geometry_source": "dxf_flat_pattern"})
    djm.apply_mirror_geometry([base, twin])
    assert "no flat blank of its own to give" in _refusal(twin)


def test_a_mirror_that_succeeds_records_no_refusal():
    """A flag on a part the rule filled would be a false alarm on every handed pack that
    works — noise is how real flags get ignored."""
    base, twin = _pair(base_over={"geometry_source": "dxf_flat_pattern",
                                  "blank_length_mm": 420.0, "blank_width_mm": 133.0})
    djm.apply_mirror_geometry([base, twin])
    assert "MIRROR NOT APPLIED" not in _refusal(twin)
    assert "_mirror_refused" not in twin


def test_a_part_that_is_not_a_hand_is_never_flagged():
    """mirror_base decides what is a hand. A part the rule does not recognise as one must not
    collect a refusal for a rule that was never about it."""
    plain = {"part_number": "11650-04-03A", "normalized_geometry": {}}
    djm.apply_mirror_geometry([plain])
    assert not plain.get("review_flags")


@pytest.mark.parametrize("spelling", ["11650-04-03A-HANDED", "11650-04-03A MIR",
                                      "Mirror11650-04-03A"])
def test_every_spelling_of_a_hand_gets_the_same_answer(spelling):
    """The index defect was invisible for a year because it broke ONE spelling while two
    others worked. Whatever the rule does, it has to do it for all three."""
    base, twin = _pair(base_over={"geometry_source": "llm_extract",
                                  "blank_length_mm": 420.0, "blank_width_mm": 133.0})
    twin["part_number"] = spelling
    djm.apply_mirror_geometry([base, twin])
    assert "MIRROR NOT APPLIED" in _refusal(twin), spelling


def test_the_refusal_names_the_part_and_the_base_so_it_reads_alone():
    """A flag reaches an estimator with no code beside it. 'Mirror not applied' with no part
    numbers is a sentence nobody can act on."""
    base, twin = _pair(base_over={"geometry_source": "llm_extract",
                                  "blank_length_mm": 420.0, "blank_width_mm": 133.0})
    djm.apply_mirror_geometry([base, twin])
    flag = _refusal(twin)
    assert "11650-04-03A-HANDED" in flag and "11650-04-03A" in flag
    assert "may not agree with the hand it pairs with" in flag


# ── (3) a mirrored hand inherits, it does not gap-fill ───────────────────────────────
#
# 11650-04-01A-HANDED came out of a run with cut_length_mm 3802.9 while the base it mirrors
# measured 7582.17 — half the cut, on the same panel, so the twin laser-costed at a different
# rate from its own mirror image. Its base carried 0 holes and it carried 4.
#
# normalized_geometry was GAP-FILLED: copied only where the twin had nothing. The twin had a
# cut length read off an assembly page, so it was not blank, so the base's measured figure
# never arrived. Then, because something else HAD been filled, the whole node was stamped
# geometry_source = mirror_of_measured — claiming inheritance over the very number that had
# not been inherited.
#
# geometry_rollup, forty lines below in the same function, was corrected to submit each value
# through the resolver, with a comment saying exactly why gap-filling is wrong. The lesson went
# into one loop and not the other.

def _measured_base(**ng):
    base_ng = {"geometry_source": "dxf_flat_pattern",
               "blank_length_mm": 1250.0, "blank_width_mm": 525.0}
    base_ng.update(ng)
    return {"part_number": "11650-04-01A", "page_roles": ["detail"],
            "normalized_geometry": base_ng}


def test_a_measured_base_beats_the_twins_assembly_page_reading():
    base = _measured_base(cut_length_mm=7582.17)
    twin = {"part_number": "11650-04-01A-HANDED", "page_roles": ["assembly"],
            "normalized_geometry": {"cut_length_mm": 3802.9}}
    djm.apply_mirror_geometry([base, twin])
    assert twin["normalized_geometry"]["cut_length_mm"] == 7582.17, (
        "the twin kept an assembly reading over its base's measured cut — it lasers at a "
        "different rate from the part it is a mirror of")


def test_the_twins_own_export_still_wins():
    """The reason to submit rather than overwrite. A hand with its own DXF is not guessing,
    and mirror_of_measured (75) must lose to dxf (80) — exactly as this pair's 2.0mm gauge
    survived its base's 2.2mm, with the disagreement written down."""
    base = _measured_base(cut_length_mm=7582.17)
    twin = {"part_number": "11650-04-01A-HANDED",
            "normalized_geometry": {"cut_length_mm": 3802.9,
                                    "cut_length_mm_source": "dxf_flat_pattern"}}
    djm.apply_mirror_geometry([base, twin])
    assert twin["normalized_geometry"]["cut_length_mm"] == 3802.9
    flags = " ".join(str(f) for f in (twin.get("review_flags") or []))
    assert "NOT applied" in flags and "disagree" in flags, (
        "a refused inheritance between two measurements is the estimator's call and has to "
        "be on the record")


def test_the_node_does_not_claim_a_mirror_it_did_not_do():
    """A node-level source is a claim about every value under it. Stamped on 'something was
    filled', it said mirror_of_measured over a cut length the mirror had not written — the
    record and its own per-field sources disagreeing about one part."""
    base = _measured_base(perimeter_mm=3550.0)
    twin = {"part_number": "11650-04-01A-HANDED",
            "normalized_geometry": {"blank_length_mm": 1250.0, "blank_width_mm": 525.0,
                                    "blank_length_mm_source": "dxf_flat_pattern",
                                    "blank_width_mm_source": "dxf_flat_pattern"}}
    djm.apply_mirror_geometry([base, twin])
    ng = twin["normalized_geometry"]
    assert ng.get("perimeter_mm") == 3550.0, "the gap was still filled"
    assert ng.get("geometry_source") != "mirror_of_measured", (
        "this part kept its own blank — the node is not the base's geometry")
    assert ng.get("mirrored_from") == "11650-04-01A", (
        "which part it mirrors is a fact about it, true either way")


def test_a_hand_with_nothing_of_its_own_takes_the_whole_flat():
    base = _measured_base(cut_length_mm=7582.17, perimeter_mm=3550.0)
    twin = {"part_number": "11650-04-01A-HANDED", "normalized_geometry": {}}
    djm.apply_mirror_geometry([base, twin])
    ng = twin["normalized_geometry"]
    assert ng["blank_length_mm"] == 1250.0 and ng["blank_width_mm"] == 525.0
    assert ng["cut_length_mm"] == 7582.17
    assert ng["geometry_source"] == "mirror_of_measured"


def test_the_mirror_never_copies_the_bases_provenance_as_if_it_were_its_own():
    """Copying geometry_source or a per-field <field>_source off the base would relabel this
    part's numbers as the base's DXF — laundering rank 75 into rank 80 and defeating every
    later arbitration."""
    base = _measured_base(cut_length_mm=7582.17, cut_length_mm_source="dxf_flat_pattern")
    twin = {"part_number": "11650-04-01A-HANDED", "normalized_geometry": {}}
    djm.apply_mirror_geometry([base, twin])
    ng = twin["normalized_geometry"]
    assert ng.get("cut_length_mm_source") == "mirror_of_measured", (
        "the twin's cut length came from the mirror, not from a DXF of its own")
    assert sp.rank(ng["cut_length_mm_source"]) < sp.rank("dxf_flat_pattern")


def test_a_measured_zero_on_the_base_is_a_value_and_travels():
    """0 holes is a measurement, not an absence — the fold rule-out is built on exactly that
    distinction, and treating it as blank gives a flat part its mirror's features."""
    base = _measured_base(hole_count=0)
    twin = {"part_number": "11650-04-01A-HANDED", "normalized_geometry": {}}
    djm.apply_mirror_geometry([base, twin])
    assert twin["normalized_geometry"]["hole_count"] == 0
