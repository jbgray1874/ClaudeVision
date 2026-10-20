"""HRInventry Anywhere, the app portal's HR app: named people only, a job the app polls, and nothing else
of /api/hr reachable from outside the office.

The app is reached through the App Proxy, which cuts a request off after about
85 seconds, while a BrightHR check takes minutes - so the routes start a job and
the screen polls it. Who is in the building is personal data and an update
writes to the fire roll call, so only a signed-in person on SDI_HR_APP_USERS
gets in: not the shared key, not the office network's unsigned access.
"""
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI                     # noqa: E402
from fastapi.testclient import TestClient       # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth                                     # noqa: E402
import config                                   # noqa: E402
import hr_config as cfg                         # noqa: E402
import hr_routes                                # noqa: E402

ALLOWED = {"name": "Pat Example", "email": "pat.example@wearesdi.com", "oid": "1", "kind": "user"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "HR_SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setattr(cfg, "HR_APP_USERS", {"pat.example@wearesdi.com"})
    monkeypatch.setattr(config, "API_KEY", "machine-key")
    who = {"user": ALLOWED}
    monkeypatch.setattr(auth, "current_user", lambda request: who["user"])
    calls = []

    def blip():
        calls.append("blip")
        (tmp_path / "blip_latest.json").write_text(
            '{"on_site": [{"first_name": "Zoe", "surname": "Test", "clocking": {"start": "2026-10-20T07:00:00Z"}},'
            ' {"first_name": "Alex", "surname": "Example", "clocking": {"start": "2026-10-20T06:30:00Z"}}]}',
            encoding="utf-8")
        return {"status": "ok", "on_site": 2, "employees_checked": 190, "warnings": []}

    def push(apply=False, **kw):
        calls.append(("push", apply))
        return {"status": "ok", "signed_in_names": ["Zoe Test"], "signed_out_names": [], "warnings": []}

    monkeypatch.setattr(hr_routes.hr_blip, "run_blip", blip)
    monkeypatch.setattr(hr_routes.hr_onsite_push, "run_push", push)
    monkeypatch.setattr(hr_routes, "_app_job", {"state": "idle"})
    a = FastAPI()
    a.include_router(hr_routes.router)
    client = TestClient(a)
    client.who, client.calls = who, calls
    return client


def _finished(client):
    for _ in range(100):
        job = client.get("/api/hr/app/status").json()["job"]
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    pytest.fail("the job never finished")


def test_a_check_reads_brighthr_and_changes_nothing(app):
    r = app.post("/api/hr/app/check")
    assert r.status_code == 200 and r.json()["job"]["state"] == "running"
    job = _finished(app)
    assert job["state"] == "done" and job["by"] == "Pat Example"
    assert app.calls == ["blip"]                                   # no push
    assert [p["name"] for p in job["result"]["clocked_in"]] == ["Alex Example", "Zoe Test"]


def test_an_update_checks_then_writes_to_inventry(app):
    app.post("/api/hr/app/update")
    job = _finished(app)
    assert app.calls == ["blip", ("push", True)]                   # live, after the check
    assert job["result"]["push"]["signed_in_names"] == ["Zoe Test"]


def test_a_busy_brighthr_check_does_not_update(app, monkeypatch):
    monkeypatch.setattr(hr_routes.hr_blip, "run_blip",
                        lambda: {"status": "busy", "warnings": ["A BrightHR Blip query is already running"]})
    app.post("/api/hr/app/update")
    job = _finished(app)
    assert "already running" in job["result"]["not_updated"]
    assert ("push", True) not in app.calls


def test_one_job_at_a_time(app, monkeypatch):
    monkeypatch.setattr(hr_routes, "_app_job", {"state": "running", "kind": "update",
                                                "by": "Sam Other", "started": "2026-10-20T09:15:00+00:00"})
    r = app.post("/api/hr/app/check")
    assert r.status_code == 409 and "Sam Other" in r.json()["detail"]
    assert app.calls == []


def test_a_failure_is_reported_to_the_app(app, monkeypatch):
    def boom():
        raise RuntimeError("BrightHR token refused")
    monkeypatch.setattr(hr_routes.hr_blip, "run_blip", boom)
    app.post("/api/hr/app/check")
    job = _finished(app)
    assert job["state"] == "error" and "token refused" in job["error"]


@pytest.mark.parametrize("user, code", [
    (None, 401),                                                    # not signed in
    ({"name": "Office network (not signed in)", "email": "", "kind": "anonymous"}, 401),
    ({"name": "Service account (X-SDI-Key)", "email": "", "kind": "machine"}, 401),
    ({"name": "Not Listed", "email": "someone.else@wearesdi.com", "kind": "user"}, 403),
])
def test_only_a_signed_in_person_on_the_list_gets_in(app, user, code):
    app.who["user"] = user
    for method, path in (("get", "/api/hr/app/status"), ("post", "/api/hr/app/check"),
                         ("post", "/api/hr/app/update")):
        assert getattr(app, method)(path).status_code == code
    assert app.calls == []


def test_the_list_is_read_without_regard_to_case(app):
    app.who["user"] = dict(ALLOWED, email="Pat.Example@WeAreSDI.com")
    assert app.get("/api/hr/app/status").status_code == 200


def test_an_empty_list_lets_nobody_in(app, monkeypatch):
    monkeypatch.setattr(cfg, "HR_APP_USERS", set())
    assert app.get("/api/hr/app/status").status_code == 403


def test_from_outside_only_the_app_part_of_hr_is_reachable():
    try:
        import app as backend
    except Exception as exc:                                       # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    allowed = backend._PUBLIC_ALLOW

    def reachable(path):
        return any(path == a or path.startswith(a + "/") for a in allowed)

    assert reachable("/api/hr/app/status") and reachable("/api/hr/app/update")
    for internal in ("/api/hr/blip", "/api/hr/blip/push", "/api/hr/blip/load", "/api/hr/sync",
                     "/api/hr/inventry/check", "/api/files"):
        assert not reachable(internal), internal
