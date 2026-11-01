"""The estimating app's question box is answered by grok-4.7 from the record chosen (D-615).

JG, 1 November 2026: "yes, switch it to grok-4.7", and among the priorities the same day,
"questions and walkthroughs pinned to the correct saved estimate". The box matched words
against the record; anything it did not expect fell through. The record it chose now goes to
the engine's question module, the lookup's answer with it; the lookup still answers when the
model cannot be had.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import estimating_job_tools as tools  # noqa: E402

RECORD = {
    "drawing_number": "12678-01-GA", "customer": "M&S",
    "final_estimate": {"totals": {"unit_gbp": 538.06, "material_gbp": 300.0,
                                  "labour_gbp": 238.06, "unit_cell": "Estimate!H62"},
                       "labour_rows": [{"operation": "Weld", "total_value_gbp": 90}],
                       "huge_trace": ["x" * 1000] * 50},
    "costed_job": {"lines": [{"part_number": "12678-01-003", "qty_per_unit": 2,
                              "description": "Side panel", "charged_ext_gbp": 41.2}] * 80,
                   "release": {"status": "provisional", "to_confirm": 3},
                   "decisions_required": [{"kind": "missing_price", "part": "12678-01-077"}],
                   "gaps": {"heavy": ["x"] * 100}},
    "drawing_reads": {"pages": ["big"] * 500},
}
ROUTES = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
POCKET = (BACKEND / "appportal" / "estimating-pocket.html").read_text(encoding="utf-8")
DESK = (BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")


class _Proc:
    def __init__(self, stdout):
        self.stdout, self.stderr = stdout, ""


class TheModelAnswersTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.python = Path(self.dir.name) / "python.exe"
        self.cli = Path(self.dir.name) / "estimate_qa.py"
        self.python.write_text("")
        self.cli.write_text("")
        self.sent = {}

    def _run(self, reply):
        def run(cmd, input=None, **kw):
            self.sent.update(cmd=cmd, payload=json.loads(input), kw=kw)
            if isinstance(reply, Exception):
                raise reply
            return _Proc("[env] Loaded C:\\ClaudeVision\\.env\n" + json.dumps(reply))
        return run

    def _ask(self, question, reply):
        return tools.answer_with_the_model(RECORD, question, engine_python=str(self.python),
                                           qa_cli=str(self.cli), run=self._run(reply),
                                           record_name="12678-01-GA_record.json",
                                           run_id="run-7")

    def test_the_models_answer_from_the_record_is_shown_and_named(self):
        said = self._ask("Why is labour high at 1 off?",
                         {"status": "answered", "answer": "Set-up is carried by one unit.",
                          "model": "grok-4.7", "sources": ["final_estimate.totals"],
                          "recorded": ["Unit cost £538.06 ex VAT at 1 off."],
                          "coverage_note": "Answered from part of the record: 40 of 80 parts.",
                          "refused_figures": []})
        self.assertEqual(said["recorded"], ["Unit cost £538.06 ex VAT at 1 off."])
        self.assertTrue(said["coverage_note"].startswith("Answered from part of the record"))
        self.assertEqual((self.sent["payload"]["record_name"], self.sent["payload"]["run_id"]),
                         ("12678-01-GA_record.json", "run-7"))
        self.assertEqual(said["answer"], "Set-up is carried by one unit.")
        self.assertEqual((said["answered_by"], said["model"]), ("grok-4.7", "grok-4.7"))
        self.assertEqual(said["sources"], ["final_estimate.totals"])

    def test_the_lookup_goes_with_it_and_is_kept(self):
        said = self._ask("what did it cost", {"status": "answered", "answer": "£538.06 a unit.",
                                              "model": "grok-4.7"})
        self.assertIn("Calculated unit total: £538.06", self.sent["payload"]["record_answer"])
        self.assertIn("Calculated unit total: £538.06", said["record_answer"])
        self.assertTrue(said["complete"])

    def test_what_the_service_reads_travels_whole_and_the_drawing_reads_stay(self):
        """D-616: every line, the release block and the open decisions go; the service
        chooses and counts what the model sees. The first cut sent 60 lines and no release."""
        self._ask("what did it cost", {"status": "answered", "answer": "x", "model": "grok-4.7"})
        sent = self.sent["payload"]["record"]
        self.assertNotIn("drawing_reads", sent)
        self.assertNotIn("huge_trace", sent["final_estimate"])
        self.assertNotIn("gaps", sent["costed_job"])
        self.assertEqual(sent["final_estimate"]["totals"]["unit_gbp"], 538.06)
        self.assertEqual(len(sent["costed_job"]["lines"]), 80)
        self.assertEqual(sent["costed_job"]["release"]["status"], "provisional")
        self.assertEqual(len(sent["costed_job"]["decisions_required"]), 1)
        self.assertEqual(self.sent["kw"]["timeout"], tools.ASK_TIMEOUT_SECONDS)
        self.assertLessEqual(tools.ASK_TIMEOUT_SECONDS, 85, "inside App Proxy's default")

    def test_when_the_model_cannot_answer_the_lookup_does(self):
        for reply in ({"status": "unavailable", "answer": "No answer came back."},
                      subprocess.TimeoutExpired("qa", 75), OSError("no engine")):
            with self.subTest(reply=type(reply).__name__):
                said = self._ask("what did it cost", reply)
                self.assertTrue(said["answer"].startswith("Calculated unit total: £538.06"))
                self.assertEqual((said["answered_by"], said["model"]), ("record lookup", ""))
                self.assertEqual(said["record_answer"], "")

    def test_no_engine_on_this_box_is_the_lookup(self):
        said = tools.answer_with_the_model(RECORD, "what did it cost",
                                           engine_python=str(Path(self.dir.name) / "none.exe"),
                                           qa_cli=str(self.cli), run=self._run({}))
        self.assertEqual(said["answered_by"], "record lookup")
        self.assertEqual(self.sent, {}, "nothing was run")

    def test_a_bad_question_is_refused_before_anything_is_asked(self):
        for bad in ("", "x" * 501):
            with self.subTest(bad=len(bad)):
                with self.assertRaises(ValueError):
                    self._ask(bad, {"status": "answered", "answer": "x"})
        self.assertEqual(self.sent, {})


class TheRouteAndPagesTests(unittest.TestCase):
    ROUTE = ROUTES.split('@router.post("/tools/ask")', 1)[1].split("\n# ══", 1)[0]

    def test_both_kinds_of_question_go_through_the_model(self):
        self.assertEqual(self.ROUTE.count("answer_with_the_model("), 2)
        self.assertEqual(self.ROUTE.count('qa_cli=str(_REPO_ROOT / "src" / "estimate_qa.py")'), 2)

    def test_a_model_failure_is_never_reported_as_an_unreadable_record(self):
        read = self.ROUTE.split("The saved run record cannot be safely read.", 1)[1]
        self.assertIn("answer_with_the_model(record", read)

    def test_the_pages_say_who_answered(self):
        self.assertIn('" · answered by " + j.answered_by', DESK)
        self.assertIn('"by " + a.model', POCKET)
        self.assertIn("Read from this saved record only.", POCKET)

    def test_the_pages_show_the_record_figures_the_lookup_and_the_coverage_beside_it(self):
        """D-616: the lookup was kept in the reply and shown nowhere."""
        for page, names in ((DESK, ('"From the record: " + j.recorded.join(" ")',
                                    '"Record lookup: " + j.record_answer',
                                    "j.coverage_note")),
                            (POCKET, ('"From the record: " + a.recorded.join(" ")',
                                      '"Record lookup: " + a.record_answer',
                                      "a.coverage_note"))):
            for name in names:
                with self.subTest(name=name):
                    self.assertIn(name, page)

    def test_each_question_names_its_record_and_run_to_the_service(self):
        self.assertIn('record_name=held["record_name"]', self.ROUTE)
        self.assertIn("record_name=path.name, run_id=run.run_id", self.ROUTE)


if __name__ == "__main__":
    unittest.main()
