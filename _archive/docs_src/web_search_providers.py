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


def search_serpapi(
    query: str,
    *,
    top_n: int = 5,
    api_key: Optional[str] = None,
    region: str = "uk",
    hl: str = "en",
) -> Tuple[List[SearchHit], Optional[str]]:
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
        logger.warning("SerpAPI search failed: %s", exc)
        return [], str(exc)

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
