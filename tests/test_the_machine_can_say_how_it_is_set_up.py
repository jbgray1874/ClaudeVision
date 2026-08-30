r"""
test_the_machine_can_say_how_it_is_set_up.py

EVERY ENVIRONMENT FAULT THIS PROJECT HAS HIT LOOKED LIKE SOMETHING ELSE.

SDI_SW_RUN_ANALYSER was read in one place and set nowhere, so SolidWorks extraction was off
for weeks and the estimates merely looked drawings-only. A console left elevated made the
database time out while the same test from a normal window succeeded instantly. The runner
took SDI_ENGINE_ROOT from whichever PowerShell window launched it, so the page could estimate
with a checkout nobody had pulled while reporting itself healthy.

None announced themselves. Each was found days later by somebody chasing a wrong number, and
in every case the machine could have said so in a second if anything had asked.

The checker DISCOVERS the switches by reading the source. A hardcoded list is the thing that
drifts -- this project already shipped a switch read in one place, set nowhere, documented in
neither README, and a checker carrying its own list would have called that setup healthy.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "diagnose"))

import environment_check as ec  # noqa: E402


# ── it finds the switches by reading, not by remembering ────────────────────────────
def test_it_discovers_the_switches_from_the_source():
    found = ec.switches_the_code_reads()
    assert "SDI_SW_RUN_ANALYSER" in found, "the switch that caused the regression is not found"
    assert "SDI_ENGINE_ROOT" in found, "the runner's switches are not covered"
    assert "SDI_OFFLINE" in found
    assert len(found) > 20, "too few switches found; the reader has stopped reading"


def test_it_names_who_reads_each_one():
    """"SDI_ENGINE_ROOT is unset" is not actionable. "unset, and the runner reads it" is."""
    found = ec.switches_the_code_reads()
    assert "runner" in found["SDI_ENGINE_ROOT"]
    assert found["SDI_SW_RUN_ANALYSER"].endswith(".py")


def test_it_finds_every_way_the_code_asks(tmp_path):
    """os.environ.get, os.getenv and os.environ[...] are all used in this codebase. Reading
    two of the three would report a switch as unread while something reads it."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text(
        'import os\n'
        'a = os.environ.get("SDI_ALPHA")\n'
        'b = os.getenv("SDI_BETA", "x")\n'
        'c = os.environ["SDI_GAMMA"]\n', encoding="utf-8")
    saved, ec.ROOT = ec.ROOT, tmp_path
    try:
        found = ec.switches_the_code_reads("src")
    finally:
        ec.ROOT = saved
    assert set(found) == {"SDI_ALPHA", "SDI_BETA", "SDI_GAMMA"}


def test_operating_system_variables_are_not_listed():
    """PATH and TEMP are read, and listing them would bury the handful that decide what an
    estimate does."""
    found = ec.switches_the_code_reads()
    assert not ({"PATH", "TEMP", "USERNAME", "VIRTUAL_ENV"} & set(found))


# ── a value that must never be printed ──────────────────────────────────────────────
@pytest.mark.parametrize("name", ["XAI_API_KEY", "SDI_API_KEY", "SDI_DB_PASSWORD",
                                  "BH_CLIENT_SECRET", "SQL_CONNECTION_STRING"])
def test_a_secret_is_described_never_shown(name):
    shown = ec._show(name, "super-secret-live-value")
    assert "super-secret-live-value" not in shown
    assert "chars" in shown, "say that it IS set, or an unset key looks the same as a set one"


def test_an_empty_secret_is_distinguished_from_an_absent_one():
    """A key set to "" is a different fault from a key nobody set, and they need different
    fixes. The distinction between a recorded nothing and an absence, again."""
    assert ec._show("XAI_API_KEY", "") != ec._show("XAI_API_KEY", None)


def test_a_plain_switch_shows_its_value():
    assert ec._show("SDI_SW_RUN_ANALYSER", "0") == "'0'"


# ── and it actually reports the faults that have bitten ─────────────────────────────
def _run(env):
    full = dict(os.environ)
    full.update(env)
    full["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "diagnose" / "environment_check.py")],
        capture_output=True, text=True, env=full, cwd=str(ROOT))


def test_the_analyser_being_off_is_reported_and_fails():
    out = _run({"SDI_SW_RUN_ANALYSER": "0"})
    assert "OFF" in out.stdout and "drawings-only" in out.stdout
    assert out.returncode == 1, "a machine that cannot read models must not report itself well"


def test_the_analyser_unset_reads_as_on():
    """Unset means ON, and a checker that said otherwise would send somebody to fix a
    non-problem -- the polarity of this default has already been got wrong once."""
    env = {k: v for k, v in os.environ.items() if k != "SDI_SW_RUN_ANALYSER"}
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "diagnose" / "environment_check.py")],
        capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert "SolidWorks native extraction : ON" in out.stdout


def test_offline_is_reported():
    assert "SDI_OFFLINE is set" in _run({"SDI_OFFLINE": "1"}).stdout


def test_it_changes_nothing():
    """Safe to run any time. A diagnostic that writes is one nobody dares run on the machine
    that matters."""
    import ast
    body = ast.unparse(ast.parse(
        (ROOT / "tools" / "diagnose" / "environment_check.py").read_text(encoding="utf-8")))
    for forbidden in ("write_text(", "os.environ[", "load_dotenv(", "makedirs", "unlink"):
        assert forbidden not in body, f"the checker {forbidden} — it must only read"
