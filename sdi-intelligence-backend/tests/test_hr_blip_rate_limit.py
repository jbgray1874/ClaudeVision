"""BrightHR rate limiting: one pause for every worker, and one Blip run at a time.

On the server, nearly every Blip query came back 429 because two runs overlapped
and each worker backed off alone; the run ended degraded and the push refused it.
"""
import os
import time

import pytest

import hr_blip
import hr_config as cfg


class Resp:
    def __init__(self, status, items=None, headers=None):
        self.status_code = status
        self._items = items or []
        self.headers = headers or {}

    def json(self):
        return {"items": self._items}


class NoWait(hr_blip._Throttle):
    """Records the pauses asked for without waiting them out."""

    def __init__(self):
        super().__init__()
        self.pauses = []

    def wait(self):
        pass

    def pause(self, seconds):
        self.pauses.append(seconds)
        return True


def test_a_rate_limited_query_is_retried_until_it_answers(monkeypatch):
    replies = [Resp(429), Resp(429, headers={"Retry-After": "3"}), Resp(200, items=[{"start": "x"}])]
    monkeypatch.setattr(hr_blip.requests, "post", lambda *a, **k: replies.pop(0))
    throttle = NoWait()

    clockings, ok = hr_blip._query_one("tok", "EMP-1", "2026-10-19T17:52:26Z", throttle)

    assert ok is True and clockings == [{"start": "x"}]
    assert throttle.pauses == [10, 3]


def test_retry_after_from_brighthr_is_honoured_and_capped():
    assert hr_blip._retry_after(Resp(429, headers={"Retry-After": "7"}), 0) == 7
    assert hr_blip._retry_after(Resp(429, headers={"Retry-After": "600"}), 0) == hr_blip.MAX_PAUSE
    assert hr_blip._retry_after(Resp(429), 1) == 20          # no header: 10s, 20s, ...


def test_a_429_pauses_every_worker_not_just_the_one_refused():
    throttle = hr_blip._Throttle()
    assert throttle.pause(0.2) is True
    assert throttle.pause(0.1) is False                       # already held longer
    started = time.monotonic()
    throttle.wait()                                           # another worker
    assert time.monotonic() - started >= 0.15


def test_a_query_refused_every_time_is_a_failure_not_an_empty_result(monkeypatch):
    monkeypatch.setattr(hr_blip.requests, "post", lambda *a, **k: Resp(429))
    throttle = NoWait()

    clockings, ok = hr_blip._query_one("tok", "EMP-1", "2026-10-19T17:52:26Z", throttle)

    assert ok is False and clockings == []
    assert len(throttle.pauses) == hr_blip.MAX_ATTEMPTS


@pytest.fixture
def snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "HR_SNAPSHOT_DIR", str(tmp_path))
    return tmp_path


def test_a_second_run_while_one_is_going_does_not_query(snapshots, monkeypatch):
    (snapshots / "blip.lock").write_text("123 running")
    monkeypatch.setattr(hr_blip, "_get_token",
                        lambda: pytest.fail("a busy run must not reach BrightHR"))

    summary = hr_blip.run_blip()

    assert summary["status"] == "busy"
    assert "already running" in summary["warnings"][0]
    assert (snapshots / "blip.lock").exists()                 # the other run's lock


def test_a_lock_left_by_a_dead_run_is_cleared(snapshots, monkeypatch):
    lock = snapshots / "blip.lock"
    lock.write_text("123 died")
    old = time.time() - (hr_blip.LOCK_STALE_MINUTES + 5) * 60
    os.utime(lock, (old, old))
    monkeypatch.setattr(hr_blip, "_run_blip", lambda: {"status": "ok"})

    assert hr_blip.run_blip()["status"] == "ok"
    assert not lock.exists()                                  # released after the run


def test_the_lock_is_released_when_the_run_fails(snapshots, monkeypatch):
    def boom():
        raise RuntimeError("BrightHR token refused")
    monkeypatch.setattr(hr_blip, "_run_blip", boom)

    with pytest.raises(RuntimeError):
        hr_blip.run_blip()
    assert not (snapshots / "blip.lock").exists()
