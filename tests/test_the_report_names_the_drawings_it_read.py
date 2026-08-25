"""The job report must name the drawings the number came from.

The pack was recorded and never shown. `job_source_pdfs` sat in the summary and the report used
it only for counts and filename-hygiene checks; `cad_inputs` held the files that were present and
NOT read, and nothing rendered those either. So the one document people actually read could not
answer "which drawings produced this?" — which, six weeks later when somebody asks, is the whole
question.

It matters MORE since staging, not less. Selection now genuinely decides what is priced, so a
drawing left off the list is absent from the estimate — and there was nothing on paper saying
which ones were on it. A short list is also the cheapest way to catch the expensive mistake, a
pack missing a part: somebody who knows the job reads six filenames and sees the seventh is not
there.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# APPENDED, never prepended: putting src/ first makes the ENGINE's `config` beat the portal
# backend's for the whole process, and the backend's own tests then fail depending on collection
# order. build_report_html imports costed_facts, so src/ has to be reachable somehow.
import sys
if str(_ROOT / "src") not in sys.path:
    sys.path.append(str(_ROOT / "src"))
_spec = importlib.util.spec_from_file_location("jrh", _ROOT / "src" / "job_report_html.py")
jrh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jrh)


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ")


PACK = {
    "job_source_pdfs": [{"name": "10575-02-GA [Rev D].PDF"}],
    "dxf_augmentation": {"matched": [{"dxf_name": "10575-02-009_DIBOND_3.0mm.DXF"}],
                         "unmatched_dxf": [{"dxf_name": "spare.DXF"}]},
    "cad_inputs": {"unread": ["10575-02-GA [Rev D].DWG"],
                   "solidworks": ["10575-02-GA.SLDDRW"],
                   "converted": ["bracket_from_dwg.DXF"]},
}


# ── what is named ───────────────────────────────────────────────────────────────────────

def test_every_file_that_was_read_is_named(jrh_section=None):
    out = _text(jrh._files_read_section(PACK))
    for name in ("10575-02-GA [Rev D].PDF", "10575-02-009_DIBOND_3.0mm.DXF",
                 "10575-02-GA.SLDDRW", "bracket_from_dwg.DXF"):
        assert name in out, f"{name} was read and is not named"


def test_a_file_present_but_not_read_is_named_too(jrh_section=None):
    """THE ROW THAT CHANGES WHAT THE NUMBER MEANS. A DWG nobody could convert is not a neutral
    fact — it is geometry that sat in the folder and did not reach the estimate. Listing only
    what was read would make a pack look complete when it was not."""
    out = _text(jrh._files_read_section(PACK))
    assert "10575-02-GA [Rev D].DWG" in out
    assert "NOT READ" in out


def test_the_unread_count_is_called_out_not_left_in_the_table(jrh_section=None):
    out = _text(jrh._files_read_section(PACK))
    assert "1 file(s) were in the pack and were not read" in out


def test_a_clean_pack_carries_no_unread_warning(jrh_section=None):
    out = _text(jrh._files_read_section(
        {"job_source_pdfs": [{"name": "ga.pdf"}], "cad_inputs": {"unread": []}}))
    # The intro sentence legitimately contains "were not read" — about drawings that were never
    # selected. What must be absent is the WARNING, which is about files that were in the pack.
    assert "were in the pack and were not read" not in out
    assert "PRESENT, NOT READ" not in out
    assert "ga.pdf" in out


def test_the_same_file_is_not_listed_twice(jrh_section=None):
    """A name can appear in more than one source list. Two rows for one drawing reads as a bug
    in the report rather than as what it is."""
    s = {"job_source_pdfs": [{"name": "ga.pdf"}, {"name": "ga.pdf"}], "cad_inputs": {}}
    out = _text(jrh._files_read_section(s))
    assert out.count("ga.pdf") == 1


def test_it_says_the_folder_was_not_read_wholesale(jrh_section=None):
    """The point of staging, stated where an estimator will see it: what was selected is what
    was priced."""
    out = _text(jrh._files_read_section(PACK))
    assert "nothing else in the folder" in out


# ── the case where we cannot answer ─────────────────────────────────────────────────────

def test_no_record_says_so_rather_than_showing_an_empty_list(jrh_section=None):
    """Silence would read as "this job had no drawings", which is never true of a job that
    produced a number."""
    out = _text(jrh._files_read_section({}))
    assert "did not record" in out
    assert "staged input folder" in out


# ── it is actually in the report ────────────────────────────────────────────────────────

def test_the_section_appears_in_the_rendered_report(jrh_section=None):
    """Written and not wired in is the failure this catches — the section renders correctly on
    its own and never reaches the page."""
    summary = dict(PACK)
    summary["estimate_summary"] = {"estimate_workbook_inputs": {"assumed_job_quantity": 1}}
    html = jrh.build_report_html(summary)
    assert "Drawings this estimate was built from" in html
    assert "10575-02-GA [Rev D].PDF" in html


def test_the_sub_numbering_does_not_collide(jrh_section=None):
    """4.1 is the new list, so Strengths and Weaknesses shift down. Two 4.2s in one section is
    the kind of thing nobody notices until a report is being read aloud in a meeting."""
    summary = dict(PACK)
    summary["estimate_summary"] = {"estimate_workbook_inputs": {"assumed_job_quantity": 1}}
    html = jrh.build_report_html(summary)
    for n in ("4.1", "4.2", "4.3"):
        assert html.count(f"{n} &nbsp;") == 1, f"{n} appears {html.count(f'{n} &nbsp;')} times"
