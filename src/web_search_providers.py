"""
Programmatic web search for UK supplier price discovery.

Supports SerpAPI (Google results proxy) and Google Custom Search JSON API.
Returns top-N result URLs for ``build_web_search_query()`` — scrape prices separately.

Environment variables:
  SERPAPI_API_KEY          — SerpAPI (https://serpapi.com)
  GOOGLE_CSE_API_KEY       — Google Cloud API key with Custom Search API enabled
  GOOGLE_CSE_CX            — Programmable Search Engine ID (cx)

Config: PRICE_SOURCE_CONFIG["web"]["search"] (see config.py).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import config

logger = logging.getLogger(__name__)

SearchHit = Dict[str, Any]


def _web_search_cfg() -> Dict[str, Any]:
    web = (getattr(config, "PRICE_SOURCE_CONFIG", None) or {}).get("web", {}) or {}
    search = web.get("search")
    if isinstance(search, dict):
        return dict(search)
    return {}


def _http_get_json(url: str, *, timeout: int = 25) -> Dict[str, Any]:
    web = (getattr(config, "PRICE_SOURCE_CONFIG", None) or {}).get("web", {}) or {}
    ua = str(web.get("user_agent") or "SDIEstimator/1.0")
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _domain_allowed(url: str, allowed_domains: List[str]) -> bool:
    if not allowed_domains:
        return True
    try:
        host = (urlparse(url).netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
    except Exception:
        return False
    for dom in allowed_domains:
        d = str(dom).strip().lower()
        if not d:
            continue
        if d.startswith("www."):
            d = d[4:]
        if host == d or host.endswith("." + d):
            return True
    return False


def _filter_hits(hits: List[SearchHit], allowed_domains: List[str]) -> List[SearchHit]:
    if not allowed_domains:
        return hits
    return [h for h in hits if _domain_allowed(str(h.get("url") or ""), allowed_domains)]


def resolve_search_provider(explicit: Optional[str] = None) -> str:
    """
    Choose provider: serpapi | google_cse | anthropic | none.

    ``auto`` prefers SerpAPI, then Google CSE, then anthropic if ANTHROPIC_API_KEY set.
    """
    cfg = _web_search_cfg()
    choice = (explicit or cfg.get("provider") or "auto").strip().lower()
    if choice in {"serpapi", "google_cse", "google", "anthropic", "none", "disabled"}:
        if choice == "google":
            return "google_cse"
        if choice in {"none", "disabled"}:
            return "none"
        return choice

    if os.environ.get("SERPAPI_API_KEY", "").strip():
        return "serpapi"
    if os.environ.get("GOOGLE_CSE_API_KEY", "").strip() and os.environ.get("GOOGLE_CSE_CX", "").strip():
        return "google_cse"
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    return "none"


# ── an answer about the ACCOUNT is not an answer about the query ────────────────────
# 429 (out of quota / rate limited), 401 and 403 (key rejected) are the provider talking
# about the subscription, not about what was asked. Trying a different material cannot change
# any of them, so asking again is time spent to be told the same thing -- one 11650 run put
# seven identical "HTTP Error 429: Too Many Requests" lines through the console, each one a
# network round trip, and the only information in the last six was already in the first.
#
# So the refusal is remembered for the run and said ONCE, plainly: web price lookup is off,
# and every line that would have used it is left for the estimator rather than priced at
# nothing. Keyed by provider, so a dead SerpAPI key does not silence Google CSE.
_PROVIDER_REFUSED: Dict[str, str] = {}
_ACCOUNT_LEVEL = ("429", "401", "403", "Too Many Requests", "quota", "Unauthorized",
                  "Forbidden")


def _account_level_refusal(exc: BaseException) -> bool:
    text = f"{exc}"
    return any(t.lower() in text.lower() for t in _ACCOUNT_LEVEL)


def _remember_refusal(provider: str, reason: str) -> None:
    if provider in _PROVIDER_REFUSED:
        return
    _PROVIDER_REFUSED[provider] = reason
    print(f"   [web-price] {provider} refused on the ACCOUNT, not the query ({reason}). "
          f"Asking again with a different material cannot change that, so web price lookup "
          f"is off for the rest of this run. Lines that needed it are left for the "
          f"estimator, not priced at nothing.", flush=True)


def forget_provider_refusals() -> None:
    """Clear the latch. For tests and for a caller that knows the account was topped up."""
    _PROVIDER_REFUSED.clear()
    _TRANSPORT_FAILURES.clear()


# ── A PROVIDER THAT NEVER ANSWERS IS COSTING WALL CLOCK, NOT BUYING INFORMATION ──────
# The latch above is for what the provider SAYS. This one is for what it does not say at
# all. A timeout is transient and must not latch on the first one — a blip should not turn
# web pricing off for a whole job — but the failure mode actually seen is not a blip: on
# 12552 every SerpAPI call timed out, and each part waited the full web_ai_call_timeout_s
# (25s) to learn nothing. A run takes twenty to forty minutes and that is a slice of it
# spent on a provider that was never going to reply.
#
# Two CONSECUTIVE failures is the threshold, and any success resets the count, so a network
# that is merely slow keeps its lookups and a network where the provider is unreachable
# stops paying for the discovery once. Deliberately per-run and in memory: nothing is
# remembered into the next job, because the next job may be on a working connection.
_TRANSPORT_FAILURES: Dict[str, int] = {}
_TRANSPORT_STRIKES = 2


#
# KEYED THE WAY THE GUARD READS IT. search_serpapi opens with `if "serpapi" in
# _PROVIDER_REFUSED`, lowercase — so a latch written under "SerpAPI" would be set, printed,
# and then never consulted: the run would announce that lookups were off and keep making
# them. The key is the caller's own lowercase token; the display name is passed separately
# and used only in the message.
def _note_transport_failure(key: str, shown_as: str, reason: str) -> None:
    _TRANSPORT_FAILURES[key] = _TRANSPORT_FAILURES.get(key, 0) + 1
    if _TRANSPORT_FAILURES[key] < _TRANSPORT_STRIKES:
        logger.warning("%s search failed: %s", shown_as, reason)
        return
    if key in _PROVIDER_REFUSED:
        return
    _PROVIDER_REFUSED[key] = f"unreachable ({reason})"
    print(f"   [web-price] {shown_as} did not answer {_TRANSPORT_STRIKES} times running "
          f"({reason}). Every further call would wait the full timeout to learn the same "
          f"thing, so web price lookup is off for the rest of this run. Lines that needed "
          f"it are left for the estimator, not priced at nothing.", flush=True)


def _note_transport_success(key: str) -> None:
    _TRANSPORT_FAILURES.pop(key, None)


def search_serpapi(
    query: str,
    *,
    top_n: int = 5,
    api_key: Optional[str] = None,
    region: str = "uk",
    hl: str = "en",
) -> Tuple[List[SearchHit], Optional[str]]:
    if "serpapi" in _PROVIDER_REFUSED:
        return [], _PROVIDER_REFUSED["serpapi"]
    key = (api_key or os.environ.get("SERPAPI_API_KEY", "")).strip()
    if not key:
        return [], "SERPAPI_API_KEY not set"

    params = {
        "engine": "google",
        "q": query,
        "api_key": key,
        "num": str(max(1, min(int(top_n), 10))),
        "gl": region or "uk",
        "hl": hl or "en",
    }
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    try:
        body = _http_get_json(url)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        if _account_level_refusal(exc):
            _remember_refusal("serpapi", str(exc))
        else:
            _note_transport_failure("serpapi", "SerpAPI", str(exc))
        return [], str(exc)
    _note_transport_success("serpapi")

    hits: List[SearchHit] = []
    for i, item in enumerate(body.get("organic_results") or [], start=1):
        link = str(item.get("link") or "").strip()
        if not link:
            continue
        hits.append(
            {
                "rank": i,
                "url": link,
                "title": str(item.get("title") or ""),
                "snippet": str(item.get("snippet") or ""),
                "provider": "serpapi",
            }
        )
        if len(hits) >= top_n:
            break
    return hits, None


def search_google_cse(
    query: str,
    *,
    top_n: int = 5,
    api_key: Optional[str] = None,
    cx: Optional[str] = None,
    gl: str = "uk",
    hl: str = "en",
) -> Tuple[List[SearchHit], Optional[str]]:
    if "google_cse" in _PROVIDER_REFUSED:
        return [], _PROVIDER_REFUSED["google_cse"]
    key = (api_key or os.environ.get("GOOGLE_CSE_API_KEY", "")).strip()
    engine_id = (cx or os.environ.get("GOOGLE_CSE_CX", "")).strip()
    if not key:
        return [], "GOOGLE_CSE_API_KEY not set"
    if not engine_id:
        return [], "GOOGLE_CSE_CX (Programmable Search Engine ID) not set"

    params = {
        "key": key,
        "cx": engine_id,
        "q": query,
        "num": str(max(1, min(int(top_n), 10))),
        "gl": gl or "uk",
        "hl": hl or "en",
    }
    url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
    try:
        body = _http_get_json(url)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        if _account_level_refusal(exc):
            _remember_refusal("google_cse", str(exc))
        else:
            logger.warning("Google CSE search failed: %s", exc)
        return [], str(exc)

    if body.get("error"):
        err = body["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        return [], msg or "Google CSE error"

    hits: List[SearchHit] = []
    for i, item in enumerate(body.get("items") or [], start=1):
        link = str(item.get("link") or "").strip()
        if not link:
            continue
        hits.append(
            {
                "rank": i,
                "url": link,
                "title": str(item.get("title") or ""),
                "snippet": str(item.get("snippet") or ""),
                "provider": "google_cse",
            }
        )
        if len(hits) >= top_n:
            break
    return hits, None


def search_web_result_urls(
    query: str,
    *,
    top_n: Optional[int] = None,
    provider: Optional[str] = None,
    allowed_domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Run a web search and return top-N URLs (optionally filtered to allowed_domains).

    Returns:
        ok (bool), query, provider, hits (list), urls (list[str]), error (optional)
    """
    cfg = _web_search_cfg()
    if not cfg.get("enabled", True):
        return {"ok": False, "query": query, "provider": "none", "hits": [], "urls": [], "error": "search_disabled"}

    n = int(top_n if top_n is not None else cfg.get("top_n") or 5)
    n = max(1, min(n, 10))
    domains = allowed_domains if allowed_domains is not None else list(cfg.get("allowed_domains") or [])
    resolved = resolve_search_provider(provider)

    hits: List[SearchHit] = []
    err: Optional[str] = None

    if resolved == "serpapi":
        hits, err = search_serpapi(
            query,
            top_n=n,
            region=str(cfg.get("region") or cfg.get("google_gl") or "uk"),
            hl=str(cfg.get("google_hl") or "en"),
        )
    elif resolved == "google_cse":
        hits, err = search_google_cse(
            query,
            top_n=n,
            gl=str(cfg.get("google_gl") or "uk"),
            hl=str(cfg.get("google_hl") or "en"),
        )
    elif resolved == "anthropic":
        return {
            "ok": False,
            "query": query,
            "provider": "anthropic",
            "hits": [],
            "urls": [],
            "error": "Use web_ai_price_lookup._web_search_price for Anthropic tool search",
        }
    else:
        return {
            "ok": False,
            "query": query,
            "provider": "none",
            "hits": [],
            "urls": [],
            "error": "No search API configured (set SERPAPI_API_KEY or GOOGLE_CSE_API_KEY+GOOGLE_CSE_CX)",
        }

    if err and not hits:
        return {"ok": False, "query": query, "provider": resolved, "hits": [], "urls": [], "error": err}

    filtered = _filter_hits(hits, domains)
    urls = [str(h["url"]) for h in filtered if h.get("url")]
    return {
        "ok": bool(urls),
        "query": query,
        "provider": resolved,
        "hits": filtered,
        "urls": urls,
        "all_hits_before_filter": hits,
        "allowed_domains": domains,
        "error": err,
    }
