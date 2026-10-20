"""The portal's "Load to InVentry" button, end to end through its HTTP route.

The button POSTs to /api/hr/blip/push?apply=<HR_PUSH_APPLY>. These tests drive
that route over HTTP - the same request the portal makes - through to the push
and a fake InVentry, so the wiring between button, route and push code is
proven rather than assumed. They skip where the portal's web stack is not
installed (the scheduled task's own venv needs none of it).
"""
import datetime
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI                     # noqa: E402
from fastapi.testclient import TestClient       # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config                                   # noqa: E402
import hr_config as cfg                         # noqa: E402
import hr_inventry_api as api                   # noqa: E402
import hr_routes                                # noqa: E402

KEY = "test-portal-key"


class FakeInVentry:
    instances = []

    def __init__(self, *a, **kw):
        self.people = [
            {"ID": "INV-ALEX", "FirstName": "Alex", "Surname": "Fenn",
             "EmailAddress": "alex@wearesdi.com", "PersonID": "AD-1",
             "LastActivity": "OUT", "LastActivityDate": "2026-10-14T07:00:00",
             "LastEventLocation": ""},
            {"ID": "INV-GONE", "FirstName": "Sam", "Surname": "Holt",
             "EmailAddress": "sam@wearesdi.com", "PersonID": "",
             "LastActivity": "IN", "LastActivityDate": "2026-10-14T07:00:00",
             "LastEventLocation": cfg.INVENTRY_ACTION_LOCATION},
        ]
        self.signed_in, self.signed_out, self.warnings = [], [], []
        FakeInVentry.instances.append(self)

    def get_personnel(self):
        return self.people

    def sign_in(self, ident, when=None, **kw):
        self.signed_in.append(ident)

    def sign_out(self, ident, when=None, **kw):
        self.signed_out.append(ident)


@pytest.fixture
def portal(tmp_path, monkeypatch):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    monkeypatch.setattr(cfg, "HR_SNAPSHOT_DIR", str(snapshots))
    monkeypatch.setattr(cfg, "INVENTRY_ENABLE_SIGN_OUT", True)
    monkeypatch.setattr(config, "API_KEY", KEY)
    monkeypatch.setattr(api, "InVentryAPI", FakeInVentry)
    FakeInVentry.instances.clear()

    now = datetime.datetime.now(datetime.timezone.utc)
    (snapshots / "blip_latest.json").write_text(json.dumps({
        "summary": {"timestamp": now.isoformat(), "employees_checked": 2,
                    "on_site": 1, "query_failures": 0, "status": "ok"},
        "on_site": [{"id": "BH-1", "first_name": "Alex", "surname": "Fenn",
                     "email": "alex@wearesdi.com",
                     "clocking": {"start": (now - datetime.timedelta(hours=1)).isoformat()}}],
        "query_failed": [],
    }), encoding="utf-8")

    app = FastAPI()
    app.include_router(hr_routes.router)
    return TestClient(app)


def test_the_button_in_dry_run_plans_but_writes_nothing(portal):
    """HR_PUSH_APPLY = false - what the portal ships with."""
    r = portal.post("/api/hr/blip/push?apply=false", headers={"X-SDI-Key": KEY})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["signed_in"] == ["INV-ALEX"]          # planned
    assert body["signed_out"] == ["INV-GONE"]         # planned
    fake = FakeInVentry.instances[-1]
    assert fake.signed_in == [] and fake.signed_out == []   # nothing sent


def test_the_button_live_signs_in_and_out_through_the_new_code(portal):
    """HR_PUSH_APPLY = true. INV-GONE has no PersonID: the 28 Sep code could
    never sign it out. Seeing it signed out here proves the button reaches the
    new push code, not the old."""
    r = portal.post("/api/hr/blip/push?apply=true", headers={"X-SDI-Key": KEY})
    assert r.status_code == 200
    fake = FakeInVentry.instances[-1]
    assert fake.signed_in == ["INV-ALEX"]
    assert fake.signed_out == ["INV-GONE"]


def test_the_button_is_refused_without_a_key_or_a_sign_in(portal):
    r = portal.post("/api/hr/blip/push?apply=true")
    assert r.status_code == 401
    assert FakeInVentry.instances == []               # never reached InVentry
