from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import os
import json

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

    def is_available(self) -> bool:
        return bool(self.sources and requests is not None and BeautifulSoup is not None)

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
                    model = os.getenv("XAI_MODEL", "grok-2-latest")
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

    def get_material_price(self, material: str, thickness_mm: Optional[float] = None, quantity: Optional[int] = None) -> List[Dict[str, Any]]:
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

        return results

    def get_labour_rate(self, operation: str) -> List[Dict[str, Any]]:
        return []
