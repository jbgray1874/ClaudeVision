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
    The listing is faked here because this filesystem is case-sensitive and cannot show it.
    """
    from split_delivery_notes import scans_to_read
    source = tmp_path / "Scans"
    out = source / "SplitScan"
    out.mkdir(parents=True)
    one = source / "scan21092026.pdf"
    one.write_bytes(b"%PDF-1.4\n")
    # What a doubled listing looks like: the same file twice.
    monkeypatch.setattr(type(source), "iterdir", lambda self: iter([one, one]))
    assert [p.name for p in scans_to_read(source, out)] == ["scan21092026.pdf"]


def test_an_uppercase_extension_is_still_a_scan(tmp_path):
    """The scanner's naming is not ours to rely on, and .PDF is a PDF."""
    from split_delivery_notes import scans_to_read
    source = tmp_path / "Scans"
    (source / "SplitScan").mkdir(parents=True)
    (source / "SCAN21092026.PDF").write_bytes(b"%PDF-1.4\n")
    (source / "notes.txt").write_bytes(b"not a scan")
    assert [p.name for p in scans_to_read(source, source / "SplitScan")] == [
        "SCAN21092026.PDF"]


def test_a_folder_that_cannot_be_listed_says_so_rather_than_reading_as_empty(tmp_path):
    """THE FAILURE THIS REPLACES. `source.glob("*.pdf")` returns nothing when the folder
    cannot be enumerated, nothing when the scans are one level down, and nothing when the
    day was genuinely quiet — three different situations, one line of output. The real share
    reported `0 PDF(s) in the folder` for a folder Explorer shows 948 items in."""
    from split_delivery_notes import scans_to_read
    source = tmp_path / "Scans"
    source.mkdir()
    out = source / "SplitScan"

    def _refuse(self):
        raise PermissionError(13, "Access is denied")

    original = type(source).iterdir
    try:
        type(source).iterdir = _refuse
        with pytest.raises(RuntimeError) as caught:
            scans_to_read(source, out)
    finally:
        type(source).iterdir = original
    assert "cannot list" in str(caught.value)
    assert str(source) in str(caught.value)


def test_scans_in_subfolders_are_reached_only_when_asked_for(tmp_path):
    """The share may file by date. Recursing by default would also pull in whatever else
    lives under Scans, so it is a flag — but the flag has to work."""
    from split_delivery_notes import scans_to_read
    source = tmp_path / "Scans"
    day = source / "21-09-2026"
    day.mkdir(parents=True)
    (source / "SplitScan").mkdir()
    (day / "scan001.pdf").write_bytes(b"%PDF-1.4\n")
    out = source / "SplitScan"
    assert scans_to_read(source, out) == []
    assert [p.name for p in scans_to_read(source, out, recurse=True)] == ["scan001.pdf"]


def test_recursing_still_does_not_read_back_what_it_wrote(tmp_path):
    """SplitScan is a CHILD of Scans, so --recurse walks straight into the output folder
    unless it is excluded by name — every note re-split into a one-page note named after
    itself, for ever."""
    from split_delivery_notes import scans_to_read
    source = tmp_path / "Scans"
    out = source / "SplitScan"
    (out / "_Unsorted").mkdir(parents=True)
    (source / "scan21092026.pdf").write_bytes(b"%PDF-1.4\n")
    (out / "30022230 Tesco.pdf").write_bytes(b"%PDF-1.4\n")
    (out / "_Unsorted" / "scan21092026 p3.pdf").write_bytes(b"%PDF-1.4\n")
    assert [p.name for p in scans_to_read(source, out, recurse=True)] == [
        "scan21092026.pdf"]


def test_two_date_folders_may_each_hold_a_scan_of_the_same_name(tmp_path, monkeypatch):
    """A ledger keyed on the bare filename lets one day's scan001.pdf mask another's."""
    from split_delivery_notes import _ledger_key
    source = tmp_path / "Scans"
    a = source / "21-09-2026" / "scan001.pdf"
    b = source / "22-09-2026" / "scan001.pdf"
    assert _ledger_key(a, source) != _ledger_key(b, source)


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


def test_a_folder_with_no_pdfs_says_what_is_in_it(tmp_path, capsys):
    """"0 PDF(s) in the folder" is the same sentence for a quiet day and for a folder of 948
    things none of which the job could see. It has to say which."""
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    (source / "SplitScan").mkdir(parents=True)
    (source / "21-09-2026").mkdir()
    (source / "index.csv").write_bytes(b"a,b\n")
    sys.argv = ["split", "--source", str(source), "--out", str(source / "SplitScan"),
                "--dry-run"]
    S.main()
    said = capsys.readouterr().out
    assert "0 PDF(s) in the folder" in said
    assert "1 file(s)" in said and "folder(s)" in said
    assert ".csv" in said
    assert "--recurse" in said, "a folder of subfolders must point at the flag that reads them"


def test_the_job_does_not_build_the_share_it_was_told_to_check(tmp_path, capsys):
    """HOW THE GUESSED UNC BECAME A REAL FOLDER.

    `out_dir.mkdir(parents=True)` on \\\\...\\Logistics\\Scans\\SplitScan created Logistics,
    then Scans, then SplitScan, on a share where none of them existed. The next run found
    its source folder present — it had just been made — empty, and reported a quiet day.
    Test-Path said True. The front-door guard added for exactly this could not fire, because
    the job had already answered its own question.

    It creates the output folder. It does not create the tree above it.
    """
    from split_delivery_notes import prepare_out
    nowhere = tmp_path / "Logistics" / "Scans" / "SplitScan"
    with pytest.raises(RuntimeError) as caught:
        prepare_out(nowhere)
    assert not (tmp_path / "Logistics").exists(), "it built the path it was checking"
    assert str(nowhere.parent) in str(caught.value)

    # The ordinary case is untouched: the folder above exists, so the output folder is made.
    nowhere.parent.mkdir(parents=True)
    prepare_out(nowhere)
    assert nowhere.is_dir()


def test_a_scan_folder_holding_only_our_own_output_is_not_a_quiet_day(tmp_path, capsys):
    """The symptom on the real share: 0 files, 1 folder, and the folder was SplitScan.

    That is not an empty day's post. It is a path that was created rather than found, and
    saying "nothing to do" about it sends somebody looking at the scanner.
    """
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    (source / "SplitScan").mkdir(parents=True)
    sys.argv = ["split", "--source", str(source), "--out", str(source / "SplitScan"),
                "--dry-run"]
    S.main()
    said = capsys.readouterr().out
    assert "this job's own output folder" in said
    assert "CREATED rather than found" in said
    assert "DisplayRoot" in said, "it must say how to find the real share"


def test_the_front_door_refuses_an_output_path_with_no_parent(tmp_path, capsys):
    """Exit 2 rather than manufacture the tree, and say how to get the real path."""
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    source.mkdir()
    sys.argv = ["split", "--source", str(source),
                "--out", str(tmp_path / "typo" / "Scans" / "SplitScan"), "--dry-run"]
    assert S.main() == 2
    assert not (tmp_path / "typo").exists()
    said = capsys.readouterr().out
    assert "Refusing to create it" in said


def test_finding_a_mapped_drives_real_name_does_not_rest_on_net_use(capsys):
    """`net use` printed "There are no entries in the list." for a drive that is mapped —
    Group Policy and logon-script mappings do not appear there. Advice that stops at
    `net use` reads as "the drive is not really mapped", which is how a guess gets made."""
    from split_delivery_notes import _how_to_find_the_share
    _how_to_find_the_share(Path(r"K:\Logistics\Scans"))
    said = capsys.readouterr().out
    assert "(Get-PSDrive K).DisplayRoot" in said
    assert "Win32_LogicalDisk" in said
    assert "net use" in said and "does not mean" in said


def test_a_folder_that_refuses_to_be_listed_is_not_reported_as_a_quiet_day(tmp_path, capsys):
    """Exit 2, not 0. A job that cannot read the share must not report success."""
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    source.mkdir()

    def _refuse(self):
        raise PermissionError(13, "Access is denied")

    original = type(source).iterdir
    sys.argv = ["split", "--source", str(source), "--out", str(source / "SplitScan"),
                "--dry-run"]
    try:
        type(source).iterdir = _refuse
        assert S.main() == 2
    finally:
        type(source).iterdir = original
    said = capsys.readouterr().out
    assert "cannot list" in said
    assert "Access is denied" in said
