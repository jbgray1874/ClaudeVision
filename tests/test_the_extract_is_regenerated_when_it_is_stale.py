"""The engine said the extract was stale and then declined to regenerate it.

WHAT HAPPENED. 10575-02 was assembled by copying 28 SolidWorks models into the job folder,
and the run reported:

    [solidworks] EXTRACT IS STALE — the native models have changed since it was taken.
    [solidworks] native extract applied — flat+0 thickness+0 material+0 bends+0 qty+0
                 assembly-parent+0 bought-in+0

Every field zero. There is no "analyser exited" line anywhere in that log, because the
analyser was never launched.

TWO QUESTIONS, TWO SIGNALS, AND THEY DISAGREED.

    is the extract stale     compare the manifest's recorded fingerprint (count, size and
                             mtime of every native file) against the folder. Exact.
    should it be regenerated  newest_mtime > the extract's own mtime.

`Copy-Item` PRESERVES LastWriteTime. Those 28 models arrived carrying their original 2023
timestamps — older than the `_sw_native_extract.json` already sitting in the destination. So
the fingerprint saw 28 new files and said STALE; the timestamp check saw nothing newer and
said "no need". The estimate was then built on an extract describing a different set of
files, and nothing said the fix had been declined.

It was blamed on the console being elevated, which was wrong and worth recording: elevation
broke the DWG conversion, a separate path, and the engine itself reports that converting
those general arrangements "would add nothing" because the PDFs of the same sheets are
already read. An elevated run with SolidWorks CLOSED starts its own instance and works —
the connector says so in a comment written after that same mistake was made once before.

A timestamp is also blind to a deleted or renamed model, which is the same fault pointing the
other way.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
_SRC = (_ROOT / "src" / "source_connectors" / "solidworks.py").read_text(encoding="utf-8")


def _should_run():
    from source_connectors.solidworks import _should_run                # noqa: PLC0415
    return _should_run


def _job(tmp_path: Path, *, model_mtime: float, fingerprint: str | None,
         extract_mtime: float) -> Path:
    """A job folder with one model and one extract, both with times we choose."""
    model = tmp_path / "part.SLDPRT"
    model.write_bytes(b"x")
    import os
    os.utime(model, (model_mtime, model_mtime))

    # schema_version CURRENT, deliberately. _should_run re-runs an extract whose schema is
    # behind the code, and it checks that BEFORE anything else — so a fixture without it
    # returns True for a reason that has nothing to do with what is being tested here, and
    # every assertion below would pass while proving nothing.
    from source_connectors.solidworks import _MIN_EXTRACT_SCHEMA_VERSION    # noqa: PLC0415
    payload = {"parts": [], "schema_version": _MIN_EXTRACT_SCHEMA_VERSION}
    if fingerprint is not None:
        payload["_manifest"] = {"native_files_fingerprint": fingerprint,
                                "schema_version": _MIN_EXTRACT_SCHEMA_VERSION}
    extract = tmp_path / "_sw_native_extract.json"
    extract.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(extract, (extract_mtime, extract_mtime))
    return extract


# ── the failure that prompted this ───────────────────────────────────────────

def test_a_copied_model_with_an_old_timestamp_still_triggers_a_re_run(tmp_path):
    """THE ASSERTION. The model is OLDER than the extract — exactly what Copy-Item produces —
    but it is not the file the extract describes."""
    extract = _job(tmp_path, model_mtime=1_600_000_000,       # 2020
                   fingerprint="anextractofsomethingelse",
                   extract_mtime=1_750_000_000)               # 2025, newer
    assert _should_run()(extract, tmp_path), (
        "the analyser would not be launched, so the estimate is built on an extract that "
        "describes a different set of files — and nothing says the fix was declined")


def test_a_matching_fingerprint_does_not_re_run(tmp_path):
    """The other half. Re-running the analyser costs minutes and a SolidWorks seat; doing it
    when nothing has changed would make every job pay for it."""
    from source_connectors.solidworks import native_files_state          # noqa: PLC0415
    extract = _job(tmp_path, model_mtime=1_600_000_000, fingerprint="placeholder",
                   extract_mtime=1_750_000_000)
    from source_connectors.solidworks import _MIN_EXTRACT_SCHEMA_VERSION  # noqa: PLC0415
    real = native_files_state(tmp_path)["fingerprint"]
    extract.write_text(json.dumps(
        {"schema_version": _MIN_EXTRACT_SCHEMA_VERSION,
         "_manifest": {"native_files_fingerprint": real,
                       "schema_version": _MIN_EXTRACT_SCHEMA_VERSION}}), encoding="utf-8")
    import os
    os.utime(extract, (1_750_000_000, 1_750_000_000))
    assert not _should_run()(extract, tmp_path), (
        "the analyser re-runs when the files are unchanged, so every job pays for a seat "
        "and several minutes it does not need")


# ── the cases the timestamp still covers ─────────────────────────────────────

def test_no_manifest_falls_back_to_the_timestamp(tmp_path):
    """Older extracts carry no manifest. A weaker check is better than none, and the
    connector already records that it was weak."""
    extract = _job(tmp_path, model_mtime=1_800_000_000, fingerprint=None,
                   extract_mtime=1_700_000_000)
    assert _should_run()(extract, tmp_path), "a newer model no longer triggers a re-run"


def test_a_missing_extract_always_runs(tmp_path):
    assert _should_run()(tmp_path / "nothing.json", tmp_path)


def test_an_extract_behind_the_code_still_re_runs(tmp_path):
    """Checked before the fingerprint, and it must stay that way: a 2019 model is older than
    any extract taken since, so the same unchanged files can still owe us a field the code
    has since learned to read."""
    import os                                                            # noqa: PLC0415
    (tmp_path / "part.SLDPRT").write_bytes(b"x")
    extract = tmp_path / "_sw_native_extract.json"
    extract.write_text(json.dumps({"schema_version": 1, "_manifest": {}}), encoding="utf-8")
    os.utime(extract, (1_750_000_000, 1_750_000_000))
    assert _should_run()(extract, tmp_path), (
        "an extract behind the schema is reused, so a field the code can now read is never "
        "picked up from models that have not changed")


def test_an_unreadable_folder_does_not_wipe_a_good_extract(tmp_path):
    """An empty current fingerprint means the folder could not be read — a VPN down, a share
    not mapped. Re-running against files it cannot see would replace a good extract with an
    empty one, which is worse than a stale one."""
    extract = _job(tmp_path, model_mtime=1_600_000_000, fingerprint="recorded",
                   extract_mtime=1_750_000_000)
    for f in tmp_path.glob("*.SLDPRT"):
        f.unlink()
    assert not _should_run()(extract, tmp_path), (
        "with no readable native files it would re-run and overwrite the extract with nothing")


# ── the two signals answer to one definition ─────────────────────────────────

def test_both_questions_now_use_the_fingerprint():
    """The defect was not either check being wrong. It was two checks answering the same
    question by different means and disagreeing on a real job."""
    at = _SRC.index("def _should_run")
    body = _SRC[at:_SRC.index("\ndef ", at + 10)]
    assert "native_files_fingerprint" in body, (
        "the re-run decision does not consult the fingerprint the staleness check uses")
    assert "newest_mtime" in body, "the timestamp fallback for manifest-less extracts is gone"
