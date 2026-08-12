r"""
test_the_runner_dials_the_page_the_service_serves.py

TWO DEFAULTS FOR ONE NUMBER, and the runner held the wrong one.

The SDI Estimating Intelligence page showed "No runner connected - estimates cannot be run"
and went on showing it. Nothing was broken. The page is served by the installed Windows
service on 8071, which is config.py's default; start-runner.ps1 defaulted to 8072, which is
the port start-service.ps1 uses ON PURPOSE for a hand-started copy because 8071 is already
held. So a runner started with no arguments connected to a service nobody was looking at,
reported itself healthy in its own window, and the page it was meant to serve stayed red.

Nothing anywhere compared the two numbers. This does: the runner's default port is the port
the service defaults to serving on. It is a text read of two files and needs neither Windows
nor PowerShell, so it runs here.

The general shape is the one this codebase keeps meeting -- two rules for one question, each
correct in its own file. The rule here is that the DEFAULT must agree with the DEFAULT; an
explicit -Server is a deliberate override and is none of this test's business.
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


def _runner_default_port() -> str:
    """The port start-runner.ps1 dials when given no -Server."""
    m = re.search(r'\$Server\s*=\s*\(?"?http://localhost:(?:"?\s*\+\s*)?'
                  r'.*?(\d{4})', _read(RUNNER_PS1), re.DOTALL)
    assert m, "start-runner.ps1 no longer declares a default server in the form this reads"
    return m.group(1)


def test_the_runner_defaults_to_the_port_the_service_defaults_to():
    service, runner = _service_default_port(), _runner_default_port()
    assert runner == service, (
        f"start-runner.ps1 dials port {runner} by default; the service listens on {service} "
        f"by default. A runner started with no arguments therefore connects to a service the "
        f"page is not talking to, and the page shows 'No runner connected' forever while the "
        f"runner's own window reports itself healthy. Nothing in either process is wrong, "
        f"which is what makes it cost a morning.")


def test_the_runner_honours_sdi_port_before_its_own_default():
    """A window that already knows the port is believed. Otherwise setting SDI_PORT for the
    service and starting the runner in the same shell reintroduces the same split."""
    body = _read(RUNNER_PS1)
    assert "$env:SDI_PORT" in body, (
        "start-runner.ps1 ignores SDI_PORT, so a service moved off the default takes the "
        "runner with it only if somebody remembers -Server")
    assert body.index("$env:SDI_PORT") < body.index("$Root"), \
        "SDI_PORT must be consulted in the $Server default, not somewhere later"


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
