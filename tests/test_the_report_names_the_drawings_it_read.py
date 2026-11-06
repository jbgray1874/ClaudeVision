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


# ── the record the ENGINE writes, not the one the first fixture imagined (D-408) ─────────
#
# drawing_job_merge writes `dxf` on a matched record and `path` on an unmatched, skipped or
# ambiguous one — full Windows paths as written on the box — and `candidates` where several
# flats were weighed. The fixture above used `dxf_name`, a key no run has ever written, so the
# section passed its tests while live reports named every PDF and every model and not one DXF.
# 12675-01's 19:10 report: the only DXF in the pack minted the priced part and appeared nowhere
# in 4.1, and 4.2 could say only "1 file(s) — check naming" about a file refused for carrying
# 22 dimension entities.

LIVE = {
    "job_source_pdfs": [{"name": "12675-01-GA Stacking Block Model_Design Intent.PDF"}],
    "dxf_augmentation": {
        "matched": [{"part_number": "12675-01-03",
                     "dxf": r"C:\SDI\staging\12675-01\12675-01-03_2mm_SS.DXF",
                     "geometry_reliability": 0.95}],
        "unmatched_dxf": [
            {"path": r"C:\SDI\staging\12675-01\12675-01-02 Block Model V2.dxf",
             "part_number": "12675-01-02",
             "reason": ("drawing_export_not_a_flat: 22 dimension entities — this is a drawing "
                        "of the part, not its flat pattern")},
            {"path": r"C:\SDI\staging\12675-01\12675-03-BOOTS BAR BLACK_RevB.DXF",
             "part_number": "12675-03",
             "reason": "code_belongs_to_another_assembly_in_this_job_number"},
        ],
        "skipped": [
            {"path": r"C:\SDI\staging\12675-01\0355255 - Table Top Holder - 12675_REV B.DXF",
             "reason": "drawing_export_not_a_flat",
             "detail": "9 dimension entities — this is a drawing of the part, not its flat pattern"},
            {"path": r"C:\SDI\staging\12675-01\12675-01-GA.DXF", "reason": "ga_dxf_ignored"},
        ],
        "ambiguous_dxf": [
            {"part_number": "12675-01-05",
             "candidates": [r"C:\SDI\staging\12675-01\12675-01-05-1.DXF",
                            r"C:\SDI\staging\12675-01\12675-01-05-2.DXF"],
             "reason": "numbered_piece_or_separate_item_unresolved", "evidence": []},
        ],
    },
    "cad_inputs": {},
}


def _section_41() -> str:
    return _text(jrh._files_read_section(LIVE))


def _section_42() -> str:
    return _text(jrh._render_drawing_analysis(jrh._extract_drawing_quality(LIVE), LIVE))


def test_a_dxf_is_named_by_the_key_the_merge_actually_writes():
    out = _section_41()
    for name in ("12675-01-03_2mm_SS.DXF", "12675-01-02 Block Model V2.dxf",
                 "12675-03-BOOTS BAR BLACK_RevB.DXF", "0355255 - Table Top Holder - 12675_REV B.DXF",
                 "12675-01-GA.DXF", "12675-01-05-1.DXF", "12675-01-05-2.DXF"):
        assert name in out, f"{name} is in the engine's record and is not named"


def test_the_staged_path_is_shown_as_its_filename():
    out = _section_41()
    assert r"C:\SDI" not in out and "staging" not in out


def test_a_matched_flat_still_reads_as_measured():
    out = _section_41()
    assert re.search(r"12675-01-03_2mm_SS\.DXF\s+DXF\s+matched to a part — measured flat pattern", out)


def test_a_refused_drawing_export_says_why_beside_its_name():
    """The reason the merge recorded, in the row for the file — not a count two sections away."""
    out = _section_41()
    assert re.search(r"Block Model V2\.dxf\s+DXF\s+present, not used: a drawing of a part, not a "
                     r"flat pattern — it minted no part and measured nothing \(22 dimension entities\)", out)
    # the same reason written the other way the merge writes it (code + detail)
    assert re.search(r"12675_REV B\.DXF\s+DXF\s+present, not used: a drawing of a part.*\(9 dimension entities\)", out)
    # the verdict the content reader appends to its evidence is not printed twice
    assert "this is a drawing of the part, not its flat pattern" not in out


def test_every_recorded_reason_reaches_the_row():
    out = _section_41()
    assert "its code belongs to another assembly under this job number" in out
    assert "a general-arrangement export — not a flat pattern, not measured" in out
    assert "could be a numbered piece or a separate item — not attached; say which" in out


def test_an_unknown_reason_code_is_printed_not_dropped():
    s = {"job_source_pdfs": [{"name": "ga.pdf"}], "cad_inputs": {},
         "dxf_augmentation": {"unmatched_dxf": [
             {"path": r"C:\x\odd.DXF", "reason": "some_new_reason_the_merge_learned"}]}}
    out = _text(jrh._files_read_section(s))
    assert "odd.DXF" in out
    assert "some new reason the merge learned" in out


def test_a_file_that_contributed_nothing_is_marked_like_an_unread_one():
    html_out = jrh._files_read_section(LIVE)
    row = re.search(r"<tr><td><code>12675-01-02 Block Model V2\.dxf</code></td>.*?</tr>", html_out).group(0)
    assert "color:#b3261e" in row, "a refused DXF contributed nothing and is not shown in red"
    row = re.search(r"<tr><td><code>12675-01-03_2mm_SS\.DXF</code></td>.*?</tr>", html_out).group(0)
    assert "color:#b3261e" not in row, "a measured flat is not a warning"


def test_the_weaknesses_table_lists_refused_drawings_by_name_with_the_evidence():
    out = _section_42()
    assert "DXFs that are drawings, not flat patterns" in out
    assert "12675-01-02 Block Model V2.dxf — 22 dimension entities" in out
    assert "0355255 - Table Top Holder - 12675_REV B.DXF — 9 dimension entities" in out
    assert "2 DXF(s) carry dimensions or a title block" in out
    assert "None minted a part" in out


def test_the_weaknesses_table_lists_unmatched_files_with_their_reason_not_a_count():
    out = _section_42()
    assert "12675-03-BOOTS BAR BLACK_RevB.DXF — its code belongs to another assembly" in out
    # the refused drawing is NOT also counted as a naming problem
    assert "1 DXF(s) present and tied to no part" in out
    assert "check naming/part-number alignment" not in out


def test_an_old_record_with_bare_entries_still_gets_the_count():
    """A summary saved before reasons were recorded carries unmatched entries with no name or
    reason. The count is all there is, and it is still said."""
    s = {"dxf_augmentation": {"unmatched_dxf": [{}, {}]}}
    out = _text(jrh._render_drawing_analysis(jrh._extract_drawing_quality(s), s))
    assert "Unmatched DXFs" in out and "2 file(s)" in out


def test_the_first_fixtures_key_still_works():
    """`dxf_name` is still read — the fix widened the reader, it did not move it."""
    out = _text(jrh._files_read_section(PACK))
    assert "10575-02-009_DIBOND_3.0mm.DXF" in out
    assert re.search(r"spare\.DXF\s+DXF\s+present, not used: matched to no part", out)


def test_the_sub_numbering_does_not_collide(jrh_section=None):
    """4.1 is the new list, so Strengths and Weaknesses shift down. Two 4.2s in one section is
    the kind of thing nobody notices until a report is being read aloud in a meeting."""
    summary = dict(PACK)
    summary["estimate_summary"] = {"estimate_workbook_inputs": {"assumed_job_quantity": 1}}
    html = jrh.build_report_html(summary)
    for n in ("4.1", "4.2", "4.3"):
        assert html.count(f"{n} &nbsp;") == 1, f"{n} appears {html.count(f'{n} &nbsp;')} times"
