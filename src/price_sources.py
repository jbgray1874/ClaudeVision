from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import config
from source_connectors import AccessPriceConnector, SpreadsheetPriceConnector, SqlServerPriceConnector, WebPriceConnector

_DEFAULT_CONNECTORS: Optional[Dict[str, Any]] = None


@dataclass
class PriceRequest:
    kind: str
    material: Optional[str] = None
    thickness_mm: Optional[float] = None
    quantity: Optional[int] = None
    operation: Optional[str] = None
    part_code: Optional[str] = None
    description: Optional[str] = None
    finish: Optional[str] = None
    colour: Optional[str] = None


@dataclass
class PriceCandidate:
    source: str
    kind: str
    price: Optional[float]
    currency: str
    unit: str
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


def _candidate_from_row(row: Dict[str, Any]) -> PriceCandidate:
    metadata = {
        key: value
        for key, value in row.items()
        if key not in {"source", "kind", "price", "currency", "unit", "confidence", "evidence"}
    }
    return PriceCandidate(
        source=row.get("source", "unknown"),
        kind=row.get("kind", "unknown"),
        price=row.get("price"),
        currency=row.get("currency", "GBP"),
        unit=row.get("unit", "unknown"),
        confidence=float(row.get("confidence", 0.0)),
        evidence=row.get("evidence", {}),
        metadata=metadata,
    )


def build_price_connectors(config_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config_map or config.PRICE_SOURCE_CONFIG
    connectors: Dict[str, Any] = {}

    spreadsheet_cfg = cfg.get("spreadsheet", {})
    if spreadsheet_cfg.get("enabled"):
        connectors["spreadsheet"] = SpreadsheetPriceConnector(spreadsheet_cfg.get("template_workbook", ""))

    sqlserver_cfg = cfg.get("sqlserver", {})
    if sqlserver_cfg.get("enabled"):
        connectors["sqlserver"] = SqlServerPriceConnector(
            server=sqlserver_cfg.get("server", ""),
            database=sqlserver_cfg.get("database", ""),
            username=sqlserver_cfg.get("username", ""),
            password=sqlserver_cfg.get("password", ""),
            material_price_query=sqlserver_cfg.get("material_price_query", ""),
            labour_rate_query=sqlserver_cfg.get("labour_rate_query", ""),
            part_system_cost_query=sqlserver_cfg.get("part_system_cost_query", ""),
            driver=sqlserver_cfg.get("driver", "ODBC Driver 18 for SQL Server"),
            encrypt=bool(sqlserver_cfg.get("encrypt", True)),
            trust_server_certificate=bool(sqlserver_cfg.get("trust_server_certificate", True)),
        )

    access_cfg = cfg.get("access", {})
    if access_cfg.get("enabled"):
        connectors["access"] = AccessPriceConnector(
            access_cfg.get("database_path", ""),
            access_cfg.get("material_price_query", ""),
        )

    web_cfg = cfg.get("web", {})
    if web_cfg.get("enabled"):
        connectors["web"] = WebPriceConnector(
            web_cfg.get("sources", []),
            user_agent=web_cfg.get("user_agent", "CodexPriceCollector/1.0"),
        )

    return connectors


def _get_default_connectors() -> Dict[str, Any]:
    global _DEFAULT_CONNECTORS
    if _DEFAULT_CONNECTORS is None:
        _DEFAULT_CONNECTORS = build_price_connectors()
    return _DEFAULT_CONNECTORS


def _fetch_candidates_from_connector(connector: Any, request: PriceRequest) -> List[PriceCandidate]:
    rows: List[Dict[str, Any]] = []
    if request.kind == "material_price" and hasattr(connector, "get_material_price"):
        rows = connector.get_material_price(request.material or "", request.thickness_mm, request.quantity)
    elif request.kind == "labour_rate" and hasattr(connector, "get_labour_rate"):
        rows = connector.get_labour_rate(request.operation or "")
    elif request.kind == "part_system_cost" and hasattr(connector, "get_part_system_cost"):
        rows = connector.get_part_system_cost(request.part_code or "", request.description or "")

    return [_candidate_from_row(row) for row in rows]


def get_best_price(request: PriceRequest, connectors: Optional[Dict[str, Any]] = None, source_priority: Optional[List[str]] = None) -> Dict[str, Any]:
    resolved_connectors = connectors or _get_default_connectors()
    priority = source_priority or config.PRICE_SOURCE_PRIORITY

    candidates: List[PriceCandidate] = []
    audit_trail: List[Dict[str, Any]] = []

    for source_name in priority:
        connector = resolved_connectors.get(source_name)
        if connector is None:
            audit_trail.append({"source": source_name, "status": "skipped", "reason": "connector_not_configured"})
            continue
        if hasattr(connector, "is_available") and not connector.is_available():
            audit_trail.append({"source": source_name, "status": "skipped", "reason": "connector_unavailable"})
            continue

        source_candidates = _fetch_candidates_from_connector(connector, request)
        audit_trail.append(
            {
                "source": source_name,
                "status": "queried",
                "candidate_count": len(source_candidates),
            }
        )
        candidates.extend(source_candidates)

        usable = [candidate for candidate in source_candidates if candidate.price is not None]
        if usable:
            best_usable = max(usable, key=lambda candidate: candidate.confidence)
            return {
                "request": request.__dict__,
                "selected": best_usable.__dict__,
                "candidates": [candidate.__dict__ for candidate in candidates],
                "audit_trail": audit_trail,
            }

    best_fallback = max(candidates, key=lambda candidate: candidate.confidence).__dict__ if candidates else None
    return {
        "request": request.__dict__,
        "selected": best_fallback,
        "candidates": [candidate.__dict__ for candidate in candidates],
        "audit_trail": audit_trail,
    }
