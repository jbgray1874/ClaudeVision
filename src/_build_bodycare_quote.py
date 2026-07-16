#!/usr/bin/env python3
r"""
_build_bodycare_quote.py

Builds a client-facing, WeAreSDI-branded quotation document for Bodycare (job 12439-01-13,
Temporary Tiered Unit — Small Cubes), with BOTH real company logos inlined from C:\Logos.

This is a CLIENT document — it deliberately shows NONE of the estimating internals (no £/m2
provenance, no parity-vs-manual, no engine diagnostics, no in-house-vs-buy working). It shows a
clean unit price, what's included, and SDI's capability. The technical parity report is separate.

Reads:  C:\Logos\WeAreSDI.svg  and  C:\Logos\BodyCare_106.svg
Writes: C:\ClaudeVision\output\12439_Bodycare_Quotation.html   (self-contained, logos embedded)

The figures below are the CONFIRMED 12439 numbers — EDIT the QUOTE dict if the run changes.

Usage (from anywhere, on the machine that has C:\Logos):
    C:\ClaudeVision\.venv\Scripts\python.exe _build_bodycare_quote.py
Then open the HTML, or print to PDF for sending.
"""
from __future__ import annotations
import os, re, datetime, html

SDI_SVG   = r"C:\Logos\WeAreSDI.svg"
BODY_SVG  = r"C:\Logos\BodyCare_106.svg"
OUT_DIR   = r"C:\ClaudeVision\output"
OUT_FILE  = os.path.join(OUT_DIR, "12439_Bodycare_Quotation.html")

# ── CONFIRMED quotation figures — EDIT HERE if the run changes ──────────────────────────
QUOTE = {
    "job_no":        "12439-01-13",
    "rev":           "A",
    "title":         "Temporary Tiered Unit — Small Cubes",
    "customer":      "Bodycare",
    "quantity":      2025,
    "unit_price":    2.90,          # per-unit ex VAT (the workbook Unit Cost)
    "currency":      "£",
    "lead_desc":     "Formed clear acrylic cube, diamond-polished, line-bent and packed.",
    "material":      "Clear acrylic (XT)",
    "date":          datetime.date.today().strftime("%d %B %Y"),
    "valid_days":    30,
    # what's included — client-facing, plain language (NOT the internal op/material breakdown)
    "includes": [
        "Precision-cut acrylic from full sheet stock",
        "CNC / laser cutting and drilling as required",
        "Line-bending and forming to drawing",
        "Diamond polishing to all visible edges",
        "Protective film removal and clean assembly",
        "Individual poly-bagging and boxed packing",
    ],
}
# extended order value
QUOTE["order_value"] = round(QUOTE["unit_price"] * QUOTE["quantity"], 2)


def _read_svg(path: str, target_height_px: int) -> str:
    """Read an SVG file and normalise it to a target pixel height, preserving aspect via viewBox.
    Returns an inline <svg> string wrapped in a scoped span so IDs/styles don't bleed."""
    if not os.path.exists(path):
        return (f'<span style="display:inline-block;height:{target_height_px}px;'
                f'line-height:{target_height_px}px;color:#b91c1c;font:600 12px sans-serif;">'
                f'[missing logo: {html.escape(os.path.basename(path))}]</span>')
    svg = open(path, "r", encoding="utf-8").read()

    # find viewBox to preserve aspect ratio
    vb = re.search(r'viewBox\s*=\s*"([\d.\s-]+)"', svg)
    width_attr = re.search(r'\bwidth\s*=\s*"([\d.]+)"', svg)
    height_attr = re.search(r'\bheight\s*=\s*"([\d.]+)"', svg)

    aspect = None
    if vb:
        parts = vb.group(1).split()
        if len(parts) == 4:
            try:
                vw, vh = float(parts[2]), float(parts[3])
                if vh > 0:
                    aspect = vw / vh
            except ValueError:
                aspect = None
    if aspect is None and width_attr and height_attr:
        try:
            w, h = float(width_attr.group(1)), float(height_attr.group(1))
            if h > 0:
                aspect = w / h
        except ValueError:
            aspect = None
    if aspect is None:
        aspect = 1.0

    target_width = round(target_height_px * aspect, 1)

    # strip any hard-coded width/height on the root <svg ...> and set our own
    def _fix_root(m):
        tag = m.group(0)
        tag = re.sub(r'\swidth\s*=\s*"[^"]*"', '', tag)
        tag = re.sub(r'\sheight\s*=\s*"[^"]*"', '', tag)
        # insert our sizing right after '<svg'
        return tag[:4] + f' width="{target_width}" height="{target_height_px}"' + tag[4:]

    svg = re.sub(r'<svg\b[^>]*>', _fix_root, svg, count=1)
    # scope wrapper prevents cross-logo id/class collisions
    return f'<span class="logo-wrap" style="display:inline-flex;align-items:center;">{svg}</span>'


def build():
    os.makedirs(OUT_DIR, exist_ok=True)
    sdi_logo  = _read_svg(SDI_SVG, 56)    # roundel — a touch larger
    body_logo = _read_svg(BODY_SVG, 30)   # wordmark — sits at cap height

    q = QUOTE
    includes_html = "\n".join(
        f'      <li>{html.escape(x)}</li>' for x in q["includes"]
    )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(q['customer'])} — Quotation {html.escape(q['job_no'])}</title>
<style>
  :root {{
    --sdi-yellow:#F5D947; --sdi-ink:#282928; --ink:#1f2321; --muted:#6b6f6c;
    --line:#e6e7e4; --bg:#ffffff; --soft:#fbfbf8; --accent:#282928;
  }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; padding:0; }}
  body {{ font-family:'Segoe UI','Helvetica Neue',Arial,sans-serif; color:var(--ink);
          background:var(--soft); line-height:1.55; font-size:14px; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  .sheet {{ max-width:820px; margin:24px auto; background:var(--bg); border:1px solid var(--line);
            border-radius:4px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.04); }}

  /* header band with both logos */
  .head {{ display:flex; align-items:center; justify-content:space-between; gap:20px;
           padding:28px 40px; border-bottom:4px solid var(--sdi-yellow); }}
  .head .cust {{ text-align:right; }}
  .head .cust .lbl {{ font-size:10px; letter-spacing:.14em; text-transform:uppercase;
                      color:var(--muted); margin-bottom:6px; }}

  .band {{ background:var(--sdi-ink); color:#fff; padding:22px 40px; }}
  .band h1 {{ margin:0; font-size:22px; font-weight:600; letter-spacing:.01em; }}
  .band .meta {{ margin-top:6px; font-size:13px; color:#d8d9d6; }}
  .band .meta b {{ color:var(--sdi-yellow); font-weight:600; }}

  .body {{ padding:32px 40px; }}
  .lead {{ font-size:15px; color:var(--ink); margin:0 0 24px; }}

  .grid {{ display:flex; gap:24px; flex-wrap:wrap; margin-bottom:28px; }}
  .spec {{ flex:1; min-width:240px; }}
  .spec h3 {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted);
              margin:0 0 10px; }}
  .spec table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  .spec td {{ padding:5px 0; border-bottom:1px solid var(--line); }}
  .spec td:last-child {{ text-align:right; font-weight:600; }}

  .price-box {{ background:var(--sdi-ink); color:#fff; border-radius:6px; padding:22px 26px;
                display:flex; align-items:center; justify-content:space-between; margin-bottom:28px; }}
  .price-box .u {{ font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:#c9cac7; }}
  .price-box .unit {{ font-size:34px; font-weight:700; color:var(--sdi-yellow); line-height:1; }}
  .price-box .per {{ font-size:13px; color:#c9cac7; margin-top:4px; }}
  .price-box .right {{ text-align:right; }}
  .price-box .right .ov {{ font-size:20px; font-weight:600; }}

  .inc h3 {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted);
             margin:0 0 10px; }}
  .inc ul {{ margin:0; padding:0; list-style:none; columns:2; column-gap:32px; }}
  .inc li {{ padding:6px 0 6px 22px; position:relative; font-size:13.5px; break-inside:avoid; }}
  .inc li::before {{ content:""; position:absolute; left:0; top:12px; width:10px; height:10px;
                     background:var(--sdi-yellow); border-radius:2px; }}

  .foot {{ padding:20px 40px 28px; border-top:1px solid var(--line); color:var(--muted);
           font-size:12px; display:flex; justify-content:space-between; gap:20px; flex-wrap:wrap; }}
  .foot .terms b {{ color:var(--ink); }}
  .logo-wrap svg {{ display:block; }}

  @media print {{
    body {{ background:#fff; }}
    .sheet {{ border:none; box-shadow:none; margin:0; max-width:100%; }}
  }}
</style>
</head>
<body>
  <div class="sheet">

    <div class="head">
      <div class="sdi">{sdi_logo}</div>
      <div class="cust">
        <div class="lbl">Prepared for</div>
        {body_logo}
      </div>
    </div>

    <div class="band">
      <h1>Quotation — {html.escape(q['title'])}</h1>
      <div class="meta">
        Job <b>{html.escape(q['job_no'])}</b> &nbsp;·&nbsp; Rev {html.escape(q['rev'])}
        &nbsp;·&nbsp; {q['quantity']:,} units &nbsp;·&nbsp; {html.escape(q['date'])}
      </div>
    </div>

    <div class="body">
      <p class="lead">{html.escape(q['lead_desc'])}</p>

      <div class="grid">
        <div class="spec">
          <h3>Specification</h3>
          <table>
            <tr><td>Material</td><td>{html.escape(q['material'])}</td></tr>
            <tr><td>Quantity</td><td>{q['quantity']:,}</td></tr>
            <tr><td>Finish</td><td>Diamond polished</td></tr>
            <tr><td>Packing</td><td>Poly-bagged, boxed</td></tr>
          </table>
        </div>
        <div class="spec">
          <h3>Commercial</h3>
          <table>
            <tr><td>Unit price (ex VAT)</td><td>{q['currency']}{q['unit_price']:.2f}</td></tr>
            <tr><td>Order quantity</td><td>{q['quantity']:,}</td></tr>
            <tr><td>Quotation date</td><td>{html.escape(q['date'])}</td></tr>
            <tr><td>Valid for</td><td>{q['valid_days']} days</td></tr>
          </table>
        </div>
      </div>

      <div class="price-box">
        <div>
          <div class="u">Unit price</div>
          <div class="unit">{q['currency']}{q['unit_price']:.2f}</div>
          <div class="per">per unit, ex VAT · {q['quantity']:,} off</div>
        </div>
        <div class="right">
          <div class="u">Order value</div>
          <div class="ov">{q['currency']}{q['order_value']:,.2f}</div>
          <div class="per">ex VAT</div>
        </div>
      </div>

      <div class="inc">
        <h3>What's included</h3>
        <ul>
{includes_html}
        </ul>
      </div>
    </div>

    <div class="foot">
      <div class="terms">
        <b>we.are.sdi</b> · Design-led manufacturer · Loughborough, UK<br>
        hello@wearesdi.com · 0116 274 7040 · wearesdi.com
      </div>
      <div class="terms" style="text-align:right;">
        Prices ex VAT, GBP. Valid {q['valid_days']} days from quotation date.<br>
        wearesdi is the trading name of SDI Displays Ltd.
      </div>
    </div>

  </div>
</body>
</html>
"""
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"  written: {OUT_FILE}")
    print("  Open it in a browser; File > Print > Save as PDF for a sendable copy.")
    print("")
    print("  If a logo shows as '[missing logo: ...]', check the path in C:\\Logos.")
    print(f"  Figures used: unit {q['currency']}{q['unit_price']:.2f} × {q['quantity']:,} "
          f"= {q['currency']}{q['order_value']:,.2f}. Edit the QUOTE dict to change.")


if __name__ == "__main__":
    build()
