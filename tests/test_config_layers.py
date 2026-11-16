"""Which configuration file a value comes from, and which one wins.

The old arrangement was one committed .env doing two incompatible jobs: it
carried live credentials into the repository, and a git merge on a second
machine would overwrite that machine's settings with the first machine's.

    python -m pytest tests/test_config_layers.py -q
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"

_ABSENT = object()   # "config was not imported at all", which is not None


@pytest.fixture()
def load(tmp_path, monkeypatch):
    """Import config against a throwaway backend directory.

    PUT BACK WHAT YOU BORROW. Both the engine (src/) and the backend have a module
    called config. Importing one leaves it in sys.modules for every test that runs
    afterwards, and the first version of this fixture made ninety unrelated
    estimating tests fail: they imported the BACKEND's config and found none of
    the engine's rates in it. monkeypatch.delitem does not help, because it has
    nothing to restore when the key was absent at the moment it was called."""
    pytest.importorskip("dotenv", reason="python-dotenv not installed here")

    original = sys.modules.get("config", _ABSENT)
    fake = tmp_path / "backend"
    (fake / "env").mkdir(parents=True)
    (fake / "config.py").write_bytes((BACKEND / "config.py").read_bytes())

    def go(common=None, profile=None, dotenv=None, profile_name=None, environ=None):
        if common is not None:
            (fake / "env" / "common.env").write_text(common, encoding="utf-8")
        if profile is not None:
            (fake / "env" / f"{profile_name}.env").write_text(profile, encoding="utf-8")
        if dotenv is not None:
            (fake / ".env").write_text(dotenv, encoding="utf-8")

        for key in ("SDI_PORT", "SDI_API_KEY", "SDI_FILE_ROOTS",
                    "SDI_ALLOWED_ORIGINS", "SDI_PROFILE"):
            monkeypatch.delenv(key, raising=False)
        for key, value in (environ or {}).items():
            monkeypatch.setenv(key, value)
        if profile_name:
            monkeypatch.setenv("SDI_PROFILE", profile_name)

        monkeypatch.syspath_prepend(str(fake))
        sys.modules.pop("config", None)
        return importlib.import_module("config")

    try:
        yield go
    finally:
        if original is _ABSENT:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = original


def test_common_supplies_what_every_machine_shares(load):
    """And a UNC root survives the round trip. Raw strings on both sides, because
    counting backslashes through a Python literal into a file and back is how a
    path silently becomes a different path."""
    cfg = load(common="SDI_FILE_ROOTS=" + r"\\srv\a" + "\nSDI_ALLOWED_ORIGINS=*\n")
    assert cfg.FILE_ROOTS == [r"\\srv\a"]


def test_a_profile_beats_common(load):
    """Port differs per machine and is not a secret, so it belongs in a profile."""
    cfg = load(common="SDI_PORT=8071\nSDI_FILE_ROOTS=x\nSDI_ALLOWED_ORIGINS=*\n",
               profile="SDI_PORT=8072\n", profile_name="laptop")
    assert cfg.PORT == 8072


def test_dotenv_beats_a_profile(load):
    """.env is this machine's last word, and the only place a secret may live."""
    cfg = load(common="SDI_PORT=8071\nSDI_FILE_ROOTS=x\nSDI_ALLOWED_ORIGINS=*\n",
               profile="SDI_PORT=8072\n", profile_name="laptop",
               dotenv="SDI_PORT=8099\nSDI_API_KEY=secret\n")
    assert cfg.PORT == 8099
    assert cfg.API_KEY == "secret"


def test_the_real_environment_beats_every_file(load):
    """So a service can be started with a one-off port without editing anything —
    which is exactly what start-service.ps1 does."""
    cfg = load(common="SDI_PORT=8071\nSDI_FILE_ROOTS=x\nSDI_ALLOWED_ORIGINS=*\n",
               profile="SDI_PORT=8072\n", profile_name="laptop",
               dotenv="SDI_PORT=8099\n",
               environ={"SDI_PORT": "8073"})
    assert cfg.PORT == 8073


def test_a_missing_profile_is_not_an_error(load):
    """A machine with no profile of its own runs on common plus .env. Falling over
    because a file is absent would make every new machine a support call."""
    cfg = load(common="SDI_FILE_ROOTS=x\nSDI_ALLOWED_ORIGINS=*\n",
               profile_name="no-such-machine")
    assert cfg.FILE_ROOTS == ["x"]


def test_it_says_which_files_it_read(load, capsys):
    """An evening was lost to a port set in one window and not another."""
    load(common="SDI_FILE_ROOTS=x\nSDI_ALLOWED_ORIGINS=*\n",
         profile="SDI_PORT=8072\n", profile_name="laptop",
         dotenv="SDI_API_KEY=k\n")
    out = capsys.readouterr().out
    assert "[config]" in out
    for expected in (".env", "laptop.env", "common.env"):
        assert expected in out, f"{expected} was read and not reported"


def test_no_committed_file_may_hold_a_secret():
    """The rule the whole arrangement exists to enforce, checked rather than
    trusted: env/ is committed, so nothing in it may look like a credential."""
    suspicious = ("PASSWORD", "SECRET", "API_KEY", "CLIENT_SECRET", "TOKEN", "PWD")
    for path in (BACKEND / "env").glob("*.env"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            name = line.split("=", 1)[0].strip().upper()
            assert not any(s in name for s in suspicious), (
                f"{path.name} sets {name}, which belongs in .env — env/ is committed")
