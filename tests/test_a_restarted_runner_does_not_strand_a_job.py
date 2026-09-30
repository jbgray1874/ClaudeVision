"""A runner restarted mid-job does not strand the job, and the machine cannot quietly run two portals.

30 Sep 2026, the M&S steel run. The laptop's runner was restarted twenty minutes into the job.
The engine finished on the laptop, but filing to the share is the runner's last step, so the
report, quote and note never left output\\estimates. The service kept the run "running": the
restarted runner polls under the same machine id, so nothing looked dead, and the next run of
the job was refused as a duplicate for 27 minutes until released by hand. The new runner was
also serving only 8072, the port that answered at the moment it started, while the page was
on 8071; the laptop had portals on both ports, each with its own queue.

D-369:
* a claim or heartbeat from the same machine under a NEW process fails the run the old process
  held, with where its results are — no timer involved, so it holds for any job length;
* restart-runner.ps1 refuses to restart a runner mid-job unless -Force;
* the runner is given every local portal port, not only the ones answering at start;
* the page warns when a second portal answers on the same machine.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))


@pytest.fixture()
def er(monkeypatch):
    import estimate_routes
    estimate_routes._RUNS.clear()
    estimate_routes._RUNNERS.clear()
    monkeypatch.setattr(estimate_routes, "_other_local_services", lambda port: [])
    return estimate_routes


def _running(er, process="pid 100 LAPTOP since 17:55"):
    run = er.Run(run_id="r1", client="M&S", drawing_number="bdab4adf-3340-40M&S", units=350,
                 job_folder="J", output_path="O")
    run.status, run.runner, run.lease_until = "running", "LAPTOP-abc", 9e18
    run.claimed_by_process = process
    er._RUNS["r1"] = run
    er._RUNNERS["LAPTOP-abc"] = er.Runner(runner_id="LAPTOP-abc", hostname="LAPTOP",
                                           run_id="r1")
    return run


def _claim(er, process):
    return er.claim(er.ClaimRequest(runner_id="LAPTOP-abc", hostname="LAPTOP",
                                    process=process, build="92e32ea"))


def test_a_restarted_runner_releases_the_job_its_predecessor_held(er):
    run = _running(er)
    _claim(er, "pid 200 LAPTOP since 18:04")
    assert run.status == "error"
    assert "restarted while this job was running" in run.error
    assert "output" in run.error and "estimates" in run.error
    assert er._RUNNERS["LAPTOP-abc"].run_id == ""


def test_the_same_process_polling_keeps_its_job(er):
    run = _running(er)
    out = _claim(er, "pid 100 LAPTOP since 17:55")
    assert run.status == "running"
    assert out["run"] is None


def test_a_heartbeat_from_a_new_process_releases_it_too(er):
    run = _running(er)
    er.heartbeat(er.ClaimRequest(runner_id="LAPTOP-abc", hostname="LAPTOP",
                                 process="pid 300 LAPTOP since 18:10"))
    assert run.status == "error"


def test_a_runner_too_old_to_name_its_process_is_left_to_the_lease(er):
    run = _running(er, process="")
    _claim(er, "pid 200 LAPTOP since 18:04")
    assert run.status == "running"


def test_another_machines_runner_never_releases_it(er):
    run = _running(er)
    er.claim(er.ClaimRequest(runner_id="SERVER-xyz", hostname="SERVER", process="pid 9"))
    assert run.status == "running"


def test_the_claim_records_its_process(er):
    run = er.Run(run_id="q1", client="M&S", drawing_number="X", units=1,
                 job_folder="J", output_path="O")
    run.wants_engine = True
    er._RUNS["q1"] = run
    _claim(er, "pid 400 LAPTOP since 19:00")
    assert run.status == "running" and run.claimed_by_process == "pid 400 LAPTOP since 19:00"


def test_the_runners_list_names_a_second_local_portal(er, monkeypatch):
    monkeypatch.setattr(er, "_other_local_services",
                        lambda port: [{"port": 8071, "commit": "509500d"}])
    assert er.runners()["other_local_services"] == [{"port": 8071, "commit": "509500d"}]
    page = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
        encoding="utf-8")
    assert "d.other_local_services" in page and "A second " in page


def test_restart_runner_refuses_mid_job_unless_forced():
    src = (ROOT / "tools" / "start" / "restart-runner.ps1").read_text(encoding="utf-8")
    assert "[switch] $Force" in src
    guard = src.index("# -- 0b. NOT IN THE MIDDLE OF A JOB")
    assert guard < src.index("# -- 1. PULL, IF ASKED"), "asked before any pull or stop"
    assert "/api/estimate/runners" in src[guard:] and "exit 6" in src[guard:]


def test_the_runner_is_given_every_local_port():
    start = (ROOT / "tools" / "start" / "start-runner.ps1").read_text(encoding="utf-8")
    assert '$Server = ($candidates -join ",")' in start
    task = (ROOT / "tools" / "start" / "install-runner-task.ps1").read_text(encoding="utf-8")
    line = next(l for l in task.splitlines() if "[string] $Server" in l)
    assert "8071" in line and "8072" in line and "SDI_PORT" in line
