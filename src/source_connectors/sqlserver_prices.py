import os
import time
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
        source_name: str = "sqlserver",
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
        self.source_name = source_name

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

    def _execute_query(self, cursor, query: str, params: List[Any]) -> None:
        try:
            cursor.timeout = int(os.getenv("SQL_QUERY_TIMEOUT_SEC", "8"))
        except Exception:
            pass
        marker_count = query.count("?")
        if marker_count == 0:
            cursor.execute(query)
            return
        if marker_count > len(params):
            raise ValueError(
                f"SQL expects {marker_count} parameters but only {len(params)} were supplied."
            )
        cursor.execute(query, *params[:marker_count])

    def _debug(self, message: str) -> None:
        if os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}:
            print(f"[DEBUG] sqlserver_prices {message}")

    def get_material_price(self, material: str, thickness_mm: Optional[float] = None, quantity: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.is_available() or not self.material_price_query:
            return []

        normalized_material = canonical_material(material) or normalize_text(material).upper()
        thickness = thickness_mm if thickness_mm is not None else 0.0
        qty = quantity if quantity is not None else 1
        rows: List[Dict[str, Any]] = []

        try:
            started = time.time()
            self._debug(f"start get_material_price material={normalized_material} thickness={thickness} qty={qty}")
            with self._connect() as connection:
                cursor = connection.cursor()
                self._execute_query(cursor, self.material_price_query, [normalized_material, thickness, qty])
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
            self._debug(f"done get_material_price rows={len(rows)} elapsed={round(time.time()-started,2)}s")
        except Exception:
            self._debug("failed get_material_price -> returning []")
            return []
        return rows

    def get_labour_rate(self, operation: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not self.labour_rate_query:
            return []

        op = normalize_text(operation).lower()
        rows: List[Dict[str, Any]] = []
        try:
            started = time.time()
            self._debug(f"start get_labour_rate operation={op}")
            with self._connect() as connection:
                cursor = connection.cursor()
                self._execute_query(cursor, self.labour_rate_query, [op])
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
            self._debug(f"done get_labour_rate rows={len(rows)} elapsed={round(time.time()-started,2)}s")
        except Exception:
            self._debug("failed get_labour_rate -> returning []")
            return []
        return rows

    def get_part_system_cost(self, part_code: str, description: str) -> List[Dict[str, Any]]:
        if not self.is_available() or not self.part_system_cost_query:
            return []

        part_code_norm = normalize_text(part_code).upper()
        desc_norm = normalize_text(description)
        rows: List[Dict[str, Any]] = []
        try:
            started = time.time()
            self._debug(f"start get_part_system_cost part_code={part_code_norm} desc_len={len(desc_norm)}")
            with self._connect() as connection:
                cursor = connection.cursor()
                self._execute_query(cursor, self.part_system_cost_query, [part_code_norm, desc_norm, part_code_norm])
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
            self._debug(f"done get_part_system_cost rows={len(rows)} elapsed={round(time.time()-started,2)}s")
        except Exception:
            self._debug("failed get_part_system_cost -> returning []")
            return []
        return rows

