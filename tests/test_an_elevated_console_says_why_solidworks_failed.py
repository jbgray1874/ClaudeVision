"""An elevated console cannot reach SolidWorks at all, and the failure should say so.

Windows will not hand an elevated process a COM server running at normal integrity. The
running-object table an admin process can see is not the one a designer's SolidWorks
registered itself in, so Dispatch("SldWorks.Application") cannot ATTACH to the SolidWorks
already open on the machine -- it tries to start a second, elevated instance instead, which on
a single-seat licence fails or hangs.

THIS IS NOT THE EXCEL CAVEAT. run-job.ps1 has always warned that Excel COM is UNRELIABLE from
an elevated shell. SolidWorks is not unreliable there, it is unavailable -- and the note said
nothing about it, so the estimating PC ran elevated all week with forty-one models beside it
and the obvious suspects were the licence, the share and the models.

A failure that says only "the analyser exited 1" sends somebody to check all three. When the
cause is the window they typed into, the message should lead with that.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from source_connectors import solidworks as sw                        # noqa: E402


def test_elevation_is_three_valued_not_guessed():
    """False and "cannot tell" are different, and only one of them may print a confident
    sentence about UAC. Guessing False off Windows would put Windows advice in front of
    somebody running Linux."""
    assert sw.running_elevated() in (True, False, None)
    import os
    if os.name != "nt":
        assert sw.running_elevated() is None


def test_a_failed_analyser_run_names_elevation_when_we_are_elevated(monkeypatch):
    monkeypatch.setattr(sw, "running_elevated", lambda: True)

    class _R:
        returncode, stdout, stderr = 1, "", "Dispatch failed"
    monkeypatch.setattr(sw.subprocess, "run", lambda *a, **k: _R())
    msg = sw._run_analyser("/tmp/models")
    assert "ELEVATED" in msg and "NORMAL PowerShell" in msg
    assert "exited 1" in msg, "the underlying failure must still be reported"


def test_it_stays_quiet_about_elevation_when_we_are_not_elevated(monkeypatch):
    """A hint printed on every failure is a hint nobody reads. It has to mean something when
    it appears."""
    monkeypatch.setattr(sw, "running_elevated", lambda: False)

    class _R:
        returncode, stdout, stderr = 1, "", "no licence"
    monkeypatch.setattr(sw.subprocess, "run", lambda *a, **k: _R())
    msg = sw._run_analyser("/tmp/models")
    assert "ELEVATED" not in msg and "no licence" in msg


def test_an_exception_path_names_it_too(monkeypatch):
    """Dispatch failing outright raises rather than returning a code, and that is the shape
    the elevated case actually takes."""
    monkeypatch.setattr(sw, "running_elevated", lambda: True)

    def _boom(*a, **k):
        raise OSError("com error")
    monkeypatch.setattr(sw.subprocess, "run", _boom)
    assert "ELEVATED" in sw._run_analyser("/tmp/models")


def test_the_console_note_warns_about_solidworks_and_not_only_excel():
    """The note the estimating PC printed all week listed drive mappings and Excel. Nothing
    said the one thing that made native extraction impossible from that window."""
    note = (_ROOT / "run-job.ps1").read_text(encoding="utf-8")
    block = note[note.index("NOTE: this console is ELEVATED."):][:1400]
    assert "SOLIDWORKS CANNOT BE ATTACHED TO AT ALL" in block
    assert "Excel COM" in block, "the older Excel caveat must survive alongside it"


if __name__ == "__main__":                                              # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
