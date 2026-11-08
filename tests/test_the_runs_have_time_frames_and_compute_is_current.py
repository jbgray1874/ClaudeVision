"""The control panel's lists take a time frame, a machine's compute is as current as it says,
and a run that has ended never says its model read is "not reached yet" (D-746).

JG, 7 Nov 2026: "We should add in another filter for time frames also as the list will get
large." And of the laptop's compute tile: "is this updating dynamically / regularly? needs to
be accurate..."

The runner measures every 5 s. The service running the job hears every reading; the other
services heard one in three, from a 15 s beat. The "15 MIN" line was 180 points of whatever
arrived 4 s apart, re-sent readings included, so it spanned anything from 12 to 45 minutes.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
WALL = BACKEND / "sdi-estimating-wall.html"
NOW = time.mktime((2026, 11, 7, 21, 0, 0, 0, 0, -1))


def _wall():
    sys.path.insert(0, str(BACKEND))
    try:
        import estimate_wall
        return estimate_wall
    finally:
        sys.path.remove(str(BACKEND))


def _run(status, log, **kw):
    return {"run_id": "r1", "status": status, "job_type": "", "log": log,
            "error": "stopped from the page" if status == "error" else "", **kw}


# ── what a finished run says about its models ───────────────────────────────────────────

def test_a_run_that_ended_before_its_model_read_never_says_not_reached_yet():
    W = _wall()
    for status in ("done", "error"):
        ev = W.evidence(_run(status, ["[scan] staged", "[pricing] parts priced"]))
        assert ev["kind"] == "none" and ev["label"] == "No model read in its log"
        assert "yet" not in ev["label"]
    waiting = W.evidence(_run("error", ["[scan] staged"], sw_wait_since=NOW - 60))
    assert waiting["why"] == "it ended while waiting for SolidWorks"
    assert W.evidence(_run("running", ["[scan] staged"]))["label"] == "Model read not reached yet"


def test_what_was_kept_before_this_change_is_said_the_new_way():
    W = _wall()
    run = _run("done", [], evidence_kept={"kind": "pending", "label": "Model read not reached yet",
                                          "why": "", "caution": False, "lines": 12})
    assert W.evidence(run)["label"] == "No model read in its log"


# ── a machine's compute ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    share = tmp_path / "share"
    (share / "stage").mkdir(parents=True)
    (share / "out").mkdir()
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SDI_FILE_ROOTS", str(share))
    monkeypatch.setenv("SDI_STAGING_ROOT", str(share / "stage"))
    monkeypatch.setenv("SDI_ESTIMATE_OUTPUT_ROOT", str(share / "out"))
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email", "staging", "estimate_history",
             "estimate_wall")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    sys.path.insert(0, str(BACKEND))
    try:
        import estimate_routes as er
        er._RUNS.clear()
        er._RUNNERS.clear()
        yield er
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        sys.path.remove(str(BACKEND))
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def _reading(at, cpu):
    return {"at": at, "cpu_pct": cpu, "mem_total_gb": 64.0, "mem_used_gb": 28.0,
            "host": "DESKTOP-GFAAP80", "by": "psutil"}


def test_one_point_per_reading_and_fifteen_minutes_of_them(client):
    er = client
    rn = er.Runner(runner_id="laptop", hostname="DESKTOP-GFAAP80")
    er._note_compute(rn, _reading(1000.0, 7.2), now=NOW)
    er._note_compute(rn, _reading(1000.0, 7.2), now=NOW + 2)     # the same reading, re-sent
    er._note_compute(rn, _reading(1000.0, 7.2), now=NOW + 4)
    assert len(rn.compute_history) == 1
    assert rn.compute["received_at"] == NOW + 4                  # still heard: the runner is alive
    er._note_compute(rn, _reading(1005.0, 9.0), now=NOW + 5)
    assert [p[1] for p in rn.compute_history] == [7.2, 9.0]
    for i in range(1, 200):                                      # 16 more minutes of readings
        er._note_compute(rn, _reading(1005.0 + 5 * i, 10.0), now=NOW + 5 + 5 * i)
    span = rn.compute_history[-1][0] - rn.compute_history[0][0]
    assert span <= er._COMPUTE_WINDOW_S and span >= er._COMPUTE_WINDOW_S - 5
    assert len(rn.compute_history) == 181                        # 900 s at one reading each 5 s


def test_every_service_hears_each_reading_while_a_job_runs():
    sys.path.insert(0, str(ROOT / "tools" / "runner"))
    try:
        import sdi_estimate_runner as runner
    finally:
        sys.path.remove(str(ROOT / "tools" / "runner"))
    assert runner._heartbeat_while_busy._EVERY == runner._COMPUTE_EVERY == 5.0


def test_the_wall_says_how_old_each_machines_reading_is():
    page = WALL.read_text(encoding="utf-8")
    assert '(m.fresh ? "measured " : "last measured ") + fmtDur(m.age_s) + " ago"' in page


# ── time frames on the lists ────────────────────────────────────────────────────────────

def test_the_lists_take_a_time_frame():
    page = WALL.read_text(encoding="utf-8")
    assert '<select id="hRunsT"><option value="">last 30 days</option><option value="7">last 7 days</option>' in page
    assert '<option value="today">today</option>' in page
    assert '<select id="hFiledT"><option value="">all time</option><option value="365">last 12 months</option>' in page
    assert "function sinceOf(v){" in page and "function dayOf(ts){" in page
    assert "(!since || (r.finished_at || 0) >= since)" in page
    assert 'String(r.stamp || "").slice(0, 10) >= from' in page
    assert '$("hRunsT").addEventListener("change", renderHRuns);' in page
    assert '$("hFiledT").addEventListener("change", renderHFiled);' in page
    # A period reaching past the newest listed is said to be partial, never shown as whole.
    assert '" · only the newest " + rows.length + " are listed"' in page


def test_the_panel_is_named_live_estimating():
    """JG, 8 Nov 2026: "SDI INTELLIGENCE // ESTIMATING - pls change to SDI INTELLIGENCE // LIVE
    ESTIMATING"."""
    page = WALL.read_text(encoding="utf-8")
    assert "<h1>SDI INTELLIGENCE <b>//</b> LIVE ESTIMATING</h1>" in page
