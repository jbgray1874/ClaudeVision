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
    with pytest.raises(AssertionError, match="neither routed nor charged"):
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


REVIEWED = sorted(d.name for d in REPLAY.iterdir()
                  if d.is_dir() and (d / "accepted_facts.json").is_file())


def test_the_reviewed_packs_are_the_ones_we_think():
    """Which packs carry estimator-reviewed facts is versioned; whether each is FROZEN is not.

    This used to assert the unfrozen set, which is true in the cloud (records are never
    committed) and false on the laptop the moment a pack is frozen there, so the one place a
    baseline is protected would have gone red for being protected. The frozen state of each
    pack is reported per job by tools/run_replay_baselines.py on the laptop (SCRUM-134); this
    pins only that a pack cannot be added or lost without somebody saying so."""
    assert REVIEWED == ["10975-02", "7332-01"], (
        f"the reviewed packs changed to {REVIEWED}: if a pack was just reviewed, add it here")


KNOWN_KEYS = {"_reviewed", "_review", "_money_note", "bom_identities", "quantities",
              "required_operations", "forbidden_operations",
              "forbidden_operations_anywhere", "material_charged", "materials",
              "no_duplicate_operations", "allowed_repeats", "no_minted_children",
              "decisions_expected", "forbidden_names_everywhere", "phrase_counts"}


@pytest.mark.parametrize("job", REVIEWED)
def test_every_reviewed_pack_has_accepted_facts_that_parse(job: str):
    facts = json.loads((REPLAY / job / "accepted_facts.json").read_text(encoding="utf-8"))
    assert isinstance(facts, dict) and facts, f"{job}: accepted facts are empty"
    assert "DRAFT" not in str(facts.get("_reviewed") or "").upper(), (
        f"{job}: accepted_facts.json still carries the draft notice; a person has to review "
        f"and sign it before it gates anything")
    known = KNOWN_KEYS
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
    for job in REVIEWED:
        facts = json.loads(
            (REPLAY / job / "accepted_facts.json").read_text(encoding="utf-8"))
        for key, value in facts.items():
            if key.startswith("_"):
                continue                      # commentary may quote the accepted numbers
            assert "gbp" not in key.lower() and "price" not in key.lower(), \
                f"{job}: '{key}' looks like a money pin in the structure layer"


# ── a required operation is asserted against the ROUTE, not a derived line list ────────

from test_frozen_replays import (                                        # noqa: E402
    canonical_decisions,
    required_ops_for,
)


def _routed(part: str, operation: str, status: str = "required", key: str = "canonical_route",
            nested: bool = False) -> dict:
    decision = {"part_number": part, "operation": operation, "status": status}
    payload = {"decisions": [decision]}
    return {"estimate_summary": {key: payload}} if nested else {key: payload}


def test_a_required_op_the_route_records_satisfies_the_pin_even_with_an_empty_line():
    """THE DEFECT THE REVIEWER FOUND ON THE REAL RECORD. costed_job() derives a line's
    operations from the workbook rows that carry decision ids, so on a record whose rows carry
    none the list comes back EMPTY — even though the canonical route records tubebend on
    7332-01-002. The gate would reject a structurally correct record, because the pin was
    testing whether decision ids reached the sheet rather than whether the route was compiled."""
    facts = {"required_operations": {"7332-01-002": ["tubebend"]}}
    lines = [_line("7332-01-002", operations=[])]          # exactly what the real record gives
    with pytest.raises(AssertionError):
        assert_accepted_structure("7332-01", facts, lines)            # no summary: still fails
    summary = _routed("7332-01-002", "tubebend")
    assert_accepted_structure("7332-01", facts, lines, summary=summary)


@pytest.mark.parametrize("key,nested", [
    ("canonical_route", False), ("canonical_route_shadow", False),
    ("canonical_route", True), ("canonical_route_shadow", True)])
def test_both_spellings_and_both_nestings_are_read(key, nested):
    """costed_facts reads canonical_route_shadow, the compiler writes it into estimate_summary,
    and a record may carry canonical_route. Picking one and missing the other is how a route
    that IS recorded reads as absent."""
    summary = _routed("X-002", "tubebend", key=key, nested=nested)
    assert required_ops_for(summary, "X-002") == {"tubebend"}


@pytest.mark.parametrize("status", ["unverified", "not_applicable", "refused", "excluded", ""])
def test_only_a_required_decision_satisfies_a_required_pin(status):
    """"The compiler considered tubebend" is not "the route bends the tube". A decision with no
    status at all does not qualify either: absence is not a claim."""
    summary = _routed("X-002", "tubebend", status=status)
    assert required_ops_for(summary, "X-002") == set()
    with pytest.raises(AssertionError, match="neither routed nor charged"):
        assert_accepted_structure("syn", {"required_operations": {"X-002": ["tubebend"]}},
                                  [_line("X-002", operations=[])], summary=summary)


def test_a_decision_naming_the_part_as_a_participant_counts():
    """An assembly-scoped weld event is one event across three parts, and legitimately belongs
    to each participant."""
    summary = {"canonical_route": {"decisions": [
        {"target_id": "ASSY-1", "operation": "welding", "status": "required",
         "participants": ["X-002", "X-003"]}]}}
    assert required_ops_for(summary, "X-002") == {"welding"}
    assert required_ops_for(summary, "X-009") == set()


def test_the_failure_message_says_which_source_was_empty():
    """So the next person can tell "the route never required it" from "it never reached the
    sheet" — two different repairs."""
    summary = _routed("X-002", "laser_cutting")
    with pytest.raises(AssertionError) as err:
        assert_accepted_structure("syn", {"required_operations": {"X-002": ["tubebend"]}},
                                  [_line("X-002", operations=["folding"])], summary=summary)
    text = str(err.value)
    assert "route requires ['laser_cutting']" in text
    assert "line carries ['folding']" in text


def test_a_forbidden_op_is_still_judged_on_what_is_CHARGED():
    """The two pins assert different things against different authorities: required against the
    route, forbidden against the money. A route that merely CONSIDERED folding has not charged
    for it, and the forbidden pin must not fire on consideration alone."""
    summary = _routed("X-002", "folding", status="not_applicable")
    assert_accepted_structure("syn", {"forbidden_operations": {"X-002": ["folding"]}},
                              [_line("X-002", operations=["tubebend"])], summary=summary)
    with pytest.raises(AssertionError, match="ruled-out op 'folding' is charged"):
        assert_accepted_structure("syn", {"forbidden_operations": {"X-002": ["folding"]}},
                                  [_line("X-002", operations=["folding"])], summary=summary)


def test_canonical_decisions_does_not_duplicate_one_decision_found_twice():
    decision = {"part_number": "X-002", "operation": "tubebend", "status": "required"}
    summary = {"canonical_route": {"decisions": [decision]},
               "estimate_summary": {"canonical_route_shadow": {"decisions": [decision]}}}
    assert len(canonical_decisions(summary)) == 1


def test_an_absent_route_is_not_an_error_just_an_empty_set():
    assert required_ops_for({}, "X-002") == set()
    assert canonical_decisions({}) == []


# ── SCRUM-134: swapped materials and duplicate operations are caught ─────────────────


def test_a_material_pin_catches_a_swapped_material():
    facts = {"materials": {"X-002": "STAINLESS 304"}}
    assert_accepted_structure("synthetic", facts,
                              [_line("X-002", material_label="Stainless Steel 304 2B")])
    with pytest.raises(AssertionError, match="missing"):
        assert_accepted_structure("synthetic", facts,
                                  [_line("X-002", material_label="Mild Steel CR4")])


def test_a_material_pin_on_a_part_that_vanished_fails():
    with pytest.raises(AssertionError, match="is missing"):
        assert_accepted_structure("synthetic", {"materials": {"X-002": "OAK"}},
                                  [_line("X-003", material_label="Oak")])


def test_a_material_printed_differently_is_not_a_swap():
    """Case, punctuation and word order are print, not material."""
    facts = {"materials": {"X-002": "MFMDF Oak"}}
    assert_accepted_structure("synthetic", facts,
                              [_line("X-002", material_label="oak-faced mfmdf, 18 core")])


def test_an_operation_charged_on_two_rows_of_one_part_is_caught():
    facts = {"no_duplicate_operations": True}
    lines = [_line("X-002", operation_charges={"laser_cutting": 2, "folding": 1})]
    with pytest.raises(AssertionError, match="X-002 laser_cutting x2"):
        assert_accepted_structure("synthetic", facts, lines)


def test_a_repeat_the_estimator_accepted_still_passes():
    facts = {"no_duplicate_operations": True,
             "allowed_repeats": {"x-002": ["Folding"]}}
    assert_accepted_structure("synthetic", facts,
                              [_line("X-002", operation_charges={"folding": 2})])
    with pytest.raises(AssertionError, match="laser_cutting"):
        assert_accepted_structure(
            "synthetic", facts,
            [_line("X-002", operation_charges={"folding": 2, "laser_cutting": 2})])


def test_without_the_pin_a_repeat_is_not_judged():
    assert_accepted_structure("synthetic", {},
                              [_line("X-002", operation_charges={"laser_cutting": 3})])


def test_the_record_counts_the_rows_that_charge_each_operation():
    """costed_facts publishes the count the pin reads, from the priced rows themselves."""
    import costed_facts as cf
    summary = {"workbook_labour": {"rows": [
        {"workbook_row": 10, "part_numbers": ["X-002"], "engine_operations": ["laser_cutting"]},
        {"workbook_row": 11, "part_numbers": ["X-002", "X-003"],
         "engine_operations": ["laser_cutting"]},
        {"workbook_row": 12, "part_numbers": ["X-002"], "engine_operations": ["folding"]},
    ]}}
    assert cf.operation_charge_counts(summary, "X-002") == {"laser_cutting": 2, "folding": 1}
    assert cf.operation_charge_counts(summary, "X-003") == {"laser_cutting": 1}


# ── every committed pack's rules run in CI on a synthetic record ──────────────────────


def _synthetic_record(facts: dict) -> list:
    """The smallest record that satisfies every structural pin in `facts`.

    Built from the FACTS, never from a job's record, which stays on the laptop. It lets CI
    execute each committed pack's own pins, so a pin that could never fail or never pass is
    found here and not on the day the pack is frozen (SCRUM-134)."""
    ids = list(facts.get("bom_identities") or [])
    for key in ("quantities", "required_operations", "materials"):
        ids += list((facts.get(key) or {}).keys())
    ids += list(facts.get("material_charged") or [])
    ids = list(dict.fromkeys(str(i) for i in ids))
    allowed = {str(k).upper(): v for k, v in (facts.get("allowed_repeats") or {}).items()}
    lines = []
    for pn in ids:
        routed = [str(o).lower() for o in (facts.get("required_operations") or {}).get(pn, [])]
        charges = {op: 1 for op in routed}
        charges.update({str(op).lower(): 2 for op in allowed.get(pn.upper(), [])})
        lines.append(_line(pn, qty_per_unit=float((facts.get("quantities") or {}).get(pn, 1)),
                           route_operations=routed,
                           material_label=str((facts.get("materials") or {}).get(pn, "")),
                           operation_charges=charges))
    return lines


def _plants(facts: dict, lines: list):
    """(what was broken, the broken record) for every break this pack's pins should catch."""
    import copy

    def broken(fn):
        out = copy.deepcopy(lines)
        fn(out)
        return out

    def first(d):
        return next(iter((d or {}).items()), (None, None))

    if facts.get("bom_identities") and len(lines) > 1:
        yield "a missing part", broken(lambda ls: ls.pop())
        yield "an extra part", broken(lambda ls: ls.append(_line("PLANTED-EXTRA")))
    pn, q = first(facts.get("quantities"))
    if pn is not None:
        def _qty(ls, pn=pn, q=q):
            next(l for l in ls if l["part_number"] == pn)["qty_per_unit"] = float(q) + 1
        yield "a wrong quantity", broken(_qty)
    pn, _ = first(facts.get("materials"))
    if pn is not None:
        def _swap(ls, pn=pn):
            next(l for l in ls if l["part_number"] == pn)["material_label"] = "PLANTEDSWAP"
        yield "a swapped material", broken(_swap)
    if facts.get("no_duplicate_operations") and lines:
        def _dup(ls):
            ls[0]["operation_charges"]["planted_op"] = 2
        yield "a duplicate operation", broken(_dup)
    pn, ops = first(facts.get("required_operations"))
    if pn is not None and ops:
        def _drop(ls, pn=pn):
            next(l for l in ls if l["part_number"] == pn)["route_operations"] = []
        yield "a required operation lost", broken(_drop)
    for op in (facts.get("forbidden_operations_anywhere") or [])[:1]:
        def _forbid(ls, op=op):
            ls[0]["operations"] = list(ls[0]["operations"]) + [op]
        yield "a ruled-out operation charged", broken(_forbid)
    for pn in (facts.get("material_charged") or [])[:1]:
        def _free(ls, pn=pn):
            next(l for l in ls if l["part_number"] == pn)["engine_unit_gbp"] = 0.0
        yield "a made part with no material money", broken(_free)


@pytest.mark.parametrize("job", REVIEWED)
def test_each_reviewed_pack_s_rules_pass_a_record_that_keeps_them(job: str):
    facts = json.loads((REPLAY / job / "accepted_facts.json").read_text(encoding="utf-8"))
    assert_accepted_structure(job, facts, _synthetic_record(facts))


@pytest.mark.parametrize("job", REVIEWED)
def test_each_reviewed_pack_s_rules_catch_every_planted_break(job: str):
    facts = json.loads((REPLAY / job / "accepted_facts.json").read_text(encoding="utf-8"))
    lines = _synthetic_record(facts)
    missed = []
    planted = 0
    for what, record in _plants(facts, lines):
        planted += 1
        try:
            assert_accepted_structure(job, facts, record)
        except AssertionError:
            continue
        missed.append(what)
    assert planted, f"{job}: its facts pin nothing a planted break could test"
    assert not missed, f"{job}: the pins let these planted breaks through: {missed}"


def test_the_synthetic_record_is_proved_on_the_new_pins_too():
    """The two new pins take part in the per-pack plant, so a pack that uses them is held."""
    facts = {"bom_identities": ["A", "B"], "quantities": {"A": 2},
             "materials": {"A": "OAK MFMDF"}, "no_duplicate_operations": True,
             "allowed_repeats": {"B": ["folding"]}}
    lines = _synthetic_record(facts)
    assert_accepted_structure("synthetic", facts, lines)
    kinds = [what for what, _ in _plants(facts, lines)]
    assert {"a swapped material", "a duplicate operation", "a wrong quantity",
            "a missing part"} <= set(kinds)
