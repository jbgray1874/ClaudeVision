"""The extract is asked to quote the drawing, and the cache can see that it was asked.

A prompt change the cache cannot see is a prompt change that does nothing: the run returns
the answer to the question asked before it, indefinitely, and looks exactly like an edit
with no effect.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import llm_full_extract as lfe  # noqa: E402


def test_the_schema_asks_for_evidence_on_every_route():
    assert '"evidence": ""' in lfe._PROMPT
    assert '"evidence_where": ""' in lfe._PROMPT


def test_the_rules_tell_it_to_quote_rather_than_paraphrase():
    """"P/C 30% GLOSS" is the evidence; "powder coating" is our reading of it. A field
    that holds the second cannot be checked against the drawing."""
    assert "Copy the drawing's own" in lfe._PROMPT
    assert "Do not paraphrase" in lfe._PROMPT


def test_an_empty_evidence_field_is_told_to_be_the_right_answer():
    """Otherwise the model fills the box with a plausible sentence, which removes the one
    signal that would have told anybody to look at that operation."""
    assert 'Leave "evidence" EMPTY' in lfe._PROMPT
    assert "never penalised" in lfe._PROMPT


def test_both_passes_carry_the_rule():
    """The two passes return the same shape; only whether they may fill an unstated field
    differs. A rule on one and not the other is two schemas wearing one name."""
    assert "EVIDENCE. For every route" in lfe._PROMPT
    assert "EVIDENCE. For every route" in lfe._INFER_PROMPT


# ---------------------------------------------------------------------------
# The cache has to see the change
# ---------------------------------------------------------------------------
def test_editing_the_prompt_changes_the_full_pass_key():
    before = lfe._cache_key("full", "doc", "grok", lfe._PROMPT, lfe.SYSTEM_TRANSCRIBE)
    after = lfe._cache_key("full", "doc", "grok", lfe._PROMPT + " ask for evidence",
                           lfe.SYSTEM_TRANSCRIBE)
    assert before != after


def test_editing_the_prompt_changes_the_inference_key():
    """This one keyed on the system message alone, so an edit to _INFER_PROMPT could not
    invalidate it."""
    source = (SRC / "llm_full_extract.py").read_text(encoding="utf-8")
    assert '_cache_key("infer", payload, model, SYSTEM_INFER, _INFER_PROMPT)' in source


def test_the_same_prompt_and_document_return_the_same_key():
    """The property the cache exists for: a re-run of the same job on the same code asks
    the same question and is entitled to the same answer."""
    a = lfe._cache_key("full", "doc", "grok", lfe._PROMPT, lfe.SYSTEM_TRANSCRIBE)
    b = lfe._cache_key("full", "doc", "grok", lfe._PROMPT, lfe.SYSTEM_TRANSCRIBE)
    assert a == b


def test_a_different_document_is_a_different_key():
    a = lfe._cache_key("full", "doc one", "grok", lfe._PROMPT, lfe.SYSTEM_TRANSCRIBE)
    b = lfe._cache_key("full", "doc two", "grok", lfe._PROMPT, lfe.SYSTEM_TRANSCRIBE)
    assert a != b
