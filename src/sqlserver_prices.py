from datetime import date
from typing import Any, Dict, List, Optional

from extractor_patterns import canonical_material, normalize_text

try:
    import pyodbc  # type: ignore
except ImportError:  # pragma: no cover
    pyodbc = None


class SqlServerPriceConnector:
    source_name = "sqlserver"

    def __init__(
        self,
        server: str,
        database: str,
        username: str,
        password: str,
        material_price_query: str = "",
        labour_rate_query: str = "",
        part_system_cost_query: str = "",
        driver: str = "ODBC Driver 18 for SQL Server",
        encrypt: bool = True,
        trust_server_certificate: bool = True,
    ) -> None:
        self.server = server
        self.database = database
        self.username = username
        self.password = password
        self.material_price_query = material_price_query
        self.labour_rate_query = labour_rate_query
        self.part_system_cost_query = part_system_cost_query
        self.driver = driver
        self.encrypt = encrypt
        self.trust_server_certificate = trust_server_certificate

    def is_available(self) -> bool:
        return bool(
            pyodbc is not None
            and self.server
            and self.database
            and self.username
            and self.password
        )

    def _connect(self):
        encrypt = "yes" if self.encrypt else "no"
        trust = "yes" if self.trust_server_certificate else "no"
        conn_str = (
            f"DRIVER={{{self.driver}}};"
            f"SERVER={self.server};"
            f"DATABASE={self.database};"
            f"UID={self.username};"
            f"PWD={self.password};"
            f"Encrypt={encrypt};"
            f"TrustServerCertificate={trust};"
        )
        return pyodbc.connect(conn_str, timeout=10)

    def _rows_to_dicts(self, cursor) -> List[Dict[str, Any]]:
        columns = [col[0] for col in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_material_price(self, material: str, thickness_mm: Optional[float] = None, quantity: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.is_available() or not self.material_price_query:
            return []

        normalized_material = canonical_material(material) or normalize_text(material).upper()
        thickness = thickness_mm if thickness_mm is not None else 0.0
        qty = quantity if quantity is not None else 1
        rows: List[Dict[str, Any]] = []

        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(self.material_price_query, normalized_material, thickness, qty)
            for row in self._rows_to_dicts(cursor):
                price = row.get("price")
                if price is None:
                    price = row.get("unit_price")
                rows.append(
                    {
                        "source": self.source_name,
                        "kind": "material_price",
                        "material": normalized_material,
                        "thickness_mm": thickness_mm,
                        "quantity": quantity,
                        "price": price,
                        "currency": row.get("currency") or "GBP",
                        "unit": row.get("unit") or "GBP_per_kg",
                        "confidence": float(row.get("confidence") or 0.92),
                        "evidence": {
                            "server": self.server,
                            "database": self.database,
                            "supplier_source": row.get("supplier_source"),
                            "price_date": str(row.get("price_date") or date.today()),
                            "row": row,
                        },
                    }
                )
        return rows

    def get_labour_rate(self, operation: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not self.labour_rate_query:
            return []

        op = normalize_text(operation).lower()
        rows: List[Dict[str, Any]] = []
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(self.labour_rate_query, op)
            for row in self._rows_to_dicts(cursor):
                rate = row.get("price")
                if rate is None:
                    rate = row.get("hourly_rate")
                rows.append(
                    {
                        "source": self.source_name,
                        "kind": "labour_rate",
                        "operation": operation,
                        "price": rate,
                        "currency": row.get("currency") or "GBP",
                        "unit": row.get("unit") or "GBP_per_hour",
                        "confidence": float(row.get("confidence") or 0.92),
                        "evidence": {
                            "server": self.server,
                            "database": self.database,
                            "rate_code": row.get("rate_code"),
                            "price_date": str(row.get("price_date") or date.today()),
                            "row": row,
                        },
                    }
                )
        return rows

    def get_part_system_cost(self, part_code: str, description: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not self.part_system_cost_query:
            return []

        part_code_norm = normalize_text(part_code).upper()
        desc_norm = normalize_text(description)
        rows: List[Dict[str, Any]] = []
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(self.part_system_cost_query, part_code_norm, desc_norm)
            for row in self._rows_to_dicts(cursor):
                price = row.get("price")
                if price is None:
                    price = row.get("system_cost_per")
                rows.append(
                    {
                        "source": self.source_name,
                        "kind": "part_system_cost",
                        "part_code": part_code_norm,
                        "description": desc_norm,
                        "price": price,
                        "currency": row.get("currency") or "GBP",
                        "unit": row.get("unit") or "each",
                        "supplier_code": row.get("supplier_code"),
                        "supplier_name": row.get("supplier_name"),
                        "confidence": float(row.get("confidence") or 0.9),
                        "evidence": {
                            "server": self.server,
                            "database": self.database,
                            "supplier_code": row.get("supplier_code"),
                            "supplier_name": row.get("supplier_name"),
                            "price_date": str(row.get("price_date") or date.today()),
                            "row": row,
                        },
                    }
                )
        return rows

