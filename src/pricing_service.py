from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import config
from estimator import estimate_document
from json_normaliser import normalise_json

try:
    import pyodbc  # type: ignore
except ImportError:  # pragma: no cover
    pyodbc = None


class PricingService:
    """Workbook-first pricing engine with joined source provenance."""

    def __init__(self, conn: Any = None, connection_factory: Optional[Callable[[], Any]] = None) -> None:
        self._connection_factory = connection_factory or self._get_db_connection
        self.conn = conn or self._connection_factory()

    def __enter__(self) -> "PricingService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass

    def _get_db_connection(self):
        if pyodbc is None:
            raise RuntimeError("pyodbc is required for PricingService")
        c = config.PRICE_SOURCE_CONFIG.get("sqlserver", {})
        conn_str = (
            f"DRIVER={{{c.get('driver', 'ODBC Driver 18 for SQL Server')}}};"
            f"SERVER={c.get('server')};DATABASE={c.get('database')};"
            f"UID={c.get('username')};PWD={c.get('password')};"
            "Encrypt=yes;TrustServerCertificate=yes;"
        )
        return pyodbc.connect(conn_str, timeout=30)

    def _is_connection_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        tokens = ("connection", "closed", "08s01", "08003", "communication link failure")
        return any(token in message for token in tokens)

    def _fetch_one_with_retry(self, query: str, params: List[Any]) -> Any:
        for attempt in range(2):
            cursor = None
            try:
                cursor = self.conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchone()
            except Exception as exc:
                if attempt == 0 and self._is_connection_error(exc):
                    self.conn = self._connection_factory()
                    continue
                raise
            finally:
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception:
                        pass
        return None

    def _fetch_all_with_retry(self, query: str, params: List[Any]) -> List[Any]:
        for attempt in range(2):
            cursor = None
            try:
                cursor = self.conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
            except Exception as exc:
                if attempt == 0 and self._is_connection_error(exc):
                    self.conn = self._connection_factory()
                    continue
                raise
            finally:
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception:
                        pass
        return []

    def _freshness_adjustment(self, raw_date: Any) -> Dict[str, Any]:
        if raw_date is None:
            return {"bucket": "unknown", "age_days": None, "penalty": 0.15}
        parsed = None
        text = str(raw_date).strip().replace("T", " ")
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return {"bucket": "unknown", "age_days": None, "penalty": 0.15}
        age_days = max(0, (datetime.now(timezone.utc).date() - parsed.date()).days)
        if age_days <= 30:
            return {"bucket": "fresh", "age_days": age_days, "penalty": 0.0}
        if age_days <= 120:
            return {"bucket": "stale", "age_days": age_days, "penalty": 0.08}
        return {"bucket": "old", "age_days": age_days, "penalty": 0.2}

    def _get_udef_anchor(self, part: Dict[str, Any]) -> Dict[str, Any] | None:
        """
        UDEF anchor: must match SDILive column names on UDEF_PARTS_TABLE_FOR_ESTIMATING.
        Uses the same shape as PRICE_SOURCE_CONFIG['sqlserver']['part_system_cost_query']:
        [Part ref], [Description], [System cost per], SUP_TBL join.
        If your database exposes a price-effective date column, add it to the SELECT list
        as a 5th column and pass it to _freshness_adjustment().
        """
        part_code = str(part.get("part_number") or "").strip()
        desc = str(part.get("description") or "").strip()
        if not part_code and len(desc) < 8:
            return None

        row = self._fetch_one_with_retry(
            """
            SELECT TOP 1
                u.[Part ref],
                u.[Description],
                ISNULL(s.[SUP_NAME], CAST(u.[Cus code] AS nvarchar(200))),
                CAST(u.[System cost per] AS decimal(18,4))
            FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
            LEFT JOIN dbo.SUP_TBL s
                ON s.[SUP_CODE] = u.[Cus code]
            WHERE
                UPPER(LTRIM(RTRIM(u.[Part ref]))) = UPPER(LTRIM(RTRIM(?)))
                OR (
                    LEN(LTRIM(RTRIM(?))) >= 8
                    AND UPPER(u.[Description]) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%'
                )
            ORDER BY
                CASE WHEN UPPER(LTRIM(RTRIM(u.[Part ref]))) = UPPER(LTRIM(RTRIM(?))) THEN 0 ELSE 1 END,
                u.[System cost per] DESC
            """,
            [part_code, desc, desc, part_code],
        )
        if not row:
            return None

        price = float(row[3] or 0.0)
        if price <= 0:
            return None
        matched_code = str(row[0] or "").strip().upper()
        part_code_upper = part_code.strip().upper()
        base_confidence = 0.95 if part_code_upper and part_code_upper == matched_code else 0.82
        # No standard effective-date column in the live UDEF query path; treat as unknown freshness.
        freshness = self._freshness_adjustment(None)
        return {
            "source": "UDEF_PARTS_TABLE_FOR_ESTIMATING",
            "unit_price_gbp": price,
            "provenance": f"UDEF match on {row[0]} ({row[1]}) supplier={row[2]}",
            "confidence": max(0.3, round(base_confidence - freshness["penalty"], 2)),
            "effective_date": None,
            "supplier_name": row[2] or "Unknown",
            "freshness": freshness,
        }

    def _get_historical_rag(self, part: Dict[str, Any]) -> Dict[str, Any] | None:
        desc = str(part.get("description") or "").strip().lower()
        if not desc:
            return None
        row = self._fetch_one_with_retry(
            """
            SELECT TOP 1 line_description, unit_price_gbp, line_total_gbp
            FROM dbo.historical_quote_material_line
            WHERE line_description LIKE ?
            ORDER BY COALESCE(line_total_gbp, 0) DESC
            """,
            [f"%{desc}%"],
        )
        if not row or row[1] is None:
            return None
        return {
            "source": "historical_quote_material_line",
            "unit_price_gbp": float(row[1]),
            "provenance": f"Historical match: {row[0]}",
            "confidence": 0.75,
        }

    def get_top_historical_matches(self, part: Dict[str, Any], k: int) -> List[Dict[str, Any]]:
        desc = str(part.get("description") or "").strip().lower()
        if not desc:
            return []
        top_k = max(1, min(25, int(k)))
        rows = self._fetch_all_with_retry(
            """
            SELECT TOP (?)
                line_description,
                unit_price_gbp,
                line_total_gbp
            FROM dbo.historical_quote_material_line
            WHERE line_description LIKE ?
              AND unit_price_gbp IS NOT NULL
            ORDER BY COALESCE(line_total_gbp, 0) DESC
            """,
            [top_k, f"%{desc}%"],
        )
        matches: List[Dict[str, Any]] = []
        for row in rows:
            matches.append(
                {
                    "line_description": row[0],
                    "unit_price_gbp": float(row[1]),
                    "line_total_gbp": float(row[2] or 0.0),
                    "confidence": 0.65,
                    "source": "historical_quote_material_line",
                }
            )
        return matches

    def _get_supplier_catalog(self, part: Dict[str, Any]) -> Dict[str, Any] | None:
        material_hint = str(part.get("normalized_material") or "").strip().lower()
        if not material_hint:
            return None
        row = self._fetch_one_with_retry(
            """
            SELECT TOP 1 catalog_url, material_hint, unit_price_gbp
            FROM dbo.estimating_supplier_catalog_url
            WHERE material_hint LIKE ?
            ORDER BY sort_order ASC
            """,
            [f"%{material_hint}%"],
        )
        if not row or row[2] is None:
            return None
        return {
            "source": "estimating_supplier_catalog_url",
            "unit_price_gbp": float(row[2]),
            "provenance": f"Catalog: {row[1]} ({row[0]})",
            "confidence": 0.65,
        }

    def _select_anchor_price_source(self, part: Dict[str, Any]) -> Dict[str, Any]:
        return (
            self._get_udef_anchor(part)
            or self._get_historical_rag(part)
            or self._get_supplier_catalog(part)
            or {
                "source": "fallback",
                "unit_price_gbp": 0.0,
                "confidence": 0.3,
                "provenance": "No price source found",
            }
        )

    def _resolve_effective_material_cost(
        self,
        part: Dict[str, Any],
        quantity: int,
        workbook_material_cost_gbp: float,
        anchor_price_source: Dict[str, Any],
    ) -> Dict[str, Any]:
        confidence = float(anchor_price_source.get("confidence", 0.0) or 0.0)
        unit_price = float(anchor_price_source.get("unit_price_gbp", 0.0) or 0.0)
        weight_kg = float((part.get("normalized_geometry") or {}).get("weight_kg") or 0.0)
        policy = getattr(config, "PRICING_SERVICE_POLICY", {}) or {}
        anchor_threshold = float(
            policy.get("anchor_override_min_confidence", 0.90)
        )
        scrap_factor = float(policy.get("anchor_override_scrap_factor", 1.04))

        if confidence >= anchor_threshold and unit_price > 0.0 and weight_kg > 0.0:
            anchor_material_cost = weight_kg * unit_price * quantity * scrap_factor
            return {
                "material_cost_gbp": float(anchor_material_cost),
                "material_pricing_mode": "anchor_override",
                "anchor_applied": True,
                "anchor_threshold": anchor_threshold,
                "anchor_inputs": {
                    "confidence": confidence,
                    "unit_price_gbp": unit_price,
                    "weight_kg": weight_kg,
                    "scrap_factor": scrap_factor,
                },
            }

        return {
            "material_cost_gbp": float(workbook_material_cost_gbp),
            "material_pricing_mode": "workbook_primary",
            "anchor_applied": False,
            "anchor_threshold": anchor_threshold,
            "anchor_inputs": {
                "confidence": confidence,
                "unit_price_gbp": unit_price,
                "weight_kg": weight_kg,
                "scrap_factor": scrap_factor,
            },
        }

    def calculate_estimate(
        self,
        drawing_json: Dict[str, Any],
        historical_top_k: int = 5,
        save_to_db: bool = True,
    ) -> Dict[str, Any]:
        drawing_json = normalise_json(drawing_json)
        parts = drawing_json.get("manufacturing_writeup", {}).get("parts") or drawing_json.get("parts", [])
        workbook_estimate = estimate_document(parts)
        part_estimates = workbook_estimate.get("part_estimates", [])
        estimate_lookup = {
            str(item.get("part_number") or ""): item for item in part_estimates if item.get("part_number")
        }
        priced_parts: List[Dict[str, Any]] = []

        for part in parts:
            part_number = str(part.get("part_number") or "")
            qty = max(1, int(round(float(part.get("quantity", 1) or 1))))
            wb = estimate_lookup.get(part_number, {})
            historical_matches = self.get_top_historical_matches(part, k=historical_top_k)
            anchor_price_source = self._select_anchor_price_source(part)
            wb_breakdown = wb.get("cost_breakdown", {})
            wb_material = wb_breakdown.get("material", {})
            wb_labour = wb_breakdown.get("labour", {})
            workbook_unit_total_cost = float(wb.get("unit_total_cost_gbp") or 0.0)
            workbook_extended_total_cost = float(wb.get("extended_total_cost_gbp") or 0.0)
            workbook_material_cost = float(wb_material.get("extended_material_cost_gbp") or 0.0)
            labour_cost = float(wb_labour.get("total_labour_cost_gbp") or 0.0)
            effective_material = self._resolve_effective_material_cost(
                part=part,
                quantity=qty,
                workbook_material_cost_gbp=workbook_material_cost,
                anchor_price_source=anchor_price_source,
            )
            material_cost = float(effective_material["material_cost_gbp"])
            computed_extended_total_cost = material_cost + labour_cost
            unit_total_cost = computed_extended_total_cost / qty if qty else 0.0

            pricing_basis = wb_breakdown.get("costing_basis")
            if str(pricing_basis or "").startswith("system_cost_per_part"):
                computed_extended_total_cost = workbook_extended_total_cost
                unit_total_cost = workbook_unit_total_cost

            priced_parts.append(
                {
                    "part_number": part_number,
                    "description": part.get("description"),
                    "quantity": qty,
                    "material_cost_gbp": round(material_cost, 2),
                    "labour_cost_gbp": round(labour_cost, 2),
                    "unit_total_cost_gbp": round(unit_total_cost, 2),
                    "extended_total_cost_gbp": round(computed_extended_total_cost, 2),
                    "pricing_basis": pricing_basis,
                    "price_source": anchor_price_source,
                    "joined_sources": {
                        "reverse_engineered_workbook": {
                            "material": wb_material,
                            "labour": wb_labour,
                            "system_cost": wb_breakdown.get("system_cost", {}),
                            "assumptions": wb_breakdown.get("assumptions", {}),
                        },
                        "anchor_lookup": anchor_price_source,
                        "material_decision": effective_material,
                    },
                    "top_historical_matches": historical_matches,
                }
            )

        workbook_equivalent = workbook_estimate.get("workbook_equivalent_pricing", {})
        material_total = sum(float(item.get("material_cost_gbp") or 0.0) for item in priced_parts)
        labour_total = sum(float(item.get("labour_cost_gbp") or 0.0) for item in priced_parts)
        grand_total_cost = sum(float(item.get("extended_total_cost_gbp") or 0.0) for item in priced_parts)
        workbook_sell_price = float(workbook_equivalent.get("l111_sell_price_gbp") or 0.0)
        sell_price = workbook_sell_price if workbook_sell_price > 0 else grand_total_cost * 1.30
        order_qty = max(1, int(round(float(drawing_json.get("quantity", 1) or 1))))
        run_uuid = drawing_json.get("run_uuid") or str(uuid.uuid4())
        margin_pct = round(((sell_price - grand_total_cost) / sell_price) * 100.0, 1) if sell_price else None

        result = {
            "schema": "priced_estimate.v1",
            "drawing_source": drawing_json.get("source_file", "unknown"),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "run_uuid": run_uuid,
            "parts": priced_parts,
            "summary": {
                "total_material_gbp": round(material_total, 2),
                "total_labour_gbp": round(labour_total, 2),
                "grand_total_cost_gbp": round(grand_total_cost, 2),
                "sell_price_per_unit_gbp": round(sell_price / order_qty, 2) if order_qty else 0.0,
                "total_sell_price_gbp": round(sell_price, 2),
                "margin_pct": margin_pct,
            },
            "workbook_equivalent_pricing": workbook_equivalent,
            "estimate_source_extract": workbook_estimate.get("estimate_source_extract", {}),
            "historical_comparison_projection": workbook_estimate.get("historical_comparison_projection", {}),
            "provenance": "reverse-engineered workbook first, with UDEF/historical/catalog joined as anchors",
        }
        if save_to_db:
            self._save_to_database(result, run_uuid)
        return result

    def _save_to_database(self, priced_result: Dict[str, Any], run_uuid: Optional[str] = None) -> None:
        for attempt in range(2):
            cursor = None
            try:
                cursor = self.conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO dbo.drawing_priced_estimate (run_uuid, priced_json, total_cost_gbp, sell_price_gbp)
                    VALUES (?, ?, ?, ?)
                    """,
                    run_uuid or str(uuid.uuid4()),
                    json.dumps(priced_result, ensure_ascii=False),
                    priced_result["summary"]["grand_total_cost_gbp"],
                    priced_result["summary"]["total_sell_price_gbp"],
                )
                self.conn.commit()
                return
            except Exception as exc:
                if attempt == 0 and self._is_connection_error(exc):
                    self.conn = self._connection_factory()
                    continue
                raise
            finally:
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception:
                        pass


if __name__ == "__main__":
    path = Path(r"C:\ClaudeVision\output\json\YOUR_DRAWING_v4.json")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    with PricingService() as engine:
        result = engine.calculate_estimate(data)
    print(json.dumps(result["summary"], indent=2))
    print("\nSaved to drawing_priced_estimate table")
