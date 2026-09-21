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
    assert "sdi-dc01" in DEFAULT_OUT and "DeliveryNotesOutput" in DEFAULT_OUT
    assert ":" not in DEFAULT_OUT.replace("shareddata$", ""), "a drive letter crept back in"


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
