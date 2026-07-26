from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import os
import json

import config
from extractor_patterns import canonical_material, normalize_text

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover
    requests = None

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover
    BeautifulSoup = None

# Optional LLM helpers: Grok / xAI and OpenAI.
try:  # pragma: no cover - optional dependency
    import xai_sdk  # type: ignore
except ImportError:  # pragma: no cover
    xai_sdk = None

try:  # pragma: no cover - optional dependency
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover
    OpenAI = None


class WebPriceConnector:
    source_name = "web"

    def __init__(self, sources: List[Dict[str, Any]], user_agent: str = "CodexPriceCollector/1.0") -> None:
        self.sources = sources
        self.user_agent = user_agent
        self.llm_provider = os.getenv("WEB_PRICE_LLM_PROVIDER", "").lower()
        # If config sets provider explicitly, prefer that over env var.
        # Caller can override by setting WEB_PRICE_LLM_PROVIDER env var.

    def _fallback_policy(self) -> Dict[str, Any]:
        return getattr(config, "FALLBACK_PRICING_POLICY", {}) or {}

    def is_available(self) -> bool:
        if requests is None:
            return False
        web_cfg = (getattr(config, "PRICE_SOURCE_CONFIG", {}) or {}).get("web", {}) or {}
        if not web_cfg.get("enabled"):
            return False
        pol = self._fallback_policy()
        if pol.get("enable_web_ai_fallback") and (self._xai_client() is not None or self._openai_client() is not None):
            return True
        return bool(self.sources and BeautifulSoup is not None)

    # ---- LLM helpers -------------------------------------------------

    def _xai_client(self):
        if xai_sdk is None:
            return None
        api_key = os.getenv("XAI_API_KEY") or ""
        if not api_key:
            return None
        try:
            return xai_sdk.Client(api_key=api_key)
        except Exception:
            return None

    def _openai_client(self):
        if OpenAI is None:
            return None
        api_key = os.getenv("OPENAI_API_KEY") or ""
        if not api_key:
            return None
        try:
            return OpenAI(api_key=api_key)
        except Exception:
            return None

    def _llm_extract_price(self, html: str, url: str, material: str, default_unit: str) -> Dict[str, Any]:
        """
        Ask an LLM (Grok/xAI or OpenAI) to extract a numeric price from a supplier/catalog page.

        Returns dict with keys: price (float or None), currency, unit, model, provider, raw_response.
        """
        prompt = (
            "You are a pricing parser for manufacturing materials.\n"
            "Extract the best single unit price from this HTML page for the requested material, "
            "if it is clearly present.\n"
            "Return ONLY a JSON object with keys: price, currency, unit.\n"
            "If no clear price is present, set price to null.\n\n"
            f"URL: {url}\n"
            f"Requested material hint: {material}\n\n"
            "HTML snippet:\n"
            f"{html[:12000]}"
        )

        # Default result when no LLM or failure.
        result: Dict[str, Any] = {
            "price": None,
            "currency": "GBP",
            "unit": default_unit or "unknown",
            "provider": None,
            "model": None,
            "raw_response": None,
        }

        provider = os.getenv("WEB_PRICE_LLM_PROVIDER", "").lower()

        # Try xAI / Grok first if requested.
        if provider in {"xai", "grok", ""}:
            client = self._xai_client()
            if client is not None:
                try:
                    model = os.getenv("XAI_MODEL", "grok-4.5")
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "You extract numeric prices for engineering materials."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.1,
                    )
                    content = (resp.choices[0].message.content or "").strip()
                    result["raw_response"] = content
                    result["provider"] = "xai"
                    result["model"] = model
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict):
                            result["price"] = parsed.get("price")
                            result["currency"] = parsed.get("currency") or result["currency"]
                            result["unit"] = parsed.get("unit") or result["unit"]
                            return result
                    except Exception:
                        pass
                except Exception:
                    # Fall through to OpenAI or return default.
                    pass

        # Fallback to OpenAI if configured.
        if provider in {"openai", ""}:
            client = self._openai_client()
            if client is not None:
                try:
                    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "You extract numeric prices for engineering materials."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.1,
                    )
                    content = (resp.choices[0].message.content or "").strip()
                    result["raw_response"] = content
                    result["provider"] = "openai"
                    result["model"] = model
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict):
                            result["price"] = parsed.get("price")
                            result["currency"] = parsed.get("currency") or result["currency"]
                            result["unit"] = parsed.get("unit") or result["unit"]
                            return result
                    except Exception:
                        pass
                except Exception:
                    pass

        return result

    def _parse_llm_json_object(self, content: str) -> Dict[str, Any]:
        text = (content or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                pass
        return {}

    def _llm_market_price_row(
        self,
        *,
        kind: str,
        material: str,
        thickness_mm: Optional[float],
        quantity: Optional[int],
        part_code: str,
        description: str,
    ) -> Optional[Dict[str, Any]]:
        """
        When internal SQL/spreadsheet sources miss a price, ask an LLM for an indicative UK-trade
        reference (same role as a human estimator searching the web). Clearly tagged in evidence.
        """
        pol = self._fallback_policy()
        if not pol.get("enable_web_ai_fallback"):
            return None
        web_cfg = (getattr(config, "PRICE_SOURCE_CONFIG", {}) or {}).get("web", {}) or {}
        if not web_cfg.get("enabled"):
            return None
        if not web_cfg.get("llm_market_estimate_fallback", True):
            return None

        cap = float(pol.get("fallback_confidence_cap", 0.72) or 0.72)
        q_hint = f"{material} sheet/board stock {thickness_mm or ''}mm".strip()
        if kind == "part_system_cost":
            q_hint = f"bought-in component {part_code} {description}".strip()[:500]

        prompt = (
            "You are assisting a UK manufacturing estimator. No internal catalogue price was found.\n"
            "Return ONLY a compact JSON object (no markdown) with keys:\n"
            '  "price_gbp": number or null (typical UK trade purchase price in GBP),\n'
            '  "unit": either "GBP_per_kg" for raw material stock OR "each" for a discrete bought-in part,\n'
            '  "confidence": number between 0 and 1 reflecting your uncertainty,\n'
            '  "rationale": one short sentence (no URLs required),\n'
            '  "suggested_supplier_type": short string e.g. "catalogue distributor"\n'
            "Rules: prefer trade/indicative prices, not luxury retail. If you truly cannot estimate, set price_gbp to null.\n\n"
            f"kind: {kind}\n"
            f"material_hint: {material}\n"
            f"thickness_mm: {thickness_mm}\n"
            f"quantity_context: {quantity}\n"
            f"part_code: {part_code}\n"
            f"description: {description[:900]}\n"
            f"search_hint: {q_hint}\n"
        )

        content = ""
        provider_used = None
        model_used = None
        client = self._xai_client()
        if client is not None:
            try:
                model = str(web_cfg.get("xai_model") or os.getenv("XAI_MODEL", "grok-4.5"))
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You return only valid JSON for manufacturing price hints."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                )
                content = (resp.choices[0].message.content or "").strip()
                provider_used = "xai"
                model_used = model
            except Exception:
                content = ""

        if not content:
            oa = self._openai_client()
            if oa is not None:
                try:
                    model = str(web_cfg.get("openai_model") or os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
                    resp = oa.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "You return only valid JSON for manufacturing price hints."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.2,
                    )
                    content = (resp.choices[0].message.content or "").strip()
                    provider_used = "openai"
                    model_used = model
                except Exception:
                    content = ""

        data = self._parse_llm_json_object(content)
        price = data.get("price_gbp")
        try:
            price_f = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_f = None
        if price_f is None or price_f <= 0:
            return None

        unit = str(data.get("unit") or ("GBP_per_kg" if kind == "material_price" else "each")).strip().lower()
        if unit not in {"gbp_per_kg", "each"}:
            unit = "gbp_per_kg" if kind == "material_price" else "each"

        try:
            conf = float(data.get("confidence") or pol.get("fallback_confidence", 0.65))
        except (TypeError, ValueError):
            conf = float(pol.get("fallback_confidence", 0.65) or 0.65)
        conf = max(0.05, min(cap, conf))

        rationale = str(data.get("rationale") or "").strip()
        supplier_type = str(data.get("suggested_supplier_type") or "unknown").strip()

        return {
            "source": self.source_name,
            "kind": kind,
            "material": material or None,
            "part_code": part_code or None,
            "description": description or None,
            "thickness_mm": thickness_mm,
            "quantity": quantity,
            "price": price_f,
            "currency": "GBP",
            "unit": unit,
            "confidence": conf,
            "evidence": {
                "pricing_mode": "web_ai_llm_estimate",
                "source_note": "Not in internal database (SQL / bought_in_parts / spreadsheet) — indicative LLM market estimate.",
                "web_query": q_hint[:500],
                "llm_provider": provider_used,
                "llm_model": model_used,
                "llm_raw_response": content[:8000],
                "rationale": rationale,
                "suggested_supplier_type": supplier_type,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    def get_material_price(
        self,
        material: str,
        thickness_mm: Optional[float] = None,
        quantity: Optional[int] = None,
        description: str = "",
    ) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []

        normalized_material = canonical_material(material) or normalize_text(material).upper()
        results: List[Dict[str, Any]] = []

        for source in self.sources:
            url = source.get("url")
            if not url:
                continue
            material_hint = normalize_text(str(source.get("material_hint", ""))).upper()
            if material_hint and material_hint not in normalized_material:
                continue

            try:
                response = requests.get(
                    url,
                    headers={"User-Agent": self.user_agent},
                    timeout=20,
                )
                response.raise_for_status()
            except Exception as exc:
                results.append(
                    {
                        "source": self.source_name,
                        "kind": "material_price",
                        "material": normalized_material,
                        "thickness_mm": thickness_mm,
                        "quantity": quantity,
                        "price": None,
                        "currency": "GBP",
                        "unit": "unknown",
                        "confidence": 0.0,
                        "evidence": {
                            "url": url,
                            "error": str(exc),
                        },
                    }
                )
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            selector = source.get("price_selector")
            price_text = ""
            if selector:
                element = soup.select_one(selector)
                if element:
                    price_text = normalize_text(element.get_text(" ", strip=True))

            llm_price_info: Dict[str, Any] = {}
            if not price_text or source.get("use_llm", True):
                # Use an LLM helper (Grok / xAI or OpenAI) to parse the full page when enabled.
                llm_price_info = self._llm_extract_price(
                    html=response.text,
                    url=url,
                    material=normalized_material,
                    default_unit=source.get("unit", "unknown"),
                )

            price = None
            currency = source.get("currency", "GBP")
            unit = source.get("unit", "unknown")
            confidence = 0.2

            if llm_price_info.get("price") is not None:
                price = float(llm_price_info["price"])
                currency = llm_price_info.get("currency") or currency
                unit = llm_price_info.get("unit") or unit
                confidence = 0.7
            elif price_text:
                # We only have raw text; estimator code or a later pass can interpret it.
                confidence = 0.45

            results.append(
                {
                    "source": self.source_name,
                    "kind": "material_price",
                    "material": normalized_material,
                    "thickness_mm": thickness_mm,
                    "quantity": quantity,
                    "price": price,
                    "currency": currency,
                    "unit": unit,
                    "confidence": confidence,
                    "evidence": {
                        "url": url,
                        "price_text": price_text,
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "llm_provider": llm_price_info.get("provider"),
                        "llm_model": llm_price_info.get("model"),
                        "llm_raw_response": llm_price_info.get("raw_response"),
                    },
                }
            )

        if any(row.get("price") is not None for row in results):
            return results

        llm_row = self._llm_market_price_row(
            kind="material_price",
            material=normalized_material,
            thickness_mm=thickness_mm,
            quantity=quantity,
            part_code="",
            description=str(description or ""),
        )
        if llm_row:
            results.append(llm_row)
        return results

    def get_part_system_cost(self, part_code: str, description: str) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        row = self._llm_market_price_row(
            kind="part_system_cost",
            material="",
            thickness_mm=None,
            quantity=None,
            part_code=str(part_code or "").strip(),
            description=str(description or "").strip(),
        )
        return [row] if row else []

    def get_labour_rate(self, operation: str) -> List[Dict[str, Any]]:
        return []
