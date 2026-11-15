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

SEVERAL FOLDERS AT ONCE, AND A STOPPED LISTING CARRIES ON (15 Nov 2026). Over the VPN one folder
takes about 150 ms to answer, so SDI_DRAWING_INDEX_WORKERS (8) folders are asked together, level
by level, in one order whatever the number, so the index made is the same. Progress is saved as
it goes to index.json.gz.partial, which is never an index; the next listing of the same roots
takes what it holds as listed, and it is removed when a listing completes. NOTHING ON THE SHARE
IS EVER WRITTEN, MOVED OR REMOVED: folders are listed and file names, sizes and dates read.

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
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(index, fh, separators=(",", ":"))
    os.replace(tmp, path)


# ── a stopped listing is not lost (15 Nov 2026) ──────────────────────────────────────────
# The index is written once, when a listing ends. Two full listings stopped part-way saved
# nothing, and a "quick" refresh then listed 150,000 folders afresh over four hours with the
# same all-or-nothing ending. Progress is now saved as it goes to a PARTIAL file beside the
# index. It is never the index: its schema is its own, so load(), is_fresh(), covers() and every
# reader refuse it. The next listing of the same roots takes each folder it holds as already
# listed, and the file is removed when a listing completes.
PARTIAL_SCHEMA = "drawing_index.partial.v1"
PARTIAL_TRUST_HOURS = 12.0      # a folder listed this recently is taken as listed, unasked
PARTIAL_KEEP_DAYS = 7.0         # older than this, a partial file is ignored


def partial_path(index_path: Path) -> Path:
    return index_path.with_name(index_path.name + ".partial")


def _roots_key(roots: Iterable[Any], depth: int) -> str:
    return json.dumps([sorted(os.path.normcase(os.path.normpath(str(r))) for r in roots), int(depth)])


def load_partial(index_path: Path, roots: Iterable[Any], depth: int, now: float) -> Dict[str, Any]:
    """{"started", "folders"} of an unfinished listing of these same roots, or {} (none, another
    listing's, too old, or unreadable)."""
    try:
        with gzip.open(partial_path(index_path), "rt", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, EOFError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != PARTIAL_SCHEMA \
            or data.get("key") != _roots_key(roots, depth) or not isinstance(data.get("folders"), dict):
        return {}
    started = float(data.get("started") or 0)
    if now - started > PARTIAL_KEEP_DAYS * 86400:
        return {}
    return {"started": started, "folders": data["folders"]}


def save_partial(index_path: Path, roots: Iterable[Any], depth: int, started: float,
                 folders: Dict[str, Any]) -> None:
    p = partial_path(index_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({"schema": PARTIAL_SCHEMA, "key": _roots_key(roots, depth), "started": started,
                   "folders": folders}, fh, separators=(",", ":"))
    os.replace(tmp, p)


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


def lock_path(index_path: Path) -> Path:
    return index_path.with_name("full_listing.lock")


def full_listing_running(index_path: Path, max_hours: float = 16.0) -> bool:
    """True while a full listing holds the lock (and has not been at it longer than any could)."""
    try:
        return time.time() - lock_path(index_path).stat().st_mtime < max_hours * 3600
    except OSError:
        return False


def refresh(roots: List[Path], path: Path, depth: int = 10, full: bool = False,
            full_days: float = 0.0, now: Optional[float] = None,
            progress: Optional[Any] = None, every: int = 2000, recent_days: float = 90.0,
            top_levels: int = 2, workers: Optional[int] = None, save_every: int = 2000) -> Dict[str, Any]:
    """Bring the index up to date and save it; the summary of what was done.

    A QUICK REFRESH (the hourly one) checks only the top levels (clients, their job folders) and
    folders that changed in the last `recent_days`: a new job appears as a new folder near the
    top, and work goes on inside recently changed ones. A dormant folder is taken from the last
    index unchecked; the resolver re-lists a chosen job's folders live, so nothing is priced on
    a stale listing, and a full listing (--full, overnight) catches the rest.

    `workers` folders are asked of the share at once (SDI_DRAWING_INDEX_WORKERS, 8; 1 is one at a
    time). Every `save_every` folders newly listed, progress is saved to the partial file."""
    now = now if now is not None else time.time()
    if workers is None:
        try:
            workers = int(os.getenv("SDI_DRAWING_INDEX_WORKERS") or 8)
        except ValueError:
            workers = 8
    workers = max(1, min(32, int(workers)))
    if not full and full_listing_running(path):
        # THE FULL LISTING IS RUNNING (overnight, ~10 hours): it writes the index when it ends, so a
        # quick refresh now would only race it. The index as it stands is reported instead.
        current = load(path) or {}
        out = summary(current) if current else {"built_at": "", "folders": 0, "drawings": 0, "roots": {}, "last": {}}
        out["skipped"] = "a full listing is running"
        return out
    lock = lock_path(path)
    if full:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}\n", encoding="utf-8")
    try:
        return _refresh(roots, path, depth, full, full_days, now, progress, every, recent_days, top_levels,
                        workers, save_every)
    finally:
        if full:
            try:
                lock.unlink()
            except OSError:
                pass


def _visit(job: Tuple[Path, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]
           ) -> Tuple[str, Optional[Dict[str, Any]]]:
    """One folder asked of the share: ("reused" | "resumed" | "listed" | "unreadable", record).
    `prev` is the folder as the last index held it (None: not to be reused), `saved` as an
    unfinished listing held it. Either stands when the folder's own time has not changed."""
    f, prev, saved = job
    try:
        mt = round(f.stat().st_mtime, 1)
    except OSError:
        return "unreadable", None
    if prev is not None and prev.get("mtime") == mt:
        return "reused", prev
    if saved is not None and saved.get("mtime") == mt:
        return "resumed", saved
    got = _list(f)
    if got is None:
        return "unreadable", None
    return "listed", dict(got, mtime=mt)


def _refresh(roots: List[Path], path: Path, depth: int, full: bool, full_days: float, now: float,
             progress: Optional[Any], every: int, recent_days: float, top_levels: int,
             workers: int = 1, save_every: int = 2000) -> Dict[str, Any]:
    old = load(path) or {}
    old_folders: Dict[str, Any] = old.get("folders") or {}
    if not full and full_days and old.get("full_at") and now - float(old["full_at"]) > full_days * 86400:
        full = True
    recent = now - recent_days * 86400
    partial = load_partial(path, roots, depth, now)
    saved: Dict[str, Any] = partial.get("folders") or {}
    # The partial file keeps the time its FIRST listing began, however often it is resumed, so
    # "listed this recently" is never said of a folder listed before that.
    began = float(partial.get("started") or now)
    trusted = bool(saved) and now - began <= PARTIAL_TRUST_HOURS * 3600
    folders: Dict[str, Any] = {}
    stats = {"listed": 0, "reused": 0, "unreadable": 0}
    roots_out: Dict[str, Any] = {}
    started = time.time()
    said = [0]
    unsaved = [0]

    def _tell(key: str) -> None:
        if progress and every and len(folders) // every > said[0]:
            said[0] = len(folders) // every
            progress(f"  ... {len(folders)} folder(s), listed {stats['listed']}, reused {stats['reused']}, "
                     + (f"resumed {stats['resumed']}, " if stats.get("resumed") else "")
                     + f"{round(time.time() - started)} s, now in {key}")

    def _keep() -> None:
        if save_every and unsaved[0] >= save_every:
            unsaved[0] = 0
            try:
                save_partial(path, roots, depth, began, folders)
            except OSError:
                pass                                    # progress not saved; the listing goes on

    pool = None
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="drawing-index")
    try:
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
            # LEVEL BY LEVEL, IN ONE ORDER WHATEVER THE NUMBER OF WORKERS: the folders of a level
            # are asked of the share together and taken in the order they were found, so one
            # worker and eight make the same index.
            level: List[Tuple[Path, int]] = [(root, 0)]
            while level:
                nxt: List[Tuple[Path, int]] = []
                for at in range(0, len(level), 256):
                    chunk = level[at:at + 256]
                    done: List[Any] = [None] * len(chunk)
                    ask: List[int] = []
                    jobs = []
                    for i, (f, lvl) in enumerate(chunk):
                        key = str(f)
                        prev = old_folders.get(key)
                        if prev is not None and not full and lvl > top_levels \
                                and float(prev.get("mtime") or 0) < recent:
                            done[i] = ("dormant", prev)        # kept as last listed, not checked
                        elif trusted and key in saved:
                            done[i] = ("resumed", saved[key])  # listed within hours: not asked again
                        else:
                            ask.append(i)
                            jobs.append((f, None if full else prev, saved.get(key)))
                    got = list(pool.map(_visit, jobs)) if pool is not None else [_visit(j) for j in jobs]
                    for i, res in zip(ask, got):
                        done[i] = res
                    for (f, lvl), res in zip(chunk, done):
                        how, rec = res
                        if rec is None:
                            stats["unreadable"] += 1
                            continue
                        stats[how] = stats.get(how, 0) + 1
                        if how == "listed":
                            unsaved[0] += 1
                        key = str(f)
                        folders[key] = rec
                        _tell(key)
                        if lvl < depth:
                            nxt.extend((f / d, lvl + 1) for d in rec.get("dirs") or [])
                    _keep()
                level = nxt
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
    index = {"schema": SCHEMA, "built_at": now, "full_at": now if full else old.get("full_at") or now,
             "roots": roots_out, "depth": depth, "folders": folders,
             "last": dict(stats, seconds=round(time.time() - started, 1), full=full, workers=workers)}
    save(path, index)
    build_db(index, db_path(path))
    try:
        partial_path(path).unlink()                     # the listing completed: nothing to resume
    except OSError:
        pass
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


# THE RULE THAT READS A DRAWING NUMBER FROM A FILE NAME, BY VERSION. Each file's number is worked
# out once, when the database is made; a database made under an older rule is made again on its
# first use (2: a customer's item number in front, "0359829_12674-01-GA_...PDF", JG 10 Nov 2026).
# 3: an assembly word standing apart from its number, "12773-02 GA.SLDASM" (12 Nov 2026).
DID_RULE = "3"


def build_db(index: Dict[str, Any], db: Path) -> int:
    import sqlite3
    sys.path.insert(0, str(HERE))
    from pack_resolver import drawing_id
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_name(f"{db.name}.{os.getpid()}.tmp")
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
                         ("roots", json.dumps(index.get("roots") or {})),
                         ("did_rule", DID_RULE)])
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
    return {"built_at": float(meta.get("built_at") or 0), "roots": json.loads(meta.get("roots") or "{}"),
            "did_rule": str(meta.get("did_rule") or "1")}


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
    ap.add_argument("--log", default="", help="append the output to this file (the scheduled full listing)")
    ap.add_argument("--convert", action="store_true",
                    help="build the lookup database (index.sqlite) from the existing index, without listing the share")
    args = ap.parse_args(argv)
    if args.log:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = open(args.log, "a", encoding="utf-8", buffering=1)
        print(f"\n[drawing-index] {datetime.now().isoformat(timespec='seconds')} "
              f"{'full listing' if args.full else 'refresh'} started", flush=True)
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
        if s.get("skipped"):
            print(f"Not refreshed: {s['skipped']} (it writes the index when it ends).", flush=True)
            return 0
        last = s["last"]
        print(f"{s['folders']} folder(s), {s['drawings']} drawing file(s); listed {last.get('listed')}, "
              f"reused {last.get('reused')}, resumed from a stopped listing {last.get('resumed', 0)}, "
              f"dormant (not checked) {last.get('dormant', 0)}, unreadable "
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
