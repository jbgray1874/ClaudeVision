"""A researched price is asked about the item the pack describes, and says what it priced.

11650-06, 23 Sep 2026: the Yiree binding screw was researched as "YIREE CODE - DWG491667" — a
supplier code, no noun — and came back at £126.04 each, £2,621.63 a kit. The pack names it
"Yiree Binding Screw" on sheet 2 and puts it in "BINDING SCREW SPARE SET OF 4"; the model
was told neither, was told nothing said it was BOUGHT, and never saw the brief's own request
("per unit, the pack it is sold in, a real current listing") because the prompt builder read
only its fixed fields.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import research_context as rc                                        # noqa: E402

YIREE = {"part_number": "YIREE CODE-DWG491667", "description": "YIREE CODE - DWG491667",
         "page_roles": ["bought_in"], "quantity": 20}
ROWS = [
    {"part_number": "YIREE CODE - DWG491667", "description": "YIREE CODE - DWG491667",
     "bom_parent": "11650-06-SA02"},
    {"part_number": "11650-06-SA02", "description": "BINDING SCREW SPARE SET OF 4 AC0706-04",
     "bom_parent": "11650-06-GA"},
    {"part_number": "Yiree Binding Screw", "description": "YIREE CODE - DWG491667",
     "bom_parent": "11650-06-GA"},
]


def test_the_pack_says_what_the_code_is():
    ctx = rc.research_context(YIREE, [YIREE], ROWS)
    assert "also listed as 'Yiree Binding Screw'" in ctx, ctx
    assert "part of 'BINDING SCREW SPARE SET OF 4" in ctx, ctx


def test_only_bought_in_lines_are_stamped_and_the_description_is_untouched():
    made = {"part_number": "11650-03-02M", "description": "ARM"}
    parts = [dict(YIREE), made]
    n = rc.stamp_research_context(parts, {"document_analysis": {"bom_rows": ROWS}})
    assert n == 1 and "Yiree Binding Screw" in parts[0]["research_context"]
    assert parts[0]["description"] == "YIREE CODE - DWG491667"
    assert "research_context" not in made


def test_the_model_is_told_it_is_bought_and_is_given_the_request():
    import web_ai_price_lookup as w
    block = w._build_spec_block(description="YIREE CODE - DWG491667 — also listed as "
                                "'Yiree Binding Screw'", part_code="YIREE CODE-DWG491667",
                                ask="Current UK trade unit price for: … name a real listing",
                                supply="bought_in")
    assert block.startswith("Supply: a PURCHASED catalogue component"), block
    assert "What is needed: Current UK trade unit price" in block
    assert "Yiree Binding Screw" in block
    # A made part is not told it is bought.
    assert "PURCHASED" not in w._build_spec_block(description="ARM", material="MILD_STEEL")


def test_the_model_must_say_what_it_priced_and_it_reaches_the_line():
    import web_ai_price_lookup as w
    assert '"item_priced"' in w._LLM_PROMPT_TEMPLATE
    import estimator as e
    import web_ai_price_lookup as wl
    seen = {}

    def fake(spec):
        seen.update(spec)
        return {"found": True, "price_gbp": 0.85, "unit": "each", "price_date": "2026-09-23",
                "source": "https://example", "price_basis": "per screw",
                "price_is_reproducible": True, "item_priced": "binding screw, one screw"}
    orig = wl.lookup_web_ai_price
    wl.lookup_web_ai_price = fake
    try:
        out = e._rung4_researcher({"kind": "bought_in_component", "description": "x",
                                   "code": "c", "ask": "per unit", "wanted_unit": "each"})
    finally:
        wl.lookup_web_ai_price = orig
    assert seen.get("supply") == "bought_in" and seen.get("ask") == "per unit"
    assert out["item_priced"] == "binding screw, one screw"


def test_the_brief_carries_the_context_and_the_line_says_what_was_priced():
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert 'str(part.get("research_context") or "").strip()' in src
    assert "stamp_research_context(estimable_parts, summary)" in src
    assert 'f"AI researched price £{_ind_price:,.2f}: priced as "' in src
    ip = (ROOT / "src" / "indicative_price.py").read_text(encoding="utf-8")
    assert '"item_priced": _clean(found.get("item_priced"))' in ip


def test_the_earlier_fallback_asks_the_same_question(monkeypatch):
    """The 19:30 run: D-204 was in the build and Yiree was still £126.04 with no 'priced as',
    because PricingService._get_web_ai_fallback answers BEFORE the researched rung, with its
    own spec — a bare code — and its stored answer to that bare code came straight back."""
    import pricing_service as ps
    import generated_price_cache as gpc
    import web_ai_price_lookup as wl
    seen = {}

    def fake(spec, **kw):
        seen.update(spec)
        return {"found": True, "price_gbp": 0.85, "source_type": "llm_market_estimate",
                "llm_provider": "xai", "price_is_reproducible": True,
                "item_priced": "binding screw, one screw"}
    monkeypatch.setattr(wl, "lookup_web_ai_price", fake)
    monkeypatch.setattr(gpc, "cached_estimate", lambda spec, prov, model, compute, **k: compute())
    svc = object.__new__(ps.PricingService)
    part = dict(YIREE, research_context="also listed as 'Yiree Binding Screw', part of "
                                        "'BINDING SCREW SPARE SET OF 4 AC0706-04'")
    out = svc._get_web_ai_fallback(part)
    assert "Yiree Binding Screw" in seen["description"], seen
    assert seen.get("supply") == "bought_in"
    assert "name a real current listing" in (seen.get("ask") or ""), seen
    assert out["item_priced"] == "binding screw, one screw"
