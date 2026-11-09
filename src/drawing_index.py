#!/usr/bin/env python3
"""The drawing index: every folder and drawing file on the design share, held on this machine (JG, 9 Nov 2026).

Walking W: over the network to find one job's drawings takes minutes; looking it up here takes
under a second. The hourly design sweep refreshes it, and the TTI pricer (and anything else that
has to find a drawing by number) reads it.

    python src/drawing_index.py --build           refresh now (only changed folders are listed)
    python src/drawing_index.py --build --full    list every folder again
    python src/drawing_index.py --find 12181-00-GA

WHAT IS INDEXED. Every folder under each root in SDI_DRAWING_INDEX_ROOTS ('|' between them;
default \\\\sdi-dc01\\CAD\\Design\\Customers April 08 Onwards and ...\\Prototype, which is W:), down to SDI_DRAWING_INDEX_DEPTH
(10) levels, with the drawing and model files directly in it (.pdf .dxf .dwg .sldprt .sldasm
.slddrw .step .stp): name, size, modified time. Archive, old, superseded and backup folders are
left out, as the sweep leaves them out.

WHY A REFRESH IS QUICK. A folder's modified time changes when anything directly inside it is
added, removed or renamed. A folder whose time is unchanged since the last refresh is taken from
the index as it was, sub-folders included, without being listed again; only changed folders cost
a listing. A file edited in place does not change its folder's time, so its size and date can lag
until the weekly full listing (SDI_DRAWING_INDEX_FULL_DAYS, 7).

WHERE IT IS KEPT. SDI_DRAWING_INDEX (output\\drawing_index\\index.json.gz), compressed, written
whole and swapped in, so a reader never sees half of one. An index older than
SDI_DRAWING_INDEX_MAX_HOURS (26) is stale, and a reader walks the share instead and says so.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "drawing_index.v1"
HERE = Path(__file__).resolve().parent
DRAWING_EXT = {".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw", ".step", ".stp"}
SKIP = re.compile(r"\b(archive|archived|old|superseded|backup|back up|obsolete|recycle)\b|^[._~$]",
                  re.IGNORECASE)
DEFAULT_ROOTS = r"\\sdi-dc01\CAD\Design\Customers April 08 Onwards|\\sdi-dc01\CAD\Prototype"  # W:

sys.path.insert(0, str(HERE))
from drive_map import to_unc  # noqa: E402  (W:\ as its network path where the letter is not mapped)


def settings(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    e = env if env is not None else os.environ
    return {
        "roots": [Path(to_unc(r.strip(), e)) for r in (e.get("SDI_DRAWING_INDEX_ROOTS") or DEFAULT_ROOTS).split("|")
                  if r.strip()],
        "path": Path(e.get("SDI_DRAWING_INDEX") or (HERE.parent / "output" / "drawing_index" / "index.json.gz")),
        "depth": max(1, int(e.get("SDI_DRAWING_INDEX_DEPTH") or 10)),
        "max_hours": float(e.get("SDI_DRAWING_INDEX_MAX_HOURS") or 26),
        "full_days": float(e.get("SDI_DRAWING_INDEX_FULL_DAYS") or 7),
    }


def load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and data.get("schema") == SCHEMA else None
    except (OSError, ValueError, EOFError):
        return None


def save(path: Path, index: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(index, fh, separators=(",", ":"))
    os.replace(tmp, path)


def _list(folder: Path) -> Optional[Dict[str, Any]]:
    dirs: List[str] = []
    files: List[List[Any]] = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if not SKIP.search(e.name):
                            dirs.append(e.name)
                    elif e.is_file(follow_symlinks=False) and os.path.splitext(e.name)[1].lower() in DRAWING_EXT:
                        st = e.stat()
                        files.append([e.name, int(st.st_size), round(st.st_mtime, 1)])
                except OSError:
                    continue
    except OSError:
        return None
    return {"dirs": sorted(dirs), "files": sorted(files)}


def refresh(roots: List[Path], path: Path, depth: int = 10, full: bool = False,
            full_days: float = 7.0, now: Optional[float] = None) -> Dict[str, Any]:
    """Bring the index up to date and save it; the summary of what was done."""
    now = now if now is not None else time.time()
    old = load(path) or {}
    old_folders: Dict[str, Any] = old.get("folders") or {}
    if not full and old.get("full_at") and now - float(old["full_at"]) > full_days * 86400:
        full = True
    folders: Dict[str, Any] = {}
    stats = {"listed": 0, "reused": 0, "unreadable": 0}
    roots_out: Dict[str, Any] = {}
    started = time.time()
    for root in roots:
        readable = root.is_dir()
        roots_out[str(root)] = {"readable": readable}
        if not readable:
            # An unreadable root keeps what was last known of it, marked so, rather than
            # emptying the index because the share was briefly away.
            for k, v in old_folders.items():
                if _under(k, str(root)):
                    folders[k] = v
            continue
        stack: List[Tuple[Path, int]] = [(root, 0)]
        while stack:
            f, lvl = stack.pop()
            key = str(f)
            try:
                mt = round(f.stat().st_mtime, 1)
            except OSError:
                stats["unreadable"] += 1
                continue
            prev = old_folders.get(key)
            if prev is not None and not full and prev.get("mtime") == mt:
                rec = prev
                stats["reused"] += 1
            else:
                got = _list(f)
                if got is None:
                    stats["unreadable"] += 1
                    continue
                rec = dict(got, mtime=mt)
                stats["listed"] += 1
            folders[key] = rec
            if lvl < depth:
                stack.extend((f / d, lvl + 1) for d in rec.get("dirs") or [])
    index = {"schema": SCHEMA, "built_at": now, "full_at": now if full else old.get("full_at") or now,
             "roots": roots_out, "depth": depth, "folders": folders,
             "last": dict(stats, seconds=round(time.time() - started, 1), full=full)}
    save(path, index)
    return summary(index)


def summary(index: Dict[str, Any]) -> Dict[str, Any]:
    folders = index.get("folders") or {}
    return {"built_at": datetime.fromtimestamp(float(index.get("built_at") or 0)).isoformat(timespec="minutes"),
            "folders": len(folders), "drawings": sum(len(v.get("files") or []) for v in folders.values()),
            "roots": index.get("roots") or {}, "last": index.get("last") or {}}


def is_fresh(index: Optional[Dict[str, Any]], max_hours: float, now: Optional[float] = None) -> bool:
    now = now if now is not None else time.time()
    return bool(index) and now - float(index.get("built_at") or 0) <= max_hours * 3600


def _under(path: str, root: str) -> bool:
    p, r = os.path.normcase(os.path.normpath(path)), os.path.normcase(os.path.normpath(root))
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def covers(index: Dict[str, Any], root: Path) -> bool:
    """True when the index was built over this folder (it is one of the roots, or inside one)."""
    return any(_under(str(root), r) and (index.get("roots") or {}).get(r, {}).get("readable")
               for r in (index.get("roots") or {}))


def folders_under(index: Dict[str, Any], root: Path) -> List[Tuple[Path, List[Tuple[Path, int, float]]]]:
    """Every indexed folder under a root, each with its drawing files (path, size, modified)."""
    out = []
    r = str(root)
    for k, v in (index.get("folders") or {}).items():
        if _under(k, r):
            p = Path(k)
            out.append((p, [(p / n, int(s), float(m)) for n, s, m in v.get("files") or []]))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--find", default="", help="list indexed drawings whose path names this text")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(HERE))
    try:
        import config  # noqa: F401  (loads .env)
    except Exception:                                                    # noqa: BLE001
        pass
    cfg = settings()
    if args.build:
        s = refresh(cfg["roots"], cfg["path"], cfg["depth"], full=args.full, full_days=cfg["full_days"])
        for r, v in s["roots"].items():
            print(f"{r}  {'readable' if v.get('readable') else 'NOT READABLE from this window'}", flush=True)
        last = s["last"]
        print(f"{s['folders']} folder(s), {s['drawings']} drawing file(s); listed {last.get('listed')}, "
              f"reused {last.get('reused')}, unreadable {last.get('unreadable')} in {last.get('seconds')} s"
              f"{' (full)' if last.get('full') else ''} -> {cfg['path']}", flush=True)
    if args.find:
        idx = load(cfg["path"])
        if not idx:
            print(f"No index at {cfg['path']}: run with --build first.", flush=True)
            return 1
        needle = args.find.lower()
        n = 0
        for k, v in sorted((idx.get("folders") or {}).items()):
            for name, _s, m in v.get("files") or []:
                if needle in (k + "\\" + name).lower():
                    print(f"{datetime.fromtimestamp(m):%Y-%m-%d}  {k}\\{name}", flush=True)
                    n += 1
                    if n >= 60:
                        return 0
        print(f"{n} match(es); index built {summary(idx)['built_at']}", flush=True)
    if not (args.build or args.find):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
