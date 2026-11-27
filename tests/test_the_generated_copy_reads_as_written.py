r"""The generated copy reads as written, not as generated.

James Gray, 18 September 2026, on the covering note for 401912-02:

    "Weak generated copy: 'quantitys', 'set of explains'. Add a copy-quality test/linter for
     generated email text and prohibit raw engine instructions in email templates."

TWO SMALL THINGS THAT COST MORE THAN THEY LOOK. `_plural` appended "s" to anything, so the
section about quantity breaks read **"3 quantitys"** — in a document whose whole claim is
that its arithmetic can be trusted. And the opening offered "a set of explains you can work
with", which is not English and survived because nobody reads their own boilerplate.

A reader who finds two errors in the prose checks the numbers differently. That is the cost,
and it is why generated copy needs the same care as a figure.

THIS LINTS THE OUTPUT, NOT THE SOURCE. Six tests in this suite have matched commentary ABOUT
a thing rather than the thing; a copy check that greps the module would do exactly that. It
renders a real note and reads what a person would read.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimate_explained as EE  # noqa: E402


# ── the pluraliser ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("count,noun,expected", [
    (3, "quantity", "3 quantities"),
    (1, "quantity", "1 quantity"),
    (2, "line", "2 lines"),
    (2, "part number", "2 part numbers"),
    (2, "box", "2 boxes"),
    (2, "batch", "2 batches"),
    (2, "day", "2 days"),          # vowel + y stays a plain -s
    (0, "quantity", "0 quantities"),
])
def test_ordinary_english_plurals(count, noun, expected):
    assert EE._plural(count, noun) == expected


def test_an_irregular_plural_is_still_passed_explicitly():
    """A general pluraliser would be a library and a source of new wrong answers. The
    argument has always been there for the words English does not inflect by rule."""
    assert EE._plural(2, "die", "dies") == "2 dies"


def test_a_count_that_is_not_a_number_still_reads_as_english():
    assert EE._plural(None, "quantity") == "None quantities"


# ── and the copy a person actually reads ────────────────────────────────────────────

# A number followed by a noun pluralised by blindly appending "s": "3 quantitys", "2 batchs",
# "2 boxs". Deliberately NOT "...ss" — that matched "84 across" on the first run, and a linter
# that cries wolf is one somebody switches off.
_BAD_PLURALS = re.compile(r"\b\d+\s+\w*(?:[bcdfghjklmnpqrstvwxz]ys|chs|shs|xs|zs)\b")
# Phrases the note must never PRODUCE. The workbook's own row marker (`_INDICATIVE_TAG`) is
# deliberately not here: it is a cell on a sheet James has signed off, four tests assert it,
# and changing it is a separate decision. What this forbids is the note INSTRUCTING a person
# in the engine's vocabulary.
_ENGINE_SPEAK = (
    "AI market indication",
    "Overwrite anything tagged",
    "set of explains",
    "(s)",                      # "1 part number(s)" — the fault _plural exists to prevent
)


@pytest.fixture(scope="module")
def note_text():
    """A REAL covering note, rendered, with its markup stripped — what a person reads.

    Built from the covering-note suite's own fixture rather than a fresh one, so this lints
    the output somebody actually receives. An earlier version of this file grepped the module
    source instead and matched a COMMENT recounting a fault from 2026 — the seventh time in
    this suite a text search has found prose about a thing rather than the thing.
    """
    import importlib
    sibling = importlib.import_module("test_the_covering_note_says_what_the_estimate_costs")
    import tempfile
    d = Path(tempfile.mkdtemp())
    note = EE.covering_email(
        sibling._workbook(d / "12349-02_20260902_153051.xlsx"),
        sibling._scan(d / "12349-02.json"),
        client="fanatics",
        deliverables=[str(d / "12349-02.xlsx")],
    )
    return re.sub(r"<[^>]+>", " ", note["html"]) + " " + note["text"] + " " + note["subject"]


def test_no_number_is_followed_by_a_mis_pluralised_noun():
    """The check itself, proved against the string that failed: '3 quantitys'."""
    assert _BAD_PLURALS.search("3 quantitys"), "the linter cannot see the fault it exists for"
    assert not _BAD_PLURALS.search("3 quantities")
    assert not _BAD_PLURALS.search("2 boxes")


def test_the_note_a_person_receives_has_no_mis_pluralised_nouns(note_text):
    found = _BAD_PLURALS.findall(note_text)
    assert not found, f"the note reads as generated: {found}"


def test_the_opening_is_english(note_text):
    assert "set of explains" not in note_text


def test_no_engine_instruction_reaches_the_reader(note_text):
    """Internal system language on a document for a person."""
    for phrase in _ENGINE_SPEAK:
        assert phrase not in note_text, \
            f"engine language in a document for a person: {phrase!r}"


def test_the_report_and_the_note_use_the_same_words_for_a_researched_price():
    """Two documents describing one line in two vocabularies is how a reader ends up
    believing they are two different findings."""
    note = Path(EE.__file__.replace(".pyc", ".py")).read_text(encoding="utf-8")
    import job_report_html as J
    report = Path(J.__file__.replace(".pyc", ".py")).read_text(encoding="utf-8")
    assert "researched market price" in note
    assert "researched market price" in report
    for stale in ("AI market indication",):
        assert stale not in "\n".join(
            l for l in report.split("\n") if not l.lstrip().startswith("#"))
