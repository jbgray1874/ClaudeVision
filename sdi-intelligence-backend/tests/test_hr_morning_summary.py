"""The weekday morning summary for HR, emailed at 08:45 with a link to the app.

Simon and Charlotte asked for one email each morning: who is in, what needs
looking at, and the roll calls since the last one. A check changes nothing;
--update changes InVentry exactly as the app's button does. Fictional names.
"""
import datetime
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tools"))

import hr_config as cfg                 # noqa: E402
import hr_history                       # noqa: E402
import hr_rollcall                      # noqa: E402
import hr_morning_summary as ms         # noqa: E402

NOW = datetime.datetime(2026, 11, 4, 8, 45, tzinfo=datetime.timezone.utc)


def _ago(**kw):
    return (NOW - datetime.timedelta(**kw)).isoformat()


@pytest.fixture
def server(tmp_path, monkeypatch):
    """BrightHR, InVentry and the mailbox, all pretend."""
    import hr_blip
    import hr_onsite_push
    import estimate_email
    monkeypatch.setattr(cfg, "HR_SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setattr(cfg, "HR_ROLLCALL_DIR", str(tmp_path / "Roll calls"))
    monkeypatch.setattr(cfg, "HR_MORNING_TO", {"pat.example@wearesdi.com", "alex.example@wearesdi.com"})
    monkeypatch.setattr(cfg, "HR_APP_URL", "https://sdi.example/app/hr-inventry.html")
    monkeypatch.setattr(hr_rollcall, "_schedule_export", lambda rid: None)
    monkeypatch.setattr(ms.os, "chdir", lambda path: None)
    monkeypatch.delenv("SDI_REVIEW_FROM", raising=False)
    s = {"calls": [], "sent": [], "send_ok": True,
         "inventry": [{"name": "Zoe Test", "since": _ago(hours=2), "by": "sync"},
                      {"name": "Ann Desk", "since": _ago(hours=1), "by": "reception"},
                      {"name": "Old Leaver", "since": _ago(days=1), "by": "sync"}],
         "blip": [{"status": "ok", "on_site": 3, "employees_checked": 190, "warnings": [],
                   "timestamp": NOW.isoformat()}]}

    def run_blip():
        s["calls"].append("blip")
        result = s["blip"].pop(0) if len(s["blip"]) > 1 else s["blip"][0]
        if result["status"] == "busy":
            return result                                    # another check holds BrightHR
        (tmp_path / "blip_latest.json").write_text(json.dumps({
            "summary": {"timestamp": NOW.isoformat(), "status": "ok", "on_site": 3,
                        "employees_checked": 190, "warnings": []},
            "on_site": [{"first_name": "Zoe", "surname": "Test", "clocking": {"start": _ago(hours=2)}},
                        {"first_name": "New", "surname": "Starter", "clocking": {"start": _ago(hours=1)}},
                        {"first_name": "Sam", "surname": "Forgot", "clocking": {"start": _ago(days=80)}}]}),
            encoding="utf-8")
        return result

    def run_push(apply=False, **kw):
        s["calls"].append(("push", apply, kw.get("by")))
        s["inventry"] = [p for p in s["inventry"] if p["name"] != "Old Leaver"]
        return {"status": "ok", "signed_in_names": [], "signed_out_names": ["Old Leaver"], "warnings": []}

    def send(to, subject, page, text):
        s["sent"].append((to, subject, text))
        return {"sent": s["send_ok"], "reason": "mailbox refused"}

    monkeypatch.setattr(hr_blip, "run_blip", run_blip)
    monkeypatch.setattr(hr_onsite_push, "run_push", run_push)
    monkeypatch.setattr(hr_rollcall, "inventry_on_site", lambda: (s["inventry"], None))
    monkeypatch.setattr(estimate_email, "send", send)
    return s


def test_a_check_changes_nothing_and_says_who_to_look_at(server):
    d = ms.gather(now=NOW)
    assert server["calls"] == ["blip"]                               # no update
    assert d["not_on_inventry"] == ["New Starter"]
    assert d["not_clocked_in"] == ["Old Leaver"]
    assert [r["name"] for r in d["forgotten"]] == ["Sam Forgot"]
    assert d["at_reception"] == 1 and d["on_inventry"] == 3
    # It is in the app's History, by name, like a press of the button.
    assert hr_history.recent(1)[0]["by"] == ms.BY and hr_history.recent(1)[0]["kind"] == "check"


def test_with_update_inventry_is_updated_first_and_read_after(server):
    d = ms.gather(update=True, now=NOW)
    assert ("push", True, ms.BY) in server["calls"]
    assert d["not_clocked_in"] == []                                 # signed out by the update
    subject, page, text = ms.compose(d, ms.app_url())
    assert "InVentry updated: 0 signed in, 1 signed out" in text


def test_the_email_has_the_figures_the_names_and_the_link(server):
    subject, page, text = ms.compose(ms.gather(now=NOW), ms.app_url())
    assert subject == "HR morning summary: 3 clocked in, 4 to check"
    for said in ("New Starter", "Old Leaver", "Sam Forgot (80 days)", "press Update InVentry",
                 "https://sdi.example/app/hr-inventry.html#roll", "1 signed in at reception"):
        assert said in text, said
    assert "https://sdi.example/app/hr-inventry.html#roll" in page


def test_a_quiet_morning_says_so(server):
    server["inventry"] = [{"name": "Zoe Test", "since": _ago(hours=2), "by": "sync"},
                          {"name": "New Starter", "since": _ago(hours=1), "by": "sync"}]
    hr_history.record({"time": _ago(hours=1), "kind": "update", "by": "Pat Example", "status": "ok"})
    d = ms.gather(now=NOW)
    d["forgotten"] = []
    subject, _, text = ms.compose(d, ms.app_url())
    assert subject.endswith("nothing to check") and "Nothing needs attention." in text


def test_inventry_not_answering_is_said_not_read_as_everyone_missing(server, monkeypatch):
    monkeypatch.setattr(hr_rollcall, "inventry_on_site",
                        lambda: (None, "InVentry did not answer (401), so this list is from BrightHR only."))
    d = ms.gather(now=NOW)
    assert d["not_on_inventry"] == [] and d["on_inventry"] is None
    assert "InVentry did not answer" in [h for h, _, _ in ms.attention(d)]


def test_the_roll_calls_since_the_last_summary_with_who_was_absent(server, monkeypatch):
    people = [{"key": "ann desk#0", "name": "Ann Desk"}, {"key": "zoe test#0", "name": "Zoe Test"}]
    monkeypatch.setattr(hr_rollcall, "_now", lambda: NOW - datetime.timedelta(days=3))
    hr_rollcall.start_new("Pat Example")
    hr_rollcall.tick("ann desk#0", True, "Pat Example", people=people)      # before the last summary
    ms._mark_sent(NOW - datetime.timedelta(days=1))
    monkeypatch.setattr(hr_rollcall, "_now", lambda: NOW - datetime.timedelta(hours=18))
    hr_rollcall.start_new("Pat Example")
    hr_rollcall.tick("zoe test#0", True, "Pat Example", people=people)
    d = ms.gather(now=NOW)
    assert len(d["roll_calls"]) == 1
    assert d["roll_calls"][0]["absent"] == ["Ann Desk"]
    _, _, text = ms.compose(d, ms.app_url())
    assert "1 present, 1 absent, started by Pat Example" in text and "Absent: Ann Desk" in text


def test_it_is_sent_to_the_list_and_remembered_only_once_sent(server):
    assert ms.main(["--send"], today=datetime.date(2026, 11, 4)) == 0
    (to, subject, _), = server["sent"]
    assert to == ["alex.example@wearesdi.com", "pat.example@wearesdi.com"]
    assert ms.last_sent() is not None


def test_a_failed_send_is_not_remembered_so_the_roll_calls_come_again(server):
    server["send_ok"] = False
    assert ms.main(["--send"], today=datetime.date(2026, 11, 4)) == 2
    assert ms.last_sent() is None


def test_a_test_goes_to_one_person_and_is_not_the_last_summary(server):
    assert ms.main(["--send", "--to", "pat.example@wearesdi.com"], today=datetime.date(2026, 11, 4)) == 0
    (to, _, _), = server["sent"]
    assert to == ["pat.example@wearesdi.com"] and ms.last_sent() is None


def test_nobody_to_send_to_sends_nothing(server, monkeypatch):
    monkeypatch.setattr(cfg, "HR_MORNING_TO", set())
    assert ms.main(["--send"], today=datetime.date(2026, 11, 4)) == 2
    assert server["sent"] == []


def test_not_at_the_weekend(server):
    assert ms.main(["--send", "--weekdays-only"], today=datetime.date(2026, 11, 7)) == 0   # a Saturday
    assert server["calls"] == [] and server["sent"] == []


BUSY = {"status": "busy", "on_site": 0, "employees_checked": 0,
        "warnings": ["A BrightHR Blip query is already running"], "timestamp": NOW.isoformat()}


def test_a_check_already_running_is_waited_for(server):
    server["blip"] = [BUSY, dict(server["blip"][0])]
    waited = []
    d = ms.gather(now=NOW, sleep=waited.append)
    assert waited == [ms.BUSY_WAIT_SECONDS] and d["status"] == "ok" and d["clocked_in"] == 3


def test_busy_throughout_reports_the_last_check_not_zero(server, tmp_path):
    """4 November: BrightHR stayed busy and the summary said "0 of 0 staff
    checked". The figures come from the last check that finished, and say so."""
    (tmp_path / "blip_latest.json").write_text(json.dumps({
        "summary": {"timestamp": _ago(minutes=40), "status": "ok", "on_site": 2, "employees_checked": 190,
                    "warnings": []},
        "on_site": [{"first_name": "Zoe", "surname": "Test", "clocking": {"start": _ago(hours=2)}},
                    {"first_name": "New", "surname": "Starter", "clocking": {"start": _ago(hours=1)}}]}),
        encoding="utf-8")
    server["blip"] = [BUSY]
    waited = []
    d = ms.gather(now=NOW, sleep=waited.append)
    assert (d["clocked_in"], d["staff_checked"]) == (2, 190)
    assert len(waited) == ms.BUSY_RETRIES
    subject, _, text = ms.compose(d, ms.app_url())
    assert subject.startswith("HR morning summary: 2 clocked in")
    assert text.count("already running") == 0 and "busy with another check" in text


def test_a_check_from_the_last_few_minutes_is_used_as_it_is(server, tmp_path):
    (tmp_path / "blip_latest.json").write_text(json.dumps({
        "summary": {"timestamp": _ago(minutes=3), "status": "ok", "on_site": 1, "employees_checked": 190},
        "on_site": [{"first_name": "Zoe", "surname": "Test", "clocking": {"start": _ago(hours=2)}}]}),
        encoding="utf-8")
    d = ms.gather(now=NOW)
    assert server["calls"] == [] and d["clocked_in"] == 1


def test_a_long_list_gives_twenty_names_and_points_to_the_app(server):
    d = ms.gather(now=NOW)
    d["not_on_inventry"] = [f"Person {i:02d}" for i in range(89)]
    _, _, text = ms.compose(d, ms.app_url())
    assert "Person 19" in text and "Person 20" not in text and "and 69 more: see the app" in text
    assert "Missing from InVentry's fire list: 89 people" in text
    assert "the one reception would use in a fire" in text and "The Roll call in the app does" in text


def test_one_day_is_a_day():
    d = {"not_on_inventry": [], "not_clocked_in": [], "notes": [], "push": {"status": "ok"},
         "forgotten": [{"name": "Sam Forgot", "days": 1.2}], "time": NOW.isoformat()}
    assert ms.attention(d)[0][2] == ["Sam Forgot (1 day)"]


def test_it_is_sent_from_the_sdi_intelligence_mailbox_through_microsoft(server, monkeypatch):
    """Office 365 refused the server's SMTP login (530 5.7.57) on 4 November.
    The AM CRM morning review sends through Graph from sdi-intelligence@; so
    does this."""
    import morning_review
    graph = []
    monkeypatch.setenv("SDI_REVIEW_FROM", "sdi-intelligence@wearesdi.com")
    monkeypatch.setattr(morning_review, "send_via_graph",
                        lambda to, subject, page: graph.append(to) or {"sent": True})
    assert ms.main(["--send"], today=datetime.date(2026, 11, 4)) == 0
    assert graph == [["alex.example@wearesdi.com", "pat.example@wearesdi.com"]] and server["sent"] == []


def test_the_task_runs_at_0845_on_weekdays_as_the_service():
    ps1 = (BACKEND / "deploy" / "install_hr_morning_task.ps1").read_bytes()
    assert ps1.isascii() and b"\r\n" in ps1
    text = ps1.decode()
    assert '"08:45"' in text and "Monday, Tuesday, Wednesday, Thursday, Friday" in text
    assert '"SYSTEM"' in text and "--weekdays-only" in text and "^SDI_HR_MORNING_TO=" in text
    assert "--update" in text and "[switch]$Update" in text                  # off unless asked


def test_the_link_opens_the_roll_call_tab():
    page = (BACKEND / "appportal" / "hr-inventry.html").read_text(encoding="utf-8")
    assert "location.hash.slice(1)" in page and '.tab[data-v="' in page
