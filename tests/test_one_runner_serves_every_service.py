"""One runner serves every SDI service on the machine — there is no port to get wrong.

James Gray, 23 Sep 2026: "this runner going down all the time is completely unacceptable."

It had not gone down. On 22 and 23 September the runner was up, healthy and on the right
build, and registered with the OTHER service: the installed one on 8071 and a hand-started
one on 8072 each keep their own queue and their own list of runners, and a runner polled
exactly one. Whichever page was open said "No runner connected". Five fixes to WHICH port it
should pick each moved the failure instead of removing it, because the fault was the choice.

So the runner takes a list and asks every service on it for work. One job still runs at a
time; while it runs, the other services receive a heartbeat that can never hand out a job.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import sdi_estimate_runner as runner                                  # noqa: E402


class _Reply:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _FakeRequests:
    """Two services: 8071 has nothing queued, 8072 has one job."""

    def __init__(self):
        self.posts = []
        self.handed = False

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append(url)
        if url.endswith("/runner/claim") and ":8072" in url and not self.handed:
            self.handed = True
            return _Reply({"run": {"run_id": "r1"}})
        return _Reply({"run": None})


def test_a_job_on_either_service_is_found():
    fake = _FakeRequests()
    job_a, _ = runner._ask_for_work(fake, "http://localhost:8071", {}, "rid", "p", "b", None)
    job_b, _ = runner._ask_for_work(fake, "http://localhost:8072", {}, "rid", "p", "b", None)
    assert job_a is None and job_b == {"run_id": "r1"}
    assert fake.posts == ["http://localhost:8071/api/estimate/runner/claim",
                          "http://localhost:8072/api/estimate/runner/claim"]


def test_while_busy_the_others_get_a_heartbeat_never_a_claim(monkeypatch):
    monkeypatch.setattr(runner._heartbeat_while_busy, "_EVERY", 0.01)
    fake = _FakeRequests()
    import time
    with runner._heartbeat_while_busy(fake, ["http://localhost:8071"], {}, "rid", "p", "b"):
        time.sleep(0.05)
    assert fake.posts, "the other service heard nothing for the length of the job"
    assert all(u == "http://localhost:8071/api/estimate/runner/heartbeat" for u in fake.posts)


def test_a_dead_service_does_not_stop_the_live_one():
    class _Half(_FakeRequests):
        def post(self, url, **kw):
            if ":8071" in url:
                raise ConnectionError("refused")
            return super().post(url, **kw)
    fake = _Half()
    job, said = runner._ask_for_work(fake, "http://localhost:8071", {}, "rid", "p", "b", None)
    assert job is None and said == "unreachable"
    job, _ = runner._ask_for_work(fake, "http://localhost:8072", {}, "rid", "p", "b", None)
    assert job == {"run_id": "r1"}


def test_the_task_and_the_start_script_serve_both_ports_by_default():
    task = (ROOT / "tools" / "start" / "install-runner-task.ps1").read_text(encoding="utf-8-sig")
    assert "http://localhost:8071,http://localhost:8072" in task
    start = (ROOT / "tools" / "start" / "start-runner.ps1").read_text(encoding="utf-8-sig")
    assert '$Server = ($answering -join ",")' in start


@pytest.fixture()
def api(tmp_path, monkeypatch):
    stub = types.ModuleType("config")
    stub.API_KEY = ""
    stub.FILE_ROOTS = [str(tmp_path)]
    monkeypatch.setitem(sys.modules, "config", stub)
    monkeypatch.syspath_prepend(str(BACKEND))
    sys.modules.pop("estimate_routes", None)
    er = pytest.importorskip("estimate_routes",
                             reason="fastapi/pydantic not installed in this environment")
    er._RUNS.clear(); er._RUNNERS.clear()
    return er


def test_a_heartbeat_shows_the_runner_online_and_hands_out_nothing(api):
    er = api
    er._RUNS["q1"] = er.Run(run_id="q1", client="C", drawing_number="D", units=1,
                            job_folder="", output_path="", queued_at=0.0)
    out = er.heartbeat(er.ClaimRequest(runner_id="rid", hostname="DESKTOP",
                                       process="pid 1", build="abc"))
    assert "run" not in out and er._RUNS["q1"].status == "queued"
    listed = er.runners()
    assert listed["online"] == 1 and listed["runners"][0]["busy_elsewhere"] is True
    # A real claim afterwards clears the flag and takes the job.
    assert er.claim(er.ClaimRequest(runner_id="rid"))["run"]["run_id"] == "q1"
    assert er.runners()["runners"][0]["busy_elsewhere"] is False
