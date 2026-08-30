#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_bom_vision_reader.py  —  PATH B (standalone): read the BOM with a VISION LLM.

This is the COVERAGE NET half of the dual-path BOM architecture. Path A (the
deterministic _bom_words_reader.py, extract_words + x-columns) is the auditable
base; Path B (this) renders each drawing page to an image and asks a vision LLM
to read the BOM — robust to ANY table format, so a novel layout can never cause
a SILENT MISS. This file PROVES Path B in isolation (verifies against the 12120
and 1282 known-good oracles) BEFORE any cache or merge is built.

Design commitments (agreed with JG):
  * VISION, not text — the model sees the layout, so it handles formats the
    deterministic reader has never seen.
  * SAME schema as Path A ({item_number, part_ref, description, quantity, kind,
    parent}) so the later merge compares like-for-like.
  * STRICT prompt — only what is VISIBLY in a BOM table; do NOT infer/invent.
    Mirrors the engine's "only cost what's on the drawing" rule inside the LLM path.
  * temperature=0 (+ page-hash cache, added in the next step) → stable, and on
    re-runs free. Here (proving stage) there's no cache yet; that's deliberate.
  * The Grok vision CALL is isolated in ONE function (call_vision_llm) so it can
    be swapped to match the existing vision_extractor.py client in a single place.

Render: PyMuPDF (fitz) — already a dependency (vision_extractor.py). 300 DPI,
long side capped, so A3 BOM text is readable without a huge payload.

Run (from C:\ClaudeVision\src so imports/keys resolve):
  C:\ClaudeVision\.venv\Scripts\python.exe _bom_vision_reader.py --pdf-dir "<folder>"
  optional: --dpi 300  --max-side 2000  --page N (single page)  --dump-image
"""
from __future__ import annotations
import argparse
import base64
import glob
import io
import json
import os
import threading
import re
import sys
import hashlib
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load C:\ClaudeVision\.env the same way the rest of the project does, so the
# XAI_API_KEY in .env is picked up automatically. A key already set in the shell
# still works (python-dotenv does not override existing env vars by default).
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass  # if python-dotenv isn't present, rely on the shell env var

# ----------------------------------------------------------------------------
# Oracles (same known-good sets used to prove Path A). Match on (item, token, qty)
# so minor description wording differences don't fail the check.
# ----------------------------------------------------------------------------
ORACLE = {
    "12120-01-GA": [
        ("1", "SA01", 1), ("2", "103", 1), ("3", "04M", 1),
        ("4", "THUM620", 4), ("5", "08M", 1), ("6", "FIXINGTBC", 2),
    ],
    "12120-01-SA01": [("1", "101", 1), ("2", "05M", 1)],
    "12120-01-101": [
        ("1", "02M", 1), ("2", "03M", 1), ("3", "PEM", 2), ("4", "CLINCH", 4),
    ],
    "12120-01-103": [
        ("1", "01M", 1), ("2", "06M", 1),
        # item 3 = keyhole pem qty 2. Its description ("KEYHOLE PEM SIZE REQUIRED")
        # is a NOTE, not the table cell - vision correctly returns item 3/qty 2 with
        # a blank desc (obeying the strict "blank if only in a note" prompt rule).
        # Match on item+qty, same as Path A's oracle.
        ("3", "", 2),
    ],
    # 1282 (2013 template) — the job where Path A only reached ~90%.
    "1282-GA": [
        ("1", "1448-GA", 2), ("2", "1449-01C", 3), ("3", "1450-GA", 1),
        ("4", "1453-GA-C", 1), ("5", "2621-01C", 1), ("6", "3886-GA", 2),
        ("7", "1455-C-GA", 1),
    ],
    "1448-GA": [("1", "1448-01", 1), ("2", "1448-02", 1)],
    "1455-C-GA": [
        ("1", "1455-C-101", 1), ("2", "1455-C-005", 1),
        ("3", "LOOM", 1), ("4", "RIVET", 2),
    ],
    # weldment 1455-C-101's own children (nested sub-BOM on its detail page)
    "1455-C-101": [
        ("1", "1455-C-001", 1), ("2", "1455-C-002", 1),
        ("3", "1455-C-003", 1), ("4", "1455-C-004", 1),
    ],
    # 3886 lower-leg sub-assembly (note the drawing's trailing-hyphen codes)
    "3886-GA": [
        ("1", "3886-01", 1), ("2", "3886-02", 1), ("3", "3886-03", 1),
        ("4", "FIXING", 2), ("5", "FIXING", 2),  # nutsert x2, glide x2
    ],
}


# ----------------------------------------------------------------------------
# Page rendering (fitz) — vectors re-rendered at target DPI, long side capped.
# ----------------------------------------------------------------------------
def render_page_to_png(pdf_path: str, page_index: int, dpi: int = 300,
                       max_side: int = 2000) -> bytes:
    import fitz  # PyMuPDF
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        zoom = dpi / 72.0
        # cap the long side: shrink zoom if the rendered page would exceed max_side
        rect = page.rect
        long_pts = max(rect.width, rect.height)
        px_long = long_pts * zoom
        if px_long > max_side:
            zoom = zoom * (max_side / px_long)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def count_pages(pdf_path: str) -> int:
    import fitz
    doc = fitz.open(pdf_path)
    try:
        return doc.page_count
    finally:
        doc.close()


# ----------------------------------------------------------------------------
# The vision LLM call — ISOLATED so it can be matched to vision_extractor.py.
# Uses the xAI OpenAI-compatible client (base_url=https://api.x.ai/v1). Swap the
# body of THIS function to match the existing project client if needed.
# ----------------------------------------------------------------------------
# Bump PROMPT_VERSION whenever _VISION_PROMPT changes — it is part of the cache
# key, so a prompt change correctly invalidates every cached page result.
PROMPT_VERSION = "v2"  # v2: BOM rows (unchanged rules) + part_details + spec_block enrichment

_VISION_PROMPT = """You are reading a single page of an engineering CAD drawing (SDI Displays).
Transcribe ONLY what is VISIBLY PRINTED on this page. NEVER infer, guess, invent, or
calculate. If a value is not printed on this page, use null (or an empty list).

PRIMARY TASK — the Bill of Materials (BOM) / parts table:
A BOM table has columns for an ITEM number, a PART NUMBER / DWG NO / PartNo, a DESCRIPTION,
and a QUANTITY (QTY). The header words vary between drawings.
- Transcribe ONLY rows that are visibly present in a BOM/parts table on THIS page.
- Do NOT infer, guess, invent, or add rows that are not in a table. If a description is
  only in a note (not the table cell), leave that row's description blank.
- Read part numbers and quantities EXACTLY as printed (including hyphens/spaces).
- Read the drawing's own DWG NO from the title block (bottom-right) — that is the PARENT
  assembly this table belongs to.
- If there is NO BOM/parts table on this page, return an empty "rows" list.

SECONDARY — if THIS sheet details ONE part, capture its PRINTED detail (else leave null):
material, thickness (mm), tube/section (e.g. "30 x 30 x 1.5mm"), cut length (mm), overall
size, weight in grams (ONLY a printed weight — NEVER computed), finish, hole count (only if
a count or hole table is printed), whether fold/bend lines are shown, and any verbatim
manufacturing callouts (e.g. "SEAM THIS FACE", "CHROME").

SECONDARY — the repeated notes/spec block, if present (else null): powder-coat micron
range, weld specification, tolerances, material grades, timber note.

Return ONLY valid JSON, no markdown, in EXACTLY this shape:
{
  "parent": "<title-block DWG NO, or null>",
  "rows": [
    {"item": "1", "part_code": "1448-GA", "description": "UPPER LEG ASSEMBLY", "qty": 2}
  ],
  "part_details": {
    "material": null, "thickness_mm": null, "tube_section": null, "cut_length_mm": null,
    "overall_size": null, "weight_g": null, "finish": null, "hole_count": null,
    "fold_or_bend": null, "process_notes": []
  },
  "spec_block": {
    "powder_micron": null, "weld_spec": null, "tolerances": null,
    "material_grades": [], "timber_note": null
  }
}
Fill part_details / spec_block ONLY from values printed on THIS sheet; any field not printed
stays null. NEVER compute weight, area, or cut length — transcribe a printed number or null.
"""


def call_vision_llm(png_bytes: bytes, model: str) -> str:
    """Send the page image to the vision LLM, return the raw text response.

    ISOLATED: to match the project's existing Grok vision client
    (vision_extractor.py), replace the client construction / call below. The
    contract is: bytes in (PNG) -> model's text response out (expected JSON).
    """
    from openai import OpenAI  # xAI is OpenAI-compatible

    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "XAI_API_KEY not found. Set it in C:\\ClaudeVision\\.env "
            "(XAI_API_KEY=xai-...) or in the shell ($env:XAI_API_KEY=\"xai-...\")."
        )

    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    b64 = base64.b64encode(png_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"

    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": _VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Cache: each unique (page image + model + prompt version) hits Grok ONCE ever.
# Stored as inspectable JSON in the cache dir. Re-runs load from cache (no call,
# deterministic). The raw response is stored too, so a PARSER change can re-parse
# the cached raw WITHOUT re-calling Grok — only a model/prompt change re-fetches.
# ---------------------------------------------------------------------------
def _default_cache_dir() -> str:
    """Where cached vision reads live. Derived from the installed tree, not from the
    path one machine happened to be checked out at: a hardcoded C:\\ClaudeVision means
    every re-run on any other machine pays for Grok again and silently gets nothing
    when the drive is absent."""
    try:
        import config
        return str(config.BASE_DIR / "cache" / "vision_bom")
    except Exception:
        return str(Path(__file__).resolve().parents[1] / "cache" / "vision_bom")


DEFAULT_CACHE_DIR = _default_cache_dir()


def _cache_key(png_bytes: bytes, model: str, prompt_version: str) -> str:
    h = hashlib.sha256()
    h.update(png_bytes)
    h.update(b"\x00")
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(prompt_version.encode("utf-8"))
    return h.hexdigest()


def _cache_path(cache_dir: str, key: str) -> str:
    return os.path.join(cache_dir, key + ".json")


def get_vision_bom_cached(png_bytes: bytes, model: str, pdf_name: str, page_index: int,
                          cache_dir: str, use_cache: bool = True,
                          refresh: bool = False, cache_only: bool = False) -> Dict[str, Any]:
    """Return {'parsed':..., 'raw_response':..., 'cache_hit':bool} for a page.

    - use_cache False  -> always call Grok, never read/write cache.
    - refresh True     -> ignore any existing entry, call Grok, overwrite it.
    - cache_only True  -> use an existing entry if there is one, but NEVER call Grok;
                          a miss returns parsed=None with 'skipped': True.
    - otherwise        -> load from cache if present; else call Grok and store.
    Re-parsing: on a cache hit we RE-PARSE the stored raw_response with the current
    parser (so parser fixes take effect for free), but do NOT re-call Grok.

    cache_only exists so the decision NOT to spend on a page never becomes a decision
    not to KNOW about it. The cache is keyed on the page image, so an already-read page
    costs nothing to read again — being selective about which pages are worth paying for
    should not throw away pages already paid for.
    """
    key = _cache_key(png_bytes, model, PROMPT_VERSION)
    path = _cache_path(cache_dir, key)

    if use_cache and not refresh and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                entry = json.load(fh)
            raw = entry.get("raw_response", "")
            parsed = parse_vision_response(raw)  # re-parse fresh (free parser fixes)
            return {"parsed": parsed, "raw_response": raw, "cache_hit": True}
        except Exception:
            pass  # corrupt/old cache entry -> fall through and re-fetch

    if cache_only:
        return {"parsed": None, "raw_response": "", "cache_hit": False, "skipped": True}

    # miss (or refresh / no-cache): call Grok
    raw = call_vision_llm(png_bytes, model=model)
    parsed = parse_vision_response(raw)

    if use_cache:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            entry = {
                "schema_version": 1,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "pdf_name": pdf_name,
                "page_index": page_index,
                "created_utc": datetime.datetime.utcnow().isoformat() + "Z",
                "raw_response": raw,
                "parsed": parsed,
            }
            # WRITTEN WHOLE OR NOT AT ALL. The key is a hash of the page IMAGE, so two
            # identical pages in a pack — a repeated title block, the same GA sheet in two
            # PDFs — share one cache file. Read sequentially that never mattered. Read
            # concurrently, two threads can be part-way through writing it while a third
            # reads, and json.dump into an open handle is not atomic.
            #
            # The existing reader catches a corrupt entry and re-fetches, so the worst case
            # was a wasted call rather than a wrong answer. os.replace is atomic on Windows
            # and POSIX alike, which removes the window instead of tolerating it.
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(entry, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as exc:
            print(f"  [cache write failed for {pdf_name} p{page_index}: {exc}]")

    return {"parsed": parsed, "raw_response": raw, "cache_hit": False}


# ----------------------------------------------------------------------------
# Parse the LLM JSON into the Path A schema.
# ----------------------------------------------------------------------------
def _strip_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    return s


def parse_vision_response(raw: str) -> Optional[Dict[str, Any]]:
    txt = _strip_fences(raw)
    # find the first {...} block if there's stray prose
    if not txt.startswith("{"):
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            txt = m.group(0)
    try:
        obj = json.loads(txt)
    except Exception:
        return None
    rows_in = obj.get("rows") or []
    parent = obj.get("parent")
    rows: List[Dict[str, Any]] = []
    for r in rows_in:
        item = str(r.get("item", "")).strip()
        code = str(r.get("part_code", "") or "").strip()
        desc = str(r.get("description", "") or "").strip()
        qty_raw = r.get("qty", None)
        try:
            qty = int(qty_raw)
        except Exception:
            continue  # a row without a clean integer qty isn't a usable BOM row
        rows.append({
            "item_number": item,
            "part_ref": code,
            "description": desc,
            "quantity": qty,
            "kind": "vision",       # provenance tag; classification happens in merge
        })
    # Capture the v2 enrichment (part_details + spec_block) if present. Additive: consumers that
    # only read "rows"/"parent" are unaffected. These are the LLM (Layer-3) view; the deterministic
    # drawing_facts (Layer 2) remains authoritative — this is the cross-check / no-DXF backup.
    part_details = obj.get("part_details") if isinstance(obj.get("part_details"), dict) else None
    spec_block = obj.get("spec_block") if isinstance(obj.get("spec_block"), dict) else None
    return {"parent": parent, "rows": rows, "part_details": part_details, "spec_block": spec_block}


# ----------------------------------------------------------------------------
# Verify against the oracle (same logic as Path A's verifier).
# ----------------------------------------------------------------------------
def _norm_code(s: str) -> str:
    """Display-normalise a code: upper, collapse spaces around hyphens, de-dupe
    hyphens. Used for readable output."""
    c = (s or "").upper()
    c = re.sub(r"\s*-\s*", "-", c)
    c = re.sub(r"-{2,}", "-", c)
    c = re.sub(r"\s+", " ", c).strip()
    return c


def _bare_code(s: str) -> str:
    """Match-normalise a code: uppercase, strip ALL separators (spaces, hyphens).
    So '1455-C GA', '1455-C-GA', '1455-C- GA', '1455 C GA' all become '1455CGA'.
    This makes code matching robust to the stray-space / hyphen-split variants
    SDI drawings produce (the class the bom_table_extractor docstring names).

    The rule itself lives in part_code_conventions, because the dual-path reconciler
    compares this reader's codes with the deterministic reader's and must go on doing
    so when this module is unavailable. Kept as a name here so callers of the vision
    reader are unaffected."""
    from part_code_conventions import bare_code
    return bare_code(s)


def _token_matches(exp_tok: str, part_ref: str, desc: str) -> bool:
    """An oracle token matches if it's empty (thin row), OR its bare form appears
    in the bare part code, OR (as a fallback) it appears in the description.
    Bare-code comparison ignores hyphen/space variation between code segments."""
    if exp_tok == "":
        return True
    et = _bare_code(exp_tok)
    pr = _bare_code(part_ref)
    if et and et in pr:
        return True
    # description fallback (for thin rows whose code cell was blank, e.g. keyhole)
    return _bare_code(exp_tok) in _bare_code(desc) or exp_tok.upper() in (desc or "").upper()


def _oracle_lookup(parent: Optional[str]):
    """Find an oracle for this parent, tolerant of spacing/hyphen/case variants
    (so '1282 - GA' matches oracle key '1282-GA', '3886-GA-' matches '3886-GA')."""
    if not parent:
        return None
    if parent in ORACLE:
        return ORACLE[parent]
    target = _bare_code(parent)
    for key, val in ORACLE.items():
        if _bare_code(key) == target:
            return val
    return None


def verify(parent: Optional[str], rows: List[Dict[str, Any]]):
    expected = _oracle_lookup(parent)
    if expected is None:
        return None, f"(no oracle for {parent})"
    got = [(r["item_number"], r.get("part_ref", ""), (r.get("description") or ""), r["quantity"]) for r in rows]
    details, ok = [], True
    for ei, et, eq in expected:
        match = None
        for gi, gpr, gdesc, gqty in got:
            if gi == ei and _token_matches(et, gpr, gdesc):
                match = (gqty == eq, gqty); break
        if match is None:
            ok = False; details.append(f"    MISSING item {ei} ({et} x{eq})")
        elif not match[0]:
            ok = False; details.append(f"    QTY WRONG item {ei} ({et}): got {match[1]}, want {eq}")
        else:
            details.append(f"    ok item {ei} ({et} x{eq})")
    for gi, gpr, gdesc, gqty in got:
        if not any(gi == ei and _token_matches(et, gpr, gdesc) for ei, et, eq in expected):
            details.append(f"    EXTRA item {gi} ({_norm_code(gpr) or gdesc[:18]} x{gqty}) — not in oracle")
    return ok, "\n".join(details)


def find_pdfs(pdf_dir: str) -> List[str]:
    # On Windows the filesystem is case-insensitive, so globbing *.pdf AND *.PDF
    # returns every file TWICE. Dedupe by normalised absolute path so each file is
    # processed once (prevents double-counting every BOM).
    hits = glob.glob(os.path.join(pdf_dir, "*.pdf")) + glob.glob(os.path.join(pdf_dir, "*.PDF"))
    seen, out = set(), []
    for p in hits:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key); out.append(p)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default=None, help="folder of PDFs to scan")
    ap.add_argument("--pdf", default=None, help="single PDF instead of a folder")
    ap.add_argument("--page", type=int, default=None, help="single page index (0-based)")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--max-side", type=int, default=2000)
    ap.add_argument("--model", default=os.environ.get("XAI_VISION_MODEL", "grok-4.3"))
    ap.add_argument("--dump-image", action="store_true", help="save rendered PNGs for inspection")
    ap.add_argument("--verbose", action="store_true", help="print the raw LLM response for each page")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help="where to store/read cached page results")
    ap.add_argument("--no-cache", action="store_true", help="do not read or write the cache (pure live calls)")
    ap.add_argument("--refresh", action="store_true", help="ignore existing cache, re-fetch every page from Grok, overwrite")
    ap.add_argument("--force-llm", action="store_true", help="alias for --refresh: force a fresh Grok read of ALL pages (use when drawings were reissued and you want certainty, not relying on the image-hash auto-detect)")
    ap.add_argument("--refresh-file", default=None, help="re-read only files whose name contains this substring (surgical: e.g. --refresh-file 1448 re-reads just the revised 1448 drawing, keeps the rest cached)")
    args = ap.parse_args()

    if not args.pdf and not args.pdf_dir:
        print("Provide --pdf <file> or --pdf-dir <folder>."); sys.exit(1)
    pdfs = [args.pdf] if args.pdf else find_pdfs(args.pdf_dir)
    if not pdfs:
        print(f"No PDF found in {args.pdf_dir or args.pdf}"); sys.exit(1)

    print("=" * 78)
    print("PATH B — VISION BOM READER (standalone proving run)")
    print(f"Model: {args.model}   DPI: {args.dpi}   max-side: {args.max_side}px")
    print(f"Files: {len(pdfs)}")
    print("=" * 78)

    # --force-llm is an explicit, human-readable alias for --refresh (re-read all).
    force_all = args.refresh or args.force_llm

    cache_hits = 0
    cache_misses = 0
    if args.no_cache:
        print("Cache: DISABLED (--no-cache) — every page is a live Grok call.")
    elif force_all:
        why = "--force-llm" if args.force_llm else "--refresh"
        print(f"Cache: FORCE FRESH ({why}) — re-reading ALL pages from Grok, overwriting {args.cache_dir}")
    elif args.refresh_file:
        print(f"Cache: ON, but FORCING fresh read of files matching '{args.refresh_file}' (rest from cache)")
    else:
        print(f"Cache: ON — {args.cache_dir} (each page hits Grok once ever; changed drawings auto-refresh via image hash)")

    all_boms = []
    for pdf_path in pdfs:
        # Decide if THIS file gets a forced fresh read: global force, or its name
        # matches --refresh-file. Otherwise normal cache behaviour (auto-refresh on
        # genuine content change via the image hash).
        this_file_refresh = force_all or (
            args.refresh_file is not None
            and args.refresh_file.lower() in os.path.basename(pdf_path).lower()
        )
        try:
            n = count_pages(pdf_path)
        except Exception as exc:
            print(f"  [skip] {os.path.basename(pdf_path)}: cannot open ({exc})"); continue
        pages = [args.page] if args.page is not None else range(n)
        for pi in pages:
            try:
                png = render_page_to_png(pdf_path, pi, dpi=args.dpi, max_side=args.max_side)
            except Exception as exc:
                print(f"  [skip] {os.path.basename(pdf_path)} p{pi}: render failed ({exc})"); continue
            if args.dump_image:
                out = f"_vis_{os.path.splitext(os.path.basename(pdf_path))[0]}_p{pi}.png"
                with open(out, "wb") as fh: fh.write(png)
            try:
                result = get_vision_bom_cached(
                    png, model=args.model, pdf_name=os.path.basename(pdf_path),
                    page_index=pi, cache_dir=args.cache_dir,
                    use_cache=not args.no_cache, refresh=this_file_refresh,
                )
            except Exception as exc:
                print(f"  [LLM error] {os.path.basename(pdf_path)} p{pi}: {exc}"); continue
            raw = result["raw_response"]
            parsed = result["parsed"]
            if result["cache_hit"]:
                cache_hits += 1
            else:
                cache_misses += 1
            if args.verbose:
                tag = "CACHE HIT" if result["cache_hit"] else "grok call"
                print(f"\n  ---- RAW RESPONSE ({os.path.basename(pdf_path)} p{pi}, image {len(png)} bytes, {tag}) ----")
                print(raw[:4000] if raw else "  (empty response)")
                print("  ---- END RAW RESPONSE ----\n")
            if args.verbose and parsed is not None:
                print(f"  parsed: parent={parsed.get('parent')!r}, rows={len(parsed.get('rows', []))}")
            if not parsed or not parsed["rows"]:
                continue  # no BOM on this page (expected for detail sheets)
            parsed["pdf_name"] = os.path.basename(pdf_path)
            parsed["page_index"] = pi
            all_boms.append(parsed)

    print(f"\nVision found {len(all_boms)} BOM table(s).\n")

    checked, all_ok = 0, True
    for bom in all_boms:
        parent = bom["parent"] or "(unknown)"
        print("#" * 78)
        print(f"FILE: {bom['pdf_name']}  PAGE {bom['page_index']}  PARENT: {parent}")
        print("#" * 78)
        for r in bom["rows"]:
            print(f"  item {r['item_number']:>2} | {r['part_ref']:<16} | {r['description'][:40]:<40} | qty {r['quantity']}")
        ok, detail = verify(bom["parent"], bom["rows"])
        if ok is None:
            print(f"\n  VERIFY: {detail}")
        else:
            checked += 1
            print(f"\n  VERIFY vs oracle: {'PASS' if ok else 'FAIL'}")
            print(detail)
            if not ok: all_ok = False
        print()

    print("=" * 78)
    print(f"Cache: {cache_hits} hit(s), {cache_misses} Grok call(s) this run.")
    print("=" * 78)
    print(f"RESULT: {checked} table(s) checked — "
          f"{'ALL PASS' if all_ok and checked else ('SOME FAIL' if checked else 'NONE CHECKED')}")
    print("=" * 78)
    if checked and all_ok:
        print("\nPath B (vision) matches the known-good oracles. It reads the BOM on both")
        print("the modern (12120) and 2013 (1282) templates. Ready to build the cache,")
        print("then the additive merge with Path A.")
    elif checked:
        print("\nSome tables mismatch — paste the output; we tune the prompt/DPI before merge.")


if __name__ == "__main__":
    main()
