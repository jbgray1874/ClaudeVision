r"""
test_the_quote_says_what_produced_it.py

THE LETTERHEAD NAMED WHOSE IT IS AND WHO IT IS FOR, AND NOTHING BETWEEN THEM.

The quote header carried SDI's mark on the left and the customer's on the right, so a
document that came out of the estimating engine gave no sign of what produced it. James, of
the portal's own header: "for the job quote, between the we are sdi logo and the client logo,
can we add in SDI Intelligence / SDI Estimating Intelligence, as it looks in the attached."

The same two-line lockup the portal uses, so the page somebody runs the job from and the
document that comes out of it read as one system.

THE ACCENT IS NOT --sdi-yellow. That variable is tuned for the dark band; #F5D947 on white is
barely a colour, and a quote is printed as often as it is read on screen. The gold used here
is the one already chosen for the provisional banner's rule, which was picked to survive
black and white.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import client_quote_html as q                                      # noqa: E402


@pytest.fixture(scope="module")
def html():
    return q.build_quote_html(
        {"drawing_info": {"drawing_number": "12349-02", "title": "Gravity Feeder"},
         "estimate_summary": {}},
        job_stem="12349-02", customer="fanatics")


@pytest.fixture(scope="module")
def head(html):
    # Captured INCLUDING its opening tag: excluding it while keeping the matching </div>
    # makes the tags look unbalanced when they are not, and a test that fails for a reason
    # in the test is worse than one that does not exist.
    found = re.search(r'(<div class="head">.*?)<div class="band">', html, re.S)
    assert found, "the quote has no header block"
    return found.group(1)


# ── what was asked for ─────────────────────────────────────────────────────────

def test_the_engine_is_named_on_the_quote(head):
    assert "SDI Estimating" in head and "Intelligence" in head


def test_it_sits_between_the_sdi_mark_and_the_customers(head):
    """Between them, in that order — a mark after the customer's logo reads as the
    customer's own."""
    order = [head.index('class="sdi"'), head.index('class="mark"'), head.index('class="cust"')]
    assert order == sorted(order)


def test_it_is_the_two_line_lockup_the_portal_uses(head):
    assert "eyebrow" in head and "SDI Intelligence" in head


# ── and the ways a header change goes wrong ────────────────────────────────────

def test_neither_logo_was_displaced(head):
    assert 'class="sdi"' in head and 'class="cust"' in head
    assert "fanatics" in head


def test_the_accent_is_legible_on_white(html):
    """--sdi-yellow is #F5D947, which is for the dark band. On the white letterhead it is
    barely a colour, and this document gets printed."""
    rule = re.search(r"\.head \.mark \.name b \{ ([^}]*) \}", html)
    assert rule, "the accent rule is not in the stylesheet"
    assert "var(--sdi-yellow)" not in rule.group(1)
    assert "#B8860B" in rule.group(1)


def test_it_gives_way_rather_than_squeezing_the_logos_on_a_narrow_page(html):
    assert re.search(r"@media \(max-width:\d+px\) \{ \.head \.mark \{ display:none", html), (
        "on a narrow page three-up wraps, and the mark is what should go")


def test_the_header_divs_balance(head):
    """A stray <div> in a letterhead pushes the rest of the quote inside it. Counted rather
    than eyeballed, because the failure renders as "the page looks a bit odd"."""
    assert head.count("<div") == head.count("</div>"), (
        f"{head.count('<div')} opened, {head.count('</div>')} closed")
