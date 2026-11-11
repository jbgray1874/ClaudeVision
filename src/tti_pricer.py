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

WHERE THE DRAWINGS ARE. Under SDI_TTI_DESIGN_ROOT (\\\\sdi-dc01\\CAD\\Design\\Customers April 08 Onwards\\TTI, W:), then
SDI_TTI_PROTOTYPE_ROOT (\\\\sdi-dc01\\CAD\\Prototype\\TTi): a folder whose path names the drawing number (as a
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
DRAWING_EXT = {".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw", ".step", ".stp", ".igs", ".iges"}
SKIP = re.compile(r"\b(archive|archived|superseded|old|backup|obsolete)\b", re.IGNORECASE)
DEFAULT_DESIGN = r"\\sdi-dc01\CAD\Design\Customers April 08 Onwards\TTI"  # W:
DEFAULT_PROTOTYPE = r"\\sdi-dc01\CAD\Prototype\TTi"
PACK_NAMED = "candidate pack: drawing number in the file or folder name; not verified"
PACK_JOB_FOLDER = "candidate pack: job folder only; drawings not matched to this number; not verified"
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


def _col_letter(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


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
    # THE LATEST FEEDBACK (JG, 10 Nov 2026): "quantity reduced from 5 to 3", "drawings existing
    # from Rome". A column headed Feedback is part of the job's brief, beside the Notes.
    fb_c = find("feedback")
    # THE NUMBER OF UNITS (JG, 10 Nov 2026: "column N Quantity"). --col-qty names the column;
    # without it the header that says Qty / Quantity is used.
    qty_c = col_index(cols["qty"]) if cols.get("qty") else find("qty", "quantity")
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
        feedback = str(ws.cell(r, fb_c).value or "").strip() if fb_c else ""
        if not (drawing or notes or desc or pics.get(r)):
            continue
        try:
            qty = int(float(ws.cell(r, qty_c).value)) if qty_c and ws.cell(r, qty_c).value else 1
        except (TypeError, ValueError):
            qty = 1
        out.append({"row": r, "drawing": drawing_ref(drawing), "drawing_cell": drawing, "notes": notes, "description": desc,
                    "feedback": feedback,
                    "quantity": max(1, qty), "pictures": pics.get(r, []),
                    "cost_before": ws.cell(r, col_index(cols["cost"])).value})
    return {"sheet": ws.title, "header_row": header_row,
            "header": {"description": heads.get(desc_c) if desc_c else None,
                       "quantity": heads.get(qty_c) if qty_c else None,
                       "quantity_column": _col_letter(qty_c) if qty_c else None,
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
_DB_ROWS: List[bool] = []          # non-empty while the batch reads from the lookup database
_SIZE: Dict[str, int] = {}


def _size(p: Path) -> int:
    k = str(p)
    if k not in _SIZE:
        try:
            _SIZE[k] = p.stat().st_size
        except OSError:
            _SIZE[k] = 0
    return _SIZE[k]


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
        db = di.db_path(cfg["path"])
        if not db.exists() and cfg["path"].exists():
            di.build_db(di.load(cfg["path"]) or {}, db)          # once, from the index already built
        idx = di.db_meta(db) if db.exists() else None
    except Exception:                                                    # noqa: BLE001
        idx, cfg, di, db = None, None, None, None
    if idx and di.is_fresh(idx, cfg["max_hours"]) and di.covers(idx, design) and di.covers(idx, proto):
        out = []
        for area, root in (("design", design), ("prototype", proto)):
            folders = []
            for folder, files in di.db_folders_under(db, root):
                folders.append(folder)
                _FILES[str(folder)] = sorted(f for f, _s, _m in files)
                for f, s, m in files:
                    _MTIME[str(f)] = m
                    _SIZE[str(f)] = s
            out.append((area, folders))
        return out, f"drawing index built {datetime.fromtimestamp(idx['built_at']).isoformat(timespec='minutes')}"
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

    # EXCEL BUSY IS ASKED AGAIN, NEVER REPLACED BY OPENPYXL (11 Nov 2026). Row 18's write met
    # "Call was rejected by callee" (Excel busy, RPC_E_CALL_REJECTED) and the batch switched to
    # openpyxl for good. openpyxl rewrites the whole workbook and drops its pictures, and the
    # tracker's rows carry thumbnails. Where Excel exists it is the only writer: tried again a few
    # times, then the cost is left unwritten with the reason, and the next batch writes it from
    # the ledger without pricing again.
    EXCEL_TRIES = 5
    EXCEL_WAIT_S = 6.0

    def write(self, row: int, value: float) -> None:
        if self.how == "excel":
            last: Optional[Exception] = None
            for i in range(self.EXCEL_TRIES):
                try:
                    self._excel(row, value)
                    return
                except Exception as exc:                                 # noqa: BLE001
                    last = exc
                    print(f"[tti] Excel could not write row {row} (try {i + 1} of {self.EXCEL_TRIES}: "
                          f"{exc})", flush=True)
                    time.sleep(self.EXCEL_WAIT_S * (i + 1))
            raise OSError(f"Excel would not write {self.col}{row} after {self.EXCEL_TRIES} tries ({last}); "
                          f"close the tracker if it is open and run these rows again: the cost is kept "
                          f"in the ledger and written then, without pricing again")
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


# ── THE CONFERENCE FOLDER (JG, 11 Nov 2026) ────────────────────────────────────────────────
# "save the GA PDF file for each job we run for TTI ... (keep the existing copy of ALL the output
# files to where they get saved to now) to K:\Estimating\Completed\Live Enquiries\completed AI
# briefs\TTI\TTI_Amsterdam-Conference (will be a long list of s/sheets and GA-PDF files)". A copy:
# the run's own folder keeps everything. TTI only, because it is this batch that does it.
DEFAULT_COPY_TO = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Live Enquiries"
                   r"\completed AI briefs\TTI\TTI_Amsterdam-Conference")


def copy_to_conference(dest: str, output: Any, manifest: Optional[Dict[str, Any]],
                       drawing: str) -> List[str]:
    """The run's spreadsheets and its GA's PDF, copied into `dest`. A file already there with the
    same size is kept; a different one beside it gets the time added, never overwritten."""
    if not dest or str(dest).strip().lower() in ("none", "off", "no"):
        return []
    from drive_map import to_unc
    unc = to_unc(str(dest))
    if unc.startswith("\\\\") and os.name != "nt":
        raise OSError(f"{unc} is a Windows share; it is reached from the estimating laptop")
    d = Path(unc)
    d.mkdir(parents=True, exist_ok=True)
    picks: List[Tuple[Path, str]] = []
    out = Path(str(output)) if output else None
    if out is not None and out.is_file() and out.suffix.lower() in (".xlsx", ".xlsm"):
        picks.append((out, out.name))
    elif out is not None and out.is_dir():
        picks += [(f, f.name) for f in sorted(out.iterdir())
                  if f.is_file() and f.suffix.lower() in (".xlsx", ".xlsm") and not f.name.startswith("~$")]
    if manifest:
        import pack_resolver as pr
        ga = next((x for x in manifest.get("members") or []
                   if pr._same(str(x.get("drawing")), str(manifest.get("drawing") or drawing))), None)
        pdf = next((f for f in (ga or {}).get("files") or [] if str(f.get("format")).lower() == "pdf"), None)
        if pdf:
            rev = (ga or {}).get("revision") or manifest.get("revision") or ""
            picks.append((Path(pdf["path"]), f"{drawing}_GA" + (f"_rev{rev}" if rev else "") + ".pdf"))
    done: List[str] = []
    for src, name in picks:
        if not src.is_file():
            continue
        target = d / name
        if target.exists():
            if target.stat().st_size == src.stat().st_size:
                done.append(f"{name} (already there)")
                continue
            target = d / f"{target.stem} {datetime.now():%Y-%m-%d %H%M}{target.suffix}"
        shutil.copy2(src, target)
        done.append(target.name)
    return done


def row_cells(sheet: Path, tab: str, row: int) -> Dict[str, Any]:
    """Every cell of one sheet row as stored (formulas as formulas), by column letter: the
    before-and-after picture a write-back is checked against."""
    import openpyxl
    from openpyxl.utils import get_column_letter
    wb = openpyxl.load_workbook(sheet)
    ws = wb[tab] if tab else wb.active
    return {get_column_letter(c): ws.cell(row, c).value for c in range(1, ws.max_column + 1)}


def check_write(before: Dict[str, Any], after: Dict[str, Any], col: str, value: float) -> str:
    """'' when the cost cell holds the value and every other cell of the row is as it was;
    otherwise what differs. A write-back is not trusted until this says so."""
    col = col.upper()
    problems = []
    try:
        if after.get(col) is None or abs(float(after.get(col)) - float(value)) > 0.005:
            problems.append(f"{col} reads {after.get(col)!r}, not {value}")
    except (TypeError, ValueError):
        problems.append(f"{col} reads {after.get(col)!r}, not {value}")
    for k in sorted(set(before) | set(after)):
        if k != col and before.get(k) != after.get(k):
            problems.append(f"{k} changed from {before.get(k)!r} to {after.get(k)!r}")
    return "; ".join(problems)


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
    if r.get("feedback"):
        parts.append(f"Latest feedback: {r['feedback']}.")
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


def unit_cost_at(st: Dict[str, Any], qty: int) -> Optional[float]:
    """The unit cost at exactly `qty` from the run's quantity breaks; None when it priced none."""
    for q in st.get("quantity_prices") or []:
        try:
            if int(q.get("quantity")) == int(qty) and q.get("unit_gbp") is not None:
                return round(float(q["unit_gbp"]), 2)
        except (TypeError, ValueError):
            continue
    return None


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


def pack_for(drawing: str, listings: List[Tuple[str, List[Path]]], client: str
             ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """The row's drawing pack through the shared resolver (src/pack_resolver.py, SCRUM-199): the
    same rules and manifest as the estimating page and Self-Running. ({}, None) when no file is
    named for the drawing, so the job-folder fallback can say what it found instead."""
    import pack_resolver as pr
    folders = [(f, area) for area, fs in listings for f in fs]
    if _DB_ROWS:
        # THE LOOKUP DATABASE: the drawing's own and its job's folders, the GA's surroundings
        # re-listed now, and shared-library parts found anywhere: the page's and Self-Running's way.
        rows, _src, lookup = pr.folders_for(drawing)
        m = pr.resolve(drawing, rows, client=client, lookup=lookup, client_folders_only=True)
        if m["status"] == "not found":
            return {}, None
        area = "prototype" if "prototype" in str(m.get("selected_folder") or "").lower() else "design"
        files = [f["path"] for x in m["members"] for f in x["files"]]
        return ({"area": area, "match": "pack", "folder": m.get("selected_folder"), "files": files,
                 "technical": "technical" in str(m.get("selected_folder") or "").lower(), "newest": "",
                 "other_folders": [c["folder"] for c in m["candidates"] if c["folder"] != m.get("selected_folder")][:5]},
                m)
    own = [f for f, _a in folders if any(pr._same(pr.drawing_id(x.name), drawing) for x in drawings_in(f))]
    if not own:
        return {}, None
    # The candidates' folders and everything below them; the job's other folders for children the
    # GA references elsewhere; shared-library parts are looked up by name across both areas.
    job = re.match(r"\s*(\d{3,})", drawing)
    keep = [f for f, _a in folders
            if any(f == o or o in f.parents for o in own) or (job and job.group(1) in str(f))]
    rows = [(f, [(x, _size(x), _mtime(x)) for x in drawings_in(f)], False) for f in keep]
    m = pr.resolve(drawing, rows, client=client, client_folders_only=True)
    if m["status"] == "not found":
        return {}, None
    area = next((a for f, a in folders if str(f) == m.get("selected_folder")), "design")
    files = [f["path"] for x in m["members"] for f in x["files"]]
    found = {"area": area, "match": "pack", "folder": m.get("selected_folder"), "files": files,
             "technical": "technical" in str(m.get("selected_folder") or "").lower(),
             "newest": "", "other_folders": [c["folder"] for c in m["candidates"]
                                             if c["folder"] != m.get("selected_folder")][:5]}
    return found, m


def pack_line(m: Dict[str, Any]) -> str:
    """One line for the screen: the pack's status, size and revision, and why."""
    bits = [f"{m['status']} pack: {len(m['members'])} drawing(s), revision {m.get('revision') or 'not read'}"]
    if m.get("identity") == "verified":
        bits.append("GA identity verified from its title block")
    elif m.get("identity"):
        bits.append("GA named by its file name only")
    if m.get("missing"):
        _miss = [str(x.get("drawing") if isinstance(x, dict) else x) for x in m["missing"]]
        bits.append(f"INCOMPLETE: {len(_miss)} made part(s) referenced with no drawing: {', '.join(_miss[:8])}")
    elif m.get("members"):
        _unread = any("text was not read" in str(a) for a in (m.get("assumptions") or []))
        bits.append("the GA's own text was not read, so its references are unchecked" if _unread
                    else "every made part the GA references has a drawing")
    if m.get("conflicts"):
        bits.append("CONFLICT: " + m["conflicts"][0])
    if m.get("bought_in_unmatched"):
        bits.append("bought-in, no drawing needed, price from catalogue or a labelled allowance: "
                    + ", ".join(map(str, m["bought_in_unmatched"][:8])))
    if m.get("question"):
        bits.append("ASK: " + m["question"])
    return "; ".join(bits)


def inputs_root() -> Path:
    """Where each row's drawings and thumbnails are copied before its run. The service's own
    reader takes files only from inside its shares (SDI_FILE_ROOTS), so the default is a
    `_held` folder under the staging share; output\\tti only when no staging root is set."""
    explicit = (os.getenv("SDI_TTI_INPUTS") or "").strip()
    if explicit:
        return Path(explicit)
    staging = (os.getenv("SDI_STAGING_ROOT") or "").strip()
    return Path(staging) / "_held" / "tti" if staging else ROOT / "output" / "tti"


# ── THE BATCH LEDGER (JG, 11 Nov 2026) ─────────────────────────────────────────────────────
# "Restarting the batch must resume outstanding work, not duplicate jobs ... keep a per-row
# record linking the pack manifest, run ID, workbook, cost, assumptions and write-back result."
# One file per sheet, beside the status file, kept across runs: a row's entry holds the pack it
# was priced from (its key), the run, the cost, what was written where, and whether the result
# is finished, ready for the estimator, or provisional. A rerun reads it before submitting.
_ENDED = ("done", "error", "cancelled", "failed", "abandoned", "timeout")


def ledger_path(sheet: Path, status_path: Optional[Path]) -> Optional[Path]:
    """Beside the status file; None (kept in memory only) when the batch keeps no status file.
    main() always passes one, so a real batch always has its ledger."""
    if not status_path:
        return None
    return status_path.parent / (re.sub(r"[^\w .-]", "_", sheet.stem) + ".ledger.json")


def load_ledger(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                                    # noqa: BLE001
        return {}


def row_key(r: Dict[str, Any]) -> str:
    return f"{r['row']}|{(r.get('drawing') or '').upper()}|{r.get('quantity')}"


def pack_key(manifest: Optional[Dict[str, Any]]) -> str:
    """The pack a row is priced from: the GA, its revision and every member file's fingerprint.
    A changed drawing is a new key, so a stored result is never reused for a different pack."""
    if not manifest:
        return ""
    import hashlib
    parts = [str(manifest.get("drawing")), str(manifest.get("revision"))]
    for x in manifest.get("members") or []:
        parts += sorted(str(f.get("fingerprint")) for f in x.get("files") or [])
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def input_key(manifest: Optional[Dict[str, Any]], r: Dict[str, Any], body_brief: str,
              method: str, client: str) -> Dict[str, Any]:
    """Everything a row's price depends on: the pack (GA, revision, files), the quantity, the
    brief and the estimating mode. A result is reused, and a written cost trusted as current,
    only while every one is unchanged."""
    import hashlib
    return {"pack": pack_key(manifest), "revision": (manifest or {}).get("revision"),
            "quantity": r.get("quantity"), "method": method, "client": client,
            "brief": hashlib.sha1(str(body_brief).encode()).hexdigest()[:12]}


def changed_inputs(before: Optional[Dict[str, Any]], now: Dict[str, Any]) -> List[str]:
    if not before:
        return []
    return [k for k in now if before.get(k) != now.get(k)]


def approval_of(item: Dict[str, Any], manifest: Optional[Dict[str, Any]]) -> str:
    """Finished is not approved (11 Nov 2026 review). "Ready for estimator approval" needs a
    verified pack AND the estimate's own tally clean: no missing costs, no provisional figures,
    no open decisions. Anything less is priced and labelled provisional, with why."""
    if item.get("state") != "done" or item.get("unit_cost") is None:
        return "not finished"
    if not item.get("written"):
        return "finished, not written"
    if item.get("write_check"):
        return "written, but the check failed: " + str(item["write_check"])[:160]
    q = item.get("quality") or {}
    gaps = [*(manifest or {}).get("missing", []), *(manifest or {}).get("bought_in_unmatched", [])]
    why = []
    if not (manifest and manifest.get("status") == "verified"):
        why.append("pack provisional" + (f" ({', '.join(map(str, gaps[:6]))})" if gaps else ""))
    if q.get("state") != "complete":
        why.append(q.get("label") or "the estimate gave no review tally")
    if not why:
        return "ready for estimator approval"
    return "provisional: estimator to review — " + "; ".join(why)


def run_batch(args: argparse.Namespace, portal: Any = None, status_path: Optional[Path] = None,
              sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    sheet = Path(args.sheet)
    cols = {"drawing": args.col_drawing, "notes": args.col_notes, "thumbs": args.col_thumbs.split(","),
            "cost": args.col_cost, "qty": getattr(args, "col_qty", "") or ""}
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
    _SIZE.clear()
    if not args.dry_run and not design.is_dir() and not proto.is_dir():
        # Every row would fall to an LLM estimate for want of a readable share, not of drawings.
        raise SystemExit(f"Neither drawing area can be read from here ({design}; {proto}), so every row "
                         f"would be priced without its drawings. Nothing was queued or written. Set "
                         f"SDI_DRIVE_MAP (W=\\\\server\\share) or the two SDI_TTI_*_ROOT settings, and run "
                         f"--dry-run until rows show their folders.")
    listings, source = area_listings(design, proto)
    _DB_ROWS.clear()
    if source.startswith("drawing index"):
        _DB_ROWS.append(True)
    out_root = inputs_root() / re.sub(r"[^\w .-]", "_", sheet.stem)
    report: Dict[str, Any] = {"sheet": str(sheet), "tab": data["sheet"], "header_row": data["header_row"],
                              "header": data["header"], "started": datetime.now().isoformat(timespec="seconds"),
                              "dry_run": bool(args.dry_run), "method": args.method,
                              "roots": {"design": str(design), "design_readable": design.is_dir(),
                                        "design_folders": len(listings[0][1]),
                                        "prototype": str(proto), "prototype_readable": proto.is_dir(),
                                        "prototype_folders": len(listings[1][1]), "source": source},
                              "rows": []}

    lpath = ledger_path(sheet, status_path)
    ledger = load_ledger(lpath)
    report["ledger"] = str(lpath) if lpath else None

    def save() -> None:
        # THE BATCH'S PULSE (SCRUM-271 review): Grid Control calls a batch stopped when this has
        # not moved for a while, so a killed batch is never shown as working for ever.
        report["updated"] = datetime.now().isoformat(timespec="seconds")
        if status_path:
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        if not args.dry_run and lpath is not None:
            lpath.parent.mkdir(parents=True, exist_ok=True)
            lpath.write_text(json.dumps(ledger, indent=1, default=str), encoding="utf-8")

    _pulse = {"at": 0.0}

    def _waiting(seconds: float) -> None:
        """Sleep while a run works, saving the status about every five minutes as a pulse."""
        sleep(seconds)
        if time.time() - _pulse["at"] >= 300:
            _pulse["at"] = time.time()
            save()

    def record(item: Dict[str, Any], r: Dict[str, Any], manifest: Optional[Dict[str, Any]]) -> None:
        """The row's line in the ledger: pack, run, workbook, cost, assumptions, write-back."""
        e = ledger.setdefault(row_key(r), {})
        e.update({"row": r["row"], "drawing": r.get("drawing"), "quantity": r.get("quantity"),
                  "pack_key": pack_key(manifest), "pack_status": (manifest or {}).get("status"),
                  "inputs": item.get("inputs") or e.get("inputs"),
                  "quality": item.get("quality"), "write_check": item.get("write_check"),
                  "tab": data["sheet"],
                  "revision": (manifest or {}).get("revision"),
                  "pack_folder": (item.get("kept") or {}).get("folder") if isinstance(item.get("kept"), dict)
                  else item.get("kept"),
                  "missing": (manifest or {}).get("missing"),
                  "bought_in_unmatched": (manifest or {}).get("bought_in_unmatched"),
                  "assumptions": (manifest or {}).get("assumptions"),
                  "run_id": item.get("run_id") or e.get("run_id"), "state": item.get("state"),
                  "unit_cost": item.get("unit_cost"), "workbook": item.get("output"),
                  "written": item.get("written"), "why": item.get("why"),
                  "approval": approval_of(item, manifest),
                  "updated": datetime.now().isoformat(timespec="seconds")})
        item["approval"] = e["approval"]
        for k in ("filed", "filed_error", "central", "central_ok"):
            if k in item:
                e[k] = item[k]

    def extras(item: Dict[str, Any], r: Dict[str, Any], manifest: Optional[Dict[str, Any]],
               output: Any, cost: Optional[float], copy: bool = True, central_too: bool = True) -> None:
        """After a finished run: the copies in the conference folder, and the cost on the central
        sheet. Neither is allowed to fail the row; each says what it did."""
        if copy:
          try:
            item["filed"] = copy_to_conference(getattr(args, "copy_to", ""), output, manifest,
                                               r.get("drawing") or "")
          except Exception as exc:                                   # noqa: BLE001
            item["filed_error"] = f"not copied to the conference folder ({exc})"
        central = getattr(args, "central_sheet", "")
        if central_too and central and cost is not None:
            import tti_central
            res = tti_central.write(central, data["sheet"], r.get("drawing") or "", r["row"],
                                    cost, drawing_ref)
            item["central"], item["central_ok"] = res.get("said"), bool(res.get("ok"))

    # THE TAB THE ROWS WERE READ FROM IS THE TAB WRITTEN TO, by name, never the active one.
    writer = None if args.dry_run else SheetWriter(sheet, data["sheet"], args.col_cost)
    priced: Dict[Tuple[str, int], Dict[str, Any]] = {}
    # ONE RUN PER DRAWING, EVERY QUANTITY THE SHEET ASKS FOR AS ITS BREAKS (11 Nov 2026 dry run:
    # 12110-01-GA1 is on five rows at 1, 2 and 3 off; three full estimates of one pack). The run
    # prices each quantity; a later row at another quantity takes that quantity's break.
    qtys_of: Dict[str, List[int]] = {}
    for _r in data["rows"]:
        if _r.get("drawing"):
            qtys_of.setdefault(_r["drawing"], [])
            if _r["quantity"] not in qtys_of[_r["drawing"]]:
                qtys_of[_r["drawing"]].append(_r["quantity"])
    runs_of: Dict[str, Dict[str, Any]] = {}
    for r in data["rows"]:
        manifest = None
        found: Dict[str, Any] = {}
        if r["drawing"]:
            found, manifest = pack_for(r["drawing"], listings, args.client)
            if not found:
                found = find_drawings(r["drawing"], listings)
        item = {"row": r["row"], "drawing": r["drawing"], "drawing_cell": r.get("drawing_cell", r["drawing"]),
                "quantity": r["quantity"],
                "kind": (f"full estimate ({manifest['status']} pack)" if manifest
                         else "full estimate (job folder)" if found.get("match") == "job folder"
                         else "full estimate") if found else "LLM estimate (no drawings found)",
                "found": {k: v for k, v in found.items() if k != "files"} if found else None,
                "files": len(found.get("files") or []) if found else 0,
                "thumbnails": len(r["pictures"]), "cost_before": r["cost_before"], "state": "planned",
                "previous": {k: (ledger.get(row_key(r)) or {}).get(k)
                             for k in ("run_id", "state", "unit_cost", "written", "approval")}
                if ledger.get(row_key(r)) else None,
                # WHAT WAS FOUND IS A CANDIDATE, NOT A VERIFIED PACK (SCRUM-199). Nothing here has read
                # the GA's title block, revision or references yet; the screen says so on every row.
                "pack": (pack_line(manifest) if manifest else PACK_JOB_FOLDER if found.get("match") == "job folder"
                         else PACK_NAMED) if found else ""}
        item["inputs"] = input_key(manifest, r, brief_for(r), args.method, args.client)
        if manifest:
            item["pack_status"] = manifest["status"]
            item["pack_detail"] = {k: manifest.get(k) for k in ("selected_folder", "revision", "revision_from",
                                                                "reason", "missing", "conflicts", "assumptions",
                                                                "question", "candidates")}
        if not found and r["drawing"]:
            item["job_folders"] = job_folders(r["drawing"], listings)
        report["rows"].append(item)
        # ONLY THE ROWS WITH A DRAWING NUMBER (JG, 10 Nov 2026): "in effect the same as a normal
        # run: the client, the number of units, the drawing pack, the description". The rest are
        # listed, not priced.
        if getattr(args, "drawings_only", False) and not r["drawing"]:
            item.update(state="skipped", kind="not priced (no drawing number)",
                        why="no drawing number on the row; --drawings-only")
            save()
            continue
        # A DRAWING PACK OR NOTHING (JG, 11 Nov 2026): "price drawing-pack rows only — no
        # thumbnail-only estimates". A number that found no drawings needs one; a job folder
        # with no resolved GA needs a person to name the pack.
        if getattr(args, "drawings_only", False) and not manifest:
            item.update(state="needs drawing" if not found else "needs decision",
                        why=("no drawings found for this number" if not found else
                             "only a job folder matched; no GA pack resolved, so it is not priced"))
            save()
            continue
        # A COST ALREADY IN THE CELL STAYS unless replacing is asked for.
        _before = r.get("cost_before")
        _prev = ledger.get(row_key(r)) or {}
        _changed = changed_inputs(_prev.get("inputs"), item["inputs"])
        if _before in (None, "") and _prev.get("written") and not _changed \
                and not getattr(args, "replace_costs", False):
            item.update(state="written before", run_id=_prev.get("run_id"),
                        why=f"an earlier batch wrote {_prev.get('unit_cost')} to "
                            f"{args.col_cost}{r['row']}, which is now empty; not written twice "
                            f"(--replace-costs to write it again)")
            save()
            continue
        if _before not in (None, "") and not getattr(args, "replace_costs", False):
            if _changed and _prev.get("written"):
                item.update(state="has a cost", outdated=_changed,
                            why=f"{args.col_cost}{r['row']} holds {_before}, priced before these "
                                f"inputs changed: {', '.join(_changed)} — kept but POSSIBLY "
                                f"OUTDATED (--replace-costs to price it again)")
                item["approval"] = "outdated: inputs changed since it was priced"
                save()
                continue
            if not (_prev.get("written") and str(_prev.get("unit_cost")) == str(_before)):
                item.update(state="has a cost", why=f"{args.col_cost}{r['row']} already holds "
                            f"{_before}; kept (--replace-costs to price and replace it)")
                save()
                continue
            item.update(state="done", unit_cost=_prev.get("unit_cost"), run_id=_prev.get("run_id"),
                        output=_prev.get("workbook"), written=_prev.get("written"),
                        why="priced and written by an earlier batch; not run again")
            item["approval"] = _prev.get("approval")
            # A ROW PRICED BEFORE THE CONFERENCE FOLDER AND THE CENTRAL SHEET EXISTED gets them
            # now, once: nothing is run again for it.
            _copy_on = str(getattr(args, "copy_to", "") or "").strip().lower() not in ("", "none", "off", "no")
            _need_copy = _copy_on and not _prev.get("filed")
            _need_central = bool(getattr(args, "central_sheet", "")) and not _prev.get("central_ok")
            if not args.dry_run and (_need_copy or _need_central):
                extras(item, r, manifest, _prev.get("workbook"), _prev.get("unit_cost"),
                       copy=_need_copy, central_too=_need_central)
                record(item, r, manifest)
            priced[(r["drawing"], r["quantity"])] = item
            save()
            continue
        save()
        # THE SAME DRAWING AT THE SAME QUANTITY IS PRICED ONCE PER BATCH; later rows take its cost.
        same = priced.get((r["drawing"], r["quantity"])) if r["drawing"] else None
        if same is not None:
            item.update(state="same as row %d" % same["row"], same_as_row=same["row"])
            if args.dry_run or same.get("unit_cost") is None:
                save()
                continue
        if same is None and manifest and not manifest["price_ok"]:
            # An ambiguity the evidence cannot settle is asked, not priced on a guess (SCRUM-199).
            # A dry run says so too: "planned" there read as if it would be priced.
            item.update(state="ask", why=manifest["question"])
            save()
            continue
        _shared = runs_of.get(r["drawing"]) if (r["drawing"] and same is None) else None
        if args.dry_run:
            if _shared is not None:
                item.update(state="same run as row %d" % _shared["row"],
                            why=f"priced from that run's {r['quantity']}-off break")
            elif r["drawing"]:
                priced[(r["drawing"], r["quantity"])] = item
                runs_of[r["drawing"]] = {"row": r["row"]}
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
        if _shared is not None and _shared.get("st") is not None:
            _bc = unit_cost_at(_shared["st"], r["quantity"])
            if _bc is not None:
                item.update(state="done", unit_cost=_bc, run_id=_shared["st"].get("run_id") or _shared.get("run_id"),
                            same_run_as_row=_shared["row"],
                            why=f"the {r['quantity']}-off break of row {_shared['row']}'s run")
                try:
                    writer.write(r["row"], _bc)
                    item["written"] = f"{args.col_cost}{r['row']} = {_bc}"
                except OSError as exc:
                    item["why"] = f"{args.col_cost}{r['row']} could not be written ({exc})"
                priced[(r["drawing"], r["quantity"])] = item
                save()
                continue
        name = re.sub(r"[^\w .-]", "_", r["drawing"] or f"row{r['row']}")
        if manifest:
            # THE PACK IS KEPT IN LIVE ENQUIRY\<client>\<drawing> (src/pack_store.py): re-used when
            # unchanged, a new version beside it when changed; the run reads the kept copy.
            import pack_store as ps
            kept = ps.store(manifest, args.client)
            item["kept"] = kept
            inputs = ps.stored_files(kept, manifest)
        else:
            inputs = copy_inputs(found.get("files") or [], [] if found else r["pictures"],
                                 out_root / f"row{r['row']}_{name}")
        if not inputs and not (r["notes"] or r["description"]):
            item.update(state="skipped", why="no drawings, pictures, description or notes to price from")
            save()
            continue
        body = {"client": args.client, "drawing_number": r["drawing"] or f"TTI-row{r['row']}",
                "source": "tti",
                "units": r["quantity"], "files": inputs, "deliverables": True,
                "quantity_breaks": sorted(q for q in qtys_of.get(r["drawing"] or "", []) if q != r["quantity"]),
                "method": args.method if found else "llm",
                "enquiry_brief": brief_for(r) + (
                    f" Drawing pack {manifest['status']}: " + "; ".join(manifest["assumptions"][:6])
                    if manifest and manifest.get("assumptions") else "")}
        # RESUME, NEVER DUPLICATE: a run an earlier batch started for this row and this same pack
        # is waited for (queued or running) or taken (done); only one that ended without a
        # result, or a changed pack, is submitted again.
        _prev = ledger.get(row_key(r)) or {}
        st = None
        if _prev.get("run_id") and not changed_inputs(_prev.get("inputs"), item["inputs"]):
            try:
                _pst = portal.status(_prev["run_id"]) or {}
            except Exception:                                            # noqa: BLE001
                _pst = {}
            _ps = str(_pst.get("status") or "")
            # A WORKER THAT WENT SILENT MAY STILL BE WORKING (row 7, 11 Nov 2026: slot 2 stopped
            # answering 40334 s in; the service failed the run, the process was never seen to
            # end). Submitting again could run the job twice and write twice, so the row is held
            # until a person confirms that worker is gone and asks for it with --resubmit-lost.
            if _ps == "error" and "stopped responding" in str(_pst.get("error") or "") \
                    and not getattr(args, "resubmit_lost", False):
                item.update(state="held: lost worker", run_id=_prev["run_id"],
                            why=f"run {_prev['run_id']} failed because {_pst.get('runner') or 'its runner'} "
                                f"stopped answering; confirm that process has ended, then run this row "
                                f"with --resubmit-lost")
                record(item, r, manifest)
                save()
                continue
            if _ps and _ps not in _ENDED:
                item.update(state="resumed", run_id=_prev["run_id"],
                            resumed=f"run {_prev['run_id']} from an earlier batch is {_ps}; waited for, not resubmitted")
                record(item, r, manifest)
                save()
                st = wait_for(portal, item["run_id"], sleep=_waiting)
            elif _ps == "done" and unit_cost_of(_pst, r["quantity"]) is not None:
                item.update(run_id=_prev["run_id"], resumed=f"run {_prev['run_id']} from an earlier batch already finished; its result is used")
                st = _pst
        if st is None:
            try:
                started = portal.start(body)
            except Exception as exc:                                     # noqa: BLE001
                _m = re.search(r"/api/estimate/([0-9a-f]{6,})/", str(exc))
                item.update(state="not queued", why=str(exc)
                            + (f" — this batch did not start run {_m.group(1)}; let it finish or stop it on "
                               f"Grid Control, then run this row again" if _m else ""))
                record(item, r, manifest)
                save()
                continue
            item.update(state="running", run_id=started.get("run_id"))
            record(item, r, manifest)
            save()
            st = wait_for(portal, item["run_id"], sleep=_waiting)
        cost = unit_cost_of(st, r["quantity"])
        item.update(state=str(st.get("status")), unit_cost=cost, output=st.get("output_path") or st.get("output"),
                    quality=st.get("quality") or None, review=st.get("review") or None)
        if r["drawing"]:
            priced[(r["drawing"], r["quantity"])] = item
            if str(st.get("status")) == "done":
                runs_of[r["drawing"]] = {"row": r["row"], "st": st, "run_id": item.get("run_id")}
        if cost is not None and str(st.get("status")) == "done":
            try:
                try:
                    _cells_before = row_cells(sheet, data["sheet"], r["row"])
                except Exception:                                        # noqa: BLE001
                    _cells_before = None
                writer.write(r["row"], cost)
                item["written"] = f"{args.col_cost}{r['row']} = {cost}"
                # READ IT BACK (11 Nov 2026 review): the cost cell holds the cost, on the named
                # tab, and nothing else on the row moved.
                if _cells_before is not None:
                    try:
                        item["write_check"] = check_write(_cells_before, row_cells(
                            sheet, data["sheet"], r["row"]), args.col_cost, cost)
                    except Exception as _wc:                             # noqa: BLE001
                        item["write_check"] = f"could not be read back ({_wc})"
                    if not item["write_check"]:
                        item["write_checked"] = (f"{args.col_cost}{r['row']} reads {cost} on "
                                                 f"'{data['sheet']}'; no other cell of the row changed")
            except OSError as exc:
                # Usually the workbook is open in Excel. The cost is kept here and in the run's
                # own folder; the row is priced, only the cell is not filled.
                item["why"] = f"priced, but {args.col_cost}{r['row']} could not be written ({exc}); close the workbook and run the row again"
        else:
            item["why"] = (st.get("error") or f"the run ended {st.get('status')} without a unit cost; "
                           f"{args.col_cost}{r['row']} left as it was")
        if cost is not None and str(st.get("status")) == "done":
            extras(item, r, manifest, item.get("output"), cost)
        record(item, r, manifest)
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
    ap.add_argument("--drawings-only", action="store_true",
                    help="price only the rows that carry a drawing number; the rest are listed, not priced")
    ap.add_argument("--replace-costs", action="store_true",
                    help="price and replace a cost already in the cost column; by default it is kept")
    ap.add_argument("--copy-to", default=os.getenv("SDI_TTI_COPY_TO") or DEFAULT_COPY_TO,
                    help="also copy each finished row's spreadsheets and GA PDF here; 'none' to stop")
    ap.add_argument("--central-sheet", default=os.getenv("SDI_TTI_CENTRAL_SHEET", ""),
                    help="also write the AI Cost on this central workbook (its SharePoint address)")
    ap.add_argument("--resubmit-lost", action="store_true",
                    help="submit again a row whose earlier run failed because its runner stopped "
                         "answering; only once that process is confirmed ended")
    ap.add_argument("--col-qty", default="", help="the number of units, e.g. N; default the column headed Qty / Quantity")
    ap.add_argument("--dry-run", action="store_true", help="find the drawings and say what would run; nothing queued or written")
    ap.add_argument("--server", default=os.getenv("SDI_SERVER", "http://localhost:8072"))
    ap.add_argument("--api-key", default=os.getenv("SDI_API_KEY", ""))
    ap.add_argument("--status-file", default="")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    # .ENV BEFORE THE SETTINGS ARE READ (11 Nov 2026): the arguments' defaults come from the
    # environment, and read before .env was loaded, SDI_TTI_CENTRAL_SHEET was empty: row 17's cost
    # never reached the central tracker, and nothing said so.
    sys.path.insert(0, str(HERE))
    try:
        import config  # noqa: F401  (loads .env)
    except Exception:                                                    # noqa: BLE001
        pass
    args = build_parser().parse_args(argv)
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
    _qh = rep["header"]
    print(f"units from column {_qh.get('quantity_column') or '-'} ({_qh.get('quantity') or 'none found: every row priced at 1'})",
          flush=True)
    print(f"copies to: {args.copy_to or 'none'}", flush=True)
    print(f"central sheet: {args.central_sheet or 'not set (SDI_TTI_CENTRAL_SHEET)'}", flush=True)
    print(f"unit cost written to column {args.col_cost.upper()} ({_qh.get('cost') or 'no header'})"
          + (" — dry run: nothing is written" if args.dry_run else ""), flush=True)
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
        print(f"row {it['row']:>4}  {shown:<28} x{it.get('quantity', 1):<5} {it['kind']:<34} {it['state']:<12} "
              f"{it.get('unit_cost', '') if it.get('unit_cost') is not None else ''}  {where}", flush=True)
        if it.get("pack"):
            print(f"{'':<11}{it['pack']}", flush=True)
        if it.get("cost_before") not in (None, "") or it.get("previous"):
            _pv = it.get("previous") or {}
            print(f"{'':<11}now in {args.col_cost.upper()}: {it.get('cost_before') if it.get('cost_before') not in (None, '') else 'empty'}"
                  + (f"; earlier run {_pv.get('run_id')} {_pv.get('state')}"
                     + (f", {_pv.get('unit_cost')}" if _pv.get('unit_cost') is not None else "")
                     + (f", {_pv.get('approval')}" if _pv.get('approval') else "") if _pv.get("run_id") else ""),
                  flush=True)
        if it.get("write_checked") or it.get("write_check"):
            print(f"{'':<11}write-back: {it.get('write_checked') or 'CHECK FAILED: ' + str(it.get('write_check'))}",
                  flush=True)
        if it.get("resumed"):
            print(f"{'':<11}{it['resumed']}", flush=True)
        if it.get("filed") or it.get("filed_error"):
            print(f"{'':<11}conference folder: {', '.join(it.get('filed') or []) or it.get('filed_error')}",
                  flush=True)
        if it.get("central"):
            print(f"{'':<11}central sheet: {it['central']}", flush=True)
        if it.get("approval") and not args.dry_run:
            print(f"{'':<11}result: {it['approval']}", flush=True)
        if it.get("why") and it.get("state") not in ("planned", "skipped"):
            # WHY A ROW WAS NOT PRICED IS SAID ON SCREEN (JG, 11 Nov 2026: row 7 showed "not
            # queued" and nothing else; the reason was only in the status file).
            print(f"{'':<11}why: {it['why']}", flush=True)
    _st: Dict[str, int] = {}
    for it in rep["rows"]:
        k = it.get("pack_status") or ("skipped" if it.get("state") == "skipped" else
                                      "job folder only" if it.get("found") else "no drawings")
        _st[k] = _st.get(k, 0) + 1
    print(f"{found} of {len(rep['rows'])} row(s) have drawings: "
          + ", ".join(f"{n} {k}" for k, n in sorted(_st.items()))
          + ". Verified: the GA's number and revision read from its title block, every part it "
            "references has a drawing and nothing bought is left to price; provisional: any of those "
            "not yet true, priced with the gaps listed; ambiguous: asked, not priced. "
          f"status file: {status}", flush=True)
    if not args.dry_run:
        _out: Dict[str, List[str]] = {}
        for it in rep["rows"]:
            a = str(it.get("approval") or "")
            k = ("priced, ready for estimator approval" if a.startswith("ready")
                 else "priced, provisional" if a.startswith("provisional")
                 else "finished, not written" if a.startswith("finished")
                 else str(it.get("state")))
            _out.setdefault(k, []).append(str(it["row"]))
        print("batch: " + "; ".join(f"{k}: rows {', '.join(v)}" for k, v in sorted(_out.items()))
              + f". ledger: {rep.get('ledger')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
