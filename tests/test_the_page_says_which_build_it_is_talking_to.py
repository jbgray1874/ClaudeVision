"""The estimating page names the service and the build behind it.

WHAT THIS COST. An afternoon, on four failures that look identical from the page:

  1. the change was never committed or pushed
  2. the service is behind the page (the HTML is re-read per request, estimate_routes is
     imported once at start-up)
  3. the browser is serving a cached copy (fixed separately: the routes now say no-store)
  4. there are TWO services on the box and this tab is on the older one

Number 4 was the real one. Ports 8071 and 8072 were both listening, from the same folder, with
their Python THIRTY-FIVE COMMITS APART — so the newer HTML was being served over the older engine
and the three new buttons would have rendered perfectly and 404'd on every press.

X-SDI-Commit has been on every response for a while, stamped by a middleware and added to CORS
expose_headers, built for precisely this question. It was invisible to anybody using the page, so
the question could only be answered from a PowerShell prompt by somebody who already suspected the
answer. The page now reads it off a reply it was making anyway.

The two facts have to appear TOGETHER. A commit with no origin cannot distinguish two instances on
one box, and an origin with no commit cannot distinguish a current service from a stale one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
PAGE = BACKEND / "sdi-estimating-intelligence.html"
APP = BACKEND / "app.py"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _show_build() -> str:
    """The function body, so a test about what it says cannot be satisfied by the word
    appearing in a comment elsewhere on the page."""
    page = _page()
    start = page.index("function showBuild(commit){")
    return page[start:page.index("async function checkRunners()", start)]


# ── the line exists and carries both facts ────────────────────────────────────────────


def test_the_page_has_somewhere_to_say_it():
    assert 'id="buildLine"' in _page()
    assert 'buildLine=$("buildLine")' in _page(), "bound explicitly like every other element"


def test_it_names_the_build_and_the_origin_together():
    body = _show_build()
    assert "location.origin" in body, (
        "a commit alone cannot tell two instances on one box apart — which was the real failure")
    assert "commit" in body


def test_it_reads_the_header_the_service_already_sends():
    page = _page()
    assert 'r.headers.get("X-SDI-Commit")' in page
    # and the service must actually send it, on every reply and readably from the page
    app = APP.read_text(encoding="utf-8")
    assert 'response.headers["X-SDI-Commit"] = SDI_COMMIT' in app
    assert 'expose_headers=["X-SDI-Commit"]' in app, (
        "a header a cross-origin fetch cannot read is a header the page does not have")


def test_it_costs_no_extra_request():
    """Read off the runner poll the page makes every fifteen seconds anyway. A dedicated
    version fetch would be a second thing that can fail, with its own failure to explain."""
    page = _page()
    poll = page[page.index("async function checkRunners()"):]
    poll = poll[:poll.index("setInterval(checkRunners")]
    assert 'api("/api/estimate/runners")' in poll
    assert "showBuild(" in poll
    assert page.count("showBuild(") >= 2, "defined once, called from the poll"


# ── and it never states a version it does not have ────────────────────────────────────


def test_an_unreported_build_is_not_silence():
    """An empty line reads as "nothing to report", which is the opposite of the truth."""
    body = _show_build()
    assert "build not reported" in body
    assert "may be an old one" in body, "and says what that means for the reader"


def test_unknown_is_printed_as_unknown():
    """SDI_COMMIT resolves to the literal string 'unknown' when git is not on the service's
    PATH — which is its normal state under NT AUTHORITY\\SYSTEM. That must not render as a
    build identifier somebody then trusts."""
    body = _show_build()
    assert '"unknown"' in body
    assert "could not read its own commit" in body


def test_a_service_that_stops_answering_clears_the_build():
    """A commit read on an earlier poll describes a service that is no longer there. Leaving it
    on screen states a version for something that is down."""
    page = _page()
    catch = page[page.index("// The fetch itself failed"):]
    catch = catch[:catch.index("if(!r.ok){")]
    assert "buildLine" in catch, "the build line is cleared when the service goes away"
    assert "not answering" in catch


def test_a_page_newer_than_its_service_still_reports_the_build():
    """The 404 case is when this matters most — "restart me" is only actionable once you know
    WHICH service to restart. showBuild is called before the r.ok check, so it runs either way."""
    page = _page()
    poll = page[page.index("async function checkRunners()"):]
    assert poll.index("showBuild(") < poll.index("if(!r.ok){")
    assert "This page is newer than the service" in poll, "the existing 404 message is kept"


# ── the second instance: what the page still cannot see ───────────────────────────────


def test_the_commit_is_read_from_git_without_a_git_executable():
    """THE SERVICE ANSWERED "unknown" ON A BOX WITH GIT, A CLONE, AND A FRESH PULL.

    It runs as NT AUTHORITY\\SYSTEM. A git installed per-user lives under that user's AppData,
    where SYSTEM cannot see it, so shutil.which found nothing and the one hardcoded path missed.
    Guessing at more install locations is a losing game — winget, scoop, a portable copy and an
    MSI each put it somewhere different.

    `git rev-parse HEAD` reads .git/HEAD and then one ref file. So this reads them directly:
    no PATH, no subprocess, no account it has to be able to impersonate.
    """
    from pathlib import Path as _P
    src = APP.read_text(encoding="utf-8")
    body = src[src.index("def _commit_from_git_dir"):src.index("def _resolve_commit")]
    namespace = {"Path": _P}
    exec(compile(body, str(APP), "exec"), namespace)               # noqa: S102
    read = namespace["_commit_from_git_dir"]

    # it agrees with git on this very checkout
    import subprocess
    expected = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10)
    if expected.returncode == 0 and expected.stdout.strip():
        assert read(ROOT) == expected.stdout.strip()[:7], (
            "reading .git must give the same answer git gives")
    else:
        assert read(ROOT), "there is a .git here, so something should have been read"

    # and it is silent rather than wrong where there is nothing to read
    assert read(_P("/")) == "", "a folder that is not a checkout reports nothing, not a guess"


def test_reading_git_comes_before_asking_the_executable():
    """Order is the fix. Left as a fallback it would never run on the machine that needed it,
    because the subprocess branch does not fail fast — it returns a non-zero exit that the loop
    treats as "try the next folder" and then falls through to the stamp file."""
    src = APP.read_text(encoding="utf-8")
    resolve = src[src.index("def _resolve_commit"):src.index("SDI_COMMIT = _resolve_commit()")]
    assert "_commit_from_git_dir" in resolve
    assert resolve.index("_commit_from_git_dir") < resolve.index('shutil.which("git")')
    # env still wins: a deploy with no working tree states its own version
    assert resolve.index('os.getenv("SDI_COMMIT"') < resolve.index("_commit_from_git_dir")
    # and the copied-files case still falls through to the stamp
    assert resolve.index('shutil.which("git")') < resolve.index('".sdi-commit"')


def test_it_never_raises_into_the_service():
    """A version header that can stop the service is worse than no version header."""
    src = APP.read_text(encoding="utf-8")
    body = src[src.index("def _commit_from_git_dir"):src.index("def _resolve_commit")]
    assert "except Exception:" in body
    assert 'return ""' in body


def test_a_packed_ref_is_found_too():
    """A freshly cloned repo has no loose refs/heads file at all — every branch is in
    packed-refs — so a reader that only looks in refs/heads reports "unknown" on exactly the
    machine most likely to have just been cloned."""
    src = APP.read_text(encoding="utf-8")
    body = src[src.index("def _commit_from_git_dir"):src.index("def _resolve_commit")]
    assert "packed-refs" in body
    assert 'startswith(("#", "^"))' in body, "peeled tag lines are not commits for a branch ref"


def test_a_worktree_or_submodule_is_followed():
    src = APP.read_text(encoding="utf-8")
    body = src[src.index("def _commit_from_git_dir"):src.index("def _resolve_commit")]
    assert "gitdir:" in body, ".git is a FILE in a worktree, not a directory"


def test_a_detached_head_is_the_hash_itself():
    src = APP.read_text(encoding="utf-8")
    body = src[src.index("def _commit_from_git_dir"):src.index("def _resolve_commit")]
    assert 'if not head.startswith("ref:")' in body


def test_the_two_default_ports_are_both_documented_somewhere():
    """NOT A FIX, A PIN ON A KNOWN TRAP. Two different defaults exist in this repo — config.py
    falls back to 8071 and start-service.ps1's -Port defaults to 8072 — which is how two
    services came to be listening from one folder at once. The build line makes the situation
    visible; it does not prevent it. This test exists so that changing one default without the
    other is a deliberate act, and so the next person finds the pair named together.
    """
    cfg = (BACKEND / "config.py").read_text(encoding="utf-8")
    start = (ROOT / "tools" / "start" / "start-service.ps1").read_text(
        encoding="utf-8", errors="ignore")
    assert re.search(r'_opt\("SDI_PORT",\s*"8071"\)', cfg), "config.py's fallback"
    assert re.search(r"\[int\]\s*\$Port\s*=\s*8072", start), "the start script's default"
