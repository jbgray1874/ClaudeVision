"""Self-Running asks for the drawing extract, stages the pack and runs it (D-702, SCRUM-185).

Until now a Live Enquiry row with no drawings waited for a person to copy them into the Live
Enquiry folder. The portal already asks the Document Manager for a pack from its Extract
button. With SDI_LIVE_ENQUIRY_EXTRACT_FROM_DM on, Self-Running asks the same route the same
way for each waiting row, follows the job across cycles, and stages the pack where the runner
looks. Off by default: nothing here changes a cycle until the switch is set.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import live_enquiry_runner as ler  # noqa: E402
import self_running as sr  # noqa: E402

ROUTES = ROOT / "sdi-intelligence-backend" / "estimate_routes.py"


class FakeDM:
    """The portal's extract routes: a job finishes after `polls` status calls."""

    def __init__(self, out_dir: Path, polls: int = 1, ok: bool = True, readable: bool = True):
        self.out_dir, self.polls, self.ok, self.readable = out_dir, polls, ok, readable
        self.asked, self.status_calls, self.started = [], 0, []

    def dm_extract(self, body):
        self.asked.append(dict(body))
        return {"job_id": f"job{len(self.asked)}", "status": "queued"}

    def dm_extract_status(self, job_id):
        self.status_calls += 1
        done = self.status_calls >= self.polls
        return {"job_id": job_id, "status": "completed" if done else "running",
                "finished": done, "ok": done and self.ok,
                "error": None if self.ok else "COM is down",
                "output_dir": str(self.out_dir) if done else None,
                "file_count": 2, "readable_here": done and self.readable,
                "note": "" if self.readable else "not inside SDI_FILE_ROOTS"}

    # what a cycle also calls
    def start(self, body):
        self.started.append(body["drawing_number"])
        return {"run_id": f"r{len(self.started)}", "output_path": "\\\\share\\x"}

    def status(self, run_id):
        return {"status": "done", "engine_price_gbp": 1.0, "seconds": 1,
                "output_path": "\\\\share\\x", "deliverables": []}


def _row(n, drawing, customer="M&S"):
    return ler.EnquiryRow(row=n, customer=customer, drawing=drawing, description="TABLE",
                          received=date(2026, 11, 5), ai_check="YES", quantities="1, 50")


@pytest.fixture
def share(tmp_path):
    root = tmp_path / "Live Enquiry"
    root.mkdir()
    pack = tmp_path / "dm-out" / "12693-02"
    (pack / "DXF").mkdir(parents=True)
    (pack / "12693-02-GA.pdf").write_bytes(b"%PDF-1.4 ga")
    (pack / "DXF" / "12693-02-03M.DXF").write_bytes(b"0\nSECTION")
    return {"root": root, "pack": pack, "ledger": tmp_path / "ledger.json",
            "workbook": tmp_path / "Live Enquiry.xlsx"}


def _waiting(share, *rows):
    ledger = ler.load_ledger(share["ledger"])
    decisions = ler.plan(list(rows), ler._sources(share["root"]), ledger)
    assert all(d.status == "waiting" for d in decisions)
    return ledger, decisions


def test_the_request_is_the_pages():
    d = ler.Decision(row=_row(5, "12693-02"), status="waiting", reason="")
    assert sr.extract_request(d) == {"project_number": "12693", "customer": "M&S",
                                     "assembly_folder": "12693-02"}


def test_a_waiting_row_is_asked_followed_and_staged(share):
    ledger, decisions = _waiting(share, _row(5, "12693-02"))
    dm = FakeDM(share["pack"], polls=2)
    first = sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None)
    assert first[0]["status"] == "queued" and dm.asked == [sr.extract_request(decisions[0])]
    second = sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None)
    assert second[0]["status"] == "running", "polled, not waited on"
    third = sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None)
    assert third[0]["status"] == "copied"
    staged = share["root"] / "M&S" / "12693-02"
    assert (staged / "12693-02-GA.pdf").is_file()
    assert (staged / "DXF" / "12693-02-03M.DXF").is_file()
    again = ler.plan([_row(5, "12693-02")], ler._sources(share["root"]), ledger)
    assert again[0].status == "ready", "the runner finds what was staged"
    assert len(dm.asked) == 1, "asked once"


def test_one_heavy_extract_at_a_time(share):
    ledger, decisions = _waiting(share, _row(5, "12693-02"), _row(6, "12693-03"))
    dm = FakeDM(share["pack"], polls=99)
    got = sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None)
    assert [g["status"] for g in got] == ["queued"]
    assert len(dm.asked) == 1, "the second row waits for the host"
    got = sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None)
    assert [g["status"] for g in got] == ["running"] and len(dm.asked) == 1


def test_a_failed_extract_waits_with_its_reason_and_is_asked_again_later(share):
    ledger, decisions = _waiting(share, _row(5, "12693-02"))
    dm = FakeDM(share["pack"], polls=1, ok=False)
    now = datetime(2026, 11, 5, 13, 0)
    sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None, now=now)
    got = sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None,
                                   now=now)
    assert got[0]["status"] == "failed" and "COM is down" in got[0]["note"]
    assert not (share["root"] / "M&S" / "12693-02").exists(), "nothing runs on no pack"
    soon = sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None,
                                    now=now + timedelta(hours=1))
    assert soon == []
    later = sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None,
                                     now=now + timedelta(hours=24))
    assert later and later[0]["status"] == "queued"


def test_a_pack_the_portal_cannot_read_is_not_staged(share):
    ledger, decisions = _waiting(share, _row(5, "12693-02"))
    dm = FakeDM(share["pack"], polls=1, readable=False)
    sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None)
    got = sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None)
    assert got[0]["status"] == "unreadable" and "SDI_FILE_ROOTS" in got[0]["note"]
    assert not (share["root"] / "M&S" / "12693-02").exists()


def test_a_copy_that_fails_leaves_no_partial_pack(share, monkeypatch):
    ledger, decisions = _waiting(share, _row(5, "12693-02"))
    dm = FakeDM(share["pack"], polls=1)
    sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None)
    import shutil
    real, calls = shutil.copy2, []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise OSError("share went away")
        return real(src, dst)

    monkeypatch.setattr(shutil, "copy2", flaky)
    got = sr.extract_missing_packs(decisions, share["root"], ledger, dm, say=lambda s: None)
    assert got[0]["status"] == "error"
    assert not (share["root"] / "M&S" / "12693-02").exists(), "a partial pack never runs"
    assert not list((share["root"] / "M&S").glob("*.extract-partial"))


def test_a_dry_run_asks_for_nothing_and_records_nothing(share):
    ledger, decisions = _waiting(share, _row(5, "12693-02"))
    dm = FakeDM(share["pack"])
    got = sr.extract_missing_packs(decisions, share["root"], ledger, dm, dry_run=True,
                                   say=lambda s: None)
    assert got[0]["status"] == "would_ask" and dm.asked == []
    assert not ledger.get("extracted")


class FakeSwitch:
    def beat(self, rep):
        return True


def _settings(share):
    return {"root": share["root"], "ledger": share["ledger"], "workbook": share["workbook"]}


def test_off_by_default_a_cycle_asks_for_nothing(share, monkeypatch):
    assert sr.config.LIVE_ENQUIRY_EXTRACT_FROM_DM is False
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": [_row(5, "12693-02")])
    dm = FakeDM(share["pack"])
    out = sr.cycle(_settings(share), dm, FakeSwitch(), say=lambda s: None,
                   wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert dm.asked == [] and out["extracted"] == []


def test_switched_on_a_cycle_asks_then_a_later_cycle_runs_the_staged_pack(share, monkeypatch):
    monkeypatch.setattr(sr.config, "LIVE_ENQUIRY_EXTRACT_FROM_DM", True)
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": [_row(5, "12693-02")])
    dm = FakeDM(share["pack"], polls=1)
    first = sr.cycle(_settings(share), dm, FakeSwitch(), say=lambda s: None,
                     wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert [e["status"] for e in first["extracted"]] == ["queued"] and dm.started == []
    second = sr.cycle(_settings(share), dm, FakeSwitch(), say=lambda s: None,
                      wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert [e["status"] for e in second["extracted"]] == ["copied"]
    assert dm.started == ["12693-02"], "the staged pack is run in the same cycle"


def test_the_client_calls_routes_the_portal_serves():
    routes = ROUTES.read_text(encoding="utf-8")
    assert '@router.post("/dm/extract")' in routes
    assert '@router.get("/dm/extract/{job_id}")' in routes
    src = (ROOT / "src" / "live_enquiry_runner.py").read_text(encoding="utf-8")
    assert '"/api/estimate/dm/extract"' in src and 'f"/api/estimate/dm/extract/{job_id}"' in src
