"""A SUBMIT THAT GOT NO ANSWER IS RECONCILED BEFORE ANYTHING IS SENT AGAIN (15 Nov 2026).

Row 3's pack was 65 files with its models. The service was still taking it in when the batch's
wait ran out, and the row was written down as "not queued" while the service may have queued
it. Run again, that is the same estimate twice. The batch now asks the service whether it holds
a run for the drawing, started since the request left, before it says anything.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import live_enquiry_runner as ler  # noqa: E402
import tti_pricer as tp  # noqa: E402


class _Service:
    def __init__(self, runs):
        self.runs, self.asked = runs, 0

    def recent(self, limit=100):
        self.asked += 1
        return {"runs": self.runs(self.asked) if callable(self.runs) else self.runs}


def _run(drawing="12181-00-GA", source="tti", queued_at=None, run_id="abc123"):
    return {"run_id": run_id, "drawing_number": drawing, "source": source,
            "queued_at": time.time() if queued_at is None else queued_at}


def _quiet(_m):
    pass


def test_the_run_the_service_queued_is_found_and_followed():
    asked_at = time.time() - 1
    s = _Service([_run("12353-13-GA", run_id="other"), _run(run_id="mine")])
    assert tp.adopt_after_no_answer(s, "12181-00-GA", asked_at, sleep=lambda x: None, say=_quiet) == "mine"


def test_a_run_that_appears_a_little_later_is_still_found():
    asked_at = time.time() - 1
    s = _Service(lambda n: [] if n < 3 else [_run(run_id="late")])
    assert tp.adopt_after_no_answer(s, "12181-00-GA", asked_at, sleep=lambda x: None, say=_quiet) == "late"
    assert s.asked == 3


def test_an_older_run_another_drawing_or_another_source_is_not_taken():
    asked_at = time.time()
    s = _Service([_run(queued_at=asked_at - 3600, run_id="yesterday"),
                  _run("12181-00-GA2", run_id="sibling"),
                  _run(source="self-running", run_id="theirs")])
    assert tp.adopt_after_no_answer(s, "12181-00-GA", asked_at, wait_s=30, every_s=15,
                                    sleep=lambda x: None, say=_quiet) is None
    assert s.asked == 3, "it must ask for the whole wait, then stop"


def test_a_service_that_cannot_be_asked_gives_no_run_and_does_not_wait_for_ever():
    class Dead:
        def recent(self, limit=100):
            raise ler.PortalError(0, "no answer")
    assert tp.adopt_after_no_answer(Dead(), "12181-00-GA", time.time(), wait_s=30, every_s=15,
                                    sleep=lambda x: None, say=_quiet) is None


def test_the_batch_follows_the_found_run_and_sends_nothing_twice(tmp_path, monkeypatch):
    from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal, _areas, _args
    from test_the_tracker_batch_runs_the_rows_named_on_their_own_briefs_and_never_lists_the_share_in_silence import _tracker
    sheet = _tracker(tmp_path, [("TTI-10234", "Counter", "", "", 4)])
    _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)

    class Slow(FakePortal):
        sent = 0

        def start(self, body):
            Slow.sent += 1
            self.started.append(body)
            raise ler.PortalError(0, "the portal did not answer (timed out)")

        def recent(self, limit=100):
            return {"runs": [_run("TTI-10234", run_id="r1")]}
    portal = Slow()
    rep = tp.run_batch(_args(sheet), portal=portal, status_path=None, sleep=lambda s: None)
    row = rep["rows"][0]
    assert Slow.sent == 1, "the request was sent again"
    assert row["run_id"] == "r1" and "nothing was sent twice" in row["resumed"]
    assert row["state"] != "not queued"


def test_with_no_run_on_the_service_the_row_says_so_and_what_to_check(tmp_path, monkeypatch):
    from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal, _areas, _args
    from test_the_tracker_batch_runs_the_rows_named_on_their_own_briefs_and_never_lists_the_share_in_silence import _tracker
    sheet = _tracker(tmp_path, [("TTI-10234", "Counter", "", "", 4)])
    _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)

    class Gone(FakePortal):
        def start(self, body):
            raise ler.PortalError(0, "the portal did not answer (timed out)")

        def recent(self, limit=100):
            return {"runs": []}
    rep = tp.run_batch(_args(sheet), portal=Gone(), status_path=None, sleep=lambda s: None)
    row = rep["rows"][0]
    assert row["state"] == "not queued" and "check Grid Control before running the row again" in row["why"]


def test_a_row_whose_last_request_got_no_answer_takes_up_the_run_the_service_holds(tmp_path, monkeypatch):
    """Row 3: the batch wrote 'not queued', the service ran the job. Run again, the batch must
    take that run up, not send a second."""
    from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal, _areas, _args
    from test_the_tracker_batch_runs_the_rows_named_on_their_own_briefs_and_never_lists_the_share_in_silence import _tracker
    sheet = _tracker(tmp_path, [("TTI-10234", "Counter", "", "", 4)])
    _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)
    status = tmp_path / "status.json"

    class NoAnswer(FakePortal):
        def start(self, body):
            raise ler.PortalError(0, "the portal did not answer (timed out)")

        def recent(self, limit=100):
            return {"runs": []}
    first = tp.run_batch(_args(sheet), portal=NoAnswer(), status_path=status, sleep=lambda s: None)
    assert first["rows"][0]["state"] == "not queued"

    class Later(FakePortal):
        def start(self, body):
            self.started.append(body)
            return {"run_id": "second"}

        def recent(self, limit=100):
            return {"runs": [_run("TTI-10234", run_id="first")]}

        def status(self, run_id):
            return {"status": "done", "quantity_prices": [{"quantity": 4, "unit_gbp": 12.5}],
                    "output_path": f"X:\\out\\{run_id}"}
    portal = Later()
    again = tp.run_batch(_args(sheet), portal=portal, status_path=status, sleep=lambda s: None)
    row = again["rows"][0]
    assert portal.started == [], "a second request was sent for a run the service already holds"
    assert row["run_id"] == "first" and "taken up" in row["resumed"]

    # the contrast: the service holds no such run, so the row is sent
    (tmp_path / "another batch").mkdir()
    status2 = tmp_path / "another batch" / "status.json"          # its own ledger
    tp.run_batch(_args(sheet), portal=NoAnswer(), status_path=status2, sleep=lambda s: None)

    class Empty(Later):
        def recent(self, limit=100):
            return {"runs": []}
    portal = Empty()
    tp.run_batch(_args(sheet), portal=portal, status_path=status2, sleep=lambda s: None)
    assert len(portal.started) == 1
