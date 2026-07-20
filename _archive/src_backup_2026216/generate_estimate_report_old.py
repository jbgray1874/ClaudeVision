"""
SDIAIVision — Estimate Report Generator
Reads a scan JSON and produces HTML + CSV:
  1. Full BOM cost summary (all parts)
  2. Fabricated parts — steel / acrylic detail + geometry bars
  3. Bought-in parts
  4. Labour operations (from costs_gbp / batch_hours when present)
  5. Cost summary

Usage:
    python -u src/generate_estimate_report.py --json "output/json/12242-01-GA Vue Sprung Cup Holder_revD.json"
    python -u src/generate_estimate_report.py --json "path/to/scan.json" --out-dir "output/reports"
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Helpers ───────────────────────────────────────────────────────────────────


def _sf(v: Any, dp: int = 2) -> str:
    try:
        return f"£{float(v):.{dp}f}" if v is not None else "—"
    except (TypeError, ValueError):
        return "—"


def _ff(v: Any, dp: int = 2, suffix: str = "") -> str:
    try:
        return f"{float(v):.{dp}f}{suffix}" if v is not None else "—"
    except (TypeError, ValueError):
        return "—"


def _s(v: Any) -> str:
    return str(v).strip() if v is not None else "—"


def _source_badge(ps: Dict) -> Tuple[str, str]:
    """Return (label, css_class): UDEF green, RAG amber, Config grey, Web red."""
    if not ps:
        return "Config default", "badge-config"
    src = str(ps.get("source_name") or ps.get("source") or ps.get("source_type") or "").lower()
    conf = float(ps.get("confidence") or 0)
    if "udef" in src:
        return "UDEF (SDI Catalogue)", "badge-udef"
    if "pma" in src or "erp" in src:
        return "ERP Parts Master", "badge-erp"
    if "workbook_sheet_steel" in src:
        return "Workbook Formula", "badge-wb"
    if "sqlserver" in src or "historical" in src or "spreadsheet" in src:
        return f"Historical RAG ({conf:.0%})", "badge-rag"
    if "supplier_catalog" in src:
        return "Supplier Catalogue", "badge-cat"
    if "web_scrape" in src:
        return "Web scrape Tier 5 ⚠", "badge-web"
    if "web" in src or "llm" in src:
        return "Web AI Estimate ⚠", "badge-web"
    if "bought_in" in src:
        return "SDI Bought-in List", "badge-udef"
    if "config" in src:
        return "Config default", "badge-config"
    return "Config default", "badge-config"


def _get_parts(d: Dict) -> List[Dict]:
    est = d.get("estimate_summary") or {}
    parts = est.get("part_estimates") or est.get("parts") or []
    if not parts:
        mfg = d.get("manufacturing_writeup") or {}
        parts = mfg.get("parts") or d.get("parts") or []
    return [p for p in parts if isinstance(p, dict) and p.get("part_number")]


def _get_mfg_part(d: Dict, pn: str) -> Dict:
    mfg = d.get("manufacturing_writeup") or {}
    for p in mfg.get("parts") or []:
        if str(p.get("part_number", "")).strip().upper() == str(pn).strip().upper():
            return p if isinstance(p, dict) else {}
    return {}


def _part_page_roles(p: Dict, d: Dict) -> List[str]:
    roles = p.get("page_roles")
    if roles:
        return list(roles) if isinstance(roles, list) else [str(roles)]
    m = _get_mfg_part(d, str(p.get("part_number") or ""))
    roles = m.get("page_roles") or []
    return list(roles) if isinstance(roles, list) else []


def _is_bought_in(p: Dict, d: Dict) -> bool:
    roles = _part_page_roles(p, d)
    if "bought_in" in roles:
        return True
    cb = p.get("cost_breakdown") or {}
    sc = cb.get("system_cost") or {}
    if sc.get("applied_to_total"):
        return True
    return False


def _is_assembly_only_placeholder(p: Dict, d: Dict) -> bool:
    roles = _part_page_roles(p, d)
    if not roles:
        return False
    if all(r == "assembly" for r in roles):
        try:
            unit = float(p.get("unit_total_cost_gbp") or 0)
        except (TypeError, ValueError):
            unit = 0.0
        return unit == 0.0
    return False


def _material_display(p: Dict, d: Dict) -> str:
    mpart = _get_mfg_part(d, str(p.get("part_number") or ""))
    mat = mpart.get("materials")
    if isinstance(mat, list) and mat:
        return _s(mat[0])
    if isinstance(mat, str) and mat:
        return _s(mat)
    me = p.get("material_estimate") or {}
    return _s(me.get("material") or p.get("normalized_material") or "")


def _is_steel_or_acrylic(p: Dict, d: Dict) -> bool:
    blob = (
        _material_display(p, d)
        + " "
        + _s(p.get("description"))
        + " "
        + _s(p.get("normalized_material"))
    ).upper()
    steel_kw = (
        "STEEL",
        "ZINTEC",
        "GALV",
        "STAINLESS",
        "SPCC",
        "METAL SHEET",
        "CR4",
        "DC01",
    )
    acry_kw = ("ACRYLIC", "PMMA", "PERSPEX", "HIAM", "HIGH IMPACT ACRYLIC")
    return any(k in blob for k in steel_kw) or any(k in blob for k in acry_kw)


def _drawing_title_meta(d: Dict) -> Tuple[str, str, str, str]:
    """drawing_no, description, client, revision."""
    meta = d.get("drawing_metadata") or d.get("document_analysis") or {}
    tb = meta.get("title_block") or {}
    mfg = d.get("manufacturing_writeup") or {}

    nums = tb.get("drawing_numbers")
    if isinstance(nums, list) and nums:
        dwg = _s(nums[0])
    else:
        dwg = _s(tb.get("drawing_number"))

    ps = d.get("pattern_summary") or {}
    if not dwg or dwg == "—":
        pn = ps.get("drawing_numbers")
        if isinstance(pn, list) and pn:
            dwg = _s(pn[0])
        elif pn:
            dwg = _s(pn)

    desc = _s(tb.get("description") or mfg.get("document_overview", {}).get("description") or "")
    client = _s(tb.get("client") or "")
    rev = _s(tb.get("revision") or "")
    revs = tb.get("revisions")
    if (not rev or rev == "—") and isinstance(revs, list) and revs:
        rev = _s(revs[0])
    return dwg, desc, client, rev


def _collect_labour_operations(parts: List[Dict]) -> Dict[str, Dict[str, Any]]:
    """Aggregate per-operation hours and cost across parts (estimator labour_estimate shape)."""
    all_ops: Dict[str, Dict[str, Any]] = {}
    for p in parts:
        pn = p.get("part_number")
        le = p.get("labour_estimate") or {}
        nested = le.get("operations") or le.get("labour_by_operation") or {}
        if isinstance(nested, dict) and nested:
            for op_name, op_data in nested.items():
                if not isinstance(op_data, dict):
                    continue
                bucket = all_ops.setdefault(op_name, {"parts": [], "total_hours": 0.0, "total_cost": 0.0})
                bucket["parts"].append(pn)
                bucket["total_hours"] += float(op_data.get("hours") or op_data.get("time_hrs") or 0)
                bucket["total_cost"] += float(op_data.get("cost_gbp") or op_data.get("cost") or 0)
            continue

        costs = le.get("costs_gbp") or {}
        hours = le.get("batch_hours") or {}
        if not isinstance(costs, dict):
            continue
        for op_name, cost in costs.items():
            try:
                c = float(cost)
            except (TypeError, ValueError):
                continue
            bucket = all_ops.setdefault(str(op_name), {"parts": [], "total_hours": 0.0, "total_cost": 0.0})
            bucket["parts"].append(pn)
            bucket["total_cost"] += c
            hv = hours.get(op_name) if isinstance(hours, dict) else None
            try:
                bucket["total_hours"] += float(hv) if hv is not None else 0.0
            except (TypeError, ValueError):
                pass

    return all_ops


def _unit_labour_gbp(le: Dict) -> float:
    """Per-unit labour (estimator uses total_labour_cost_gbp as the unit sum)."""
    if not isinstance(le, dict):
        return 0.0
    v = le.get("unit_labour_cost_gbp")
    if v is None:
        v = le.get("total_labour_cost_gbp")
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _ext_labour_gbp(le: Dict, qty: int) -> float:
    q = max(1, int(qty))
    if isinstance(le, dict):
        ext = le.get("extended_labour_cost_gbp")
        if ext is not None:
            try:
                return float(ext)
            except (TypeError, ValueError):
                pass
    return _unit_labour_gbp(le if isinstance(le, dict) else {}) * q


CSS = """
:root {
    --navy:   #1A2E44;
    --green:  #0F6E56;
    --light:  #F4F7FA;
    --border: #D0D9E3;
    --text:   #1A2E44;
    --muted:  #6B7D8F;
    --amber:  #D97706;
    --red:    #DC2626;
    --ok:     #059669;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px;
       color: var(--text); background: #fff; }
.page { max-width: 1200px; margin: 0 auto; padding: 24px; }

.hdr { background: var(--navy); color: #fff; padding: 20px 28px;
       border-radius: 8px; margin-bottom: 20px;
       display: flex; justify-content: space-between; align-items: flex-start; }
.hdr h1 { font-size: 20px; margin-bottom: 6px; }
.hdr .meta { font-size: 12px; opacity: .8; line-height: 1.8; }
.hdr .total-box { background: var(--green); border-radius: 8px;
                  padding: 14px 20px; text-align: center; min-width: 160px; }
.hdr .total-box .label { font-size: 11px; opacity: .85; }
.hdr .total-box .amount { font-size: 26px; font-weight: 700; }
.hdr .total-box .qty { font-size: 11px; opacity: .75; margin-top: 2px; }

.stats { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.stat { background: var(--light); border: 1px solid var(--border);
        border-radius: 6px; padding: 12px 16px; flex: 1; min-width: 130px; }
.stat .s-label { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
.stat .s-value { font-size: 18px; font-weight: 600; color: var(--navy); }

.section { margin-bottom: 28px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--navy);
                 border-bottom: 2px solid var(--green); padding-bottom: 6px;
                 margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.section-title .count { background: var(--green); color: #fff; border-radius: 20px;
                         padding: 2px 8px; font-size: 11px; }

table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { background: var(--navy); color: #fff; padding: 8px 10px;
     text-align: left; font-weight: 500; white-space: nowrap; }
th.r, td.r { text-align: right; }
th.c, td.c { text-align: center; }
td { padding: 7px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
tr:hover td { background: #F0F5FA; }
tr.sub td { background: var(--light); font-weight: 500; }
tr.total-row td { background: var(--navy); color: #fff; font-weight: 600; }
tr.bought-in td { background: #FFFBF0; }
tr.assembly td { background: #F0FFF4; color: var(--muted); font-style: italic; }

.badge { display: inline-block; padding: 2px 7px; border-radius: 10px;
         font-size: 10px; font-weight: 500; white-space: nowrap; }
.badge-udef  { background: #D1FAE5; color: #065F46; }
.badge-erp   { background: #DBEAFE; color: #1E40AF; }
.badge-wb    { background: #E0E7FF; color: #3730A3; }
.badge-rag   { background: #FEF3C7; color: #92400E; }
.badge-cat   { background: #FCE7F3; color: #9D174D; }
.badge-web   { background: #FEE2E2; color: #991B1B; }
.badge-config{ background: #F3F4F6; color: #6B7280; }

.role { display: inline-block; padding: 1px 6px; border-radius: 3px;
        font-size: 10px; font-weight: 500; }
.role-detail   { background: #DBEAFE; color: #1E40AF; }
.role-assembly { background: #D1FAE5; color: #065F46; }
.role-bought   { background: #FEF3C7; color: #92400E; }

.ops { display: flex; flex-wrap: wrap; gap: 3px; }
.op  { background: #E0E7FF; color: #3730A3; padding: 1px 6px;
       border-radius: 3px; font-size: 10px; }

.geo-bar { display: flex; align-items: center; gap: 6px; }
.geo-bg  { flex: 1; background: var(--border); border-radius: 3px; height: 6px; max-width: 80px; }
.geo-fill{ height: 6px; border-radius: 3px; background: var(--green); }

.footer { text-align: center; color: var(--muted); font-size: 11px;
          margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border); }
"""


def build_html(d: Dict, source_file: str) -> str:
    est = d.get("estimate_summary") or {}
    mfg = d.get("manufacturing_writeup") or {}
    dwg_no, desc, client, rev = _drawing_title_meta(d)

    source_stem = Path(source_file).stem
    title_line = dwg_no if dwg_no and dwg_no != "—" else source_stem

    est_qty = est.get("quantity")
    doc_qty = d.get("assumed_job_quantity")
    try:
        qty = int(est_qty if est_qty is not None else doc_qty or 1)
    except (TypeError, ValueError):
        qty = 1

    geo_rel = 0.0
    gs = d.get("geometry_summary") or {}
    if isinstance(gs.get("document_geometry_reliability"), (int, float)):
        geo_rel = float(gs["document_geometry_reliability"])
    elif mfg.get("geometry_reliability"):
        try:
            geo_rel = float(mfg["geometry_reliability"])
        except (TypeError, ValueError):
            geo_rel = 0.0

    parts = _get_parts(d)
    bought_in_list = [p for p in parts if _is_bought_in(p, d)]
    fabricated_count = len([p for p in parts if not _is_bought_in(p, d)])

    doc_total_val = 0.0
    for p in parts:
        try:
            doc_total_val += float(p.get("extended_total_cost_gbp") or p.get("unit_total_cost_gbp") or 0)
        except (TypeError, ValueError):
            pass
    if doc_total_val == 0:
        try:
            doc_total_val = float(est.get("total_cost_gbp") or est.get("document_total_cost_gbp") or 0)
        except (TypeError, ValueError):
            doc_total_val = 0.0

    now = datetime.now().strftime("%d %b %Y %H:%M")

    h: List[str] = []
    h.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SDIAIVision Estimate — {source_stem}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">

<div class="hdr">
  <div>
    <h1>SDIAIVision — AI Estimate Report</h1>
    <div class="meta">
      <div><strong>Drawing:</strong> {title_line}</div>
      <div><strong>Source file:</strong> {source_stem}</div>
      {f"<div><strong>Client:</strong> {client}</div>" if client and client != "—" else ""}
      {f"<div><strong>Description:</strong> {desc}</div>" if desc and desc != "—" else ""}
      {f"<div><strong>Revision:</strong> {rev}</div>" if rev and rev != "—" else ""}
      <div><strong>Reference quantity:</strong> {qty}</div>
      <div><strong>Generated:</strong> {now}</div>
    </div>
  </div>
  <div class="total-box">
    <div class="label">TOTAL ESTIMATE</div>
    <div class="amount">{_sf(doc_total_val)}</div>
    <div class="qty">for qty {qty}</div>
  </div>
</div>

<div class="stats">
  <div class="stat">
    <div class="s-label">Total parts</div>
    <div class="s-value">{len(parts)}</div>
  </div>
  <div class="stat">
    <div class="s-label">Fabricated</div>
    <div class="s-value">{fabricated_count}</div>
  </div>
  <div class="stat">
    <div class="s-label">Bought-in</div>
    <div class="s-value">{len(bought_in_list)}</div>
  </div>
  <div class="stat">
    <div class="s-label">Geometry reliability</div>
    <div class="s-value">{geo_rel:.0%}</div>
  </div>
</div>
""")

    # SECTION 1
    h.append(f"""
<div class="section">
  <div class="section-title">
    Full Bill of Materials — Cost Summary
    <span class="count">{len(parts)} items</span>
  </div>
  <table>
    <thead>
      <tr>
        <th>Part number</th>
        <th>Description</th>
        <th class="c">Qty</th>
        <th>Role</th>
        <th>Material</th>
        <th class="c">Thk (mm)</th>
        <th>Operations</th>
        <th class="r">Unit mat £</th>
        <th class="r">Unit lab £</th>
        <th class="r">Unit total £</th>
        <th class="r">Extended £</th>
        <th>Price source</th>
      </tr>
    </thead>
    <tbody>
""")

    mat_subtotal = lab_subtotal = bom_total = 0.0

    for p in parts:
        pn = _s(p.get("part_number"))
        pdesc = _s(p.get("description"))
        qty_p_raw = p.get("quantity")
        try:
            qty_p = int(qty_p_raw) if qty_p_raw is not None else 1
        except (TypeError, ValueError):
            qty_p = 1
        mpart = _get_mfg_part(d, pn)
        thk = _s(mpart.get("normalized_thickness_mm") or p.get("normalized_thickness_mm") or "")
        mat_str = _material_display(p, d)
        ops_raw = mpart.get("textual_operations") or mpart.get("operations") or []
        ops_list = (
            [str(o).replace("_", " ").title() for o in ops_raw] if isinstance(ops_raw, list) else []
        )

        cb = p.get("cost_breakdown") or {}
        me = p.get("material_estimate") or {}
        le = p.get("labour_estimate") or {}
        sc = cb.get("system_cost") or {}

        unit_mat = float(me.get("unit_material_cost_gbp") or (cb.get("material") or {}).get("unit_material_cost_gbp") or 0)
        unit_lab = _unit_labour_gbp(le)
        unit_sys = float(sc.get("unit_cost_gbp") or 0)
        unit_tot = float(p.get("unit_total_cost_gbp") or unit_mat + unit_lab + unit_sys)
        ext_tot = float(p.get("extended_total_cost_gbp") or unit_tot * qty_p)

        if sc.get("applied_to_total"):
            ps_src = sc.get("source") or {}
        else:
            ps_src = me.get("price_source") or {}
        badge_label, badge_class = _source_badge(ps_src if isinstance(ps_src, dict) else {})

        try:
            mat_subtotal += float(me.get("extended_material_cost_gbp") or unit_mat * qty_p)
        except (TypeError, ValueError):
            pass
        try:
            lab_subtotal += float(_ext_labour_gbp(le, qty_p))
        except (TypeError, ValueError):
            pass
        bom_total += ext_tot

        if _is_bought_in(p, d):
            row_class = "bought-in"
            role_tag = '<span class="role role-bought">Bought-in</span>'
        elif _is_assembly_only_placeholder(p, d):
            row_class = "assembly"
            role_tag = '<span class="role role-assembly">Assembly</span>'
        else:
            row_class = ""
            role_tag = '<span class="role role-detail">Fabricated</span>'

        ops_html = (
            '<div class="ops">' + "".join(f'<span class="op">{o}</span>' for o in ops_list) + "</div>"
            if ops_list
            else "—"
        )

        mat_cell = "—" if unit_mat == 0 and not _is_bought_in(p, d) else _sf(unit_mat)
        h.append(f"""      <tr class="{row_class}">
        <td><strong>{pn}</strong></td>
        <td>{pdesc}</td>
        <td class="c">{qty_p}</td>
        <td>{role_tag}</td>
        <td>{mat_str if mat_str != "—" else ""}</td>
        <td class="c">{thk if thk != "—" else ""}</td>
        <td>{ops_html}</td>
        <td class="r">{mat_cell}</td>
        <td class="r">{"—" if unit_lab == 0 else _sf(unit_lab)}</td>
        <td class="r">{_sf(unit_tot) if unit_tot > 0 else "—"}</td>
        <td class="r"><strong>{_sf(ext_tot) if ext_tot > 0 else "—"}</strong></td>
        <td><span class="badge {badge_class}">{badge_label}</span></td>
      </tr>
""")

    h.append(f"""      <tr class="total-row">
        <td colspan="7"><strong>Totals</strong></td>
        <td class="r"><strong>{_sf(mat_subtotal)}</strong></td>
        <td class="r"><strong>{_sf(lab_subtotal)}</strong></td>
        <td class="r"></td>
        <td class="r"><strong>{_sf(bom_total)}</strong></td>
        <td></td>
      </tr>
    </tbody>
  </table>
</div>
""")

    # SECTION 2 — steel / acrylic fabricated only
    fab_parts = [
        p
        for p in parts
        if not _is_bought_in(p, d)
        and not _is_assembly_only_placeholder(p, d)
        and _is_steel_or_acrylic(p, d)
    ]
    if fab_parts:
        h.append(f"""
<div class="section">
  <div class="section-title">
    Fabricated parts — steel / acrylic detail
    <span class="count">{len(fab_parts)} parts</span>
  </div>
  <table>
    <thead>
      <tr>
        <th>Part</th>
        <th>Description</th>
        <th class="c">Qty</th>
        <th>Material</th>
        <th class="r">Weight (kg)</th>
        <th class="r">Mat / unit</th>
        <th class="r">Mat ext</th>
        <th class="r">Lab / unit</th>
        <th class="r">Lab ext</th>
        <th class="r">Unit total</th>
        <th class="r">Extended</th>
        <th>Geo source</th>
        <th class="c">Geometry</th>
      </tr>
    </thead>
    <tbody>
""")
        for p in fab_parts:
            pn_b = _s(p.get("part_number"))
            desc_b = _s(p.get("description"))
            try:
                qty_b = int(p.get("quantity") or 1)
            except (TypeError, ValueError):
                qty_b = 1
            mpart_b = _get_mfg_part(d, pn_b)
            mat_b = _material_display(p, d)
            cb_b = p.get("cost_breakdown") or {}
            me_b = p.get("material_estimate") or {}
            le_b = p.get("labour_estimate") or {}

            weight = float(
                me_b.get("unit_material_mass_kg") or (cb_b.get("material") or {}).get("unit_material_mass_kg") or 0
            )
            unit_mat_b = float(
                me_b.get("unit_material_cost_gbp") or (cb_b.get("material") or {}).get("unit_material_cost_gbp") or 0
            )
            ext_mat_b = float(me_b.get("extended_material_cost_gbp") or unit_mat_b * qty_b)
            unit_lab_b = _unit_labour_gbp(le_b)
            ext_lab_b = _ext_labour_gbp(le_b, qty_b)
            unit_tot_b = float(p.get("unit_total_cost_gbp") or unit_mat_b + unit_lab_b)
            ext_tot_b = float(p.get("extended_total_cost_gbp") or unit_tot_b * qty_b)

            geo_src = _s(mpart_b.get("geometry_source") or p.get("geometry_source") or "pdf")
            rollup = mpart_b.get("geometry_rollup") or p.get("geometry_rollup") or {}
            conf = rollup.get("confidence") if isinstance(rollup, dict) else {}
            geo_score = float(
                p.get("geometry_score")
                or (conf.get("geometry_reliability") if isinstance(conf, dict) else 0)
                or 0
            )
            geo_fill = max(0, min(100, int(round(geo_score * 100))))
            geo_color = "#059669" if geo_score >= 0.95 else ("#D97706" if geo_score >= 0.7 else "#DC2626")

            h.append(f"""      <tr>
        <td><strong>{pn_b}</strong></td>
        <td>{desc_b}</td>
        <td class="c">{qty_b}</td>
        <td>{mat_b}</td>
        <td class="r">{_ff(weight, 4) if weight > 0 else "—"}</td>
        <td class="r">{_sf(unit_mat_b) if unit_mat_b > 0 else "—"}</td>
        <td class="r">{_sf(ext_mat_b) if ext_mat_b > 0 else "—"}</td>
        <td class="r">{_sf(unit_lab_b) if unit_lab_b > 0 else "—"}</td>
        <td class="r">{_sf(ext_lab_b) if ext_lab_b > 0 else "—"}</td>
        <td class="r"><strong>{_sf(unit_tot_b) if unit_tot_b > 0 else "—"}</strong></td>
        <td class="r"><strong>{_sf(ext_tot_b) if ext_tot_b > 0 else "—"}</strong></td>
        <td style="font-size:11px">{geo_src}</td>
        <td class="c">
          <div class="geo-bar">
            <div class="geo-bg"><div class="geo-fill" style="width:{geo_fill}%;background:{geo_color}"></div></div>
            <span style="font-size:10px;color:{geo_color}">{geo_fill}%</span>
          </div>
        </td>
      </tr>
""")
        h.append("    </tbody>\n  </table>\n</div>\n")

    # SECTION 3
    if bought_in_list:
        h.append(f"""
<div class="section">
  <div class="section-title">
    Bought-in parts &amp; components
    <span class="count">{len(bought_in_list)} items</span>
  </div>
  <table>
    <thead>
      <tr>
        <th>Part code</th>
        <th>Description</th>
        <th class="c">Qty</th>
        <th class="r">Unit price</th>
        <th class="r">Extended</th>
        <th>Price source</th>
        <th>Supplier</th>
      </tr>
    </thead>
    <tbody>
""")
        bi_total = 0.0
        for p in bought_in_list:
            pn_c = _s(p.get("part_number"))
            desc_c = _s(p.get("description"))
            try:
                qty_c = int(p.get("quantity") or 1)
            except (TypeError, ValueError):
                qty_c = 1
            cb_c = p.get("cost_breakdown") or {}
            sc_c = cb_c.get("system_cost") or {}
            me_c = p.get("material_estimate") or {}

            unit_p = float(
                sc_c.get("unit_cost_gbp") or p.get("unit_total_cost_gbp") or me_c.get("unit_material_cost_gbp") or 0
            )
            ext_p = float(p.get("extended_total_cost_gbp") or unit_p * qty_c)
            bi_total += ext_p

            ps_src = sc_c.get("source") or me_c.get("price_source") or {}
            badge_label_c, badge_class_c = _source_badge(ps_src if isinstance(ps_src, dict) else {})
            supplier = ""
            if isinstance(ps_src, dict):
                supplier = _s(ps_src.get("supplier_source") or ps_src.get("supplier_name") or sc_c.get("supplier_name"))

            h.append(f"""      <tr class="bought-in">
        <td><strong>{pn_c}</strong></td>
        <td>{desc_c}</td>
        <td class="c">{qty_c}</td>
        <td class="r">{_sf(unit_p) if unit_p > 0 else "—"}</td>
        <td class="r"><strong>{_sf(ext_p) if ext_p > 0 else "—"}</strong></td>
        <td><span class="badge {badge_class_c}">{badge_label_c}</span></td>
        <td style="font-size:11px">{supplier if supplier != "—" else ""}</td>
      </tr>
""")
        h.append(f"""      <tr class="sub">
        <td colspan="4"><strong>Bought-in subtotal</strong></td>
        <td class="r"><strong>{_sf(bi_total)}</strong></td>
        <td colspan="2"></td>
      </tr>
    </tbody>
  </table>
</div>
""")

    # SECTION 4
    all_ops = _collect_labour_operations(parts)

    if all_ops:
        h.append(f"""
<div class="section">
  <div class="section-title">
    Labour route — operations breakdown
    <span class="count">{len(all_ops)} operations</span>
  </div>
  <table>
    <thead>
      <tr>
        <th>Operation</th>
        <th>Applies to parts</th>
        <th class="r">Total hours</th>
        <th class="r">Total cost</th>
      </tr>
    </thead>
    <tbody>
""")
        lab_grand = 0.0
        for op_name, op_data in sorted(all_ops.items()):
            parts_str = ", ".join(str(x) for x in op_data["parts"] if x)
            h.append(f"""      <tr>
        <td><strong>{str(op_name).replace("_", " ").title()}</strong></td>
        <td style="font-size:11px">{parts_str}</td>
        <td class="r">{_ff(op_data["total_hours"], 3)}</td>
        <td class="r">{_sf(op_data["total_cost"])}</td>
      </tr>
""")
            lab_grand += op_data["total_cost"]
        h.append(f"""      <tr class="sub">
        <td colspan="3"><strong>Labour total (allocated)</strong></td>
        <td class="r"><strong>{_sf(lab_grand)}</strong></td>
      </tr>
    </tbody>
  </table>
</div>
""")
    else:
        h.append("""
<div class="section">
  <div class="section-title">Labour route — operations breakdown</div>
  <p style="color:var(--muted);font-size:12px;">No per-operation labour breakdown in this JSON (empty
  <code>labour_estimate.costs_gbp</code> on all parts).</p>
</div>
""")

    bi_sum = sum(float(p.get("extended_total_cost_gbp") or 0) for p in bought_in_list)

    h.append(f"""
<div class="section">
  <div class="section-title">Cost summary</div>
  <table style="max-width:500px">
    <tbody>
      <tr class="sub">
        <td>Material subtotal</td>
        <td class="r"><strong>{_sf(mat_subtotal)}</strong></td>
      </tr>
      <tr class="sub">
        <td>Labour subtotal</td>
        <td class="r"><strong>{_sf(lab_subtotal)}</strong></td>
      </tr>
      <tr class="sub">
        <td>Bought-in subtotal</td>
        <td class="r"><strong>{_sf(bi_sum)}</strong></td>
      </tr>
      <tr class="total-row">
        <td><strong>Total manufacturing cost (qty {qty})</strong></td>
        <td class="r"><strong>{_sf(doc_total_val)}</strong></td>
      </tr>
    </tbody>
  </table>
</div>

<div class="footer">
  Generated by SDIAIVision · {now} · <em>AI estimate — review required before quoting</em>
</div>

</div>
</body>
</html>""")

    return "".join(h)


def build_csv(d: Dict) -> List[List[Any]]:
    parts = _get_parts(d)
    rows: List[List[Any]] = [
        [
            "Part number",
            "Description",
            "Qty",
            "Role",
            "Material",
            "Thickness (mm)",
            "Operations",
            "Weight (kg)",
            "Unit mat £",
            "Ext mat £",
            "Unit labour £",
            "Ext labour £",
            "Unit total £",
            "Extended £",
            "Price source",
            "Supplier",
        ]
    ]
    for p in parts:
        pn = p.get("part_number", "")
        desc = p.get("description", "")
        qty_p = p.get("quantity") or 1
        if _is_bought_in(p, d):
            role = "bought_in"
        elif _is_assembly_only_placeholder(p, d):
            role = "assembly"
        else:
            role = "fabricated"
        mpart = _get_mfg_part(d, str(pn))
        mat = (mpart.get("materials") or [""])[0] if isinstance(mpart.get("materials"), list) else mpart.get("materials", "")
        thk = mpart.get("normalized_thickness_mm", "")
        ops = ", ".join(str(x) for x in (mpart.get("textual_operations") or []))
        cb = p.get("cost_breakdown") or {}
        me = p.get("material_estimate") or {}
        le = p.get("labour_estimate") or {}
        sc = cb.get("system_cost") or {}
        weight = me.get("unit_material_mass_kg", "")
        unit_mat = me.get("unit_material_cost_gbp") or (cb.get("material") or {}).get("unit_material_cost_gbp", "")
        ext_mat = me.get("extended_material_cost_gbp", "")
        unit_lab = _unit_labour_gbp(le)
        ext_lab = _ext_labour_gbp(le, qty_p)
        unit_tot = p.get("unit_total_cost_gbp", "")
        ext_tot = p.get("extended_total_cost_gbp", "")
        ps_src = sc.get("source") or me.get("price_source") or {}
        badge, _ = _source_badge(ps_src if isinstance(ps_src, dict) else {})
        supplier = ps_src.get("supplier_source", "") if isinstance(ps_src, dict) else ""
        rows.append(
            [
                pn,
                desc,
                qty_p,
                role,
                mat,
                thk,
                ops,
                weight,
                unit_mat,
                ext_mat,
                unit_lab,
                ext_lab,
                unit_tot,
                ext_tot,
                badge,
                supplier,
            ]
        )
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate SDIAIVision estimate report (HTML + CSV)")
    parser.add_argument("--json", required=True, help="Path to scan JSON")
    parser.add_argument("--out-dir", default=None, help="Output directory (default: <repo>/output/reports)")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print part count and output paths to stderr",
    )
    args = parser.parse_args(argv)

    json_path = Path(args.json).expanduser().resolve()
    if not json_path.is_file():
        print(f"ERROR: {json_path} not found", file=sys.stderr)
        return 1

    repo_root = Path(__file__).resolve().parent.parent
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else (repo_root / "output" / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    d = json.loads(json_path.read_text(encoding="utf-8"))
    stem = json_path.stem
    if args.verbose:
        n = len(_get_parts(d))
        print(f"[generate_estimate_report] parts in BOM table: {n}", file=sys.stderr)

    html_path = out_dir / f"{stem}.estimate_report.html"
    html_path.write_text(build_html(d, str(json_path)), encoding="utf-8")
    print(f"HTML report: {html_path}")

    csv_path = out_dir / f"{stem}.estimate_report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(build_csv(d))
    print(f"CSV report:  {csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
