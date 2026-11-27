r"""
test_the_refusal_names_a_process_you_can_find.py

The single-runner refusal is correct and its diagnostic was not.

It told the reader to look for `Name='python.exe'`. The portal starts a runner of its own when
it starts, and starts it WINDOWLESS — so the runner the message is complaining about runs as
pythonw.exe and the query it hands you cannot see it. A live runner looked like a stale lock.

That is the one wrong conclusion this message must never invite, because the message's own
next line then tells you to delete the lock — a lock a running runner is holding.

3 September: twenty minutes lost to exactly that, and the process was there the whole time
under the other name.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "runner"))

SRC = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")


def _refusal_text() -> str:
    mod = pytest.importorskip("sdi_estimate_runner", reason="the runner")
    with pytest.raises(SystemExit) as e:
        mod._refuse("pid 61580 on DESKTOP-GFAAP80 since 2026-09-03 08:50:43")
    return str(e.value)


def test_it_still_says_who_holds_the_lock():
    """The whole point of reading the identity: WHICH window to close."""
    assert "pid 61580" in _refusal_text()


def test_the_query_it_hands_you_can_see_a_windowless_runner():
    text = _refusal_text()
    assert "pythonw.exe" in text, (
        "the portal starts its runner windowless; a query for python.exe alone cannot find "
        "the process this message is naming")
    assert "python.exe" in text, "a runner started by hand is a python.exe and still counts"


def test_the_query_is_one_powershell_command_that_parses():
    """It is pasted, not read. A line break in the wrong place makes it a syntax error, which
    is how the reader ends up guessing instead."""
    text = _refusal_text()
    m = re.search(r"Get-CimInstance Win32_Process -Filter \"([^\"]+)\"", text)
    assert m, "the filter is not a single quoted string any more"
    assert m.group(1).count("Name=") == 2 and " OR " in m.group(1)


def test_deleting_the_lock_is_gated_on_finding_nothing():
    """The dangerous half. Offered unconditionally it reads as the fix for a refusal, and the
    refusal is usually correct."""
    text = _refusal_text()
    i, j = text.index("Remove-Item"), text.index("ONLY if nothing at all is listed")
    assert j < i, "the condition must come before the command, not after it"


def test_it_says_why_this_usually_happens():
    """Restarting the portal starts a runner. Without that sentence the reader has no account
    of where the other runner came from, and concludes there isn't one."""
    assert "portal starts a runner of its own" in _refusal_text()


def test_the_lock_still_decides_and_the_text_is_only_a_label():
    """The identity may be stale without anything behaving incorrectly — an OS lock is
    released when the holder dies however it dies. This is asserted because the fix above
    makes the MESSAGE better and must not tempt anyone into trusting it over the lock."""
    i = SRC.index("def claim_the_machine")
    body = SRC[i:SRC.index("\ndef ", i + 10)]
    assert "if not _take_lock(handle):" in body
    assert "_refuse(previous or" in body, "the refusal must be driven by the lock, not the text"
