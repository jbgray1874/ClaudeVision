"""
SameDay's picture index, kept current from K: - once a day, with a report.

5 November 2026 (James): "e-mail me every day with any changes to [the index on K:] ... if it's updated we copy auto
with the daily check to the server." Muhammad's weekly update puts a new build on K: (index-for-server): the picture
index (all_img_index.npz), the job list built with it (projects.db), the thumbnails and BUILD.txt. SameDay reads the
thumbnails from K: where they are; the index and the job list it keeps on the server, so a new build has to be
brought across - by sameday_watch.py, once a day, with the same checks as deploy/Copy-SameDay-Index.ps1:

  * a new build only - BUILD.txt on K: differs from the copy kept beside the server's index
  * both files finished copying (not written to for two minutes), the index opens, the job list has exactly as many
    pictures as the index (picture n is job-list row n) - checked again on the copies, before anything is swapped
  * room on the server's C: for both twice over, with 20 GB left free (a production server)
  * the old job list and index kept in backups (the two newest automatic ones are kept)
  * SameDay stopped for the seconds a rename takes, started again, and watched until picture matching is on; if it
    can't read the new job list, the old one goes straight back

It runs as SYSTEM on the server, like SameDay's own service, which reads K: the same way. It never touches the keys,
the chats or anything of SameDay's but these two files.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

K_INDEX = (r"\\sdi-dc01\shareddata$\Shared\IT\AI & Automation\Design\SDI Same Day Intelligence"
           r"\index-for-server")
SPARE_GB = 20
KEEP_AUTO_BACKUPS = 2


def _opt(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def build_text(path: Path) -> str:
    """BUILD.txt as one line, or '' when there is none."""
    try:
        return " | ".join(x.strip() for x in path.read_text(encoding="utf-8", errors="ignore").splitlines()
                          if x.strip())[:600]
    except OSError:
        return ""


def pictures_in(npz: Path) -> int:
    """How many pictures the index holds (from emb.npy's header) - 0 when it won't open (a half-copied one won't)."""
    try:
        with zipfile.ZipFile(npz) as z:
            name = next((n for n in z.namelist() if n.split("/")[-1] == "emb.npy"), None)
            if not name:
                return 0
            with z.open(name) as f:
                head = f.read(512).decode("latin-1")
        m = re.search(r"'shape':\s*\((\d+),", head)
        return int(m.group(1)) if m else 0
    except (OSError, zipfile.BadZipFile, ValueError):
        return 0


def rows_in(db: Path) -> int:
    """How many pictures the job list holds - 0 when it isn't a complete database."""
    try:
        with open(db, "rb") as f:
            if not f.read(16).startswith(b"SQLite format 3"):
                return 0
        con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
        try:
            return int(con.execute("SELECT count(*) FROM project_images").fetchone()[0])
        finally:
            con.close()
    except (OSError, sqlite3.Error, ValueError):
        return 0


def count_thumbs(folder: Path, limit_s: float = 300) -> Optional[int]:
    """The thumbnails on K: (417,787 on 5 Nov) - None if the count takes longer than limit_s."""
    t0, n, stack = time.time(), 0, [str(folder)]
    try:
        while stack:
            for e in os.scandir(stack.pop()):
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                else:
                    n += 1
            if time.time() - t0 > limit_s:
                return None
    except OSError:
        return None
    return n


def free_gb(path: str) -> Optional[float]:
    try:
        return shutil.disk_usage(path).free / 1e9
    except OSError:
        return None


def _sc(action: str, name: str = "SDISameDay") -> None:
    subprocess.run(["sc", action, name], capture_output=True, text=True, timeout=60,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def refresh(server: Path, k_dir: Path, get: Callable, service: Callable, sc: Callable = _sc,
            free: Callable = free_gb, settle_s: float = 10, wait_s: float = 360, poll_s: float = 10,
            now: Optional[datetime] = None) -> dict:
    """Bring a new build from K: to the server, if there is one. Returns what was found and done - never raises."""
    now = now or datetime.now()
    rep = {"k_build": "", "server_build": "", "action": "none", "detail": "", "pictures_on": None, "jobs": None}
    npz, db, build = k_dir / "all_img_index.npz", k_dir / "projects.db", k_dir / "BUILD.txt"
    if not db.exists() and (k_dir / "brief_lite" / "projects.db").exists():
        db = k_dir / "brief_lite" / "projects.db"
    s_npz, s_db, s_build = server / "all_img_index.npz", server / "brief_lite" / "projects.db", server / "all_img_index.BUILD.txt"
    rep["k_build"], rep["server_build"] = build_text(build), build_text(s_build)
    try:
        for p in (npz, db):
            st = p.stat()
            rep[p.name] = f"{st.st_size / 1e6:,.0f} MB, {datetime.fromtimestamp(st.st_mtime):%d %b %Y %H:%M}"
    except OSError:
        rep.update(action="skipped", detail="K:'s index or job list can't be read (is index-for-server still there?)")
        return rep
    if not rep["k_build"]:
        rep.update(action="skipped", detail="no BUILD.txt on K: - which build it is can't be told, so nothing is copied")
        return rep
    if rep["k_build"] == rep["server_build"]:
        return rep                                       # the server already has it

    # A new build. Finished copying? Both files the same size a while apart, and not written to for two minutes.
    sizes = {p: p.stat().st_size for p in (npz, db)}
    time.sleep(settle_s)
    for p in (npz, db):
        st = p.stat()
        if st.st_size != sizes[p] or time.time() - st.st_mtime < 120:
            rep.update(action="waiting", detail=f"{p.name} on K: is still being written - tried again tomorrow")
            return rep
    n = pictures_in(npz)
    if not n:
        rep.update(action="skipped", detail="the index on K: won't open - a half-finished copy?")
        return rep
    # 10 Nov 2026: a matching build (269,278 and 269,278) was turned away as "doesn't match". K: is a \\server\share
    # path, and SQLite refuses the file://server/... address it makes, so the count read 0. The job list is checked
    # here only when it can be read from here; it is always checked again below, on the copy on this server.
    k_rows = rows_in(db)
    if k_rows and k_rows != n:
        rep.update(action="skipped", detail=f"the job list on K: doesn't match the index ({k_rows:,} rows, "
                                            f"{n:,} pictures) - not one build")
        return rep
    need = 2 * (npz.stat().st_size + db.stat().st_size) / 1e9 + SPARE_GB
    space = free(str(server))
    if space is None or space < need:
        rep.update(action="skipped", detail=f"not enough room on the server's C: ({space or 0:.1f} GB free, "
                                            f"{need:.1f} GB needed with {SPARE_GB} GB kept free)")
        return rep

    # Copied alongside, checked again, while SameDay keeps running.
    in_npz, in_db = Path(str(s_npz) + ".incoming"), Path(str(s_db) + ".incoming")
    try:
        shutil.copyfile(npz, in_npz)
        shutil.copyfile(db, in_db)
    except OSError as exc:
        for p in (in_npz, in_db):
            p.unlink(missing_ok=True)
        rep.update(action="failed", detail=f"copying from K: failed ({exc})")
        return rep
    got_pics, got_rows = pictures_in(in_npz), rows_in(in_db)
    if got_pics != n or got_rows != n:
        for p in (in_npz, in_db):
            p.unlink(missing_ok=True)
        rep.update(action="failed", detail=f"the copies didn't check out ({got_pics:,} pictures, {got_rows:,} job-list "
                                           f"rows, {n:,} expected) - not one build, nothing swapped")
        return rep

    # Keep what is there now; only the newest automatic backups are kept.
    keep = server / "backups" / f"before-index-auto-{now:%Y%m%d-%H%M%S}"
    keep.mkdir(parents=True, exist_ok=True)
    for p in (s_db, s_npz, s_build):
        if p.exists():
            shutil.copy2(p, keep / p.name)
    for old in sorted((server / "backups").glob("before-index-auto-*"))[:-KEEP_AUTO_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)

    def swap_in(files: list[tuple[Path, Path]]) -> Optional[str]:
        sc("stop")
        t0 = time.time()
        while service("SDISameDay") not in ("STOPPED", "") and time.time() - t0 < 60:
            time.sleep(min(2, poll_s))
        try:
            for src, dst in files:
                os.replace(src, dst)
            return None
        except OSError as exc:
            return str(exc)
        finally:
            sc("start")

    err = swap_in([(in_npz, s_npz), (in_db, s_db)])
    if err:
        swap_in([(keep / p.name, p) for p in (s_db, s_npz) if (keep / p.name).exists()])
        rep.update(action="failed", detail=f"the swap failed ({err}) - what was there has been put back")
        return rep
    shutil.copyfile(build, s_build)

    # Does SameDay use it?
    t0, past = time.time(), {}
    while time.time() - t0 < wait_s:
        time.sleep(poll_s)
        code, body, _ = get(_opt("SAMEDAY_URL", "http://127.0.0.1:5020").rstrip("/") + "/api/version")
        past = (body or {}).get("past_work") or {} if code == 200 and isinstance(body, dict) else {}
        if past and (past.get("pictures") or "loading" not in str(past.get("why") or "")):
            break
    rep["pictures_on"], rep["jobs"] = bool(past.get("pictures")), past.get("jobs")
    if past and not past.get("jobs"):                    # can't read the new job list: the old one goes back
        swap_in([(keep / p.name, p) for p in (s_db, s_npz) if (keep / p.name).exists()])
        if (keep / s_build.name).exists():
            shutil.copyfile(keep / s_build.name, s_build)
        rep.update(action="failed", detail=f"SDI Live couldn't read the new job list ({past.get('why')}) - "
                                           "the old one has been put back")
        return rep
    rep.update(action="copied", server_build=build_text(s_build),
               detail="picture matching is on" if rep["pictures_on"] else
               f"copied, but picture matching isn't on yet ({past.get('why') or 'no answer'})")
    return rep


def compose(rep: dict, thumbs: Optional[int], thumbs_before: Optional[int], now: datetime,
            backup: str = "") -> dict:
    """The daily email. `backup`: last night's backup of SameDay's chats, in one line (sameday_backup.summary)."""
    head = {"none": "no change", "copied": "new build copied to the server", "waiting": "new build still arriving",
            "skipped": "new build NOT copied", "failed": "new build NOT copied"}.get(rep["action"], rep["action"])
    lines = [f"Today: {head}" + (f" - {rep['detail']}" if rep["detail"] else ""), "",
             f"On K: {rep['k_build'] or '(no BUILD.txt)'}",
             f"On the server: {rep['server_build'] or '(none recorded)'}", ""]
    for name in ("all_img_index.npz", "projects.db"):
        if rep.get(name):
            lines.append(f"{name} on K:: {rep[name]}")
    if thumbs is not None:
        change = "" if thumbs_before is None else f" ({thumbs - thumbs_before:+,} since yesterday)"
        lines.append(f"Thumbnails on K:: {thumbs:,}{change}")
    if rep.get("jobs") is not None:
        lines.append(f"SDI Live now: {rep['jobs']} past jobs, picture matching {'on' if rep['pictures_on'] else 'off'}")
    if backup:
        lines += ["", backup]
    lines += ["", now.strftime("Checked %A %d %B %Y, %H:%M on the server (sameday_watch.py, daily).")]
    text = "\n".join(lines)
    import html as _h
    body = ("<div style='font:14px/1.5 Segoe UI,Arial,sans-serif;color:#17181B'>"
            + "".join(f"<p style='margin:0 0 6px'>{_h.escape(x)}</p>" if x else "<br>" for x in lines) + "</div>")
    return {"subject": f"SDI Live index: {head}", "text": text, "html": body}
