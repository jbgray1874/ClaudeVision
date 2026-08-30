"""A switch nobody can find is a switch nobody sets.

SDI_SW_RUN_ANALYSER decided whether the strongest source in the building was read at all. It
was read in exactly one place, set in none, and documented in NEITHER README -- while both of
its sibling variables were. The only way to learn it existed was to read file_scan.py.

That is not a footnote to the regression, it is most of it. The in-pipeline analyser call was
turned off in July for a good reason, the reason was fixed, and the default was never
restored -- and nobody noticed for weeks, because the one thing that could have turned it
back on was invisible from outside the source. Meanwhile every job quietly reported
"native_models_not_read" and everyone read that as an ops step nobody had done.

So the rule is: if the engine's behaviour depends on an environment variable, the variable is
written down where an operator looks. Not a comment beside the getenv -- a comment is only
visible to whoever is already reading that file, and whoever is reading that file does not
need it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

# Where an operator would look. A variable named in either is documented.
_DOCS = ("README.md", "tools/solidworks/README.md")

_GETENV = re.compile(r"""os\.getenv\(\s*["'](SDI_[A-Z0-9_]+)["']""")


def _read_switches() -> dict:
    """Every SDI_* variable the shipped engine reads, and where from."""
    found: dict = {}
    for path in sorted((_ROOT / "src").rglob("*.py")):
        # Probes, patches and one-off diagnostics are not the shipped engine; they come and
        # go and holding them to the documentation rule would make it noise.
        if path.name.startswith(("_", "patch_", "diag_", "check_", "probe_", "test_")):
            continue
        if not path.is_file():      # this tree contains a directory named *.py
            continue
        for name in _GETENV.findall(path.read_text(encoding="utf-8", errors="ignore")):
            found.setdefault(name, str(path.relative_to(_ROOT)))
    return found


def _documented() -> set:
    text = "\n".join((_ROOT / d).read_text(encoding="utf-8") for d in _DOCS)
    return set(re.findall(r"SDI_[A-Z0-9_]+", text))


def test_every_environment_switch_the_engine_reads_is_documented():
    undocumented = {n: w for n, w in _read_switches().items() if n not in _documented()}
    assert not undocumented, (
        "these switches change what the engine does and appear in no README, so the only way "
        "to discover them is to read the source: "
        + "; ".join(f"{n} (read in {w})" for n, w in sorted(undocumented.items())))


def test_the_switch_that_caused_the_regression_is_named_in_the_docs():
    """Belt and braces on the specific one, because the general rule above would be satisfied
    by documenting it once and could be satisfied again by deleting the mention."""
    assert "SDI_SW_RUN_ANALYSER" in _documented()


def test_the_docs_say_which_way_the_solidworks_default_points():
    """"There is a switch" is not the fact that matters. The fact that matters is what happens
    when nobody touches it -- and for weeks the answer was "your models are not read"."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    line = next(ln for ln in readme.splitlines() if "SDI_SW_RUN_ANALYSER" in ln)
    assert "the analyser runs" in line, "the documented default must state that it runs"
    assert "=0" in line, "and how to turn it off where that matters"


def test_the_tool_readme_says_it_is_not_a_routine_manual_step():
    """The estimate invokes it. A README that reads like a required ritual is how a fixed
    default goes unnoticed -- everybody assumes the manual step is simply outstanding."""
    doc = (_ROOT / "tools" / "solidworks" / "README.md").read_text(encoding="utf-8")
    assert "do not normally run this tool by hand" in doc.lower()


def test_the_operator_has_the_exact_commands_not_a_description():
    """A runbook that says "run the analyser on the job folder" is how three sessions were
    lost to unset variables and unquoted paths. The folders contain spaces; the commands have
    to be copyable."""
    doc = (_ROOT / "tools" / "solidworks" / "README.md").read_text(encoding="utf-8")
    assert "sw_native_analyse.py \"$pack\" --out \"$extract\"" in doc, \
        "the hand-run command must be quoted and copyable"
    assert "$LASTEXITCODE" in doc, "and the exit code must be readable without guessing"
    for code in ("| `0` |", "| `1` |", "| `2` |"):
        assert code in doc, f"exit code {code} is not explained"
    assert "Remove-Item Env:\\SDI_SW_EXTRACT_JSON" in doc, \
        "an extract path left in the environment follows the operator onto the next job"


def test_the_limits_are_written_down_with_their_numbers():
    """"There are limits" helps nobody. The numbers are what let somebody tell a folder that
    is too big from a model that is out of window from a licence that is not there."""
    doc = (_ROOT / "tools" / "solidworks" / "README.md").read_text(encoding="utf-8")
    for fact in ("30 minutes", "1 \u2013 2500 mm", "0.3 \u2013 50 mm", "off unless `--flatten`"):
        assert fact in doc, f"the limit {fact!r} is not documented"


if __name__ == "__main__":                                              # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
