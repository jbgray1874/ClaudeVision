"""The BOM the estimate uses comes from reading the table the drawing prints.

Three things are asserted here, and each one was false in production before it was:

  1. The dual path is ON unless someone deliberately turns it off. It was built behind
     a flag defaulting OFF, so no live run ever read a BOM table — the rows reaching the
     estimate came from regexes over pdfplumber's text flow instead.
  2. A reader that could not run says so. Both readers failing silently to a print left
     a single-reader job looking exactly like a job both readers agreed was small.
  3. Neither reader failing can end the process. merge_boms began as a script and called
     sys.exit(1) on an import error; imported into the pipeline that would take an entire
     estimate down over an optional dependency.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import bom_pipeline  # noqa: E402
import merge_boms  # noqa: E402
import part_code_conventions  # noqa: E402


def _structured(findings, code):
    """Findings are a mixed channel: code-quality entries are prose strings, structured
    entries are dicts. Only the dicts carry a code."""
    return [f for f in findings if isinstance(f, dict) and f.get("code") == code]


# ---------------------------------------------------------------------------
# 1. The gate
# ---------------------------------------------------------------------------
@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("SDI_DUALPATH_BOM", raising=False)
    return monkeypatch


def test_reading_the_printed_bom_is_the_default(clean_env):
    assert bom_pipeline.dual_path_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", " off "])
def test_the_old_single_reader_path_can_still_be_forced(clean_env, value):
    clean_env.setenv("SDI_DUALPATH_BOM", value)
    assert bom_pipeline.dual_path_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", ""])
def test_anything_that_is_not_a_refusal_leaves_it_on(clean_env, value):
    clean_env.setenv("SDI_DUALPATH_BOM", value)
    assert bom_pipeline.dual_path_enabled() is True


def test_the_gate_has_exactly_one_definition():
    """Two independent env reads is how one of them goes stale while the other doesn't.

    This rule previously existed as two separate os.getenv calls in file_scan, either of
    which could have been edited alone. The check is that nothing outside bom_pipeline
    reads the variable directly.
    """
    offenders = []
    for path in sorted((SRC).glob("*.py")):
        # patch_*.py are one-shot applicators that carry the OLD source as string
        # literals; _*.py are hand-run diagnostics. Neither is on the estimate path.
        # (src also contains a DIRECTORY whose name ends in .py, so is_file matters.)
        if (not path.is_file() or path.name == "bom_pipeline.py"
                or path.name.startswith("_") or path.name.startswith("patch_")):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "SDI_DUALPATH_BOM" in line and "getenv" in line:
                offenders.append(f"{path.name}:{lineno}")
    assert not offenders, (
        "the dual-path rule is read directly outside bom_pipeline.dual_path_enabled(): "
        + ", ".join(offenders)
    )


# ---------------------------------------------------------------------------
# 2. A reader that did not run says so
# ---------------------------------------------------------------------------
class _StubPathA:
    """Finds one BOM row on one page, so 'B is missing' is the only difference."""

    @staticmethod
    def read_bom_from_page(page):
        return {
            "parent": "1282-GA",
            "rows": [{"item_number": "1", "part_ref": "1282-01", "description": "PANEL",
                      "quantity": 2}],
        }


def _stub_pdfplumber(monkeypatch, pages=1):
    """A pdfplumber whose open() yields `pages` blank pages, so run_path_a has work."""
    import types

    class _Pdf:
        def __init__(self):
            self.pages = [object() for _ in range(pages)]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    module = types.ModuleType("pdfplumber")
    module.open = lambda _path: _Pdf()
    monkeypatch.setitem(sys.modules, "pdfplumber", module)


def test_a_vision_reader_that_will_not_import_is_reported_not_swallowed(monkeypatch, tmp_path):
    _stub_pdfplumber(monkeypatch)
    monkeypatch.setattr(merge_boms, "pathA", _StubPathA)
    monkeypatch.setattr(merge_boms, "pathB", None)
    monkeypatch.setattr(merge_boms, "PATH_B_IMPORT_ERROR", "ModuleNotFoundError: No module named 'openai'")

    pdf = tmp_path / "1282 - GA.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    result = merge_boms.reconcile_job([str(pdf)])

    assert result["rows"] if "rows" in result else result["pages"], "path A's row must survive"
    job_scope = [u for u in result["unread"] if u["path"] == "B" and u["scope"] == "job"]
    assert job_scope, "a vision reader that never ran must appear in unread"
    assert "openai" in job_scope[0]["detail"]


def test_the_unread_reader_reaches_the_caller_as_a_blocking_finding(monkeypatch, tmp_path):
    _stub_pdfplumber(monkeypatch)
    monkeypatch.setattr(merge_boms, "pathA", _StubPathA)
    monkeypatch.setattr(merge_boms, "pathB", None)
    monkeypatch.setattr(merge_boms, "PATH_B_IMPORT_ERROR", "RuntimeError: XAI_API_KEY not found")

    pdf = tmp_path / "1282 - GA.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    out = bom_pipeline.reconciled_bom_rows_for_job(pdfs=[str(pdf)])

    assert out["rows"], "the deterministic reader's rows must still be delivered"
    unread = _structured(out["findings"], "bom_reader_did_not_run")
    assert unread, "bom_pipeline must promote an unread reader to a finding"
    assert any(f.get("severity") == "blocking" for f in unread)
    assert "corroboration" in unread[0]["detail"]


def test_a_job_where_both_readers_ran_raises_no_unread_finding(monkeypatch, tmp_path):
    """Mutation guard: the finding above must be caused by the missing reader, not
    emitted on every job. A check that cannot be silent proves nothing when it fires."""
    _stub_pdfplumber(monkeypatch)

    class _StubPathB:
        DEFAULT_CACHE_DIR = ""

        @staticmethod
        def count_pages(_path):
            return 1

        @staticmethod
        def render_page_to_png(_path, _pi, dpi=300, max_side=2000):
            return b"png"

        @staticmethod
        def get_vision_bom_cached(_png, **_kw):
            return {"parsed": {
                "parent": "1282-GA",
                "rows": [{"item_number": "1", "part_ref": "1282-01",
                          "description": "PANEL", "quantity": 2}],
            }}

    monkeypatch.setattr(merge_boms, "pathA", _StubPathA)
    monkeypatch.setattr(merge_boms, "pathB", _StubPathB)

    pdf = tmp_path / "1282 - GA.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    out = bom_pipeline.reconciled_bom_rows_for_job(pdfs=[str(pdf)])

    assert not _structured(out["findings"], "bom_reader_did_not_run")
    assert out["rows"][0]["bom_source"] == "BOTH"
    assert out["rows"][0]["bom_confidence"] == "HIGH"


# ---------------------------------------------------------------------------
# 3. Importing the reconciler cannot end the process
# ---------------------------------------------------------------------------
def test_importing_merge_boms_does_not_call_sys_exit():
    source = (SRC / "merge_boms.py").read_text(encoding="utf-8")
    head = source.split("def main(", 1)[0]
    assert "sys.exit" not in head, (
        "merge_boms must not end the process at import or from a library function — "
        "only main() may, and only when run from the command line"
    )


# ---------------------------------------------------------------------------
# The comparison rule itself
# ---------------------------------------------------------------------------
def test_two_readers_spellings_of_one_code_compare_equal():
    bare = part_code_conventions.bare_code
    assert bare("1455-C GA") == bare("1455-C-GA") == bare("1455-C- GA") == bare("1455 C GA")
    assert bare("3886-GA-") == "3886GA"


def test_the_comparison_rule_survives_the_vision_reader_being_absent(monkeypatch):
    """merge_boms._bare used to BE the vision reader's function. Reconciliation of an
    A-only job would then have died on the very path that made it A-only."""
    monkeypatch.setattr(merge_boms, "pathB", None)
    assert merge_boms._bare("1455-C GA") == "1455CGA"


def test_the_vision_readers_own_name_still_answers():
    """Callers of the vision reader keep working; the rule just lives elsewhere now."""
    import _bom_vision_reader

    assert _bom_vision_reader._bare_code("1450 - GA") == part_code_conventions.bare_code("1450 - GA")


def test_the_vision_cache_is_not_pinned_to_one_machines_drive():
    import _bom_vision_reader

    assert "C:\\ClaudeVision" not in _bom_vision_reader.DEFAULT_CACHE_DIR
    assert _bom_vision_reader.DEFAULT_CACHE_DIR.endswith(os.path.join("cache", "vision_bom"))


# ---------------------------------------------------------------------------
# 4. The invariant an estimator actually sees
# ---------------------------------------------------------------------------
def _job(unread, rows=3):
    return {"document_analysis": {
        "bom_rows": [{"part_number": f"1282-{i:02d}", "quantity": 1} for i in range(rows)],
        "bom_readers_unread": unread,
    }}


def test_a_reader_that_never_ran_blocks():
    import invariants

    out = invariants.check_both_bom_readers_ran(_job([
        {"path": "B", "scope": "job", "pdf": "", "page": None,
         "detail": "vision BOM reader unavailable (RuntimeError: XAI_API_KEY not found)"},
    ]))
    assert len(out) == 1
    assert out[0]["code"] == "bom_reader_never_ran"
    assert out[0]["severity"] == invariants.BLOCKING
    assert "read once, not twice" in out[0]["message"]


def test_one_unreadable_page_is_a_warning_not_a_blocker():
    import invariants

    out = invariants.check_both_bom_readers_ran(_job([
        {"path": "B", "scope": "page", "pdf": "12392-04-GA.pdf", "page": 2,
         "detail": "TimeoutError: read timed out"},
    ]))
    assert len(out) == 1
    assert out[0]["code"] == "bom_page_not_read_by_both"
    assert out[0]["severity"] == invariants.WARNING
    assert "page 3" in out[0]["message"], "pages are reported 1-based, as the estimator counts them"


def test_a_job_both_readers_covered_is_silent():
    """Mutation guard. If this ever fails, the check above is firing on every job and
    means nothing when it fires."""
    import invariants

    assert invariants.check_both_bom_readers_ran(_job([])) == []


def test_a_scan_that_predates_the_coverage_record_is_unevaluated_not_clean():
    """A summary produced before the readers reported coverage cannot answer the
    question. Saying 'fine' would be the same silence the check exists to end."""
    import invariants

    out = invariants.check_both_bom_readers_ran({"document_analysis": {"bom_rows": []}})
    assert out and out[0].get("status") != "ok"
    assert "Re-run" in (out[0].get("message") or "")


def test_the_check_is_registered():
    import invariants

    assert invariants.check_both_bom_readers_ran in invariants.CHECKS
