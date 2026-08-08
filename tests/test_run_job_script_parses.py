"""run-job.ps1 must at least parse.

This exists because a PowerShell bug shipped from a container with no PowerShell in it:
`@()` around a list but not the pipeline, so a single surviving search root unwrapped to a
bare string and the `+=` that appends the parent concatenated onto it instead. Nothing
caught it, because nothing could run it.

SKIPPED WHERE PWSH IS ABSENT, AND THAT IS HONEST. On a Windows estimating machine there is
Windows PowerShell 5.1 and no `pwsh`, so this will skip there and run wherever PowerShell 7
is installed — a CI image, a dev container. A skip reports itself; it does not report a
pass. The script's real exercise is the manual run, and this only rules out the class of
failure that never reaches one.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "run-job.ps1"

PWSH = shutil.which("pwsh") or next(
    (str(p) for p in (Path("/opt/ps/pwsh"),) if p.is_file()), None)


@pytest.mark.skipif(not PWSH, reason="no PowerShell 7 on this machine")
def test_the_job_runner_parses():
    check = (
        "$e = $null; $t = $null; "
        f"$null = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPT}', [ref]$t, [ref]$e); "
        "if ($e -and $e.Count) { "
        "  $e | ForEach-Object { \"line $($_.Extent.StartLineNumber): $($_.Message)\" }; "
        "  exit 1 } else { exit 0 }"
    )
    out = subprocess.run([PWSH, "-NoProfile", "-Command", check],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, f"run-job.ps1 does not parse:\n{out.stdout}{out.stderr}"


def test_the_script_is_where_the_documentation_says_it_is():
    """Running it from src\\ reports an unknown COMMAND rather than a missing FILE, which
    names neither the file nor the directory. The header says to run from the repo root;
    this asserts the arrangement that makes that instruction true."""
    assert SCRIPT.is_file()
    assert not (SCRIPT.parent / "src" / "run-job.ps1").exists(), \
        "a second copy under src\\ would make 'run from the repo root' wrong"
    assert "cd C:\\ClaudeVision" in SCRIPT.read_text(encoding="utf-8-sig"), \
        "the header no longer tells the reader where to run it from"


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
