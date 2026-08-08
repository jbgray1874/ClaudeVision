"""The BOM is read twice and the route is not.

A BOM row only one reader saw is emitted, flagged, and blocked when it carries real money.
The route has had no equivalent: an operation the model reasoned and an operation measured
off a cut list both arrive as REQUIRED, distinguishable only by a rank number nothing
downstream weighed.

A decision is corroborated when some claim behind it was READ — a bend count, a weld
symbol, a finish note, a cut-list property — or quotes the drawing's own words.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import invariants  # noqa: E402
import route_compiler as rc  # noqa: E402


# ---------------------------------------------------------------------------
# A claim can quote the drawing
# ---------------------------------------------------------------------------
def test_a_claim_carries_the_drawings_own_words():
    claim = rc.make_claim("powder_coating", rc.REQUIRED, "llm_full_extract",
                          "12392-02-02M", "12392-02-02M",
                          evidence="POWDER COATED - 30% GLOSS",
                          evidence_where="detail sheet note")
    assert claim.evidence == "POWDER COATED - 30% GLOSS"
    assert claim.evidence_where == "detail sheet note"


def test_evidence_is_whitespace_normalised_and_bounded():
    """A quote wrapped across a note's lines is the same quote, and a runaway paste is
    not allowed to become the field."""
    claim = rc.make_claim("fold", rc.REQUIRED, "llm_full_extract", "X", "X",
                          evidence="POWDER\n  COATED   -  30% GLOSS")
    assert claim.evidence == "POWDER COATED - 30% GLOSS"
    assert len(rc.make_claim("f", rc.REQUIRED, "s", "X", "X",
                             evidence="A" * 999).evidence) == 300


def test_a_claim_with_no_evidence_says_nothing_rather_than_none():
    assert rc.make_claim("fold", rc.REQUIRED, "dxf", "X", "X").evidence == ""


# ---------------------------------------------------------------------------
# The invariant that weighs it
# ---------------------------------------------------------------------------
def _job(corroborated, value=8.0, other=2.0):
    return {
        "canonical_route": {"decisions": [
            {"operation": "weld", "target_id": "12392-02-01M", "status": "required",
             "corroborated": corroborated, "source": "llm_full_extract"},
            {"operation": "fold", "target_id": "12392-02-02M", "status": "required",
             "corroborated": True, "source": "dxf"},
        ]},
        "final_estimate": {"labour_rows": [
            {"operation": "weld", "total_value_gbp": value},
            {"operation": "fold", "total_value_gbp": other},
        ]},
    }


def test_uncorroborated_labour_is_named_and_priced():
    out = invariants.check_uncorroborated_route_operations(_job(False))
    assert len(out) == 1
    d = out[0]["detail"]
    assert d["count"] == 1 and d["value_gbp"] == 8.0
    assert d["share_pct"] == 80.0


def test_a_large_share_blocks():
    out = invariants.check_uncorroborated_route_operations(_job(False, value=8.0, other=2.0))
    assert out[0]["severity"] == invariants.BLOCKING


def test_a_small_share_warns_rather_than_blocks():
    out = invariants.check_uncorroborated_route_operations(_job(False, value=1.0, other=20.0))
    assert out[0]["severity"] == invariants.WARNING


def test_a_route_everything_read_is_silent():
    """Mutation guard. If this fires on a fully-corroborated route it means nothing when
    it fires at all."""
    assert invariants.check_uncorroborated_route_operations(_job(True)) == []


def test_a_job_with_no_canonical_route_is_left_to_the_check_that_owns_it():
    """Absence of a canonical route is check_canonical_route_shadow's finding, not this
    one's. Reporting it here made every complete, consistent job unreleasable over a
    route this check was never given."""
    assert invariants.check_uncorroborated_route_operations({
        "final_estimate": {"labour_rows": [{"operation": "weld", "total_value_gbp": 8.0}]},
    }) == []


# ---------------------------------------------------------------------------
# The compiler's own verdict, not a fixture's
# ---------------------------------------------------------------------------
# Every test above hands the invariant a decision with `corroborated` already set, which
# proves the weighing and nothing about whether the compiler ever computes it. Forcing
# _corroborated to True left them all passing.
def _decide(claims):
    return rc.arbitrate_event("decision:test", claims)


def test_the_compiler_marks_a_reasoned_operation_uncorroborated():
    claims = [rc.make_claim("welding", rc.REQUIRED, "llm_full_extract",
                            "12392-02-01M", "12392-02-01M")]
    assert _decide(claims).corroborated is False


def test_the_compiler_marks_a_measured_operation_corroborated():
    claims = [rc.make_claim("folding", rc.REQUIRED, "dxf_flat_pattern",
                            "12392-02-02M", "12392-02-02M")]
    d = _decide(claims)
    assert d.corroborated is True


def test_quoting_the_drawing_corroborates_a_reasoned_claim():
    """The whole reason the evidence field exists: a claim that quotes the sheet has been
    checked against the sheet by the act of quoting it."""
    claims = [rc.make_claim("powder_coating", rc.REQUIRED, "llm_full_extract",
                            "12392-02-02M", "12392-02-02M",
                            evidence="POWDER COATED - 30% GLOSS")]
    d = _decide(claims)
    assert d.corroborated is True
    assert d.evidence == "POWDER COATED - 30% GLOSS"


def test_a_zero_value_operation_is_not_worth_interrupting_for():
    job = _job(False, value=0.0, other=5.0)
    assert invariants.check_uncorroborated_route_operations(job) == []


def test_the_check_is_registered():
    assert invariants.check_uncorroborated_route_operations in invariants.CHECKS
