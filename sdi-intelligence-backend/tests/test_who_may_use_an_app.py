"""One rule for who may use a gated app, shared by every surface.

Four apps each carried the same four lines: read a setting, split on commas,
compare the signed-in person's object ID. That works, and it means IT edits a
file on the server and restarts the service every time somebody joins or
leaves a team - for every app, every person, every time.

A list may now hold GROUP object IDs as well as people's, so "SDI TTI
Despatch" goes in SDI_TTI_OIDS once and Customer Services is managed in Entra
from then on. The app is no less restricted for it.

What must not drift:

  * every app keeps its OWN door. There is deliberately no portal-wide "anyone
    in this group" fallback: these apps are not interchangeable, and an empty
    list admits nobody rather than everybody;
  * the web app and the ChatGPT connector decide it the same way, from the
    same module - somebody in on one surface and out on the other is the bug
    found by the person who should not have seen the data;
  * a service principal or an API key is never a person;
  * and a group that never arrives is told apart from a person who is not in
    it, because they need different people to fix them.
"""
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import access                                                       # noqa: E402

GATED = {
    "SDI_TTI_OIDS": "tti_despatch_routes.py",
    "SDI_OPS_OIDS": "sdi_ops_routes.py",
    "SDI_ESTIMATOR_OIDS": "app.py",
}


def person(oid="person-1", groups=(), kind="user"):
    return {"kind": kind, "oid": oid, "groups": list(groups),
            "name": "A Person", "email": "a.person@wearesdi.com"}


class ANamedPersonStillGetsInTests(unittest.TestCase):
    """The lists that exist keep working exactly as they did."""

    ENV = {"APP": "CC53597A-C1B5-4BF9-B862-F63F7392FF81, 5acf6b37-147f-4468-bdb1-ecc3da1f1076"}

    def test_by_object_id_whatever_the_case(self):
        self.assertTrue(access.may_use(
            "APP", person("cc53597a-c1b5-4bf9-b862-f63f7392ff81"), self.ENV))
        self.assertTrue(access.may_use(
            "APP", person("5ACF6B37-147F-4468-BDB1-ECC3DA1F1076"), self.ENV))

    def test_somebody_else_is_refused(self):
        self.assertFalse(access.may_use("APP", person("someone-else"), self.ENV))

    def test_a_truncated_id_matches_nobody(self):
        """One character short is a different id, and it fails silently - the
        person is simply refused and nothing says the setting is a typo."""
        short = "5acf6b37-147f-4468-bdb1-ecc3da1f107"
        self.assertFalse(access.may_use("APP", person(short), self.ENV))


class AGroupOnTheListLetsItsMembersInTests(unittest.TestCase):
    GROUP = "11111111-2222-3333-4444-555555555555"

    def test_a_member_is_let_in_without_being_named(self):
        self.assertTrue(access.may_use(
            "APP", person("anybody", [self.GROUP]), {"APP": self.GROUP}))

    def test_case_does_not_matter_either_way(self):
        self.assertTrue(access.may_use(
            "APP", person("anybody", [self.GROUP.upper()]), {"APP": self.GROUP}))

    def test_a_different_group_is_refused(self):
        self.assertFalse(access.may_use(
            "APP", person("anybody", ["another-group"]), {"APP": self.GROUP}))

    def test_people_and_groups_can_be_mixed_in_one_setting(self):
        env = {"APP": f"{self.GROUP}, person-9"}
        self.assertTrue(access.may_use("APP", person("person-9"), env))
        self.assertTrue(access.may_use("APP", person("x", [self.GROUP]), env))
        self.assertFalse(access.may_use("APP", person("x", ["y"]), env))


class EmptyAdmitsNobodyTests(unittest.TestCase):
    """── THE FAILURE THAT IS SILENT ON THE DAY IT HAPPENS ─────────────────
    An empty list meaning "everyone" turns a missing line in a .env file - a
    file that is hand-edited over a share and is not in version control - into
    an open door, with nothing on any screen to show it."""

    def test_an_unset_setting_admits_nobody(self):
        self.assertFalse(access.may_use("NOT_SET", person(), {}))

    def test_a_setting_of_commas_and_spaces_admits_nobody(self):
        for empty in ("", "   ", ",", " , , ", "\t"):
            with self.subTest(value=repr(empty)):
                self.assertFalse(access.may_use("APP", person(), {"APP": empty}))

    def test_there_is_no_portal_wide_fallback(self):
        """Each app keeps its own door. A fallback that opened every app with
        no list of its own would be one setting away from opening all of them."""
        source = (BACKEND / "access.py").read_text(encoding="utf-8")
        self.assertNotIn("DEFAULT_SETTING", source)
        self.assertIn("EVERY APP KEEPS ITS OWN DOOR", source)
        # And nothing is admitted by another app's setting.
        env = {"SDI_TTI_OIDS": "a-group", "SDI_OPS_OIDS": ""}
        self.assertFalse(access.may_use("SDI_OPS_OIDS", person("x", ["a-group"]), env))


class OnlyAPersonTests(unittest.TestCase):
    def test_a_service_or_a_key_is_not_a_person(self):
        """These apps read live commercial data, so a read nobody can be named
        for is refused however valid the credential is."""
        for kind in ("service", "app", "key", "", None):
            with self.subTest(kind=kind):
                self.assertFalse(access.may_use(
                    "APP", person("person-1", kind=kind), {"APP": "person-1"}))

    def test_nothing_at_all_is_refused(self):
        for nobody in (None, {}, "person-1", 42, []):
            with self.subTest(user=nobody):
                self.assertFalse(access.may_use("APP", nobody, {"APP": "person-1"}))

    def test_a_person_with_no_object_id_is_refused(self):
        for blank in ("", None):
            with self.subTest(oid=blank):
                self.assertFalse(access.may_use(
                    "APP", person(blank), {"APP": "person-1"}))


class TheRefusalSaysWhichWallTests(unittest.TestCase):
    """Four walls, because they need four different things done."""

    def test_nobody_named_at_all(self):
        said = access.why_refused("SDI_TTI_OIDS", person(), {})
        self.assertIn("SDI_TTI_OIDS is empty", said)
        self.assertIn("GROUP", said)

    def test_not_a_person(self):
        said = access.why_refused("APP", person(kind="service"), {"APP": "x"})
        self.assertIn("signed-in person", said)

    def test_a_group_is_named_but_the_sign_in_carries_none(self):
        """── THE ONE THAT WOULD HAVE COST AN EVENING ──────────────────────
        Entra omits the groups claim unless the app registration is set to
        emit it. Until that is done every token says "groups": [] and a group
        in a setting matches nobody - which looks exactly like "that person is
        not in the group" and is fixed by somebody else entirely."""
        said = access.why_refused("APP", person("x", []), {"APP": "a-group"})
        self.assertIn("carried no group at all", said)
        self.assertIn("'groups' claim", said)

    def test_simply_not_on_the_list(self):
        said = access.why_refused("APP", person("x", ["b"]), {"APP": "a"})
        self.assertIn("not on the list", said)
        self.assertIn("/api/me", said)
        self.assertIn("an admin account is a different account", said)

    def test_no_refusal_ever_prints_what_is_in_the_setting(self):
        """It names the setting. Printing its contents would hand a stranger
        the object IDs of everybody who IS allowed."""
        secret = "11111111-2222-3333-4444-555555555555"
        for user in (person("x"), person("x", ["b"]), person(kind="service")):
            said = access.why_refused("APP", user, {"APP": secret})
            with self.subTest(user=user.get("kind")):
                self.assertNotIn(secret, said)


class EveryGatedAppUsesItTests(unittest.TestCase):
    """One rule, one place to get right - and one place to change."""

    def test_each_app_asks_the_shared_rule(self):
        for setting, filename in GATED.items():
            source = (BACKEND / filename).read_text(encoding="utf-8")
            with self.subTest(app=filename):
                self.assertIn(f'access.may_use("{setting}"', source)

    def test_none_of_them_still_splits_the_setting_itself(self):
        """A second copy of the rule is a second thing to get wrong, and it
        would not learn about groups."""
        for setting, filename in GATED.items():
            source = (BACKEND / filename).read_text(encoding="utf-8")
            with self.subTest(app=filename):
                self.assertNotIn(f'os.getenv("{setting}", "").split(",")', source)

    def test_the_chatgpt_connectors_share_it_too(self):
        identity = (BACKEND / "connector_identity.py").read_text(encoding="utf-8")
        self.assertIn("access.may_use", identity)
        self.assertNotIn('os.getenv(setting, "").split(",")', identity)

    def test_the_private_assistant_is_deliberately_not_on_this(self):
        """It is one person's mailbox, gated by its own owner check and its own
        Microsoft registration. A group would be the wrong shape entirely."""
        routes = (BACKEND / "private_email_routes.py").read_text(encoding="utf-8")
        self.assertNotIn("access.may_use", routes)


if __name__ == "__main__":
    unittest.main()
