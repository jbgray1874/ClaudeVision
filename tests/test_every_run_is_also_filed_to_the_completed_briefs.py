"""Every finished run is also filed to the completed AI briefs area, one folder per run (D-617).

JG, 1 Nov 2026: "when we save down the estimates to the C:\\ClaudeVision\\output\\estimates, I now
need a save down to the K:\\Estimating\\Completed\\Live Enquiries\\completed AI briefs\\$ClientArea\\
followed by the job pack number, if we do multiple runs for the same job pack we create a new sub
dir below this with a timestamp and some other identifier like a version number so that we have
a record of them all."
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import sdi_estimate_runner as runner  # noqa: E402
from test_estimate_queue import _check_in, _request, api  # noqa: E402,F401

RUNNER_SRC = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")


# ── the claim says where ────────────────────────────────────────────────────────────────

def test_the_claim_names_the_briefs_root_and_the_runs_own_time(api, tmp_path, monkeypatch):
    er, root = api
    monkeypatch.setattr(er, "COMPLETED_BRIEFS_ROOT", tmp_path / "briefs")
    monkeypatch.setattr(er, "FILE_TO_COMPLETED_BRIEFS", True)
    _check_in(er)
    run_id = er.start(_request(er, root))["run_id"]
    job = _check_in(er)["run"]
    assert job["archive_root"] == str(tmp_path / "briefs")
    stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(er._RUNS[run_id].queued_at))
    assert job["archive_stamp"] == stamp
    assert Path(job["output_path"]).name.startswith(stamp), "the same stamp as its AISheets folder"


def test_switched_off_there_is_no_second_copy(api, monkeypatch):
    er, root = api
    monkeypatch.setattr(er, "FILE_TO_COMPLETED_BRIEFS", False)
    _check_in(er)
    er.start(_request(er, root))
    assert _check_in(er)["run"]["archive_root"] == ""


def test_the_default_is_the_completed_ai_briefs_share(api):
    er, _ = api
    assert str(er.COMPLETED_BRIEFS_ROOT).endswith(
        r"Estimating\Completed\Live Enquiries\completed AI briefs")
    assert str(er.COMPLETED_BRIEFS_ROOT).startswith("\\\\sdi-dc01\\"), "UNC, never K:"


# ── one folder per run ──────────────────────────────────────────────────────────────────

def test_the_first_run_of_a_pack_is_v1_and_the_next_v2(tmp_path):
    base = tmp_path / "M&S" / "12677-01-GA"
    first = runner.archive_folder(base, "2026-11-01 10-15-30", 1)
    second = runner.archive_folder(base, "2026-11-01 11-02-07", 5)
    assert first.name == "2026-11-01 10-15-30 v1 (1 off)"
    assert second.name == "2026-11-01 11-02-07 v2 (5 off)"


def test_numbering_carries_on_from_the_highest_and_ignores_other_folders(tmp_path):
    base = tmp_path / "pack"
    (base / "2026-10-30 09-00-00 v4 (1 off)").mkdir(parents=True)
    (base / "drawings").mkdir()
    (base / "notes from Dave").mkdir()
    assert runner.archive_folder(base, "2026-11-01 10-00-00", 1).name == \
        "2026-11-01 10-00-00 v5 (1 off)"


def test_the_same_second_twice_is_two_folders_never_one(tmp_path):
    base = tmp_path / "pack"
    a = runner.archive_folder(base, "2026-11-01 10-00-00", 1)
    b = runner.archive_folder(base, "2026-11-01 10-00-00", 1)
    assert a != b and a.is_dir() and b.is_dir()


def test_the_client_area_already_there_is_used_whatever_its_spacing(tmp_path):
    (tmp_path / "M & S").mkdir()
    assert runner.client_area(tmp_path, "M&S") == tmp_path / "M & S"
    assert runner.client_area(tmp_path, "Boots") == tmp_path / "Boots"
    assert runner.client_area(tmp_path, 'A/B: "x"').name == "A-B- -x-"


# ── the copy ────────────────────────────────────────────────────────────────────────────

def _filed(tmp_path):
    out = tmp_path / "AISheets" / "M&S" / "12677-01-GA" / "2026-11-01 10-15-30 (1 off)"
    out.mkdir(parents=True)
    names = ["12677-01-GA_20261101.xlsx", "12677-01-GA_20261101_record.json",
             "12677-01-GA_report.html", "12677-01-GA_walkthrough.wav"]
    for n in names:
        (out / n).write_bytes(b"x" + n.encode())
    return [{"name": n, "path": str(out / n)} for n in names]


def _job(tmp_path, **kw):
    return dict({"archive_root": str(tmp_path / "briefs"), "client": "M&S",
                 "drawing_number": "12677-01-GA", "units": 1,
                 "archive_stamp": "2026-11-01 10-15-30"}, **kw)


def test_every_file_of_the_run_is_copied_and_the_log_says_where(tmp_path):
    filed, log = _filed(tmp_path), []
    folder = Path(runner.file_a_copy(_job(tmp_path), filed, log))
    assert folder == tmp_path / "briefs" / "M&S" / "12677-01-GA" / "2026-11-01 10-15-30 v1 (1 off)"
    assert sorted(p.name for p in folder.iterdir()) == sorted(f["name"] for f in filed)
    assert log == [f"[archive] 4 of 4 file(s) also filed to {folder}"]
    assert all(Path(f["path"]).exists() for f in filed), "the AISheets copy is untouched"


def test_a_second_run_of_the_same_pack_keeps_the_first(tmp_path):
    filed = _filed(tmp_path)
    one = Path(runner.file_a_copy(_job(tmp_path), filed, []))
    two = Path(runner.file_a_copy(_job(tmp_path, archive_stamp="2026-11-01 12-00-00",
                                       units=5), filed, []))
    assert one.name.endswith("v1 (1 off)") and two.name.endswith("v2 (5 off)")
    assert len(list(one.iterdir())) == 4 and len(list(two.iterdir())) == 4


def test_an_unreachable_share_is_said_and_never_fails_the_run(tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("a file where the share should be")
    log = []
    assert runner.file_a_copy(_job(tmp_path, archive_root=str(blocker)), _filed(tmp_path), log) == ""
    assert log and log[0].startswith("[archive] NOT filed to the completed AI briefs area")


def test_one_file_that_cannot_be_copied_is_named_and_the_rest_go(tmp_path):
    filed = _filed(tmp_path) + [{"name": "gone.xlsx", "path": str(tmp_path / "gone.xlsx")}]
    log = []
    folder = Path(runner.file_a_copy(_job(tmp_path), filed, log))
    assert len(list(folder.iterdir())) == 4
    assert log[0] == f"[archive] 4 of 5 file(s) also filed to {folder}"
    assert log[1].startswith("[archive] NOT copied: gone.xlsx")


def test_no_root_or_nothing_filed_copies_nothing(tmp_path):
    assert runner.file_a_copy(_job(tmp_path, archive_root=""), _filed(tmp_path), []) == ""
    assert runner.file_a_copy(_job(tmp_path), [], []) == ""
    assert not (tmp_path / "briefs").exists()


def test_only_a_finished_estimate_is_copied():
    done = RUNNER_SRC.split('"The engine finished without producing a workbook. "', 1)[1]
    done = done.split("# WHERE THE ENGINE PUTS ITS ANSWER.", 1)[0]
    assert done.index("file_a_copy(job, filed, log)") < done.index(
        '_finish(requests, base, headers, run_id, runner_id, "done", "", log, filed,')
    assert RUNNER_SRC.count("file_a_copy(job, filed, log)") == 1
