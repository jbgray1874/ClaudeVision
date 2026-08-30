"""A SolidWorks seat costs £300 a month. The one measurement only a seat can make was switched off.

WHAT THIS IS ABOUT. The estimating engine's single largest source of inaccuracy is a drawing
that arrives without a flat pattern: with no blank size, the engine infers one, and inferred
geometry is where the wrong numbers come from. A SolidWorks seat can answer that question
exactly — the analyser opens the formed part, flattens it IN MEMORY, and measures the resulting
bounding box. A flattened body's box IS the blank, by construction.

WHY THE PROPERTY ROUTE IS NOT ENOUGH, which is the whole reason this code exists. SolidWorks
uses the property name `Bounding Box Length` for BOTH a sheet-metal flat pattern AND a weldment
solid's folded envelope. Reading the property cannot tell them apart. On 12120-01-01M it
returned 126.39 x 82.2 where the true blank is 132.39 x 88.2 — material under-bought, on a part
that looked fully sourced. Measuring a flatten cannot be fooled that way.

AND IT HAD NEVER RUN. `flat_pattern_by_flatten` was gated behind a `--flatten` command-line
flag, described as opt-in "because it rebuilds each model in memory and costs time".
`_run_analyser` — the only way the pipeline ever invokes the analyser — built its command as

    cmd = [exe, str(analyser), str(folder)]

and never passed it. So on every automated estimate the strongest geometry a paid seat can
produce was skipped, and the blank was inferred instead. Nothing failed; a measurement was
simply never taken, which is the same shape as every other defect in this suite that cost money
quietly.

THE TRADE, stated plainly, because "it costs time" was a real objection and not a silly one.
Flattening fires only on a part that is sheet metal, IS formed, and has NO usable blank from the
cut list. That is exactly the population that would otherwise be guessed. Seconds of rebuild per
such part against a mis-bought blank is not a close call.

THE RISK THAT IS REAL, and the reason this could not simply be turned on. Flattening is
read-only in intent — the bend state is restored and the document closed without saving — but on
a BORROWED document, one a designer already has open, all of that happens inside the window they
are looking at: the part visibly unfolds and refolds, and the rebuild marks their file dirty.
That is the same distinction `close_all()` already draws, and it is why document acquisition
could be turned back on at all. So flattening is refused on any borrowed document.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_ANALYSER_PATH = _ROOT / "tools" / "solidworks" / "sw_native_analyse.py"
_CONNECTOR_PATH = _ROOT / "src" / "source_connectors" / "solidworks.py"
_ANALYSER = _ANALYSER_PATH.read_text(encoding="utf-8")
_CONNECTOR = _CONNECTOR_PATH.read_text(encoding="utf-8")


def _run_analyser_source() -> str:
    """The body of the one function that invokes the analyser as a subprocess."""
    at = _CONNECTOR.index("def _run_analyser(")
    tree = ast.parse(_CONNECTOR)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_analyser":
            lines = _CONNECTOR.splitlines()[node.lineno - 1:node.end_lineno]
            return "\n".join(lines)
    raise AssertionError("_run_analyser not found")            # pragma: no cover


# ── the measurement is asked for ───────────────────────────────────────────────

def test_flattening_is_on_by_default_in_the_analyser():
    """THE ASSERTION. It defaulted to False and only a command-line flag turned it on, so
    every caller that did not know about the flag silently got the inferred blank."""
    tree = ast.parse(_ANALYSER)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "ALLOW_FLATTEN" for t in node.targets):
            assert node.value.value is True, (
                "ALLOW_FLATTEN defaults to False — a paid seat's best measurement is off "
                "unless somebody passes a flag")
            return
    raise AssertionError("ALLOW_FLATTEN is not assigned at module level any more")


def test_the_pipeline_does_not_turn_it_off():
    """The default only helps if the one path that actually runs the analyser leaves it
    alone. This is where it was lost: the command was built without the flag and nobody
    reading `_run_analyser` would have known a flag existed."""
    body = _run_analyser_source()
    assert "--no-flatten" in body, (
        "_run_analyser does not mention flattening at all — which is how it came to be "
        "skipped on every automated estimate")
    # Only ever appended under the explicit opt-out, never unconditionally.
    for m in re.finditer(r'^(\s*)cmd\.append\("--no-flatten"\)', body, re.M):
        indent = len(m.group(1))
        assert indent > 4, "--no-flatten is appended unconditionally, disabling the measurement"


def test_the_opt_out_exists_and_is_named():
    """"It costs time" was a real objection. Somebody batching a thousand legacy models has
    to be able to turn it off — by name, not by editing the source."""
    body = _run_analyser_source()
    assert "SDI_SW_FLATTEN" in body
    assert re.search(r'"0", "false", "no", "off"', body), (
        "the opt-out should accept the same spellings as every other switch in this codebase")


def test_the_old_flag_still_works_rather_than_erroring():
    """--flatten is in scripts and in people's notes. A flag that starts erroring is a worse
    answer than a flag that agrees with the default."""
    assert '"--flatten" in argv' in _ANALYSER
    assert "--no-flatten" in _ANALYSER


# ── it is never done to somebody else's open document ─────────────────────────

def test_a_borrowed_document_is_never_flattened():
    """THE THING THAT MADE THIS SAFE TO DEFAULT ON. Read-only in intent is not the same as
    invisible: on a document a designer has open, the part unfolds and refolds in front of
    them and the rebuild dirties their file."""
    assert "session.last_open_borrowed" in _ANALYSER, (
        "the flatten decision does not consult document ownership")
    m = re.search(r"sheet_metal_signals\(\s*\n?\s*doc,\s*allow_flatten=([^)]+)\)", _ANALYSER)
    assert m, "sheet_metal_signals is not called with an explicit flatten permission"
    assert "not session.last_open_borrowed" in m.group(1), (
        f"the permission passed is {m.group(1).strip()!r} — it must exclude borrowed documents")


def test_the_session_records_ownership_on_every_route_out_of_open():
    """`open()` has four ways of returning a document — reused, recovered from a
    same-title refusal, freshly opened, and the already-open branch. A route that forgets to
    record ownership leaves the previous file's value in place, and the NEXT part inherits
    it. That is a stale-flag bug that would flatten somebody's open model."""
    at = _ANALYSER.index("    def open(self, path: str):")
    body = _ANALYSER[at:_ANALYSER.index("    def _get_open_document(")]
    assert body.count("self.last_open_borrowed") >= 4, (
        f"only {body.count('self.last_open_borrowed')} ownership records in open() — every "
        f"return path needs one, including the reset at the top")
    # Reset before any branching, so no route can inherit the previous file's answer.
    first = body.index("self.last_open_borrowed")
    assert body.index("_get_open_document(path") > first, (
        "ownership is not reset before open() starts choosing a route")


# ── the reason it is worth the seconds ────────────────────────────────────────

def test_it_only_fires_where_the_blank_would_otherwise_be_guessed():
    """The cost objection is answered by the population, not by the speed. If this ran on
    every part it would be indefensible; it runs only where the alternative is a guess."""
    at = _ANALYSER.index("_may_flatten = ALLOW_FLATTEN if allow_flatten is None")
    condition = _ANALYSER[at:_ANALYSER.index(":", _ANALYSER.index("if (_may_flatten", at))]
    for required in ("sig.is_sheet_metal", "sig.bend_count", "not (sig.flat_length_mm"):
        assert required in condition, (
            f"the flatten condition no longer requires {required} — it would fire on parts "
            f"whose blank is already known, and the time objection would be a fair one")


def test_the_measurement_verifies_itself_rather_than_trusting_a_bend_state():
    """swSMBendState_e values differ across SolidWorks versions. The code tries each
    candidate and checks the RESULT against geometry only a real flatten can produce — the
    box must grow in an axis, and its smallest axis must collapse to sheet thickness. Without
    that, a version mismatch returns a plausible wrong number instead of nothing."""
    at = _ANALYSER.index("def flat_pattern_by_flatten(")
    body = _ANALYSER[at:at + 6000]
    assert "SELF-VERIFYING" in body
    assert "thickness" in body.lower() and "grow" in body.lower()


def test_nothing_is_written_to_any_file():
    """The contract that makes a rebuild acceptable at all. If this ever started saving, it
    would be writing to the live CAD share — which the whole Document Manager design exists
    to avoid."""
    at = _ANALYSER.index("def flat_pattern_by_flatten(")
    doc = ast.get_docstring(
        next(n for n in ast.walk(ast.parse(_ANALYSER))
             if isinstance(n, ast.FunctionDef) and n.name == "flat_pattern_by_flatten"))
    assert "without saving" in doc.lower()
    assert "nothing is written" in doc.lower()


# ── the analyser is launched by an interpreter that can talk to SolidWorks ────
#
# Everything above is moot if the subprocess never gets as far as a COM call.

def test_the_analyser_runs_under_the_interpreter_that_is_already_running():
    """THE OTHER WAY THIS SILENTLY DOES NOT FIRE, and it has nothing to do with flags.

    The engine is started as `.venv\\Scripts\\python.exe src\\main.py`. `_run_analyser`
    resolved its interpreter as

        exe = python_exe or os.environ.get("SDI_PYTHON_EXE") or "python"

    so with SDI_PYTHON_EXE unset it launched the analyser as bare `python` — a DIFFERENT
    interpreter, the system one or none at all, with no pywin32 in it. Every COM call then
    fails on a machine with a perfectly good seat, and invariants reports "the analyser had a
    problem" when the real problem is which python ran it.

    sw_batch_health.py, in the same directory, already resolved this correctly. Two ways of
    finding the interpreter is the same defect as two copies of an exclusion list, and it is
    invisible for the same reason: on a machine where bare `python` HAPPENS to be the venv,
    nothing goes wrong at all.
    """
    body = _run_analyser_source()
    m = re.search(r"exe\s*=\s*(.+)", body)
    assert m, "_run_analyser no longer resolves an interpreter"
    resolution = m.group(1)
    assert "sys.executable" in resolution, (
        f"the analyser is launched as {resolution.strip()} — without sys.executable it can "
        f"reach an interpreter that has no pywin32, and no COM call will succeed")
    assert resolution.index("sys.executable") < resolution.index('"python"'), (
        "bare \"python\" is tried before the running interpreter")


def test_both_launchers_resolve_the_interpreter_the_same_way():
    """The drift that caused it. If these two ever disagree again, one of them is wrong and
    nothing will say which."""
    health = (_ROOT / "tools" / "solidworks" / "sw_batch_health.py").read_text(encoding="utf-8")
    for source, name in ((_run_analyser_source(), "_run_analyser"),
                         (health, "sw_batch_health")):
        assert "SDI_PYTHON_EXE" in source and "sys.executable" in source, (
            f"{name} does not resolve the interpreter the same way as its sibling")


# ── the connector still parses and the analyser still imports cleanly ─────────

@pytest.mark.parametrize("path", [_ANALYSER_PATH, _CONNECTOR_PATH],
                         ids=["analyser", "connector"])
def test_the_file_still_parses(path):
    ast.parse(path.read_text(encoding="utf-8"))


# ── the measurement has to be findable once it is taken ───────────────────────
#
# Every analyser note was promoted to the part's `review_flags` — the list whose only job is
# to say "a person should look at this line". That included the analyser's own COM traces,
# which appear on every SolidWorks part. Turning flattening on adds more of them (one per
# rejected bend-state candidate), so switching the measurement on without filtering would
# have traded a silent gap for a noisy report.

import sys as _sys                                                         # noqa: E402
if str(_ROOT / "src") not in _sys.path:
    _sys.path.insert(0, str(_ROOT / "src"))
from source_connectors.solidworks import _is_com_trace                     # noqa: E402


@pytest.mark.parametrize("note", [
    "mdoc_wrapped=CDispatch",
    "first_feature=obj",
    "features_visited=47",
    "weldment_section=Square tube",
])
def test_com_plumbing_does_not_reach_an_estimator(note):
    """A review flag that fires on every part tells you nothing about any of them."""
    assert _is_com_trace(note, flatten_succeeded=False)


@pytest.mark.parametrize("note", [
    "REJECTED flat 126.39x82.2mm — part is FOLDED",
    "flat pattern MEASURED by flattening in memory: 132.39x88.2mm",
    "cutlist_err: COMError(...)",
    "material_name_err: AttributeError(...)",
    "feature_walk_error: RuntimeError(...)",
    "likely bought-in (imported body, no fabrication features)",
])
def test_findings_and_failures_still_reach_one(note):
    """An error is a finding: it is the difference between "we did not read a blank" and
    "we tried to read one and could not"."""
    assert not _is_com_trace(note, flatten_succeeded=False)


def test_a_rejected_bend_state_is_noise_once_another_one_worked():
    """Self-verification trying several states and discarding the wrong ones is the design
    working. It is only worth reporting when NONE of them worked — then it is the evidence
    for why this part has no blank."""
    attempt = "flatten attempt (state 2) rejected: box 126.4x82.2x14.0mm"
    assert _is_com_trace(attempt, flatten_succeeded=True)
    assert not _is_com_trace(attempt, flatten_succeeded=False)


def test_the_filter_is_applied_where_the_notes_are_promoted():
    """Defined and not called is the failure mode this whole file exists to catch."""
    body = _CONNECTOR[_CONNECTOR.index("for _n in nat.notes:") - 400:]
    assert "_is_com_trace(_n, flatten_succeeded=" in body[:900], (
        "the notes loop does not consult the filter")
    assert 'any("MEASURED by flattening" in _n for _n in nat.notes)' in body[:900], (
        "flatten_succeeded is not computed from the part's own notes")


def test_a_blank_that_was_measured_is_still_announced():
    """The point of the filter is to make this one visible, not to hide it with the rest."""
    assert not _is_com_trace(
        "flat pattern MEASURED by flattening in memory: 132.39x88.2mm "
        "(folded envelope was 126.39x82.2mm; blank is one sheet thick at 2mm) — bend state 2",
        flatten_succeeded=True)
