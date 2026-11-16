r"""
test_the_runner_dials_the_page_the_service_serves.py

TWO DEFAULTS FOR ONE NUMBER, and the runner held the wrong one.

The SDI Estimating Intelligence page showed "No runner connected - estimates cannot be run"
and went on showing it. Nothing was broken. The page is served by the installed Windows
service on 8071, which is config.py's default; start-runner.ps1 defaulted to 8072, which is
the port start-service.ps1 uses ON PURPOSE for a hand-started copy because 8071 is already
held. So a runner started with no arguments connected to a service nobody was looking at,
reported itself healthy in its own window, and the page it was meant to serve stayed red.

THEN IT HAPPENED AGAIN, THE OTHER WAY ROUND. The rule used to be "make the two defaults
agree", and the runner's default was changed from 8072 to 8071 to satisfy it. Then the
installed 8071 service was stopped for testing, the hand-started 8072 one was the only live
service, and a runner started with no arguments polled 8071 into silence -- reporting itself
healthy, with the page red, exactly as before.

A default cannot be right, because WHICH service is live changes. So the rule changed: the
runner ASKS. It probes SDI_PORT, then 8072, then 8071, serves whichever answers /api/health,
and REFUSES TO START when nothing does -- in the window somebody is looking at, rather than
leaving the fact on a page they are not.

These tests hold that shape: no hard-coded port stands alone, the probe exists, and a dead
port stops the runner instead of being polled for ever.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PS1 = ROOT / "tools" / "start" / "start-runner.ps1"
SERVICE_PS1 = ROOT / "tools" / "start" / "start-service.ps1"
BACKEND_CONFIG = ROOT / "sdi-intelligence-backend" / "config.py"


def _read(p: Path) -> str:
    # utf-8-sig: these scripts carry a BOM deliberately, so PowerShell 5.1 reads them as
    # UTF-8 rather than in the system codepage. See the note in start-service.ps1.
    return p.read_text(encoding="utf-8-sig", errors="replace")


def _service_default_port() -> str:
    """The port app.py listens on when nothing overrides it. The one real answer."""
    m = re.search(r'PORT\s*=\s*int\(_opt\(\s*"SDI_PORT"\s*,\s*"(\d+)"\s*\)\)', _read(BACKEND_CONFIG))
    assert m, "config.py no longer declares a default SDI_PORT in the form this reads"
    return m.group(1)


def test_the_runner_does_not_hard_code_one_port_as_its_default():
    """A baked-in default has now been wrong in both directions.

    Whichever number is written here is correct only while that service happens to be the
    live one, and which is live changes with what somebody started this morning.
    """
    body = _read(RUNNER_PS1)
    m = re.search(r'\[string\]\s*\$Server\s*=\s*("")', body)
    assert m, (
        "start-runner.ps1 declares a hard-coded default server again. That has failed twice: "
        "as 8072 while the page was on 8071, and as 8071 once the 8071 service was stopped. "
        "The default must be empty and the port discovered.")


def test_the_runner_probes_before_it_polls():
    """The failure was never that the port was wrong. It was that a runner polling nothing
    looks exactly like a runner working, in a window nobody doubts."""
    body = _read(RUNNER_PS1)
    assert "/api/health" in body, \
        "start-runner.ps1 never asks whether anything is there before it starts polling"
    probe_at = body.index("/api/health")
    launch_at = body.rindex("& $python $runner")
    assert probe_at < launch_at, "the probe must happen BEFORE the runner is launched"


def test_a_dead_port_stops_the_runner_rather_than_being_polled_for_ever():
    body = _read(RUNNER_PS1)
    assert "exit 1" in body, "nothing answering must stop the runner, not start it anyway"
    assert "start-service.ps1" in body, \
        "and the message must say how to fix it, not merely that it is broken"


def test_the_runner_still_honours_sdi_port_first():
    """A window that already knows the port is believed, ahead of any probing order."""
    body = _read(RUNNER_PS1)
    assert "$env:SDI_PORT" in body, "start-runner.ps1 ignores SDI_PORT"
    assert body.index("$env:SDI_PORT") < body.rindex("& $python $runner"), \
        "SDI_PORT must be consulted while choosing the server, not after launching"


def test_the_hand_started_service_keeps_its_own_port_on_purpose():
    """start-service.ps1's 8072 is NOT the bug and must not be 'fixed' to match. 8071 is held
    by the installed service; the whole point of that default is to start a second copy
    without fighting it. Recorded here so the next person reads the reason before changing
    it, rather than making both files agree in the wrong direction."""
    body = _read(SERVICE_PS1)
    m = re.search(r'\[int\]\s*\$Port\s*=\s*(\d+)', body)
    assert m, "start-service.ps1 no longer declares a default -Port"
    assert m.group(1) != _service_default_port(), (
        "start-service.ps1 now defaults to the same port as the installed service, so a "
        "hand-started copy will collide with it. That default is deliberately different.")
    assert "already held" in body or "collides" in body, \
        "the reason that default differs is no longer written down next to it"


@pytest.mark.parametrize("script", [RUNNER_PS1, SERVICE_PS1])
def test_the_start_scripts_stay_ascii(script):
    """PowerShell 5.1 reads a .ps1 in the system codepage unless it carries a BOM, so one em
    dash arrives as three bytes of nonsense, ends a string early, and produces a parse error
    pointing thirty lines from the real one. Both files say this at the top; this is the
    check that makes saying it worth anything."""
    body = _read(script)
    bad = sorted({ch for ch in body if ord(ch) > 127})
    assert not bad, (
        f"{script.name} contains non-ASCII characters {bad!r}. Windows PowerShell 5.1 will "
        f"mis-read them and fail with a parse error nowhere near the real line.")
