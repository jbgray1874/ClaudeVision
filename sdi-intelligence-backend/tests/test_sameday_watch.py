"""SameDay watch: SameDay is checked every 15 minutes on the server, and James is emailed when something is wrong.

5 November 2026 (James): "this is for sales people and directors who have a very high standard ... can we get alerting
for this?" These run offline: SameDay, SDI Intelligence, OpenAI and Anthropic are stand-ins, and nothing is sent.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
import sameday_watch as W  # noqa: E402

KEY = "sk-proj-" + "x" * 40                      # stand-in key - must never appear in anything said
GOOD_VERSION = {"version": "2026-11-05 09:00 repo claude/inspiring-planck-8juriz aacf0ca",
                "can_read": {"W": True, "S": True, "K": True},
                "past_work": {"jobs": 9312, "estimates": True, "pictures": False, "why": "no picture index (all_img_index.npz)"}}


class Fake:
    """Answers as a healthy server would, unless told otherwise."""

    def __init__(self, **change):
        self.answers = {
            "5020/api/version": (200, dict(GOOD_VERSION)),
            "8071/sameday/api/version": (200, dict(GOOD_VERSION)),
            "msappproxy.net/sameday/": (302, ""),
            "api.openai.com": (200, {"data": []}),
            "api.anthropic.com": (200, {"data": []}),
            "5020/api/status": (200, {"spent_today": 1.25, "cap": 10.0}),
        }
        self.answers.update(change)
        self.asked = []

    def get(self, url, headers=None, timeout=15, redirects=True):
        self.asked.append((url, dict(headers or {})))
        for part, (code, body) in self.answers.items():
            if part in url:
                return code, body, ""
        return 0, "no answer", ""


def run(fake=None, services=None, env=None, log="", free=28.4):
    fake = fake or Fake()
    states = {"SDISameDay": "RUNNING", "SDIIntelligence": "RUNNING", "WAPCSvc": "absent"} | (services or {})
    return W.check(get=fake.get, service=lambda n: states.get(n, ""),
                   env={"OPENAI_API_KEY": KEY, "ANTHROPIC_API_KEY": "sk-ant-" + "y" * 40} if env is None else env,
                   log_text=log, disk=lambda path: free)


def keys(problems):
    return {p["key"]: p["level"] for p in problems}


class WhatItChecksTests(unittest.TestCase):
    def test_a_healthy_sameday_has_nothing_to_say(self):
        problems, facts = run()
        self.assertEqual(problems, [])
        self.assertEqual(facts["past_jobs"], 9312)
        self.assertIn("1.25 of 10.00", facts["spend"])

    def test_sameday_down(self):
        self.assertEqual(keys(run(Fake(**{"5020/api/version": (0, "refused")}))[0]).get("answer"), "down")
        self.assertEqual(keys(run(services={"SDISameDay": "STOPPED"})[0]).get("service"), "down")

    def test_code_that_didnt_come_from_the_repository(self):
        k = dict(GOOD_VERSION, version="2026-11-04 16:37-a5aa4104")       # K:'s stamp - UPDATE_SAME_DAY.bat
        p = run(Fake(**{"5020/api/version": (200, k)}))[0]
        self.assertEqual(keys(p).get("code"), "warn")
        self.assertIn("Update-SameDay.ps1", p[0]["fix"])

    def test_past_jobs_and_drives(self):
        none = dict(GOOD_VERSION, past_work={"jobs": 0, "why": "no job index (projects.db)"})
        self.assertEqual(keys(run(Fake(**{"5020/api/version": (200, none)}))[0]).get("past_jobs"), "down")
        nod = dict(GOOD_VERSION, can_read={"W": False, "S": True, "K": True})
        p = run(Fake(**{"5020/api/version": (200, nod)}))[0]
        self.assertEqual(keys(p).get("drives"), "down")
        self.assertIn("W:", p[0]["title"])

    def test_the_phone_address(self):
        self.assertEqual(keys(run(Fake(**{"8071/sameday/api/version": (503, "SameDay isn't answering")}))[0]).get("phone"),
                         "down")
        self.assertEqual(keys(run(services={"SDIIntelligence": "STOPPED"})[0]).get("intelligence"), "down")
        self.assertEqual(keys(run(services={"WAPCSvc": "STOPPED"})[0]).get("connector"), "down")
        self.assertEqual(keys(run(Fake(**{"msappproxy.net/sameday/": (0, "x")}))[0]).get("public"), "warn")
        self.assertEqual(run(services={"WAPCSvc": "absent"})[0], [])       # a connector elsewhere is not a problem

    def test_the_phone_check_goes_the_way_a_phone_does(self):
        """5 Nov: the first run said the phone address was down - SDI Intelligence asks 127.0.0.1 to sign in."""
        os.environ["SDI_API_KEY"] = "machine-key-not-real"
        try:
            fake = Fake()
            self.assertEqual(run(fake)[0], [])
            sent = [h for url, h in fake.asked if "8071/sameday" in url]
            self.assertEqual(sent, [{"X-SDI-Key": "machine-key-not-real"}])
            said = json.dumps(run(Fake(**{"8071/sameday/api/version": (401, {"error": "Signed out"})})))
            self.assertIn('"phone"', said)                      # with the key, a refusal IS a problem
            self.assertNotIn("machine-key-not-real", said)
        finally:
            os.environ.pop("SDI_API_KEY", None)
        problems, facts = run(Fake(**{"8071/sameday/api/version": (401, {"error": "Signed out"})}))
        self.assertEqual(problems, [])                         # no key: never a false "down"
        self.assertIn("answering", facts["phone"])

    def test_the_phone_check_goes_by_the_server_s_name(self):
        """5 Nov: through 127.0.0.1 SDI Intelligence asks for a sign-in, and SDI_API_KEY isn't set on the server -
        by its network name (as the laptop's checks go) it is followed all the way to SameDay."""
        import socket
        fake = Fake()
        run(fake)
        via = [u for u, _ in fake.asked if "/sameday/api/version" in u]
        self.assertEqual(via, [f"http://{socket.gethostname()}:8071/sameday/api/version"])

    def test_the_keys(self):
        self.assertEqual(keys(run(Fake(**{"api.openai.com": (401, {"error": "bad key"})}))[0]).get("openai"), "down")
        self.assertEqual(keys(run(env={"ANTHROPIC_API_KEY": "sk-ant-" + "y" * 40})[0]).get("openai"), "down")
        self.assertEqual(keys(run(Fake(**{"api.anthropic.com": (401, {})}))[0]).get("anthropic"), "down")
        self.assertEqual(keys(run(Fake(**{"api.openai.com": (0, "timeout")}))[0]).get("openai"), "warn")

    def test_spend_against_the_cap(self):
        self.assertEqual(keys(run(Fake(**{"5020/api/status": (200, {"spent_today": 8.5, "cap": 10})}))[0]).get("spend"), "warn")
        p = run(Fake(**{"5020/api/status": (200, {"spent_today": 10.02, "cap": 10})}))[0]
        self.assertEqual(keys(p).get("spend"), "down")
        self.assertIn("brief_lite_daily_cap_usd", p[0]["fix"])

    def test_the_server_s_disk(self):
        """5 Nov (James: "this is a production server"): a copy was started on a guess at its size."""
        p = run(free=4.2)[0]
        self.assertEqual(keys(p).get("disk"), "down")
        self.assertIn("all_img_thumbs", p[0]["fix"])
        self.assertEqual(keys(run(free=8.0)[0]).get("disk"), "warn")
        self.assertEqual(run(free=28.4)[0], [])
        self.assertIn("28.4 GB", run(free=28.4)[1]["server C: free"])
        self.assertEqual(run(free=None)[0], [])                 # can't be read here: never a false alarm
        self.assertIsNone(W.disk_free_gb("Q:\\no-such-drive\\"))

    def test_no_credit_in_sameday_s_log(self):
        p = run(log="rt done abc make_concepts: NOTHING drawn - Renders are paused ... needs topping up")[0]
        self.assertEqual(keys(p).get("credit"), "down")
        self.assertTrue(p[0].get("sticky"))

    def test_the_keys_are_sent_only_to_their_own_service_and_never_said(self):
        fake = Fake(**{"api.openai.com": (401, {}), "api.anthropic.com": (401, {})})
        problems, facts = run(fake)
        for url, headers in fake.asked:
            if KEY in json.dumps(headers):
                self.assertTrue(url.startswith("https://api.openai.com/"), url)
        said = json.dumps([problems, facts]) + json.dumps(W.compose({"new": problems, "remind": [], "recovered": []},
                                                                    facts, datetime(2026, 11, 5, 10, 0)))
        self.assertNotIn(KEY, said)
        self.assertNotIn("y" * 40, said)

    def test_a_check_that_cannot_run_is_never_a_pass(self):
        self.assertTrue(run(Fake(**{"5020/api/version": (200, "not json")}))[0])


class WhenItEmailsTests(unittest.TestCase):
    NOW = datetime(2026, 11, 5, 10, 0)
    DOWN = [{"key": "answer", "level": "down", "title": "SameDay isn't answering", "fix": "Start it."}]

    def test_once_then_a_reminder_then_all_clear(self):
        state = {}
        first = W.decide(state, self.DOWN, self.NOW, True, 3)
        self.assertEqual([p["key"] for p in first["new"]], ["answer"])
        again = W.decide(state, self.DOWN, self.NOW + timedelta(minutes=15), True, 3)
        self.assertEqual(again, {"new": [], "remind": [], "recovered": []})            # not every 15 minutes
        later = W.decide(state, self.DOWN, self.NOW + timedelta(hours=3), True, 3)
        self.assertEqual([p["key"] for p in later["remind"]], ["answer"])
        fixed = W.decide(state, [], self.NOW + timedelta(hours=3, minutes=15), True, 3)
        self.assertEqual(fixed["recovered"], ["SameDay isn't answering"])
        self.assertEqual(W.decide(state, [], self.NOW + timedelta(hours=4), True, 3)["recovered"], [])

    def test_nothing_at_night_and_the_morning_hears_what_is_still_wrong(self):
        state, night = {}, datetime(2026, 11, 5, 2, 0)
        self.assertFalse(W.in_hours(night, "7-19"))
        self.assertEqual(W.decide(state, self.DOWN, night, False, 3)["new"], [])
        self.assertEqual([p["key"] for p in W.decide(state, self.DOWN, datetime(2026, 11, 5, 7, 0), True, 3)["new"]],
                         ["answer"])
        blip = {}                                   # wrong at night, fixed by the morning: nobody is woken or told
        W.decide(blip, self.DOWN, night, False, 3)
        self.assertEqual(W.decide(blip, [], datetime(2026, 11, 5, 7, 0), True, 3),
                         {"new": [], "remind": [], "recovered": []})

    def test_no_credit_is_not_emailed_every_15_minutes_nor_called_fixed(self):
        state = {}
        credit = [{"key": "credit", "level": "down", "title": "OpenAI says the account has no credit", "fix": "Top up.",
                   "sticky": True}]
        self.assertEqual(len(W.decide(state, credit, self.NOW, True, 3)["new"]), 1)
        quiet = W.decide(state, [], self.NOW + timedelta(minutes=15), True, 3)
        self.assertEqual(quiet["recovered"], [])                                       # it can't be seen to be fixed
        self.assertEqual(W.decide(state, credit, self.NOW + timedelta(minutes=30), True, 3)["new"], [])
        gone = W.decide(state, [], self.NOW + timedelta(hours=4), True, 3)
        self.assertEqual(gone["recovered"], [])
        self.assertNotIn("credit", state["open"])

    def test_the_email_says_what_to_do(self):
        mail = W.compose({"new": self.DOWN, "remind": [], "recovered": []}, {"version": "v1"}, self.NOW)
        self.assertTrue(mail["subject"].startswith("SameDay: PROBLEM - SameDay isn't answering"))
        self.assertIn("What to do: Start it.", mail["text"])
        self.assertIn("Start it.", mail["html"])
        clear = W.compose({"new": [], "remind": [], "recovered": ["SameDay isn't answering"]}, {}, self.NOW)
        self.assertTrue(clear["subject"].startswith("SameDay: all clear"))
        self.assertIsNone(W.compose({"new": [], "remind": [], "recovered": []}, {}, self.NOW))

    def test_an_email_that_wasnt_sent_is_tried_again(self):
        d = Path(tempfile.mkdtemp(prefix="watch-"))
        keep = (W.STATE, W.check, W.send, W.datetime, os.environ.get("SAMEDAY_ALERT_TO"))
        W.STATE = d / "state.json"
        W.check = lambda log_text="": (self.DOWN[:1] and [dict(self.DOWN[0], level="warn")], {})
        sent = []

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 5, 10, 0)
        W.datetime = Clock
        os.environ["SAMEDAY_ALERT_TO"] = "james@example.com"
        os.environ["SAMEDAY_INDEX_HOUR"] = "25"            # not the daily index check - that has its own tests
        try:
            W.send = lambda to, email: sent.append(email["subject"]) or {"sent": False, "reason": "Graph 503"}
            W.main(["--send"])
            self.assertEqual(json.loads(W.STATE.read_text())["open"]["answer"]["sent"], "")   # not counted as told
            W.send = lambda to, email: sent.append(email["subject"]) or {"sent": True}
            W.main(["--send"])
            self.assertEqual(len(sent), 2)
            self.assertTrue(json.loads(W.STATE.read_text())["open"]["answer"]["sent"])
        finally:
            W.STATE, W.check, W.send, W.datetime = keep[:4]
            os.environ.pop("SAMEDAY_INDEX_HOUR", None)
            if keep[4] is None:
                os.environ.pop("SAMEDAY_ALERT_TO", None)
            else:
                os.environ["SAMEDAY_ALERT_TO"] = keep[4]


class ReadingTheLogTests(unittest.TestCase):
    def test_from_now_on_first_then_only_new_lines_and_a_restart_starts_over(self):
        d = Path(tempfile.mkdtemp(prefix="watchlog-"))
        log = d / "SDISameDay.log"
        log.write_text("old: insufficient_quota\n")
        state = {}
        self.assertEqual(W.new_log_text(log, state), "")            # never an alarm about yesterday
        with open(log, "a") as f:
            f.write("new line\n")
        self.assertEqual(W.new_log_text(log, state), "new line\n")
        log.write_text("after restart\n")                            # a new, shorter file
        self.assertEqual(W.new_log_text(log, state), "after restart\n")


class OnTheServerTests(unittest.TestCase):
    INSTALL = (BACKEND / "deploy" / "Install-SameDay-Watch.ps1").read_text(encoding="utf-8")
    BODY = "\n".join(re.sub(r"(^|\s)#.*$", "", x) for x in re.sub(r"<#.*?#>", "", INSTALL, flags=re.S).split("\n"))

    def test_ship_it_carries_it(self):
        deploy = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")
        files = deploy.split("$Files = @(", 1)[1].split("\n)", 1)[0]
        self.assertIn('"sameday_watch.py"', files)
        self.assertIn('"sameday_watch.cmd"', files)

    def test_the_task_runs_every_15_minutes_as_system(self):
        self.assertIn("/RU SYSTEM", self.BODY)
        self.assertIn("/SC MINUTE /MO 15", self.BODY)
        self.assertIn('/TR "$Backend\\sameday_watch.cmd"', self.BODY)
        cmd = (BACKEND / "sameday_watch.cmd").read_text(encoding="utf-8")
        self.assertIn('".venv\\Scripts\\python.exe" sameday_watch.py --send >> logs\\sameday_watch.log 2>&1', cmd)

    def test_nobody_to_email_stops_it_before_anything_changes(self):
        self.assertLess(self.BODY.index("SAMEDAY_ALERT_TO\\s*=\\s*\\S+@"), self.BODY.index("/Create"))
        self.assertNotIn("Get-Content -LiteralPath \"$Share\\.env\"", self.BODY)    # the settings are never shown

    def test_powershell_traps(self):
        self.assertTrue(all(ord(c) < 128 for c in self.INSTALL))
        for line in self.BODY.splitlines():
            for s in re.findall(r'"[^"]*"', line):
                self.assertIsNone(re.search(r"\$(?!env:)[A-Za-z_]\w*:", s), line)
        self.assertIn("[switch]$Remove", self.BODY)

    def test_it_only_reads_sameday(self):
        src = (BACKEND / "sameday_watch.py").read_text(encoding="utf-8")
        for verb in ("httpx.post", ".write_text(json.dumps(state", "requests.post"):
            if verb == ".write_text(json.dumps(state":
                continue                            # its own state file, in SDI Intelligence's logs folder
            self.assertNotIn(verb, src)
        self.assertNotIn("print(env", src)
        self.assertNotIn("print(k", src)


if __name__ == "__main__":
    unittest.main()
