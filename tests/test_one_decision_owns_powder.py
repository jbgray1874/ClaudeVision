"""The powder MASS and the powder OPERATION come from one decision.

They did not. The route compiler arbitrates powder_coating as a first-class operation --
ranked, evidenced, conflicts recorded -- and the coated-area sum that produces the POWDER
bill-of-materials line consulted it not at all. It measured every sheet part it could and
applied a per-piece floor, so a job whose route had decided nothing is coated still carried
powder mass. 11650's side panels shipped GBP 0.97 of it -- the only material money on the
sheet -- beside a log line saying nothing in the job carries a POWDER finish.

That log line came from the LEGACY finish gate, and tracing it produced the real finding:
every consumer of that gate sits inside `for pe in ([] if _canonical_cutover else
labour_parts)`. Under the canonical route it decides nothing whatsoever, and went on
printing its conclusions regardless. A gate nobody asks reports nothing; this one reported
anyway, and credible-looking evidence with no authority behind it is worse than silence --
it made a classification bug look like a policy dispute to two readers.

THREE FACTS THIS FILE KEEPS APART:
  * "the route says this part is not coated"  -- a decision. Obey it.
  * "the route said nothing about powder"     -- not a decision. Do not delete a line over
                                                 it, or every job compiled before the
                                                 operation existed loses its powder.
  * "there is no compiled route"              -- legacy. Unchanged behaviour, entirely.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import wb_populate                                                  # noqa: E402
from wb_populate import parts_the_route_says_are_coated as coated   # noqa: E402


def _summary(decisions=None, *, present=True):
    payload = {}
    if decisions is not None:
        payload = {"cutover": True, "decisions": decisions, "nodes": []}
    return {"estimate_summary": {"canonical_route_shadow": payload} if present else {}}


def _decision(operation, status, target, participants=()):
    return {"decision_id": f"d:{operation}:{target}", "operation": operation,
            "status": status, "target_id": target,
            "participants": list(participants)}


# ── the decision is obeyed ──────────────────────────────────────────────────────────
def test_a_required_powder_decision_names_its_target():
    out = coated(_summary([_decision("powder_coating", "required", "11650-02-01A")]))
    assert out == {"11650-02-01A"}


def test_a_ruled_out_powder_decision_coats_nothing():
    """The live failure. The route said no; the mass calc charged anyway."""
    out = coated(_summary([_decision("powder_coating", "ruled_out", "11650-04-01A")]))
    assert out == set(), "a part the route ruled out must not contribute coated area"


def test_an_assembly_decision_coats_its_participants_too():
    """A finish belongs to the object that goes through the booth, and that object is
    often an assembly: you form raw, weld, then coat. Reading target_id alone would drop
    the coating off every weldment's components -- an under-charge on exactly the jobs
    where powder is largest."""
    out = coated(_summary([_decision("powder_coating", "required", "7670-01-101",
                                     participants=["7670-01-02M", "7670-01-03M"])]))
    assert out == {"7670-01-101", "7670-01-02M", "7670-01-03M"}


@pytest.mark.parametrize("spelling", ["powder_coating", "powder_coat", "powder",
                                      "p_coat", "pcoat"])
def test_every_spelling_of_the_operation_is_recognised(spelling):
    """The compiler, the workbook's operation map and the impossibility table each spell
    this differently. A reader that knows one spelling silently ignores the others."""
    assert coated(_summary([_decision(spelling, "required", "X1")])) == {"X1"}


def test_other_operations_do_not_coat_anything():
    out = coated(_summary([_decision("welding", "required", "A1"),
                           _decision("folding", "required", "A2")]))
    assert out is None, "a route that never considered powder has not ruled on it"


# ── silence is not a ruling ─────────────────────────────────────────────────────────
def test_a_route_that_never_considered_powder_returns_none():
    """None and empty-set are different facts and only one of them may delete a line.
    Treating silence as a ruling would strip powder from every job whose route was built
    before the operation existed -- a large, quiet under-charge."""
    assert coated(_summary([_decision("welding", "required", "A1")])) is None


def test_a_job_with_no_compiled_route_returns_none():
    assert coated(_summary(None)) is None
    assert coated(_summary(present=False)) is None
    assert coated({}) is None


def test_a_decision_list_that_is_not_a_list_returns_none():
    assert coated({"estimate_summary": {"canonical_route_shadow":
                                        {"decisions": "broken"}}}) is None


def test_none_and_empty_set_are_distinguishable():
    """The whole safety of this change rests on the caller being able to tell them apart."""
    ruled_none = coated(_summary([_decision("powder_coating", "ruled_out", "A1")]))
    no_ruling = coated(_summary([_decision("welding", "required", "A1")]))
    assert ruled_none == set() and no_ruling is None
    assert ruled_none is not None


# ── every accumulator asks, not just one ────────────────────────────────────────────
_SRC = Path(wb_populate.__file__).read_text(encoding="utf-8")


def test_all_four_powder_accumulators_consult_the_route():
    """Sheet, wire, section and the per-piece floor each add mass independently. One that
    does not ask re-invents exactly the mass the others declined to book -- and the floor
    is the worst of them, because it needs no geometry at all to produce a number."""
    assert _SRC.count("_route_says_coated(") >= 5, (
        "an accumulator is not consulting the route: "
        f"only {_SRC.count('_route_says_coated(')} reference(s) found")


def test_the_legacy_gate_does_not_speak_where_it_has_no_vote():
    """Built is not wired, and its inverse: wired to nothing but still talking. Every
    conclusion the legacy finish gate prints must go through the muted helper, or a job
    running the canonical route gets a second opinion with no authority printed beside
    the arbitrated one."""
    start = _SRC.index("    _assembly_is_powder = False")
    end = _SRC.index("        _finish_is_powder[_pn] = _fin_is_powder(_stated_fin(_mp))")
    block = _SRC[start:end]
    stray = block.count('_flag(f"') + block.count('_flag("') - (
        block.count('_gate_flag(f"') + block.count('_gate_flag("'))
    assert stray == 0, f"{stray} unmuted flag call(s) left in the legacy finish gate"
    assert block.count("_gate_flag(") >= 7, "the gate's conclusions are no longer routed"


def test_the_legacy_path_is_not_silenced_when_it_still_decides():
    """The gate is dead under cutover and LIVE without it. Muting it everywhere would
    remove real findings from every job that has no compiled route."""
    assert "if _canonical_cutover:\n            return\n        _flag(_msg, _fl)" in _SRC, \
        "the mute is unconditional -- legacy jobs have lost their finish findings"


def test_the_run_says_which_authority_decided_powder():
    """An estimator reading the flags must be able to tell an arbitrated decision from a
    measurement. Two mechanisms that can disagree, and no statement of which one ran, is
    how this defect survived as long as it did."""
    assert "decided by the compiled route" in _SRC or \
           "powder follows the compiled route" in _SRC


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
