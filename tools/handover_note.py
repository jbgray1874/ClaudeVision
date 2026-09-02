#!/usr/bin/env python3
r"""Every row of an estimate, explained, in one document an estimator can read.

WHY THIS EXISTS. The deliverables already say where each number came from — the report's
"where the bill of materials came from" and "how each operation was decided", the workbook's
AI Provenance tab. What none of them says is WHICH FILE AND WHICH PAGE. The workbook has no
page, sheet or drawing column in any tab, so the one question estimating always asks —
"where did you see that?" — cannot be answered from the pack that was sent, and gets asked
by email instead.

The page numbers are not missing from the engine. Every part record carries `pages` and
`page_roles`, and the run log says so out loud: "39/39 row(s) traced to a sheet; 39 carry
the drawing that owns them". They are simply dropped before anything is written out. So this
joins the workbook (the money, the materials, the routes) to the scan JSON (the pages) on the
part number, and prints one section per question an estimator actually asks.

HAND-BUILT ONCE, THEN GENERATED. This is a tool, not a template to fill in, because a
document typed out by hand is accurate for one run and stale for the next — and the numbers
on this job have moved between runs on identical drawings. What it prints is also the
specification for the report sections that will replace it: file and page on every BOM field
and every route row, and the price source beside every figure.

    python tools/handover_note.py --workbook <estimate.xlsx> --scan-json <12552-00.json>

The scan JSON is optional. Without it every other column still prints and the page column
says so, rather than the tool refusing to run — an estimator with most of the answer is
better off than one with none of it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import openpyxl
except ImportError:                                              # pragma: no cover
    raise SystemExit("openpyxl is required: pip install openpyxl")


# ── reading the workbook ─────────────────────────────────────────────────────

def _rows(ws, header_row: int = 1) -> List[Dict[str, Any]]:
    """A sheet as dicts keyed by its own header, blank rows dropped."""
    header = [str(ws.cell(header_row, c).value or "").strip()
              for c in range(1, ws.max_column + 1)]
    out: List[Dict[str, Any]] = []
    for r in range(header_row + 1, ws.max_row + 1):
        values = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
        if not any(v not in (None, "") for v in values):
            continue
        out.append({h: v for h, v in zip(header, values) if h})
    return out


def _sheet(wb, name: str) -> List[Dict[str, Any]]:
    return _rows(wb[name]) if name in wb.sheetnames else []


def _estimate_bom(wb) -> List[Dict[str, Any]]:
    """The Bill of Materials block on the Estimate sheet.

    Found by its own header text rather than a row number: the block moves whenever a job
    has more or fewer lines, and a hard-coded row would silently read the wrong band.
    """
    if "Estimate" not in wb.sheetnames:
        return []
    ws = wb["Estimate"]
    header_row = None
    for r in range(1, min(ws.max_row, 60) + 1):
        joined = " ".join(str(ws.cell(r, c).value or "") for c in range(1, 16)).lower()
        if "bill of materials" in joined and "part code" in joined:
            header_row = r
            break
    if header_row is None:
        return []
    out = []
    for r in range(header_row + 1, ws.max_row + 1):
        code = ws.cell(r, 8).value           # "Part code"
        text = ws.cell(r, 3).value           # the description column
        if not code and not text:
            if out:
                break                        # the block has ended
            continue
        out.append({
            "code": str(code or "").strip(),
            "text": str(text or "").strip(),
            "supplier": ws.cell(r, 9).value,
            "price": ws.cell(r, 10).value,
            "qty": ws.cell(r, 11).value,
        })
    return out


# ── reading the scan ─────────────────────────────────────────────────────────

def _scan_parts(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    """part number -> the scan record, for the pages the workbook does not carry."""
    if not path or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:                                            # noqa: BLE001
        return {}
    parts = ((data.get("manufacturing_writeup") or {}).get("parts")
             or data.get("parts") or [])
    return {str(p.get("part_number") or "").strip().upper(): p
            for p in parts if isinstance(p, dict)}


def _pages_of(record: Dict[str, Any]) -> str:
    pages = record.get("pages") or []
    roles = record.get("page_roles") or []
    if not pages:
        return "no sheet of its own"
    shown = ", ".join(f"p.{p}" for p in pages)
    return f"{shown} ({', '.join(str(r) for r in roles)})" if roles else shown


# ── the money's provenance ───────────────────────────────────────────────────

_INDICATIVE = ("grok", "llm", "xai", "indicative", "market")


def _price_source(bom_row: Dict[str, Any], provenance: Dict[str, Dict[str, Any]]) -> str:
    """Which book priced this line, in words an estimator can act on.

    THE FABRICATED PARTS ARE NOT UNPRICED. Every "-M" line carries a blank in the BOM's
    price column and says so in its own text — "costed in Sheet Steel below" — because sheet
    metal is priced from blank area on the Sheet Steel block, not per piece here. Reading the
    blank as "no rate" put fifteen made parts on the estimator's to-do list, which is both
    wrong and the fastest way to lose their trust in the rest of the document.

    A BLANK WITH NO EXPLANATION IS THE ONE THAT MATTERS, and it stays loud.
    """
    code = bom_row["code"].upper()
    text = str(bom_row.get("text") or "")
    supplier = str(bom_row.get("supplier") or "").strip()
    prov = provenance.get(code) or {}
    named = str(prov.get("Price Source") or prov.get("price_source") or "").strip()

    if "costed in sheet steel" in text.lower():
        return "priced by blank area on the Sheet Steel block, not per piece"
    if bom_row.get("price") in (None, ""):
        return "**NOT PRICED — needs a rate**"
    if any(token in supplier.lower() for token in _INDICATIVE):
        return f"AI market indication ({supplier}) — NOT A QUOTE, replace it"
    if any(token in named.lower() for token in _INDICATIVE):
        return f"AI market indication ({named}) — NOT A QUOTE, replace it"
    if supplier:
        return f"catalogue — {supplier}"
    if named:
        return named
    # Said plainly rather than guessed at. "config rate card" was asserted here for anything
    # unlabelled, which claimed a source for the bearing's GBP 1.42 that nothing in the
    # workbook actually states.
    return "source not named in the workbook — check AI Provenance"


# ── the document ─────────────────────────────────────────────────────────────

def _description(bom_row: Dict[str, Any]) -> str:
    """What the part IS, with the workbook's warnings stripped off the end.

    The Estimate sheet's description cell carries the part code, then the description, then
    any notice appended to it — "[AI ESTIMATE - INDICATIVE, NOT A QUOTE]", "MATERIAL
    UNPRICED: enter a unit rate for this item". Taking the LAST segment kept the notice and
    threw the description away, so the concrete slab appeared as "[AI ESTIMATE - INDICATIVE,
    NOT A QUOTE]" and the nylon washer as "MATERIAL UNPRICED" — a table naming no parts.
    Those notices are already carried, properly, by the price column beside it.
    """
    text = str(bom_row.get("text") or "")
    code = str(bom_row.get("code") or "")
    if code and text.upper().startswith(code.upper()):
        text = text[len(code):]
    for marker in ("[AI ESTIMATE", "—  MATERIAL UNPRICED", "— MATERIAL UNPRICED",
                   "MATERIAL UNPRICED", "— costed in Sheet Steel", "— costed in sheet steel"):
        cut = text.find(marker)
        if cut > 0:
            text = text[:cut]
    text = text.strip(" —-—\t")
    return (text[:60] or "—")


def _fmt(value: Any, dash: str = "—") -> str:
    if value in (None, ""):
        return dash
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def build(workbook: Path, scan_json: Optional[Path]) -> str:
    wb = openpyxl.load_workbook(workbook, data_only=True)
    scan = _scan_parts(scan_json)
    material = {str(r.get("Part") or "").upper(): r for r in _sheet(wb, "AI Material Detail")}
    provenance = {str(r.get("Part") or "").upper(): r for r in _sheet(wb, "AI Price Provenance")}
    routes = _sheet(wb, "Canonical Route")
    bom = _estimate_bom(wb)

    lines: List[str] = []
    add = lines.append

    add(f"# {workbook.stem}")
    add("")
    if not scan:
        add("> **Page numbers are unavailable** — no scan JSON was supplied, so the "
            "\"which sheet\" column reads *not supplied* throughout. Re-run with "
            "`--scan-json output/json/<job>.json` to fill it.")
        add("")

    # ── every BOM line ───────────────────────────────────────────────────────
    add("## Every line on the Bill of Materials")
    add("")
    add("| Part | Description | Qty | Unit £ | Where the £ came from | Material | Gauge | "
        "Blank | Which sheet |")
    add("|---|---|---|---|---|---|---|---|---|")
    for row in bom:
        code = row["code"].upper()
        mat = material.get(code, {})
        rec = scan.get(code, {})
        blank_l, blank_w = mat.get("Blank L"), mat.get("Blank W")
        blank = (f"{_fmt(blank_l)} × {_fmt(blank_w)}"
                 if blank_l or blank_w else "not a cut part")
        add(f"| {row['code'] or '—'} "
            f"| {_description(row)} "
            f"| {_fmt(row.get('qty'))} "
            f"| {_fmt(row.get('price'))} "
            f"| {_price_source(row, provenance)} "
            f"| {_fmt(mat.get('Material'))} "
            f"| {_fmt(mat.get('Gauge'), 'none — not sheet')} "
            f"| {blank} "
            f"| {_pages_of(rec) if rec else 'not supplied'} |")
    add("")

    # ── every route line ─────────────────────────────────────────────────────
    add("## Every operation, and who decided it")
    add("")
    add("| Part | Operation | Seq | Scope | Qty | Decided by | On what basis | Which sheet |")
    add("|---|---|---|---|---|---|---|---|")
    for row in routes:
        target = str(row.get("Target") or "").upper()
        rec = scan.get(target, {})
        add(f"| {_fmt(row.get('Target'))} "
            f"| {_fmt(row.get('Operation'))} "
            f"| {_fmt(row.get('Seq'))} "
            f"| {_fmt(row.get('Scope'))} "
            f"| {_fmt(row.get('Qty/unit'))} "
            f"| {_fmt(row.get('Source'))} "
            f"| {str(row.get('Reason') or '—')[:70]} "
            f"| {_pages_of(rec) if rec else 'not supplied'} |")
    add("")

    # ── what each sheet could be read for ────────────────────────────────────
    if scan:
        add("## Drawing quality, sheet by sheet")
        add("")
        add("| Sheet | Part | Material stated | Thickness stated | Finish stated | "
            "Geometry | What it could not give |")
        add("|---|---|---|---|---|---|---|")
        for code, rec in sorted(scan.items(),
                               key=lambda kv: ((kv[1].get("pages") or [999])[0], kv[0])):
            geom = rec.get("geometry_rollup") or {}
            reliability = ((geom.get("confidence") or {}).get("geometry_reliability"))
            missing = []
            if not rec.get("materials"):
                missing.append("material")
            if not rec.get("thicknesses_mm"):
                missing.append("thickness")
            if not rec.get("surface_finishes"):
                missing.append("finish")
            if not (geom.get("estimated_cut_length_mm") or 0):
                missing.append("cut length")
            add(f"| {_pages_of(rec)} | {code} "
                f"| {', '.join(str(m) for m in rec.get('materials') or []) or '**no**'} "
                f"| {', '.join(str(t) for t in rec.get('thicknesses_mm') or []) or '**no**'} "
                f"| {', '.join(str(f) for f in rec.get('surface_finishes') or []) or '**no**'} "
                f"| {_fmt(rec.get('geometry_source'))}"
                f"{f' ({reliability:.0%})' if isinstance(reliability, (int, float)) else ''} "
                f"| {', '.join(missing) or 'nothing — complete'} |")
        add("")

    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workbook", required=True, type=Path)
    ap.add_argument("--scan-json", type=Path,
                    help="output/json/<job>.json — supplies the page numbers the "
                         "workbook does not carry")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    text = build(args.workbook, args.scan_json)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
