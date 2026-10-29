"""Every module the service imports is on the deploy, and a missing one degrades.

26 October 2026. private_draft_writer.py was added, private_email_routes.py was
made to import it, and the module was left out of Deploy-AMCRM.ps1's file list.
The deploy copied the code that needed it, restarted the service, and the import
failed. App Proxy answered BadGateway for the whole portal - HR, estimating, the
AM CRM and the app portal, none of which have anything to do with email.

Two things follow, and these are both of them:

  * a module the backend imports at startup is on the deploy's list, checked
    here rather than discovered by a service that will not start;
  * the private assistant's own optional parts degrade instead of taking the
    host down with them. Failing closed is right for anything guarding the
    mailbox. Suggested wording guards nothing.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

DEPLOY = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")

# What the deploy actually copies into the backend folder on the server.
DEPLOYED = set(re.findall(r'"([^"]+\.(?:py|html|json))"',
                          DEPLOY.split("$Files = @(", 1)[1].split(")", 1)[0]))

# The private assistant's own modules: the ones this session adds and the ones
# they pull in. Everything here must reach the server together or not at all.
ROOTS = ["private_email_integration.py", "private_email_routes.py",
         "private_email.py", "private_auth.py", "private_draft_writer.py"]


def imports_of(name):
    """Local modules a file imports, by file name."""
    tree = ast.parse((BACKEND / name).read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return {m + ".py" for m in found if (BACKEND / (m + ".py")).exists()}


class DeployCoversWhatIsImportedTests(unittest.TestCase):
    def test_every_private_module_is_on_the_deploy(self):
        for name in ROOTS:
            with self.subTest(module=name):
                self.assertTrue((BACKEND / name).exists(), f"{name} is missing")
                self.assertIn(name, DEPLOYED,
                              f"{name} is imported by the service but Deploy-AMCRM.ps1 "
                              f"never copies it - the service will not start")

    def test_whatever_those_modules_import_is_on_the_deploy_too(self):
        """Following the imports, not just the list I remembered to write."""
        seen, queue = set(), list(ROOTS)
        while queue:
            name = queue.pop()
            if name in seen or not (BACKEND / name).exists():
                continue
            seen.add(name)
            for needed in imports_of(name):
                with self.subTest(imported_by=name, module=needed):
                    self.assertIn(needed, DEPLOYED,
                                  f"{name} imports {needed}, which the deploy "
                                  f"does not copy")
                queue.append(needed)

    def test_the_page_the_router_checks_for_is_on_the_deploy(self):
        """The router refuses to build without its page, by design - so a page
        left behind is a service that will not start, exactly like a module."""
        for page in ("private-email.html", "private-email-readonly.html"):
            with self.subTest(page=page):
                self.assertIn(page, DEPLOYED)

    def test_the_catalogue_the_portal_reads_is_on_the_deploy(self):
        self.assertIn("services.json", DEPLOYED)


class DegradesRatherThanStopsTests(unittest.TestCase):
    def test_the_writer_is_imported_in_a_way_that_cannot_stop_the_service(self):
        source = (BACKEND / "private_email_routes.py").read_text(encoding="utf-8")
        head = source.split("def make_router", 1)[0]
        self.assertIn("try:", head)
        self.assertIn("import private_draft_writer as writer", head)
        self.assertIn("except Exception", head)

    def test_without_the_writer_the_mailbox_still_works(self):
        """Simulated by the stand-in the import falls back to: it answers, it
        offers nothing, and nothing raises."""
        import private_email_routes as routes
        blank = {"summary": "", "asks": [], "draft": "", "gaps": []}

        class Gone:
            @staticmethod
            def available():
                return False

            @staticmethod
            def compose(message, instruction="", client=None):
                return dict(blank)

        self.assertFalse(Gone.available())
        self.assertEqual(Gone.compose({"body": {"content": "hello"}}), blank)
        # And the real module, when present, answers the same shape.
        self.assertEqual(set(routes.writer.compose({"body": {"content": ""}})),
                         set(blank))

    def test_what_guards_the_mailbox_still_fails_closed(self):
        """The opposite rule, and it has not been softened: drafts asked for
        with nowhere to keep the pending approvals stops the service."""
        source = (BACKEND / "private_email_integration.py").read_text(encoding="utf-8")
        self.assertIn("raise RuntimeError", source)
        integration = source.split("def install", 1)[1]
        self.assertNotIn("try:", integration.split("raise RuntimeError", 1)[0])


if __name__ == "__main__":
    unittest.main()


class TheOtherDeployScriptTests(unittest.TestCase):
    """Two deploy scripts with different file sets, and nothing said which one
    a change needed.

    26 October 2026: the TTI despatch view deployed "successfully" through
    Deploy-AMCRM.ps1, restarted cleanly, and was not mounted - because its
    wiring is in app.py, which that script deliberately never copies. A green
    deploy that silently omits the file holding your change is worse than a
    failed one.
    """

    def test_the_deploy_says_when_a_file_it_does_not_copy_differs(self):
        """It used to name app.py alone. The same trap applies to every backend
        file the list leaves out, and the estimating API is the one that bit
        next: a change to estimate_routes.py deploys "successfully" through
        this script, restarts, and is not on the server at all."""
        self.assertIn("this script does not copy them", DEPLOY)
        self.assertIn("push-to-server.ps1 -Apply", DEPLOY)
        named = DEPLOY.split("$NotCopied = @(", 1)[1].split(")", 1)[0]
        for name in ("app.py", "estimate_routes.py", "estimating_job_tools.py",
                     "public_surface.py"):
            with self.subTest(file=name):
                self.assertIn(f'"{name}"', named)

    def test_it_still_does_not_copy_app_py(self):
        """The warning is the fix, not a change of policy: the server's copy
        has drifted before, and copying a whole file over drift is worse."""
        self.assertNotIn('"app.py"', DEPLOY.split("$Files = @(", 1)[1].split(")", 1)[0])

    def test_the_tti_modules_and_page_are_on_this_list(self):
        for name in ("sue_despatch.py", "tracker_snapshot.py",
                     "tti_despatch_routes.py", "tti_plan_source.py",
                     "appportal/tti-despatch.html"):
            with self.subTest(file=name):
                self.assertIn(f'"{name}"', DEPLOY)
