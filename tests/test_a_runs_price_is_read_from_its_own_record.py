"""A run's price is its own: its drawing, its workbook, its pinned record (11 Nov 2026).

Self-Running showed different jobs at identical prices. The runner read the first .json in name
order among the files it filed. The reviewer: "Each displayed price must match that run's ID,
drawing, quantity, pinned record and workbook, not merely the newest filename." Covered here:
another job's late files, an older run of the same drawing, overlapping runs, a run whose files
name only other jobs, and the audit of prices already saved."""
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import own_record as orc  # noqa: E402
import price_audit  # noqa: E402

_spec = importlib.util.spec_from_file_location("sdi_estimate_runner_price", ROOT / "tools/runner/sdi_estimate_runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def _run_files(folder: Path, job: str, stamp: str, unit: float, by_qty=None):
    """A run's workbook and its pinned record, as the engine names them."""
    book = folder / f"{job}_{stamp}.xlsx"
    book.write_bytes(b"x")
    rec = folder / f"{job}_{stamp}_record.json"
    rec.write_text(json.dumps({"totals": {"unit_cost_gbp": unit},
                               "quantity_sweep": {"rows": [{"quantity": q, "unit": u}
                                                           for q, u in (by_qty or {}).items()]}}),
                   encoding="utf-8")
    return [{"name": book.name, "path": str(book)}, {"name": rec.name, "path": str(rec)}]


def _at(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y%m%d_%H%M%S").timestamp()


def test_another_jobs_late_files_do_not_price_this_run(tmp_path):
    # 12674-01-GA's files land in the checkout while 6364-01 runs, and sort first by name.
    late = _run_files(tmp_path, "12674-01-GA", "20261111_143500", 1034.37)
    own = _run_files(tmp_path, "6364-01", "20261111_143000", 1383.58, {1: 1383.58, 5: 1100.0})
    files = late + own
    log = []
    assert runner._unit_cost_from_deliverables(files, "6364-01", _at("20261111_142000"), log) == 1383.58
    assert runner._quantity_prices_from_deliverables(files, "6364-01", _at("20261111_142000")) == [
        {"quantity": 1, "unit_gbp": 1383.58}, {"quantity": 5, "unit_gbp": 1100.0}]
    assert any("6364-01_20261111_143000_record.json" in line for line in log)
    assert orc.other_jobs_files(files, "6364-01") == sorted(f["name"] for f in late)


def test_a_newer_record_of_another_job_never_wins(tmp_path):
    own = _run_files(tmp_path, "12773-01-GA", "20261111_193914", 648.94)
    newer = _run_files(tmp_path, "12674-01-GA", "20261111_194500", 696.18)
    assert runner._unit_cost_from_deliverables(own + newer, "12773-01-GA", _at("20261111_190000")) == 648.94


def test_an_earlier_run_of_the_same_drawing_is_not_this_run(tmp_path):
    old = _run_files(tmp_path, "12773-01-GA", "20261111_150000", 667.93)
    new = _run_files(tmp_path, "12773-01-GA", "20261111_193914", 648.94)
    assert runner._unit_cost_from_deliverables(old + new, "12773-01-GA", _at("20261111_191000")) == 648.94
    # only the old run's files reached this run: no price, not the old one
    assert runner._unit_cost_from_deliverables(old, "12773-01-GA", _at("20261111_191000")) is None


def test_files_naming_only_other_jobs_give_no_price(tmp_path):
    a = _run_files(tmp_path, "12674-01-GA", "20261111_143500", 1034.37)
    b = _run_files(tmp_path, "11896-01-00-GA", "20261111_143600", 898.96)
    log = []
    assert runner._unit_cost_from_deliverables(a + b, "6364-01", 0.0, log) is None
    assert any("NOT READ" in line and "several jobs" in line for line in log)


def test_a_page_job_whose_workbook_is_named_from_the_job_number_is_still_read(tmp_path):
    own = _run_files(tmp_path, "0360297", "20261111_101500", 512.0)
    assert runner._unit_cost_from_deliverables(own, "12773-01-GA", _at("20261111_100000")) == 512.0


def test_a_workbook_with_no_pinned_record_gives_no_price_from_a_stray_json(tmp_path):
    own = _run_files(tmp_path, "6364-01", "20261111_143000", 1383.58)[:1]
    stray = tmp_path / "0_walkthrough.json"
    stray.write_text(json.dumps({"totals": {"unit_cost_gbp": 1034.37}}), encoding="utf-8")
    assert runner._unit_cost_from_deliverables(own + [{"name": stray.name, "path": str(stray)}], "6364-01") is None


def test_spelling_of_the_drawing_does_not_matter(tmp_path):
    own = _run_files(tmp_path, "12773-01-GA", "20261111_193914", 648.94)
    other = _run_files(tmp_path, "12674-01-GA", "20261111_194500", 696.18)
    assert orc.own_record(own + other, "12773 01 ga")[0]["name"] == "12773-01-GA_20261111_193914_record.json"


def _saved(run_id, drawing, shown, files, qty=None, started="20261111_100000"):
    return {"run_id": run_id, "drawing_number": drawing, "client": "c", "status": "done",
            "engine_price_gbp": shown, "started_at": _at(started), "deliverables": files,
            "quantity_prices": [{"quantity": q, "unit_gbp": u} for q, u in (qty or {}).items()]}


def test_the_audit_reports_a_saved_price_that_is_another_jobs(tmp_path):
    late = _run_files(tmp_path, "12674-01-GA", "20261111_143500", 1034.37)
    own = _run_files(tmp_path, "6364-01", "20261111_143000", 1383.58, {1: 1383.58, 5: 1100.0})
    bad = price_audit.check_run(_saved("r1", "6364-01", 1034.37, late + own, {1: 1034.37, 5: 800.0}))
    assert bad["verdict"] == "MISMATCH" and bad["own"] == 1383.58
    assert "1034.37" in bad["why"] and "at 5 off" in bad["why"]
    assert bad["other_jobs_files"]
    good = price_audit.check_run(_saved("r2", "6364-01", 1383.58, own, {1: 1383.58, 5: 1100.0}))
    assert good["verdict"] == "ok"


def test_the_audit_never_calls_an_unreachable_run_ok(tmp_path):
    gone = [{"name": "6364-01_20261111_143000.xlsx", "path": str(tmp_path / "gone.xlsx")},
            {"name": "6364-01_20261111_143000_record.json", "path": str(tmp_path / "gone.json")}]
    assert price_audit.check_run(_saved("r3", "6364-01", 1.0, gone))["verdict"] == "not checked"
    assert price_audit.check_run(_saved("r4", "6364-01", 1.0, []))["verdict"] == "not checked"


def test_the_audit_checks_a_ledger_cost_against_its_run_and_says_if_it_was_written(tmp_path):
    own = _run_files(tmp_path, "12424-02-GA", "20261111_120000", 285.07, {1: 285.07, 500: 199.0})
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "r9.json").write_text(json.dumps(_saved("r9", "12424-02-GA", 285.07, own, {1: 285.07, 500: 199.0})))
    by_run = {str(r["run_id"]): r for r in price_audit.check_runs(runs)}
    led = tmp_path / "t.ledger.json"
    led.write_text(json.dumps({
        "17|12424-02-GA|500": {"run_id": "r9", "unit_cost": 199.0, "written": True},
        "18|12424-02-GA|500": {"run_id": "r9", "unit_cost": 274.40, "written": True},
        "19|X|1": {"run_id": "nope", "unit_cost": 5.0}}))
    rows = {r["row"]: r for r in price_audit.check_ledger(led, by_run)}
    assert rows["17|12424-02-GA|500"]["verdict"] == "ok"
    assert rows["18|12424-02-GA|500"]["verdict"] == "MISMATCH" and "WRITTEN" in rows["18|12424-02-GA|500"]["why"]
    assert rows["19|X|1"]["verdict"] == "not checked"
