#!/usr/bin/env python3
"""Pack-size check: does each drawing say the same pack quantity as the catalogue? (17 Nov 2026)

An account manager's catalogue lists, for each product, the SDI drawing number and how many
units are in a pack. Some GA drawings say "PACK OF 45"; a drawing that says nothing is a pack
of 1. This reads every drawing's own PDF and reports where the two disagree, so a wrong pack
quantity is found before it is ordered, not after.

    cd C:\\ClaudeVision
    .\\.venv\\Scripts\\python.exe tools\\pack_size_check.py --sheet "C:\\...\\catalogue.xlsx"
    ... --tabs A,B                  the tabs to check, by the letter their names start with (default A,B)
    ... --root "W:\\...\\<customer folder>"   look only under this folder (repeatable); default the Design
                                    customers area, then Prototype, as every estimating tool
    ... --fresh                     list the job folders again instead of using today's list

READ-ONLY. Nothing on the drawing shares is changed, and the catalogue itself is never written:
the report is a NEW workbook (output\\pack_check\\<name> - pack check <date>.xlsx) holding the
same tabs with columns added after the last one. Every finding quotes the drawing's own words
and names the file it read, so a person can check any line in seconds.

RESULTS, one per row:
    Matches                       the drawing states the sheet's pack quantity (or states none,
                                  and the sheet says 1)
    MISMATCH                      the drawing states a different pack quantity
    CHECK: no pack on drawing     the sheet says more than 1 and the drawing states no pack
    CHECK: several on drawing     the drawing states more than one pack quantity
    Drawing not found             no job folder, or no PDF named for the drawing in it
    Drawing not readable          a PDF with no text (a scan): read it by eye
Finding the drawing uses the estimating engine's own rules (src/pack_resolver.py): the file
named for the drawing number, its latest revision, archive folders only where nothing else is.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# Run from a copy elsewhere (e.g. %TEMP%), the checkout it is run in supplies the engine's code.
for _src in (ROOT / "src", Path.cwd() / "src"):
    if (_src / "pack_resolver.py").exists():
        sys.path.insert(0, str(_src))
        break

# ── what a drawing says ──────────────────────────────────────────────────────────────────

# Each pattern's first group is the quantity. Read on the drawing's text in capitals, with its
# line breaks as spaces, so "PACK OF\n45" is still one phrase.
_PACK = [
    re.compile(r"\bPACKS?\s+OF\s+(\d{1,4})\b"),                          # PACK OF 45, PACKS OF 10
    re.compile(r"\b(\d{1,4})\s*(?:PCS|PIECES|UNITS|ITEMS|OFF)?\s*(?:PER|/)\s*PACK\b"),  # 45 PER PACK
    re.compile(r"\bPACK\s*(?:QTY|QUANTITY|SIZE)\s*[:=\-]?\s*(\d{1,4})\b"),  # PACK QTY: 45
    re.compile(r"\bQTY\.?\s*(?:PER|/)\s*PACK\s*[:=\-]?\s*(\d{1,4})\b"),   # QTY PER PACK 45
    re.compile(r"\b(\d{1,4})\s*-?\s*PACK\b(?!\s+OF)"),                   # 10 PACK, 6-PACK
]


def packs_stated(text: str) -> List[Tuple[int, str]]:
    """Every pack quantity the text states: (quantity, the words around it), in order, each once."""
    flat = re.sub(r"\s+", " ", str(text or "")).upper()
    out: List[Tuple[int, str]] = []
    spans: List[Tuple[int, int]] = []
    for pat in _PACK:
        for m in pat.finditer(flat):
            if any(a <= m.start() < b or a < m.end() <= b for a, b in spans):
                continue                    # the same words, already read by an earlier pattern
            q = int(m.group(1))
            if q <= 0:
                continue
            spans.append((m.start(), m.end()))
            a, b = max(0, m.start() - 25), min(len(flat), m.end() + 25)
            while a > 0 and flat[a - 1] != " ":                   # whole words either side
                a -= 1
            while b < len(flat) and flat[b] != " ":
                b += 1
            out.append((q, flat[a:b].strip()))
    out.sort(key=lambda x: flat.find(x[1]))
    return out


def judge(sheet_qty: Optional[int], stated: Sequence[Tuple[int, str]]) -> Tuple[str, str]:
    """(result, what the drawing says) for a drawing whose text was read."""
    found = sorted({q for q, _w in stated})
    if sheet_qty is None:
        return "CHECK: sheet quantity is not a number", ", ".join(map(str, found)) or "none stated (1)"
    if not found:
        return (("Matches", "none stated (so 1)") if sheet_qty == 1
                else ("CHECK: no pack on drawing", "none stated (so 1)"))
    if len(found) > 1:
        return "CHECK: several on drawing", ", ".join(map(str, found))
    return ("Matches" if found[0] == sheet_qty else "MISMATCH"), str(found[0])


def sheet_own_check(qty: Optional[int], description: Any, upc: Any) -> str:
    """The catalogue against itself: "PACK OF N" in the description and "(N)" in the UPC."""
    said = []
    d = re.search(r"PACK\s+OF\s+(\d+)", str(description or ""), re.IGNORECASE)
    u = re.search(r"\((\d+)\)\s*$", str(upc or "").strip())
    if d and qty is not None and int(d.group(1)) != qty:
        said.append(f"description says PACK OF {d.group(1)}")
    if u and qty is not None and int(u.group(1)) != qty:
        said.append(f"UPC ends ({u.group(1)})")
    return ("DIFFERS: " + "; ".join(said)) if said else ""


def as_qty(v: Any) -> Optional[int]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if float(v) == int(v) and v > 0 else None
    m = re.fullmatch(r"\s*(\d{1,5})\s*", str(v))
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


# ── finding the drawing ──────────────────────────────────────────────────────────────────

def job_number(drawing: Any) -> str:
    m = re.match(r"\s*(\d{3,})", str(drawing or ""))
    return m.group(1) if m else ""


def walk_job_folders(root: Path, depth: int = 3, say: Any = print) -> List[str]:
    """Every folder named for a job (a name starting with 3+ digits) under `root`, looking no deeper
    than `depth` folders above the jobs. Archive folders are left out, as the engine does."""
    import pack_resolver as pr
    found: List[str] = []
    stack = [(Path(root), 0)]
    seen = 0
    while stack:
        f, lvl = stack.pop()
        try:
            with os.scandir(f) as it:
                names = sorted(e.name for e in it if e.is_dir())
        except OSError as exc:
            if lvl == 0:
                raise SystemExit(f"STOP: {root} could not be read ({type(exc).__name__}). VPN on? "
                                 f"Nothing was written.")
            say(f"   [skip] could not read {f} ({type(exc).__name__})")
            continue
        for n in names:
            p = f / n
            if pr._archive_path(p):
                continue
            if re.match(r"\d{3,}", n):
                found.append(str(p))
            elif lvl < depth:
                stack.append((p, lvl + 1))
        seen += 1
        if seen % 500 == 0:
            say(f"   ... {seen} folders looked at, {len(found)} job folders so far")
    return found


def job_folder_list(roots: Sequence[Path], cache: Path, fresh: bool, say: Any = print) -> Dict[str, List[str]]:
    """{root: [job folders]}, listed once a day: the list is kept beside the report and reused."""
    try:
        kept = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() and not fresh else {}
    except (OSError, ValueError):
        kept = {}
    out: Dict[str, List[str]] = {}
    for r in roots:
        k = str(r)
        e = kept.get(k)
        if e and time.time() - float(e.get("at", 0)) < 24 * 3600:
            out[k] = list(e["folders"])
            say(f"[folders] {k}: {len(out[k])} job folders (listed {e.get('when')}; --fresh lists again)")
            continue
        t0 = time.time()
        say(f"[folders] listing the job folders under {k} - once a day, this can take several minutes")
        out[k] = walk_job_folders(r, say=say)
        kept[k] = {"at": time.time(), "when": datetime.now().strftime("%d %b %H:%M"), "folders": out[k]}
        say(f"[folders] {k}: {len(out[k])} job folders in {round(time.time() - t0)} s")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(kept), encoding="utf-8")
    return out


def pdfs_for(drawing: str, job_folders: Iterable[str], list_files: Any = None) -> Tuple[List[Path], str, bool]:
    """(the PDFs named for the drawing, the drawing number they were matched as, archive only?).
    `list_files(job_folder)` gives [(folder, [(path, size, mtime), ...]), ...] for every folder under it.
    The drawing's own number first; a bare job number ("4101") falls back to its GA ("4101-GA",
    "4101-00-GA"), said so."""
    import pack_resolver as pr
    lister = list_files or (lambda f: [(r[0], r[1]) for r in pr.rows_now(Path(f))])
    current: List[Tuple[Path, str, int, float]] = []
    archived: List[Tuple[Path, str, int, float]] = []
    for jf in job_folders:
        try:
            rows = lister(jf)
        except Exception:                                            # noqa: BLE001 - a folder that can't be read
            continue
        for folder, files in rows:
            for f in files:
                p = Path(f[0])
                if p.suffix.lower() != ".pdf":
                    continue
                (archived if pr._archive_path(Path(folder)) or pr._archive_path(p) else current).append(
                    (p, pr.drawing_id(p.name), int(f[1]), float(f[2])))
    up = drawing.strip().upper()
    for pool, is_arch in ((current, False), (archived, True)):
        own = [x for x in pool if pr._same(x[1], up)]
        if own:
            return [x[0] for x in sorted(own, key=lambda x: x[3], reverse=True)], up, is_arch
    if not re.search(r"(GA|SA)\d*$", up):
        for pool, is_arch in ((current, False), (archived, True)):
            ga = [x for x in pool if re.fullmatch(re.escape(up) + r"(-\d{1,3})*-?GA\d*", x[1] or "")]
            if ga:
                named = sorted({x[1] for x in ga})[0]
                return [x[0] for x in sorted(ga, key=lambda x: x[3], reverse=True)
                        if x[1] == named], named, is_arch
    return [], "", False


def newest(pdfs: List[Path]) -> Path:
    import pack_resolver as pr
    rows = []
    for p in pdfs:
        try:
            st = p.stat()
            rows.append((p, st.st_size, st.st_mtime))
        except OSError:
            rows.append((p, 0, 0.0))
    return pr._newest_revision_pdf(rows)[0]


def check_drawing(drawing: str, sheet_qty: Optional[int], folders: Dict[str, List[str]],
                  read_text: Any = None, list_files: Any = None) -> Dict[str, Any]:
    import pack_resolver as pr
    reader = read_text or (lambda p: pr.read_pdf_text(p, pages=12))
    job = job_number(drawing)
    if not job:
        return {"result": "Drawing not found", "note": "no job number in the drawing number"}
    mine = [f for fs in folders.values() for f in fs if re.match(rf"{job}(?!\d)", Path(f).name)]
    if not mine:
        return {"result": "Drawing not found", "note": f"no folder for job {job} in the areas searched"}
    pdfs, named, arch = pdfs_for(drawing, mine, list_files)
    if not pdfs:
        return {"result": "Drawing not found",
                "note": f"job {job} found ({Path(mine[0]).name}), but no PDF named for {drawing}"}
    pdf = newest(pdfs)
    text = reader(pdf)
    note = []
    if named != drawing.strip().upper():
        note.append(f"read its GA, {named}")
    if arch:
        note.append("only an archived copy exists")
    if not str(text or "").strip():
        return {"result": "Drawing not readable", "file": str(pdf),
                "note": "; ".join(note + ["no text in the PDF (a scan?) - read it by eye"])}
    stated = packs_stated(text)
    result, says = judge(sheet_qty, stated)
    return {"result": result, "on_drawing": says, "words": " | ".join(w for _q, w in stated[:3]),
            "file": str(pdf), "note": "; ".join(note)}


# ── the catalogue and the report ─────────────────────────────────────────────────────────

def _header_col(headers: Dict[int, str], *words: str, default: int) -> int:
    for c, h in headers.items():
        if all(w in h for w in words):
            return c
    return default


def tabs_wanted(names: Sequence[str], letters: Sequence[str]) -> List[str]:
    out = []
    for L in letters:
        hit = [n for n in names if re.match(rf"\s*{re.escape(L)}\s*(-|\s|$)", n, re.IGNORECASE)]
        if not hit:
            raise SystemExit(f"STOP: no tab whose name starts with {L!r} (tabs: {', '.join(names)}). Nothing was written.")
        out.append(hit[0])
    return out


RESULT_FILL = {"Matches": "C6EFCE", "MISMATCH": "FFC7CE", "CHECK": "FFEB9C",
               "Drawing not found": "D9D9D9", "Drawing not readable": "D9D9D9"}
NEW_COLS = ["Pack check: result", "Pack on drawing", "Drawing's words", "Sheet's own check",
            "Drawing read", "Note"]


def run(sheet: Path, letters: Sequence[str], roots: Sequence[Path], out_dir: Path, fresh: bool = False,
        say: Any = print, read_text: Any = None, list_files: Any = None,
        folders: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    values = openpyxl.load_workbook(sheet, data_only=True, read_only=False)
    book = openpyxl.load_workbook(sheet)
    tabs = tabs_wanted(values.sheetnames, letters)
    rows: List[Dict[str, Any]] = []
    for tab in tabs:
        ws = values[tab]
        headers = {c.column: str(c.value or "").strip().lower() for c in ws[1] if c.value}
        c_dwg = _header_col(headers, "drawing", default=6)
        c_qty = _header_col(headers, "per pack", default=10)
        c_desc = _header_col(headers, "description", default=5)
        c_upc = _header_col(headers, "upc", default=4)
        last = 1
        for (cell,) in ws.iter_rows(min_row=2, min_col=c_dwg, max_col=c_dwg):
            if cell.value not in (None, ""):
                last = cell.row
        for r in range(2, last + 1):
            d = ws.cell(r, c_dwg).value
            if d in (None, ""):
                continue
            q = ws.cell(r, c_qty).value
            rows.append({"tab": tab, "row": r, "drawing": str(d).strip(), "qty_cell": q, "qty": as_qty(q),
                         "own": sheet_own_check(as_qty(q), ws.cell(r, c_desc).value, ws.cell(r, c_upc).value),
                         "end_col": max(ws.max_column, max(headers) if headers else 0)})
    say(f"[sheet] {sheet.name}: {len(rows)} rows on {', '.join(tabs)}; "
        f"{len({x['drawing'].upper() for x in rows})} distinct drawings")
    if folders is None:
        folders = job_folder_list(roots, out_dir / "job_folders.json", fresh, say)
    seen: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    for i, x in enumerate(rows, 1):
        k = (x["drawing"].upper(), x["qty"])
        if k not in seen:
            try:
                seen[k] = check_drawing(x["drawing"], x["qty"], folders, read_text, list_files)
            except Exception as exc:                                  # noqa: BLE001 - one drawing never stops the rest
                seen[k] = {"result": "Drawing not readable", "note": f"{type(exc).__name__}: {str(exc)[:120]}"}
            say(f"  {i:>4}/{len(rows)}  {x['drawing']:<18} sheet {x['qty_cell']!s:<5} {seen[k]['result']}"
                + (f" - drawing: {seen[k].get('on_drawing')}" if seen[k].get("on_drawing") else ""))
        x.update(seen[k])

    # the report: the catalogue's own tabs, columns added after the last one; the catalogue untouched
    bold = Font(bold=True)
    end = {t: max(x["end_col"] for x in rows if x["tab"] == t) for t in {x["tab"] for x in rows}}
    for t, c0 in end.items():
        ws = book[t]
        for j, h in enumerate(NEW_COLS, 1):
            ws.cell(1, c0 + j, h).font = bold
    for x in rows:
        ws = book[x["tab"]]
        c0 = end[x["tab"]]
        vals = [x["result"], x.get("on_drawing", ""), x.get("words", ""), x["own"],
                Path(x["file"]).name if x.get("file") else "", x.get("note", "")]
        for j, v in enumerate(vals, 1):
            ws.cell(x["row"], c0 + j, v)
        fill = RESULT_FILL.get(x["result"]) or RESULT_FILL["CHECK"]
        ws.cell(x["row"], c0 + 1).fill = PatternFill("solid", start_color=fill, end_color=fill)
        if x["own"]:
            ws.cell(x["row"], c0 + 4).fill = PatternFill("solid", start_color="FFC7CE", end_color="FFC7CE")
    counts = Counter(("CHECK" if x["result"].startswith("CHECK") else x["result"]) for x in rows)
    own = [x for x in rows if x["own"]]
    sm = book.create_sheet("Pack check", 0)
    sm["A1"] = "Pack-size check"; sm["A1"].font = Font(bold=True, size=14)
    sm["A2"] = (f"{sheet.name}, tabs {', '.join(tabs)}; checked {datetime.now():%d %B %Y %H:%M}. Each drawing's own PDF "
                f"was read for its pack quantity; a drawing that states none is a pack of 1.")
    r = 4
    for k in ("MISMATCH", "CHECK", "Drawing not found", "Drawing not readable", "Matches"):
        sm.cell(r, 1, k); sm.cell(r, 2, counts.get(k, 0)); r += 1
    sm.cell(r, 1, "Sheet disagrees with itself"); sm.cell(r, 2, len(own)); r += 2
    sm.cell(r, 1, "To look at").font = bold; r += 1
    for j, h in enumerate(["Tab", "Row", "Drawing", "Sheet (pack qty)", "Result", "On drawing", "Drawing's words",
                           "Sheet's own check", "Drawing read"], 1):
        sm.cell(r, j, h).font = bold
    for x in rows:
        if x["result"] == "Matches" and not x["own"]:
            continue
        r += 1
        for j, v in enumerate([x["tab"], x["row"], x["drawing"], x["qty_cell"], x["result"], x.get("on_drawing", ""),
                               x.get("words", ""), x["own"], x.get("file", "")], 1):
            sm.cell(r, j, v)
    for col, w in zip("ABCDEFGHI", (28, 6, 18, 14, 26, 16, 50, 34, 60)):
        sm.column_dimensions[col].width = w
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sheet.stem} - pack check {datetime.now():%Y-%m-%d %H%M}.xlsx"
    if out.resolve() == sheet.resolve():
        raise SystemExit("STOP: the report would overwrite the catalogue. Nothing was written.")
    book.save(out)
    return {"report": str(out), "counts": dict(counts), "own": len(own), "rows": len(rows)}


def default_roots() -> List[Path]:
    import drawing_index as di
    return list(di.settings()["roots"])


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--tabs", default="A,B")
    ap.add_argument("--root", action="append", default=[])
    ap.add_argument("--out", default=str(Path.cwd() / "output" / "pack_check"))
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args(argv)
    sheet = Path(a.sheet)
    if not sheet.exists():
        raise SystemExit(f"STOP: {sheet} was not found. Nothing was written.")
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        raise SystemExit("STOP: this Python cannot read PDFs. Run it with .\\.venv\\Scripts\\python.exe")
    from drive_map import to_unc
    roots = [Path(to_unc(r)) for r in a.root] or default_roots()
    res = run(sheet, [t.strip() for t in a.tabs.split(",") if t.strip()], roots, Path(a.out), a.fresh)
    c = res["counts"]
    print()
    print(f"{res['rows']} rows: {c.get('Matches', 0)} match, {c.get('MISMATCH', 0)} MISMATCH, {c.get('CHECK', 0)} to check, "
          f"{c.get('Drawing not found', 0)} drawing not found, {c.get('Drawing not readable', 0)} not readable; "
          f"the sheet disagrees with itself on {res['own']}.")
    print(f"report: {res['report']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
