"""A GATE THAT SKIPS IS NOT A GATE, AND A PIN THAT NEVER RUNS IS NOT A PIN.

Both frozen packs — 7332-01 and 10975-02 — carried accepted_facts.json and no summary.json,
so every replay test SKIPPED. Four skips inside a 4,600-test run is indistinguishable from
four passes, and the packs sat unprotected for weeks while every push reported green. Two
things follow, and this file covers both:

    the MISSING FIXTURE must fail, not skip      — otherwise nobody learns the gate is off
    the PINS must be executable without a pack   — otherwise a pin can be added, never run,
                                                   and believed in

The second is the subtler one. While no pack was frozen, a new accepted-fact check could be
written, committed, and never executed once; it would be indistinguishable from a working
check. So the structural checks live in assert_accepted_structure(), which takes plain record
lines, and every one of them is proved here against a synthetic record that is deliberately
NOT any real job. These fixtures are test scaffolding and must never be mistaken for an
estimator-reviewed baseline: that is what tests/replay/<job>/ and its provenance.json are for.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "replay"))

from test_frozen_replays import (                                        # noqa: E402
    PROVENANCE_FIELDS,
    assert_accepted_structure,
)

REPLAY = ROOT / "tests" / "replay"


def _line(pn: str, **over) -> dict:
    """A costed record line, shaped as costed_facts.costed_job() emits one."""
    line = {"part_number": pn, "qty_per_unit": 1.0, "operations": [],
            "charged_unit_gbp": None, "engine_unit_gbp": 1.0}
    line.update(over)
    return line


# ── the pins catch what they claim ────────────────────────────────────────────────────


def test_a_quantity_pin_catches_a_leg_booked_once_instead_of_twice():
    """Legs x2 is the reviewed expectation. A leg booked once halves its material and its
    labour, and nothing else on the record looks wrong — the line is present and routed."""
    facts = {"quantities": {"X-002": 2}}
    assert_accepted_structure("synthetic", facts, [_line("X-002", qty_per_unit=2.0)])
    with pytest.raises(AssertionError, match="qty 1.0 != accepted 2"):
        assert_accepted_structure("synthetic", facts, [_line("X-002", qty_per_unit=1.0)])


def test_a_quantity_pin_on_a_part_that_vanished_fails_rather_than_passing_vacuously():
    """The bug this guards: `next(..., None)` finding nothing and the loop moving on."""
    with pytest.raises(AssertionError):
        assert_accepted_structure("synthetic", {"quantities": {"X-002": 2}},
                                  [_line("SOMETHING-ELSE")])


def test_material_charged_catches_a_line_that_is_present_routed_and_free():
    """The failure that produced GBP 0 lines. An identity check passes (the line is there), a
    route check passes (it is routed) and the money is still missing."""
    facts = {"material_charged": ["X-002"]}
    assert_accepted_structure("synthetic", facts, [_line("X-002", engine_unit_gbp=12.40)])
    for empty in (0.0, None):
        with pytest.raises(AssertionError, match="no material money reaches it"):
            assert_accepted_structure("synthetic", facts,
                                      [_line("X-002", engine_unit_gbp=empty)])


def test_material_charged_prefers_the_excel_figure_when_there_is_one():
    """charged_unit_gbp is what Excel computed; engine_unit_gbp is the pre-Excel figure. A line
    Excel priced at zero is not rescued by the engine's optimism."""
    with pytest.raises(AssertionError):
        assert_accepted_structure("synthetic", {"material_charged": ["X-002"]},
                                  [_line("X-002", charged_unit_gbp=0.0,
                                         engine_unit_gbp=12.40)])


def test_forbidden_anywhere_catches_a_finish_that_moved_to_another_part():
    """This is why the per-part forbid was not enough. On 7332 the plated and Harrods-1
    finishes were read as powder; ruling powder off part 002 alone would not have caught it
    landing on 101 instead."""
    facts = {"forbidden_operations": {"X-002": ["powder_coating"]},
             "forbidden_operations_anywhere": ["powder_coating"]}
    clean = [_line("X-002", operations=["tubebend"]), _line("X-101", operations=["plating"])]
    assert_accepted_structure("synthetic", facts, clean)
    # ruled off 002, charged on 101 — the per-part pin alone passes this
    moved = [_line("X-002", operations=["tubebend"]),
             _line("X-101", operations=["powder_coating"])]
    assert_accepted_structure("synthetic", {"forbidden_operations":
                                            {"X-002": ["powder_coating"]}}, moved)
    with pytest.raises(AssertionError, match="charged on \\['X-101'\\]"):
        assert_accepted_structure("synthetic", facts, moved)


def test_no_minted_children_catches_a_stock_child_invented_under_a_part():
    """Rather than charging the leg's own tube, a child node is minted beneath it to carry the
    stock — so the money lands twice, or on a node no estimator has ever seen."""
    facts = {"no_minted_children": ["X-002"]}
    assert_accepted_structure("synthetic", facts,
                              [_line("X-002"), _line("X-003")])
    with pytest.raises(AssertionError, match="gained minted child line"):
        assert_accepted_structure("synthetic", facts,
                                  [_line("X-002"), _line("X-002-TUBE")])


def test_no_minted_children_ignores_punctuation_so_a_renaming_cannot_evade_it():
    """X-002/TUBE, X_002_TUBE and X002TUBE are the same mint wearing different punctuation."""
    for name in ("X-002/TUBE", "X_002_TUBE", "X002TUBE", "x-002-stock"):
        with pytest.raises(AssertionError):
            assert_accepted_structure("synthetic", {"no_minted_children": ["X-002"]},
                                      [_line("X-002"), _line(name)])


def test_the_parent_itself_is_not_mistaken_for_its_own_minted_child():
    """The guard on the guard: a prefix test that counts the parent fails every clean job."""
    assert_accepted_structure("synthetic", {"no_minted_children": ["X-002"]}, [_line("X-002")])


def test_a_required_operation_that_disappeared_fails():
    facts = {"required_operations": {"X-002": ["tubebend"]}}
    assert_accepted_structure("synthetic", facts, [_line("X-002", operations=["tubebend"])])
    with pytest.raises(AssertionError, match="required op 'tubebend' absent"):
        assert_accepted_structure("synthetic", facts, [_line("X-002", operations=["folding"])])


def test_a_forbidden_operation_that_reappeared_on_its_own_part_fails():
    facts = {"forbidden_operations": {"X-002": ["folding"]}}
    assert_accepted_structure("synthetic", facts, [_line("X-002", operations=["tubebend"])])
    with pytest.raises(AssertionError, match="ruled-out op 'folding' is charged"):
        assert_accepted_structure("synthetic", facts, [_line("X-002", operations=["folding"])])


def test_bom_identity_drift_is_caught_in_both_directions():
    facts = {"bom_identities": ["X-002", "X-003"]}
    assert_accepted_structure("synthetic", facts, [_line("X-002"), _line("X-003")])
    with pytest.raises(AssertionError, match="BOM drifted"):
        assert_accepted_structure("synthetic", facts, [_line("X-002")])
    with pytest.raises(AssertionError, match="BOM drifted"):
        assert_accepted_structure("synthetic", facts,
                                  [_line("X-002"), _line("X-003"), _line("X-004")])


def test_an_empty_facts_file_pins_nothing_and_raises_nothing():
    """Only what an estimator has reviewed gets pinned; absence must not invent a pin."""
    assert_accepted_structure("synthetic", {}, [_line("ANYTHING")])


# ── the gate itself ───────────────────────────────────────────────────────────────────


def test_every_job_directory_either_is_frozen_or_fails_the_suite():
    """The contract, asserted on the harness rather than on a pack: no code path turns a
    missing fixture into a silent pass. Either the fixture is there, or the run goes red unless
    somebody explicitly set SDI_REPLAY_ALLOW_MISSING."""
    source = (REPLAY / "test_frozen_replays.py").read_text(encoding="utf-8")
    assert "pytest.fail(message)" in source, "a missing fixture must FAIL"
    assert "SDI_REPLAY_ALLOW_MISSING" in source, "with one explicit, named opt-out"
    # and every tier goes through the one loader, so no tier can skip on its own
    assert source.count("_frozen_summary(job)") == 3, \
        "all three tiers must load through the strict loader"


def test_the_unfrozen_packs_are_reported_as_unprotected_right_now():
    """Honesty about today's state: both reviewed packs have accepted facts and no frozen
    record, so neither is protected. This test PASSES while that is true and documents it; it
    is the freeze of each pack that removes the hole, not this file."""
    unfrozen = sorted(d.name for d in REPLAY.iterdir()
                      if d.is_dir() and (d / "accepted_facts.json").is_file()
                      and not (d / "summary.json").is_file())
    assert unfrozen == ["10975-02", "7332-01"], (
        f"the set of unprotected packs changed to {unfrozen} — if a pack was just frozen, "
        f"update this list; if one was added unfrozen, freeze it")


@pytest.mark.parametrize("job", ["7332-01", "10975-02"])
def test_every_reviewed_pack_has_accepted_facts_that_parse(job: str):
    facts = json.loads((REPLAY / job / "accepted_facts.json").read_text(encoding="utf-8"))
    assert isinstance(facts, dict) and facts, f"{job}: accepted facts are empty"
    known = {"_reviewed", "_money_note", "bom_identities", "quantities",
             "required_operations", "forbidden_operations",
             "forbidden_operations_anywhere", "material_charged", "no_minted_children",
             "decisions_expected", "forbidden_names_everywhere", "phrase_counts"}
    unknown = sorted(set(facts) - known)
    assert not unknown, (
        f"{job}: accepted facts carry key(s) {unknown} that no check reads — a pin nobody "
        f"executes reads as protection and is not")


def test_the_reviewed_7332_expectations_are_actually_pinned():
    """The four the estimator named: legs x2, material present, no powder, no stock-child."""
    facts = json.loads(
        (REPLAY / "7332-01" / "accepted_facts.json").read_text(encoding="utf-8"))
    assert facts["quantities"]["7332-01-002"] == 2
    assert "7332-01-002" in facts["material_charged"]
    assert "powder_coating" in facts["forbidden_operations_anywhere"]
    assert "7332-01-002" in facts["no_minted_children"]
    assert "tubebend" in facts["required_operations"]["7332-01-002"]


def test_the_provenance_contract_names_what_a_baseline_has_to_answer():
    """A frozen record with no provenance is an unlabelled number: "the run the estimator
    signed off" and "whichever run last passed" look identical on disk."""
    assert set(PROVENANCE_FIELDS) == {
        "job", "accepted_run", "accepted_by", "accepted_on", "source_path"}


def test_money_is_still_not_pinned_in_the_fast_layer():
    """Rates move; this layer pins structure. £40.89 / £33.59 / £80.09 are reconciled by the
    Windows run with Excel and read-back. A number creeping in here would make the fast layer
    fail on a rate change and teach everyone to edit the baseline."""
    for job in ("7332-01", "10975-02"):
        facts = json.loads(
            (REPLAY / job / "accepted_facts.json").read_text(encoding="utf-8"))
        for key, value in facts.items():
            if key.startswith("_"):
                continue                      # commentary may quote the accepted numbers
            assert "gbp" not in key.lower() and "price" not in key.lower(), \
                f"{job}: '{key}' looks like a money pin in the structure layer"
