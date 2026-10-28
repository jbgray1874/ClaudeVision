"""The Despatch Plan comes from SharePoint, read with the asker's own rights.

26 October 2026: "I cannot verify a UNC copy of the Despatch Plan. The verified
source is this SharePoint workbook, not a server share path. Don't construct a
UNC path from that URL."

Quite right, so none is constructed. The properties here:

  * the workbook is fetched as the SIGNED-IN PERSON, so access is theirs and a
    403 is a true answer about them rather than a prompt to retry wider;
  * the site and the file are configuration - a request carries a date, and
    there is no path, URL or site a caller can name;
  * the copy lives for the life of the request and is never written to disk;
  * the answer carries SharePoint's own lastModifiedDateTime, because an
    answer dated "now" about a workbook saved last Tuesday is the lie that
    matters in a despatch question.
"""
import ast
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import tti_plan_source as plan  # noqa: E402

SOURCE = (BACKEND / "tti_plan_source.py").read_text(encoding="utf-8")
ROUTES = (BACKEND / "tti_despatch_routes.py").read_text(encoding="utf-8")
LOADER = (BACKEND / "tti_data.py").read_text(encoding="utf-8")

SITE = "sdidisplays.sharepoint.com:/sites/SUESOSOD"
FILE = "General/TTI Delivery Schedule 2021 V3.xlsx"


class Reply:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code, self._body, self.content = status, body or {}, content

    def json(self):
        return self._body


class Graph:
    """Answers the two calls and records what was asked."""

    def __init__(self, facts=None, content=b"PK-not-a-real-xlsx", status=200,
                 site_status=None):
        self.site_status = site_status
        self.facts = facts if facts is not None else {
            "name": "TTI Delivery Schedule 2021 V3.xlsx", "size": 5120,
            "lastModifiedDateTime": "2026-10-23T14:05:00Z", "eTag": '"{ABC},7"'}
        self.content, self.status, self.calls = content, status, []

    def get(self, url, headers=None, params=None, **kw):
        self.calls.append((url, headers, params))
        if "/drive/root:" not in url:                 # resolving the site
            return Reply(self.site_status or self.status, body={"id": "site-abc"})
        if url.endswith("/content"):
            return Reply(self.status, content=self.content)
        return Reply(self.status, body=self.facts)

    def close(self):
        pass


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        import os
        for key, value in (("SDI_TTI_PLAN_SITE", SITE), ("SDI_TTI_PLAN_PATH", FILE)):
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)

    def test_the_site_and_the_file_are_settings_not_parameters(self):
        self.assertTrue(plan.configured())
        tree = ast.parse(SOURCE)
        # Nothing in this module takes a URL, a path or a site from a caller.
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                names = {a.arg for a in node.args.args}
                self.assertEqual(names & {"url", "path", "site", "href"}, set(),
                                 f"{node.name} accepts a caller-supplied location")

    def test_nothing_builds_a_unc_path(self):
        for invented in ("\\\\sdidisplays", "\\\\sdi-dc01", "sharepoint.com\\\\"):
            self.assertNotIn(invented, SOURCE)

    def test_spaces_in_the_file_name_are_escaped_and_folders_are_not(self):
        url = plan._item_url("site-abc", "/content")
        self.assertIn("TTI%20Delivery%20Schedule%202021%20V3.xlsx", url)
        self.assertIn("/drive/root:/General/", url)
        self.assertTrue(url.endswith(":/content"))

    def test_without_configuration_it_says_what_to_set(self):
        import os
        os.environ.pop("SDI_TTI_PLAN_SITE", None)
        self.assertFalse(plan.configured())
        with self.assertRaises(plan.PlanUnavailable) as caught:
            plan.fetch_plan("a-token")
        self.assertIn("SDI_TTI_PLAN_SITE", str(caught.exception))


class ReadAsThePersonTests(unittest.TestCase):
    def setUp(self):
        import os
        for key, value in (("SDI_TTI_PLAN_SITE", SITE), ("SDI_TTI_PLAN_PATH", FILE)):
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)

    def test_the_signed_in_persons_token_is_what_is_presented(self):
        graph = Graph()
        plan.fetch_plan("sues-delegated-token", client=graph)
        for url, headers, _ in graph.calls:
            self.assertEqual(headers["Authorization"], "Bearer sues-delegated-token")

    def test_no_token_is_refused_rather_than_retried_as_the_service(self):
        graph = Graph()
        with self.assertRaises(plan.PlanUnavailable):
            plan.fetch_plan("", client=graph)
        self.assertEqual(graph.calls, [], "it must not ask Graph without a token")

    def test_a_403_is_a_true_answer_about_that_person(self):
        with self.assertRaises(plan.PlanUnavailable) as caught:
            plan.fetch_plan("tok", client=Graph(status=403))
        said = str(caught.exception)
        self.assertIn("your access", said.lower())
        self.assertIn("reads the workbook as you", said)

    def test_the_other_refusals_are_told_apart(self):
        for status, expected in ((404, "renamed or moved"),
                                 (401, "sign-in has expired"),
                                 (400, "could not understand the request"),
                                 (500, "refused to supply")):
            with self.subTest(status=status):
                with self.assertRaises(plan.PlanUnavailable) as caught:
                    plan.fetch_plan("tok", client=Graph(status=status))
                self.assertIn(expected, str(caught.exception))

    def test_an_enormous_workbook_is_refused_before_it_is_downloaded(self):
        graph = Graph(facts={"size": 200 * 1024 * 1024,
                             "lastModifiedDateTime": "2026-10-23T14:05:00Z"})
        with self.assertRaises(plan.PlanUnavailable):
            plan.fetch_plan("tok", client=graph)
        self.assertEqual([u for u, _, _ in graph.calls if u.endswith("/content")], [])


class TheSaveTimeIsSharePointsTests(unittest.TestCase):
    def setUp(self):
        import os
        for key, value in (("SDI_TTI_PLAN_SITE", SITE), ("SDI_TTI_PLAN_PATH", FILE)):
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)

    def test_the_plans_own_last_saved_time_comes_back(self):
        _, saved, version = plan.fetch_plan("tok", client=Graph())
        self.assertEqual(saved, datetime(2026, 10, 23, 14, 5, tzinfo=timezone.utc))
        self.assertIn("ABC", version)

    def test_an_unreadable_timestamp_does_not_become_a_wrong_one(self):
        graph = Graph(facts={"size": 10, "lastModifiedDateTime": "not a date"})
        _, saved, _ = plan.fetch_plan("tok", client=graph)
        # Unknown beats wrong: it falls back to now rather than inventing a save.
        self.assertAlmostEqual(saved.timestamp(),
                               datetime.now(timezone.utc).timestamp(), delta=10)

    def test_an_unchanged_file_is_not_downloaded_again(self):
        """Six views now ask the same workbook six questions, and a voice
        assistant will ask two or three in a row. The metadata request still
        happens with THIS person's token every time - so their access still
        decides - and only the download and the parse are skipped."""
        graph = Graph()
        _, _, version = plan.fetch_plan("tok", client=graph)
        data, saved, same = plan.fetch_plan("tok", client=graph,
                                            known_version=version)
        self.assertIsNone(data, "the content was fetched although nothing changed")
        self.assertEqual(same, version)
        self.assertEqual(saved, datetime(2026, 10, 23, 14, 5, tzinfo=timezone.utc))

    def test_a_changed_file_is_downloaded(self):
        graph = Graph()
        data, _, _ = plan.fetch_plan("tok", client=graph,
                                     known_version='"OLD-ETAG"')
        self.assertIsNotNone(data)

    def test_every_route_reads_the_plan_as_of_its_save_not_todays_date(self):
        self.assertIn("auth.graph_token(request)", ROUTES)
        self.assertIn("st_mtime", LOADER)
        for handler in ("def leaving_on(", "def search(", "def chase_list(",
                        "def overdue(", "def morning_summary(", "def quality("):
            body = ROUTES.split(handler, 1)[1].split("\n    @router", 1)[0]
            with self.subTest(handler=handler):
                self.assertIn("as_of=plan.saved.date()", body)


class NothingTouchesTheDiskTests(unittest.TestCase):
    def test_the_workbook_is_parsed_from_memory(self):
        reader = (BACKEND / "tracker_snapshot.py").read_text(encoding="utf-8")
        self.assertIn("io.BytesIO(data)", reader)
        self.assertIn("read_schedule_bytes", LOADER)
        for writing in ("open(", "write_bytes", "write_text", "NamedTemporary"):
            self.assertNotIn(writing, SOURCE)
        # The loader holds the parsed rows in memory and writes nothing. The
        # one open() it has is the local-snapshot fallback, through
        # tracker_snapshot, which reads.
        for writing in ("write_bytes", "write_text", "NamedTemporary", '", "w"'):
            self.assertNotIn(writing, LOADER)

    def test_a_file_that_is_not_a_workbook_is_refused_with_a_reason(self):
        from tracker_snapshot import read_schedule_bytes
        with self.assertRaises(ValueError) as caught:
            read_schedule_bytes(b"this is not a spreadsheet")
        self.assertIn("does not open as a workbook", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class TheSiteIsResolvedFirstTests(unittest.TestCase):
    """The obvious URL chains two colon-paths and Graph answers 400.

    26 October 2026, the first live read: "SharePoint refused to supply the
    plan (400)." It had refused nothing - the colon form may appear once per
    URL, and /sites/host:/sites/NAME: followed by /drive/root:/file: is two.
    The word "refused" then sent the next look at SharePoint permissions that
    were perfectly fine.
    """

    def setUp(self):
        import os
        plan._RESOLVED.clear()
        self.addCleanup(plan._RESOLVED.clear)
        for key, value in (("SDI_TTI_PLAN_SITE", SITE), ("SDI_TTI_PLAN_PATH", FILE)):
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)

    def test_the_site_is_looked_up_before_the_file(self):
        graph = Graph()
        plan.fetch_plan("tok", client=graph)
        first = graph.calls[0][0]
        self.assertTrue(first.endswith("/sites/" + SITE), first)
        for url, _, _ in graph.calls[1:]:
            self.assertIn("/sites/site-abc/drive/root:/", url)

    def test_no_url_addresses_the_site_and_the_file_by_colon_path_at_once(self):
        """The thing that produced the 400, stated as a rule.

        "root:/General/file.xlsx:/content" is ONE colon-path, opened and
        closed, and is correct. What Graph will not parse is a site colon-path
        AND a drive colon-path in the same URL."""
        graph = Graph()
        plan.fetch_plan("tok", client=graph)
        for url, _, _ in graph.calls:
            with self.subTest(url=url):
                site_by_path = "sharepoint.com:" in url
                file_by_path = "/drive/root:" in url
                self.assertFalse(site_by_path and file_by_path, url)

    def test_the_site_is_resolved_once_and_remembered(self):
        graph = Graph()
        plan.fetch_plan("tok", client=graph)
        plan.fetch_plan("tok", client=graph)
        lookups = [u for u, _, _ in graph.calls if "/drive/root:" not in u]
        self.assertEqual(len(lookups), 1, "the site id does not change between questions")

    def test_a_400_says_it_is_our_address_not_your_access(self):
        with self.assertRaises(plan.PlanUnavailable) as caught:
            plan.fetch_plan("tok", client=Graph(site_status=400))
        said = str(caught.exception)
        self.assertIn("not your access", said)
        self.assertIn("SDI_TTI_PLAN_SITE", said)
        self.assertNotIn("refused", said)

    def test_an_unrecognised_site_names_the_setting_and_its_shape(self):
        graph = Graph()
        graph.get = lambda url, headers=None, params=None, **kw: Reply(200, body={})
        with self.assertRaises(plan.PlanUnavailable) as caught:
            plan.fetch_plan("tok", client=graph)
        self.assertIn("sdidisplays.sharepoint.com:/sites/SUESOSOD", str(caught.exception))
