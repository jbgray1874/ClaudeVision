"""What each store gave back is on the book (D-555).

A cache that never hits looks exactly like one that works. The timing record (D-553) keeps the
reuse counts beside the log; the book is where somebody looks, so the estimate carries them
too and the Provenance sheet's header line says them beside the build that asked.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import run_timing as rt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_the_estimate_carries_what_each_store_gave_back():
    import estimator
    rt.reset()
    try:
        assert estimator._reads_reused() == {}
        rt.reuse("pdf_readings", True)
        rt.reuse("pdf_readings", True)
        rt.reuse("vision_bom", False)
        assert estimator._reads_reused() == {"pdf_readings": {"reused": 2, "computed": 0},
                                             "vision_bom": {"reused": 0, "computed": 1}}
    finally:
        rt.reset()
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert '"reads_reused": _reads_reused(),' in src
    assert src.index('"engine_build": engine_build.describe(),') < src.index('"reads_reused": _reads_reused(),')


def test_the_books_header_says_them_beside_the_build():
    from estimation_report import _reads_line
    rt.reset()
    try:
        line = _reads_line({"estimate_summary": {"reads_reused": {
            "vision_bom": {"reused": 11, "computed": 2},
            "pdf_readings": {"reused": 3, "computed": 0}}}})
        assert line == "Reads: pdf_readings 3 reused / 0 made; vision_bom 11 reused / 2 made"
        assert _reads_line({"estimate_summary": {}}) == ""            # nothing read through a store
        assert _reads_line({}) == ""
        # A book costed in this process but whose estimate predates the record: this run's counts.
        rt.reuse("llm_extract", True)
        assert _reads_line({"estimate_summary": {}}) == "Reads: llm_extract 1 reused / 0 made"
    finally:
        rt.reset()
    src = (ROOT / "src" / "estimation_report.py").read_text(encoding="utf-8")
    body = src.split("def add_provenance_sheet(")[1]
    assert "_reads_txt = _reads_line(summary)" in body
    assert body.index("_build_txt = f\"   |   Build:") < body.index("_reads_txt = _reads_line(summary)")
    assert body.index("_reads_txt = _reads_line(summary)") < body.index("cell(2, 1,")


def test_the_clear_tool_knows_the_read_store():
    tool = (ROOT / "tools" / "diagnose" / "clear_llm_cache.py").read_text(encoding="utf-8")
    assert "def _read_store_entries(" in tool
    assert "targets = list(vis) + list(full) + list(kept)" in tool
