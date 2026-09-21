"""The splitter as an app in the suite: one button, the same script the nightly task runs.

James Gray, 21 September 2026: "we can add to the SDI Intelligence Apps with way of an end
point. to start with I can run manually, then we add it to the SDI Intelligence suite of apps
for a user to run. is that a sensible idea?"

THE SAME SCRIPT, NOT A SECOND IMPLEMENTATION OF IT. A button and a nightly task that read a
document differently are two answers to one question, and the one nobody is watching is the
one that goes wrong. The route shells out to `tools/logistics/split_delivery_notes.py`, which
is what the scheduled task runs and what a person runs by hand — the same three ways in, one
piece of code underneath.

AND THE SHARE IS NAMED BY UNC, NEVER BY K:. A mapped drive belongs to a logged-on session.
This service has no session, and neither does a scheduled task — so `K:\\IT\\...` is simply not
there when either of them runs. What then happens is worse than an error: the job creates a
folder of that name on the local disk, writes the day's delivery notes into it, and exits 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "logistics"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))


# ── the path the whole thing writes to ──────────────────────────────────────────────

def test_the_default_output_is_a_unc_path_not_a_drive_letter():
    """THE SILENT FAILURE THIS PREVENTS. K: resolves to nothing under a service or a task,
    the job invents a local folder of that name, files the day into it and reports success.
    Nobody looks in C:\\Windows\\System32\\K: for a delivery note."""
    from split_delivery_notes import DEFAULT_OUT
    assert DEFAULT_OUT.startswith("\\\\"), DEFAULT_OUT
    assert "sdi-dc01" in DEFAULT_OUT and "SplitScan" in DEFAULT_OUT
    assert ":" not in DEFAULT_OUT.replace("shareddata$", ""), "a drive letter crept back in"


def test_the_default_source_is_a_unc_path_too():
    """The input is a mapped drive on the screenshots as well, and a task cannot see it."""
    from split_delivery_notes import DEFAULT_SOURCE
    assert DEFAULT_SOURCE.startswith("\\\\"), DEFAULT_SOURCE
    assert DEFAULT_SOURCE.endswith("Logistics\\Scans"), DEFAULT_SOURCE


def test_the_output_folder_is_inside_the_input_folder_and_is_not_read_back(tmp_path):
    """K:\\Logistics\\Scans\\SplitScan is a CHILD of K:\\Logistics\\Scans.

    So everything this job writes lands in the folder it reads. Non-recursive globbing
    happens not to see it, which puts one line of code between the job and eating its own
    output for ever — every note re-split into a one-page note named after itself, on every
    run, for as long as nobody looks.
    """
    from split_delivery_notes import scans_to_read
    source = tmp_path / "Scans"
    out = source / "SplitScan"
    out.mkdir(parents=True)
    (source / "scan21092026.pdf").write_bytes(b"%PDF-1.4\n")
    (out / "30022230 Tesco.pdf").write_bytes(b"%PDF-1.4\n")
    found = [p.name for p in scans_to_read(source, out)]
    assert found == ["scan21092026.pdf"], found


def test_a_case_insensitive_filesystem_does_not_double_every_scan(tmp_path, monkeypatch):
    """`*.pdf` AND `*.PDF` ARE THE SAME FILES ON WINDOWS.

    Globbing both and adding the lists is right on the Linux box this was written on and
    doubles every file on the machine it runs on — each scan read, OCR'd and split twice.
    The glob is faked here because this filesystem is case-sensitive and cannot show it.
    """
    from split_delivery_notes import scans_to_read
    source = tmp_path / "Scans"
    out = source / "SplitScan"
    out.mkdir(parents=True)
    one = source / "scan21092026.pdf"
    one.write_bytes(b"%PDF-1.4\n")
    # What Windows returns: the same file for both patterns.
    monkeypatch.setattr(type(source), "glob", lambda self, pattern: iter([one]))
    assert [p.name for p in scans_to_read(source, out)] == ["scan21092026.pdf"]


def test_only_recent_scans_can_be_asked_for(tmp_path):
    """The folder holds 948 items going back months, so the first run is the long one."""
    import os
    import time

    from split_delivery_notes import scans_to_read
    source = tmp_path / "Scans"
    out = source / "SplitScan"
    out.mkdir(parents=True)
    fresh, stale = source / "today.pdf", source / "august.pdf"
    for f in (fresh, stale):
        f.write_bytes(b"%PDF-1.4\n")
    old = time.time() - (40 * 86400)
    os.utime(stale, (old, old))
    assert [p.name for p in scans_to_read(source, out, since_days=7)] == ["today.pdf"]
    assert len(scans_to_read(source, out)) == 2, "no --since must still take everything"


def test_the_scheduled_task_installer_defaults_to_the_same_place():
    """Two defaults that disagree is how the button and the nightly run file to two folders."""
    from split_delivery_notes import DEFAULT_OUT
    ps1 = (ROOT / "tools" / "logistics" / "Install-SplitScanTask.ps1").read_text(
        encoding="utf-8")
    assert DEFAULT_OUT in ps1


# ── the endpoint ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def routes(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    import estimate_routes
    monkeypatch.setattr(estimate_routes.config, "FILE_ROOTS", [str(tmp_path)], raising=False)
    monkeypatch.setattr(estimate_routes, "_check_key", lambda _k: None)
    return estimate_routes


def test_a_folder_outside_the_shares_is_refused(routes, tmp_path):
    """It takes a path from a request and runs a process on it, so it follows the same
    containment rule as every other route on this service."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        routes.logistics_split_scans(
            routes.SplitScansRequest(source="/etc", out=str(tmp_path)), None)
    assert caught.value.status_code == 403


def test_an_output_folder_outside_the_shares_is_refused(routes, tmp_path):
    from fastapi import HTTPException
    source = tmp_path / "in"
    source.mkdir()
    with pytest.raises(HTTPException) as caught:
        routes.logistics_split_scans(
            routes.SplitScansRequest(source=str(source), out="/etc/passwd"), None)
    assert caught.value.status_code == 403


def test_the_route_runs_the_same_script_the_task_runs(routes, tmp_path, monkeypatch):
    """Checked on the command it builds, because the alternative is a second copy of the
    reading logic living behind the button."""
    source = tmp_path / "in"
    source.mkdir()
    seen = {}

    class _Done:
        returncode = 0
        stdout = "  30022230 Tesco.pdf  (written, page(s) 1 of scan.pdf)\n1 delivery note(s)"
        stderr = ""

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _Done()

    monkeypatch.setattr(routes.subprocess, "run", _fake_run)
    out = routes.logistics_split_scans(
        routes.SplitScansRequest(source=str(source), out=str(tmp_path), dry_run=True), None)

    assert out["ok"] is True
    assert "1 delivery note(s)" in out["summary"]
    assert any(str(c).endswith("split_delivery_notes.py") for c in seen["cmd"])
    assert "--dry-run" in seen["cmd"]


def test_a_missing_tesseract_is_explained_rather_than_echoed(routes, tmp_path, monkeypatch):
    """The scans have no text layer at all, so this is the one failure a user will actually
    hit on a new machine, and "returncode 1" tells them nothing."""
    from fastapi import HTTPException

    source = tmp_path / "in"
    source.mkdir()

    class _Failed:
        returncode = 1
        stdout = ""
        stderr = "RuntimeError: tesseract could not be run: [Errno 2] No such file"

    monkeypatch.setattr(routes.subprocess, "run", lambda cmd, **kw: _Failed())
    with pytest.raises(HTTPException) as caught:
        routes.logistics_split_scans(
            routes.SplitScansRequest(source=str(source), out=str(tmp_path)), None)
    assert caught.value.status_code == 502
    assert "no text layer" in str(caught.value.detail)


# ── the front door ──────────────────────────────────────────────────────────────────

def test_a_missing_source_folder_is_refused_loudly(tmp_path, capsys):
    """THE FIRST LIVE RUN PRINTED "0 delivery note(s)" AND EXITED 0.

    Nothing was wrong with the reading — nothing had been read, because `Path.glob` on a
    folder that does not exist returns no files and no error. A typo, a VPN down, a task with
    no drive mapping and a permissions problem all look identical from inside the loop, and
    all of them are obvious the moment the path is printed.

    This file has comments about that failure mode in three places and did not guard its own
    front door.
    """
    import split_delivery_notes as S

    code = S.main.__wrapped__ if hasattr(S.main, "__wrapped__") else S.main
    sys.argv = ["split", "--source", str(tmp_path / "not-there"),
                "--out", str(tmp_path / "out")]
    assert code() == 2
    said = capsys.readouterr().out
    assert "does not exist" in said
    assert str(tmp_path / "not-there") in said, "it must name the folder it could not reach"


def test_it_always_says_where_it_looked_and_what_it_found(tmp_path, capsys):
    """A run that finds nothing and a run that was pointed at the wrong share read the same
    on the console unless it says which folder and how many files."""
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    (source / "SplitScan").mkdir(parents=True)
    (source / "a.pdf").write_bytes(b"%PDF-1.4\n")
    sys.argv = ["split", "--source", str(source), "--out", str(source / "SplitScan"),
                "--dry-run", "--since", "7"]
    S.main()
    said = capsys.readouterr().out
    assert str(source) in said
    assert "1 PDF(s) in the folder" in said
    assert "last 7 day(s)" in said
