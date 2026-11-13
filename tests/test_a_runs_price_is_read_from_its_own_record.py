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


# ── two runs at once, one output folder (reviewer, 12 Nov 2026) ─────────────────────────────
import os
import time

import price_correct  # noqa: E402


def _engine_writes(root: Path, job: str, stamp: str, unit: float):
    est = root / "output" / "estimates"
    est.mkdir(parents=True, exist_ok=True)
    made = _run_files(est, job, stamp, unit)
    for suffix in ("_covering_email.html", "_covering_email.txt", "_walkthrough.txt", "_walkthrough.wav"):
        f = est / f"{job}_{stamp}{suffix}"
        f.write_text("<!-- subject: x -->" if suffix.endswith(".html") else "x", encoding="utf-8")
        made.append({"name": f.name, "path": str(f)})
    return made


def test_two_runs_at_once_in_one_output_folder_do_not_exchange_results(tmp_path):
    root = tmp_path / "engine"
    (root / "output" / "estimates").mkdir(parents=True)
    now = time.time()
    stamp_a = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
    stamp_b = time.strftime("%Y%m%d_%H%M%S", time.localtime(now + 1))
    before_a = runner.snapshot(root)          # runner A starts 12674-01-GA
    before_b = runner.snapshot(root)          # runner B starts 6364-01 while A is running
    _engine_writes(root, "12674-01-GA", stamp_a, 1034.37)
    _engine_writes(root, "6364-01", stamp_b, 1383.58)
    log_a, log_b = [], []
    filed_a = runner.collect(root, tmp_path / "share_a", before_a, log_a, "12674-01-GA", started_at=now - 5)
    filed_b = runner.collect(root, tmp_path / "share_b", before_b, log_b, "6364-01", started_at=now - 5)
    names_a = {f["name"] for f in filed_a}
    names_b = {f["name"] for f in filed_b}
    assert not any(n.startswith("6364-01_") for n in names_a)
    assert not any(n.startswith("12674-01-GA_") for n in names_b)
    assert f"12674-01-GA_{stamp_a}.xlsx" in names_a and f"6364-01_{stamp_b}.xlsx" in names_b
    assert f"6364-01_{stamp_b}_record.json" in names_b and f"6364-01_{stamp_b}_covering_email.html" in names_b
    assert any("left behind" in line and "12674-01-GA" in line for line in log_b)
    assert runner._unit_cost_from_deliverables(filed_a, "12674-01-GA", now - 5) == 1034.37
    assert runner._unit_cost_from_deliverables(filed_b, "6364-01", now - 5) == 1383.58


def test_the_service_does_not_take_another_jobs_files_from_an_older_runner(tmp_path):
    sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
    import estimate_routes as er
    theirs = _engine_writes(tmp_path / "a", "12674-01-GA", "20261111_141715", 1034.37)
    own = _engine_writes(tmp_path / "b", "6364-01", "20261111_143000", 1383.58)

    class _Run:
        drawing_number, started_at, said = "6364-01", _at("20261111_141000"), []
        def line(self, text):
            self.said.append(text)
    run = _Run()
    kept = er._only_this_runs_files(run, theirs + own)
    assert {f["name"] for f in kept} == {f["name"] for f in own}
    assert any("named for another job" in t for t in run.said)
    import estimate_email
    assert "6364-01" in Path(next(f["path"] for f in kept if f["name"].endswith("_covering_email.html"))).name
    assert estimate_email.engine_note(kept) is not None


# ── the correction shows its changes first and keeps the original ───────────────────────────
def _saved_run_file(runs: Path, run: dict) -> Path:
    runs.mkdir(exist_ok=True)
    p = runs / f"{run['run_id']}.json"
    p.write_text(json.dumps(run), encoding="utf-8")
    return p


def test_the_correction_proposes_first_and_changes_nothing(tmp_path, capsys):
    late = _engine_writes(tmp_path / "a", "12674-01-GA", "20261111_141715", 1034.37)
    own = _run_files(tmp_path, "6364-01", "20261111_143000", 1383.58, {1: 1383.58, 5: 974.39})
    run = _saved("b45095", "6364-01", 1034.37, late + own, {1: 1034.37, 5: 769.03})
    run["email_result"] = {"sent": True, "recipients": ["a@x", "b@x"],
                           "attached": [f["name"] for f in late + own if not f["name"].endswith("_covering_email.html")]}
    path = _saved_run_file(tmp_path / "runs", run)
    was = path.read_text()
    assert price_correct.main(["--runs", str(tmp_path / "runs")]) == 0
    out = capsys.readouterr().out
    assert "1034.37  ->  1383.58" in out and "5: 974.39" in out
    assert "12674-01-GA_20261111_141715.xlsx" in out and "left on disk" in out
    assert "ANOTHER JOB'S NOTE" in out and "sent to 2 recipient(s)" in out
    assert "Nothing was changed" in out
    assert path.read_text() == was and not (tmp_path / "runs" / "corrections").exists()


def test_applying_keeps_the_original_and_deletes_no_file(tmp_path, capsys):
    late = _engine_writes(tmp_path / "a", "12674-01-GA", "20261111_141715", 1034.37)
    own = _run_files(tmp_path, "6364-01", "20261111_143000", 1383.58, {1: 1383.58, 5: 974.39})
    run = _saved("b45095", "6364-01", 1034.37, late + own, {1: 1034.37, 5: 769.03})
    path = _saved_run_file(tmp_path / "runs", run)
    ok = _saved_run_file(tmp_path / "runs", _saved("fine", "6364-01", 1383.58, own, {1: 1383.58, 5: 974.39}))
    ok_was = ok.read_text()
    price_correct.main(["--runs", str(tmp_path / "runs"), "--apply"])
    now = json.loads(path.read_text())
    assert now["engine_price_gbp"] == 1383.58
    assert now["quantity_prices"] == [{"quantity": 1, "unit_gbp": 1383.58}, {"quantity": 5, "unit_gbp": 974.39}]
    assert {d["name"] for d in now["deliverables"]} == {f["name"] for f in own}
    assert {d["name"] for d in now["set_aside_files"]} == {f["name"] for f in late}
    assert all(Path(f["path"]).is_file() for f in late + own), "no file is deleted or moved"
    kept = list((tmp_path / "runs" / "corrections").glob("b45095.*.before.json"))
    assert len(kept) == 1 and json.loads(kept[0].read_text())["engine_price_gbp"] == 1034.37
    assert ok.read_text() == ok_was
    assert price_audit.check_run(now)["verdict"] == "ok"
    # a second pass has nothing left to do, and the service's own loader ignores the copies
    capsys.readouterr()
    price_correct.main(["--runs", str(tmp_path / "runs")])
    assert "0 saved run(s) would change" in capsys.readouterr().out
    assert sorted(p.name for p in (tmp_path / "runs").glob("*.json")) == ["b45095.json", "fine.json"]


def test_a_record_filed_with_another_run_is_located_and_checked(tmp_path):
    a = _run_files(tmp_path, "12674-01-GA", "20261111_141715", 1034.37)
    b = _run_files(tmp_path, "6364-01", "20261111_143000", 1383.58)
    runs = tmp_path / "runs"
    _saved_run_file(runs, _saved("c2623d", "12674-01-GA", 1034.37, a[:1]))        # its record went elsewhere
    _saved_run_file(runs, _saved("b45095", "6364-01", 1034.37, a + b))
    rows = {r["run_id"]: r for r in price_audit.check_runs(runs)}
    assert rows["c2623d"]["verdict"] == "ok" and "filed with run b45095" in rows["c2623d"]["record_found"]
    assert rows["b45095"]["verdict"] == "MISMATCH"


def test_a_record_declaring_another_drawing_is_never_used(tmp_path):
    own = _run_files(tmp_path, "6364-01", "20261111_143000", 1383.58)
    rec = Path(own[1]["path"])
    rec.write_text(json.dumps({"declared_product": "12674-01-GA", "totals": {"unit_cost_gbp": 1034.37}}))
    row = price_audit.check_run(_saved("x", "6364-01", 1034.37, own))
    assert row["verdict"] == "not checked" and "declares drawing 12674-01-GA" in row["why"]


def test_a_run_whose_record_priced_other_quantities_is_held_not_rewritten(tmp_path, capsys):
    own = _run_files(tmp_path, "11896-02-01-GA", "20261110_135633", 1311.40, {1: 1311.40, 8: 943.47})
    run = _saved("ad01", "11896-02-01-GA", 898.96, own, {1: 898.96, 68: 423.85}, started="20261110_130000")
    run["quantity_breaks"] = [1, 68]
    path = _saved_run_file(tmp_path / "runs", run)
    was = path.read_text()
    price_correct.main(["--runs", str(tmp_path / "runs"), "--apply"])
    out = capsys.readouterr().out
    assert "HELD" in out and "[1, 68]" in out and "[1, 8]" in out
    assert path.read_text() == was
    run["quantity_breaks"] = [1, 8]                 # the run was asked for what the record priced
    path.write_text(json.dumps(run))
    price_correct.main(["--runs", str(tmp_path / "runs"), "--apply"])
    assert json.loads(path.read_text())["engine_price_gbp"] == 1311.40
