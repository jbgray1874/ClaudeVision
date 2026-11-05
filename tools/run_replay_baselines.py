"""Run every frozen baseline and say, per job, PASS, FAIL or NOT FROZEN (SCRUM-134).

RUN THIS ON THE BOX, where the frozen records are:

    python tools\\run_replay_baselines.py

It runs tests\\replay with SDI_REPLAY_ALLOW_MISSING cleared whatever the shell has set, because
the opt-out exists for checkouts that hold no records and this machine holds them: here a
missing record is a hole in the protection, and it is reported as one. Each job gets one line:

    PASS         all three tiers ran on the frozen record and held
    FAIL         a tier ran and a pin broke; the first line of each failure follows
    NOT FROZEN   the job has reviewed facts but no frozen record on this machine
    DRAFT ONLY   a drafted facts file waits for review; nothing gates the job yet

The exit code is 0 only when every reviewed job PASSES, so it can gate a release step.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "tests" / "replay"
TIERS = (("test_frozen_replay", "record"),
         ("test_frozen_stage_contracts", "stages"),
         ("test_frozen_routing_and_costing_re_execute", "route+cost"))


def packs(replay: Path = REPLAY) -> Dict[str, Dict[str, bool]]:
    """{job: {reviewed, frozen, provenance, draft}} for every job folder under tests/replay."""
    out: Dict[str, Dict[str, bool]] = {}
    for d in sorted(p for p in replay.iterdir() if p.is_dir() and not p.name.startswith("_")):
        state = {"reviewed": (d / "accepted_facts.json").is_file(),
                 "frozen": (d / "summary.json").is_file(),
                 "provenance": (d / "provenance.json").is_file(),
                 "draft": (d / "accepted_facts.draft.json").is_file()}
        if state["reviewed"] or state["draft"]:
            out[d.name] = state
    return out


def read_junit(path: Path) -> Dict[Tuple[str, str], Tuple[str, str]]:
    """{(tier test, job): (outcome, first line of the message)} from a pytest junit file."""
    results: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        name = case.get("name") or ""
        if "[" not in name:
            continue
        test, job = name.split("[", 1)
        job = job.rstrip("]")
        outcome, message = "passed", ""
        for tag in ("failure", "error", "skipped"):
            node = case.find(tag)
            if node is not None:
                outcome = "skipped" if tag == "skipped" else "failed"
                text = (node.get("message") or node.text or "").strip()
                message = text.splitlines()[0] if text else ""
                break
        results[(test, job)] = (outcome, message)
    return results


def verdicts(state: Dict[str, Dict[str, bool]],
             results: Dict[Tuple[str, str], Tuple[str, str]]) -> List[Tuple[str, str, List[str]]]:
    """[(job, verdict, notes)] in job order. Pure, so it is tested without a pack."""
    rows = []
    for job, s in state.items():
        if not s["reviewed"]:
            rows.append((job, "DRAFT ONLY", ["accepted_facts.draft.json waits for review"]))
            continue
        if not s["frozen"]:
            rows.append((job, "NOT FROZEN",
                         [f"python tools\\freeze_replay_fixture.py {job} --find"]))
            continue
        notes, failed, ran = [], False, 0
        for test, label in TIERS:
            outcome, message = results.get((test, job), ("missing", "the tier did not run"))
            if outcome == "passed":
                ran += 1
            elif outcome == "skipped":
                notes.append(f"{label}: skipped: {message}")
            else:
                failed = True
                notes.append(f"{label}: {message}")
        rows.append((job, "FAIL" if failed or not ran else "PASS", notes))
    return rows


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--job", action="append", help="limit to these jobs (repeatable)")
    a = ap.parse_args(argv)
    state = packs()
    if a.job:
        state = {j: s for j, s in state.items() if j in set(a.job)}
    if not state:
        print("!! no reviewed jobs found under tests/replay")
        return 2
    env = dict(os.environ)
    env.pop("SDI_REPLAY_ALLOW_MISSING", None)
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "replay.xml"
        target = str(REPLAY / "test_frozen_replays.py")
        nodes = ([f"{target}::{test}[{job}]" for job in state for test, _ in TIERS]
                 if a.job else [target])
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
               "-p", "no:cacheprovider", *nodes, f"--junitxml={junit}"]
        subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        results = read_junit(junit) if junit.is_file() else {}
    rows = verdicts(state, results)
    width = max(len(j) for j, _, _ in rows)
    print(f"{'job':<{width}}  verdict")
    for job, verdict, notes in rows:
        print(f"{job:<{width}}  {verdict}")
        for n in notes:
            print(f"{'':<{width}}    {n}")
    passed = sum(1 for _, v, _ in rows if v == "PASS")
    print(f"\n{passed} of {len(rows)} reviewed job(s) protected and passing")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
