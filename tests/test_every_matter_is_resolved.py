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
