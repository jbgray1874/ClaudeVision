"""No scan is missed: what is in scope is decided by the job's own record, not by when the job
happens to run - and there is no date for anybody to set.

James Gray, 13 October 2026, on BARDON DELIVERY NOTES 7-10-2026 never reaching SplitScan:
"how do we fix then as we can't miss files." It was saved at 07:18 on a Thursday. The task
ran `--since 1` - 24 hours counted back from when it ran - at logon on a laptop: Thursday's
run was before the file existed and Friday's started after 07:18, so the file was too old
for it. Nothing failed and nothing was said.

And then, of the start date that first fixed it: "SDI_SCAN_FROM=2026-10-01 - I've not done
this.. looks like a hard coded hack" and "I don't have time to manually do re runs because of a
bug / mis timing". So the job now remembers how far it has got, and runs as a service.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "logistics"))

import split_delivery_notes as S  # noqa: E402

HOUR = 3600


def _scan(folder: Path, name: str, hours_old: float = 0) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / name
    pdf.write_bytes(b"%PDF-1.4\n" + name.encode())
    when = time.time() - hours_old * HOUR
    os.utime(pdf, (when, when))
    return pdf


def _fake_split(calls, fail=()):
    def split(pdf, out_dir, dry_run=False):
        calls.append(pdf.name)
        if pdf.name in fail:
            raise ValueError("cannot read page 3")
        name = f"{pdf.stem}-note.pdf"
        if not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / name).write_bytes(b"%PDF-1.4\n")
        return {"source": pdf.name, "pages": 1, "unsorted": [],
                "notes": [{"file": name, "written": True, "path": str(out_dir / name),
                           "number": "30022230", "client": "Tesco", "account": "TES01",
                           "pages": [1], "already": False}]}
    return split


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def test_the_scan_a_late_run_missed_is_in_scope_with_a_start_date(tmp_path):
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    out.mkdir(parents=True)
    bardon = _scan(source, "BARDON DELIVERY NOTES 7-10-2026.pdf", hours_old=24.7)
    every = S.scans_to_read(source, out)
    assert S.recent(every, since_days=1) == [], "the rolling day had already passed it"
    assert S.recent(every, from_ts=S.from_cutoff(_days_ago(3))) == [bardon]


def _ledger_with(out: Path, **records) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / S.LEDGER).write_text(json.dumps(records), encoding="utf-8")


def _main(monkeypatch, source, out, *extra, calls=None, fail=()):
    monkeypatch.setattr(S, "split_pdf", _fake_split(calls if calls is not None else [], fail))
    monkeypatch.setattr(S, "find_tesseract", lambda explicit=None: "tesseract")
    monkeypatch.setattr(sys, "argv", ["split", "--source", str(source), "--out", str(out),
                                      *extra])
    return S.main()


def test_an_old_tasks_since_1_can_no_longer_narrow_a_run(tmp_path, monkeypatch, capsys):
    """The laptop's task still passes --since 1. The job's own record decides what is in
    scope; --since can only reach further back, so the old task cannot lose BARDON again."""
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    _ledger_with(out, _meta={"covered_to": time.time() - 3 * 86400})
    _scan(source, "BARDON DELIVERY NOTES 7-10-2026.pdf", hours_old=30)
    calls = []
    assert _main(monkeypatch, source, out, "--since", "1", calls=calls) == 0
    said = capsys.readouterr().out
    assert calls == ["BARDON DELIVERY NOTES 7-10-2026.pdf"], said
    assert "the last complete run" in said and "0 already split, 1 to read" in said, said
    assert (out / "BARDON DELIVERY NOTES 7-10-2026-note.pdf").exists()


def test_the_first_run_picks_up_everything_missed_since_the_job_began(tmp_path, monkeypatch,
                                                                      capsys):
    """No record of how far it got yet (the ledger the laptop task wrote): it starts at the
    first scan the ledger knows, so whatever the old window let slip since then is filed."""
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    _scan(source, "split-long-ago.pdf", hours_old=20 * 24)
    _scan(source, "missed.pdf", hours_old=12 * 24)
    _scan(source, "back-catalogue.pdf", hours_old=60 * 24)          # before the job: left
    _ledger_with(out, **{"split-long-ago.pdf": {
        "mark": S._fingerprint(source / "split-long-ago.pdf"), "files": ["old-note.pdf"]}})
    (out / "old-note.pdf").write_bytes(b"%PDF-1.4\n")
    calls = []
    assert _main(monkeypatch, source, out, "--since", "1", calls=calls) == 0
    said = capsys.readouterr().out
    assert calls == ["missed.pdf"], said
    assert "the first scan this job has a record of" in said, said
    meta = json.loads((out / S.LEDGER).read_text())[S.META]
    assert time.time() - meta["covered_to"] < 60, "a complete run records how far it got"


def test_a_machine_off_for_three_weeks_loses_nothing(tmp_path):
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    _ledger_with(out, _meta={"covered_to": time.time() - 21 * 86400})
    _scan(source, "while-it-was-off.pdf", hours_old=20 * 24)
    calls = []
    import pytest as _pytest
    with _pytest.MonkeyPatch.context() as m:
        m.setattr(S, "split_pdf", _fake_split(calls))
        S.run(source, out)
    assert calls == ["while-it-was-off.pdf"]


def test_a_run_that_does_not_finish_does_not_move_the_record_on(tmp_path, monkeypatch):
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    _scan(source, "a.pdf")
    _scan(source, "b.pdf")
    good = _fake_split([])

    def stopped_at_b(pdf, out_dir, dry_run=False):
        if pdf.name == "b.pdf":
            raise S.NoOCR("the run was stopped")
        return good(pdf, out_dir, dry_run)

    monkeypatch.setattr(S, "split_pdf", stopped_at_b)
    with pytest.raises(S.NoOCR):
        S.run(source, out)
    assert S.META not in json.loads((out / S.LEDGER).read_text())


def test_a_bad_date_is_refused_rather_than_read_as_everything(tmp_path, monkeypatch, capsys):
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    out.mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["split", "--source", str(source), "--out", str(out),
                                      "--from", "13/10/2026"])
    assert S.main() == 2
    assert "YYYY-MM-DD" in capsys.readouterr().out


def test_a_failing_scan_is_never_marked_done_and_is_tried_every_run(tmp_path, monkeypatch):
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    _scan(source, "good.pdf")
    _scan(source, "bad.pdf")
    calls = []
    monkeypatch.setattr(S, "split_pdf", _fake_split(calls, fail={"bad.pdf"}))
    first = S.run(source, out)
    assert [r["source"] for r in first["results"] if r.get("error")] == ["bad.pdf"]
    ledger = json.loads((out / S.LEDGER).read_text())
    assert ledger["bad.pdf"]["failed"] == 1 and "files" not in ledger["bad.pdf"]
    started = ledger["bad.pdf"]["first_failed"]

    calls.clear()
    second = S.run(source, out)
    assert calls == ["bad.pdf"], "the good one is skipped; the failing one is tried again"
    assert second["results"][0]["failed"] == 2
    assert json.loads((out / S.LEDGER).read_text())["bad.pdf"]["first_failed"] == started

    calls.clear()
    monkeypatch.setattr(S, "split_pdf", _fake_split(calls))          # fixed (or re-scanned)
    S.run(source, out)
    assert calls == ["bad.pdf"] and (out / "bad-note.pdf").exists()
    calls.clear()
    assert S.run(source, out)["skipped"] == ["bad.pdf", "good.pdf"] and calls == []


def test_progress_survives_a_run_that_is_stopped_part_way(tmp_path, monkeypatch):
    """The task has a two-hour limit. The ledger used to be written once, at the end, so a
    run stopped at 1h59 forgot everything it had done."""
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    _scan(source, "a.pdf")
    _scan(source, "b.pdf")
    calls = []
    good = _fake_split(calls)

    def stopped_at_b(pdf, out_dir, dry_run=False):
        if pdf.name == "b.pdf":
            raise S.NoOCR("the run was stopped")                       # escapes run()
        return good(pdf, out_dir, dry_run)

    monkeypatch.setattr(S, "split_pdf", stopped_at_b)
    with pytest.raises(S.NoOCR):
        S.run(source, out)
    assert "a.pdf" in json.loads((out / S.LEDGER).read_text())


def test_each_run_leaves_a_dated_log_in_the_output_folder(tmp_path, monkeypatch):
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    out.mkdir(parents=True)
    _scan(source, "scan.pdf")
    monkeypatch.setattr(S, "split_pdf", _fake_split([]))
    monkeypatch.setattr(S, "find_tesseract", lambda explicit=None: "tesseract")
    monkeypatch.setattr(sys, "argv", ["split", "--source", str(source), "--out", str(out)])
    assert S.main() == 0
    logs = list((out / S.LOGS).glob("splitscan-*.log"))
    assert len(logs) == 1, logs
    text = logs[0].read_text(encoding="utf-8")
    assert "exit 0" in text and "1 PDF(s) in the folder" in text and "scan-note.pdf" in text


def test_a_failing_scan_is_listed_as_needing_attention(tmp_path, monkeypatch, capsys):
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    out.mkdir(parents=True)
    _scan(source, "bad.pdf")
    monkeypatch.setattr(S, "split_pdf", _fake_split([], fail={"bad.pdf"}))
    monkeypatch.setattr(S, "find_tesseract", lambda explicit=None: "tesseract")
    monkeypatch.setattr(sys, "argv", ["split", "--source", str(source), "--out", str(out)])
    S.main()
    said = capsys.readouterr().out
    assert "NEEDS ATTENTION: 1 scan(s) could not be split" in said
    assert "bad.pdf (attempt 1): ValueError: cannot read page 3" in said


def test_there_is_no_start_date_to_set():
    """ "looks like a hard coded hack" - it is gone from config, the README and the task."""
    for rel in ("src/config.py", "README.md", "tools/logistics/Install-SplitScanTask.ps1",
                "tools/logistics/split_delivery_notes.py"):
        assert "SDI_SCAN_FROM" not in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_a_second_run_waits_its_turn_and_a_dead_ones_lock_is_taken_over(tmp_path,
                                                                        monkeypatch, capsys):
    """The service, the page's button and the laptop's old task share one ledger."""
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    out.mkdir(parents=True)
    _scan(source, "scan.pdf")
    (out / S.LOCK).write_text("SDI-APP01 (pid 4242), started 2026-10-13 09:00")
    calls = []
    assert _main(monkeypatch, source, out, calls=calls) == 0
    said = capsys.readouterr().out
    assert calls == [] and "another run is already splitting (SDI-APP01" in said, said

    old = time.time() - S.LOCK_STALE - 60                          # its machine went off
    os.utime(out / S.LOCK, (old, old))
    assert _main(monkeypatch, source, out, calls=calls) == 0
    assert calls == ["scan.pdf"] and not (out / S.LOCK).exists(), "the lock is released"


def test_the_service_leaves_a_scan_that_is_still_being_written(tmp_path):
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    out.mkdir(parents=True)
    _scan(source, "landed.pdf", hours_old=0.5)
    _scan(source, "arriving.pdf")
    chosen, waiting = S.in_scope(S.scans_to_read(source, out), 0, {}, source, settle=S.SETTLE)
    assert [p.name for p in chosen] == ["landed.pdf"]
    assert [p.name for p, _ in waiting] == ["arriving.pdf"]


def test_the_service_retries_a_failing_scan_hourly_not_every_check(tmp_path, monkeypatch):
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    _scan(source, "bad.pdf")
    calls = []
    monkeypatch.setattr(S, "split_pdf", _fake_split(calls, fail={"bad.pdf"}))
    S.run(source, out, retry_after=S.RETRY_AFTER)
    S.run(source, out, retry_after=S.RETRY_AFTER)
    assert calls == ["bad.pdf"]
    S.run(source, out)                                    # by hand: tried again now
    assert calls == ["bad.pdf", "bad.pdf"]


def test_the_service_says_when_it_last_checked_and_logs_only_what_matters(tmp_path,
                                                                         monkeypatch):
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    out.mkdir(parents=True)
    _scan(source, "scan.pdf", hours_old=1)
    passes = {"n": 0}

    def sleep(_seconds):
        passes["n"] += 1
        if passes["n"] == 2:
            raise KeyboardInterrupt                                # the service is stopped

    monkeypatch.setattr(S.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        _main(monkeypatch, source, out, "--watch", "5")
    status = (out / S.LOGS / S.STATUS).read_text(encoding="utf-8")
    assert status.startswith("Last check: ") and "Next check: about" in status, status
    log = next((out / S.LOGS).glob("splitscan-*.log")).read_text(encoding="utf-8")
    assert log.count("====") == 1, "the quiet second check is not in the day's log:\n" + log
    assert "scan-note.pdf" in log


def test_the_server_installer_runs_it_as_a_service_under_an_account_that_can_reach_the_share():
    ps1 = (ROOT / "tools" / "logistics" / "Install-SplitScanService.ps1").read_text(
        encoding="utf-8")
    assert "--watch" in ps1
    assert "ObjectName" in ps1, "LocalSystem cannot reach \\\\sdi-dc01 - an account is needed"
    assert "service-status.txt" in ps1, "the installer proves the service reached the share"
    block = re.search(r"^param\((.*?)^\)", ps1, re.S | re.M).group(1)
    assert not re.search(r"=\s*['\"]\\\\", block), "no folder is guessed: " + block


def test_a_deploy_carries_the_splitter_to_the_server():
    ps1 = (ROOT / "sdi-intelligence-backend" / "deploy" / "Deploy-AMCRM.ps1").read_text(
        encoding="utf-8")
    for f in ("tools/logistics/split_delivery_notes.py", "tools/logistics/delivery_note_reader.py",
              "tools/logistics/Install-SplitScanService.ps1"):
        assert f in ps1, f
    assert "SDISplitScan" in ps1


def test_a_page_read_twice_is_not_filed_twice(tmp_path):
    """A re-read scan put "scan p3 (2).pdf" into _Unsorted: every save had a new /ID, so the
    same page never compared equal - including against files already on the share."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"page {i}")
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(doc.tobytes())
    doc.close()

    def carve(**kw):
        src, out = pymupdf.open(str(scan)), pymupdf.open()
        out.insert_pdf(src, from_page=2, to_page=2)
        data = out.tobytes(**kw)
        out.close(), src.close()
        return data

    target = tmp_path / "_Unsorted" / "scan p3.pdf"
    target.parent.mkdir()
    target.write_bytes(carve())                         # as the old code wrote it, with an /ID
    time.sleep(1.1)
    assert S._unique(target, carve(no_new_id=True)) is None, "the old file is the same page"
    assert S._unique(target, carve()) is None, "and a fresh /ID does not make it different"
    other = tmp_path / "other.pdf"
    other.write_bytes(b"%PDF-1.4 something else")
    assert S._unique(other, carve()) == other.with_name("other (2).pdf")
