from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import config
from source_connectors import AccessPriceConnector, SpreadsheetPriceConnector, WebPriceConnector


@dataclass
class PriceRequest:
    kind: str
    material: Optional[str] = None
    thickness_mm: Optional[float] = None
    quantity: Optional[int] = None
    operation: Optional[str] = None
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


def _fetch_candidates_from_connector(connector: Any, request: PriceRequest) -> List[PriceCandidate]:
    rows: List[Dict[str, Any]] = []
    if request.kind == "material_price" and hasattr(connector, "get_material_price"):
        rows = connector.get_material_price(request.material or "", request.thickness_mm, request.quantity)
    elif request.kind == "labour_rate" and hasattr(connector, "get_labour_rate"):
        rows = connector.get_labour_rate(request.operation or "")

    return [_candidate_from_row(row) for row in rows]


def get_best_price(request: PriceRequest, connectors: Optional[Dict[str, Any]] = None, source_priority: Optional[List[str]] = None) -> Dict[str, Any]:
    resolved_connectors = connectors or build_price_connectors()
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
