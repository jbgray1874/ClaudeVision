"""The corpus reader, before there is a corpus to read.

tests/fixtures/jobs/ was built to be replayed and has held zero jobs since the day it was
written. So every structural rule in this suite is asserted against records whose author also
wrote the rule — and a dict written by the person who wrote the rule cannot disagree with it
about the shape of a record. Three times in a row on 11350, that is exactly what went wrong.

Seeding it is a commercial decision, not an engineering one: job records carry client names,
drawing numbers and prices. So the reader takes both an in-repo folder and $SDI_JOB_CORPUS,
and the decision changes a path instead of a test.

WHAT THIS FILE GUARDS is the seeding itself. A reader that knows one document shape reports
"no parts" on every job of another, and the first thing that happens when somebody drops six
saved jobs in is six failures that look like a broken harness rather than six documents worth
replaying. Older jobs are the valuable ones precisely because nobody wrote them with today's
rules in mind, and they are the ones most likely to be shaped differently.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import job_corpus  # noqa: E402


def _write(directory, name, doc):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


PART = {"part_number": "11650-04-01A", "normalized_material": "ABS"}


def test_an_empty_corpus_is_not_a_failure():
    """A suite that cannot run without client data is a suite nobody outside can run. The
    corpus adds evidence; it is never a dependency."""
    assert list(job_corpus.jobs()) is not None


def test_a_job_on_a_share_is_read(tmp_path, monkeypatch):
    """For keeping client pricing out of git. Same replay, path from the environment."""
    _write(tmp_path / "share", "8352-010.json", {"manufacturing_writeup": {"parts": [PART]}})
    monkeypatch.setenv(job_corpus.CORPUS_ENV, str(tmp_path / "share"))
    names = [p.name for p in job_corpus.paths()]
    assert "8352-010.json" in names


def test_both_locations_are_read_not_one_or_the_other(tmp_path, monkeypatch):
    """Whichever way the decision goes, a job already sitting in the other place must not
    silently stop being tested."""
    monkeypatch.setattr(job_corpus, "IN_REPO", tmp_path / "repo")
    _write(tmp_path / "repo", "11650-04.json", {"manufacturing_writeup": {"parts": [PART]}})
    _write(tmp_path / "share", "10575-01.json", {"manufacturing_writeup": {"parts": [PART]}})
    monkeypatch.setenv(job_corpus.CORPUS_ENV, str(tmp_path / "share"))
    names = sorted(p.name for p in job_corpus.paths())
    assert names == ["10575-01.json", "11650-04.json"]


@pytest.mark.parametrize("doc", [
    {"manufacturing_writeup": {"parts": [PART]}},          # what the engine writes today
    {"parts": [PART]},                                     # a flatter older document
    {"estimate_summary": {"parts": [PART]}},               # and one that nests it
])
def test_the_parts_are_found_wherever_that_engine_put_them(doc, tmp_path, monkeypatch):
    monkeypatch.setattr(job_corpus, "IN_REPO", tmp_path)
    _write(tmp_path, "j.json", doc)
    _, loaded = next(job_corpus.jobs())
    assert job_corpus.raw_parts(loaded) == [PART]


def test_the_costed_projection_is_a_different_question_from_the_raw_record():
    """Both live in one document and the rules read different ones. Conflating them is how a
    checker comes to assert a structural property against a projection that never carried it."""
    costed = {"part_number": "11650-04-01A", "material_estimate": {}}
    # BOTH UNDER ONE HOLDER, which is the case that separates the two readers. With the raw
    # parts only at the top level, a costed reader that tried "parts" first would fall
    # through to the right answer by luck and the distinction would be untested.
    doc = {"manufacturing_writeup": {"parts": [PART]},
           "estimate_summary": {"parts": [PART], "part_estimates": [costed]}}
    assert job_corpus.raw_parts(doc) == [PART]
    assert job_corpus.costed_parts(doc) == [costed]


def test_a_document_that_yields_nothing_says_what_it_actually_is(tmp_path, monkeypatch):
    """The difference between a two-minute answer and an afternoon. 'No parts' on a file
    somebody just copied in is indistinguishable from a broken harness unless it names the
    keys it did find."""
    monkeypatch.setattr(job_corpus, "IN_REPO", tmp_path)
    _write(tmp_path, "odd.json", {"totals": {}, "route_graph": {}})
    _, doc = next(job_corpus.jobs())
    assert job_corpus.raw_parts(doc) == []
    described = job_corpus.what_this_document_holds(doc)
    assert "route_graph" in described and "totals" in described


def test_an_llm_extract_is_not_a_job(tmp_path, monkeypatch):
    """A different document with a different shape sitting in the same output folder. Copying
    output\\json\\*.json wholesale will bring them along, and replaying one proves nothing
    while failing loudly."""
    monkeypatch.setattr(job_corpus, "IN_REPO", tmp_path)
    _write(tmp_path, "11650-04_llm_extract.json", {"pages": []})
    _write(tmp_path, "11650-04.json", {"manufacturing_writeup": {"parts": [PART]}})
    assert [p.name for p in job_corpus.paths()] == ["11650-04.json"]


def test_a_corpus_file_nobody_can_read_is_reported_not_skipped(tmp_path, monkeypatch):
    """A file in the corpus that quietly does nothing is worse than no file: the count of jobs
    being replayed reads as coverage that is not there."""
    monkeypatch.setattr(job_corpus, "IN_REPO", tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(AssertionError, match="broken.json"):
        list(job_corpus.jobs())


def test_the_replay_actually_runs_a_seeded_job(tmp_path, monkeypatch):
    """THE POINT OF ALL OF IT. Not that the reader reads, but that a job dropped into the
    corpus reaches the structural rules — that dropping 11650-04 in tomorrow changes what this
    suite proves. A handed part whose base was measured must not arrive at costing with no
    blank of its own, on a real record.
    """
    from document_builder import flat_blank_mm
    from drawing_job_merge import apply_mirror_geometry

    base = {"part_number": "11650-04-01A",
            "normalized_geometry": {"geometry_source": "dxf_flat_pattern",
                                    "blank_length_mm": 1250.0, "blank_width_mm": 525.0}}
    twin = {"part_number": "11650-04-01A-HANDED", "normalized_geometry": {}}
    monkeypatch.setattr(job_corpus, "IN_REPO", tmp_path)
    _write(tmp_path, "11650-04.json", {"manufacturing_writeup": {"parts": [base, twin]}})

    replayed = 0
    for _path, doc in job_corpus.jobs():
        parts = job_corpus.raw_parts(doc)
        apply_mirror_geometry(parts)
        for p in parts:
            from part_code_conventions import mirror_base
            base_pn = mirror_base(str(p.get("part_number") or ""))
            if not base_pn:
                continue
            twin_base = next((q for q in parts
                              if str(q.get("part_number") or "").upper() == base_pn.upper()), None)
            if twin_base is None or not all(flat_blank_mm(twin_base)):
                continue
            assert all(flat_blank_mm(p)), (
                f"{p.get('part_number')} mirrors a measured part and reached costing "
                f"with no blank")
            replayed += 1
    assert replayed == 1, "the seeded job was not actually replayed"
