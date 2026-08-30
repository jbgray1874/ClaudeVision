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
    """The canonical job part list, shared with the sheet and every other deliverable.

    Reading part_estimates here put this report on a different set of rows from the
    Estimate sheet in the same job: cost streams that omitted a bought-in the sheet
    charges, and quantities that differ for anything below the first level."""
    from costed_facts import job_parts
    return job_parts(summary) or (
        _get(summary, "estimate_summary", "part_estimates", default=[]) or [])


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
            # A findable name, not "?". part_number may be None (rejected as boilerplate); fall
            # back through the description and the source filename so Tim can locate the part the
            # review flag is about, instead of a bare "?" he cannot act on.
            _src = f.get("source_file")
            _label = (f.get("part_number") or f.get("part") or f.get("description")
                      or (str(_src).rsplit("\\", 1)[-1].rsplit("/", 1)[-1] if _src else None)
                      or "unidentified (no part number)")
            review["flagged_parts"].append({
                "part": _label,
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
    # ONE MODULE ANSWERS "DO WE BUY THIS". A local BI- prefix test read four bought-ins and
    # two AI-priced lines on 12120, while the invariant reading the same job said three —
    # because THUM620 does not start with BI-, and bought_in_policy has listed THUM as a
    # bought-in family all along. Two counts of the same thing on one page is the defect that
    # module exists to prevent; the prefix stays only as a fallback if it cannot be imported.
    try:
        from bought_in_policy import is_bought_in as _is_bought_in
    except ImportError:
        def _is_bought_in(p):
            return str(p.get("part_number") or "").upper().startswith("BI-")
    bi = [p for p in parts if _is_bought_in(p)]
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


def _render_drawing_analysis(dq: Dict[str, Any], summary: Optional[Dict[str, Any]] = None) -> str:
    """Section 4 — the drawing-quality audit. Honest severity, not alarmist counts.

    Takes the summary as well as the quality figures, because the most serious thing that can be
    wrong with a drawing pack is a drawing that is not in it, and that fact lives on the job
    rather than in the extraction stats."""
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
    # DRAWINGS THAT NEVER ARRIVED COME FIRST, because it is the one weakness that changes what
    # the total MEANS rather than how precisely it was measured. A pack missing four welded
    # assemblies is not a cheap job; it is a job we have only seen part of, and the reader needs
    # that before any confidence percentage below it.
    try:
        from costed_facts import undrawn_bom_lines as _undrawn
        _missing_drawings = _undrawn(summary)
    except Exception:                                            # noqa: BLE001
        _missing_drawings = []
    if _missing_drawings:
        _names = ", ".join(
            f"{m['part_number']}" + (f" ({m['description']})" if m.get("description") else "")
            for m in _missing_drawings[:6])
        _extra = f" …and {len(_missing_drawings) - 6} more" if len(_missing_drawings) > 6 else ""
        wk += (f'<tr><td><b>Drawings named on the BOM but not in the pack</b></td>'
               f'<td>{_esc(_names)}{_extra}</td>'
               f'<td>Nothing read these, so nothing costed them. The estimate is priced from '
               f'what was supplied and is <b>not</b> a price for the whole product — ask for '
               f'the detail drawings before quoting the complete job.</td></tr>')
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

    weaknesses = f"""<h3>4.3 &nbsp;Weaknesses &amp; inconsistencies found</h3>
<table><thead><tr><th>Finding</th><th>Where</th><th>Effect on estimating</th></tr></thead>
<tbody>{wk}</tbody></table>""" if wk else """<h3>4.3 &nbsp;Weaknesses &amp; inconsistencies found</h3>
<div class="callout good"><b>No significant drawing faults detected.</b> The pack read cleanly with no
missing DXFs, filename issues, or contaminated fields flagged.</div>"""

    return f"""<h2>4 &nbsp;Drawing analysis</h2>
<p>The estimate is only ever as good as the drawing pack it reads. This section audits the drawings
directly — what was clear, and where the engine had to work around them.</p>
{_files_read_section(summary or {})}
<h3>4.2 &nbsp;Strengths of the drawing pack</h3>
<ul class="clean">{''.join(strengths)}</ul>
{weaknesses}"""


def _files_read_section(summary: Dict[str, Any]) -> str:
    """4.1 — THE DRAWINGS THIS NUMBER CAME FROM, NAMED.

    The pack was recorded and never shown. `job_source_pdfs` was in the summary and the report
    used it for counts and filename hygiene; `cad_inputs` held the files that were present and
    NOT read. Neither was ever put in front of the estimator, so the one document people
    actually read could not answer "which drawings produced this?" — six weeks later, when
    somebody asks, that is the whole question.

    It matters more since staging, not less. Selection now genuinely decides what is priced, so
    a drawing left off the list is absent from the estimate and there was nothing on paper
    saying which ones were on it. A short list is also the fastest way to catch the expensive
    mistake — a pack that is missing a part — because a person who knows the job reads six
    filenames and sees the seventh is not there.

    Files present and NOT read are named beside the ones that were. A DWG nobody could convert
    is not a neutral fact: it is geometry that was in the folder and did not reach the number.
    """
    read = [str(p.get("name") or p) if isinstance(p, dict) else str(p)
            for p in (summary.get("job_source_pdfs") or [])]
    cad = summary.get("cad_inputs") or {}
    dxf = summary.get("dxf_augmentation") or {}

    def _names(items) -> List[str]:
        out = []
        for it in items or []:
            nm = (it.get("dxf_name") or it.get("name") or it.get("file")
                  if isinstance(it, dict) else str(it))
            if nm:
                out.append(str(nm))
        return out

    rows: List[tuple] = []
    for n in read:
        rows.append((n, "PDF", "read"))
    for n in _names(dxf.get("matched")):
        rows.append((n, "DXF", "matched to a part — measured flat pattern"))
    for n in _names(dxf.get("unmatched_dxf")):
        rows.append((n, "DXF", "present, matched to no part"))
    for n in (cad.get("solidworks") or []):
        rows.append((str(n), "MODEL", "SOLIDWORKS model"))
    for n in (cad.get("converted") or []):
        rows.append((str(n), "DXF", "converted from a DWG"))
    # LAST AND MARKED, because this is the row that changes what the number means.
    unread = [str(n) for n in (cad.get("unread") or [])]
    for n in unread:
        rows.append((n, "—", "PRESENT, NOT READ — contributed nothing"))

    if not rows:
        # Silence would read as "no drawings", which is never true of a job that produced a
        # number. Say that the record is missing, not that the pack was.
        return ('<h3>4.1 &nbsp;Drawings this estimate was built from</h3>'
                '<div class="callout warn">The engine did not record which files it read on '
                'this job, so they cannot be listed here. The staged input folder for this '
                'client and drawing holds exactly the pack that was priced.</div>')

    seen, body = set(), ""
    for name, kind, what in rows:
        key = (name.lower(), kind)
        if key in seen:
            continue
        seen.add(key)
        cls = ' style="color:#b3261e;font-weight:600"' if "NOT READ" in what else ""
        body += (f'<tr><td><code>{_esc(name)}</code></td><td>{_esc(kind)}</td>'
                 f'<td{cls}>{_esc(what)}</td></tr>')

    note = ""
    if unread:
        note = (f'<div class="callout warn"><b>{len(unread)} file(s) were in the pack and were '
                f'not read.</b> They contributed nothing to this estimate. A DWG usually means '
                f'no converter was available; a STEP or IGES carries geometry but no part '
                f'numbers, quantities or material, so it is never a source.</div>')

    return (f'<h3>4.1 &nbsp;Drawings this estimate was built from</h3>'
            f'<p>Exactly these files, and nothing else in the folder. Drawings not selected for '
            f'the run were not read.</p>'
            f'<table><thead><tr><th>File</th><th>Type</th><th>What it contributed</th></tr>'
            f'</thead><tbody>{body}</tbody></table>{note}')


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
{_provenance_strip(summary)}
{_bom_provenance_section(summary)}
{_purchased_key_section(summary)}
{_unpriced_section(summary)}
{_route_decisions_section(summary)}
{_invariants_section(summary)}"""


def _provenance_strip(summary: Dict[str, Any]) -> str:
    """Four lines an estimator reads before anything else.

    The two provenance tables below are long by design. What a reviewer needs first is
    whether to trust the number at all, and that is four facts: where the totals came from,
    the best source that contributed anything, how many decisions had to be settled rather
    than simply read, and who owns powder. Powder is on this strip because it is the one
    figure that has twice been produced by a mechanism nobody could name from the sheet.
    """
    try:
        from source_precedence import display_name, rank
    except Exception:
        return ""
    hl = _extract_headline(summary) or {}
    payload = ((summary.get("estimate_summary") or {}).get("canonical_route_shadow")
               or summary.get("canonical_route_shadow") or {})
    decisions = [d for d in (payload.get("decisions") or []) if isinstance(d, dict)]

    # WHERE THE TOTALS CAME FROM, said rather than implied. A reader cannot otherwise tell
    # a figure the workbook calculated from one this report worked out for itself, and only
    # the first can be checked by opening the sheet.
    if hl.get("source_of_truth") == "populated_xlsx_excel_com":
        truth = ("the workbook's own calculated cells, read back after Excel recalculated "
                 "&mdash; not re-computed here")
    elif hl.get("source_of_truth"):
        truth = f"{_esc(hl.get('source_of_truth'))} &mdash; <b>not</b> the workbook's own cells"
    else:
        truth = "<b>not recorded</b> &mdash; treat every total below as unverified"

    best = ""
    for d in decisions:
        nm = str(d.get("source") or "")
        if nm and (not best or rank(nm) > rank(best)):
            best = nm
    best_txt = (f"{_esc(display_name(best))} (rank {rank(best)})" if best
                else "<b>none &mdash; no operation was arbitrated</b>")

    contested = [d for d in decisions if d.get("contested")]
    keys = sorted({str(d.get("settled_by_key") or "") for d in contested if d.get("settled_by_key")})
    con_txt = ("none &mdash; every decision had a single strongest source" if not contested
               else f"<b>{len(contested)}</b>" + (f", settled by {_esc(', '.join(keys))}" if keys else ""))

    powder = [d for d in decisions
              if str(d.get("operation") or "").lower() in
              ("powder_coating", "powder_coat", "powder", "p_coat", "pcoat")]
    if powder:
        req = [d for d in powder if str(d.get("status")) == "required"]
        pow_txt = (f"the route compiler &mdash; {len(req)} part(s) decided coated"
                   if req else "the route compiler &mdash; <b>nothing coated on this job</b>")
    elif decisions:
        pow_txt = ("<b>no powder decision on this route.</b> Mass, if any, came from "
                   "geometry, not from an arbitrated decision")
    else:
        pow_txt = "<b>the legacy finish gate</b> &mdash; no compiled route on this job"

    # THE FIRST THING TO SAY, WHEN IT APPLIES. Every figure above this strip is presented as
    # the workbook's; when the Excel read-back did not run they are the engine's PRE-Excel
    # numbers instead, which is a different total. Section 11 says so too, but an estimator
    # reading top-down has already formed a view of the number by the time they reach it.
    _fe = summary.get("final_estimate")
    if not isinstance(_fe, dict):
        _fe = (summary.get("estimate_summary") or {}).get("final_estimate")
    _no_readback = (
        '<div class="callout warn"><b>The calculated sheet was never read back.</b> Excel did '
        'not return this workbook\'s computed totals, so the figures above are the engine\'s '
        'own, not what the Estimate sheet calculates &mdash; two different numbers. Nothing '
        'below has been reconciled against the workbook.</div>'
        if not isinstance(_fe, dict) or not _fe else '')

    return ('<h2>8 &nbsp;How far to trust this number</h2>'
            + _no_readback +
            '<table><tbody>'
            f'<tr><td><b>Totals came from</b></td><td>{truth}</td></tr>'
            f'<tr><td><b>Best source used</b></td><td>{best_txt}</td></tr>'
            f'<tr><td><b>Decisions needing resolution</b></td><td>{con_txt}</td></tr>'
            f'<tr><td><b>Powder decided by</b></td><td>{pow_txt}</td></tr>'
            '</tbody></table>')


def _bom_provenance_section(summary: Dict[str, Any]) -> str:
    """Where each PART's costing facts came from -- the BOM half of the same question.

    Section 8 explains the ROUTE. This explains the BILL OF MATERIALS, and the two are
    asked for together every time: an estimator looking at a line wants to know whether the
    material, the thickness and the quantity behind it were measured off a model, read off
    a DXF, taken from the title block, or produced by a language model. Until now the report
    named none of them, so a figure derived from a model and one derived from Grok looked
    identical on the page.

    READ THROUGH source_precedence, which is where each datum's source is actually stamped.
    Deriving it here from filenames or geometry hints -- which is what other parts of this
    codebase used to do -- produces a second opinion about provenance, and a report that
    disagrees with the record it is reporting on is worse than no report.
    """
    try:
        from source_precedence import source_of, display_name, was_measured, rank
    except Exception:
        return ""
    parts = _extract_parts(summary) or []
    if not parts:
        # SILENCE IS NOT A CLEAN BILL, and section 10 already knows it. A missing section
        # reads as nothing-to-report; here it means no part reached the costed pool at all.
        return ('<h2>9 &nbsp;Where the bill of materials came from</h2>'
                '<div class="callout warn"><b>No costed parts on this job.</b> Nothing '
                'reached the costed pool, so no material provenance can be shown &mdash; '
                'this is not a job whose provenance is clean.</div>')

    _FIELDS = (("normalized_material", "Material"),
               ("normalized_thickness_mm", "Thickness"),
               ("quantity", "Quantity"),
               ("blank_length_mm", "Blank size"))
    rows, reasoned_n, unstamped_n = [], 0, 0
    for p in parts:
        if not isinstance(p, dict):
            continue
        cells, worst, any_reasoned, any_missing = [], 999, False, False
        for field, _label in _FIELDS:
            src = ""
            try:
                src = str(source_of(p, field) or "")
            except Exception:
                src = ""
            if not src:
                cells.append('<td class="mini"><i>not stamped</i></td>')
                any_missing = True
                continue
            measured = was_measured(src)
            any_reasoned = any_reasoned or not measured
            worst = min(worst, rank(src))
            cells.append(f'<td class="mini">{"" if measured else "&#9889; "}'
                         f'{_esc(display_name(src))}</td>')
        reasoned_n += 1 if any_reasoned else 0
        unstamped_n += 1 if any_missing else 0
        rows.append((worst, str(p.get("part_number") or ""),
                     f'<tr class="{"over" if any_reasoned else ""}">'
                     f'<td class="pn"><a id="bom-{_esc(p.get("part_number"))}" href="#route-{_esc(p.get("part_number"))}">{_esc(p.get("part_number"))}</a></td>'
                     + "".join(cells) + "</tr>"))
    if not rows:
        return ""
    rows.sort(key=lambda r: (r[0], r[1]))          # weakest provenance first
    _heads = "".join(f"<th>{h}</th>" for _f, h in _FIELDS)
    _note = (f'<p class="mini"><b>{reasoned_n} of {len(rows)} part(s)</b> rest on at least one '
             f'reasoned value (&#9889;) rather than a measurement, and are listed first. '
             f'{unstamped_n} part(s) carry a field with no recorded source at all -- an '
             f'unstamped datum is not a measured one.</p>' if (reasoned_n or unstamped_n)
             else '<p class="mini">Every costing datum on every part was measured and '
                  'carries a recorded source.</p>')
    return ('<h2>9 &nbsp;Where the bill of materials came from</h2>'
            '<p class="mini">The source recorded against each costing datum, weakest first. '
            '&#9889; marks a value that was reasoned rather than measured: it can be right, '
            'but it cannot be held against the drawing.</p>' + _note +
            f'<table><thead><tr><th>Part</th>{_heads}</tr></thead><tbody>'
            + "".join(r[2] for r in rows) + '</tbody></table>')


def _purchased_key_section(summary: Dict[str, Any]) -> str:
    """What each purchased part was looked up BY, and whether we had a real key to use.

    "No price found" is two different problems wearing one face. Either the manufacturer's
    number was tried and nobody had it -- which an estimator can act on, by asking the
    supplier -- or there was never a number to try, because the drawing named the part in
    prose and the engine minted BI-BINDINGSCREW to stand in for it. Only the second is ours,
    and it is invisible unless the report says which happened.

    CAPTURING THE REFERENCE WITHOUT SHOWING IT WOULD BE THE SAME DEFECT IN A NEW PLACE. This
    engine's recurring failure is correct evidence with no reader; a supplier_references field
    that appears only in the JSON is exactly that.
    """
    try:
        import supplier_reference as _sr
    except Exception:
        return ""
    parts = [p for p in (_extract_parts(summary) or [])
             if isinstance(p, dict) and (p.get("supplier_references")
                                         or _sr.is_synthesised_key(p.get("part_number")))]
    if not parts:
        return ""
    rows, keyless = [], 0
    for p in parts:
        refs = p.get("supplier_references") or []
        minted = _sr.is_synthesised_key(p.get("part_number"))
        if not refs:
            keyless += 1
        keys = ", ".join(str(r.get("reference")) for r in refs[:3]) or "&mdash;"
        conv = ", ".join(sorted({str(r.get("convention") or "") for r in refs})) or (
            "none found on the drawing")
        rows.append((0 if not refs else 1, str(p.get("part_number") or ""),
                     f'<tr class="{"over" if not refs else ""}">'
                     f'<td class="pn">{_esc(p.get("part_number"))}</td>'
                     f'<td class="mini">{_esc(p.get("description") or "")}</td>'
                     f'<td class="mini">{keys}</td>'
                     f'<td class="mini">{_esc(conv)}</td>'
                     f'<td class="mini">{"minted here" if minted else "read off the drawing"}</td>'
                     f'</tr>'))
    rows.sort(key=lambda r: (r[0], r[1]))          # the ones with no real key first
    _note = (f'<p class="mini"><b>{keyless} of {len(rows)} purchased line(s)</b> carry no '
             f'manufacturer reference at all, so the only key available was one this engine '
             f'minted from the description. Nothing in any catalogue, price file or supplier '
             f'system has ever heard of that key, so those lines cannot be priced by lookup '
             f'however good the catalogue gets &mdash; they need the number off the drawing '
             f'or off the estimator.</p>' if keyless else
             '<p class="mini">Every purchased line carries a manufacturer reference, so every '
             'one of them can be priced by lookup against a catalogue or a supplier price '
             'file that uses the same key.</p>')
    return ('<h2>10 &nbsp;What each purchased part was looked up by</h2>'
            '<p class="mini">A price lookup can only find what it asks for. These are the '
            'keys used for the bought-in lines, lines with no real key first.</p>' + _note +
            '<table><thead><tr><th>Part</th><th>Description</th>'
            '<th>Manufacturer reference</th><th>Convention</th><th>Part number</th>'
            '</tr></thead><tbody>' + "".join(r[2] for r in rows) + '</tbody></table>')


def _unpriced_section(summary: Dict[str, Any]) -> str:
    """Every line the sheet priced at nothing, and WHOSE nothing it is.

    A blank in a price column reads as free. On this pack sixteen fabricated lines sit at
    GBP 0.00 because their material is costed in the Sheet Steel block -- pricing them again
    would double the material total -- beside a lock and a mag catch that genuinely are not
    priced at all. Identical on the sheet, opposite actions, and until the reasons were
    written nothing anywhere could tell them apart.

    ORDERED BY WHO HAS TO ACT, WORST FIRST. An engine gap is work that will be done and
    invoiced with nothing on the sheet asking anyone to price it, so the job is under-charged
    by that amount and no estimator input can fix it. That is the only category here worth
    interrupting somebody for, so it leads.
    """
    try:
        import price_provenance as _pp
        # EITHER SHAPE. Some writers stamp final_estimate on the summary root and some inside
        # estimate_summary. Reading one place only renders an empty section on every job of
        # the other shape — which here means a report that silently claims nothing is unpriced.
        _fe = summary.get("final_estimate")
        if not isinstance(_fe, dict):
            _fe = (summary.get("estimate_summary") or {}).get("final_estimate") or {}
    except AttributeError:
        return ""
    # THE SECTION DISAPPEARING IS THE SAME LIE THE TABLE WOULD TELL. When the Excel read-back
    # fails -- Excel busy or absent, a workbook that will not open -- there is no
    # final_estimate, so there are no rows, so this section rendered nothing at all and the
    # report read as a job with no unpriced lines. The estimate on that page is then built
    # from the PRE-Excel numbers, which is a different total, and nothing on the page says so.
    if not _fe:
        return ('<h2>11 &nbsp;Why these lines carry no price</h2>'
                '<div class="callout warn"><b>The calculated sheet was never read back, so '
                'this could not be checked.</b> No material row reached this report, which is '
                'not the same as a job with nothing unpriced &mdash; the figures above come '
                'from before Excel calculated, and no blank on the sheet has been examined.'
                '</div>')
    rows = _fe.get("material_rows") or []
    if not rows:
        return ""
    blanks = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        value = r.get("price_gbp", r.get("total_value_gbp", r.get("unit_price_gbp")))
        try:
            if value is not None and float(value) != 0:
                continue
        except (TypeError, ValueError):
            pass
        blanks.append(r)
    if not blanks:
        return ('<h2>11 &nbsp;Why these lines carry no price</h2>'
                '<p class="mini">Every material line on this job carries a price.</p>')
    # A SHEET FULL OF BLANKS AND NO REASONS IS THE DEFECT, NOT AN EMPTY SECTION. The
    # vocabulary existed for months with no writer and the check stayed green throughout;
    # a report that quietly shows an empty table when the stamping did not run would let
    # exactly that happen again, one layer up.
    if not any(isinstance(r.get("unpriced_reason"), dict) for r in blanks):
        return ('<h2>11 &nbsp;Why these lines carry no price</h2>'
                f'<div class="callout warn"><b>{len(blanks)} line(s) carry no price and no '
                f'recorded reason.</b> A blank in a price column reads as free. Nothing on '
                f'this job says which of them are correctly nil, which are waiting on an '
                f'estimator, and which are work this engine cannot charge for.</div>')
    _RANK = {"engine": 0, "estimator": 1, "nobody": 2}
    out, tally = [], {"engine": 0, "estimator": 0, "nobody": 0}
    for r in blanks:
        reason = r.get("unpriced_reason")
        reason = reason if isinstance(reason, dict) else _pp.unpriced_reason(_pp.UNEXPLAINED)
        owner = reason.get("owner") or "engine"
        tally[owner] = tally.get(owner, 0) + 1
        code = str(r.get("part_number") or r.get("part_code") or r.get("description") or "?")
        out.append((_RANK.get(owner, 0), code,
                    f'<tr class="{"over" if reason.get("undercharging") else ""}">'
                    f'<td class="pn">{_esc(code[:40])}</td>'
                    f'<td class="mini">{_esc(reason.get("category"))}</td>'
                    f'<td class="mini">{_esc(reason.get("why"))}'
                    + (f' &mdash; {_esc(reason.get("detail"))}' if reason.get("detail") else "")
                    + f'</td><td class="mini">{_esc(owner)}</td></tr>'))
    out.sort(key=lambda t: (t[0], t[1]))
    gaps = tally.get("engine", 0)
    _lead = (f'<div class="callout warn"><b>{gaps} line(s) are unpriced because this ENGINE '
             f'has no way to price them</b>, not because anything is missing from the '
             f'drawings. That work will be done and invoiced. The job is under-charged by '
             f'that amount and no estimator input can fix it.</div>' if gaps else
             '<p class="mini">No line is unpriced because of a gap in the engine.</p>')
    return ('<h2>11 &nbsp;Why these lines carry no price</h2>'
            f'<p class="mini">{len(blanks)} blank line(s): <b>{tally.get("estimator", 0)}</b> '
            f'waiting on the estimator, <b>{tally.get("nobody", 0)}</b> correctly nil '
            f'(costed elsewhere, a duplicate article, or an assembly whose material is its '
            f'children\'s), <b>{gaps}</b> the engine cannot price. Worst first.</p>'
            + _lead +
            '<table><thead><tr><th>Line</th><th>Kind of nothing</th><th>Why</th>'
            '<th>Who acts</th></tr></thead><tbody>'
            + "".join(r[2] for r in out) + '</tbody></table>')


def _route_decisions_section(summary: Dict[str, Any]) -> str:
    """Where every route decision was taken, and which of them were contested.

    THIS RENDERS ON EVERY JOB. The only route detail the report carried before came from
    parity_report_html and appeared solely when a manual workbook was passed with
    --parity-workbook -- so on an ordinary run, the document an estimator works from could
    not say what decided a single operation. "Where did this come from" is the first
    question asked of any estimate this engine produces, and the report had no answer.

    CONTESTED LINES COME FIRST, and say what the other source claimed. A decision taken
    over an objection is the one worth reading, and the table that buries it among fifty
    unanimous rows has hidden the only line that needed a person.
    """
    payload = {}
    try:
        payload = ((summary.get("estimate_summary") or {}).get("canonical_route_shadow")
                   or summary.get("canonical_route_shadow") or {})
    except Exception:
        payload = {}
    decisions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(decisions, list) or not decisions:
        # SILENCE IS NOT A CLEAN BILL. A job with no compiled route has had no operation
        # arbitrated at all, and a missing section reads as "nothing to report".
        return ('<h2>12 &nbsp;How each operation was decided</h2>'
                '<div class="callout warn"><b>No compiled route on this job.</b> No operation '
                'was arbitrated, so nothing here can say what decided it. The labour below '
                'came from the legacy path.</div>')

    rows, contested_n = [], 0
    for d in decisions:
        if not isinstance(d, dict):
            continue
        _contested = bool(d.get("contested"))
        contested_n += 1 if _contested else 0
        _losing = ", ".join(str(x) for x in (d.get("losing_statuses") or []))
        _ev = str(d.get("evidence") or "")
        rows.append((
            0 if _contested else 1,                       # contested first
            str(d.get("target_id") or ""),
            f'<tr class="{"over" if _contested else ""}">'
            f'<td class="pn"><a id="route-{_esc(d.get("target_id"))}" href="#bom-{_esc(d.get("target_id"))}">{_esc(d.get("target_id"))}</a></td>'
            f'<td>{_esc(str(d.get("operation") or "").replace("_", " "))}</td>'
            f'<td>{_esc(d.get("status"))}</td>'
            f'<td>{_esc(d.get("decided_by") or d.get("source") or "not recorded")}</td>'
            f'<td class="num">{_esc(d.get("source_rank"))}</td>'
            f'<td>{("<b>resolved over " + _esc(_losing) + "</b> &#8226; by " + _esc(d.get("settled_by_key") or "rank")) if _contested else "—"}</td>'
            f'<td class="mini">{_esc(_ev[:70]) if _ev else "<i>nothing quoted</i>"}</td></tr>'))
    if not rows:
        return ""
    rows.sort(key=lambda r: (r[0], r[1]))
    _note = (f'<p class="mini"><b>{contested_n} decision(s) were contested</b> and are listed '
             f'first: two equally-ranked sources disagreed and the arbiter settled it. '
             f'The losing claim is named so it can be checked.</p>' if contested_n else
             '<p class="mini">No decision was contested — every operation had a single '
             'strongest source and nothing at that rank disagreed with it.</p>')
    return ('<h2>12 &nbsp;How each operation was decided</h2>'
            '<p class="mini">Every operation on this job, the source that decided it and the '
            'rank that source carries. "Nothing quoted" means no claim carried the drawing\'s '
            'own words, so the decision cannot be held against the sheet.</p>'
            + _note +
            '<table><thead><tr><th>Part</th><th>Operation</th><th>Status</th>'
            '<th>Decided by</th><th>Rank</th><th>Contested</th><th>Drawing says</th>'
            '</tr></thead><tbody>' + "".join(r[2] for r in rows) + '</tbody></table>')


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
        return ('<h2>13 &nbsp;Consistency checks</h2>'
                '<div class="callout warn"><b>The consistency checks did not run on this job.</b> '
                'Nothing here has been verified against the workbook: rows have not been '
                'reconciled to their totals, priced rows have not been joined to the parts that '
                'produced them, and geometry claims have not been tested. Treat every figure in '
                'this report as unverified.</div>')
    _v = [x for x in (inv.get("violations") or []) if isinstance(x, dict)]
    _n = len(inv.get("checks_run") or [])
    if inv.get("may_quote_firm") and not _v:
        return (f'<h2>13 &nbsp;Consistency checks</h2>'
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
        _DETAIL_LISTS = ("parts", "lines", "rows", "problems", "failed_paths", "files")
        for _k in _DETAIL_LISTS:
            for _item in (_d.get(_k) or [])[:8]:
                if isinstance(_item, dict):
                    # `part` as well as `part_number`: the firmness checks report a line by
                    # whatever named it, and a detail block that renders as a bare count is
                    # the thing this whole section exists to stop.
                    _lbl = (_item.get("part_number") or _item.get("part")
                            or _item.get("workbook_row") or _item.get("block")
                            or _item.get("path") or _item.get("where"))
                    _why = (_item.get("geometry_source") or _item.get("wb_operation")
                            or _item.get("reason") or _item.get("code")
                            or _item.get("material_class") or "")
                    _bits.append(f"{_lbl}{f' ({_why})' if _why else ''}")
                elif _item:
                    _bits.append(str(_item))
        for _k, _v in sorted(_d.items()):
            if _k in _DETAIL_LISTS or _v in (None, "", [], {}):
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
    return (f'<h2>13 &nbsp;Consistency checks</h2>{_head}'
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
        _render_drawing_analysis(dq, summary),
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
