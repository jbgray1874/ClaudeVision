r"""
test_settings_come_from_the_file_not_the_window.py

WHAT WAS WRONG. config.py reads ten environment variables at import time -- the default job
quantity, the policy version, the powder rate per kg, the punch minimum, the canonical route
workbook, the wire and sheet steel rates -- and loaded no .env at all. main.py loaded .env,
before importing config, so a RUN through main.py was configured from the file.

Nothing else was. why_this_price.py, tools/pricing/udef_supplier_profile.py, check_tiers.py,
the runner's engine call and every test in this suite import config directly, and each of
them got whatever the shell happened to be holding, or a silent default. Two windows, two
answers, and nothing anywhere saying which had been used. That is a setting applied by
accident -- decided not by anyone choosing it but by which door the code was entered through.

So the loader moved into config, where the settings are read, and main.py's copy went. These
tests are about the CALL, not the function: a loader that exists and is not called is exactly
the bug that was already here, and this suite has been fooled by testing the helper instead
of the caller more than once today.

The last test is about the other direction of the same fault. A key set in .env under a name
nothing reads -- SERPAPI_API_KEY written as SERP_API_KEY -- gives a file that looks right, a
console that says nothing, and the feature behind it switched off.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "diagnose"))

import config  # noqa: E402


def _module(name: str) -> ast.Module:
    return ast.parse((ROOT / name).read_text(encoding="utf-8-sig", errors="replace"))


# ── one loader, and it is the one in config ─────────────────────────────────────────
def test_config_loads_the_env_file_at_import():
    """Not "config has a loader" -- config CALLS it, at module scope, unconditionally."""
    calls = [n for n in _module("src/config.py").body
             if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and isinstance(n.value.func, ast.Name) and n.value.func.id == "load_dot_env"]
    assert calls, ("config.py defines load_dot_env and never calls it at import. A loader "
                   "nobody calls is the exact defect this replaced.")


def test_the_load_happens_before_config_reads_any_environment_variable():
    """A gate that runs after the thing it gates decides nothing. config reads
    ESTIMATE_DEFAULT_JOB_QUANTITY, POWDER_MATERIAL_GBP_PER_KG and eight more at import; if
    .env is loaded below any of them, those keep taking the shell value silently."""
    tree = _module("src/config.py")
    load_at = min(n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "load_dot_env")
    reads = []
    # MODULE SCOPE ONLY. A read inside a function body happens when that function is called,
    # which is necessarily after import; the ones that decide an import-time constant are the
    # ones that have to come after the load. (Counting the loader's own announcement reads
    # would make this fail against correct code, which is how a guard gets deleted.)
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(top):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in {"getenv", "get"} \
                    and ast.unparse(node.func.value) in {"os", "os.environ"}:
                reads.append(node.lineno)
            elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                reads.append(node.lineno)
    assert reads, ("no module-scope os.environ read found in config.py at all — this guard "
                   "would pass vacuously, and config is known to read ten of them")
    early = [n for n in reads if n < load_at]
    assert not early, (f"config.py reads os.environ at line(s) {early}, before .env is "
                       f"loaded at line {load_at}. Those settings still come from the shell.")


def test_main_no_longer_carries_a_second_loader():
    """Two loaders with slightly different search orders is the shape of defect this
    codebase keeps paying for, and the asymmetry was worse than the duplication."""
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8-sig", errors="replace")
    tree = ast.parse(src)
    loaders = [ast.unparse(n)[:60] for n in ast.walk(tree)
               if isinstance(n, ast.Call)
               and "load_dotenv" in ast.unparse(n.func).lower()]
    assert not loaders, ("main.py calls load_dotenv itself again. config.load_dot_env is the "
                         f"one loader:\n  " + "\n  ".join(loaders))


def test_config_is_mains_first_engine_import():
    """Load-bearing ordering. Anything imported before config that reads os.environ at its
    own import time reads it before the file has been loaded."""
    stdlib = {"argparse", "json", "os", "re", "sys", "pathlib", "typing", "datetime", "math",
              "shutil", "subprocess", "time", "collections", "itertools", "logging", "csv",
              "traceback", "hashlib", "copy", "warnings", "dataclasses", "functools"}
    first = None
    for node in _module("src/main.py").body:
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        outside = [n for n in names if n and n not in stdlib]
        if outside:
            first = outside[0]
            break
    assert first == "config", (
        f"main.py's first non-stdlib import is {first!r}, not config. .env is loaded when "
        f"config is imported, so anything ahead of it reads the shell instead of the file.")


# ── the loader itself, pointed somewhere harmless ───────────────────────────────────
@pytest.fixture()
def env_file(tmp_path, monkeypatch):
    pytest.importorskip("dotenv")
    (tmp_path / ".env").write_text(
        "SDI_TEST_FROM_FILE=from-file\n"
        "SDI_TEST_SHADOWED=file-value\n"
        "SDI_TEST_API_KEY=file-secret\n", encoding="utf-8")
    for k in ("SDI_TEST_FROM_FILE", "SDI_TEST_SHADOWED", "SDI_TEST_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_a_value_in_the_file_reaches_the_environment(env_file):
    assert config.load_dot_env(announce=False, root=env_file) is True
    assert os.environ["SDI_TEST_FROM_FILE"] == "from-file"


def test_the_shell_still_wins_and_says_so(env_file, monkeypatch, capsys):
    """Precedence is unchanged -- a deliberate `SDI_OFFLINE=1 python ...` has to keep
    working. What changed is that the disagreement is spoken."""
    monkeypatch.setenv("SDI_TEST_SHADOWED", "shell-value")
    config.load_dot_env(announce=True, root=env_file)
    assert os.environ["SDI_TEST_SHADOWED"] == "shell-value"
    said = capsys.readouterr().out
    assert "SDI_TEST_SHADOWED" in said and "THIS SHELL" in said, (
        "a shell value silently beating the file is how a run becomes unreproducible")


def test_the_announcement_does_not_print_the_secret(env_file, monkeypatch, capsys):
    monkeypatch.setenv("SDI_TEST_API_KEY", "shell-secret")
    config.load_dot_env(announce=True, root=env_file)
    said = capsys.readouterr().out
    assert "SDI_TEST_API_KEY" in said, "the name must still be reported"
    assert "shell-secret" not in said and "file-secret" not in said, (
        "a credential printed here lands in every console log and screenshot")


def test_a_missing_file_is_reported_as_such(tmp_path):
    assert config.load_dot_env(announce=False, root=tmp_path) is False


# ── a key nothing reads is a switch that is off while the file looks right ──────────
import environment_check as ec  # noqa: E402


def test_a_misspelt_key_is_named_along_with_what_it_should_have_been():
    orphans = ec.keys_nothing_reads(
        on_file={"SERP_API_KEY": "x"},
        reads={"SERPAPI_API_KEY": "src/web_ai_price_lookup.py"},
        mentioned={})
    assert orphans == {"SERP_API_KEY": "~SERPAPI_API_KEY"}


def test_a_key_the_engine_reads_is_not_flagged():
    assert ec.keys_nothing_reads({"XAI_API_KEY": "x"},
                                 {"XAI_API_KEY": "src/llm_full_extract.py"}, {}) == {}


def test_a_key_read_only_by_a_probe_is_reported_separately():
    """Not a typo -- just not wired to anything that ships. Calling it a PROBLEM would be
    crying wolf, and a checker that cries wolf gets its findings ignored."""
    out = ec.keys_nothing_reads({"SDI_SOMETHING": "1"}, {}, {"SDI_SOMETHING": "src/_probe.py"})
    assert out == {"SDI_SOMETHING": "src/_probe.py"}


def test_an_unrecognisable_key_is_named_with_no_guess():
    assert ec.keys_nothing_reads({"COMPLETELY_MADE_UP": "7"}, {"SDI_OFFLINE": "x"}, {}) == {
        "COMPLETELY_MADE_UP": None}


def test_the_checker_actually_asks_and_fails_on_what_it_finds(monkeypatch, capsys):
    """THE CALLER, NOT THE HELPER. A check that returns the right answer to nobody is the
    same as no check, and this suite has already been fooled that way today."""
    monkeypatch.setattr(ec, "_dotenv_values",
                        lambda: (ROOT / ".env", {"SERP_API_KEY": "x"}))
    monkeypatch.setattr(ec, "switches_the_code_reads",
                        lambda *a: {"SERPAPI_API_KEY": "src/web_ai_price_lookup.py"})
    monkeypatch.setattr(ec, "_every_name_the_source_mentions", lambda: {})
    monkeypatch.setattr(sys, "argv", ["environment_check.py"])
    rc = ec.main()
    out = capsys.readouterr().out
    assert "SERP_API_KEY" in out and "SERPAPI_API_KEY" in out
    assert rc == 1, "a .env key that decides nothing must fail the check, not just print"
