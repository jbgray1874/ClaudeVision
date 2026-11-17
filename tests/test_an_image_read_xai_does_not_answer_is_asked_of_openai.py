"""AN IMAGE READ XAI DOES NOT ANSWER IS ASKED OF OPENAI (JG, 17 Nov 2026: "yes, 100 percent fall
back").

The drawing read already went to the OpenAI fallback when xAI gave no answer. The parts-list image
read and the concept image read did not: on the TTI batch a parts-list read sat at "60 s into try 1
of 4 (limit 600 s a try)" with nothing to fall back to, and a read xAI never answered was left NOT
done after the job's whole xAI limit.

Now any xAI failure on an image read (no answer, busy, an error, the job's xAI limit spent, no xAI
key) asks OpenAI the same question with the same page images at once, and says so. With no OpenAI
key the reader fails as it did before, so the read is still marked NOT done.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import openai  # noqa: E402

import _bom_vision_reader as bvr  # noqa: E402
import concept_scan as cs  # noqa: E402
import openai_fallback  # noqa: E402
import vision_fallback  # noqa: E402
import xai_models as xm  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class _XaiNeverAnswers:
    """Stands in for the xAI client: every request times out, and each is counted."""
    asked = 0

    def __init__(self, *a, **kw):
        self.chat = self
        self.completions = self

    def create(self, **kw):
        type(self).asked += 1
        raise TimeoutError("Request timed out.")


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setitem(xm._SPENT, "s", 0.0)
    monkeypatch.setenv("SDI_XAI_JOB_BUDGET_S", "1800")
    monkeypatch.setenv("SDI_XAI_RETRY_SECONDS", "0")
    monkeypatch.setenv("XAI_API_KEY", "dummy-for-test")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-for-test")
    monkeypatch.delenv("SDI_LLM_FALLBACK", raising=False)
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.delenv("SDI_DETERMINISTIC_ONLY", raising=False)
    _XaiNeverAnswers.asked = 0
    monkeypatch.setattr(openai, "OpenAI", _XaiNeverAnswers)
    asked = []

    def ask_image(prompt, pngs, client=None):
        asked.append((prompt, list(pngs)))
        return '{"rows": []}'
    monkeypatch.setattr(openai_fallback, "ask_image", ask_image)
    return asked


READERS = {
    "parts-list": lambda: bvr.call_vision_llm(PNG, "grok-test"),
    "concept": lambda: cs._call_vision_llm([PNG], "grok-test"),
}


@pytest.mark.parametrize("reader", sorted(READERS))
def test_an_image_read_xai_does_not_answer_is_answered_by_openai(setup, reader, capsys):
    out = READERS[reader]()
    assert out == '{"rows": []}'
    assert len(setup) == 1 and setup[0][1] == [PNG], "OpenAI is sent the same page image"
    assert setup[0][0], "and the same question"
    assert _XaiNeverAnswers.asked == 1, "xAI is not asked again once it gave no answer"
    assert vision_fallback.LAST_ANSWERED_BY.startswith("openai:")
    said = capsys.readouterr().out
    assert "xAI gave no answer" in said and "asking openai" in said and "openai answered" in said


@pytest.mark.parametrize("reader", sorted(READERS))
def test_without_an_openai_key_the_read_still_fails_and_is_not_done(setup, reader, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(Exception):
        READERS[reader]()
    assert setup == []


@pytest.mark.parametrize("reader", sorted(READERS))
def test_once_the_jobs_xai_limit_is_spent_openai_is_asked_without_asking_xai(setup, reader,
                                                                           monkeypatch):
    monkeypatch.setitem(xm._SPENT, "s", 5000.0)
    assert READERS[reader]() == '{"rows": []}'
    assert _XaiNeverAnswers.asked == 0
    assert len(setup) == 1


@pytest.mark.parametrize("reader", sorted(READERS))
def test_any_xai_error_goes_to_openai_not_only_a_timeout(setup, reader, monkeypatch):
    class Refused(_XaiNeverAnswers):
        def create(self, **kw):
            raise RuntimeError("Error code: 403 - credits exhausted")
    monkeypatch.setattr(openai, "OpenAI", Refused)
    assert READERS[reader]() == '{"rows": []}'
    assert len(setup) == 1


@pytest.mark.parametrize("reader", sorted(READERS))
def test_with_no_xai_key_openai_reads_the_image(setup, reader, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY")
    assert READERS[reader]() == '{"rows": []}'
    assert _XaiNeverAnswers.asked == 0


def test_the_fallback_switch_turns_the_image_fallback_off(setup, monkeypatch):
    monkeypatch.setenv("SDI_LLM_FALLBACK", "off")
    with pytest.raises(Exception):
        bvr.call_vision_llm(PNG, "grok-test")
    assert setup == []


def test_openai_is_sent_the_question_and_every_page_as_images():
    sent = {}

    class Client:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **kw):
            sent.update(kw)

            class C:
                finish_reason = "stop"

                class message:
                    content = "ok"

            class R:
                choices = [C]
            return R

    assert openai_fallback.ask_image("Q", [PNG, PNG], client=Client()) == "ok"
    parts = sent["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Q"}
    assert [p["type"] for p in parts[1:]] == ["image_url", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "temperature" not in sent
