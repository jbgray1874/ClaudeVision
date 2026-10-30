"""The six people, the real filter, the actual rows each one gets back.

── WHY THIS IS NOT THE SAME AS THE OTHER OWNER TEST ─────────────────────────
test_each_person_sees_their_own_records.py exercises the MAPPING - e-mail to
initials - and then asserts about records_for by reading its source text,
because voicecrm.py could not be imported without httpx.

Reading source is not running it. It cannot catch a filter that is correct in
one branch and wrong in the other, a comparison that is case-sensitive when
the sheet is not, or a row with a blank owner quietly joining somebody's
queue. Those are the failures that would reach a director as "why am I
looking at Nick's accounts" - which is the one outcome that cannot happen.

So this one calls records_for with a fake tracker and checks, row by row,
exactly what each of the six people gets. The names and initials are the real
ones being onboarded, because a test that passes for Alice and Bob tells you
nothing about whether Charlotte Blackwell was spelled right in the setting.
"""
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import crm_owners                                                   # noqa: E402

# What the laptop is told to write into .env, character for character.
# Both of Nick's addresses: he signs in as @sdidisplays.co.uk (found by the
# Entra audit on 30 October) and may have a second account on @wearesdi.com.
# Ian Jones is PM on Nick's accounts and sees Nick's rows.
SETTING = ("nick.garrish@sdidisplays.co.uk=NG,"
           "nick.garrish@wearesdi.com=NG,"
           "ian.jones@wearesdi.com=NG,"
           "kayleigh.thornhill@wearesdi.com=KT,"
           "andy.baxter@wearesdi.com=AB,"
           "charlotte.blackwell@wearesdi.com=CB,"
           "matt.evans@wearesdi.com=ME,"
           "james.gray@wearesdi.com=JG")

PEOPLE = {
    "Nick Garrish":       "Nick.Garrish@sdidisplays.co.uk",
    "Kayleigh Thornhill": "kayleigh.thornhill@wearesdi.com",
    "Andy Baxter":        "Andy.Baxter@wearesdi.com",
    "Charlotte Blackwell": "charlotte.blackwell@wearesdi.com",
    "Matt Evans":         "Matt.Evans@wearesdi.com",
    "James Gray":         "James.Gray@wearesdi.com",
    "Ian Jones":          "ian.jones@wearesdi.com",
}

WRITERS = ("james.gray@wearesdi.com,"
           "nick.garrish@sdidisplays.co.uk,"
           "nick.garrish@wearesdi.com,"
           "andy.baxter@wearesdi.com,"
           "ian.jones@wearesdi.com")

# A tracker with rows for several owners, some blank, and some with the casing
# and stray spaces a hand-maintained sheet actually contains.
SHEET = [
    ("xl10", "NG", "Northgate Retail"),
    ("xl11", "NG", "Ashby & Co"),
    ("xl12", "KT", "Milbourne Group"),
    ("xl13", "kt", "Carrowbridge Leisure"),      # lower case in the sheet
    ("xl14", " AB ", "Pellingham Stores"),       # stray spaces
    ("xl15", "CB", "Westhaven Trading"),
    ("xl16", "ME", "Orrell & Sons"),
    ("xl17", "IJ", "Somebody else's job"),
    ("xl18", "", "Owner left blank"),
    ("xl19", "NG", "Thornbury Retail"),
]

OWNER_FIELD = "AM Owner"


class FakeTracker:
    """Stands in for ExcelStore. Returns rows shaped as records_for expects."""
    configured = True
    xlsx = "AM Tracker (sandbox copy).xlsx"

    def rows(self, token):
        return {"state": "ok", "sheet": "Live Projects",
                "headers": [OWNER_FIELD, "ACCOUNT", "Status"],
                "source": "live",
                "items": [{"id": rid,
                           "fields": {OWNER_FIELD: owner, "ACCOUNT": account,
                                      "Status": "Live"}}
                          for rid, owner, account in SHEET]}


TOUCHED = ("SDI_VOICECRM_OWNERS", "SDI_VOICECRM_OWNER", "SDI_VOICECRM_OWNER_FIELD",
           "SDI_VOICECRM_STORE", "SDI_VOICECRM_WRITERS")


def load_voicecrm(setting: str):
    """voicecrm reads its settings at import, so it is reloaded per case."""
    import importlib
    import os
    os.environ["SDI_VOICECRM_OWNERS"] = setting
    os.environ["SDI_VOICECRM_OWNER"] = "NG"
    os.environ["SDI_VOICECRM_OWNER_FIELD"] = OWNER_FIELD
    os.environ["SDI_VOICECRM_STORE"] = "excel"
    import voicecrm
    importlib.reload(voicecrm)
    voicecrm.EXCEL = FakeTracker()
    voicecrm.CONFIGURED = True
    voicecrm.OWNER_FIELD = OWNER_FIELD
    return voicecrm


# ── PUT voicecrm BACK WHEN THIS MODULE IS DONE ───────────────────────────────
# This file sets environment variables and reloads voicecrm, which is module
# state every other test shares. requirements-dev.txt carries pytest-randomly
# for exactly this reason: "90 tests once passed in one order and failed in
# another, through state one of them left behind in sys.modules". Leaving a
# fake tracker and a test owner map bolted to the real module would be the
# same trap, set by the test written to prove the app is safe.
_WAS = None


def setUpModule():
    import os
    global _WAS
    _WAS = {k: os.environ.get(k) for k in TOUCHED}


def tearDownModule():
    import importlib
    import os
    for key, value in (_WAS or {}).items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    import voicecrm
    importlib.reload(voicecrm)          # real settings, real store, no fake


def accounts(result):
    return sorted(i["fields"]["ACCOUNT"] for i in result.get("items", []))


class EachOfTheSixGetsTheirOwnRowsTests(unittest.TestCase):
    """The run that decides whether Monday goes well."""

    @classmethod
    def setUpClass(cls):
        cls.vc = load_voicecrm(SETTING)

    def rows_for(self, name):
        user = {"name": name, "email": PEOPLE[name], "kind": "user"}
        return self.vc.records_for("fake-token", self.vc.owner_for(user))

    def test_nick_gets_nicks_three(self):
        self.assertEqual(accounts(self.rows_for("Nick Garrish")),
                         ["Ashby & Co", "Northgate Retail", "Thornbury Retail"])

    def test_kayleigh_gets_hers_including_the_lower_case_row(self):
        """── THE SHEET IS HAND-MAINTAINED ─────────────────────────────────
        One row says "kt" and not "KT". A case-sensitive comparison loses it,
        and losing a row silently is worse than showing none: she would not
        know to look.
        """
        self.assertEqual(accounts(self.rows_for("Kayleigh Thornhill")),
                         ["Carrowbridge Leisure", "Milbourne Group"])

    def test_andy_gets_his_despite_the_stray_spaces(self):
        self.assertEqual(accounts(self.rows_for("Andy Baxter")),
                         ["Pellingham Stores"])

    def test_charlotte_gets_hers(self):
        self.assertEqual(accounts(self.rows_for("Charlotte Blackwell")),
                         ["Westhaven Trading"])

    def test_matt_gets_his(self):
        self.assertEqual(accounts(self.rows_for("Matt Evans")),
                         ["Orrell & Sons"])

    def test_nobody_gets_a_row_belonging_to_somebody_else(self):
        """The whole point, stated as the thing that must never happen."""
        for name in PEOPLE:
            with self.subTest(person=name):
                got = accounts(self.rows_for(name))
                self.assertNotIn("Somebody else's job", got)

    def test_a_blank_owner_joins_nobodys_queue(self):
        """An unowned row attaching itself to whoever signs in first is a
        quiet way to show one person another's work."""
        for name in PEOPLE:
            with self.subTest(person=name):
                self.assertNotIn("Owner left blank", accounts(self.rows_for(name)))

    def test_james_is_mapped_but_owns_nothing_and_is_told_so(self):
        """── THE ONE THAT LOOKS LIKE A FAULT AND IS NOT ───────────────────
        JG appears in no row. That is an empty list, not an error - and the
        app says which owner values it DID find, which is how you discover
        that an initial was wrong before a director does.
        """
        out = self.rows_for("James Gray")
        self.assertEqual(out["state"], "ok")
        self.assertEqual(out["items"], [])
        self.assertIn("owner_values", out)
        found = dict(out["owner_values"])
        self.assertIn("NG", found)
        self.assertEqual(found["NG"], 3)

    def test_two_people_in_the_same_run_do_not_leak_into_each_other(self):
        """Module-level state is what made the original bug. Interleave them."""
        for _ in range(3):
            self.assertEqual(accounts(self.rows_for("Nick Garrish")),
                             ["Ashby & Co", "Northgate Retail", "Thornbury Retail"])
            self.assertEqual(accounts(self.rows_for("Kayleigh Thornhill")),
                             ["Carrowbridge Leisure", "Milbourne Group"])

    def test_the_reply_names_the_owner_it_filtered_on(self):
        self.assertEqual(self.rows_for("Kayleigh Thornhill")["owner_filter"], "KT")

    def test_it_counts_what_it_held_back(self):
        out = self.rows_for("Charlotte Blackwell")
        self.assertEqual(out["skipped_other_owner"], len(SHEET) - 1)


class SomebodyNotInTheSettingTests(unittest.TestCase):
    """A new starter, a typo in an address, or somebody who should not be
    there at all. All three must land in the same safe place."""

    @classmethod
    def setUpClass(cls):
        cls.vc = load_voicecrm(SETTING)

    def rows_for(self, email):
        return self.vc.records_for(
            "fake-token", self.vc.owner_for({"email": email, "kind": "user"}))

    def test_an_unmapped_person_gets_no_rows_at_all(self):
        out = self.rows_for("someone.new@wearesdi.com")
        self.assertEqual(out["state"], "no_owner")
        self.assertEqual(out["items"], [])

    def test_and_never_the_service_wide_owners_rows(self):
        """── THE FAILURE THIS WHOLE CHANGE EXISTS TO PREVENT ──────────────
        Before the mapping, an unrecognised person saw SDI_VOICECRM_OWNER's
        records - Nick's - with nothing on screen to say they were not theirs.
        """
        self.assertEqual(accounts(self.rows_for("someone.new@wearesdi.com")), [])

    def test_a_typo_in_the_setting_does_not_silently_fall_back(self):
        """Somebody mistypes an address when adding the seventh person."""
        vc = load_voicecrm(SETTING.replace("charlotte.blackwell@", "charlote.blackwell@"))
        out = vc.records_for("fake-token",
                             vc.owner_for({"email": "charlotte.blackwell@wearesdi.com"}))
        self.assertEqual(out["state"], "no_owner")
        self.assertEqual(out["items"], [])


class SeeingEverythingTests(unittest.TestCase):
    """Andy is Sales Director and may want the whole pipeline rather than a
    queue. "*" is how, and it must mean ALL rows - including the blank-owner
    one, which exists and belongs to somebody."""

    @classmethod
    def setUpClass(cls):
        cls.vc = load_voicecrm(SETTING.replace("andy.baxter@wearesdi.com=AB",
                                               "andy.baxter@wearesdi.com=*"))

    def test_the_star_returns_every_row(self):
        out = self.vc.records_for(
            "fake-token", self.vc.owner_for({"email": "andy.baxter@wearesdi.com"}))
        self.assertEqual(len(out["items"]), len(SHEET))
        self.assertIn("Somebody else's job", accounts(out))
        self.assertEqual(out["skipped_other_owner"], 0)

    def test_it_does_not_change_what_anybody_else_sees(self):
        out = self.vc.records_for(
            "fake-token", self.vc.owner_for({"email": "kayleigh.thornhill@wearesdi.com"}))
        self.assertEqual(accounts(out), ["Carrowbridge Leisure", "Milbourne Group"])


class WritingIsStillSeparateTests(unittest.TestCase):
    """Kayleigh, Charlotte and Matt are read-only. Seeing their own rows must
    not have made them able to change them."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ["SDI_VOICECRM_WRITERS"] = WRITERS
        cls.vc = load_voicecrm(SETTING)

    def test_the_writers_may_write(self):
        for name in ("Nick Garrish", "Andy Baxter", "James Gray", "Ian Jones"):
            with self.subTest(person=name):
                self.assertTrue(self.vc._may_write({"email": PEOPLE[name]}))

    def test_the_three_read_only_people_may_not(self):
        for name in ("Kayleigh Thornhill", "Charlotte Blackwell", "Matt Evans"):
            with self.subTest(person=name):
                self.assertFalse(self.vc._may_write({"email": PEOPLE[name]}),
                                 f"{name} is read-only and would be able to "
                                 f"change records")

    def test_being_mapped_to_rows_is_not_permission_to_change_them(self):
        kayleigh = {"email": PEOPLE["Kayleigh Thornhill"]}
        self.assertEqual(self.vc.owner_for(kayleigh), "KT")
        self.assertFalse(self.vc._may_write(kayleigh))


class NickAndIanTests(unittest.TestCase):
    """── 30 OCTOBER ───────────────────────────────────────────────────────
    Nick signs in as nick.garrish@sdidisplays.co.uk - the old domain - with
    his mailbox on @wearesdi.com. The settings were first written with the
    mailbox, and he was locked out of his own records. Both addresses are in
    now, so whichever he signs in with, he gets the same rows and can save.

    Ian Jones is PM on Nick's accounts and Nick asked for him to have write
    access. His own initials are in the PM Owner column, which the filter
    does not read, so mapping him to "IJ" would show him an empty list. He
    sees Nick's rows instead, which is what he works on.
    """

    @classmethod
    def setUpClass(cls):
        import os
        os.environ["SDI_VOICECRM_WRITERS"] = WRITERS
        cls.vc = load_voicecrm(SETTING)

    def rows(self, email):
        return accounts(self.vc.records_for("fake-token",
                                            self.vc.owner_for({"email": email})))

    NICKS = ["Ashby & Co", "Northgate Retail", "Thornbury Retail"]

    def test_nick_gets_his_rows_under_either_address(self):
        for address in ("nick.garrish@sdidisplays.co.uk", "Nick.Garrish@wearesdi.com"):
            with self.subTest(address=address):
                self.assertEqual(self.rows(address), self.NICKS)

    def test_nick_can_save_under_either_address(self):
        for address in ("nick.garrish@sdidisplays.co.uk", "nick.garrish@wearesdi.com"):
            with self.subTest(address=address):
                self.assertTrue(self.vc._may_write({"email": address}))

    def test_ian_sees_nicks_rows(self):
        self.assertEqual(self.rows("ian.jones@wearesdi.com"), self.NICKS)

    def test_ian_can_save(self):
        self.assertTrue(self.vc._may_write({"email": "ian.jones@wearesdi.com"}))

    def test_ian_does_not_see_the_row_his_initials_would_point_at(self):
        """The IJ row in the fake sheet stands for an AM Owner of IJ. Ian is
        mapped to NG, so it is not his - which is the point of not guessing
        "IJ" from his name."""
        self.assertNotIn("Somebody else's job", self.rows("ian.jones@wearesdi.com"))

    def test_the_read_only_three_are_still_read_only(self):
        for address in ("kayleigh.thornhill@wearesdi.com",
                        "charlotte.blackwell@wearesdi.com", "matt.evans@wearesdi.com"):
            with self.subTest(address=address):
                self.assertFalse(self.vc._may_write({"email": address}))


if __name__ == "__main__":
    unittest.main()
