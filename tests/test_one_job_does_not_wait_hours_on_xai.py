"""ONE JOB DOES NOT WAIT HOURS ON XAI (JG, 17 Nov 2026: "ONE JOB TAKEN 4 HOURS").

11762-00-GA2 asked xAI targeted question after targeted question, each allowed four tries of up
to ten minutes, and ran 4 h 18 min against a usual 29. Each estimate runs in its own process, so
the time this process has spent on xAI is the job's, and it has a limit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import xai_models as xm  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setitem(xm._SPENT, "s", 0.0)
    monkeypatch.setenv("SDI_XAI_JOB_BUDGET_S", "1800")
    monkeypatch.setenv("SDI_XAI_RETRY_SECONDS", "20,60,120")
    return Clock()


def _slow(clock, seconds, fail=True):
    def fn():
        clock.t += seconds
        if fail:
            raise TimeoutError("Request timed out.")
        return "answer"
    return fn


def test_questions_stop_being_asked_once_the_job_has_spent_its_xai_time(fresh):
    said = []
    clock = fresh
    for _ in range(3):                                   # three questions that each time out
        with pytest.raises(Exception):
            xm.call_with_retry(_slow(clock, 600), "grok", what="a targeted question",
                               sleep=lambda s: None, say=said.append, waiting_every_s=0, clock=clock)
    assert xm.job_spent_s() <= 1800 + 600, "a question went on asking after the limit"
    asked = []
    with pytest.raises(xm.XaiJobBudgetSpent):
        xm.call_with_retry(lambda: asked.append(1), "grok", sleep=lambda s: None, say=said.append,
                           waiting_every_s=0, clock=clock)
    assert asked == [], "xAI was asked after the job's limit was spent"
    assert any("not asked" in m and "SDI_XAI_JOB_BUDGET_S" in m for m in said)
    assert xm.busy_kind(xm.XaiJobBudgetSpent("xAI timeout: limit spent")) == "timeout", \
        "callers must treat it as an xAI that stayed busy"


def test_a_job_whose_answers_come_back_is_not_limited(fresh):
    clock = fresh
    for _ in range(20):
        assert xm.call_with_retry(_slow(clock, 30, fail=False), "grok", sleep=lambda s: None,
                                  say=lambda m: None, waiting_every_s=0, clock=clock) == "answer"
    assert xm.job_spent_s() == 600


def test_the_limit_can_be_set_and_switched_off(fresh, monkeypatch):
    monkeypatch.setenv("SDI_XAI_JOB_BUDGET_S", "off")
    assert xm.job_budget_s() == 0
    xm._SPENT["s"] = 99999
    assert xm.call_with_retry(lambda: "ok", "grok", sleep=lambda s: None, say=lambda m: None,
                              waiting_every_s=0, clock=fresh) == "ok"
    monkeypatch.setenv("SDI_XAI_JOB_BUDGET_S", "10")
    assert xm.job_budget_s() == 60, "never under a minute"
