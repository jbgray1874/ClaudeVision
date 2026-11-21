"""A BRIEF PAGE IS DRAWN EVEN WHERE THE SERVICE HAS NO PyMuPDF (21 Nov 2026).

The first description-only TTI row sent through the service ended in an HTTP 500:
"ModuleNotFoundError: No module named 'pymupdf'". The service stages a brief-only job by drawing
the brief as a page image, PyMuPDF is the ENGINE's library, and the service's own environment
never listed it. The page is now drawn in the service where the library is there, and otherwise
by the engine's Python, out of process. With neither, the refusal is a staging error that says
what to install: an answer, not a crash.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def staging(tmp_path, monkeypatch):
    stub = types.ModuleType("config")
    stub.STAGING_ROOT = str(tmp_path / "SDIIntelligenceAISheet")
    monkeypatch.setitem(sys.modules, "config", stub)
    spec = importlib.util.spec_from_file_location("staging_brief_page_under_test", BACKEND / "staging.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _no_pymupdf(monkeypatch):
    """The service's environment as it was on the laptop: neither name of PyMuPDF imports."""
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    monkeypatch.setitem(sys.modules, "fitz", None)


def test_with_no_pymupdf_in_the_service_the_engines_python_draws_the_page(staging, tmp_path, monkeypatch):
    _no_pymupdf(monkeypatch)
    monkeypatch.setenv("SDI_ENGINE_PYTHON", sys.executable)      # this test's Python has PyMuPDF
    res = staging.stage_brief_only(client="TTI", drawing="TTI-C-test", brief="A red steel table, 3 off.")
    page = Path(res["folder"]) / staging.BRIEF_PAGE_NAME
    assert page.is_file() and page.stat().st_size > 1000
    assert res["brief_only"] is True


def test_with_neither_it_is_a_staging_error_that_says_what_to_install(staging, tmp_path, monkeypatch):
    _no_pymupdf(monkeypatch)
    monkeypatch.setenv("SDI_ENGINE_PYTHON", str(tmp_path / "no" / "python.exe"))
    with pytest.raises(staging.StagingError) as exc:
        staging.stage_brief_only(client="TTI", drawing="TTI-C-test", brief="A red steel table.")
    assert "PyMuPDF" in str(exc.value) and "SDI_ENGINE_PYTHON" in str(exc.value)


def test_where_the_service_has_it_the_page_is_drawn_in_process(staging):
    res = staging.stage_brief_only(client="TTI", drawing="TTI-C-test2", brief="A blue rack.")
    assert (Path(res["folder"]) / staging.BRIEF_PAGE_NAME).is_file()
