"""A RUN THAT FILED NO COVERING NOTE IS NOT SENT LOOKING LIKE AN ESTIMATE (JG, 12 Nov 2026).

A job went out headed "SDI Intelligence estimate. not reported/unit at 1 off" over a list of
fourteen files: no note, no record, no report, no walkthrough. "The e-mail needs to be the
one earlier was": that one is the engine's own note, and this message is only what is sent
when the engine stopped before writing it. It now says so first.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))

import estimate_email as EE  # noqa: E402

RUN = {"drawing_number": "10000-04-00-GA", "client": "A Customer", "units": 1, "engine_price_gbp": None}
FILED = [{"path": "/out/10000-04-00-GA_20261112_165204.xlsx", "what": "the workbook"},
         {"path": "/out/10000-04-00-GA_run.log", "what": "the run log"},
         {"path": "/out/runner-2026-11-12.log", "what": "the runner's log"}]


def test_the_subject_and_the_first_words_say_it_is_incomplete_and_what_is_missing():
    m = EE.compose(RUN, FILED)
    assert m["subject"].startswith("10000-04-00-GA: INCOMPLETE RUN, not an estimate to use")
    for missing in ("the covering note", "the run's pinned record", "the report",
                    "the spoken walkthrough", "a unit price"):
        assert missing in m["subject"] and missing in m["text"]
    assert m["text"].startswith("INCOMPLETE RUN.") and "INCOMPLETE RUN." in m["html"]
    assert "10000-04-00-GA_run.log" in m["text"], "the files that were filed are still listed"
    assert "not reported/unit" not in m["subject"]


def test_the_engines_own_note_is_sent_as_it_is_when_the_run_filed_one(tmp_path):
    note = tmp_path / "10000-04-00-GA_20261112_165204_covering_email.html"
    note.write_text("<!-- subject: 10000-04-00-GA, PROVISIONAL. 1 off -->\n<p>the full note</p>", encoding="utf-8")
    m = EE.compose(RUN, FILED + [{"path": str(note)}])
    assert m["subject"] == "10000-04-00-GA, PROVISIONAL. 1 off" and "the full note" in m["html"]
    assert "INCOMPLETE" not in m["html"]
