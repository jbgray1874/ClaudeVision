"""Claude stands in when xAI stays busy or has no key (JG, 10 Nov 2026), through the one text call
every drawing read and targeted question makes, and the read says who answered it."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import claude_fallback as cf                                       # noqa: E402
import llm_full_extract as lfe                                     # noqa: E402


class Busy(Exception):
    status_code = 429

    def __str__(self):
        return "Error code: 429 - resource-exhausted: The model is currently at capacity"


def _fake_openai(monkeypatch, exc=None, text="xai answer"):
    calls = []

    class _Completions:
        def create(self, **kw):
            calls.append(kw)
            if exc is not None:
                raise exc
            msg = types.SimpleNamespace(content=text)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    class OpenAI:
        def __init__(self, **kw):
            self.chat = types.SimpleNamespace(completions=_Completions())
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=OpenAI))
    return calls


@pytest.fixture
def claude(monkeypatch):
    asked = []
    monkeypatch.setenv("SDI_XAI_RETRY_SECONDS", "0")
    monkeypatch.setattr(cf, "available", lambda: True)
    monkeypatch.setattr(cf, "ask", lambda system, user, **kw: asked.append((system, user)) or
                        "claude answer")
    return asked


def test_xai_busy_after_its_retries_is_answered_by_claude_and_said(monkeypatch, claude, capsys):
    monkeypatch.setenv("XAI_API_KEY", "x")
    _fake_openai(monkeypatch, exc=Busy())
    assert lfe._call_llm("the question", "grok-4.7", system="sys") == "claude answer"
    assert claude == [("sys", "the question")], "the same question, system prompt and all"
    assert lfe.LAST_ANSWERED_BY == f"claude:{cf.model()}"
    out = capsys.readouterr().out
    assert "xAI stayed busy (capacity): asking Claude" in out


def test_no_xai_key_is_answered_by_claude(monkeypatch, claude):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert lfe._call_llm("q", "grok-4.7") == "claude answer"


def test_an_xai_answer_is_xais_and_claude_is_not_asked(monkeypatch, claude):
    monkeypatch.setenv("XAI_API_KEY", "x")
    _fake_openai(monkeypatch, text="xai answer")
    assert lfe._call_llm("q", "grok-4.7") == "xai answer"
    assert claude == [] and lfe.LAST_ANSWERED_BY == "grok-4.7"


def test_an_error_that_is_not_busy_is_raised_not_handed_to_claude(monkeypatch, claude):
    monkeypatch.setenv("XAI_API_KEY", "x")

    class BadKey(Exception):
        status_code = 401
    _fake_openai(monkeypatch, exc=BadKey("Incorrect API key"))
    with pytest.raises(BadKey):
        lfe._call_llm("q", "grok-4.7")
    assert claude == []


def test_without_claude_a_busy_xai_is_raised_as_before(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "x")
    monkeypatch.setenv("SDI_XAI_RETRY_SECONDS", "0")
    monkeypatch.setattr(cf, "available", lambda: False)
    _fake_openai(monkeypatch, exc=Busy())
    with pytest.raises(Busy):
        lfe._call_llm("q", "grok-4.7")


def test_the_fallback_needs_the_key_and_can_be_switched_off(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not cf.available()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("SDI_LLM_FALLBACK", "off")
    assert not cf.available()
    assert cf.model() == "claude-opus-5-5" and cf.effort() == "medium"


def test_claude_is_asked_streamed_with_the_refusal_fallback_and_a_refusal_is_not_an_answer():
    seen = {}

    class _Stream:
        def __init__(self, msg):
            self.msg = msg

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return self.msg

    def _client(stop="end_turn"):
        msg = types.SimpleNamespace(stop_reason=stop, stop_details=None, content=[
            types.SimpleNamespace(type="thinking", thinking=""),
            types.SimpleNamespace(type="text", text="the read")])

        def stream(**kw):
            seen.update(kw)
            return _Stream(msg)
        return types.SimpleNamespace(beta=types.SimpleNamespace(
            messages=types.SimpleNamespace(stream=stream)))
    assert cf.ask("sys", "q", client=_client()) == "the read"
    assert seen["model"] == "claude-opus-5-5" and seen["system"] == "sys"
    assert seen["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in seen["betas"]
    assert "temperature" not in seen
    with pytest.raises(RuntimeError):
        cf.ask("sys", "q", client=_client("refusal"))


def test_an_older_sdk_without_the_fallback_parameter_still_reads():
    calls = []

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return types.SimpleNamespace(stop_reason="end_turn", stop_details=None, content=[
                types.SimpleNamespace(type="text", text="old sdk read")])

    def stream(**kw):
        calls.append(sorted(kw))
        if "fallbacks" in kw:
            raise TypeError("stream() got an unexpected keyword argument 'fallbacks'")
        return _Stream()
    client = types.SimpleNamespace(beta=types.SimpleNamespace(
        messages=types.SimpleNamespace(stream=stream)))
    assert cf.ask("sys", "q", client=client) == "old sdk read"
    assert "fallbacks" in calls[0] and "fallbacks" not in calls[1] and "output_config" in calls[1]
