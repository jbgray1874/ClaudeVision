"""THE SELF-RUNNING RE-RUN BUTTON REACHES SELF-RUNNING (JG and the reviewer, 12 Nov 2026).

"Could not ask for a re-run: That run is not on this service." The page posted to
/api/estimate/self-running/rerun. A route declared earlier, /{run_id}/rerun, took the request,
looked for a run called "self-running", found none and refused. Nothing was queued.

These tests press the button over HTTP on the real router, and walk every route so that no
pattern can swallow a fixed path declared after it again.
"""
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"


@pytest.fixture
def er(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SDI_GRID_PEERS", "")
    monkeypatch.delenv("SDI_SELF_RUNNING_HOME", raising=False)
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email", "staging", "estimate_history",
             "estimate_wall", "grid_peers")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    sys.path.insert(0, str(BACKEND))
    try:
        import estimate_routes as mod
        mod._RUNS.clear()
        mod._RUNNERS.clear()
        monkeypatch.setattr(mod, "_self_running_home", lambda request: "")
        yield mod
    finally:
        sys.path.remove(str(BACKEND))
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def _client(er):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(er.router)
    tc = TestClient(app)
    key = getattr(er.config, "API_KEY", "") or ""
    if key:
        tc.headers.update({"X-SDI-Key": key})
    return tc


def test_the_self_running_button_reaches_self_running_and_the_job_is_asked_for(er):
    tc = _client(er)
    r = tc.post("/api/estimate/self-running/rerun",
                json={"drawing": "12345-01-GA", "customer": "A customer", "by": "the page"})
    assert r.status_code == 200, r.text
    assert "not on this service" not in r.text
    asked = er.self_running_switch._load().get("rerun") or []
    assert [a["drawing"] for a in asked] == ["12345-01-GA"], "the watcher has the job to take"
    assert asked[0]["by"] == "the page"


def test_pressing_twice_asks_for_the_job_once(er):
    tc = _client(er)
    for _ in range(2):
        assert tc.post("/api/estimate/self-running/rerun",
                       json={"drawing": "12345-01-GA"}).status_code == 200
    asked = er.self_running_switch._load().get("rerun") or []
    assert len(asked) == 1


def test_a_press_with_no_drawing_is_refused_by_self_running_itself(er):
    r = _client(er).post("/api/estimate/self-running/rerun", json={"drawing": " "})
    assert r.status_code == 400 and "which drawing" in r.text


def test_a_run_id_this_service_does_not_hold_is_still_refused(er):
    r = _client(er).post("/api/estimate/no-such-run/rerun")
    assert r.status_code == 404 and "not on this service" in r.text


def test_grid_controls_re_run_on_another_service_still_has_its_own_route(er):
    r = _client(er).post("/api/estimate/grid/rerun",
                         json={"service": "http://10.9.9.9:8071", "run_id": "abc"})
    assert "That run is not on this service" not in r.text, "not read as a run called 'grid'"


def _swallows(pattern: str, fixed: str) -> bool:
    """Would this pattern route take a request for this fixed path?"""
    rx = "^" + re.sub(r"\\\{[^/}:]+:path\\\}", ".*",
                      re.sub(r"\\\{[^/}:]+\\\}", "[^/]+", re.escape(pattern))) + "$"
    return re.match(rx, fixed) is not None


def test_no_pattern_route_is_declared_ahead_of_a_fixed_path_it_would_take(er):
    routes = [(r.path, set(r.methods or ())) for r in er.router.routes if hasattr(r, "methods")]
    taken = []
    for i, (early, early_methods) in enumerate(routes):
        if "{" not in early:
            continue
        for late, late_methods in routes[i + 1:]:
            if "{" in late or not (early_methods & late_methods):
                continue
            if _swallows(early, late):
                taken.append(f"{sorted(early_methods & late_methods)} {early} takes {late}")
    assert not taken, "declare the fixed path first:\n" + "\n".join(taken)


def test_the_check_itself_sees_the_fault_it_guards():
    assert _swallows("/api/estimate/{run_id}/rerun", "/api/estimate/self-running/rerun")
    assert not _swallows("/api/estimate/{run_id}/rerun", "/api/estimate/self-running/stop")
