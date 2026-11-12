"""The Latest runs list, and so every Re-run button, is on the card after a restart and with
Self-Running switched off (JG, 12 Nov 2026: "where have all the re-run buttons gone on the
portal now?").

The list was sent only after a read of the sheet. The service keeps it in memory, each publish
restarts the service, and with the switch off no read follows: no list, no buttons."""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import self_running as sr  # noqa: E402


def _ledger(tmp_path):
    now = datetime.now().isoformat(timespec="seconds")
    p = tmp_path / "ledger.json"
    import live_enquiry_runner as ler
    p.write_text(json.dumps({"schema": ler.LEDGER_SCHEMA, "jobs": {
        "M&S|12674-01-GA": {"customer": "M&S", "drawing": "12674-01-GA", "attempts": [
            {"status": "done", "queued_at": now, "finished_at": now, "engine_price_gbp": 931.87, "run_id": "r1"}]},
        "tesco|6364-01": {"customer": "tesco", "drawing": "6364-01", "attempts": [
            {"status": "error", "queued_at": now, "finished_at": now, "run_id": "r2", "error": "x"}]}}}),
        encoding="utf-8")
    return p


def test_a_beat_that_ran_no_cycle_still_carries_the_runs(tmp_path):
    got = sr.recent_from_ledger(_ledger(tmp_path))
    assert {r["drawing"] for r in got} == {"12674-01-GA", "6364-01"}
    assert all(r["status"] in ("done", "error") for r in got)


def test_a_ledger_that_cannot_be_read_never_stops_a_beat(tmp_path):
    assert sr.recent_from_ledger(tmp_path / "missing.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert sr.recent_from_ledger(bad) == []


def test_the_idle_beat_sends_them():
    src = (ROOT / "src" / "self_running.py").read_text(encoding="utf-8")
    i = src.index('on = switch.beat(report("idle"')
    assert 'recent=recent_from_ledger(s["ledger"])' in src[i:i + 320]


def test_every_finished_line_on_the_page_has_its_button():
    page = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
    assert "if(!live && !selfRerunSeen.has(key))" in page and "data-self-rerun" in page
