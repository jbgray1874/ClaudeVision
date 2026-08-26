#!/usr/bin/env python3
r"""
parity_report_html.py — GENERAL parity diagnostic report generator (any job).

Reads a parity BUNDLE (produced by estimate_full_parity_report.py) and renders a self-contained
HTML diagnostic in the SDI navy house style. Job-agnostic: every number comes from the bundle,
nothing is hard-coded per job. Runs on-demand OR is called by the AI run to auto-write the report
into the same folder as the populated spreadsheet.

Usage:
  python parity_report_html.py --bundle <job_bundle.json> --out <job>_parity.html
                               [--analysis <job>_analysis.json]

The optional --analysis JSON adds the human-diagnosis narrative (root causes, what's correct,
path to parity). Without it, a complete DATA report is produced. Schema:
  {"root_causes":[{"tag":"bug|feature|rate|parked|ok","id":"..","title":"..",
                   "location":"file.py:123","body":"html-ok text"}],
   "whats_correct":["..",".."],
   "path_to_parity":[{"id":"A","fix":"..","moves":"~£10","effort":"bug","owner":".."}]}
"""
from __future__ import annotations
import argparse, json, html, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _gbp(v: Any) -> str:
    f = _f(v)
    return "—" if f is None else ("-£%.2f" % -f if f < 0 else "£%.2f" % f)


def _pct(v: Any) -> str:
    f = _f(v)
    return "—" if f is None else ("%+.1f%%" % f)


def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


# --------------------------------------------------------------------------- money / sections
def _money_rows(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """De-duplicated section-subtotal comparisons from the bundle's label-scan."""
    seen = set()
    out = []
    for r in (bundle.get("money_cell_comparisons") or []):
        if r.get("section") != "money_cell":
            continue
        label = str(r.get("label") or "")
        # collapse the duplicate 'Unit manufacturing cost (L)/(M)' into one row
        key = label.replace(" (L)", "").replace(" (M)", "").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "label": label.replace(" (L)", "").replace(" (M)", "").strip(),
            "engine": _f(r.get("json_numeric")),
            "manual": _f(r.get("workbook_cached_numeric")),
            "pct": _f(r.get("pct_variance")),
            "status": r.get("status"),
        })
    return out


def _find_row(rows: List[Dict[str, Any]], *needles: str) -> Optional[Dict[str, Any]]:
    for r in rows:
        lab = (r.get("label") or "").lower()
        if all(n in lab for n in needles):
            return r
    return None


# --------------------------------------------------------------------------- labour route
def _route_rows(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Per-operation route view. The bundle does NOT reliably carry the manual per-operation
    COST (workbook_line_cost_gbp is 0/None; the builder flags this and routes the labour
    magnitude verdict to the section subtotal). So we present engine cost + the SDI-code route
    mapping honestly, and report whether manual per-op cost was available at all.

    Returns {"rows":[...], "manual_cost_available": bool}."""
    rows = []
    any_manual_cost = False
    for r in (bundle.get("labour_route_comparisons") or []):
        if r.get("section") != "labour_route":
            continue
        if r.get("status") in ("noise", "blank"):
            continue
        can = r.get("canonical_operation")
        disp = r.get("display_label") or can or r.get("operation_code")
        eng = _f(r.get("json_labour_cost_gbp"))
        man = _f(r.get("workbook_line_cost_gbp"))
        if man is not None and man > 0:
            any_manual_cost = True
        # only list operations that actually appear on one side or the other
        codes = r.get("workbook_operation_codes") or r.get("json_sdi_codes") or []
        on_manual = bool(codes) or (man is not None and man > 0)
        if eng is None and not on_manual:
            continue
        rows.append({
            "op": disp,
            "engine": eng,               # engine cost (reliable)
            "manual": man,               # manual cost (often 0/None — not reliable)
            "eng_hours": _f(r.get("json_hours_decimal")),
            "codes": codes,
            "on_manual": on_manual,
        })
    # sort: engine cost desc, so the operations the engine books most sit on top
    rows.sort(key=lambda x: (x["engine"] or 0.0), reverse=True)
    return {"rows": rows, "manual_cost_available": any_manual_cost}


# --------------------------------------------------------------------------- reconciliation
def _recon(bundle: Dict[str, Any]) -> Dict[str, Any]:
    return bundle.get("bom_set_reconciliation") or {}


# --------------------------------------------------------------------------- header facts
def _facts(bundle: Dict[str, Any]) -> Dict[str, Any]:
    disc = bundle.get("estimate_sheet_discovery") or {}
    qa = disc.get("parity_quantity_aligned_from_workbook") or {}
    wb_qty = _f(bundle.get("workbook_cell_D6_quantity")) or _f(qa.get("workbook_quantity"))
    json_qty = _f(qa.get("json_quantity_before_overlay"))
    ruc = bundle.get("rollup_unit_cost_comparison") or {}
    return {
        "workbook_path": bundle.get("workbook_path") or "",
        "workbook_qty": wb_qty,
        "json_qty": json_qty,
        "qty_mismatch": (wb_qty is not None and json_qty is not None and abs(wb_qty - json_qty) > 0.5),
        "manual_unit": _f(ruc.get("workbook_unit_cost_cached")),
    }


# =========================================================================== HTML rendering
_CSS = """
:root{--navy:#1F3864;--navy2:#2E4C7E;--ink:#1e293b;--muted:#64748b;--line:#e2e8f0;--bg:#f8fafc;
--panel:#fff;--over:#991b1b;--over-bg:#fef2f2;--under:#1d4ed8;--under-bg:#eff6ff;--ok:#166534;
--ok-bg:#f0fdf4;--warn:#b45309;--warn-bg:#fffbeb;--code:#f1f5f9;}
*{box-sizing:border-box;}
body{font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;color:var(--ink);background:var(--bg);
line-height:1.55;margin:0;padding:32px;}
.wrap{max-width:960px;margin:0 auto;}
h1{color:var(--navy);font-size:23px;margin:0 0 3px;}
h2{color:var(--navy);font-size:18px;margin:30px 0 8px;padding-bottom:6px;border-bottom:2px solid var(--navy);}
h3{color:var(--navy2);font-size:14px;margin:14px 0 6px;}
.sub{color:var(--muted);font-size:13px;margin:0 0 4px;}
.tagline{color:var(--muted);font-size:12px;font-style:italic;margin:0 0 20px;}
p{margin:8px 0;}
code,.pn{font-family:'Courier New',monospace;background:var(--code);padding:1px 5px;border-radius:4px;font-size:12.5px;}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px;}
th{background:var(--navy);color:#fff;text-align:left;padding:7px 10px;font-weight:600;}
td{padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top;}
tr:nth-child(even) td{background:#fafcff;}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}
.over{color:var(--over);font-weight:600;}.under{color:var(--under);font-weight:600;}.ok{color:var(--ok);font-weight:600;}
.hero{display:flex;gap:14px;margin:14px 0;}
.hero>div{flex:1;border:1px solid var(--line);border-radius:8px;padding:14px 16px;text-align:center;}
.hero .big{font-size:25px;font-weight:700;color:var(--navy);}
.hero .lbl{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin-bottom:4px;}
.callout{border-left:4px solid;border-radius:6px;padding:12px 16px;margin:14px 0;}
.c-ok{background:var(--ok-bg);border-color:var(--ok);}.c-ok b{color:var(--ok);}
.c-warn{background:var(--warn-bg);border-color:var(--warn);}.c-warn b{color:var(--warn);}
.c-info{background:var(--under-bg);border-color:var(--under);}.c-info b{color:var(--under);}
.tag{display:inline-block;font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:10px;}
.t-feat{background:#e0e7ff;color:#3730a3;}.t-bug{background:#fee2e2;color:#991b1b;}
.t-rate{background:#fef9c3;color:#854d0e;}.t-park{background:#e5e7eb;color:#374151;}.t-ok{background:#dcfce7;color:#166534;}
.root{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 18px;margin:12px 0;}
.root .loc{font-family:'Courier New',monospace;font-size:12px;color:var(--navy2);background:var(--code);padding:2px 6px;border-radius:4px;}
ul{margin:6px 0 6px 2px;padding-left:20px;}li{margin:4px 0;}
.foot{color:var(--muted);font-size:12px;margin-top:26px;padding-top:12px;border-top:1px solid var(--line);}
.muted{color:var(--muted);}
.pill{font-size:11px;padding:1px 7px;border-radius:9px;background:var(--code);color:var(--muted);}
"""


def _delta_class(engine: Optional[float], manual: Optional[float]) -> str:
    if engine is None or manual is None:
        return ""
    return "over" if engine > manual else ("under" if engine < manual else "ok")


def _section_table(rows: List[Dict[str, Any]]) -> str:
    """Δ AND THE PERCENTAGE MUST POINT THE SAME WAY, OR THE TABLE READS BACKWARDS.

    The bundle's own `pct_variance` is a magnitude measured against the ENGINE figure, with no
    direction: material came out `Δ -£179.27` beside `+163.5%`. The engine is £179 lower and the
    percentage says positive. Read at a glance — which is how a variance column is read — it
    announced the engine as 163% over when it was 62% under.

    So the percentage is computed here from the same two numbers as Δ, against the MANUAL figure,
    which is what "the engine is x% under the estimator" means to the person reading it. The
    header says which way round it is rather than leaving it to be inferred.
    """
    body = []
    for r in rows:
        e, m = r["engine"], r["manual"]
        d = (e - m) if (e is not None and m is not None) else None
        cls = _delta_class(e, m)
        # Signed, and against the manual. Falls back to the bundle's own figure only when the
        # delta cannot be computed, where there is no sign to disagree with anyway.
        if d is not None and m:
            var = _pct(d / m * 100.0)
        elif d is not None and not m:
            var = "—"                      # manual is zero: a percentage of nothing says nothing
        else:
            var = _pct(r["pct"]) if r.get("pct") is not None else "—"
        body.append(
            "<tr><td>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
            "<td class='num %s'>%s</td><td class='num %s'>%s</td></tr>" % (
                _esc(r["label"]), _gbp(e), _gbp(m), cls, (_gbp(d) if d is not None else "—"),
                cls, var))
    return ("<table><tr><th>Section</th><th class='num'>Engine</th><th class='num'>Manual</th>"
            "<th class='num'>&Delta;</th><th class='num'>Var vs manual</th></tr>%s</table>"
            % "".join(body))


def _route_table(route: Dict[str, Any]) -> str:
    rows = route["rows"]
    has_manual = route["manual_cost_available"]
    body = []
    for r in rows:
        e = r["engine"]
        eh = ("%.2f" % r["eng_hours"]) if r.get("eng_hours") is not None else "—"
        codes = ", ".join(str(c) for c in (r.get("codes") or [])[:5])
        booked = "engine + manual" if (r.get("on_manual") and e is not None) else (
                 "manual only" if r.get("on_manual") else "engine only")
        bcls = "" if r.get("on_manual") and e is not None else ("under" if r.get("on_manual") else "over")
        # Manual £ column only shown if it's actually reliable in this bundle
        if has_manual:
            m = r["manual"]
            d = (e - m) if (e is not None and m is not None) else None
            dcls = "" if d is None else ("over" if d > 0 else ("under" if d < 0 else ""))
            body.append(
                "<tr><td>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                "<td class='num %s'>%s</td><td class='num'>%s</td>"
                "<td class='muted' style='font-size:11.5px'>%s</td></tr>" % (
                    _esc(r["op"]), _gbp(e), _gbp(m), dcls,
                    (_gbp(d) if d is not None else "—"), eh, _esc(codes)))
        else:
            body.append(
                "<tr><td>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                "<td class='%s' style='font-size:11.5px'>%s</td>"
                "<td class='muted' style='font-size:11.5px'>%s</td></tr>" % (
                    _esc(r["op"]), _gbp(e), eh, bcls, _esc(booked), _esc(codes)))
    if has_manual:
        head = ("<tr><th>Operation</th><th class='num'>Engine £</th><th class='num'>Manual £</th>"
                "<th class='num'>&Delta;</th><th class='num'>Eng hrs</th><th>SDI codes</th></tr>")
    else:
        head = ("<tr><th>Operation</th><th class='num'>Engine £</th><th class='num'>Engine hrs</th>"
                "<th>Booked on</th><th>SDI codes (route mapping)</th></tr>")
    return "<table>%s%s</table>" % (head, "".join(body))


def _matched_table(recon: Dict[str, Any]) -> str:
    ms = recon.get("matched") or []
    if not ms:
        return "<p class='muted'>No lines matched on part code between the two estimates.</p>"
    body = []
    for m in ms:
        kind = m.get("match_kind", "code")
        pill = "code" if kind == "code" else "code-stem"
        mc, ac = _f(m.get("manual_cost_gbp")), _f(m.get("ai_cost_gbp"))
        var = _f(m.get("variance_pct"))
        cls = "" if var is None else ("over" if var > 3 else ("under" if var < -3 else "ok"))
        body.append(
            "<tr><td><span class='pn'>%s</span> <span class='pill'>%s</span></td>"
            "<td><span class='pn'>%s</span></td><td>%s</td>"
            "<td class='num'>%s</td><td class='num'>%s</td><td class='num %s'>%s</td></tr>" % (
                _esc(m.get("code")), pill, _esc(m.get("ai_code") or m.get("code")),
                _esc(m.get("description")), _gbp(mc), _gbp(ac),
                cls, (_pct(var) if var is not None else "—")))
    return ("<table><tr><th>Manual code</th><th>Engine code</th><th>Description</th>"
            "<th class='num'>Manual £</th><th class='num'>Engine £</th><th class='num'>Var</th></tr>"
            "%s</table>" % "".join(body))


def _unmatched_section(recon: Dict[str, Any]) -> str:
    """"THEY ARE NOT MISSES" WAS A HARDCODED SENTENCE THAT CONTRADICTED THE DATA UNDER IT.

    The reconciliation classifies every unmatched line. On 10575-02 four carried
    `category: "genuine_miss"` with the issue "the engine should have produced this. Investigate."
    — one of them 20KGMOQ, the £12.50 of powder the engine costed at nothing. This function read
    only `.get("code")`, threw away the category, the issue and both cost fields, and printed a
    blanket denial over the top. The most important line in the comparison was presented as
    nothing to worry about.

    The lines are now separated by what the bundle says they are, and the money is shown, because
    a gap with no cost against it cannot be prioritised.
    """
    mo = list(recon.get("manual_only") or [])
    ao = list(recon.get("ai_only") or [])
    if not mo and not ao:
        return ""

    # FOUR BUCKETS, NOT TWO. "Everything that is not a miss" was a naming-differences table, which
    # meant logistics the estimator adds at quote time — and later powder, which the engine costs
    # per part — were both presented as the two estimates spelling a part name differently. Three
    # unrelated situations reading as one, and the reader given no way to tell them apart.
    def _cat(row):
        return str(row.get("category", "")).lower()

    misses = [r for r in mo if _cat(r) == "genuine_miss"]
    elsewhere = [r for r in mo if _cat(r) == "costed_elsewhere"]
    scope = [r for r in mo if _cat(r) == "out_of_scope"]
    naming = [r for r in mo if _cat(r) not in {"genuine_miss", "costed_elsewhere", "out_of_scope"}]
    out = []

    if misses:
        total = sum(_f(r.get("manual_cost_gbp")) or 0.0 for r in misses)
        out.append(
            "<div class='callout c-warn'><b>%d line(s) the engine should have produced and did not "
            "&mdash; %s on the manual estimate.</b> These are the reconciliation's own "
            "<span class='pn'>genuine_miss</span> classification, not a naming difference. Each one "
            "is work or material the estimator priced and the engine did not.</div>"
            % (len(misses), _gbp(total)))
        rows = "".join(
            "<tr><td><span class='pn'>%s</span></td><td>%s</td><td class='num'>%s</td></tr>" % (
                _esc(r.get("code")), _esc(r.get("description") or "—"),
                _gbp(r.get("manual_cost_gbp")))
            for r in sorted(misses, key=lambda r: -(_f(r.get("manual_cost_gbp")) or 0.0)))
        out.append("<table><tr><th>Missing from the engine</th><th>Description</th>"
                   "<th class='num'>Manual cost</th></tr>%s</table>" % rows)

    if ao:
        total = sum(_f(r.get("ai_cost_gbp")) or 0.0 for r in ao)
        out.append(
            "<h3>On the engine estimate only</h3>"
            "<p class='muted'>%d line(s), %s costed. Some are the engine's own naming for a part the "
            "manual calls something else; a line here that names a part from <b>another job</b>, or a "
            "part number that is not a part at all, is a fault worth reporting.</p>"
            % (len(ao), _gbp(total)))
        rows = "".join(
            "<tr><td><span class='pn'>%s</span></td><td>%s</td><td class='num'>%s</td></tr>" % (
                _esc(r.get("code")), _esc((r.get("description") or "—")[:90]),
                _gbp(r.get("ai_cost_gbp")))
            for r in sorted(ao, key=lambda r: -(_f(r.get("ai_cost_gbp")) or 0.0)))
        out.append("<table><tr><th>On engine only</th><th>Description</th>"
                   "<th class='num'>Engine cost</th></tr>%s</table>" % rows)

    if elsewhere:
        total = sum(_f(r.get("manual_cost_gbp")) or 0.0 for r in elsewhere)
        out.append(
            "<h3>Costed by the engine, in a different shape</h3>"
            "<p class='muted'>%d manual line(s), %s. <b>These are not missing.</b> The engine carries "
            "the same money somewhere other than a line with this code &mdash; powder, for instance, is "
            "priced by mass inside each part rather than bought as a catalogue item. Compare against "
            "the engine field named below; a genuine under-charge shows as a difference between the "
            "two totals, not as an absent line.</p>" % (len(elsewhere), _gbp(total)))
        rows = "".join(
            "<tr><td><span class='pn'>%s</span></td><td>%s</td><td class='num'>%s</td>"
            "<td class='muted'>%s</td></tr>" % (
                _esc(r.get("code")), _esc(r.get("description") or "—"),
                _gbp(r.get("manual_cost_gbp")), _esc(r.get("issue") or "—"))
            for r in elsewhere)
        out.append("<table><tr><th>On manual only</th><th>Description</th>"
                   "<th class='num'>Manual cost</th><th>Where the engine carries it</th></tr>"
                   "%s</table>" % rows)

    if scope:
        total = sum(_f(r.get("manual_cost_gbp")) or 0.0 for r in scope)
        out.append(
            "<h3>Out of scope for the engine</h3>"
            "<p class='muted'>%d line(s), %s. Logistics and packaging the estimator adds at quote "
            "time. Not derivable from a drawing and not an engine fault &mdash; but they are real "
            "money on the manual estimate, so they are shown rather than hidden.</p>"
            % (len(scope), _gbp(total)))
        rows = "".join(
            "<tr><td><span class='pn'>%s</span></td><td>%s</td><td class='num'>%s</td></tr>" % (
                _esc(r.get("code")), _esc(r.get("description") or "—"),
                _gbp(r.get("manual_cost_gbp")))
            for r in scope)
        out.append("<table><tr><th>On manual only</th><th>Description</th>"
                   "<th class='num'>Manual cost</th></tr>%s</table>" % rows)

    if naming:
        out.append(
            "<h3>Naming differences</h3>"
            "<p class='muted'>%d manual line(s) the reconciliation did not classify as a miss &mdash; "
            "the two estimates use different naming for the same fabricated part (e.g. "
            "<span class='pn'>1449-PEGPANEL</span> vs <span class='pn'>1449-01C</span>). Their cost is "
            "compared at the section-subtotal level above.</p>" % len(naming))
        rows = "".join(
            "<tr><td><span class='pn'>%s</span></td><td>%s</td><td class='num'>%s</td></tr>" % (
                _esc(r.get("code")), _esc(r.get("description") or "—"),
                _gbp(r.get("manual_cost_gbp")))
            for r in naming)
        out.append("<table><tr><th>On manual only</th><th>Description</th>"
                   "<th class='num'>Manual cost</th></tr>%s</table>" % rows)

    return "".join(out)


_REASON_WORDS = {
    "large_flat": "measured as one large flat panel — check it is a part and not a drawing border",
    "missing_material_thickness": "no thickness read",
    "missing_material_spec": "no material read",
    "low_part_confidence": "low confidence",
    "risk_flag": "flagged",
}


def _review_table(bundle: Dict[str, Any]) -> str:
    """NAME THE PARTS. The section said "4 part(s) flagged" and referred the reader to another
    document for which four. The bundle carries them, with reasons, and a count nobody can act
    on is not a review section."""
    sig = ((bundle.get("estimate_provenance") or {}).get("estimate_review_signals") or {})
    flagged = sig.get("parts_flagged") or []
    if not flagged:
        return ""
    rows = []
    for p in flagged:
        why = []
        for r in p.get("reasons") or []:
            code, detail = str(r.get("code") or ""), r.get("detail")
            if code == "low_part_confidence":
                why.append("confidence %s" % detail)
            else:
                why.append(_REASON_WORDS.get(str(detail), str(detail or code)))
        rows.append("<tr><td><span class='pn'>%s</span></td><td>%s</td><td>%s</td></tr>" % (
            _esc(p.get("part_number")), _esc(p.get("description") or "—"),
            _esc("; ".join(why) or "—")))
    return ("<table><tr><th>Part</th><th>Description</th><th>Why it is flagged</th></tr>%s</table>"
            % "".join(rows))


def _unpriced_table(bundle: Dict[str, Any]) -> str:
    """Parts the engine carried at nothing.

    This is where an incomplete pack shows up as money. A BOM line whose drawing was never
    supplied reaches the estimate as a part with a material of "REFER TO INDIVIDUAL COMPONENT
    DRAWINGS" and a cost of £0 — which sums into a total that still reads as a finished estimate.
    Naming them here answers the question the headline gap raises.
    """
    prov = bundle.get("estimate_provenance") or {}
    rows = []
    for p in prov.get("parts_for_demo") or []:
        cost = _f(p.get("unit_total_cost_gbp"))
        if cost is None or cost > 0.005:
            continue
        rows.append("<tr><td><span class='pn'>%s</span></td><td>%s</td><td>%s</td></tr>" % (
            _esc(p.get("part_number")), _esc(p.get("description") or "—"),
            _esc((p.get("database_system_cost") or {}).get("supplier_name")
                 or (p.get("material_price") or {}).get("supplier_display") or "—")))
    if not rows:
        return ""
    return ("<div class='callout c-warn'><b>%d part(s) reached the estimate costing nothing.</b> "
            "A £0 line is not a free part &mdash; it is a part nothing could price, and it sums "
            "into a total that still reads as finished. Where the reason is "
            "<span class='pn'>REFER TO INDIVIDUAL COMPONENT DRAWINGS</span>, the detail drawing was "
            "not in the pack.</div>"
            "<table><tr><th>Part</th><th>Description</th><th>Why nothing was applied</th></tr>%s"
            "</table>" % (len(rows), "".join(rows)))


def _powder_note(bundle: Dict[str, Any], recon: Dict[str, Any]) -> str:
    """Powder as a number rather than a dash in the route table.

    The route table showed "Powder Coating — manual only", which is a hint. The bundle holds the
    engine's own powder total and the manual's powder line, and the two together are a finding.
    """
    prov = bundle.get("estimate_provenance") or {}
    pc = prov.get("powder_coating_summary") or {}
    eng = _f(pc.get("powder_total_gbp"))
    if eng is None:
        return ""
    man = 0.0
    for r in (recon.get("manual_only") or []):
        if "powder" in str(r.get("description", "")).lower() or "POWDER" in str(r.get("code", "")):
            man += _f(r.get("manual_cost_gbp")) or 0.0
    if eng > 0.005 or man <= 0.005:
        return ""
    return ("<div class='callout c-warn'><b>Powder coating: engine £0.00, manual %s.</b> "
            "The engine applied no powder material and no powder labour to a job the estimator "
            "powder coated. Powder is the one finish this engine can cost, so a zero here is a "
            "gap in the route, not a finish it was never asked to price.</div>" % _gbp(man))


def _analysis_html(analysis: Optional[Dict[str, Any]]) -> str:
    if not analysis:
        return ""
    parts = []
    rc = analysis.get("root_causes") or []
    if rc:
        parts.append("<h2>Root causes</h2>")
        for c in rc:
            tag = c.get("tag", "feat")
            loc = ("<span class='loc'>%s</span>" % _esc(c["location"])) if c.get("location") else ""
            parts.append(
                "<div class='root'><h3><span class='tag t-%s'>%s</span> &nbsp;%s</h3>"
                "<p>%s %s</p></div>" % (
                    _esc(tag), _esc(tag), _esc(c.get("title", "")), c.get("body", ""), loc))
    wc = analysis.get("whats_correct") or []
    if wc:
        parts.append("<h2>What's correct &mdash; credit where due</h2><div class='callout c-ok'>"
                     "<ul>%s</ul></div>" % "".join("<li>%s</li>" % w for w in wc))
    pp = analysis.get("path_to_parity") or []
    if pp:
        rows = "".join(
            "<tr><td>%s</td><td>%s</td><td class='num'>%s</td>"
            "<td><span class='tag t-%s'>%s</span></td><td class='muted'>%s</td></tr>" % (
                _esc(s.get("id", "")), _esc(s.get("fix", "")), _esc(s.get("moves", "")),
                _esc(s.get("effort", "park")), _esc(s.get("effort", "")), _esc(s.get("owner", "")))
            for s in pp)
        parts.append("<h2>Path to parity</h2><table><tr><th>#</th><th>Fix</th>"
                     "<th class='num'>Moves</th><th>Effort</th><th>Owner / next step</th></tr>"
                     "%s</table>" % rows)
    return "".join(parts)


def generate_parity_html(bundle: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> str:
    facts = _facts(bundle)
    money = _money_rows(bundle)
    route = _route_rows(bundle)
    recon = _recon(bundle)

    unit = _find_row(money, "unit")
    mat = _find_row(money, "material")
    lab = _find_row(money, "labour")

    eng_unit = unit["engine"] if unit else None
    man_unit = unit["manual"] if unit else facts.get("manual_unit")
    diff = (eng_unit - man_unit) if (eng_unit is not None and man_unit is not None) else None

    # Clean job name: take the filename stem from any path style (UNC/Windows/posix), tidy noise.
    _wbp = str(bundle.get("workbook_path", "job")).replace("\\", "/")
    job = _wbp.rsplit("/", 1)[-1]
    for _ext in (".xls", ".xlsx", ".xlsm"):
        if job.lower().endswith(_ext):
            job = job[: -len(_ext)]
    job = job.strip().strip("-").strip() or "job"
    now = datetime.datetime.now().strftime("%d %b %Y %H:%M")

    # qty caveat
    qty_note = ""
    if facts["qty_mismatch"]:
        qty_note = (
            "<div class='callout c-info'><b>Quantities differ &mdash; read per-unit numbers with care.</b> "
            "The engine estimate is at qty <b>%s</b>; the manual estimate is at qty <b>%s</b>. Setup costs "
            "amortise differently, so per-unit figures are not strictly like-for-like. The comparison below "
            "uses the workbook-formula-equivalent figures (computed the same way on both sides).</div>" % (
                _esc(int(facts["json_qty"])) if facts["json_qty"] else "—",
                _esc(int(facts["workbook_qty"])) if facts["workbook_qty"] else "—"))

    # two-opposite-errors callout (auto)
    opp = ""
    if mat and lab and mat["engine"] is not None and mat["manual"] is not None \
            and lab["engine"] is not None and lab["manual"] is not None:
        md = mat["engine"] - mat["manual"]
        ld = lab["engine"] - lab["manual"]
        if md * ld < 0 and (abs(md) > 5 or abs(ld) > 5):
            opp = ("<div class='callout c-warn'><b>Material and labour diverge in opposite directions.</b> "
                   "Material is %s (%s) while labour is %s (%s) &mdash; the two partly offset in the unit "
                   "total, so a close-looking total can hide two real gaps. Both are broken out below.</div>" % (
                       "over" if md > 0 else "under", _gbp(md),
                       "over" if ld > 0 else "under", _gbp(ld)))

    # RAG verdict on unit variance
    verdict, vclass = "Review", "c-warn"
    if diff is not None and man_unit:
        p = abs(diff) / man_unit * 100
        if p <= 5:
            verdict, vclass = "On track &mdash; within 5% of the manual estimate", "c-ok"
        elif p <= 15:
            verdict, vclass = "Needs a look &mdash; 5&ndash;15% from the manual estimate", "c-warn"
        else:
            verdict, vclass = "Material variance &mdash; over 15% from the manual estimate", "c-warn"

    parts_flagged = ((bundle.get("estimate_provenance") or {}).get("estimate_review_signals") or {})
    # COUNT THE LIST WHEN THE COUNTER IS ABSENT. Keying the whole section off one summary field
    # meant a bundle carrying the flagged parts but not the tally dropped them silently — the
    # parts are the point, the number is a convenience.
    flag_n = parts_flagged.get("flagged_part_count")
    if not flag_n:
        flag_n = len(parts_flagged.get("parts_flagged") or []) or None

    body = []
    body.append("<h1>Parity Diagnostic &mdash; %s</h1>" % _esc(job))
    body.append("<p class='sub'>Engine estimate vs manual benchmark &middot; generated %s</p>" % _esc(now))
    body.append("<p class='tagline'>Internal &mdash; engineering &amp; estimating. Section subtotals and "
                "per-operation labour are compared like-for-like; part lines are matched where codes agree, "
                "otherwise rolled into section totals. All figures from the parity bundle.</p>")

    body.append("<div class='hero'><div><div class='lbl'>Engine unit cost</div><div class='big'>%s</div></div>"
                "<div><div class='lbl'>Manual</div><div class='big'>%s</div></div>"
                "<div><div class='lbl'>Difference</div><div class='big'>%s</div></div></div>" % (
                    _gbp(eng_unit), _gbp(man_unit), (_gbp(diff) if diff is not None else "—")))
    body.append("<div class='callout %s'><b>%s</b></div>" % (vclass, verdict))
    body.append(qty_note)
    body.append(opp)

    body.append("<h2>1 &middot; Section subtotals &mdash; engine vs manual</h2>")
    body.append("<p class='muted'>The reliable comparison: each estimate's own section totals, found by "
                "label. Positive &Delta; = engine higher.</p>")
    body.append(_section_table(money))

    body.append("<h2>2 &middot; Labour by operation</h2>")
    if route["manual_cost_available"]:
        body.append("<p class='muted'>Per-operation engine vs manual. SDI codes show how the engine's "
                    "canonical operations map to the workbook route codes (e.g. tubebend folds into "
                    "Folding, spotweld into Welding) &mdash; so some rows group codes the manual keeps "
                    "separate. The reliable labour verdict is the <b>Labour subtotal</b> in Section 1.</p>")
    else:
        body.append("<div class='callout c-info'><b>Operation-level view &mdash; engine costs and route "
                    "mapping.</b> The manual estimate expresses labour as many small hour-lines and its "
                    "per-operation cost is not cleanly extractable, so this table shows the engine's cost "
                    "per operation and which SDI route codes each maps to. The <b>like-for-like labour "
                    "verdict is the Labour subtotal in Section 1</b> "
                    "(engine %s vs manual %s), which is computed on both sides and reliable.</div>" % (
                        _gbp(lab["engine"]) if lab else "—", _gbp(lab["manual"]) if lab else "—"))
    body.append(_route_table(route))

    body.append("<h2>3 &middot; Part lines matched on code</h2>")
    rc = recon
    body.append("<p class='muted'>%s of the manual's lines matched an engine line on part code "
                "(exact or code-stem). Variance is engine vs manual on the same part.</p>" % (
                    _esc(rc.get("matched_count", 0))))
    body.append(_matched_table(recon))

    us = _unmatched_section(recon)
    if us:
        body.append("<h2>4 &middot; Lines not matched on code</h2>")
        body.append(us)

    _powder = _powder_note(bundle, recon)
    _unpriced = _unpriced_table(bundle)
    if _powder or _unpriced:
        body.append("<h2>5 &middot; Where the engine's total went short</h2>")
        body.append("<p class='muted'>The headline gap has causes, and these are the ones readable "
                    "from this bundle. They are stated here so the difference in Section 1 is not "
                    "left as a number without an explanation.</p>")
        body.append(_powder)
        body.append(_unpriced)

    if flag_n:
        body.append("<h2>6 &middot; Engine self-review</h2>")
        body.append("<div class='callout c-warn'><b>%s part(s) flagged by the engine for manual "
                    "review.</b> The engine surfaces its own weak reads rather than presenting them "
                    "as settled.</div>" % _esc(flag_n))
        body.append(_review_table(bundle))

    body.append(_analysis_html(analysis))

    body.append("<div class='foot'>Generated %s from parity bundle &middot; workbook: %s &middot; "
                "%s section comparisons, %s operations, %s code-matched lines. Engine figures are the "
                "workbook-formula-equivalent (like-for-like with the manual). This is a diagnostic pass; "
                "gaps are named for follow-up.</div>" % (
                    _esc(now), _esc(Path(facts["workbook_path"]).name), len(money), len(route['rows']),
                    _esc(rc.get("matched_count", 0))))

    return ("<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
            "<title>%s &mdash; Parity Diagnostic</title><style>%s</style></head>"
            "<body><div class='wrap'>%s</div></body></html>" % (_esc(job), _CSS, "".join(body)))



def generate_report_files(bundle_path, out_dir=None, analysis_path=None, job_stem=None):
    """Convenience entry for the AI estimating run: build the parity report and write it into
    out_dir (defaults to the bundle's folder). Returns the written HTML path.

    Called both on-demand (CLI main) and automatically at the end of a populate run so the
    report lands in the same directory as the estimating spreadsheet.
    """
    bundle_path = Path(bundle_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    analysis = None
    if analysis_path and Path(analysis_path).exists():
        analysis = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
    html_doc = generate_parity_html(bundle, analysis)
    if job_stem is None:
        _wbp = str(bundle.get("workbook_path", bundle_path.stem)).replace("\\", "/")
        job_stem = _wbp.rsplit("/", 1)[-1]
        for _ext in (".xls", ".xlsx", ".xlsm"):
            if job_stem.lower().endswith(_ext):
                job_stem = job_stem[: -len(_ext)]
        job_stem = job_stem.strip().strip("-").strip() or bundle_path.stem
    out_dir = Path(out_dir) if out_dir else bundle_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (job_stem + "_parity_report.html")
    out_path.write_text(html_doc, encoding="utf-8")
    return str(out_path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a parity diagnostic HTML from a parity bundle.")
    ap.add_argument("--bundle", required=True, help="Path to the parity bundle JSON")
    ap.add_argument("--out", required=True, help="Output HTML path")
    ap.add_argument("--analysis", default=None, help="Optional per-job analysis JSON (narrative)")
    a = ap.parse_args()
    bundle = json.loads(Path(a.bundle).read_text(encoding="utf-8"))
    analysis = json.loads(Path(a.analysis).read_text(encoding="utf-8")) if a.analysis else None
    html_doc = generate_parity_html(bundle, analysis)
    Path(a.out).write_text(html_doc, encoding="utf-8")
    print("Parity report written: %s (%d chars)" % (a.out, len(html_doc)))


if __name__ == "__main__":
    main()
