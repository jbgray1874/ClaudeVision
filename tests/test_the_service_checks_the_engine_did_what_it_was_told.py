"""A stale runner produced a full estimate wearing an LLM-only label, and nothing caught it.

WHAT HAPPENED, ON 10575-02, THROUGH THE FORM. The service was current. It read method="llm",
set Run.llm_only, put "llm_only": true in the claim payload, and printed its LLM-ONLY banner on
the run's own log — every one of which the page showed. The runner on DESKTOP-GFAAP80 had been
up since before --llm-only existed. A running Python process holds the module it imported at
start, and `git pull` does not reload it, so it built the command from the old build_command:

    $ ...\\python.exe -u ...\\main.py --job "..." --order-qty 1 --deliverables --customer Dyson

No flag. The engine then did the ordinary thing and said so, at length: eleven DXF flat patterns
augmented, `[solidworks] native extract applied`, `[hierarchy] applied to 4 assembly node(s)`,
and `[bom-readers] both agreed 32` — Path A and Path B both reading, which is exactly what an
LLM-only run does not do.

WHY IT MATTERS MORE THAN AN ORDINARY BUG. The output is not wrong; it is a perfectly good
estimate. It is filed in a folder named for an LLM-only run, under a page that says UNVERIFIED,
DO NOT QUOTE, over the top of it. Every warning on that page is now attached to the wrong file.
The next person to compare "the LLM read" against "the real estimate" is comparing a normal run
with a normal run and will conclude the model is far better than it is. That is the single file
this feature exists to prevent, and it was found by a human reading a command echo by eye.

THE SERVICE CANNOT INSPECT THE RUNNER'S CODE, so it checks the runner's own words. The command
echo is ground truth about what the engine was told, it arrives on the progress feed before the
engine has written anything, and a run whose instruction was not carried out is stopped there
rather than fifteen minutes later with a workbook on the share.

A HANDSHAKE AT CLAIM TIME WOULD BE NEATER AND WOULD NOT HAVE HELPED. A runner too old to pass
--llm-only is also too old to declare that it can't.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")

# The prose in this module names every string the negative assertions look for — including the
# command line that has no flag in it. Seven times in this repo a guard has passed on the
# comment explaining the thing it guards.
CODE = re.sub(r"#[^\n]*", " ", re.sub(r'""".*?"""', " ", SRC, flags=re.S))


@pytest.fixture()
def routes():
    import sys
    sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
    import estimate_routes as m
    return m


def _run(routes, **kw):
    r = routes.Run(run_id="t", client="Dyson", drawing_number="10575-02", units=1,
                   job_folder="j", output_path="o", queued_at=0.0, **kw)
    r.status = "running"
    r.runner = "DESKTOP-GFAAP80"
    return r


# THE ECHO THAT WENT PAST UNCHALLENGED, verbatim in shape.
STALE = ('$ C:\\ClaudeVision\\.venv\\Scripts\\python.exe -u C:\\ClaudeVision\\src\\main.py '
         '--job "\\\\sdi-dc01\\shareddata$\\...\\10575-02" --order-qty 1 --deliverables '
         '--customer Dyson')
TOLD = STALE + " --llm-only"


def test_the_run_that_asked_and_was_not_obeyed_is_stopped(routes):
    run = _run(routes, llm_only=True)
    routes._check_the_engine_was_told(run, STALE)
    assert run.llm_only_refused, "the missing flag was not noticed"
    assert run.cancel_requested, (
        "the engine is left running: fifteen minutes of SOLIDWORKS and Excel producing the "
        "one workbook that must not exist")
    assert run.error, "nothing says why it stopped"


def test_the_run_that_was_obeyed_is_left_alone(routes):
    run = _run(routes, llm_only=True)
    routes._check_the_engine_was_told(run, TOLD)
    assert not run.llm_only_refused
    assert not run.cancel_requested, "a correct LLM-only run is being cancelled"


def test_an_ordinary_estimate_is_never_touched(routes):
    """Every normal run's command echo has no --llm-only in it, and there are far more of
    those than of these. A guard that fired on them would stop the estimating."""
    run = _run(routes, llm_only=False)
    routes._check_the_engine_was_told(run, STALE)
    assert not run.llm_only_refused
    assert not run.cancel_requested


@pytest.mark.parametrize("prose", [
    "LLM-ONLY: read by the vision model alone — the deterministic BOM reader is OFF.",
    "UNVERIFIED: Grok alone — no deterministic BOM reader, no DXF, no SolidWorks.",
    "   [cad] main.py could not attach to a SolidWorks seat",
    "Reading   \\\\sdi-dc01\\shareddata$\\...\\10575-02",
])
def test_prose_on_the_same_log_is_not_read_as_the_command(routes, prose):
    """THE TRAP THIS REPO KEEPS WALKING INTO. The run's log carries the LLM-ONLY banner, the
    engine's own warnings, and this guard's own three lines of explanation. A looser match —
    "a line mentioning main.py", or worse "a line without --llm-only" — would fire on the
    banner that announces the run is correct, and cancel every LLM read there has ever been."""
    run = _run(routes, llm_only=True)
    routes._check_the_engine_was_told(run, prose)
    assert not run.cancel_requested, "cancelled by a line of prose: " + prose


def test_it_fires_once_and_does_not_rewrite_its_own_reason(routes):
    """The engine goes on talking after it is told to stop — the runner only hears the
    cancellation on its next heartbeat. A guard that re-fired would bury the explanation under
    copies of itself."""
    run = _run(routes, llm_only=True)
    routes._check_the_engine_was_told(run, STALE)
    first = list(run.log)
    routes._check_the_engine_was_told(run, STALE)
    assert run.log == first, "the same refusal is being written twice"


def test_the_progress_feed_is_where_it_is_checked():
    """BEFORE ANYTHING IS WRITTEN, not at the end. The echo is one of the first lines the
    runner sends; waiting for /complete would mean cancelling a run that had already filed."""
    at = CODE.index("def progress(")
    body = CODE[at:CODE.index("\n@router", at)]
    assert "_check_the_engine_was_told(run, text)" in body, (
        "the progress feed does not check the instruction was carried out, so a mislabelled "
        "run is only noticed once the workbook is on the share")


def test_the_outcome_cannot_come_back_done():
    """THE ENGINE EXITS 0 EITHER WAY — it was never told there was a second kind of run — so
    the runner reports "done" in good faith. "Complete" on the page is what makes an estimator
    open the file and believe it."""
    at = CODE.index("def complete(")
    body = CODE[at:CODE.index("\n@router", at)]
    assert "llm_only_refused" in body, "a refused run can still be reported as complete"
    assert body.index("run.error = req.error") < body.index("if run.llm_only_refused"), (
        "the runner's own error message is applied AFTER the override and would replace the "
        "reason with a blank")
