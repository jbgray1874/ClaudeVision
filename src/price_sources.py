from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import os
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
    part_confidence_overall: Optional[float] = None
    part_geometry_reliability: Optional[float] = None
    # If set, only these connector names are queried (e.g. ("web",) for an explicit web-only pass).
    sources_only: Optional[tuple] = None


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


def _parse_price_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # accept YYYY-MM-DD and ISO-like datetime values.
    text = text.replace("T", " ")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None


def _freshness_bucket(candidate: PriceCandidate, rules: Dict[str, Any]) -> str:
    evidence = candidate.evidence or {}
    metadata = candidate.metadata or {}
    raw_price_date = metadata.get("price_date") or evidence.get("price_date")
    dt = _parse_price_date(raw_price_date)
    candidate.evidence = {
        **evidence,
        "price_date_raw": raw_price_date,
        "price_date_parsed": dt.isoformat() if dt else "unparseable",
    }
    if dt is None:
        return "unknown"
    age_days = max(0, (date.today() - dt).days)
    fresh_days = int(rules.get("default_days_fresh", 30))
    stale_days = int(rules.get("default_days_stale", 120))
    if age_days <= fresh_days:
        return "fresh"
    if age_days <= stale_days:
        return "stale"
    return "unknown"


def _candidate_rank_tuple(candidate: PriceCandidate, rules: Dict[str, Any]) -> tuple:
    """Rank a price candidate. Lower is better, and the order must be TOTAL.

    THE BUG THIS CLOSES. The tuple was (-priority, penalty, -confidence), and
    `sorted(usable, ...)[0]` took the winner. Two catalogue rows for the same part code tie
    on all three, so the choice fell through to Python's stable sort — which preserves the
    order the connector returned, and a SQL query with no ORDER BY does not promise one.

    Job 12120 priced three times on identical inputs: GBP 27.67, GBP 29.39, GBP 32.86. The
    knurled knob went 1.45 -> 1.90 -> 1.45, coming BACK — not a catalogue being updated, the
    same two rows being chosen between. Labour was identical to the penny every run.

    A deterministic tail makes the same candidate set always yield the same answer: cheapest
    first (an estimator can defend the lower of two catalogue rows far more easily than a
    number that moves), then source name, then a stable digest of the row's own fields. None
    of it is meaningful ordering — it exists so the result cannot depend on row order.
    """
    pri = (rules.get("source_priority") or {}).get(candidate.source, 10)
    bucket = _freshness_bucket(candidate, rules)
    penalty = float((rules.get("freshness_penalty") or {}).get(bucket, 20.0))
    return (-pri, penalty, -float(candidate.confidence or 0.0),
            float(candidate.price if candidate.price is not None else float("inf")),
            str(candidate.source or ""), _candidate_digest(candidate))


def _candidate_digest(candidate: PriceCandidate) -> str:
    """A stable fingerprint of one candidate row, so two rows that are otherwise identical
    in rank still order deterministically between runs."""
    import hashlib
    try:
        basis = repr(sorted((str(k), str(v)) for k, v in
                            (candidate.metadata or {}).items()))
    except Exception:
        basis = ""
    return hashlib.sha1((f"{candidate.source}|{candidate.kind}|{candidate.price}|"
                         f"{candidate.unit}|{basis}").encode("utf-8")).hexdigest()[:12]


def _price_disagreement(usable: List[PriceCandidate]) -> Optional[Dict[str, Any]]:
    """Do the usable candidates agree on what this part costs?

    Determinism alone is not correctness. If the catalogue holds THUM620 at both GBP 1.16 and
    GBP 1.32, picking the same one every time is repeatable and still hides a data problem
    that belongs in front of a person. Reported so an estimator sees the spread rather than
    only the survivor.
    """
    prices = [c.price for c in usable if c.price is not None]
    if len(prices) < 2:
        return None
    lo, hi = min(prices), max(prices)
    if hi <= 0 or (hi - lo) <= max(0.005, 0.005 * hi):
        return None
    return {
        "low_gbp": round(lo, 4), "high_gbp": round(hi, 4),
        "spread_pct": round((hi - lo) / hi * 100.0, 2),
        "candidate_count": len(prices),
        "sources": sorted({str(c.source) for c in usable if c.price is not None}),
    }


def build_price_connectors(config_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # SDI_OFFLINE: BUILD NOTHING THAT CAN DIAL OUT.
    #
    # This is the third and widest outbound path from costing, after the PricingService
    # singleton and the xAI lookup. It constructs a SQL Server connector, an MS Access
    # connector that opens a file on \\sdi-dc01\shareddata$, and a web connector -- and
    # estimate_part reaches it through _resolve_part_system_cost on every part it prices.
    # A share that is mounted but slow blocks with no timeout, which is what stopped the
    # rules suite dead on the estimating machine while finishing in seconds anywhere the
    # network was absent.
    #
    # Returning no connectors rather than a stub price: get_best_price then records
    # "connector_not_configured" against every source in its audit trail and returns its own
    # no-result. Nothing is invented, and the reason an offline run found no price is
    # written down instead of looking like a price that does not exist.
    if os.environ.get("SDI_OFFLINE"):
        return {}
    cfg = config_map or config.PRICE_SOURCE_CONFIG
    connectors: Dict[str, Any] = {}

    udef_cfg = cfg.get("udef_sqlserver", {})
    if udef_cfg.get("enabled"):
        connectors["udef_sqlserver"] = SqlServerPriceConnector(
            server=udef_cfg.get("server", ""),
            database=udef_cfg.get("database", ""),
            username=udef_cfg.get("username", ""),
            password=udef_cfg.get("password", ""),
            material_price_query=udef_cfg.get("material_price_query", ""),
            labour_rate_query=udef_cfg.get("labour_rate_query", ""),
            part_system_cost_query=udef_cfg.get("part_system_cost_query", ""),
            part_system_cost_query_by_code=udef_cfg.get("part_system_cost_query_by_code", ""),
            driver=udef_cfg.get("driver", "ODBC Driver 18 for SQL Server"),
            encrypt=bool(udef_cfg.get("encrypt", True)),
            trust_server_certificate=bool(udef_cfg.get("trust_server_certificate", True)),
            source_name="udef_sqlserver",
        )

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
            part_system_cost_query_by_code=sqlserver_cfg.get("part_system_cost_query_by_code", ""),
            driver=sqlserver_cfg.get("driver", "ODBC Driver 18 for SQL Server"),
            encrypt=bool(sqlserver_cfg.get("encrypt", True)),
            trust_server_certificate=bool(sqlserver_cfg.get("trust_server_certificate", True)),
            source_name="sqlserver",
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


def reset_connectors() -> None:
    global _DEFAULT_CONNECTORS
    _DEFAULT_CONNECTORS = None


def _validate_priority_entries(connectors: Dict[str, Any], priority: List[str]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for source_name in priority:
        if source_name not in connectors:
            issues.append(
                {
                    "source": source_name,
                    "status": "warning",
                    "reason": "priority_source_missing_connector",
                }
            )
    return issues


def _fetch_candidates_from_connector(connector: Any, request: PriceRequest) -> List[PriceCandidate]:
    rows: List[Dict[str, Any]] = []
    if request.kind == "material_price" and hasattr(connector, "get_material_price"):
        gm = getattr(connector, "get_material_price")

        def _try_material(key: str) -> List[Dict[str, Any]]:
            try:
                return gm(key, request.thickness_mm, request.quantity, request.description or "") or []
            except TypeError:
                return gm(key, request.thickness_mm, request.quantity) or []

        # ── Fix 1: VENEERED MDF (and similar finish+material combos) ──────────
        # finish="VENEERED" + material="MDF" → try "VENEERED MDF" first so the
        # £32/m² catalog entry is matched instead of plain MDF £8.50/m².
        if request.finish:
            combined = f"{request.finish.strip().upper()} {(request.material or '').strip().upper()}"
            rows = _try_material(combined)
            if rows:
                return [_candidate_from_row(row) for row in rows]

        # ── Fix 2: WSF45 and catalog-code hints in description ────────────────
        # normalized_material="TIMBER" won't match catalog entry "WSF45 £9.50/each".
        # Scan description for catalog-code tokens (2-4 uppercase letters + 2-4 digits,
        # e.g. WSF45, MDF18, HIA3) and try each before the generic material fallback.
        if request.description:
            import re as _re
            catalog_tokens = _re.findall(
                r'\b([A-Z]{2,5}\d{2,5}(?:[A-Z]{1,3})?)\b',
                request.description.upper(),
            )
            for token in dict.fromkeys(catalog_tokens):   # deduplicate, preserve order
                rows = _try_material(token)
                if rows:
                    return [_candidate_from_row(row) for row in rows]

        # ── Standard material lookup (original behaviour) ─────────────────────
        rows = _try_material(request.material or "")

    elif request.kind == "labour_rate" and hasattr(connector, "get_labour_rate"):
        rows = connector.get_labour_rate(request.operation or "")
    elif request.kind == "part_system_cost" and hasattr(connector, "get_part_system_cost"):
        rows = connector.get_part_system_cost(request.part_code or "", request.description or "")

    return [_candidate_from_row(row) for row in rows]


def get_best_price(request: PriceRequest, connectors: Optional[Dict[str, Any]] = None, source_priority: Optional[List[str]] = None) -> Dict[str, Any]:
    resolved_connectors = connectors or _get_default_connectors()
    priority = list(source_priority or config.PRICE_SOURCE_PRIORITY)
    if getattr(request, "sources_only", None):
        allow = {str(x).strip() for x in (request.sources_only or ()) if str(x).strip()}
        priority = [name for name in priority if name in allow]

    candidates: List[PriceCandidate] = []
    audit_trail: List[Dict[str, Any]] = _validate_priority_entries(resolved_connectors, priority)

    for source_name in priority:
        connector = resolved_connectors.get(source_name)
        if connector is None:
            audit_trail.append({"source": source_name, "status": "skipped", "reason": "connector_not_configured"})
            continue
        if hasattr(connector, "is_available") and not connector.is_available():
            audit_trail.append({"source": source_name, "status": "skipped", "reason": "connector_unavailable"})
            continue

        # ONE PRICE SOURCE FAILING MUST NOT END THE ESTIMATE.
        #
        # A connector that cannot answer is a source with no candidates -- the waterfall
        # exists precisely so the next one is asked. It was not written that way: an
        # exception here propagated out of estimate_material, out of estimate_part, out of
        # estimate_document and killed main.py. Job 11650's side panels died mid-run
        # because Excel returned RPC_E_CALL_REJECTED ("call was rejected by callee") when
        # the spreadsheet connector tried to open the price template -- Excel was busy, or
        # the shell was elevated and Excel was not. No estimate, no workbook, no partial
        # answer, over a price lookup that has three fallbacks behind it.
        #
        # Recorded as a FAILED source rather than a quiet skip: a source that errored and
        # one that had nothing to say are different facts, and the audit trail is where an
        # estimator finds out which prices were never even asked for.
        try:
            source_candidates = _fetch_candidates_from_connector(connector, request)
            _status, _reason = "queried", None
        except Exception as _e_conn:                                # noqa: BLE001
            source_candidates = []
            _status, _reason = "failed", f"{type(_e_conn).__name__}: {_e_conn}"
            print(f"   [price] {source_name} could not be queried ({_reason}) -- "
                  f"falling through to the next source", flush=True)
        audit_trail.append(
            {
                "source": source_name,
                "status": _status,
                "candidate_count": len(source_candidates),
                **({"reason": _reason} if _reason else {}),
            }
        )
        candidates.extend(source_candidates)

        usable = [candidate for candidate in source_candidates if candidate.price is not None]
        if usable:
            rules = config.PRICE_FRESHNESS_RULES or {}
            best_usable = sorted(usable, key=lambda c: _candidate_rank_tuple(c, rules))[0]
            _dis = _price_disagreement(usable)
            return {
                "request": request.__dict__,
                "selected": best_usable.__dict__,
                "candidates": [candidate.__dict__ for candidate in candidates],
                "audit_trail": audit_trail,
                # PROVENANCE. Which source answered, and whether the answers agreed. Without
                # this a price that moves between runs is invisible: every run is internally
                # consistent and the number is simply different.
                "provenance": {
                    "source": best_usable.source,
                    "price_gbp": best_usable.price,
                    "considered": len(usable),
                    "disagreement": _dis,
                },
            }

    best_fallback = max(candidates, key=lambda candidate: candidate.confidence).__dict__ if candidates else None
    return {
        "request": request.__dict__,
        "selected": best_fallback,
        "candidates": [candidate.__dict__ for candidate in candidates],
        "audit_trail": audit_trail,
    }
