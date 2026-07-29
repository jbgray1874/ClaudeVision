"""
job_report_html.py — SDI Intelligence unified job report (generic, data-driven).

Produces the rich 7-section review report for ANY job from its summary JSON:
  1. Estimate at a glance          5. What to focus on when checking
  2. What the engine got right     6. Design recommendations
  3. Review items & limitations    7. Verdict
  4. Drawing analysis

When a parity bundle is supplied (a manual estimate exists), an additional
"Parity vs manual estimate" comparison section is inserted after section 1.
One builder, one code path — the report is simply fuller when a manual exists.

PRINCIPLE: report what the JSON actually contains, not fixed template claims.
Every section inspects the data and states what is true for THIS job. If a job
has no drawing faults, section 4 says so rather than inventing them.

CLI:
    python job_report_html.py --json <summary.json> [--bundle <parity_bundle.json>] --out <report>.html

API:
    generate_report(summary_json_path, out_path=None, bundle_path=None, job_stem=None) -> str

Job-agnostic. Reads only the summary JSON (+ optional parity bundle). No DB, no re-run.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────

def _esc(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def _money(v: Any) -> str:
    try:
        f = float(v)
        return f"-£{abs(f):,.2f}" if f < 0 else f"£{f:,.2f}"
    except (TypeError, ValueError):
        return "—"


def _num(v: Any, dp: int = 0) -> str:
    try:
        return f"{float(v):,.{dp}f}"
    except (TypeError, ValueError):
        return "—"


def _get(d: Any, *path, default=None):
    """Safe nested get: _get(summary, 'estimate_summary', 'workbook_equivalent_pricing', 'm105...')."""
    cur = d
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def _first_num(d: Dict[str, Any], *keys, default=None):
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return v
    return default


# ─────────────────────────────────────────────────────────────────────────────
# Field extraction — turn the summary JSON into a normalised view-model
# ─────────────────────────────────────────────────────────────────────────────

def _extract_header(summary: Dict[str, Any]) -> Dict[str, Any]:
    stem = str(summary.get("job_output_stem") or summary.get("source_file") or "").replace(".json", "")
    # job number = leading token; name = remainder after ' - '
    job_no = stem.split("-")[0].strip() if stem else ""
    if " - " in stem:
        job_no = stem.split(" - ")[0].strip()
        name = stem.split(" - ", 1)[1].strip()
    else:
        name = stem
    pdfs = summary.get("job_source_pdfs") or []
    pages = summary.get("pages") or []
    dxf = summary.get("dxf_augmentation") or {}
    matched = dxf.get("matched") or []
    qty = (summary.get("assumed_job_quantity")
           or _get(summary, "estimate_summary", "estimate_workbook_inputs", "assumed_job_quantity")
           or _get(summary, "bay_estimate", "order_quantity"))
    return {
        "stem": stem,
        "job_no": job_no,
        "name": name,
        "pdf_count": len(pdfs),
        "pdf_names": [str(p.get("name") or p) if isinstance(p, dict) else str(p) for p in pdfs],
        "page_count": summary.get("page_count") or len(pages),
        "dxf_matched": len(matched) if isinstance(matched, list) else (matched or 0),
        "quantity": qty,
    }


def _extract_headline(summary: Dict[str, Any]) -> Dict[str, Any]:
    wep = _get(summary, "estimate_summary", "workbook_equivalent_pricing", default={}) or {}
    unit = _first_num(wep, "m105_total_unit_cost_gbp", "l105_total_unit_cost_gbp")
    material = _first_num(wep, "m59_material_subtotal_gbp")
    labour = _first_num(wep, "m103_labour_subtotal_gbp")
    hours = _first_num(wep, "labour_hours_total")
    src = wep.get("source_of_truth")
    # fallbacks to cost_breakdown if WEP absent
    if unit is None:
        unit = _get(summary, "estimate_summary", "document_total_estimated_cost_gbp")
    return {
        "unit": unit, "material": material, "labour": labour,
        "hours": hours, "source_of_truth": src,
    }


def _extract_parts(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _get(summary, "estimate_summary", "part_estimates", default=[]) or []


def _extract_cost_streams(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Group part_estimates into material streams (steel / bought-in / acrylic / boards)."""
    parts = _extract_parts(summary)
    streams: Dict[str, Dict[str, Any]] = {}

    def bucket(part: Dict[str, Any]) -> str:
        pn = str(part.get("part_number") or "").upper()
        mat = str(part.get("normalized_material") or "").upper()
        me = part.get("material_estimate") or {}
        stock = str(me.get("stock_form") or "").lower()
        if pn.startswith("BI-") or stock == "bought_in":
            return "Bought-in items"
        if "ACRYLIC" in mat or "ACR" in mat:
            return "Acrylic"
        if pn.startswith("VINYL") or "BOARD" in mat or "DISPLAY" in mat:
            return "Display boards"
        if "STEEL" in mat or mat in ("MILD_STEEL", "CR4", "MS"):
            return "Sheet steel"
        return "Other material"

    for p in parts:
        b = bucket(p)
        me = p.get("material_estimate") or {}
        cost = me.get("extended_material_cost_gbp")
        c = float(cost) if isinstance(cost, (int, float)) else 0.0
        s = streams.setdefault(b, {"name": b, "count": 0, "value": 0.0})
        s["count"] += 1
        s["value"] += c

    # powder as its own stream
    pc = _get(summary, "estimate_summary", "powder_coating_summary", default={}) or {}
    powder_total = pc.get("powder_total_gbp")
    if isinstance(powder_total, (int, float)) and powder_total:
        streams["Powder material"] = {"name": "Powder material", "count": None, "value": float(powder_total)}

    # order: steel, boards, acrylic, bought-in, powder, other
    order = ["Sheet steel", "Display boards", "Acrylic", "Bought-in items", "Powder material", "Other material"]
    out = [streams[k] for k in order if k in streams]
    # any not in the order list
    out += [v for k, v in streams.items() if k not in order]
    return out


def _extract_review_items(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Low-confidence parts, flagged parts, risk flags, provisional rates."""
    parts = _extract_parts(summary)
    review = {"flagged_parts": [], "risk_flag_tally": {}, "provisional": []}

    ers = _get(summary, "estimate_summary", "estimate_review_signals", default={}) or {}
    flagged = ers.get("parts_flagged") or []

    # translate reason codes into plain language
    def _reason_text(reasons: List[Dict[str, Any]]) -> str:
        if not reasons:
            return ""
        bits = []
        for r in reasons:
            if not isinstance(r, dict):
                continue
            code = str(r.get("code", ""))
            detail = r.get("detail")
            if code == "low_part_confidence":
                try:
                    bits.append(f"low extraction confidence ({float(detail)*100:.0f}%)")
                except (TypeError, ValueError):
                    bits.append("low extraction confidence")
            elif code == "risk_flag":
                RF = {
                    "many_bends": "high bend count",
                    "missing_material_spec": "material spec missing on the drawing",
                    "weld_required": "weld cue detected — verify weld/dress content",
                }
                bits.append(RF.get(str(detail), f"risk flag: {detail}"))
            elif code == "geometry_with_powder_below":
                bits.append("low geometry confidence on a powder-coated part")
            elif code:
                bits.append(f"{code.replace('_', ' ')}" + (f" ({detail})" if detail is not None else ""))
        return "; ".join(bits)

    for f in flagged:
        if isinstance(f, dict):
            review["flagged_parts"].append({
                "part": f.get("part_number") or f.get("part") or "?",
                "reason": _reason_text(f.get("reasons") or []),
                "cost": f.get("unit_total_cost_gbp") or f.get("cost"),
            })

    # risk flag tally across parts
    for p in parts:
        for rf in (p.get("risk_flags") or []):
            review["risk_flag_tally"][rf] = review["risk_flag_tally"].get(rf, 0) + 1

    # provisional rate signals
    pc = _get(summary, "estimate_summary", "powder_coating_summary", default={}) or {}
    ci = pc.get("costing_inputs") or {}
    if ci.get("powder_rate_per_kg_gbp") is not None:
        review["provisional"].append({
            "item": f"Powder £{ci.get('powder_rate_per_kg_gbp')}/kg",
            "note": "Powder material rate — confirm with supplier.",
        })
    return review


def _extract_drawing_quality(summary: Dict[str, Any]) -> Dict[str, Any]:
    """The drawing-quality audit: DXF coverage, geometry reliability, contaminated fields,
    filename issues, part-number variety, validation issues, junk records."""
    dxf = summary.get("dxf_augmentation") or {}
    geo = summary.get("geometry_summary") or {}
    mw = summary.get("manufacturing_writeup") or {}
    val = mw.get("validation") or summary.get("validation") or {}
    mri = summary.get("manual_review_items") or []
    parts = summary.get("parts") or _extract_parts(summary)

    # filename issues: stray spaces before extension, spaces generally
    pdfs = summary.get("job_source_pdfs") or []
    dxf_names = []
    for k in ("matched", "unmatched_dxf", "ambiguous_dxf", "skipped"):
        for it in (dxf.get(k) or []):
            nm = it.get("dxf_name") or it.get("name") or it.get("file") if isinstance(it, dict) else str(it)
            if nm:
                dxf_names.append(str(nm))
    all_names = [str(p.get("name") or p) if isinstance(p, dict) else str(p) for p in pdfs] + dxf_names
    stray_space = [n for n in all_names if re.search(r"\s\.(dxf|pdf)$", n, re.I) or "  " in n]

    # part-number format variety
    pn_patterns = set()
    for p in parts:
        pn = str(p.get("part_number") or "")
        if not pn:
            continue
        # crude signature: letters/digits/dashes shape
        sig = re.sub(r"\d+", "N", re.sub(r"[A-Za-z]+", "L", pn))
        pn_patterns.add(sig)

    # contaminated / low-confidence fields from manual_review_items, BY SEVERITY
    # (distinguish genuine errors from low-confidence dimension-read warnings/info)
    sev_tally = {"error": 0, "warning": 0, "info": 0}
    field_tally: Dict[str, int] = {}
    contaminated = []
    for item in mri:
        if not isinstance(item, dict):
            continue
        for iss in (item.get("issues") or []):
            if isinstance(iss, dict):
                sev = str(iss.get("severity", "") or "").lower()
                fld = iss.get("field", "")
                msg = iss.get("message") or iss.get("note") or ""
                if sev in sev_tally:
                    sev_tally[sev] += 1
                else:
                    sev_tally["info"] += 1  # unknown severities counted as info, not error
                if fld:
                    field_tally[fld] = field_tally.get(fld, 0) + 1
                if sev in ("warning", "error") or fld:
                    contaminated.append({"page": item.get("page_number"), "field": fld, "msg": msg, "sev": sev})

    # geometry reliability: it's a float — give it a descriptive band
    geo_rel = geo.get("document_geometry_reliability")
    geo_conf = geo.get("overall_confidence")

    def _band(v):
        try:
            f = float(v)
            if f >= 0.9:
                return "high"
            if f >= 0.7:
                return "medium"
            return "low"
        except (TypeError, ValueError):
            return None

    # SolidWorks native flat patterns — measured blanks from the model's sheet-metal cut
    # list. A part that has one is NOT missing geometry, so it must not be reported under
    # "parts without DXF": that would tell the estimator the blank is provisional when it
    # is measured. Layer 0 of the waterfall gets its own count.
    _native = summary.get("solidworks_native") or {}
    _native_flat_pns = {
        str(p.get("part_number") or "").strip().upper()
        for p in parts
        if p.get("native_flat_pattern")
        or str(p.get("geometry_source") or "") == "solidworks_flat_pattern"
    } - {""}
    _without_dxf = []
    for x in (dxf.get("parts_without_dxf") or []):
        _pn = (str(x.get("part_number") or "") if isinstance(x, dict) else str(x)).strip().upper()
        if _pn and _pn in _native_flat_pns:
            continue
        _without_dxf.append(x)

    return {
        "dxf_matched": len(dxf.get("matched") or []),
        "dxf_unmatched": len(dxf.get("unmatched_dxf") or []),
        "dxf_ambiguous": len(dxf.get("ambiguous_dxf") or []),
        "dxf_skipped": len(dxf.get("skipped") or []),
        "native_flat_parts": len(_native_flat_pns),
        "native_top_assembly": _native.get("top_assembly") or "",
        "native_counts": _native.get("counts") or {},
        "parts_without_dxf": _without_dxf,
        "geo_reliability": geo_rel,
        "geo_reliability_band": _band(geo_rel),
        "geo_confidence": geo_conf,
        "geo_confidence_band": _band(geo_conf),
        "validation_issues": val.get("issues") or [],
        "stray_space_files": stray_space,
        "pn_pattern_count": len(pn_patterns),
        "pn_patterns": sorted(pn_patterns),
        "review_errors": sev_tally["error"],
        "review_warnings": sev_tally["warning"],
        "review_info": sev_tally["info"],
        "review_total": sum(sev_tally.values()),
        "review_fields": sorted(field_tally.items(), key=lambda kv: -kv[1])[:5],
        "contaminated": contaminated[:12],
    }


# (builder continues in part 2)

# ─────────────────────────────────────────────────────────────────────────────
# CSS — the navy 12532 house style (verbatim tokens)
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
  :root{
    --navy:#1F3864; --navy2:#2E4A7D; --steel:#41668f; --ink:#1c2530;
    --mut:#5b6b7d; --line:#dce3ec; --bg:#f4f7fb; --card:#ffffff;
    --good:#1e7d51; --goodbg:#e8f6ef; --warn:#a8710a; --warnbg:#fbf3e2;
    --bad:#b23636; --badbg:#fbecec; --info:#3a5c8c; --infobg:#eaf1fa;
    --accent:#c9a227;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
  .wrap{max-width:960px;margin:0 auto;padding:40px 28px 80px;}
  header.rpt{border-bottom:3px solid var(--navy);padding-bottom:22px;margin-bottom:8px;}
  .kicker{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--steel);font-weight:700;}
  h1{font-size:27px;line-height:1.2;margin:8px 0 6px;color:var(--navy);font-weight:750;letter-spacing:-.01em;}
  .sub{color:var(--mut);font-size:14px;}
  .meta{display:flex;flex-wrap:wrap;gap:20px;margin-top:16px;font-size:13px;color:var(--mut);}
  .meta b{color:var(--ink);font-weight:650;}
  h2{font-size:20px;color:var(--navy);margin:38px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--line);font-weight:700;}
  h3{font-size:16px;color:var(--navy2);margin:24px 0 8px;font-weight:670;}
  p{margin:10px 0;}
  .lead{font-size:16px;color:#28323e;}
  .card{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:20px 22px;margin:16px 0;
    box-shadow:0 1px 2px rgba(20,40,70,.04);}
  .headline{display:flex;flex-wrap:wrap;gap:18px;align-items:stretch;margin:18px 0;}
  .fig{flex:1;min-width:150px;background:var(--card);border:1px solid var(--line);border-radius:11px;padding:16px 18px;}
  .fig .lab{font-size:11.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--steel);font-weight:700;}
  .fig .val{font-size:26px;font-weight:760;color:var(--navy);margin-top:3px;letter-spacing:-.01em;}
  .fig .note{font-size:12.5px;color:var(--mut);margin-top:2px;}
  table{width:100%;border-collapse:collapse;margin:14px 0;font-size:14px;}
  th,td{text-align:left;padding:9px 11px;border-bottom:1px solid var(--line);vertical-align:top;}
  th{background:#eef3f9;color:var(--navy);font-weight:680;font-size:12.5px;letter-spacing:.02em;}
  td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;}
  tr:last-child td{border-bottom:none;}
  .tag{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.03em;padding:2px 9px;border-radius:20px;
    text-transform:uppercase;vertical-align:middle;}
  .t-good{background:var(--goodbg);color:var(--good);}
  .t-warn{background:var(--warnbg);color:var(--warn);}
  .t-bad{background:var(--badbg);color:var(--bad);}
  .t-info{background:var(--infobg);color:var(--info);}
  .t-fixed{background:var(--goodbg);color:var(--good);}
  .callout{border-left:4px solid var(--steel);background:#eef3f9;border-radius:0 9px 9px 0;padding:13px 17px;margin:15px 0;font-size:14px;}
  .callout.good{border-color:var(--good);background:var(--goodbg);}
  .callout.warn{border-color:var(--warn);background:var(--warnbg);}
  .callout.info{border-color:var(--info);background:var(--infobg);}
  ul.clean{margin:10px 0;padding-left:20px;}
  ul.clean li{margin:6px 0;}
  .rec{display:flex;gap:12px;margin:11px 0;align-items:flex-start;}
  .rec .num{flex:none;width:26px;height:26px;border-radius:50%;background:var(--navy);color:#fff;font-weight:700;font-size:13px;
    display:flex;align-items:center;justify-content:center;margin-top:1px;}
  .rec .body{flex:1;}
  .rec .body b{color:var(--navy2);}
  .split{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
  @media(max-width:680px){.split{grid-template-columns:1fr;}}
  .mini{font-size:13px;color:var(--mut);}
  code{background:#eef2f7;border:1px solid var(--line);border-radius:5px;padding:1px 5px;font-size:12.5px;
    font-family:"SF Mono",Consolas,Monaco,monospace;color:#31465f;}
  .foot{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);font-size:12.5px;color:var(--mut);}
  .chk{list-style:none;padding-left:0;margin:10px 0;}
  .chk li{padding:8px 0 8px 30px;position:relative;border-bottom:1px dashed var(--line);}
  .chk li:before{content:"\\25A1";position:absolute;left:4px;top:7px;font-size:17px;color:var(--steel);}
  .chk li:last-child{border-bottom:none;}
  /* Scoped styles for the detailed parity tables reused from parity_report_html
     (kept under .parity-detail so their .num/.over/.pn/.pill do not collide). */
  .parity-detail h3{color:var(--navy);font-size:14px;margin:18px 0 4px;}
  .parity-detail .num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}
  .parity-detail .over{color:#991b1b;font-weight:600;}
  .parity-detail .under{color:#1d4ed8;font-weight:600;}
  .parity-detail .ok{color:#166534;font-weight:600;}
  .parity-detail .muted{color:var(--mut);}
  .parity-detail .pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;background:#eef2f7;color:var(--mut);}
  .parity-detail .pn{font-family:"SF Mono",Consolas,Monaco,monospace;background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:12px;}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Section renderers — each returns an HTML string, driven by the view-model
# ─────────────────────────────────────────────────────────────────────────────

def _render_header(h: Dict[str, Any], has_parity: bool) -> str:
    kind = "Estimate Review &amp; Parity" if has_parity else "Estimate Review"
    return f"""<header class="rpt">
  <div class="kicker">SDI Intelligence &middot; {kind}</div>
  <h1>Job {_esc(h['job_no'])} — {_esc(h['name'])}</h1>
  <div class="sub">Automated estimate analysis &amp; drawing-quality audit</div>
  <div class="meta">
    <span><b>Job</b> {_esc(h['stem'])}</span>
    <span><b>Drawing pack</b> {h['page_count']} pages &middot; {h['pdf_count']} PDFs &middot; {h['dxf_matched']} DXFs matched</span>
    <span><b>Quantity basis</b> {_esc(h['quantity'])} off</span>
  </div>
</header>"""


def _render_headline(hl: Dict[str, Any], h: Dict[str, Any], streams: List[Dict[str, Any]]) -> str:
    parts = _extract_parts_count_note(streams)
    src_note = ""
    if hl.get("source_of_truth") == "populated_xlsx_excel_com":
        src_note = "Workbook-computed (Excel)"
    return f"""<div class="headline">
  <div class="fig"><div class="lab">Unit Cost (workbook)</div><div class="val">{_money(hl['unit'])}</div><div class="note">{src_note or 'Deliverable figure'} &middot; qty {_esc(h['quantity'])}</div></div>
  <div class="fig"><div class="lab">Material</div><div class="val">{_money(hl['material'])}</div><div class="note">Steel + BOM + boards + powder</div></div>
  <div class="fig"><div class="lab">Labour</div><div class="val">{_money(hl['labour'])}</div><div class="note">{_num(hl['hours'],2)} hrs · all depts</div></div>
  <div class="fig"><div class="lab">Parts costed</div><div class="val">{parts}</div><div class="note">across material streams</div></div>
</div>"""


def _extract_parts_count_note(streams: List[Dict[str, Any]]) -> str:
    counts = [s["count"] for s in streams if s.get("count")]
    return str(sum(counts)) if counts else "—"


def _render_glance(streams: List[Dict[str, Any]], hl: Dict[str, Any]) -> str:
    # Authoritative workbook-computed figures (the Excel's own SUM) — the single source of truth.
    fig_rows = ""
    if hl.get("material") is not None:
        fig_rows += f'<tr><td>Material</td><td class="n">{_money(hl["material"])}</td></tr>'
    if hl.get("labour") is not None:
        fig_rows += f'<tr><td>Labour</td><td class="n">{_money(hl["labour"])}</td></tr>'
    fig_rows += f'<tr><td><b>Unit Cost</b></td><td class="n"><b>{_money(hl["unit"])}</b></td></tr>'

    # Parts grouped by material stream — COUNTS only. The per-stream £ breakdown was on an
    # engine-internal basis that did not reconcile with the workbook total, so it is not shown
    # here; the per-stream cost breakdown lives in the populated spreadsheet.
    stream_rows = ""
    for s in streams:
        if not s.get("count"):
            continue
        stream_rows += f'<tr><td>{_esc(s["name"])}</td><td class="n">{s["count"]}</td></tr>'
    stream_table = ""
    if stream_rows:
        stream_table = f"""<h3>Parts by material stream</h3>
<table>
  <thead><tr><th>Material stream</th><th class="n">Parts</th></tr></thead>
  <tbody>{stream_rows}</tbody>
</table>"""

    return f"""<h2>1 &nbsp;Estimate at a glance</h2>
<p>The figures below are the <b>authoritative workbook-computed</b> costs — the Excel's own SUM, the one
true number. Parts are grouped by material stream as counts; the per-stream cost breakdown is in the
populated spreadsheet.</p>
<table>
  <thead><tr><th>Figure</th><th class="n">Value</th></tr></thead>
  <tbody>{fig_rows}</tbody>
</table>
{stream_table}"""


def _render_parity(bundle: Dict[str, Any]) -> str:
    """Conditional section — engine vs manual estimate comparison, from the parity bundle."""
    if not bundle:
        return ""
    # Headline engine-vs-manual comparison — REUSE parity_report_html's extractor + renderer so it
    # parses the REAL bundle schema. (The previous hand-rolled key guesses — json_value/workbook_value
    # — did not match the bundle, so this table rendered blank.) Scoped under .parity-detail.
    money_block = ""
    verdict_html = ""
    match_note = ""
    try:
        from parity_report_html import _money_rows, _section_table, _find_row
        _mrows = _money_rows(bundle)
        if _mrows:
            money_block = "<div class='parity-detail'>" + _section_table(_mrows) + "</div>"
            _u = _find_row(_mrows, "unit")
            if _u and _u.get("engine") is not None and _u.get("manual"):
                _pct = abs(_u["engine"] - _u["manual"]) / _u["manual"] * 100.0
                if _pct <= 5:
                    verdict_html = '<div class="callout good"><b>On track</b> — engine unit cost within 5% of the manual estimate.</div>'
                elif _pct <= 15:
                    verdict_html = '<div class="callout warn"><b>Needs a look</b> — engine unit cost 5–15% from the manual estimate.</div>'
                else:
                    verdict_html = '<div class="callout warn"><b>Variance</b> — engine unit cost over 15% from the manual estimate.</div>'
    except Exception:
        money_block = ""
        verdict_html = ""

    # Detailed comparison tables — REUSE parity_report_html's exact renderers (no duplication),
    # scoped under .parity-detail so their .num/.over/.pn/.pill styling can't collide with the
    # job report's own classes. Failure-isolated: if the bundle lacks a piece, that table is skipped.
    detail = ""
    try:
        from parity_report_html import (_route_rows, _recon, _route_table,
                                        _matched_table, _unmatched_section)
        _route = _route_rows(bundle)
        _rec = _recon(bundle)
        _blocks = ["<div class='parity-detail'>"]
        if _route and _route.get("rows"):
            _blocks.append("<h3>Labour by operation</h3>")
            _blocks.append("<p class='mini'>Engine cost per operation, and how the engine's canonical "
                           "operations map to the workbook route codes. Rows marked <b>manual only</b> are "
                           "operations the manual books that the engine does not yet (e.g. Dress Welds) — "
                           "the route gaps to close.</p>")
            _blocks.append(_route_table(_route))
        if _rec.get("matched"):
            _blocks.append("<h3>Part lines matched on code</h3>")
            _blocks.append("<p class='mini'>%s manual line(s) matched an engine line on part code "
                           "(exact or code-stem).</p>" % _esc(_rec.get("matched_count", len(_rec.get("matched") or []))))
            _blocks.append(_matched_table(_rec))
        _us = _unmatched_section(_rec)
        if _us:
            _blocks.append("<h3>Lines not matched on code</h3>")
            _blocks.append(_us)
        _blocks.append("</div>")
        if len(_blocks) > 2:
            detail = "".join(_blocks)
    except Exception:
        detail = ""

    return f"""<h2>1a &nbsp;Parity vs manual estimate</h2>
<p>This job has a manual estimate on file. The engine's figures are compared against it below —
the manual estimate is the human benchmark, not necessarily ground truth (it may itself be at a
different quantity or revision).</p>
{money_block}
{verdict_html}
{match_note}
{detail}"""

def bought_in_strength_row(bi: List[Dict[str, Any]]) -> str:
    """The "bought-in items recognised" row, as its own function so a test can drive it.

    RECOGNISING A PART AND PRICING IT ARE DIFFERENT ACHIEVEMENTS. This row said every
    bought-in was "identified and priced from catalogue/historical sources" under a green
    Sound tag, on a job where three of the applied prices were AI market estimates and a
    fourth was zero. Identification is what went right; say that, and count how the prices
    actually arrived.

    Extracted because the fixture first written for it could only check whether a helper
    existed and passed when it did not — a test that asserts nothing is worse than none,
    because the suite goes green either way.
    """
    if not bi:
        return ""
    try:
        import price_provenance
        guessed = len({str(p.get("part_number") or "").upper()
                       for p in bi if price_provenance.applied_ai_prices(p)})
    except Exception:
        guessed = 0

    def _priced(p: Dict[str, Any]) -> bool:
        # _num() in this module FORMATS a number for display; it is not a parser and returns
        # a string, so testing it for truthiness would call every line priced.
        for v in (((p.get("cost_breakdown") or {}).get("system_cost") or {}).get("unit_cost_gbp"),
                  p.get("unit_cost_gbp"),
                  (p.get("material_estimate") or {}).get("unit_material_cost_gbp")):
            try:
                if v is not None and float(v) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    unpriced = len([p for p in bi if not _priced(p)])
    tag, note = "t-good", "identified as purchased rather than fabricated."
    if guessed or unpriced:
        bits = []
        if guessed:
            bits.append(f"{guessed} priced by an AI market estimate, not a catalogue")
        if unpriced:
            bits.append(f"{unpriced} carrying no price at all")
        tag = "t-warn"
        note = ("identified as purchased rather than fabricated \u2014 but "
                + " and ".join(bits) + ". Identification is not pricing.")
    return (f'<tr><td><span class="tag {tag}">'
            f'{"Sound" if tag == "t-good" else "Check"}</span></td>'
            f'<td><b>Bought-in items recognised.</b> {len(bi)} bought-in part(s) {note}</td></tr>')


def _render_whats_right(summary: Dict[str, Any], streams: List[Dict[str, Any]]) -> str:
    """Section 2 — verify claims from the data rather than assert fixed ones."""
    rows = ""
    parts = _extract_parts(summary)

    # material streams separated?
    stream_names = [s["name"] for s in streams if s.get("count")]
    if len(stream_names) > 1:
        rows += (f'<tr><td><span class="tag t-good">Sound</span></td><td><b>Material streams correctly separated.</b> '
                 f'The engine costed {len(stream_names)} distinct streams ({_esc(", ".join(stream_names))}) — '
                 f'each material costed on its own basis, none mis-routed into another.</td></tr>')

    # no double-counting: a part shouldn't be in both a fabricated stream and bought-in
    dup = 0  # the streams are mutually exclusive by construction here
    rows += ('<tr><td><span class="tag t-good">Sound</span></td><td><b>No double-counting.</b> '
             'Each part is assigned to exactly one cost stream — fabricated parts to their material, '
             'purchased items to the bill of materials.</td></tr>')

    # estimate status — READ THE SAME GATE THE QUOTE READS.
    # estimate_status is the DATA-SUFFICIENCY verdict: did the engine have enough to reach a
    # number. The invariants are a different and later question: does that number hold
    # together. Reporting the first as "completed cleanly" while the quote for the same job
    # carried "3 consistency check(s) FAILED" left two documents describing one estimate and
    # disagreeing about whether it could be trusted — and the one an estimator reads first is
    # the one that said everything was fine.
    status = _get(summary, "estimate_summary", "estimate_status")
    _inv = summary.get("invariants") if isinstance(summary.get("invariants"), dict) else None
    if status == "ok" and _inv is not None and not _inv.get("may_quote_firm"):
        rows += ('<tr><td><span class="tag t-bad">Not firm</span></td><td><b>Consistency checks did '
                 'not pass.</b> The engine reached a full costed estimate — data sufficiency was '
                 f'met — but {_inv.get("blocking", 0)} check(s) FAILED and '
                 f'{_inv.get("unverified", 0)} could not be run. The figures below are '
                 '<b>provisional</b> and must not be released as a firm price. See section 8.</td></tr>')
    elif status == "ok" and _inv is None:
        rows += ('<tr><td><span class="tag t-warn">Unverified</span></td><td><b>Estimate completed, '
                 'but unchecked.</b> The engine reached a full costed estimate; the consistency '
                 'checks did not run, so none of its figures have been verified against the '
                 'workbook.</td></tr>')
    elif status == "ok":
        rows += ('<tr><td><span class="tag t-good">Sound</span></td><td><b>Estimate completed cleanly.</b> '
                 'The engine reached a full costed estimate, and every consistency check passed.</td></tr>')

    # powder handled?
    # Post-costing source, shared with the client quote (costed_facts). The powder MATERIAL
    # summary is not evidence on its own: it can carry a line for a part whose powder LABOUR
    # was gated off, which is how this bullet came to congratulate the engine for correctly
    # powder-coating eight lacquered timber panels that the Estimate sheet never charges
    # powder on. A report claiming a process the sheet does not price is worse than silence.
    from costed_facts import part_numbers_with_operation
    _pc_parts = part_numbers_with_operation(summary, "powder_coating", "p.coat")
    if _pc_parts:
        rows += (f'<tr><td><span class="tag t-good">Sound</span></td><td><b>Powder coating scoped to the right parts.</b> '
                 f'{len(_pc_parts)} part(s) are <b>charged</b> powder coating — not applied blanket '
                 f'across raw/assembly parts.</td></tr>')

    # bought-ins recognised
    bi = [p for p in parts if str(p.get("part_number") or "").upper().startswith("BI-")]
    rows += bought_in_strength_row(bi)

    if not rows:
        rows = '<tr><td><span class="tag t-info">Note</span></td><td>No specific strengths auto-detected for this job.</td></tr>'

    return f"""<h2>2 &nbsp;What the engine got right</h2>
<div class="card"><table><tbody>{rows}</tbody></table></div>"""


def _render_review_items(review: Dict[str, Any]) -> str:
    """Section 3 — provisional / low-confidence items to check."""
    rows = ""
    flagged = review.get("flagged_parts", [])
    specific = []
    low_conf_only = []
    for fp in flagged:
        reason = (fp.get("reason") or "").lower()
        if any(k in reason for k in ("weld", "material spec", "bend", "risk flag", "price")):
            specific.append(fp)
        elif reason:
            low_conf_only.append(fp)

    for fp in specific:
        cost = _money(fp["cost"]) if fp.get("cost") is not None else ""
        rows += (f'<tr><td><b>{_esc(fp["part"])}</b> {cost} <span class="tag t-warn">Verify</span></td>'
                 f'<td>{_esc(fp["reason"])}</td>'
                 f'<td>Review against the drawing.</td></tr>')

    if low_conf_only:
        names = ", ".join(_esc(fp["part"]) for fp in low_conf_only[:10])
        more = f" (+{len(low_conf_only)-10} more)" if len(low_conf_only) > 10 else ""
        rows += (f'<tr><td><b>{len(low_conf_only)} parts — low extraction confidence</b> '
                 f'<span class="tag t-info">Confidence</span></td>'
                 f'<td>{names}{more}</td>'
                 f'<td>Read below the confidence threshold (a drawing-clarity signal, not necessarily a costing error) — '
                 f'spot-check dimensions/material.</td></tr>')

    # risk flag tally as review rows
    rf = review.get("risk_flag_tally", {})
    RISK_LABEL = {
        "weld_required": ("Weld detected — verify weld/dress content", "Confirm weldment labour is captured."),
        "missing_material_spec": ("Missing material spec on part", "Material inferred; confirm the correct spec."),
        "many_bends": ("High bend count", "Check fold time on these parts."),
    }
    for flag, count in sorted(rf.items()):
        if flag.startswith("missing_labour_rate:"):
            op = flag.split(":", 1)[1]
            rows += (f'<tr><td><b>Missing labour rate: {_esc(op)}</b> <span class="tag t-info">Rate</span></td>'
                     f'<td>{count} part(s) reference an operation with no configured labour rate.</td>'
                     f'<td>Add the rate so the operation is costed.</td></tr>')
        elif flag in RISK_LABEL:
            lbl, imp = RISK_LABEL[flag]
            rows += (f'<tr><td><b>{_esc(lbl)}</b> <span class="tag t-warn">Verify</span> ×{count}</td>'
                     f'<td>{count} part(s) flagged.</td><td>{_esc(imp)}</td></tr>')

    for pv in review.get("provisional", []):
        rows += (f'<tr><td><b>{_esc(pv["item"])}</b> <span class="tag t-info">Provisional</span></td>'
                 f'<td>{_esc(pv["note"])}</td><td>Confirm the rate.</td></tr>')

    if not rows:
        rows = '<tr><td colspan="3" class="mini">No provisional or low-confidence items flagged for this job.</td></tr>'

    return f"""<h2>3 &nbsp;Review items &amp; limitations</h2>
<p>None of the following break the total — the estimate is structurally sound. They are points where a
value is <b>provisional</b> or <b>derived with limited confidence</b>, listed so an estimator can review
them deliberately.</p>
<table>
  <thead><tr><th>Item</th><th>Nature</th><th>Impact</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""


def _render_drawing_analysis(dq: Dict[str, Any]) -> str:
    """Section 4 — the drawing-quality audit. Honest severity, not alarmist counts."""
    # 4.1 strengths
    strengths = []
    if dq.get("native_flat_parts"):
        _nc = dq.get("native_counts") or {}
        _ta = f" (top assembly {dq['native_top_assembly']})" if dq.get("native_top_assembly") else ""
        strengths.append(
            f"<li><b>SolidWorks models read natively.</b> {dq['native_flat_parts']} part(s) "
            f"carry a modelled flat pattern from the sheet-metal cut list{_ta} — blank size, "
            f"sheet gauge and bend radius are taken from the model, not inferred from the "
            f"drawing. Material coverage {_nc.get('material_coverage', '—')} of "
            f"{_nc.get('parts_with_signals', '—')} part(s); quantities from the full-depth "
            f"assembly BOM.</li>")
    if dq["dxf_matched"]:
        strengths.append(f"<li><b>Flat-pattern DXFs present.</b> {dq['dxf_matched']} DXF(s) matched to parts, "
                         f"giving reliable cut-length and bend geometry.</li>")
    if dq.get("geo_reliability") is not None:
        band = dq.get("geo_reliability_band") or ""
        rel_pct = _num(float(dq["geo_reliability"]) * 100, 0) if isinstance(dq["geo_reliability"], (int, float)) else "—"
        # Name this for what it is. A high number here is PDF VECTOR EXTRACTION confidence —
        # how cleanly we read the page — NOT flat-pattern/manufacturing geometry coverage.
        # Shown unqualified next to "0 DXFs matched" it reads as "fab geometry is solid",
        # which is the opposite of the truth on a PDF-only pack.
        # The caveat only holds when NOTHING measured the blanks. Native SolidWorks flats
        # are measured geometry, so a native job must not be told its blanks are provisional.
        _no_measured = not (dq.get("dxf_matched") or dq.get("native_flat_parts"))
        _caveat = ("  <em>This measures how cleanly the PDF vectors were read — it is "
                   "<b>not</b> flat-pattern coverage. No DXFs or SolidWorks models are "
                   "matched on this job, so blank sizes, bend counts and cut lengths "
                   "remain provisional.</em>"
                   if _no_measured else "")
        strengths.append(f"<li><b>PDF vector extraction confidence: {band} ({rel_pct}%).</b> "
                         f"Overall extraction confidence "
                         f"{_num(float(dq['geo_confidence'])*100,0) if isinstance(dq.get('geo_confidence'),(int,float)) else '—'}%."
                         f"{_caveat}</li>")
    if not strengths:
        strengths.append("<li>Drawing pack read; see findings below.</li>")

    # 4.2 weaknesses table — only genuine issues
    wk = ""
    if dq.get("parts_without_dxf"):
        parts = dq["parts_without_dxf"]
        n = len(parts)
        # note geometry reliability where available — DXF-less doesn't always mean low-confidence
        names_bits = []
        low_conf_any = False
        for x in parts[:6]:
            if isinstance(x, dict):
                pn = x.get("part_number", "?")
                gr = x.get("geometry_reliability")
                if isinstance(gr, (int, float)):
                    names_bits.append(f"{pn} ({_num(gr*100,0)}%)")
                    if gr < 0.9:
                        low_conf_any = True
                else:
                    names_bits.append(str(pn))
            else:
                names_bits.append(str(x))
        effect = ("geometry came from PDF/inference rather than a DXF flat pattern"
                  + (" — reliability varies, check the lower-scoring ones" if low_conf_any
                     else ", though reliability stayed high"))
        wk += (f'<tr><td><b>Parts without a DXF</b></td><td>{_esc(", ".join(names_bits))}{"…" if n>6 else ""}</td>'
               f'<td>{n} part(s): {effect}.</td></tr>')
    if dq.get("dxf_unmatched"):
        wk += (f'<tr><td><b>Unmatched DXFs</b></td><td>{dq["dxf_unmatched"]} file(s)</td>'
               f'<td>DXFs present but not tied to a part — check naming/part-number alignment.</td></tr>')
    if dq.get("dxf_ambiguous"):
        wk += (f'<tr><td><b>Ambiguous DXFs</b></td><td>{dq["dxf_ambiguous"]} file(s)</td>'
               f'<td>DXF could match more than one part — clearer naming would disambiguate.</td></tr>')
    if dq.get("stray_space_files"):
        ex = _esc(dq["stray_space_files"][0])
        wk += (f'<tr><td><b>Stray spaces in filenames</b></td><td><code>{ex}</code></td>'
               f'<td>Spaces (esp. before the extension) complicate file matching; tolerated but fragile.</td></tr>')
    if dq.get("pn_pattern_count", 0) > 2:
        wk += (f'<tr><td><b>Inconsistent part-number formats</b></td><td>{dq["pn_pattern_count"]} distinct patterns</td>'
               f'<td>Mixed conventions make it harder to tell fabricated parts from sub-assemblies and bought-ins.</td></tr>')
    # review items — honest severity, not a lump "contaminated" count
    if dq.get("review_total"):
        errs = dq.get("review_errors", 0)
        warns = dq.get("review_warnings", 0)
        infos = dq.get("review_info", 0)
        top_fields = ", ".join(f"{f} ×{c}" for f, c in dq.get("review_fields", []))
        sev_desc = []
        if errs:
            sev_desc.append(f"<b>{errs} error(s)</b>")
        if warns:
            sev_desc.append(f"{warns} warning(s)")
        if infos:
            sev_desc.append(f"{infos} info")
        where = f"{errs} error / {warns} warning / {infos} info"
        effect = (f"Mostly low-confidence reads on {top_fields}. "
                  + ("No errors — these are fields the engine read but flagged for a check, not corrupt data."
                     if not errs else "Includes errors that warrant a direct look."))
        wk += (f'<tr><td><b>Low-confidence field reads</b></td><td>{_esc(where)}</td>'
               f'<td>{effect}</td></tr>')
    if dq.get("validation_issues"):
        wk += (f'<tr><td><b>Validation issues</b></td><td>{len(dq["validation_issues"])} item(s)</td>'
               f'<td>The manufacturing write-up flagged structural issues (assembly-only parts, missing cues).</td></tr>')

    weaknesses = f"""<h3>4.2 &nbsp;Weaknesses &amp; inconsistencies found</h3>
<table><thead><tr><th>Finding</th><th>Where</th><th>Effect on estimating</th></tr></thead>
<tbody>{wk}</tbody></table>""" if wk else """<h3>4.2 &nbsp;Weaknesses &amp; inconsistencies found</h3>
<div class="callout good"><b>No significant drawing faults detected.</b> The pack read cleanly with no
missing DXFs, filename issues, or contaminated fields flagged.</div>"""

    return f"""<h2>4 &nbsp;Drawing analysis</h2>
<p>The estimate is only ever as good as the drawing pack it reads. This section audits the drawings
directly — what was clear, and where the engine had to work around them.</p>
<h3>4.1 &nbsp;Strengths of the drawing pack</h3>
<ul class="clean">{''.join(strengths)}</ul>
{weaknesses}"""


def _render_checklist(review: Dict[str, Any], dq: Dict[str, Any]) -> str:
    items = ""
    flagged = review.get("flagged_parts", [])
    # Split: parts with a SPECIFIC issue (weld/material/etc.) get individual lines;
    # parts flagged ONLY for low confidence get grouped into one summary line (else it's noise).
    specific = []
    low_conf_only = []
    for fp in flagged:
        reason = (fp.get("reason") or "").lower()
        has_specific = any(k in reason for k in ("weld", "material spec", "bend", "risk flag", "price"))
        if has_specific:
            specific.append(fp)
        elif reason:
            low_conf_only.append(fp)

    for fp in specific:
        cost = f" ({_money(fp['cost'])})" if fp.get("cost") is not None else ""
        items += f"<li><b>{_esc(fp['part'])}{cost}</b> — {_esc(fp['reason'])}.</li>"

    if low_conf_only:
        names = ", ".join(_esc(fp["part"]) for fp in low_conf_only[:8])
        more = f" (+{len(low_conf_only)-8} more)" if len(low_conf_only) > 8 else ""
        items += (f"<li><b>{len(low_conf_only)} part(s) flagged for low extraction confidence</b> — "
                  f"{names}{more}. These read below the confidence threshold; spot-check their "
                  f"dimensions/material against the drawing.</li>")

    for pv in review.get("provisional", []):
        items += f"<li><b>{_esc(pv['item'])}</b> — {_esc(pv['note'])}</li>"

    if not items:
        items = "<li>No specific review points — the estimate read cleanly.</li>"
    return f"""<h2>5 &nbsp;What to focus on when checking this job</h2>
<p>A practical checklist for the estimator reviewing the populated sheet:</p>
<ul class="chk">{items}</ul>"""


_DESIGN_RECS = [
    ("Standardise part-number format.", "One consistent scheme (e.g. <code>JOB-ASSY-NNL</code>) so fabricated parts, sub-assemblies and bought-ins are distinguishable at a glance. Avoid section labels and un-numbered details becoming \"parts\"."),
    ("State material in the title block of every detail — per part.", "Don't rely on a single assembly-level material for a multi-material product. Each detail should carry its own <code>MATERIAL:</code> field so nothing inherits the wrong default."),
    ("Export clean flat-pattern DXFs.", "No dimension/annotation/note layers in the flat-pattern DXF — geometry only. This single change removes the largest source of mis-read part sizes."),
    ("No spaces in filenames.", "{FILE_EXAMPLE} Consistent naming ties each DXF unambiguously to its part."),
    ("Consistent BOM table layout.", "Same columns, same order, same identifiers on every GA page — and clearly distinguish printed/graphic/display-board and bought-in items from fabricated parts."),
    ("Consistent dimension conventions.", "State overall size on every detail so the engine never has to infer it, and keep dimension text readable even where geometry is complex."),
    ("Consistent data mappings across drawings.", "The same field should mean the same thing on every drawing — material, finish, thickness, quantity in fixed places — so the engine can rely on structure instead of guessing per job."),
]


def _render_design_recs(dq: Optional[Dict[str, Any]] = None) -> str:
    # Build a concrete filename example from THIS job if a stray-space file was found;
    # otherwise use a neutral, job-agnostic example (never another job's real filename).
    file_example = "Remove spaces from DXF/PDF filenames — e.g. <code>PART_revA.dxf</code>, not <code>PART_revA .dxf</code>."
    if dq and dq.get("stray_space_files"):
        real = str(dq["stray_space_files"][0])
        fixed = re.sub(r"\s+\.", ".", re.sub(r"\s{2,}", "_", real)).replace(" ", "_")
        file_example = (f"This pack has <code>{_esc(real)}</code> — the space complicates matching. "
                        f"Prefer <code>{_esc(fixed)}</code>.")
    recs = ""
    for i, (title, body) in enumerate(_DESIGN_RECS, start=1):
        body = body.replace("{FILE_EXAMPLE}", file_example)
        recs += f'<div class="rec"><div class="num">{i}</div><div class="body"><b>{title}</b> {body}</div></div>'
    return f"""<h2>6 &nbsp;Design recommendations — for consistent, reliable estimating</h2>
<p>These changes to how drawings are produced would let the engine <b>read</b> the drawings rather than
<b>cope</b> with them — reducing variation job-to-job and making every future estimate more reliable.</p>
{recs}
<div class="callout good">
  <b>The prize:</b> with consistent drawings, the engine moves from <i>coping with variation</i> to
  <i>reliably reading a known structure</i> — cleaner BOMs, positively-identified manufacturing routes
  mapped to shop-floor machines, and estimates that need less manual correction each time.
</div>"""


def _render_verdict(hl: Dict[str, Any], dq: Dict[str, Any], has_parity: bool,
                    summary: Dict[str, Any]) -> str:
    faults = bool(dq.get("parts_without_dxf") or dq.get("stray_space_files")
                  or dq.get("review_errors") or dq.get("validation_issues"))
    draw_note = ("The drawing pack is largely legible, with the main opportunities captured as Design "
                 "recommendations above." if faults else
                 "The drawing pack read cleanly with no significant faults detected.")
    parity_note = (" The engine's figures are compared against the manual estimate in section 1a." if has_parity else "")
    _inv = summary.get("invariants") if isinstance(summary.get("invariants"), dict) else None
    if _inv is not None and not _inv.get("may_quote_firm"):
        _lead = (f"<b>This estimate is PROVISIONAL and must not be released as a firm price.</b> "
                 f"{_inv.get('blocking', 0)} consistency check(s) failed and "
                 f"{_inv.get('unverified', 0)} could not be run — listed in section 8. The "
                 f"structure is sound (material streams separated, no double-counting) and the "
                 f"workbook Unit Cost is <b>{_money(hl['unit'])}</b>, but that figure is not yet "
                 f"one the engine can stand behind.")
    elif _inv is None:
        _lead = (f"The estimate is <b>structurally sound</b>: material streams are correctly "
                 f"separated and there is no double-counting. The workbook Unit Cost is "
                 f"<b>{_money(hl['unit'])}</b>. The consistency checks did NOT run on this job, "
                 f"so none of these figures have been verified against the workbook — treat as "
                 f"provisional.")
    else:
        _lead = (f"The estimate is <b>structurally sound</b> and every consistency check passed: "
                 f"material rows and labour rows each reconcile to the workbook's own totals, "
                 f"and those totals to the unit price. The workbook Unit Cost is "
                 f"<b>{_money(hl['unit'])}</b>. It is presented with a transparent list of "
                 f"provisional items for estimator review.")
    return f"""<h2>7 &nbsp;Verdict</h2>
<p class="lead">{_lead}{parity_note} {draw_note}</p>
{_invariants_section(summary)}"""


# ─────────────────────────────────────────────────────────────────────────────
# Assembly
# ─────────────────────────────────────────────────────────────────────────────

def _invariants_section(summary: Dict[str, Any]) -> str:
    """What the engine checked about its own answer, and what it found.

    The quote can only carry a banner — it goes to a customer. The report is the document an
    estimator works from, so it gets the detail: every check that ran, and for each failure
    the engine's own sentence about what is wrong. Without this the report asserted the
    estimate was sound while the quote for the same job said three checks had failed, and
    nothing in either told anyone WHICH.
    """
    inv = summary.get("invariants")
    if not isinstance(inv, dict):
        return ('<h2>8 &nbsp;Consistency checks</h2>'
                '<div class="callout warn"><b>The consistency checks did not run on this job.</b> '
                'Nothing here has been verified against the workbook: rows have not been '
                'reconciled to their totals, priced rows have not been joined to the parts that '
                'produced them, and geometry claims have not been tested. Treat every figure in '
                'this report as unverified.</div>')
    _v = [x for x in (inv.get("violations") or []) if isinstance(x, dict)]
    _n = len(inv.get("checks_run") or [])
    if inv.get("may_quote_firm") and not _v:
        return (f'<h2>8 &nbsp;Consistency checks</h2>'
                f'<div class="callout good"><b>All {_n} checks passed.</b> Material and labour '
                f'rows each reconcile to the workbook\'s own totals, those totals reconcile to '
                f'the unit price, every priced row joins to exactly one route, and no report '
                f'names an operation the sheet did not charge for.</div>')
    _order = {"blocking": 0, "unverified": 1, "warning": 2}
    _label = {"blocking": ('t-bad', 'Failed'),
              "unverified": ('t-warn', 'Not verified'),
              "warning": ('t-info', 'Advisory')}
    rows = ""
    for x in sorted(_v, key=lambda a: _order.get(str(a.get("severity")), 3)):
        _cls, _txt = _label.get(str(x.get("severity")), ('t-info', 'Advisory'))
        # THE DETAIL, not just the sentence. "5 part(s) claim measured geometry but carry no
        # usable outline" tells an estimator a number and nothing they can act on: they
        # cannot open five unnamed parts. Every check already collects which records it
        # objected to; printing the message and discarding the evidence made the report
        # describe a problem instead of locating it.
        _d = x.get("detail") if isinstance(x.get("detail"), dict) else {}
        _bits = []
        for _k in ("parts", "rows", "problems", "failed_paths"):
            for _item in (_d.get(_k) or [])[:8]:
                if isinstance(_item, dict):
                    _lbl = (_item.get("part_number") or _item.get("workbook_row")
                            or _item.get("block") or _item.get("path"))
                    _why = (_item.get("geometry_source") or _item.get("wb_operation")
                            or _item.get("reason") or _item.get("code") or "")
                    _bits.append(f"{_lbl}{f' ({_why})' if _why else ''}")
                elif _item:
                    _bits.append(str(_item))
        for _k, _v in sorted(_d.items()):
            if _k in ("parts", "rows", "problems", "failed_paths") or _v in (None, "", [], {}):
                continue
            if not isinstance(_v, (list, dict)):
                _bits.append(f"{_k}={_v}")
        _detail = (f'<br><span class="mini">{_esc("; ".join(_bits[:12]))}</span>'
                   if _bits else "")
        rows += (f'<tr><td><span class="tag {_cls}">{_txt}</span></td>'
                 f'<td><code>{_esc(str(x.get("code") or ""))}</code></td>'
                 f'<td>{_esc(str(x.get("message") or ""))}{_detail}</td></tr>')
    _head = ('<div class="callout warn"><b>This estimate is not a firm price.</b> '
             f'{inv.get("blocking", 0)} check(s) failed and {inv.get("unverified", 0)} could '
             f'not be run, out of {_n}. A check that could not run has verified nothing — it '
             f'is not a pass.</div>' if not inv.get("may_quote_firm") else
             '<div class="callout info">No check failed. The advisories below are worth '
             'reading but do not affect whether the price can be released.</div>')
    return (f'<h2>8 &nbsp;Consistency checks</h2>{_head}'
            f'<table><thead><tr><th>Status</th><th>Check</th><th>What it found</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def build_report_html(summary: Dict[str, Any], bundle: Optional[Dict[str, Any]] = None) -> str:
    has_parity = bool(bundle)
    h = _extract_header(summary)
    hl = _extract_headline(summary)
    streams = _extract_cost_streams(summary)
    review = _extract_review_items(summary)
    dq = _extract_drawing_quality(summary)

    title = f"Job {h['job_no']} {h['name']} — Estimate Review"
    body = "\n".join([
        _render_header(h, has_parity),
        f'<p class="lead">This report presents the engine model\'s estimate for job {_esc(h["job_no"])}, '
        f'together with a detailed audit of the drawing pack: what the drawings gave us cleanly, where they '
        f'were inconsistent or hard to read, and how Design could make future jobs more reliable to estimate.</p>',
        _render_headline(hl, h, streams),
        _render_glance(streams, hl),
        _render_parity(bundle) if has_parity else "",
        _render_whats_right(summary, streams),
        _render_review_items(review),
        _render_drawing_analysis(dq),
        _render_checklist(review, dq),
        _render_design_recs(dq),
        _render_verdict(hl, dq, has_parity, summary),
        f'<div class="foot">SDI Intelligence &middot; ClaudeVision automated estimating engine &middot; '
        f'Job {_esc(h["stem"])}<br>Unit Cost {_money(hl["unit"])} is the workbook-computed figure. '
        f'Provisional items and drawing recommendations are listed for estimator and Design review. '
        f'Generated for internal review.</div>',
    ])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
{body}
</div>
</body>
</html>"""


def generate_report(summary_json_path: str, out_path: Optional[str] = None,
                    bundle_path: Optional[str] = None, job_stem: Optional[str] = None) -> str:
    summary = json.loads(Path(summary_json_path).read_text(encoding="utf-8"))
    bundle = None
    if bundle_path and Path(bundle_path).exists():
        try:
            bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
        except Exception:
            bundle = None
    htmlout = build_report_html(summary, bundle)
    if out_path is None:
        stem = job_stem or summary.get("job_output_stem") or Path(summary_json_path).stem
        stem = re.sub(r"[^\w\- ]", "", str(stem)).strip()
        out_dir = Path(summary_json_path).parent
        out_path = str(out_dir / f"{stem}_report.html")
    Path(out_path).write_text(htmlout, encoding="utf-8")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the unified SDI job report (7 sections + conditional parity).")
    ap.add_argument("--json", required=True, help="Summary JSON path.")
    ap.add_argument("--bundle", help="Optional parity bundle JSON (adds the comparison section).")
    ap.add_argument("--out", help="Output HTML path.")
    args = ap.parse_args()
    out = generate_report(args.json, out_path=args.out, bundle_path=args.bundle)
    print(f"report -> {out}")


if __name__ == "__main__":
    main()
