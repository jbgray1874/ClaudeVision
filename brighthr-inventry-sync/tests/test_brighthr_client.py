"""Tests for BrightHR parsing, field mapping and presence derivation.

No network access: responses are stubbed so the whole BrightHR side can be
verified before the API key or the real JSON sample exist.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from brighthr_client import (
    STATE_OFF_SITE,
    STATE_ON_BREAK,
    STATE_ON_SITE,
    AttendanceEvent,
    BrightHRClient,
    BrightHRError,
    FieldMap,
    derive_presence,
    parse_timestamp,
    unwrap_collection,
)
from config import BrightHRConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def field_map():
    return FieldMap.load(PROJECT_ROOT / "field_map.json")


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class StubResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if isinstance(self._payload, (dict, list)):
            return self._payload
        raise ValueError("not json")


class StubSession:
    """Returns queued responses and records the requests made."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.requests.append({"url": url, "params": params, "headers": headers})
        if not self.responses:
            raise AssertionError(f"Unexpected extra request to {url}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_client(responses, **overrides):
    config = BrightHRConfig(
        api_key="test-key",
        field_map_path=PROJECT_ROOT / "field_map.json",
        retry_backoff_seconds=0.0,
        **overrides,
    )
    return BrightHRClient(config, session=StubSession(responses))


# --------------------------------------------------------------- field map


def test_snake_case_fixture_maps_cleanly(field_map):
    records = unwrap_collection(load_fixture("brighthr_events_snake.json"), field_map.events_root)
    assert len(records) == 5
    event = AttendanceEvent.from_record(records[0], field_map)
    assert event.employee_id == "EMP001"
    assert event.employee_name == "John Smith"
    assert event.event_type == "clock_in"
    assert event.location == "Shepshed"


def test_camel_case_and_nested_fixture_maps_without_code_change(field_map):
    """The handover flags field names as unknown - a different shape must still parse."""
    records = unwrap_collection(load_fixture("brighthr_events_camel.json"), field_map.events_root)
    assert len(records) == 2
    event = AttendanceEvent.from_record(records[0], field_map)
    assert event.employee_id == "EMP001"
    assert event.employee_name == "John Smith"
    assert event.event_type == "clock_in"  # "ClockIn" normalises
    assert event.timestamp == datetime(2026, 5, 29, 6, 45, tzinfo=timezone.utc)


def test_bare_list_payload_is_accepted(field_map):
    payload = [{"employee_id": "EMP001", "event_type": "clock_in"}]
    assert len(unwrap_collection(payload, field_map.events_root)) == 1


def test_event_type_classification_prefers_longest_match(field_map):
    assert field_map.classify_event_type("break_start") == "break_start"
    assert field_map.classify_event_type("BREAK-END") == "break_end"
    assert field_map.classify_event_type("clock out") == "clock_out"
    assert field_map.classify_event_type("teleported_in") is None


def test_record_without_employee_id_is_skipped_not_fatal(field_map):
    assert AttendanceEvent.from_record({"event_type": "clock_in"}, field_map) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-05-29T07:45:00Z", datetime(2026, 5, 29, 7, 45, tzinfo=timezone.utc)),
        ("2026-05-29T08:45:00+01:00", datetime(2026, 5, 29, 7, 45, tzinfo=timezone.utc)),
        ("2026-05-29 07:45:00", datetime(2026, 5, 29, 7, 45, tzinfo=timezone.utc)),
        (1780040700, datetime.fromtimestamp(1780040700, tz=timezone.utc)),
        (1780040700000, datetime.fromtimestamp(1780040700, tz=timezone.utc)),
        ("not a date", None),
        (None, None),
    ],
)
def test_parse_timestamp(raw, expected):
    assert parse_timestamp(raw) == expected


# ------------------------------------------------------------- presence


def build_events(field_map, name="brighthr_events_snake.json"):
    records = unwrap_collection(load_fixture(name), field_map.events_root)
    return [AttendanceEvent.from_record(r, field_map) for r in records]


def test_presence_uses_latest_event_per_employee(field_map):
    presence = derive_presence(build_events(field_map))
    assert presence["EMP001"].state == STATE_ON_SITE
    assert presence["EMP002"].state == STATE_ON_BREAK
    assert presence["EMP003"].state == STATE_OFF_SITE  # clocked out at 14:30


def test_break_handling_is_configurable(field_map):
    """Handover leaves this as a decision for James/Matt, so both ways must work."""
    events = build_events(field_map)
    assert derive_presence(events, treat_break_as_on_site=True)["EMP002"].is_on_site is True
    assert derive_presence(events, treat_break_as_on_site=False)["EMP002"].is_on_site is False


def test_unknown_event_type_is_treated_as_present(field_map):
    event = AttendanceEvent(employee_id="EMP009", raw_event_type="wandered_in", event_type=None)
    assert derive_presence([event])["EMP009"].is_on_site is True


def test_events_without_timestamps_fall_back_to_arrival_order(field_map):
    events = [
        AttendanceEvent(employee_id="EMP001", event_type="clock_in"),
        AttendanceEvent(employee_id="EMP001", event_type="clock_out"),
    ]
    assert derive_presence(events)["EMP001"].state == STATE_OFF_SITE


# --------------------------------------------------------------- client


def test_get_clocked_in_staff_uses_status_filter():
    client = make_client([StubResponse(load_fixture("brighthr_events_snake.json"))])
    on_site = client.get_clocked_in_staff()
    assert client.session.requests[0]["params"] == {"status": "clocked_in"}
    assert {p.employee_id for p in on_site} == {"EMP001", "EMP002"}


def test_falls_back_to_event_replay_when_status_filter_rejected():
    client = make_client(
        [
            StubResponse({"error": "unsupported"}, status_code=400),
            StubResponse(load_fixture("brighthr_events_snake.json")),
        ]
    )
    on_site = client.get_clocked_in_staff()
    assert len(client.session.requests) == 2
    assert "from" in client.session.requests[1]["params"]
    assert {p.employee_id for p in on_site} == {"EMP001", "EMP002"}


def test_server_errors_are_retried_then_raise():
    client = make_client([StubResponse({}, status_code=500)] * 3, max_retries=3)
    with pytest.raises(BrightHRError):
        client.get_clocked_in_staff()
    assert len(client.session.requests) == 3


def test_rate_limit_is_retried_and_honours_retry_after():
    client = make_client(
        [
            StubResponse({}, status_code=429, headers={"Retry-After": "0"}),
            StubResponse(load_fixture("brighthr_events_snake.json")),
        ]
    )
    assert len(client.get_clocked_in_staff()) == 2


def test_bad_api_key_fails_immediately_without_retrying():
    client = make_client([StubResponse({}, status_code=401)])
    with pytest.raises(BrightHRError, match="rejected the API key"):
        client.get_clocked_in_staff()
    assert len(client.session.requests) == 1


def test_absences_only_count_approved_and_covering_dates():
    payload = {
        "absences": [
            {"employee_id": "EMP001", "status": "approved", "start_date": "2026-05-28", "end_date": "2026-05-30"},
            {"employee_id": "EMP002", "status": "pending", "start_date": "2026-05-29", "end_date": "2026-05-29"},
            {"employee_id": "EMP003", "status": "approved", "start_date": "2026-06-10", "end_date": "2026-06-12"},
        ]
    }
    client = make_client([StubResponse(payload)])
    absent = client.get_absent_employee_ids(on_date=datetime(2026, 5, 29).date())
    assert absent == {"EMP001"}


def test_employees_are_normalised_from_name_parts():
    payload = {"employees": [{"id": "EMP007", "firstName": "Ada", "lastName": "Lovelace", "workEmail": "ada@sdi.com"}]}
    client = make_client([StubResponse(payload)])
    employees = client.get_employees()
    assert employees[0]["employee_id"] == "EMP007"
    assert employees[0]["employee_name"] == "Ada Lovelace"
    assert employees[0]["email"] == "ada@sdi.com"
