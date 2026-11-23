"""The main runner's process was replaced at 12:13:49 (23 Nov 2026) while a job ran. The
next submission's build check saw the new process before its first check-in and stopped
the whole queue on "Runner build/health mismatch"; the runner was healthy on the same
build half a minute later. The check now waits for a runner mid-restart; a real mismatch
is still refused with the same words when the wait runs out."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("settled_batch", ROOT / "src/tti_concept_batch.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

GOOD = [{"online": True, "build": "abcdef12", "process_count": 1, "runner_id": "r1"},
        {"online": True, "build": "abcdef12", "process_count": 1, "runner_id": "r2"}]
RESTARTING = [{"online": True, "build": "abcdef12", "process_count": 1, "runner_id": "r1"},
              {"online": True, "build": "abcdef12", "process_count": None, "runner_id": "r2"}]


class Api:
    def __init__(self, answers):
        self.answers = list(answers)
    def runners(self):
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def test_a_runner_that_checks_back_in_does_not_stop_the_queue():
    waits = []
    api = Api([RESTARTING, RESTARTING, GOOD])
    b.settled_check_build(api, "abcdef12", 2, wait_s=300, sleep=waits.append)
    assert len(waits) == 2


def test_a_real_mismatch_is_still_refused_in_the_same_words():
    api = Api([RESTARTING])
    with pytest.raises(RuntimeError, match="Runner build/health mismatch: r2"):
        b.settled_check_build(api, "abcdef12", 2, wait_s=0, sleep=lambda _: None)


def test_the_batch_submits_through_the_settled_check():
    src = (ROOT / "src/tti_concept_batch.py").read_text(encoding="utf-8")
    assert "settled_check_build(api,expected,at_once,sleep=sleep)" in src
    assert "check_build(api.runners(),expected,at_once)" not in src
