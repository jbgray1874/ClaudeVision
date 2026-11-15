"""A REQUEST TO xAI HAS A STATED LIMIT AND SAYS IT IS WAITING (15 Nov 2026).

Two estimates sat at three times their usual length in the full-pack read, the log silent. The
client's defaults were a 600 s limit and two retries of its own, inside this module's four
tries: one read could wait two hours and print nothing. The client now makes one request per
try with the limit named, and a line each minute says a request is still out.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import xai_models  # noqa: E402


def test_the_client_makes_one_request_per_try_with_the_limit_named(monkeypatch):
    monkeypatch.delenv("SDI_XAI_TIMEOUT_S", raising=False)
    assert xai_models.client_budget() == {"timeout": 600.0, "max_retries": 0}
    monkeypatch.setenv("SDI_XAI_TIMEOUT_S", "240")
    assert xai_models.client_budget()["timeout"] == 240.0
    monkeypatch.setenv("SDI_XAI_TIMEOUT_S", "1")
    assert xai_models.client_budget()["timeout"] == 30.0, "a limit no request can meet"
    monkeypatch.setenv("SDI_XAI_TIMEOUT_S", "soon")
    assert xai_models.client_budget()["timeout"] == 600.0


def test_a_request_still_out_is_said_and_a_quick_one_says_nothing():
    said = []

    def slow():
        time.sleep(0.35)
        return "answer"
    assert xai_models.call_with_retry(slow, "m", what="the drawing read", say=said.append,
                                      waiting_every_s=0.1) == "answer"
    waiting = [m for m in said if "still waiting for xAI on the drawing read" in m]
    assert len(waiting) >= 2 and "try 1 of" in waiting[0] and "limit" in waiting[0]
    n = len(said)
    time.sleep(0.25)
    assert len(said) == n, "the waiting line went on after the answer came"
    quick = []
    assert xai_models.call_with_retry(lambda: "now", "m", say=quick.append, waiting_every_s=0.1) == "now"
    assert quick == []


def test_the_waiting_line_names_the_try_it_is_on(monkeypatch):
    monkeypatch.setenv("SDI_XAI_RETRY_SECONDS", "0.01")
    said, calls = [], []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("request timed out")
        time.sleep(0.25)
        return "second"
    assert xai_models.call_with_retry(fn, "m", say=said.append, sleep=lambda s: None,
                                      waiting_every_s=0.1) == "second"
    assert any("try 2 of 2" in m and "still waiting" in m for m in said)
    assert any("timeout" in m and "try 1 of 2 failed" in m for m in said)


def test_the_drawing_read_builds_its_client_with_that_budget(monkeypatch):
    import llm_full_extract as lfe
    seen = {}

    class _Client:
        def __init__(self, **kw):
            seen.update(kw)
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

        def _create(self, **kw):
            msg = types.SimpleNamespace(content="read")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")],
                                         usage=None, model=kw.get("model"))
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_Client))
    monkeypatch.setenv("XAI_API_KEY", "k")
    monkeypatch.setenv("SDI_XAI_TIMEOUT_S", "300")
    fn = next(getattr(lfe, n) for n in dir(lfe)
              if callable(getattr(lfe, n)) and getattr(getattr(lfe, n), "__code__", None) is not None
              and "user_content" in getattr(lfe, n).__code__.co_varnames[:4]
              and "OpenAI" in getattr(lfe, n).__code__.co_names)
    try:
        fn("some-model", "what is on this sheet")
    except Exception:                                                # noqa: BLE001
        pass
    assert seen.get("timeout") == 300.0 and seen.get("max_retries") == 0
