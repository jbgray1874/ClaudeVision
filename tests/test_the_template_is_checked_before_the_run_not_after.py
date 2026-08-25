"""The workbook template must be checked before the engine starts, not sixteen minutes in.

10575-02 on 25 Aug read the pack, priced it, ran the arbitration and the invariants — and then:

    [wb_populate] TEMPLATE NOT FOUND: \\\\sdi-dc01\\...\\AISheets\\Blank Estimate Sheet  WB 2026.xlsx
    [wb_populate] failed (populate_workbook returned None)
    -> NO fallback workbook written: canonical route cutover is enabled, and the legacy
       builder can resurrect or multiply rejected operations.

The refusal to fall back is correct — the legacy builder can resurrect rejected operations, and
a wrong workbook is worse than none. But it meant there was no second path, so the run ended
with a summary and no estimate after 971 seconds.

The runner already pre-checks the drawing, the job folder and the parity workbook, with the
reason written into the source: a path this runner cannot see "must be reported as such, not
handed to the engine to fail forty minutes later inside the deliverables pass." The template was
simply not on that list, and it is the one that decided the outcome.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "runner", _ROOT / "tools" / "runner" / "sdi_estimate_runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


# ── the runner and the engine must look for the same file ──────────────────────────────

def test_the_runner_default_matches_the_engine_default():
    """A runner that checks for a different file than the engine opens is worse than no check:
    it would pass a run the engine then fails on, which is the bug it exists to prevent.

    Read out of wb_populate's source rather than imported — importing the engine pulls in
    openpyxl and a `config` module that collides with the backend's."""
    src = (_ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    at = src.index('"template_path"')
    line = src[at:src.index("\n", at)]
    default = line.split("r\"", 1)[1].rsplit("\"", 1)[0]
    assert default == runner.WB_TEMPLATE_DEFAULT, (
        "the runner pre-checks a different template than wb_populate opens:\n"
        f"  engine: {default}\n  runner: {runner.WB_TEMPLATE_DEFAULT}")


def test_the_double_space_in_the_filename_is_preserved():
    """`Blank Estimate Sheet  WB 2026.xlsx` really does carry two spaces. Anything that
    normalises whitespace here turns a working path into a missing file."""
    assert "Sheet  WB" in runner.WB_TEMPLATE_DEFAULT


# ── the override, resolved the same way ────────────────────────────────────────────────

def test_the_env_override_wins(monkeypatch):
    monkeypatch.setenv("SDI_WB_TEMPLATE", r"C:\local\template.xlsx")
    assert runner.workbook_template() == r"C:\local\template.xlsx"


def test_quotes_around_the_override_are_stripped(monkeypatch):
    """Windows users paste paths with the quotes still attached, and a quoted path is a path
    that does not exist."""
    monkeypatch.setenv("SDI_WB_TEMPLATE", '"C:\\local\\template.xlsx"')
    assert runner.workbook_template() == r"C:\local\template.xlsx"


def test_an_empty_override_falls_back_to_the_share(monkeypatch):
    monkeypatch.setenv("SDI_WB_TEMPLATE", "   ")
    assert runner.workbook_template() == runner.WB_TEMPLATE_DEFAULT


def test_no_override_is_the_share(monkeypatch):
    monkeypatch.delenv("SDI_WB_TEMPLATE", raising=False)
    assert runner.workbook_template() == runner.WB_TEMPLATE_DEFAULT


# ── the check is wired in, and before the engine is launched ───────────────────────────

def test_the_check_runs_before_the_engine_is_started():
    """Ordering is the whole point. A template check after `subprocess` has been launched
    saves nobody the sixteen minutes."""
    src = (_ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    check = src.index("The estimate workbook template is not readable")
    launch = src.index("cmd = engine_command(")
    assert check < launch, "the template is checked after the engine command is built"


def test_the_failure_names_the_path_and_the_override():
    """"Template not found" without the path is a message that starts an investigation
    instead of ending one."""
    src = (_ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    at = src.index("The estimate workbook template is not readable")
    msg = src[at:at + 700]
    assert "{tpl}" in msg
    assert "SDI_WB_TEMPLATE" in msg
