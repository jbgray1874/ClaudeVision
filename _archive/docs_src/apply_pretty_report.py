"""Apply v2 pretty report from Downloads (run once)."""
from pathlib import Path

SRC = Path(r"c:\Users\james.gray\Documents\Downloads\estimate_parity_pretty_report (1).py")
DST = Path(__file__).resolve().parent / "estimate_parity_pretty_report.py"

text = SRC.read_text(encoding="utf-8")

OLD_LABELS = '''_SOURCE_LABELS: Dict[str, str] = {
    "udef_sqlserver":  "SDI Internal Catalogue (Access Supply Chain)",
    "sqlserver":       "SQL Server ERP Database",
    "spreadsheet":     "Blank Estimate Spreadsheet",
    "access":          "Access Database",
    "web":             "Web Catalogue Lookup",
    "web_ai_fallback": "AI Market Estimate (internet fallback — needs checking)",
    "config":          "Config Rate Card",
    "unknown":         "Unknown source",
}'''

NEW_LABELS = '''_SOURCE_LABELS: Dict[str, str] = {
    "udef_sqlserver":                  "SDI Internal Catalogue (Access Supply Chain)",
    "udef_parts_table_for_estimating": "SDI UDEF Parts Table (Access Supply Chain)",
    "sqlserver":                       "SQL Server ERP Database",
    "spreadsheet":                     "Blank Estimate Spreadsheet",
    "access":                          "Access Database",
    "bought_in_parts":                 "SDI Bought-In Parts Catalogue",
    "historical_quote_material_line":  "Historical Quote Database (SDI RAG)",
    "estimating_supplier_catalog_url": "Supplier Catalogue (Tier 4)",
    "web":                             "Web Catalogue Lookup",
    "web_catalog":                     "Web Catalogue Lookup",
    "web_search":                      "Web Search (Tier 5)",
    "llm_market_estimate":             "AI Market Estimate (LLM)",
    "web_ai_fallback":                 "AI Market Estimate (internet fallback — needs checking)",
    "fallback":                        "No price source matched",
    "config":                          "Config Rate Card",
    "unknown":                         "Unknown source",
}'''

OLD_ICONS = '''_SOURCE_ICONS: Dict[str, str] = {
    "udef_sqlserver":  "🏭",
    "sqlserver":       "🗄",
    "spreadsheet":     "📊",
    "access":          "🗄",
    "web":             "🌐",
    "web_ai_fallback": "🤖",
    "config":          "⚙",
    "unknown":         "❓",
}'''

NEW_ICONS = '''_SOURCE_ICONS: Dict[str, str] = {
    "udef_sqlserver":                  "🏭",
    "udef_parts_table_for_estimating": "🏭",
    "sqlserver":                       "🗄",
    "spreadsheet":                     "📊",
    "access":                          "🗄",
    "bought_in_parts":                 "📦",
    "historical_quote_material_line":  "📜",
    "estimating_supplier_catalog_url": "🛒",
    "web":                             "🌐",
    "web_catalog":                     "🌐",
    "web_search":                      "🔍",
    "llm_market_estimate":             "🤖",
    "web_ai_fallback":                 "🤖",
    "fallback":                        "❓",
    "config":                          "⚙",
    "unknown":                         "❓",
}'''

text = text.replace(OLD_LABELS, NEW_LABELS).replace(OLD_ICONS, NEW_ICONS)

HELPER = '''

def _normalize_source_key(ps: Dict[str, Any]) -> str:
    if not ps:
        return "config"
    raw = str(ps.get("source") or ps.get("source_type") or ps.get("source_name") or "unknown").lower()
    if str(ps.get("source_type") or "").lower() == "web_ai_fallback" or raw in {
        "web_ai_fallback", "llm_market_estimate", "web_search"
    }:
        return "web_ai_fallback"
    return raw.replace(" ", "_")


def _source_label(key: str) -> str:
    return _SOURCE_LABELS.get(key, key.replace("_", " ").title())


def _source_icon(key: str) -> str:
    return _SOURCE_ICONS.get(key, "❓")


def _collect_report_parts(summary: Dict[str, Any], bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    est = summary.get("estimate_summary") or {}
    if not isinstance(est, dict):
        est = {}
    raw: List[Dict[str, Any]] = []
    for bucket in (
        est.get("part_estimates") or [],
        est.get("parts") or [],
        summary.get("parts") or [],
        bundle.get("priced_parts") or [],
    ):
        for item in bucket:
            if isinstance(item, dict):
                raw.append(item)
    if not raw:
        mfg = summary.get("manufacturing_writeup") or {}
        raw = [p for p in (mfg.get("parts") or []) if isinstance(p, dict)]
    by_pn: Dict[str, Dict[str, Any]] = {}
    for p in raw:
        pn = str(p.get("part_number") or "").strip()
        if not pn:
            continue
        if pn not in by_pn:
            by_pn[pn] = dict(p)
            continue
        prev = by_pn[pn]
        for field in (
            "price_source", "joined_sources", "top_historical_matches",
            "material_cost_gbp", "labour_cost_gbp", "unit_total_cost_gbp",
            "extended_total_cost_gbp", "material_estimate", "labour_estimate",
            "cost_breakdown", "process_estimate", "risk_flags",
        ):
            if p.get(field) not in (None, {}, []):
                prev[field] = p[field]
    return list(by_pn.values())


def _part_material_labour_cost(p: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    cb = p.get("cost_breakdown") or {}
    mat = _safe_float(p.get("material_cost_gbp"))
    if mat is None:
        mat = _safe_float((cb.get("material") or {}).get("extended_material_cost_gbp"))
    if mat is None:
        mat = _safe_float((p.get("material_estimate") or {}).get("extended_material_cost_gbp"))
    lab = _safe_float(p.get("labour_cost_gbp"))
    if lab is None:
        lab = _safe_float((cb.get("labour") or {}).get("total_labour_cost_gbp"))
    if lab is None:
        lab = _safe_float((p.get("labour_estimate") or {}).get("total_labour_cost_gbp"))
    return mat, lab
'''

text = text.replace("def _price_source_badge(ps: Dict[str, Any]) -> str:", HELPER + "def _price_source_badge(ps: Dict[str, Any]) -> str:")

OLD_BADGE = '''def _price_source_badge(ps: Dict[str, Any]) -> str:
    if not ps:
        return "<span class='src-badge src-config'>⚙ Config rate</span>"
    src_type = str(ps.get("source_type") or ps.get("source_name") or "unknown").lower()
    src_name = str(ps.get("source_name") or "unknown").lower()
    key = "web_ai_fallback" if src_type == "web_ai_fallback" else src_name
    label = _SOURCE_LABELS.get(key, key)
    icon = _SOURCE_ICONS.get(key, "❓")'''

NEW_BADGE = '''def _price_source_badge(ps: Dict[str, Any]) -> str:
    if not ps:
        return "<span class='src-badge src-config'>⚙ Config rate</span>"
    key = _normalize_source_key(ps)
    label = _source_label(key)
    icon = _source_icon(key)'''

text = text.replace(OLD_BADGE, NEW_BADGE)

text = text.replace(
    '    parts = est.get("part_estimates") or []\n    mt = lt = 0.0\n    for p in parts:\n        if not isinstance(p, dict):\n            continue\n        me = p.get("material_estimate") or {}\n        le = p.get("labour_estimate") or {}\n        mt += float(me.get("extended_material_cost_gbp") or 0.0)\n        lt += float(le.get("total_labour_cost_gbp") or 0.0)',
    '    parts = est.get("part_estimates") or est.get("parts") or []\n    mt = lt = 0.0\n    for p in parts:\n        if not isinstance(p, dict):\n            continue\n        m, l = _part_material_labour_cost(p)\n        mt += float(m or 0.0)\n        lt += float(l or 0.0)',
)

text = text.replace(
    '''        # Costs
        cb = p.get("cost_breakdown") or {}
        mat_cost = _safe_float((cb.get("material") or {}).get("extended_material_cost_gbp"))
        lab_cost = _safe_float((cb.get("labour") or {}).get("total_labour_cost_gbp"))
        unit_cost = _safe_float(p.get("unit_total_cost_gbp") or cb.get("unit_total_cost_gbp"))
        ext_cost = _safe_float(p.get("extended_total_cost_gbp") or cb.get("extended_total_cost_gbp"))

        # Price source
        me = p.get("material_estimate") or {}
        ps = me.get("price_source") or {}
        src_badge = _price_source_badge(ps)''',
    '''        mat_cost, lab_cost = _part_material_labour_cost(p)
        cb = p.get("cost_breakdown") or {}
        unit_cost = _safe_float(p.get("unit_total_cost_gbp") or cb.get("unit_total_cost_gbp"))
        ext_cost = _safe_float(p.get("extended_total_cost_gbp") or cb.get("extended_total_cost_gbp"))
        me = p.get("material_estimate") or {}
        ps = p.get("price_source") or me.get("price_source") or {}
        src_badge = _price_source_badge(ps)''',
)

text = text.replace(
    '        mat_label = _SOURCE_LABELS.get(src_type if src_type in _SOURCE_LABELS else src_name, src_name)\n        mat_icon = _SOURCE_ICONS.get(src_type if src_type in _SOURCE_ICONS else src_name, "❓")',
    '        prov_key = _normalize_source_key(ps)\n        mat_label = _source_label(prov_key)\n        mat_icon = _source_icon(prov_key)',
)

text = text.replace(
    '    parts = [p for p in (est.get("part_estimates") or est.get("parts") or []) if isinstance(p, dict)]',
    '    parts = _collect_report_parts(summary, bundle)',
)

text = text.replace(
    '        if str(((p.get("material_estimate") or {}).get("price_source") or {}).get("source_type") or "").lower() == "web_ai_fallback"',
    '        ps = p.get("price_source") or (p.get("material_estimate") or {}).get("price_source") or {}\n        if str(ps.get("source_type") or ps.get("source") or "").lower() in {"web_ai_fallback", "web_search", "llm_market_estimate"}',
)

DST.write_text(text, encoding="utf-8")
marker = Path(__file__).resolve().parent / "_pretty_report_deployed.txt"
marker.write_text(f"ok {DST.stat().st_size}\n", encoding="utf-8")
print(f"wrote {DST} ({DST.stat().st_size} bytes)")
