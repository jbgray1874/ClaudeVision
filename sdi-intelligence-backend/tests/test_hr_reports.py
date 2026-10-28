"""The reports around the sync: data issues, run history, forgotten clock-outs.

All read-only. Fictional names throughout.
"""
import datetime
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import hr_config as cfg                 # noqa: E402
import hr_history                       # noqa: E402
import hr_onsite_push as push           # noqa: E402


def rec(ident, first, surname, email="", pid="", seen="2026-10-01T08:00:00", activity="OUT"):
    return {"ID": ident, "FirstName": first, "Surname": surname, "EmailAddress": email,
            "PersonID": pid, "LastActivity": activity, "LastActivityDate": seen,
            "LastEventLocation": ""}


def staff(ident, first, surname, email=""):
    return {"id": ident, "first_name": first, "surname": surname, "email": email}


# ── data issues ───────────────────────────────────────────────────────────────

@pytest.fixture
def report():
    people = [
        rec("INV-1", "Jo", "Office", "jo@wearesdi.com"),
        # one person, two records sharing an email: a duplicate
        rec("INV-2", "Sam", "Twice", "sam@wearesdi.com", seen="2026-10-20T07:00:00"),
        rec("INV-3", "Sam", "Twice", "sam@wearesdi.com", seen="2026-03-01T07:00:00"),
        # two different people on one email: a shared identifier
        rec("INV-4", "Andy", "One", "team@wearesdi.com"),
        rec("INV-5", "Jamie", "Two", "team@wearesdi.com"),
        # nickname, matched by email
        rec("INV-6", "Liz", "Tart", "elizabeth@wearesdi.com"),
        # nobody in BrightHR
        rec("INV-7", "Long", "Gone", "", seen="2025-01-01T07:00:00"),
    ]
    employees = [
        staff("BH-1", "Jo", "Office", "jo@wearesdi.com"),
        staff("BH-2", "Sam", "Twice", "sam@wearesdi.com"),
        staff("BH-4", "Andy", "One", "team@wearesdi.com"),
        staff("BH-5", "Jamie", "Two", "team@wearesdi.com"),
        staff("BH-6", "Elizabeth", "Tart", "elizabeth@wearesdi.com"),
        staff("BH-9", "New", "Starter"),                       # not in InVentry at all
    ]
    return push.data_issues(employees, people)


def test_a_duplicate_names_the_copy_the_sync_uses(report):
    (dup,) = report["duplicates"]
    assert dup["name"] == "Sam Twice" and dup["shared"] == "email"
    used = [r["id"] for r in dup["records"] if r["used"]]
    assert used == ["INV-2"]                                    # the most recently used


def test_an_email_shared_by_two_people_is_listed(report):
    assert report["shared_identifiers"] == [{"shared": "email", "names": ["Andy One", "Jamie Two"]}]


def test_staff_missing_from_inventry_are_listed(report):
    assert [u["name"] for u in report["unmatched"]] == ["New Starter"]


def test_a_nickname_match_is_listed_for_a_glance(report):
    assert report["name_checks"] == [{"brighthr": "Elizabeth Tart", "inventry": "Liz Tart", "by": "email"}]


def test_inventry_records_with_no_employee_are_listed_with_why(report):
    only = {r["name"]: r["why"] for r in report["inventry_only"]}
    assert only["Long Gone"] == "no current BrightHR employee matches it"
    assert only["Sam Twice"] == "the unused copy of a duplicate"
    assert "Jo Office" not in only


def test_counts(report):
    assert report["brighthr_staff"] == 6 and report["inventry_records"] == 7


# ── run history ───────────────────────────────────────────────────────────────

@pytest.fixture
def snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "HR_SNAPSHOT_DIR", str(tmp_path))
    return tmp_path


def test_history_keeps_newest_first(snapshots):
    for i in range(3):
        hr_history.record({"n": i})
    assert [e["n"] for e in hr_history.recent(2)] == [2, 1]


def test_history_survives_a_bad_line(snapshots):
    hr_history.record({"n": 1})
    with open(snapshots / "hr_history.jsonl", "a", encoding="utf-8") as f:
        f.write("not json\n")
    hr_history.record({"n": 2})
    assert [e["n"] for e in hr_history.recent()] == [2, 1]


def test_history_is_trimmed_when_it_grows(snapshots, monkeypatch):
    monkeypatch.setattr(hr_history, "MAX_BYTES", 50)       # 20 lines of ~9 bytes overflow it
    monkeypatch.setattr(hr_history, "KEEP_LINES", 3)
    for i in range(20):
        hr_history.record({"n": i})
    lines = (snapshots / "hr_history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) < 10 and json.loads(lines[-1])["n"] == 19      # bounded, newest kept


def test_a_push_line_says_who_and_who_changed():
    line = hr_history.from_push({"timestamp": "t", "dry_run": False, "status": "ok",
                                 "signed_in_names": ["Zoe Test"], "signed_out_names": ["Jo Gone"],
                                 "unmatched": [{"name": "x"}], "warnings": []}, "scheduled task")
    assert line["kind"] == "update" and line["by"] == "scheduled task"
    assert line["signed_in"] == ["Zoe Test"] and line["signed_out"] == ["Jo Gone"]
    assert line["unmatched"] == 1 and line["note"] is None


def test_a_refused_push_line_carries_the_reason():
    line = hr_history.from_push({"dry_run": True, "status": "aborted",
                                 "warnings": ["On-site data is 90 minutes old"]}, "x")
    assert line["kind"] == "dry run" and "90 minutes" in line["note"]


def test_every_push_writes_a_history_line(snapshots):
    # Even one refused at the first guard: no snapshot at all is an abort the
    # history should show.
    (snapshots / "blip_latest.json").write_text(json.dumps({
        "summary": {"timestamp": "2020-01-01T00:00:00+00:00", "status": "ok"}, "on_site": []}),
        encoding="utf-8")
    push.run_push(apply=False, by="intranet portal")
    (entry,) = hr_history.recent()
    assert entry["by"] == "intranet portal" and entry["status"] == "aborted"


# ── forgotten clock-outs ──────────────────────────────────────────────────────

import forgotten_clockouts as fc        # noqa: E402

NOW = datetime.datetime(2026, 10, 28, 12, 0, tzinfo=datetime.timezone.utc)


def snap_with(*starts):
    return {"on_site": [{"first_name": f"P{i}", "surname": "X", "clocking": {"start": s}}
                        for i, s in enumerate(starts)]}


def test_only_clockings_open_past_the_limit_are_reported_oldest_first():
    rows = fc.forgotten(snap_with("2026-10-28T07:00:00Z",          # this morning
                                  "2026-08-06T07:00:00Z",          # 83 days
                                  "2026-10-27T06:00:00Z"),         # 30 hours
                        now=NOW, max_age_hours=20)
    assert [r["name"] for r in rows] == ["P1 X", "P2 X"]
    assert round(rows[0]["days"]) == 83


def test_the_email_says_what_to_do():
    rows = fc.forgotten(snap_with("2026-08-06T07:00:00Z"), now=NOW, max_age_hours=20)
    subject, page, text = fc.compose(rows, "2026-10-28T12:00:00+00:00")
    assert subject == "Forgotten BrightHR clock-outs: 1 person"
    assert "closed with the time they actually left" in text and "P0 X" in page


# ── the bulk probe reads an employee id wherever BrightHR puts it ─────────────

import probe_blip_bulk as bulk          # noqa: E402


@pytest.mark.parametrize("item, expected", [
    ({"employeeId": "E1"}, "E1"),
    ({"employee": {"id": "E2"}}, "E2"),
    ({"start": "x"}, None),
])
def test_employee_id_of(item, expected):
    assert bulk.employee_id_of(item) == expected
