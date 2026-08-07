"""
SDI AI Estimating Platform — Web / AI Fallback Price Lookup
===========================================================
When internal sources (UDEF / SQL / spreadsheet) return no price for a part,
this module searches the web and/or queries an LLM for an indicative UK trade price.

Every result is clearly flagged as indicative and requires human verification.

Price source priority (when all internal sources fail):
  1. Explicit catalogue URLs configured in PRICE_SOURCE_CONFIG["web"]["sources"]
  2. Programmatic search (SerpAPI or Google Custom Search) → scrape allowlisted supplier URLs
  3. Web search via Anthropic API (optional; uses Claude's web search tool)
  4. LLM market estimate (Claude/xAI reasoning from part spec, no live web call)

All prices returned carry:
  - source_type: "web_catalog" | "web_search" | "llm_market_estimate"
  - confidence: 0.40–0.72 (never above 0.72 — always lower than internal sources)
  - review_flag: True
  - review_reason: plain English explanation
  - web_query: the search string used (for audit)

Usage:
    from web_ai_price_lookup import lookup_web_ai_price, build_web_search_query, search_web_result_urls
    urls = search_web_result_urls(build_web_search_query(material="ACRYLIC", thickness_mm=3))
    result = lookup_web_ai_price(part_spec)
    if result["found"]:
        price = result["price_gbp"]
        source = result["source_type"]   # always check this
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

import config
from web_search_providers import resolve_search_provider, search_web_result_urls

logger = logging.getLogger(__name__)

# Re-export for callers that only import this module.
__all__ = [
    "build_web_search_query",
    "lookup_web_ai_price",
    "search_web_result_urls",
    "summarise_estimate_json",
]

# Maximum confidence for any web/AI fallback price.
# Must stay below all internal source confidences (UDEF=0.95, SQL=0.93, spreadsheet=0.80).
_MAX_WEB_CONFIDENCE = 0.68
_LLM_ESTIMATE_CONFIDENCE = 0.45
_WEB_SEARCH_CONFIDENCE = 0.58


# ─────────────────────────────── query builder ──────────────────────────────

def build_web_search_query(
    material: Optional[str] = None,
    description: Optional[str] = None,
    thickness_mm: Optional[float] = None,
    part_code: Optional[str] = None,
    finish: Optional[str] = None,
    quantity: Optional[int] = None,
) -> str:
    """
    Build a focused search query from part specification.
    Designed to find UK industrial/manufacturing trade prices.
    """
    tokens: List[str] = []

    # Part code first — most specific
    if part_code and len(part_code) > 3:
        tokens.append(part_code)

    # Material
    mat = str(material or "").replace("_", " ").strip()
    if mat:
        # Human-readable material names
        mat_map = {
            "MILD_STEEL": "mild steel sheet",
            "MILD_STEEL_SPCC": "SPCC steel sheet",
            "STAINLESS_STEEL": "stainless steel sheet",
            "STAINLESS_STEEL_304": "304 stainless steel",
            "STAINLESS_STEEL_316": "316 stainless steel",
            "ALUMINIUM": "aluminium sheet",
            "ACRYLIC": "acrylic sheet",
            "POLYCARBONATE": "polycarbonate sheet",
            "MDF": "MDF board",
            "PLYWOOD": "plywood sheet",
            "BIRCH_PLYWOOD": "birch plywood",
            "OAK_VENEER_MDF": "oak veneer MDF",
            "TIMBER": "timber",
            "HDPE_PLASTIC": "HDPE plastic sheet",
        }
        tokens.append(mat_map.get(mat.upper(), mat.lower()))

    # Thickness
    if thickness_mm and thickness_mm > 0:
        tokens.append(f"{thickness_mm}mm")

    # Description keywords (trim to useful manufacturing terms)
    if description:
        desc_clean = re.sub(r"[^\w\s]", " ", str(description)).strip()
        # Keep first 6 meaningful words, skip common filler
        stop = {"the", "a", "an", "of", "for", "and", "or", "with", "to", "at"}
        words = [w for w in desc_clean.split() if w.lower() not in stop and len(w) > 2][:6]
        if words:
            tokens.append(" ".join(words))

    # Finish
    if finish and finish.upper() not in ("FREE ISSUED", "NONE", ""):
        tokens.append(str(finish).lower()[:30])

    # Context
    tokens.extend(["price", "UK supplier"])
    if quantity and quantity > 1:
        tokens.append(f"qty {quantity}")

    query = " ".join(tokens)
    # Trim to sensible search length
    return query[:200].strip()


# ─────────────────────────── LLM market estimate ────────────────────────────

_LLM_PROMPT_TEMPLATE = """You are a UK manufacturing cost expert with 20 years experience in sheet metal fabrication, display fixtures, and retail shopfitting.

A part from an engineering drawing has no price in the company's internal database. Provide an indicative UK trade/subcontract price.

Part specification:
{spec_block}

Respond with ONLY a JSON object in this exact format (no other text):
{{
  "price_gbp": <number — unit price in GBP, realistic UK trade/subcontract price>,
  "unit": "<each|per_kg|per_metre|per_m2>",
  "price_basis": "<brief explanation of what drives this price>",
  "low_estimate_gbp": <lower bound>,
  "high_estimate_gbp": <upper bound>,
  "confidence": <0.3 to 0.65 — your confidence in this estimate>,
  "key_assumptions": ["<assumption 1>", "<assumption 2>"],
  "verify_against": ["<where to verify: e.g. 'Metals4U', 'RS Components', 'local powder coat supplier'>"],
  "review_note": "<one sentence plain English note for the estimator about what to check>"
}}

Be conservative — if you are unsure, use the low estimate. Do not invent specificity you don't have."""


def _build_spec_block(
    material: Optional[str] = None,
    description: Optional[str] = None,
    thickness_mm: Optional[float] = None,
    part_code: Optional[str] = None,
    finish: Optional[str] = None,
    colour: Optional[str] = None,
    quantity: Optional[int] = None,
    length_mm: Optional[float] = None,
    width_mm: Optional[float] = None,
    weight_kg: Optional[float] = None,
    operations: Optional[List[str]] = None,
) -> str:
    lines = []
    if part_code:
        lines.append(f"Part code: {part_code}")
    if description:
        lines.append(f"Description: {description}")
    if material:
        mat_human = str(material).replace("_", " ").title()
        lines.append(f"Material: {mat_human}")
    if thickness_mm:
        lines.append(f"Thickness: {thickness_mm} mm")
    if length_mm and width_mm:
        lines.append(f"Blank/part size: {length_mm:.0f} × {width_mm:.0f} mm")
    elif length_mm:
        lines.append(f"Length: {length_mm:.0f} mm")
    if weight_kg:
        lines.append(f"Weight: {weight_kg:.4f} kg")
    if finish and finish.upper() not in ("NONE", ""):
        lines.append(f"Finish / surface treatment: {finish}")
    if colour:
        lines.append(f"Colour: {colour}")
    if quantity:
        lines.append(f"Order quantity: {quantity}")
    if operations:
        ops_human = [o.replace("_", " ").title() for o in operations[:8]]
        lines.append(f"Manufacturing operations: {', '.join(ops_human)}")
    lines.append("Customer: UK retail/commercial display manufacturer")
    return "\n".join(lines)


def _call_anthropic_llm(prompt: str, model: str = "claude-sonnet-4-20250514") -> Optional[Dict[str, Any]]:
    """
    Call Anthropic API for LLM market estimate.
    Requires ANTHROPIC_API_KEY environment variable.
    Returns parsed JSON response dict or None on failure.
    """
    import urllib.request
    import urllib.error

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set — Anthropic LLM skipped, falling back to xAI")
        return None

    payload = json.dumps({
        "model": model,
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = ""
        for block in body.get("content") or []:
            if block.get("type") == "text":
                text += block.get("text", "")
        # Strip markdown fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("LLM price lookup failed: %s", exc)
        return None


def _offline() -> bool:
    """True when the process has declared itself offline.

    The rules suite sets SDI_OFFLINE=1 before importing anything so that fixtures cannot
    reach a live service. Exactly one module honoured it, and every outbound path in
    costing went straight past -- including this one, which is a paid LLM call. A fixture
    that prices a part was therefore billing real money on any machine with a key.

    Guarded at the network primitives rather than at each of the four call sites
    (pricing_service, note_scan, bay_rollup, probe_pipeline), so a fifth caller added later
    inherits it instead of having to remember.
    """
    return bool(os.environ.get("SDI_OFFLINE"))


def _call_xai_llm(
    prompt: str,
    *,
    max_completion_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Call xAI Grok API for LLM market estimate.
    Requires XAI_API_KEY environment variable.

    Optional per-call overrides (default None => current config/behaviour, so the price
    waterfall is unchanged). The note-scan FINDER passes its own values: more completion
    budget + lower reasoning effort + temperature 0 so the same notes prompt returns the
    same item list run-to-run (the reasoning trace, not sampling, was the instability).
    """
    if _offline():
        return None          # SDI_OFFLINE: no paid call from a fixture
    import urllib.request
    import urllib.error
    # Importing config runs its os.environ.setdefault(...) for the keys and carries
    # the model/effort, so do it BEFORE reading the key.
    try:
        import config as _config
        _web_cfg = (getattr(_config, "PRICE_SOURCE_CONFIG", None) or {}).get("web", {}) or {}
    except Exception:
        _web_cfg = {}
    api_key = os.environ.get("XAI_API_KEY", "").strip()
    if not api_key:
        logger.warning("XAI_API_KEY not set — xAI LLM fallback unavailable")
        return None
    model = str(_web_cfg.get("xai_model") or "grok-4.3").strip()
    effort = (reasoning_effort if reasoning_effort is not None
              else str(_web_cfg.get("xai_reasoning_effort") or "low")).strip().lower()
    req_body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        # grok-4.3 is a reasoning model: it counts reasoning tokens against the
        # completion budget and uses max_completion_tokens (not max_tokens). Give
        # headroom so reasoning doesn't consume the budget before the JSON answer.
        "max_completion_tokens": int(max_completion_tokens) if max_completion_tokens else 4000,
        "temperature": float(temperature) if temperature is not None else 0.1,
    }
    if seed is not None:
        req_body["seed"] = int(seed)
    if effort in ("none", "low", "medium", "high"):
        req_body["reasoning_effort"] = effort
    payload = json.dumps(req_body).encode("utf-8")

    req = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        body = json.loads(raw)
        choices = body.get("choices") or []
        if not choices:
            logger.warning("xAI returned no choices (model=%s): %s", model, raw[:300])
            return None
        text = ((choices[0].get("message") or {}).get("content") or "").strip()
        if not text:
            fr = choices[0].get("finish_reason")
            logger.warning(
                "xAI returned empty content (model=%s, finish_reason=%s) — reasoning "
                "likely consumed the token budget; raise max_completion_tokens or "
                "lower xai_reasoning_effort.", model, fr,
            )
            return None
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("xAI reply was not valid JSON (model=%s): %s", model, text[:300])
            return None
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        logger.warning("xAI HTTP %s for model=%s — %s", exc.code, model, detail or exc.reason)
        return None
    except urllib.error.URLError as exc:
        logger.warning("xAI could not reach api.x.ai: %s", getattr(exc, "reason", exc))
        return None
    except Exception as exc:
        logger.warning("xAI price lookup failed (unexpected): %r", exc)
        return None


def _llm_market_estimate(spec: Dict[str, Any], provider: str = "auto",
                         *, use_cache: bool = True, refresh: bool = False) -> Dict[str, Any]:
    """Ask the model for an indicative UK trade price, once per distinct specification.

    The same part asked four times returned £35.62, £95.62, £75.62 and £85.62. That is
    what kept this number out of the price column — not that it was uncertain, but that
    it moved sixty pounds while the job stood still. An uncertain number an estimator can
    weigh; a number that answers differently every time it is asked cannot be weighed at
    all, because there is nothing stable to weigh.

    So it is asked once and stored against the spec that produced it. It changes when the
    part changes, when the model or prompt changes, or when somebody refreshes it.
    """
    import generated_price_cache as _gpc

    _model = os.environ.get("XAI_MODEL", "grok-4.3") if provider != "anthropic" else "anthropic"
    return _gpc.cached_estimate(
        spec, provider, _model,
        lambda: _llm_market_estimate_uncached(spec, provider),
        use_cache=use_cache, refresh=refresh,
    )


def _llm_market_estimate_uncached(spec: Dict[str, Any], provider: str = "auto") -> Dict[str, Any]:
    """
    Ask LLM for indicative UK trade price.
    Returns a standardised result dict.
    """
    spec_block = _build_spec_block(**{
        k: spec.get(k)
        for k in ["material", "description", "thickness_mm", "part_code", "finish",
                  "colour", "quantity", "length_mm", "width_mm", "weight_kg", "operations"]
    })
    prompt = _LLM_PROMPT_TEMPLATE.format(spec_block=spec_block)

    parsed = None
    used_provider = "none"

    if provider in ("auto", "anthropic"):
        parsed = _call_anthropic_llm(prompt)
        if parsed:
            used_provider = "anthropic"

    if parsed is None and provider in ("auto", "xai"):
        parsed = _call_xai_llm(prompt)
        if parsed:
            used_provider = "xai"

    if parsed is None:
        return {
            "found": False,
            "source_type": "llm_market_estimate",
            "error": "LLM call failed or no API key configured",
            "price_gbp": None,
        }

    # Cap confidence at _LLM_ESTIMATE_CONFIDENCE
    raw_conf = float(parsed.get("confidence") or _LLM_ESTIMATE_CONFIDENCE)
    capped_conf = min(raw_conf, _LLM_ESTIMATE_CONFIDENCE)

    return {
        "found": True,
        "source_type": "llm_market_estimate",
        "llm_provider": used_provider,
        "price_gbp": float(parsed.get("price_gbp") or 0),
        "unit": str(parsed.get("unit") or "each"),
        "currency": "GBP",
        "confidence": capped_conf,
        "low_estimate_gbp": float(parsed.get("low_estimate_gbp") or 0),
        "high_estimate_gbp": float(parsed.get("high_estimate_gbp") or 0),
        "price_basis": str(parsed.get("price_basis") or ""),
        "key_assumptions": list(parsed.get("key_assumptions") or []),
        "verify_against": list(parsed.get("verify_against") or []),
        "review_note": str(parsed.get("review_note") or "Verify against supplier quote before using for customer pricing."),
        "review_flag": True,
        "review_reason": (
            "This price was estimated by AI reasoning from part specification — "
            "it is INDICATIVE only. It has NOT been verified against a supplier catalogue or quote. "
            "Do not use for customer pricing without verification."
        ),
        "web_query": None,
        "price_date": str(date.today()),
        "spec_used": spec_block,
    }


# ─────────────────────── programmatic search + scrape ───────────────────────

def _web_search_cfg() -> Dict[str, Any]:
    web = (getattr(config, "PRICE_SOURCE_CONFIG", None) or {}).get("web", {}) or {}
    search = web.get("search")
    return dict(search) if isinstance(search, dict) else {}


def _web_search_programmatic_price(query: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    SerpAPI / Google CSE → top-N URLs on allowlisted domains → extract £ from HTML.
    """
    cfg = _web_search_cfg()
    if not cfg.get("enabled", True):
        return {"found": False, "source_type": "web_search", "error": "programmatic_search_disabled"}

    configured = str(cfg.get("provider") or "auto").strip().lower()
    if configured in {"none", "disabled", "anthropic"}:
        return {"found": False, "source_type": "web_search", "error": f"provider_{configured}"}

    top_n = int(cfg.get("top_n") or 5)
    max_scrape = int(cfg.get("max_urls_to_scrape") or 3)
    web_cfg = (getattr(config, "PRICE_SOURCE_CONFIG", None) or {}).get("web", {}) or {}
    user_agent = str(web_cfg.get("user_agent") or "SDIEstimator/1.0")

    search_out: Dict[str, Any] = {"urls": [], "provider": "none", "error": "no_provider"}
    if configured == "auto":
        for candidate in ("serpapi", "google_cse"):
            if resolve_search_provider(candidate) != candidate:
                continue
            attempt = search_web_result_urls(query, top_n=top_n, provider=candidate)
            if attempt.get("urls"):
                search_out = attempt
                break
            search_out = attempt
    else:
        search_out = search_web_result_urls(query, top_n=top_n, provider=configured)
    urls: List[str] = list(search_out.get("urls") or [])
    if not urls:
        return {
            "found": False,
            "source_type": "web_search",
            "search_provider": search_out.get("provider"),
            "error": search_out.get("error") or "no_allowlisted_urls",
            "web_query": query,
            "search_hits": search_out.get("all_hits_before_filter") or [],
        }

    for url in urls[: max(1, max_scrape)]:
        price = _parse_catalogue_price(url, str(spec.get("material") or ""), user_agent=user_agent)
        if price is None:
            continue
        hit = next((h for h in (search_out.get("hits") or []) if h.get("url") == url), {})
        return {
            "found": True,
            "source_type": "web_search",
            "search_provider": search_out.get("provider"),
            "price_gbp": price,
            "unit": "each",
            "currency": "GBP",
            "confidence": min(_WEB_SEARCH_CONFIDENCE, _MAX_WEB_CONFIDENCE),
            "supplier_name": str(hit.get("title") or url)[:120],
            "source_url": url,
            "price_basis": f"Scraped from search result (rank {hit.get('rank', '?')})",
            "review_flag": True,
            "review_reason": (
                "Price scraped from a web search result on an allowlisted supplier domain. "
                "Confirm SKU, unit, and SDI negotiated terms before quoting."
            ),
            "web_query": query,
            "search_hits": search_out.get("hits") or [],
            "price_date": str(date.today()),
        }

    return {
        "found": False,
        "source_type": "web_search",
        "search_provider": search_out.get("provider"),
        "error": "no_price_on_search_urls",
        "web_query": query,
        "search_urls_tried": urls[:max_scrape],
        "search_hits": search_out.get("hits") or [],
    }


# ─────────────────────── Anthropic web search (optional) ────────────────────

def _web_search_price_anthropic(query: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Use Anthropic web search to find current UK trade price.
    Requires ANTHROPIC_API_KEY.
    """
    import urllib.request
    import urllib.error

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return {"found": False, "source_type": "web_search", "error": "No API key"}

    spec_summary = _build_spec_block(**{
        k: spec.get(k)
        for k in ["material", "description", "thickness_mm", "part_code", "finish", "quantity"]
    })

    user_content = (
        f"I need the current UK trade or retail price for this manufacturing part. "
        f"Search for it and return the best price you can find from a UK supplier.\n\n"
        f"Part specification:\n{spec_summary}\n\n"
        f"Search for: {query}\n\n"
        f"Return ONLY a JSON object:\n"
        f'{{"price_gbp": <number>, "unit": "<each|per_kg|per_metre>", "source_url": "<url>", '
        f'"supplier_name": "<name>", "price_basis": "<brief note>", "confidence": <0.4-0.65>}}'
    )

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 600,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": user_content}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        text = ""
        for block in body.get("content") or []:
            if block.get("type") == "text":
                text += block.get("text", "")

        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        parsed = json.loads(text)

        raw_conf = float(parsed.get("confidence") or _WEB_SEARCH_CONFIDENCE)
        capped = min(raw_conf, _MAX_WEB_CONFIDENCE)

        return {
            "found": True,
            "source_type": "web_search",
            "price_gbp": float(parsed.get("price_gbp") or 0),
            "unit": str(parsed.get("unit") or "each"),
            "currency": "GBP",
            "confidence": capped,
            "supplier_name": str(parsed.get("supplier_name") or "web search result"),
            "source_url": str(parsed.get("source_url") or ""),
            "price_basis": str(parsed.get("price_basis") or ""),
            "review_flag": True,
            "review_reason": (
                "Price found via live web search. This is a current market price but "
                "may not reflect SDI's negotiated supplier terms. "
                "Verify against your preferred supplier before quoting."
            ),
            "web_query": query,
            "price_date": str(date.today()),
        }

    except Exception as exc:
        logger.warning("Web search price lookup failed for query %r: %s", query, exc)
        return {"found": False, "source_type": "web_search", "error": str(exc)}


# ─────────────────────── catalogue URL lookup ────────────────────────────────

def _parse_catalogue_price(url: str, material_hint: str, user_agent: str = "SDIEstimator/1.0") -> Optional[float]:
    """
    Fetch a supplier catalogue URL and extract the first visible price (GBP).
    Very lightweight — just looks for £X.XX patterns in the page text.
    """
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html_bytes = resp.read(65536)  # First 64 KB only
        text = html_bytes.decode("utf-8", errors="ignore")

        # Find price patterns: £12.34 or 12.34 GBP
        patterns = [
            r"£\s*(\d{1,6}(?:\.\d{1,2})?)",
            r"(\d{1,6}\.\d{2})\s*(?:GBP|gbp)",
            r"price[^£\d]*£?\s*(\d{1,6}(?:\.\d{1,2})?)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                if 0.01 <= val <= 99999:
                    return val
    except Exception as exc:
        logger.debug("Catalogue fetch failed %r: %s", url, exc)
    return None


def _catalogue_lookup(sources: List[Dict[str, Any]], spec: Dict[str, Any]) -> Dict[str, Any]:
    """Try each configured catalogue URL for a price match."""
    material = str(spec.get("material") or "").upper()
    description = str(spec.get("description") or "").upper()

    for src in sources or []:
        hint = str(src.get("material_hint") or "").upper()
        if hint and hint not in material and hint not in description:
            continue
        url = str(src.get("url") or "").strip()
        if not url:
            continue
        price = _parse_catalogue_price(url, hint)
        if price is not None:
            return {
                "found": True,
                "source_type": "web_catalog",
                "price_gbp": price,
                "unit": str(src.get("unit") or "each"),
                "currency": "GBP",
                "confidence": min(0.65, _MAX_WEB_CONFIDENCE),
                "supplier_name": str(src.get("name") or url),
                "source_url": url,
                "review_flag": True,
                "review_reason": "Price from supplier catalogue URL. Check this is the correct SKU and reflects SDI's terms.",
                "web_query": url,
                "price_date": str(date.today()),
            }
    return {"found": False, "source_type": "web_catalog"}


# ─────────────────────────── main entry point ───────────────────────────────

def lookup_web_ai_price(
    spec: Dict[str, Any],
    *,
    enable_web_search: bool = True,
    enable_llm_estimate: bool = True,
    catalogue_sources: Optional[List[Dict[str, Any]]] = None,
    llm_provider: str = "auto",
    rate_limit_delay_s: float = 0.5,
) -> Dict[str, Any]:
    """
    Main fallback price lookup. Tries catalogue → web search → LLM estimate.

    spec keys (all optional):
        material, description, thickness_mm, part_code, finish, colour,
        quantity, length_mm, width_mm, weight_kg, operations (list of str)

    Returns a dict with:
        found (bool)
        price_gbp (float or None)
        unit (str)
        source_type: "web_catalog" | "web_search" | "llm_market_estimate"
        confidence (float, always <= _MAX_WEB_CONFIDENCE)
        review_flag: True always
        review_reason (str)
        web_query (str)
        + source-specific fields
    """
    if _offline():
        # Same shape the exhausted-every-source path returns, so callers need no new branch.
        return {
            "found": False,
            "source_type": "none",
            "price_gbp": None,
            "unit": None,
            "confidence": 0.0,
            "review_flag": True,
            "review_reason": "SDI_OFFLINE is set - no catalogue, web or AI lookup was "
                             "attempted. This is a test/offline run, not evidence that no "
                             "price exists.",
        }
    # 1. Catalogue URLs
    if catalogue_sources:
        result = _catalogue_lookup(catalogue_sources, spec)
        if result.get("found"):
            logger.info("Web catalogue price found for %s: £%.4f", spec.get("part_code") or spec.get("description"), result.get("price_gbp"))
            return result
        time.sleep(rate_limit_delay_s)

    # 2. Web search (programmatic SerpAPI / Google CSE, then optional Anthropic)
    if enable_web_search:
        query = build_web_search_query(
            material=spec.get("material"),
            description=spec.get("description"),
            thickness_mm=spec.get("thickness_mm"),
            part_code=spec.get("part_code"),
            finish=spec.get("finish"),
            quantity=spec.get("quantity"),
        )
        search_cfg = _web_search_cfg()
        prog_enabled = bool(search_cfg.get("enabled", True))
        provider = resolve_search_provider(str(search_cfg.get("provider") or "auto"))

        if prog_enabled and provider in {"serpapi", "google_cse"}:
            result = _web_search_programmatic_price(query, spec)
            if result.get("found") and result.get("price_gbp"):
                logger.info(
                    "Programmatic web search (%s) for %r: £%.4f",
                    result.get("search_provider"),
                    query[:60],
                    result.get("price_gbp"),
                )
                return result
            time.sleep(rate_limit_delay_s)

        use_anthropic = provider == "anthropic" or (
            provider == "auto"
            and not os.environ.get("SERPAPI_API_KEY", "").strip()
            and not (
                os.environ.get("GOOGLE_CSE_API_KEY", "").strip()
                and os.environ.get("GOOGLE_CSE_CX", "").strip()
            )
        )
        if use_anthropic and os.environ.get("ANTHROPIC_API_KEY", "").strip():
            result = _web_search_price_anthropic(query, spec)
            if result.get("found") and result.get("price_gbp"):
                logger.info(
                    "Anthropic web search price for %r: £%.4f (conf %.2f)",
                    query[:60],
                    result.get("price_gbp"),
                    result.get("confidence", 0),
                )
                return result
            time.sleep(rate_limit_delay_s)

    # 3. LLM reasoning estimate
    if enable_llm_estimate:
        result = _llm_market_estimate(spec, provider=llm_provider)
        if result.get("found") and result.get("price_gbp"):
            logger.info("LLM market estimate for %s: £%.4f (conf %.2f)", spec.get("part_code") or spec.get("material"), result.get("price_gbp"), result.get("confidence", 0))
            return result

    # Nothing found
    return {
        "found": False,
        "source_type": "none",
        "price_gbp": None,
        "unit": None,
        "confidence": 0.0,
        "review_flag": True,
        "review_reason": "No price found in any source — internal DB, web, or AI. Add this part to the bought_in_parts table or UDEF_PARTS_TABLE_FOR_ESTIMATING.",
        "web_query": build_web_search_query(
            material=spec.get("material"),
            description=spec.get("description"),
            thickness_mm=spec.get("thickness_mm"),
        ),
        "price_date": str(date.today()),
    }


# ─────────────────── plain-English JSON summary ─────────────────────────────

def summarise_estimate_json(summary: Dict[str, Any], *, verbose: bool = False) -> str:
    """
    Produce a plain-English text summary of what the AI found in a drawing scan.
    Designed for estimators, not developers. Shows BOM, routes, prices, and what's missing.

    Args:
        summary: The full scan/estimate JSON dict
        verbose: If True, includes per-part detail. If False, just the headline summary.

    Returns:
        Multi-line plain text string.
    """
    lines: List[str] = []
    sep = "─" * 70

    # Header
    src = str(summary.get("source_file") or summary.get("drawing_number") or "unknown drawing")
    dwg_no = str(summary.get("drawing_number") or "")
    page_count = summary.get("page_count") or 0
    lines.append(sep)
    lines.append(f"AI ESTIMATE SUMMARY — {dwg_no or src}")
    lines.append(f"Drawing file: {src}  |  Pages scanned: {page_count}")
    lines.append(sep)

    est = summary.get("estimate_summary") or {}
    parts = est.get("part_estimates") or []
    total = est.get("document_total_estimated_cost_gbp")
    lines.append(f"\nParts found: {len(parts)}")
    if total is not None:
        lines.append(f"Total manufacturing cost (AI estimate): £{float(total):,.2f}")

    # Policy
    manifest = summary.get("estimate_policy_manifest") or {}
    snap = manifest.get("policy_snapshot") or {}
    policy_ver = snap.get("estimate_policy_version") or "unknown"
    qty = snap.get("assumed_job_quantity") or est.get("assumed_job_quantity")
    lines.append(f"Policy version: {policy_ver}  |  Assumed quantity: {qty}")

    # Overall validation
    val = (summary.get("manufacturing_writeup") or {}).get("validation") or {}
    val_status = val.get("status") or "unknown"
    val_issues = val.get("issues") or []
    lines.append(f"Extraction validation: {val_status}")
    if val_issues:
        lines.append(f"Validation issues: {len(val_issues)}")
        for issue in val_issues[:5]:
            lines.append(f"  • [{issue.get('code','?')}] {issue.get('reason','')} (part: {issue.get('part_number','—')})")

    lines.append("")
    lines.append("── PRICE SOURCES USED ──────────────────────────────────────────────")

    # Tally price sources
    source_counts: Dict[str, int] = {}
    missing_prices: List[str] = []
    ai_fallback_parts: List[str] = []

    for p in parts:
        pn = str(p.get("part_number") or "?")
        me = p.get("material_estimate") or {}
        ps = me.get("price_source") or {}
        src_type = str(ps.get("source_type") or ps.get("source_name") or "config").lower()
        source_counts[src_type] = source_counts.get(src_type, 0) + 1
        if src_type == "web_ai_fallback":
            ai_fallback_parts.append(pn)
        if not me.get("applied_price_per_kg_gbp") and not me.get("material_price_per_kg_gbp") and not (p.get("cost_breakdown") or {}).get("material"):
            missing_prices.append(pn)

    for src_type, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        label = {
            "udef_sqlserver": "SDI Internal Catalogue (Access Supply Chain)",
            "sqlserver": "SQL Server ERP",
            "spreadsheet": "Blank Estimate Spreadsheet",
            "web_ai_fallback": "AI internet fallback (NEEDS CHECKING)",
            "config": "Config rate card",
        }.get(src_type, src_type)
        lines.append(f"  {count:3d} part(s) — {label}")

    if ai_fallback_parts:
        lines.append(f"\n⚠️  AI FALLBACK PRICES (need verification): {', '.join(ai_fallback_parts[:10])}")
        lines.append("   These prices came from an AI internet search, not your internal database.")
        lines.append("   Add them to bought_in_parts or UDEF_PARTS_TABLE_FOR_ESTIMATING to fix.")

    if missing_prices:
        lines.append(f"\n❌ MISSING PRICES (uncosted): {', '.join(missing_prices[:10])}")
        lines.append("   These parts contributed £0 to the total. Add them to the material price table.")

    lines.append("")
    lines.append("── BILL OF MATERIALS ───────────────────────────────────────────────")

    for p in parts:
        pn = str(p.get("part_number") or "?")
        desc = str(p.get("description") or "—")[:60]
        qty = int(float(p.get("quantity") or 1))
        mat_norm = str(p.get("normalized_material") or p.get("material") or "—")
        thk = p.get("thickness_mm")
        thk_s = f" {thk}mm" if thk else ""
        finish_list = p.get("surface_finishes") or []
        finish_s = f" / {', '.join(finish_list[:2])}" if finish_list else ""
        cb = p.get("cost_breakdown") or {}
        unit_cost = p.get("unit_total_cost_gbp") or cb.get("unit_total_cost_gbp")
        ext_cost = p.get("extended_total_cost_gbp") or cb.get("extended_total_cost_gbp")
        unit_s = f"£{float(unit_cost):,.2f}" if unit_cost else "£—"
        ext_s = f"£{float(ext_cost):,.2f}" if ext_cost else "£—"

        # Price source
        me = p.get("material_estimate") or {}
        ps = me.get("price_source") or {}
        src_type = str(ps.get("source_type") or ps.get("source_name") or "config").lower()
        src_icon = {"udef_sqlserver": "🏭", "sqlserver": "🗄", "spreadsheet": "📊", "web_ai_fallback": "🤖", "config": "⚙"}.get(src_type, "❓")

        # Risk flags
        risks = p.get("risk_flags") or []
        risk_s = f"  ⚠ {len(risks)} flag(s)" if risks else ""

        lines.append(f"  {pn:<20} {desc:<60} qty:{qty:<4} {mat_norm}{thk_s}{finish_s}")
        lines.append(f"  {'':20} Unit: {unit_s:<12} Ext: {ext_s:<12} {src_icon} {src_type}{risk_s}")

        if verbose:
            # Operations
            ops = list(dict.fromkeys((p.get("textual_operations") or []) + (p.get("inferred_operations") or [])))
            if ops:
                lines.append(f"  {'':20} Operations: {', '.join(str(o) for o in ops[:8])}")
            # Route times
            proc = p.get("process_estimate") or {}
            times = proc.get("times_min") or {}
            if times:
                route_parts = [f"{op.replace('_',' ').title()}: {v:.1f}min" for op, v in times.items() if float(v or 0) > 0]
                if route_parts:
                    lines.append(f"  {'':20} Route: {' | '.join(route_parts[:6])}")
            # Risk flags detail
            for rf in risks[:3]:
                lines.append(f"  {'':20} ⚠ {rf}: {_explain_risk_text(rf)[:80]}")
        lines.append("")

    lines.append(sep)
    lines.append("END OF SUMMARY")
    lines.append(sep)
    return "\n".join(lines)


def _explain_risk_text(flag: str) -> str:
    _RISK: Dict[str, str] = {
        "web_ai_indicative_material_price": "AI internet price — verify against supplier",
        "web_ai_indicative_system_cost": "AI internet cost — verify against Access Supply Chain",
        "missing_material_spec": "No material found — estimate incomplete",
        "missing_material_thickness": "Thickness missing — material cost may be wrong",
        "missing_material_price": "No price in database — add to rate card",
        "assembly_only_part_record": "No detail drawing — geometry estimated",
        "section_or_wire_stock_pricing_review": "Section stock — check kg/m figure",
    }
    for k, v in _RISK.items():
        if flag.startswith(k):
            return v
    if flag.startswith("missing_labour_rate:"):
        op = flag.split(":", 1)[1] if ":" in flag else ""
        return f"Labour rate for '{op}' not in database"
    return "Review against drawing and manual estimate"
