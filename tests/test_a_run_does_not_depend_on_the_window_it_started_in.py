r"""
test_a_run_does_not_depend_on_the_window_it_started_in.py

A RUN WHOSE BEHAVIOUR DEPENDS ON THE SHELL IT WAS STARTED FROM IS A RUN NOBODY CAN REPRODUCE.

main.py loads C:\ClaudeVision\.env before anything reads os.environ, resolved from __file__
rather than the working directory -- so the ENGINE's switches are the same however it was
started. Two gaps sat either side of that.

THE RUNNER DID NOT LOAD .env AT ALL. SDI_ENGINE_ROOT, SDI_SERVER, SDI_API_KEY and
SDI_ENGINE_PYTHON came from whichever PowerShell window happened to launch it. SDI_ENGINE_ROOT
is the worst: point it at a stale checkout and the web page silently estimates with code
nobody has pulled, while the console reports a healthy runner.

AND .env LOSES EVERY DISAGREEMENT, SILENTLY. load_dotenv does not override an existing
variable, and it should not -- a deliberate `SDI_OFFLINE=1 python main.py` has to keep
working. But that made a variable left set in one window beat the file, with nothing anywhere
saying which value was used. This project has paid for that twice already: SDI_SW_RUN_ANALYSER
read in one place and set nowhere, and a morning lost to an elevated console.

Precedence is unchanged. The shadowing is said out loud.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

RUNNER = ROOT / "tools" / "runner" / "sdi_estimate_runner.py"
MAIN = ROOT / "src" / "main.py"
CONFIG = ROOT / "src" / "config.py"


# ── the runner reads the same file the engine does ──────────────────────────────────
# ASSERTED ON THE CALL, NOT THE DEFINITION. The first version matched the string
# "load_dotenv" and the string "_load_engine_env()" anywhere in the file -- so deleting the
# CALL left the def in place and the test passed, and moving the call inside main() matched
# the `def` line first and the ordering test passed too. Two mutants survived a test written
# to catch exactly them. Third time today: test the caller, not the helper.
def _module_level_calls(path: Path, name: str):
    """Line numbers where `name()` is called at module scope, not merely defined."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in tree.body:                    # module scope ONLY
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name) and node.value.func.id == name:
            out.append(node.lineno)
    return out


def _first_getenv_default(path: Path, var: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "getenv" and node.args \
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == var:
            return node.lineno
    pytest.fail(f"the runner no longer reads {var}")


def test_the_runner_actually_calls_the_env_loader():
    calls = _module_level_calls(RUNNER, "_load_engine_env")
    assert calls, (
        "the runner defines a .env loader and never calls it, so SDI_ENGINE_ROOT, SDI_SERVER "
        "and SDI_API_KEY still come from whichever window started it")


def test_the_loader_runs_before_any_default_is_read_from_the_shell():
    """os.getenv is evaluated when the argument parser is BUILT. Loading .env afterwards
    leaves every default already taken from the shell."""
    call = _module_level_calls(RUNNER, "_load_engine_env")[0]
    assert call < _first_getenv_default(RUNNER, "SDI_ENGINE_ROOT"), \
        "the .env load runs after the defaults have already been read from the shell"


def test_the_loader_reads_a_real_dotenv():
    body = ast.unparse(ast.parse(RUNNER.read_text(encoding="utf-8")))
    assert "load_dotenv" in body


def test_the_runner_finds_it_from_its_own_location():
    """Not from the working directory. A runner started from anywhere must read the same
    file, or the fragility just moves from the window to the folder it was opened in."""
    body = ast.unparse(ast.parse(RUNNER.read_text(encoding="utf-8")))
    assert "Path(__file__).resolve()" in body
    assert "os.getcwd" not in body


def test_the_announcement_comes_before_the_load():
    """The announcement compares the shell against the file, so it has to run BEFORE
    load_dotenv -- afterwards there is nothing left to compare.

    This used to live in main.py. It is now inside config.load_dot_env, the one loader, so
    every entry point gets it and not just a run through main. See
    test_settings_come_from_the_file_not_the_window.py for why that moved.
    """
    tree = ast.parse(CONFIG.read_text(encoding="utf-8"))
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "load_dot_env"), None)
    assert fn is not None, "config.load_dot_env is gone"
    announce = [n.lineno for n in ast.walk(fn)
                if isinstance(n, ast.If) and ast.unparse(n.test) == "announce"]
    load = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "load_dotenv"]
    assert announce, "load_dot_env never announces what the shell is overriding"
    assert load, "load_dot_env no longer loads .env"
    assert min(announce) < min(load), \
        "the announcement runs after load_dotenv, when there is nothing left to compare"


# ── and a shell override is announced, not silent ───────────────────────────────────
# EXERCISED THROUGH THE REAL LOADER, pointed at a temporary directory. The previous version
# exec'd the announcement function out of main.py in isolation, which is how the call site
# came to be deleted with every test still green.
@pytest.fixture
def load():
    pytest.importorskip("dotenv")
    import config
    return config.load_dot_env


def _env_file(tmp_path, **pairs):
    (tmp_path / ".env").write_text("\n".join(f"{k}={v}" for k, v in pairs.items()),
                                   encoding="utf-8")
    return tmp_path


def test_a_shadowed_switch_is_named(load, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SDI_OFFLINE", "1")
    load(root=_env_file(tmp_path, SDI_OFFLINE="0"))
    said = capsys.readouterr().out
    assert "SDI_OFFLINE comes from THIS SHELL" in said
    assert "'1' overrides '0'" in said, "say both values or nobody can tell which run they got"


def test_a_secret_is_never_printed(load, tmp_path, monkeypatch, capsys):
    """The whole point is to name the variable. Naming its VALUE would put a live key in
    every console log and in whatever captures them."""
    monkeypatch.setenv("XAI_API_KEY", "xai-real-key-do-not-print")
    load(root=_env_file(tmp_path, XAI_API_KEY="xai-other-key"))
    said = capsys.readouterr().out
    assert "XAI_API_KEY comes from THIS SHELL" in said
    assert "xai-real-key-do-not-print" not in said and "xai-other-key" not in said
    assert "<hidden>" in said


def test_agreement_is_not_announced(load, tmp_path, monkeypatch, capsys):
    """A message that prints when nothing is wrong stops being read, and this one has to be
    trusted on the day it matters."""
    monkeypatch.setenv("SDI_OFFLINE", "1")
    load(root=_env_file(tmp_path, SDI_OFFLINE="1"))
    assert "THIS SHELL" not in capsys.readouterr().out


def test_a_variable_only_in_the_file_is_not_announced(load, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SDI_SW_RUN_ANALYSER", raising=False)
    load(root=_env_file(tmp_path, SDI_SW_RUN_ANALYSER="1"))
    assert "THIS SHELL" not in capsys.readouterr().out


def test_a_missing_or_unreadable_file_is_silent(load, tmp_path, capsys):
    """Announcing is a courtesy and must never be the thing that stops a run."""
    assert load(root=tmp_path / "no-such-dir") is False
    assert capsys.readouterr().out == ""


def test_precedence_is_unchanged(load, tmp_path, monkeypatch):
    """It REPORTS. It must not start winning arguments -- a deliberate SDI_OFFLINE=1 in a
    test harness has to keep working, and this file is proof that was considered."""
    monkeypatch.setenv("SDI_OFFLINE", "1")
    load(root=_env_file(tmp_path, SDI_OFFLINE="0"))
    assert os.environ["SDI_OFFLINE"] == "1"
