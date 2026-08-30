"""Every matter is resolved, and the disagreement still travels with the decision.

An equal-rank disagreement used to produce STATUS_UNVERIFIED. That is not a decision, it is
the absence of one -- and it was handed downstream to a reader with strictly less to go on
than the arbiter had. Nothing prices an UNVERIFIED operation, so an unsettled tie left the
shop doing work nobody charged for. A metadata disagreement was worse: any conflict at all,
even about an operation's SEQUENCE, demoted the whole operation to UNVERIFIED, so an
argument about WHEN something happens deleted the fact THAT it happens.

The arbiter now decides. What must not be lost is that it was contested: `contested`,
`losing_statuses`, the `conflicts` record and its `resolution` string all survive, so a
report can say "resolved over an objection" rather than presenting a settled tie as
unanimous. Those are different facts and an estimator should be able to tell them apart --
a decision taken over an objection is the first one worth looking at.

REPRODUCIBILITY IS PART OF THE CONTRACT. The tiebreak ends in claim_id precisely so the
same job compiles to the same route twice. "Same code, same pack, same answer" is the
property the whole parallel run rests on, and an arbiter that resolved by wall-clock or
dict order would destroy it here, invisibly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import route_compiler as rc                                         # noqa: E402
import source_precedence as sp                                      # noqa: E402
from route_compiler import (REQUIRED, RULED_OUT, UNVERIFIED,        # noqa: E402
                            arbitrate_event, make_claim)


def _claim(status, source, **kw):
    return make_claim("folding", status, source, "04M", "04M", **kw)


# ── every matter is resolved ────────────────────────────────────────────────────────
def test_an_equal_rank_disagreement_is_settled():
    d = arbitrate_event("d1", [_claim(REQUIRED, "dxf"), _claim(RULED_OUT, "dxf")])
    assert d.status in (REQUIRED, RULED_OUT)
    assert d.status != UNVERIFIED, \
        "an unpriced UNVERIFIED operation is how real work comes off the sheet"


def test_a_settled_tie_still_says_it_was_a_tie():
    d = arbitrate_event("d1", [_claim(REQUIRED, "dxf"), _claim(RULED_OUT, "dxf")])
    assert d.contested is True
    assert d.losing_statuses, "what the other source claimed must survive the resolution"
    assert d.status not in d.losing_statuses
    conflict = next((c for c in d.conflicts if c.get("field") == "status"), None)
    assert conflict is not None
    assert conflict.get("resolution"), \
        "the record must say HOW it was settled, not merely that it was"
    assert sorted(conflict["sources"]) == ["dxf"]


def test_an_uncontested_decision_does_not_claim_to_be_contested():
    """The flag has to mean something. If everything reads as contested, nothing does."""
    d = arbitrate_event("d1", [_claim(REQUIRED, "dxf"), _claim(REQUIRED, "dxf")])
    assert d.contested is False
    assert d.losing_statuses == []
    assert d.conflicts == []


def test_rank_still_decides_before_any_tiebreak():
    """Resolving ties must not have loosened the waterfall. A measured negative still
    beats an inferred positive on rank alone, and confidence must not rescue it."""
    weak_yes = _claim(REQUIRED, "inference", confidence="high")
    measured_no = _claim(RULED_OUT, "dxf", reason="DXF measured zero bend lines")
    d = arbitrate_event("d1", [weak_yes, measured_no])
    assert d.status == RULED_OUT
    assert d.contested is False, "a rank difference is not a tie"


# ── the tiebreak is principled, not a coin flip ─────────────────────────────────────
def test_the_claim_that_quotes_the_drawing_wins_an_equal_rank_tie():
    """SELF-CALIBRATING, because the first version of this passed by luck.

    Written the obvious way -- one bare claim, one quoted claim, assert the quoted one wins
    -- it passed with the evidence rule DELETED: the tiebreak fell through to claim_id and
    the quoted claim happened to sort first anyway. A mutation showed it. So: find out
    which claim wins on claim_id alone with neither quoting, then hand the quote to the
    OTHER one. Only the evidence rule can flip that, and if it is removed this fails.
    """
    a = _claim(REQUIRED, "dxf")
    b = _claim(RULED_OUT, "dxf")
    baseline = arbitrate_event("d1", [a, b]).status
    loser_status = RULED_OUT if baseline == REQUIRED else REQUIRED

    quoted_loser = _claim(loser_status, "dxf", evidence="NO BEND LINES ON FLAT PATTERN",
                          evidence_where="sheet 2 note")
    winner_bare = a if baseline == REQUIRED else b
    flipped = arbitrate_event("d1", [winner_bare, quoted_loser])

    assert flipped.status == loser_status, (
        "a claim that can be held against the drawing must beat one that cannot -- "
        f"baseline went to {baseline!r} and quoting {loser_status!r} did not flip it")


def test_confidence_outranks_evidence():
    """Order matters: a claim's own stated certainty is a stronger signal than the mere
    presence of a quote, so confidence is asked first."""
    conf = _claim(REQUIRED, "dxf", confidence="high")
    quoted = _claim(RULED_OUT, "dxf", evidence="NO BEND LINES")
    assert arbitrate_event("d1", [conf, quoted]).status == REQUIRED


@pytest.mark.parametrize("order", [False, True])
def test_the_resolution_does_not_depend_on_claim_order(order):
    """Same code, same pack, same answer -- the property the parallel run rests on. An
    arbiter that resolved by arrival order would break it here and nowhere visible."""
    a, b = _claim(REQUIRED, "dxf"), _claim(RULED_OUT, "dxf")
    claims = [b, a] if order else [a, b]
    assert arbitrate_event("d1", claims).status == arbitrate_event("d1", [a, b]).status


def test_one_ordering_settles_status_and_metadata():
    """Status and metadata resolved by different rules would let a decision describe one
    claim and its quantity describe another."""
    src = Path(rc.__file__).read_text(encoding="utf-8")
    assert src.count("_resolution_key") >= 4, \
        "a call site has stopped using the shared ordering"


# ── metadata conflicts resolve too ──────────────────────────────────────────────────
def test_a_contested_quantity_is_resolved_not_defaulted():
    """The worst version of the old behaviour: a disagreement about how many times an
    operation happens returned None, and None then took the compiler's default of 1.0 --
    so the argument was settled by a constant that had read neither claim."""
    two = _claim(REQUIRED, "dxf", qty_per_unit=2, confidence="high")
    five = _claim(REQUIRED, "dxf", qty_per_unit=5)
    d = arbitrate_event("d1", [two, five])
    assert d.qty_per_unit == 2.0, "the stronger claim's quantity must be taken"
    assert d.field_provenance.get("qty_per_unit") != "compiler_default", \
        "a contested quantity was answered by a default that read neither claim"
    assert any(c.get("field") == "qty_per_unit" for c in d.conflicts)
    assert d.contested is True


def test_a_disagreement_about_sequence_does_not_delete_the_operation():
    """An argument about WHEN an operation happens is not doubt about WHETHER it happens.
    Answering the second question with the first is how real work left the sheet."""
    a = _claim(REQUIRED, "dxf", sequence=10, confidence="high")
    b = _claim(REQUIRED, "dxf", sequence=90)
    d = arbitrate_event("d1", [a, b])
    assert d.status == REQUIRED, "the operation survived a dispute about its ordering"
    assert d.sequence == 10.0


def test_the_reason_an_estimator_reads_names_the_disagreement():
    d = arbitrate_event("d1", [_claim(REQUIRED, "dxf"), _claim(RULED_OUT, "dxf")])
    assert "resolved over a disagreement" in (d.reason or "")
    assert "status" in (d.reason or "")


# ── where the decision was taken ────────────────────────────────────────────────────
@pytest.mark.parametrize("source,expected", [
    ("solidworks_api", "the SolidWorks model"),
    ("solidworks_flat_pattern", "the SolidWorks flat pattern"),
    ("dxf_flat_pattern", "the DXF flat pattern"),
    ("llm_full_extract", "Grok (xAI)"),
    ("estimator_confirmed", "an estimator"),
    ("mirror_of_measured", "the measured opposite hand"),
])
def test_a_decision_names_where_it_was_taken(source, expected):
    d = arbitrate_event("d1", [_claim(REQUIRED, source)])
    assert d.decided_by == expected, \
        "a report that cannot say a model decided this cannot be checked against the model"


def test_an_unfamiliar_source_still_prints_something():
    """Printing nothing is the failure this exists to prevent: a blank reads as 'nobody
    decided', which is the one thing it never means."""
    assert sp.display_name("some_new_reader") == "some new reader"
    assert sp.display_name("") == ""


def test_every_ranked_source_has_a_display_name():
    """A source the waterfall ranks but the reports cannot name renders as a blank in the
    one document written to explain the decision."""
    missing = sorted(k for k in sp.SOURCE_RANK if k not in sp.SOURCE_DISPLAY_NAME)
    assert not missing, f"ranked but unnameable: {missing}"


def test_measured_and_reasoned_are_distinguishable():
    """The whole point of the waterfall. A number off a model can be held against the
    model; a number off a language model cannot."""
    assert sp.was_measured("solidworks_api")
    assert sp.was_measured("dxf_flat_pattern")
    assert not sp.was_measured("llm_full_extract")
    assert not sp.was_measured("inference")
    assert not sp.was_measured("")


def test_no_module_keeps_a_private_source_name_table():
    """A private copy of a rule that exists elsewhere is how two readers of one job come
    to disagree about what it says."""
    for mod in ("job_decision_report.py", "route_compiler.py"):
        src = (Path(rc.__file__).parent / mod).read_text(encoding="utf-8")
        assert '"the SolidWorks flat pattern"' not in src, \
            f"{mod} has grown its own copy of the source-name table"


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── the secondary key: within-rank source priority ──────────────────────────────────
# OPTION 1, AND WHY IT IS THE FIRST KEY RATHER THAN THE ONLY ONE.
#
# "SolidWorks beats xAI" is not this rule — that is the RANK, 90 against 40, and putting
# it here as well would be a second copy of the waterfall free to drift out of step with
# the first. Only six pairs share a rank at all, and this orders those. It cannot touch
# the commonest tie of all, which is one source disagreeing with ITSELF.
@pytest.mark.parametrize("winner,loser", [
    ("estimator_confirmed", "knowledge_base"),      # a person beats a stored default
    ("solidworks_flat_pattern", "solidworks_api"),  # the blank beats the finished part
    ("dxf_flat_pattern", "dxf"),
    ("title_block", "drawing_deterministic"),       # a controlled field beats body text
    ("llm_full_extract", "llm_extract"),            # the pack beats one page
    ("geometry_inference", "inference"),            # resting on something beats resting on nothing
])
def test_within_rank_source_priority_settles_the_pair(winner, loser):
    assert sp.SOURCE_RANK[winner] == sp.SOURCE_RANK[loser], \
        "these do not share a rank, so this pair proves nothing about the tiebreak"
    d = arbitrate_event("d1", [_claim(RULED_OUT, loser), _claim(REQUIRED, winner)])
    assert d.status == REQUIRED and d.source == winner


def test_the_tiebreak_never_reaches_across_a_rank():
    """The one thing it must never do. A within-rank ordering that could outrank the
    waterfall would quietly become a second, competing precedence table."""
    d = arbitrate_event("d1", [_claim(REQUIRED, "llm_full_extract"),   # priority 2, rank 40
                               _claim(RULED_OUT, "dxf")])              # priority 1, rank 80
    assert d.status == RULED_OUT, "a within-rank preference outranked the waterfall"


def test_an_unlisted_source_falls_through_rather_than_scoring_high():
    """An ordering nobody can justify is worse than none. A new source must not win ties
    by accident simply because it is missing from the table."""
    assert sp.tiebreak_priority("some_new_reader") == 0
    assert sp.tiebreak_priority("") == 0


def test_the_tiebreak_table_only_contains_sources_that_share_a_rank():
    """An entry for a source with a rank to itself can never fire, and reads as a rule
    that is doing something when it is not."""
    from collections import Counter
    shared = {s for s, n in Counter(sp.SOURCE_RANK.values()).items() if n > 1}
    for source in sp.SOURCE_TIEBREAK:
        assert sp.SOURCE_RANK.get(source) in shared, \
            f"{source} has its own rank, so its tiebreak entry can never fire"


def test_required_is_deliberately_not_preferred_over_ruled_out():
    """THE OPTION THAT WAS REJECTED, guarded so it cannot be added back by instinct.

    Preferring 'required' sounds prudent and is a systematic bias toward charging for work
    that was ruled out on evidence. It would have kept the powder line on 11650's PETG
    panels -- the exact failure this month's work removed. Here two claims are identical
    but for their status and their source priority, and the LOW-priority source says
    required: if status were a key, required would win.
    """
    d = arbitrate_event("d1", [_claim(REQUIRED, "dxf"),                 # priority 1
                               _claim(RULED_OUT, "dxf_flat_pattern")])  # priority 2
    assert d.status == RULED_OUT, \
        "status is being used as a tiebreak -- that is a bias toward charging"


# ── which key settled it ────────────────────────────────────────────────────────────
# THE AUDIT TRAIL FOR THE EVERY-MATTER-RESOLVED RULE. "Resolved" alone does not say whether
# the drawing's own words decided it or a reproducibility backstop did, and those deserve
# very different amounts of trust from an estimator tuning the engine.
#
# This test exists because a mutation showed the gap: the HTML report's own tests fed
# settled_by_key in as fixture data, so blanking it in the compiler broke nothing. A field
# asserted only where it is handed to the renderer is not asserted at all.
def test_a_contested_decision_names_the_key_that_settled_it():
    d = arbitrate_event("d1", [_claim(REQUIRED, "dxf"), _claim(RULED_OUT, "dxf")])
    assert d.contested and d.settled_by_key, \
        "a contested decision does not say which key settled it"
    assert d.settled_by_key in rc.RESOLUTION_KEYS
    conflict = next(c for c in d.conflicts if c.get("field") == "status")
    assert conflict.get("settled_by") == d.settled_by_key, \
        "the decision and its conflict record disagree about how it was settled"


def test_an_uncontested_decision_names_no_key():
    """The field has to mean something. A key on every decision would say nothing about
    which ones the arbiter actually had to choose in."""
    d = arbitrate_event("d1", [_claim(REQUIRED, "dxf"), _claim(REQUIRED, "dxf")])
    assert d.settled_by_key == ""


@pytest.mark.parametrize("winner,loser,expected", [
    # separated by the source itself
    (_claim(REQUIRED, "dxf_flat_pattern"), _claim(RULED_OUT, "dxf"),
     "within-rank source priority"),
    # same source, separated by stated certainty
    (_claim(REQUIRED, "dxf", confidence="high"), _claim(RULED_OUT, "dxf"),
     "confidence"),
    # same source, same certainty, separated by the drawing's own words
    (_claim(REQUIRED, "dxf", evidence="4 BEND LINES"), _claim(RULED_OUT, "dxf"),
     "quotes the drawing"),
])
def test_the_named_key_is_the_one_that_actually_separated_them(winner, loser, expected):
    d = arbitrate_event("d1", [loser, winner])
    assert d.settled_by_key == expected, \
        f"reported {d.settled_by_key!r}, but {expected!r} is what separated the claims"


def test_a_pure_coin_flip_admits_to_being_one():
    """Two identical claims differing only in status are settled by claim_id, and the
    report must say so rather than implying evidence decided it. This is the case an
    estimator most needs to see, because it means the engine had nothing to go on."""
    d = arbitrate_event("d1", [_claim(REQUIRED, "dxf"), _claim(RULED_OUT, "dxf")])
    assert "claim id" in d.settled_by_key, \
        "a decision with no distinguishing evidence is claiming a reason it did not have"
