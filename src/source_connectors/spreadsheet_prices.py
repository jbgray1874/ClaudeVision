from pathlib import Path
from typing import Any, Dict, List, Optional

from estimate_template_parser import parse_estimate_template
from extractor_patterns import canonical_material, normalize_text


class SpreadsheetPriceConnector:
    source_name = "spreadsheet"

    def __init__(self, workbook_path: str | Path) -> None:
        self.workbook_path = Path(workbook_path)
        self._parsed: Optional[Dict[str, Any]] = None

    def is_available(self) -> bool:
        return self.workbook_path.exists()

    def _load(self) -> Dict[str, Any]:
        if self._parsed is None:
            self._parsed = parse_estimate_template(self.workbook_path)
        return self._parsed

    def get_material_price(self, material: str, thickness_mm: Optional[float] = None, quantity: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []

        parsed = self._load()
        normalized_material = canonical_material(material) or normalize_text(material).upper()
        results: List[Dict[str, Any]] = []

        for entry in parsed.get("key_formulas", {}).get("material_formulas", []):
            formula = str(entry.get("formula", ""))
            labels = normalize_text(
                " ".join(
                    [
                        str(entry.get("labels", {}).get("left", "")),
                        str(entry.get("labels", {}).get("left_2", "")),
                        str(entry.get("labels", {}).get("right", "")),
                    ]
                )
            ).upper()
            if normalized_material and normalized_material not in labels and "MATERIAL PRICE BREAK" not in formula.upper():
                continue
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
                    "confidence": 0.55,
                    "evidence": {
                        "workbook": str(self.workbook_path),
                        "sheet": entry.get("sheet"),
                        "address": entry.get("address"),
                        "formula": formula,
                        "labels": entry.get("labels"),
                        "value": entry.get("value"),
                    },
                }
            )
        return results[:20]

    def get_labour_rate(self, operation: str) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []

        parsed = self._load()
        operation_upper = normalize_text(operation).upper()
        results: List[Dict[str, Any]] = []

        for entry in parsed.get("key_formulas", {}).get("labour_formulas", []):
            labels = normalize_text(
                " ".join(
                    [
                        str(entry.get("labels", {}).get("left", "")),
                        str(entry.get("labels", {}).get("left_2", "")),
                        str(entry.get("labels", {}).get("right", "")),
                    ]
                )
            ).upper()
            formula = str(entry.get("formula", ""))
            if operation_upper and operation_upper not in labels and operation_upper not in formula.upper():
                continue
            results.append(
                {
                    "source": self.source_name,
                    "kind": "labour_rate",
                    "operation": operation,
                    "price": None,
                    "currency": "GBP",
                    "unit": "hour",
                    "confidence": 0.5,
                    "evidence": {
                        "workbook": str(self.workbook_path),
                        "sheet": entry.get("sheet"),
                        "address": entry.get("address"),
                        "formula": formula,
                        "labels": entry.get("labels"),
                        "value": entry.get("value"),
                    },
                }
            )
        return results[:20]
