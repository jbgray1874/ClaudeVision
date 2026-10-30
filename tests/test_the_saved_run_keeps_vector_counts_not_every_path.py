"""The saved run keeps what the vectors measured, not every vector (D-598x).

An 18-page pack printed to PDF with its lettering as outlines carries thousands of vector paths a
page. Each page's raw list was saved twice, and one dry run wrote a 513 MB JSON, a 141 MB text
file and a 990 MB SQL script, each copied again to the archive. The files now carry each list's
count; the run's own summary keeps the paths for the readers that measure them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import file_scan  # noqa: E402


def _paths(n: int):
    return [{"items": [["l", "Point(0, 0)", "Point(1, 1)"]], "type": "s", "width": 0.1}
            for _ in range(n)]


def _summary():
    vision = {"page_number": 1, "drawings": _paths(500), "ocr_text": "SHELF A"}
    return {
        "source_file": "pack.pdf", "page_count": 1, "detected_labels": [],
        "pattern_summary": {"part_numbers": [], "dates": []},
        "pages": [{"page_number": 1, "pdfplumber_text": "", "labels_found": [],
                   "pattern_summary": {}, "page_role": {"primary_role": "detail"},
                   "vision_extraction": vision,
                   "page_analysis": {"title_block": {"drawing_number": "305.4"},
                                     "vision_extraction": vision}}],
        "job_files": {"drawings": ["a.pdf", "b.pdf"]},
        "manufacturing_writeup": {"parts": []},
    }


def test_each_raw_vector_list_is_saved_as_its_count():
    s = _summary()
    saved = file_scan.persisted_summary(s)
    page = saved["pages"][0]
    for vision in (page["vision_extraction"], page["page_analysis"]["vision_extraction"]):
        assert vision["drawings"]["raw_vector_paths"] == 500
        assert vision["ocr_text"] == "SHELF A", "everything else on the page is kept"
    assert page["page_analysis"]["title_block"] == {"drawing_number": "305.4"}


def test_the_runs_own_summary_keeps_its_paths():
    s = _summary()
    file_scan.persisted_summary(s)
    assert len(s["pages"][0]["vision_extraction"]["drawings"]) == 500
    assert len(s["pages"][0]["page_analysis"]["vision_extraction"]["drawings"]) == 500


def test_a_list_named_drawings_that_is_not_vector_paths_is_kept():
    s = _summary()
    saved = file_scan.persisted_summary(s)
    assert saved["job_files"]["drawings"] == ["a.pdf", "b.pdf"]
    empty = file_scan.persisted_summary({"drawings": []})
    assert empty == {"drawings": []}


def test_the_written_json_carries_the_count_and_the_run_keeps_the_rest(tmp_path):
    s = _summary()
    out = {k: tmp_path / f"run.{k}" for k in ("json", "txt", "log", "csv", "sql", "xlsx", "vcsv")}
    file_scan._write_primary_outputs(s, out["json"], out["txt"], out["log"], out["csv"],
                                     out["sql"], out["xlsx"], out["vcsv"], [])
    written = json.loads(out["json"].read_text(encoding="utf-8"))
    assert written["pages"][0]["vision_extraction"]["drawings"]["raw_vector_paths"] == 500
    assert "Point(0, 0)" not in out["json"].read_text(encoding="utf-8")
    if out["txt"].exists():
        assert "Point(0, 0)" not in out["txt"].read_text(encoding="utf-8")
    if out["sql"].exists():
        assert "Point(0, 0)" not in out["sql"].read_text(encoding="utf-8")
    assert len(s["pages"][0]["vision_extraction"]["drawings"]) == 500


def test_the_reconciled_rewrite_saves_the_same_form():
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "json.dump(_saved(summary), _fh_rw" in src
    assert "json.dump(summary, _fh_rw" not in src
