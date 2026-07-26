"""
probe_pipeline.py — one-command health check for the three fallback tiers.

Run before a pricing wave to confirm web search, the xAI LLM, and the RAG
corpus are all reachable and answering. Each probe is isolated, so one failing
tier still lets the others report. On failure the real cause is printed (the
xAI path now surfaces HTTP status + response body, missing key, empty content,
etc.) rather than a bare "failed".

Usage:
    python probe_pipeline.py
"""

from __future__ import annotations

import logging
import os

# Surface the named failure causes the engine logs (xAI HTTP body, empty
# content, missing key, web-search errors) to the console.
logging.basicConfig(level=logging.INFO, format="    [log] %(levelname)s %(name)s: %(message)s")

import config  # noqa: E402  -- import early so its setdefault(...) sets the API keys


def _mask(name: str) -> str:
    v = os.environ.get(name, "").strip()
    return f"set (…{v[-4:]})" if len(v) >= 4 else ("set" if v else "NOT SET")


SAMPLE = {
    "description": "M6 x 16mm hex set screw BZP",
    "material": "steel",
    "part_code": "M6X16",
    "quantity": 100,
    "operations": [],
}

results = {}


def banner(title: str) -> None:
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


# ── 0. Environment / config ──────────────────────────────────────────────────
banner("0. ENVIRONMENT")
print(f"  XAI_API_KEY      : {_mask('XAI_API_KEY')}")
print(f"  SERPAPI_API_KEY  : {_mask('SERPAPI_API_KEY')}")
web_cfg = (getattr(config, "PRICE_SOURCE_CONFIG", {}) or {}).get("web", {}) or {}
pol = getattr(config, "FALLBACK_PRICING_POLICY", {}) or {}
print(f"  xai_model        : {web_cfg.get('xai_model', '(default grok-4.5)')}")
print(f"  xai_reasoning    : {web_cfg.get('xai_reasoning_effort', '(default low)')}")
print(f"  fallback enabled : {pol.get('enable_web_ai_fallback')}")
print(f"  max_web_ai_calls : {pol.get('max_web_ai_calls', '(default 300)')}")


# ── 1. WEB SEARCH (SerpAPI, LLM off) ─────────────────────────────────────────
banner("1. WEB SEARCH  (catalogue + SerpAPI, LLM disabled)")
try:
    from web_ai_price_lookup import lookup_web_ai_price
    r = lookup_web_ai_price(SAMPLE, enable_web_search=True, enable_llm_estimate=False)
    if r.get("found") and r.get("price_gbp"):
        print(f"  PASS  £{r['price_gbp']:.4f}  via {r.get('source_type')}  "
              f"(conf {r.get('confidence')})  query={r.get('web_query')!r}")
        results["web"] = True
    else:
        print(f"  FAIL  no web price — {r.get('error') or r}")
        results["web"] = False
except Exception as exc:
    print(f"  ERROR  {exc!r}")
    results["web"] = False


# ── 2. xAI LLM (web off) ─────────────────────────────────────────────────────
banner("2. xAI LLM  (web disabled, LLM only)")
try:
    from web_ai_price_lookup import lookup_web_ai_price
    r = lookup_web_ai_price(SAMPLE, enable_web_search=False, enable_llm_estimate=True)
    if r.get("found") and r.get("price_gbp"):
        print(f"  PASS  £{r['price_gbp']:.4f}  via {r.get('llm_provider')}  "
              f"(conf {r.get('confidence')})  basis={str(r.get('price_basis'))[:60]!r}")
        results["llm"] = True
    else:
        # the module logger above will have printed WHY (HTTP body / key / etc.)
        print(f"  FAIL  no LLM price — {r.get('error') or r}")
        results["llm"] = False
except Exception as exc:
    print(f"  ERROR  {exc!r}")
    results["llm"] = False


# ── 3. RAG corpus (SQL Server) ───────────────────────────────────────────────
banner("3. RAG CORPUS  (SQL Server historical quotes)")
try:
    from pricing_service import PricingService
    with PricingService() as svc:
        row = svc._fetch_one_with_retry(
            "SELECT COUNT(*) FROM dbo.historical_quote_header", []
        )
        n = row[0] if row else 0
        print(f"  jobs in corpus   : {n}   (expect ~1,669 after the reload)")
        sample_part = {"description": "shelf bracket", "normalized_material": "mild steel"}
        rag = svc._get_historical_rag(sample_part)
        if rag:
            print(f"  RAG sample match : £{rag.get('unit_price_gbp')}  "
                  f"(conf {rag.get('confidence')})  via {rag.get('source')}")
        else:
            print("  RAG sample match : none returned for sample part (not an error "
                  "in itself — confirms the path runs)")
        results["rag"] = n > 0
        print(f"  {'PASS' if n > 0 else 'FAIL'}  DB reachable, corpus {'loaded' if n else 'EMPTY'}")
except Exception as exc:
    print(f"  ERROR  {exc!r}")
    results["rag"] = False


# ── 4. FULL CHAIN (all tiers, real precedence) ───────────────────────────────
banner("4. FULL CHAIN  (catalogue -> web -> LLM, as the engine runs it)")
try:
    from web_ai_price_lookup import lookup_web_ai_price
    r = lookup_web_ai_price(SAMPLE)  # both enabled, llm_provider=auto
    if r.get("found") and r.get("price_gbp"):
        print(f"  £{r['price_gbp']:.4f}  answered by {r.get('source_type')}"
              f"{'/' + r.get('llm_provider') if r.get('llm_provider') else ''}  "
              f"(conf {r.get('confidence')})")
    else:
        print(f"  no price from any tier — {r.get('error') or r}")
except Exception as exc:
    print(f"  ERROR  {exc!r}")


# ── Summary ──────────────────────────────────────────────────────────────────
banner("SUMMARY")
for tier in ("web", "llm", "rag"):
    print(f"  {tier.upper():4}  {'PASS' if results.get(tier) else 'FAIL / not reached'}")
all_ok = all(results.get(t) for t in ("web", "llm", "rag"))
print("\n  " + ("ALL THREE TIERS UP — ready for the test set."
                if all_ok else
                "NOT all tiers up — see the failing probe above for the named cause."))
