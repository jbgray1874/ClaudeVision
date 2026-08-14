"""Tests for the sync engine, focused on the handover's edge cases.

The safety rails matter most: InVentry drives the fire evacuation list, so a
BrightHR outage or a partial response must never sign the building out.
"""

from datetime import datetime, timezone
from typing import List

import pytest

from brighthr_client import STATE_ON_BREAK, STATE_ON_SITE, BrightHRError, StaffPresence
from config import Config, InVentryConfig, LoggingConfig, SyncConfig, BrightHRConfig
from employee_map import EmployeeMap, EmployeeMapError
from inventry_client import InVentryClient, InVentryError, OnSiteRecord
from sync import EXIT_ERROR, EXIT_OK, EXIT_PARTIAL, SyncEngine

NOW = datetime(2026, 5, 29, 9, 0, tzinfo=timezone.utc)


class FakeBrightHR:
    def __init__(self, presence, absent=None, error=None):
        self.presence = presence
        self.absent = absent or set()
        self.error = error

    def get_clocked_in_staff(self, treat_break_as_on_site=True):
        if self.error:
            raise self.error
        if treat_break_as_on_site:
            return list(self.presence)
        return [p for p in self.presence if p.state != STATE_ON_BREAK]

    def get_absent_employee_ids(self, on_date=None):
        return set(self.absent)


class FakeInVentry(InVentryClient):
    def __init__(self, records=None, fail_on=None, read_error=None):
        self.records = {r.staff_id: r for r in (records or [])}
        self.signed_in: List[str] = []
        self.signed_out: List[str] = []
        self.fail_on = fail_on or set()
        self.read_error = read_error

    def get_on_site(self):
        if self.read_error:
            raise self.read_error
        return list(self.records.values())

    def sign_in(self, staff_id, staff_name, when, location):
        if staff_id in self.fail_on:
            raise InVentryError(f"simulated failure for {staff_id}")
        self.signed_in.append(staff_id)
        self.records[staff_id] = OnSiteRecord(staff_id, staff_name, when, location, "BRIGHTHR_SYNC")

    def sign_out(self, staff_id, when):
        if staff_id in self.fail_on:
            raise InVentryError(f"simulated failure for {staff_id}")
        self.signed_out.append(staff_id)
        self.records.pop(staff_id, None)


def presence(employee_id, name="", state=STATE_ON_SITE):
    return StaffPresence(
        employee_id=employee_id, employee_name=name, state=state, since=NOW, location="Shepshed"
    )


def on_site(staff_id, name="", source="BRIGHTHR_SYNC"):
    return OnSiteRecord(staff_id=staff_id, staff_name=name, sign_in_time=NOW, location="Shepshed", source=source)


def make_config(**sync_overrides):
    return Config(
        brighthr=BrightHRConfig(api_key="test"),
        inventry=InVentryConfig(driver="dryrun", source_tag="BRIGHTHR_SYNC"),
        sync=SyncConfig(**sync_overrides),
        logging=LoggingConfig(),
    )


def make_engine(brighthr, inventry, mapping=None, **sync_overrides):
    employee_map = EmployeeMap(
        brighthr_to_inventry=mapping if mapping is not None else {"EMP001": "SDI-001", "EMP002": "SDI-002"}
    )
    return SyncEngine(make_config(**sync_overrides), brighthr, inventry, employee_map)


# ------------------------------------------------------------ happy path


def test_signs_in_staff_clocked_in_on_brighthr():
    inventry = FakeInVentry()
    engine = make_engine(FakeBrightHR([presence("EMP001", "John Smith")]), inventry)

    result = engine.run(apply_changes=True)

    assert inventry.signed_in == ["SDI-001"]
    assert result.exit_code == EXIT_OK


def test_signs_out_staff_no_longer_clocked_in():
    inventry = FakeInVentry([on_site("SDI-001"), on_site("SDI-002")])
    engine = make_engine(FakeBrightHR([presence("EMP001")]), inventry)

    engine.run(apply_changes=True)

    assert inventry.signed_out == ["SDI-002"]
    assert inventry.signed_in == []


def test_already_matching_state_produces_no_writes():
    inventry = FakeInVentry([on_site("SDI-001")])
    engine = make_engine(FakeBrightHR([presence("EMP001")]), inventry)

    result = engine.run(apply_changes=True)

    assert (inventry.signed_in, inventry.signed_out) == ([], [])
    assert result.plan.is_empty


def test_staff_on_break_stay_signed_in():
    """Handover: on a break they are still in the building, so still on the roll."""
    inventry = FakeInVentry([on_site("SDI-002")])
    engine = make_engine(
        FakeBrightHR([presence("EMP002", state=STATE_ON_BREAK)]), inventry, treat_break_as_on_site=True
    )

    engine.run(apply_changes=True)

    assert inventry.signed_out == []


# ------------------------------------------------------------- edge cases


def test_unmapped_brighthr_employee_is_skipped_not_guessed():
    inventry = FakeInVentry()
    engine = make_engine(FakeBrightHR([presence("EMP999", "New Starter")]), inventry)

    result = engine.run(apply_changes=True)

    assert inventry.signed_in == []
    assert any("employee_map" in item.reason for item in result.plan.skipped)


def test_approved_absence_blocks_sign_in():
    inventry = FakeInVentry()
    engine = make_engine(FakeBrightHR([presence("EMP001")], absent={"EMP001"}), inventry)

    result = engine.run(apply_changes=True)

    assert inventry.signed_in == []
    assert any("absence" in item.reason for item in result.plan.skipped)


def test_absence_lookup_failure_does_not_abort_the_sync():
    class FlakyAbsences(FakeBrightHR):
        def get_absent_employee_ids(self, on_date=None):
            raise BrightHRError("absences endpoint down")

    inventry = FakeInVentry()
    engine = make_engine(FlakyAbsences([presence("EMP001")]), inventry)

    engine.run(apply_changes=True)

    assert inventry.signed_in == ["SDI-001"]


def test_manual_inventry_sign_in_is_never_auto_signed_out():
    inventry = FakeInVentry([on_site("SDI-002", source="RECEPTION_TERMINAL")])
    engine = make_engine(FakeBrightHR([]), inventry, allow_full_sign_out=True)

    result = engine.run(apply_changes=True)

    assert inventry.signed_out == []
    assert any("manual" in item.reason for item in result.plan.skipped)


def test_unknown_source_is_treated_as_manual_when_no_source_column():
    """With no source column InVentry cannot tell us who wrote the row, so leave it."""
    inventry = FakeInVentry([on_site("SDI-002", source="")])
    engine = make_engine(FakeBrightHR([]), inventry, allow_full_sign_out=True)

    engine.run(apply_changes=True)

    assert inventry.signed_out == []


def test_visitor_unknown_to_the_map_is_left_alone():
    inventry = FakeInVentry([on_site("VISITOR-42", "Contractor")])
    engine = make_engine(FakeBrightHR([presence("EMP001")]), inventry)

    result = engine.run(apply_changes=True)

    assert inventry.signed_out == []
    assert any("not in employee_map" in item.reason for item in result.plan.skipped)


def test_sign_out_unmapped_can_be_enabled_explicitly():
    inventry = FakeInVentry([on_site("VISITOR-42")])
    engine = make_engine(
        FakeBrightHR([presence("EMP001")]), inventry, sign_out_unmapped=True, max_sign_out_ratio=1.0
    )

    engine.run(apply_changes=True)

    assert inventry.signed_out == ["VISITOR-42"]


def test_individual_write_failure_is_reported_not_fatal():
    inventry = FakeInVentry(fail_on={"SDI-002"})
    engine = make_engine(FakeBrightHR([presence("EMP001"), presence("EMP002")]), inventry)

    result = engine.run(apply_changes=True)

    assert inventry.signed_in == ["SDI-001"]
    assert result.exit_code == EXIT_PARTIAL
    assert result.failures


# ----------------------------------------------------------- safety rails


def test_brighthr_outage_makes_no_changes_at_all():
    """The critical rule: an API failure must not empty the fire roll call."""
    inventry = FakeInVentry([on_site("SDI-001"), on_site("SDI-002")])
    engine = make_engine(FakeBrightHR([], error=BrightHRError("connection refused")), inventry)

    result = engine.run(apply_changes=True)

    assert (inventry.signed_in, inventry.signed_out) == ([], [])
    assert result.aborted_reason
    assert result.exit_code == EXIT_ERROR


def test_inventry_read_failure_makes_no_changes():
    inventry = FakeInVentry(read_error=InVentryError("database unreachable"))
    engine = make_engine(FakeBrightHR([presence("EMP001")]), inventry)

    result = engine.run(apply_changes=True)

    assert inventry.signed_in == []
    assert result.exit_code == EXIT_ERROR


def test_empty_brighthr_response_does_not_sign_everyone_out():
    inventry = FakeInVentry([on_site("SDI-001"), on_site("SDI-002")])
    engine = make_engine(FakeBrightHR([]), inventry)

    result = engine.run(apply_changes=True)

    assert inventry.signed_out == []
    assert result.plan.sign_out_blocked_reason
    assert len(result.plan.suppressed_sign_outs) == 2
    assert result.exit_code == EXIT_PARTIAL


def test_empty_brighthr_response_can_be_allowed_deliberately():
    inventry = FakeInVentry([on_site("SDI-001")])
    engine = make_engine(FakeBrightHR([]), inventry, allow_full_sign_out=True, max_sign_out_ratio=1.0)

    engine.run(apply_changes=True)

    assert inventry.signed_out == ["SDI-001"]


def test_mass_sign_out_above_ratio_is_suppressed():
    records = [on_site(f"SDI-{i:03d}") for i in range(1, 11)]
    mapping = {f"EMP{i:03d}": f"SDI-{i:03d}" for i in range(1, 11)}
    inventry = FakeInVentry(records)
    # Only one of ten still clocked in - a plausible partial-response failure.
    engine = make_engine(
        FakeBrightHR([presence("EMP001")]), inventry, mapping=mapping, max_sign_out_ratio=0.5
    )

    result = engine.run(apply_changes=True)

    assert inventry.signed_out == []
    assert "InVentry's on-site register" in result.plan.sign_out_blocked_reason


def test_sign_out_count_cap_is_enforced():
    records = [on_site(f"SDI-{i:03d}") for i in range(1, 11)]
    mapping = {f"EMP{i:03d}": f"SDI-{i:03d}" for i in range(1, 11)}
    inventry = FakeInVentry(records)
    engine = make_engine(
        FakeBrightHR([presence(f"EMP{i:03d}") for i in range(1, 8)]),
        inventry,
        mapping=mapping,
        max_sign_outs_per_run=2,
        max_sign_out_ratio=1.0,
    )

    result = engine.run(apply_changes=True)

    assert inventry.signed_out == []
    assert "SYNC_MAX_SIGN_OUTS_PER_RUN" in result.plan.sign_out_blocked_reason


def test_normal_sized_sign_out_passes_the_rails():
    records = [on_site(f"SDI-{i:03d}") for i in range(1, 11)]
    mapping = {f"EMP{i:03d}": f"SDI-{i:03d}" for i in range(1, 11)}
    inventry = FakeInVentry(records)
    engine = make_engine(
        FakeBrightHR([presence(f"EMP{i:03d}") for i in range(1, 10)]), inventry, mapping=mapping
    )

    result = engine.run(apply_changes=True)

    assert inventry.signed_out == ["SDI-010"]
    assert result.plan.sign_out_blocked_reason is None


# ---------------------------------------------------------------- dry run


def test_dry_run_writes_nothing():
    # Two on site in InVentry so signing one out stays inside the ratio rail.
    inventry = FakeInVentry([on_site("SDI-001"), on_site("SDI-002")])
    engine = make_engine(
        FakeBrightHR([presence("EMP001"), presence("EMP003")]),
        inventry,
        mapping={"EMP001": "SDI-001", "EMP002": "SDI-002", "EMP003": "SDI-003"},
    )

    result = engine.run(apply_changes=False)

    assert (inventry.signed_in, inventry.signed_out) == ([], [])
    assert result.dry_run
    # The plan still reports what would have happened.
    assert result.signed_in == ["SDI-003"]
    assert result.signed_out == ["SDI-002"]


# ----------------------------------------------------------- employee map


def test_employee_map_accepts_both_entry_shapes():
    employee_map = EmployeeMap.from_dict(
        {"mappings": {"EMP001": "SDI-001", "EMP002": {"inventry_staff_id": "SDI-002", "name": "Aisha Khan"}}}
    )
    assert employee_map.to_inventry("EMP001") == "SDI-001"
    assert employee_map.to_brighthr("SDI-002") == "EMP002"
    assert employee_map.name_for("EMP002") == "Aisha Khan"
    assert employee_map.to_inventry("EMP999") is None


def test_employee_map_rejects_duplicate_inventry_ids():
    with pytest.raises(EmployeeMapError):
        EmployeeMap.from_dict({"mappings": {"EMP001": "SDI-001", "EMP002": "SDI-001"}})


def test_employee_map_identity_fallback_is_opt_in():
    employee_map = EmployeeMap.from_dict({"fallback_to_brighthr_id": True, "mappings": {}})
    assert employee_map.to_inventry("EMP123") == "EMP123"
