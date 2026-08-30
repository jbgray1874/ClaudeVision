#!/usr/bin/env python3
r"""
_build_bodycare_quote_v2.py

Client-facing WeAreSDI-branded quotation for Bodycare (job 12439-01-13), now with:
  - the unit image RENDERED from the GA PDF and placed in the header BETWEEN the two logos
  - contact email updated to matt.evans@wearesdi.com
  - both real logos inlined from C:\Logos (as before)

The unit image is produced by rendering the GA PDF's first page to a PNG, auto-cropping the
white margins to content, and embedding it base64 in the header. This is GENERAL — for any job,
point PDF_PATH at that job's GA PDF and it renders that unit. The image is the engineering
drawing (dimensions/title block included), which is what exists; if you later have product
photos, drop one in place of PDF_PATH handling.

Requires one of: PyMuPDF (fitz) OR pdf2image+poppler, plus Pillow for cropping. The script tries
PyMuPDF first, then pdf2image. If neither is installed it prints the pip line and still builds
the doc WITHOUT the image (logos only), so you always get a document.

Install if needed (venv):
    C:\ClaudeVision\.venv\Scripts\python.exe -m pip install PyMuPDF Pillow --break-system-packages

Reads:  C:\Logos\WeAreSDI.svg, C:\Logos\BodyCare_106.svg,
        the GA PDF at PDF_PATH.
Writes: C:\ClaudeVision\output\12439_Bodycare_Quotation.html   (self-contained)

Usage (on the machine with the files):
    C:\ClaudeVision\.venv\Scripts\python.exe _build_bodycare_quote_v2.py
"""
from __future__ import annotations
import os, re, base64, io, html, datetime

SDI_SVG   = r"C:\Logos\WeAreSDI.svg"
BODY_SVG  = r"C:\Logos\BodyCare_106.svg"
PDF_PATH  = r"K:\Estimating\Completed\AI Estimating\Live Enquiry\12439-01-13 Temporary Tiered Unit — Small Cubes (Rev A)\12439-01-13_GA_REVB.pdf"
OUT_DIR   = r"C:\ClaudeVision\output"
OUT_FILE  = os.path.join(OUT_DIR, "12439_Bodycare_Quotation.html")

CONTACT_EMAIL = "matt.evans@wearesdi.com"

# ── CONFIRMED quotation figures — EDIT HERE ────────────────────────────────────────────
# NOTE: unit_price below is the COST from the workbook (Margin 0%). If you want to quote a
# SELL price, set sell_price (and it will be shown instead). Leave sell_price = None to show cost.
QUOTE = {
    "job_no":     "12439-01-13",
    "rev":        "A",
    "title":      "Temporary Tiered Unit — Small Cubes",
    "customer":   "Bodycare",
    "quantity":   2025,
    "unit_cost":  2.90,          # workbook cost (internal)
    "sell_price": None,          # <-- SET THIS to the client sell price, e.g. 4.20; None shows cost
    "currency":   "£",
    "lead_desc":  "Formed clear acrylic cube, diamond-polished, line-bent and packed.",
    "material":   "Clear acrylic (XT)",
    "date":       datetime.date.today().strftime("%d %B %Y"),
    "valid_days": 30,
    "includes": [
        "Precision-cut acrylic from full sheet stock",
        "CNC / laser cutting and drilling as required",
        "Line-bending and forming to drawing",
        "Diamond polishing to all visible edges",
        "Protective film removal and clean assembly",
        "Individual poly-bagging and boxed packing",
    ],
}
_shown = QUOTE["sell_price"] if QUOTE["sell_price"] is not None else QUOTE["unit_cost"]
QUOTE["unit_shown"]  = _shown
QUOTE["order_value"] = round(_shown * QUOTE["quantity"], 2)
QUOTE["is_cost"]     = QUOTE["sell_price"] is None


def _read_svg(path: str, target_height_px: int) -> str:
    if not os.path.exists(path):
        return (f'<span style="display:inline-block;height:{target_height_px}px;color:#b91c1c;'
                f'font:600 12px sans-serif;">[missing: {html.escape(os.path.basename(path))}]</span>')
    svg = open(path, "r", encoding="utf-8").read()
    vb = re.search(r'viewBox\s*=\s*"([\d.\s-]+)"', svg)
    wa = re.search(r'\bwidth\s*=\s*"([\d.]+)"', svg)
    ha = re.search(r'\bheight\s*=\s*"([\d.]+)"', svg)
    aspect = None
    if vb:
        p = vb.group(1).split()
        if len(p) == 4:
            try:
                vw, vh = float(p[2]), float(p[3])
                aspect = vw / vh if vh else None
            except ValueError:
                aspect = None
    if aspect is None and wa and ha:
        try:
            w, h = float(wa.group(1)), float(ha.group(1))
            aspect = w / h if h else None
        except ValueError:
            aspect = None
    aspect = aspect or 1.0
    tw = round(target_height_px * aspect, 1)
    def _root(m):
        t = m.group(0)
        t = re.sub(r'\swidth\s*=\s*"[^"]*"', '', t)
        t = re.sub(r'\sheight\s*=\s*"[^"]*"', '', t)
        return t[:4] + f' width="{tw}" height="{target_height_px}"' + t[4:]
    svg = re.sub(r'<svg\b[^>]*>', _root, svg, count=1)
    return f'<span class="logo-wrap" style="display:inline-flex;align-items:center;">{svg}</span>'


def _render_pdf_image(pdf_path: str, max_w_px: int = 900) -> str | None:
    """Render page 1 of the PDF to a PNG, auto-crop white margins, return a base64 data URI.
    Returns None (and prints why) if it can't."""
    if not os.path.exists(pdf_path):
        print(f"  [image] PDF not found: {pdf_path} — building without the unit image.")
        return None

    png_bytes = None
    # Try PyMuPDF first
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        page = doc.load_page(0)
        # render at ~200 dpi
        zoom = 200 / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        png_bytes = pix.tobytes("png")
        doc.close()
        print("  [image] rendered page 1 via PyMuPDF.")
    except Exception as e:
        print(f"  [image] PyMuPDF unavailable/failed ({e}); trying pdf2image...")
        try:
            from pdf2image import convert_from_path
            imgs = convert_from_path(pdf_path, dpi=200, first_page=1, last_page=1)
            if imgs:
                buf = io.BytesIO()
                imgs[0].save(buf, format="PNG")
                png_bytes = buf.getvalue()
                print("  [image] rendered page 1 via pdf2image.")
        except Exception as e2:
            print(f"  [image] pdf2image also unavailable ({e2}).")
            print("  [image] Install one renderer:")
            print("          ...python.exe -m pip install PyMuPDF Pillow --break-system-packages")
            return None

    if not png_bytes:
        return None

    # Auto-crop white margins + downscale, using Pillow
    try:
        from PIL import Image, ImageChops, ImageOps
        im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        # trim near-white border
        bg = Image.new("RGB", im.size, (255, 255, 255))
        diff = ImageChops.difference(im, bg)
        bbox = diff.getbbox()
        if bbox:
            # pad the crop slightly
            pad = 12
            l, t, r, b = bbox
            l = max(0, l - pad); t = max(0, t - pad)
            r = min(im.width, r + pad); b = min(im.height, b + pad)
            im = im.crop((l, t, r, b))
        # downscale to max width
        if im.width > max_w_px:
            ratio = max_w_px / im.width
            im = im.resize((max_w_px, int(im.height * ratio)), Image.LANCZOS)
        # white background flatten (already RGB) and re-encode
        out = io.BytesIO()
        im.save(out, format="PNG", optimize=True)
        data = out.getvalue()
        print(f"  [image] cropped to {im.width}x{im.height}px.")
    except Exception as e:
        print(f"  [image] Pillow crop failed ({e}); using full render.")
        data = png_bytes

    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build():
    os.makedirs(OUT_DIR, exist_ok=True)
    sdi_logo  = _read_svg(SDI_SVG, 56)
    body_logo = _read_svg(BODY_SVG, 30)
    unit_uri  = _render_pdf_image(PDF_PATH)

    q = QUOTE
    includes_html = "\n".join(f'      <li>{html.escape(x)}</li>' for x in q["includes"])

    unit_img_html = ""
    if unit_uri:
        unit_img_html = f'''
      <div class="unit-view">
        <img src="{unit_uri}" alt="{html.escape(q['title'])} — general arrangement" />
        <div class="unit-cap">General arrangement · {html.escape(q['job_no'])} Rev {html.escape(q['rev'])}</div>
      </div>'''

    price_note = "ex VAT" if not q["is_cost"] else "ex VAT · indicative"

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(q['customer'])} — Quotation {html.escape(q['job_no'])}</title>
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
  .head .mid {{ flex:1; display:flex; justify-content:center; }}
  .head .mid .miniview {{ max-height:70px; }}
  .head .mid img {{ max-height:70px; max-width:220px; object-fit:contain; }}

  /* full unit view under the band */
  .unit-view {{ text-align:center; padding:22px 40px 4px; }}
  .unit-view img {{ max-width:100%; max-height:320px; object-fit:contain;
                    border:1px solid var(--line); border-radius:4px; background:#fff; padding:8px; }}
  .unit-cap {{ font-size:11px; color:var(--muted); margin-top:8px; letter-spacing:.04em; }}

  .band {{ background:var(--sdi-ink); color:#fff; padding:20px 40px; }}
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

  .foot {{ padding:20px 40px 26px; border-top:1px solid var(--line); color:var(--muted);
           font-size:12px; display:flex; justify-content:space-between; gap:20px; flex-wrap:wrap; }}
  .foot .terms b {{ color:var(--ink); }}
  .logo-wrap svg {{ display:block; }}

  @media print {{ body {{ background:#fff; }} .sheet {{ border:none; box-shadow:none; margin:0; max-width:100%; }} }}
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
{unit_img_html}

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
            <tr><td>Unit price ({price_note})</td><td>{q['currency']}{q['unit_shown']:.2f}</td></tr>
            <tr><td>Order quantity</td><td>{q['quantity']:,}</td></tr>
            <tr><td>Quotation date</td><td>{html.escape(q['date'])}</td></tr>
            <tr><td>Valid for</td><td>{q['valid_days']} days</td></tr>
          </table>
        </div>
      </div>

      <div class="price-box">
        <div>
          <div class="u">Unit price</div>
          <div class="unit">{q['currency']}{q['unit_shown']:.2f}</div>
          <div class="per">per unit, {price_note} · {q['quantity']:,} off</div>
        </div>
        <div class="right">
          <div class="u">Order value</div>
          <div class="ov">{q['currency']}{q['order_value']:,.2f}</div>
          <div class="per">{price_note}</div>
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
        {html.escape(CONTACT_EMAIL)} · 0116 274 7040 · wearesdi.com
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
    if q["is_cost"]:
        print(f"  *** SHOWING COST £{q['unit_cost']:.2f} (margin 0%). Set QUOTE['sell_price'] to quote a")
        print(f"      real sell price before sending to the client. ***")
    print(f"  Open in a browser; File > Print > Save as PDF to send.")


if __name__ == "__main__":
    build()
