r"""
test_the_llm_price_cannot_be_mistaken_for_a_quote.py

A SECOND PRICING METHOD, AND THE ONLY DANGEROUS THING ABOUT IT IS FORGETTING WHICH ONE YOU
ARE HOLDING.

11650-00 took about forty minutes on the runner, and estimates run one at a time because
SOLIDWORKS and Excel are driven on one desktop. A hundred-drawing M&S enquiry at that rate
is sixty hours, so the full engine cannot be the method for an enquiry of that size — not
because it is wrong, but because the answer arrives next week.

So a drawing can also be read straight by the model, in seconds. That number is not firm,
not reproducible and carries no BOM. What it IS, that the engine is not, is independent: it
shares none of the engine's rate tables, nesting rules or catalogue lookups, so where the
two disagree the disagreement means something. That is the reason to run both.

Everything below is about the number not being able to pass for something it is not, and
about a hundred-drawing run surviving its own failures.

THE STAMP IS THE POINT. price_provenance already treats "llm" and "grok" as
non-reproducible tokens, so naming the source llm_scan_estimate_grok makes every existing
check refuse to call this job firm — on the day the route is written, rather than the day
somebody remembers to update a list. A pricing route that needs the checks taught about it
is a route that will one day be added without them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import llm_scan_price as lsp  # noqa: E402
import price_provenance as pp  # noqa: E402


@pytest.fixture()
def drawing(tmp_path):
    p = tmp_path / "MS-1000 SHELF UNIT.pdf"
    p.write_bytes(b"%PDF-1.4 not really a pdf")
    return p


def _answer(monkeypatch, reply, context="DWG NO 11650-01-01M\nMILD STEEL 2mm\n1257 x 68"):
    monkeypatch.setattr(lsp, "_cache_path", lambda key: None)      # never touch real cache

    import types
    stub = types.ModuleType("llm_full_extract")
    stub.build_document_context = lambda path, **k: context
    stub._call_llm = lambda prompt, model, system=None: reply
    monkeypatch.setitem(sys.modules, "llm_full_extract", stub)
    return stub


GOOD = json.dumps({"price_gbp": 41.5, "confidence": 0.4,
                   "basis": "2mm mild steel panel, laser and fold, 45 off",
                   "assumptions": ["powder coat assumed", "no fixings shown"]})


# ── the stamp ───────────────────────────────────────────────────────────────────────
def test_the_price_is_recognised_as_not_reproducible_by_the_checks_that_already_exist(
        drawing, monkeypatch):
    """Not by a rule written for it. If this needed price_provenance taught about a new
    name, the next pricing route would be added without teaching it."""
    _answer(monkeypatch, GOOD)
    out = lsp.scan_price(drawing, 45)
    assert out["found"] and out["price_gbp"] == 41.5
    assert pp.is_non_reproducible_source(out["source"]) is True


def test_it_never_claims_to_be_firm_or_reproducible(drawing, monkeypatch):
    _answer(monkeypatch, GOOD)
    out = lsp.scan_price(drawing, 45)
    assert out["firm"] is False and out["reproducible"] is False
    assert out["price_source"]["source_type"] == "ai_estimate"
    assert "not a supplier quote" in out["price_source"]["note"].lower()


def test_the_number_can_be_attributed_to_what_produced_it(drawing, monkeypatch):
    """A figure whose model and prompt cannot be named is neither reproducible NOR
    auditable, which is worse than merely not reproducible."""
    _answer(monkeypatch, GOOD)
    out = lsp.scan_price(drawing, 45, model="grok-4.3")
    assert out["model"] == "grok-4.3"
    assert out["prompt_version"] == lsp.PROMPT_VERSION
    assert out["units"] == 45


def test_the_assumptions_come_back_with_the_price(drawing, monkeypatch):
    """A price with no stated assumptions cannot be argued with, and an estimator who
    cannot argue with a number can only accept it or bin it."""
    _answer(monkeypatch, GOOD)
    out = lsp.scan_price(drawing, 45)
    assert out["assumptions"] == ["powder coat assumed", "no fixings shown"]
    assert "laser and fold" in out["basis"]


# ── what it refuses to invent ───────────────────────────────────────────────────────
@pytest.mark.parametrize("reply", [
    json.dumps({"price_gbp": None, "why_not": "no material or size is given"}),
    json.dumps({"price_gbp": 0}),
    json.dumps({"price_gbp": "not enough information"}),
    "I would need more detail to price this.",
    "",
    "```json\n{\"price_gbp\": null}\n```",
])
def test_a_model_that_will_not_price_it_does_not_produce_a_zero(drawing, monkeypatch, reply):
    """ZERO IS A CLAIM. Downstream it reads as a part that is free to make, which is the
    silent under-charge this whole codebase keeps paying for. "I do not know" has to stay
    "I do not know" all the way to the sheet."""
    _answer(monkeypatch, reply)
    out = lsp.scan_price(drawing, 45)
    assert out["found"] is False
    assert out.get("price_gbp") is None
    assert out.get("why"), "it declined without saying why, which nobody can act on"


def test_fenced_json_is_still_read():
    """Models fence JSON and sometimes put a sentence in front of it. Tolerating a
    formatting habit is not the same as tolerating an answer with no number in it."""
    out = lsp._parse("Here is my estimate:\n```json\n" + GOOD + "\n```")
    assert out["found"] and out["price_gbp"] == 41.5


def test_a_scanned_drawing_says_that_is_why(drawing, monkeypatch):
    """A picture with no text layer cannot be priced by this method, and the reason belongs
    on the row — "no price" and "this method cannot read this drawing" send an estimator to
    different places."""
    _answer(monkeypatch, GOOD, context="")
    out = lsp.scan_price(drawing, 45)
    assert out["found"] is False and "scan" in out["why"]


# ── one failure must not cost the other ninety-nine ─────────────────────────────────
def test_an_unreachable_model_is_a_result_not_an_exception(drawing, monkeypatch):
    stub = _answer(monkeypatch, GOOD)

    def _boom(prompt, model, system=None):
        raise RuntimeError("connection reset")
    stub._call_llm = _boom
    out = lsp.scan_price(drawing, 45)
    assert out["found"] is False and "could not be reached" in out["why"]
    assert out["source"] == lsp.SOURCE_NAME, "a failure still has to say which method failed"


def test_an_unreadable_drawing_is_a_result_not_an_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(lsp, "_cache_path", lambda key: None)
    out = lsp.scan_price(tmp_path / "does-not-exist.pdf", 45)
    assert out["found"] is False and "not readable" in out["why"]


@pytest.mark.parametrize("units", [0, -1, None, "many"])
def test_a_missing_quantity_is_refused_rather_than_assumed(drawing, monkeypatch, units):
    """A price per unit means nothing without one, and picking a default would put a number
    against a quantity nobody chose."""
    _answer(monkeypatch, GOOD)
    out = lsp.scan_price(drawing, units)
    assert out["found"] is False


# ── the cache ───────────────────────────────────────────────────────────────────────
def test_the_same_drawing_is_not_asked_twice(drawing, tmp_path, monkeypatch):
    """Asking again costs money and, because the model is not reproducible, may give a
    different answer for the same drawing inside one enquiry."""
    calls = []
    stub = _answer(monkeypatch, GOOD)
    stub._call_llm = lambda p, m, system=None: (calls.append(1), GOOD)[1]
    monkeypatch.setattr(lsp, "_cache_path",
                        lambda key: tmp_path / "cache" / f"{key}.json")
    first = lsp.scan_price(drawing, 45)
    second = lsp.scan_price(drawing, 45)
    assert len(calls) == 1, "the model was asked twice about one drawing"
    assert second["price_gbp"] == first["price_gbp"]
    assert second.get("cached") is True, "a cached answer must say it is cached"


def test_a_different_quantity_is_a_different_question(drawing, tmp_path, monkeypatch):
    """Keyed on the path alone, an enquiry re-run at 500 off would be served the answer for
    45 off — and it would look like a real answer."""
    calls = []
    stub = _answer(monkeypatch, GOOD)
    stub._call_llm = lambda p, m, system=None: (calls.append(1), GOOD)[1]
    monkeypatch.setattr(lsp, "_cache_path", lambda key: tmp_path / "c" / f"{key}.json")
    lsp.scan_price(drawing, 45)
    lsp.scan_price(drawing, 500)
    assert len(calls) == 2


def test_a_changed_prompt_is_a_different_question(drawing, tmp_path, monkeypatch):
    """A cached answer produced by a different question is not an answer to this one, and a
    cache that cannot tell would serve yesterday's prompt for ever."""
    a = lsp._key(drawing, 45, "grok-4.3")
    monkeypatch.setattr(lsp, "PROMPT_VERSION", lsp.PROMPT_VERSION + "-changed")
    assert lsp._key(drawing, 45, "grok-4.3") != a


def test_a_refusal_is_not_cached(drawing, tmp_path, monkeypatch):
    """One unreachable moment must not become permanent. Cache the miss and the next run
    reports the drawing as unpriceable without ever asking again."""
    stub = _answer(monkeypatch, GOOD)
    stub._call_llm = lambda p, m, system=None: '{"price_gbp": null, "why_not": "no size"}'
    monkeypatch.setattr(lsp, "_cache_path", lambda key: tmp_path / "c" / f"{key}.json")
    lsp.scan_price(drawing, 45)
    assert not list((tmp_path / "c").glob("*.json")) if (tmp_path / "c").exists() else True


def test_the_suite_leaves_no_real_cache_behind():
    """A test that writes into cache/llm_scan_prices would serve an invented price to a
    real run. This has already happened once, with market sheet rates."""
    live = ROOT / "cache" / "llm_scan_prices"
    assert not live.exists() or not list(live.glob("*.json")), (
        f"{live} holds entries written by the suite")
