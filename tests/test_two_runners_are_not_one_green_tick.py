"""Two runners ran on one desktop for three days and every screen said "ready".

    ProcessId    : 3668
    CreationDate : 12/09/2026 13:26:54
    CommandLine  : "C:\\ClaudeVision\\.venv\\Scripts\\pythonw.exe"
                   "C:\\ClaudeVision\\tools\\runner\\sdi_estimate_runner.py"
                   --server "http://localhost:8072"

    ProcessId    : 14796
    CreationDate : 12/09/2026 13:26:55
    CommandLine  : "C:\\Users\\james.gray\\AppData\\Local\\Programs\\Python\\Python310\\pythonw.exe"
                   "C:\\ClaudeVision\\tools\\runner\\sdi_estimate_runner.py"
                   --server "http://localhost:8072"

Same script, same engine root, same server, two interpreters. Both polling, both claiming,
both able to drive the one SOLIDWORKS seat and the one Excel on that desktop — which is the
thing the single-runner lock exists to make impossible.

NOTHING COULD SEE IT, AND THAT IS THE DEFECT. `runner_id` is `{node}-{mac}`, deliberately
stable per machine so a restart does not leave the page listing a graveyard of dead runners.
The consequence was never faced: two processes answer to one id, so the service counts ONE
runner and the page draws one green tick reading "ready". The lock was the only guard, and it
fails OPEN by design — when it cannot take the lock it says so and carries on, which is right,
because a lock bug must not stop a shop estimating. Right, and it leaves nothing watching.

THIS IS A HANDOVER TEST BEFORE IT IS AN ENGINEERING ONE. An estimator cannot be given a
machine where two runners fight over Excel and the screen says ready; they have no way to find
out, and the first they would know is a number that will not reconcile. So the page says it in
the words of the consequence — "an estimate may be wrong, stop one before running anything" —
not in the words of the mechanism.

AND A SERVICE THAT DOES NOT KNOW MUST SAY SO. A runner too old to report which process it is
leaves `process_count` None, never 1. "One" is precisely the reassurance that was false for
three days, and inventing it from silence would rebuild the same lie in the place built to
catch it.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))

import estimate_routes as er                                            # noqa: E402

PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html")
RUNNER = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py")


def _runner(*processes, build=""):
    r = er.Runner(runner_id="DESKTOP-GFAAP80-a1b2c3", hostname="DESKTOP-GFAAP80")
    now = time.time()
    for p in processes:
        r.processes[p] = now
    r.build = build
    return r


P3668 = "pid 3668 DESKTOP-GFAAP80 since 2026-09-12 13:26:54"
P14796 = "pid 14796 DESKTOP-GFAAP80 since 2026-09-12 13:26:55"


# ── the service can now tell them apart ──────────────────────────────────────────────────

def test_one_process_is_reported_as_one():
    j = _runner(P3668).as_json()
    assert j["process_count"] == 1
    assert j["conflict"] is False


def test_two_processes_answering_to_one_id_are_a_conflict():
    """The three-day case, exactly."""
    j = _runner(P3668, P14796).as_json()
    assert j["process_count"] == 2
    assert j["conflict"] is True
    assert P3668 in j["processes"] and P14796 in j["processes"]


def test_a_runner_that_cannot_say_reports_unknown_and_never_one():
    """THE MOST IMPORTANT ASSERTION HERE. A runner from before this change sends no process
    identity. The honest answer is "I do not know", and the dishonest one — the one that
    was true on screen for three days — is "one"."""
    j = _runner().as_json()
    assert j["process_count"] is None
    assert j["conflict"] is False
    assert j["processes"] == []


def test_a_process_that_stopped_answering_is_not_counted_forever():
    """Kill one of the two and the warning must clear by itself, or nobody will believe the
    next one."""
    r = _runner(P3668, P14796)
    r.processes[P3668] = time.time() - (er.RUNNER_ONLINE_SECONDS + 30)
    j = r.as_json()
    assert j["process_count"] == 1
    assert j["conflict"] is False
    assert j["processes"] == [P14796]


def test_the_claim_records_the_process_and_the_build():
    req = er.ClaimRequest(runner_id="R1", hostname="BOX", process=P3668,
                          build="a382f82 · src 0e1f2a3b4c5d (657 modules)")
    assert req.process == P3668 and req.build.startswith("a382f82")


def test_an_old_runners_claim_still_parses():
    """A runner that predates this must keep working — an estimating shop does not stop
    because a field was added."""
    req = er.ClaimRequest(runner_id="R1", hostname="BOX")
    assert req.process == "" and req.build == ""


# ── and the page says it in the words of the consequence ─────────────────────────────────

def test_the_page_warns_in_plain_words_not_in_mechanism():
    src = PAGE.read_text(encoding="utf-8")
    assert "Two runners are running" in src
    assert "an estimate may be wrong" in src
    assert "Stop one before running anything" in src


def test_the_warning_turns_the_tick_red():
    """It read "ready" in green. A warning underneath a green tick is read as a footnote."""
    block = src_block = PAGE.read_text(encoding="utf-8").split("d.conflicts")[1][:600]
    assert "var(--bad)" in block


def test_the_top_level_reply_names_the_conflicts():
    """So the page does not have to walk the list to discover its tick is wrong."""
    src = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
    assert '"conflicts": [r["runner_id"] for r in online if r.get("conflict")]' in src


# ── which build is doing the work ────────────────────────────────────────────────────────

def test_the_runner_says_which_build_it_is_on():
    """The page has answered this for the SERVICE since August, with X-SDI-Commit. The half
    of the system that does the work could not answer it at all — so "is the runner on my
    fix?" was a question nobody on the box could settle."""
    src = RUNNER.read_text(encoding="utf-8")
    assert "build_stamp_line" in src
    assert 'print(f"  build    {_build}")' in src
    assert 'print(f"  process  {_process}")' in src


def test_naming_its_build_is_never_fatal():
    """A runner that will not start because it cannot name its own version is worse than one
    that cannot name it."""
    src = RUNNER.read_text(encoding="utf-8")
    block = src.split("from build_stamp import build_stamp_line")[1][:400]
    assert "except Exception" in block
    assert "unknown" in block
