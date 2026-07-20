#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_bom_words_reader.py  —  PHASE 1 standalone BOM reader (extract_words + x-columns).

WHY: the live Layer 1 reads the BOM via extract_tables(), which on 12120 collapses
the ruled table into one blob cell — the row-shape check fails, Layer 1 finds
nothing, and fixings fall through to the Layer 2 prose recogniser (which misses
the thumbscrew/keyhole entirely and defaults every qty to 1). The probe proved
extract_words()+x-column clustering recovers every BOM row perfectly. This reader
uses that primitive and REUSES bom_table_extractor's proven classify/clean logic.

It is STANDALONE — reads the PDF, prints the structured hierarchical BOM, and
verifies against Grok's known-good output. NO pipeline changes. If Phase 1 matches
the oracle on all tables, Phase 2 wires it in as Layer 1 (with the 1282 regression).

Column detection is from the HEADER row on each page (not hard-coded x), so it
adapts to other SDI drawings whose title-block template shifts the columns.

Run (from C:\ClaudeVision\src, so it can import bom_table_extractor):
    C:\ClaudeVision\.venv\Scripts\python.exe _bom_words_reader.py --pdf-dir "K:\Estimating\Completed\AI Estimating\Live Enquiry\12120-01-GA- DIGITAL TICKETING BRACKET"
"""
from __future__ import annotations
import argparse
import glob
import os
import re
import sys
from typing import Any, Dict, List, Optional

# ── Reuse bom_table_extractor's proven logic; fall back to inlined copies ──
try:
    from bom_table_extractor import _classify_part_ref, _normalize_bom_code, _clean  # type: ignore
    _REUSED = True
except Exception:
    _REUSED = False

    def _clean(cell: Any) -> str:
        return re.sub(r"\s+", " ", str(cell or "")).strip()

    def _normalize_bom_code(code: str) -> str:
        c = _clean(code).upper()
        c = re.sub(r"\s*-\s*", "-", c)
        c = re.sub(r"-{2,}", "-", c)
        c = c.strip("-")
        c = re.sub(r"\s+", "", c)
        return c

    def _classify_part_ref(raw: str):
        s = _clean(raw)
        joined = re.sub(r"\s*-\s*", "-", s).strip("-")
        if " " not in joined and re.match(r"^\d{3,}(?:-[A-Z0-9]+)+$", joined, re.I):
            return "drawing_ref", _normalize_bom_code(s)
        return "bought_in", s


# ── The new extraction primitive: words -> rows by x-columns ──

_DEBUG_PAGE = None  # set to True to dump BOM-band rows
HEADER_TOKENS = {"ITEM", "DWG", "NO.", "NO", "DESCRIPTION", "QTY", "QTY."}


def _cluster_rows(words: List[dict], y_tol: float = 3.0) -> List[List[dict]]:
    """Group words into rows by their 'top' coordinate (within y_tol)."""
    rows: List[List[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        placed = False
        for row in rows:
            if abs(row[0]["top"] - w["top"]) <= y_tol:
                row.append(w)
                placed = True
                break
        if not placed:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    return rows


def _find_header(rows: List[List[dict]]) -> Optional[Dict[str, Any]]:
    """Find the BOM header row and return the column x-boundaries derived from it.

    Header looks like: ITEM  DWG NO.  DESCRIPTION  QTY  — we take the x0 of ITEM,
    DWG, DESCRIPTION, QTY as column anchors and set boundaries midway between them.
    """
    for ri, row in enumerate(rows):
        texts = {w["text"].upper().rstrip(".") for w in row}
        if "ITEM" in texts and "DESCRIPTION" in texts and "QTY" in texts:
            anchors: Dict[str, float] = {}
            for w in row:
                t = w["text"].upper().rstrip(".")
                if t == "ITEM":
                    anchors["item"] = w["x0"]
                elif t == "DWG":
                    anchors["code"] = w["x0"]
                elif t == "DESCRIPTION":
                    anchors["desc"] = w["x0"]
                elif t == "QTY":
                    anchors["qty"] = w["x0"]
            if all(k in anchors for k in ("item", "code", "desc", "qty")):
                # boundaries midway between adjacent column anchors
                item_code = (anchors["item"] + anchors["code"]) / 2
                code_desc = (anchors["code"] + anchors["desc"]) / 2
                desc_qty = (anchors["desc"] + anchors["qty"]) / 2
                return {
                    "header_row_index": ri,
                    "header_top": row[0]["top"],
                    "bounds": {
                        "item_max": item_code,
                        "code_max": code_desc,
                        "desc_max": desc_qty,
                    },
                    "anchors": anchors,
                }
    return None


def _split_row_by_columns(row: List[dict], bounds: Dict[str, float]) -> Dict[str, str]:
    """Assign each word in a row to item/code/desc/qty by its x0 vs the boundaries."""
    item, code, desc, qty = [], [], [], []
    for w in row:
        x = w["x0"]
        if x < bounds["item_max"]:
            item.append(w["text"])
        elif x < bounds["code_max"]:
            code.append(w["text"])
        elif x < bounds["desc_max"]:
            desc.append(w["text"])
        else:
            qty.append(w["text"])
    return {
        "item": " ".join(item).strip(),
        "code": " ".join(code).strip(),
        "desc": " ".join(desc).strip(),
        "qty": " ".join(qty).strip(),
    }


def _title_block_dwg_no(words: List[dict]) -> Optional[str]:
    """The parent assembly = the DWG NO in the title block (a 12120-01-* token
    low on the page). We take the last such token (title block sits at bottom)."""
    cand = None
    for w in sorted(words, key=lambda w: w["top"]):
        t = w["text"].strip()
        if re.match(r"^\d{3,}-\d+-[A-Z0-9]+$", t, re.I):
            cand = t  # keep the lowest (last) match = title block
    return cand


def read_bom_from_page(page) -> Optional[Dict[str, Any]]:
    """Return {'parent': dwgno, 'rows': [...]} for a page that has a BOM table,
    else None. Uses extract_words()+x-columns (not extract_tables)."""
    try:
        words = page.extract_words(x_tolerance=1.5, y_tolerance=1.5) or []
    except Exception:
        return None
    if not words:
        return None

    rows = _cluster_rows(words)
    header = _find_header(rows)
    if _DEBUG_PAGE is not None and _DEBUG_PAGE:
        import sys as _sys
        print(f"    [DBG] page words={len(words)} rows={len(rows)} header={'FOUND' if header else 'NONE'}", file=_sys.stderr)
        if header:
            print(f"    [DBG] header_top={header['header_top']} bounds={header['bounds']}", file=_sys.stderr)
        for _r in rows:
            _top = _r[0]['top']
            # only dump rows in the BOM band (near/after header, before title block)
            if header and header['header_top'] - 5 <= _top <= header['header_top'] + 120:
                _cells = " | ".join(f"{_w['x0']:.0f}:{_w['text']}" for _w in _r)
                print(f"    [DBG] y={_top:.0f}: {_cells}", file=_sys.stderr)
    if not header:
        return None

    bounds = header["bounds"]
    header_top = header["header_top"]
    parent = _title_block_dwg_no(words)

    data_rows: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        top = row[0]["top"]
        if top <= header_top:
            continue  # skip header and anything above it
        cols = _split_row_by_columns(row, bounds)
        item, code, desc, qty = cols["item"], cols["code"], cols["desc"], cols["qty"]

        # a BOM data row: item is a small int, qty is a small int
        if not (item.isdigit() and 1 <= int(item) <= 99):
            continue
        if not (qty.isdigit() and 1 <= int(qty) <= 250):
            continue

        part_ref = code
        # keep sparse rows (item+qty present) even if code/desc thin — flag them
        thin = not (re.search(r"[A-Za-z]{2,}", desc) or re.search(r"[A-Za-z0-9]{2,}", part_ref))

        kind, code_or_spec = _classify_part_ref(part_ref) if part_ref else ("bought_in", "")
        key = (item, _clean(part_ref), qty)
        if key in seen:
            continue
        seen.add(key)

        data_rows.append({
            "item_number": item,
            "part_ref": _clean(part_ref),
            "part_number": code_or_spec if kind == "drawing_ref" else "",
            "description": desc,
            "quantity": int(qty),
            "kind": kind,
            "thin": thin,
        })

    if not data_rows:
        return None
    return {"parent": parent, "rows": data_rows}


# ── Grok known-good oracle (per-parent, code/desc-token -> qty) ──
# We compare on (item, a recognisable token, qty) so minor desc wording differences
# don't fail the check — the QUANTITIES and the presence of each item are what matter.
ORACLE = {
    "12120-01-GA": [
        ("1", "SA01", 1), ("2", "103", 1), ("3", "04M", 1),
        ("4", "THUM620", 4), ("5", "08M", 1), ("6", "FIXINGTBC", 2),
    ],
    "12120-01-SA01": [
        ("1", "101", 1), ("2", "05M", 1),
    ],
    "12120-01-101": [
        ("1", "02M", 1), ("2", "03M", 1),
        ("3", "PEM", 2), ("4", "CLINCH", 4),
    ],
    "12120-01-103": [
        ("1", "01M", 1), ("2", "06M", 1),
        ("3", "KEYHOLE", 2),
    ],
}


def _row_token(row: Dict[str, Any]) -> str:
    """A recognisable token for oracle matching: the part-code tail, or a desc word."""
    pr = (row.get("part_ref") or "").upper()
    if pr:
        # take the last hyphen segment for 12120-01-XXX, else the whole ref
        tail = pr.rsplit("-", 1)[-1] if "-" in pr else pr
        return tail
    return ""


def verify(parent: str, rows: List[Dict[str, Any]]):
    """Compare extracted rows for a parent against the oracle. Returns (ok, detail)."""
    expected = ORACLE.get(parent)
    if expected is None:
        return None, f"(no oracle for {parent})"
    got = []
    for r in rows:
        tok = _row_token(r)
        desc_up = (r.get("description") or "").upper()
        got.append((r["item_number"], tok, desc_up, r["quantity"]))

    details = []
    ok = True
    for exp_item, exp_tok, exp_qty in expected:
        # match by item number, then check the token appears in code-tail OR desc, and qty matches
        match = None
        for gi, gtok, gdesc, gqty in got:
            if gi == exp_item and (exp_tok in gtok or exp_tok in gdesc):
                match = (gqty == exp_qty, gqty)
                break
        if match is None:
            ok = False
            details.append(f"    MISSING item {exp_item} ({exp_tok} x{exp_qty})")
        elif not match[0]:
            ok = False
            details.append(f"    QTY WRONG item {exp_item} ({exp_tok}): got {match[1]}, want {exp_qty}")
        else:
            details.append(f"    ok item {exp_item} ({exp_tok} x{exp_qty})")
    # extra rows not in oracle?
    for gi, gtok, gdesc, gqty in got:
        if not any(gi == ei and (et in gtok or et in gdesc) for ei, et, eq in expected):
            details.append(f"    EXTRA item {gi} ({gtok or gdesc[:20]} x{gqty}) — not in oracle")
    return ok, "\n".join(details)


def find_pdf(pdf_dir):
    pdfs = glob.glob(os.path.join(pdf_dir, "*.pdf")) + glob.glob(os.path.join(pdf_dir, "*.PDF"))
    return sorted(pdfs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--pdf", default=None)
    args = ap.parse_args()

    try:
        import pdfplumber
    except ImportError:
        print("pdfplumber not importable in this venv.")
        sys.exit(1)

    pdf_path = args.pdf or (find_pdf(args.pdf_dir) or [None])[0]
    if not pdf_path:
        print(f"No PDF in {args.pdf_dir}")
        sys.exit(1)

    print("=" * 78)
    print(f"PHASE 1 BOM READER (extract_words + x-columns)")
    print(f"PDF: {os.path.basename(pdf_path)}")
    print(f"Reused bom_table_extractor logic: {_REUSED}")
    print("=" * 78)

    boms: List[Dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pi, page in enumerate(pdf.pages):
            global _DEBUG_PAGE
            _DEBUG_PAGE = pi in (2, 3)  # dump the two failing tables (101, 103 sheets)
            if _DEBUG_PAGE:
                import sys as _s; print(f'\n=== DEBUG PAGE {pi} ===', file=_s.stderr)
            bom = read_bom_from_page(page)
            if bom:
                bom["page_index"] = pi
                boms.append(bom)

    print(f"\nFound {len(boms)} BOM table(s).\n")

    all_ok = True
    checked = 0
    for bom in boms:
        parent = bom["parent"] or "(unknown parent)"
        print("#" * 78)
        print(f"PAGE {bom['page_index']}  PARENT: {parent}")
        print("#" * 78)
        for r in bom["rows"]:
            flag = "  [THIN]" if r.get("thin") else ""
            kind = r["kind"]
            code = r["part_number"] or r["part_ref"]
            print(f"  item {r['item_number']:>2} | {code:<16} | {r['description']:<40} | qty {r['quantity']} | {kind}{flag}")

        ok, detail = verify(bom["parent"], bom["rows"])
        if ok is None:
            print(f"\n  VERIFY: {detail}")
        else:
            checked += 1
            print(f"\n  VERIFY vs Grok oracle: {'PASS' if ok else 'FAIL'}")
            print(detail)
            if not ok:
                all_ok = False
        print()

    print("=" * 78)
    print(f"RESULT: {checked} table(s) checked against oracle — "
          f"{'ALL PASS' if all_ok and checked else ('SOME FAIL' if checked else 'NONE CHECKED')}")
    print("=" * 78)
    if all_ok and checked >= 4:
        print("\nPhase 1 extraction matches Grok's known-good output. The extract_words()")
        print("primitive recovers every BOM row + quantity. Ready to consider Phase 2")
        print("(wire in as Layer 1, with 1282 regression).")
    elif checked:
        print("\nMismatches above. The extraction needs adjustment before integration.")
        print("Paste the output and I'll tune the column/row logic.")


if __name__ == "__main__":
    main()
