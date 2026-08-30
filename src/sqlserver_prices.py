import os
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from extractor_patterns import canonical_material, normalize_text

try:
    import pyodbc  # type: ignore
except ImportError:  # pragma: no cover
    pyodbc = None


class SqlServerPriceConnector:
    source_name = "sqlserver"
    _pool: "Dict[str, Any]" = {}  # class-level connection pool, keyed by conn string

    def __init__(
        self,
        server: str,
        database: str,
        username: str,
        password: str,
        material_price_query: str = "",
        labour_rate_query: str = "",
        part_system_cost_query: str = "",
        part_system_cost_query_by_code: str = "",
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
        self.part_system_cost_query_by_code = part_system_cost_query_by_code
        self.driver = driver
        self.encrypt = encrypt
        self.trust_server_certificate = trust_server_certificate
        self.source_name = source_name
        # THE SAME PART, ASKED TWICE, THREE SECONDS EACH.
        #
        # 10575-02 costs 25 parts and the log shows every one of them queried TWICE, back to
        # back, same code, same description, same empty answer:
        #
        #   get_part_system_cost part_code=10575-01-001 -> rows=0 elapsed=3.4s
        #   get_part_system_cost part_code=10575-01-001 -> rows=0 elapsed=3.41s
        #
        # That is ~170 seconds of a ~10 minute run spent asking a question that has already
        # been answered. Held per INSTANCE, so it lives exactly as long as one run of the
        # engine and cannot carry a stale price between jobs -- prices move, and a cache that
        # outlived a run would be a quiet way to quote yesterday's.
        #
        # A MISS IS CACHED TOO, deliberately. Misses are the expensive case here: a fabricated
        # part is not in the purchased-parts catalogue and never will be, so every one of them
        # scans the table and returns nothing, twice. Caching only hits would leave the whole
        # cost exactly where it is.
        self._part_cost_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    def is_available(self) -> bool:
        return bool(
            pyodbc is not None
            and self.server
            and self.database
            and self.username
            and self.password
        )

    def _conn_str(self) -> str:
        encrypt = "yes" if self.encrypt else "no"
        trust = "yes" if self.trust_server_certificate else "no"
        return (
            f"DRIVER={{{self.driver}}};"
            f"SERVER={self.server};"
            f"DATABASE={self.database};"
            f"UID={self.username};"
            f"PWD={self.password};"
            f"Encrypt={encrypt};"
            f"TrustServerCertificate={trust};"
        )

    def _connect(self):
        """Return a persistent pooled connection — connect once per process."""
        key = f"{self.server}|{self.database}|{self.username}"
        conn = SqlServerPriceConnector._pool.get(key)
        # Test if existing connection is still alive
        if conn is not None:
            try:
                conn.cursor().execute("SELECT 1")
            except Exception:
                conn = None
                SqlServerPriceConnector._pool.pop(key, None)
        if conn is None:
            conn = pyodbc.connect(self._conn_str(), timeout=10)
            conn.autocommit = True
            SqlServerPriceConnector._pool[key] = conn
            if os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}:
                print(f"[DEBUG] sqlserver_prices new connection to {self.server}/{self.database}")
        return conn

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
            connection = self._connect()
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
            connection = self._connect()
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
        # KEYED ON WHAT THE QUERY ACTUALLY USES — the normalised code and description, not the
        # raw arguments. Two callers passing "10575-01-001" and " 10575-01-001 " ask the
        # database the identical question and must not miss each other in here.
        _ck = (part_code_norm, desc_norm)
        if _ck in self._part_cost_cache:
            self._debug(f"cached get_part_system_cost part_code={part_code_norm} "
                        f"rows={len(self._part_cost_cache[_ck])}")
            # A COPY. The caller is handed a list of dicts it may well annotate — a source
            # name, a confidence, a note — and handing out the cached objects themselves would
            # let the first caller's edits appear in the second caller's answer.
            return [dict(r) for r in self._part_cost_cache[_ck]]
        rows: List[Dict[str, Any]] = []
        try:
            started = time.time()
            self._debug(f"start get_part_system_cost part_code={part_code_norm} desc_len={len(desc_norm)}")
            connection = self._connect()
            cursor = connection.cursor()
            # Fast path: exact part-code seek (sargable, ~ms) BEFORE the description
            # LIKE '%...%' scan. A code match already outranks a description match in
            # the full query, so when this hits, the result is identical — it just
            # avoids the 91k-row table scan (which was costing ~5.7s per part).
            db_rows: List[Dict[str, Any]] = []
            if part_code_norm and self.part_system_cost_query_by_code:
                self._execute_query(
                    cursor,
                    self.part_system_cost_query_by_code,
                    [part_code_norm, part_code_norm, part_code_norm],
                )
                db_rows = self._rows_to_dicts(cursor)
                if db_rows:
                    self._debug(
                        f"code-seek hit part_code={part_code_norm} elapsed={round(time.time()-started,2)}s"
                    )
            # Fallback: description LIKE '%...%' scan. This is a leading-wildcard
            # scan of the whole 91k-row purchased-parts table (~11s each) and it
            # fires on every code-miss — i.e. every fabricated part, which are not
            # in the purchased-parts catalogue, so it just burns seconds returning
            # nothing. Real catalogue/bought-in parts are already found by exact
            # code above. OFF by default; enable with SDI_ENABLE_PART_DESC_SCAN=1
            # only when you specifically want description cross-matching.
            if not db_rows:
                if os.getenv("SDI_ENABLE_PART_DESC_SCAN", "").lower() in {"1", "true", "yes"}:
                    params = [part_code_norm, desc_norm, part_code_norm, desc_norm, part_code_norm]
                    self._execute_query(cursor, self.part_system_cost_query, params)
                    db_rows = self._rows_to_dicts(cursor)
                else:
                    self._debug(
                        f"code-seek miss part_code={part_code_norm} -> description scan skipped "
                        f"(set SDI_ENABLE_PART_DESC_SCAN=1 to enable)"
                    )
            for row in db_rows:
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
            # NOT CACHED. A dropped connection or a timeout is not the answer "this part is not
            # in the catalogue" — it is no answer at all. Storing it would turn one blip into a
            # whole run priced as though the part had been looked up and found missing, which
            # is indistinguishable in the output from a part that genuinely is not there.
            self._debug("failed get_part_system_cost -> returning [] (not cached)")
            return []
        self._part_cost_cache[_ck] = [dict(r) for r in rows]
        return rows

