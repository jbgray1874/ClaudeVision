"""No scan is missed: what is in scope is decided by a start date and the ledger, not by when
the job happens to run.

James Gray, 13 October 2026, on BARDON DELIVERY NOTES 7-10-2026 never reaching SplitScan:
"how do we fix then as we can't miss files." It was saved at 07:18 on a Thursday. The task
ran `--since 1` - 24 hours counted back from when it ran - at logon on a laptop: Thursday's
run was before the file existed and Friday's started after 07:18, so the file was too old
for it. Nothing failed and nothing was said.
"""
from __future__ import annotations

import json
import os
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


def test_a_start_date_in_env_beats_an_old_tasks_since_1(tmp_path, monkeypatch, capsys):
    """The installed task still passes --since 1. SDI_SCAN_FROM decides anyway, so the
    fix does not wait on anybody reinstalling a task."""
    source, out = tmp_path / "Scans", tmp_path / "Scans" / "SplitScan"
    out.mkdir(parents=True)
    _scan(source, "BARDON DELIVERY NOTES 7-10-2026.pdf", hours_old=30)
    calls = []
    monkeypatch.setattr(S, "split_pdf", _fake_split(calls))
    monkeypatch.setattr(S, "find_tesseract", lambda explicit=None: "tesseract")
    monkeypatch.setattr(S, "DEFAULT_FROM", _days_ago(5))
    monkeypatch.setattr(sys, "argv", ["split", "--source", str(source), "--out", str(out),
                                      "--since", "1"])
    assert S.main() == 0
    said = capsys.readouterr().out
    assert calls == ["BARDON DELIVERY NOTES 7-10-2026.pdf"], said
    assert f"1 from {_days_ago(5)} on: 0 already split, 1 to read" in said, said
    assert (out / "BARDON DELIVERY NOTES 7-10-2026-note.pdf").exists()


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
    monkeypatch.setattr(S, "DEFAULT_FROM", "")
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
    monkeypatch.setattr(S, "DEFAULT_FROM", "")
    monkeypatch.setattr(sys, "argv", ["split", "--source", str(source), "--out", str(out)])
    S.main()
    said = capsys.readouterr().out
    assert "NEEDS ATTENTION: 1 scan(s) could not be split" in said
    assert "bad.pdf (attempt 1): ValueError: cannot read page 3" in said


def test_the_installer_can_give_the_task_a_start_date():
    ps1 = (ROOT / "tools" / "logistics" / "Install-SplitScanTask.ps1").read_text(encoding="utf-8")
    assert "[string]$From = ''" in ps1
    assert "--from {0}' -f $From" in ps1
