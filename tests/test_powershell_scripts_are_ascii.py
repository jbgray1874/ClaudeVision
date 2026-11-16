"""A .ps1 file must contain no byte above 127.

Windows PowerShell 5.1 reads a script as ANSI unless the file carries a BOM. A UTF-8
em-dash is three bytes, and 5.1 reads them as three ANSI characters — so

    $md += "# Parallel run - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"

arrived as `# Parallel run a<E2><80><94> $(...)` and the string parser broke on it. The
script had been written, reviewed and executed successfully — under PowerShell 7, which
defaults to UTF-8 and shows none of this. Twenty parse errors on the estimator's machine
from a file that ran perfectly on mine.

A BOM would also fix it. ASCII is better: it cannot be lost by an editor, a copy-paste,
a git filter, or a terminal in a different code page, and there is nothing an em-dash
does in a comment that a hyphen does not.

This test needs no PowerShell, so unlike the parse guard it runs everywhere — including
on the machines that would never have caught the bug it exists for.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _scripts():
    return sorted(p for p in ROOT.glob("*.ps1")) + \
           sorted(ROOT.glob("scripts/**/*.ps1")) + \
           sorted(ROOT.glob("sdi-intelligence-backend/*.ps1"))


def test_there_are_scripts_to_check():
    """A guard that finds no files reports success about nothing."""
    assert _scripts(), "no .ps1 files found — this guard is looking in the wrong place"


@pytest.mark.parametrize("script", _scripts(), ids=lambda p: p.name)
def test_a_powershell_script_is_pure_ascii(script):
    data = script.read_bytes()
    offenders = [(i, hex(b)) for i, b in enumerate(data) if b > 127]
    if not offenders:
        return

    # Name the LINE, not the byte offset. "byte 2553" sends the reader counting; a line
    # number and the text around it is one look.
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    first = offenders[0][0]
    line_no = data[:first].count(b"\n") + 1
    context = lines[line_no - 1] if line_no <= len(lines) else ""
    pytest.fail(
        f"{script.name} holds {len(offenders)} non-ASCII byte(s); Windows PowerShell 5.1 "
        f"reads this file as ANSI and will mangle them into a parse error.\n"
        f"  first at line {line_no}: {context.strip()[:110]}\n"
        f"  replace them with ASCII (- for an em-dash, GBP for a pound sign)")


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
