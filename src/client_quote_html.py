r"""
client_quote_html.py — generate a we.are.sdi client quotation HTML from a job's summary JSON.

GENERAL / job-agnostic. Reproduces the SDI house-style quote layout (yellow + ink), populated
entirely from the engine's summary JSON. Client-facing only: price, quantity, material, finish,
plain-language operations, GA image. NO cost breakdown, parity, flags, per-part costs, or route
codes ever appear.

Field sources (all confirmed against real 1282 JSON):
  job number   <- job_output_stem, split on first '-'
  product      <- job_output_stem, leading number stripped   (JG: folder name for now)
  rev          <- GA PDF /Title  '..._revC'  -> 'Rev C'
  quantity     <- estimate_summary.estimate_workbook_inputs.assumed_job_quantity
  date         <- today (quote generation date)
  customer     <- derived from folder/GA path  -> logo key -> assets/customer_logos/<key>.svg|.png
  UNIT PRICE   <- estimate_summary.workbook_equivalent_pricing.m105  (the REAL Excel-computed cost)
  order value  <- unit price x quantity
  material     <- distinct normalized_material across part_estimates
  finish       <- costed_facts.costed_finish_label  (named from what was CHARGED)
  what's incl. <- costed_facts.costed_operations -> plain EN  (never the drawing's routing text)
  GA image     <- primary_pdf.path -> render page 1 to PNG (PyMuPDF) -> base64 embed

Standalone:
    python client_quote_html.py --json <summary.json> --out <quote>.html
Convenience API (for the --deliverables hook):
    generate_quote_files(json_path, out_dir=None, job_stem=None) -> written html path

Price note: shows the engine's computed UNIT COST as 'indicative' ex-VAT (JG's decision). A markup
hook (MARKUP_FACTOR) is provided but defaults to 1.0 (cost shown as-is). Change later for sell price.
"""
from __future__ import annotations
import argparse, base64, html, json, os, re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── config ──────────────────────────────────────────────────────────────────
ASSETS_LOGOS = r"C:\ClaudeVision\assets\customer_logos"
SDI_LOGO_KEY = "wearesdi"          # SDI's own logo file (left header), in the same folder
MARKUP_FACTOR = 1.0                # 1.0 = show computed cost as-is (JG). >1.0 later for sell price.
VALID_DAYS = 30

# Plain-language descriptions for the engine's canonical operations. General: any op the engine
# emits maps to a client-friendly line; unknown ops fall back to a title-cased version.
OP_PLAIN_LANGUAGE = {
    "laser_cutting":       "Laser cutting and profiling from sheet",
    "punch":               "CNC punching of holes and features",
    "punching":            "CNC punching of holes and features",
    "folding":             "Precision folding and forming to drawing",
    "bending":             "Precision bending and forming to drawing",
    "tube_bending":        "Tube bending and forming",
    "rolling":             "Rolling and forming",
    "welding":             "Welding and fabrication",
    "spot_welding":        "Spot welding and assembly",
    "dressing":            "Weld dressing and finishing",
    "powder_coating":      "Powder-coated finish to specified colour",
    "wet_spray":           "Wet-spray painted finish",
    "cnc_machining":       "CNC machining to drawing",
    "diamond_polishing":   "Diamond polishing to visible edges",
    "diamond_polish":      "Diamond polishing to visible edges",
    "line_bending":        "Line bending and forming (acrylic)",
    "linebend":            "Line bending and forming (acrylic)",
    "gluing":              "Bonding and assembly",
    "glueing":             "Bonding and assembly",
    "bonding":             "Bonding and assembly",
    "drilling":            "Drilling to drawing",
    "handling":            "Handling, inspection and clean assembly",
    "assembly":            "Assembly to drawing",
    "packing":             "Protective packing for transport",
    "manual_packing":      "Protective packing for transport",
    "machine_packing":     "Protective packing for transport",
    "pin_router":          "Pin-router profiling (acrylic)",
    "saw":                 "Sawing to length",
    "tube_cut":            "Tube cutting to length",
    "manual_labour_acrylic":"Hand finishing (acrylic)",
    # Operation keys the engine actually emits. Without these the quote printed raw
    # internal names ("Cnc routing", "Dress welds", "Glue") to the customer.
    "cnc_routing":         "CNC routing and joinery machining",
    "cnc":                 "CNC machining to drawing",
    "cnc_joinery":         "CNC routing and joinery machining",
    "glue":                "Bonding and assembly",
    "dress_welds":         "Weld dressing and finishing",
    "deburring":           "Deburring and edge finishing",
    "deburr":              "Deburring and edge finishing",
    "linishing":           "Linishing and edge finishing",
    "guillotine":          "Guillotine cutting from sheet",
    "edge_banding":        "Edge banding to exposed edges",
    "bench_work":          "Bench fitting and assembly",
    "spotweld":            "Spot welding and assembly",
    "tubebend":            "Tube bending and forming",
    "roll":                "Rolling and forming",
    "wire_forming":        "Wire forming",
    "robomac":             "Wire forming",
    "lacquer":             "Lacquered finish",
    "lacquering":          "Lacquered finish",
}
# operations we don't surface to clients as their own bullet (too internal / logistics-only)
_OPS_HIDE = {"handling"}


# ── helpers ─────────────────────────────────────────────────────────────────
def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def _money(v: Optional[float]) -> str:
    try:
        return "£{:,.2f}".format(float(v))
    except (TypeError, ValueError):
        return "—"


def _num(v: Optional[float]) -> str:
    try:
        f = float(v)
        return "{:,.0f}".format(f) if abs(f - round(f)) < 1e-9 else "{:,.2f}".format(f)
    except (TypeError, ValueError):
        return "—"


def _get(d: Any, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _normalise_key(name: str) -> str:
    # '&' -> 'and' so a customer typed "M&S" (key 'mands') matches the saved logo file
    # "MAndS.png" (also 'mands'). Without this, "M&S" normalises to 'ms' and never matches.
    s = (name or "").lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", s)


def _title_material(m: str) -> str:
    return (m or "").replace("_", " ").title()


# ── customer + logo ─────────────────────────────────────────────────────────
def _derive_customer(summary: Dict[str, Any], job_stem: str, manual_workbook: Optional[str] = None,
                     customer_override: Optional[str] = None) -> str:
    """Best-effort customer name for display + logo key. Uses folder/GA-path tokens.
    General fallback chain; when a real customer field exists in future JSONs it can be added here.

    An explicit customer (from --customer) is AUTHORITATIVE and short-circuits everything — no
    guessing. Next, a pinned manual estimate workbook (--parity-workbook) whose
    ...\\Manual Estimates\\<year>\\<CUSTOMER>\\... path names the customer takes precedence over
    the heuristics below."""
    # (-1) Explicit --customer wins outright.
    if customer_override and str(customer_override).strip():
        return str(customer_override).strip()
    # (0) Explicit pinned workbook path wins — no guessing, no share glob.
    if manual_workbook:
        _cust_pinned = _customer_from_workbook_path(str(manual_workbook))
        if _cust_pinned:
            return _cust_pinned
    # look in folder path + GA title for a known-ish brand token
    hay = " ".join([
        str(summary.get("job_folder") or ""),
        str(job_stem or ""),
        str(_get(summary, "pdf_metadata", "/Title", default="")),
        str(_get(summary, "drawing_metadata", "pdf_metadata", "/Title", default="")),
    ])
    # if any logo file stem appears in the haystack, that's our customer
    try:
        for fn in os.listdir(ASSETS_LOGOS):
            stem = os.path.splitext(fn)[0]
            if stem.lower() == SDI_LOGO_KEY:
                continue
            if _normalise_key(stem) and _normalise_key(stem) in _normalise_key(hay):
                return stem
    except OSError:
        pass
    # else: product words after the job number (e.g. '1282 - Milwaukee Wall Bay' -> 'Milwaukee')
    # (1) Manual-estimate folder carries the real customer:
    #     ...\Manual Estimates\<year>\<CUSTOMER>\<jobfolder>\...
    #     Prefer it over any folder-name guess (fixes the '01-GA-' drawing-fragment bug).
    _cust_from_manual = _customer_from_manual_path(summary)
    if _cust_from_manual:
        return _cust_from_manual

    # (2) Word-grab fallback, but REJECT drawing-number fragments (e.g. '01-GA-', '02-XX')
    #     and pure codes — those are never a customer name.
    prod = re.sub(r"^\d+\s*-\s*", "", job_stem or "").strip()
    first = prod.split()[0] if prod else ""
    _looks_like_code = bool(re.match(r"^\d+[-]?[A-Za-z]{0,3}[-]?$", first)) or bool(re.match(r"^\d", first))
    if first and not _looks_like_code:
        return first
    # (3) Neutral — never emit a drawing-number fragment as the customer.
    return "Customer"


def _customer_from_workbook_path(mp: str) -> str:
    """Extract <CUSTOMER> from a manual-estimate path
    ...\Manual Estimates\<year>\<CUSTOMER>\<jobfolder>\*.xls — else ''.
    Pure path parsing; works for a UNC share or a mapped drive (e.g. K:\\...)."""
    if not mp:
        return ""
    try:
        norm = str(mp).replace("/", "\\")
        parts = norm.split("\\")
        for i, seg in enumerate(parts):
            if seg.strip().lower() == "manual estimates" and i + 2 < len(parts):
                # parts[i+1] = year, parts[i+2] = customer
                cust = parts[i + 2].strip()
                if cust and not cust.isdigit():
                    return cust
    except Exception:
        return ""
    return ""


def _customer_from_manual_path(summary: Dict[str, Any]) -> str:
    """If a manual estimate exists for this job, its path is
    ...\Manual Estimates\<year>\<CUSTOMER>\<jobfolder>\*.xls — return <CUSTOMER>.
    Uses the deployed _find_manual_workbook when available; else returns ''."""
    try:
        import file_scan as _FS
        mp = _FS._find_manual_workbook(summary) if hasattr(_FS, "_find_manual_workbook") else None
    except Exception:
        mp = None
    return _customer_from_workbook_path(str(mp)) if mp else ""


def _size_svg(svg_markup: str, *, height_px: int, width_px: Optional[int] = None) -> str:
    """Force an inline SVG to a fixed display size. A CSS max-height does NOT constrain an SVG that
    declares its own width/height, so we rewrite the opening <svg> tag: drop existing width/height
    and inject fixed ones (viewBox is preserved so it scales correctly)."""
    m = re.search(r"<svg\b[^>]*>", svg_markup, re.I | re.S)
    if not m:
        return svg_markup
    tag = m.group(0)
    # strip any existing width/height attributes
    tag2 = re.sub(r'\s(width|height)="[^"]*"', "", tag, flags=re.I)
    # build the size attrs: always height; width only if given (else auto via viewBox)
    size_attr = f' height="{height_px}"'
    if width_px is not None:
        size_attr = f' width="{width_px}"' + size_attr
    tag2 = tag2[:-1] + size_attr + ' style="height:%dpx;width:auto;display:block;" >' % height_px
    return svg_markup.replace(tag, tag2, 1)


def _load_logo_markup(customer: str) -> str:
    """Return inline SVG (bare) or <img> base64 for the customer logo, else empty (text fallback)."""
    key = _normalise_key(customer)
    if not key or not os.path.isdir(ASSETS_LOGOS):
        return ""
    # match a file whose normalised stem == key
    try:
        for fn in os.listdir(ASSETS_LOGOS):
            stem, ext = os.path.splitext(fn)
            if _normalise_key(stem) != key:
                continue
            p = os.path.join(ASSETS_LOGOS, fn)
            if ext.lower() == ".svg":
                svg = open(p, encoding="utf-8", errors="replace").read()
                m = re.search(r"<svg\b.*?</svg>", svg, re.S | re.I)
                inner = _size_svg(m.group(0) if m else svg, height_px=72)
                return f'<span style="display:inline-flex;align-items:center;">{inner}</span>'
            if ext.lower() in (".png", ".jpg", ".jpeg", ".gif"):
                data = base64.b64encode(open(p, "rb").read()).decode("ascii")
                mime = "image/png" if ext.lower() == ".png" else ("image/jpeg" if ext.lower() in (".jpg", ".jpeg") else "image/gif")
                return f'<img src="data:{mime};base64,{data}" alt="{_esc(customer)}" style="max-height:72px;max-width:300px;object-fit:contain;">'
    except OSError:
        pass
    return ""


def _sdi_logo_markup() -> str:
    """SDI's own yellow-circle logo (left header). Read from the assets folder; fall back to a
    plain yellow circle if the file is missing so a quote still renders."""
    try:
        for fn in os.listdir(ASSETS_LOGOS):
            stem, ext = os.path.splitext(fn)
            if _normalise_key(stem) == SDI_LOGO_KEY and ext.lower() == ".svg":
                svg = open(os.path.join(ASSETS_LOGOS, fn), encoding="utf-8", errors="replace").read()
                m = re.search(r"<svg\b.*?</svg>", svg, re.S | re.I)
                inner = _size_svg(m.group(0) if m else svg, height_px=52)
                return f'<span style="display:inline-flex;align-items:center;">{inner}</span>'
    except OSError:
        pass
    return ('<span style="display:inline-flex;"><svg width="56" height="56" viewBox="0 0 100 100">'
            '<circle cx="50" cy="50" r="50" fill="#F5D947"/></svg></span>')


# ── GA image ────────────────────────────────────────────────────────────────
def _ga_image_data_uri(summary: Dict[str, Any]) -> Optional[str]:
    """Render page 1 of the primary GA PDF to a PNG data URI via PyMuPDF. None if unavailable."""
    pdf_path = _get(summary, "primary_pdf", "path")
    if not pdf_path or not os.path.exists(pdf_path):
        return None
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        if doc.page_count == 0:
            return None
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6))  # modest DPI; keeps file reasonable
        png = pix.tobytes("png")
        doc.close()
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    except Exception as exc:
        print(f"   [quote] GA image render skipped ({type(exc).__name__}: {exc}).", flush=True)
        return None


# ── content assembly ────────────────────────────────────────────────────────
def _collect_operations(parts: List[Dict[str, Any]],
                        summary: Optional[Dict[str, Any]] = None) -> List[str]:
    """Distinct operations across all parts, in a stable order, mapped to plain language.

    Driven by the operations we actually COSTED (labour cost lines / process times), not by
    the drawing's interpreted `routing` text. That text is transcribed from drawing notes,
    which on many packs carry a shared specification legend covering the customer's whole
    product range ("CHROME PLATING ... POLISHING SPECIFICATION ... POWDER COATED STEEL").
    Reading it put processes on the client quote that the job does not have and we never
    charged for — e.g. powder coat and diamond polish promised on a lacquered pine crate.

    A quote must describe what we priced. If an operation carries no cost on this job, it
    does not appear. Same de-pollution principle applied to materials and routes upstream.
    """
    seen: List[str] = []

    def _add(op: Any) -> None:
        if isinstance(op, str) and op and op not in seen:
            seen.append(op)

    # Costed labour lines and process times — the authoritative "what we charged for",
    # from the one shared post-costing source so the quote, the internal report and the
    # Decision Report cannot each derive a different answer.
    from costed_facts import costed_operations
    # Pass the SUMMARY: workbook_labour (the canonical accepted route) hangs off it, not
    # off the parts list. Handing over parts alone silently drops to the pre-filter
    # engine fields, which is what put powder and weld dressing on a timber crate.
    for op in costed_operations(summary if isinstance(summary, dict) else parts):
        _add(op)

    # 3. Fallback ONLY if the estimate carries no costed operations at all (e.g. a parts-free
    #    summary). Interpreted routing is better than an empty list, but never overrides real
    #    costed operations above.
    if not seen:
        for p in parts:
            routing = _get(p, "process_estimate", "routing", default=[]) or []
            if isinstance(routing, list):
                for item in routing:
                    _add(item.get("operation") if isinstance(item, dict) else item)

    lines = []
    for op in seen:
        if op in _OPS_HIDE:
            continue
        lines.append(OP_PLAIN_LANGUAGE.get(op, op.replace("_", " ").capitalize()))
    # de-dupe plain-language collisions while preserving order
    out, s = [], set()
    for l in lines:
        if l not in s:
            out.append(l); s.add(l)
    # Closing lines. Protective film is carried by acrylic and bright/coated steel sheet — it
    # is not present on bare timber/board, so only claim its removal when such a material is
    # actually in the job. Clean assembly and packing apply to everything.
    _mats = " ".join(str(p.get("normalized_material") or "") for p in parts).upper()
    _has_film = any(k in _mats for k in ("ACRYLIC", "PERSPEX", "POLYCARB", "STEEL", "ALUMIN", "ZINTEC"))
    tails = ["Clean assembly and inspection", "Individual packing for transport"]
    if _has_film:
        tails.insert(0, "Protective film removal")
    for tail in tails:
        if tail not in s:
            out.append(tail); s.add(tail)
    return out


def _materials_line(parts: List[Dict[str, Any]]) -> str:
    mats = []
    for p in parts:
        m = p.get("normalized_material")
        if m and m not in mats:
            mats.append(m)
    return ", ".join(_title_material(m) for m in mats) if mats else "As drawing"


def _finish_line(summary: Dict[str, Any], parts: List[Dict[str, Any]]) -> str:
    """Headline finish for the quote — from the finish we COSTED, not the drawing's
    interpreted routing text (which carries the customer's range-wide specification
    legend and would claim 'Powder coated' on a lacquered timber product)."""
    # ONE shared post-costing source (costed_facts), so the quote, the internal report and
    # the Decision Report cannot describe three different jobs. Note this no longer ORs in
    # powder_coating_summary: a powder MATERIAL line can survive after the powder LABOUR has
    # been gated off a part, and that combination promised "Powder coated" to the customer
    # on a lacquered timber crate whose priced sheet contains no powder at all.
    from costed_facts import costed_finish_label
    return costed_finish_label(summary if isinstance(summary, dict) else parts)


# ── main render ─────────────────────────────────────────────────────────────
def _invariant_banner(summary: Dict[str, Any]) -> str:
    """A visible, unmissable statement when the engine's own checks say this is not a firm
    price — and an equally explicit one when they could not run at all.

    The three states are deliberately distinct. "Checks failed" and "checks did not run" are
    different facts, and the second is the more dangerous of the two because it looks like
    silence rather than a problem: a read-back failure leaves every reconciliation check with
    nothing to examine, finds nothing wrong, and produces a clean-looking job.
    """
    inv = summary.get("invariants")
    if not isinstance(inv, dict):
        return ('    <div class="prov">PROVISIONAL — the consistency checks did not run on '
                'this estimate, so none of its figures have been verified against the '
                'workbook. Not for release as a firm price.</div>')
    if inv.get("may_quote_firm"):
        return ""
    _blocking = [v for v in (inv.get("violations") or [])
                 if isinstance(v, dict) and v.get("severity") == "blocking"]
    _unver = [v for v in (inv.get("violations") or [])
              if isinstance(v, dict) and v.get("severity") == "unverified"]
    _bits = []
    if _blocking:
        _bits.append(f"{len(_blocking)} consistency check(s) FAILED")
    if _unver:
        _bits.append(f"{len(_unver)} check(s) could not be run, so those figures are "
                     f"unverified")
    _detail = "; ".join(_esc(str(v.get("message") or "")) for v in (_blocking + _unver)[:3])
    return ('    <div class="prov">PROVISIONAL — ' + _esc(" and ".join(_bits)) +
            '. This estimate is not for release as a firm price until they are resolved.'
            + (f'<span class="prov-d">{_detail}</span>' if _detail else "") + '</div>')


def build_quote_html(summary: Dict[str, Any], job_stem: Optional[str] = None,
                     manual_workbook: Optional[str] = None, customer: Optional[str] = None) -> str:
    stem = job_stem or summary.get("job_output_stem") or summary.get("job_folder", "").split("\\")[-1] or "Job"
    stem = str(stem)

    job_number = stem.split("-")[0].strip() if "-" in stem else stem
    product = re.sub(r"^\d+\s*-\s*", "", stem).strip() or stem

    title = str(_get(summary, "pdf_metadata", "/Title", default="")
                or _get(summary, "drawing_metadata", "pdf_metadata", "/Title", default=""))
    m = re.search(r"_rev([A-Za-z0-9]+)", title)
    rev = ("Rev " + m.group(1).upper()) if m else ""

    es = summary.get("estimate_summary", {}) or {}
    qty = _get(es, "estimate_workbook_inputs", "assumed_job_quantity") or 0
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        qty = 0

    unit_cost = _get(es, "workbook_equivalent_pricing", "m105_total_unit_cost_gbp")
    unit_price = (unit_cost * MARKUP_FACTOR) if isinstance(unit_cost, (int, float)) else None
    order_value = (unit_price * qty) if (unit_price is not None and qty) else None

    parts = es.get("part_estimates") or []
    material = _materials_line(parts)
    finish = _finish_line(summary, parts)
    ops = _collect_operations(parts, summary)

    # THE INVARIANT GATE, READ BY THE DOCUMENT THAT LEAVES THE BUILDING.
    # The checks ran and wrote their verdict onto the job, and the quote was generated
    # regardless — a gate nothing consumes is a log line, not a gate. Suppressing the quote
    # is not the answer either (an estimator still needs the working); the answer is that a
    # price we cannot stand behind must not LOOK like one we can.
    _inv_banner = _invariant_banner(summary)

    customer = _derive_customer(summary, stem, manual_workbook=manual_workbook, customer_override=customer)
    logo_markup = _load_logo_markup(customer)
    cust_header = logo_markup if logo_markup else f'<div style="font-size:18px;font-weight:600;color:#282928;">{_esc(customer)}</div>'
    sdi_logo = _sdi_logo_markup()

    ga_uri = _ga_image_data_uri(summary)
    today = date.today().strftime("%d %B %Y")

    # operations -> two-column bullet list
    inc_items = "\n".join(f"      <li>{_esc(o)}</li>" for o in ops)

    ga_block = ""
    if ga_uri:
        ga_block = f"""
      <div class="unit-view">
        <h3 class="ref-h">Drawing reference</h3>
        <img src="{ga_uri}" alt="{_esc(product)} — general arrangement" />
        <div class="unit-cap">General arrangement · {_esc(job_number)}{(' ' + _esc(rev)) if rev else ''}</div>
      </div>"""

    meta_bits = f"Job <b>{_esc(job_number)}</b>"
    if rev:
        meta_bits += f" &nbsp;·&nbsp; {_esc(rev)}"
    if qty:
        meta_bits += f" &nbsp;·&nbsp; {_num(qty)} units"
    meta_bits += f" &nbsp;·&nbsp; {_esc(today)}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(product)} — Quotation {_esc(job_number)}</title>
<style>
  :root {{ --sdi-yellow:#F5D947; --sdi-ink:#282928; --ink:#1f2321; --muted:#6b6f6c;
           --line:#e6e7e4; --bg:#ffffff; --soft:#fbfbf8; }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; padding:0; }}
  body {{ font-family:'Segoe UI','Helvetica Neue',Arial,sans-serif; color:var(--ink);
          background:var(--soft); line-height:1.55; font-size:14px;
          -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  .sheet {{ max-width:820px; margin:24px auto; background:var(--bg); border:1px solid var(--line);
            border-radius:4px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.04); }}
  .head {{ display:flex; align-items:center; justify-content:space-between; gap:16px;
           padding:26px 40px 22px; border-bottom:4px solid var(--sdi-yellow); }}
  .head .cust {{ text-align:right; }}
  .head .cust .lbl {{ font-size:10px; letter-spacing:.14em; text-transform:uppercase;
                      color:var(--muted); margin-bottom:6px; }}
  .band {{ background:var(--sdi-ink); color:#fff; padding:20px 40px; }}
  /* Not decorative. This is the difference between a price the shop can commit to and one
     the engine could not verify, and it has to survive being printed in black and white. */
  .prov {{ background:#fff3cd; border-top:3px solid #b8860b; border-bottom:1px solid #e0cfa0;
           color:#5c4400; padding:14px 40px; font-size:12.5px; font-weight:700;
           letter-spacing:.01em; }}
  .prov-d {{ display:block; margin-top:6px; font-weight:400; font-size:11px; color:#6b5520; }}
  .band h1 {{ margin:0; font-size:22px; font-weight:600; }}
  .band .meta {{ margin-top:6px; font-size:13px; color:#d8d9d6; }}
  .band .meta b {{ color:var(--sdi-yellow); font-weight:600; }}
  .body {{ padding:28px 40px; }}
  .lead {{ font-size:15px; margin:0 0 22px; }}
  .grid {{ display:flex; gap:24px; flex-wrap:wrap; margin-bottom:26px; }}
  .spec {{ flex:1; min-width:240px; }}
  .spec h3 {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin:0 0 10px; }}
  .spec table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  .spec td {{ padding:5px 0; border-bottom:1px solid var(--line); }}
  .spec td:last-child {{ text-align:right; font-weight:600; }}
  .price-box {{ background:var(--sdi-ink); color:#fff; border-radius:6px; padding:22px 26px;
                display:flex; align-items:center; justify-content:space-between; margin-bottom:26px; }}
  .price-box .u {{ font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:#c9cac7; }}
  .price-box .unit {{ font-size:34px; font-weight:700; color:var(--sdi-yellow); line-height:1; }}
  .price-box .per {{ font-size:13px; color:#c9cac7; margin-top:4px; }}
  .price-box .right {{ text-align:right; }}
  .price-box .right .ov {{ font-size:20px; font-weight:600; }}
  .inc h3 {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin:0 0 10px; }}
  .inc ul {{ margin:0; padding:0; list-style:none; columns:2; column-gap:32px; }}
  .inc li {{ padding:6px 0 6px 22px; position:relative; font-size:13.5px; break-inside:avoid; }}
  .inc li::before {{ content:""; position:absolute; left:0; top:12px; width:10px; height:10px;
                     background:var(--sdi-yellow); border-radius:2px; }}
  .unit-view {{ text-align:center; padding:6px 40px 26px; border-top:1px solid var(--line); }}
  .unit-view .ref-h {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase;
                       color:var(--muted); margin:22px 0 12px; text-align:left; }}
  .unit-view img {{ max-width:100%; max-height:340px; object-fit:contain;
                    border:1px solid var(--line); border-radius:4px; background:#fff; padding:8px; }}
  .unit-cap {{ font-size:11px; color:var(--muted); margin-top:8px; letter-spacing:.04em; }}
  .foot {{ padding:20px 40px 26px; border-top:1px solid var(--line); color:var(--muted);
           font-size:12px; display:flex; justify-content:space-between; gap:20px; flex-wrap:wrap; }}
  .foot .terms b {{ color:var(--ink); }}
  @media print {{ body {{ background:#fff; }} .sheet {{ border:none; box-shadow:none; margin:0; max-width:100%; }} }}
</style>
</head>
<body>
  <div class="sheet">
    <div class="head">
      <div class="sdi">{sdi_logo}</div>
      <div class="cust">
        <div class="lbl">Prepared for</div>
        {cust_header}
      </div>
    </div>
    <div class="band">
      <h1>Quotation — {_esc(product)}</h1>
      <div class="meta">{meta_bits}</div>
    </div>
{_inv_banner}
    <div class="body">
      <p class="lead">{_esc(product)} — manufactured to drawing. {_esc(material)}{(', ' + _esc(finish.lower())) if finish and finish!='As drawing' else ''}.</p>
      <div class="grid">
        <div class="spec">
          <h3>Specification</h3>
          <table>
            <tr><td>Material</td><td>{_esc(material)}</td></tr>
            <tr><td>Quantity</td><td>{_num(qty) if qty else '—'}</td></tr>
            <tr><td>Finish</td><td>{_esc(finish)}</td></tr>
            <tr><td>Packing</td><td>Boxed for transport</td></tr>
          </table>
        </div>
        <div class="spec">
          <h3>Commercial</h3>
          <table>
            <tr><td>Unit price (ex VAT · indicative)</td><td>{_money(unit_price)}</td></tr>
            <tr><td>Order quantity</td><td>{_num(qty) if qty else '—'}</td></tr>
            <tr><td>Quotation date</td><td>{_esc(today)}</td></tr>
            <tr><td>Valid for</td><td>{VALID_DAYS} days</td></tr>
          </table>
        </div>
      </div>
      <div class="price-box">
        <div>
          <div class="u">Unit price</div>
          <div class="unit">{_money(unit_price)}</div>
          <div class="per">per unit, ex VAT · indicative{(' · ' + _num(qty) + ' off') if qty else ''}</div>
        </div>
        <div class="right">
          <div class="u">Order value</div>
          <div class="ov">{_money(order_value)}</div>
          <div class="per">ex VAT · indicative</div>
        </div>
      </div>
      <div class="inc">
        <h3>What's included</h3>
        <ul>
{inc_items}
        </ul>
      </div>
    </div>{ga_block}
    <div class="foot">
      <div class="terms">
        <b>we.are.sdi</b> · Design-led manufacturer · Loughborough, UK<br>
        matt.evans@wearesdi.com · 0116 274 7040 · wearesdi.com
      </div>
      <div class="terms" style="text-align:right;">
        Prices ex VAT, GBP. Valid {VALID_DAYS} days from quotation date.<br>
        wearesdi is the trading name of SDI Displays Ltd.
      </div>
    </div>
  </div>
</body>
</html>"""


def generate_quote_files(json_path: str, out_dir: Optional[str] = None, job_stem: Optional[str] = None,
                         manual_workbook: Optional[str] = None, customer: Optional[str] = None) -> Optional[str]:
    jp = Path(json_path)
    summary = json.loads(jp.read_text(encoding="utf-8"))
    stem = job_stem or summary.get("job_output_stem") or jp.stem
    html_str = build_quote_html(summary, job_stem=stem, manual_workbook=manual_workbook, customer=customer)
    out_dir_p = Path(out_dir) if out_dir else jp.parent
    out_dir_p.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\- ]", "", str(stem)).strip() or "quote"
    out_path = out_dir_p / f"{safe}_quote.html"
    out_path.write_text(html_str, encoding="utf-8")
    return str(out_path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a we.are.sdi client quotation HTML from a summary JSON.")
    ap.add_argument("--json", required=True, help="Summary JSON path")
    ap.add_argument("--out", help="Output HTML path (default: <job>_quote.html next to the JSON)")
    a = ap.parse_args()
    summary = json.loads(Path(a.json).read_text(encoding="utf-8"))
    stem = summary.get("job_output_stem") or Path(a.json).stem
    html_str = build_quote_html(summary, job_stem=stem)
    out = a.out or str(Path(a.json).parent / (re.sub(r"[^\w\- ]", "", str(stem)).strip() + "_quote.html"))
    Path(out).write_text(html_str, encoding="utf-8")
    print(f"Wrote quote: {out}")


if __name__ == "__main__":
    main()
