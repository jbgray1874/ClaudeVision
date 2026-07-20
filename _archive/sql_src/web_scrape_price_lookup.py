"""
SDIAIVision — Tactical Web Scrape Price Lookup (Tier 5)
Rule-based, no paid API required.

Pipeline:
  normalized query (material, description, dimensions)
  → catalog_url from estimating_supplier_catalog_url (preferred)
  → OR domain allowlist search URL
  → fetch HTML (requests + retry/backoff) — **no JS execution**
  → JSON-LD Product/Offer extraction (primary)
  → CSS/regex fallback (per-domain selectors)
  → normalize unit + currency to GBP
  → return price with confidence 0.30–0.45 + full audit trail

**Tier 5 reality:** domains marked ``spa_client_rendered`` (e.g. metals4u React) ship
an HTML shell; prices load in the browser — use Playwright for those or prefer
WooCommerce-style sites (ritemp, lawcris) that embed JSON-LD in the initial HTML.

**Catalog URL:** If the path returns HTTP 404 or has no extractable price, the same domain's
``search_url`` is tried automatically when ``--material`` / ``--description`` is non-empty.
Override globally with env ``WEB_SCRAPE_VERIFY_SSL=0`` (testing only; insecure).

Usage (standalone test):
  python src/web_scrape_price_lookup.py --material "MILD STEEL"
  python src/web_scrape_price_lookup.py --url "https://www.metals4u.co.uk/..." -v
  python src/web_scrape_price_lookup.py --material "sheet" --json-audit
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

logger = logging.getLogger(__name__)

# ── HTTP headers ───────────────────────────────────────────────────────────────
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.google.co.uk/",
}

# ── Domain allowlist + per-domain CSS/regex selectors ─────────────────────────
# Each entry: list of CSS-like regex patterns to try if JSON-LD fails.
# Pattern format: a regex applied to the raw HTML.
# WooCommerce / server-rendered sites first; JS SPAs last (see spa_client_rendered).
DOMAIN_CONFIG: Dict[str, Dict[str, Any]] = {
    "ritemp.co.uk": {
        # TLS chain issues on some networks (self-signed / incomplete chain) — verify disabled only here.
        "verify_tls": False,
        "unit_hint": "sheet",
        "currency": "GBP",
        "search_url": "https://www.ritemp.co.uk/?s={query}",
        "price_patterns": [
            r'"price":\s*"?([\d,]+\.?\d*)"?',
            r'class="[^"]*woocommerce-Price-amount[^"]*"[^>]*>\s*<[^>]*>£</[^>]*>([\d,]+\.?\d*)',
            r'woocommerce-Price-amount[^>]*>[\s\S]{0,120}?<bdi[^>]*>\s*£?\s*([\d,]+\.?\d*)',
            r'class="[^"]*price[^"]*"[^>]*>\s*£\s*([\d,]+\.?\d*)',
        ],
    },
    "lawcris.co.uk": {
        "unit_hint": "sheet",
        "currency": "GBP",
        "search_url": "https://www.lawcris.co.uk/?s={query}",
        "price_patterns": [
            r'"price":\s*"?([\d,]+\.?\d*)"?',
            r'class="[^"]*price[^"]*"[^>]*>\s*£\s*([\d,]+\.?\d*)',
        ],
    },
    "leengatemetal.co.uk": {
        "unit_hint": "kg",
        "currency": "GBP",
        "search_url": "https://www.leengatemetal.co.uk/?s={query}",
        "price_patterns": [
            r'"price":\s*"?([\d,]+\.?\d*)"?',
            r'class="[^"]*price[^"]*"[^>]*>\s*£\s*([\d,]+\.?\d*)',
        ],
    },
    "aalco.co.uk": {
        "unit_hint": "kg",
        "currency": "GBP",
        "search_url": "https://www.aalco.co.uk/search?q={query}",
        "price_patterns": [
            r'"price":\s*"?([\d,]+\.?\d*)"?',
            r'data-price="([\d,]+\.?\d*)"',
        ],
    },
    "panelco.co.uk": {
        "unit_hint": "sheet",
        "currency": "GBP",
        "search_url": "https://www.panelco.co.uk/?s={query}",
        "price_patterns": [
            r'"price":\s*"?([\d,]+\.?\d*)"?',
        ],
    },
    "fastenright.co.uk": {
        "unit_hint": "each",
        "currency": "GBP",
        "search_url": "https://www.fastenright.co.uk/search?q={query}",
        "price_patterns": [
            r'"price":\s*"?([\d,]+\.?\d*)"?',
            r'class="[^"]*price[^"]*"[^>]*>\s*£\s*([\d,]+\.?\d*)',
        ],
    },
    "fhbrundle.co.uk": {
        "unit_hint": "each",
        "currency": "GBP",
        "search_url": "https://www.fhbrundle.co.uk/search?q={query}",
        "price_patterns": [
            r'"price":\s*"?([\d,]+\.?\d*)"?',
        ],
    },
    "metals4u.co.uk": {
        "spa_client_rendered": True,
        "unit_hint": "kg",
        "currency": "GBP",
        "search_url": "https://www.metals4u.co.uk/search?q={query}",
        "price_patterns": [
            r'"price":\s*"?([\d,]+\.?\d*)"?',
            r'data-price="([\d,]+\.?\d*)"',
            r'class="[^"]*price[^"]*"[^>]*>\s*£\s*([\d,]+\.?\d*)',
        ],
    },
}

ALLOWED_DOMAINS = set(DOMAIN_CONFIG.keys())

# Extra site-search phrases when the raw material token matches no products (e.g. ACRYLIC → acrylic).
_MATERIAL_SEARCH_ALIASES: Dict[str, List[str]] = {
    "ACRYLIC": ["acrylic", "perspex", "plexiglass"],
    "PERSPEX": ["perspex", "acrylic"],
    "POLYCARBONATE": ["polycarbonate", "lexan"],
}


def _search_query_variants(
    material_hint: Optional[str],
    description: Optional[str],
    combined: str,
    max_variants: int = 6,
) -> List[str]:
    """Distinct search strings: original, lowercased, material aliases — for WordPress/Woo stores."""
    out: List[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = (q or "").strip()
        if len(q) < 2:
            return
        k = q.casefold()
        if k in seen:
            return
        seen.add(k)
        out.append(q)
        if len(out) >= max_variants:
            return

    add(combined)
    add(combined.lower())
    mh = (material_hint or "").strip().upper()
    if mh in _MATERIAL_SEARCH_ALIASES:
        for alt in _MATERIAL_SEARCH_ALIASES[mh]:
            add(alt)
            if len(out) >= max_variants:
                return
    desc = (description or "").strip()
    if desc and desc.casefold() != combined.casefold():
        add(desc)
    return out


def _wordpress_search_zero_hits(html: str) -> bool:
    """Typical WP/Woo 'no results' copy (not a hard bot wall)."""
    low = html.lower()
    if "sorry, no posts matched your criteria" in low:
        return True
    if "nothing found" in low and "no posts matched" in low:
        return True
    if "no results found" in low and "search results" in low:
        return True
    return False


def _is_query_search_url(url: str) -> bool:
    q = urlparse(url).query.lower()
    return "s=" in q or "q=" in q or "search=" in q


def _should_verify_tls(url: str) -> bool:
    """
    Whether to verify TLS certificates for this URL.
    Per-domain ``verify_tls: False`` in DOMAIN_CONFIG, or
    env ``WEB_SCRAPE_VERIFY_SSL=0`` disables verification globally (debug only).
    """
    env = (os.environ.get("WEB_SCRAPE_VERIFY_SSL") or "").strip().lower()
    if env in ("0", "false", "no"):
        return False
    if env in ("1", "true", "yes"):
        return True
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return bool(DOMAIN_CONFIG.get(host, {}).get("verify_tls", True))


# ── Unit normalisation ─────────────────────────────────────────────────────────
_UNIT_MAP = {
    "per kg":     "kg",  "per kilogram": "kg",  "kg": "kg",
    "per m":      "m",   "per metre":    "m",   "per meter": "m",   "m": "m",
    "per m2":     "m2",  "per m²":       "m2",  "per sqm":   "m2",
    "per sheet":  "sheet","sheet":        "sheet",
    "per length": "m",
    "each":       "each", "per unit":    "each", "ea": "each",
    "per roll":   "roll",
}

def _normalise_unit(raw: str) -> Optional[str]:
    if not raw:
        return None
    low = raw.strip().lower()
    for k, v in _UNIT_MAP.items():
        if k in low:
            return v
    return raw.strip() or None

def _schema_types(node: Dict[str, Any]) -> List[str]:
    t = node.get("@type")
    if t is None:
        return []
    if isinstance(t, list):
        return [str(x).strip().lower() for x in t if x is not None]
    return [str(t).strip().lower()]


# ── JSON-LD extraction ─────────────────────────────────────────────────────────
def _extract_jsonld_prices(html: str) -> List[Dict[str, Any]]:
    """
    Find all <script type="application/ld+json"> blocks.
    Return list of dicts with keys: price, currency, unit_text, name, url.
    """
    results: List[Dict[str, Any]] = []
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(html):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue

        def _walk(obj: Any) -> None:
            if isinstance(obj, list):
                for item in obj:
                    _walk(item)
                return
            if not isinstance(obj, dict):
                return
            types = _schema_types(obj)
            if any(x in ("product", "offer", "aggregateoffer") for x in types):
                is_offer = "offer" in types or "aggregateoffer" in types
                offers = obj.get("offers") or obj.get("offer") or (obj if is_offer else None)
                name = obj.get("name") or ""
                url = obj.get("url") or ""
                if isinstance(offers, dict):
                    offers = [offers]
                if isinstance(offers, list):
                    for o in offers:
                        if not isinstance(o, dict):
                            continue
                        price_val = o.get("price") or o.get("lowPrice")
                        currency  = o.get("priceCurrency", "GBP")
                        unit_text = (
                            o.get("priceSpecification", {}).get("unitText") or
                            o.get("unitText") or ""
                        )
                        try:
                            price_f = float(str(price_val).replace(",", ""))
                        except (TypeError, ValueError):
                            continue
                        if price_f > 0:
                            results.append({
                                "price": price_f,
                                "currency": currency,
                                "unit_text": unit_text,
                                "name": name,
                                "url": url,
                                "source": "json_ld",
                            })
            # Recurse
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    _walk(v)

        _walk(data)

    return results


def _extract_meta_product_prices(html: str) -> List[Dict[str, Any]]:
    """
    WooCommerce / Facebook Open Graph product meta (often present when JSON-LD is minimal).
    """
    results: List[Dict[str, Any]] = []
    price = None
    currency = "GBP"
    for m in re.finditer(
        r'<meta\s+property=["\']product:price:amount["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.I,
    ):
        try:
            price = float(m.group(1).replace(",", ""))
        except (TypeError, ValueError):
            continue
        break
    if price is None:
        for m in re.finditer(
            r'<meta\s+property=["\']og:price:amount["\']\s+content=["\']([^"\']+)["\']',
            html,
            re.I,
        ):
            try:
                price = float(m.group(1).replace(",", ""))
            except (TypeError, ValueError):
                continue
            break
    if price is None or price <= 0:
        return results
    cur_m = re.search(
        r'<meta\s+property=["\']product:price:currency["\']\s+content=["\']([A-Z]{3})["\']',
        html,
        re.I,
    )
    if cur_m:
        currency = cur_m.group(1).upper()
    results.append({
        "price": price,
        "currency": currency,
        "unit_text": "",
        "name": "",
        "url": "",
        "source": "meta_product_price",
    })
    return results


# ── Regex/CSS fallback extraction ──────────────────────────────────────────────
def _extract_regex_prices(html: str, domain: str) -> List[Dict[str, Any]]:
    """Apply per-domain regex patterns to raw HTML."""
    cfg = DOMAIN_CONFIG.get(domain, {})
    patterns = cfg.get("price_patterns", [])
    results: List[Dict[str, Any]] = []
    for pat in patterns:
        for m in re.finditer(pat, html, re.IGNORECASE):
            try:
                price_f = float(m.group(1).replace(",", ""))
            except (ValueError, IndexError):
                continue
            if 0.001 < price_f < 100_000:
                results.append({
                    "price": price_f,
                    "currency": cfg.get("currency", "GBP"),
                    "unit_text": cfg.get("unit_hint", ""),
                    "name": "",
                    "url": "",
                    "source": "regex_css",
                })
    return results


# ── HTTP fetch with retry ──────────────────────────────────────────────────────
def _fetch_html(url: str, timeout: int = 12, retries: int = 2) -> Tuple[Optional[str], int, str]:
    """
    Fetch URL. Returns (html, http_status, error_msg).
    Uses requests if available, falls back to urllib.
    """
    verify = _should_verify_tls(url)
    try:
        import requests as req_lib
        _has_requests = True
    except ImportError:
        _has_requests = False

    try:
        from urllib3.exceptions import InsecureRequestWarning
    except ImportError:
        InsecureRequestWarning = None  # type: ignore[misc, assignment]

    last_err = ""
    for attempt in range(retries + 1):
        if attempt > 0:
            time.sleep(1.5 * attempt)
        try:
            if _has_requests:
                with warnings.catch_warnings():
                    if not verify and InsecureRequestWarning is not None:
                        warnings.simplefilter("ignore", InsecureRequestWarning)
                    resp = req_lib.get(
                        url,
                        headers=_HEADERS,
                        timeout=timeout,
                        allow_redirects=True,
                        verify=verify,
                    )
                html = resp.text
                status = resp.status_code
                # Detect blocks
                if status in (403, 429, 503):
                    last_err = f"HTTP {status} — bot-blocked"
                    continue
                # Do not sniff "captcha" / "access denied" in raw HTML — WooCommerce ships
                # reCAPTCHA scripts on normal product pages (false positive).
                return html, status, ""
            else:
                import ssl
                import urllib.request

                ctx = ssl.create_default_context()
                if not verify:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                r = urllib.request.urlopen(
                    urllib.request.Request(url, headers=_HEADERS),
                    timeout=timeout,
                    context=ctx,
                )
                raw = r.read().decode("utf-8", errors="replace")
                code = getattr(r, "status", None)
                if code is None:
                    code = r.getcode()
                return raw, int(code), ""
        except Exception as exc:
            last_err = str(exc)
            logger.debug("Fetch attempt %d failed for %s: %s", attempt + 1, url, exc)
    return None, 0, last_err


# ── FX / unit normalisation to GBP per target unit ────────────────────────────
_EUR_TO_GBP = 0.855  # fallback — update periodically

def _to_gbp(price: float, currency: str) -> float:
    currency = (currency or "GBP").upper().strip()
    if currency == "GBP":
        return price
    if currency == "EUR":
        return round(price * _EUR_TO_GBP, 4)
    if currency == "USD":
        return round(price * 0.79, 4)
    # Unknown — return as-is with warning
    logger.warning("Unknown currency %s — returning price as-is", currency)
    return price


# ── Sanity bounds per unit ─────────────────────────────────────────────────────
_UNIT_BOUNDS: Dict[str, Tuple[float, float]] = {
    "kg":    (0.30, 200.0),
    "m":     (0.50, 500.0),
    "m2":    (0.50, 800.0),
    "sheet": (5.00, 3000.0),
    "each":  (0.001, 5000.0),
    "roll":  (1.00, 500.0),
}

def _price_in_bounds(price: float, unit: Optional[str]) -> bool:
    if unit and unit in _UNIT_BOUNDS:
        lo, hi = _UNIT_BOUNDS[unit]
        return lo <= price <= hi
    return 0.001 < price < 100_000


def _likely_hard_bot_wall(html: str) -> Optional[str]:
    """
    Narrow signals for an actual interstitial / block page (not normal reCAPTCHA assets).
    """
    if not html:
        return None
    low = html.lower()[:15000]
    if "checking your browser before accessing" in low:
        return "cloudflare_or_proxy_browser_check"
    if "just a moment..." in low and "cloudflare" in low:
        return "cloudflare_interstitial"
    if "sorry, you have been blocked" in low or "you have been blocked" in low:
        return "explicit_block_page"
    if "incapsula incident id" in low:
        return "incapsula_block"
    if "distil_r_block" in low or "distil networks" in low:
        return "distil_block"
    return None


def _diagnose_no_price(html: Optional[str], domain: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Why JSON-LD / regex may have found nothing (Tier 5 debugging)."""
    if not html:
        return {"reason": "empty_html"}
    low = html.lower()
    n_ld = len(re.findall(r"application/ld\+json", html, re.I))
    bot = _likely_hard_bot_wall(html)
    return {
        "html_length": len(html),
        "json_ld_script_tags": n_ld,
        "domain": domain,
        "spa_client_rendered_config": bool(cfg.get("spa_client_rendered")),
        "likely_js_shell_no_ldjson": n_ld == 0
        and (('id="root"' in low) or ("id='root'" in low) or ("__next" in low) or ("react" in low)),
        "likely_hard_bot_wall": bot,
    }

def scrape_price_with_audit(
    *,
    material_hint: Optional[str] = None,
    description: Optional[str] = None,
    catalog_url: Optional[str] = None,
    unit_hint: Optional[str] = None,
    max_price_age_hours: int = 72,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Same as scrape_price but always returns the audit dict (even on failure) for CLI / logging.

    max_price_age_hours — reserved for future HTTP caching.
    """
    _ = max_price_age_hours
    audit: Dict[str, Any] = {
        "material_hint": material_hint,
        "description": description,
        "catalog_url": catalog_url,
        "unit_hint": unit_hint,
        "steps": [],
    }

    attempts: List[Tuple[str, str, Dict[str, Any]]] = []

    if catalog_url:
        domain = urlparse(catalog_url).netloc.replace("www.", "")
        if domain not in ALLOWED_DOMAINS:
            audit["steps"].append({"action": "catalog_url_not_in_allowlist", "domain": domain})
            return None, audit
        cfg = DOMAIN_CONFIG.get(domain, {})
        attempts.append((catalog_url, domain, cfg))
        audit["steps"].append({"action": "use_catalog_url", "url": catalog_url, "domain": domain})
        query_fb = " ".join(filter(None, [material_hint, description])).strip()
        tpl = cfg.get("search_url", "")
        search_urls_added: List[str] = []
        if query_fb and tpl:
            variants = _search_query_variants(material_hint, description, query_fb)
            for qv in variants:
                search_u = tpl.format(query=quote_plus(qv))
                if search_u.rstrip("/") == str(catalog_url).rstrip("/"):
                    continue
                if any(a[0].rstrip("/") == search_u.rstrip("/") for a in attempts):
                    continue
                attempts.append((search_u, domain, cfg))
                search_urls_added.append(search_u)
            if search_urls_added:
                audit["steps"].append({
                    "action": "same_domain_search_fallback_queued",
                    "urls": search_urls_added,
                    "query_variants": variants,
                    "reason": "try after direct catalog URL if missing price or HTTP error",
                })
    else:
        query = " ".join(filter(None, [material_hint, description])).strip()
        if not query:
            audit["steps"].append({"action": "abort", "reason": "no_query"})
            return None, audit
        q_enc = quote_plus(query)
        for dom, cfg in DOMAIN_CONFIG.items():
            tpl = cfg.get("search_url", "")
            if not tpl:
                continue
            attempts.append((tpl.format(query=q_enc), dom, cfg))
        audit["steps"].append({"action": "search_sequence", "domains": [a[1] for a in attempts], "query": query})

    if not attempts:
        audit["steps"].append({"action": "abort", "reason": "no_url_available"})
        return None, audit

    candidates: List[Dict[str, Any]] = []
    url_to_fetch: Optional[str] = None
    http_status = 0
    domain = ""

    for url, dom, cfg in attempts:
        audit["steps"].append({"action": "try_fetch", "domain": dom, "url": url})
        html, http_status, fetch_err = _fetch_html(url)
        audit["steps"].append({
            "action": "fetch",
            "url": url,
            "http_status": http_status,
            "error": fetch_err or None,
            "html_chars": len(html or ""),
            "tls_verify": _should_verify_tls(url),
        })
        if http_status >= 400:
            audit["steps"].append({
                "action": "http_client_error",
                "http_status": http_status,
                "hint": "Page may not exist (wrong slug) — same-domain search will be tried if queued.",
            })
        if not html:
            logger.info("Web scrape fetch failed for %s: %s", url, fetch_err)
            continue

        if _is_query_search_url(url) and _wordpress_search_zero_hits(html):
            audit["steps"].append({
                "action": "search_zero_results",
                "url": url,
                "domain": dom,
            })
            audit["steps"].append({
                "action": "no_price_in_response",
                "domain": dom,
                "diagnostics": _diagnose_no_price(html, dom, cfg),
            })
            continue

        jsonld_hits = _extract_jsonld_prices(html)
        if jsonld_hits:
            candidates.extend(jsonld_hits)
            audit["steps"].append({"action": "json_ld_extraction", "domain": dom, "hits": len(jsonld_hits)})
            url_to_fetch = url
            domain = dom
            break

        meta_hits = _extract_meta_product_prices(html)
        if meta_hits:
            candidates.extend(meta_hits)
            audit["steps"].append({"action": "meta_price_extraction", "domain": dom, "hits": len(meta_hits)})
            url_to_fetch = url
            domain = dom
            break

        # On 404/410, HTML is often a themed error page — regex can pick spurious £ amounts.
        if http_status not in (404, 410):
            regex_hits = _extract_regex_prices(html, dom)
            if regex_hits:
                candidates.extend(regex_hits)
                audit["steps"].append({"action": "regex_extraction", "domain": dom, "hits": len(regex_hits)})
                url_to_fetch = url
                domain = dom
                break
        else:
            audit["steps"].append({"action": "skip_regex_on_404", "domain": dom})

        audit["steps"].append({
            "action": "no_price_in_response",
            "domain": dom,
            "diagnostics": _diagnose_no_price(html, dom, cfg),
        })

    if not candidates:
        audit["steps"].append({
            "action": "failed_after_trying",
            "domains": list(dict.fromkeys(a[1] for a in attempts)),
        })
        if any(
            isinstance(s, dict) and s.get("action") == "fetch" and int(s.get("http_status") or 0) == 404
            for s in audit["steps"]
        ):
            audit["steps"].append({
                "action": "hint",
                "message": "HTTP 404 on catalog URL usually means wrong path. Use a live product link, or omit --url and pass --material to use site search.",
            })
        spa = [a[1] for a in attempts if DOMAIN_CONFIG.get(a[1], {}).get("spa_client_rendered")]
        if spa:
            audit["steps"].append({
                "action": "tier5_hint",
                "message": (
                    "Client-rendered catalog (React/Vue): static HTML has no offer data with requests. "
                    f"Use Playwright (or skip) for: {', '.join(spa)}"
                ),
            })
        return None, audit

    jsonld_only = [c for c in candidates if c.get("source") == "json_ld"]
    pool = jsonld_only if jsonld_only else candidates
    pool_valid = [c for c in pool if c.get("price", 0) and float(c["price"]) > 0]
    if not pool_valid:
        audit["steps"].append({"action": "no_valid_price_candidates"})
        return None, audit

    best = min(pool_valid, key=lambda c: float(c["price"]))
    price_gbp = _to_gbp(float(best["price"]), best.get("currency", "GBP"))
    cfg_dom = DOMAIN_CONFIG.get(domain, {})
    raw_unit = (
        _normalise_unit(str(best.get("unit_text") or ""))
        or _normalise_unit(unit_hint or "")
        or (cfg_dom.get("unit_hint") or None)
    )

    if not _price_in_bounds(price_gbp, raw_unit):
        audit["steps"].append({
            "action": "sanity_check_failed",
            "price_gbp": price_gbp,
            "unit": raw_unit,
        })
        return None, audit

    confidence = 0.45 if best.get("source") == "json_ld" else (0.38 if best.get("source") == "meta_product_price" else 0.30)
    audit["steps"].append({
        "action": "selected",
        "price_gbp": price_gbp,
        "unit": raw_unit,
        "extraction": best.get("source"),
        "confidence": confidence,
        "domain": domain,
    })

    return {
        "price_gbp": round(price_gbp, 4),
        "unit": raw_unit,
        "confidence": confidence,
        "source_name": "web_scrape",
        "source_url": url_to_fetch or "",
        "http_status": http_status,
        "extraction_method": best.get("source"),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "review_required": True,
        "audit": audit,
    }, audit


def scrape_price(
    *,
    material_hint: Optional[str] = None,
    description: Optional[str] = None,
    catalog_url: Optional[str] = None,
    unit_hint: Optional[str] = None,
    max_price_age_hours: int = 72,
) -> Optional[Dict[str, Any]]:
    """
    Attempt to scrape a price. Returns None if nothing found (no audit — use scrape_price_with_audit for diagnostics).
    """
    data, _audit = scrape_price_with_audit(
        material_hint=material_hint,
        description=description,
        catalog_url=catalog_url,
        unit_hint=unit_hint,
        max_price_age_hours=max_price_age_hours,
    )
    return data


# ── Pricing service integration ────────────────────────────────────────────────

def get_web_scrape_price(
    material: Optional[str] = None,
    description: Optional[str] = None,
    catalog_url: Optional[str] = None,
    unit: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Adapter for the pricing_service tier chain.
    Returns a pricing_service-compatible result dict or None.

    Call from pricing_service._get_web_ai_fallback() when ANTHROPIC_API_KEY absent:

        from web_scrape_price_lookup import get_web_scrape_price
        result = get_web_scrape_price(
            material=material_hint,
            catalog_url=catalog_url_from_supplier_catalog,
        )
        if result:
            return {
                "source":           "web_scrape",
                "source_name":      "web_scrape",
                "unit_price_gbp":   result["price_gbp"],
                "unit":             result["unit"],
                "confidence":       result["confidence"],
                "review_required":  True,
                "audit":            result["audit"],
            }
    """
    try:
        return scrape_price(
            material_hint=material,
            description=description,
            catalog_url=catalog_url,
            unit_hint=unit,
        )
    except Exception as exc:
        logger.warning("web_scrape_price_lookup error: %s", exc)
        return None


# ── CLI test ───────────────────────────────────────────────────────────────────

def _cli() -> None:
    parser = argparse.ArgumentParser(description="Test web scrape price lookup (Tier 5 — rule-based)")
    parser.add_argument("--material", default="MILD STEEL")
    parser.add_argument("--description", default="")
    parser.add_argument("--url", default=None, help="Direct catalog URL to test")
    parser.add_argument("--unit", default=None)
    parser.add_argument(
        "--json-audit",
        action="store_true",
        help="On failure (or with --verbose), print full audit as JSON on stdout",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print(f"\nScraping price for: {args.material} {args.description}")
    print(f"URL: {args.url or '(multi-domain search — WooCommerce-friendly sites first, metals4u last)'}")
    print("-" * 60)

    result, audit = scrape_price_with_audit(
        material_hint=args.material,
        description=args.description,
        catalog_url=args.url,
        unit_hint=args.unit,
    )

    if result:
        print(f"  Price:      £{result['price_gbp']:.4f} per {result['unit'] or '?'}")
        print(f"  Confidence: {result['confidence']:.0%}")
        print(f"  Method:     {result['extraction_method']}")
        print(f"  HTTP:       {result['http_status']}")
        print(f"  Review:     {result['review_required']}")
        if args.verbose or args.json_audit:
            print("\n  Audit trail:")
            for step in audit["steps"]:
                print(f"    {step}")
            if args.json_audit:
                print(json.dumps(audit, indent=2, default=str))
    else:
        print("  No price found.", file=sys.stderr)
        print("\n  Audit trail (why Tier 5 failed):", file=sys.stderr)
        for step in audit["steps"]:
            print(f"    {step}", file=sys.stderr)
        if args.json_audit:
            print(json.dumps(audit, indent=2, default=str))
        elif not args.verbose:
            print("\n  Tip: re-run with -v or --json-audit for the same trail on stdout.", file=sys.stderr)


if __name__ == "__main__":
    _cli()
