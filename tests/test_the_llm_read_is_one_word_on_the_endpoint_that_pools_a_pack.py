"""One drawing or thirty, one endpoint, one word changed.

WHAT WAS ALREADY THERE AND DID NOT ANSWER THE QUESTION. /api/estimate/batch takes
method="both"|"llm"|"engine", and its "llm" calls scan_price — whose docstring is one line:
"One drawing, one price." A figure and a basis, per PDF, each file treated as its own
enquiry. No BOM, no routes, no pack. The vocabulary existed; what James wanted to test had
no path through it.

WHAT THIS ADDS. The same three words on POST /api/estimate, which pools a folder or a list
of files into ONE job. A pack of one PDF is a pack, so a single drawing and a whole folder
are the same call with no branching — which is exactly why it belongs here rather than on
the batch endpoint, which has to keep pretending every file is a separate enquiry.

"llm" carries --llm-only to the engine: the deterministic BOM reader, the DXF flat patterns
and the SolidWorks extract all off, every page to the model.

THE THING THIS FILE EXISTS TO PROTECT. On 10575-02 the LLM-only run produced a workbook with
the same template, the same tabs, the same totals column and a unit cost within 5% of the
real estimate — while costing ONE steel part out of nine, on a 90 x 10 mm blank read from a
title block, with a 10,646 mm cut path through it. Sitting on the share a week later there
is nothing to tell the two files apart.

So it says what it is in four places: the button, a confirm before it runs, the run's own
log, and the engine's console. Three of those are on this page, because the fourth scrolls
past in a window nobody has open.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_ROUTES = (_ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
_RUNNER = (_ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
_PAGE = (_ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")
_SCRIPT = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", _PAGE, re.S | re.I))
_MARKUP = re.sub(r"<script[^>]*>.*?</script>", " ", _PAGE, flags=re.S | re.I)

# THE WHOLE HANDLER, NOT THE FIRST 1400 CHARACTERS OF IT. Every test below used to slice a
# fixed window after the `onclick`, which is a guard that quietly stops guarding: adding four
# lines of comment to the top of the handler pushes `method: "llm"` past the end of the window
# and the assertion passes on a body it can no longer see. The handler ends at the only line
# that closes it at column zero.
_AT = _SCRIPT.index('$("bRunLLM").onclick')
_HANDLER = _SCRIPT[_AT:_SCRIPT.index("\n};", _AT)]

# AND THE CODE WITHOUT ITS PROSE, for every assertion of the form "this is NOT in here".
# The handler carries a comment naming the enquiry widgets it must no longer touch, and the
# one naming `batchFiles` as the list it must not read — so both negative assertions failed on
# the explanation of the fix rather than on the fix. That is the same trap seven times over in
# this repo: a search that matches the sentence describing what is being searched for.
_CODE = re.sub(r"//[^\n]*", " ", re.sub(r"/\*.*?\*/", " ", _HANDLER, flags=re.S))


# ── the request reaches the engine ───────────────────────────────────────────

def test_the_single_pack_endpoint_takes_a_method():
    assert re.search(r"method:\s*str\s*=\s*\"both\"", _ROUTES), (
        "POST /api/estimate has no method, so a pack can only ever be run one way")


def test_it_validates_the_same_three_words_as_the_batch_endpoint():
    """Two vocabularies for one idea is how a page ends up sending 'llm_only' to an endpoint
    that wants 'llm'."""
    assert _ROUTES.count('{"both", "llm", "engine"}') >= 2, (
        "the single-pack endpoint does not validate the same three methods as the batch one")


def test_it_refuses_before_it_stages():
    """Staging clears and refills a folder on the share. Doing that and THEN refusing over a
    typo in one word leaves the estimator's job folder rewritten for nothing."""
    at = _ROUTES.index('def start(req: EstimateRequest')
    body = _ROUTES[at:_ROUTES.index("_sources: List[str] = []", at)]
    assert 'method not in {"both", "llm", "engine"}' in body, (
        "the method is validated after staging, or not at all")


def test_the_run_carries_it_and_the_runner_is_told():
    assert "llm_only: bool = False" in _ROUTES, "the Run does not record it"
    assert '"llm_only": bool(run.llm_only)' in _ROUTES, "the claim payload does not carry it"
    assert 'job.get("llm_only")' in _RUNNER, "the runner never reads it"


def test_the_runner_passes_the_engine_flag():
    assert '["--llm-only"] if llm_only else []' in _RUNNER, (
        "the runner accepts the field and does not act on it — the run would be an ordinary "
        "estimate wearing the wrong label, which is worse than not offering it")


def test_it_is_not_confused_with_wants_engine():
    """wants_engine decides whether a runner picks the run up AT ALL — the batch path's
    LLM scan needs no runner. This one does: it produces a workbook and deliverables like
    any other run, it just reads with one source instead of four."""
    at = _ROUTES.index("llm_only: bool = False")
    assert "wants_engine" in _ROUTES[at - 900:at], "the two flags are no longer adjacent"
    assert re.search(r"wants_engine=\(method != \"llm\"\)", _ROUTES), (
        "the batch path's wants_engine rule has changed; check it still means what the "
        "single-pack llm_only does not")


# ── it cannot be mistaken for an estimate ────────────────────────────────────

def test_the_button_exists_and_is_not_styled_as_a_run_button():
    assert 'id="bRunLLM"' in _MARKUP, "there is no LLM read button in the Drawing section"
    assert "btn-measure" in _MARKUP, "it is styled as an ordinary run button"


def test_the_button_says_what_it_is_and_is_not():
    at = _MARKUP.index('id="bRunLLM"')
    block = _MARKUP[at:at + 1600]
    assert "not a price" in block or "not an estimate" in block
    assert "must not be quoted" in block, (
        "nothing beside the button warns against quoting its total")


def test_it_asks_before_it_runs():
    """The workbook it produces is indistinguishable from a real estimate once it is on the
    share — same template, same tabs, same totals. The only place to warn is before."""
    assert "confirm(" in _HANDLER, "it runs without asking"
    assert "CANNOT size a folded part" in _HANDLER, (
        "the confirmation does not say what the model cannot do, which is the whole limit")


def test_the_runs_own_log_records_it():
    """The engine's banner scrolls past in a console nobody has open. The estimator watching
    this page sees the run log."""
    assert 'run.line("LLM-ONLY' in _ROUTES, (
        "the run's log does not say it was read by one source")


# ── it posts what the endpoint expects ───────────────────────────────────────

def test_it_posts_to_the_pooling_endpoint_not_the_batch_one():
    assert '"/api/estimate"' in _HANDLER, "it posts to the batch endpoint, which prices per file"
    assert '"/api/estimate/batch"' not in _CODE
    assert 'method: "llm"' in _HANDLER


def test_it_reads_the_drawings_panel_and_not_the_enquiry_list():
    """THE FAILURE THIS BUTTON WAS ONE COMMIT AWAY FROM SHIPPING. It first went in beside
    "Estimate every drawing" and read `batchFiles` — the multi-drawing enquiry's list, where
    every file is its own job. Posted to the POOLING endpoint that becomes one estimate over a
    hundred unrelated drawings: a confident answer to a question nobody asked, filed in one
    folder, with nothing on the face of it to say so.

    A directory belongs in job_folder, not in files — the pack endpoint takes both."""
    assert "drawings.filter(d => !d.is_dir).map(d => d.path)" in _HANDLER, (
        "it does not send the Drawings panel's files the way the pack estimator does")
    assert "batchFiles" not in _CODE, (
        "the LLM read is pooling the multi-drawing enquiry's files into ONE job")
    assert "job_folder:" in _HANDLER, "a folder would be posted as a file and read as empty"


def test_it_sends_the_drawing_number_the_endpoint_requires():
    """/api/estimate refuses without one; /api/estimate/batch derives a name per drawing and
    never asks. The gate is the PACK button's `missing` list, which already carries the drawing
    number because the pack button posts to the same endpoint — the two share a panel, a job
    and a destination folder, so a state one refuses cannot be a state the other accepts."""
    assert "drawing_number:" in _HANDLER
    gate = _SCRIPT[_SCRIPT.index("runBtn.disabled = running || missing.length > 0;"):][:700]
    assert "bRunLLM.disabled = running || missing.length > 0;" in gate, (
        "the LLM button is not gated with the pack button, so it can be pressed without a "
        "drawing number and the endpoint will refuse it")
    assert 'if(!safe(drawing.value))            missing.push("drawing number");' in _SCRIPT, (
        "the shared gate no longer requires a drawing number")


def test_the_run_is_stoppable_and_reports_where_it_was_launched_from():
    """IT HOLDS THE MACHINE EXACTLY AS AN ESTIMATE DOES — same queue, same lease, same
    SOLIDWORKS desktop — and a twenty-page pack is minutes of vision calls. `running` is what
    shows Stop, what names the run to abandon, and what keeps the two buttons from starting
    over each other.

    And it reports into the JOB panel. Launched from up here and logging into the enquiry card
    halfway down the page, the panel you pressed sits idle and the run looks like it never
    started."""
    assert "running = true; refresh();" in _HANDLER, (
        "the run is not held: Stop cannot see it and the pack button stays pressable")
    assert "runId = started.run_id;" in _HANDLER, "nothing records the run id, so Stop is blind"
    for enquiry_widget in ("bSet(", "bRows", "bCount", "bProgress", "bWhere"):
        assert enquiry_widget not in _CODE, (
            "the LLM read reports into the enquiry card, not the panel it was pressed in: "
            + enquiry_widget)


def test_a_single_run_is_watched_by_something_that_knows_about_single_runs():
    """watchBatch follows an enquiry of many drawings. Fed one run id it would poll an
    endpoint that does not know it and report 'not found' as a failure of the run."""
    assert "function watchOneRun(" in _SCRIPT
    at = _SCRIPT.index("function watchOneRun(")
    watcher = _SCRIPT[at:_SCRIPT.index("\n}", at)]
    assert '"/api/estimate/" + encodeURIComponent(runId)' in watcher
    assert watcher.count("running = false; refresh();") >= 2, (
        "an LLM read that ends without releasing `running` leaves the job panel showing a run "
        "that finished and both buttons dead until the page is reloaded")
    assert "404" in watcher, (
        "a restarted service answers 404 and the watcher would report a run that is still "
        "working, and will still file, as a failure")
