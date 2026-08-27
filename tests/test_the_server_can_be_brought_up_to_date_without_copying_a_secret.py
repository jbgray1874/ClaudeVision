"""SDI-APP01 has no git. That is why it serves pages the laptop fixed weeks ago.

WHAT HAPPENED. Menu items "disappear" on the server — the SDI Fixture Library Guide is not in
its copy of the HTML — and `/estimating` and `/guide` are black-only with no size control
there. Nothing is broken on that machine. It is simply running an older set of files, because:

    PS C:\\ClaudeVision> git pull origin claude/codebase-improvements-jcl03i
    git : The term 'git' is not recognized as the name of a cmdlet...

There has never been a mechanism, so there has always been drift, and the drift is invisible
from either end: both machines have a C:\\ClaudeVision, both prompts read `PS C:\\ClaudeVision>`,
and the stale page looks like a working page.

WHAT MUST NEVER TRAVEL. The two machines hold DIFFERENT .env files — different file roots,
different staging paths, a service account on the server the laptop does not use. A blanket
folder copy would overwrite a working configuration with one describing a machine it is not
running on, silently, because the files have the same name. That is a worse outcome than the
staleness being fixed.

HOW THE SCRIPT MAKES THAT IMPOSSIBLE. The file list is `git ls-files`. A .env is gitignored,
therefore untracked, therefore absent from the list. The guard is not a rule applied to the
list — it is the reason the list cannot contain one. This file pins that, because the
tempting simplification (robocopy the folder) breaks it completely and would look identical
for the first several months.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _ROOT / "tools" / "start" / "push-to-server.ps1"
_S = _SCRIPT_PATH.read_text(encoding="utf-8")


# ── a secret cannot travel, by construction ───────────────────────────────────

def test_the_file_list_comes_from_git_and_not_from_the_folder():
    """THE ASSERTION. `git ls-files` cannot name an untracked file. Anything that walks the
    directory — robocopy, Get-ChildItem, xcopy — can and would."""
    assert "git ls-files" in _S, "the file list is not taken from git"
    for walker in ("robocopy", "Get-ChildItem", "xcopy", "-Recurse"):
        assert walker not in _S, (
            f"{walker} enumerates the FOLDER, so it would pick up the .env sitting in it — "
            f"the one file that must not cross between these two machines")


def test_no_env_is_tracked_in_this_repository():
    """The premise the guard rests on. If a .env were ever `git add -f`'d, the list would
    contain it and the script would copy it — so this is checked here as well as at runtime."""
    out = subprocess.run(["git", "ls-files"], cwd=_ROOT, capture_output=True, text=True)
    tracked = [ln for ln in out.stdout.splitlines() if Path(ln).name == ".env"]
    assert not tracked, f"a .env is tracked and would be copied to the server: {tracked}"


def test_it_still_refuses_at_runtime_if_one_ever_is():
    """Belt and braces. The premise above is true today and is checked by a test that someone
    could delete. The script should not depend on that."""
    assert '-eq ".env"' in _S, "there is no runtime check for a tracked .env"
    at = _S.index('-eq ".env"')
    assert "exit 2" in _S[at:at + 800], (
        "the .env check warns and continues — it must refuse, because the damage is silent")


# ── it sends what the server runs, not the repository ────────────────────────

def _include_list() -> list[str]:
    """The $Include default, as the script declares it."""
    at = _S.index("[string[]]$Include = @(")
    block = _S[at:_S.index(")", at)]
    return re.findall(r'"([^"]+)"', block)


def _src_closure() -> set[str]:
    """Every src module reachable from the one the SERVICE imports.

    estimate_routes._scan_one does sys.path.insert on src and imports llm_scan_price — the
    fast LLM drawing read runs on the service on purpose, because putting it on the runner
    would file a hundred scans in behind a forty-minute estimate. Follow that import through
    and you have the complete list of src files the server needs.
    """
    src = _ROOT / "src"
    modules = {p.stem for p in src.glob("*.py")}

    def imported_by(path: Path) -> set[str]:
        import ast
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            return set()
        out: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                out.add(node.module.split(".")[0])
        return out

    seen: set[str] = set()
    stack = ["llm_scan_price"]
    while stack:
        name = stack.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        stack.extend(imported_by(src / f"{name}.py"))
    return seen


def test_the_entry_point_the_service_uses_has_not_moved():
    """The premise the closure is computed from. If _scan_one stops importing llm_scan_price,
    or the sys.path insert goes away, the list below is computed from the wrong root and
    would agree with the script while both are wrong."""
    routes = (_ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
    assert "from llm_scan_price import scan_price" in routes
    assert 'parents[1] / "src"' in routes, (
        "the service no longer puts src on its path — recompute what it needs from scratch")


def test_the_src_files_sent_are_exactly_the_ones_the_service_imports():
    """THE ASSERTION, and the reason this is a test rather than a comment. Seven modules out
    of 655. A hand-maintained list of seven is wrong within a month; one checked against the
    imports is not."""
    listed = {Path(p).stem for p in _include_list() if p.startswith("src/")}
    needed = _src_closure()
    assert listed == needed, (
        f"the script sends {sorted(listed)} but the service imports {sorted(needed)}\n"
        f"  missing (the scan would fail on the server): {sorted(needed - listed)}\n"
        f"  extra   (sent for no reason):                {sorted(listed - needed)}")


def test_it_does_not_send_the_whole_of_src_or_the_tests():
    """The first version of this script sent all 990 tracked files. That is 183 test files,
    several hundred one-off src/_probe_*.py scripts, a prototype for a different client and
    a Sage X3 zip, onto a production server that runs none of them."""
    listed = _include_list()
    assert "src/" not in listed, "the whole of src is being sent to a machine that runs none of it"
    for junk in ("tests/", "_archive/", "alba-pip/", "Notes/", "sagex3/"):
        assert junk not in listed, f"{junk} has no business on the server"


def test_what_it_does_send_is_what_the_server_serves():
    """The backend is the thing running there; tools/start is how it gets restarted and
    repaired; tools/diagnose is how you find out why it will not."""
    listed = _include_list()
    for needed in ("sdi-intelligence-backend/", "tools/start/", "tools/diagnose/"):
        assert needed in listed, f"{needed} is not sent, so the server cannot be updated or fixed"


def test_the_wider_copy_is_available_but_not_the_default():
    assert "[switch]$All" in _S, "there is no way to send everything when that is genuinely wanted"
    assert "if ($All)" in _S


# ── it does not pretend to know what it has not compared ──────────────────────

def test_it_compares_before_it_copies():
    """A copy-everything script reports 1,665 files every time and tells you nothing. The
    useful output is the six that differ."""
    assert "Get-FileHash" in _S, "files are not compared, so every run looks identical"
    assert "$changed" in _S


def test_looking_is_the_default():
    assert "[switch]$Apply" in _S
    assert "if (-not $Apply)" in _S, "there is no read-only path"


def test_it_stops_when_the_share_is_unreachable_rather_than_creating_it():
    """`Copy-Item -Force` to an unreachable UNC path fails per-file, 1,665 times. Worse, if
    the path is merely wrong rather than unreachable, New-Item would happily build a whole
    tree in the wrong place and report success."""
    at = _S.index("Test-Path -LiteralPath $Destination")
    assert "exit 2" in _S[at:at + 700], "an unreachable destination does not stop the run"


# ── it says which half of the change is live and which is not ────────────────

def test_it_distinguishes_python_from_html_afterwards():
    """These have OPPOSITE follow-ups and getting them the wrong way round costs an afternoon
    each way: .py is read once at process start so it needs a restart; .html is read from
    disk per request so it is already live, and the thing standing between you and it is the
    browser cache."""
    tail = _S[_S.index("# WHAT NOW NEEDS DOING"):]
    assert "restart-service.ps1 -Port 8071" in tail, (
        "changed Python is not followed by a restart instruction, so the copy does nothing")
    assert re.search(r"hard refresh", tail, re.I), (
        "changed HTML is not followed by a cache instruction — the server would serve the new "
        "page and the browser would show the old one")
    assert tail.index("restart") < tail.index("hard refresh"), (
        "the restart advice must come first; it is the one that blocks everything else")


def test_a_changed_manifest_is_called_out_before_the_restart():
    """The only follow-up here that does not degrade the service but PREVENTS IT STARTING.
    FastAPI raises at startup if an upload endpoint is declared without python-multipart, so
    a copy that looked fine is followed by a service that will not come up — and the obvious
    reading of that is "the copy broke it", which sends you to revert rather than to pip."""
    tail = _S[_S.index("# WHAT NOW NEEDS DOING"):]
    assert "pip install -r" in tail, (
        "a changed requirements.txt is not called out, so the server can be left with code "
        "that imports a package its virtualenv does not have")
    assert tail.index("pip install -r") < tail.index("restart-service.ps1"), (
        "the install must be advised BEFORE the restart — after it, the service is already "
        "down and the reason looks like the copy rather than the manifest")


def test_the_port_is_the_servers_and_not_the_laptops():
    """8072 is the laptop. 8071 is SDI-APP01. This script only ever talks about the server."""
    assert "8071" in _S
    assert "8072" not in _S, (
        "this script names the laptop's port, and it runs against the server")


# ── PowerShell faults that cannot be caught by running it on Linux ────────────

def test_no_if_statement_is_used_where_a_value_is_expected():
    """`if` is a statement in PowerShell, not an expression. `-ForegroundColor (if ...)` is a
    PARSE error, so the script would not run at all — and there is no PowerShell in the
    environment it was written in to find that out."""
    assert not re.search(r"-\w+\s+\(if\s", _S), (
        "an if-statement is being passed as a parameter value; assign it first")


def test_the_braces_and_parentheses_balance():
    assert _S.count("{") == _S.count("}"), "unbalanced braces"
    assert _S.count("(") == _S.count(")"), "unbalanced parentheses"


def test_forward_slashes_are_translated_for_windows():
    """git ls-files returns POSIX separators. Join-Path with an untranslated 'tools/start/x'
    produces a path Windows accepts in some APIs and not others — the kind of fault that
    works until it does not."""
    # ONE backslash. PowerShell does not use it as an escape character (the backtick is its
    # escape), so "\" is a literal single backslash, and .NET's replacement syntax only
    # treats `$` specially. Asserting two here was this test being wrong about the language
    # rather than the script being wrong about the paths.
    assert '-replace "/", "\\"' in _S, "git's forward slashes are never converted"
