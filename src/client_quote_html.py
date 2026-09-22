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
    python client_quote_html.py --json <summary.json> [--out-dir <folder>]
Convenience API (for the --deliverables hook):
    generate_quote_files(json_path, out_dir=None, job_stem=None) -> written html path

Price note: shows the engine's computed UNIT COST as 'indicative' ex-VAT (JG's decision). A markup
hook (MARKUP_FACTOR) is provided but defaults to 1.0 (cost shown as-is). Change later for sell price.
"""
from __future__ import annotations
import argparse, base64, html, json, os, re, zlib
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── config ──────────────────────────────────────────────────────────────────
# BESIDE THE REPO, NOT AT A HARDCODED WINDOWS PATH. This was
# r"C:\ClaudeVision\assets\customer_logos" — the same literal that put a directory named
# exactly that into the working tree when the extract cache used one, and which resolves to
# nothing on the 8071 service box unless it happens to have the same drive layout. A logo
# folder that silently is not there produces a quote with a text fallback and no error, which
# is exactly how "the Dyson logo is missing" gets read as a missing FILE when it may be a
# missing FOLDER.
#
# SDI_CUSTOMER_LOGOS relocates it; the Windows install still resolves to the same place.
ASSETS_LOGOS = os.environ.get("SDI_CUSTOMER_LOGOS") or str(
    Path(__file__).resolve().parents[1] / "assets" / "customer_logos")
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
    "fold":                "Precision folding and forming to drawing",
    "glue":                "Bonding and assembly",
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
from quote_state import (CUSTOMER, NotReleasable, PORTAL,  # noqa: E402
                         quote_state, release_meta_tag)
from display_material import describes_the_product  # noqa: E402
from release_record import apply_to_summary  # noqa: E402

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


# A drawing/job code token: 3+ leading digits, optional -NN / /NN groups (7332-01, 12349-02, 7332).
_JOB_CODE_TOKEN = re.compile(r"^\d{3,}(?:[-/]\d+)*$")


def _clean_customer_name(name: str) -> str:
    """Strip a job/drawing-number token a customer name has picked up: 'Harrods 7332-01' ->
    'Harrods'.

    THE JOB NUMBER IN THE NAME IS WHY THE LOGO NEVER MATCHES. _normalise_key keeps digits, so
    'Harrods 7332-01' keys to 'harrods733201' and no saved 'Harrods' logo file can ever match it
    — and the same job-numbered string prints as the heading. 7332-01's quote read 'Harrods
    7332-01' with no mark. The job/drawing reference already appears on its own line, so the
    customer block should carry the customer alone.

    Only tokens that ARE a drawing code are dropped (3+ leading digits with optional -NN groups),
    so a genuine digit-bearing brand — 3M, 7-Eleven — is left exactly as it is."""
    if not name:
        return name
    kept = [tok for tok in str(name).split() if not _JOB_CODE_TOKEN.match(tok)]
    cleaned = " ".join(kept).strip(" -–—")
    return cleaned or str(name).strip()


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
    # THE DRAWING NAMES THE CUSTOMER AND WE WERE NOT READING IT.
    #
    # This looked only at the folder name, the job stem and the PDF's /Title. 11350's folder
    # is "11350-BootsLadderRackCommsBar", so Boots was found by accident of naming; 12422-24's
    # is "12422-24-GA_End Cap_RevB", which names no customer at all — so the same client got
    # a logo on one job and a text fallback on the next.
    #
    # extract_title_block_fields already reads `clients` off the CLIENT: cell, and
    # `project_titles` beside it. The customer is on the drawing, in a labelled field, and
    # the one place that needs it was guessing from a filename.
    def _title_block_tokens() -> str:
        out = []
        for holder in (summary,
                       summary.get("document_analysis") or {},
                       (summary.get("document_analysis") or {}).get("title_block") or {},
                       summary.get("pattern_summary") or {},
                       summary.get("title_block") or {}):
            if not isinstance(holder, dict):
                continue
            for key in ("clients", "client", "customers", "customer", "project_titles"):
                val = holder.get(key)
                if isinstance(val, str):
                    out.append(val)
                elif isinstance(val, (list, tuple)):
                    out.extend(str(v) for v in val)
        return " ".join(out)

    hay = " ".join([
        str(summary.get("job_folder") or ""),
        str(job_stem or ""),
        str(_get(summary, "pdf_metadata", "/Title", default="")),
        str(_get(summary, "drawing_metadata", "pdf_metadata", "/Title", default="")),
        _title_block_tokens(),
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
    # NOR IS A CAD PACKAGE A CUSTOMER. The folder "2085 - SolidWorks" word-grabbed to
    # "SolidWorks" and printed it as the customer's name on their own quotation. Same root
    # cause as the headline: a folder name carries whatever the person who made it typed.
    if first and _STEM_NOISE.fullmatch(first):
        return "Customer"
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


def _svg_is_light(svg_markup: str) -> Optional[bool]:
    """True when an inline SVG's marks are all white or near-white.

    A brand mark drawn in white is drawn for a dark ground. Dyson's is:
    `.st0{fill:#FFFFFF;}` on every path.
    """
    fills = re.findall(r'(?:fill|stroke)\s*[:=]\s*"?\s*(#[0-9a-fA-F]{3,8}|white|none)',
                       svg_markup, re.I)
    seen = [f.lower() for f in fills if f.lower() != "none"]
    if not seen:
        return None
    def _light(c: str) -> bool:
        if c == "white":
            return True
        h = c.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) < 6:
            return False
        try:
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return False
        return (0.299 * r + 0.587 * g + 0.114 * b) > 200
    return all(_light(c) for c in seen)


def _png_visible_luminance(path: str) -> Optional[float]:
    """Mean luminance of a PNG's visible pixels, using only the standard library.

    WHY NOT JUST PILLOW. Pillow is in requirements.txt and is the better tool, but a logo
    rendering invisibly is not the kind of defect that should depend on whether one optional
    package got installed on the box that happens to be running the job. The failure mode when
    it is missing is silent and looks exactly like success — which is the same shape as the bug
    this function exists to catch. So the common case is handled without it.

    Scope is deliberately narrow: 8-bit, non-interlaced, colour types 0/2/3/4/6. That is every
    logo any design agency has ever sent. Anything else returns None and Pillow answers, or
    nothing does and the logo is left exactly as it renders today.

    STOPS EARLY. A brand mark can be 3800x1600, and defiltering six million pixels in Python
    per quote is not free. Scanlines must be defiltered in order — each depends on the one
    above — but once enough visible pixels have been seen the answer will not change.
    """
    try:
        raw = open(path, "rb").read()
    except OSError:
        return None
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, width, height, depth, ctype, interlace = 8, [], 0, 0, 0, 0, 0
    palette, trns = b"", b""
    while pos + 8 <= len(raw):
        ln = int.from_bytes(raw[pos:pos + 4], "big")
        tag = raw[pos + 4:pos + 8]
        body = raw[pos + 8:pos + 8 + ln]
        if tag == b"IHDR":
            width, height = (int.from_bytes(body[0:4], "big"),
                             int.from_bytes(body[4:8], "big"))
            depth, ctype, interlace = body[8], body[9], body[12]
        elif tag == b"PLTE":
            palette = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
        pos += 12 + ln
    if depth != 8 or interlace != 0 or not idat or not width or not height:
        return None
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        return None
    try:
        data = zlib.decompress(b"".join(idat))
    except zlib.error:
        return None

    stride = width * channels
    if height * (1 + stride) > len(data):
        return None

    # HOW MUCH DEFILTERING THIS WILL COST, BEFORE COMMITTING TO IT. Scanline filters are
    # per-byte and sequential, so a large filtered image is genuinely slow in Python. Reading
    # one byte per row to find out is not — and a palette export like this one turns out to use
    # filter 0 on all 1600 rows, so there is nothing to undo at all.
    _work = sum(stride for _y in range(height) if data[_y * (1 + stride)])
    if _work > 6_000_000:
        return None                      # let Pillow answer; this would take seconds

    prev = bytearray(stride)
    lum, seen, off = 0.0, 0, 0
    # Sample across the row rather than every pixel: a wordmark is wide, and every few columns
    # is a fair sample of it.
    step = max(1, width // 400) * channels
    # AND ACROSS THE WHOLE HEIGHT. The first version stopped as soon as it had enough visible
    # pixels, which sounds like a saving and is a bias: a wordmark sits in the middle of its
    # canvas, so the first fifty rows of a 1600-row logo are margin. On the real Dyson file
    # that returned a mean luminance of 0.0 — pure black — for an image whose lettering is
    # white. Rows are still defiltered in order because each depends on the one above; only
    # the SAMPLING is spread.
    row_step = max(1, height // 200)
    for _y in range(height):
        ftype = data[off]
        line = bytearray(data[off + 1:off + 1 + stride])
        off += 1 + stride
        if ftype:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                if ftype == 1:
                    line[i] = (line[i] + a) & 0xFF
                elif ftype == 2:
                    line[i] = (line[i] + b) & 0xFF
                elif ftype == 3:
                    line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
                elif ftype == 4:
                    c = prev[i - channels] if i >= channels else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[i] = (line[i] + pred) & 0xFF
                else:
                    return None
        prev = line
        if _y % row_step:
            continue
        for i in range(0, stride, step):
            if ctype == 6:
                r, g, b, alpha = line[i], line[i + 1], line[i + 2], line[i + 3]
            elif ctype == 2:
                r, g, b, alpha = line[i], line[i + 1], line[i + 2], 255
            elif ctype == 0:
                r = g = b = line[i]
                alpha = 255
            elif ctype == 4:
                r = g = b = line[i]
                alpha = line[i + 1]
            else:                                          # palette
                idx = line[i]
                if (idx + 1) * 3 > len(palette):
                    continue
                r, g, b = palette[idx * 3:idx * 3 + 3]
                alpha = trns[idx] if idx < len(trns) else 255
            if alpha > 128:
                lum += 0.299 * r + 0.587 * g + 0.114 * b
                seen += 1
    return (lum / seen) if seen >= 20 else None


def _raster_is_light(path: str) -> Optional[bool]:
    """True when a raster logo's VISIBLE pixels are predominantly light.

    ALPHA IS THE WHOLE POINT. A transparent PNG of a white wordmark is almost entirely
    transparent, so averaging every pixel says "dark" and gets it exactly backwards —
    reproducing the bug this is here to catch. Only pixels the reader will see are weighed.

    None means "could not tell", which is a real answer and must not collapse to either
    extreme: an unreadable file, a format neither reader handles, or an image with nothing
    visible in it all leave the logo exactly as it renders today.
    """
    lum = _png_visible_luminance(path)
    if lum is None:
        try:
            from PIL import Image                                   # type: ignore
        except ImportError:
            return None
        try:
            with Image.open(path) as im:
                im = im.convert("RGBA")
                im.thumbnail((160, 160))
                tot, n = 0.0, 0
                for r, g, b, a in im.getdata():
                    if a > 128:
                        tot += 0.299 * r + 0.587 * g + 0.114 * b
                        n += 1
            if n < 20:
                return None
            lum = tot / n
        except Exception:                                           # noqa: BLE001
            return None
    return lum > 200


# A white mark needs a ground to sit on. SDI's own ink, so the plate reads as part of the
# letterhead rather than a box somebody drew round the customer's logo.
_DARK_PLATE = ("display:inline-flex;align-items:center;background:#282928;"
               "padding:10px 16px;border-radius:4px;")


def _webp_to_png_bytes(path: str) -> Optional[bytes]:
    """A WEBP logo re-encoded as PNG bytes, so the quote's data URI is a format every mail
    client and PDF engine renders. Returns None when Pillow/libwebp cannot read it — the
    caller treats that exactly as an unreadable file (text fallback), never a crash."""
    try:
        from PIL import Image                                       # type: ignore
        import io
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            buf = io.BytesIO()
            im.convert("RGBA").save(buf, "PNG")
            return buf.getvalue()
    except Exception:                                               # noqa: BLE001
        return None


def _load_logo_markup(customer: str) -> str:
    """Return inline SVG (bare) or <img> base64 for the customer logo, else empty (text fallback).

    A WHITE LOGO ON A WHITE LETTERHEAD IS AN ABSENT LOGO.

    "Dyson logo missing." It was not missing. `Dyson.svg` was on the page, correctly sized and
    correctly placed, drawn entirely in `.st0{fill:#FFFFFF;}` — a white wordmark on a white
    header. James renamed the file, then made a PNG, and the PNG is white on transparent too,
    so the second attempt rendered exactly as invisibly as the first. Reading the delivered
    quote and decoding its own base64 is what showed it: 3800x1600, valid PNG, white letters.

    THE FILE WAS NEVER THE PROBLEM AND NEITHER WAS THE FORMAT. Dyson's brand mark IS white —
    that is the correct mark, and their own guidelines put it on a dark ground. So the fix is
    the ground, not the file: a logo whose visible marks are light gets SDI's ink behind it.

    Done by measuring rather than by a per-customer rule, because the next white logo will
    arrive without anyone remembering this, and a list of customers-whose-logo-is-white is a
    list somebody has to maintain.
    """
    key = _normalise_key(customer)
    if not key or not os.path.isdir(ASSETS_LOGOS):
        return ""
    # ── ONE KEY, TWO FILES, AND WHICHEVER THE FILESYSTEM HANDED BACK FIRST ──────────
    #
    # This was `for fn in os.listdir(...)`, unsorted, returning the FIRST stem that matched.
    # After the Dyson SVG was replaced with a PNG there were two files answering to the same
    # customer — Dyson.svg and Dyson.png — and which one reached the quote depended on the
    # order the directory happened to enumerate in. Same folder, same code, same customer,
    # different logo between runs.
    #
    # That is a far better fit for what was actually observed than any single-cause theory:
    # "Dyson logo missing", then a rename, then "dyson is there.....", then missing again. The
    # SVG is drawn in white (`.st0{fill:#FFFFFF;}`) and vanishes on a white header; the PNG is
    # a black plate with white lettering and shows. Two files, one key, a coin toss each run.
    #
    # NEWEST WINS, which is both deterministic and the right reading of intent: somebody who
    # exports a new logo for a customer means the new one. Ties break on name so two files
    # written in the same second still resolve the same way on every machine.
    try:
        _matches = [fn for fn in os.listdir(ASSETS_LOGOS)
                    if _normalise_key(os.path.splitext(fn)[0]) == key]
    except OSError:
        return ""

    def _newest_first(fn: str):
        try:
            return (-os.path.getmtime(os.path.join(ASSETS_LOGOS, fn)), fn)
        except OSError:
            return (0.0, fn)

    _matches.sort(key=_newest_first)
    if len(_matches) > 1:
        # SAID, NOT SILENTLY RESOLVED. An ambiguity nobody is told about is one nobody tidies
        # up, and this one presents as an intermittent rendering fault.
        print(f"   [quote] {len(_matches)} logo files match customer {customer!r}: "
              f"{', '.join(_matches)} — using {_matches[0]} (most recently written). "
              f"Delete the others to make this unambiguous.", flush=True)
    try:
        for fn in _matches:
            stem, ext = os.path.splitext(fn)
            p = os.path.join(ASSETS_LOGOS, fn)
            if ext.lower() == ".svg":
                svg = open(p, encoding="utf-8", errors="replace").read()
                m = re.search(r"<svg\b.*?</svg>", svg, re.S | re.I)
                _markup = m.group(0) if m else svg
                inner = _size_svg(_markup, height_px=72)
                _style = (_DARK_PLATE if _svg_is_light(_markup)
                          else "display:inline-flex;align-items:center;")
                return f'<span style="{_style}">{inner}</span>'
            if ext.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                if ext.lower() == ".webp":
                    # A CLIENT DROPS THE FILE THEY WERE SENT, WHATEVER IT IS. Harrods'
                    # logo arrived as .webp and would otherwise be skipped — its stem
                    # matches, but the extension was not in the accepted set, so the quote
                    # fell back to the customer's name in text and nobody was told why.
                    #
                    # WEBP is not embedded raw. The quote is emailed and printed to PDF,
                    # and WEBP is unreliable in both (Outlook's Word engine will not render
                    # it). So it is transcoded to PNG here — the data URI the quote carries
                    # is always a format every mail client and PDF engine handles, and the
                    # folder becomes drop-anything.
                    raw = _webp_to_png_bytes(p)
                    if raw is None:
                        # Pillow/libwebp unavailable or the file is unreadable — treat it
                        # exactly as any unreadable logo: skip, text fallback, never crash.
                        continue
                    mime = "image/png"
                else:
                    raw = open(p, "rb").read()
                    mime = "image/png" if ext.lower() == ".png" else ("image/jpeg" if ext.lower() in (".jpg", ".jpeg") else "image/gif")
                data = base64.b64encode(raw).decode("ascii")
                img = (f'<img src="data:{mime};base64,{data}" alt="{_esc(customer)}" '
                       f'style="max-height:72px;max-width:300px;object-fit:contain;">')
                if _raster_is_light(p):
                    return f'<span style="{_DARK_PLATE}">{img}</span>'
                return img
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
                        summary: Optional[Dict[str, Any]] = None,
                        packing_charged: bool = True) -> List[str]:
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
    # ALIASES OF ONE DEPARTMENT ARE ONE LINE. A Fold row can invert to both "folding" and
    # "fold", and 7332-01's quote listed "Precision folding and forming to drawing" and
    # "Fold" as two things we do. Siblings come from the same department map the sheet is
    # built from, so the first alias seen speaks for the department.
    # From OP_NAME_MAP ALONE — not the tube remap, which sends "folding" to the Tubebend
    # department for a tube job and would make a press-brake fold on another part a
    # sibling of tube bending.
    try:
        from wb_populate import OP_NAME_MAP as _NAME_MAP
        _by_dept: Dict[str, set] = {}
        for _eng, _dept in (_NAME_MAP or {}).items():
            if _dept:
                _by_dept.setdefault(str(_dept).strip().lower(), set()).add(
                    str(_eng).strip().lower())
        _siblings: Dict[str, set] = {}
        for _low in _by_dept.values():
            for _o in _low:
                _siblings.setdefault(_o, set()).update(_low)
    except Exception:                                            # noqa: BLE001
        _siblings = {}
    _spoken: set = set()
    # Pass the SUMMARY: workbook_labour (the canonical accepted route) hangs off it, not
    # off the parts list. Handing over parts alone silently drops to the pre-filter
    # engine fields, which is what put powder and weld dressing on a timber crate.
    for op in costed_operations(summary if isinstance(summary, dict) else parts):
        _key = str(op).strip().lower()
        if _key in _spoken:
            continue
        _spoken |= _siblings.get(_key, {_key})
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
    # PACKING IS PROMISED ONLY WHEN IT IS PRICED. 7332-01 carried PACKAGING on the sheet at
    # £0 and this list still promised "Individual packing for transport".
    tails = ["Clean assembly and inspection"]
    if packing_charged:
        tails.append("Individual packing for transport")
    if _has_film:
        tails.insert(0, "Protective film removal")
    for tail in tails:
        if tail not in s:
            out.append(tail); s.add(tail)
    return out


def _materials_line(parts: List[Dict[str, Any]]) -> str:
    """What the customer is told the product is made of.

    IT COLLECTED `normalized_material` OFF EVERY LINE, including the bought-ins — and a
    bought-in carries the drawing sheet's material because the sheet's reading was stamped on
    every row it found. At best that repeats what a fabricated part already said; at worst it
    puts a second material on a quotation for a product made of one, which is a claim about
    the goods.

    `describes_the_product` answers None for anything whose material is not its own: a
    commercial line, a subcontract service, roll goods, and a bought-in wearing the assembly's
    reading.
    """
    mats = []
    for p in parts:
        m = describes_the_product(p)
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


# Words that describe the FILE rather than the product. The revision alternative
# deliberately has no trailing word boundary: it ends on "]" in "REV[E]", and "]" followed
# by a space is two non-word characters, so \b never matches there.
_STEM_NOISE = re.compile(
    r"\b(?:solidworks|combined|merged|final|copy|drawings?|pack|scan|pdf|dxf|dwg)\b"
    r"|\brev\[?[a-z0-9]*\]?",
    re.IGNORECASE)


def _part_records(summary: Dict[str, Any]):
    """Every plain-dict part record on the job, wherever this pipeline files them.

    Three populations hold the same descriptions and no single one is always present: the
    write-up's parts, the costed estimates, and the raw parts list. Asked in that order
    because the write-up is the one whose descriptions a person has read."""
    for _where in (
        ((summary.get("manufacturing_writeup") or {}).get("parts")),
        ((summary.get("estimate_summary") or {}).get("part_estimates")),
        summary.get("parts"),
    ):
        for _rec in (_where or []):
            if isinstance(_rec, dict):
                yield _rec


# What the engine writes where a description would be, on a part that has no drawing sheet to
# take one from. Useful on the provenance tab, never a thing to print as the name of a product.
_ENGINE_NOTES = ("from the solidworks model", "minted from", "no drawing sheet of its own")
_BARE_KINDS = ("assembly", "sub-assembly", "sub assembly", "weldment", "part", "component")


def _is_an_engine_note(text: Any) -> bool:
    """True when this 'description' is the engine talking about itself.

    Two shapes: a sentence explaining where a record came from, and a bare kind word —
    "assembly" is what a thing IS, not what it is called, and a quotation headed "assembly"
    tells a customer nothing they did not know from the drawing number above it.
    """
    t = str(text or "").strip().lower()
    if not t:
        return False
    if any(n in t for n in _ENGINE_NOTES):
        return True
    return t.strip(" .-–—()") in _BARE_KINDS


def _reads_as_an_instruction(text: Any) -> bool:
    """True when a 'title' is a manufacturing note wearing the title box's clothes.

    11908-21's quotation went out headed "QTY FILL ANY OPEN GAPS ON CORNERS WITH
    MATCHING WAX" — a drawing note the extractor filed as the title, printed as the
    PRODUCT NAME on a customer document. A product name names a thing; an instruction
    commands one, and the imperative verbs are the tell. Judged on words, never on this
    job: "FILL", "CHECK", "ENSURE" head notes on every SDI drawing, and no SDI product
    is called any of them.
    """
    t = str(text or "").strip().upper()
    if not t:
        return False
    _IMPERATIVES = ("FILL ", "CHECK ", "ENSURE ", "DO NOT", "APPLY ", "REMOVE ",
                    "ALLOW ", "REFER TO", "SEE SHEET", "SEE DRAWING", "MUST BE",
                    "TO BE ", "NOTE:", "ALL DIMENSIONS")
    _t_body = re.sub(r"^QTY\.?\s+", "", t)      # a swallowed column header before a note
    return any(_t_body.startswith(w) for w in _IMPERATIVES)


# A code, not a name: digits-led, then only SEPARATED short segments — 10975-02-GA,
# 7332-01-001, 0355255. The separator is required, not optional: without it the pattern
# chops any run of letters into code-sized pieces and "600mm Shelf" reads as a part number.
_CODE_SHAPED = re.compile(r"^\d{3,}[A-Za-z]?(?:[-_ ][A-Za-z0-9]{1,4})*$")


def _source_drawing_names(summary: Dict[str, Any]) -> List[str]:
    """The filenames of the drawings this job was read from, without their extensions.

    The office names a pack for the office AND for the product — "0355255 - A4 Table Top
    Graphic Holder - 10975_REV B.pdf" — so when no record in the job can say what the unit
    is, the drawing file often can.

    READ THE FIELDS THE SCAN ACTUALLY WRITES. The first version of this guessed at plausible
    key names and found NOTHING on the real 10975-02 record, so the fallback it existed to
    feed still produced the drawing code. file_scan writes exactly two:

        primary_pdf       {"name": ..., "path": ...}
        job_source_pdfs   [{"name": ..., "path": ..., "page_count": ...}, ...]

    Both are read here, at the top level and under estimate_summary, because a caller may
    hand this either the whole record or the estimate half of it. The speculative keys are
    kept below them — they cost nothing and a differently-shaped record still answers — but
    the two real ones come first and are what the regression test pins.
    """
    out: List[str] = []
    _seen = set()

    def _add(value: Any) -> None:
        if isinstance(value, dict):
            value = value.get("name") or value.get("path")
        text = str(value or "").strip()
        if not text:
            return
        base = re.sub(r"\.(pdf|dxf|dwg|xls[xm]?|step|stp)$", "",
                      text.replace("\\", "/").split("/")[-1],
                      flags=re.IGNORECASE).strip()
        if base and base.upper() not in _seen:
            _seen.add(base.upper())
            out.append(base)

    if not isinstance(summary, dict):
        return out
    _roots = [summary]
    _es = summary.get("estimate_summary")
    if isinstance(_es, dict):
        _roots.append(_es)

    for _root in _roots:
        # The two the scan really writes, primary first — on a multi-PDF pack the primary
        # is the sheet the job was identified from.
        _add(_root.get("primary_pdf"))
        for _rec in (_root.get("job_source_pdfs") or []):
            _add(_rec)
        # And the shapes other readers have used, which cost nothing to try.
        for key in ("source_pdfs", "source_files", "pdf_files", "drawing_files",
                    "files_scanned", "input_files", "pdf_path", "primary_pdf_path",
                    "source_pdf", "drawing_file"):
            value = _root.get(key)
            if isinstance(value, (str, dict)):
                _add(value)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    _add(item)
        _da = _root.get("document_analysis")
        if isinstance(_da, dict):
            for key in ("source_file", "pdf_path", "file", "files"):
                value = _da.get(key)
                if isinstance(value, (str, dict)):
                    _add(value)
                elif isinstance(value, (list, tuple)):
                    for item in value:
                        _add(item)
            for page in (_da.get("pages") or []):
                if isinstance(page, dict):
                    _add(page.get("source_file") or page.get("source_pdf")
                         or page.get("file"))
        for page in (_root.get("pages") or []):
            if isinstance(page, dict):
                _add(page.get("source_file") or page.get("source_pdf") or page.get("file"))
    return out


def _title_from_a_filename(name: Any) -> str:
    """The product name inside a drawing's filename, or "" when there is none in it.

    A pack is named for the office as well as for the product, and the office's half
    brackets the product's:

        0355255 - A4 Table Top Graphic Holder - 10975_REV B
        0359967 - 11908-21-GA - Rev A - Sunglsses Tray Large Colour Core

    Job numbers, sheet-role tokens and a bare revision letter are all in their own boxes on
    the sheet already, so they come off — but only as WHOLE TOKENS AT THE ENDS, which is why
    "A4", "Type 2 Bracket" and "L Stand" keep every word they have.
    """
    cleaned = re.sub(r"\.(pdf|dxf|dwg|xls[xm]?)$", "", str(name or ""),
                     flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*\d+[A-Za-z]?(?:[-_]\d+[A-Za-z]?)*\s*[-_]?\s*", "", cleaned)
    # ORDER MATTERS HERE, and it is not the obvious one. Separators become spaces FIRST, so
    # "GA2_REV[E]" exposes its own word boundary. The noise filter runs BEFORE the camel-case
    # split, because splitting turns "SolidWorks" into "Solid Works" and the filter would
    # then match neither half.
    cleaned = re.sub(r"[_\-]+", " ", cleaned)
    cleaned = _STEM_NOISE.sub(" ", cleaned)
    # Folder names are written without spaces far more often than not, and
    # "BootsLadderRackCommsBar" is not something to put in front of a customer.
    cleaned = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -_")
    _debris = re.compile(r"^(?:\d+|[A-Za-z]|GA\d?|ASSY|ASSEMBLY|ARR|GEN)$", re.IGNORECASE)
    words = cleaned.split()
    while words and _debris.match(words[0]):
        words.pop(0)
    while words and _debris.match(words[-1]):
        words.pop()
    cleaned = " ".join(words).strip(" -_")
    return cleaned if len(cleaned) > 2 and not _reads_as_a_code(cleaned) else ""


def _reads_as_a_code(text: Any) -> bool:
    """True when a 'description' is only the number the job is already filed under.

    10975-02's Description box came out reading "10975-02-GA" — the assembly's own code,
    printed under a label an estimator asked for so he could tell at a glance WHAT a sheet
    was for when requoting. The number is already in the Drawing box beside it, so this
    says nothing twice and costs the box its only job.

    The existing guard compared the description against the drawing NUMBER and let this
    through, because "10975-02-GA" and "10975-02" are not equal strings — they are the same
    fact in two spellings, which is precisely the case worth catching. Judged on SHAPE
    instead, so it holds for any pack: a code is digits followed by short segments, and a
    product name has a word in it.
    """
    return bool(_CODE_SHAPED.match(str(text or "").strip()))


def _drawing_identity(summary: Dict[str, Any], stem: str) -> tuple:
    """(drawing number, revision, unit description) for the quotation header.

    Every one of these is stated on the drawing, and the extract already transcribes the
    title block. Reading them beats parsing a folder name, which carries whatever the
    person who made the folder happened to type — "SolidWorks", "combined.pdf", a revision
    tag — none of which is the product.
    """
    _di = (summary.get("llm_full_extract") or {}).get("drawing_info") or {}
    if not _di and isinstance(summary.get("estimate_summary"), dict):
        _di = (summary["estimate_summary"].get("llm_full_extract") or {}).get("drawing_info") or {}

    _number = str(_di.get("drawing_number") or "").strip()
    _rev_raw = str(_di.get("revision") or "").strip()
    _title = str(_di.get("title") or "").strip()
    # A NOTE IS NOT A NAME. Cleared here, at the source, so the top-assembly fallback
    # below supplies the draughtsman's own description instead — the same path a blank
    # title has always taken.
    if _reads_as_an_instruction(_title):
        _title = ""
    _project = str(_di.get("project") or "").strip()

    # The canonical top assembly is the next best statement of what the unit IS: it is the
    # thing every other part hangs off, and it carries the draughtsman's own description.
    if not _number or not _title:
        _payload = ((summary.get("estimate_summary") or {}).get("canonical_route_shadow")
                    or summary.get("canonical_route_shadow") or {})
        # `top_assembly` IS BLANK WHENEVER A JOB HAS MORE THAN ONE ROOT — the compiler says
        # so where it emits the field, and it is the common case on a pack of modules.
        # Reading only that field meant this fell through to the drawing NUMBER as the unit
        # description, and on 12349-02 the Description box came out empty (a description
        # that is only the number is not written) on a job whose own provenance tab prints
        # "GRAVITY FEEDER MODULES" against the very node the graph calls the top.
        #
        # So the forest is consulted too, and narrowed the only way that cannot invent a
        # product name: the root the drawing number PREFIXES, outermost first — 12349-02
        # picks 12349-02-69 over 12349-02-69-100. Where several roots ship and none is the
        # outermost of the others, nothing is claimed and the caller writes nothing, which
        # is the honest answer to "what is this one unit called" when there are two.
        _roots = [str(r) for r in (_payload.get("top_assemblies") or []) if r]
        _top = str(_payload.get("top_assembly") or "")
        if not _top and _roots:
            if len(_roots) == 1:
                _top = _roots[0]
            elif _number:
                _owned = sorted((r for r in _roots if r.upper().startswith(_number.upper())),
                                key=len)
                if _owned:
                    _top = _owned[0]
        # AND THE NODE MAY NOT BE A DICT. The graph's nodes are PartNode objects; the
        # projection copies them as they are, and `json.dump(default=str)` turns each one
        # into its repr on the way to the saved record. So this arm was looking for a
        # dictionary in a list that holds objects in memory and strings on disk, and found
        # neither. The part RECORDS are plain dictionaries in both worlds and carry the same
        # descriptions the provenance tab prints, so they answer when the nodes cannot.
        if _top:
            _title = "" if _is_an_engine_note(_title) else _title
            for _node in (_payload.get("nodes") or []):
                _npn = (_node.get("part_number") if isinstance(_node, dict)
                        else getattr(_node, "part_number", None))
                if str(_npn or "") != _top:
                    continue
                _ndesc = (_node.get("description") if isinstance(_node, dict)
                          else getattr(_node, "description", None))
                _number = _number or str(_npn or "")
                _title = _title or str(_ndesc or "")
                break
            if not _title:
                for _rec in _part_records(summary):
                    if str(_rec.get("part_number") or "").strip().upper() == _top.upper():
                        _title = str(_rec.get("description") or "").strip()
                        if _title:
                            break
            # AND A NOTE THE ENGINE WROTE TO ITSELF IS NOT A PRODUCT NAME.
            #
            # An assembly parent minted from the SolidWorks component tree has no drawing
            # sheet of its own, so it has no description — it carries the sentence saying
            # where it came from instead. On 12349-02 that parent is also the OUTERMOST
            # root, so it became the unit's identity, and the customer quotation went out
            # headed
            #
            #     Quotation 12349-02-69-GA - assembly (from the SolidWorks model's own tree)
            #
            # with the same phrase in the Description box of the estimate and in the alt
            # text of the general arrangement. Reading the models made the header worse than
            # leaving it blank.
            #
            # So the note is refused and the search carries on into the roots that DO have a
            # description — innermost of the ones this drawing number owns, which on this job
            # is 12349-02-69, "GRAVITY FEEDER MODULES". Nothing is invented: if no root can
            # say what the unit is, the caller writes nothing, exactly as before.
            if _is_an_engine_note(_title):
                _title = ""
            if not _title:
                _others = sorted((r for r in _roots if r and r != _top), key=len)
                # WHOSE JOB IS THIS. `_number` is still empty whenever the title block could
                # not be read, which is exactly the case this arm exists for — so the prefix
                # comes from the folder when the drawing cannot supply it. Without it a
                # second customer's assembly, staged in the same pack, can name this unit.
                _pref = str(_number or "").strip()
                if not _pref:
                    _m0 = re.match(r"\s*(\d+[A-Za-z]?(?:[-_]\d+[A-Za-z]?)*)", stem)
                    _pref = _m0.group(1).strip(" -_") if _m0 else ""
                if _pref:
                    _others = [r for r in _others
                               if r.upper().startswith(_pref.upper())] or _others
                for _cand in _others:
                    for _rec in _part_records(summary):
                        if str(_rec.get("part_number") or "").strip().upper() != _cand.upper():
                            continue
                        _d = str(_rec.get("description") or "").strip()
                        if _d and not _is_an_engine_note(_d):
                            _title = _d
                            break
                    if _title:
                        break
            _number = _number or _top

    # THE PART RECORDS, WHATEVER THE GRAPH DID — and this arm sits OUTSIDE the top-assembly
    # block on purpose, because that is where it was and that is why it did not fire.
    #
    # Both earlier attempts lived under `if _top:`, so both depended on the graph naming a
    # root. When SolidWorks applies, the tree mints a parent above everything and that parent
    # is the only root, carrying the engine's own note for a description. When SolidWorks does
    # NOT apply, there may be no named root at all — and then neither fix ran, the title stayed
    # empty, and 12349-02's Description box came out blank on run after run of a job whose own
    # provenance tab prints "GRAVITY FEEDER MODULES" against 12349-02-69.
    #
    # A description does not need a graph. It needs the part records, which every run has, and
    # the drawing number to say which of them is this unit: the outermost code the number owns,
    # shortest first, skipping anything that is the engine talking about itself. Nothing is
    # invented — no owned record with a real description means nothing is written, exactly as
    # before.
    if not _title:
        # THE JOB'S NUMBER, NOT THE TOP ASSEMBLY'S CODE. `_number` may by now BE the minted
        # parent — 12349-02-69-GA — and filtering the records by that prefix matches only the
        # minted parent itself, whose description is the note we are here to refuse. The
        # folder is the job, and the job is who owns these records.
        _m1 = re.match(r"\s*(\d+[A-Za-z]?(?:[-_]\d+[A-Za-z]?)*)", stem or "")
        _pref2 = (_m1.group(1).strip(" -_") if _m1 else "") or str(_number or "").strip()
        if _pref2:
            # A LEAF PART'S DESCRIPTION IS NEVER THE NAME OF THE PRODUCT.
            #
            # This took the shortest owned part number with a description, and on 7332-01
            # that is 7332-01-001 — so a Harrods A3 signage stand went out with
            #
            #     Description    BASE
            #
            # in the header box an estimator asked for so he could trace a job back when
            # requoting it. A back panel's name on the whole job is worse for that purpose
            # than an empty box, because an empty box sends him to the drawing and a wrong
            # one does not.
            #
            # So a record may only name the unit if things HANG OFF IT: flagged as an
            # assembly, or its part number is the stem of other parts in this pack. That is
            # structural rather than a list of words, so it holds on packs nobody has seen —
            # 12349-02-69 owns -04M and -03M-01 and keeps "GRAVITY FEEDER MODULES", while
            # 7332-01-001 owns nothing and is refused.
            #
            # Where no assembly can say what the unit is, nothing is written, which is the
            # rule everywhere else in this function: the number, revision, client and date
            # still identify the job, and none of them can be wrong.
            # LIST, NOT THE GENERATOR. _part_records yields, so building the name set below
            # exhausts it and the sort that follows would see nothing — blanking every
            # description on every job, which is a worse fault than the one being fixed.
            _recs = list(_part_records(summary))
            _all_pns = {str(r.get("part_number") or "").strip().upper() for r in _recs}
            _all_pns.discard("")

            def _owns_other_parts(_pn: str) -> bool:
                _u = _pn.upper()
                return any(o != _u and o.startswith(_u) and o[len(_u):len(_u) + 1] in "-_"
                           for o in _all_pns)

            # WHERE THE JOB OWNS EXACTLY ONE RECORD, THAT RECORD IS THE UNIT. The refusal is
            # about CHOOSING BETWEEN SIBLINGS: 7332-01 owns six flat parts, none of which
            # hangs off another, and picking the shortest of six equals is arbitrary — it
            # returned BASE, and STRAP or CAP were as good a guess. One candidate is not a
            # guess, and a job whose graph gave no root still has to be able to name itself.
            _owned = [r for r in _recs
                      if str(r.get("part_number") or "").strip().upper()
                      .startswith(_pref2.upper())]
            _alone = len(_owned) == 1
            for _rec in sorted(_owned,
                               key=lambda r: len(str(r.get("part_number") or "")) or 999):
                _pn = str(_rec.get("part_number") or "").strip()
                if not _pn:
                    continue
                if not (_alone or _rec.get("is_assembly_parent") or _rec.get("is_sub_assembly")
                        or _owns_other_parts(_pn)):
                    continue
                _d = str(_rec.get("description") or "").strip()
                if _d and not _is_an_engine_note(_d):
                    _title = _d
                    break

    # AND A CODE IS NOT A DESCRIPTION EITHER. Every arm above reads a description off a
    # record, and a minted assembly parent's "description" is often just its own code.
    # Refused here, in front of the stem fallback, so the pack's own filename gets the
    # chance it was always meant to have — "0355255 - A4 Table Top Graphic Holder -
    # 10975_REV B.pdf" knows what the unit is even when no record says so.
    if _title and _reads_as_a_code(_title):
        _title = ""

    # Folder name LAST, and cleaned. A stem that reduces to nothing but noise words yields
    # no description at all rather than a misleading one — "SolidWorks" is not a product.
    if not _number:
        # A JOB NUMBER IS DIGITS, NOT ANY RUN OF ALPHANUMERICS.
        #
        # [0-9A-Za-z_-]* is greedy and every character of "11350-BootsLadderRackCommsBar"
        # is in it, so the whole folder name came out as the drawing number. Bounded to
        # leading digits, an optional single letter, and further all-digit groups — which
        # keeps "11772-01-09" and "0357299_2" whole while stopping at the first word.
        _m = re.match(r"\s*(\d+[A-Za-z]?(?:[-_]\d+[A-Za-z]?)*)", stem)
        _number = _m.group(1).strip(" -_") if _m else stem
    if not _title:
        # THE PACK'S OWN FILENAMES, NOT ONLY THE CALLER'S STEM.
        #
        # This arm was always here and on 10975-02 it never fired, because `stem` is the JOB
        # stem — "10975-02" — which cleans down to nothing. The name that knows what the
        # unit is sits on the drawing file itself: "0355255 - A4 Table Top Graphic Holder -
        # 10975_REV B.pdf". The refusal of a code-shaped title correctly blanked the
        # Description box, and then there was nothing to put in it.
        #
        # Longest first: a pack usually holds a GA and some details, and the GA's name is
        # the one carrying the product. Nothing is invented — a filename that cleans to
        # noise still yields no description, exactly as the folder name does.
        _names = [stem]
        try:
            for _f in (_source_drawing_names(summary) or []):
                if _f and _f not in _names:
                    _names.append(_f)
        except Exception:                                             # noqa: BLE001
            pass
        for _cand_stem in sorted(_names, key=lambda s: -len(str(s or ""))):
            _title = _title_from_a_filename(_cand_stem)
            if _title:
                break

    _rev = ""
    if _rev_raw:
        _rev = _rev_raw if _rev_raw.lower().startswith("rev") else f"Rev {_rev_raw.upper()}"
    else:
        # THE REVISION IS ON THE PACK'S NAME, AND THIS COULD NOT READ IT.
        #
        # The old pattern required "_rev" immediately followed by the letter, and searched
        # only the PDF title or the caller's stem. Both real packs defeat it:
        #
        #     "0355255 - A4 Table Top Graphic Holder - 10975_REV B"   -> space before B
        #     "0359967_-_11908-21-GA_-_Rev_A_Sunglsses..."            -> underscore before A
        #
        # so 10975-02 went out with an empty Rev box beside a filename that says REV B. The
        # separator is now any of space, dot, dash or underscore, the drawings' own names are
        # searched as well, and the token has to END there — "REVERSE PANEL" is not Rev E.
        _pdf_title = str(_get(summary, "pdf_metadata", "/Title", default="")
                         or _get(summary, "drawing_metadata", "pdf_metadata", "/Title",
                                 default=""))
        _rev = ""
        _rev_re = re.compile(
            r"(?:^|[_\-\s])rev(?:ision)?[\s._\-]*\[?([A-Za-z]\d?|\d{1,2})\]?(?![A-Za-z0-9])",
            re.IGNORECASE)
        for _text in [_pdf_title, stem] + list(_source_drawing_names(summary) or []):
            _m2 = _rev_re.search(str(_text or ""))
            if _m2:
                _rev = "Rev " + _m2.group(1).upper()
                break

    return _number, _rev, (_title or _project or _number)


def build_quote_html(summary: Dict[str, Any], job_stem: Optional[str] = None,
                     manual_workbook: Optional[str] = None, customer: Optional[str] = None,
                     audience: Optional[str] = None) -> str:
    """The quotation page, for the audience the record allows.

    PORTAL is the estimator's editable view: it may carry a pending price and say what is
    outstanding, because the person reading it is the person who closes those items.
    CUSTOMER is the released document, and asking for one the record does not allow raises
    `NotReleasable` rather than producing a page that has to apologise for itself.

    The default is not a default: it is `audience_for(summary)`, so a caller that says nothing
    gets the portal view until the record earns the customer one. Naming CUSTOMER explicitly
    is how you ask for a released document, and it is checked.
    """
    _state = quote_state(summary)
    if audience == CUSTOMER and not _state["customer_releasable"]:
        raise NotReleasable(
            "this quotation is not released for customer issue — "
            + "; ".join(b["what"] for b in _state["blocking"]))
    audience = audience or (CUSTOMER if _state["customer_releasable"] else PORTAL)
    _for_customer = (audience == CUSTOMER)
    # Declared in the document, because that is what the delivery routes read. See
    # `quote_state.release_meta_tag`.
    _release_meta = release_meta_tag(audience)
    stem = job_stem or summary.get("job_output_stem") or summary.get("job_folder", "").split("\\")[-1] or "Job"
    stem = str(stem)

    # THE UNIT IS NOT THE FOLDER NAME.
    #
    # product was the job stem with a leading job number stripped off. For the folder
    # "2085 - SolidWorks" that leaves "SolidWorks", so the customer's quotation was headed
    # "Quotation — SolidWorks". For a combined PDF it leaves the whole filename,
    # "...-GA2_REV[E]-combined.pdf", which is worse in the other direction. Neither names
    # the thing being quoted.
    #
    # The drawing states both facts in its own title block, and the extract already
    # transcribes them: drawing_number and title. Use those, and fall back through the
    # canonical top assembly before ever reaching the folder name.
    job_number, rev, product = _drawing_identity(summary, stem)

    es = summary.get("estimate_summary", {}) or {}
    qty = _get(es, "estimate_workbook_inputs", "assumed_job_quantity") or 0
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        qty = 0

    # ── THE CUSTOMER'S FIGURE RESTS ON A TRACEABLE COST ─────────────────────────
    #
    # D-141. This read the workbook-equivalent cost straight out of the summary and marked it
    # up. Every other document was put behind `publishable_total` — a total with no recorded
    # workbook cell is not publishable — and the one page that goes OUTSIDE the building was
    # the last still taking the raw figure. A quote is the worst place for an untraceable
    # number: it is the only deliverable a customer keeps.
    #
    # Where the cost cannot be traced, no unit price is computed, so the quote renders its
    # own missing-price path rather than a confident figure resting on nothing.
    # ── AND IT FAILS CLOSED, IN ONE PLACE ───────────────────────────────────────
    #
    # Three shapes were tried. `except Exception: pass` left the old price LIVE when the check
    # broke — the one failure mode a guard exists for. Removing the handling altogether made a
    # raising check CRASH quote generation, against the rule that a draft is always generated
    # in the portal. Catching, refusing the figure and keeping the page satisfies both, and it
    # now lives in `quote_state._price_fact` rather than here: the page and the release
    # decision were answering the same question in two places, which is how a fact acquires
    # two names.
    unit_cost = _state["price"].get("amount")
    unit_price = (unit_cost * MARKUP_FACTOR) if isinstance(unit_cost, (int, float)) else None
    order_value = (unit_price * qty) if (unit_price is not None and qty) else None

    # ── A MISSING FIGURE IS ONE LINE OF WORK, NOT A WARNING ──────────────────────
    #
    # James Gray, 18 September 2026:
    #
    #     "The default objective is a fully priced estimate, using the precedence pipeline —
    #      not a polished list of missing prices."
    #     "If still unresolved, surface ONE CONCISE INTERNAL ESTIMATOR ACTION — not a long
    #      warning block — and let the estimator enter or amend the value in the workbook."
    #     "Customer output should simply be unavailable until the estimate is complete; it
    #      should not contain 'do not issue', pricing caveats, or a catalogue of gaps."
    #
    # THIS PAGE HAS NOW GROWN A WARNING BLOCK SIX TIMES AND HAD IT REMOVED SIX TIMES — the red
    # LLM-only band, the invariant banner, "DRAFT — not for issue", the undrawn-parts gap
    # list, PRICE PENDING, and last of all a PORTAL VIEW panel with a bulleted catalogue of
    # everything outstanding. Every one was accurate. Every one was the same mistake: telling
    # a professional what is wrong with a document instead of telling them what to do next.
    #
    # The safety is not on the page and never was. An incomplete estimate is not written as a
    # customer file, is not served as a download and is not attached to a mail — none of which
    # needs a sentence on the page to work. So what is left here is the one thing the page can
    # usefully say: which value to enter, and where.
    # ── AN INTERNAL PAGE SHOWS THE FIGURE THE WORKBOOK HOLDS ────────────────────────
    #
    # James Gray, 22 Sep 2026: "Quote needs to have a price — even if a bad one since we
    # know it's only indicative... it keeps being over ridden."
    #
    # The customer document is unchanged and still fails closed: `unit_price` comes from the
    # traceable figure, and without one a customer sees no number. But this file is also
    # generated as _quote_PORTAL.html and _quote_LLM-ONLY.html — pages whose entire purpose
    # is to show the estimator what the run produced, and which already say "Indicative —
    # for internal comparison" in their own Basis row. Printing a dash there, on a job whose
    # workbook says £102.70 and whose report prints £102.70, is not caution: it sends
    # somebody to a second document to read the number this one is about.
    #
    # So the internal pages fall back to the workbook's own figure, captioned as what it is.
    # The release gates are untouched: what may reach a customer is decided by audience and
    # by `customer_releasable`, never by whether a number was rendered here.
    _internal = bool(summary.get("llm_only")) or (audience or PORTAL) != CUSTOMER
    _workbook_only = _state["price"].get("workbook_amount")
    if unit_price is None and _internal and isinstance(_workbook_only, (int, float)):
        _indicative = _workbook_only * MARKUP_FACTOR
        _price_class, _order_class = "unit", "ov"
        _unit_figure = _money(_indicative)
        _order_figure = _money(_indicative * qty) if qty else "&mdash;"
        _unit_caption = ("per unit, ex VAT · indicative, from the workbook"
                         + ((' · ' + _num(qty) + ' of') if qty else ''))
        _order_caption = "ex VAT · indicative"
        _pending_note = (
            '\n      <div class="estimator-action">Indicative: this figure is the workbook\'s '
            'own total and has not been traced to a signed-off cell. Settle the open lines on '
            'the Estimate sheet and regenerate before it is quoted.</div>')
    elif unit_price is None:
        _price_class = _order_class = "unit"
        _unit_figure = _order_figure = "&mdash;"
        _unit_caption = "per unit, ex VAT"
        _order_caption = "ex VAT"
        _pending_note = (
            '\n      <div class="estimator-action">Enter the unit cost on the Estimate sheet '
            'and regenerate — the price follows from the workbook.</div>')
    else:
        _price_class, _order_class = "unit", "ov"
        _unit_figure, _order_figure = _money(unit_price), _money(order_value)
        _unit_caption = ("per unit, ex VAT · indicative"
                         + ((' · ' + _num(qty) + ' of') if qty else ''))
        _order_caption = "ex VAT · indicative"
        # A PRICED PAGE AWAITING RELEASE SAYS NOTHING AT ALL. The estimate is complete; what
        # is outstanding is a person's sign-off, and the release form is where that is done.
        # A caveat here would be a caveat on a document that is about to be correct.
        _pending_note = ""

    # ONE part list across every deliverable (costed_facts.job_parts): the canonical
    # list the Estimate sheet was built from, not the engine's pre-canonical one. They are
    # different sets -- merged duplicates, rolled quantities, and bought-in BOM lines the
    # sheet adds -- so a quote built from part_estimates named materials and finishes for a
    # job the sheet does not contain.
    from costed_facts import job_parts as _job_parts
    parts = _job_parts(summary) or (es.get("part_estimates") or [])
    material = _materials_line(parts)
    finish = _finish_line(summary, parts)

    # THE ONE RECORD decides scope and release. What is excluded, and whether this page is
    # a draft, are read from costed_facts.costed_job — the same record the workbook tabs,
    # the report and the covering e-mail read — never re-derived here.
    try:
        from costed_facts import costed_job as _costed_job, packaging_status as _pack_status
        _record = _costed_job(summary)
        _packing = _pack_status(summary)
    except Exception:                                            # noqa: BLE001
        _record, _packing = {}, "absent"
    # THE RELEASE STATUS IS READ BUT NOT PRINTED HERE — see the draft block below.
    _release = _record.get("release") or {}
    _draft = bool(_release.get("draft"))  # retained: the fixtures assert it changes nothing
    ops = _collect_operations(parts, summary, packing_charged=(_packing != "unpriced"))

    # THE INVARIANT GATE, READ BY THE DOCUMENT THAT LEAVES THE BUILDING.
    # The checks ran and wrote their verdict onto the job, and the quote was generated
    # regardless — a gate nothing consumes is a log line, not a gate. Suppressing the quote
    # is not the answer either (an estimator still needs the working); the answer is that a
    # price we cannot stand behind must not LOOK like one we can.
    # THE INVARIANT BANNER IS NOT CUSTOMER-FACING, AND IS NO LONGER RENDERED HERE.
    #
    # It was written in engineering language and carried the engine's own reasoning onto a
    # document that leaves the building: "2 consistency check(s) FAILED", "the credibility
    # gate has judged the measured coverage too low", "5 SolidWorks model file(s) ... were
    # not read. Run tools/solidworks/sw_native_analyse.py". None of that is a customer's
    # business, and naming an internal script on a quotation is worse than saying nothing.
    #
    # The warning itself is NOT lost, and that is the condition for removing it. The
    # internal job report still leads with "This estimate is PROVISIONAL and must not be
    # released as a firm price" and renders the full invariants section, and the price on
    # this page is labelled INDICATIVE in all three places it appears — so nothing here
    # reads as a firm quotation. The estimator is warned; the customer is not shown the
    # workings.
    _inv_banner = ""  # retained for the fixture that asserts it stays empty

    # ── AND IT CANNOT BE PRINTED OR SAVED INTO A CUSTOMER DOCUMENT ───────────────
    #
    # "export, email attachment, print/share: disabled while `customer_releasable` is false."
    #
    # The attachment half is enforced where attachments are chosen (`main.py` asks
    # `quote_state`) and the filename half in `generate_quote_files`, which does not write a
    # file called `_quote.html` for a page that is not one. This is the half that lives on the
    # page, because print-to-PDF is how an HTML view becomes a document somebody emails, and
    # it is the one route no server-side gate can see.
    #
    # It replaces the page rather than watermarking it: a watermark still produces a PDF of a
    # quotation with a mark on it, and somebody will crop it.
    # WHY IT STILL DOES NOT PRINT, AND WHY THAT IS NOT A CAVEAT. Print-to-PDF is how an
    # HTML view becomes a file somebody emails, and it is the one export no server-side gate
    # can see. The page says nothing about issuing; it simply is not the customer's document
    # yet, so it does not produce one. The estimator reads it on screen as normal.
    _print_block = "" if _for_customer else """  @media print {{
    body > * {{ display:none !important; }}
    body::after {{ display:block; content:"SDI Intelligence — working copy.";
      font:600 14px/1.6 system-ui, sans-serif; padding:40px; }}
  }}"""

    customer = _derive_customer(summary, stem, manual_workbook=manual_workbook, customer_override=customer)
    # Strip any job/drawing code the name carried ('Harrods 7332-01' -> 'Harrods') BEFORE the logo
    # lookup — _normalise_key keeps digits, so the code otherwise blocks the logo file match — and
    # before the text fallback, so the heading reads as the customer, not the customer plus a code.
    customer = _clean_customer_name(customer)
    logo_markup = _load_logo_markup(customer)
    cust_header = logo_markup if logo_markup else f'<div style="font-size:18px;font-weight:600;color:#282928;">{_esc(customer)}</div>'
    sdi_logo = _sdi_logo_markup()

    ga_uri = _ga_image_data_uri(summary)
    today = date.today().strftime("%d %B %Y")

    # operations -> two-column bullet list
    inc_items = "\n".join(f"      <li>{_esc(o)}</li>" for o in ops)

    # THE GAP LIST IS INTERNAL, AND THAT IS A DELIBERATE COMMERCIAL CHOICE.
    #
    # A quotation once carried a "Not included in this price" block naming every BOM line whose
    # drawing was missing. It is defensible engineering and it is the wrong document for it: what
    # a customer is told about scope is the estimator's decision and their wording, not a list
    # this engine generates from its own findings. The same page already carries INDICATIVE in
    # three places, so nothing here reads as a firm price for a whole product.
    #
    # THE GAP IS NOT LOST, which is the condition for keeping it off this page. costed_facts
    # .undrawn_bom_lines is read by the Estimate sheet, the AI Provenance tab, the Decision
    # Report and the job report's drawing-pack section — every document the estimator works
    # from names those parts, and they decide what the customer hears.
    exc_block = ""
    # A COMMERCIAL EXCLUSION IS DIFFERENT, AND IT IS DECLARED. Packaging and delivery held
    # at £0 on the sheet are not in this price; a quotation that says nothing about them
    # promises them. One line, in the words of the record, not the engine's findings.
    if _packing == "unpriced":
        exc_block = """
      <div class="inc">
        <h3>Not included in this price</h3>
        <ul>
          <li>Packaging and delivery are not included in this price</li>
        </ul>
      </div>"""

    # THE DRAFT BANNER IS NOT CUSTOMER-FACING EITHER, AND IS NO LONGER RENDERED HERE.
    #
    # It read, in full, across the top of a quotation:
    #
    #   DRAFT — not for issue · 2 prices missing + 1 market figure to replace + 3
    #   manufacturing decisions + 1 indicative rate to verify: PACKAGING, DELIVERY,
    #   7332-01-101, 7332-01-002, 7332-01-003, 7332-01-004, 7332-01-005, 7332-01-007,
    #   7332-01-008, PLATERFREIGHT
    #
    # James: "we know that the estimator can make amendments to the s/sheet and regenerate
    # the quote and it will be sent out on the back of their changes, so we don't want
    # anything which makes it look like it's not a quote for a CLIENT, because after their
    # changes, it will be."
    #
    # That is the whole argument, and it is about WHEN this page is true rather than about
    # how frank to be. The banner describes the moment the engine finished, and the document
    # is issued at a later moment — after an estimator has priced the two missing lines and
    # settled the decisions on the sheet, and regenerated. Every word of it is then false,
    # and it is false on the one document a customer reads. Worse, it names SDI's internal
    # part numbers and its open questions to that customer.
    #
    # It is exactly the reasoning already applied twice on this page: to the invariant
    # banner above, and to the "Not included in this price" gap list below it. The engine's
    # findings are the estimator's to act on; what a customer is told is the estimator's
    # decision and their wording.
    #
    # THE TALLY IS NOT LOST, which is the condition for removing it. outstanding_summary is
    # printed by the covering e-mail subject, the job report banner, the AI Explanation and
    # the Decision Report, and every open row is shaded on the Estimate sheet's OUTSTANDING
    # ESTIMATOR INPUTS block — so the person who can settle these sees all of them, on the
    # documents they work from, before the quote is sent. The customer is not shown the
    # workings. A test holds all four of those surfaces, so this cannot become silence.
    draft_block = ""  # retained for the fixture that asserts it stays empty

    ga_block = ""
    if ga_uri:
        ga_block = f"""
      <div class="unit-view">
        <h3 class="ref-h">Drawing reference</h3>
        <img src="{ga_uri}" alt="{_esc(product)} — general arrangement" />
        <div class="unit-cap">General arrangement · {_esc(job_number)}{(' ' + _esc(rev)) if rev else ''}</div>
      </div>"""

    # DRAWING NUMBER FIRST. It is the reference the customer and the shop both quote back,
    # and on the previous layout it appeared only as "Job <n>" beneath a headline naming
    # the folder. Revision belongs next to it — a quotation against the wrong revision is
    # the expensive kind of mistake.
    meta_bits = f"Drawing <b>{_esc(job_number)}</b>"
    if rev:
        meta_bits += f" &nbsp;·&nbsp; {_esc(rev)}"
    if qty:
        # "1 units" on a client page reads as nobody having looked at it.
        meta_bits += f" &nbsp;·&nbsp; {_num(qty)} unit{'' if _num(qty) == '1' else 's'}"
    meta_bits += f" &nbsp;·&nbsp; {_esc(today)}"

    # When the drawing states no title we fall back to its number, and repeating it either
    # side of a dash reads as a fault rather than a shortage of information.
    # ── A MEASUREMENT IS NOT AN OFFER, SO IT HAS NO OFFER WINDOW ────────────────────
    #
    # James: "Drop 'Valid 30 days' on LLM-only. A measurement isn't an offer window. Keep
    # indicative."
    #
    # This is the one thing on the page that was a COMMITMENT rather than a figure. A price
    # marked indicative is a number somebody will check; "valid for 30 days" is a promise with
    # a date on it, and it was being made off a pack that one reader had seen. It is also the
    # line that survives a document being forwarded, because it reads as boilerplate and
    # boilerplate is what nobody re-reads.
    #
    # Everything else on the page stays identical to a full-run quote — that is the point of
    # the comparison, and the reason the red banner went. This is not a warning added back in
    # another form: it is the removal of a claim the run cannot support.
    from run_readers import run_was_llm_only
    _llm = run_was_llm_only(summary)
    # AND A DRAFT NO LONGER DECLARES ITSELF ONE HERE. It used to take the same route as the
    # LLM-only case and print "Basis: Draft — not for issue" in place of the offer window,
    # in the Basis row and again in the footer.
    #
    # That is the banner's argument in two smaller places, and removing the banner alone
    # would have left the quotation saying "not for issue" twice while looking otherwise
    # finished — the worst of both. The offer window is the estimator's to make: they amend
    # the sheet, regenerate, and send, and at that moment {VALID_DAYS} days is exactly what
    # SDI is offering.
    #
    # THE LLM-ONLY CASE IS UNTOUCHED, and it is a different fact. "Indicative — for internal
    # comparison" does not describe an unfinished estimate, it describes a pack read by one
    # reader that cannot size a folded part — a measurement, not an offer, which is why
    # James asked for the window to go and the word indicative to stay. No amount of
    # estimator work on the sheet turns that run into a full one.
    _validity_row = ("<tr><td>Basis</td><td>Indicative — for internal comparison</td></tr>"
                     if _llm else
                     f"<tr><td>Valid for</td><td>{VALID_DAYS} days</td></tr>")
    _validity_foot = ("Prices ex VAT, GBP. Indicative."
                      if _llm else
                      f"Prices ex VAT, GBP. Valid {VALID_DAYS} days from quotation date.")
    # "to be priced" is the estimator's instruction, not the customer's business — the same
    # tell as the draft banner, in the packing row. What the customer needs is the scope:
    # this price does not cover packaging and delivery.
    _packing_row = ("Not included in this price"
                    if _packing == "unpriced" else "Boxed for transport")
    # The run's own identity, so "which engine run produced this quote" is checkable.
    _run_foot = ""
    if isinstance(summary, dict) and summary.get("run_id"):
        _run_foot = (f"<br>Ref {_esc(str(summary.get('run_id')))} · qty "
                     f"{_esc(str(summary.get('assumed_job_quantity') or summary.get('quantity') or 1))}")

    _lead_open = (
        f"Manufactured to drawing {_esc(job_number)}{(' ' + _esc(rev)) if rev else ''}. "
        if str(product).strip() == str(job_number).strip() else
        f"{_esc(product)} — manufactured to drawing {_esc(job_number)}"
        f"{(' ' + _esc(rev)) if rev else ''}. ")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{_release_meta}
<title>Quotation {_esc(job_number)} — {_esc(product)}</title>
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
  /* The customer block is the logo, not a labelled field: a caption above the embedded
     image threw its alignment out on any logo whose aspect ratio differed from the one the
     offset was tuned against, and a customer's own mark needs no caption saying whose it
     is. Flex centring replaces the fixed offset, so a tall logo and a wide one both sit
     level with the SDI mark. */
  .head .cust {{ text-align:right; display:flex; align-items:center;
                 justify-content:flex-end; min-height:44px; }}
  .head .cust img {{ max-height:56px; width:auto; display:block; }}
  /* WHO PRODUCED THIS, BETWEEN WHOSE IT IS AND WHO IT IS FOR.
     The letterhead carried SDI's mark and the customer's and nothing between them, so a
     quote gave no sign of what produced it. Set in the portal's own two-line lockup so the
     page and the document read as one system.
     The accent is NOT --sdi-yellow: that is tuned for the dark band, and #F5D947 on white
     is barely a colour. This is the same gold already used for the provisional banner's
     rule, which was chosen to survive being printed in black and white. */
  .head .mark {{ flex:1; text-align:center; line-height:1.25; padding:0 8px; }}
  .head .mark .eyebrow {{ display:block; font-size:9.5px; letter-spacing:.18em;
                          text-transform:uppercase; color:var(--muted); }}
  .head .mark .name {{ display:block; font-size:15px; font-weight:600; color:var(--sdi-ink);
                       white-space:nowrap; }}
  .head .mark .name b {{ color:#B8860B; font-weight:600; }}
  /* On a narrow page the three-up header stacks; the mark goes first out of the middle
     rather than squeezing the two logos it sits between. */
  @media (max-width:560px) {{ .head .mark {{ display:none; }} }}
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
  .estimator-action {{ margin:-14px 0 26px; font-size:13px; color:var(--muted); }}
{_print_block}
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
  <div class="sheet">{draft_block}
    <div class="head">
      <div class="sdi">{sdi_logo}</div>
      <div class="mark">
        <span class="eyebrow">SDI Intelligence</span>
        <span class="name">SDI Estimating <b>Intelligence</b></span>
      </div>
      <div class="cust">{cust_header}</div>
    </div>
    <div class="band">
      <h1>{_esc(product)}</h1>
      <div class="meta">{meta_bits}</div>
    </div>
    <div class="body">
      <p class="lead">{_lead_open}{_esc(material)}{(', ' + _esc(finish.lower())) if finish and finish!='As drawing' else ''}.</p>
      <div class="grid">
        <div class="spec">
          <h3>Specification</h3>
          <table>
            <tr><td>Material</td><td>{_esc(material)}</td></tr>
            <tr><td>Quantity</td><td>{_num(qty) if qty else '—'}</td></tr>
            <tr><td>Finish</td><td>{_esc(finish)}</td></tr>
            <tr><td>Packing</td><td>{_packing_row}</td></tr>
          </table>
        </div>
        <div class="spec">
          <h3>Commercial</h3>
          <table>
            <tr><td>Unit price (ex VAT · indicative)</td><td>{_unit_figure}</td></tr>
            <tr><td>Order quantity</td><td>{_num(qty) if qty else '—'}</td></tr>
            <tr><td>Quotation date</td><td>{_esc(today)}</td></tr>
            {_validity_row}
          </table>
        </div>
      </div>
      <div class="price-box">
        <div>
          <div class="u">Unit price</div>
          <div class="{_price_class}">{_unit_figure}</div>
          <div class="per">{_unit_caption}</div>
        </div>
        <div class="right">
          <div class="u">Order value</div>
          <div class="{_order_class}">{_order_figure}</div>
          <div class="per">{_order_caption}</div>
        </div>
      </div>{_pending_note}
      <div class="inc">
        <h3>What's included</h3>
        <ul>
{inc_items}
        </ul>
      </div>{exc_block}
    </div>{ga_block}
    <div class="foot">
      <div class="terms">
        <b>we.are.sdi</b> · Design-led manufacturer · Loughborough, UK<br>
        matt.evans@wearesdi.com · 0116 274 7040 · wearesdi.com
      </div>
      <div class="terms" style="text-align:right;">
        {_validity_foot}<br>
        wearesdi is the trading name of SDI Displays Ltd.{_run_foot}
      </div>
    </div>
  </div>
</body>
</html>"""


# THE PAGE CARRIES NO BANNER. THE FILENAME CARRIES THE MARK.
#
# There was a red block here — "LLM-ONLY MEASUREMENT RUN — NOT A QUOTATION", above the
# letterhead, ending "do not send it to a customer and do not quote its total". James removed
# it, and both of his reasons are structural rather than presentational:
#
#   THE COMPARISON. An LLM-only run exists to be held against a full one. Two documents that
#   differ by a 100mm red block at the top no longer differ only in their numbers, and the
#   numbers are the entire question. Printed side by side the banner also pushes the lower half
#   of a one-page quote off the sheet, so the run that is meant to be compared is the one that
#   cannot be read to the end. "the lower section is missing.. again.."
#
#   WHOSE DECISION IT IS. "The estimator takes responsibility. remove this sort of alarming
#   disclaimer." A document that tells a professional not to trust it is not adding a control;
#   it is declining to produce the artefact and hoping the reader supplies the judgement
#   anyway. Everyone in the room knows which button was pressed.
#
# WHAT REPLACES IT IS NOT NOTHING. The filename still says _quote_LLM-ONLY.html, which is how a
# file is identified from a folder listing, an attachment box or a share — the places the wrong
# document actually gets picked up. And the job report says, in full and in its own section,
# which readers ran and which were switched off. The warning lives where somebody can act on
# it, not stamped across the thing being measured.


def generate_quote_files(json_path: str, out_dir: Optional[str] = None, job_stem: Optional[str] = None,
                         manual_workbook: Optional[str] = None, customer: Optional[str] = None) -> Optional[str]:
    jp = Path(json_path)
    summary = json.loads(jp.read_text(encoding="utf-8"))

    # ── NO CUSTOMER QUOTE OFF A MEASUREMENT RUN ──────────────────────────────────────
    #
    # THE DOCUMENT THIS PRODUCES IS THE MOST DANGEROUS FILE THIS ENGINE WRITES. It carries
    # the SDI letterhead, a unit price, "valid 30 days" and a "what's included" list of
    # laser, weld, powder and pack. On the 10575-02 LLM-only run it did all of that for a
    # total the same job's Decision Report described, in capitals, as INSUFFICIENT DATA —
    # DO NOT QUOTE FROM THIS TOTAL. The word "indicative" appeared; "read by a language
    # model alone" did not. James's verdict on seeing it: "Do not send this."
    #
    # main.py ALREADY BELIEVED THIS GATE EXISTED. Its call site reads:
    #     # None = deliberately suppressed by the credibility gate, which has
    #     # already said why. Do not print a path that does not exist.
    # That comment has been there through every run; the function it describes always wrote
    # the file and always returned a path. A safety documented at the call site and absent
    # from the callee is worse than no safety, because it stops anyone looking.
    #
    # STAMPED AND WRITTEN, NOT SUPPRESSED.
    #
    # This withheld the file. James overruled it, and the reason is the one that matters:
    # "we absolutely need to generate the same documents... everyone knows it's an LLM only
    # run but we still run them." An LLM-only run exists to be COMPARED against a full one,
    # and a comparison where the two runs produce different sets of documents is not a
    # comparison. Withholding the quote also hides the very thing being measured — what a
    # customer-facing document would have said off a one-reader BOM.
    #
    # So it is marked instead, in the two places a file can be identified without opening it
    # and reading to the end:
    #   the FILENAME  — ..._quote_LLM-ONLY.html, so it is distinguishable on the share, in a
    #                   folder listing, and in an email attachment box
    #   the FIRST THING ON THE PAGE — above the letterhead, not below the total
    #
    # BOTH SIGNALS FOR THE RUN, because this is also a CLI entry point run against a JSON long
    # after the process that made it has gone: the environment answers for the run in flight,
    # the summary key answers for every reader afterwards.
    _llm_only = bool(summary.get("llm_only")) or (
        os.environ.get("SDI_LLM_ONLY", "").strip().lower() in {"1", "true", "yes", "on"})

    stem = job_stem or summary.get("job_output_stem") or jp.stem
    out_dir_p = Path(out_dir) if out_dir else jp.parent
    # ── THE ESTIMATOR'S OWN DECISION, PICKED UP HERE ────────────────────────────────
    #
    # The commercial inputs and the release authorisation are a PERSON'S record and outlive
    # the run they were made about, so they do not live in the summary — the engine rewrites
    # that whole on every estimate. They sit beside the deliverables and are merged in at the
    # one point a quote is built. See `release_record`.
    apply_to_summary(summary, out_dir_p, stem)
    # THE AUDIENCE IS THE RECORD'S TO DECIDE, and this asks rather than assuming: a caller
    # that wanted the customer document and cannot have one gets the portal view, because
    # generating nothing was never the answer.
    _releasable = bool(quote_state(summary).get("customer_releasable"))
    html_str = build_quote_html(summary, job_stem=stem,
                                manual_workbook=manual_workbook,
                                customer=customer)
    if _llm_only:
        print("   [deliverables] client quote written. This run read the pack with the vision "
              "model alone — the page says so in its Basis row, and section 4.1 of the job "
              "report names which readers ran.", flush=True)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\- ]", "", str(stem)).strip() or "quote"
    # ── THE NAME SAYS WHETHER IT MAY GO OUT, AND NOTHING ELSE ───────────────────────
    #
    # James Gray, 22 Sep 2026: "WHY IS THE filename also LLM ONLY.. we need to stop making
    # decisions like this. we know quotes won't go out without being checked."
    #
    # `_quote_LLM-ONLY.html` was the same instinct as the six warning blocks that came off
    # this page, moved into the filename: labelling a document with what is imperfect about
    # it, on the assumption somebody will attach it unread. They will not — a quote is
    # checked before it is sent, and the run that produced it is named in the page's own
    # Basis row and in section 4.1 of the report. A third place to say it is friction, not
    # safety.
    #
    # WHAT THE NAME STILL CARRIES IS THE ONE THING IT IS FOR: whether this file may reach a
    # customer. `_quote_PORTAL.html` is not a defensive label, it is the export gate —
    # "email attachment, print/share disabled while customer_releasable is false" — and the
    # way an unreleased quote goes out is that somebody attaches it from a folder listing. So
    # a released quote is `_quote.html` and an unreleased one is not, whichever readers ran.
    out_path = out_dir_p / (f"{safe}_quote.html" if _releasable
                            else f"{safe}_quote_PORTAL.html")
    out_path.write_text(html_str, encoding="utf-8")
    return str(out_path)


def main() -> None:
    """The CLI, which goes through `generate_quote_files` like everything else.

    IT DID NOT, AND THAT WAS A HOLE. It called `build_quote_html` and wrote the result to
    `<stem>_quote.html` unconditionally — so a portal working copy regenerated from the
    command line landed on the share under the RELEASED document's name, and the release
    model's naming rule was true of every path but this one. Two files that differ only in
    what is inside them is exactly the failure `_quote_PORTAL.html` exists to prevent.

    The FILENAME is the engine's to choose, so `--out` became `--out-dir`.
    """
    ap = argparse.ArgumentParser(description="Generate a we.are.sdi client quotation HTML from a summary JSON.")
    ap.add_argument("--json", required=True, help="Summary JSON path")
    ap.add_argument("--out-dir", dest="out_dir",
                    help="Folder to write into (default: beside the JSON). The FILENAME is "
                         "the engine's, because it says which document this is.")
    a = ap.parse_args()
    print(f"Wrote quote: {generate_quote_files(a.json, out_dir=a.out_dir)}")


if __name__ == "__main__":
    main()
