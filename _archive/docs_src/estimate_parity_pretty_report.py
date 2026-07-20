"""
SDI AI Estimating Platform — Parity Report Generator v2
========================================================
Produces a self-contained HTML dashboard comparing AI estimates vs manual workbook.

Designed to be readable by estimators and directors WITHOUT technical knowledge.
Every section has plain-English explanations. Every number shows where it came from.
Price source provenance is shown for every part line.

Usage (same API as original):
    from estimate_parity_pretty_report import generate_pretty_parity_html
    html_written = generate_pretty_parity_html(bundle=bundle, summary=summary_obj, output_path=out_html)
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────── helpers ────────────────────────────────────

def _esc(x: Any) -> str:
    return html.escape(str(x if x is not None else ""), quote=True)


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, str):
            v = x.strip().replace("£", "").replace(",", "")
            return float(v) if v else None
        return float(x)
    except (TypeError, ValueError):
        return None


def _fmt_gbp(v: Optional[float], dash: str = "—") -> str:
    if v is None:
        return dash
    return f"£{v:,.2f}"


def _fmt_pct(v: Optional[float], dash: str = "—") -> str:
    if v is None:
        return dash
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def _fmt_hours(v: Any) -> str:
    f = _safe_float(v)
    if f is None:
        return "—"
    return f"{f:.3f} h"


def _money_totals_from_json(est: Dict[str, Any]) -> Tuple[float, float]:
    cb = est.get("cost_breakdown") or {}
    mat = _safe_float((cb.get("material") or {}).get("total")) or 0.0
    lab = _safe_float((cb.get("labour") or {}).get("total")) or 0.0
    if mat or lab:
        return round(mat, 2), round(lab, 2)
    parts = est.get("part_estimates") or est.get("parts") or []
    mt = lt = 0.0
    for p in parts:
        if not isinstance(p, dict):
            continue
        m, l = _part_material_labour_cost(p)
        mt += float(m or 0.0)
        lt += float(l or 0.0)
    return round(mt, 2), round(lt, 2)


def _is_qty_row(r: Dict[str, Any]) -> bool:
    path = str(r.get("json_path") or "").lower()
    if "assumed_job_quantity" in path:
        return True
    lab = str(r.get("label") or "").lower()
    return "quantity" in lab and ("order" in lab or "reference" in lab or "assembly qty" in lab)


def _money_pair(money: List[Dict[str, Any]], suffix: str) -> Tuple[Optional[float], Optional[float]]:
    for r in money:
        if str(r.get("json_path") or "").endswith(suffix):
            return _safe_float(r.get("json_numeric")), _safe_float(r.get("workbook_cached_numeric"))
    return None, None


def _status_traffic(status: str) -> Tuple[str, str, str]:
    """Returns (bg_class, badge_html, icon)."""
    s = (status or "").lower()
    if s == "match":
        return (
            "bg-emerald-50",
            "<span class='badge badge-match'>✓ Match</span>",
            "✓",
        )
    if s == "warning":
        return (
            "bg-amber-50",
            "<span class='badge badge-warn'>⚠ Review</span>",
            "⚠",
        )
    if s in ("info", "route_only", "no_wb_cost", "blank"):
        return (
            "",
            "<span class='badge' style='background:#e2e8f0;color:#475569;'>○ Route only</span>",
            "○",
        )
    if s == "review":
        return (
            "bg-amber-50",
            "<span class='badge badge-warn'>⚠ Review</span>",
            "⚠",
        )
    return (
        "bg-red-50",
        "<span class='badge badge-fail'>✕ Fail</span>",
        "✕",
    )


# ─────────────────────── price source plain-English ─────────────────────────

_SOURCE_LABELS: Dict[str, str] = {
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
}

_SOURCE_ICONS: Dict[str, str] = {
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
}

_FRESHNESS_LABELS: Dict[str, str] = {
    "fresh":   "✅ Fresh (< 30 days)",
    "stale":   "⚠️ Stale (30–120 days old)",
    "unknown": "❓ Age unknown",
}

_RISK_PLAIN: Dict[str, str] = {
    "web_ai_indicative_material_price":     "Material price came from an AI internet search — not your internal catalogue. It needs to be verified against a real supplier quote before using this estimate.",
    "web_ai_indicative_system_cost":        "The bought-in part cost came from an AI internet search. Verify against Access Supply Chain (UDEF) or a supplier quote.",
    "weld_required":                        "The drawing shows welding is needed. Check the routing includes weld time and the correct weld labour rate.",
    "missing_material_spec":                "No material was identified for this part. The material price is missing and the estimate will be incomplete.",
    "missing_material_thickness":           "Thickness couldn't be read from the drawing. Material weight and cost may be wrong.",
    "missing_material_price":               "Material was identified but no price was found in the SQL database or config. Add it to the rate card.",
    "assembly_only_part_record":            "This part was found only in the assembly BOM — there is no detail drawing for it. Geometry and material are estimated.",
    "section_or_wire_stock_pricing_review": "This looks like tube, angle or channel section stock. Check the price per metre and kg/m figure used.",
    "low_part_confidence":                  "The AI had low confidence extracting data from this drawing page. Results may be incomplete.",
    "low_geometry_reliability_with_powder": "Geometry reliability was low on a part that needs powder coating. Surface area and P/C cost may be wrong.",
}


def _explain_risk(flag: str) -> str:
    for key, msg in _RISK_PLAIN.items():
        if flag == key or flag.startswith(key):
            return msg
    if flag.startswith("missing_labour_rate:"):
        op = flag.split(":", 1)[1] if ":" in flag else flag
        return f"The labour rate for '{op}' wasn't found in the SQL database. Add it to the labour_rates table or config."
    return "Review this flag against the drawing and the manual estimate."




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


def _price_source_badge(ps: Dict[str, Any]) -> str:
    if not ps:
        return "<span class='src-badge src-config'>⚙ Config rate</span>"
    key = _normalize_source_key(ps)
    label = _source_label(key)
    icon = _source_icon(key)
    css = {
        "udef_sqlserver":                  "src-udef",
        "udef_parts_table_for_estimating": "src-udef",
        "sqlserver":                       "src-sql",
        "spreadsheet":                     "src-sheet",
        "bought_in_parts":                 "src-bought",
        "historical_quote_material_line":  "src-historic",
        "estimating_supplier_catalog_url": "src-catalog",
        "web":                             "src-web",
        "web_catalog":                     "src-web",
        "web_search":                      "src-websearch",
        "llm_market_estimate":             "src-ai",
        "web_ai_fallback":                 "src-ai",
        "config":                          "src-config",
    }.get(key, "src-unknown")
    supplier = ps.get("supplier_source") or ps.get("supplier_code")
    sup_str = f" · {_esc(str(supplier)[:30])}" if supplier else ""
    freshness = _FRESHNESS_LABELS.get(str(ps.get("freshness_bucket") or "unknown"), "")
    conf = _safe_float(ps.get("confidence"))
    conf_str = f" · conf {conf:.0%}" if conf is not None else ""
    date_str = str(ps.get("price_date") or "")[:10]
    date_display = f" · {date_str}" if date_str else ""
    tip = f"{label}{sup_str}{conf_str}{date_display}. {freshness}"
    return f"<span class='src-badge {css}' title='{_esc(tip)}'>{icon} {_esc(label[:35])}</span>"


# ─────────────────────────── section builders ───────────────────────────────

def _build_bom_table(parts: List[Dict[str, Any]]) -> str:
    """Full BOM table with one row per part — material, ops, route, price source, risk."""
    if not parts:
        return "<p class='no-data'>No parts found in the AI estimate.</p>"

    rows = []
    for p in parts:
        pn = _esc(p.get("part_number") or "—")
        desc = _esc((p.get("description") or "—")[:80])
        qty = int(_safe_float(p.get("quantity")) or 1)
        mat_norm = _esc(p.get("normalized_material") or p.get("material") or "—")
        thk = p.get("thickness_mm")
        thk_s = f"{thk} mm" if thk else "—"
        finish = _esc(", ".join(p.get("surface_finishes") or []) or "—")
        colour = _esc(", ".join(p.get("colours") or []) or "—")

        ops = (p.get("textual_operations") or []) + (p.get("inferred_operations") or [])
        ops_unique = list(dict.fromkeys(str(o) for o in ops if o))
        ops_s = _esc(", ".join(ops_unique) or "—")

        # Route
        route_steps = []
        est = p.get("process_estimate") or {}
        times = est.get("times_min") or {}
        for op_name, mins in times.items():
            m = _safe_float(mins)
            if m and m > 0:
                route_steps.append(f"{op_name.replace('_',' ').title()}: {m:.1f} min")
        route_s = _esc("; ".join(route_steps) or "—")

        mat_cost, lab_cost = _part_material_labour_cost(p)
        cb = p.get("cost_breakdown") or {}
        unit_cost = _safe_float(p.get("unit_total_cost_gbp") or cb.get("unit_total_cost_gbp"))
        ext_cost = _safe_float(p.get("extended_total_cost_gbp") or cb.get("extended_total_cost_gbp"))
        me = p.get("material_estimate") or {}
        ps = p.get("price_source") or me.get("price_source") or {}
        src_badge = _price_source_badge(ps)

        # Geometry reliability
        geom_rel = _safe_float(((p.get("geometry_rollup") or {}).get("confidence") or {}).get("geometry_reliability"))
        conf_overall = _safe_float((p.get("confidence") or {}).get("overall"))
        geom_bar = ""
        if geom_rel is not None:
            pct = int(geom_rel * 100)
            col = "#22c55e" if pct >= 70 else ("#f59e0b" if pct >= 45 else "#ef4444")
            geom_bar = f"<div class='conf-bar'><div class='conf-fill' style='width:{pct}%;background:{col}'></div></div><span class='conf-pct'>{pct}%</span>"

        # Risk flags
        risks = p.get("risk_flags") or []
        risk_html = ""
        if risks:
            items = "".join(
                f"<li title='{_esc(_explain_risk(rf))}'><span class='risk-dot'></span>{_esc(str(rf)[:60])}</li>"
                for rf in risks[:6]
            )
            risk_html = f"<ul class='risk-list'>{items}</ul>"
        else:
            risk_html = "<span class='ok-flag'>✓ No flags</span>"

        row_cls = "row-risk" if risks else ""
        rows.append(f"""
<tr class='{row_cls}'>
  <td class='col-pn'><span class='pn'>{pn}</span></td>
  <td class='col-desc'>{desc}</td>
  <td class='col-qty tc'>{qty}</td>
  <td class='col-mat'>{mat_norm}<br><span class='sub'>{thk_s}</span></td>
  <td class='col-fin'>{finish}<br><span class='sub'>{colour}</span></td>
  <td class='col-ops'>{ops_s}</td>
  <td class='col-route'>{route_s}</td>
  <td class='col-cost tr'>{_fmt_gbp(mat_cost)}</td>
  <td class='col-cost tr'>{_fmt_gbp(lab_cost)}</td>
  <td class='col-unit tr'><strong>{_fmt_gbp(unit_cost)}</strong><br><span class='sub'>{_fmt_gbp(ext_cost)} ext</span></td>
  <td class='col-src'>{src_badge}</td>
  <td class='col-geom'>{geom_bar}</td>
  <td class='col-risk'>{risk_html}</td>
</tr>""")

    header = """
<tr class='thead-row'>
  <th>Part No.</th><th>Description</th><th class='tc'>Qty</th>
  <th>Material / Thickness</th><th>Finish / Colour</th>
  <th>Operations detected</th><th>Route (AI times)</th>
  <th class='tr'>Mat cost (ext)</th><th class='tr'>Labour (ext)</th>
  <th class='tr'>Unit cost / Extended</th>
  <th>Price source</th><th>Geom confidence</th><th>Flags</th>
</tr>"""
    return f"<div class='table-scroll'><table class='bom-table'><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def _build_price_provenance(parts: List[Dict[str, Any]]) -> str:
    """Plain-English breakdown of where every price came from."""
    if not parts:
        return "<p class='no-data'>No parts priced.</p>"

    rows = []
    for p in parts:
        pn = _esc(p.get("part_number") or "—")
        me = p.get("material_estimate") or {}
        # pricing_service.py outputs price_source at part level; fall back to material_estimate.price_source
        ps = p.get("price_source") or me.get("price_source") or {}
        le = p.get("labour_estimate") or {}
        lab_source = le.get("rate_source") or le.get("source") or "config"

        # pricing_service.py joined_sources has the detailed breakdown
        joined = p.get("joined_sources") or {}
        wb_mat = (joined.get("reverse_engineered_workbook") or {}).get("material") or {}
        mat_price = _safe_float(
            me.get("applied_price_per_kg_gbp")
            or me.get("material_price_per_kg_gbp")
            or wb_mat.get("material_price_per_kg_gbp")
        )
        mat_basis = _esc(str(me.get("applied_basis") or me.get("basis") or wb_mat.get("basis") or "—"))

        # Source identification — handle both source_type and source keys
        src_raw = str(ps.get("source") or ps.get("source_type") or ps.get("source_name") or "").lower()
        src_type = src_raw
        src_name = src_raw or "config"
        supplier = (
            ps.get("supplier_name") or ps.get("supplier_source") or ps.get("supplier_code") or "—"
        )
        freshness_obj = ps.get("freshness") or {}
        freshness = str(ps.get("freshness_bucket") or freshness_obj.get("label") or "unknown")
        price_date = str(ps.get("effective_date") or ps.get("price_date") or "—")[:10]
        conf = _safe_float(ps.get("confidence"))
        web_query = ps.get("web_query") or ""
        prov_str = ps.get("provenance") or ""

        prov_key = _normalize_source_key(ps)
        mat_label = _source_label(prov_key)
        mat_icon = _source_icon(prov_key)
        freshness_label = _FRESHNESS_LABELS.get(freshness, freshness)

        web_note = ""
        if web_query:
            web_note = f"<div class='prov-web-query'>🔍 Web query used: <em>{_esc(web_query[:100])}</em></div>"

        ai_note = ""
        if prov_key == "web_ai_fallback":
            ai_note = "<div class='prov-ai-warn'>⚠️ This price was estimated by AI from internet sources — it is INDICATIVE only. Verify against a supplier quote or Access Supply Chain before quoting the customer.</div>"

        mat_price_s = f"£{mat_price:.4f}/kg" if mat_price else "—"

        # Labour sources
        lab_rows = []
        costs_gbp = le.get("costs_gbp") or {}
        rate_lookup = le.get("rate_sources") or {}
        for op, cost in costs_gbp.items():
            c = _safe_float(cost)
            if c and c > 0:
                op_src = rate_lookup.get(op) or lab_source
                lab_rows.append(
                    f"<tr><td>{_esc(op.replace('_',' ').title())}</td>"
                    f"<td class='tr'>{_fmt_gbp(c)}</td>"
                    f"<td><span class='src-badge src-config'>⚙ {_esc(str(op_src)[:30])}</span></td></tr>"
                )
        lab_table = (
            f"<table class='prov-lab-table'><thead><tr><th>Operation</th><th>Cost</th><th>Rate source</th></tr></thead>"
            f"<tbody>{''.join(lab_rows)}</tbody></table>"
            if lab_rows else "<p class='sub'>No labour breakdown available.</p>"
        )

        # Historical RAG matches with token overlap scores
        hist_matches = p.get("top_historical_matches") or []
        hist_html = ""
        if hist_matches:
            hist_rows = ""
            for hm in hist_matches[:5]:
                score = hm.get("token_overlap_score") or 0
                quality = hm.get("match_quality") or ("strong" if score >= 0.35 else "moderate" if score >= 0.15 else "weak")
                q_color = {"strong": "#15803d", "moderate": "#92400e", "weak": "#94a3b8"}.get(quality, "#94a3b8")
                hist_rows += (
                    f"<tr><td>{_esc(str(hm.get('line_description') or '')[:50])}</td>"
                    f"<td class='tr'>{_fmt_gbp(_safe_float(hm.get('unit_price_gbp')))}</td>"
                    f"<td>{_esc(str(hm.get('quote_date') or '')[:10])}</td>"
                    f"<td>{_esc(str(hm.get('drawing_number') or '—'))}</td>"
                    f"<td><span style='color:{q_color};font-weight:600'>{score:.0%} ({quality})</span></td></tr>"
                )
            hist_html = (
                "<div class='prov-section' style='grid-column:span 2'>"
                "<h4>📜 Historical RAG comparators (token overlap ranked)</h4>"
                "<table class='prov-lab-table'><thead><tr>"
                "<th>Historical description</th><th class='tr'>Unit price</th>"
                "<th>Date</th><th>Drawing</th><th>Match quality</th>"
                "</tr></thead><tbody>" + hist_rows + "</tbody></table></div>"
            )

        prov_detail = f"<div class='prov-web-query'>🔗 Provenance: <em>{_esc(prov_str[:200])}</em></div>" if prov_str else ""

        rows.append(f"""
<details class='prov-card'>
  <summary class='prov-summary'>
    <span class='prov-pn'>{pn}</span>
    <span class='prov-desc'>{_esc((p.get("description") or "")[:60])}</span>
    <span class='prov-src'>{mat_icon} {_esc(mat_label[:40])}</span>
    <span class='prov-price'>{_fmt_gbp(_safe_float(p.get("unit_total_cost_gbp")))}</span>
  </summary>
  <div class='prov-body'>
    <div class='prov-section'>
      <h4>Material price source</h4>
      <table class='prov-meta'>
        <tr><td>Source system</td><td><strong>{mat_icon} {_esc(mat_label)}</strong></td></tr>
        <tr><td>Supplier / source</td><td>{_esc(str(supplier))}</td></tr>
        <tr><td>Price used</td><td>{_esc(mat_price_s)} (basis: {mat_basis})</td></tr>
        <tr><td>Price date</td><td>{_esc(price_date)}</td></tr>
        <tr><td>Freshness</td><td>{_esc(freshness_label)}</td></tr>
        <tr><td>Confidence</td><td>{f"{conf:.0%}" if conf else "—"}</td></tr>
        <tr><td>Material cost</td><td>{_fmt_gbp(_safe_float(p.get("material_cost_gbp")))}</td></tr>
        <tr><td>Labour cost</td><td>{_fmt_gbp(_safe_float(p.get("labour_cost_gbp")))}</td></tr>
        <tr><td>Unit total</td><td><strong>{_fmt_gbp(_safe_float(p.get("unit_total_cost_gbp")))}</strong></td></tr>
      </table>
      {prov_detail}{web_note}{ai_note}
    </div>
    <div class='prov-section'>
      <h4>Labour rates source</h4>
      {lab_table}
    </div>
    {hist_html}
  </div>
</details>""")

    return "".join(rows)


def _build_money_table(money: List[Dict[str, Any]]) -> str:
    if not money:
        return "<p class='no-data'>No money cell comparisons in this bundle.</p>"

    rows = []
    for r in money:
        st = str(r.get("status") or "review")
        is_qty = _is_qty_row(r)
        j = _safe_float(r.get("json_numeric"))
        w = _safe_float(r.get("workbook_cached_numeric"))
        bg, badge, _ = _status_traffic(st)

        j_s = (str(int(round(j))) if j is not None and is_qty else _fmt_gbp(j)) if j is not None else "—"
        w_s = (str(int(round(w))) if w is not None and is_qty else _fmt_gbp(w)) if w is not None else "—"

        delta = (j - w) if (j is not None and w is not None) else None
        if delta is None:
            delta_s, delta_cls = "—", ""
        elif is_qty:
            delta_s = f"{delta:+g} units" if abs(delta) > 1e-6 else "matches"
            delta_cls = "" if abs(delta) < 1e-6 else "val-warn"
        else:
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            thr = max(abs(w or 0) * 0.05, 5)
            delta_cls = "" if abs(delta) < 0.01 else ("val-warn" if abs(delta) < thr else "val-fail")
            delta_s = f"{arrow} {_fmt_gbp(abs(delta))}"

        if not is_qty and j is not None and w is not None and abs(w) > 0.01:
            pct = round(100.0 * (j - w) / w, 1)
            pct_s = _fmt_pct(pct)
        else:
            pct_s = "—"

        label = _esc(r.get("label") or "")
        cell = _esc(r.get("cell") or "")
        path = _esc(r.get("json_path") or "")

        rows.append(f"""
<tr class='{bg}'>
  <td><div class='cell-label'>{label}</div><div class='cell-ref'>{cell}</div></td>
  <td class='tr val-ai'>{j_s}</td>
  <td class='tr val-wb'>{w_s}</td>
  <td class='tr {delta_cls}'>{delta_s}</td>
  <td class='tr val-pct'>{pct_s}</td>
  <td class='tc'>{badge}</td>
  <td class='path-col' title='{path}'>{path}</td>
</tr>""")

    return f"""
<div class='table-scroll'>
<table class='money-table'>
<thead>
<tr class='thead-row'>
  <th>Cell label / reference</th>
  <th class='tr'>AI value</th>
  <th class='tr'>Manual workbook</th>
  <th class='tr'>Difference</th>
  <th class='tr'>Variance %</th>
  <th class='tc'>Status</th>
  <th>JSON path (internal)</th>
</tr>
</thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
<p class='table-note'>Green = within 3% tolerance. Amber = 3–10%. Red = >10% or missing.<br>
JSON path shows exactly which field in the AI output was compared to the workbook cell.</p>"""


def _build_route_table(labour: List[Dict[str, Any]]) -> str:
    filtered = [
        r for r in labour
        if r.get("operation_code") and str(r.get("status") or "").lower() != "noise"
    ]
    if not filtered:
        return "<p class='no-data'>No labour route rows found in this parity bundle. The workbook may not expose SDI operation codes in the scanned range.</p>"

    rows = []
    for r in filtered[:60]:
        st = str(r.get("status") or "")
        bg, badge, _ = _status_traffic(st)
        op_label = r.get("display_label") or r.get("operation_code") or "—"
        op = _esc(op_label)
        wb_codes = r.get("workbook_operation_codes") or []
        if wb_codes:
            op += f"<br><span class='sub'>{_esc(', '.join(str(c) for c in wb_codes[:6]))}</span>"
        row_ref = r.get("sheet_row")
        if row_ref is None:
            rows_list = r.get("workbook_sheet_rows") or []
            row_ref = ", ".join(str(x) for x in rows_list[:8]) if rows_list else "—"
        row_ref = _esc(str(row_ref))
        j_h = _fmt_hours(r.get("json_hours_decimal"))
        w_h = _fmt_hours(r.get("workbook_hours_decimal"))
        j_c = _safe_float(r.get("json_labour_cost_gbp"))
        w_c = _safe_float(r.get("workbook_line_cost_gbp"))
        delta_c = (j_c - w_c) if (j_c is not None and w_c is not None) else None
        arrow = "↑" if (delta_c or 0) > 0 else ("↓" if (delta_c or 0) < 0 else "→")
        delta_s = f"{arrow} {_fmt_gbp(abs(delta_c))}" if delta_c is not None else "—"

        rows.append(f"""
<tr class='{bg}'>
  <td class='op-col'><span class='op-code'>{op}</span></td>
  <td class='tc'>{row_ref}</td>
  <td class='tr'>{j_h}</td>
  <td class='tr'>{w_h}</td>
  <td class='tr val-ai'>{_fmt_gbp(j_c)}</td>
  <td class='tr val-wb'>{_fmt_gbp(w_c)}</td>
  <td class='tr'>{delta_s}</td>
  <td class='tc'>{badge}</td>
</tr>""")

    return f"""
<div class='table-scroll'>
<table class='route-table'>
<thead>
<tr class='thead-row'>
  <th>SDI Op code</th><th class='tc'>Sheet row</th>
  <th class='tr'>AI hours</th><th class='tr'>Workbook hours</th>
  <th class='tr'>AI cost</th><th class='tr'>WB cost</th>
  <th class='tr'>Difference</th><th class='tc'>Status</th>
</tr>
</thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
<p class='table-note'>Each row is one SDI operation code (e.g. LASM, FOLD, PCOA). Hours = time allocated in each system. Cost = hours × hourly rate.</p>"""


def _build_gaps_explanation(
    j_mat: Optional[float], w_mat: Optional[float],
    j_lab: Optional[float], w_lab: Optional[float],
    parts: List[Dict[str, Any]],
) -> str:
    """Plain English gap analysis — what's different and why."""
    items = []

    # Material gap
    if j_mat is not None and w_mat is not None and w_mat > 0.5:
        mat_pct = round(100.0 * (j_mat - w_mat) / w_mat, 1)
        if j_mat < w_mat * 0.55:
            items.append(
                f"<li class='gap-item gap-high'>📦 <strong>Material cost is much lower in the AI estimate ({_fmt_gbp(j_mat)}) than the manual workbook ({_fmt_gbp(w_mat)}) — a {mat_pct:+.1f}% difference.</strong> "
                "This usually means some bought-in components or catalogue parts have no price in the SQL database. "
                "Check the 'bought_in_parts' table and the UDEF_PARTS_TABLE_FOR_ESTIMATING in Access Supply Chain. "
                "Parts flagged as [web/AI] below have fallback prices that may be lower than actual supplier cost.</li>"
            )
        elif j_mat > w_mat * 1.35:
            items.append(
                f"<li class='gap-item gap-high'>📦 <strong>Material cost is much higher in the AI estimate ({_fmt_gbp(j_mat)}) than the workbook ({_fmt_gbp(w_mat)}) — a {mat_pct:+.1f}% difference.</strong> "
                "This can happen if section stock (tube, angle, channel) is being priced as sheet material, "
                "or if the blank size calculation is producing a larger area than the manual measurement. "
                "Check the geometry reliability scores and blank dimensions in the BOM table above.</li>"
            )
        elif abs(mat_pct) > 5:
            items.append(
                f"<li class='gap-item gap-med'>📦 Material cost differs by {mat_pct:+.1f}% (AI: {_fmt_gbp(j_mat)} vs manual: {_fmt_gbp(w_mat)}). "
                "Small differences are normal — check the material price date and whether the workbook uses the same steel price per tonne.</li>"
            )

    # Labour gap
    if j_lab is not None and w_lab is not None and w_lab > 0.5:
        lab_pct = round(100.0 * (j_lab - w_lab) / w_lab, 1)
        if j_lab > w_lab * 1.35:
            items.append(
                f"<li class='gap-item gap-high'>⏱ <strong>Labour cost is much higher in the AI estimate ({_fmt_gbp(j_lab)}) than the workbook ({_fmt_gbp(w_lab)}) — a {lab_pct:+.1f}% difference.</strong> "
                "This often means the AI is counting more operations than the manual estimate, or the minutes-per-operation figures are too high. "
                "Check the route table below — look for operations the manual estimate doesn't include, or where AI hours are significantly higher than workbook hours.</li>"
            )
        elif j_lab < w_lab * 0.55:
            items.append(
                f"<li class='gap-item gap-high'>⏱ <strong>Labour cost is much lower in the AI estimate ({_fmt_gbp(j_lab)}) than the workbook ({_fmt_gbp(w_lab)}) — a {lab_pct:+.1f}% difference.</strong> "
                "Some operations may be missing from the AI routing. Check whether assembly, bench work, or packing lines appear in the workbook but not in the AI route table.</li>"
            )
        elif abs(lab_pct) > 10:
            items.append(
                f"<li class='gap-item gap-med'>⏱ Labour differs by {lab_pct:+.1f}% (AI: {_fmt_gbp(j_lab)} vs manual: {_fmt_gbp(w_lab)}). "
                "Review the route table for individual operation hour differences.</li>"
            )

    # Web/AI fallback warnings
    ai_parts = []
    for p in parts:
        ps = p.get("price_source") or (p.get("material_estimate") or {}).get("price_source") or {}
        src = str(ps.get("source_type") or ps.get("source") or "").lower()
        if src in {"web_ai_fallback", "web_search", "llm_market_estimate"}:
            ai_parts.append(p)
    if ai_parts:
        pn_list = ", ".join(_esc(str(p.get("part_number") or "?")) for p in ai_parts[:8])
        items.append(
            f"<li class='gap-item gap-ai'>🤖 <strong>{len(ai_parts)} part(s) have AI internet fallback prices: {pn_list}.</strong> "
            "These prices came from an AI web search because no price was found in Access Supply Chain or the SQL database. "
            "They are indicative estimates and MUST be verified against actual supplier quotes before using this estimate for customer pricing. "
            "To fix: add these parts to the bought_in_parts table or the UDEF_PARTS_TABLE_FOR_ESTIMATING in Access Supply Chain.</li>"
        )

    # Missing prices
    def _computed_material_cost(p):
        me = p.get("material_estimate") or {}
        v = me.get("extended_material_cost_gbp")
        if v in (None, ""):
            v = me.get("cost_per_part_gbp")
        try:
            return float(v or 0)
        except Exception:
            return 0.0
    # A part is genuinely uncosted only if its COMPUTED material cost is zero. The engine
    # prices sheet metal by nesting (sheet area x rate/tonne), so a missing per-kg price does
    # NOT mean uncosted. Flag on the real cost, not the per-kg lookup.
    missing = [p for p in parts if _computed_material_cost(p) <= 0]
    if missing:
        pn_list = ", ".join(_esc(str(p.get("part_number") or "?")) for p in missing[:6])
        items.append(
            f"<li class='gap-item gap-high'>❌ <strong>{len(missing)} part(s) have £0 computed material cost: {pn_list}.</strong> "
            "If a part is a bought-in item already covered in the Standard Materials BOM (e.g. a slotted tube), this is expected; "
            "otherwise it is genuinely uncosted and needs a flat DXF or a price (MATERIAL_PRICE_GBP_PER_KG / SQL material_prices).</li>"
        )

    if not items:
        items.append("<li class='gap-item gap-ok'>✅ No significant gaps identified. Material and labour are within expected tolerances.</li>")

    return f"<ul class='gap-list'>{''.join(items)}</ul>"


def _build_summary_scorecard(
    exec_s: Dict[str, Any],
    counts: Dict[str, Any],
    j_mat: Optional[float], w_mat: Optional[float],
    j_lab: Optional[float], w_lab: Optional[float],
    doc_total: Optional[float],
    wb_combined: Optional[float],
) -> Tuple[str, str]:
    """Returns (overall_status_class, scorecard_html)."""
    mf = int(counts.get("money_fail") or 0)
    mw = int(counts.get("money_warning") or 0)
    pct = exec_s.get("pct_ok")

    if mf == 0 and mw == 0:
        status_cls = "status-green"
        verdict = "✅ On track — AI and manual workbook agree within tolerance"
        verdict_detail = f"{exec_s.get('money_match', 0)} of {exec_s.get('money_total', 0)} money cells match."
    elif mf <= 1:
        status_cls = "status-amber"
        verdict = "⚠️ Mostly aligned — a few lines need review"
        verdict_detail = f"{mf} failing, {mw} warning money lines. Review the highlighted rows below."
    else:
        status_cls = "status-red"
        verdict = "🔴 Significant differences — review before quoting"
        verdict_detail = f"{mf} failing money lines. Do not use this estimate for customer pricing without resolving the gaps."

    mat_pct = round(100.0 * (j_mat - w_mat) / w_mat, 1) if (j_mat is not None and w_mat and w_mat > 0.5) else None
    lab_pct = round(100.0 * (j_lab - w_lab) / w_lab, 1) if (j_lab is not None and w_lab and w_lab > 0.5) else None
    total_pct = round(100.0 * (doc_total - wb_combined) / wb_combined, 1) if (doc_total is not None and wb_combined and wb_combined > 0.5) else None

    def _score_row(label: str, ai_val: Optional[float], wb_val: Optional[float], pct_val: Optional[float]) -> str:
        if ai_val is None and wb_val is None:
            return f"<tr><td>{label}</td><td>—</td><td>—</td><td>—</td></tr>"
        cls = ""
        if pct_val is not None:
            cls = "val-ok" if abs(pct_val) < 5 else ("val-warn" if abs(pct_val) < 15 else "val-fail")
        pct_s = _fmt_pct(pct_val) if pct_val is not None else "—"
        return (
            f"<tr><td>{label}</td>"
            f"<td class='tr val-ai'>{_fmt_gbp(ai_val)}</td>"
            f"<td class='tr val-wb'>{_fmt_gbp(wb_val)}</td>"
            f"<td class='tr {cls}'>{pct_s}</td></tr>"
        )

    scorecard = f"""
<div class='scorecard {status_cls}'>
  <div class='verdict'>{verdict}</div>
  <div class='verdict-detail'>{_esc(verdict_detail)}</div>
  <table class='score-table'>
    <thead><tr><th>Component</th><th class='tr'>AI estimate</th><th class='tr'>Manual workbook</th><th class='tr'>Variance</th></tr></thead>
    <tbody>
      {_score_row("Material cost", j_mat, w_mat, mat_pct)}
      {_score_row("Labour cost", j_lab, w_lab, lab_pct)}
      {_score_row("Total (mat + lab)", doc_total, wb_combined, total_pct)}
    </tbody>
  </table>
  <p class='score-note'>{mf} failing &middot; {mw} within tolerance (3&ndash;10%) &middot; {int(counts.get('money_match') or 0)} exact match (&lt;3%) &mdash; of {exec_s.get('money_total',0)} money lines.</p>
</div>"""
    return status_cls, scorecard


# ─────────────────────────── main generator ─────────────────────────────────

def generate_pretty_parity_html(
    *,
    bundle: Dict[str, Any],
    summary: Dict[str, Any],
    output_path: Path,
) -> Path:
    est = summary.get("estimate_summary") or {}
    if not isinstance(est, dict):
        est = {}

    money = [r for r in (bundle.get("money_cell_comparisons") or []) if r.get("section") == "money_cell"]
    labour = [r for r in (bundle.get("labour_route_comparisons") or []) if r.get("section") == "labour_route"]
    counts = bundle.get("status_counts") or {}
    parts = _collect_report_parts(summary, bundle)

    mat_gbp, lab_gbp = _money_totals_from_json(est)
    j_m59, w_m59 = _money_pair(money, "m59_material_subtotal_gbp")
    j_m103, w_m103 = _money_pair(money, "m103_labour_subtotal_gbp")
    wb_combined = (w_m59 or 0.0) + (w_m103 or 0.0) if (w_m59 is not None or w_m103 is not None) else None

    doc_total = _safe_float(est.get("document_total_estimated_cost_gbp"))

    ok = sum(1 for r in money if r.get("status") == "match")
    total_money = len(money)
    pct_ok = round(100.0 * ok / total_money, 1) if total_money else None
    exec_s = {"pct_ok": pct_ok, "money_match": ok, "money_total": total_money}

    gap_gbp = round(doc_total - wb_combined, 2) if (doc_total is not None and wb_combined is not None) else None
    gap_pct = round(100.0 * gap_gbp / wb_combined, 1) if (gap_gbp is not None and wb_combined and wb_combined > 0) else None
    gap_s = f"{'+' if (gap_gbp or 0) >= 0 else ''}{_fmt_gbp(gap_gbp)} ({_fmt_pct(gap_pct)} vs manual)" if gap_gbp is not None else "—"

    wb_path = str(bundle.get("workbook_path", "—"))
    source_file = str(summary.get("source_file") or summary.get("drawing_number") or "drawing")
    drawing_no = str(summary.get("drawing_number") or Path(source_file).stem)
    now = datetime.now().strftime("%d %b %Y %H:%M")
    policy_ver = str((summary.get("estimate_policy_manifest") or {}).get("policy_snapshot", {}).get("estimate_policy_version") or "—")

    status_cls, scorecard_html = _build_summary_scorecard(
        exec_s, counts,
        j_m59 or mat_gbp, w_m59,
        j_m103 or lab_gbp, w_m103,
        doc_total, wb_combined,
    )
    gaps_html = _build_gaps_explanation(j_m59 or mat_gbp, w_m59, j_m103 or lab_gbp, w_m103, parts)
    bom_html = _build_bom_table(parts)
    prov_html = _build_price_provenance(parts)
    money_html = _build_money_table(money)
    route_html = _build_route_table(labour)

    # Risk rollup
    from collections import Counter as _Counter
    risk_counter: _Counter[str] = _Counter()
    for p in parts:
        for rf in (p.get("risk_flags") or []):
            if isinstance(rf, str):
                risk_counter[rf.strip()] += 1
    risk_items = "".join(
        f"<li><span class='risk-flag'>{_esc(flag)}</span> ×{n} — {_esc(_explain_risk(flag))}</li>"
        for flag, n in risk_counter.most_common(20)
    ) or "<li class='ok-flag'>No risk flags across all parts.</li>"

    # Chart data
    pie_labels = json.dumps(["Material", "Labour"])
    pie_data = json.dumps([mat_gbp, lab_gbp])
    bar_labels = json.dumps(["Material", "Labour"])
    bar_ai = json.dumps([mat_gbp, lab_gbp])
    bar_wb = json.dumps([w_m59 or 0, w_m103 or 0])
    has_wb = (w_m59 is not None) or (w_m103 is not None)
    bar_script = ""
    if has_wb:
        bar_script = f"""
const barCtx = document.getElementById('barChart');
new Chart(barCtx, {{
  type: 'bar',
  data: {{
    labels: {bar_labels},
    datasets: [
      {{label: 'AI estimate', data: {bar_ai}, backgroundColor: '#1e3a5f'}},
      {{label: 'Manual workbook', data: {bar_wb}, backgroundColor: '#94a3b8'}}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: 'bottom' }}}},
    scales: {{ y: {{ beginAtZero: true, ticks: {{ callback: v => '£'+v.toLocaleString() }}}}}}
  }}
}});"""

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SDI AI Parity Report — {_esc(drawing_no)}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
/* ── reset & base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; color: #1e293b; background: #f8fafc; line-height: 1.5; }}
a {{ color: #1e3a8a; }}

/* ── layout ── */
.page {{ max-width: 1400px; margin: 0 auto; padding: 24px 20px 60px; }}
.section {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; margin-bottom: 28px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
.section-header {{ padding: 18px 24px; border-bottom: 1px solid #e2e8f0; background: #f8fafc; }}
.section-header h2 {{ font-size: 17px; font-weight: 700; color: #1e293b; margin-bottom: 4px; }}
.section-header p {{ font-size: 13px; color: #64748b; }}
.section-body {{ padding: 20px 24px; }}

/* ── top bar ── */
.topbar {{ background: #1e3a5f; color: #fff; padding: 16px 24px; border-radius: 12px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
.topbar h1 {{ font-size: 20px; font-weight: 700; }}
.topbar .meta {{ font-size: 12px; color: #94a3b8; }}
.topbar .badge-version {{ background: #334155; padding: 3px 10px; border-radius: 99px; font-size: 12px; }}

/* ── scorecard ── */
.scorecard {{ border-radius: 10px; padding: 20px 24px; margin-bottom: 8px; border: 2px solid; }}
.status-green {{ background: #f0fdf4; border-color: #86efac; }}
.status-amber {{ background: #fffbeb; border-color: #fcd34d; }}
.status-red   {{ background: #fff1f2; border-color: #fca5a5; }}
.verdict {{ font-size: 18px; font-weight: 700; margin-bottom: 6px; }}
.verdict-detail {{ font-size: 13px; color: #475569; margin-bottom: 16px; }}
.score-table {{ width: 100%; border-collapse: collapse; max-width: 600px; }}
.score-table th, .score-table td {{ padding: 8px 12px; border: 1px solid #e2e8f0; font-size: 13px; }}
.score-table th {{ background: #f1f5f9; font-weight: 600; }}
.score-note {{ margin-top: 12px; font-size: 12px; color: #64748b; }}

/* ── gap analysis ── */
.gap-list {{ list-style: none; }}
.gap-item {{ padding: 12px 16px; border-radius: 8px; margin-bottom: 10px; font-size: 13px; border-left: 4px solid; }}
.gap-ok   {{ background: #f0fdf4; border-color: #22c55e; }}
.gap-med  {{ background: #fffbeb; border-color: #f59e0b; }}
.gap-high {{ background: #fff1f2; border-color: #ef4444; }}
.gap-ai   {{ background: #fff7ed; border-color: #f97316; }}

/* ── badges ── */
.badge {{ display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 99px; font-size: 12px; font-weight: 600; }}
.badge-match {{ background: #dcfce7; color: #15803d; }}
.badge-warn  {{ background: #fef9c3; color: #92400e; }}
.badge-fail  {{ background: #fee2e2; color: #991b1b; }}

/* ── source badges ── */
.src-badge {{ display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; cursor: help; white-space: nowrap; }}
.src-udef     {{ background: #dbeafe; color: #1e40af; }}
.src-sql      {{ background: #ede9fe; color: #5b21b6; }}
.src-sheet    {{ background: #dcfce7; color: #15803d; }}
.src-web      {{ background: #cffafe; color: #0e7490; }}
.src-ai       {{ background: #fff7ed; color: #c2410c; border: 1px solid #fdba74; }}
.src-config   {{ background: #f1f5f9; color: #475569; }}
.src-unknown  {{ background: #fafafa; color: #94a3b8; border: 1px solid #e2e8f0; }}
.src-historic {{ background: #fef3c7; color: #78350f; }}
.src-bought   {{ background: #f0fdf4; color: #166534; }}
.src-catalog  {{ background: #e0f2fe; color: #075985; }}
.src-websearch{{ background: #ecfeff; color: #0e7490; }}

/* ── tables ── */
.table-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
.bom-table, .money-table, .route-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
.bom-table th, .money-table th, .route-table th {{ background: #1e3a5f; color: #fff; padding: 9px 10px; text-align: left; white-space: nowrap; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }}
.bom-table td, .money-table td, .route-table td {{ padding: 8px 10px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
.bom-table tr:hover, .money-table tr:hover, .route-table tr:hover {{ background: #f8fafc; }}
.row-risk {{ background: #fffbeb; }}
.thead-row {{ /* already styled via th */ }}
.tr {{ text-align: right; }}
.tc {{ text-align: center; }}
.pn {{ font-family: 'Courier New', monospace; font-weight: 700; font-size: 12px; background: #f1f5f9; padding: 1px 5px; border-radius: 4px; }}
.sub {{ font-size: 11px; color: #94a3b8; }}
.op-code {{ font-family: monospace; font-weight: 700; font-size: 12px; }}
.cell-label {{ font-weight: 600; color: #1e293b; }}
.cell-ref {{ font-family: monospace; font-size: 11px; color: #94a3b8; }}
.path-col {{ font-family: monospace; font-size: 10px; color: #94a3b8; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.val-ai {{ color: #1e40af; }}
.val-wb {{ color: #374151; }}
.val-ok {{ color: #15803d; }}
.val-warn {{ color: #92400e; }}
.val-fail {{ color: #991b1b; font-weight: 600; }}
.val-pct {{ font-size: 11px; color: #64748b; }}
.table-note {{ font-size: 11px; color: #94a3b8; margin-top: 8px; padding: 0 4px; }}

/* ── confidence bar ── */
.conf-bar {{ display: inline-block; width: 60px; height: 6px; background: #e2e8f0; border-radius: 3px; vertical-align: middle; overflow: hidden; margin-right: 4px; }}
.conf-fill {{ height: 100%; border-radius: 3px; }}
.conf-pct {{ font-size: 11px; color: #475569; }}

/* ── risk ── */
.risk-list {{ list-style: none; }}
.risk-list li {{ font-size: 11px; color: #92400e; margin-bottom: 2px; cursor: help; }}
.risk-dot {{ display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #f59e0b; margin-right: 4px; vertical-align: middle; }}
.ok-flag {{ font-size: 11px; color: #15803d; }}
.risk-flag {{ font-family: monospace; font-size: 12px; font-weight: 600; color: #b45309; }}
.gap-list li, .gap-list ul {{ font-size: 13px; }}

/* ── provenance cards ── */
.prov-card {{ border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 8px; overflow: hidden; }}
.prov-summary {{ padding: 12px 16px; cursor: pointer; display: grid; grid-template-columns: 120px 1fr 200px 100px; gap: 12px; align-items: center; background: #fafafa; font-size: 13px; }}
.prov-summary:hover {{ background: #f1f5f9; }}
.prov-pn {{ font-family: monospace; font-weight: 700; font-size: 12px; }}
.prov-desc {{ color: #475569; }}
.prov-src {{ font-size: 12px; }}
.prov-price {{ text-align: right; font-weight: 700; font-size: 14px; color: #1e3a5f; }}
.prov-body {{ padding: 16px; background: #fff; border-top: 1px solid #e2e8f0; display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
.prov-section h4 {{ font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: #64748b; margin-bottom: 10px; }}
.prov-meta {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
.prov-meta td {{ padding: 4px 8px; border-bottom: 1px solid #f1f5f9; }}
.prov-meta td:first-child {{ color: #64748b; width: 140px; }}
.prov-web-query {{ margin-top: 8px; font-size: 11px; background: #f0fdf4; padding: 6px 10px; border-radius: 6px; color: #166534; }}
.prov-ai-warn {{ margin-top: 8px; font-size: 12px; background: #fff7ed; padding: 8px 12px; border-radius: 6px; color: #c2410c; border: 1px solid #fdba74; font-weight: 500; }}
.prov-lab-table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
.prov-lab-table th, .prov-lab-table td {{ padding: 5px 8px; border: 1px solid #e2e8f0; }}
.prov-lab-table th {{ background: #f1f5f9; font-weight: 600; }}
.no-data {{ color: #94a3b8; font-size: 13px; padding: 12px 0; }}

/* ── charts ── */
.charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
@media (max-width: 700px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
.chart-box {{ border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; background: #fff; }}
.chart-title {{ font-size: 13px; font-weight: 700; color: #1e293b; margin-bottom: 12px; }}

/* ── print ── */
@media print {{
  .no-print {{ display: none !important; }}
  body {{ background: #fff; }}
  .section {{ box-shadow: none; border: 1px solid #ccc; }}
  .topbar {{ background: #1e3a5f !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
}}
</style>
</head>
<body>
<div class="page">

  <!-- TOP BAR -->
  <div class="topbar">
    <div>
      <div class="meta">SDI Displays Ltd · AI Estimating Platform</div>
      <h1>Parity Report — {_esc(drawing_no)}</h1>
      <div class="meta" style="margin-top:4px">Workbook: {_esc(Path(wb_path).name)} · Generated: {_esc(now)} · Policy v{_esc(policy_ver)}</div>
    </div>
    <div style="text-align:right">
      <div class="meta">Parts in AI estimate</div>
      <div style="font-size:28px;font-weight:700">{len(parts)}</div>
    </div>
  </div>

  <!-- SECTION 1: VERDICT & SCORECARD -->
  <div class="section">
    <div class="section-header">
      <h2>1 · Overall verdict</h2>
      <p>How closely does the AI estimate match the manually-built workbook? Green = good to go. Amber = needs a look. Red = do not use for quoting without fixing.</p>
    </div>
    <div class="section-body">
      {scorecard_html}
    </div>
  </div>

  <!-- SECTION 2: WHAT'S DIFFERENT AND WHY -->
  <div class="section">
    <div class="section-header">
      <h2>2 · What's different and why — plain English</h2>
      <p>This section explains the gaps in plain language, with specific things to check or fix. Read this first before looking at the detailed tables.</p>
    </div>
    <div class="section-body">
      {gaps_html}
    </div>
  </div>

  <!-- SECTION 3: CHARTS -->
  <div class="section">
    <div class="section-header">
      <h2>3 · Cost breakdown charts</h2>
      <p>AI estimate split between material and labour. Side-by-side comparison where workbook values are available.</p>
    </div>
    <div class="section-body">
      <div class="charts-grid">
        <div class="chart-box">
          <div class="chart-title">AI estimate — material vs labour split</div>
          <canvas id="pieChart" style="max-height:260px"></canvas>
          <p style="font-size:12px;color:#64748b;margin-top:10px">
            Material: {_fmt_gbp(mat_gbp)} · Labour: {_fmt_gbp(lab_gbp)} · Total: {_fmt_gbp(doc_total)}
          </p>
        </div>
        <div class="chart-box">
          <div class="chart-title">AI vs manual — material and labour bars</div>
          {'<canvas id="barChart" style="max-height:260px"></canvas>' if has_wb else '<p class="no-data">Workbook M59/M103 values not matched — bar chart not available.</p>'}
        </div>
      </div>
    </div>
  </div>

  <!-- SECTION 4: FULL BOM TABLE -->
  <div class="section">
    <div class="section-header">
      <h2>4 · Full Bill of Materials — AI extracted</h2>
      <p>Every part the AI found in the drawing. Shows material, finish, operations detected, the AI routing times, cost per part, and where the price came from.
      <strong>Geom %</strong> = how reliably the AI read the geometry (size/area) from the drawing. Below 70% means the blank size may be approximate.</p>
    </div>
    <div class="section-body" style="padding:0">
      {bom_html}
    </div>
  </div>

  <!-- SECTION 5: WHERE DID EVERY PRICE COME FROM -->
  <div class="section">
    <div class="section-header">
      <h2>5 · Price provenance — where did every price come from?</h2>
      <p>For each part: which system the material price came from, how fresh it is, and which operations drove the labour cost.
      <span style="color:#c2410c;font-weight:600">🤖 AI/internet prices must be verified before quoting.</span></p>
    </div>
    <div class="section-body">
      {prov_html if prov_html else '<p class="no-data">No parts priced.</p>'}
    </div>
  </div>

  <!-- SECTION 6: MONEY CELLS SIDE BY SIDE -->
  <div class="section">
    <div class="section-header">
      <h2>6 · Money cells — AI vs manual workbook (side by side)</h2>
      <p>Every cell in the estimate workbook that the AI mapped to a JSON value. Shows the AI number, the workbook number, the difference, and whether they match.
      <strong>JSON path</strong> shows the exact field in the AI output that was compared.</p>
    </div>
    <div class="section-body" style="padding:12px 0 0">
      {money_html}
    </div>
  </div>

  <!-- SECTION 7: LABOUR ROUTE -->
  <div class="section">
    <div class="section-header">
      <h2>7 · Labour route — AI hours vs workbook hours per operation</h2>
      <p>Compares each SDI operation code (LASM = laser, FOLD = folding, PCOA = powder coat, etc.) between the AI estimate and the manual workbook.
      Hours × hourly rate = labour cost per operation.</p>
    </div>
    <div class="section-body" style="padding:12px 0 0">
      {route_html}
    </div>
  </div>

  <!-- SECTION 8: RISK FLAGS -->
  <div class="section">
    <div class="section-header">
      <h2>8 · Risk flags — what needs human attention</h2>
      <p>Anything the AI flagged as uncertain, missing, or requiring verification. Each flag has a plain-English explanation of what to check.</p>
    </div>
    <div class="section-body">
      <ul class="gap-list">
        {risk_items}
      </ul>
    </div>
  </div>

  <!-- FOOTER -->
  <div class="no-print" style="margin-top:20px;padding:16px;background:#f1f5f9;border-radius:8px;font-size:11px;color:#64748b">
    <strong>SDI AI Estimating Platform</strong> · Parity report generated {_esc(now)} ·
    Drawing: {_esc(source_file)} · Workbook: {_esc(wb_path)} ·
    Policy version: {_esc(policy_ver)} ·
    Parts: {len(parts)} · Money cells checked: {total_money} · Matched: {ok}
  </div>

</div>

<script>
// Pie chart
const pieCtx = document.getElementById('pieChart');
new Chart(pieCtx, {{
  type: 'doughnut',
  data: {{
    labels: {pie_labels},
    datasets: [{{ data: {pie_data}, backgroundColor: ['#1e3a5f', '#38bdf8'], borderWidth: 2, borderColor: '#fff' }}]
  }},
  options: {{ plugins: {{ legend: {{ position: 'bottom' }}}}, cutout: '55%' }}
}});
// Bar chart
{bar_script}
</script>
</body>
</html>"""

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


def write_pretty_report_from_paths(
    *,
    summary_json: Path,
    bundle_json: Path,
    output_html: Path,
) -> Path:
    summary = json.loads(Path(summary_json).read_text(encoding="utf-8"))
    bundle = json.loads(Path(bundle_json).read_text(encoding="utf-8"))
    return generate_pretty_parity_html(bundle=bundle, summary=summary, output_path=Path(output_html))
