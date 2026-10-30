"""SDI Remote Control Intelligence, phase two: one action, and one question.

"yes build both" - James Gray, 30 October 2026, to:

  * a Restart button, replacing `Check-AMCRM-Live.ps1 -Restart` from the
    laptop - the process ends itself and the Windows service manager starts
    it again, so it is not a command and can do nothing a crash could not;
  * "can this person use AM CRM?", replacing Ready-For-People.ps1 - yes or no
    about a typed address, never the lists.

What is pinned here is what would cost a director's morning if it drifted: a
restart that drops an estimate somebody is waiting for, a restart a stray POST
can trigger, and an answer about a person that discloses the list it came from.
"""
import sys
import time
import types
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import sdi_ops_routes as ops  # noqa: E402

PAGE = (BACKEND / "appportal" / "sdi-remote-control.html").read_text(encoding="utf-8")


def client(restart="yes", busy=None):
    """The real router, with the gate opened and the exit recorded rather
    than taken - os._exit in a test run would end the test run."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    exits = []
    made = FastAPI()
    made.include_router(ops.make_router(
        env={"SDI_OPS_RESTART": restart} if restart else {},
        exit_soon=lambda: exits.append(time.time()),
        in_hand=lambda: list(busy or [])))
    return TestClient(made), exits


SAME_ORIGIN = {"Origin": "http://testserver", "X-SDI-Ops-Action": "1"}


class WithTheGateOpen(unittest.TestCase):
    def setUp(self):
        real_allowed, real_started = ops.allowed, ops.STARTED
        ops.allowed = lambda request: True
        ops.STARTED = time.time() - 3600          # up an hour: past the settle time
        self.addCleanup(setattr, ops, "allowed", real_allowed)
        self.addCleanup(setattr, ops, "STARTED", real_started)


class TheRestartTests(WithTheGateOpen):
    def test_it_restarts_when_asked_properly(self):
        web, exits = client()
        answer = web.post("/api/ops/restart", json={"confirm": "restart"}, headers=SAME_ORIGIN)
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertTrue(answer.json()["restarting"])
        self.assertEqual(len(exits), 1)

    def test_switched_off_the_route_is_not_there_at_all(self):
        web, exits = client(restart=None)
        answer = web.post("/api/ops/restart", json={"confirm": "restart"}, headers=SAME_ORIGIN)
        self.assertIn(answer.status_code, (404, 405))
        self.assertEqual(exits, [])

    def test_a_post_from_another_site_is_refused(self):
        web, exits = client()
        for headers in ({"Origin": "https://evil.example", "X-SDI-Ops-Action": "1"},
                        {"Origin": "http://testserver"},             # no action header
                        {}):
            with self.subTest(headers=headers):
                answer = web.post("/api/ops/restart", json={"confirm": "restart"},
                                  headers=headers)
                self.assertEqual(answer.status_code, 403)
        self.assertEqual(exits, [])

    def test_the_word_has_to_be_typed(self):
        web, exits = client()
        for word in ("", "yes", "restar"):
            with self.subTest(word=word):
                answer = web.post("/api/ops/restart", json={"confirm": word},
                                  headers=SAME_ORIGIN)
                self.assertEqual(answer.status_code, 400)
        self.assertEqual(exits, [])

    def test_never_while_an_estimate_is_in_hand(self):
        """Runs live in the service's memory. A restart mid-run loses the
        queue, the claim and the e-mail that says the book is done."""
        busy = [{"run_id": "r1", "client": "M&S", "drawing_number": "0359962",
                 "status": "running"}]
        web, exits = client(busy=busy)
        answer = web.post("/api/ops/restart", json={"confirm": "restart"}, headers=SAME_ORIGIN)
        self.assertEqual(answer.status_code, 409)
        self.assertIn("M&S 0359962", answer.json()["detail"])
        self.assertIn("lose track", answer.json()["detail"])
        self.assertEqual(exits, [])

    def test_not_twice_in_three_minutes(self):
        ops.STARTED = time.time() - 20
        web, exits = client()
        answer = web.post("/api/ops/restart", json={"confirm": "restart"}, headers=SAME_ORIGIN)
        self.assertEqual(answer.status_code, 409)
        self.assertIn("restarted 20 seconds ago", answer.json()["detail"])
        self.assertEqual(exits, [])

    def test_the_status_says_whether_it_could_and_why_not(self):
        """/status imports the live app, which a test cannot start, so the
        sentence is checked here and its place in /status below."""
        busy = [{"client": "Boots", "drawing_number": "12552", "status": "queued"}]
        self.assertIn("Boots 12552 (queued)", ops.why_not_restart(3600, busy, True))
        self.assertIn("SDI_OPS_RESTART=yes", ops.why_not_restart(3600, [], False))
        self.assertIsNone(ops.why_not_restart(3600, [], True))
        source = (BACKEND / "sdi_ops_routes.py").read_text(encoding="utf-8")
        self.assertIn('"restart": restart_state()', source.split("def status(", 1)[1])

    def test_who_asked_is_logged_before_the_process_ends(self):
        source = (BACKEND / "sdi_ops_routes.py").read_text(encoding="utf-8")
        restart = source.split("def restart(", 1)[1]
        self.assertLess(restart.index("[ops] restart asked by"), restart.index("exit_soon()"))

    def test_it_is_the_process_ending_not_a_command(self):
        source = (BACKEND / "sdi_ops_routes.py").read_text(encoding="utf-8")
        self.assertIn("os._exit(RESTART_EXIT_CODE)", source)
        for forbidden in ("subprocess", "os.system", "sc.exe", "Restart-Service"):
            self.assertNotIn(forbidden, source)


class TheEstimatingQueueAnswersTests(unittest.TestCase):
    def test_estimating_reports_only_unfinished_runs(self):
        try:
            import estimate_routes
        except Exception as exc:                                   # noqa: BLE001
            self.skipTest(f"estimating cannot be imported here: {exc}")
        held = dict(estimate_routes._RUNS)
        self.addCleanup(lambda: (estimate_routes._RUNS.clear(),
                                 estimate_routes._RUNS.update(held)))
        estimate_routes._RUNS.clear()
        for status in ("queued", "running", "done", "error"):
            run = types.SimpleNamespace(run_id=status, client="C", drawing_number="D",
                                        status=status)
            estimate_routes._RUNS[status] = run
        self.assertEqual(sorted(r["status"] for r in estimate_routes.work_in_hand()),
                         ["queued", "running"])

    def test_without_estimating_loaded_there_is_nothing_to_lose(self):
        held = sys.modules.pop("estimate_routes", None)
        if held is not None:
            self.addCleanup(sys.modules.__setitem__, "estimate_routes", held)
        self.assertEqual(ops.work_in_hand(), [])


class ThePersonCheckTests(WithTheGateOpen):
    """Ready-For-People.ps1's answers, from a phone."""

    def fake_crm(self, owners, writers, write_on=True):
        crm = types.ModuleType("voicecrm")
        crm.OWNERS = owners
        crm.WRITERS = set(writers)
        crm.WRITE_ENABLED = write_on
        crm.owner_for = lambda user: owners.get(user["email"]) if owners else "NG"
        crm._may_write = lambda user: user["email"] in crm.WRITERS
        held = sys.modules.get("voicecrm")
        sys.modules["voicecrm"] = crm
        self.addCleanup(lambda: sys.modules.__setitem__("voicecrm", held) if held
                        else sys.modules.pop("voicecrm", None))

    def ask(self, email):
        web, _ = client()
        return web.get("/api/ops/person", params={"email": email})

    def test_a_writer_who_sees_everything(self):
        self.fake_crm({"andy.baxter@wearesdi.com": "*"}, ["andy.baxter@wearesdi.com"])
        p = self.ask("Andy.Baxter@wearesdi.com ").json()
        self.assertEqual((p["sees"], p["may_write"], p["writes_switched_on"]),
                         ("*", True, True))

    def test_a_reader(self):
        self.fake_crm({"kayleigh.thornhill@wearesdi.com": "*"}, [])
        p = self.ask("kayleigh.thornhill@wearesdi.com").json()
        self.assertEqual((p["sees"], p["may_write"]), ("*", False))

    def test_somebody_not_mapped_sees_nothing(self):
        self.fake_crm({"a@wearesdi.com": "*"}, [])
        self.assertIsNone(self.ask("stranger@wearesdi.com").json()["sees"])

    def test_the_other_domain_is_named(self):
        """Nick, 30 October: set up as @sdidisplays.co.uk, checked as his
        mailbox, and looked like he was not set up at all."""
        self.fake_crm({"nick.garrish@sdidisplays.co.uk": "*"},
                      ["nick.garrish@sdidisplays.co.uk"])
        p = self.ask("nick.garrish@wearesdi.com").json()
        self.assertIsNone(p["sees"])
        self.assertEqual(p["elsewhere"], ["nick.garrish@sdidisplays.co.uk"])

    def test_the_lists_themselves_never_leave(self):
        self.fake_crm({"a@x.com": "*", "b@x.com": "NG", "c@x.com": "AB"},
                      ["a@x.com", "b@x.com"])
        body = self.ask("a@x.com").text
        for other in ("b@x.com", "c@x.com", "NG", "AB"):
            self.assertNotIn(other, body)

    def test_an_address_needs_its_at(self):
        self.fake_crm({}, [])
        self.assertEqual(self.ask("kayleigh").status_code, 400)

    def test_am_crm_not_loaded_says_so(self):
        held = sys.modules.pop("voicecrm", None)
        if held is not None:
            self.addCleanup(sys.modules.__setitem__, "voicecrm", held)
        p = self.ask("a@x.com").json()
        self.assertFalse(p["checked"])


class ThePageTests(unittest.TestCase):
    def test_it_watches_for_a_new_start_rather_than_trusting_the_answer(self):
        self.assertIn("s.started !== before", PAGE)

    def test_it_says_what_to_do_if_it_does_not_come_back(self):
        self.assertIn("Check-AMCRM-Live.ps1 -Restart", PAGE)

    def test_the_am_crm_settings_are_listed_by_name(self):
        for name in ("SDI_VOICECRM_OWNERS", "SDI_VOICECRM_WRITERS", "SDI_VOICECRM_WRITE",
                     "SDI_OPS_RESTART"):
            self.assertIn(name, ops.SETTINGS)

    def test_it_names_the_gates_it_cannot_see(self):
        self.assertIn("AADSTS50105", PAGE)
        self.assertIn("SharePoint", PAGE)


if __name__ == "__main__":
    unittest.main()
