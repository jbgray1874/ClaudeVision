"""Nineteen pages, one at a time, each a network round trip.

10575-02 reported:

    [bom-vision] 19 page(s) sent to the model, 3 from cache, 0 not selected

and `run_path_b` sent them sequentially — render a page, call xAI, wait, render the next. It
is the largest single block in a run, and from the outside a slow model and a stuck one look
identical.

Nothing made it sequential. Each page is independent, the cache is keyed per page, and the
results are collected rather than accumulated into shared state. The work is entirely WAITING
on an API, so the GIL is released throughout and threads are the right tool — processes would
pay to pickle a rendered PNG per page for no gain.

WHAT THIS FILE PROTECTS, because concurrency is easy to add and easy to get subtly wrong:

  order        results used to arrive in page order. Something downstream may lean on that
               without saying so, and a reordering that only appears on a pack with two GAs
               is not a debugging session anybody wants.
  counting     paid / cached / skipped decide what the run reports it spent. Incremented
               from six threads, that total quietly stops matching the bill.
  one bad page one page the model refuses must not take the other eighteen with it. The
               sequential version continued past an error and so must this.
  a way back   SDI_VISION_WORKERS=1 restores exactly the old behaviour, which is the first
               thing to reach for if the model starts rate-limiting.
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
_SRC = (_ROOT / "src" / "merge_boms.py").read_text(encoding="utf-8")


def _run_path_b():
    import merge_boms                                                   # noqa: PLC0415
    return merge_boms


class _Args:
    dpi = 200
    max_side = 2000
    model = "grok-test"
    cache_dir = None
    no_cache = False
    refresh = False
    force_llm = False
    refresh_file = None


def _fake_pathB(pages_per_pdf: int, *, fail_on: set[int] = frozenset(),
                calls: list | None = None):
    """A stand-in vision reader that records the order it was asked in."""
    mod = types.SimpleNamespace()
    mod.count_pages = lambda p: pages_per_pdf
    mod.render_page_to_png = lambda p, pi, dpi=0, max_side=0: b"png"

    def _cached(png, model, pdf_name, page_index, cache_dir, use_cache, refresh,
                cache_only=False):
        if calls is not None:
            calls.append(page_index)
        if page_index in fail_on:
            raise RuntimeError("the model refused this page")
        return {"parsed": {"rows": [{"item_number": str(page_index)}]},
                "raw_response": "", "cache_hit": page_index % 3 == 0, "skipped": False}

    mod.get_vision_bom_cached = _cached
    return mod


# ── it still returns the same thing, in the same order ───────────────────────

def test_pages_come_back_in_order(monkeypatch):
    """THE ASSERTION most likely to be broken by adding threads, and the one whose failure
    would surface weeks later on one unusual pack."""
    mb = _run_path_b()
    monkeypatch.setattr(mb, "pathB", _fake_pathB(8))
    monkeypatch.setenv("SDI_VISION_WORKERS", "6")
    out = mb.run_path_b(["/x/one.pdf"], _Args())
    assert [r["page_index"] for r in out] == list(range(8))


def test_every_page_is_read_exactly_once(monkeypatch):
    calls: list[int] = []
    mb = _run_path_b()
    monkeypatch.setattr(mb, "pathB", _fake_pathB(10, calls=calls))
    monkeypatch.setenv("SDI_VISION_WORKERS", "4")
    mb.run_path_b(["/x/one.pdf"], _Args())
    assert sorted(calls) == list(range(10)), f"pages read: {sorted(calls)}"


def test_the_spend_is_counted_once_per_page(monkeypatch):
    """paid / cached / skipped is what the run reports it spent. Counted from six threads,
    that total stops matching the bill."""
    mb = _run_path_b()
    monkeypatch.setattr(mb, "pathB", _fake_pathB(12))
    monkeypatch.setenv("SDI_VISION_WORKERS", "6")
    spend: dict = {}
    mb.run_path_b(["/x/one.pdf"], _Args(), spend=spend)
    assert sum(spend.values()) == 12, f"12 pages produced {spend}"


# ── one bad page is one bad page ─────────────────────────────────────────────

def test_a_page_the_model_refuses_does_not_take_the_others(monkeypatch):
    """The sequential version continued past an error. A thread pool that lets the exception
    out would lose the whole pack to one page."""
    mb = _run_path_b()
    monkeypatch.setattr(mb, "pathB", _fake_pathB(6, fail_on={2, 4}))
    monkeypatch.setenv("SDI_VISION_WORKERS", "6")
    unread: list = []
    out = mb.run_path_b(["/x/one.pdf"], _Args(), unread=unread)
    assert [r["page_index"] for r in out] == [0, 1, 3, 5]
    assert {u["page"] for u in unread} == {2, 4}, "the failed pages are not recorded"


# ── there is a way back ──────────────────────────────────────────────────────

def test_one_worker_restores_the_old_behaviour(monkeypatch):
    """The first thing to reach for if xAI starts rate-limiting, and it has to actually
    work rather than merely be documented."""
    calls: list[int] = []
    mb = _run_path_b()
    monkeypatch.setattr(mb, "pathB", _fake_pathB(5, calls=calls))
    monkeypatch.setenv("SDI_VISION_WORKERS", "1")
    out = mb.run_path_b(["/x/one.pdf"], _Args())
    assert calls == [0, 1, 2, 3, 4], "with one worker the pages are not read in order"
    assert len(out) == 5


def test_the_worker_count_is_bounded():
    """An unbounded value from the environment would open a connection per page — 19 at once
    on this pack, more on a hundred-drawing enquiry, and a rate limit turns a slow run into a
    failed one."""
    body = _SRC[_SRC.index("def run_path_b"):]
    assert "SDI_VISION_WORKERS" in body
    assert re.search(r"max\(1,\s*min\(_workers,\s*\d+\)\)", body), (
        "the worker count is not clamped, so a typo in the environment decides how hard "
        "this hits the API")
