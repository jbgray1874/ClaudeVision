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
import hr_blip_inventry as source_loader  # noqa: E402
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
           email="john.smith@wearesdi.com", person_id="BH-1", activity="OUT",
           location=""):
    """Shaped like a real GetPersonnel record - LastActivity, not
    LastActivityType, which is what the field-information PDF wrongly implied."""
    return {"ID": inventry_id, "FirstName": first, "Surname": surname,
            "EmailAddress": email, "PersonID": person_id,
            "LastActivity": activity, "LastActivityDate": "2026-09-21T07:45:00.000",
            "LastEventLocation": location, "MemberOfStaff": True}


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
    assert call["url"].endswith("/PartnerAPI/AddPersonnelAction")
    assert isinstance(call["data"], dict)          # requests form-encodes a dict
    assert call["data"]["PersonnelID"] == "INV-1"
    assert call["data"]["ActionType"] == cfg.INVENTRY_EVENT_TYPE_IN


def test_sign_in_uses_the_documented_datetime_format():
    client, session = make_client([StubResponse({"response": "OK"})])
    client.sign_in("INV-1", when="2026-09-21T07:45:00Z")
    # Their own examples: "T" separator, no timezone.
    assert session.calls[0]["data"]["ActionDateTime"] == "2026-09-21T07:45:00"


def test_empty_values_are_dropped_from_post_bodies():
    """ActionDateTime and ActionLocation are optional; blanks are not sent."""
    client, session = make_client([StubResponse({"response": "OK"})])
    client.sign_in("INV-1", location="")
    data = session.calls[0]["data"]
    assert "ActionDateTime" not in data
    assert "ActionLocation" not in data
    assert data["PersonnelID"] == "INV-1"


def test_sign_out_marks_our_own_writes_with_the_location():
    """Our marker in ActionLocation is what makes safe sign-out possible."""
    client, session = make_client([StubResponse({"response": "OK"})])
    client.sign_out("INV-1", when="2026-09-21T17:00:00Z")
    data = session.calls[0]["data"]
    assert data["ActionType"] == cfg.INVENTRY_EVENT_TYPE_OUT
    assert data["ActionLocation"] == cfg.INVENTRY_ACTION_LOCATION


def test_personnel_request_hits_the_real_endpoint():
    client, session = make_client([StubResponse([person()])])
    client.get_personnel()
    assert session.calls[0]["url"].endswith("/PartnerAPI/GetPersonnel/")
    assert session.calls[0]["params"] == {"IncludeNonStaff": "false"}


def test_check_auth_uses_the_cheap_endpoint():
    client, session = make_client([StubResponse({"response": "OK"})])
    client.check_auth()
    assert session.calls[0]["url"].endswith("/PartnerAPI/CheckAuth")


def test_latest_actions_passes_the_collection_id():
    client, session = make_client([StubResponse([])])
    client.get_latest_actions(last_collection_id=42)
    assert session.calls[0]["params"] == {"LastCollectionId": 42}


def test_add_personnel_stores_our_id_in_person_id():
    """PersonID is documented as the field for an external system's ID."""
    client, session = make_client([StubResponse({"response": "OK", "ID": "INV-9"})])
    client.add_personnel("Jane", "Doe", email="jane@wearesdi.com", person_id="BH-UUID-123")
    data = session.calls[0]["data"]
    assert session.calls[0]["url"].endswith("/PartnerAPI/AddPersonnel")
    assert data["PersonID"] == "BH-UUID-123"
    assert data["MemberOfStaff"] == "True"


def test_missing_configuration_is_reported_clearly():
    client, _ = make_client(base_url="", api_key="", partner_secret="")
    with pytest.raises(api.InVentryAPIError, match="INVENTRY_API_BASE_URL"):
        client.get_personnel()


def test_bad_credentials_do_not_retry():
    client, session = make_client([StubResponse(status_code=401, text="denied")])
    with pytest.raises(api.InVentryAPIError, match="rejected the credentials"):
        client.get_personnel()
    assert len(session.calls) == 1


def test_404_names_the_path_setting_to_check():
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
    ([{"ID": "1", "FirstName": "A"}], 1),          # the real shape: a bare list
    ({"personnel": [{"ID": "1"}, {"ID": "2"}]}, 2),
    ({"data": [{"ID": "1"}]}, 1),
    ({"ID": "1", "FirstName": "A"}, 1),
    ({"nothing": True}, 0),
])
def test_personnel_list_is_found_in_several_response_shapes(payload, expected):
    client, _ = make_client([StubResponse(payload)])
    assert len(client.get_personnel()) == expected


def test_on_site_detection_uses_the_live_last_activity_field():
    assert api.is_on_site(person(activity="IN")) is True
    assert api.is_on_site(person(activity="in")) is True
    assert api.is_on_site(person(activity="OUT")) is False
    assert api.is_on_site(person(activity="")) is False
    # Real records carry null for anyone with no history.
    assert api.is_on_site({"ID": "X", "LastActivity": None}) is False


def test_our_own_sign_ins_are_recognisable_by_location():
    mine = person(activity="IN", location=cfg.INVENTRY_ACTION_LOCATION)
    reception = person(activity="IN", location="CONSOLE")
    assert api.signed_in_by_us(mine) is True
    assert api.signed_in_by_us(reception) is False
    assert api.signed_in_by_us(person(activity="IN", location="1")) is False


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
               email="john.smith@wearesdi.com", start=None):
    """start defaults to an hour ago, so the forgotten-clock-out guard keeps it."""
    if start is None:
        start = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(hours=1)).isoformat().replace("+00:00", "Z")
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
    """Sign-ins go live first; sign-out is an explicit decision."""
    snapshot([clocked_in()])
    fake = FakeAPI([person(person_id="BH-1", activity="IN"),
                    person(inventry_id="INV-2", person_id="BH-2", activity="IN")])

    result = push.run_push(apply=True, client=fake)

    assert fake.signed_out == []
    assert result["sign_out_enabled"] is False


def test_sign_out_when_enabled_only_touches_people_we_manage(snapshot):
    ours = cfg.INVENTRY_ACTION_LOCATION
    snapshot([clocked_in()])
    fake = FakeAPI([
        person(person_id="BH-1", activity="IN", location=ours),                    # still here
        person(inventry_id="INV-2", person_id="BH-2", activity="IN", location=ours),  # left
        person(inventry_id="INV-3", person_id="", activity="IN", location=ours),   # visitor
    ])

    push.run_push(apply=True, client=fake, enable_sign_out=True)

    assert fake.signed_out == ["INV-2"]


def test_a_reception_sign_in_is_never_undone(snapshot):
    """LastEventLocation says the sign-in came from the console, not from us."""
    snapshot([clocked_in()])
    fake = FakeAPI([
        person(person_id="BH-1", activity="IN", location=cfg.INVENTRY_ACTION_LOCATION),
        person(inventry_id="INV-2", person_id="BH-2", activity="IN", location="CONSOLE"),
    ])

    result = push.run_push(apply=True, client=fake, enable_sign_out=True)

    assert fake.signed_out == []
    assert result["skipped_not_ours"] == 1
    assert any("reception" in w for w in result["warnings"])


def test_mass_sign_out_is_capped(snapshot, monkeypatch):
    monkeypatch.setattr(cfg, "INVENTRY_MAX_SIGN_OUTS_PER_RUN", 2)
    ours = cfg.INVENTRY_ACTION_LOCATION
    snapshot([clocked_in()])
    people = [person(person_id="BH-1", activity="IN", location=ours)] + [
        person(inventry_id=f"INV-{i}", person_id=f"BH-{i}", activity="IN", location=ours)
        for i in range(2, 8)
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


# ─────────────────────── forgotten clock-outs ───────────────────────


def test_forgotten_clockouts_are_excluded_from_presence(snapshot):
    """Real data, 28 Sep 2026: 15 of 104 'on site' had clockings days old.

    BrightHR reports any open clocking, so someone who forgot to clock out
    stays on site indefinitely. They are not in the building and must never
    reach the evacuation list.
    """
    snapshot([
        clocked_in(bh_id="BH-1", start="2026-09-28T07:45:00Z"),                     # today
        clocked_in(bh_id="BH-2", first="Joshua", surname="Briggs",
                   email="joshua@wearesdi.com", start="2026-07-28T09:23:49Z"),      # 61 days
    ])
    fake = FakeAPI([person(person_id="BH-1"), person(inventry_id="INV-2", person_id="BH-2")])

    result = push.run_push(apply=True, client=fake,
                           now=datetime.datetime(2026, 9, 28, 9, 1, tzinfo=datetime.timezone.utc))

    assert fake.signed_in == ["INV-1"]
    assert result["brighthr_on_site"] == 1
    assert [f["name"] for f in result["forgotten_clockouts"]] == ["Joshua Briggs"]
    assert any("forgot to clock out" in w for w in result["warnings"])


def test_a_long_shift_is_not_mistaken_for_a_forgotten_clock_out():
    """The earliest real shifts start 04:33; still on site at 21:00 is 16.5h."""
    records = [{"first_name": "Early", "surname": "Start",
                "signed_in": "2026-09-28T04:33:00Z", "email": "", "brighthr_id": ""}]
    now = datetime.datetime(2026, 9, 28, 21, 0, tzinfo=datetime.timezone.utc)

    present, forgotten = source_loader.split_stale_clockins(records, max_age_hours=20, now=now)

    assert len(present) == 1 and forgotten == []


def test_yesterdays_clocking_is_caught():
    """04:33 yesterday, checked at 09:00 today = 28h - clearly forgotten."""
    records = [{"first_name": "Left", "surname": "Yesterday",
                "signed_in": "2026-09-27T04:33:00Z", "email": ""}]
    now = datetime.datetime(2026, 9, 28, 9, 0, tzinfo=datetime.timezone.utc)

    present, forgotten = source_loader.split_stale_clockins(records, max_age_hours=20, now=now)

    assert present == [] and len(forgotten) == 1
    assert forgotten[0]["clockin_age_hours"] == 28.4


def test_records_without_a_clock_in_time_are_kept():
    """Omitting someone who is present is the more dangerous mistake."""
    records = [{"first_name": "No", "surname": "Time", "signed_in": "", "email": ""}]
    present, forgotten = source_loader.split_stale_clockins(records, max_age_hours=20)
    assert len(present) == 1 and forgotten == []


def test_the_check_can_be_disabled():
    records = [{"first_name": "Old", "surname": "Clocking",
                "signed_in": "2026-07-28T09:23:49Z", "email": ""}]
    present, forgotten = source_loader.split_stale_clockins(records, max_age_hours=0)
    assert len(present) == 1 and forgotten == []
