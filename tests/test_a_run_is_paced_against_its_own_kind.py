"""The wall paces a run against runs of its own kind, not one pooled "usual".

JG, 22 Nov 2026: "our time estimates for a run are way off, so we're always appearing to
over run". One median for everything sat above every thumbnail and below most drawing packs,
so packs went amber from half way through and thumbnails were told to expect an hour.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "estimate_wall", ROOT / "sdi-intelligence-backend" / "estimate_wall.py")
w = importlib.util.module_from_spec(spec)
sys.modules["estimate_wall"] = w
spec.loader.exec_module(w)

NOW = 1_800_000_000.0
TH = {"history_days": 30, "silent_after_s": 900, "slow_over": 1.0, "late_over": 1.6,
      "runner_quiet_after_s": 120}


def done(i, minutes, **extra):
    fin = NOW - 3600 * (i + 1)
    return {"run_id": f"r{i}", "status": "done", "drawing_number": extra.pop("drawing", f"D{i}"),
            "client": "ACME", "started_at": fin - minutes * 60, "finished_at": fin,
            "log": ["ESTIMATE SAVED"], **extra}


# Six thumbnails of about 15 min, six drawing packs of about 60 min, one pack that hung for
# five hours (an Excel prompt nobody saw).
HISTORY = ([done(i, 13 + i, drawing=f"TTI-C-{i:04x}", llm_only=True) for i in range(6)]
           + [done(10 + i, 55 + 2 * i) for i in range(6)]
           + [done(30, 300)])


def test_each_kind_has_its_own_usual_and_the_hung_run_does_not_set_it():
    assert w.run_kind({"drawing_number": "TTI-C-7c4c", "status": "done"}) == "brief"
    assert w.run_kind({"drawing_number": "12769-01-GA", "status": "done"}) == "pack"
    brief = w.expected_seconds(HISTORY, NOW, 30, kind="brief")
    pack = w.expected_seconds(HISTORY, NOW, 30, kind="pack")
    assert 14 * 60 <= brief <= 16 * 60
    assert 58 * 60 <= pack <= 62 * 60
    # The hung run is left out: it is past four times the packs' median.
    win = w.predict_window(HISTORY, NOW, 30, kind="pack")
    assert win["n"] == 6 and win["kind"] == "pack"
    assert win["hi_s"] < 70 * 60
    assert "hung runs left out" in win["basis"]


def test_a_drawing_pack_an_hour_in_is_on_pace_and_a_thumbnail_an_hour_in_is_late():
    pack_run = {"run_id": "p", "status": "running", "drawing_number": "12769-01-GA",
                "started_at": NOW - 58 * 60, "last_line_at": NOW - 30, "log": ["Reading"]}
    brief_run = {"run_id": "b", "status": "running", "drawing_number": "TTI-C-7c4c",
                 "llm_only": True, "started_at": NOW - 58 * 60, "last_line_at": NOW - 30,
                 "log": ["Reading"]}
    pack_win = w.window_for(HISTORY, pack_run, NOW, 30)
    brief_win = w.window_for(HISTORY, brief_run, NOW, 30)
    colour, why = w.run_rag(pack_run, NOW, w.expected_seconds(HISTORY, NOW, 30, kind="pack"),
                            TH, window=pack_win)
    assert colour == w.GREEN, why
    assert "drawing pack usually takes" in why
    colour, why = w.run_rag(brief_run, NOW, w.expected_seconds(HISTORY, NOW, 30, kind="brief"),
                            TH, window=brief_win)
    assert colour == w.RED, why
    assert "thumbnail / brief usually takes" in why


def test_slow_starts_past_the_kinds_upper_quarter_not_its_median():
    # 61 min in: past the packs' median (60) but inside their upper quarter (about 62).
    run = {"run_id": "p", "status": "running", "drawing_number": "12769-01-GA",
           "started_at": NOW - 61 * 60, "last_line_at": NOW - 30, "log": ["Reading"]}
    win = w.window_for(HISTORY, run, NOW, 30)
    assert win["mid_s"] < 61 * 60 < win["hi_s"]
    colour, why = w.run_rag(run, NOW, win["mid_s"], TH, window=win)
    assert colour == w.GREEN, why


def test_a_kind_with_too_little_history_borrows_the_pooled_window_and_says_so():
    history = [done(10 + i, 55 + 2 * i) for i in range(6)]
    brief_run = {"run_id": "b", "status": "running", "drawing_number": "TTI-C-7c4c",
                 "llm_only": True, "started_at": NOW - 60, "log": []}
    win = w.window_for(history, brief_run, NOW, 30)
    assert win["kind"] == "brief" and "too few thumbnail / brief runs yet" in win["basis"]


def test_a_queued_thumbnail_behind_a_pack_waits_its_own_kinds_usual():
    queued = [{"run_id": "q1", "status": "queued", "drawing_number": "TTI-C-aaaa",
               "llm_only": True, "queued_at": NOW - 10},
              {"run_id": "q2", "status": "queued", "drawing_number": "12800-01-GA",
               "queued_at": NOW - 5}]
    out = w.queue_etas(queued, [], NOW, 1, 60 * 60, None,
                       expected_for=lambda q: 15 * 60 if w.run_kind(q) == "brief" else 60 * 60)
    assert out[0]["finish_at"] - out[0]["start_at"] == 15 * 60
    assert out[1]["start_at"] == out[0]["finish_at"]
    assert out[1]["finish_at"] - out[1]["start_at"] == 60 * 60


def test_the_snapshot_carries_each_live_runs_kind_and_window():
    live = {"run_id": "p", "status": "running", "drawing_number": "12769-01-GA",
            "runner": "s1", "started_at": NOW - 58 * 60, "last_line_at": NOW - 30,
            "log": ["Reading"]}
    snap = w.snapshot(HISTORY + [live], [{"runner_id": "s1", "online": True,
                                          "seconds_since_seen": 2, "build": "abc"}],
                      NOW, service_commit="abc", max_runs=2)
    (card,) = snap["live"]
    assert card["kind"] == "pack" and card["window"]["kind"] == "pack"
    assert card["rag"] == w.GREEN, card["rag_reason"]
    assert set(snap["windows"]) == {"brief", "pack"}
