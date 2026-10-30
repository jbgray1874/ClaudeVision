"""The first screen, for people who did not build it.

"THEY ARE COMPANY DIRECTORS AND NORTHERN ENGLISH SO A BIT ...SCEPTICAL OF
TECHNOLOGY AND AI SO EVERYTHING WE DO HAS TO BE PERFECT"

Two of the four states a new person can land in were written for whoever
configured the app rather than for the person reading them, and both were
found by rendering the page as each of them rather than by reading the code:

  * the empty-record panel opened with "no record has AM Owner set to CB" and
    then listed SDI_VOICECRM_OWNER, SDI_VOICECRM_OWNER_FIELD and every column
    in the sheet. To somebody opening the app for the first time that reads
    as half-built, when the truth is that one initial is wrong;

  * the read-only panel said "the write loop is switched off until the
    sandbox pilot is approved" to EVERY person who could not write. For
    Kayleigh, Charlotte and Matt that is simply false - writing is on, it is
    not theirs - and a deliberate permission reading as an unfinished feature
    is the difference between "I'm not set up for that" and "this doesn't
    work".

The diagnostics are all still there. They are folded away, under a heading
saying who they are for.
"""
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

PAGE = (BACKEND / "appportal" / "voice-crm.html").read_text(encoding="utf-8")
SOURCE = (BACKEND / "voicecrm.py").read_text(encoding="utf-8")

# Every setting name the app knows about. None of these belongs in the first
# paragraph of anything a director reads.
SETTINGS = ("SDI_VOICECRM_OWNER", "SDI_VOICECRM_OWNER_FIELD", "SDI_VOICECRM_OWNERS",
            "SDI_VOICECRM_WRITE", "SDI_VOICECRM_APPROVED_BY", "SDI_VOICECRM_WRITERS",
            "SDI_VOICECRM_SITE", "SDI_VOICECRM_XLSX")


def readable(source: str) -> str:
    """The text as a PERSON would see it, not as the file stores it.

    These panels are JavaScript string concatenation, so a sentence in the
    page is "one-minute '\n  +'change" in the file, and an apostrophe is
    \\'. Asserting against the raw source tests the line wrapping rather than
    the wording - the first version of this file failed on exactly that and
    said nothing about what Charlotte reads.
    """
    import re
    joined = re.sub(r"'\s*\+\s*'", "", source)      # 'abc ' + 'def'  ->  'abc def'
    return joined.replace("\\'", "'")


def panel(title: str) -> str:
    """The body of one panel(...) call, by its title.

    Everything up to the NEXT panel( call. Counting brackets would be wrong
    here: these bodies are full of them inside string literals - "(propose →
    read back → confirm → journal)" among others - and a balancer that does
    not know a string from code stops in the middle of a sentence.
    """
    at = PAGE.index("panel('" + title)
    rest = PAGE[at + 10:]
    nxt = rest.find("panel('")
    return readable(PAGE[at:at + 10 + (nxt if nxt != -1 else len(rest))])


class TheEmptyRecordPanelTests(unittest.TestCase):
    """Charlotte signs in, her initials are not in the sheet, and this is the
    whole of what she sees."""

    def body(self):
        return panel("Nothing is filed against you yet")

    def test_it_opens_by_saying_nothing_is_wrong(self):
        body = self.body()
        self.assertIn("without any trouble", body)
        self.assertIn("one-minute change", body)

    def test_it_says_who_to_ask(self):
        self.assertIn("James Gray", self.body())

    def test_no_setting_name_appears_before_the_fold(self):
        """── THE RULE ─────────────────────────────────────────────────────
        Everything above the <details> is what she reads without choosing to.
        A setting name there is me talking to myself in front of a customer.
        """
        visible = self.body().split("<details", 1)[0]
        for name in SETTINGS:
            with self.subTest(setting=name):
                self.assertNotIn(name, visible)

    def test_the_diagnostics_are_kept_not_deleted(self):
        """Folding them away must not lose them: they are how the wrong
        initial is found, and they are the reason this is a one-minute fix."""
        folded = self.body().split("<details", 1)[1]
        self.assertIn("owner_values", folded)
        self.assertIn("headers_seen", folded)
        self.assertIn("SDI_VOICECRM_OWNERS", folded)

    def test_the_fold_says_who_it_is_for(self):
        self.assertIn("FOR IT", self.body())

    def test_it_does_not_name_another_employee(self):
        """It used to end "If Nick appears under a different value...", which
        tells Charlotte whose records she is not seeing."""
        self.assertNotIn("If Nick appears", self.body())


class TheReadOnlyPanelTests(unittest.TestCase):
    """Three of the six are read-only BY DESIGN. That has to read as a
    decision, not as an unfinished feature."""

    def test_there_are_two_panels_because_there_are_two_reasons(self):
        self.assertIn("You can ask anything", PAGE)
        self.assertIn("Changes are switched off for everyone", PAGE)

    def test_the_personal_one_does_not_claim_the_feature_is_unfinished(self):
        body = panel("You can ask anything")
        for wrong in ("switched off until", "not approved", "built, but"):
            with self.subTest(phrase=wrong):
                self.assertNotIn(wrong, body)

    def test_the_personal_one_says_it_is_a_list_and_how_to_get_on_it(self):
        body = panel("You can ask anything")
        self.assertIn("limited to named people", body)
        self.assertIn("James Gray", body)

    def test_neither_shows_a_setting_name_to_the_person(self):
        for title in ("You can ask anything", "Changes are switched off for everyone"):
            with self.subTest(panel=title):
                for name in SETTINGS:
                    self.assertNotIn(name, panel(title))

    def test_the_page_can_tell_the_two_apart(self):
        """It could not before: there was one flag, so there was one message."""
        self.assertIn("ST.writes_switched_on && !ST.may_write", PAGE)

    def test_the_server_sends_both_flags(self):
        for flag in ('"writes_switched_on"', '"may_write"'):
            with self.subTest(flag=flag):
                self.assertIn(flag, SOURCE)


class TheUnmappedPanelTests(unittest.TestCase):
    """Andy signs in before his initials are set. He is a Sales Director and
    this is his first impression of the thing."""

    def body(self):
        return readable(PAGE.split("case 'no_owner':", 1)[1].split("case '", 1)[0])

    def test_it_says_plainly_that_it_is_not_an_empty_pipeline(self):
        self.assertIn('not</b> "you have no live jobs"', self.body())

    def test_it_explains_why_it_shows_nothing_rather_than_guessing(self):
        self.assertIn("somebody else's pipeline", self.body())


if __name__ == "__main__":
    unittest.main()
