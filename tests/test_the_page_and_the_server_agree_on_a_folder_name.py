r"""
test_the_page_and_the_server_agree_on_a_folder_name.py

TWO SANITISERS FOR ONE QUESTION, WHICH IS THE DEFECT THIS CODEBASE KEEPS PAYING FOR.

A client name and a drawing number become FOLDER names, and a folder name is not free text.
The server sanitises them because the page can be bypassed -- estimate_routes.safe_segment
decides what the folder is actually called. The page sanitises them too, because it shows
the estimator where the work is going before they press the button.

Those are different jobs and both are needed. What is not allowed is for them to disagree,
because then the screen names a destination that is not where the work went, and the person
who trusts it goes looking in the wrong folder days later.

They had drifted in three ways, all found by running them side by side:

    "M & S .."           page "M & S "   server "M & S"    trailing space kept
    140-character name   page keeps 140  server cuts 120   a different folder entirely
    " /M & S "           agreed, but by luck: the page trimmed before substituting and the
                         server substitutes before trimming, which agree only while no
                         unsafe character sits at either end

None of that is exotic. "M & S" is a real client and a trailing space in a pasted name is
the most ordinary thing there is.

WHY THIS TEST RUNS BOTH RATHER THAN ASSERTING ON EITHER. Two implementations checked
separately against a list of expectations drift the moment somebody updates one list.
Running the real JavaScript and the real Python over the same names compares the things
themselves, so there is nothing to keep in step by hand.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
PAGE = BACKEND / "sdi-estimating-intelligence.html"

# Ordinary names, awkward names, and the three that were actually wrong. A folder name is
# whatever somebody types into a box, including what they pasted out of an email.
NAMES = [
    "M & S", "Boots", "M&S", "11650-00", "M & S Retail Ltd",
    "M & S ..", "M & S. ", " /M & S ", "  Boots  ", "Boots.",
    "M & S/Retail", "C:\\jobs", "a<b>c", 'quote"d', "pipe|d", "star*", "q?", "",
    "   ", ".", "..", "A" * 140, "Ünïcode Cliént", "tab\tname", "new\nline",
    # WHERE THE ORDER OF THE STEPS ACTUALLY SHOWS. The unsafe class includes \x00-\x1f,
    # and a tab and a newline are BOTH unsafe characters and whitespace. Substitute first
    # and a leading tab becomes "-"; trim first and it disappears. Every other name in this
    # list agrees under either order, so without these three the two implementations could
    # be reordered against each other and nothing would notice.
    "\tM & S", "M & S\n", " \tBoots ",
]


def _server(names):
    sys.path.insert(0, str(BACKEND))
    import types
    stub = types.ModuleType("config")
    stub.API_KEY = ""
    stub.FILE_ROOTS = []
    sys.modules.setdefault("config", stub)
    sys.modules.pop("estimate_routes", None)
    er = pytest.importorskip("estimate_routes",
                             reason="fastapi/pydantic not installed in this environment")
    return [er.safe_segment(n) for n in names]


def _page(names):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here, so the page's half cannot be run")
    src = PAGE.read_text(encoding="utf-8")
    # THE REAL LINE OUT OF THE REAL PAGE. Re-typing it here would be a third implementation,
    # and a third implementation is how the first two came to disagree.
    m = re.search(r"^const safe = .*?;$", src, re.S | re.M)
    assert m, "the page no longer defines safe() in a form this test can lift out"
    script = m.group(0) + "\nconsole.log(JSON.stringify(" + json.dumps(names) + ".map(safe)));"
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert proc.returncode == 0, f"the page's safe() will not run:\n{proc.stderr[:500]}"
    return json.loads(proc.stdout)


def test_the_page_and_the_server_name_every_folder_the_same_way():
    theirs, ours = _page(NAMES), _server(NAMES)
    differ = [(n, p, s) for n, p, s in zip(NAMES, theirs, ours) if p != s]
    assert not differ, (
        "the page shows a destination the server will not use:\n  "
        + "\n  ".join(f"{n!r}: page {p!r}  server {s!r}" for n, p, s in differ))


def test_the_comparison_is_not_vacuous():
    """A guard that compares two empty lists passes for ever. If the extraction or the
    import quietly returns nothing, this is what says so."""
    assert len(_server(NAMES)) == len(NAMES) > 20
    assert any(_server(NAMES)), "every name sanitised to nothing — the rule is not running"


def test_the_real_client_name_survives_intact():
    """M & S is a client, not an edge case. An ampersand is legal in a Windows folder name
    and mangling it would file every one of their enquiries somewhere nobody expects."""
    assert _server(["M & S"]) == ["M & S"]
    assert _page(["M & S"]) == ["M & S"]


def test_a_name_that_sanitises_to_nothing_is_empty_on_both_sides():
    """"..." and "   " are refused by the caller, not silently turned into a folder called
    something. Both halves have to agree that there is nothing there."""
    for name in ("", "   ", ".", ".."):
        assert _server([name]) == [""], name
        assert _page([name]) == [""], name
