"""The master tracker, read from where it lives, without ever writing to it (JG, 15 Nov 2026).

"ultimately we want to just run that command button whenever estimating / PMs say that the
s.sheet has new rows / changes to it, so that our process finds that s/sheet on the sharepoint,
does the delta and prices any changes."

The master is the workbook SDI_TTI_CENTRAL_SHEET names: its SharePoint address as desktop Excel's
File > Info > Copy path gives it, or a local path. src/tti_central.py already writes its AI Cost
through the laptop's signed-in desktop Excel; this reads it by the same route.

    snapshot(address, dest_dir)   opens the master READ-ONLY, saves a COPY under dest_dir, closes
                                  without saving. Refuses any address that is not the configured
                                  master. The master is never saved by this module.
    tracker_rows(copy, tab)       the copy's job rows in the shape the change check compares:
                                  permanent AI Row ID (None where the sheet has none), drawing,
                                  quantity, both feedback columns, cost, whether the drawing
                                  index holds current files for the drawing, and every reason a
                                  row is on hold. Nothing is defaulted: a blank quantity is a
                                  hold, not 1.

Run as a command by the service (which never imports the engine):

    python src/tti_tracker_source.py --out-dir output/tti_tracker --json-out <file>

Settings: SDI_TTI_CENTRAL_SHEET (the master), SDI_TTI_TRACKER_TAB (its tab; default the active
one), SDI_TTI_HOLD_OUT (drawing numbers never priced by the button, comma separated).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
ROW_ID_HEADER = "AI Row ID"
_REV = re.compile(r"\bREV(?:ISION)?\s*[:.-]?\s*([A-Z0-9]+)\b", re.IGNORECASE)
# The check compares costs itself; and the batch prices rows that repeat a drawing each on its
# own brief (run keys, 15 Nov 2026), so that repeat alone is not a reason to hold a row.
_NOT_A_HOLD_HERE = ("AI cost already present", "Drawing repeated at different quantities")


class NotTheMaster(ValueError):
    pass


def _norm(address: Any) -> str:
    v = urllib.parse.unquote(str(address or "").strip().strip('"').split("?")[0])
    return v.replace("\\", "/").rstrip("/").casefold()


def is_master(address: Any, master: Any) -> bool:
    return bool(_norm(master)) and _norm(address) == _norm(master)


class _ExcelBook:
    """The master, open read-only in the laptop's desktop Excel. Only two things can be asked
    of it: a copy saved elsewhere, and closing without saving."""

    def __init__(self, address: str) -> None:
        import win32com.client                                       # laptop only
        self._xl = win32com.client.DispatchEx("Excel.Application")
        self._xl.DisplayAlerts = False
        self._xl.AutomationSecurity = 3                              # no macros in this instance
        self._wb = self._xl.Workbooks.Open(address, UpdateLinks=0, ReadOnly=True)

    def SaveCopyAs(self, path: str) -> None:
        self._wb.SaveCopyAs(path)

    def Close(self, SaveChanges: bool = False) -> None:              # noqa: N803 (Excel's name)
        try:
            self._wb.Close(SaveChanges=False)
        finally:
            self._xl.Quit()


def snapshot(address: str, dest_dir: Path, master: Optional[str] = None,
             opener: Optional[Callable[[str], Any]] = None,
             now: Optional[datetime] = None) -> Path:
    """A local copy of the master, named for the minute it was taken. `opener(address)` returns
    an object with SaveCopyAs(path) and Close(SaveChanges=False); the default is desktop Excel."""
    master = master if master is not None else os.getenv("SDI_TTI_CENTRAL_SHEET", "")
    if not str(master or "").strip():
        raise NotTheMaster("No master tracker is set (SDI_TTI_CENTRAL_SHEET); nothing was read.")
    if not is_master(address, master):
        raise NotTheMaster("That is not the configured master tracker (SDI_TTI_CENTRAL_SHEET); "
                           "nothing was read.")
    address = str(address).strip().strip('"').split("?")[0]
    suffix = Path(urllib.parse.unquote(address)).suffix.lower()
    if suffix not in (".xlsx", ".xlsm"):
        raise NotTheMaster("The master tracker's address does not end in a workbook name (.xlsx).")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"tracker-{stamp}{suffix}"
    n = 1
    while dest.exists():                                             # a copy is never overwritten
        n += 1
        dest = dest_dir / f"tracker-{stamp}-{n}{suffix}"
    if not address.lower().startswith("http") and opener is None:
        shutil.copy2(address, dest)
        return dest
    book = (opener or _ExcelBook)(address)
    try:
        book.SaveCopyAs(str(dest))
    finally:
        book.Close(SaveChanges=False)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise OSError(f"Excel reported the copy saved but {dest} is not there")
    return dest


def _row_ids(path: Path, tab: Optional[str], header_row: int) -> Tuple[bool, Dict[int, str]]:
    """(the sheet has an AI Row ID column, {sheet row: id}) read from the header's own row."""
    import openpyxl
    book = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        ws = book[tab] if tab else book.active
        col = None
        ids: Dict[int, str] = {}
        for n, cells in enumerate(ws.iter_rows(min_row=header_row, values_only=True), header_row):
            if n == header_row:
                hits = [i for i, v in enumerate(cells)
                        if str(v or "").strip().casefold() == ROW_ID_HEADER.casefold()]
                if len(hits) > 1:
                    raise ValueError(f"The tracker has {len(hits)} columns headed {ROW_ID_HEADER}")
                if not hits:
                    return False, {}
                col = hits[0]
                continue
            v = cells[col] if col is not None and col < len(cells) else None
            if v not in (None, ""):
                ids[n] = str(v).strip()
        return True, ids
    finally:
        book.close()


def pack_of(files: Sequence[Tuple[Any, int, float]]) -> Tuple[str, str]:
    """(state, key) of the drawing's current files in the index: 'ready' with a key that changes
    when a file is added, removed, resized or re-saved; 'missing' with no key."""
    if not files:
        return "missing", ""
    listed = sorted((str(p).replace("\\", "/").casefold(), int(sz), int(float(m) // 60)) for p, sz, m in files)
    return "ready", hashlib.sha256(json.dumps(listed).encode()).hexdigest()


def tracker_rows(path: Path, tab: Optional[str] = None, *,
                 lookup: Optional[Callable[[str], Sequence[Tuple[Any, int, float]]]] = None,
                 index_problem: str = "", hold_out: Iterable[str] = (), client: str = "TTI",
                 method: str = "both") -> Dict[str, Any]:
    """The copy's job rows for the change check. `lookup(drawing)` gives the drawing's current
    indexed files; `index_problem` (the index is missing or stale) puts every row with a drawing
    on hold with that reason, because a pack cannot then be called current."""
    import tti_preflight
    raw, meta = tti_preflight.read_tracker(path, tab or None)
    has_ids, ids = _row_ids(Path(path), meta.get("sheet"), int(meta["header_row"]))
    held_out = {str(h).strip().upper() for h in hold_out if str(h).strip()}
    rows: List[Dict[str, Any]] = []
    for r in raw:
        fb = {("previous" if "previous" in tti_preflight.header_key(f["label"]) else
               "latest" if "latest" in tti_preflight.header_key(f["label"]) else
               tti_preflight.header_key(f["label"])): f["text"] for f in r["feedback"]}
        holds = [h for h in r["holds"] if not h.startswith(_NOT_A_HOLD_HERE)]
        drawing = r["drawing"]
        state, key = ("missing", "")
        if drawing:
            if drawing.upper() in held_out:
                holds.append("Held out of the button's work by setting (SDI_TTI_HOLD_OUT)")
            if index_problem:
                holds.append(index_problem)
            elif lookup is not None:
                state, key = pack_of(lookup(drawing))
        rev = _REV.search(r.get("drawing_cell") or "")
        cost = r.get("cost_before")
        rows.append({
            "row_id": ids.get(r["row"]), "row": r["row"], "drawing": drawing or "",
            "quantity": r["quantity"], "description": r["description"],
            "previous_feedback": fb.get("previous", ""), "latest_feedback": fb.get("latest", ""),
            "revision": rev.group(1).upper() if rev else "", "pack_key": key, "method": method,
            "client": client, "cost": None if cost in (None, "") else (cost if isinstance(cost, (int, float)) else str(cost)),
            "pack_state": state, "pack_safe": state == "ready", "holds": holds, "history": None,
            "snapshot_file": str(path), "tab": meta.get("sheet") or ""})
    return {"rows": rows, "tab": meta.get("sheet") or "", "row_id_column": has_ids,
            "rows_without_id": [r["row"] for r in rows if not r["row_id"]]}


def index_lookup(env: Optional[Dict[str, str]] = None, now: Optional[float] = None
                 ) -> Tuple[Optional[Callable[[str], Sequence[Tuple[Any, int, float]]]], str]:
    """(lookup, problem). The drawing index's own database; a missing or stale index is a stated
    problem, never a silent listing of the share."""
    import drawing_index
    cfg = drawing_index.settings(env)
    db = drawing_index.db_path(cfg["path"])
    if not db.is_file():
        return None, "The drawing index has not been built on this machine; packs cannot be checked"
    meta = drawing_index.db_meta(db)
    if not drawing_index.is_fresh(meta, cfg["max_hours"], now):
        built = datetime.fromtimestamp(meta["built_at"]).strftime("%d %b %H:%M") if meta["built_at"] else "never"
        return None, (f"The drawing index is older than {cfg['max_hours']:g} hours (built {built}); "
                      f"refresh it before pricing changes")
    return (lambda d: drawing_index.db_lookup(db, d)), ""


def main(argv: Optional[List[str]] = None) -> int:
    sys.path.insert(0, str(HERE))
    try:
        import config  # noqa: F401  (loads .env, as the batch does)
    except Exception:                                                # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Copy the master tracker and list its rows; writes nothing to it.")
    ap.add_argument("--master", default=os.getenv("SDI_TTI_CENTRAL_SHEET", ""))
    ap.add_argument("--tab", default=os.getenv("SDI_TTI_TRACKER_TAB", ""))
    ap.add_argument("--out-dir", default=str(HERE.parent / "output" / "tti_tracker"))
    ap.add_argument("--client", default="TTI")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)
    out: Dict[str, Any]
    try:
        copy = snapshot(args.master, Path(args.out_dir), master=args.master)
        lookup, problem = index_lookup()
        out = tracker_rows(copy, args.tab or None, lookup=lookup, index_problem=problem,
                           hold_out=(os.getenv("SDI_TTI_HOLD_OUT", "")).split(","), client=args.client)
        out.update(ok=True, snapshot=str(copy), taken=time.time(), index_problem=problem)
    except Exception as exc:                                         # noqa: BLE001
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    body = json.dumps(out, ensure_ascii=False, default=str)
    if args.json_out:
        Path(args.json_out).write_text(body, encoding="utf-8")
    else:
        print(body)
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
