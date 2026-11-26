"""The InVentry-only check: who is signed in on InVentry but not clocked in on BrightHR."""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import hr_config as cfg        # noqa: E402
import hr_inventry_only as chk  # noqa: E402

NOW = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.timezone.utc)
TODAY = "2026-11-26T07:40:00.000"


def rec(ident, first, surname, email, on_site=True, location="CONSOLE", since=TODAY):
    return {"ID": ident, "FirstName": first, "Surname": surname, "EmailAddress": email,
            "PersonID": "", "LastActivity": "IN" if on_site else "OUT",
            "LastActivityDate": since, "LastEventLocation": location, "MemberOfStaff": True}


def clocking(bh, first, surname, email, start="2026-11-26T07:30:00Z"):
    return {"id": bh, "first_name": first, "surname": surname, "email": email,
            "clocking": {"start": start}}


def snapshot(*on_site):
    return {"summary": {"timestamp": (NOW - datetime.timedelta(minutes=2)).isoformat(),
                        "status": "ok"}, "on_site": list(on_site)}


def staff(*people):
    return [{"id": bh, "first_name": f, "surname": s, "email": e} for bh, f, s, e in people]


PEOPLE = [
    rec("1", "Ann", "Able", "ann@example.com", location=cfg.INVENTRY_ACTION_LOCATION),
    rec("2", "Ben", "Bell", "ben@example.com"),
    rec("3", "Cal", "Cole", "cal@example.com"),
    rec("4", "Dee", "Dunn", "dee@example.com"),
    rec("5", "Eve", "Earl", "eve@example.com"),
    rec("6", "Fay", "Ford", "fay@example.com", since="2026-11-20T08:02:00.000"),
    rec("7", "Gus", "Gray", "gus@example.com", on_site=False),
]
SNAP = snapshot(clocking("A", "Ann", "Able", "ann@example.com"),
                clocking("B", "Ben", "Bell", "ben@example.com"),
                clocking("C", "Cal", "Cole", "cal@example.com", start="2026-11-20T07:00:00Z"))
STAFF = staff(("A", "Ann", "Able", "ann@example.com"), ("B", "Ben", "Bell", "ben@example.com"),
              ("C", "Cal", "Cole", "cal@example.com"), ("D", "Dee", "Dunn", "dee@example.com"),
              ("F", "Fay", "Ford", "fay@example.com"), ("G", "Gus", "Gray", "gus@example.com"))


def test_lists_only_people_on_inventry_who_are_not_clocked_in():
    rows = {r["name"]: r for r in chk.find(PEOPLE, SNAP, STAFF, now=NOW)["rows"]}

    assert set(rows) == {"Cal Cole", "Dee Dunn", "Eve Earl", "Fay Ford"}
    assert rows["Cal Cole"]["brighthr"] == chk.FORGOTTEN
    assert rows["Dee Dunn"]["brighthr"] == chk.NOT_CLOCKED_IN
    assert rows["Eve Earl"]["brighthr"] == chk.NOT_EMPLOYED
    assert rows["Fay Ford"]["earlier_day"] is True
    assert rows["Dee Dunn"]["earlier_day"] is False
    assert all(r["how"] == chk.CONSOLE for r in rows.values())


def test_a_nickname_on_inventry_still_counts_as_clocked_in():
    """Matched by email, as the sync matches them: not listed."""
    people = [rec("1", "Rob", "Lane", "robert.lane@example.com")]
    snap = snapshot(clocking("R", "Robert", "Lane", "robert.lane@example.com"))

    assert chk.find(people, snap, [], now=NOW)["rows"] == []


def test_the_syncs_own_sign_in_is_marked_and_listed_last():
    people = [rec("8", "Zoe", "Zinn", "zoe@example.com", location=cfg.INVENTRY_ACTION_LOCATION),
              rec("9", "Abe", "Ash", "abe@example.com")]

    rows = chk.find(people, snapshot(), [], now=NOW)["rows"]

    assert [(r["name"], r["how"]) for r in rows] == [("Abe Ash", chk.CONSOLE), ("Zoe Zinn", chk.SYNC)]


def test_without_the_staff_list_it_says_so_rather_than_guess():
    rows = chk.find(PEOPLE, SNAP, None, now=NOW)["rows"]

    assert {r["brighthr"] for r in rows if r["name"] != "Cal Cole"} == {chk.UNKNOWN}


def test_the_report_counts_and_names_them():
    text = chk.report(chk.find(PEOPLE, SNAP, STAFF, now=NOW))

    assert "Signed in on InVentry, not clocked in on BrightHR: 4" in text
    assert "Dee Dunn" in text and "Eve Earl" in text
    assert "1 signed in on an earlier day and never signed out" in text


def test_nobody_is_said_plainly():
    assert "Nobody." in chk.report(chk.find([], snapshot(), [], now=NOW))
