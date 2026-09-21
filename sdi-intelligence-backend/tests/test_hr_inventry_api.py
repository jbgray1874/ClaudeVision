"""
Tests for the InVentry Partner API client and the presence push.

Everything InVentry-facing is stubbed: no network, no credentials, no reachable
InVentry. The assertions encode what their documentation specifies, so if we
have misread it these are the tests that should change.
"""
import datetime
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_config as cfg  # noqa: E402
import hr_inventry_api as api  # noqa: E402
import hr_onsite_push as push  # noqa: E402


class StubResponse:
    def __init__(self, payload=None, status_code=200, headers=None, text=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(payload or {})

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class StubSession:
    """Records every call and returns queued responses."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def request(self, method, url, headers=None, params=None, data=None, timeout=None, verify=None):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "params": params, "data": data, "verify": verify})
        if not self.responses:
            return StubResponse({})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class NoWaitLimiter:
    def acquire(self):
        return 0.0


def make_client(responses=None, **kw):
    kw.setdefault("base_url", "https://inventry.sdi.local")
    kw.setdefault("api_key", "test-api-key")
    kw.setdefault("partner_secret", "test-partner-secret")
    kw.setdefault("verify", False)
    session = StubSession(responses)
    return api.InVentryAPI(session=session, limiter=NoWaitLimiter(), **kw), session


def person(inventry_id="INV-1", first="John", surname="Smith",
           email="john.smith@wearesdi.com", person_id="BH-1", activity="OUT"):
    return {"ID": inventry_id, "FirstName": first, "Surname": surname,
            "EmailAddress": email, "PersonID": person_id, "LastActivityType": activity}


# ─────────────────────────────── the client ───────────────────────────────


def test_credentials_go_in_the_headers_as_documented():
    client, session = make_client([StubResponse([person()])])
    client.get_personnel()
    headers = session.calls[0]["headers"]
    assert headers["apikey"] == "test-api-key"
    assert headers["partnersecret"] == "test-partner-secret"


def test_post_sends_form_encoded_not_json():
    """Their docs are explicit: POST bodies are x-www-form-urlencoded."""
    client, session = make_client([StubResponse({"response": "OK", "message": "signed in"})])
    client.sign_in("INV-1", when="2026-09-21T07:45:00Z")
    call = session.calls[0]
    assert call["method"] == "POST"
    assert isinstance(call["data"], dict)          # requests form-encodes a dict
    assert call["data"]["EventType"] == cfg.INVENTRY_EVENT_TYPE_IN


def test_sign_in_formats_datetime_for_sql_server():
    client, session = make_client([StubResponse({"response": "OK"})])
    client.sign_in("INV-1", when="2026-09-21T07:45:00Z")
    # SQL Server datetime, no timezone suffix.
    assert session.calls[0]["data"]["EventDateTime"] == "2026-09-21 07:45:00"


def test_empty_values_are_dropped_from_post_bodies():
    client, session = make_client([StubResponse({"response": "OK"})])
    client.sign_in("INV-1", location_id="", reason="")
    data = session.calls[0]["data"]
    assert "Reason" not in data
    assert "ID" in data


def test_add_personnel_stores_our_id_in_person_id():
    """PersonID is documented as the field for an external system's ID."""
    client, session = make_client([StubResponse({"response": "OK", "ID": "INV-9"})])
    client.add_personnel("Jane", "Doe", email="jane@wearesdi.com", person_id="BH-UUID-123")
    data = session.calls[0]["data"]
    assert data["PersonID"] == "BH-UUID-123"
    assert data["MemberOfStaff"] == "1"


def test_missing_configuration_is_reported_clearly():
    client, _ = make_client(base_url="", api_key="", partner_secret="")
    with pytest.raises(api.InVentryAPIError, match="INVENTRY_API_BASE_URL"):
        client.get_personnel()


def test_bad_credentials_do_not_retry():
    client, session = make_client([StubResponse(status_code=401, text="denied")])
    with pytest.raises(api.InVentryAPIError, match="rejected the credentials"):
        client.get_personnel()
    assert len(session.calls) == 1


def test_404_explains_that_paths_are_unconfirmed():
    client, _ = make_client([StubResponse(status_code=404, text="not found")])
    with pytest.raises(api.InVentryAPIError, match="INVENTRY_PATH"):
        client.get_personnel()


def test_rate_limit_is_retried():
    client, session = make_client([
        StubResponse(status_code=429, headers={"Retry-After": "0"}),
        StubResponse([person()]),
    ])
    assert len(client.get_personnel()) == 1
    assert len(session.calls) == 2


def test_tls_verification_off_is_surfaced_as_a_warning():
    client, _ = make_client(verify=False)
    assert any("TLS verification is OFF" in w for w in client.warnings)


def test_ca_bundle_keeps_verification_on():
    client, session = make_client([StubResponse([])], verify="/etc/ssl/inventry.pem")
    client.get_personnel()
    assert session.calls[0]["verify"] == "/etc/ssl/inventry.pem"
    assert client.warnings == []


def test_get_rate_limiter_allows_the_documented_burst():
    limiter = api.RateLimiter(calls=3, window=60.0)
    assert all(limiter.acquire() == 0.0 for _ in range(3))


@pytest.mark.parametrize("payload,expected", [
    ([{"ID": "1", "FirstName": "A"}], 1),
    ({"personnel": [{"ID": "1"}, {"ID": "2"}]}, 2),
    ({"data": [{"ID": "1"}]}, 1),
    ({"ID": "1", "FirstName": "A"}, 1),
    ({"nothing": True}, 0),
])
def test_personnel_list_is_found_in_several_response_shapes(payload, expected):
    client, _ = make_client([StubResponse(payload)])
    assert len(client.get_personnel()) == expected


def test_on_site_detection_uses_last_activity_type():
    assert api.is_on_site(person(activity="IN")) is True
    assert api.is_on_site(person(activity="in")) is True
    assert api.is_on_site(person(activity="OUT")) is False
    assert api.is_on_site(person(activity="")) is False


def test_fields_are_read_case_insensitively():
    assert api._field({"firstname": "Jo"}, "FirstName") == "Jo"
    assert api._field({"PersonID": "X"}, "personid") == "X"


# ──────────────────────────────── the push ────────────────────────────────


class FakeAPI:
    """Stands in for InVentryAPI, recording writes."""

    def __init__(self, people, fail_on=None, read_error=None):
        self.people = people
        self.signed_in = []
        self.signed_out = []
        self.warnings = []
        self.fail_on = fail_on or set()
        self.read_error = read_error

    def get_personnel(self):
        if self.read_error:
            raise api.InVentryAPIError(self.read_error)
        return self.people

    def sign_in(self, ident, when=None, **kw):
        if ident in self.fail_on:
            raise api.InVentryAPIError("simulated failure")
        self.signed_in.append(ident)

    def sign_out(self, ident, when=None, **kw):
        if ident in self.fail_on:
            raise api.InVentryAPIError("simulated failure")
        self.signed_out.append(ident)


def _iso(minutes_ago=1):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=minutes_ago)).isoformat()


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    monkeypatch.setattr(cfg, "HR_SNAPSHOT_DIR", str(snapshots))
    monkeypatch.setattr(cfg, "BLIP_MAX_STALE_MINUTES", 15)
    monkeypatch.setattr(cfg, "INVENTRY_MAX_SIGN_OUTS_PER_RUN", 25)

    def write(on_site, status="ok", age_minutes=1, query_failures=0):
        (snapshots / "blip_latest.json").write_text(json.dumps({
            "summary": {"timestamp": _iso(age_minutes), "employees_checked": 192,
                        "on_site": len(on_site), "query_failures": query_failures,
                        "status": status},
            "on_site": on_site,
        }), encoding="utf-8")

    return write


def clocked_in(bh_id="BH-1", first="John", surname="Smith",
               email="john.smith@wearesdi.com", start="2026-09-21T07:45:00Z"):
    return {"id": bh_id, "first_name": first, "surname": surname,
            "email": email, "clocking": {"start": start}}


def test_signs_in_staff_matched_on_person_id(snapshot):
    snapshot([clocked_in()])
    fake = FakeAPI([person(person_id="BH-1", activity="OUT")])

    result = push.run_push(apply=True, client=fake)

    assert fake.signed_in == ["INV-1"]
    assert result["matched_by"]["PersonID"] == 1
    assert result["status"] == "ok"


def test_falls_back_to_email_then_name(snapshot):
    snapshot([clocked_in(bh_id="BH-UNKNOWN"),
              clocked_in(bh_id="", first="Aisha", surname="Khan", email="")])
    fake = FakeAPI([
        person(inventry_id="INV-1", person_id="", email="john.smith@wearesdi.com"),
        person(inventry_id="INV-2", first="Aisha", surname="Khan", person_id="", email=""),
    ])

    result = push.run_push(apply=True, client=fake)

    assert sorted(fake.signed_in) == ["INV-1", "INV-2"]
    assert result["matched_by"]["email"] == 1
    assert result["matched_by"]["name"] == 1


def test_person_already_on_site_is_not_signed_in_again(snapshot):
    snapshot([clocked_in()])
    fake = FakeAPI([person(person_id="BH-1", activity="IN")])

    result = push.run_push(apply=True, client=fake)

    assert fake.signed_in == []
    assert result["already_on_site"] == 1


def test_unmatched_staff_are_reported_not_invented(snapshot):
    snapshot([clocked_in(bh_id="BH-NEW", first="New", surname="Starter", email="new@wearesdi.com")])
    fake = FakeAPI([person(person_id="BH-1")])

    result = push.run_push(apply=True, client=fake)

    assert fake.signed_in == []
    assert result["unmatched"][0]["name"] == "New Starter"
    assert any("PersonID" in w for w in result["warnings"])


def test_ambiguous_name_is_not_matched(snapshot):
    """Two John Smiths and no id: signing in the wrong one is worse than none."""
    snapshot([clocked_in(bh_id="", email="")])
    fake = FakeAPI([person(inventry_id="INV-1", person_id="", email=""),
                    person(inventry_id="INV-2", person_id="", email="")])

    result = push.run_push(apply=True, client=fake)

    assert fake.signed_in == []
    assert result["unmatched"][0]["reason"] == "ambiguous name"


def test_sign_out_is_disabled_by_default(snapshot):
    """InVentry cannot tell our sign-ins from terminal ones, so we do not undo them."""
    snapshot([clocked_in()])
    fake = FakeAPI([person(person_id="BH-1", activity="IN"),
                    person(inventry_id="INV-2", person_id="BH-2", activity="IN")])

    result = push.run_push(apply=True, client=fake)

    assert fake.signed_out == []
    assert result["sign_out_enabled"] is False


def test_sign_out_when_enabled_only_touches_people_we_manage(snapshot):
    snapshot([clocked_in()])
    fake = FakeAPI([
        person(person_id="BH-1", activity="IN"),                                  # still here
        person(inventry_id="INV-2", person_id="BH-2", activity="IN"),             # left
        person(inventry_id="INV-3", person_id="", activity="IN"),                 # visitor
    ])

    push.run_push(apply=True, client=fake, enable_sign_out=True)

    assert fake.signed_out == ["INV-2"]


def test_mass_sign_out_is_capped(snapshot, monkeypatch):
    monkeypatch.setattr(cfg, "INVENTRY_MAX_SIGN_OUTS_PER_RUN", 2)
    snapshot([clocked_in()])
    people = [person(person_id="BH-1", activity="IN")] + [
        person(inventry_id=f"INV-{i}", person_id=f"BH-{i}", activity="IN") for i in range(2, 8)
    ]
    fake = FakeAPI(people)

    result = push.run_push(apply=True, client=fake, enable_sign_out=True)

    assert fake.signed_out == []
    assert any("INVENTRY_MAX_SIGN_OUTS_PER_RUN" in w for w in result["warnings"])


def test_dry_run_sends_nothing(snapshot):
    snapshot([clocked_in()])
    fake = FakeAPI([person(person_id="BH-1", activity="OUT")])

    result = push.run_push(apply=False, client=fake)

    assert fake.signed_in == []
    assert result["dry_run"] is True
    assert result["signed_in"] == ["INV-1"]      # still reports the plan


def test_degraded_snapshot_is_refused(snapshot):
    snapshot([clocked_in()], status="degraded", query_failures=31)
    fake = FakeAPI([person(person_id="BH-1")])

    result = push.run_push(apply=True, client=fake)

    assert result["status"] == "aborted"
    assert fake.signed_in == []


def test_stale_snapshot_is_refused(snapshot):
    snapshot([clocked_in()], age_minutes=90)
    fake = FakeAPI([person(person_id="BH-1")])

    assert push.run_push(apply=True, client=fake)["status"] == "aborted"


def test_inventry_read_failure_aborts_without_writing(snapshot):
    snapshot([clocked_in()])
    fake = FakeAPI([], read_error="connection refused")

    result = push.run_push(apply=True, client=fake)

    assert result["status"] == "aborted"
    assert fake.signed_in == []


def test_individual_failure_is_partial_not_fatal(snapshot):
    snapshot([clocked_in(), clocked_in(bh_id="BH-2", first="Aisha", surname="Khan",
                                       email="aisha@wearesdi.com")])
    fake = FakeAPI([person(person_id="BH-1"), person(inventry_id="INV-2", person_id="BH-2")],
                   fail_on={"INV-2"})

    result = push.run_push(apply=True, client=fake)

    assert fake.signed_in == ["INV-1"]
    assert result["status"] == "partial"
    assert result["failures"]
