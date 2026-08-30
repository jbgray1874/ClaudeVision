"""Asking the model again, from the page, without deleting anything.

THE RUN THAT MEASURED NOTHING. The first LLM-only run through the page reported:

    [bom-vision] 0 page(s) sent to the model, 22 from cache, 0 not selected
    [llm-full-extract] reusing the cached read for this pack

Not one call reached Grok. Both caches are keyed on content — the page image for one, the pack
text for the other — so an unchanged pack replays its stored answers. Correct for an estimate,
and the exact opposite of what a MEASUREMENT of the model is for.

WHY NOT CLEAR THE CACHE FROM THE PAGE. The cache is on the RUNNER'S machine. The service may be
on another box entirely — it is, for the 8071 install — so a page that deleted files would be
deleting the wrong machine's, or nothing. And deletion is permanent and shared: those files are
every other job's settled answer. Telling the engine to bypass them for one run is reversible,
local to the run, and costs nobody else anything.

WHY IT IS NOT THE DEFAULT. The caches exist because 2085 returned a route with welding on one
run and without it on the next and the unit cost halved. An estimate that moves by half between
identical runs is not an estimate.

AND WHY IT DOES NOT MAKE THE RUN MUCH SLOWER THAN IT ALREADY IS — which is the thing everyone
assumes. The cache key for a page is a hash of the RENDERED PNG, and the key for the pack read
is built from the extracted pack TEXT. Both have to be computed before the cache can be
consulted, so every page is rendered and every PDF is parsed on a fully cached run too. The
cache saves the model's time and the bill. It has never saved the rendering.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
MERGE = (ROOT / "src" / "merge_boms.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
RUNNER = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")
SCRIPT = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", PAGE, re.S | re.I))
MARKUP = re.sub(r"<script[^>]*>.*?</script>", " ", PAGE, flags=re.S | re.I)


# ── every link of the chain, because it is five long and it broke at link four ───────

def test_the_engine_takes_the_flag():
    assert '"--fresh-read"' in MAIN, "main.py has no --fresh-read"


def test_it_sets_both_caches_and_not_just_the_one_that_is_easy_to_find():
    """TWO CACHES AT OPPOSITE ENDS OF THE PIPELINE. The per-page vision reader and the
    whole-pack extract. Bypassing only the first leaves the log still saying "reusing the
    cached read for this pack", which is the line that started this."""
    at = MAIN.index('if getattr(args, "fresh_read", False):')
    body = MAIN[at:at + 900]
    assert 'os.environ["SDI_VISION_REFRESH"] = "1"' in body
    assert 'os.environ["SDI_LLM_EXTRACT_REFRESH"] = "1"' in body


def test_the_vision_reader_is_reached_by_the_environment_variable():
    assert 'os.environ.get("SDI_VISION_REFRESH"' in MERGE, (
        "nothing reads SDI_VISION_REFRESH, so --fresh-read sets a variable nobody consults")


def test_it_is_resolved_before_the_namespace_that_carries_it():
    """THE BUG THIS NEARLY SHIPPED, AND IT WOULD NOT HAVE FAILED — it would have quietly gone
    on answering last week's question. `refresh` defaults to None so the environment can supply
    it, and run_path_b reads it out of the argparse.Namespace built a few lines below. Resolve
    None -> bool AFTER that Namespace is built and None is what run_path_b gets: falsy, every
    page from cache, the flag set and honoured by nobody.

    Stated as an ORDER because both lines are correct in isolation; only their sequence is
    wrong, and nothing about the code reads as broken."""
    at = MERGE.index("def reconcile_job(")
    body = MERGE[at:at + 4000]
    resolved = body.index('os.environ.get("SDI_VISION_REFRESH"')
    built = body.index("_args = argparse.Namespace(")
    assert resolved < built, (
        "refresh is resolved from the environment after the Namespace that carries it is "
        "built, so --fresh-read would set a variable that arrives as None")


def test_the_service_takes_it_and_hands_it_on():
    assert "fresh_read: bool = False" in ROUTES, "the request cannot carry it"
    assert '"fresh_read": bool(run.fresh_read)' in ROUTES, "the claim payload drops it"
    assert "fresh_read=bool(req.fresh_read)" in ROUTES, "the Run never records it"


def test_the_runner_passes_it_to_the_engine():
    assert '["--fresh-read"] if fresh_read else []' in RUNNER
    assert 'job.get("fresh_read")' in RUNNER, "the runner never reads it off the claim"


def test_the_page_offers_it_and_sends_it():
    assert 'id="freshRead"' in MARKUP, "there is no way to ask for it from the page"
    assert "fresh_read: !!freshRead.checked" in SCRIPT, "the page offers it and does not send it"


def test_it_is_off_by_default():
    """A ticked box would make every LLM read a paid one, including the many that are pressed
    just to look at a pack the model has already read."""
    at = MARKUP.index('id="freshRead"')
    tag = MARKUP[MARKUP.rindex("<input", 0, at + 1):MARKUP.index(">", at)]
    assert not re.search(r"(?<![-\w])checked(?![-\w])", tag), "fresh read is on by default"


def test_the_run_log_says_which_of_the_two_it_was():
    """A cached read and a fresh one produce the same workbook in the same folder and are told
    apart by nothing else. The whole value of the fresh one is that its number may have moved,
    which is unreadable if you cannot tell afterwards which you ran."""
    assert "FRESH READ" in SCRIPT, "the page's log does not distinguish them"
    assert 'run.line("FRESH READ' in ROUTES, "the service's log does not distinguish them"
    at = SCRIPT.index("freshRead.checked")
    assert "Cached read" in SCRIPT[at:at + 600], (
        "only the fresh case is announced, so a cached read is silent and reads as a fresh one")


def test_nothing_on_this_path_deletes_a_cache_file():
    """THE SHAPE OF THE FIX. The cache is on the runner's machine, which for the 8071 install
    is not the service's machine at all, and those files are every other job's settled answer.
    The page asks the engine to bypass them; it never reaches for anyone's disk."""
    for name, src in (("the service", ROUTES), ("the page", PAGE)):
        # The comments explain the caches by name, which is the whole reason this repo keeps
        # writing guards that pass on their own explanation.
        code = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
        code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
        code = re.sub(r"(?m)^\s*#[^\n]*", " ", code)
        code = re.sub(r"//[^\n]*", " ", code)
        for cache in ("vision_bom", "llm_extract", "SDI_LLM_EXTRACT_CACHE_DIR"):
            assert cache not in code, (
                f"{name} names the {cache} cache. Neither of them can see the runner's disk, "
                f"and those files are every other job's settled answer — the engine is asked "
                f"to bypass them, nobody reaches for them")


def test_the_control_says_the_word_somebody_will_look_for():
    """JAMES ASKED TO "CLEAR THE CACHE" AND THEN COULD NOT FIND THE CONTROL, which was on his
    screen. The label said "reusing the answers held for this pack" — accurate, careful, and
    missing the only word he was scanning for. A control nobody can find is a control that
    does not exist, and the page is read by people hunting for a word, not by people reading
    it start to finish."""
    at = MARKUP.index('id="freshRead"')
    block = MARKUP[at:MARKUP.index("</label>", at)]
    assert "cache" in block.lower(), (
        "the fresh-read control never says 'cache', which is the word somebody looking for it "
        "will search the page for")
