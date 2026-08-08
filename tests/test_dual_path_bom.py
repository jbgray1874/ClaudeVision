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
    def survey_page(page):
        import _bom_words_reader as wr
        return wr.survey_page(page)

    @staticmethod
    def read_bom_from_page(page):
        return {
            "parent": "1282-GA",
            "rows": [{"item_number": "1", "part_ref": "1282-01", "description": "PANEL",
                      "quantity": 2}],
        }


def _words(text, top=100.0):
    """Turn a line of text into pdfplumber-shaped word dicts on one y-band."""
    out, x = [], 10.0
    for tok in text.split():
        out.append({"text": tok, "x0": x, "x1": x + 8 * len(tok), "top": top,
                    "bottom": top + 8})
        x += 8 * len(tok) + 12
    return out


def _stub_pdfplumber(monkeypatch, pages=1, texts=None):
    """A pdfplumber whose open() yields `pages` pages carrying real word geometry, so
    the deterministic reader's own survey_page runs against them.

    `texts` gives each page's single line of words. The default is a title block with
    no parts-list column vocabulary — a plain detail sheet.
    """
    import types

    class _Page:
        def __init__(self, text):
            self._text = text

        def extract_words(self, **_kw):
            return _words(self._text)

        def extract_text(self):
            return self._text

    class _Pdf:
        def __init__(self):
            self.pages = [
                _Page((texts or {}).get(i, "SCALE 1:2 DRAWN BY SHEET 1 OF 4"))
                for i in range(pages)
            ]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    module = types.ModuleType("pdfplumber")
    module.open = lambda _path: _Pdf()
    monkeypatch.setitem(sys.modules, "pdfplumber", module)


def _delegating_path_a(read_bom_from_page):
    """A Path A stub whose survey_page is the REAL one, so selection is exercised
    against the shipped rule rather than against the stub's opinion of it."""
    import _bom_words_reader as wr

    class _Stub:
        survey_page = staticmethod(wr.survey_page)

    _Stub.read_bom_from_page = staticmethod(read_bom_from_page)
    return _Stub


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
    """The cache directory must be DERIVED from the install, not written down.

    Asserting that the literal "C:\\ClaudeVision" is absent from the VALUE cannot tell
    the two apart, because on the estimating machine the install genuinely is at
    C:\\ClaudeVision and the correctly derived path contains that text. That test passed
    everywhere except the one place it was meant to protect. So: check the value against
    the derived path, and check the SOURCE for a written-down one separately.
    """
    import config
    import _bom_vision_reader

    assert _bom_vision_reader.DEFAULT_CACHE_DIR == str(config.BASE_DIR / "cache" / "vision_bom")

    source = (SRC / "_bom_vision_reader.py").read_text(encoding="utf-8")
    literal = "C:" + chr(92) + "ClaudeVision" + chr(92) + "cache"
    assert literal not in source, "the cache path is written down rather than derived"


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


# ---------------------------------------------------------------------------
# 5. Paying for the pages that carry a BOM, and only those
# ---------------------------------------------------------------------------
def test_a_page_with_nothing_on_it_is_not_paid_for():
    assert merge_boms.page_needs_vision(
        {"has_text": True, "header_found": False, "header_words": False,
         "rows_parsed": 0})[0] is False


def test_a_table_the_reader_could_see_and_not_read_is_the_loudest_reason_to_pay():
    """A header row found with zero rows under it. This is the coverage gap, and it
    used to arrive as the same None as a plain detail sheet."""
    pay, why = merge_boms.page_needs_vision(
        {"has_text": True, "header_found": True, "header_words": True, "rows_parsed": 0})
    assert pay is True
    assert "could not read" in why


def test_a_page_the_reader_read_is_still_corroborated():
    pay, why = merge_boms.page_needs_vision(
        {"has_text": True, "header_found": True, "header_words": True, "rows_parsed": 7})
    assert pay is True
    assert "corroborate" in why


def test_column_words_without_a_qualifying_header_row_are_paid_for():
    pay, why = merge_boms.page_needs_vision(
        {"has_text": True, "header_found": False, "header_words": True, "rows_parsed": 0})
    assert pay is True
    assert "layout" in why


def test_a_page_with_no_text_layer_is_paid_for():
    pay, why = merge_boms.page_needs_vision({"has_text": False})
    assert pay is True
    assert "raster" in why


def test_the_selection_vocabulary_is_the_readers_own():
    """A private copy of the header synonyms here would drift from the ones the header
    matcher uses, and only one of the two would ever be corrected.

    Read against the CODE, not the file, and against the right thing in the code. The
    first version matched the raw text and failed on a COMMENT describing what a merge
    decides; the second matched every string literal and failed on `row.get("quantity")`,
    which is this module reading a field of its own row schema — not a column heading it
    hopes to recognise. Neither was the defect. A guard satisfied by rewording a comment
    or renaming a dict key leaves the thing it defends against free to arrive next week.

    What a private vocabulary actually looks like here: the synonyms `_bom_words_reader`
    matches printed headings against, which are UPPERCASE because printed headings are.
    Schema keys are lowercase. That is the line, and it is the one the codebase already
    draws.
    """
    import ast

    source = (SRC / "merge_boms.py").read_text(encoding="utf-8")
    headings = [n.value for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and len(n.value) <= 40
                and any(c.isalpha() for c in n.value)
                and n.value == n.value.upper()]
    for word in ("DESCRIPTION", "QUANTITY", "PARTS LIST", "BILL OF MATERIAL"):
        assert not any(word in s for s in headings), (
            f"merge_boms carries its own parts-list vocabulary ({word}); the synonym sets "
            f"in _bom_words_reader are the one definition")


def test_the_survey_and_the_header_matcher_agree_on_a_real_header():
    """survey_page must say header_found on exactly what _find_all_headers accepts."""
    import _bom_words_reader as wr

    def _w(text, x0, top):
        return {"text": text, "x0": x0, "x1": x0 + 20, "top": top, "bottom": top + 8}

    header = [_w("ITEM", 10, 100), _w("PART", 60, 100), _w("NO", 85, 100),
              _w("DESCRIPTION", 120, 100), _w("QTY", 300, 100)]

    class _Page:
        def extract_words(self, **_kw):
            return header

    v = wr.survey_page(_Page())
    assert v["has_text"] is True
    assert v["header_words"] is True, "the column words are plainly present"
    assert v["header_found"] is True, "and the header matcher accepts this row"


def test_a_title_block_does_not_read_as_a_parts_list():
    import _bom_words_reader as wr

    def _w(text, x0, top):
        return {"text": text, "x0": x0, "x1": x0 + 20, "top": top, "bottom": top + 8}

    # REF and PART are in _HDR_CODE; NO is in _HDR_ITEM. Two families, not three.
    title_block = [_w("REF", 10, 500), _w("NO", 40, 500), _w("SCALE", 80, 500),
                   _w("1:2", 120, 500), _w("MATERIAL", 10, 520)]

    class _Page:
        def extract_words(self, **_kw):
            return title_block

    v = wr.survey_page(_Page())
    assert v["header_found"] is False
    assert v["header_words"] is False, "two column families is a title block, not a BOM"
    assert merge_boms.page_needs_vision(v)[0] is False


class _CountingPathB:
    """Records which pages were paid for and which were only asked of the cache."""

    DEFAULT_CACHE_DIR = ""

    def __init__(self, cached=(), pages=1):
        self.paid = []
        self.asked = []
        self._cached = set(cached)
        self._pages = pages

    def count_pages(self, _path):
        return self._pages

    def render_page_to_png(self, _path, pi, dpi=300, max_side=2000):
        return f"png{pi}".encode()

    def get_vision_bom_cached(self, png, *, model, pdf_name, page_index, cache_dir,
                              use_cache=True, refresh=False, cache_only=False):
        self.asked.append(page_index)
        if page_index in self._cached:
            return {"parsed": {"parent": "1282-GA", "rows": [
                {"item_number": "1", "part_ref": "1282-01", "description": "PANEL",
                 "quantity": 2}]}, "cache_hit": True}
        if cache_only:
            return {"parsed": None, "raw_response": "", "cache_hit": False, "skipped": True}
        self.paid.append(page_index)
        return {"parsed": {"parent": "1282-GA", "rows": []}, "cache_hit": False}


def _args(**kw):
    import argparse as _ap
    base = dict(dpi=300, max_side=2000, model="m", cache_dir="", no_cache=False,
                refresh=False, force_llm=False, refresh_file=None)
    base.update(kw)
    return _ap.Namespace(**base)


def test_only_selected_pages_are_paid_for(monkeypatch, tmp_path):
    stub = _CountingPathB(pages=4)
    monkeypatch.setattr(merge_boms, "pathB", stub)
    pdf = tmp_path / "job.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    spend = {}
    merge_boms.run_path_b([str(pdf)], _args(), [],
                          {("job.pdf", 0): True, ("job.pdf", 2): True}, spend)

    assert stub.paid == [0, 2], "only the selected pages may reach the model"
    assert spend["paid"] == 2 and spend["skipped"] == 2


def test_a_cached_page_is_used_even_when_not_selected(monkeypatch, tmp_path):
    """Being selective about what to PAY for must not mean discarding what is already
    paid for. The cache is keyed on the page image, so re-reading it costs nothing."""
    stub = _CountingPathB(cached={3}, pages=4)
    monkeypatch.setattr(merge_boms, "pathB", stub)
    pdf = tmp_path / "job.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    spend = {}
    out = merge_boms.run_path_b([str(pdf)], _args(), [], {}, spend)

    assert stub.paid == [], "no page was selected, so nothing may be paid for"
    assert spend["cached"] == 1
    assert out and out[0]["page_index"] == 3, "the cached page's rows must still arrive"


def test_a_page_nobody_looked_at_is_recorded_not_assumed_empty(monkeypatch, tmp_path):
    stub = _CountingPathB(pages=2)
    monkeypatch.setattr(merge_boms, "pathB", stub)
    pdf = tmp_path / "job.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    unread = []
    merge_boms.run_path_b([str(pdf)], _args(), unread, {}, {})

    assert len(unread) == 2
    assert all(u["reason"] == "not_selected" for u in unread)
    assert all(u["scope"] == "page" for u in unread), "a skipped page is a page-level gap"


def test_force_llm_overrides_the_selection(monkeypatch, tmp_path):
    stub = _CountingPathB(pages=3)
    monkeypatch.setattr(merge_boms, "pathB", stub)
    pdf = tmp_path / "job.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    merge_boms.run_path_b([str(pdf)], _args(force_llm=True), [], {}, {})
    assert stub.paid == [0, 1, 2]


def test_a_page_path_a_read_is_always_worth_corroborating(monkeypatch, tmp_path):
    """Selection must not skip the page carrying the money. A row only one reader saw
    is the entire reason the BOM is read twice."""
    _stub_pdfplumber(monkeypatch, pages=3)

    _state = {"calls": 0}

    def _read(page):
        # A table on page 2 only. Its words carry no header vocabulary, so the ONLY
        # reason to pay for that page is that the deterministic reader read it.
        _state["calls"] += 1
        if _state["calls"] == 2:
            return {"parent": "1282-GA", "rows": [
                {"item_number": "1", "part_ref": "1282-01", "description": "PANEL",
                 "quantity": 2}]}
        return None

    _SilentPathA = _delegating_path_a(_read)
    stub = _CountingPathB(pages=3)
    monkeypatch.setattr(merge_boms, "pathA", _SilentPathA)
    monkeypatch.setattr(merge_boms, "pathB", stub)
    pdf = tmp_path / "job.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    merge_boms.reconcile_job([str(pdf)])
    assert stub.paid == [1], "the page Path A found a table on, and no other"


def test_a_page_whose_text_will_not_come_out_is_paid_for(monkeypatch, tmp_path):
    """A scanned or raster sheet yields no text, so no vocabulary test can pass on it.
    That is precisely the page vision exists for: unknown is not the same as no."""
    class _RasterPage:
        def extract_text(self):
            raise ValueError("no text layer")

    import types

    class _Pdf:
        pages = [_RasterPage()]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    module = types.ModuleType("pdfplumber")
    module.open = lambda _p: _Pdf()
    monkeypatch.setitem(sys.modules, "pdfplumber", module)

    _NoPathA = _delegating_path_a(lambda page: None)

    stub = _CountingPathB(pages=1)
    monkeypatch.setattr(merge_boms, "pathA", _NoPathA)
    monkeypatch.setattr(merge_boms, "pathB", stub)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    merge_boms.reconcile_job([str(pdf)])
    assert stub.paid == [0]


def test_a_parts_list_page_path_a_missed_is_paid_for(monkeypatch, tmp_path):
    """The coverage gap: the page names parts-list columns and the table reader found
    nothing. A whole parent BOM absent from a job lives here."""
    _stub_pdfplumber(monkeypatch, pages=2,
                     texts={1: "ITEM NO.  PART NUMBER  DESCRIPTION  QTY"})

    _NoPathA = _delegating_path_a(lambda page: None)

    stub = _CountingPathB(pages=2)
    monkeypatch.setattr(merge_boms, "pathA", _NoPathA)
    monkeypatch.setattr(merge_boms, "pathB", stub)
    pdf = tmp_path / "job.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    merge_boms.reconcile_job([str(pdf)])
    assert stub.paid == [1], "the parts-list page only; the plain detail sheet is skipped"


# ---------------------------------------------------------------------------
# 6. A zero row is not a costed line
# ---------------------------------------------------------------------------
def _uncorroborated_job(rows):
    return {
        "document_analysis": {"bom_rows": [
            {"part_number": "12392-02-01M", "description": "BACK PANEL",
             "bom_source": "A_ONLY", "bom_flag": "A-only — review", "quantity": 1}]},
        "final_estimate": {"totals": {"material_gbp": 13.00}, "material_rows": rows},
    }


def test_a_fabricated_part_is_counted_once_not_twice():
    """A fabricated part appears in material_rows TWICE: in the Bill of Materials at
    GBP 0.00, listed for completeness because its metal is costed in the Sheet Steel
    block, and once in that block for real. Counting both reported "2 BOM line(s)" for one
    part and named the same panel at GBP 0.00 and at GBP 4.31 in the same sentence."""
    import invariants

    out = invariants.check_uncorroborated_bom_lines_are_not_silent(_uncorroborated_job([
        {"part_code": "12392-02-01M", "description": "BACK PANEL", "total_value_gbp": 0.0},
        {"part_code": "12392-02-01M", "description": "BACK PANEL", "total_value_gbp": 4.31},
    ]))
    assert len(out) == 1
    assert out[0]["detail"]["count"] == 1
    assert out[0]["detail"]["value_gbp"] == 4.31


def test_the_money_it_does_carry_still_blocks():
    """Mutation guard. The panel carries a third of the material on one reader's word;
    de-duplicating the report must not soften the finding."""
    import invariants

    out = invariants.check_uncorroborated_bom_lines_are_not_silent(_uncorroborated_job([
        {"part_code": "12392-02-01M", "description": "BACK PANEL", "total_value_gbp": 4.31},
    ]))
    assert out[0]["severity"] == invariants.BLOCKING
    assert out[0]["detail"]["share_pct"] > 25


def test_a_part_with_only_a_zero_row_raises_nothing():
    """Identification is not pricing. A flagged row that costs nothing is not money the
    doubt covers, and saying it is would interrupt an estimator for GBP 0.00."""
    import invariants

    assert invariants.check_uncorroborated_bom_lines_are_not_silent(_uncorroborated_job([
        {"part_code": "12392-02-01M", "description": "BACK PANEL", "total_value_gbp": 0.0},
    ])) == []
