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


# The Sheet Steel block's own columns, by position, from the template.
_STEEL_COLS = {"desc": 3, "qty": 5, "length": 6, "width": 7, "gauge": 8,
               "sheet_l": 9, "sheet_w": 10, "per_sheet": 11, "scrap": 12,
               "cost_per_part": 13, "internal_cut": 20, "rate_per_hour": 23}


def _steel_rows(wb) -> Dict[str, Dict[str, Any]]:
    """The Sheet Steel block, keyed by part number.

    WHERE A FABRICATED PART'S MONEY ACTUALLY IS. A "-M" line shows a dash in the BOM price
    column and says why in its own text — "costed in Sheet Steel below" — because sheet metal
    is priced from blank area, not per piece. An explanation that stops at "priced below"
    ends exactly where the estimator's question begins: how big, off what sheet, how many out
    of it, at what cost. This reads that block so the two halves can be shown together.

    Found by its header text, not a row number: the block moves with the size of the BOM
    above it, and a fixed row would silently read whatever had shifted into it.
    """
    if "Estimate" not in wb.sheetnames:
        return {}
    ws = wb["Estimate"]
    header_row = None
    for r in range(1, min(ws.max_row, 120) + 1):
        joined = " ".join(str(ws.cell(r, c).value or "") for c in range(1, 26)).lower()
        if "part length" in joined and "gauge" in joined and "part description" in joined:
            header_row = r
            break
    if header_row is None:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for r in range(header_row + 1, ws.max_row + 1):
        text = str(ws.cell(r, _STEEL_COLS["desc"]).value or "").strip()
        if not text:
            # Blank template rows sit between the blocks; stop once we have started and
            # then hit two in a row, rather than running on into "Other Sheet Material".
            if out and not str(ws.cell(r + 1, _STEEL_COLS["desc"]).value or "").strip():
                break
            continue
        code = text.split()[0].strip().upper()
        out[code] = {"row": r, "text": text,
                     **{k: ws.cell(r, c).value for k, c in _STEEL_COLS.items() if k != "desc"}}
    return out


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
    # THREE SHAPES, BECAUSE THE FULL SCAN IS TOO BIG TO MOVE. 12552's scan JSON is 258,935
    # lines; nobody is going to send that to have three fields read out of it. So a trimmed
    # extract — a bare list of records, or {"parts": [...]} — is accepted alongside the real
    # thing, and only part_number, pages and page_roles are ever read from any of them.
    #
    # This is a workaround for the actual defect, which is that no page number reaches any
    # deliverable. Once the page is written onto the row, this whole path becomes unnecessary.
    if isinstance(data, list):
        parts = data
    else:
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


def _price_source(bom_row: Dict[str, Any], provenance: Dict[str, Dict[str, Any]],
                  steel_index: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
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
        # NAME THE ROW IT IS COSTED ON. "priced below" is true and stops exactly where the
        # question starts; an estimator wants to look at the figure, not be told it exists.
        steel_row = (steel_index or {}).get(code, {}).get("row")
        return (f"by blank area — see `Estimate!{steel_row}` below"
                if steel_row else
                "by blank area on the Sheet Steel block, not per piece")
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
    steel = _steel_rows(wb)
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
            f"| {_price_source(row, provenance, steel)} "
            f"| {_fmt(mat.get('Material'))} "
            f"| {_fmt(mat.get('Gauge'), 'none — not sheet')} "
            f"| {blank} "
            f"| {_pages_of(rec) if rec else 'not supplied'} |")
    add("")

    # ── where the fabricated money actually is ───────────────────────────────
    if steel:
        add("## The fabricated parts, priced by blank area")
        add("")
        add("Each of these shows a dash in the BOM price column above. That is not a missing "
            "rate — sheet metal is costed from its blank on this block, and pricing it in "
            "both places would double it. This is the other half of those lines.")
        add("")
        add("| Part | Blank L × W | Gauge | Off a sheet | Scrap | Cost/part | Qty | "
            "Extended | Sheet row |")
        add("|---|---|---|---|---|---|---|---|---|")
        for code, row in steel.items():
            # COST FROM THE RESOLVED FIGURE, NOT THE FORMULA CELL. The Sheet Steel block's
            # cost column is an Excel formula, and a workbook written by the engine and never
            # opened has no cached result — so reading that cell alone gives nothing and the
            # table says "computes in Excel" on the one column an estimator came for. The
            # engine's own resolved figure for the same part is on AI Material Detail, which
            # is a value, not a formula. Still read, never recalculated here.
            mat = material.get(code, {})
            add(f"| {code} "
                f"| {_fmt(row.get('length'))} × {_fmt(row.get('width'))} "
                f"| {_fmt(row.get('gauge'))} "
                f"| {_fmt(row.get('sheet_l'))} × {_fmt(row.get('sheet_w'))} "
                f"| {_fmt(row.get('scrap'))} "
                f"| {_fmt(mat.get('Cost/Part'), 'not resolved')} "
                f"| {_fmt(row.get('qty'))} "
                f"| {_fmt(mat.get('Ext Material'), 'not resolved')} "
                f"| `Estimate!{row['row']}` |")
        add("")
        add("> Cost per part and extended are the engine's own resolved figures, read from "
            "the AI Material Detail tab. The Sheet Steel block holds them as Excel formulas, "
            "which have no value until the workbook is opened — nothing here is "
            "recalculated, so this cannot disagree with the sheet.")
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
    # A FIELD MISSING FROM THIS EXTRACT IS NOT A FIELD MISSING FROM THE DRAWING.
    #
    # This section reports what each sheet could be read for, and it does that by looking for
    # materials / thicknesses_mm / surface_finishes on the record. The trimmed extract that
    # supplies the page numbers carries only part_number, pages and page_roles — so against
    # one of those every row came out "material **no**, thickness **no**, finish **no**",
    # for a pack whose page 4 plainly reads "MATERIAL: MILD STEEL", "1.5 THK", "POWDER
    # COATED". That is not a weak answer, it is a confident wrong one, and it would have gone
    # to an estimator as a drawing-quality assessment.
    #
    # So the section is built only from an extract that actually carries the fields, and
    # otherwise says what it needs. Refusing to answer is the honest failure mode; the whole
    # document exists to stop people guessing from it.
    _quality_fields = ("materials", "thicknesses_mm", "surface_finishes", "geometry_rollup")
    _has_quality = any(any(k in rec for k in _quality_fields) for rec in scan.values())
    if scan and not _has_quality:
        add("## Drawing quality, sheet by sheet")
        add("")
        add("> **Not produced.** This ran against a trimmed extract carrying only part "
            "numbers and page numbers. Reporting from it would have said every drawing "
            "states no material, no thickness and no finish — which is false: page 4 alone "
            "reads *MATERIAL: MILD STEEL*, *1.5 THK*, *POWDER COATED*. Re-run with the full "
            "`output/json/<job>.json` and this section builds itself.")
        add("")
    if scan and _has_quality:
        add("## Drawing quality, sheet by sheet")
        add("")
        add("| Sheet | Part | Material stated | Thickness stated | Finish stated | "
            "Geometry | What it could not give |")
        add("|---|---|---|---|---|---|---|")
        for code, rec in sorted(scan.items(),
                               key=lambda kv: ((kv[1].get("pages") or [999])[0], kv[0])):
            # ONLY THINGS THAT ARE DRAWINGS. A line with no page is a catalogue item, a
            # commercial line, or a fastener off a BOM table — PACKAGING, DELIVERY, FIXING17.
            # Graded here they came out "could not give: thickness, finish, cut length",
            # which reads as a deficient drawing pack and is nonsense: packaging is not a
            # drawing, and an M8 nyloc nut has no thickness because it is bought, not because
            # somebody forgot to write one. Same false-negative as grading a pack from a
            # trimmed extract, in a different place.
            if not (rec.get("pages") or []):
                continue
            geom = rec.get("geometry_rollup") or {}
            reliability = ((geom.get("confidence") or {}).get("geometry_reliability"))
            # A PURCHASED PART NAMED ON AN ASSEMBLY SHEET IS NOT AN INCOMPLETE DETAIL.
            # The bearing and the rivets appear on p.2 because that is where they are listed,
            # and they have no detail drawing because they do not need one. Saying what they
            # ARE beats listing four fields they were never going to carry.
            _roles = [str(r).lower() for r in (rec.get("page_roles") or [])]
            if "bought_in" in _roles and "detail" not in _roles:
                missing = ["bought in — listed on an assembly sheet, no detail drawing needed"]
            else:
                missing = []
                if not rec.get("materials"):
                    missing.append("material")
                if not rec.get("thicknesses_mm"):
                    missing.append("thickness")
                if not rec.get("surface_finishes"):
                    missing.append("finish")
                if not (geom.get("estimated_cut_length_mm") or 0):
                    missing.append("cut length")
            add(f"| {_pages_of(rec)} | {code or _fmt(rec.get('description'))} "
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
