"""An uploaded AI workbook must reach parity under the name the estimator's file had.

The AI side of a parity report is the engine's SUMMARY JSON. `resolve_ai_summary` exists so that
an estimator can hand over the workbook instead — which is the artefact they were actually sent —
and it finds the summary by stripping the run timestamp off the filename:

    1057502_20260824_162345.xlsx  ->  1057502.json

The upload path spooled the file to `tempfile.NamedTemporaryFile(suffix=...)`, whose name is
random. So every uploaded AI workbook arrived as `tmpq7x3k1a9.xlsx`, resolved to
`tmpq7x3k1a9.json`, and failed — with a message quoting a temp path the estimator has never seen.
"Choose from share" worked and "upload" could not, for a reason invisible from the outside.

These tests cover the name surviving the spool, and the sanitising not being a way to write
outside the temp directory it was given.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.append(str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("pr", _ROOT / "src" / "parity_run.py")
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)


# The sanitiser as the route applies it. Kept here as the contract the route must satisfy: the
# route imports FastAPI, which the engine test run does not, so the rule is asserted rather than
# the function imported.
def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ +-]", "_", Path(name.replace("\\", "/")).name).lstrip(".")


# ── the name survives, and the summary resolves ────────────────────────────────────────

def test_the_engine_workbook_name_still_yields_the_job_stem():
    """The whole point. Timestamp off, job left."""
    assert pr._job_stem(Path("1057502_20260824_162345.xlsx")) == "1057502"


def test_a_spooled_upload_resolves_its_summary(tmp_path):
    spool = tmp_path / "sdi_parity_x"
    spool.mkdir()
    wb = spool / _safe("1057502_20260824_162345.xlsx")
    wb.write_bytes(b"not really a workbook, only the name is under test")
    (spool / "1057502.json").write_text("{}", encoding="utf-8")

    assert pr.resolve_ai_summary(wb).name == "1057502.json"


def test_a_random_temp_name_is_the_failure_this_prevents(tmp_path):
    """The old behaviour, asserted so it cannot come back unnoticed: with the name discarded
    there is no stem to resolve and the estimator gets an error naming a file they never had."""
    wb = tmp_path / "tmpq7x3k1a9.xlsx"
    wb.write_bytes(b"x")
    (tmp_path / "1057502.json").write_text("{}", encoding="utf-8")

    with pytest.raises(pr.ParityInputError) as e:
        pr.resolve_ai_summary(wb)
    assert "tmpq7x3k1a9.json" in str(e.value)


def test_the_manual_side_still_takes_the_older_xls():
    """.xls is the common format for a manual estimate on the share — it is read through xlrd,
    which returns computed values, so an .xls needs no open-and-save first."""
    assert ".xls" in pr.MANUAL_SUFFIXES


# ── sanitising is a security boundary, not a tidy-up ───────────────────────────────────

@pytest.mark.parametrize("hostile", [
    "../../../../Windows/System32/evil.xlsx",
    r"..\..\Windows\evil.xlsx",
    "/etc/passwd.xlsx",
    "....//evil.xlsx",
])
def test_a_hostile_upload_name_cannot_escape_the_temp_directory(hostile, tmp_path):
    """The name is used to build a path, and a browser is not obliged to send a clean one."""
    dest = tmp_path / _safe(hostile)
    assert dest.parent == tmp_path
    assert ".." not in dest.name and "/" not in dest.name and "\\" not in dest.name


def test_sanitising_cannot_smuggle_a_file_past_the_suffix_gate():
    """Substitution must not turn a rejected name into an accepted one. A name is checked before
    sanitising and the RESULT is checked again, so neither ordering is exploitable."""
    assert not _safe("payload.exe").lower().endswith((".xlsx", ".xlsm", ".xls"))
    # A name whose extension only becomes valid after substitution must still not appear valid.
    assert not _safe("payload.xls‮").lower().endswith((".xlsx", ".xlsm", ".xls"))


def test_a_name_that_is_only_punctuation_does_not_become_a_dotfile():
    assert not _safe("...xlsx").startswith(".")
