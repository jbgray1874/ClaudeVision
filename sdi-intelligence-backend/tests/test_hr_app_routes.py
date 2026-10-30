"""HRInventry Anywhere, the app portal's HR app: named people only, a job the app polls, and nothing else
of /api/hr reachable from outside the office.

The app is reached through the App Proxy, which cuts a request off after about
85 seconds, while a BrightHR check takes minutes - so the routes start a job and
the screen polls it. Who is in the building is personal data and an update
writes to the fire roll call, so only a signed-in person on SDI_HR_APP_USERS
gets in: not the shared key, not the office network's unsigned access.
"""
import datetime
import json
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
        calls.append(("by", kw.get("by")))
        return {"status": "ok", "signed_in_names": ["Zoe Test"], "signed_out_names": [], "warnings": []}

    monkeypatch.setattr(hr_routes.hr_blip, "run_blip", blip)
    monkeypatch.setattr(hr_routes.hr_onsite_push, "run_push", push)
    monkeypatch.setattr(hr_routes, "_app_state", {"running": None, "last": {}})
    a = FastAPI()
    a.include_router(hr_routes.router)
    client = TestClient(a)
    client.who, client.calls = who, calls
    return client


def _finished(client, kind):
    for _ in range(100):
        status = client.get("/api/hr/app/status").json()
        if status["running"] is None:
            return status["last"][kind]
        time.sleep(0.02)
    pytest.fail("the job never finished")


def test_a_check_reads_brighthr_and_changes_nothing(app):
    r = app.post("/api/hr/app/check")
    assert r.status_code == 200 and r.json()["running"]["kind"] == "check"
    job = _finished(app, "check")
    assert job["state"] == "done" and job["by"] == "Pat Example"
    assert app.calls == ["blip"]                                   # no push
    assert [p["name"] for p in job["result"]["clocked_in"]] == ["Alex Example", "Zoe Test"]


def test_an_update_checks_then_writes_to_inventry(app):
    app.post("/api/hr/app/update")
    job = _finished(app, "update")
    assert app.calls[:2] == ["blip", ("push", True)]               # live, after the check
    assert app.calls[2] == ("by", "HRInventry Anywhere (pat.example@wearesdi.com)")
    assert job["result"]["push"]["signed_in_names"] == ["Zoe Test"]


def test_a_busy_brighthr_check_does_not_update(app, monkeypatch):
    monkeypatch.setattr(hr_routes.hr_blip, "run_blip",
                        lambda: {"status": "busy", "warnings": ["A BrightHR Blip query is already running"]})
    app.post("/api/hr/app/update")
    job = _finished(app, "update")
    assert "already running" in job["result"]["not_updated"]
    assert ("push", True) not in app.calls


def test_one_job_at_a_time(app, monkeypatch):
    monkeypatch.setattr(hr_routes, "_app_state", {"running": {
        "state": "running", "kind": "update", "by": "Sam Other",
        "started": "2026-10-20T09:15:00+00:00"}, "last": {}})
    r = app.post("/api/hr/app/check")
    assert r.status_code == 409 and "Sam Other" in r.json()["detail"]
    assert app.calls == []


def test_a_failure_is_reported_to_the_app(app, monkeypatch):
    def boom():
        raise RuntimeError("BrightHR token refused")
    monkeypatch.setattr(hr_routes.hr_blip, "run_blip", boom)
    app.post("/api/hr/app/check")
    job = _finished(app, "check")
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
                         ("post", "/api/hr/app/update"), ("post", "/api/hr/app/issues"),
                         ("get", "/api/hr/app/rollcall"), ("post", "/api/hr/app/rollcall/new"), ("get", "/api/hr/app/history")):
        assert getattr(app, method)(path).status_code == code
    assert app.calls == []


def test_each_kind_keeps_its_own_last_result(app):
    app.post("/api/hr/app/check")
    _finished(app, "check")
    app.post("/api/hr/app/update")
    _finished(app, "update")
    last = app.get("/api/hr/app/status").json()["last"]
    assert set(last) == {"check", "update"}


class FakeInVentry:
    def __init__(self, *a, **kw):
        pass

    def get_personnel(self):
        return [
            {"ID": "INV-1", "FirstName": "Zoe", "Surname": "Test", "EmailAddress": "zoe@wearesdi.com",
             "LastActivity": "IN", "LastActivityDate": "2026-10-28T07:01:00", "LastEventLocation": "BRIGHTHR SYNC"},
            {"ID": "INV-2", "FirstName": "Ann", "Surname": "Desk", "EmailAddress": "",
             "LastActivity": "IN", "LastActivityDate": "2026-10-28T08:15:00", "LastEventLocation": "CONSOLE"},
            {"ID": "INV-3", "FirstName": "Gone", "Surname": "Home", "EmailAddress": "",
             "LastActivity": "OUT", "LastActivityDate": "2026-10-27T17:00:00", "LastEventLocation": "CONSOLE"},
        ]


def _snapshot(tmp_path, *people):
    (tmp_path / "blip_latest.json").write_text(json.dumps({
        "summary": {"timestamp": "2026-10-28T07:30:00+00:00"},
        "on_site": [{"first_name": f, "surname": l, "clocking": {"start": t}} for f, l, t in people]}),
        encoding="utf-8")


def test_the_roll_call_merges_inventry_and_brighthr(app, monkeypatch, tmp_path):
    import hr_inventry_api as api
    monkeypatch.setattr(cfg, "INVENTRY_ACTION_LOCATION", "BRIGHTHR SYNC")
    monkeypatch.setattr(api, "InVentryAPI", FakeInVentry)
    now = datetime.datetime.now(datetime.timezone.utc)
    _snapshot(tmp_path, ("Zoe", "Test", (now - datetime.timedelta(hours=2)).isoformat()),
              ("New", "Starter", (now - datetime.timedelta(hours=1)).isoformat()),      # not on InVentry
              ("Sam", "Forgot", (now - datetime.timedelta(days=80)).isoformat()))       # left out
    r = app.get("/api/hr/app/rollcall").json()
    by_name = {p["name"]: p for p in r["people"]}
    assert set(by_name) == {"Ann Desk", "New Starter", "Zoe Test"}
    assert "inventry" in by_name["Zoe Test"] and "brighthr" in by_name["Zoe Test"]  # one entry, both
    assert "inventry" not in by_name["New Starter"]
    assert by_name["Ann Desk"]["inventry"]["by"] == "reception"
    assert r["forgotten_left_out"] == 1 and r["inventry_problem"] is None


def test_the_roll_call_still_works_when_inventry_is_down(app, monkeypatch, tmp_path):
    import hr_inventry_api as api

    class Down:
        def __init__(self, *a, **kw):
            pass

        def get_personnel(self):
            raise api.InVentryAPIError("InVentry rejected the credentials (401)")
    monkeypatch.setattr(api, "InVentryAPI", Down)
    _snapshot(tmp_path, ("Zoe", "Test", datetime.datetime.now(datetime.timezone.utc).isoformat()))
    r = app.get("/api/hr/app/rollcall")
    assert r.status_code == 200
    assert [p["name"] for p in r.json()["people"]] == ["Zoe Test"]
    assert "401" in r.json()["inventry_problem"] and "BrightHR only" in r.json()["inventry_problem"]


def test_a_tick_is_shared_and_a_new_roll_call_clears_it(app, monkeypatch, tmp_path):
    import hr_inventry_api as api
    monkeypatch.setattr(api, "InVentryAPI", FakeInVentry)
    key = next(p["key"] for p in app.get("/api/hr/app/rollcall").json()["people"] if p["name"] == "Ann Desk")

    r = app.post("/api/hr/app/rollcall/tick", json={"key": key, "ticked": True})
    assert r.json()["ticked"]["by"] == "Pat Example"
    # Another marshal's phone sees it.
    seen = {p["name"]: p["ticked"] for p in app.get("/api/hr/app/rollcall").json()["people"]}
    assert seen["Ann Desk"]["by"] == "Pat Example" and seen["Zoe Test"] is None

    after = app.post("/api/hr/app/rollcall/new").json()
    assert after["accounted"] == 0 and after["started_by"] == "Pat Example"


def test_a_tick_needs_a_person(app):
    assert app.post("/api/hr/app/rollcall/tick", json={"ticked": True}).status_code == 400


def test_the_data_check_reports_without_changing_anything(app, monkeypatch):
    import hr_inventry_api as api
    monkeypatch.setattr(api, "InVentryAPI", FakeInVentry)
    monkeypatch.setattr(hr_routes.hr_blip, "_get_token", lambda: "t")
    monkeypatch.setattr(hr_routes.hr_blip, "_current_staff", lambda token: [
        {"id": "BH-1", "first_name": "Zoe", "surname": "Test", "email": "zoe@wearesdi.com"},
        {"id": "BH-2", "first_name": "New", "surname": "Starter", "email": ""}])
    app.post("/api/hr/app/issues")
    job = _finished(app, "issues")
    issues = job["result"]["issues"]
    assert [u["name"] for u in issues["unmatched"]] == ["New Starter"]
    assert app.calls == []                                            # no check, no push


def test_history_lists_checks_and_who_ran_them(app):
    app.post("/api/hr/app/check")
    _finished(app, "check")
    entries = app.get("/api/hr/app/history").json()["entries"]
    assert entries[0]["kind"] == "check"
    assert entries[0]["by"] == "HRInventry Anywhere (pat.example@wearesdi.com)"
    assert entries[0]["staff_checked"] == 190


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
