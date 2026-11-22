#!/usr/bin/env python3
"""TTI pricer: price each row of a TTI tracker spreadsheet and write the cost back (JG, 9 Nov 2026).

    python src/tti_pricer.py --sheet "C:\\...\\TRACKER - MILWAUKEE AMSTERDAM CONFERENCE 2027.xlsx" --dry-run
    python src/tti_pricer.py --sheet "<same>"                 price every row, one after another
    python src/tti_pricer.py --sheet "<same>" --rows 5-12      only those sheet rows
    python src/tti_pricer.py --sheet "<same>" --rows 134,137   exactly those rows, none between
    python src/tti_pricer.py --sheet "<same>" --walk-live      list both drawing areas live when the
                                                               index cannot be used (hours on a VPN)

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
import subprocess
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
    # THE COST COLUMN IS THE ONE HEADED AI COST, WHEREVER IT SITS (reviewer, 13 Nov 2026).
    # "Its AiCost header is in column P; the network copy previously used Q. Resolve each
    # workbook's target by its header." --col-cost is where to write only when no column is
    # headed AI Cost and the column it names carries no other header: a cost is never
    # written under somebody else's heading.
    _asked_c = col_index(cols["cost"])
    _by_head = [c for c, h in heads.items() if re.match(r"^\s*ai\s*cost\b", h, re.IGNORECASE)]
    cost_said = ""
    if len(_by_head) > 1:
        raise SystemExit(f"{sheet.name} ({ws.title}) has {len(_by_head)} columns headed AI Cost "
                         f"({', '.join(_col_letter(c) for c in _by_head)}). Nothing is written "
                         f"until one is left.")
    if _by_head:
        if _by_head[0] != _asked_c:
            cost_said = (f"the AI Cost header is in column {_col_letter(_by_head[0])}, not "
                         f"{cols['cost']}: column {_col_letter(_by_head[0])} is used")
        cols = dict(cols, cost=_col_letter(_by_head[0]))
    elif heads.get(_asked_c):
        raise SystemExit(f"No column of {sheet.name} ({ws.title}) is headed AI Cost, and column "
                         f"{cols['cost']} is headed '{heads[_asked_c]}'. Nothing is written "
                         f"under another heading: add an AI Cost header or pass --col-cost.")
    desc_c = find("description", "item", "job")
    # THE LATEST FEEDBACK (JG, 10 Nov 2026): "quantity reduced from 5 to 3", "drawings existing
    # from Rome". A column headed Feedback is part of the job's brief, beside the Notes.
    fb_c = find("feedback")
    # EVERY FEEDBACK COLUMN, EACH UNDER ITS OWN HEADING (JG and the reviewer, 14 Nov 2026). The
    # tracker now has Previous Feedback in G and Latest Feedback in H. Only the first column
    # headed Feedback was read, so H never reached the brief (row 7's red-door instruction was
    # lost), and whatever was read was labelled "Latest feedback" whichever column it came from.
    # Each is now read and said under the sheet's own heading. The notes column is said under
    # its heading too when that heading is a feedback one, and is not then repeated.
    notes_c = col_index(cols["notes"])
    notes_label = heads.get(notes_c) if re.search(r"feedback", heads.get(notes_c) or "", re.IGNORECASE) else ""
    fb_cols = [c for c, h in sorted(heads.items()) if re.search(r"\bfeedback", h, re.IGNORECASE) and c != notes_c]
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
        feedbacks = [[heads[c], str(ws.cell(r, c).value or "").strip()] for c in fb_cols]
        feedbacks = [f for f in feedbacks if f[1]]
        if not (drawing or notes or desc or pics.get(r)):
            continue
        try:
            qty = int(float(ws.cell(r, qty_c).value)) if qty_c and ws.cell(r, qty_c).value else 1
        except (TypeError, ValueError):
            qty = 1
        out.append({"row": r, "drawing": drawing_ref(drawing), "drawing_cell": drawing, "notes": notes, "description": desc,
                    "feedback": feedback, "feedbacks": feedbacks, "notes_label": notes_label,
                    "quantity": max(1, qty), "pictures": pics.get(r, []),
                    "cost_before": ws.cell(r, col_index(cols["cost"])).value})
    return {"sheet": ws.title, "header_row": header_row,
            "header": {"description": heads.get(desc_c) if desc_c else None,
                       "quantity": heads.get(qty_c) if qty_c else None,
                       "quantity_column": _col_letter(qty_c) if qty_c else None,
                       "drawing": heads.get(dcol), "cost": heads.get(col_index(cols["cost"])),
                       "notes": heads.get(notes_c),
                       "feedback": [f"{_col_letter(c)}: {heads[c]}" for c in fb_cols]},
            "cost_column": cols["cost"], "cost_column_said": cost_said,
            "rows": out}


# ── finding the drawings ────────────────────────────────────────────────────────────────

def _token(drawing: str) -> Optional[re.Pattern]:
    d = re.sub(r"\s+", "", drawing or "")
    if len(re.sub(r"\D", "", d)) < 3:
        return None
    return re.compile(r"(?<![0-9A-Za-z])" + re.escape(d).replace(r"\-", r"[-_ ]?") + r"(?![0-9])", re.IGNORECASE)


def list_folders(root: Path, depth: int = 7, say_every: int = 2000) -> List[Path]:
    """Every folder under the root, to a depth, archives skipped: walked once per batch.
    It says how far it has got: on the real share this is some 230,000 folders."""
    out: List[Path] = []
    if not root.is_dir():
        return out
    base = len(root.parts)
    started = time.time()
    for dirpath, dirnames, _files in os.walk(root):
        p = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not SKIP.search(d)]
        if len(p.parts) - base >= depth:
            dirnames[:] = []
        out.append(p)
        if say_every and len(out) % say_every == 0:
            print(f"[tti] listing {root}: {len(out)} folder(s) so far, "
                  f"{int(time.time() - started)} s", flush=True)
    return out


class IndexNotUsable(SystemExit):
    """The drawing index exists and cannot be used, and nobody asked for the long listing."""


_FILES: Dict[str, List[Path]] = {}
_MTIME: Dict[str, float] = {}
_DB_ROWS: List[bool] = []          # non-empty while the batch reads from the lookup database
_LOOKUP_INDEX: List[Path] = []     # the index that lookup reads: the one the listing came from
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


def batch_roots() -> Tuple[Path, Path]:
    """The two folders this batch finds its drawings in: its client's Design and Prototype areas."""
    from drive_map import to_unc
    return (Path(to_unc(os.getenv("SDI_TTI_DESIGN_ROOT") or DEFAULT_DESIGN)),
            Path(to_unc(os.getenv("SDI_TTI_PROTOTYPE_ROOT") or DEFAULT_PROTOTYPE)))


def scoped_index_path(client: str = "TTI") -> Path:
    """THE BATCH'S OWN INDEX (JG, 15 Nov 2026: "we only need TTI indexed... why are we indexing
    all clients"). The batch reads two folders. The only index it could use was the one of every
    customer on the share, some 230,000 folders and hours over a VPN to make. This one holds the
    batch's two folders and nothing else; --refresh-index makes it. SDI_TTI_INDEX moves it."""
    named = os.getenv("SDI_TTI_INDEX", "").strip().strip('"')
    if named:
        return Path(named)
    tag = re.sub(r"[^a-z0-9]+", "_", str(client or "tti").lower()).strip("_") or "tti"
    return ROOT / "output" / f"drawing_index_{tag}" / "index.json.gz"


def refresh_scoped_index(client: str = "TTI", say: Any = None) -> int:
    """List the batch's two folders, and only those, into its own index. 0 when both were read."""
    sys.path.insert(0, str(HERE))
    import drawing_index as di
    say = say or (lambda line: print(line, flush=True))
    design, proto = batch_roots()
    path = scoped_index_path(client)
    cfg = di.settings()
    say(f"[tti] listing this batch's two folders only, into {path}")
    say(f"[tti]   {design}")
    say(f"[tti]   {proto}")
    s = di.refresh([design, proto], path, cfg["depth"], full=False, progress=say,
                   recent_days=cfg["recent_days"])
    for r, v in s["roots"].items():
        say(f"{r}  {'readable' if v.get('readable') else 'NOT READABLE from this window'}")
    last = s["last"]
    say(f"{s['folders']} folder(s), {s['drawings']} drawing file(s); listed {last.get('listed')}, "
        f"reused {last.get('reused')}, resumed from a stopped listing {last.get('resumed', 0)}, "
        f"dormant (not checked) {last.get('dormant', 0)}, unreadable {last.get('unreadable')} "
        f"in {last.get('seconds')} s")
    ok = all(v.get("readable") for v in s["roots"].values())
    if not ok:
        say("[tti] A folder could not be read from this window, so the batch will not use this "
            "index. Check the share is reachable and run --refresh-index again.")
    return 0 if ok else 2


def _index_at(di: Any, index_file: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    try:
        db = di.db_path(index_file)
        if not db.exists() and index_file.exists():
            di.build_db(di.load(index_file) or {}, db)              # once, from the index already built
        return (di.db_meta(db), db) if db.exists() else (None, None)
    except Exception:                                                    # noqa: BLE001
        return None, None


def area_listings(design: Path, proto: Path, walk_live: bool = False, client: str = "TTI"
                  ) -> Tuple[List[Tuple[str, List[Path]]], str]:
    """The folders of both areas: from the batch's own index where it is fresh and covers them,
    else from the index of the whole share where that is, else walked live only when asked; and
    which of the three it was, said on the status and the console."""
    try:
        sys.path.insert(0, str(HERE))
        import drawing_index as di
        cfg = di.settings()
    except Exception:                                                    # noqa: BLE001
        di, cfg = None, None
    seen: List[Tuple[str, Dict[str, Any], Path]] = []
    if di is not None:
        for label, index_file in (("batch's own drawing index", scoped_index_path(client)),
                                  ("drawing index", cfg["path"])):
            idx, db = _index_at(di, index_file)
            if idx is None:
                continue
            seen.append((label, idx, db))
            if not (di.is_fresh(idx, cfg["max_hours"]) and di.covers(idx, design) and di.covers(idx, proto)):
                continue
            _LOOKUP_INDEX[:] = [Path(index_file)]        # each row's folders come from this same index
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
            # "drawing index" opens the source either way: the batch reads its rows from the
            # lookup database whenever the source starts with those words.
            return out, (f"drawing index built {datetime.fromtimestamp(idx['built_at']).isoformat(timespec='minutes')}"
                         + (" (this batch's own two folders)" if label != "drawing index" else ""))

    def _why(idx: Dict[str, Any]) -> str:
        return "is stale" if not di.is_fresh(idx, cfg["max_hours"]) else "does not cover these folders"

    why = "; ".join(f"the {label} {_why(idx)}" for label, idx, _db in seen) or "no drawing index"
    # AN INDEX THAT CANNOT BE USED STOPS THE BATCH; IT DOES NOT START A TEN-HOUR LISTING IN
    # SILENCE (15 Nov 2026). A refresh that ran while the share was away marked both areas
    # unreadable. The batch then listed every folder of both areas itself over a VPN, printing
    # nothing: one dry run sat for ten hours and a two-row run would have done the same. Where
    # an index exists, the batch says why it cannot use it, how to put that right, and stops.
    # THE REMEDY IS THE BATCH'S OWN TWO FOLDERS, NOT EVERY CUSTOMER: the remedy first given was
    # the whole-share refresh, which ran for hours listing customers this batch never reads.
    # --walk-live asks for the listing inside the run by name. With no index at all there is
    # nothing to refresh, so the two folders are listed, and said so.
    if seen and not walk_live:
        held = ""
        try:
            n = sum(len(di.db_folders_under(seen[0][2], root, include_archive=True)) for root in (design, proto))
            if n:
                held = f"The last listing of them held {n} folder(s).\n"
        except Exception:                                                # noqa: BLE001
            held = ""
        raise IndexNotUsable(
            f"The drawing index cannot be used: {why}. Nothing was listed, queued or written.\n"
            f"List this batch's own two folders, and only those: python src\\tti_pricer.py --refresh-index\n"
            f"  {design}\n  {proto}\n"
            f"{held}"
            f"It must print both as 'readable'. A listing that is stopped carries on where it left "
            f"off when run again. Then run this again.\n"
            f"To list the two folders live inside this run instead, add --walk-live.")
    print(f"[tti] LISTING THIS BATCH'S TWO DRAWING FOLDERS LIVE ({why}). Over a VPN this can take "
          f"hours; progress is printed as it goes. python src\\tti_pricer.py --refresh-index lists "
          f"them once and keeps the result.", flush=True)
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

    # ONE EXCEL, ASKED AGAIN WHILE IT IS BUSY, AND NEVER LEFT HOLDING THE FILE (16 Nov 2026).
    # Every write since Sat 20:13 failed the same way: try 1 met "Call was rejected by callee"
    # while Excel was still opening the tracker; the exception left that Excel alive with the
    # workbook open; every later try started a new Excel, which opened the file read-only and
    # could not save. Now a busy reply is waited out in the same Excel; a workbook opened
    # read-only is refused at once; and the Excel this write started is ended, whatever happened.
    BUSY = (-2147418111, -2147417846)          # RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER
    BUSY_WAIT_S = 1.0
    BUSY_TRIES = 120

    def _patient(self, call: Callable[[], Any], tries: Optional[int] = None) -> Any:
        for i in range(tries or self.BUSY_TRIES):
            try:
                return call()
            except Exception as exc:                                     # noqa: BLE001
                code = getattr(exc, "hresult", None)
                if code is None and getattr(exc, "args", None):
                    code = exc.args[0]
                if code not in self.BUSY or i == (tries or self.BUSY_TRIES) - 1:
                    raise
                time.sleep(self.BUSY_WAIT_S)

    @staticmethod
    def _excel_pids() -> set:
        """The Excel processes running now, to tell which one a try started."""
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EXCEL.EXE", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=30).stdout
            return {int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"EXCEL.EXE"')}
        except Exception:                                                # noqa: BLE001
            return set()

    @staticmethod
    def _pid_of(xl: Any) -> Optional[int]:
        try:
            import win32process
            return int(win32process.GetWindowThreadProcessId(int(xl.Hwnd))[1])
        except Exception:                                                # noqa: BLE001
            return None

    @staticmethod
    def _end(pid: Optional[int], wait_s: float = 10.0) -> None:
        """End the Excel this write started, if Quit left it running. Only that one process."""
        if not pid:
            return
        sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
        try:
            from tti_batch_lock import pid_alive
        except Exception:                                                # noqa: BLE001
            return
        end = time.time() + wait_s
        while time.time() < end and pid_alive(pid):
            time.sleep(0.5)
        if pid_alive(pid):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)

    def _excel(self, row: int, value: float) -> None:
        import win32com.client
        # AN EXCEL STILL STARTING ANSWERS "the application is busy" (16 Nov 2026, 19:35: try 1
        # failed on its very first call, before the tracker was opened). The start is waited out
        # too, and each try that does start an Excel ends it.
        before = self._excel_pids()
        try:
            xl = self._patient(lambda: win32com.client.DispatchEx("Excel.Application"), tries=60)
        except Exception:
            for _p in self._excel_pids() - before:
                self._end(_p, wait_s=0)
            raise
        pid = self._pid_of(xl) or next(iter(self._excel_pids() - before), None)
        wb = None
        try:
            for name, val in (("DisplayAlerts", False), ("AskToUpdateLinks", False), ("EnableEvents", False)):
                try:
                    self._patient(lambda: setattr(xl, name, val), tries=10)
                except Exception:                                        # noqa: BLE001
                    pass
            wb = self._patient(lambda: xl.Workbooks.Open(str(self.sheet), 0, False))
            if self._patient(lambda: bool(wb.ReadOnly)):
                raise OSError(f"the tracker copy is open somewhere else, so Excel opened it read-only; "
                              f"close it there (or end the Excel holding it) and run these rows again")
            ws = self._patient(lambda: wb.Worksheets(self.sheet_name) if self.sheet_name else wb.ActiveSheet)
            cell = self._patient(lambda: ws.Cells(row, col_index(self.col)))
            self._patient(lambda: setattr(cell, "Value", float(value)))
            self._patient(lambda: wb.Save())
        finally:
            if wb is not None:
                try:
                    self._patient(lambda: wb.Close(SaveChanges=False), tries=20)
                except Exception:                                        # noqa: BLE001
                    pass
            try:
                self._patient(lambda: xl.Quit(), tries=20)
            except Exception:                                            # noqa: BLE001
                pass
            wb = xl = None
            self._end(pid)

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


SUPPORTING_SHEETS = ("_boms_and_routes", "_pricing_variance", "_source_drawing_data")


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
        # ONLY THE ESTIMATE AND THE GA (JG, 15 Nov 2026): "ONLY the GA PDF and the s/sheet estimate"
        # go to the conference folder. A run's folder also holds the spreadsheets that support the
        # estimate (boms and routes, pricing variance, source drawing data); those stay with the
        # full extract and are not copied here.
        picks += [(f, f.name) for f in sorted(out.iterdir())
                  if f.is_file() and f.suffix.lower() in (".xlsx", ".xlsm") and not f.name.startswith("~$")
                  and not f.stem.lower().endswith(SUPPORTING_SHEETS)]
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

def parse_rows(text: Any) -> List[int]:
    """The sheet rows --rows names: "5-12", "134,137" or "10, 114, 134-137". Empty: every row."""
    out: List[int] = []
    for piece in str(text or "").replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        a, dash, b = piece.partition("-")
        try:
            lo, hi = int(a), int(b) if dash and b.strip() else int(a)
        except ValueError:
            raise SystemExit(f"--rows: '{piece}' is not a row or a range of rows (e.g. 134,137 or 5-12)")
        if lo < 1 or hi < lo:
            raise SystemExit(f"--rows: '{piece}' is not a valid range")
        out.extend(range(lo, hi + 1))
    return sorted(set(out))


def scope_text(r: Dict[str, Any]) -> str:
    """What a row asks to be made, apart from how many: its drawing cell, description, notes
    and every feedback, spaces and case aside."""
    bits = [r.get("drawing_cell"), r.get("description"), r.get("notes")]
    bits += [f"{h}:{t}" for h, t in (r.get("feedbacks") or [])]
    if not r.get("feedbacks"):
        bits.append(r.get("feedback"))
    return " | ".join(" ".join(str(b or "").split()).lower() for b in bits)


def assign_run_keys(rows: List[Dict[str, Any]]) -> None:
    """Give each row the key of the estimate it belongs to (15 Nov 2026).

    One drawing on several rows was one run: the first row's brief priced it and the other
    rows took its cost or one of its quantity breaks. A tracker lists a booth on six rows with
    different descriptions and feedback, one of them another product built on the same
    drawing; five briefs were dropped. Rows of one drawing that ask for the same thing still
    share one run and its quantity breaks. Rows whose words differ are separate estimates,
    each priced on its own brief, and say so."""
    scopes: Dict[str, List[str]] = {}
    for r in rows:
        if r.get("drawing"):
            st = scope_text(r)
            if st not in scopes.setdefault(r["drawing"], []):
                scopes[r["drawing"]].append(st)
    for r in rows:
        d = r.get("drawing") or ""
        kinds = scopes.get(d) or []
        if d and len(kinds) > 1:
            r["run_key"] = f"{d}#{kinds.index(scope_text(r)) + 1}"
            r["scope_differs"] = len(kinds)
        else:
            r["run_key"] = d


def _rk(r: Dict[str, Any]) -> str:
    return str(r.get("run_key") or r.get("drawing") or "")


def brief_for(r: Dict[str, Any]) -> str:
    parts = [f"TTI job, sheet row {r['row']}."]
    if r.get("drawing"):
        cell = str(r.get("drawing_cell") or "")
        extra = f" (the sheet says: {cell})" if cell and cell.upper() != r["drawing"] else ""
        parts.append(f"Drawing number {r['drawing']}{extra}.")
    if r.get("description"):
        parts.append(f"Description: {r['description']}.")
    if r.get("notes"):
        parts.append(f"{r.get('notes_label') or 'Notes'}: {r['notes']}.")
    if "feedbacks" in r:
        for _head, _text in r["feedbacks"]:
            parts.append(f"{_head}: {_text}.")
    elif r.get("feedback"):
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


# ── DESIGN FIRST IS LOOKED FOR, NOT HOPED FOR (JG, 15 Nov 2026) ─────────────────────────────
# "We need to take the latest one from design as the designers save there first and then would
# usually move to prototype." The resolver prefers the Design copy WHEN IT IS OFFERED ONE. An
# index that did not hold the Design area offered it none: two packs were taken from Prototype
# as PDFs and DXFs while the job's Design Technical folder held the assemblies, the parts and
# two drawings reported missing. So the job's folders in the Design area are listed NOW for
# every row, whatever the index holds, and handed to the resolver with the rest. Where the
# Design area cannot be read the row is held: a Prototype pack is never accepted unlooked.
_DIRECT: List[bool] = []           # non-empty: packs come from the job's own folders, no index


def design_root() -> Optional[Path]:
    from drive_map import to_unc
    v = (os.getenv("SDI_TTI_DESIGN_ROOT") or DEFAULT_DESIGN or "").strip()
    return Path(to_unc(v)) if v else None


def prototype_root() -> Optional[Path]:
    from drive_map import to_unc
    v = (os.getenv("SDI_TTI_PROTOTYPE_ROOT") or DEFAULT_PROTOTYPE or "").strip()
    return Path(to_unc(v)) if v else None


def job_areas() -> List[Tuple[str, Optional[Path]]]:
    """The batch's two areas in the order they are looked in: Design, then Prototype."""
    return [("Design", design_root()), ("Prototype", prototype_root())]


def pack_for(drawing: str, listings: List[Tuple[str, List[Path]]], client: str
             ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """The row's drawing pack through the shared resolver (src/pack_resolver.py, SCRUM-199): the
    same rules and manifest as the estimating page and Self-Running. ({}, None) when no file is
    named for the drawing, so the job-folder fallback can say what it found instead."""
    import pack_resolver as pr
    folders = [(f, area) for area, fs in listings for f in fs]
    if _DIRECT:
        # THE TRACKER NAMES THE JOB; THE JOB'S OWN FOLDERS ARE READ (JG, 15 Nov 2026: "we have the
        # s/sheet, we have the drawing folder name ... we never needed this crazy index"). Design
        # is listed first and Prototype after it, both now, and the resolver's own rules choose:
        # Design where it holds the drawing, Prototype only where a Design that was read does not.
        rows, said, design_rows = pr.rows_for_job_now(drawing, job_areas())
        if not rows:
            return {}, None
        # Design first is stated here, not left to a setting: a folder listed from the first
        # area ranks ahead of any other.
        from live_library_lookup import LiveLibraryLookup, library_areas
        m = pr.resolve(drawing, rows, client=client, client_folders_only=True,
                       lookup=LiveLibraryLookup(library_areas()),
                       area_rank=lambda folder: 0 if str(folder) in design_rows else 1)
        if m["status"] == "not found":
            return {}, None
        sel = str(m.get("selected_folder") or "")
        area = "design" if sel in design_rows else "prototype"
        files = [f["path"] for x in m["members"] for f in x["files"]]
        return ({"area": area, "match": "pack", "folder": sel, "files": files, "design_looked": said,
                 "technical": "technical" in sel.lower(), "newest": "",
                 "other_folders": [c["folder"] for c in m["candidates"] if c["folder"] != sel][:5]}, m)
    if _DB_ROWS:
        # THE LOOKUP DATABASE: the drawing's own and its job's folders, the GA's surroundings
        # re-listed now, and shared-library parts found anywhere: the page's and Self-Running's way.
        rows, _src, lookup = pr.folders_for(drawing, index_path=_LOOKUP_INDEX[0] if _LOOKUP_INDEX else None)
        now_rows, looked, _d = pr.rows_for_job_now(drawing, job_areas()[:1])
        if now_rows:
            listed = {os.path.normcase(str(r[0])) for r in now_rows}
            rows = [r for r in rows if os.path.normcase(str(r[0])) not in listed] + now_rows
        m = pr.resolve(drawing, rows, client=client, lookup=lookup, client_folders_only=True)
        if m["status"] == "not found":
            return {}, None
        area = "prototype" if "prototype" in str(m.get("selected_folder") or "").lower() else "design"
        files = [f["path"] for x in m["members"] for f in x["files"]]
        return ({"area": area, "match": "pack", "folder": m.get("selected_folder"), "files": files,
                 "design_looked": looked,
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


def _formats(files: Iterable[str]) -> Dict[str, int]:
    """How many of the pack's files are of each kind, the most first: a pack with no model
    files is seen at a glance, before it is priced."""
    out: Dict[str, int] = {}
    for f in files:
        ext = Path(str(f)).suffix.lower().lstrip(".") or "no extension"
        out[ext] = out.get(ext, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


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


def ledger_folders() -> List[Path]:
    """Every folder a batch keeps a ledger in: the command line's (output/tti), the services'
    shared state folder, and any named in SDI_TTI_LEDGER_DIRS."""
    out = [ROOT / "output" / "tti"]
    try:
        _b = str(ROOT / "sdi-intelligence-backend")
        if _b not in sys.path:
            sys.path.append(_b)      # after src: the engine's own modules are found first
        import estimate_email
        out.append(estimate_email.state_dir() / "tti")
    except Exception:                                                    # noqa: BLE001
        pass
    out += [Path(x.strip()) for x in os.getenv("SDI_TTI_LEDGER_DIRS", "").split("|") if x.strip()]
    return out


def load_ledgers(path: Optional[Path], folders: Optional[Iterable[Path]] = None
                 ) -> Tuple[Dict[str, Any], List[str]]:
    """ONE HISTORY FOR A SHEET, WHEREVER THE BATCH WAS STARTED (15 Nov 2026). The command line
    kept its ledger in output/tti and the page's button kept its own in the state folder, so a
    row the one had sent, and whose outcome was not known, looked never-run to the other. The
    ledger of this sheet in every such folder is read; a row is taken from the one that wrote
    it last. Returns (ledger, what was taken from elsewhere)."""
    ledger = load_ledger(path)
    said: List[str] = []
    if path is None:
        return ledger, said
    for folder in (ledger_folders() if folders is None else folders):
        other = Path(folder) / path.name
        try:
            if other.resolve() == path.resolve() or not other.is_file():
                continue
        except OSError:
            continue
        took = 0
        for key, entry in load_ledger(other).items():
            mine = ledger.get(key)
            if not isinstance(entry, dict):
                continue
            if mine is None or str(entry.get("updated") or "") > str(mine.get("updated") or ""):
                ledger[key] = entry
                took += 1
        if took:
            said.append(f"{took} row(s) of history taken from {other}")
    return ledger, said


def numbers_in(text: Any) -> List[int]:
    return sorted({int(x) for x in re.findall(r"\d+", str(text or ""))})


def next_rows(rows: List[Dict[str, Any]], ledger: Dict[str, Any], from_row: int = 0,
              held_rows: Iterable[int] = (), held_drawings: Iterable[str] = ()
              ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """THE NEXT ROWS NOT YET RUN, IN SHEET ORDER (JG, 15 Nov 2026: "set the number of jobs we
    want to run next based on where we are on the sheet list"). A row is next when it has a
    drawing number, no cost in its cell, no earlier attempt of any kind on record, and is not
    held. Every other row from the starting row on is returned with its reason; an earlier
    attempt is never retried by being "next": it is named with --rows."""
    held_rows = {int(x) for x in held_rows}
    held_drawings = {str(d).strip().upper() for d in held_drawings if str(d).strip()}
    seen = {}
    for e in ledger.values():
        if isinstance(e, dict) and e.get("row") is not None:
            seen.setdefault((int(e["row"]), str(e.get("drawing") or "").upper()), e)
    out: List[Dict[str, Any]] = []
    passed: List[Dict[str, Any]] = []
    for r in rows:
        if r["row"] < int(from_row or 0):
            continue
        drawing = str(r.get("drawing") or "").upper()
        before = seen.get((int(r["row"]), drawing))
        why = ("no drawing number" if not drawing else
               "held: this row is on the hold list" if r["row"] in held_rows else
               "held: this drawing is on the hold list" if drawing in held_drawings else
               "has a cost" if r.get("cost_before") not in (None, "") else
               (f"an earlier attempt is on record ({before.get('state')}"
                + (f", run {before.get('run_id')}" if before.get("run_id") else "")
                + f"); name it with --rows {r['row']} to carry it on") if before else "")
        if why:
            passed.append({"row": r["row"], "drawing": r.get("drawing") or "", "why": why})
        else:
            out.append(r)
    return out, passed


def claim_one_writer(task: str) -> str:
    """ONE WRITER ON THE TRACKER, THE COMMAND LINE INCLUDED (15 Nov 2026). The page's buttons
    refused a second batch through a claim in the shared state folder; a batch started from a
    command window took no claim, so the page could start another beside it. '' when this
    process now holds the claim, else what to say."""
    try:
        _b = str(ROOT / "sdi-intelligence-backend")
        if _b not in sys.path:
            sys.path.append(_b)      # after src: the engine's own modules are found first
        import estimate_email
        import tti_batch_lock
    except Exception as exc:                                             # noqa: BLE001
        return f"the one-writer claim could not be loaded ({exc})"
    try:
        tti_batch_lock.claim(estimate_email.state_dir() / "tti" / "batch.lock", task, os.getpid())
    except tti_batch_lock.Busy as exc:
        return str(exc)
    except OSError as exc:
        return f"the one-writer claim could not be written ({exc})"
    return ""


def release_one_writer() -> None:
    try:
        import estimate_email
        import tti_batch_lock
        tti_batch_lock.release(estimate_email.state_dir() / "tti" / "batch.lock", os.getpid())
    except Exception:                                                    # noqa: BLE001
        pass


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
    from batch_job_changes import fingerprint
    return {"pack": pack_key(manifest), "revision": (manifest or {}).get("revision"),
            "quantity": r.get("quantity"), "method": method, "client": client,
            "brief": hashlib.sha1(str(body_brief).encode()).hexdigest()[:12],
            **({'customer_changes': fingerprint(r['_customer_changes'])} if r.get('_customer_changes') else {})}


def changed_inputs(before: Optional[Dict[str, Any]], now: Dict[str, Any]) -> List[str]:
    if not before:
        return ['customer_changes'] if now.get('customer_changes') else []
    keys = set(now) | ({'customer_changes'} if before.get('customer_changes') else set())
    return sorted(k for k in keys if before.get(k) != now.get(k))


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


# ── THE PACKS ALREADY CHECKED (15 Nov 2026) ─────────────────────────────────────────────────
# The pack check (src/tti_preflight.py) names, per drawing, every file of the pack it resolved
# and each file's fingerprint. A batch given that report prices ONLY those packs, and only where
# the pack found again now is the same files with the same fingerprints. It then needs no
# listing of the drawing areas: the lookup database finds the drawing's folders and the folder
# round each candidate GA is listed again now, as the pack check itself did. "We already have an
# index and checked packs. We do not need another whole-share scan to start those."
def _pack_files(manifest: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for member in (manifest or {}).get("members") or []:
        for f in member.get("files") or []:
            out[os.path.normcase(os.path.normpath(str(f.get("path") or "")))] = str(f.get("fingerprint") or "")
    return out


def load_checked_packs(path: Any) -> Dict[str, Dict[str, str]]:
    """{DRAWING: {file: fingerprint}} for every pack the report resolved. Raises SystemExit
    when the report cannot be read or resolved nothing: a batch is never run on an empty check."""
    try:
        report = json.loads(Path(str(path)).read_text(encoding="utf-8-sig"))
        rows = report["rows"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"The pack check report could not be read ({path}: {type(exc).__name__}). "
                         f"Nothing was queued or written.")
    out: Dict[str, Dict[str, str]] = {}
    for r in rows:
        pack = r.get("pack") or {}
        files = _pack_files(pack.get("manifest"))
        if pack.get("state") == "resolved" and files and r.get("drawing"):
            out[str(r["drawing"]).strip().upper()] = files
    if not out:
        raise SystemExit(f"The pack check report {path} resolved no pack. Nothing was queued or written.")
    return out


def checked_pack_difference(checked: Dict[str, Dict[str, str]], drawing: str,
                            manifest: Optional[Dict[str, Any]]) -> str:
    """Why this row's pack is not the pack that was checked, or "" when it is that pack."""
    was = checked.get(str(drawing or "").strip().upper())
    if was is None:
        return "its pack is not one the pack check resolved"
    now = _pack_files(manifest)
    if not now:
        return "the checked pack was not found again"
    added = sorted(set(now) - set(was))
    gone = sorted(set(was) - set(now))
    changed = sorted(k for k in set(now) & set(was) if now[k] != was[k])
    if not (added or gone or changed):
        return ""
    said = [f"{len(n)} file(s) {w}: {Path(n[0]).name}" + (f" and {len(n) - 1} more" if len(n) > 1 else "")
            for n, w in ((added, "not in the checked pack"), (gone, "of the checked pack not in it now"),
                         (changed, "changed since the check")) if n]
    return "the pack found now differs from the pack that was checked (" + "; ".join(said) + ")"


def runs_after_no_answer(portal: Any, drawing: str, quantity: Any, asked_at: float, wait_s: float = 600.0,
                         every_s: float = 15.0, sleep: Callable[[float], None] = time.sleep,
                         say: Callable[[str], None] = lambda m: print(m, flush=True)
                         ) -> Tuple[List[str], bool]:
    """After a request that got no answer: (the runs the service holds that this row could have
    asked for, whether the service was heard at all). A run is this row's only when it is the
    tracker's own source, the same drawing AND the same number of units, queued since the
    request left. The caller takes a run up only when there is exactly one; with none, several,
    or a service that could not be asked, the outcome is not known and nothing is sent."""
    tries = max(1, int(wait_s // max(every_s, 0.001)) + 1)
    say(f"[tti] the service did not answer the request for {drawing}; asking it whether it holds the run "
        f"(up to {wait_s:g} s). Nothing is sent again while the outcome is not known")
    heard = False
    for n in range(tries):
        try:
            runs = (portal.recent(100) or {}).get("runs") or []
            heard = True
        except Exception:                                                # noqa: BLE001
            runs = []
        mine = [x for x in runs
                if str(x.get("drawing_number") or "").strip().upper() == str(drawing).strip().upper()
                and str(x.get("source") or "") == "tti"
                and str(x.get("units")) == str(quantity)
                and float(x.get("queued_at") or 0) >= asked_at - 5]
        if mine:
            return sorted({str(x.get("run_id")) for x in mine}), True
        if n + 1 < tries:
            sleep(every_s)
    return [], heard


def take_ups(values: Any) -> Dict[int, str]:
    """--take-up 3=e2639e873262: the run that is a row's, named by the person who can see it."""
    out: Dict[int, str] = {}
    for v in values or []:
        m = re.fullmatch(r"\s*(\d+)\s*=\s*([0-9a-fA-F]{6,})\s*", str(v))
        if not m:
            raise SystemExit(f"--take-up is ROW=RUN, e.g. 3=e2639e873262; this is not: {v!r}. "
                             f"Nothing was queued or written.")
        out[int(m.group(1))] = m.group(2).lower()
    return out


def run_is_the_rows(portal: Any, run_id: str, r: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the run's status, "") when the named run is for this row's drawing and units; else (None, why)."""
    try:
        st = portal.status(run_id) or {}
    except Exception as exc:                                             # noqa: BLE001
        return None, f"run {run_id} could not be read from the service ({exc})"
    if str(st.get("drawing_number") or "").strip().upper() != str(r.get("drawing") or "").strip().upper():
        return None, f"run {run_id} is for {st.get('drawing_number') or 'no drawing'}, not {r.get('drawing')}"
    if str(st.get("units")) != str(r.get("quantity")):
        return None, f"run {run_id} is for {st.get('units')} unit(s), not this row's {r.get('quantity')}"
    return st, ""


OUTCOME_NOT_KNOWN = "outcome not known"


def run_batch(args: argparse.Namespace, portal: Any = None, status_path: Optional[Path] = None,
              sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    from batch_job_changes import load_changes, bind_changes
    changes = load_changes(getattr(args, 'job_changes', ''), args.client)
    if changes and (getattr(args, 'write_only', False) or getattr(args, 'take_up', [])):
        raise ValueError('Job changes cannot be applied by write-only or take-up of an old result')
    sheet = Path(args.sheet)
    cols = {"drawing": args.col_drawing, "notes": args.col_notes, "thumbs": args.col_thumbs.split(","),
            "cost": args.col_cost, "qty": getattr(args, "col_qty", "") or ""}
    wanted = parse_rows(args.rows)
    rows = (min(wanted), max(wanted)) if wanted else None
    data = read_rows(sheet, cols, rows, args.sheet_name)
    if wanted:
        # ONLY THE ROWS NAMED. A range read everything between its ends, so approving rows 134
        # and 137 also ran 135 and 136, which had been held (15 Nov 2026).
        _named = set(wanted)
        _got = {r["row"] for r in data["rows"]}
        data["rows"] = [r for r in data["rows"] if r["row"] in _named]
        _absent = sorted(_named - _got)
        if _absent:
            print(f"[tti] row(s) {', '.join(map(str, _absent))} named in --rows are not job rows "
                  f"of this sheet and are left out", flush=True)
    _only = {d.strip().upper() for d in str(getattr(args, "drawings", "") or "").split(",") if d.strip()}
    if _only:
        # THE DRAWINGS NAMED, AND ONLY THEM: one job, or a few, picked by number.
        _have = {str(r.get("drawing") or "").upper() for r in data["rows"]}
        data["rows"] = [r for r in data["rows"] if str(r.get("drawing") or "").upper() in _only]
        if _only - _have:
            print(f"[tti] drawing(s) {', '.join(sorted(_only - _have))} named in --drawings are on no "
                  f"job row of this sheet and are left out", flush=True)
    bind_changes(data['rows'], changes)
    assign_run_keys(data["rows"])
    if data.get("cost_column") and data["cost_column"] != args.col_cost:
        print(f"[tti] {data.get('cost_column_said')}", flush=True)
        args.col_cost = data["cost_column"]
    design, proto = batch_roots()
    _FILES.clear()
    _MTIME.clear()
    _SIZE.clear()
    if not args.dry_run and not design.is_dir() and not proto.is_dir():
        # Every row would fall to an LLM estimate for want of a readable share, not of drawings.
        raise SystemExit(f"Neither drawing area can be read from here ({design}; {proto}), so every row "
                         f"would be priced without its drawings. Nothing was queued or written. Set "
                         f"SDI_DRIVE_MAP (W=\\\\server\\share) or the two SDI_TTI_*_ROOT settings, and run "
                         f"--dry-run until rows show their folders.")
    _checked = load_checked_packs(args.checked_packs) if getattr(args, "checked_packs", "") else None
    _DB_ROWS.clear()
    _LOOKUP_INDEX.clear()
    _DIRECT.clear()
    try:
        import pack_resolver as _pr
        _pr.forget_job_folders()
    except Exception:                                                    # noqa: BLE001
        pass
    if not getattr(args, "use_index", False) and _checked is None and not getattr(args, "walk_live", False):
        listings = [("design", []), ("prototype", [])]
        source = "each job's own folders, listed now (no index)"
        print("PACKS: each row's job is looked for in the Design area, then the Prototype area, now. "
              "No index is used and neither area is listed whole.", flush=True)
        _DIRECT.append(True)
    elif _checked is not None:
        # No listing of either area: each row's pack comes from the lookup database with the
        # GA's own folders listed again now, and is held unless it is the pack that was checked.
        listings = [("design", []), ("prototype", [])]
        source = f"checked packs ({len(_checked)} in {Path(str(args.checked_packs)).parent.name})"
        print(f"PACKS: only the {len(_checked)} the pack check resolved, each compared with it file by "
              f"file. The drawing areas are not listed.", flush=True)
        _DB_ROWS.append(True)
    else:
        listings, source = area_listings(design, proto, walk_live=bool(getattr(args, "walk_live", False)),
                                         client=str(getattr(args, "client", "") or "TTI"))
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
    ledger, _elsewhere = load_ledgers(lpath, getattr(args, "ledger_folders", None) or ())
    report["ledger"] = str(lpath) if lpath else None
    for _line in _elsewhere:
        print(f"[tti] ledger: {_line}", flush=True)
    _next = max(0, int(getattr(args, "next", 0) or 0))
    _sent = 0
    _again = bool(getattr(args, "run_again", False))
    if _next:
        data["rows"], _passed = next_rows(
            data["rows"], ledger, int(getattr(args, "from_row", 0) or 0),
            numbers_in(getattr(args, "hold_rows", "")),
            str(os.getenv("SDI_TTI_HOLD_OUT", "")).split(","))
        report["next"] = {"asked": _next, "from_row": int(getattr(args, "from_row", 0) or 0),
                          "passed_over": _passed}
        _by: Dict[str, int] = {}
        for _p in _passed:
            _by[_p["why"].split(" (")[0].split(":")[0]] = _by.get(_p["why"].split(" (")[0].split(":")[0], 0) + 1
        print(f"NEXT {_next}: the next {_next} row(s) not yet run, in sheet order"
              + (f", from row {report['next']['from_row']}" if report["next"]["from_row"] else "")
              + ". Passed over: " + ("; ".join(f"{n} {k}" for k, n in _by.items()) or "none"), flush=True)
        for _p in _passed:
            if _p["why"].startswith(("held", "an earlier")):
                print(f"{'':<6}row {_p['row']} {_p['drawing']}: {_p['why']}", flush=True)

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
        if item.get('state') == 'done':
            if item.get('resumed') or item.get('run_id') == (item.get('previous') or {}).get('run_id'):
                item['result_origin'] = 'existing run collected; not proof of a new estimate'
            else:
                item.setdefault('result_origin', 'existing or shared run; freshness not established')
        e = ledger.setdefault(row_key(r), {})
        if e.get("run_id") and item.get("run_id") and e["run_id"] != item["run_id"]:
            # A ROW RUN AGAIN KEEPS ITS EARLIER RUN ON RECORD: nothing of it is overwritten.
            e.setdefault("earlier", []).append({k: e.get(k) for k in (
                "run_id", "state", "unit_cost", "workbook", "written", "updated", "pack_key", "approval")})
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
        for k in ("filed", "filed_error", "central", "central_ok", "result_origin"):
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
                                    cost, drawing_ref, quantity=r.get("quantity"))
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
            qtys_of.setdefault(_rk(_r), [])
            if _r["quantity"] not in qtys_of[_rk(_r)]:
                qtys_of[_rk(_r)].append(_r["quantity"])
    runs_of: Dict[str, Dict[str, Any]] = {}
    # TWO RUNNERS, TWO JOBS AT ONCE (JG, 14 Nov 2026: "we want two at once.. we have two
    # runners"). The batch queued a job and waited for it, so the second runner sat idle
    # through every tracker batch. With --at-once N (SDI_TTI_AT_ONCE) up to N runs are open
    # together. Everything that writes (the tracker cell, the ledger, the copies) is still done
    # by this one process, one finished run at a time, so no two writers meet. A later row for
    # a drawing still in flight waits for that run and takes its break, as before.
    at_once = max(1, int(getattr(args, "at_once", 1) or 1))
    _take_up = take_ups(getattr(args, "take_up", []))
    in_flight: List[List[Any]] = []

    def _finish(item, r, manifest, st) -> None:
        _finish_body(item, r, manifest, st, args=args, sheet=sheet, data=data, writer=writer,
                     priced=priced, runs_of=runs_of, extras=extras, record=record, save=save)

    def _finish_one(drawing: str = "") -> None:
        """Wait until one open run ends (the named drawing's, when given) and write it back."""
        while True:
            for entry in list(in_flight):
                _item, _r, _manifest, _deadline = entry
                if drawing and _r.get("drawing") != drawing:
                    continue
                try:
                    _st = portal.status(_item["run_id"]) or {}
                except Exception:                                    # noqa: BLE001
                    _st = {}
                if str(_st.get("status") or "") not in ("done", "error", "cancelled", "failed", "abandoned"):
                    if time.time() < _deadline:
                        continue
                    _st = {"status": "timeout"}
                in_flight.remove(entry)
                _finish(_item, _r, _manifest, _st)
                return
            _waiting(30)

    for r in data["rows"]:
        if _next and _sent >= _next:
            report["next"]["stopped_before_row"] = r["row"]
            break
        # A ROW FOR A DRAWING STILL RUNNING WAITS FOR IT: its cost may be that run's break.
        if r.get("drawing") and any(x[1].get("drawing") == r["drawing"] for x in in_flight):
            _finish_one(r["drawing"])
        manifest = None
        found: Dict[str, Any] = {}
        _stalled = ""
        if r["drawing"]:
            try:
                found, manifest = pack_for(r["drawing"], listings, args.client)
            except Exception as _exc:                                    # noqa: BLE001
                if type(_exc).__name__ != "PackCheckStalled":
                    raise
                # AN UNCHECKED PACK IS HELD, NOT PRICED FROM A FOLDER GUESS (14 Nov 2026).
                _stalled = str(_exc)
            if not found and not _stalled:
                found = find_drawings(r["drawing"], listings)
        item = {"row": r["row"], "drawing": r["drawing"], "drawing_cell": r.get("drawing_cell", r["drawing"]),
                "quantity": r["quantity"],
                "own_brief": (f"priced on this row's own brief: {r['drawing']} is on rows with "
                              f"{r['scope_differs']} different descriptions or feedback"
                              if r.get("scope_differs") else None),
                "kind": (f"full estimate ({manifest['status']} pack)" if manifest
                         else "full estimate (job folder)" if found.get("match") == "job folder"
                         else "full estimate") if found else "LLM estimate (no drawings found)",
                "found": {k: v for k, v in found.items() if k != "files"} if found else None,
                "files": len(found.get("files") or []) if found else 0,
                "formats": _formats(found.get("files") or []) if found else None,
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
        if _checked is not None and r["drawing"] and not _stalled:
            _differs = checked_pack_difference(_checked, r["drawing"], manifest)
            if _differs:
                item.update(state="held: not the checked pack", kind="not priced (not the checked pack)",
                            why=f"{_differs}. Nothing is queued; run the pack check again for this row")
                save()
                continue
        if _stalled:
            item.update(state="held: pack not checked", kind="not priced (pack not checked)",
                        why=f"{_stalled}. Nothing is queued from an unchecked pack; run the row again")
            save()
            continue
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
                            f"{_before}; kept (--replace-costs allows write-back/reuse; --run-again requests a fresh finished-row estimate)")
                save()
                continue
            item.update(state="done", unit_cost=_prev.get("unit_cost"), run_id=_prev.get("run_id"),
                        result_origin='existing run collected; not proof of a new estimate',
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
            priced[(_rk(r), r["quantity"])] = item
            save()
            continue
        save()
        # THE SAME DRAWING AT THE SAME QUANTITY IS PRICED ONCE PER BATCH; later rows take its cost.
        same = priced.get((_rk(r), r["quantity"])) if r["drawing"] else None
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
        _shared = runs_of.get(_rk(r)) if (r["drawing"] and same is None) else None
        if args.dry_run:
            if _shared is not None:
                item.update(state="same run as row %d" % _shared["row"],
                            why=f"priced from that run's {r['quantity']}-off break")
            elif r["drawing"]:
                priced[(_rk(r), r["quantity"])] = item
                runs_of[_rk(r)] = {"row": r["row"]}
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
                priced[(_rk(r), r["quantity"])] = item
                save()
                continue
        name = re.sub(r"[^\w .-]", "_", r["drawing"] or f"row{r['row']}")
        if manifest:
            # THE PACK IS KEPT IN LIVE ENQUIRY\<client>\<drawing> (src/pack_store.py): re-used when
            # unchanged, a new version beside it when changed; the run reads the kept copy.
            import pack_store as ps
            # THE RUN IS HANDED THE PACK THAT WAS FOUND, WHOLE, OR NOTHING IS SENT (15 Nov 2026).
            # 12736-00-01: discovery found the top-level assembly PDF; the saved pack did not
            # hold it; the service skipped the missing path and the estimate was made from the
            # other fifteen sheets, with a sub-assembly taken as the main drawing.
            _short = ""
            try:
                # A PACK A PERSON MADE IS USED ONLY ON A ONE-JOB RUN; a batch always takes the
                # pack from W: again (JG, 15 Nov 2026).
                # --write-only starts nothing, so it takes no new copy of the pack: it would be a
                # version folder no run ever read.
                kept = ps.store(manifest, args.client,
                                honour_hand_made=len(data["rows"]) == 1 and not _next,
                                fresh=not getattr(args, "write_only", False))
                item["kept"] = {k: v for k, v in kept.items() if k != "copies"}
                inputs = ps.stored_files(kept, manifest)
                _gone = ps.not_there(inputs)
                _top = ps.top_level_absent(manifest, inputs)
                if _gone:
                    _short = (f"{len(_gone)} file(s) of the pack are not in {kept.get('folder')}: "
                              + ", ".join(_gone[:6]))
                elif not any(str(x).lower().endswith(".pdf") for x in inputs):
                    # NO PDF, NO ESTIMATE (18 Nov 2026): the engine builds a job from its PDF
                    # drawings. 7758B-01 and 12132-01-GA went out with SolidWorks files and flat
                    # DXFs only and stopped in seconds with "No drawing files found", every time.
                    _short = (f"the pack in {kept.get('folder')} holds no PDF drawing (only "
                              + ", ".join(sorted({Path(str(x)).suffix.upper().lstrip('.') or '?' for x in inputs}))
                              + "); the engine prices from the GA's PDF: Design to save the GA and part "
                                "drawings as PDF")
                elif _top:
                    _short = (f"the top-level drawing {_top} is not among the files in "
                              f"{kept.get('folder')} ({kept.get('state')})")
            except OSError as _exc:
                inputs = []
                _short = f"the pack could not be saved or read where it is kept ({_exc})"
            if _short:
                item.update(state="held: pack not complete", kind="not priced (pack not complete)",
                            why=f"{_short}. Nothing is queued: an estimate is not made from part of a pack")
                save()
                continue
        else:
            inputs = copy_inputs(found.get("files") or [], [] if found else r["pictures"],
                                 out_root / f"row{r['row']}_{name}")
        if not inputs and not (r["notes"] or r["description"]):
            item.update(state="skipped", why="no drawings, pictures, description or notes to price from")
            save()
            continue
        body = {"client": args.client, "drawing_number": r["drawing"] or f"TTI-row{r['row']}",
                **({'customer_changes': r['_customer_changes']} if r.get('_customer_changes') else {}),
                "source": "tti",
                "units": r["quantity"], "files": inputs, "deliverables": True,
                "quantity_breaks": sorted(q for q in qtys_of.get(_rk(r), []) if q != r["quantity"]),
                "method": args.method if found else "llm",
                # THE PACK'S OWN RECORD TRAVELS WITH THE JOB (15 Nov 2026): what was found, where
                # each file was copied from and to, and what the drawings call for that was not
                # found. Without it the covering e-mail said "No pack manifest was saved with
                # this job" on every tracker estimate.
                "pack_manifest": (json.loads(json.dumps(dict(
                    manifest, stored=kept, staged_from="the TTI tracker batch",
                    discovery=str(found.get("design_looked") or ""),
                    taken_from={"area": found.get("area"), "folder": str(found.get("folder") or "")}),
                    default=str)) if manifest else None),
                "enquiry_brief": brief_for(r) + (
                    f" Drawing pack {manifest['status']}: " + "; ".join(manifest["assumptions"][:6])
                    if manifest and manifest.get("assumptions") else "")}
        # RESUME, NEVER DUPLICATE: a run an earlier batch started for this row and this same pack
        # is waited for (queued or running) or taken (done); only one that ended without a
        # result, or a changed pack, is submitted again.
        _prev = ledger.get(row_key(r)) or {}
        st = None
        if _again and not (str(_prev.get("state")) == "done" and _prev.get("unit_cost") is not None
                           and _prev.get("run_id")):
            # RUN AGAIN IS FOR A ROW THAT FINISHED (JG, 15 Nov 2026: "re run a row we already
            # have ran"). A row never run is simply run; one whose last attempt failed, is still
            # going or has an unknown outcome is recovered, which is a different thing.
            item.update(state="held: not a finished row",
                        why=("this row has no finished run on record"
                             + (f" (its last attempt: {_prev.get('state')})" if _prev else "")
                             + "; --run-again starts a new estimate only for a row that finished. "
                               "Nothing was sent"))
            save()
            continue
        _wo = bool(getattr(args, "write_only", False))
        _moved = changed_inputs(_prev.get("inputs"), item["inputs"])
        if 'customer_changes' in _moved and _prev.get('run_id'):
            # A changed instruction never silently duplicates an existing/unknown run.
            try:
                previous_status = portal.status(_prev['run_id']) or {}
            except Exception:
                previous_status = {}
            if previous_status.get('status') not in _ENDED:
                item.update(state='held: changed instructions while prior outcome unresolved',
                            why='Existing run must end and be reconciled before changed materials are submitted')
                save()
                continue
        if _wo and _moved and _prev.get("run_id"):
            # Written as that run's cost, and said: the pack or brief has moved since.
            item["outdated"] = _moved
        if _prev.get("run_id") and (not _moved or _wo):
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
            if _ps and _ps not in _ENDED and getattr(args, "write_only", False):
                item.update(state="still running", run_id=_prev["run_id"],
                            why=f"run {_prev['run_id']} is {_ps}; --write-only waits for nothing: run it again when it has finished")
                record(item, r, manifest)
                save()
                continue
            if _ps and _ps not in _ENDED:
                item.update(state="resumed", run_id=_prev["run_id"],
                            resumed=f"run {_prev['run_id']} from an earlier batch is {_ps}; waited for, not resubmitted")
                record(item, r, manifest)
                save()
                st = wait_for(portal, item["run_id"], sleep=_waiting)
            elif _ps == "done" and unit_cost_of(_pst, r["quantity"]) is not None and not _again:
                item.update(run_id=_prev["run_id"], resumed=f"run {_prev['run_id']} from an earlier batch already finished; its result is used")
                st = _pst
        if st is None and _wo and _prev.get("unit_cost") is not None:
            # THE SERVICE NO LONGER HOLDS THE RUN: the ledger's own record of it is the result.
            st = {"status": "done", "run_id": _prev.get("run_id"), "output_path": _prev.get("workbook"),
                  "quantity_prices": [{"quantity": r["quantity"], "unit_gbp": _prev["unit_cost"]}]}
            item.update(run_id=_prev.get("run_id"), resumed=f"run {_prev.get('run_id')}'s cost from the batch ledger")
        if st is None and getattr(args, "write_only", False):
            # WRITE BACK, NEVER PRICE (11 Nov 2026 review: "recover row 18's cost from its existing
            # completed run without allowing a new submission"). With no finished run on record
            # for these same inputs there is nothing to write, and that is said.
            _why_not = ("no run is on record for this row" if not _prev.get("run_id") else
                        "its inputs have changed since it was priced: " + ", ".join(changed_inputs(_prev.get("inputs"), item["inputs"]) or ["unknown"])
                        if changed_inputs(_prev.get("inputs"), item["inputs"]) else
                        f"run {_prev.get('run_id')} gave no usable result")
            item.update(state="nothing to write", why=f"{_why_not}; --write-only never starts an estimate")
            save()
            continue
        if st is None:
            _asked_at = time.time()
            _failed: Optional[BaseException] = None
            started = None
            _hold = ""
            # A ROW IS NEVER SENT WHILE AN EARLIER REQUEST'S OUTCOME IS NOT KNOWN (15 Nov 2026).
            # Row 3's request got no answer and the service ran the job all the same. The run that
            # is the row's is taken up when a person names it (--take-up ROW=RUN) and it is for
            # this drawing and these units, or when the service shows exactly one such run.
            # Otherwise nothing is sent: not on a lookup that failed, not on "none found", not by
            # picking the newest of several. --resubmit-lost says, by hand, that there is no run.
            _named = _take_up.get(int(r["row"]))
            _uncertain = str(_prev.get("state")) == OUTCOME_NOT_KNOWN or (
                str(_prev.get("state")) == "not queued" and "did not answer" in str(_prev.get("why") or ""))
            if _named:
                _st, _why = run_is_the_rows(portal, _named, r)
                if _st is None:
                    _hold = f"--take-up was refused: {_why}. Nothing was sent"
                else:
                    started = {"run_id": _named}
                    item["resumed"] = f"run {_named} was named as this row's and is taken up; nothing was sent"
            elif _uncertain and r.get("drawing") and not getattr(args, "resubmit_lost", False):
                try:
                    _then = datetime.fromisoformat(str(_prev.get("updated"))).timestamp()
                except (TypeError, ValueError):
                    _then = None
                _found, _heard = runs_after_no_answer(portal, r["drawing"], r["quantity"], _then - 900,
                                                      wait_s=0, sleep=sleep) if _then else ([], False)
                if len(_found) == 1:
                    started = {"run_id": _found[0]}
                    item["resumed"] = (f"the last request for this row got no answer, but the service holds "
                                       f"exactly one run for it: run {_found[0]} is taken up, nothing was sent")
                else:
                    _hold = ("the last request for this row got no answer and its outcome is still not known: "
                             + ("the service could not be asked" if not _heard else
                                f"the service shows {len(_found)} runs that could be it ({', '.join(_found)})"
                                if _found else "the service shows no run that is plainly it")
                             + f". Nothing was sent. Name the run with --take-up {r['row']}=RUN, or, once Grid "
                               f"Control shows there is no run for this row, add --resubmit-lost")
            if _hold:
                item.update(state=OUTCOME_NOT_KNOWN, why=_hold)
                record(item, r, manifest)
                save()
                continue
            if started is None:
                try:
                    started = portal.start(body)
                except Exception as exc:                                 # noqa: BLE001
                    _failed = exc
            if _failed is not None and getattr(_failed, "status", None) == 0 and r.get("drawing"):
                # NO ANSWER IS NOT A REFUSAL. The service is asked whether it holds the run; one
                # plain match is followed. Anything else is "outcome not known", never "not queued".
                _found, _heard = runs_after_no_answer(portal, r["drawing"], r["quantity"], _asked_at, sleep=sleep)
                if len(_found) == 1:
                    started = {"run_id": _found[0]}
                    item["resumed"] = (f"the service did not answer the request in time but had queued "
                                       f"it: run {_found[0]} is followed, nothing was sent twice")
                    _failed = None
                else:
                    item.update(state=OUTCOME_NOT_KNOWN,
                                why=f"{_failed} — the request left and no answer came. "
                                    + ("The service could not be asked afterwards" if not _heard else
                                       f"The service shows {len(_found)} runs that could be it ({', '.join(_found)})"
                                       if _found else "The service showed no run for it in ten minutes")
                                    + f". Nothing will be sent for this row until the outcome is known: check Grid "
                                      f"Control, then --take-up {r['row']}=RUN or --resubmit-lost")
                    record(item, r, manifest)
                    save()
                    continue
            if _failed is not None:
                _m = re.search(r"/api/estimate/([0-9a-f]{6,})/", str(_failed))
                item.update(state="not queued", why=str(_failed)
                            + (f" — this batch did not start run {_m.group(1)}; let it finish or stop it on "
                               f"Grid Control, then run this row again" if _m else ""))
                record(item, r, manifest)
                save()
                continue
            item.update(state="running", run_id=started.get("run_id"), result_origin='new submission')
            _sent += 1
            if _again and _prev.get("run_id") and _prev["run_id"] != item["run_id"]:
                item["run_again"] = (f"run again by request; the earlier run {_prev['run_id']} "
                                     f"({_prev.get('unit_cost')}) and its files are kept")
            record(item, r, manifest)
            save()
            if at_once > 1:
                # KEPT IN FLIGHT: the next row is looked at while this one runs; it is written
                # back, on this one thread, when it ends. Never more than `at_once` open.
                in_flight.append([item, r, manifest, time.time() + 4 * 3600])
                while len(in_flight) >= at_once:
                    _finish_one()
                continue
            st = wait_for(portal, item["run_id"], sleep=_waiting)
        _finish(item, r, manifest, st)
    while in_flight:
        _finish_one()
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    if writer is not None:
        report["written_by"] = writer.how
        report["backup"] = str(writer.backup) if writer.backup else None
    save()
    return report


def _finish_body(item, r, manifest, st, *, args, sheet, data, writer, priced, runs_of, extras,
                 record, save) -> None:
    """One ended run: its cost, the tracker cell, the read-back, the copies, the ledger line."""
    if True:
        if item.get('resumed') or item.get('run_id') == (item.get('previous') or {}).get('run_id'):
            item['result_origin'] = 'existing run collected; not proof of a new estimate'
        else:
            item.setdefault('result_origin', 'existing or shared run; freshness not established')
        cost = unit_cost_of(st, r["quantity"])
        item.update(state=str(st.get("status")), unit_cost=cost, output=st.get("output_path") or st.get("output"),
                    quality=st.get("quality") or None, review=st.get("review") or None)
        if r["drawing"]:
            priced[(_rk(r), r["quantity"])] = item
            if str(st.get("status")) == "done":
                runs_of[_rk(r)] = {"row": r["row"], "st": st, "run_id": item.get("run_id")}
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", default="", help="the tracker workbook (needed for everything but --refresh-index)")
    ap.add_argument("--refresh-index", action="store_true",
                    help="list this batch's own Design and Prototype folders, and only those, into "
                         "its own drawing index, then stop; nothing is priced")
    ap.add_argument("--sheet-name", default="", help="the tab; default the active one")
    ap.add_argument("--rows", default="", help="sheet rows to price: a range (5-12), a list (134,137) or both")
    ap.add_argument("--next", type=int, default=0, metavar="N",
                    help="price the next N rows not yet run, in sheet order: a drawing number, no cost, "
                         "no earlier attempt on record, not held. Rows that find no pack are listed and "
                         "do not count. Stops once N estimates are started")
    ap.add_argument("--from-row", type=int, default=0, help="with --next: start looking at this sheet row")
    ap.add_argument("--hold-rows", default=os.getenv("SDI_TTI_HOLD_ROWS", ""),
                    help="with --next: sheet rows never taken as next (e.g. 136,99,126)")
    ap.add_argument("--drawings", default="", help="only the rows for these drawing numbers (comma separated)")
    ap.add_argument("--run-again", action="store_true",
                    help="start a NEW estimate for rows that already finished, named with --rows or "
                         "--drawings. The earlier estimate, its files and its run stay on record; the "
                         "cost cell is replaced when the new run finishes")
    ap.add_argument("--walk-live", action="store_true",
                    help="list both drawing areas live when the index cannot be used (hours on a VPN)")
    ap.add_argument("--use-index", action="store_true",
                    default=(os.getenv("SDI_TTI_USE_INDEX") or "").strip().lower() in ("1", "true", "yes", "on"),
                    help="find packs through the drawing index, as before 15 Nov 2026. Without it each "
                         "row's pack is found in its job's own folders, Design first then Prototype, "
                         "listed now, and no index is needed or used")
    ap.add_argument("--checked-packs", default="",
                    help="the pack check's preflight.json: price only the packs it resolved, each "
                         "held unless found again now with the same files; the drawing areas are not listed")
    ap.add_argument("--client", default="TTI")
    ap.add_argument("--method", default="both", choices=("both", "targeted", "deterministic", "llm"))
    ap.add_argument("--col-drawing", default="L")
    ap.add_argument("--col-notes", default="G")
    ap.add_argument("--col-thumbs", default="I,J")
    ap.add_argument("--col-cost", default="P")
    ap.add_argument("--drawings-only", action="store_true",
                    help="price only the rows that carry a drawing number; the rest are listed, not priced")
    ap.add_argument("--replace-costs", action="store_true",
                    help="allow overwriting the cost column; may reuse an existing finished run. "
                         "Use --run-again for a fresh estimate of a finished row")
    ap.add_argument("--copy-to", default=os.getenv("SDI_TTI_COPY_TO") or DEFAULT_COPY_TO,
                    help="also copy each finished row's spreadsheets and GA PDF here; 'none' to stop")
    ap.add_argument("--central-sheet", default=os.getenv("SDI_TTI_CENTRAL_SHEET", ""),
                    help="also write the AI Cost on this central workbook (its SharePoint address)")
    ap.add_argument("--write-only", action="store_true",
                    help="write back the cost of runs already finished (to the cost column, the central "
                         "sheet and the conference folder); never start or wait for an estimate")
    ap.add_argument('--job-changes', default='', metavar='JSON',
                    help='explicit per-drawing material/gauge/finish decisions, filed by the service; never prices')
    ap.add_argument("--take-up", action="append", default=[], metavar="ROW=RUN",
                    help="the run that is a row's, e.g. 3=e2639e873262: it is followed or its result "
                         "used, and nothing is sent for that row. Refused when the run is for another "
                         "drawing or another number of units")
    ap.add_argument("--resubmit-lost", action="store_true",
                    help="submit again a row whose earlier run failed because its runner stopped "
                         "answering; only once that process is confirmed ended")
    ap.add_argument("--col-qty", default="", help="the number of units, e.g. N; default the column headed Qty / Quantity")
    ap.add_argument("--at-once", type=int, default=int(os.getenv("SDI_TTI_AT_ONCE", "1") or 1),
                    help="how many estimates are open together, one per Grid Runner (default 1; "
                         "2 with two runners). The tracker is still written by this one process")
    ap.add_argument("--dry-run", action="store_true", help="find the drawings and say what would run; nothing queued or written")
    ap.add_argument("--server", default=os.getenv("SDI_SERVER", "http://localhost:8072"))
    ap.add_argument("--api-key", default=os.getenv("SDI_API_KEY", ""))
    ap.add_argument("--status-file", default="")
    return ap


def central_sheet_problem(value: Any) -> str:
    """Why this is not a central sheet, or "" when it is one or is not set."""
    v = str(value or "").strip()
    if not v:
        return ""
    if re.match(r"https?://\S+$", v):
        return "" if re.search(r"\.xls[xm]?(\?|$)", v, re.I) else \
            "the address does not end in a workbook name (.xlsx): use File > Info > Copy path in desktop Excel"
    if re.search(r"\.xls[xm]?$", v, re.I) and Path(v).is_file():
        return ""
    return f"it is neither an https address nor a workbook that exists: {v[:80]!r}"


def main(argv: Optional[List[str]] = None) -> int:
    # .ENV BEFORE THE SETTINGS ARE READ (11 Nov 2026): the arguments' defaults come from the
    # environment, and read before .env was loaded, SDI_TTI_CENTRAL_SHEET was empty: row 17's cost
    # never reached the central tracker, and nothing said so.
    sys.path.insert(0, str(HERE))
    try:
        import config  # noqa: F401  (loads .env)
    except Exception:                                                    # noqa: BLE001
        pass
    _parser = build_parser()
    args = _parser.parse_args(argv)
    if args.refresh_index:
        return refresh_scoped_index(args.client)
    if not str(args.sheet or "").strip():
        _parser.error("--sheet is required")
    # THE CENTRAL SHEET IS AN ADDRESS OR A FILE, CHECKED BEFORE ANYTHING RUNS (11 Nov 2026): the
    # setting held the PowerShell lines that were meant to set it ("cd C:\ClaudeVision
    # Add-Content .env ..."), and the batch would have handed that to Excel row after row.
    _bad = central_sheet_problem(args.central_sheet)
    if _bad:
        print(f"central sheet: NOT VALID: {_bad}", flush=True)
        if not args.dry_run:
            raise SystemExit("Nothing was queued or written. Correct SDI_TTI_CENTRAL_SHEET in .env (the "
                             "tracker's https address from Excel's File > Info > Copy path), or pass "
                             "--central-sheet \"\" to run without it.")
        args.central_sheet = ""
    if args.run_again:
        if not (str(args.rows or "").strip() or str(args.drawings or "").strip()) or args.next:
            _parser.error("--run-again needs the rows or drawings named (--rows / --drawings), and not --next")
        args.replace_costs = True
    if args.next and str(args.rows or "").strip():
        _parser.error("--next chooses the rows itself; give --from-row, not --rows")
    if args.next:
        args.drawings_only = True
    portal = None
    if not args.dry_run:
        _busy = claim_one_writer(Path(args.status_file).stem if args.status_file else "command line")
        if _busy:
            raise SystemExit(f"{_busy} Nothing was queued or written.")
        args.ledger_folders = ledger_folders()
        import live_enquiry_runner as ler
        portal = ler.Portal(args.server, args.api_key, timeout=600)
    status = Path(args.status_file) if args.status_file else (ROOT / "output" / "tti" / "last_tti_run.json")
    try:
        rep = run_batch(args, portal, status)
    finally:
        if not args.dry_run:
            release_one_writer()
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
        _f = it.get("found") or {}
        if _f.get("folder"):
            print(f"{'':<11}from the {_f.get('area')} area: {_f['folder']}", flush=True)
        if it.get("formats"):
            print(f"{'':<11}files: " + ", ".join(f"{n} {e}" for e, n in it["formats"].items()), flush=True)
        if _f.get("design_looked"):
            print(f"{'':<11}looked: {_f['design_looked']}", flush=True)
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
