from pathlib import Path
from typing import Any, Dict, List, Optional

from extractor_patterns import canonical_material, normalize_text

try:
    import pyodbc  # type: ignore
except ImportError:  # pragma: no cover
    pyodbc = None


class AccessPriceConnector:
    source_name = "access"

    def __init__(self, database_path: str | Path, material_price_query: str = "") -> None:
        self.database_path = Path(database_path) if database_path else Path()
        self.material_price_query = material_price_query

    def is_available(self) -> bool:
        return pyodbc is not None and self.database_path.exists()

    def _connect(self):
        connection_string = (
            r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
            f"Dbq={self.database_path};"
        )
        return pyodbc.connect(connection_string)

    def get_material_price(self, material: str, thickness_mm: Optional[float] = None, quantity: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.is_available() or not self.material_price_query:
            return []

        normalized_material = canonical_material(material) or normalize_text(material).upper()
        rows: List[Dict[str, Any]] = []
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(self.material_price_query, normalized_material)
            columns = [column[0] for column in cursor.description]
            for record in cursor.fetchall():
                row = dict(zip(columns, record))
                rows.append(
                    {
                        "source": self.source_name,
                        "kind": "material_price",
                        "material": normalized_material,
                        "thickness_mm": thickness_mm,
                        "quantity": quantity,
                        "price": row.get("price") or row.get("unit_price"),
                        "currency": row.get("currency", "GBP"),
                        "unit": row.get("unit", "unknown"),
                        "confidence": 0.9,
                        "evidence": {
                            "database": str(self.database_path),
                            "row": row,
                        },
                    }
                )
        return rows

    def get_labour_rate(self, operation: str) -> List[Dict[str, Any]]:
        return []
