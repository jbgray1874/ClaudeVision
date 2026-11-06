"""SCRUM-134: the laptop's one-command baseline run says, per job, PASS, FAIL or NOT FROZEN.

A run that reports one green total hides which job is unprotected; this reports each one. The
packs here are synthetic folders in a temporary directory, never a job's record.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import run_replay_baselines as rb                                        # noqa: E402

PASSED = ("passed", "")


def _pack(root: Path, job: str, *files: str) -> None:
    d = root / job
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_text("{}", encoding="utf-8")


def _all_tiers(job: str, outcome=PASSED) -> dict:
    return {(t, job): outcome for t, _ in rb.TIERS}


def test_each_job_gets_its_own_verdict(tmp_path):
    _pack(tmp_path, "J-PASS", "accepted_facts.json", "summary.json", "provenance.json")
    _pack(tmp_path, "J-FAIL", "accepted_facts.json", "summary.json", "provenance.json")
    _pack(tmp_path, "J-COLD", "accepted_facts.json")
    _pack(tmp_path, "J-DRAFT", "accepted_facts.draft.json")
    _pack(tmp_path, "J-NONE")
    results = {**_all_tiers("J-PASS"), **_all_tiers("J-FAIL")}
    results[("test_frozen_replay", "J-FAIL")] = ("failed", "J-FAIL S-01: qty 1 != accepted 2")
    got = {job: (v, notes) for job, v, notes in rb.verdicts(rb.packs(tmp_path), results)}
    assert got["J-PASS"] == ("PASS", [])
    assert got["J-FAIL"][0] == "FAIL" and "qty 1 != accepted 2" in got["J-FAIL"][1][0]
    assert got["J-COLD"][0] == "NOT FROZEN"
    assert "freeze_replay_fixture.py J-COLD --find" in got["J-COLD"][1][0]
    assert got["J-DRAFT"][0] == "DRAFT ONLY"
    assert "J-NONE" not in got


def test_a_tier_that_never_ran_is_not_a_pass(tmp_path):
    _pack(tmp_path, "J-1", "accepted_facts.json", "summary.json", "provenance.json")
    got = rb.verdicts(rb.packs(tmp_path), {})
    assert got[0][1] == "FAIL"


def test_a_skipped_tier_is_named_but_the_others_still_count(tmp_path):
    _pack(tmp_path, "J-1", "accepted_facts.json", "summary.json", "provenance.json")
    results = _all_tiers("J-1")
    results[("test_frozen_stage_contracts", "J-1")] = ("skipped", "no raw part_estimates")
    job, verdict, notes = rb.verdicts(rb.packs(tmp_path), results)[0]
    assert verdict == "PASS" and "skipped" in notes[0]


def test_the_junit_file_is_read_per_tier_and_job(tmp_path):
    xml = tmp_path / "r.xml"
    xml.write_text(
        '<testsuites><testsuite>'
        '<testcase name="test_frozen_replay[J-1]"/>'
        '<testcase name="test_frozen_stage_contracts[J-1]">'
        '<failure message="J-1: BOM drifted: [A]&#10;more">trace</failure></testcase>'
        '<testcase name="test_frozen_routing_and_costing_re_execute[J-1]">'
        '<skipped message="no raw part_estimates"/></testcase>'
        '</testsuite></testsuites>', encoding="utf-8")
    got = rb.read_junit(xml)
    assert got[("test_frozen_replay", "J-1")] == PASSED
    assert got[("test_frozen_stage_contracts", "J-1")] == ("failed", "J-1: BOM drifted: [A]")
    assert got[("test_frozen_routing_and_costing_re_execute", "J-1")][0] == "skipped"


def test_the_run_clears_the_opt_out_whatever_the_shell_set():
    source = (ROOT / "tools" / "run_replay_baselines.py").read_text(encoding="utf-8")
    assert 'env.pop("SDI_REPLAY_ALLOW_MISSING", None)' in source


def test_the_tiers_named_are_the_tiers_the_harness_runs():
    harness = (ROOT / "tests" / "replay" / "test_frozen_replays.py").read_text(encoding="utf-8")
    for test, _ in rb.TIERS:
        assert f"def {test}(job: Path)" in harness
