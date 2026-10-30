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

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "logistics"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))


# ── the path the whole thing writes to ──────────────────────────────────────────────

def test_the_folders_are_a_setting_and_no_folder_is_guessed_in_source():
    """A GUESSED DEFAULT IS WORSE THAN NO DEFAULT.

    This file carried `\\\\sdi-dc01\\shareddata$\\Logistics\\Scans`, reasoned from two true
    facts: the estimating share IS `\\\\sdi-dc01\\shareddata$`, and the drive in Explorer
    reads `K:\\Logistics\\Scans`. The conclusion was wrong — and the job CREATED that tree
    rather than refusing it, after which the folder existed, `Test-Path` answered True, and
    the diagnosis went to `Path.glob`, to enumeration and to permissions, because the last
    thing anybody suspects is a folder the code made for itself.

    So: no server name in this source file at all. The folders are settings.
    """
    import importlib

    import split_delivery_notes as S
    # With nothing configured, there is no folder — not a plausible one.
    for name in ("SDI_SCAN_SOURCE_DIR", "SDI_SCAN_SPLIT_DIR"):
        os.environ.pop(name, None)
    sys.path.insert(0, str(ROOT / "src"))
    import config
    importlib.reload(config)
    assert importlib.reload(S).DEFAULT_SOURCE == ""
    assert S.DEFAULT_OUT == ""

    # And with the setting made, the default IS the setting — read, not guessed.
    os.environ["SDI_SCAN_SOURCE_DIR"] = r"\\a-server\a-share\Logistics\Scans"
    os.environ["SDI_SCAN_SPLIT_DIR"] = r"\\a-server\a-share\Logistics\Scans\SplitScan"
    try:
        importlib.reload(config)
        assert importlib.reload(S).DEFAULT_SOURCE == r"\\a-server\a-share\Logistics\Scans"
        assert S.DEFAULT_OUT.endswith("SplitScan")
    finally:
        for name in ("SDI_SCAN_SOURCE_DIR", "SDI_SCAN_SPLIT_DIR"):
            os.environ.pop(name, None)
        importlib.reload(config)
        importlib.reload(S)


def test_an_unset_folder_refuses_and_names_the_setting(tmp_path, capsys, monkeypatch):
    """"I do not know where the scans are" is a better answer than a plausible folder,
    because the plausible folder gets created and then believed."""
    import split_delivery_notes as S

    monkeypatch.setattr(S, "DEFAULT_SOURCE", "")
    monkeypatch.setattr(S, "DEFAULT_OUT", "")
    sys.argv = ["split", "--dry-run"]
    assert S.main() == 2
    said = capsys.readouterr().out
    assert "SDI_SCAN_SOURCE_DIR" in said
    assert ".env" in said
    assert "not a drive letter" in said


def test_the_setting_is_read_through_the_projects_one_config(monkeypatch):
    """James Gray: "config needs to be in config files. not json files lying around and
    being copied manually around." One .env, read by the module that reads every other
    setting — not a second loader with its own search order."""
    sys.path.insert(0, str(ROOT / "src"))
    import config
    assert hasattr(config, "SCAN_SOURCE_DIR")
    assert hasattr(config, "SCAN_SPLIT_DIR")
    assert config.dot_env_path().endswith(".env")
    # No default: unset must stay unset rather than become a share nobody named.
    monkeypatch.delenv("SDI_SCAN_SOURCE_DIR", raising=False)
    import importlib
    assert importlib.reload(config).SCAN_SOURCE_DIR == ""


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


def test_a_machine_with_no_ocr_is_said_once_and_exits_two(tmp_path, capsys, monkeypatch):
    """IT WAS SAID ONCE PER SCAN AND THE RUN EXITED 0.

    `run()` catches per file so one corrupt PDF does not cost the day — which turned a
    missing binary into four identical error lines on a `--since 1` run, and would have been
    947 of them on a full one, ending in "0 delivery note(s)" and a success code.

    A tool that is not installed is a fact about the machine: true before the first page is
    read and true after the last. It is checked once, before anything is rendered.
    """
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    (source / "SplitScan").mkdir(parents=True)
    (source / "scan.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(S, "find_tesseract", lambda explicit=None: None)
    sys.argv = ["split", "--source", str(source), "--out", str(source / "SplitScan"),
                "--dry-run"]
    assert S.main() == 2
    said = capsys.readouterr().out
    assert said.count("tesseract") < 4, "it is one machine, not one message per scan"
    assert "winget install" in said
    assert "NEW shell" in said, "a PATH change does not reach an open window"
    assert "SDI_TESSERACT_PATH" in said


def test_ocr_vanishing_mid_run_does_not_report_a_good_day(tmp_path, monkeypatch):
    """An update or a share going away mid-run must not be swallowed per file either."""
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    out = source / "SplitScan"
    out.mkdir(parents=True)
    (source / "scan.pdf").write_bytes(b"%PDF-1.4\n")

    def _gone(pdf, out_dir, **kw):
        raise S.NoOCR("tesseract could not be run")

    monkeypatch.setattr(S, "split_pdf", _gone)
    with pytest.raises(S.NoOCR):
        S.run(source, out, dry_run=True)


def test_one_bad_scan_still_does_not_cost_the_day(tmp_path, monkeypatch):
    """The other half of the same rule: a corrupt or password-protected PDF is reported and
    the rest of the folder is still split. Narrowing the catch must not have lost this."""
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    out = source / "SplitScan"
    out.mkdir(parents=True)
    for name in ("a.pdf", "b.pdf"):
        (source / name).write_bytes(b"%PDF-1.4\n")

    def _one_is_broken(pdf, out_dir, **kw):
        if pdf.name == "a.pdf":
            raise ValueError("cannot open broken document")
        return {"source": pdf.name, "pages": 1, "notes": [], "unsorted": []}

    monkeypatch.setattr(S, "split_pdf", _one_is_broken)
    report = S.run(source, out, dry_run=True)
    assert [r.get("error", "") != "" for r in report["results"]] == [True, False]
    assert "cannot open broken document" in report["results"][0]["error"]


def test_tesseract_is_found_where_its_installer_actually_puts_it(tmp_path, monkeypatch):
    """UB-Mannheim's package lands in C:\\Program Files\\Tesseract-OCR and leaves PATH
    alone, so `winget install` completes, reports success, and `tesseract` is still "not
    recognized". Looking in the usual places costs nothing and ends that."""
    import split_delivery_notes as S

    monkeypatch.setattr(S.shutil, "which", lambda _name: None)
    assert S.find_tesseract() is None or Path(S.find_tesseract()).is_file()

    # An explicit path wins, and a configured one is honoured.
    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"")
    assert S.find_tesseract(str(exe)) == str(exe)
    monkeypatch.setattr(S, "_configured", lambda name: str(exe) if "TESSERACT" in name else "")
    assert S.find_tesseract() == str(exe)


def test_ocr_output_is_read_as_utf8_whatever_the_machines_codepage(monkeypatch, tmp_path):
    """THREE REAL DELIVERY NOTES WENT TO _Unsorted ON THE FIRST WORKING RUN.

    Tesseract writes UTF-8. `subprocess.run(text=True)` decodes in the locale codepage,
    which on the logistics machine is cp1252 — and cp1252 has no character at 0x9d, the
    last byte of a curly quote. The reader thread died with a traceback, the page's text was
    lost, and a page with no text is not a delivery note.

    This fakes what Windows does: bytes decoded strictly in cp1252 unless an encoding is
    named. The text must come back whole.
    """
    import split_delivery_notes as S

    raw = 'Delivery Note N” 30022351\n'.encode("utf-8")   # …”… carries 0x9d

    class _Done:
        def __init__(self, text):
            self.stdout, self.stderr, self.returncode = text, "", 0

    def _windows_run(cmd, **kw):
        enc = kw.get("encoding")
        if enc is None:
            # What the locale does: strict cp1252, which raises on 0x9d.
            return _Done(raw.decode("cp1252"))
        return _Done(raw.decode(enc, kw.get("errors", "strict")))

    monkeypatch.setattr(S, "find_tesseract", lambda explicit=None: "tesseract")
    monkeypatch.setattr(S.subprocess, "run", _windows_run)
    text = S._tesseract(str(tmp_path / "values.png"))
    assert "30022351" in text
    assert "”" in text, "the curly quote must survive, not kill the read"


def test_a_listing_costs_one_round_trip_per_folder_not_per_file(tmp_path, monkeypatch):
    """THE RUN PRINTED ITS TWO PATHS AND SAT THERE.

    Every file was `resolve()`d — a call to the server each — and the front door listed the
    folder three times over, so a share of 947 scans cost some 3,000 round trips before a
    page was read. Free on a laptop; on a busy server, a run that appears to hang.
    """
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    out = source / "SplitScan"
    out.mkdir(parents=True)
    for n in range(40):
        (source / f"scan{n:03d}.pdf").write_bytes(b"%PDF-1.4\n")

    calls = {"resolve": 0}
    real_resolve = Path.resolve

    def _counted(self, *a, **kw):
        calls["resolve"] += 1
        return real_resolve(self, *a, **kw)

    monkeypatch.setattr(Path, "resolve", _counted)
    found = S.scans_to_read(source, out)
    assert len(found) == 40
    assert calls["resolve"] <= 2, f"{calls['resolve']} resolves for 40 files in one folder"


def test_the_front_door_lists_the_folder_once(tmp_path, monkeypatch, capsys):
    """`every`, `chosen` and then `run()` each listed the share afresh to read the same
    answer. The window is a filter on the listing, not a second listing."""
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    out = source / "SplitScan"
    out.mkdir(parents=True)
    (source / "scan.pdf").write_bytes(b"%PDF-1.4\n")
    listings = {"n": 0}
    real = S.folder_listing

    def _counted(*a, **kw):
        listings["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(S, "folder_listing", _counted)
    monkeypatch.setattr(S, "find_tesseract", lambda explicit=None: "tesseract")
    monkeypatch.setattr(S, "split_pdf", lambda pdf, out_dir, **kw: {
        "source": pdf.name, "pages": 1, "notes": [], "unsorted": []})
    sys.argv = ["split", "--source", str(source), "--out", str(out),
                "--dry-run", "--since", "7"]
    assert S.main() == 0
    assert listings["n"] == 1, f"the folder was listed {listings['n']} times"


def test_each_scan_is_announced_before_it_is_read(tmp_path, monkeypatch, capsys):
    """OCR is a minute or two for a day's post and silent while it works. A run that prints
    its count line and then nothing for ninety seconds is indistinguishable from one that
    has hung — which is what the person watching it concluded, twice."""
    import split_delivery_notes as S

    source = tmp_path / "Scans"
    out = source / "SplitScan"
    out.mkdir(parents=True)
    for name in ("a.pdf", "b.pdf"):
        (source / name).write_bytes(b"%PDF-1.4\n")
    order = []

    def _slow(pdf, out_dir, **kw):
        order.append(("read", pdf.name))
        return {"source": pdf.name, "pages": 1, "notes": [], "unsorted": []}

    monkeypatch.setattr(S, "split_pdf", _slow)
    S.run(source, out, dry_run=True,
          progress=lambda text: order.append(("said", text)))
    assert order == [("said", "  reading a.pdf (1 of 2) ..."), ("read", "a.pdf"),
                     ("said", "  reading b.pdf (2 of 2) ..."), ("read", "b.pdf")]

    # And the front door wires it up: the line reaches the console.
    monkeypatch.setattr(S, "find_tesseract", lambda explicit=None: "tesseract")
    sys.argv = ["split", "--source", str(source), "--out", str(out), "--dry-run"]
    S.main()
    assert "reading a.pdf (1 of 2)" in capsys.readouterr().out


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


def test_the_scheduled_task_installer_does_not_carry_its_own_guess():
    """Two defaults that disagree is how the button and the nightly run file to two folders,
    and a guess repeated in a second file is a guess that outlives its correction."""
    import re as _re
    ps1 = (ROOT / "tools" / "logistics" / "Install-SplitScanTask.ps1").read_text(
        encoding="utf-8")
    block = _re.search(r"^param\((.*?)^\)", ps1, _re.S | _re.M)
    assert block, "the installer has no param block"
    declared = block.group(1)
    assert not _re.search(r"=\s*['\"]\\\\", declared), (
        "a folder is hard-coded in the installer's parameters: " + declared)
    assert _re.search(r"\$Source\s*=\s*''", declared), declared
    assert _re.search(r"\$Out\s*=\s*''", declared), declared


def test_the_scheduled_task_reads_a_week_not_a_day_and_not_everything():
    """James Gray: "it runs for the current day only and won't duplicate runs?"

    `--since 1` is a rolling 24 hours from the moment the task fires, so at 06:30 a scan
    made at 06:00 the previous morning is already outside it, and a machine off over a
    weekend loses three days. And no `--since` at all would OCR all 947 on the first night.
    Seven catches the missed days and costs nothing, because a scan already split is
    skipped by its ledger without being read: the window is what gets LOOKED AT, not what
    gets done twice.
    """
    import re as _re
    ps1 = (ROOT / "tools" / "logistics" / "Install-SplitScanTask.ps1").read_text(
        encoding="utf-8")
    block = _re.search(r"^param\((.*?)^\)", ps1, _re.S | _re.M).group(1)
    assert _re.search(r"\$SinceDays\s*=\s*7\b", block), block
    assert _re.search(r"--since \{0\}' -f \$SinceDays", ps1), "the window must reach the task"


def test_the_task_says_whether_it_needs_somebody_logged_on():
    """A task registered for a named user with no password is INTERACTIVE-ONLY: it runs
    while that user is logged on and otherwise waits for the next logon. On a desktop used
    every morning that is workable; on one that is not it silently does nothing at 06:30.
    Either way it is a choice, and the installer must say which one was made."""
    import re as _re
    ps1 = (ROOT / "tools" / "logistics" / "Install-SplitScanTask.ps1").read_text(
        encoding="utf-8")
    block = _re.search(r"^param\((.*?)^\)", ps1, _re.S | _re.M).group(1)
    assert _re.search(r"\[switch\]\$RunWhenLoggedOff", block), block
    # The password is prompted for, never a parameter: a command line is in shell history.
    assert not _re.search(r"\$Password", block), "a password parameter is in the history"
    assert "Read-Host -AsSecureString" in ps1
    assert "runs only while" in ps1, "the default's consequence must be stated"


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
