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


# Header-word SYNONYMS per column. The BOM header varies across SDI title-block
# templates (2013 "PartNo"/"ITEM NO." vs 2025 "DWG NO."/"ITEM"), and a designer may
# use another variant. We match each column on a synonym set rather than one exact
# word, so the deterministic reader covers anticipatable format variation. The FIRST
# word in a row whose normalised text is in a set anchors that column.
_HDR_ITEM = {"ITEM", "ITEMNO", "ITEM NO", "NO", "POS", "POSITION", "PART ITEM"}
_HDR_CODE = {"DWG", "DWG NO", "DWGNO", "PARTNO", "PART NO", "PART", "PART NUMBER",
             "PARTNUMBER", "DRAWING", "DRAWING NO", "REF", "PART REF"}
_HDR_DESC = {"DESCRIPTION", "DESC", "TITLE", "NAME", "PART DESCRIPTION"}
_HDR_QTY = {"QTY", "QTY.", "QUANTITY", "QUANT", "QTY REQD", "QTY REQ", "REQD"}


def _hdr_norm(t: str) -> str:
    return t.upper().replace(".", "").strip()


def _header_from_row(ri: int, row: List[dict]) -> Optional[Dict[str, Any]]:
    """If this single clustered row is a BOM header, return {index, top, anchors}; else None.

    Column headers are matched against SYNONYM SETS (see _HDR_*), so this reads
    both the 2013 template (ITEM NO. / PartNo / Description / QTY.) and the 2025
    one (ITEM / DWG NO. / DESCRIPTION / QTY.) with the same primitive. We keep the
    raw x0 of each matched column; the row parser uses these anchors (not fixed
    boundaries) so it stays robust to long descriptions and stray grid-labels/notes.

    A row qualifies as the header if it carries an ITEM-like word, a DESCRIPTION-like
    word AND a QTY-like word (the three that are always present); the CODE column
    (DWG/PartNo) is located if present but its synonym set is broad.
    """
    norms = [( _hdr_norm(w["text"]), w["x0"] ) for w in row]
    norm_texts = {n for n, _ in norms}
    # Also consider two-word combinations (e.g. "ITEM" + "NO", "DWG" + "NO",
    # "PART" + "NO") so multi-token headers match the synonym sets.
    def _has(colset):
        if norm_texts & colset:
            return True
        toks = [n for n, _ in norms]
        for i in range(len(toks) - 1):
            if f"{toks[i]} {toks[i+1]}" in colset:
                return True
        return False

    if not (_has(_HDR_ITEM) and _has(_HDR_DESC) and _has(_HDR_QTY)):
        return None

    anchors: Dict[str, float] = {}
    # Assign the FIRST word matching each column set as that column's x-anchor.
    for norm, x in sorted(norms, key=lambda p: p[1]):
        if "item" not in anchors and (norm in _HDR_ITEM):
            anchors["item"] = x
        elif "code" not in anchors and (norm in _HDR_CODE):
            anchors["code"] = x
        elif "desc" not in anchors and (norm in _HDR_DESC):
            anchors["desc"] = x
        elif "qty" not in anchors and (norm in _HDR_QTY):
            anchors["qty"] = x

    # item, desc, qty required; code (DWG/PartNo) may be absent — synthesise midway.
    if not all(k in anchors for k in ("item", "desc", "qty")):
        return None
    if "code" not in anchors:
        anchors["code"] = (anchors["item"] + anchors["desc"]) / 2.0
    # anchors must be in sane left-to-right order
    if not (anchors["item"] <= anchors["code"] <= anchors["desc"] < anchors["qty"]):
        return None

    return {"header_row_index": ri, "header_top": row[0]["top"], "anchors": anchors}


def _find_header(rows: List[List[dict]]) -> Optional[Dict[str, Any]]:
    """The FIRST BOM header on the page (kept for single-table callers)."""
    for ri, row in enumerate(rows):
        h = _header_from_row(ri, row)
        if h:
            return h
    return None


def _find_all_headers(rows: List[List[dict]]) -> List[Dict[str, Any]]:
    """EVERY BOM header on the page — so a page carrying a main BOM PLUS a fixings/
    hardware sub-table is read in full, not just the first table. Belt-and-braces so
    the deterministic path covers multi-table pages rather than leaning on the vision
    backstop. Headers are returned top-to-bottom."""
    out: List[Dict[str, Any]] = []
    for ri, row in enumerate(rows):
        h = _header_from_row(ri, row)
        if h:
            out.append(h)
    return out


def _parse_row(row: List[dict], anchors: Dict[str, float]) -> Optional[Dict[str, str]]:
    """Parse one row into item/code/desc/qty using the header x-ANCHORS.

    Robust to:
      - grid-labels ('A'/'B') and edge-notes outside the table's x-extent
        (we keep only words between just-left-of-ITEM and just-right-of-QTY);
      - long descriptions that drift toward the qty column (qty is identified as
        the RIGHTMOST bare small-integer in the qty region, not by a fixed x).
    Returns None if the row has no valid item+qty (i.e. not a BOM data row).
    """
    item_x, code_x, desc_x, qty_x = (
        anchors["item"], anchors["code"], anchors["desc"], anchors["qty"],
    )
    left_bound = item_x - 25.0            # exclude far-left grid labels / notes
    right_bound = qty_x + 40.0            # exclude far-right grid labels
    inside = sorted(
        ((w["x0"], w["text"]) for w in row if left_bound <= w["x0"] <= right_bound)
    )
    if not inside:
        return None

    item_code_bound = (item_x + code_x) / 2.0
    code_desc_bound = (code_x + desc_x) / 2.0
    qty_region_min = (desc_x + qty_x) / 2.0 - 30.0   # left edge of the qty region

    # QTY = rightmost bare small-integer sitting in the qty region
    qty_word = None
    for x, t in reversed(inside):
        if t.isdigit() and 1 <= int(t) <= 250 and x >= qty_region_min:
            qty_word = (x, t)
            break
    if qty_word is None:
        return None

    # ITEM = leftmost bare small-integer in the item region
    item_word = None
    for x, t in inside:
        if x < item_code_bound and t.isdigit() and 1 <= int(t) <= 99:
            item_word = (x, t)
            break
    if item_word is None:
        return None

    code = [t for x, t in inside if item_code_bound <= x < code_desc_bound]
    desc = [t for x, t in inside if code_desc_bound <= x < qty_word[0]]
    return {
        "item": item_word[1],
        "code": " ".join(code).strip(),
        "desc": " ".join(desc).strip(),
        "qty": qty_word[1],
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


def survey_page(page) -> Dict[str, Any]:
    """What this reader SAW on a page, as distinct from what it managed to read.

    read_bom_from_page answers one bit — a BOM or None — and returns None from six
    different places that mean entirely different things. "This is a plain detail sheet"
    and "there is a parts list here whose header row I could see and whose rows I could
    not parse" arrive as the same value. The second is the single best reason to spend a
    vision call on a page, and it was indistinguishable from the best reason not to.

    Returns:
        has_text      the page yielded words at all. False = raster/scanned sheet.
        header_found  a full BOM header row (item + description + qty, in order).
        header_words  header VOCABULARY is present even though no header row qualified —
                      the words are there but the layout defeated the row clustering.
        rows_parsed   how many data rows came out under those headers.

    Deliberately reuses _HDR_* — the synonym sets the header matcher itself uses — so
    "does this page talk like a parts list" cannot drift away from "does this page parse
    as a parts list". Two lists is how one of them silently stops recognising NO OFF.
    """
    verdict = {"has_text": False, "header_found": False, "header_words": False,
               "rows_parsed": 0}
    try:
        words = page.extract_words(x_tolerance=1.5, y_tolerance=1.5) or []
    except Exception:
        return verdict
    if not words:
        return verdict
    verdict["has_text"] = True

    norms = {_hdr_norm(w["text"]) for w in words}
    hits = sum(1 for colset in (_HDR_ITEM, _HDR_CODE, _HDR_DESC, _HDR_QTY)
               if norms & colset)
    # Three of the four column families. Two is too easy: _HDR_CODE contains "REF" and
    # "PART", and _HDR_ITEM contains "NO", all of which appear in ordinary title blocks.
    verdict["header_words"] = hits >= 3

    rows = _cluster_rows(words)
    headers = _find_all_headers(rows)
    verdict["header_found"] = bool(headers)
    if headers:
        bom = read_bom_from_page(page)
        verdict["rows_parsed"] = len((bom or {}).get("rows") or [])
    return verdict


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
    headers = _find_all_headers(rows)
    if not headers:
        return None

    parent = _title_block_dwg_no(words)

    data_rows: List[Dict[str, Any]] = []
    seen = set()  # page-wide dedup across every table on the page
    # Walk each header's table independently. A page can carry a main BOM PLUS a
    # fixings/hardware sub-table; each restarts its own item sequence at 1, so the
    # contiguity guard's _max_item_seen MUST reset per table or the second table's
    # item 1 gets rejected as "backwards". Rows belong to a table when they sit
    # BELOW that header and ABOVE the next header (or the page bottom for the last).
    for hi, header in enumerate(headers):
        anchors = header["anchors"]
        header_top = header["header_top"]
        next_top = headers[hi + 1]["header_top"] if hi + 1 < len(headers) else float("inf")
        _max_item_seen = 0
        for row in rows:
            top = row[0]["top"]
            if top <= header_top or top >= next_top:
                continue  # outside this table's vertical band
            cols = _parse_row(row, anchors)
            if cols is None:
                continue  # not a BOM data row (no valid item+qty in the table extent)
            item, code, desc, qty = cols["item"], cols["code"], cols["desc"], cols["qty"]

            # GUARD 1 — item contiguity: real BOM items are a monotonic 1..N sequence.
            # A row whose item number is <= one already accepted is a duplicate/backwards
            # value — almost always sheet-edge grid NUMBERS (2..8) that survived the x-extent
            # filter because they look like integers. Reject it.
            if int(item) <= _max_item_seen:
                continue

            # GUARD 2 — numeric-noise desc: grid-number noise builds a row like
            # code='' desc='6 7' (bare integers). A genuine sparse/thin row has an EMPTY
            # desc, never a numbers-only one. Reject empty-code rows whose desc is purely
            # numeric/punctuation (no alphabetic run).
            _has_alpha = bool(re.search(r"[A-Za-z]{2,}", desc))
            _numeric_noise = bool(desc) and not _has_alpha and bool(re.match(r"^[\d\s.\-]+$", desc))
            if not code.strip() and _numeric_noise:
                continue

            _max_item_seen = int(item)
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
        # item 3 = keyhole pem qty 2. Its DESCRIPTION is in a drawing note
        # ("KEYHOLE PEM SIZE REQUIRED"), NOT the table cell, so a deterministic
        # table reader correctly yields item 3 / qty 2 with a thin (blank) desc.
        # We match on item+qty here; the note-desc is a separate enrichment step.
        ("3", "", 2),
    ],
    # ---- 1282 Milwaukee Wall Bay (2013 template, "ITEM NO./PartNo" header) ----
    # Known-good BOM extracted independently (Grok/pdf_browse) across the file set.
    # Note codes carry hyphen/space variants on the drawing (e.g. "1450 - GA",
    # "1453-GA C", "1455-C GA") which _normalize_bom_code repairs to canonical form.
    "1448-GA": [
        ("1", "1448-01", 1), ("2", "1448-02", 1),
    ],
    "1455-C-GA": [
        ("1", "1455-C-101", 1), ("2", "1455-C-005", 1),
        # item 3 = ELECTRICS 50cm LOOM (bought-in, no drawing code); item 4 = FIXING
        # dome rivet x2. Match item+qty; the code column is a commodity spec here.
        ("3", "", 1), ("4", "", 2),
    ],
    # The top-level GA parent token in 1282's title block — confirm its 7 lines.
    "1282-GA": [
        ("1", "1448-GA", 2), ("2", "1449-01C", 3), ("3", "1450-GA", 1),
        ("4", "1453-GA-C", 1), ("5", "2621-01C", 1), ("6", "3886-GA", 2),
        ("7", "1455-C-GA", 1),
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
            token_ok = (exp_tok == "") or (exp_tok in gtok) or (exp_tok in gdesc)
            if gi == exp_item and token_ok:
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
        if not any(gi == ei and (et == "" or et in gtok or et in gdesc) for ei, et, eq in expected):
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

    if args.pdf:
        pdf_paths = [args.pdf]
    else:
        pdf_paths = find_pdf(args.pdf_dir)
    if not pdf_paths:
        print(f"No PDF in {args.pdf_dir}")
        sys.exit(1)

    print("=" * 78)
    print(f"PHASE 1 BOM READER (extract_words + x-columns)")
    print(f"Scanning {len(pdf_paths)} PDF(s) in: {args.pdf_dir}")
    print(f"Reused bom_table_extractor logic: {_REUSED}")
    print("=" * 78)

    boms: List[Dict[str, Any]] = []
    for pdf_path in pdf_paths:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for pi, page in enumerate(pdf.pages):
                    bom = read_bom_from_page(page)
                    if bom:
                        bom["page_index"] = pi
                        bom["pdf_name"] = os.path.basename(pdf_path)
                        boms.append(bom)
        except Exception as exc:
            print(f"  [skip] {os.path.basename(pdf_path)}: {exc}")

    print(f"\nScanned {len(pdf_paths)} file(s). Found {len(boms)} BOM table(s).\n")

    all_ok = True
    checked = 0
    for bom in boms:
        parent = bom["parent"] or "(unknown parent)"
        print("#" * 78)
        print(f"FILE: {bom.get('pdf_name','?')}  PAGE {bom['page_index']}  PARENT: {parent}")
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
