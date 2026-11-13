"""A NOTE FILED WITH THE RUN AFTERWARDS WAS NOT THE MESSAGE (12 Nov 2026).

Three runs went out in the service's short form; once their covering notes were recovered,
the audit said each e-mail's message "was" the covering note. It was not.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))

import price_audit as pa  # noqa: E402

BOOK = "10000-01-GA_20261112_171728.xlsx"
NOTE = "10000-01-GA_20261112_171728_covering_email.html"
FILES = [{"name": BOOK, "path": "/s/" + BOOK}, {"name": NOTE, "path": "/s/" + NOTE}]


def _run(**email):
    return {"drawing_number": "10000-01-GA", "started_at": 0.0,
            "email_result": dict({"sent": True, "recipients": ["a@b.c"], "attached": [BOOK]}, **email)}


def test_a_recovered_run_says_the_short_form_went_and_the_note_came_later():
    e = pa.email_evidence(dict(_run(), recovered_at="2026-11-12 18:40:00"), FILES)
    assert e["message_was_short_form"] and "short form" in e["message_note"] and NOTE in e["message_note"]


def test_the_recorded_subject_decides_it_from_now_on():
    short = pa.email_evidence(_run(subject="SDI Intelligence estimate. not reported/unit at 1 off. 10000-01-GA"), FILES)
    assert short["message_was_short_form"]
    full = pa.email_evidence(_run(subject="10000-01-GA, PROVISIONAL. 991.84/unit at 1 of"), FILES)
    assert full["message_note"] == NOTE and not full["message_was_short_form"]


def test_a_run_whose_note_went_with_it_is_unchanged():
    e = pa.email_evidence(_run(attached=[BOOK, NOTE]), FILES)
    assert e["message_note"] == NOTE and not e["message_was_short_form"]


def test_the_service_keeps_the_subject_of_what_it_sent():
    src = (ROOT / "sdi-intelligence-backend" / "estimate_email.py").read_text(encoding="utf-8")
    assert 'result.setdefault("subject", subject)' in src and '"attached": attached, "subject": subject,' in src
