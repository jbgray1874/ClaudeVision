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
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA = "drawing_index.v1"
HERE = Path(__file__).resolve().parent
DRAWING_EXT = {".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw", ".step", ".stp", ".igs", ".iges"}
# ARCHIVES ARE INDEXED AND MARKED, NOT LEFT OUT (SCRUM-199 review): never chosen automatically, but
# searchable evidence where a reference needs an older revision or no current copy exists. Only
# system and temporary folders (. _ ~ $) are left out.
ARCHIVE = re.compile(r"\b(archive|archived|old|superseded|backup|back up|obsolete|recycle)\b", re.IGNORECASE)
SKIP = re.compile(r"^[._~$]")


def is_archive(path: str) -> bool:
    return any(ARCHIVE.search(part) for part in re.split(r"[\\/]", str(path)) if part)
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
        # 0: no automatic full listing. The share holds ~230,000 folders and a full listing took
        # ~10 hours on 9 Nov 2026, so it is run by hand, overnight (--build --full).
        "full_days": float(e.get("SDI_DRAWING_INDEX_FULL_DAYS") or 0),
        "recent_days": float(e.get("SDI_DRAWING_INDEX_RECENT_DAYS") or 90),
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
            full_days: float = 0.0, now: Optional[float] = None,
            progress: Optional[Any] = None, every: int = 2000, recent_days: float = 90.0,
            top_levels: int = 2) -> Dict[str, Any]:
    """Bring the index up to date and save it; the summary of what was done.

    A QUICK REFRESH (the hourly one) checks only the top levels (clients, their job folders) and
    folders that changed in the last `recent_days`: a new job appears as a new folder near the
    top, and work goes on inside recently changed ones. A dormant folder is taken from the last
    index unchecked; the resolver re-lists a chosen job's folders live, so nothing is priced on
    a stale listing, and a full listing (--full, overnight) catches the rest."""
    now = now if now is not None else time.time()
    old = load(path) or {}
    old_folders: Dict[str, Any] = old.get("folders") or {}
    if not full and full_days and old.get("full_at") and now - float(old["full_at"]) > full_days * 86400:
        full = True
    recent = now - recent_days * 86400
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
            prev = old_folders.get(key)
            if prev is not None and not full and lvl > top_levels and float(prev.get("mtime") or 0) < recent:
                folders[key] = prev                     # dormant: kept as last listed, not checked
                stats["dormant"] = stats.get("dormant", 0) + 1
                if lvl < depth:
                    stack.extend((f / d, lvl + 1) for d in prev.get("dirs") or [])
                continue
            try:
                mt = round(f.stat().st_mtime, 1)
            except OSError:
                stats["unreadable"] += 1
                continue
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
            if progress and len(folders) % every == 0:
                progress(f"  ... {len(folders)} folder(s), listed {stats['listed']}, reused {stats['reused']}, "
                         f"{round(time.time() - started)} s, now in {key}")
            if lvl < depth:
                stack.extend((f / d, lvl + 1) for d in rec.get("dirs") or [])
    index = {"schema": SCHEMA, "built_at": now, "full_at": now if full else old.get("full_at") or now,
             "roots": roots_out, "depth": depth, "folders": folders,
             "last": dict(stats, seconds=round(time.time() - started, 1), full=full)}
    save(path, index)
    build_db(index, db_path(path))
    return summary(index)


# ── the lookup database ──────────────────────────────────────────────────────────────────
# The index as SQLite beside it (index.sqlite), keyed by drawing number, so a lookup reads the
# few folders it needs instead of loading ~590,000 files. Rebuilt whole after every refresh and
# swapped in; `--convert` makes it from an existing index without listing the share again.

def db_path(index_path: Path) -> Path:
    name = index_path.name
    for suffix in (".json.gz", ".gz", ".json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return index_path.with_name(name + ".sqlite")


def build_db(index: Dict[str, Any], db: Path) -> int:
    import sqlite3
    sys.path.insert(0, str(HERE))
    from pack_resolver import drawing_id
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_name(db.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(str(tmp))
    try:
        con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
        con.execute("CREATE TABLE folders (id INTEGER PRIMARY KEY, path TEXT, mtime REAL, archive INTEGER)")
        con.execute("CREATE TABLE files (folder INTEGER, name TEXT, size INTEGER, mtime REAL, did TEXT)")
        rows = 0
        for fid, (k, v) in enumerate((index.get("folders") or {}).items(), start=1):
            con.execute("INSERT INTO folders VALUES (?,?,?,?)", (fid, k, v.get("mtime"), int(is_archive(k))))
            batch = [(fid, n, int(sz), float(m), drawing_id(n)) for n, sz, m in v.get("files") or []]
            con.executemany("INSERT INTO files VALUES (?,?,?,?,?)", batch)
            rows += len(batch)
        con.execute("CREATE INDEX files_did ON files(did)")
        con.execute("CREATE INDEX files_folder ON files(folder)")
        con.executemany("INSERT INTO meta VALUES (?,?)",
                        [("built_at", str(index.get("built_at") or 0)),
                         ("roots", json.dumps(index.get("roots") or {}))])
        con.commit()
    finally:
        con.close()
    os.replace(tmp, db)
    return rows


def db_meta(db: Path) -> Dict[str, Any]:
    import sqlite3
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        meta = dict(con.execute("SELECT k, v FROM meta").fetchall())
    finally:
        con.close()
    return {"built_at": float(meta.get("built_at") or 0), "roots": json.loads(meta.get("roots") or "{}")}


def _rows(con: Any, ids: Iterable[int]) -> List[Tuple[Path, List[Tuple[Path, int, float]], bool]]:
    out = []
    for fid in sorted(set(ids)):
        frow = con.execute("SELECT path, archive FROM folders WHERE id=?", (fid,)).fetchone()
        if not frow:
            continue
        p = Path(frow[0])
        files = [(p / n, int(sz), float(m)) for n, sz, m in
                 con.execute("SELECT name, size, mtime FROM files WHERE folder=?", (fid,)).fetchall()]
        out.append((p, files, bool(frow[1])))
    return out


def db_rows_for(db: Path, drawing: str) -> List[Tuple[Path, List[Tuple[Path, int, float]], bool]]:
    """The folders a drawing's pack can come from: those holding a file named for it, and every
    folder of its job (by the job number in the path), each with its drawing files."""
    import re as _re
    import sqlite3
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        want = str(drawing or "").strip().upper()
        ids = [r[0] for r in con.execute("SELECT DISTINCT folder FROM files WHERE did=?", (want,))]
        job = _re.match(r"\s*(\d{3,})", want)
        if job:
            ids += [r[0] for r in con.execute("SELECT id FROM folders WHERE instr(path, ?) > 0", (job.group(1),))]
        return _rows(con, ids)
    finally:
        con.close()


def db_lookup(db: Path, did: str) -> List[Tuple[Path, int, float]]:
    """Every current (non-archive) file named for one drawing number, anywhere on the share."""
    import sqlite3
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [(Path(p) / n, int(sz), float(m)) for p, n, sz, m in con.execute(
            "SELECT folders.path, files.name, files.size, files.mtime FROM files JOIN folders "
            "ON folders.id = files.folder WHERE files.did=? AND folders.archive=0", (str(did).upper(),))]
    finally:
        con.close()


def db_folders_under(db: Path, root: Path, include_archive: bool = False
                     ) -> List[Tuple[Path, List[Tuple[Path, int, float]]]]:
    import sqlite3
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        r = str(root)
        ids = [i for i, p, a in con.execute("SELECT id, path, archive FROM folders")
               if _under(p, r) and (include_archive or not is_archive(p[len(r):]))]
        return [(p, files) for p, files, _a in _rows(con, ids)]
    finally:
        con.close()


def live_rows(folder: Path, depth: int = 8) -> Optional[List[Tuple[Path, List[Tuple[Path, int, float]], bool]]]:
    """A job's folders listed now, not from the index: what a pack is finally chosen from. None if
    the folder cannot be read (the index's listing then stands)."""
    if not folder.is_dir():
        return None
    out = []
    stack = [(folder, 0)]
    while stack:
        f, lvl = stack.pop()
        got = _list(f)
        if got is None:
            continue
        files = []
        for n, sz, m in got["files"]:
            files.append((f / n, int(sz), float(m)))
        out.append((f, files, is_archive(str(f)[len(str(folder)):])))
        if lvl < depth:
            stack.extend((f / d, lvl + 1) for d in got["dirs"])
    return out


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


def folders_under(index: Dict[str, Any], root: Path, include_archive: bool = False
                  ) -> List[Tuple[Path, List[Tuple[Path, int, float]]]]:
    """Every indexed folder under a root, each with its drawing files (path, size, modified).
    Archive folders only when asked for: they are evidence, not candidates."""
    out = []
    r = str(root)
    for k, v in (index.get("folders") or {}).items():
        if _under(k, r) and (include_archive or not is_archive(k[len(r):])):
            p = Path(k)
            out.append((p, [(p / n, int(s), float(m)) for n, s, m in v.get("files") or []]))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--find", default="", help="list indexed drawings whose path names this text")
    ap.add_argument("--convert", action="store_true",
                    help="build the lookup database (index.sqlite) from the existing index, without listing the share")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(HERE))
    try:
        import config  # noqa: F401  (loads .env)
    except Exception:                                                    # noqa: BLE001
        pass
    cfg = settings()
    if args.build:
        s = refresh(cfg["roots"], cfg["path"], cfg["depth"], full=args.full, full_days=cfg["full_days"],
                    progress=lambda line: print(line, flush=True), recent_days=cfg["recent_days"])
        for r, v in s["roots"].items():
            print(f"{r}  {'readable' if v.get('readable') else 'NOT READABLE from this window'}", flush=True)
        last = s["last"]
        print(f"{s['folders']} folder(s), {s['drawings']} drawing file(s); listed {last.get('listed')}, "
              f"reused {last.get('reused')}, dormant (not checked) {last.get('dormant', 0)}, unreadable "
              f"{last.get('unreadable')} in {last.get('seconds')} s{' (full)' if last.get('full') else ''} "
              f"-> {cfg['path']} and {db_path(cfg['path']).name}", flush=True)
    if args.convert:
        idx = load(cfg["path"])
        if not idx:
            print(f"No index at {cfg['path']} to convert: run with --build first.", flush=True)
            return 1
        started = time.time()
        n = build_db(idx, db_path(cfg["path"]))
        print(f"{db_path(cfg['path'])}: {len(idx.get('folders') or {})} folder(s), {n} file(s) in "
              f"{round(time.time() - started, 1)} s", flush=True)
    if args.find:
        db = db_path(cfg["path"])
        if not db.exists():
            print(f"No lookup database at {db}: run with --convert (or --build) first.", flush=True)
            return 1
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        needle = f"%{args.find}%"
        rows = con.execute("SELECT folders.path, files.name, files.mtime, folders.archive FROM files JOIN folders "
                           "ON folders.id = files.folder WHERE files.name LIKE ? OR folders.path LIKE ? LIMIT 61",
                           (needle, needle)).fetchall()
        con.close()
        for path, name, m, arch in rows[:60]:
            print(f"{datetime.fromtimestamp(m):%Y-%m-%d}  {'ARCHIVE ' if arch else ''}{path}\\{name}", flush=True)
        print(f"{min(len(rows), 60)}{'+' if len(rows) > 60 else ''} match(es); lookup database built "
              f"{datetime.fromtimestamp(db_meta(db)['built_at']).isoformat(timespec='minutes')}", flush=True)
    if not (args.build or args.find or args.convert):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
