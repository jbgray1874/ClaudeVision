#!/usr/bin/env python3
"""TTI pricer: price each row of a TTI tracker spreadsheet and write the cost back (JG, 9 Nov 2026).

    python src/tti_pricer.py --sheet "C:\\...\\TRACKER - MILWAUKEE AMSTERDAM CONFERENCE 2027.xlsx" --dry-run
    python src/tti_pricer.py --sheet "<same>"                 price every row, one after another
    python src/tti_pricer.py --sheet "<same>" --rows 5-12      only those sheet rows

ONE ROW, ONE JOB. Each row is one TTI job:
    column L   the drawing number, looked for in the design and prototype areas
    column G   notes, sent with the job as its brief
    columns I, J  thumbnail pictures, usually; saved out and sent to the model where no drawing is found
    column P   AICost: the unit cost is written here, overwriting any earlier figure
A column headed Description (or Item / Job) and one headed Qty / Quantity are used where present.

WHERE THE DRAWINGS ARE. Under SDI_TTI_DESIGN_ROOT (W:\\Design\\Customers April 08 Onwards\\TTI), then
SDI_TTI_PROTOTYPE_ROOT (W:\\Prototype\\TTi): a folder whose path names the drawing number (as a
whole token, so 12693-01 is never 12693-012), preferring one with "Technical" in its path, and the
newest drawings within it. The drawings found are copied before the run into a `_held\\tti` folder
under the staging share (SDI_TTI_INPUTS to change it), so the service reads them from a folder it
is allowed to read, and the copy is the record of exactly which drawings were priced.

TWO KINDS OF ESTIMATE, SAID ON EACH ROW.
    drawings found   a full estimate (or the mode chosen with --method), the usual detailed workbook
    none found       an LLM estimate from the description, the notes and the thumbnails, labelled so
Both are filed exactly as any other run, in the usual estimating folders, client TTI. A run that
fails leaves column P as it was and says why in the status file.

WRITING THE SHEET. Through Excel itself where it is installed (so pictures, formatting and formulas
are untouched); otherwise through openpyxl, after a dated backup copy beside the sheet. Each row's
cost is written as soon as its run finishes, so a stopped batch keeps what it priced.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DRAWING_EXT = {".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw", ".step", ".stp"}
SKIP = re.compile(r"\b(archive|archived|superseded|old|backup|obsolete)\b", re.IGNORECASE)
DEFAULT_DESIGN = r"W:\Design\Customers April 08 Onwards\TTI"
DEFAULT_PROTOTYPE = r"W:\Prototype\TTi"
HEADER = re.compile(r"^\s*(drawing|dwg)\s*(number|no\.?|num|#|ref(erence)?)?\s*$", re.IGNORECASE)
_REF = re.compile(r"(?<![0-9A-Za-z])(?:[A-Za-z]{1,4}-)?\d{3,}[A-Za-z]?(?:-[A-Za-z0-9]+)*")


def drawing_ref(cell: str) -> str:
    """The drawing number in a cell that may say more: "12535-00-GA REV A (LARGER GRAPHICS)" is
    12535-00-GA, "7438 AS BASE" is 7438, "N/A" is nothing."""
    m = _REF.search(str(cell or ""))
    return m.group(0).upper() if m else ""


def job_folders(ref: str, listings: List[Tuple[str, List[Path]]], limit: int = 3) -> List[str]:
    """Where a drawing that was not found might be: folders naming its job number. Reported, never
    priced from, so a naming difference can be seen and fixed rather than guessed at."""
    job = re.search(r"\d{3,}", ref or "")
    if not job:
        return []
    pat = re.compile(r"(?<![0-9])" + job.group(0) + r"(?![0-9])")
    out: List[str] = []
    for _area, folders in listings:
        for f in folders:
            if pat.search(f.name):
                out.append(str(f))
                if len(out) >= limit:
                    return out
    return out


def col_index(letter: str) -> int:
    n = 0
    for ch in letter.strip().upper():
        n = n * 26 + (ord(ch) - 64)
    return n


# ── reading the sheet ───────────────────────────────────────────────────────────────────

def read_rows(sheet: Path, cols: Dict[str, str], rows: Optional[Tuple[int, int]] = None,
              sheet_name: str = "") -> Dict[str, Any]:
    """The header row and every job row: drawing, notes, description, quantity, thumbnails."""
    import openpyxl
    wb = openpyxl.load_workbook(sheet, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    dcol = col_index(cols["drawing"])
    # THE HEADER IS THE CELL THAT NAMES THE COLUMN, not the first one mentioning drawings: a
    # title row above it ("... drawings ...") was taken for the header once, and the real header
    # row then priced as a job called "Drawing Number" (9 Nov 2026 dry run).
    header_row = None
    for r in range(1, min(ws.max_row, 20) + 1):
        if HEADER.match(str(ws.cell(r, dcol).value or "")):
            header_row = r
            break
    if header_row is None:
        for r in range(1, min(ws.max_row, 20) + 1):
            v = str(ws.cell(r, dcol).value or "")
            if re.search(r"draw|dwg", v, re.IGNORECASE) and len(v) <= 40:
                header_row = r
                break
    if header_row is None:
        raise SystemExit(f"No header naming the drawing number in column {cols['drawing']} in the "
                         f"first 20 rows of {sheet.name} ({ws.title}). Pass --col-drawing.")
    heads = {c: str(ws.cell(header_row, c).value or "").strip() for c in range(1, ws.max_column + 1)}

    def find(*words: str) -> Optional[int]:
        for c, h in heads.items():
            if any(re.search(rf"\b{w}", h, re.IGNORECASE) for w in words):
                return c
        return None
    desc_c = find("description", "item", "job")
    qty_c = find("qty", "quantity")
    pics: Dict[int, List[Any]] = {}
    for img in getattr(ws, "_images", []) or []:
        try:
            r0, c0 = img.anchor._from.row + 1, img.anchor._from.col + 1
        except AttributeError:
            continue
        if c0 in {col_index(x) for x in cols["thumbs"]}:
            pics.setdefault(r0, []).append(img)
    out = []
    first, last = rows if rows else (header_row + 1, ws.max_row)
    for r in range(max(first, header_row + 1), min(last, ws.max_row) + 1):
        drawing = str(ws.cell(r, dcol).value or "").strip()
        if HEADER.match(drawing):
            continue                                        # a repeated header row is not a job
        notes = str(ws.cell(r, col_index(cols["notes"])).value or "").strip()
        desc = str(ws.cell(r, desc_c).value or "").strip() if desc_c else ""
        if not (drawing or notes or desc or pics.get(r)):
            continue
        try:
            qty = int(float(ws.cell(r, qty_c).value)) if qty_c and ws.cell(r, qty_c).value else 1
        except (TypeError, ValueError):
            qty = 1
        out.append({"row": r, "drawing": drawing_ref(drawing), "drawing_cell": drawing, "notes": notes, "description": desc,
                    "quantity": max(1, qty), "pictures": pics.get(r, []),
                    "cost_before": ws.cell(r, col_index(cols["cost"])).value})
    return {"sheet": ws.title, "header_row": header_row,
            "header": {"description": heads.get(desc_c) if desc_c else None,
                       "quantity": heads.get(qty_c) if qty_c else None,
                       "drawing": heads.get(dcol), "cost": heads.get(col_index(cols["cost"]))},
            "rows": out}


# ── finding the drawings ────────────────────────────────────────────────────────────────

def _token(drawing: str) -> Optional[re.Pattern]:
    d = re.sub(r"\s+", "", drawing or "")
    if len(re.sub(r"\D", "", d)) < 3:
        return None
    return re.compile(r"(?<![0-9A-Za-z])" + re.escape(d).replace(r"\-", r"[-_ ]?") + r"(?![0-9])", re.IGNORECASE)


def list_folders(root: Path, depth: int = 7) -> List[Path]:
    """Every folder under the root, to a depth, archives skipped: walked once per batch."""
    out: List[Path] = []
    if not root.is_dir():
        return out
    base = len(root.parts)
    for dirpath, dirnames, _files in os.walk(root):
        p = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not SKIP.search(d)]
        if len(p.parts) - base >= depth:
            dirnames[:] = []
        out.append(p)
    return out


_FILES: Dict[str, List[Path]] = {}
_MTIME: Dict[str, float] = {}


def _mtime(p: Path) -> float:
    k = str(p)
    if k not in _MTIME:
        try:
            _MTIME[k] = p.stat().st_mtime
        except OSError:
            _MTIME[k] = 0.0
    return _MTIME[k]


def area_listings(design: Path, proto: Path) -> Tuple[List[Tuple[str, List[Path]]], str]:
    """The folders of both areas, from the drawing index where it is fresh and covers them,
    else walked live; and which of the two it was, said on the status and the console."""
    try:
        sys.path.insert(0, str(HERE))
        import drawing_index as di
        cfg = di.settings()
        idx = di.load(cfg["path"])
    except Exception:                                                    # noqa: BLE001
        idx, cfg, di = None, None, None
    if idx and di.is_fresh(idx, cfg["max_hours"]) and di.covers(idx, design) and di.covers(idx, proto):
        out = []
        for area, root in (("design", design), ("prototype", proto)):
            folders = []
            for folder, files in di.folders_under(idx, root):
                folders.append(folder)
                _FILES[str(folder)] = sorted(f for f, _s, _m in files)
                for f, _s, m in files:
                    _MTIME[str(f)] = m
            out.append((area, folders))
        return out, f"drawing index built {di.summary(idx)['built_at']}"
    why = ("no drawing index" if not idx else "the drawing index is stale" if not di.is_fresh(idx, cfg["max_hours"])
           else "the drawing index does not cover these folders")
    return [("design", list_folders(design)), ("prototype", list_folders(proto))], f"walked live ({why})"


def drawings_in(folder: Path) -> List[Path]:
    """The drawing files directly in a folder, listed once per batch: two hundred rows must not
    list every folder on the share two hundred times."""
    key = str(folder)
    if key not in _FILES:
        try:
            _FILES[key] = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in DRAWING_EXT)
        except OSError:
            _FILES[key] = []
    return _FILES[key]


def _best(hits: List[Dict[str, Any]], area: str, match: str) -> Dict[str, Any]:
    hits.sort(key=lambda h: (h["technical"], h["newest"]), reverse=True)
    best = hits[0]
    return {"area": area, "match": match, "folder": str(best["folder"]), "files": [str(x) for x in best["files"]],
            "technical": best["technical"],
            "newest": datetime.fromtimestamp(best["newest"]).isoformat(timespec="minutes"),
            "other_folders": [str(h["folder"]) for h in hits[1:6]]}


def find_drawings(drawing: str, listings: List[Tuple[str, List[Path]]]) -> Dict[str, Any]:
    """The folder that best holds this drawing number's drawings, and its files; {} if none."""
    pat = _token(drawing)
    if not pat:
        return {}
    for area, folders in listings:
        hits = []
        for f in folders:
            path_txt = str(f)
            files = drawings_in(f)
            named_files = [x for x in files if pat.search(x.name)]
            if not (pat.search(path_txt) and files) and not named_files:
                continue
            use = files if pat.search(path_txt) else named_files
            newest = max((_mtime(x) for x in use), default=0)
            hits.append({"folder": f, "files": use, "technical": "technical" in path_txt.lower(),
                         "newest": newest})
        if hits:
            return _best(hits, area, "drawing number")
    # THE JOB FOLDER, WHEN NO FILE CARRIES THE DRAWING NUMBER. Design files a job as
    # "12181 - Sander Application Demo [Rome 2026]": the job number only. A folder whose own name
    # starts with the job number is the job; its Technical folder and newest drawings are used,
    # and the row says it was matched by job, not by drawing number (JG, 9 Nov 2026).
    job = re.search(r"\d{3,}", drawing or "")
    if not job:
        return {}
    jpat = re.compile(r"^\s*" + job.group(0) + r"(?![0-9])")
    for area, folders in listings:
        roots = [f for f in folders if jpat.search(f.name)]
        hits = []
        for f in folders:
            if not any(f == r or r in f.parents for r in roots):
                continue
            files = drawings_in(f)
            if files:
                hits.append({"folder": f, "files": files, "technical": "technical" in str(f).lower(),
                             "newest": max(_mtime(x) for x in files)})
        if hits:
            return _best(hits, area, "job folder")
    return {}


# ── staging copies and pictures ─────────────────────────────────────────────────────────

def copy_inputs(files: Iterable[str], pictures: List[Any], dest: Path) -> List[str]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        t = dest / Path(f).name
        shutil.copy2(f, t)
        out.append(str(t))
    for k, img in enumerate(pictures, start=1):
        try:
            data = img._data()
        except Exception:                                                # noqa: BLE001
            continue
        ext = "." + str(getattr(img, "format", "png") or "png").lower().replace("jpeg", "jpg")
        t = dest / f"thumbnail_{k}{ext}"
        t.write_bytes(data)
        out.append(str(t))
    return out


# ── writing the cost back ───────────────────────────────────────────────────────────────

class SheetWriter:
    """Column P, one cell at a time: Excel where it exists, else openpyxl after a backup."""

    def __init__(self, sheet: Path, sheet_name: str, cost_col: str):
        self.sheet, self.sheet_name, self.col = sheet, sheet_name, cost_col
        self.backup: Optional[Path] = None
        self.how = "excel"
        try:
            import win32com.client  # noqa: F401
        except Exception:                                                # noqa: BLE001
            self.how = "openpyxl"

    def write(self, row: int, value: float) -> None:
        if self.how == "excel":
            try:
                self._excel(row, value)
                return
            except Exception as exc:                                     # noqa: BLE001
                print(f"[tti] Excel could not write row {row} ({exc}); using openpyxl", flush=True)
                self.how = "openpyxl"
        self._openpyxl(row, value)

    def _excel(self, row: int, value: float) -> None:
        import win32com.client
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.DisplayAlerts = False
        wb = xl.Workbooks.Open(str(self.sheet))
        try:
            ws = wb.Worksheets(self.sheet_name) if self.sheet_name else wb.ActiveSheet
            ws.Cells(row, col_index(self.col)).Value = float(value)
            wb.Save()
        finally:
            wb.Close(SaveChanges=False)
            xl.Quit()

    def _openpyxl(self, row: int, value: float) -> None:
        import openpyxl
        if self.backup is None:
            self.backup = self.sheet.with_name(f"{self.sheet.stem} (before AI cost {datetime.now():%Y-%m-%d %H%M}){self.sheet.suffix}")
            shutil.copy2(self.sheet, self.backup)
        wb = openpyxl.load_workbook(self.sheet)
        ws = wb[self.sheet_name] if self.sheet_name else wb.active
        ws.cell(row, col_index(self.col)).value = float(value)
        wb.save(self.sheet)


# ── the batch ───────────────────────────────────────────────────────────────────────────

def brief_for(r: Dict[str, Any]) -> str:
    parts = [f"TTI job, sheet row {r['row']}."]
    if r.get("drawing"):
        cell = str(r.get("drawing_cell") or "")
        extra = f" (the sheet says: {cell})" if cell and cell.upper() != r["drawing"] else ""
        parts.append(f"Drawing number {r['drawing']}{extra}.")
    if r.get("description"):
        parts.append(f"Description: {r['description']}.")
    if r.get("notes"):
        parts.append(f"Notes: {r['notes']}.")
    parts.append(f"Quantity: {r['quantity']}.")
    return " ".join(parts)


def wait_for(portal: Any, run_id: str, timeout_s: int = 4 * 3600, every_s: int = 30,
             sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    waited = 0
    while waited <= timeout_s:
        st = portal.status(run_id) or {}
        if str(st.get("status") or "") in ("done", "error", "cancelled", "failed", "abandoned"):
            return st
        sleep(every_s)
        waited += every_s
    return {"status": "timeout"}


def unit_cost_of(st: Dict[str, Any], qty: int) -> Optional[float]:
    for q in st.get("quantity_prices") or []:
        try:
            if int(q.get("quantity")) == int(qty) and q.get("unit_gbp") is not None:
                return round(float(q["unit_gbp"]), 2)
        except (TypeError, ValueError):
            continue
    for k in ("engine_price_gbp", "unit_cost_gbp", "unit_gbp"):
        try:
            if st.get(k) is not None:
                return round(float(st[k]), 2)
        except (TypeError, ValueError):
            continue
    return None


def inputs_root() -> Path:
    """Where each row's drawings and thumbnails are copied before its run. The service's own
    reader takes files only from inside its shares (SDI_FILE_ROOTS), so the default is a
    `_held` folder under the staging share; output\\tti only when no staging root is set."""
    explicit = (os.getenv("SDI_TTI_INPUTS") or "").strip()
    if explicit:
        return Path(explicit)
    staging = (os.getenv("SDI_STAGING_ROOT") or "").strip()
    return Path(staging) / "_held" / "tti" if staging else ROOT / "output" / "tti"


def run_batch(args: argparse.Namespace, portal: Any = None, status_path: Optional[Path] = None,
              sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    sheet = Path(args.sheet)
    cols = {"drawing": args.col_drawing, "notes": args.col_notes, "thumbs": args.col_thumbs.split(","),
            "cost": args.col_cost}
    rows = None
    if args.rows:
        a, _, b = args.rows.partition("-")
        rows = (int(a), int(b or a))
    data = read_rows(sheet, cols, rows, args.sheet_name)
    from drive_map import to_unc
    design = Path(to_unc(os.getenv("SDI_TTI_DESIGN_ROOT") or DEFAULT_DESIGN))
    proto = Path(to_unc(os.getenv("SDI_TTI_PROTOTYPE_ROOT") or DEFAULT_PROTOTYPE))
    _FILES.clear()
    _MTIME.clear()
    if not args.dry_run and not design.is_dir() and not proto.is_dir():
        # Every row would fall to an LLM estimate for want of a readable share, not of drawings.
        raise SystemExit(f"Neither drawing area can be read from here ({design}; {proto}), so every row "
                         f"would be priced without its drawings. Nothing was queued or written. Set "
                         f"SDI_DRIVE_MAP (W=\\\\server\\share) or the two SDI_TTI_*_ROOT settings, and run "
                         f"--dry-run until rows show their folders.")
    listings, source = area_listings(design, proto)
    out_root = inputs_root() / re.sub(r"[^\w .-]", "_", sheet.stem)
    report: Dict[str, Any] = {"sheet": str(sheet), "tab": data["sheet"], "header_row": data["header_row"],
                              "header": data["header"], "started": datetime.now().isoformat(timespec="seconds"),
                              "dry_run": bool(args.dry_run), "method": args.method,
                              "roots": {"design": str(design), "design_readable": design.is_dir(),
                                        "design_folders": len(listings[0][1]),
                                        "prototype": str(proto), "prototype_readable": proto.is_dir(),
                                        "prototype_folders": len(listings[1][1]), "source": source},
                              "rows": []}

    def save() -> None:
        if status_path:
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")

    writer = None if args.dry_run else SheetWriter(sheet, args.sheet_name or "", args.col_cost)
    priced: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for r in data["rows"]:
        found = find_drawings(r["drawing"], listings) if r["drawing"] else {}
        item = {"row": r["row"], "drawing": r["drawing"], "drawing_cell": r.get("drawing_cell", r["drawing"]),
                "quantity": r["quantity"],
                "kind": ("full estimate" if found.get("match") != "job folder"
                         else "full estimate (job folder)") if found else "LLM estimate (no drawings found)",
                "found": {k: v for k, v in found.items() if k != "files"} if found else None,
                "files": len(found.get("files") or []) if found else 0,
                "thumbnails": len(r["pictures"]), "cost_before": r["cost_before"], "state": "planned"}
        if not found and r["drawing"]:
            item["job_folders"] = job_folders(r["drawing"], listings)
        report["rows"].append(item)
        save()
        # THE SAME DRAWING AT THE SAME QUANTITY IS PRICED ONCE PER BATCH; later rows take its cost.
        same = priced.get((r["drawing"], r["quantity"])) if r["drawing"] else None
        if same is not None:
            item.update(state="same as row %d" % same["row"], same_as_row=same["row"])
            if args.dry_run or same.get("unit_cost") is None:
                save()
                continue
        if args.dry_run:
            if r["drawing"]:
                priced[(r["drawing"], r["quantity"])] = item
            continue
        if same is not None:
            item["unit_cost"] = same["unit_cost"]
            try:
                writer.write(r["row"], same["unit_cost"])
                item["written"] = f"{args.col_cost}{r['row']} = {same['unit_cost']}"
            except OSError as exc:
                item["why"] = f"{args.col_cost}{r['row']} could not be written ({exc})"
            save()
            continue
        name = re.sub(r"[^\w .-]", "_", r["drawing"] or f"row{r['row']}")
        inputs = copy_inputs(found.get("files") or [], [] if found else r["pictures"], out_root / f"row{r['row']}_{name}")
        if not inputs and not (r["notes"] or r["description"]):
            item.update(state="skipped", why="no drawings, pictures, description or notes to price from")
            save()
            continue
        body = {"client": args.client, "drawing_number": r["drawing"] or f"TTI-row{r['row']}",
                "units": r["quantity"], "files": inputs, "deliverables": True,
                "method": args.method if found else "llm", "enquiry_brief": brief_for(r)}
        try:
            started = portal.start(body)
        except Exception as exc:                                         # noqa: BLE001
            item.update(state="not queued", why=str(exc))
            save()
            continue
        item.update(state="running", run_id=started.get("run_id"))
        save()
        st = wait_for(portal, item["run_id"], sleep=sleep)
        cost = unit_cost_of(st, r["quantity"])
        item.update(state=str(st.get("status")), unit_cost=cost, output=st.get("output_path") or st.get("output"))
        if r["drawing"]:
            priced[(r["drawing"], r["quantity"])] = item
        if cost is not None and str(st.get("status")) == "done":
            try:
                writer.write(r["row"], cost)
                item["written"] = f"{args.col_cost}{r['row']} = {cost}"
            except OSError as exc:
                # Usually the workbook is open in Excel. The cost is kept here and in the run's
                # own folder; the row is priced, only the cell is not filled.
                item["why"] = f"priced, but {args.col_cost}{r['row']} could not be written ({exc}); close the workbook and run the row again"
        else:
            item["why"] = st.get("error") or "the run finished without a unit cost; column P left as it was"
        save()
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    if writer is not None:
        report["written_by"] = writer.how
        report["backup"] = str(writer.backup) if writer.backup else None
    save()
    return report


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--sheet-name", default="", help="the tab; default the active one")
    ap.add_argument("--rows", default="", help="sheet rows to price, e.g. 5-12")
    ap.add_argument("--client", default="TTI")
    ap.add_argument("--method", default="both", choices=("both", "targeted", "deterministic", "llm"))
    ap.add_argument("--col-drawing", default="L")
    ap.add_argument("--col-notes", default="G")
    ap.add_argument("--col-thumbs", default="I,J")
    ap.add_argument("--col-cost", default="P")
    ap.add_argument("--dry-run", action="store_true", help="find the drawings and say what would run; nothing queued or written")
    ap.add_argument("--server", default=os.getenv("SDI_SERVER", "http://localhost:8072"))
    ap.add_argument("--api-key", default=os.getenv("SDI_API_KEY", ""))
    ap.add_argument("--status-file", default="")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    sys.path.insert(0, str(HERE))
    try:
        import config  # noqa: F401  (loads .env)
    except Exception:                                                    # noqa: BLE001
        pass
    portal = None
    if not args.dry_run:
        import live_enquiry_runner as ler
        portal = ler.Portal(args.server, args.api_key, timeout=120)
    status = Path(args.status_file) if args.status_file else (ROOT / "output" / "tti" / "last_tti_run.json")
    rep = run_batch(args, portal, status)
    ro = rep["roots"]
    for k in ("design", "prototype"):
        state = f"{ro[k + '_folders']} folder(s)" if ro[k + "_readable"] else "NOT READABLE from this window"
        print(f"{k:<10} {ro[k]}  {state}", flush=True)
    print(f"folders from: {ro.get('source')}", flush=True)
    print(f"header row {rep['header_row']} ({rep['header'].get('drawing')}); {len(rep['rows'])} job row(s)", flush=True)
    found = 0
    for it in rep["rows"]:
        where = (it.get("found") or {}).get("folder")
        found += bool(where)
        if not where:
            near = it.get("job_folders") or []
            where = ("not found; job folder(s): " + " | ".join(near)) if near else "no drawings found"
        cell = it.get("drawing_cell") or ""
        shown = it["drawing"] or "(none)"
        if cell and cell.upper() != it["drawing"]:
            shown += f" [{cell[:30]}]"
        print(f"row {it['row']:>4}  {shown:<28} {it['kind']:<34} {it['state']:<12} "
              f"{it.get('unit_cost', '') if it.get('unit_cost') is not None else ''}  {where}", flush=True)
    print(f"{found} of {len(rep['rows'])} row(s) have drawings; status file: {status}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
