from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from extractor_patterns import canonical_material, normalize_text

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover
    requests = None

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover
    BeautifulSoup = None


class WebPriceConnector:
    source_name = "web"

    def __init__(self, sources: List[Dict[str, Any]], user_agent: str = "CodexPriceCollector/1.0") -> None:
        self.sources = sources
        self.user_agent = user_agent

    def is_available(self) -> bool:
        return bool(self.sources and requests is not None and BeautifulSoup is not None)

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

            results.append(
                {
                    "source": self.source_name,
                    "kind": "material_price",
                    "material": normalized_material,
                    "thickness_mm": thickness_mm,
                    "quantity": quantity,
                    "price": None,
                    "currency": source.get("currency", "GBP"),
                    "unit": source.get("unit", "unknown"),
                    "confidence": 0.45 if price_text else 0.2,
                    "evidence": {
                        "url": url,
                        "price_text": price_text,
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
            )

        return results

    def get_labour_rate(self, operation: str) -> List[Dict[str, Any]]:
        return []
