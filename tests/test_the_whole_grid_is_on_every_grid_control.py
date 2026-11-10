"""One Grid Control for the whole grid, and the second Grid Runner's compute check shown
(JG, 10 Nov 2026).

"whether it's on local machine and on port 8071 or 8072, the control grid still needs to see it.
we also need to start running on the server and have it all integrated." and "we also need to be
able to see that it's at least tried to check for compute resources on the second grid runner."
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
RUNNER_DIR = ROOT / "tools" / "runner"
WALL = (BACKEND / "sdi-estimating-wall.html").read_text(encoding="utf-8")


@pytest.fixture
def gp(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND))
    sys.modules.pop("grid_peers", None)
    import grid_peers
    grid_peers._cache.clear()
    yield grid_peers
    sys.modules.pop("grid_peers", None)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(answers, asked=None):
    def op(req, timeout=0):
        url = req.full_url
        if asked is not None:
            asked.append((req.get_method(), url, req.data))
        for prefix, ans in answers.items():
            if url.startswith(prefix):
                if isinstance(ans, Exception):
                    raise ans
                return _Resp(json.dumps(ans).encode())
        raise OSError("refused")
    return op


def _peer_wall(service_id="other"):
    return {"grid_service_id": service_id, "service_host": "DESKTOP-GFAAP80",
            "service_commit": "abc1234", "kpis": {"max_runs": 1},
            "live": [{"run_id": "p1", "drawing_number": "11896-02-01-GA", "client": "TTI",
                      "runner": "DESKTOP-GFAAP80-90faa0001", "rag": "red", "elapsed_s": 3780,
                      "silent_s": 780, "log_tail": ["x"] * 80}],
            "queue": [{"run_id": "p2", "drawing_number": "11896-04-00-GA", "client": "TTI",
                       "queued_at": time.time() - 60}],
            "fleet": [{"runner_id": "laptop-s2", "hostname": "DESKTOP-GFAAP80",
                       "label": "Laptop · slot 2", "online": True, "rag": "amber",
                       "gate": {"slot": 2, "ok": False, "measured": "2.1 GB free (needs 3)"}},
                      {"runner_id": None, "label": "Server", "planned": True}]}


# ── the grid ──────────────────────────────────────────────────────────────────────────
def test_the_default_grid_is_both_services_on_this_machine_and_the_server_can_be_added(gp, monkeypatch):
    monkeypatch.delenv("SDI_GRID_PEERS", raising=False)
    assert gp.peers() == ["http://localhost:8071", "http://localhost:8072"]
    monkeypatch.setenv("SDI_GRID_PEERS", "http://localhost:8071, http://10.0.0.5:8071/, junk")
    assert gp.peers() == ["http://localhost:8071", "http://10.0.0.5:8071"]


def test_another_services_jobs_queue_and_runners_join_this_grid_control(gp, monkeypatch):
    monkeypatch.setenv("SDI_GRID_PEERS", "http://localhost:8071,http://localhost:8072")
    snap = {"fleet": [{"runner_id": "laptop", "label": "Laptop"}], "live": [], "queue": []}
    gp.merge(snap, _opener({"http://localhost:8071": _peer_wall(gp.SERVICE_ID),   # itself
                            "http://localhost:8072": _peer_wall("other")}))
    assert [g["label"] for g in snap["grid"]] == ["localhost:8072"], "a service never counts itself"
    g = snap["grid"][0]
    assert g["ok"] and g["live"][0]["drawing_number"] == "11896-02-01-GA"
    assert "log_tail" not in g["live"][0], "only what Grid Control shows travels"
    assert g["queue"][0]["run_id"] == "p2"
    slot2 = [f for f in snap["fleet"] if f.get("runner_id") == "laptop-s2"][0]
    assert slot2["via"] == "localhost:8072" and "via localhost:8072" in slot2["label"]
    assert not any(f.get("planned") for f in snap["fleet"]), "another service's plan is its own"


def test_a_service_that_does_not_answer_is_shown_as_such(gp, monkeypatch):
    monkeypatch.setenv("SDI_GRID_PEERS", "http://10.0.0.5:8071")
    snap = {"fleet": []}
    gp.merge(snap, _opener({}))
    assert snap["grid"][0]["ok"] is False and "not answering" in snap["grid"][0]["error"]


def test_stop_reaches_only_a_service_on_the_grid(gp, monkeypatch):
    monkeypatch.setenv("SDI_GRID_PEERS", "http://localhost:8072")
    asked = []
    out = gp.stop_on("http://localhost:8072/", "p1",
                     _opener({"http://localhost:8072": {"ok": True, "was": "running"}}, asked))
    assert out["ok"] and asked[0][:2] == ("POST", "http://localhost:8072/api/estimate/p1/abandon")
    with pytest.raises(ValueError):
        gp.stop_on("http://evil.example", "p1", _opener({}))


# ── the compute check ─────────────────────────────────────────────────────────────────
def test_a_held_slot_checks_in_with_its_compute_check(monkeypatch):
    monkeypatch.syspath_prepend(str(RUNNER_DIR))
    import sdi_estimate_runner as runner
    runner.note_gate(2, False, "2.1 GB free (needs 3); CPU 40% (limit 85%)", at=1000.0)
    sent = []

    class Req:
        def post(self, url, json=None, headers=None, timeout=0):
            sent.append((url, json))

    runner.report_gate(Req(), ["http://localhost:8071", "http://localhost:8072"], {}, "rid-s2",
                       "p", "b")
    assert [u for u, _ in sent] == ["http://localhost:8071/api/estimate/runner/heartbeat",
                                    "http://localhost:8072/api/estimate/runner/heartbeat"]
    assert sent[0][1]["gate"] == {"slot": 2, "ok": False, "at": 1000.0,
                                  "measured": "2.1 GB free (needs 3); CPU 40% (limit 85%)"}
    src = (RUNNER_DIR / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    assert '"gate": dict(_GATE) or None' in src, "and every claim carries the last check"
    assert "note_gate(a.slot, _ok, _measured)" in src


@pytest.fixture
def er(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SDI_GRID_PEERS", "")
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email", "staging", "estimate_history",
             "estimate_wall", "grid_peers")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    sys.path.insert(0, str(BACKEND))
    try:
        import estimate_routes as mod
        mod._RUNS.clear()
        mod._RUNNERS.clear()
        yield mod
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        sys.path.remove(str(BACKEND))
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_the_service_keeps_the_check_and_grid_control_shows_a_held_slot(er):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(er.router)
    tc = TestClient(app)
    key = getattr(er.config, "API_KEY", "") or ""
    if key:
        tc.headers.update({"X-SDI-Key": key})
    gate = {"slot": 2, "ok": False, "measured": "2.1 GB free (needs 3)", "at": time.time()}
    r = tc.post("/api/estimate/runner/heartbeat", json={
        "runner_id": "DESKTOP-GFAAP80-90faa0001-s2", "hostname": "DESKTOP-GFAAP80",
        "process": "p2", "build": "", "gate": gate})
    assert r.status_code == 200
    rn = er._RUNNERS["DESKTOP-GFAAP80-90faa0001-s2"]
    assert rn.gate["ok"] is False and rn.busy_elsewhere is False, "holding is not busy"
    w = tc.get("/api/estimate/wall").json()
    f = [x for x in w["fleet"] if x.get("runner_id") == "DESKTOP-GFAAP80-90faa0001-s2"][0]
    assert f["gate"]["measured"] == "2.1 GB free (needs 3)"
    assert f["rag"] == "amber" and f["rag_reason"].startswith("holding")
    assert w["grid"] == [] and w["grid_service_id"]
    local = tc.get("/api/estimate/wall?local=1").json()
    assert "grid" not in local, "a peer's question is never passed on"


def test_grid_control_names_the_fleet_and_shows_the_check_and_the_rest_of_the_grid():
    assert "<b>Fleet Grid Runners</b>" in WALL and "Fleet · runners" not in WALL
    assert "Compute check, slot ${esc(g.slot)}, at <b>${when}</b>" in WALL
    assert "${gateLine(f.gate)}" in WALL
    assert "renderQueue(s.queue || [], s.grid || [])" in WALL
    assert '"/api/estimate/grid/stop", {service: b.dataset.service, run_id: id}' in WALL
    assert "running on ${esc(g.label)}" in WALL and "queued on ${esc(g.label)}" in WALL
