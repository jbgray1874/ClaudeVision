"""
SameDay's chats and work, copied to the server's D: every night - by sameday_watch.py.

5 November 2026 (James: "yes, definitely need a back up"): everything SameDay is used for was on the server's C:
alone - the chats and briefs (brief_lite\\lite.db), Craft Memory (craft\\craft.db), the renders, GAs and PDFs it made
(brief_lite\\out), what the AMs sent it (brief_lite\\client_files) and its settings (studio_data). Once a night, from
SAMEDAY_BACKUP_HOUR (1am), they are copied to D: (the Data drive, 520 GB free on 5 Nov):

  D:\\SameDayBackups\\databases\\<date>\\   the databases, copied with SQLite's own backup (safe while SameDay is
                                          writing), each checked after copying. The newest 30 nights are kept.
  D:\\SameDayBackups\\files\\               the files: new and changed ones are copied, nothing is ever deleted - so a
                                          chat's pictures deleted on C: are still here.

Never copied: the keys (.env), the picture index, the job index and the thumbnails (they come from K:). It reads
SameDay's files and writes only under SAMEDAY_BACKUP_TO. D: holds the server's other data too (a production server),
so a copy that would leave it under SAMEDAY_BACKUP_KEEP_FREE_GB (50 GB) free is not made - and the watch emails that.

To put it back: stop SDISameDay, copy databases\\<date>\\lite.db over C:\\SDI_Automation\\brief_lite\\lite.db (and
craft.db over craft\\craft.db), copy the folders in files\\ back over C:\\SDI_Automation, start SDISameDay.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

DATABASES = ("brief_lite/lite.db", "craft/craft.db")
FOLDERS = ("brief_lite/out", "brief_lite/client_files", "studio_data")
# never: the keys, a database (copied safely above, never as a file in use), half-copied files
SKIP = re.compile(r"(^|[\\/])\.env(\.|$)|\.(db|db-wal|db-shm|db-journal|sqlite|incoming|tmp|part)$", re.I)
KEEP_NIGHTS = 30
KEEP_FREE_GB = 50
TIME_S = 1200          # 20 minutes a night; a first copy too big for that carries on the next night


def _opt(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def free_gb(path: str) -> Optional[float]:
    try:
        return shutil.disk_usage(path).free / 1e9
    except OSError:
        return None


def copy_db(src: Path, dst: Path) -> dict:
    """A consistent copy of a database SameDay may be writing to, then checked. Never writes to the source."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    tmp.unlink(missing_ok=True)
    s = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
    d = sqlite3.connect(tmp)
    try:
        s.backup(d)
        check = d.execute("PRAGMA quick_check").fetchone()[0]
        tables = {r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {t: d.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("sessions", "messages") if t in tables}
    finally:
        d.close()
        s.close()
    if check != "ok":
        tmp.unlink(missing_ok=True)
        return {"ok": False, "detail": f"the copy didn't check out ({check})"}
    os.replace(tmp, dst)
    return {"ok": True, "mb": round(dst.stat().st_size / 1e6, 1), **counts}


def files_to_copy(src_root: Path, dst_root: Path) -> list[tuple[Path, Path, int]]:
    """New or changed files under src_root, as (from, to, bytes)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
        for fn in filenames:
            src = Path(dirpath) / fn
            if SKIP.search(str(src)):
                continue
            dst = dst_root / src.relative_to(src_root)
            try:
                st = src.stat()
                if dst.exists():
                    dt = dst.stat()
                    if dt.st_size == st.st_size and dt.st_mtime >= st.st_mtime - 2:
                        continue
                out.append((src, dst, st.st_size))
            except OSError:
                continue
    return out


def backup(sameday: Path, to: Path, now: Optional[datetime] = None, free: Callable = free_gb,
           keep_free: float = KEEP_FREE_GB, keep_nights: int = KEEP_NIGHTS, time_s: float = TIME_S) -> dict:
    """One night's backup. Returns what was done - never raises."""
    now = now or datetime.now()
    rep = {"status": "ok", "detail": "", "when": now.isoformat(timespec="minutes"), "where": str(to),
           "databases": {}, "files_copied": 0, "files_mb": 0.0, "files_left": 0, "free_gb": None}
    try:
        space = free(str(to.anchor or to))
        rep["free_gb"] = round(space, 1) if space is not None else None
        if space is None:
            return {**rep, "status": "failed", "detail": f"{to.anchor or to} can't be read on this server"}
        dbs = [(sameday / rel, rel) for rel in DATABASES if (sameday / rel).exists()]
        if not any(rel == DATABASES[0] for _, rel in dbs):
            return {**rep, "status": "failed", "detail": f"SameDay's chats ({sameday / DATABASES[0]}) weren't found"}
        need_db = sum(p.stat().st_size for p, _ in dbs) / 1e9
        if space - need_db < keep_free:
            return {**rep, "status": "skipped", "detail": f"not copied: {to.anchor} has {space:.0f} GB free and "
                                                          f"{keep_free:.0f} GB must stay free"}
        night = to / "databases" / now.strftime("%Y-%m-%d")
        bad = []
        for src, rel in dbs:
            r = copy_db(src, night / Path(rel).name)
            rep["databases"][Path(rel).name] = r
            if not r["ok"]:
                bad.append(f"{Path(rel).name}: {r['detail']}")
        nights = sorted(p for p in (to / "databases").iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d\d-\d\d", p.name))
        for old in nights[:-keep_nights]:
            shutil.rmtree(old, ignore_errors=True)

        todo = []
        for rel in FOLDERS:
            if (sameday / rel).is_dir():
                todo += files_to_copy(sameday / rel, to / "files" / rel)
        need = sum(n for _, _, n in todo) / 1e9
        space = free(str(to.anchor or to)) or 0
        if todo and space - need < keep_free:
            # as many as fit, newest first - the latest work matters most
            todo.sort(key=lambda x: -x[0].stat().st_mtime)
            room, fit = max(0.0, space - keep_free) * 1e9, []
            for item in todo:
                if item[2] <= room:
                    fit.append(item)
                    room -= item[2]
            rep["files_left"] = len(todo) - len(fit)
            todo = fit
        t0, done_b = time.time(), 0
        for i, (src, dst, n) in enumerate(todo):
            if time.time() - t0 > time_s:
                rep["files_left"] += len(todo) - i
                break
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.name + ".part")
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
                rep["files_copied"] += 1
                done_b += n
            except OSError:
                rep["files_left"] += 1
        rep["files_mb"] = round(done_b / 1e6, 1)
        after = free(str(to.anchor or to))
        rep["free_gb"] = round(after, 1) if after is not None else rep["free_gb"]
        if bad:
            rep.update(status="failed", detail="; ".join(bad))
        elif rep["files_left"]:
            rep.update(status="partial", detail=f"{rep['files_left']:,} files not copied yet (room on "
                                                f"{to.anchor} or time) - the rest tomorrow night")
    except Exception as exc:          # noqa: BLE001 - a backup that can't run is reported, never a crash of the watch
        rep.update(status="failed", detail=f"{type(exc).__name__}: {str(exc)[:200]}")
    return rep


def summary(rep: Optional[dict]) -> str:
    """One line for the daily email."""
    if not rep:
        return "Backup of SameDay's chats (D:): not run yet - it runs from 1am."
    when = rep.get("when", "")[:16].replace("T", " ")
    lite = (rep.get("databases") or {}).get("lite.db") or {}
    what = (f"{lite.get('sessions', 0):,} chats, {lite.get('messages', 0):,} lines" if lite.get("ok") else "")
    files = f"{rep.get('files_copied', 0):,} new files ({rep.get('files_mb', 0):,.0f} MB)"
    free = f"; D: {rep['free_gb']:,.0f} GB free" if rep.get("free_gb") is not None else ""
    if rep.get("status") == "ok":
        return f"Backup of SameDay's chats (D:): done {when} - {what}, {files}{free}."
    return f"Backup of SameDay's chats (D:): {rep.get('status', '').upper()} {when} - {rep.get('detail')}{free}."


def problem(rep: Optional[dict], now: datetime) -> Optional[dict]:
    """A problem for the watch to email: the last backup failed or wasn't made, or none for over a day and a half."""
    fix = ("Check the server's D: (free space, and that it is there) and the watch's log "
           r"(C:\ClaudeVision\sdi-intelligence-backend\logs\sameday_watch.log). It tries again the next night.")
    if not rep:
        return None
    if rep.get("status") in ("failed", "skipped"):
        return {"key": "backup", "level": "warn", "title": f"SameDay's nightly backup wasn't made: {rep.get('detail')}",
                "fix": fix}
    try:
        age = now - datetime.fromisoformat(rep.get("when", ""))
    except ValueError:
        return None
    if age > timedelta(hours=36):
        return {"key": "backup", "level": "warn",
                "title": f"SameDay's nightly backup hasn't run since {rep.get('when', '')[:16].replace('T', ' ')}",
                "fix": fix}
    return None


if __name__ == "__main__":             # by hand on the server: python sameday_backup.py
    import json
    print(json.dumps(backup(Path(_opt("SAMEDAY_DIR", r"C:\SDI_Automation")),
                            Path(_opt("SAMEDAY_BACKUP_TO", r"D:\SameDayBackups"))), indent=1))
