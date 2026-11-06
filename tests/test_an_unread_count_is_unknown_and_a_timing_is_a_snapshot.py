"""An unread count is unknown, not nought; an advisory item is counted without becoming a
blocker; and a timing snapshot is compared whole, never by summing its inclusive stages (D-581).

Reporting must not erase advisories or redefine the release gate to match a count, and a
reporting failure cannot assert that nothing is open. From the Codex "Programme Robust"
package of 22 Oct 2026, merged.
"""
from __future__ import annotations

import ast
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import quote_story  # noqa: E402
from timing_comparison import compare, runs_from_history  # noqa: E402


class ReviewCounts(unittest.TestCase):
    def record(self, kinds, draft):
        return {"schema": "costed_job.v2", "decisions_required": [
            {"kind": k, "part_number": str(i), "question": "Confirm"}
            for i, k in enumerate(kinds)],
            "release": {"draft": draft, "outstanding": int(draft)}}

    def test_advisory_only_is_visible_without_changing_release(self):
        record = self.record(["indicative_rate"], False)
        before = copy.deepcopy(record)
        self.assertEqual(quote_story.open_items(record), 1)
        self.assertEqual(record, before)

    def test_mixed_review_count_includes_advisory(self):
        record = self.record(["market_figure"] * 5 + ["indicative_rate"], True)
        self.assertEqual(quote_story.open_items(record), 6)

    def test_empty_is_zero(self):
        self.assertEqual(quote_story.open_items(self.record([], False)), 0)

    def test_error_is_not_zero(self):
        with patch("costed_facts.outstanding_summary", side_effect=ValueError("broken")):
            self.assertEqual(quote_story.open_items({}), -1)
        for fn in (quote_story._sourced_words, quote_story._traced_words):
            self.assertIn("could not be read", fn({"open_items": -1}))

    def test_malformed_count_is_unknown(self):
        for value in (True, "6", -2, 3.5):
            with patch("costed_facts.outstanding_summary", return_value={"total": value}):
                self.assertEqual(quote_story.open_items({}), -1)


class Timings(unittest.TestCase):
    def run_record(self, total, stages):
        return dict(identity=["job", "product", "customer", "1", "150"],
                    finished_at="now", total_seconds=total, phases=stages)

    def test_nested_stages_do_not_inflate_wall_time(self):
        result = compare(self.run_record(100, {"parent": 90, "child": 80}),
                         self.run_record(80, {"parent": 70, "child": 60}))
        self.assertEqual(result["seconds_saved"], 20)

    def test_quantity_mismatch_refused(self):
        a = self.run_record(100, {})
        b = copy.deepcopy(a)
        b["identity"][-1] = "200"
        with self.assertRaises(ValueError):
            compare(a, b)

    def test_slower_run_has_negative_saving(self):
        self.assertEqual(compare(self.run_record(100, {}), self.run_record(110, {}))
                         ["seconds_saved"], -10)

    def test_invalid_snapshot_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.csv"
            path.write_text("finished_at,stem,build,total_seconds,kind,name,seconds\n"
                            "now,j,b,nan,phase,x,2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                runs_from_history(path, "j")

    def test_main_remains_syntax_valid_and_brackets_match(self):
        tree = ast.parse((ROOT / "src/main.py").read_text(encoding="utf-8-sig"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "_time_stage"
                 and n.args and isinstance(n.args[0], ast.Constant)
                 and str(n.args[0].value).startswith("enrichment_")]
        names = {n.args[0].value for n in calls}
        self.assertEqual(len(names), 5)
        for name in names:
            self.assertEqual({n.args[1].value for n in calls if n.args[0].value == name},
                             {True, False})

if __name__ == "__main__":
    unittest.main()
