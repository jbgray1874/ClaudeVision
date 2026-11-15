"""A REQUEST THAT GOT NO ANSWER: NOTHING IS SENT AGAIN UNTIL ITS OUTCOME IS KNOWN (15 Nov 2026).

Row 3's pack was 65 files with its models. The service was still taking it in when the batch's
wait ran out; the row was written down as "not queued" and the service ran the job. Run again,
that is the same estimate twice.

No answer is not a refusal. The batch asks the service whether it holds the run. It takes a run
up only when a person names it (--take-up ROW=RUN, checked against the row's drawing and
units) or the service shows exactly one run for that drawing and those units since the request
left. A lookup that failed, no run found, or several that could be it: the outcome is not known
and nothing is sent, until --take-up names the run or --resubmit-lost says there is none.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import live_enquiry_runner as ler  # noqa: E402
import tti_pricer as tp  # noqa: E402
from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal, _areas, _args  # noqa: E402
from test_the_tracker_batch_runs_the_rows_named_on_their_own_briefs_and_never_lists_the_share_in_silence import _tracker  # noqa: E402

D = "TTI-10234"


def _run(drawing=D, source="tti", queued_at=None, run_id="abc123", units=4):
    return {"run_id": run_id, "drawing_number": drawing, "source": source, "units": units,
            "queued_at": time.time() if queued_at is None else queued_at}


class _Service:
    def __init__(self, runs):
        self.runs, self.asked = runs, 0

    def recent(self, limit=100):
        self.asked += 1
        return {"runs": self.runs(self.asked) if callable(self.runs) else self.runs}


def _ask(service, **kw):
    return tp.runs_after_no_answer(service, D, 4, time.time() - 1, sleep=lambda x: None,
                                   say=lambda m: None, **kw)


def test_the_one_run_for_this_drawing_and_these_units_is_found():
    assert _ask(_Service([_run("12353-13-GA", run_id="other"), _run(run_id="mine")])) == (["mine"], True)


def test_a_run_that_appears_a_little_later_is_still_found():
    s = _Service(lambda n: [] if n < 3 else [_run(run_id="late")])
    assert _ask(s) == (["late"], True) and s.asked == 3


def test_another_quantity_another_drawing_another_source_or_an_older_run_is_not_this_rows():
    s = _Service([_run(units=25, run_id="other quantity"), _run("TTI-10234-2", run_id="sibling"),
                  _run(source="self-running", run_id="theirs"),
                  _run(queued_at=time.time() - 3600, run_id="an hour ago")])
    assert _ask(s, wait_s=30, every_s=15) == ([], True)
    assert s.asked == 3, "it asks for the whole wait, then stops"


def test_two_runs_that_could_be_it_are_both_reported_and_neither_is_chosen():
    assert _ask(_Service([_run(run_id="b"), _run(run_id="a")])) == (["a", "b"], True)


def test_a_service_that_cannot_be_asked_is_not_heard():
    class Dead:
        def recent(self, limit=100):
            raise ler.PortalError(0, "no answer")
    assert _ask(Dead(), wait_s=30, every_s=15) == ([], False)


# ── the batch ────────────────────────────────────────────────────────────────────────────
class _NoAnswer(FakePortal):
    """The request leaves and no answer comes back."""
    runs: list = []
    sent = 0

    def start(self, body):
        type(self).sent += 1
        raise ler.PortalError(0, "the portal did not answer (timed out)")

    def recent(self, limit=100):
        return {"runs": list(self.runs)}

    def status(self, run_id):
        hit = next((x for x in self.runs if x["run_id"] == run_id), None)
        return dict(hit or {}, status="done", quantity_prices=[{"quantity": 4, "unit_gbp": 12.5}],
                    output_path=f"X:\\out\\{run_id}") if hit else {}


def _batch(tmp_path, monkeypatch, portal, status=None, **kw):
    sheet = tmp_path / "tracker.xlsx"
    if not sheet.exists():
        _tracker(tmp_path, [(D, "Counter", "", "", 4)])
        _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)
    rep = tp.run_batch(_args(sheet, **kw), portal=portal, status_path=status, sleep=lambda s: None)
    return rep["rows"][0]


def _portal(runs, cls=_NoAnswer):
    class P(cls):
        pass
    P.runs, P.sent = runs, 0
    return P()


def test_one_plain_match_is_followed_and_nothing_is_sent_twice(tmp_path, monkeypatch):
    portal = _portal([_run(run_id="r1")])
    row = _batch(tmp_path, monkeypatch, portal)
    assert type(portal).sent == 1 and row["run_id"] == "r1" and "nothing was sent twice" in row["resumed"]


@pytest.mark.parametrize("runs, said", [
    (lambda: [], "showed no run for it"),
    (lambda: [_run(run_id="a"), _run(run_id="b")], "2 runs that could be it"),
    (lambda: [_run(units=25, run_id="other quantity")], "showed no run for it")])
def test_no_run_several_runs_or_another_quantitys_run_leave_the_outcome_not_known(tmp_path, monkeypatch, runs, said):
    row = _batch(tmp_path, monkeypatch, _portal(runs()))        # queued now, not when the file was read
    assert row["state"] == tp.OUTCOME_NOT_KNOWN and said in row["why"] and "--take-up 2=RUN" in row["why"]
    assert not row.get("run_id")


def test_a_row_whose_outcome_is_not_known_is_not_sent_again(tmp_path, monkeypatch):
    """The case that was unsafe: the lookup finds nothing, or fails, and the row was sent anew."""
    status = tmp_path / "status.json"
    _batch(tmp_path, monkeypatch, _portal([]), status)
    for runs in ([], [_run(run_id="a"), _run(run_id="b")]):
        portal = _portal(runs, cls=_Answers)
        row = _batch(tmp_path, monkeypatch, portal, status)
        assert portal.started == [], "a second request was sent while the first one's outcome was not known"
        assert row["state"] == tp.OUTCOME_NOT_KNOWN and "Nothing was sent" in row["why"]

    class Deaf(_Answers):
        def recent(self, limit=100):
            raise ler.PortalError(0, "no answer")
    portal = _portal([], cls=Deaf)
    row = _batch(tmp_path, monkeypatch, portal, status)
    assert portal.started == [] and "could not be asked" in row["why"]


class _Answers(_NoAnswer):
    """A service that would accept a new request, so a wrong resend would show."""

    def start(self, body):
        self.started.append(body)
        return {"run_id": "second"}


def test_exactly_one_run_on_the_service_is_taken_up_on_the_next_run_of_the_row(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    _batch(tmp_path, monkeypatch, _portal([]), status)
    portal = _portal([_run(run_id="first")], cls=_Answers)
    row = _batch(tmp_path, monkeypatch, portal, status)
    assert portal.started == [] and row["run_id"] == "first" and "taken up" in row["resumed"]


def test_a_named_run_is_taken_up_when_it_is_this_rows(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    _batch(tmp_path, monkeypatch, _portal([]), status)
    portal = _portal([_run(run_id="e2639e873262", queued_at=time.time() - 7200)], cls=_Answers)
    row = _batch(tmp_path, monkeypatch, portal, status, take_up=["2=e2639e873262"])
    assert portal.started == [] and row["run_id"] == "e2639e873262" and "named as this row's" in row["resumed"]


@pytest.mark.parametrize("run, why", [
    (lambda: _run("TTI-99999", run_id="e2639e873262"), "is for TTI-99999, not TTI-10234"),
    (lambda: _run(units=25, run_id="e2639e873262"), "is for 25 unit(s), not this row's 4")])
def test_a_named_run_for_another_drawing_or_quantity_is_refused_and_nothing_is_sent(tmp_path, monkeypatch, run, why):
    portal = _portal([run()], cls=_Answers)
    row = _batch(tmp_path, monkeypatch, portal, take_up=["2=e2639e873262"])
    assert portal.started == [] and row["state"] == tp.OUTCOME_NOT_KNOWN and why in row["why"]


def test_resubmit_lost_is_the_only_way_to_send_again_and_is_said_by_hand(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    _batch(tmp_path, monkeypatch, _portal([]), status)
    portal = _portal([], cls=_Answers)
    row = _batch(tmp_path, monkeypatch, portal, status, resubmit_lost=True)
    assert len(portal.started) == 1 and row["run_id"] == "second"


def test_take_up_is_row_equals_run():
    assert tp.take_ups(["3=E2639E873262", " 7 = abc123 "]) == {3: "e2639e873262", 7: "abc123"}
    with pytest.raises(SystemExit, match="ROW=RUN"):
        tp.take_ups(["e2639e873262"])
