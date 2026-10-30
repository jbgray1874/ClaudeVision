"""Whose briefing does a person hear when they press "Listen to my briefing"?

James Gray, 30 October: "if matt or someone else opens up the listen to my
briefing, will it say their name? how does it decide?"

It said their name. Then it read them NICK's slice of the sheet: the review
was built for SDI_VOICECRM_OWNER ("NG") whoever asked, "since the last review"
was compared with the 07:50 job's snapshot (also Nick's), and "updates saved
in the last 24 hours" was every change by anybody. "Good morning Matt",
followed by somebody else's pipeline, in a voice that sounds personal.

Three more of the same, found in the same search:

  * "Show today's review" - built for NG, greeted as Nick;
  * "Email it now" - sent to SDI_REVIEW_TO (Nick and James) whoever pressed
    it, so a per-person review would have mailed Andy's to Nick;
  * the write check compared each row with NG, so Andy - a writer - would
    have been refused a change to anything that was not Nick's row.

And the decision that shaped the fix: "this is currently a view onto Nick's
work / team / clients. He reports upwards to Matt and Andy." It is one team's
sheet, and the people who log in hear updates across the whole of it - which
is the owner value "*".
"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import morning_review as mr                                         # noqa: E402

SOURCE = (BACKEND / "voicecrm.py").read_text(encoding="utf-8")
PAGE = (BACKEND / "appportal" / "voice-crm.html").read_text(encoding="utf-8")

HEADERS = ["ACCOUNT", "BUSINESS UNIT", "OVERVIEW / DESCRIPTION / DELIVERABLES",
           "Status", "AM Owner", "NEXT STEPS", "KEY DATES FOR NEXT STEPS", "BUDGET COST"]


def row(account, owner, status="Live"):
    return {"ACCOUNT": account, "BUSINESS UNIT": "Retail",
            "OVERVIEW / DESCRIPTION / DELIVERABLES": f"{account} job",
            "Status": status, "AM Owner": owner, "NEXT STEPS": "Chase",
            "KEY DATES FOR NEXT STEPS": "01/11/2026", "BUDGET COST": "1000"}


SHEET = [row("Northgate", "NG"), row("Ashby", "NG"), row("Milbourne", "KT"),
         row("Pellingham", "AB"), row("Orrell", "IJ")]
TODAY = date(2026, 10, 30)


class TheWholeSheetIsOneOwnerValueTests(unittest.TestCase):
    def test_star_reviews_every_row(self):
        review = mr.build_review(SHEET, HEADERS, "AM Owner", "*", TODAY)
        self.assertEqual(review["counts"]["active"], len(SHEET))

    def test_an_owner_still_reviews_only_their_slice(self):
        """Nick's 07:50 email is unchanged: it is still NG's."""
        review = mr.build_review(SHEET, HEADERS, "AM Owner", "NG", TODAY)
        self.assertEqual(review["counts"]["active"], 2)

    def test_the_snapshot_says_whose_it_is(self):
        review = mr.build_review(SHEET, HEADERS, "AM Owner", "*", TODAY)
        self.assertEqual(review["snapshot"]["owner"], "*")


class NicksEmailLooksExactlyAsItDidTests(unittest.TestCase):
    """The per-person change must not touch the email Nick already reads."""

    def test_his_subject_and_counts_line_are_unchanged(self):
        review = mr.build_review(SHEET, HEADERS, "AM Owner", "NG", TODAY)
        out = mr.render(review, {"movement": "x", "items": []})
        self.assertTrue(out["subject"].startswith("NG Sandbox CRM — Morning Review"),
                        out["subject"])
        self.assertIn("Active NG records reviewed", out["text"])

    def test_the_team_review_says_team_and_not_a_wildcard(self):
        review = mr.build_review(SHEET, HEADERS, "AM Owner", "*", TODAY)
        out = mr.render(review, {"movement": "x", "items": []}, "Matt")
        self.assertTrue(out["subject"].startswith("Team Sandbox CRM"), out["subject"])
        self.assertIn("Active team records reviewed", out["text"])
        self.assertIn("Morning Matt", out["text"])
        self.assertNotIn("*", out["subject"])


class SinceTheLastReviewIsYourOwnLastReviewTests(unittest.TestCase):
    """Compared with Nick's snapshot, Matt's briefing would report every team
    record as "new" and Nick's as "no longer active" - read out as fact."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.file = self.dir / "snapshots.json"
        self._was = mr._snapshot_file
        mr._snapshot_file = lambda: self.file
        self.addCleanup(setattr, mr, "_snapshot_file", self._was)

    def write(self, snaps):
        self.file.write_text(json.dumps(snaps), encoding="utf-8")

    def test_each_owner_gets_their_own(self):
        self.write([{"date": "2026-10-29", "owner": "NG", "counts": {"active": 2}},
                    {"date": "2026-10-29", "owner": "*", "counts": {"active": 5}}])
        self.assertEqual(mr.last_snapshot(TODAY, "NG")["counts"]["active"], 2)
        self.assertEqual(mr.last_snapshot(TODAY, "*")["counts"]["active"], 5)

    def test_nobody_is_compared_with_somebody_elses(self):
        self.write([{"date": "2026-10-29", "owner": "NG", "counts": {"active": 2}}])
        self.assertIsNone(mr.last_snapshot(TODAY, "*"),
                          "the team's briefing would compare against Nick's slice")

    def test_snapshots_from_before_owners_were_recorded_are_nicks(self):
        """Every untagged snapshot was written by the 07:50 job, for NG."""
        self.write([{"date": "2026-10-28", "counts": {"active": 2}}])
        self.assertIsNotNone(mr.last_snapshot(TODAY, "NG"))
        self.assertIsNone(mr.last_snapshot(TODAY, "*"))

    def test_saving_the_teams_snapshot_does_not_delete_nicks_for_the_same_day(self):
        """── THE TRAP ────────────────────────────────────────────────────
        save_snapshot replaced any snapshot with the same DATE. Saving the
        team's would have silently deleted Nick's, and his "up from 74" would
        have compared with nothing the next morning."""
        mr.save_snapshot({"date": "2026-10-30", "owner": "NG", "counts": {"active": 2}})
        mr.save_snapshot({"date": "2026-10-30", "owner": "*", "counts": {"active": 5}})
        tomorrow = date(2026, 10, 31)
        self.assertEqual(mr.last_snapshot(tomorrow, "NG")["counts"]["active"], 2)
        self.assertEqual(mr.last_snapshot(tomorrow, "*")["counts"]["active"], 5)

    def test_saving_again_the_same_day_still_replaces_that_owners_one(self):
        mr.save_snapshot({"date": "2026-10-30", "owner": "*", "counts": {"active": 5}})
        mr.save_snapshot({"date": "2026-10-30", "owner": "*", "counts": {"active": 6}})
        snaps = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual(len([s for s in snaps if s["owner"] == "*"]), 1)

    def test_the_scheduled_run_keeps_a_team_baseline_too(self):
        main = (BACKEND / "morning_review.py").read_text(encoding="utf-8").split("def main(", 1)[1]
        self.assertIn("ALL_RECORDS", main)
        self.assertIn("save_snapshot(team[\"snapshot\"])", main)


class TheBriefingIsBuiltForThePersonTests(unittest.TestCase):
    def body(self, name):
        return SOURCE.split(f"def {name}(", 1)[1].split("\n@router", 1)[0]

    def test_the_briefing_uses_the_persons_view(self):
        body = self.body("briefing")
        self.assertIn("owner = owner_for(user)", body)
        self.assertIn("last_snapshot(today, owner)", body)
        self.assertNotIn('OWNER or "NG"', body)

    def test_the_review_uses_the_persons_view_and_name(self):
        body = self.body("_review_for")
        self.assertIn("owner = owner_for(user)", body)
        self.assertIn("first_name=_first_name(user)", body)
        self.assertNotIn('OWNER or "NG"', body)

    def test_an_unmapped_person_gets_no_briefing_rather_than_nicks(self):
        self.assertIn('"state": "no_owner"', self.body("briefing"))
        self.assertIn('"state": "no_owner"', self.body("_review_for"))

    def test_email_it_now_goes_to_whoever_pressed_it(self):
        body = self.body("review_send")
        self.assertIn("to = _mailbox_for(request, user)", body)
        self.assertIn("morning_review.send(composed, to=[to])", body)

    def test_and_to_their_real_mailbox_not_their_sign_in_name(self):
        """Nick signs in as @sdidisplays.co.uk; his mail is @wearesdi.com."""
        body = SOURCE.split("def _mailbox_for(", 1)[1].split("\n@router", 1)[0]
        self.assertIn("/me", body)
        self.assertIn('"mail"', body)

    def test_the_screen_says_all_records_not_a_star(self):
        self.assertIn("'All records'", PAGE)


class TheVoiceCrmRulesRunForRealTests(unittest.TestCase):
    """The same rules, run - not read - with the team's real setting."""

    @classmethod
    def setUpClass(cls):
        import importlib
        import os
        cls._was = {k: os.environ.get(k) for k in
                    ("SDI_VOICECRM_OWNERS", "SDI_VOICECRM_OWNER", "SDI_VOICECRM_OWNER_FIELD")}
        os.environ["SDI_VOICECRM_OWNERS"] = (
            "nick.garrish@sdidisplays.co.uk=*,andy.baxter@wearesdi.com=*,"
            "matt.evans@wearesdi.com=*,ian.jones@wearesdi.com=*,"
            "someone.with.initials@wearesdi.com=KT")
        os.environ["SDI_VOICECRM_OWNER"] = "NG"
        os.environ["SDI_VOICECRM_OWNER_FIELD"] = "AM Owner"
        import voicecrm
        cls.vc = importlib.reload(voicecrm)

    @classmethod
    def tearDownClass(cls):
        import importlib
        import os
        for key, value in cls._was.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import voicecrm
        importlib.reload(voicecrm)

    def test_andy_can_change_any_row_in_the_teams_sheet(self):
        """He was refused anything that was not Nick's."""
        andy = {"email": "andy.baxter@wearesdi.com"}
        for r in SHEET:
            with self.subTest(owner=r["AM Owner"]):
                self.assertTrue(self.vc._owner_ok(r, andy))

    def test_somebody_with_initials_may_change_only_their_rows(self):
        kt = {"email": "someone.with.initials@wearesdi.com"}
        self.assertTrue(self.vc._owner_ok(row("Milbourne", "KT"), kt))
        self.assertFalse(self.vc._owner_ok(row("Northgate", "NG"), kt))

    def test_an_unmapped_person_may_change_nothing(self):
        for r in SHEET:
            with self.subTest(owner=r["AM Owner"]):
                self.assertFalse(self.vc._owner_ok(r, {"email": "stranger@wearesdi.com"}))

    def test_matt_hears_every_change_across_the_sheet(self):
        changes = [{"project_ref": "Northgate — Retail — Northgate job", "item_id": "xl3",
                    "user_oid": "nick"},
                   {"project_ref": "Milbourne — Retail — Milbourne job", "item_id": "xl5",
                    "user_oid": "kt"}]
        self.vc._journal = type("J", (), {"applied_since": lambda self, since: changes})()
        items = [{"id": f"xl{i + 3}", "fields": r} for i, r in enumerate(SHEET)]
        got = self.vc._changes_in_view("*", items, {"oid": "matt"}, 0)
        self.assertEqual(len(got), 2)

    def test_somebody_with_initials_hears_only_changes_to_their_records(self):
        changes = [{"project_ref": "Northgate — Retail — Northgate job", "item_id": "xl3",
                    "user_oid": "nick"},
                   {"project_ref": "Milbourne — Retail — Milbourne job", "item_id": "xl5",
                    "user_oid": "kt"}]
        self.vc._journal = type("J", (), {"applied_since": lambda self, since: changes})()
        items = [{"id": f"xl{i + 3}", "fields": r} for i, r in enumerate(SHEET)]
        got = self.vc._changes_in_view("KT", items, {"oid": "kt"}, 0)
        self.assertEqual([c["item_id"] for c in got], ["xl5"])

    def test_a_shifted_row_does_not_read_somebody_elses_change_out(self):
        """Ids are row numbers. A row inserted above moves them, and a change
        journalled against xl5 yesterday may be a different record today -
        matching on the name stops it being read to the wrong person."""
        changes = [{"project_ref": "Northgate — Retail — Northgate job", "item_id": "xl5",
                    "user_oid": "nick"}]
        self.vc._journal = type("J", (), {"applied_since": lambda self, since: changes})()
        items = [{"id": f"xl{i + 3}", "fields": r} for i, r in enumerate(SHEET)]
        self.assertEqual(self.vc._changes_in_view("KT", items, {"oid": "kt"}, 0), [])


if __name__ == "__main__":
    unittest.main()
