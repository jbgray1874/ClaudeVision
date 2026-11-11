"""Grid Control picks up every job through any part of the estimator (JG, 11 Nov 2026).

"the grid runner views also need to pick up all jobs running through any part of the estimator -
the individual jobs or the ai self running portal". Every queued or running job was already on
both services' walls; now each says where it came from, and the work before the queue (Self-Running
reading or staging, a TTI batch's rows) is shown too.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
sys.path.insert(0, str(ROOT / "src"))

import estimate_wall as ew  # noqa: E402


def test_the_source_names_the_entry_point():
    import estimate_routes as er
    assert er.job_source("self_running") == "Self-Running"
    assert er.job_source("tti") == "TTI batch"
    assert er.job_source("") == "Estimating page"
    assert er.job_source("", "partner-site") == "Partner: partner-site"


def test_each_entry_point_says_where_it_came_from():
    import live_enquiry_runner as ler
    assert '"source": "self_running"' in (ROOT / "src" / "live_enquiry_runner.py").read_text()
    assert '"source": "tti"' in (ROOT / "src" / "tti_pricer.py").read_text()
    assert hasattr(ler, "request_body")


def test_the_wall_carries_the_source_on_every_job():
    run = {"run_id": "a1", "drawing_number": "12110-01-GA1", "client": "TTI", "status": "queued",
           "queued_at": 100.0, "source": "TTI batch"}
    snap = ew.snapshot([run], [], now=200.0)
    assert snap["queue"][0]["source"] == "TTI batch"


def test_self_running_and_a_tti_batch_are_shown_before_their_jobs_are_queued():
    sr = {"enabled": True, "watcher": {"connected": True, "phase": "staging the pack",
                                       "message": "11896-04-00-GA (TTI)", "host": "LAPTOP"}}
    tti = {"sheet": r"\\x\TRACKER.xlsx", "started": "2026-11-11T16:00:00", "dry_run": False,
           "rows": [{"row": 17, "state": "done"}, {"row": 18, "state": "running", "drawing": "12161-02-GA",
                                                    "run_id": "r2"}, {"row": 19, "state": "planned"}]}
    dry = dict(tti, dry_run=True)
    out = ew.intake(sr, [tti, dry], now=0.0)
    assert [x["from"] for x in out] == ["Self-Running", "TTI batch"], "a dry run queues nothing"
    assert out[0]["phase"] == "staging the pack"
    assert out[1]["by_state"]["done"] == 1 and out[1]["current"][0]["drawing"] == "12161-02-GA"


def test_a_switched_off_unconnected_watcher_and_an_old_batch_are_not_shown():
    old = {"sheet": "T.xlsx", "finished": "2026-01-01T00:00:00", "rows": []}
    assert ew.intake({"enabled": False, "watcher": {}}, [old], now=2e9) == []


def test_the_wall_page_shows_the_source_and_the_intake():
    page = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-wall.html").read_text()
    assert "function src(r)" in page and "intakeRows(intake)" in page and "s.intake" in page
