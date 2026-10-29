"""Simon's lists grouped by BrightHR manager: who reports to whom, end to end.

BrightHR's field name was not in any documentation to hand, so the usual
spellings are tried and HR_MANAGER_FIELD can name the real one. Fictional
people throughout.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_brighthr as bh                # noqa: E402
import hr_config as cfg                 # noqa: E402
import hr_rollcall                      # noqa: E402


@pytest.mark.parametrize("raw, expected", [
    ({"lineManager": {"id": "BH-7", "name": {"givenName": "Max", "familyName": "Boss"}}},
     ("BH-7", "Max Boss", "lineManager")),
    ({"manager": {"firstName": "Max", "lastName": "Boss"}}, ("", "Max Boss", "manager")),
    ({"managerId": "BH-7"}, ("BH-7", "", "managerId")),
    ({"approvers": [{}, {"id": "BH-8", "displayName": "Ann Approver"}]},
     ("BH-8", "Ann Approver", "approvers")),
    ({"reportsTo": "Max Boss"}, ("", "Max Boss", "reportsTo")),
    ({"email": "x@wearesdi.com"}, ("", "", "")),
])
def test_the_usual_shapes_of_a_manager_field_are_read(raw, expected, monkeypatch):
    monkeypatch.setattr(cfg, "HR_MANAGER_FIELD", "")
    got = bh.manager_of(raw)
    assert (got["manager_id"], got["manager_name"], got["manager_field"]) == expected


def test_the_field_can_be_named_once_the_probe_has_shown_it(monkeypatch):
    raw = {"manager": {"id": "BH-1"}, "holidayApprover": {"id": "BH-2"}}
    monkeypatch.setattr(cfg, "HR_MANAGER_FIELD", "holidayApprover.id")
    assert bh.manager_of(raw)["manager_id"] == "BH-2"


def test_a_manager_given_only_by_id_gets_their_name_from_the_staff_list(monkeypatch):
    monkeypatch.setattr(cfg, "HR_MANAGER_FIELD", "")
    staff = bh.name_managers([bh.normalise_employee(r) for r in (
        {"id": "BH-7", "firstName": "Max", "lastName": "Boss"},
        {"id": "BH-1", "firstName": "Jo", "lastName": "Office", "lineManagerId": "BH-7"},
        {"id": "BH-2", "firstName": "Sam", "lastName": "Floor", "lineManagerId": "BH-404"},
    )])
    by_id = {e["id"]: e["manager_name"] for e in staff}
    assert by_id == {"BH-7": "", "BH-1": "Max Boss", "BH-2": ""}


def test_a_check_carries_each_persons_manager_into_the_snapshot(tmp_path, monkeypatch):
    import hr_blip
    monkeypatch.setattr(cfg, "HR_SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setattr(cfg, "HR_OUTPUT_DIR", "")
    monkeypatch.setattr(cfg, "HR_MANAGER_FIELD", "")
    monkeypatch.setattr(hr_blip, "_get_token", lambda: "t")
    monkeypatch.setattr(hr_blip, "STAFF_LIST_PAUSE", 0)
    monkeypatch.setattr(bh, "fetch_employees", lambda token: [
        {"id": "BH-7", "firstName": "Max", "lastName": "Boss"},
        {"id": "BH-1", "firstName": "Jo", "lastName": "Office", "lineManager": {"id": "BH-7"}},
        {"id": "BH-2", "firstName": "Sam", "lastName": "Floor", "lineManager": {"id": "BH-7"}},
    ])
    monkeypatch.setattr(hr_blip, "_query_one", lambda token, eid, from_dt, throttle=None:
                        ([{"start": "2026-10-29T07:00:00Z"}], True) if eid == "BH-1" else ([], True))
    summary = hr_blip.run_blip()
    snap = json.loads((tmp_path / "blip_latest.json").read_text(encoding="utf-8"))
    assert [(p["first_name"], p["manager"]) for p in snap["on_site"]] == [("Jo", "Max Boss")]
    assert snap["managers"] == {"jo office": "Max Boss", "sam floor": "Max Boss"}
    assert summary["staff_with_manager"] == 2 and summary["manager_fields"] == ["lineManager"]


def test_the_roll_call_groups_reception_sign_ins_by_manager_too():
    """Someone InVentry has on site who is not clocked in on BrightHR still
    belongs to a manager: the snapshot's staff list says which."""
    snap = {"on_site": [{"first_name": "Jo", "surname": "Office", "manager": "Max Boss",
                         "clocking": {"start": "2026-10-29T07:00:00Z"}}],
            "managers": {"sam floor": "Ann Approver"}}
    import datetime
    people, _ = hr_rollcall.build([{"name": "Sam Floor", "since": "", "by": "reception"},
                                   {"name": "Vic Visitor", "since": "", "by": "reception"}], snap,
                                  now=datetime.datetime(2026, 10, 29, 9, tzinfo=datetime.timezone.utc),
                                  max_age_hours=20)
    assert {p["name"]: p["manager"] for p in people} == {
        "Jo Office": "Max Boss", "Sam Floor": "Ann Approver", "Vic Visitor": ""}


def test_the_page_has_the_button_and_remembers_the_choice():
    page = (Path(__file__).resolve().parent.parent / "appportal" / "hr-inventry.html").read_text(encoding="utf-8")
    assert "data-group" in page and "Group by manager" in page
    assert "No manager in BrightHR" in page
    assert "localStorage.setItem('hrGroupByManager'" in page
