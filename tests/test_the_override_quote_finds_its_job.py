"""A regenerated quote must carry the job, not just the price — and must say when it cannot.

THE LOOKUP FAILED ON EVERY REGENERATION MADE FROM THE PORTAL, AND FAILED SILENTLY.

run_estimator_override copies the estimator's sheet to '<stem>_MANUAL_OVERRIDE.xlsx' and then
asks find_original_summary about THAT path. The stem deriver strips a '_YYYYMMDD_HHMMSS' suffix
and nothing else, so it went looking for '10575-02_MANUAL_OVERRIDE.json' — a file that cannot
exist. The job's summary was never found, so the quotation lost the GA image, the real material
and the real operation list, and kept only the money.

It passed its tests because they called regenerate_quote_from_workbook directly, on the engine's
own '<stem>_<timestamp>.xlsx', where the deriver is correct. The portal takes the other path.

And the failure was invisible: the flag saying the summary was missing was returned into `_` and
discarded, so the CLI could not print it, the route could not return it and the page could not
show it. A thin quotation renders exactly like a complete one — right branding, right price,
right customer — so it goes out.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# By explicit path: prepending src/ makes the ENGINE's `config` beat the portal backend's for
# the whole process, and the backend's own tests then fail depending on collection order.
_spec = importlib.util.spec_from_file_location(
    "client_quote_regen", _ROOT / "src" / "client_quote_regen.py")
regen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(regen)


def _summary(tmp: Path, stem: str) -> Path:
    p = tmp / f"{stem}.json"
    p.write_text(json.dumps({"job_output_stem": stem, "marker": "the real one"}),
                 encoding="utf-8")
    return p


# ── the stem, which is where this broke ─────────────────────────────────────────────────

def test_the_engines_own_filename_still_resolves(tmp_path):
    """The case that always worked and must keep working."""
    _summary(tmp_path, "10575-02")
    wb = tmp_path / "10575-02_20260824_162345.xlsx"
    wb.write_bytes(b"PK\x03\x04")
    found = regen.find_original_summary(wb)
    assert found and found["marker"] == "the real one"


def test_the_manual_override_copy_no_longer_loses_the_job(tmp_path):
    """THE DEFECT. The portal hands over '<stem>_MANUAL_OVERRIDE.xlsx', and deriving the stem
    from that name looks for a JSON that cannot exist."""
    _summary(tmp_path, "10575-02")
    copy = tmp_path / "10575-02_MANUAL_OVERRIDE.xlsx"
    copy.write_bytes(b"PK\x03\x04")

    # Fixed at BOTH ends, deliberately. The caller now passes the stem it already knows, and
    # the deriver also strips '_MANUAL_OVERRIDE' — this module's own naming, so a lookup
    # ignorant of it was hunting for a file this module guaranteed would never be written.
    # Either fix alone closes the defect; both means a future caller that forgets to pass the
    # stem does not silently reopen it.
    found = regen.find_original_summary(copy, stem="10575-02")
    assert found and found["marker"] == "the real one", \
        "told the stem, it must find the job the quote is for"

    bare = regen.find_original_summary(copy)
    assert bare and bare["marker"] == "the real one", \
        "and without being told, because the deriver knows what the copy is called"


def test_the_original_folder_is_searched_when_the_sheet_has_been_copied(tmp_path):
    """By the time the override runs, the workbook it holds is a copy somewhere else. The
    summary may sit beside the ORIGINAL, on the share with the run's other outputs."""
    original_dir = tmp_path / "share" / "Dyson" / "10575-02"
    original_dir.mkdir(parents=True)
    _summary(original_dir, "10575-02")

    elsewhere = tmp_path / "outputs"
    elsewhere.mkdir()
    copy = elsewhere / "10575-02_MANUAL_OVERRIDE.xlsx"
    copy.write_bytes(b"PK\x03\x04")

    assert regen.find_original_summary(copy, stem="10575-02") is None, \
        "not beside the copy and not in JSON_DIR"
    found = regen.find_original_summary(copy, stem="10575-02", extra_dirs=(original_dir,))
    assert found and found["marker"] == "the real one"


def test_a_job_with_no_summary_anywhere_is_still_None(tmp_path):
    """The fallback must survive: a plain quote beats no quote. What must NOT survive is
    saying nothing about it, which the next test covers."""
    wb = tmp_path / "11650-04_MANUAL_OVERRIDE.xlsx"
    wb.write_bytes(b"PK\x03\x04")
    assert regen.find_original_summary(wb, stem="11650-04") is None


# ── the silence, which is the half that let it out of the building ──────────────────────

def test_whether_the_summary_was_found_reaches_the_caller(tmp_path):
    """It was returned into `_` and discarded, so no layer above could report it.

    Checked on the source rather than by running the whole override, which needs openpyxl,
    a real workbook and the AISheets share. The property that matters is that the flag is
    captured and returned, not that a particular job resolves.
    """
    import inspect

    src = inspect.getsource(regen.run_estimator_override)
    assert "quote_path, _qfig" in src or "quote_path, _ =" not in src, \
        "the figures carrying source_summary_found must not be discarded into _"
    assert '"source_summary_found"' in src, \
        "the override result must carry whether the job's summary was found"


def test_the_stem_is_passed_explicitly_not_re_derived(tmp_path):
    """The fix must be at the call site. Leaving regenerate_quote_from_workbook to derive the
    stem from the copy's filename reintroduces the whole defect."""
    import inspect

    src = inspect.getsource(regen.regenerate_quote_from_workbook)
    assert "stem=stem" in src, \
        "the known stem must be handed to the lookup, not re-derived from the copy"
