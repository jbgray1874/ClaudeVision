"""The explanation belongs in the workbook, and must never cost a run to put it there.

A document that travels beside a spreadsheet arrives without it — forwarded on its own, saved
somewhere else, stale the moment a rate is edited. So it is written into the file as a tab.
Everything about that is a nicety next to the estimate itself, which is why the writer's most
important property is that it cannot break a run.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import estimate_explanation_tab                                         # noqa: E402


def test_a_machine_with_no_excel_declines_rather_than_raising(tmp_path):
    """Every developer machine and every test runner is one of these."""
    book = tmp_path / "12552-00.xlsx"
    book.write_bytes(b"not really a workbook")
    assert estimate_explanation_tab.write_tab(book) is None


def test_a_missing_workbook_is_reported_not_raised(tmp_path):
    assert estimate_explanation_tab.write_tab(tmp_path / "nothing.xlsx") is None


def _function(source: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def test_every_step_that_can_fail_is_caught():
    """Structurally, not by reading the prose — a comment saying so matches a grep and a
    missing try does not."""
    fn = _function((SRC / "estimate_explanation_tab.py").read_text(encoding="utf-8"),
                   "write_tab")
    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
    assert len(handlers) >= 2, (
        "building the document and driving Excel are separate failures with separate "
        "reasons, and neither may reach the caller")
    assert any(isinstance(n, ast.Try) and n.finalbody for n in handlers), (
        "Excel must be quit in a finally, or a failed run leaves a headless EXCEL.EXE "
        "holding the workbook open against the next run")


def test_the_run_never_stops_for_a_missing_tab():
    """main.py calls it inside its own try, so even an import error is survivable."""
    source = (SRC / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_write_explanation_tab"]
    assert calls, "the tab is written from main.py after the read-back"

    guarded = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for call in calls:
                if any(call is inner for inner in ast.walk(node)):
                    guarded.append(call)
    assert len(guarded) == len(calls), (
        "an estimate that has taken an hour must not be lost to a tab that would not write")


def test_it_runs_after_the_read_back_and_not_before():
    """The tab prints Estimate!M and the sheet's own totals. Neither exists until Excel has
    calculated the template and the read-back has recorded what it found."""
    source = (SRC / "main.py").read_text(encoding="utf-8")
    assert source.index("stamp_real_totals_into_json") < source.index("_write_explanation_tab")


@pytest.mark.parametrize("name", ["build", "sections", "worksheet_rows"])
def test_the_tab_renders_the_document_rather_than_asking_again(name):
    """One builder. A tab that goes and reads the workbook itself is a second answer, and two
    answers to one question is the failure this document exists to expose."""
    source = (SRC / "estimate_explanation_tab.py").read_text(encoding="utf-8")
    assert f"estimate_explained.{name}" in source
