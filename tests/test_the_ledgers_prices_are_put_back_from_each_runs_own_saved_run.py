"""THE SELF-RUNNING LEDGER'S PRICES ARE PUT BACK FROM EACH RUN'S OWN SAVED RUN (JG, 12 Nov 2026).

The page's Self-Running list showed two different jobs at one price at every quantity, and a
job at another job's quantity. The saved runs were corrected; the ledger the list reads from
was not. "yes, build the ledger correction and show the changes first."
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ledger_correct as LC  # noqa: E402

CROSSED = [{"quantity": 1, "unit_gbp": 1083.77}, {"quantity": 17, "unit_gbp": 958.80}]
OWN = [{"quantity": 1, "unit_gbp": 612.40}, {"quantity": 5, "unit_gbp": 401.10}]


def _ledger():
    return {"schema": "live_enquiry_ledger.v1", "quantities": {}, "jobs": {
        "a|10000-02": {"customer": "A", "drawing": "10000-02", "attempts": [
            {"run_id": "run-a", "status": "done", "engine_price_gbp": 1083.77, "quantity_prices": CROSSED},
            {"run_id": "run-a-failed", "status": "error"}]},
        "b|20000-04-GA": {"customer": "B", "drawing": "20000-04-GA", "attempts": [
            {"run_id": "run-b", "status": "done", "engine_price_gbp": 1083.77, "quantity_prices": CROSSED}]},
        "c|30000-01": {"customer": "C", "drawing": "30000-01", "attempts": [
            {"run_id": "run-c", "status": "done", "engine_price_gbp": 50.0,
             "quantity_prices": [{"quantity": 1, "unit_gbp": 50.0}]},
            {"run_id": "run-gone", "status": "done", "engine_price_gbp": 9.0, "quantity_prices": []}]}}}


def _saved():
    return {"run-a": {"run_id": "run-a", "drawing_number": "10000-02", "engine_price_gbp": 612.40, "quantity_prices": OWN},
            "run-b": {"run_id": "run-b", "drawing_number": "20000-04-GA", "engine_price_gbp": 1083.77, "quantity_prices": CROSSED},
            "run-c": {"run_id": "run-c", "drawing_number": "30000-01", "engine_price_gbp": 77.0,
                      "quantity_prices": [{"quantity": 1, "unit_gbp": 77.0}]}}


OK = {"run-a": {"verdict": "ok"}, "run-b": {"verdict": "ok"},
      "run-c": {"verdict": "not checked", "why": "no pinned record"}}


def test_the_crossed_job_is_proposed_from_its_own_run_and_the_right_one_is_left():
    change, left = LC.proposals(_ledger(), _saved(), OK)
    assert [c["run_id"] for c in change] == ["run-a"]
    assert change[0]["to"] == {"engine_price_gbp": 612.40, "quantity_prices": OWN}
    assert change[0]["from"]["quantity_prices"] == CROSSED, "what it was is kept in the proposal"


def test_a_run_not_proved_against_its_record_or_not_on_the_service_is_left_and_said():
    _change, left = LC.proposals(_ledger(), _saved(), OK)
    why = {x["run_id"]: x["why"] for x in left}
    assert "not checked" in why["run-c"] and "no saved run" in why["run-gone"]
    assert "run-a-failed" not in why, "a run that did not finish carries no price to correct"


def test_a_saved_run_for_another_drawing_is_never_copied_in():
    saved = _saved()
    saved["run-a"]["drawing_number"] = "99999-09"
    change, left = LC.proposals(_ledger(), saved, OK)
    assert not change and any("not this job" in x["why"] for x in left)


def test_the_pairs_sharing_prices_are_named_before_and_gone_after():
    led = _ledger()
    assert LC.shared_prices(led) == ["10000-02 and 20000-04-GA: 1 off 1083.77, 17 off 958.80"]
    change, _ = LC.proposals(led, _saved(), OK)
    assert LC.apply(led, change, "2026-11-12 17:00:00") == 1
    assert LC.shared_prices(led) == []
    a = led["jobs"]["a|10000-02"]["attempts"][0]
    assert a["engine_price_gbp"] == 612.40 and a["price_corrected"]["from"]["engine_price_gbp"] == 1083.77
    assert a["status"] == "done" and a["run_id"] == "run-a", "nothing but the two price fields moves"


def _files(tmp_path):
    ledger = tmp_path / "live" / "ledger.json"
    ledger.parent.mkdir()
    ledger.write_text(json.dumps(_ledger()))
    runs = tmp_path / "runs"
    runs.mkdir()
    for rid, run in _saved().items():
        (runs / f"{rid}.json").write_text(json.dumps(run))
    return ledger, runs


def test_showing_the_changes_changes_nothing(tmp_path, monkeypatch, capsys):
    ledger, runs = _files(tmp_path)
    monkeypatch.setattr(LC.pa, "check_runs", lambda folder: [dict(v, run_id=k) for k, v in OK.items()])
    before = ledger.read_text()
    assert LC.main(["--ledger", str(ledger), "--runs", str(runs)]) == 0
    out = capsys.readouterr().out
    assert "Nothing was changed" in out and "1083.77  ->  612.4" in out
    assert ledger.read_text() == before and not (ledger.parent / "corrections").exists()


def test_applying_keeps_the_ledger_as_it_was_and_a_second_pass_proposes_nothing(tmp_path, monkeypatch, capsys):
    ledger, runs = _files(tmp_path)
    monkeypatch.setattr(LC.pa, "check_runs", lambda folder: [dict(v, run_id=k) for k, v in OK.items()])
    before = ledger.read_text()
    assert LC.main(["--ledger", str(ledger), "--runs", str(runs), "--apply"]) == 0
    kept = list((ledger.parent / "corrections").glob("ledger.*.before.json"))
    assert len(kept) == 1 and kept[0].read_text() == before
    assert json.loads(ledger.read_text())["jobs"]["a|10000-02"]["attempts"][0]["engine_price_gbp"] == 612.40
    capsys.readouterr()
    assert LC.main(["--ledger", str(ledger), "--runs", str(runs)]) == 0
    assert "0 attempt(s) to correct" in capsys.readouterr().out


def test_a_file_that_is_not_a_ledger_is_refused(tmp_path, capsys):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"schema": "something else"}))
    assert LC.main(["--ledger", str(p), "--runs", str(tmp_path)]) == 2
    assert "Nothing changed" in capsys.readouterr().out
