"""An elevated console can fail to reach SolidWorks, and the failure should offer that.

Windows will not hand an elevated process a COM server registered by a normal-integrity one,
so Dispatch("SldWorks.Application") from an admin console cannot ATTACH to a SolidWorks a
designer already has open. It tries to start a second, elevated instance, which a single-seat
licence refuses or hangs on.

THE FIRST VERSION OF THIS FILE SAID AN ELEVATED RUN CANNOT WORK AT ALL. That is wrong, and
the user had run it successfully that way. With SolidWorks CLOSED there is nothing to attach
to and the analyser starts its own instance quite happily. Shipping the stronger claim would
have sent somebody to reconfigure a machine that was fine -- the same shape as the stale
hazard note that kept native extraction switched off for weeks, and written into the product
by the person who had just finished removing that one.

So the hint is a CANDIDATE offered beside the real error, never a verdict. It earns its place
because "the analyser exited 1" otherwise sends somebody to check their licence, their share
and their models, when the answer may be that a colleague has the assembly open.
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
    assert "does not stop the analyser on its own" in msg, \
        "the hint must stay a candidate cause, not a verdict about a machine that may be fine"
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


def test_the_console_note_warns_about_solidworks():
    note = (_ROOT / "run-job.ps1").read_text(encoding="utf-8")
    block = note[note.index("NOTE: this console is ELEVATED."):][:1800]
    assert "SolidWorks IS affected" in block
    assert "elevated run starts its own instance and works" in block, \
        "the note must not tell somebody their working setup is broken"


def test_the_note_no_longer_claims_excel_is_affected():
    """IT NEVER WAS, AND THE CLAIM WAS MINE. Written on 9 August with no observed failure:
    the drive-mapping half of that commit had real evidence behind it and the Excel half was
    received wisdom stated as fact. It is wrong three times over.

      * the workbook is written by openpyxl -- wb.save() -- and needs no COM at all, so
        "the workbook may not be written" cannot happen for this reason;
      * the one thing that does use Excel COM, the read-back, calls DispatchEx, which always
        creates a NEW instance and never attaches to a running one;
      * so the integrity-level rule that genuinely bites SolidWorks cannot reach Excel here.

    SolidWorks uses plain Dispatch and therefore DOES attach, which is the whole difference,
    and the note now says which is which. Somebody had been running this way for months
    without a single failure and being told every time that their workbook might not be
    written."""
    note = (_ROOT / "run-job.ps1").read_text(encoding="utf-8")
    block = note[note.index("NOTE: this console is ELEVATED."):][:1800]
    assert "unreliable from an elevated process" not in block
    assert "the workbook may not be written" not in block
    assert "Excel is NOT affected" in block
    assert "openpyxl" in block and "DispatchEx" in block, \
        "the correction must say WHY, or it reads as an opinion swapped for another"


def test_the_two_com_calls_are_still_the_ones_the_note_describes():
    """The note now makes a claim about HOW each library is dispatched. If the read-back ever
    switches to plain Dispatch, or the analyser to DispatchEx, the note becomes wrong in the
    same way it was wrong before -- and nothing else would notice."""
    readback = (_ROOT / "src" / "wep_readback_from_xlsx.py").read_text(encoding="utf-8")
    analyser = (_ROOT / "tools" / "solidworks" / "sw_native_analyse.py").read_text(
        encoding="utf-8")
    assert 'DispatchEx("Excel.Application")' in readback
    assert 'Dispatch("SldWorks.Application")' in analyser
    assert 'DispatchEx("SldWorks.Application")' not in analyser


if __name__ == "__main__":                                              # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
