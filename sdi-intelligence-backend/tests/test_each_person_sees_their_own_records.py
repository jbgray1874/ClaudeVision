"""Whose records does a signed-in person see?

── THE BUG THIS CLOSES, BEFORE ANYBODY HIT IT ───────────────────────────────
SDI_VOICECRM_OWNER is ONE value, read once at startup. For a one-person pilot
that was right. The moment a second person signs in it is wrong in the worst
way available: they do not see "nothing", they see NICK'S accounts, with
nothing on screen to say the rows are not theirs.

Four people were about to be given access - a Sales Director and three others.
Handing them another person's pipeline, labelled as their own, is not a missing
feature; it is a false statement about whose numbers they are reading, and in
ChatGPT's voice mode there is not even a screen to notice it on.

So owner_for(user) decides, per person, and the rules it must keep are:

  * two people signed in at once get their own rows;
  * somebody whose job is the whole pipeline can be given all of them;
  * somebody who is not mapped sees NOTHING, and is told why - never a quiet
    fallback to whoever the service's own owner happens to be;
  * with the mapping unset, the running pilot behaves exactly as before.
"""
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# voicecrm.py imports httpx and FastAPI and cannot be imported here; the rule
# itself lives in crm_owners.py, which imports nothing. That is the point of
# the split - see that module.
import crm_owners                                                  # noqa: E402

SOURCE = (BACKEND / "voicecrm.py").read_text(encoding="utf-8")
CONNECTOR = (BACKEND / "voicecrm_connector.py").read_text(encoding="utf-8")
PAGE = (BACKEND / "appportal" / "voice-crm.html").read_text(encoding="utf-8")

NICK = {"email": "Nick.Garrish@sdidisplays.co.uk", "name": "Nick Garrish"}
KAYLEIGH = {"email": "kayleigh.thornhill@wearesdi.com", "name": "Kayleigh Thornhill"}
ANDY = {"email": "andy.baxter@wearesdi.com", "name": "Andy Baxter"}
STRANGER = {"email": "someone.else@wearesdi.com", "name": "Someone Else"}

MAPPING = ("nick.garrish@sdidisplays.co.uk=NG,"
           "kayleigh.thornhill@wearesdi.com=KT,"
           "andy.baxter@wearesdi.com=*")


SERVICE_OWNER = "NG"            # what SDI_VOICECRM_OWNER is set to today


class Owners:
    """The mapping as the service would hold it, for one setting value."""

    def __init__(self, setting: str):
        self.map = crm_owners.parse(setting)
        self.OWNER = SERVICE_OWNER
        self.ALL_RECORDS = crm_owners.ALL_RECORDS

    def owner_for(self, user):
        return crm_owners.owner_for(user, self.map, self.OWNER)


def with_owners(value: str) -> Owners:
    return Owners(value)


class EachPersonGetsTheirOwnTests(unittest.TestCase):
    def setUp(self):
        self.vc = with_owners(MAPPING)

    def test_two_people_signed_in_at_once_get_different_rows(self):
        """The whole point. One global OWNER cannot express this."""
        self.assertEqual(self.vc.owner_for(NICK), "NG")
        self.assertEqual(self.vc.owner_for(KAYLEIGH), "KT")

    def test_the_email_match_ignores_case(self):
        """Entra returns the address in whatever case it was typed in."""
        self.assertEqual(self.vc.owner_for({"email": "NICK.GARRISH@SDIDISPLAYS.CO.UK"}), "NG")
        self.assertEqual(self.vc.owner_for({"email": "  Nick.Garrish@sdidisplays.co.uk "}), "NG")

    def test_somebody_whose_job_is_the_whole_pipeline_can_have_all_of_it(self):
        self.assertEqual(self.vc.owner_for(ANDY), self.vc.ALL_RECORDS)

    def test_an_unmapped_person_is_mapped_to_nobody(self):
        self.assertIsNone(self.vc.owner_for(STRANGER))

    def test_and_so_is_nobody_at_all(self):
        for absent in (None, {}, {"email": ""}, {"email": "   "}, {"name": "no email"}):
            with self.subTest(user=str(absent)):
                self.assertIsNone(self.vc.owner_for(absent))

    def test_an_unmapped_person_never_falls_back_to_the_services_owner(self):
        """── THE ONE THAT MATTERS ─────────────────────────────────────────
        A fallback here is indistinguishable, on screen, from "these are your
        records". That is the bug, not a safety net for it.
        """
        self.assertIsNone(self.vc.owner_for(STRANGER))
        self.assertNotEqual(self.vc.owner_for(STRANGER), self.vc.OWNER)


class TheRunningPilotIsUnchangedUntilTheSettingIsWrittenTests(unittest.TestCase):
    """Empty mapping = exactly the old behaviour, so deploying this changes
    nothing for Nick until somebody chooses to change it."""

    def setUp(self):
        self.vc = with_owners("")

    def test_everyone_gets_the_services_owner_as_before(self):
        for user in (NICK, KAYLEIGH, STRANGER, None):
            with self.subTest(user=str(user)):
                self.assertEqual(self.vc.owner_for(user), self.vc.OWNER)

    def test_a_malformed_mapping_does_not_take_the_app_down(self):
        for rubbish in (",,,", "=", "no-equals-sign", "a@b=", "=TOKEN", "   "):
            with self.subTest(setting=rubbish):
                vc = with_owners(rubbish)
                self.assertEqual(vc.owner_for(NICK), vc.OWNER,
                                 "an unparseable mapping must read as unset, "
                                 "not as 'nobody sees anything'")


class TheFilterUsesThePersonNotTheServiceTests(unittest.TestCase):
    """records_for is shared by the web app and the ChatGPT connector. A
    filter left on the module-level OWNER in either one reopens the hole."""

    def test_records_for_takes_the_owner_as_an_argument(self):
        signature = SOURCE.split("def records_for(", 1)[1].split(")", 1)[0]
        self.assertIn("owner", signature)

    def test_the_row_loop_compares_against_that_argument(self):
        body = SOURCE.split("def records_for(", 1)[1].split("\ndef ", 1)[0]
        loop = body.split("for item in data[\"items\"]:", 1)[1].split("out =", 1)[0]
        self.assertIn("owner", loop)
        self.assertNotIn("OWNER.upper()", loop,
                         "the loop still compares against the service-wide owner")

    def test_the_web_app_passes_the_signed_in_person(self):
        handler = SOURCE.split("def projects(", 1)[1].split("\n@router", 1)[0]
        self.assertIn("owner_for(", handler)

    def test_chatgpt_passes_them_too(self):
        """── WHY THIS IS NOT BELT AND BRACES ──────────────────────────────
        ChatGPT is a second front door to the same records. Left on the
        service-wide owner, "what's overdue?" would answer about Nick's
        pipeline whoever asked - and in voice mode there is no screen to
        notice it on.
        """
        handler = CONNECTOR.split("def get_records(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("voicecrm.owner_for(user)", handler)

    def test_both_stores_filter_per_person(self):
        """── THE ONE THE TESTS FOUND ──────────────────────────────────────
        records_for has TWO row loops: the workbook, and the SharePoint List
        it is headed for after the pilot. The List branch had its own copy of
        the filter, still comparing against the service-wide OWNER - so the
        per-person fix would have silently stopped applying on the day the
        store changed, which is the worst possible day for it to stop.
        """
        body = SOURCE.split("def records_for(", 1)[1].split("\ndef ", 1)[0]
        self.assertEqual(body.count('"owner_filter": owner'), 2,
                         "one of the two stores reports a different filter")
        self.assertNotIn('"owner_filter": OWNER', body)
        self.assertEqual(body.count('"state": "no_owner"'), 2,
                         "one of the two stores would fall through instead of "
                         "refusing an unmapped person")

    def test_no_loop_variable_shadows_the_owner_parameter(self):
        """── A BUG THAT READS CORRECTLY AND DOES THE OPPOSITE ─────────────
        The List loop's variable was called `owner`, which is now the name of
        the parameter holding WHOSE records to return. Rebinding it mid-loop
        means every row after the first is compared against the previous
        row's owner. Same shape as a PowerShell local shadowing a switch,
        which cost a deploy earlier in this project.
        """
        body = SOURCE.split("def records_for(", 1)[1].split("\ndef ", 1)[0]
        for assignment in ("        owner = ", "    owner = ", "for owner in"):
            with self.subTest(assignment=assignment.strip()):
                self.assertNotIn(assignment, body,
                                 "something rebinds `owner` inside records_for")

    def test_the_reply_reports_the_filter_that_was_actually_applied(self):
        body = SOURCE.split("def records_for(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('"owner_filter": owner', body)
        self.assertNotIn('"owner_filter": OWNER', body)


class NobodyIsShownSomebodyElsesPipelineTests(unittest.TestCase):
    def test_an_unmapped_person_gets_a_state_of_its_own(self):
        body = SOURCE.split("def records_for(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('"state": "no_owner"', body)
        self.assertIn("if owner is None:", body)

    def test_it_returns_before_any_row_is_read(self):
        """Not an empty list filtered out of a full one - a refusal."""
        body = SOURCE.split("def records_for(", 1)[1].split("\ndef ", 1)[0]
        self.assertLess(body.index('"state": "no_owner"'),
                        body.index("for item in data[\"items\"]:"))

    def test_the_page_says_it_is_a_setting_and_not_an_empty_pipeline(self):
        """"No records" reads as "you have no live work", which is a claim
        about the business rather than about the configuration."""
        self.assertIn("case 'no_owner':", PAGE)
        self.assertIn("not</b> \"you have no live jobs\"", PAGE)

    def test_the_refusal_says_what_to_do_about_it(self):
        body = SOURCE.split("def records_for(", 1)[1].split("\ndef ", 1)[0]
        refusal = body.split('"state": "no_owner"', 1)[1][:600]
        self.assertIn("add your initials", refusal)


class WritingStaysSeparateFromSeeingTests(unittest.TestCase):
    """Being able to see your records does not make you able to change them.
    Those are two settings, and they stay two."""

    def test_writers_are_still_their_own_named_list(self):
        self.assertIn('WRITERS = {e.strip().lower() for e in _opt("SDI_VOICECRM_WRITERS")',
                      SOURCE)

    def test_the_write_check_does_not_consult_the_owner_map(self):
        body = SOURCE.split("def _may_write(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("WRITERS", body)
        for leak in ("OWNERS", "owner_for"):
            with self.subTest(term=leak):
                self.assertNotIn(leak, body)


if __name__ == "__main__":
    unittest.main()
