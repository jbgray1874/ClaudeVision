"""A measurement run writes the SAME documents, and the quote says what it is.

THIS FILE ONCE ASSERTED THE OPPOSITE, and the reasoning was wrong in a way worth keeping on
record. It suppressed the client quote on an LLM-only run, arguing that a stamped quote can be
forwarded, screenshotted or scrolled past, and a file that was never written cannot be sent.

James overruled it: "we absolutely need to generate the same documents... everyone knows it's
an LLM only run but we still run them."

He is right, and the reason is the purpose of the run. An LLM-only run exists to be COMPARED
against a full one. A comparison in which the two runs produce different SETS of documents is
not a comparison — and withholding the quote hides the very thing being measured: what a
customer-facing document would have said off a BOM that one reader produced. The risk it was
guarding against is real but it is a handling risk, and handling risks are answered by making
the document unmistakable, not by deleting it.

SO IT IS MARKED IN THE TWO PLACES A FILE IS IDENTIFIED WITHOUT BEING READ TO THE END:

  the FILENAME               ..._quote_LLM-ONLY.html — a folder listing, an attachment box,
                             a share. Two files called 10575-02_quote.html in one directory is
                             how the wrong one gets attached.
  the FIRST THING ON THE PAGE   above the letterhead, not below the total. A warning under the
                             total is read after the reader has already decided what the
                             document is.

An ordinary estimate is untouched: it keeps its name and gets no banner, however many
invariants it fails, because that is a draft somebody works from.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import client_quote_html as q                                          # noqa: E402


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
    out = q.generate_quote_files(str(jp), out_dir=str(tmp_path), job_stem="10575-02")
    return out


# ── it is written, both ways ─────────────────────────────────────────────────

def test_a_measurement_run_still_produces_a_quote(summary_json, tmp_path, monkeypatch):
    """THE POINT OF THE RUN. Different document sets cannot be compared, and the quote is
    part of what is being measured."""
    out = _write(summary_json, tmp_path, monkeypatch, llm_only=True)
    assert out, "the quote was suppressed — the two runs no longer produce the same documents"
    assert Path(out).exists()


def test_the_filename_says_which_kind_of_run_it_was(summary_json, tmp_path, monkeypatch):
    out = _write(summary_json, tmp_path, monkeypatch, llm_only=True)
    assert Path(out).name == "10575-02_quote_LLM-ONLY.html", Path(out).name


def test_an_ordinary_estimate_keeps_the_plain_name(summary_json, tmp_path, monkeypatch):
    out = _write(summary_json, tmp_path, monkeypatch, llm_only=False)
    assert Path(out).name == "10575-02_quote.html", Path(out).name


# ── and it says so before anything else ──────────────────────────────────────

def test_the_banner_is_the_first_thing_on_the_page(summary_json, tmp_path, monkeypatch):
    """Above the letterhead. Under the total it is read after the reader has decided what the
    document is."""
    out = _write(summary_json, tmp_path, monkeypatch, llm_only=True)
    html = Path(out).read_text(encoding="utf-8")
    assert "NOT A QUOTATION" in html
    body = html.lower().find("<body")
    banner = html.find("LLM-ONLY MEASUREMENT RUN")
    assert banner > body, "the banner is not inside the document body"
    # nothing of the quote proper before it
    assert "£607.47" not in html[:banner], "the price appears above the warning"


def test_the_banner_says_what_was_switched_off_and_what_not_to_do(summary_json, tmp_path,
                                                                  monkeypatch):
    out = _write(summary_json, tmp_path, monkeypatch, llm_only=True)
    html = Path(out).read_text(encoding="utf-8")
    for phrase in ("deterministic BOM reader", "DXF", "SolidWorks",
                   "Do not send it to a customer", "do not quote its total"):
        assert phrase in html, f"the banner does not say: {phrase}"


def test_the_banner_explains_why_the_document_exists_at_all(summary_json, tmp_path, monkeypatch):
    """Otherwise the obvious reading is that somebody produced a quote off a measurement run by
    mistake — which is exactly what a reader should NOT conclude, because it is deliberate and
    it is what makes the comparison possible."""
    out = _write(summary_json, tmp_path, monkeypatch, llm_only=True)
    assert "so the two can be compared" in Path(out).read_text(encoding="utf-8")


def test_an_ordinary_quote_carries_no_banner(summary_json, tmp_path, monkeypatch):
    """A warning on every quote is a warning nobody reads on the one that needs it."""
    out = _write(summary_json, tmp_path, monkeypatch, llm_only=False)
    assert "NOT A QUOTATION" not in Path(out).read_text(encoding="utf-8")


# ── the run in flight and the reader afterwards ──────────────────────────────

def test_the_environment_alone_is_enough(summary_json, tmp_path, monkeypatch):
    """generate_quote_files is also a CLI entry point run against a JSON written earlier, and
    the JSON of an older run may carry no llm_only key at all."""
    monkeypatch.setenv("SDI_LLM_ONLY", "1")
    jp = summary_json()
    out = q.generate_quote_files(str(jp), out_dir=str(tmp_path), job_stem="10575-02")
    assert Path(out).name.endswith("_quote_LLM-ONLY.html")


def test_the_json_alone_is_enough(summary_json, tmp_path, monkeypatch):
    """And the other way: a JSON re-rendered days later, in a process that never set the
    variable, must still produce a marked document."""
    monkeypatch.delenv("SDI_LLM_ONLY", raising=False)
    jp = summary_json(llm_only=True)
    out = q.generate_quote_files(str(jp), out_dir=str(tmp_path), job_stem="10575-02")
    assert Path(out).name.endswith("_quote_LLM-ONLY.html")


def test_the_stamp_survives_the_quote_markup_changing():
    """Inserted after <body> when there is one and prepended when there is not, so a change to
    the quote's own template cannot silently drop the only warning on the page."""
    assert "NOT A QUOTATION" in q._stamp_llm_only("<p>no body tag here</p>")
