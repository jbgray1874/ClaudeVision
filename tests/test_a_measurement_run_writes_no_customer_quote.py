"""The most dangerous file this engine writes, produced off a run that measured a model.

WHAT WAS ON DISK. The 10575-02 LLM-only run of 30/08 12:31 filed
`1057502V2UprightDisplay_quote.html`: SDI letterhead, "Quotation 10575-02 — V2 Upright
Display", a unit price of £607.47, valid 30 days, and a "what's included" list naming laser,
weld, powder and pack. The word "indicative" appeared once. "Read by a language model alone"
appeared nowhere.

The same run's Decision Report said, in capitals, INSUFFICIENT DATA — DO NOT QUOTE FROM THIS
TOTAL, credible 26%, DXF on 0 of 18 fabricated parts. James's verdict on reading the quote:
"Do not send this."

AND MAIN.PY ALREADY BELIEVED THIS GATE EXISTED:

    # None = deliberately suppressed by the credibility gate, which has
    # already said why. Do not print a path that does not exist.

generate_quote_files always wrote the file and always returned a path. A safety documented at
the call site and missing from the callee is worse than no safety at all, because it stops the
next person looking for one.

SUPPRESSED RATHER THAN STAMPED. A stamped quote can be forwarded, screenshotted, or have its
banner scrolled past. A file that was never written cannot be sent. An LLM-only run exists to
measure the model; a measurement has no customer.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import client_quote_html as cq                                          # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("SDI_LLM_ONLY", raising=False)


def _summary(tmp_path, **kw):
    d = {"job_output_stem": "10575-02-V2UprightDisplay",
         "parts": [], "unit_cost_gbp": 607.47}
    d.update(kw)
    p = tmp_path / "10575-02.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def test_no_quote_is_written_when_the_json_says_the_model_read_it_alone(tmp_path):
    out = cq.generate_quote_files(str(_summary(tmp_path, llm_only=True)), out_dir=str(tmp_path))
    assert out is None, "a customer quote was produced from a measurement run"
    assert not list(tmp_path.glob("*_quote.html")), (
        "the file was written anyway — returning None is not enough, nothing may reach disk")


def test_no_quote_is_written_when_the_run_in_flight_is_llm_only(tmp_path, monkeypatch):
    """The environment answers for the run happening now — the JSON is stamped at the end of
    it, and the quote is generated inside the same process."""
    monkeypatch.setenv("SDI_LLM_ONLY", "1")
    out = cq.generate_quote_files(str(_summary(tmp_path)), out_dir=str(tmp_path))
    assert out is None
    assert not list(tmp_path.glob("*_quote.html"))


def test_both_signals_are_read_because_one_of_them_is_always_gone(tmp_path, monkeypatch):
    """This is also a CLI entry point run against a JSON days later, when no environment
    describes the run; and the JSON is stamped only at the end, after the quote is written on
    some paths. Either alone leaves a hole."""
    src = (ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
    at = src.index("def generate_quote_files")
    body = src[at:at + 3000]
    assert 'summary.get("llm_only")' in body, "the recorded flag is not read"
    assert 'SDI_LLM_ONLY' in body, "the run in flight is not read"


def test_an_ordinary_estimate_still_gets_its_quote(tmp_path):
    """The gate must be narrow. Every real job produces this document, and a run that merely
    has blocking invariants — most of them do — is still an estimate somebody drafts from."""
    out = cq.generate_quote_files(str(_summary(tmp_path, blocking=11)), out_dir=str(tmp_path))
    assert out is not None, "the quote is suppressed on an ordinary estimate"
    assert Path(out).exists()


def test_the_call_site_no_longer_documents_a_safety_that_is_absent():
    """The comment that made this invisible. It is only true now because the callee returns
    None; if the gate is ever removed, this fails rather than the comment quietly going stale
    again."""
    main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "deliberately suppressed by the credibility gate" in main, (
        "the call site no longer explains why a None comes back")
    cqs = (ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
    at = cqs.index("def generate_quote_files")
    assert "return None" in cqs[at:at + 3000], (
        "main.py documents a suppression the generator cannot perform")


def test_the_run_says_out_loud_that_it_withheld_the_quote(capsys, tmp_path):
    """A deliverable that silently does not appear reads as a run that failed to produce it.
    The estimator watching the log is the person who would otherwise go looking."""
    cq.generate_quote_files(str(_summary(tmp_path, llm_only=True)), out_dir=str(tmp_path))
    said = capsys.readouterr().out
    assert "NOT WRITTEN" in said, said
    assert "vision model alone" in said, said


def test_main_stamps_the_kind_of_run_onto_the_json():
    """The JSON outlives the process. Parity, the report builders and this generator all read
    it later, and an environment variable answers for none of them."""
    main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    at = main.index("_canon_json2 = (summary.get")
    body = main[at:at + 2000]
    assert '_d["llm_only"] = True' in body, (
        "the summary JSON is never told the run was a measurement, so anything reading it "
        "afterwards treats it as an ordinary estimate")
