"""No credential is a literal in a file we commit.

WHAT WAS THERE. sdi-intelligence-portal.html carried a 64-character SDI_API_KEY as a JavaScript
literal, in a tracked file, in a repository whose history is not private. It was found while
checking what the first commit of a NEW repository would contain: squashing the history drops
BH_CLIENT_SECRET, which lives only in old commits, but it does nothing about a secret sitting in
the working tree — that goes straight into commit one.

IT WAS ALSO DOING NOTHING. The backend's X-SDI-Key check is written and SDI_API_KEY is blank, so
the gate is off; the service says so at startup and the portal's own Security section says so on
screen. The literal bought no security and one published credential.

AND IT COULD NOT HAVE BEEN SECRET ANYWAY. The page is served to the browser. Anybody who can
open the portal can read any constant in it with View Source, so a key in markup is public to
exactly the people the gate exists to stop. The only thing a literal adds over browser storage
is a copy in git and on every machine that clones it.

THIS IS A RULE OVER THE PAGES, not a check on one line. A page that grows a key tomorrow fails
here without anybody writing a new test — which is the only kind of guard that survives, because
the next one will not be called API_KEY.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _tracked(*globs: str):
    out = subprocess.run(["git", "ls-files", *globs], cwd=ROOT, capture_output=True, text=True)
    return [ROOT / p for p in out.stdout.split("\n") if p.strip()]


# A credential-shaped assignment: a name that means "secret" taking a long opaque literal.
# Deliberately not a search for one key — the next one will have a different name and value.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b (?: api[_-]?key | secret | password | passwd | token | client[_-]?secret | access[_-]?key )
    \b \s* [:=] \s*
    ['"] ([A-Za-z0-9_\-./+]{20,}) ['"]
    """)

# What a placeholder looks like. A test fixture and an example file are supposed to carry
# something key-shaped; a real credential is what this is looking for.
_OBVIOUSLY_FAKE = re.compile(
    r"(?i)(example|sample|placeholder|dummy|your[_-]|xxx|change[_-]?me|not[_-]?a[_-]?real|"
    r"s3cr3t|redacted|<[^>]+>|\.\.\.)")


def _findings(paths):
    bad = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _ASSIGNMENT.finditer(text):
            value = m.group(1)
            line = text.count("\n", 0, m.start()) + 1
            context = text[max(0, m.start() - 200):m.end() + 200]
            if _OBVIOUSLY_FAKE.search(value) or _OBVIOUSLY_FAKE.search(context):
                continue
            bad.append(f"{p.relative_to(ROOT)}:{line} -> {value[:8]}… ({len(value)} chars)")
    return bad


def test_no_page_we_serve_carries_a_credential():
    """The portal and the estimating page. Both are served to the browser and both are
    committed, which is the worst pair of properties a file holding a key can have."""
    bad = _findings(_tracked("sdi-intelligence-backend/*.html"))
    assert not bad, "a credential is a literal in a page we commit:\n  " + "\n  ".join(bad)


def test_the_portal_reads_its_key_from_the_browser_not_the_file():
    page = (ROOT / "sdi-intelligence-backend" / "sdi-intelligence-portal.html").read_text(
        encoding="utf-8")
    at = page.index("const API_KEY")
    decl = page[at:page.index("\n", at)]
    assert "localStorage" in decl, (
        "the key is not read from browser storage, so whatever it is now lives in the repo")
    assert not re.search(r"['\"][A-Za-z0-9]{20,}['\"]", decl), (
        "there is still a long literal on the API_KEY line")


def test_a_blank_key_sends_no_header():
    """Blank is the correct value everywhere the gate is off — which today is everywhere. If a
    blank key produced an empty X-SDI-Key header instead of no header, turning the gate ON
    later would reject every request from a browser that had never been given a key, and the
    failure would look like the backend being down."""
    page = (ROOT / "sdi-intelligence-backend" / "sdi-intelligence-portal.html").read_text(
        encoding="utf-8")
    at = page.index("function _hdr()")
    body = page[at:page.index("\n", at)]
    assert "API_KEY ?" in body and "{}" in body, (
        "a blank key no longer means 'send no header': " + body.strip())


def test_no_script_or_config_we_commit_carries_one_either():
    """The same rule over everything else that goes in the commit. The portal is where one was
    found; it is not the only place one could be."""
    bad = _findings(_tracked("*.py", "*.ps1", "*.json", "*.env", "*.md"))
    assert not bad, "a credential is a literal in a committed file:\n  " + "\n  ".join(bad)
