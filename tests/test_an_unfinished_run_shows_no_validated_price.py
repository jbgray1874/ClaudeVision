"""AN UNFINISHED RUN SHOWS NO VALIDATED PRICE (reviewer, 12 and 13 Nov 2026).

"For unfinished runs, show 'failed/incomplete, no validated price'. Preserve any earlier
completed estimate separately, clearly dated; don't present its price as the failed run's
result." Two ledger rows showed a figure for runs that never finished.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ledger_correct as lc  # noqa: E402
import live_enquiry_runner as ler  # noqa: E402

DONE = {"run_id": "aaa", "status": "done", "output_path": r"C:\out\J-01_20261112_1609.xlsm",
        "engine_price_gbp": 1015.79, "quantity_prices": [{"quantity": 1, "unit_price_gbp": 1015.79}],
        "deliverables": ["J-01_20261112_1609.xlsm", "J-01_record.json"], "finished_at": "2026-11-12 16:09:00"}


def _attempt(**over):
    a = json.loads(json.dumps(DONE)); a.update(over); return a


def test_a_finished_run_with_its_workbook_shows_its_price():
    assert ler.validated_price(_attempt()) == 1015.79 and ler.price_words(_attempt()) == "£1,015.79"


def test_a_failed_a_stopped_and_a_workbookless_run_show_no_price():
    for bad in (_attempt(status="error", error="engine exited 1"),
                _attempt(stopped_by_hand=True),
                _attempt(price_validated=False),
                _attempt(engine_price_gbp=None), _attempt(engine_price_gbp=0)):
        assert ler.validated_price(bad) is None, bad
        assert ler.price_words(bad) == "failed/incomplete, no validated price"


def test_a_run_still_going_shows_nothing_rather_than_a_failure():
    assert ler.price_words({"status": "running"}) == "" and ler.price_words({"status": "queued"}) == ""


def test_the_figure_a_failing_run_posted_is_kept_aside_not_shown():
    got = ler._attempt_from({"status": "error", "error": "engine exited 1", "engine_price_gbp": 812.4,
                             "quantity_prices": [{"quantity": 1, "unit_price_gbp": 812.4}]}, {})
    assert got["engine_price_gbp"] is None and got["quantity_prices"] == []
    assert got["unvalidated_price_gbp"] == 812.4 and got["price_validated"] is False
    assert got["price_note"] == ler.NO_VALIDATED_PRICE


def test_the_service_says_a_run_filed_no_workbook_and_the_ledger_follows():
    sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
    import estimate_routes as er
    book = [{"name": "J-01_20261112_1609.xlsm"}, {"name": "J-01_record.json"}]
    assert er.price_is_validated("done", "", book) is True
    assert er.price_is_validated("done", "", [{"name": "run.log"}]) is False
    assert er.price_is_validated("done", "", []) is False
    assert er.price_is_validated("error", "engine exited 1", book) is False
    assert er.price_is_validated("done", "refused", book) is False
    got = ler._attempt_from({"status": "done", "engine_price_gbp": 700.0, "price_validated": False,
                             "deliverables": []}, {})
    assert got["engine_price_gbp"] is None and got["unvalidated_price_gbp"] == 700.0
    src = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
    assert '"price_validated": price_is_validated(self.status, self.error, self.deliverables)' in src


def test_a_finished_run_keeps_its_price_through_the_same_door():
    got = ler._attempt_from({"status": "done", "output_path": DONE["output_path"], "engine_price_gbp": 1015.79,
                             "deliverables": [{"name": "J-01_20261112_1609.xlsm"}]}, {})
    assert got["engine_price_gbp"] == 1015.79 and "price_validated" not in got


def test_the_earlier_completed_estimate_is_kept_apart_and_dated():
    later = _attempt(run_id="bbb", status="error", error="stopped", engine_price_gbp=640.0,
                     finished_at="2026-11-12 18:40:00")
    job = {"customer": "C", "drawing": "J-01", "attempts": [_attempt(), later]}
    kept = ler.last_completed(job, before=later)
    assert kept == {"unit_gbp": 1015.79, "finished_at": "2026-11-12 16:09:00", "run_id": "aaa",
                    "output_path": DONE["output_path"]}
    assert ler.validated_price(later) is None, "the failed run does not borrow the earlier price"
    assert ler.last_completed({"attempts": [later]}) is None


def _ledger():
    return {"schema": lc.LEDGER_SCHEMA, "jobs": {
        "k1": {"customer": "C", "drawing": "J-01", "attempts": [
            _attempt(), _attempt(run_id="bbb", engine_price_gbp=640.0, finished_at="2026-11-12 18:40:00")]},
        "k2": {"customer": "C", "drawing": "J-02", "attempts": [_attempt(run_id="ccc")]},
        "k3": {"customer": "C", "drawing": "J-03", "attempts": [_attempt(run_id="ddd")]}}}


VERDICTS = {"aaa": {"verdict": "ok"}, "bbb": {"verdict": "not a finished run"},
            "ccc": {"verdict": "ok"}, "ddd": {"verdict": "not checked"}}


def test_the_correction_lists_only_runs_found_unfinished():
    found = lc.unfinished(_ledger(), VERDICTS)
    assert [f["run_id"] for f in found] == ["bbb"]
    assert found[0]["earlier_completed"]["unit_gbp"] == 1015.79
    assert found[0]["earlier_completed"]["finished_at"] == "2026-11-12 16:09:00"


def test_a_run_that_could_not_be_checked_keeps_its_figure():
    led = _ledger()
    lc.hold(lc.unfinished(led, VERDICTS), "2026-11-13 09:00:00")
    assert led["jobs"]["k3"]["attempts"][0]["engine_price_gbp"] == 1015.79
    assert led["jobs"]["k2"]["attempts"][0]["engine_price_gbp"] == 1015.79


def test_holding_keeps_the_figure_and_shows_the_words():
    led = _ledger()
    assert lc.hold(lc.unfinished(led, VERDICTS), "2026-11-13 09:00:00") == 1
    held = led["jobs"]["k1"]["attempts"][1]
    assert held["engine_price_gbp"] is None and held["unvalidated_price_gbp"] == 640.0
    assert ler.price_words(held) == "failed/incomplete, no validated price"
    assert ler.price_words(led["jobs"]["k1"]["attempts"][0]) == "£1,015.79"
    assert lc.unfinished(led, VERDICTS) == [], "a second pass finds nothing"
