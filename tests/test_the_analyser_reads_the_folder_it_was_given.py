"""The analyser reads the folder it was pointed at, and says so when it does not.

11650's cabinet blocks on native_models_not_read: 41 SolidWorks models in the job folder,
none of them read. The obvious reading is "nobody ran the analyser", and that is where this
stopped for a week. It is not the only way to get there.

THE TWO HALVES OF THIS SYSTEM COUNTED THE SAME FOLDER BY DIFFERENT RULES.

    consumer   native_files_state   p.relative_to(root).parts[:-1]     -> 3 models, BLOCK
    analyser   find_sw_files        Path(dirpath).parts                -> 0 models, exit 1
    analyser   _fingerprint_native  prune dirnames only                -> 3 models

`Path(dirpath).parts` names every ANCESTOR of the walked directory, including the components
of the folder the operator typed. And because `dirs[:]` already prunes archive folders below
the root, that test could never fire on a descendant -- its only reachable effect was to
refuse the target itself. So a job living under any folder whose name contains wip, temp,
old, prev, bak or archive produced this exactly: the consumer counts the models and raises a
blocker, and the tool that exists to clear that blocker reports the folder empty and writes
nothing. WIP is where live models sit.

None of this needs SolidWorks to reproduce, which is the point -- the walk is filesystem
logic that happened to live inside a COM tool, and it was never tested because the file it
sits in cannot be imported without win32com.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from source_connectors.solidworks import native_files_state              # noqa: E402

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "solidworks" / "sw_native_analyse.py"


def _walkers():
    """The analyser's walk helpers, without importing the COM half of the module.

    The tool cannot be imported on a machine with no SolidWorks bindings, which is why none
    of this had a test. The helpers are pure filesystem code and are lifted out by source
    range so they can be exercised anywhere.
    """
    src = _TOOL.read_text(encoding="utf-8")
    ns = {"os": os, "re": re}
    exec("from pathlib import Path\nfrom typing import List, Any\n"
         + src[src.index("_EXCLUDED_DIR_TOKENS = ("):src.index("def main():")], ns)
    exec(src[src.index("def _fingerprint_native_files"):src.index("def _sw_version_string")],
         ns)
    ns["_fingerprint_scope"] = lambda t: t
    return ns


@pytest.fixture(scope="module")
def sw():
    return _walkers()


def _models(folder: Path, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"")
    return folder


# ── the defect ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ancestor", ["WIP", "Temp", "Old Jobs", "2024 Archive", "prev"])
def test_a_job_under_an_archive_named_ancestor_is_still_read(sw, tmp_path, ancestor):
    """The operator NAMED this folder. An archive heuristic exists to skip a superseded
    subfolder inside a job, not to overrule an explicit target -- and WIP is where live models
    live, so the token list makes the commonest working location unreadable."""
    job = _models(tmp_path / ancestor / "11650-00-GAFragranceCoffret",
                  "a.SLDPRT", "b.SLDPRT", "c.SLDASM")
    assert len(sw["find_sw_files"](str(job))) == 3


def test_the_analyser_and_the_consumer_agree_about_the_same_folder(sw, tmp_path):
    """THE CONTRADICTION, AS ONE ASSERTION. The consumer counting models it can see while the
    analyser reports the folder empty is not two bugs -- it is one disagreement, and the
    blocker it produces is unresolvable by the operator because the tool named in the message
    refuses to run."""
    job = _models(tmp_path / "WIP" / "11650", "a.SLDPRT", "b.SLDPRT", "c.SLDASM")
    assert native_files_state(job)["count"] == len(sw["find_sw_files"](str(job))) == 3


def test_all_three_walks_see_the_same_files(sw, tmp_path):
    """The fingerprint is a third walk with a third rule, and its docstring claims it shares
    the analyser's exclusions. A manifest describing files the extract does not contain is how
    a freshness check passes on an extract of nothing."""
    job = _models(tmp_path / "WIP" / "11650", "a.SLDPRT")
    assert bool(sw["_fingerprint_native_files"](str(job)))
    assert len(sw["find_sw_files"](str(job))) == native_files_state(job)["count"] == 1


# ── and the exclusion still does its job below the root ─────────────────────────────
def test_an_archive_subfolder_inside_the_job_is_still_skipped(sw, tmp_path):
    """The narrowing must not take the rule with it. A superseded model two revisions old,
    sitting in the job's own Archive folder, is exactly what this was written to skip."""
    job = tmp_path / "11650"
    _models(job, "live.SLDPRT")
    _models(job / "Archive", "superseded.SLDPRT")
    _models(job / "Old Revs", "older.SLDPRT")
    assert [Path(p).name for p in sw["find_sw_files"](str(job))] == ["live.SLDPRT"]


def test_the_two_token_lists_have_not_drifted_apart(sw):
    """The analyser and the connector each keep a copy, and the connector's comment records
    that they were reconciled once already. Two copies of one rule is how the halves came to
    disagree in the first place."""
    from source_connectors import solidworks as conn
    assert set(sw["_EXCLUDED_DIR_TOKENS"]) == set(conn._EXCLUDED_DIR_TOKENS)
    assert set(sw["_EXCLUDED_DIR_PHRASES"]) == set(conn._EXCLUDED_DIR_PHRASES)


# ── which kind of nothing ───────────────────────────────────────────────────────────
def test_an_empty_folder_and_an_excluded_folder_get_different_answers(sw, tmp_path):
    """"No SolidWorks files under X" is true and useless: it cannot tell a folder with no
    models from one whose models were every one of them excluded, and those need opposite
    responses. An operator whose models sat one directory name away from being read was told
    to go and look somewhere else entirely."""
    empty = tmp_path / "drawings-only"
    empty.mkdir()
    (empty / "11650-01.PDF").write_bytes(b"")
    assert "no .SLDPRT" in sw["explain_no_files"](str(empty))

    job = tmp_path / "11650"
    _models(job / "Superseded", "a.SLDPRT", "b.SLDPRT")
    told = sw["explain_no_files"](str(job))
    assert "2 of 2 model file(s) were EXCLUDED" in told
    assert "Superseded" in told, "the message does not name the folder that did the excluding"
    assert "point me directly at the subfolder" in told


def test_the_diagnostic_names_a_file_name_exclusion_too(sw, tmp_path):
    job = tmp_path / "11650"
    _models(job, "bracket (old).SLDPRT")
    assert "FILE name" in sw["explain_no_files"](str(job))


def test_the_diagnostic_is_printed_when_nothing_is_analysed():
    """Built is not wired. A diagnostic function that main() never calls leaves the operator
    with the same unusable sentence."""
    src = _TOOL.read_text(encoding="utf-8")
    body = src[src.index("def main():"):]
    assert "explain_no_files(target)" in body, \
        "the analyser still exits without saying why it found nothing"


if __name__ == "__main__":                                              # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── "I could not look" is not "there is nothing there" ──────────────────────────────
# The VPN goes down, or the drive is not mapped, or the job runs from a local copy of the
# drawings while the models sit on the share. native_files_state returned count 0 and the
# consumer's "models present but unread" branch is keyed on a NON-ZERO count, so the whole
# SolidWorks story went silent -- and a job that says nothing about models reads exactly like
# a job that has none. A dropped connection REMOVED a blocker instead of raising one, and the
# estimate looked more complete than the one taken while the drive was up.
def test_a_reachable_folder_with_no_models_and_an_unreachable_one_are_different(tmp_path):
    from source_connectors.solidworks import native_files_state
    empty = tmp_path / "drawings-only"
    empty.mkdir()
    assert native_files_state(empty) == {**native_files_state(empty),
                                         "count": 0, "folder_reachable": True}
    gone = native_files_state(tmp_path / "K-drive-is-down")
    assert gone["count"] == 0 and gone["folder_reachable"] is False


def test_an_unreachable_folder_blocks_rather_than_going_quiet():
    """A blocker, not a warning, and its own code. The action is different from every other
    SolidWorks finding -- reconnect the drive, not run the analyser -- and until it is done
    nothing whatsoever can be concluded about this job's models."""
    src = (Path(__file__).resolve().parents[1] / "src" / "invariants.py").read_text(
        encoding="utf-8")
    assert '"native_folder_unreachable", BLOCKING' in src
    assert "NOT evidence that the job has no models" in src


def test_the_connector_records_it_and_the_scan_reports_it():
    """Built is not wired. A reachability flag nothing reads restores the silence exactly."""
    conn = (Path(__file__).resolve().parents[1] / "src" / "source_connectors"
            / "solidworks.py").read_text(encoding="utf-8")
    scan = (Path(__file__).resolve().parents[1] / "src" / "file_scan.py").read_text(
        encoding="utf-8")
    assert 'job.meta["native_folder_unreachable"]' in conn
    assert 'native_folder_unreachable' in scan and "COULD NOT LOOK" in scan


# ── the exit code is the only thing a script reads ──────────────────────────────────
# Every per-file failure is caught, recorded and written, and the process then exited ZERO.
# So an extraction in which SolidWorks opened nothing at all reported SUCCESS to its caller,
# wrote a well-formed extract full of error-only records, and left "did the analyser work?"
# answerable only by a human reading scrollback. The manifest has always carried files_read;
# nothing that runs this tool was ever told.
def _main_src():
    src = _TOOL.read_text(encoding="utf-8")
    return src[src.index("def main():"):]


def test_a_run_that_read_nothing_exits_non_zero():
    body = _main_src()
    assert "if all_results and not _ok:" in body, \
        "a run where every file failed still reports success to its caller"
    assert body.count("sys.exit(1)") >= 2


def test_a_partial_run_still_exits_zero():
    """Some files failing is normal -- a model open in a designer's session, a corrupt
    fixture -- and the extract is worth having: the consumer already weighs coverage and
    blocks when the failures touch the priced assembly. Exiting non-zero on any failure would
    train whoever runs this to ignore the exit code, which is how it came to be ignored."""
    body = _main_src()
    assert "if all_results and not _ok:" in body
    assert "if _errors and not _ok" not in body and "if _errors:\n        sys.exit" not in body


def test_an_extract_taken_while_the_models_moved_is_a_failed_run():
    """The results describe the files as they were when each was opened, which is no longer
    what is on disk. It is already printed as a warning and marked in the manifest; the exit
    code has to agree, or a script re-uses it as a valid snapshot."""
    body = _main_src()
    # rindex, not index: _fp_changed is tested TWICE -- once to print the warning, long
    # before the write, and once at the end to set the exit code. Asserting on the first
    # occurrence passes whether or not the second one exists, which is the whole thing
    # being checked here.
    assert body.count("if _fp_changed:") == 2
    assert body.rindex("if _fp_changed:") > body.index("EXTRACT_PATH")


def test_the_extract_is_still_written_before_the_failure_exit():
    """Minutes of SolidWorks document opens, and the error records are the diagnostic. Exiting
    before the write would throw away the evidence of what failed."""
    body = _main_src()
    assert body.index("_write(out_json)") < body.index("if all_results and not _ok:")
