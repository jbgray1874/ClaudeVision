"""A measurement run writes the SAME document. Only its name says so.

THIS FILE HAS BEEN WRONG TWICE, in opposite directions, and both are worth keeping on record
because the mistake each time was the same one: treating a document as the place to put a
control that belongs somewhere else.

  FIRST it SUPPRESSED the quote on an LLM-only run, arguing that a stamped quote can be
  forwarded, screenshotted or scrolled past, and a file that was never written cannot be sent.
  James: "we absolutely need to generate the same documents... everyone knows it's an LLM only
  run but we still run them." A comparison in which the two runs produce different SETS of
  documents is not a comparison.

  THEN it STAMPED a red block across the top — "LLM-ONLY MEASUREMENT RUN — NOT A QUOTATION",
  ending "do not send it to a customer and do not quote its total". James removed that too:
  "we've been through this.. The estimator takes responsibility.. remove this sort of alarming
  disclaimer. remove this red block entirely.. the lower section is missing.. again.."

THE SECOND REMOVAL IS THE SAME ARGUMENT AS THE FIRST, ONE STEP FURTHER IN. Suppressing the file
made the two runs incomparable at the folder level. Banding one of them in red makes them
incomparable at the page level: the quote is a one-page document, the block is 100mm of it, and
the half that gets pushed off the printed sheet is the half carrying the price breakdown. The
run that exists to be read against another became the one that cannot be read to the end.

And the block was answering a question nobody had asked. An estimator holding two documents
knows which button produced which. Telling a professional not to trust the thing you just
handed them is not a safeguard; it is declining to produce the artefact while producing it.

SO THE MARK IS IN THE FILENAME AND NOWHERE ELSE.

  ..._quote_LLM-ONLY.html   how a file is identified from a folder listing, an attachment box
                            or a share — the places where the wrong document actually gets
                            picked up. Two files called 10575-02_quote.html in one directory is
                            the failure this prevents, and it is a real one.

  the JOB REPORT            which readers ran and which were switched off, in full, in the
                            document written to be read rather than sent.

The invariant this file now holds is that the PAGE is identical either way. Anything that
distinguishes an LLM-only quote from a full-run quote on the page itself defeats the run.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import client_quote_html as q                                          # noqa: E402

SRC = (ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
# The comment block explaining the removal quotes the wording it exists to remove.
CODE = re.sub(r"#[^\n]*", " ", re.sub(r'"""(?:.|\n)*?"""', " ", SRC))


@pytest.fixture()
def summary_json(tmp_path):
    def _make(**extra):
        data = {
            "job_output_stem": "10575-02",
            "estimate_summary": {"workbook_equivalent_pricing": {"m105": 607.47},
                                 "estimate_workbook_inputs": {"assumed_job_quantity": 1}},
            "part_estimates": [],
        }
        data.update(extra)
        p = tmp_path / "summary.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p
    return _make


def _write(summary_json, tmp_path, monkeypatch, llm_only):
    monkeypatch.delenv("SDI_LLM_ONLY", raising=False)
    jp = summary_json(llm_only=llm_only) if llm_only else summary_json()
    return q.generate_quote_files(str(jp), out_dir=str(tmp_path), job_stem="10575-02")


# ── it is written, both ways ─────────────────────────────────────────────────

def test_a_measurement_run_still_produces_a_quote(summary_json, tmp_path, monkeypatch):
    """THE POINT OF THE RUN. Different document sets cannot be compared, and the quote is
    part of what is being measured."""
    out = _write(summary_json, tmp_path, monkeypatch, llm_only=True)
    assert out, "the quote was suppressed — the two runs no longer produce the same documents"
    assert Path(out).exists()


def test_the_filename_says_which_kind_of_run_it_was(summary_json, tmp_path, monkeypatch):
    """The one place the mark survives, because it is the one place a file is identified
    without being opened."""
    out = _write(summary_json, tmp_path, monkeypatch, llm_only=True)
    assert Path(out).name == "10575-02_quote_LLM-ONLY.html", Path(out).name


def test_an_ordinary_estimate_keeps_the_plain_name(summary_json, tmp_path, monkeypatch):
    out = _write(summary_json, tmp_path, monkeypatch, llm_only=False)
    assert Path(out).name == "10575-02_quote.html", Path(out).name


# ── and the page is the same page ────────────────────────────────────────────

def test_the_page_carries_no_banner(summary_json, tmp_path, monkeypatch):
    """James removed it: "remove this red block entirely". The estimator takes responsibility
    for the number; the document does not editorialise about its own reader."""
    html = Path(_write(summary_json, tmp_path, monkeypatch, llm_only=True)).read_text(
        encoding="utf-8")
    for gone in ("NOT A QUOTATION", "LLM-ONLY MEASUREMENT RUN", "do not quote its total",
                 "Do not send it to a customer"):
        assert gone not in html, f"the red block is back on the page: {gone!r}"


def test_the_measurement_run_makes_no_promise_it_cannot_keep(summary_json, tmp_path,
                                                              monkeypatch):
    """THE ONE THING ON THE PAGE THAT WAS A COMMITMENT RATHER THAN A FIGURE.

    James: "Drop 'Valid 30 days' on LLM-only. A measurement isn't an offer window. Keep
    indicative."

    Every price on the quote already says *indicative* — a number somebody will check. "Valid
    for 30 days" is different in kind: a promise, with a date on it, made off a pack one reader
    has seen. It is also the line most likely to survive being forwarded, because it reads as
    boilerplate and boilerplate is what nobody re-reads."""
    llm = Path(_write(summary_json, tmp_path, monkeypatch, llm_only=True)).read_text(
        encoding="utf-8")
    assert "Valid 30 days" not in llm and "Valid for" not in llm
    assert "30 days from quotation date" not in llm
    assert "Indicative" in llm, "the basis is no longer stated at all"


def test_the_difference_is_a_claim_REMOVED_never_a_warning_ADDED(summary_json, tmp_path,
                                                                  monkeypatch):
    """THE INVARIANT THE RUN DEPENDS ON, STATED PRECISELY.

    An LLM-only quote and a full-run quote are laid side by side to see what a one-reader BOM
    does to a customer-facing document. This file used to require them to render IDENTICALLY,
    which was right about the danger and too blunt about the remedy: dropping an offer window
    the run cannot support is not the same act as stamping a red banner across the page.

    So the rule is directional. The measurement run may say LESS than the full run. It may not
    say MORE — no banner, no disclaimer, no instruction to the reader about what to do with the
    document. A warning added is the engine editorialising about the thing being measured; a
    claim removed is the engine declining to assert what it does not know.

    Same JSON both ways, so every difference is one the mode introduced."""
    llm = Path(_write(summary_json, tmp_path, monkeypatch, llm_only=True)).read_text(
        encoding="utf-8")
    full = Path(_write(summary_json, tmp_path, monkeypatch, llm_only=False)).read_text(
        encoding="utf-8")

    def _words(html: str) -> set:
        text = re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>|data:[^\"')]+", " ", html,
                                              flags=re.S))
        return {w for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text)}

    added = _words(llm) - _words(full)
    # "Indicative" and "comparison" are the removal's replacement wording, not new claims.
    added -= {"Indicative", "comparison", "internal", "Basis"}
    assert not added, (
        f"the measurement quote says things the full quote does not: {sorted(added)} — a "
        f"difference the engine introduced, which is what the comparison then measures")


def test_nothing_reinstates_it_further_down_the_page(summary_json, tmp_path, monkeypatch):
    """A warning moved under the total is the same warning, read later. Stated against the
    source because a re-added block would most likely be appended near the footer, where a
    rendered-output check on the first screenful would not see it."""
    assert "_stamp_llm_only" not in CODE, "the stamping function is back"
    assert "LLM_ONLY_BANNER" not in CODE, "the banner constant is back"


def test_the_run_is_still_announced_on_the_console(summary_json, tmp_path, monkeypatch, capsys):
    """Removing the block from the page must not remove the fact from the operator. The person
    running the job is told which file was written and where to read what was switched off."""
    _write(summary_json, tmp_path, monkeypatch, llm_only=True)
    out = capsys.readouterr().out
    assert "vision model alone" in out
    assert "_quote_LLM-ONLY.html" in out


# ── the run in flight and the reader afterwards ──────────────────────────────

def test_the_environment_alone_is_enough(summary_json, tmp_path, monkeypatch):
    """generate_quote_files is also a CLI entry point run against a JSON written earlier, and
    the JSON of an older run may carry no llm_only key at all."""
    monkeypatch.setenv("SDI_LLM_ONLY", "1")
    out = q.generate_quote_files(str(summary_json()), out_dir=str(tmp_path), job_stem="10575-02")
    assert Path(out).name.endswith("_quote_LLM-ONLY.html")


def test_the_json_alone_is_enough(summary_json, tmp_path, monkeypatch):
    """And the other way: a JSON re-rendered days later, in a process that never set the
    variable, must still produce a marked filename."""
    monkeypatch.delenv("SDI_LLM_ONLY", raising=False)
    jp = summary_json(llm_only=True)
    out = q.generate_quote_files(str(jp), out_dir=str(tmp_path), job_stem="10575-02")
    assert Path(out).name.endswith("_quote_LLM-ONLY.html")
