"""Where a run's time went is kept, with what each store gave back (D-553).

The timing table was printed into the run log and nowhere else, so the question "which phase
do we work on next" could only be answered one job at a time. The end of every run now leaves
<stem>_timing.json beside its log and a row per phase on output/timing_history.csv, with a
reuse count per store — a cache that never hits looks exactly like one that works.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import run_timing as rt  # noqa: E402


def test_the_record_names_the_run_its_phases_and_what_each_store_gave_back(tmp_path):
    rt.reset()
    rt.identify(stem="401918-01-GA", product="401918-01-GA", customer="M&S", units=1,
                breaks="150", build="e3adb4d")
    rt.mark("start extract_pdf_summary")
    rt.mark("done extract_pdf_summary")
    rt.mark("start estimate_document")
    rt.reuse("vision_bom", True)
    rt.reuse("vision_bom", True)
    rt.reuse("vision_bom", False)
    rt.reuse("solidworks_extract", True)
    written = rt.write(tmp_path / "logs", tmp_path / "timing_history.csv")
    rec = json.loads(Path(written["json"]).read_text(encoding="utf-8"))
    assert Path(written["json"]).name == "401918-01-GA_timing.json"
    assert rec["product"] == "401918-01-GA" and rec["customer"] == "M&S" and rec["build"] == "e3adb4d"
    assert rec["reuse"]["vision_bom"] == {"reused": 2, "computed": 1}
    assert rec["reuse"]["solidworks_extract"] == {"reused": 1, "computed": 0}
    names = {p["phase"]: p for p in rec["phases"]}
    assert "extract_pdf_summary" in names
    assert names["estimate_document"].get("unfinished") is True     # a hang is the best row
    assert rec["total_seconds"] is not None and rec["unmeasured_seconds"] is not None
    rt.reset()


def test_the_history_grows_one_row_per_phase_and_per_store(tmp_path):
    hist = tmp_path / "timing_history.csv"
    for stem in ("12173-02-GA", "401918-01-GA"):
        rt.reset()
        rt.identify(stem=stem, units=1)
        rt.mark("start populate_workbook")
        rt.mark("done populate_workbook")
        rt.reuse("llm_extract", False)
        rt.write(tmp_path / "logs", hist)
    rows = list(csv.DictReader(hist.open(encoding="utf-8")))
    assert [r["stem"] for r in rows] == ["12173-02-GA", "12173-02-GA", "401918-01-GA", "401918-01-GA"]
    assert {r["kind"] for r in rows} == {"phase", "reuse"}
    assert rows[1]["name"] == "llm_extract" and rows[1]["computed"] == "1"
    assert list(rows[0].keys()) == list(rt.HISTORY_COLUMNS)
    rt.reset()


def test_nothing_is_written_for_a_run_that_timed_nothing(tmp_path):
    rt.reset()
    assert rt.write(tmp_path / "logs", tmp_path / "h.csv") == {"json": None, "history": None}
    assert not (tmp_path / "h.csv").exists()


def test_reset_forgets_the_identity_and_the_counts():
    rt.identify(stem="x")
    rt.reuse("vision_bom", True)
    rt.reset()
    assert rt.record()["stem"] is None and rt.reuse_counts() == {}


def test_the_run_writes_it_in_the_finally_and_the_stores_count():
    root = Path(__file__).resolve().parents[1] / "src"
    main = (root / "main.py").read_text(encoding="utf-8")
    assert '_rt.write(_cfg_rt.LOG_DIR, _cfg_rt.OUTPUT_DIR / "timing_history.csv")' in main
    assert "_rt_id.identify(" in main
    for mod, store in (("_bom_vision_reader.py", "vision_bom"), ("llm_full_extract.py", "llm_extract"),
                       ("concept_scan.py", "vision_concept"),
                       ("generated_price_cache.py", "generated_prices"),
                       ("source_connectors/solidworks.py", "solidworks_extract")):
        assert f'"{store}"' in (root / mod).read_text(encoding="utf-8"), store
    assert 'run_timing.identify(stem=job_folder.name)' in (root / "file_scan.py").read_text(encoding="utf-8")
