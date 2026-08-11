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

THREE FACTS THIS FILE KEEPS APART, and the middle one was got WRONG the first time:
  * "the route says this part is not coated"     -- a decision. Obey it.
  * "a COMPLETE route required no powder"        -- also a decision. Under the canonical
                                                    cutover the compiler considers powder
                                                    for every part, so its silence rules.
  * "there is no compiled route / no cutover"    -- no authority. Geometry path unchanged.

The middle line originally read "not a decision, do not delete a line over it", keyed on
whether any powder decision appeared. 11650-05 re-ran with that logic and STILL booked
GBP 0.97: nothing on the job says POWDER, so the compiler emitted no powder decision, so the
helper returned None, so the geometry path ran exactly as before. The safety valve swallowed
the fix it was guarding. It was asking the wrong question -- what needs protecting is a
route compiled by something that never knew about powder, and that is precisely what "the
cutover is not active" means.
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
    """A cutover route full of welding and folding and no powder has RULED: nothing coated.
    This asserted None before the 11650-05 re-run showed that None let the phantom through."""
    out = coated(_summary([_decision("welding", "required", "A1"),
                           _decision("folding", "required", "A2")]))
    assert out == set(), "a complete route requiring no powder must coat nothing"


# ── silence is not a ruling ─────────────────────────────────────────────────────────
def test_a_route_without_the_cutover_returns_none(monkeypatch):
    """None and empty-set are different facts and only one of them may delete a line. The
    distinction is now keyed on whether the CUTOVER is active -- i.e. whether the compiler
    was the authority on this job -- rather than on whether a powder decision happens to
    appear, which is the same question asked properly.

    The cutover is a GLOBAL config flag, not a property of the payload, so "legacy" can
    only be expressed by turning it off. A test that tried to express it by omitting a key
    from the payload proved nothing, because the flag was still on."""
    import config
    monkeypatch.setattr(config, "CANONICAL_ROUTE_WORKBOOK_CUTOVER", False, raising=False)
    assert coated(_summary([_decision("welding", "required", "A1")])) is None


def test_a_job_with_no_compiled_route_returns_none():
    assert coated(_summary(None)) is None
    assert coated(_summary(present=False)) is None
    assert coated({}) is None


def test_a_decision_list_that_is_not_a_list_returns_none():
    assert coated({"estimate_summary": {"canonical_route_shadow":
                                        {"decisions": "broken"}}}) is None


def test_none_and_empty_set_are_distinguishable(monkeypatch):
    """The whole safety of this change rests on the caller being able to tell them apart."""
    import config
    ruled = coated(_summary([_decision("powder_coating", "ruled_out", "A1")]))
    monkeypatch.setattr(config, "CANONICAL_ROUTE_WORKBOOK_CUTOVER", False, raising=False)
    no_authority = coated(_summary([_decision("welding", "required", "A1")]))
    assert ruled == set() and no_authority is None
    assert ruled is not None


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


# ── the safety valve that swallowed the fix ─────────────────────────────────────────
# THE RE-RUN THAT PROVED THE FIRST FIX DID NOT FIRE. 11650-05 ran again after the Option 3
# wiring landed and still booked GBP 0.97 of powder. Nothing on that job says POWDER, so
# the compiler emitted no powder decision, so parts_the_route_says_are_coated returned None
# ("no ruling"), so the geometry path ran exactly as it had before. The valve I added to
# protect legacy routes swallowed the fix it was meant to guard.
#
# It was asking the wrong question. What needs protecting is a route compiled by something
# that did not know about powder -- and that is exactly what "the cutover is not active"
# means. Under cutover the compiler considers powder for every part, so its silence is a
# ruling, not an absence.
def _cutover(decisions):
    return {"estimate_summary": {"canonical_route_shadow": {
        "cutover": True, "decisions": list(decisions), "nodes": []}}}


def test_a_complete_route_with_no_powder_decision_means_not_coated():
    """The live failure, as a test. Under cutover, silence is a ruling."""
    out = coated(_cutover([_decision("welding", "required", "A1")]))
    assert out == set(), \
        "a cutover route that required no powder still let the geometry path book mass"


def test_a_job_with_no_cutover_still_falls_through_to_geometry(monkeypatch):
    """The valve is still needed -- just on the right question. A route compiled by
    something that never knew about powder has not ruled against it, and stripping powder
    from those jobs would be a large, quiet under-charge."""
    import config
    monkeypatch.setattr(config, "CANONICAL_ROUTE_WORKBOOK_CUTOVER", False, raising=False)
    assert coated(_summary([_decision("welding", "required", "A1")])) is None, \
        "legacy behaviour was removed along with the bug"


def test_a_cutover_route_that_requires_powder_still_names_its_parts():
    out = coated(_cutover([_decision("powder_coating", "required", "A1"),
                           _decision("welding", "required", "A2")]))
    assert out == {"A1"}


# ── you cannot coat what you did not buy material for ───────────────────────────────
# The other half of the same GBP 0.97. 11650-05's two -HANDED records are derived from
# assembly pages, carry no stock form and no material, and every material block skips them
# as unclassifiable -- and they still contributed 0.48 m2 of coated area between them,
# which was the whole of the phantom line.
from wb_populate import _no_material_was_costed                      # noqa: E402


def test_a_record_with_no_stock_form_and_no_material_is_not_coatable():
    assert _no_material_was_costed(
        {"part_number": "11650-04-01A-HANDED",
         "material_estimate": {"stock_form": ""}, "normalized_material": ""})


def test_an_unmeasured_sheet_part_is_still_coatable():
    """DELIBERATELY NARROW. A sheet part whose blank has not been measured yet is real
    material and still gets coated -- that is a missing dimension, not a missing part, and
    resolving the two the same way would silently drop powder from every job awaiting
    dimensions."""
    assert not _no_material_was_costed(
        {"material_estimate": {"stock_form": "sheet"}, "normalized_material": "MILD STEEL"})
    assert not _no_material_was_costed(
        {"material_estimate": {"stock_form": "sheet"}, "normalized_material": ""})
    assert not _no_material_was_costed(
        {"material_estimate": {"stock_form": ""}, "normalized_material": "MILD STEEL"})


def test_the_guard_is_applied_to_the_area_sum_and_the_floor():
    """The floor needs no geometry at all to produce a number, so a guard on the area sum
    alone leaves the phantom intact by another route."""
    assert _SRC.count("_no_material_was_costed(") >= 3, \
        "the guard is not applied to both the coated-area sum and the per-piece floor"
