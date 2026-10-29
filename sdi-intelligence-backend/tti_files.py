"""Find files in the TTi folders by name: Design, Production and Prototype.

Liam asked to search W:\\Design\\Customers April 08 Onwards\\TTi, W:\\Production\\TTi
and W:\\Prototype\\TTi from the TTI app and from ChatGPT. Those folders hold a
great many files on a network share, too many to walk on every question, so
an index of names (tools/tti_index_folders.py, run on a schedule) is searched
instead, and every answer says how old the index is.

── WHAT THIS CAN AND CANNOT DO ──────────────────────────────────────────────
It finds files and folders by name and path, and says where they are. It does
not open, copy, move or delete anything, and does not read inside files. The
folders are configuration (SDI_TTI_FOLDERS), never a request parameter, so a
search can only ever look inside them.

The index is built by the server's own account, so it lists every name that
account can see. It is for the people on SDI_TTI_OIDS, like the despatch view.
"""
import datetime
import os
import re
import sqlite3
import time
from pathlib import Path

DEFAULT_FOLDERS = (r"W:\Design\Customers April 08 Onwards\TTi"
                   r"|W:\Production\TTi"
                   r"|W:\Prototype\TTi")
DEFAULT_INDEX = r"C:\SDIIntelligence\tti\tti_folders.sqlite3"
MAX_WORDS = 8
MAX_ENTRIES = 3_000_000           # a safety stop, far above three customer folders

KINDS = {
    "drawings": {".pdf", ".dxf", ".dwg", ".slddrw"},
    "models": {".sldprt", ".sldasm", ".step", ".stp", ".igs", ".iges", ".x_t", ".stl"},
    "images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".webp"},
    "documents": {".xlsx", ".xlsm", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".txt",
                  ".csv", ".msg", ".eml", ".rtf"},
}


class NotReady(Exception):
    """The index has not been built, or cannot be read. The message says which."""


def index_path() -> str:
    return os.getenv("SDI_TTI_FOLDER_INDEX", "").strip() or DEFAULT_INDEX


def _drive_map() -> dict:
    """SDI_DRIVE_MAP, as config.py reads it: "W=\\\\server\\share;K=..."."""
    raw = os.getenv("SDI_DRIVE_MAP", r"K=\\sdi-dc01\shareddata$\Shared")
    out = {}
    for pair in raw.split(";"):
        if "=" in pair:
            letter, unc = pair.split("=", 1)
            letter, unc = letter.strip().rstrip(":").upper(), unc.strip().rstrip("\\/")
            if len(letter) == 1 and letter.isalpha() and unc:
                out[letter] = unc
    return out


def to_unc(path: str):
    """(path the server can open, problem). A service has no mapped drives, so
    W:\\... must become \\\\server\\share\\... before it means anything."""
    p = path.strip()
    if len(p) >= 2 and p[1] == ":":
        unc = _drive_map().get(p[0].upper())
        if not unc:
            return p, (f"{p[0].upper()}: has no network path on the server. Add "
                       f"{p[0].upper()}=\\\\server\\share to SDI_DRIVE_MAP in .env.")
        rest = p[2:].lstrip("\\/")
        return (unc + "\\" + rest) if rest else unc, None
    return p, None


def _label(path: str) -> str:
    parts = [x for x in re.split(r"[\\/]+", path) if x]
    if parts and parts[0].endswith(":"):
        parts = parts[1:]
    elif path.startswith("\\\\") and len(parts) > 2:
        parts = parts[2:]                                  # past \\server\share
    return parts[0] if parts else path


def folders() -> list:
    """The folders searched: [{label, shown, unc, problem}]. "Label=path" names one."""
    out = []
    for item in os.getenv("SDI_TTI_FOLDERS", DEFAULT_FOLDERS).split("|"):
        item = item.strip()
        if not item:
            continue
        label, _, path = item.partition("=") if re.match(r"^[^\\/:=]{2,}=", item) else ("", "", item)
        path = path.strip().rstrip("\\/")
        unc, problem = to_unc(path)
        name = label.strip() or _label(path)
        taken = {f["label"].lower() for f in out}
        n, base = 2, name
        while name.lower() in taken:              # two folders, one label: keep them apart
            name, n = f"{base} {n}", n + 1
        out.append({"label": name, "shown": path, "unc": unc, "problem": problem})
    return out


# ── building the index ──────────────────────────────────────────────────────

def build(roots=None, index=None, max_entries=MAX_ENTRIES, log=print) -> dict:
    """Walk each folder and write a fresh index, replacing the old one only when done."""
    roots = folders() if roots is None else roots
    index = index or index_path()
    Path(index).parent.mkdir(parents=True, exist_ok=True)
    tmp = index + ".building"
    if os.path.exists(tmp):
        os.remove(tmp)
    started = time.time()
    con = sqlite3.connect(tmp)
    con.executescript("""
        CREATE TABLE files (root INTEGER, rel TEXT, name TEXT, low TEXT, name_low TEXT,
                            ext TEXT, is_dir INTEGER, size INTEGER, mtime REAL);
        CREATE TABLE roots (id INTEGER, label TEXT, shown TEXT, unc TEXT,
                            entries INTEGER, unreadable INTEGER, problem TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    total = 0
    for rid, root in enumerate(roots):
        entries = unreadable = 0
        problem = root.get("problem")
        base = root["unc"]
        if not problem and not os.path.isdir(base):
            problem = f"{root['shown']} could not be opened from the server ({base})."
        batch, stack = [], ([""] if not problem else [])
        while stack and total < max_entries:
            rel_dir = stack.pop()
            try:
                with os.scandir(os.path.join(base, rel_dir) if rel_dir else base) as it:
                    for e in it:
                        rel = os.path.join(rel_dir, e.name) if rel_dir else e.name
                        try:
                            is_dir = e.is_dir(follow_symlinks=False)
                            st = e.stat(follow_symlinks=False)
                        except OSError:
                            unreadable += 1
                            continue
                        if is_dir:
                            stack.append(rel)
                        ext = "" if is_dir else os.path.splitext(e.name)[1].lower()
                        batch.append((rid, rel, e.name, rel.lower(), e.name.lower(), ext,
                                      int(is_dir), 0 if is_dir else st.st_size, st.st_mtime))
                        entries += 1
                        total += 1
                        if len(batch) >= 5000:
                            con.executemany("INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?)", batch)
                            batch.clear()
            except OSError:
                unreadable += 1
        if batch:
            con.executemany("INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?)", batch)
        if total >= max_entries:
            problem = (problem or "") + f" Stopped at {max_entries} entries."
        con.execute("INSERT INTO roots VALUES (?,?,?,?,?,?,?)",
                    (rid, root["label"], root["shown"], base, entries, unreadable, problem))
        log(f"  {root['label']:<12} {entries:>8} entries, {unreadable} unreadable"
            + (f"  PROBLEM: {problem}" if problem else ""))
    built = datetime.datetime.now(datetime.timezone.utc).isoformat()
    con.executemany("INSERT INTO meta VALUES (?,?)", [
        ("built", built), ("seconds", f"{time.time() - started:.0f}"), ("entries", str(total))])
    con.commit()
    con.close()
    for attempt in range(10):                      # a search may hold the old file open
        try:
            os.replace(tmp, index)
            break
        except PermissionError:
            time.sleep(1 + attempt)
    else:
        raise OSError(f"Could not replace {index}: it stayed open. The new index is at {tmp}.")
    return {"built": built, "entries": total, "seconds": round(time.time() - started)}


# ── reading the index ───────────────────────────────────────────────────────

def _open(index=None):
    path = index or index_path()
    if not os.path.isfile(path):
        raise NotReady("The TTi folder index has not been built yet. It is built by "
                       "tools/tti_index_folders.py on the server.")
    try:
        return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise NotReady(f"The TTi folder index could not be read ({exc}).")


def status(index=None) -> dict:
    con = _open(index)
    try:
        meta = dict(con.execute("SELECT key, value FROM meta"))
        roots = [{"label": r[0], "shown": r[1], "entries": r[2], "unreadable": r[3],
                  "problem": r[4]} for r in
                 con.execute("SELECT label, shown, entries, unreadable, problem FROM roots ORDER BY id")]
    finally:
        con.close()
    return {"built": meta.get("built"), "entries": int(meta.get("entries") or 0),
            "age_hours": _age_hours(meta.get("built")), "folders": roots}


def _age_hours(iso):
    try:
        t = datetime.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return round((datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 3600, 1)


def _like(word: str) -> str:
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search(query: str, folder: str = "", kind: str = "", limit: int = 60, index=None) -> dict:
    """Files and folders whose path contains every word, best name matches first."""
    words = [w for w in re.split(r"\s+", str(query or "").lower().strip()) if w][:MAX_WORDS]
    if not words:
        raise ValueError("Type part of a file or folder name to search for.")
    con = _open(index)
    try:
        where = ["f.low LIKE ? ESCAPE '\\'" for _ in words]
        params = [_like(w) for w in words]
        labels = {r[0].lower(): r[1] for r in con.execute("SELECT label, id FROM roots")}
        if folder:
            if folder.lower() not in labels:
                raise ValueError(f"No TTi folder called {folder!r}. The folders are: "
                                 + ", ".join(sorted(k.title() for k in labels)) + ".")
            where.append("f.root = ?")
            params.append(labels[folder.lower()])
        kind = (kind or "").lower()
        if kind == "folders":
            where.append("f.is_dir = 1")
        elif kind in KINDS:
            exts = sorted(KINDS[kind])
            where.append("f.ext IN (" + ",".join("?" * len(exts)) + ")")
            params += exts
        elif kind:
            raise ValueError("Kind must be one of: folders, " + ", ".join(sorted(KINDS)) + ".")
        clause = " AND ".join(where)
        total = con.execute(f"SELECT COUNT(*) FROM files f WHERE {clause}", params).fetchone()[0]
        name_hits = " + ".join("(instr(f.name_low, ?) > 0)" for _ in words)
        rows = con.execute(
            f"SELECT r.label, r.shown, f.rel, f.name, f.ext, f.is_dir, f.size, f.mtime, "
            f"({name_hits}) AS nh FROM files f JOIN roots r ON r.id = f.root "
            f"WHERE {clause} ORDER BY nh DESC, f.mtime DESC LIMIT ?",
            words + params + [max(1, min(int(limit), 200))]).fetchall()
        built = dict(con.execute("SELECT key, value FROM meta")).get("built")
    finally:
        con.close()
    matches = []
    for label, shown, rel, name, ext, is_dir, size, mtime, _ in rows:
        matches.append({
            "folder": label, "name": name, "is_folder": bool(is_dir),
            "path": shown + "\\" + rel.replace("/", "\\"),
            "kind": "folder" if is_dir else next((k for k, v in KINDS.items() if ext in v), "other"),
            "size": None if is_dir else size,
            "modified": datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc).isoformat()})
    age = _age_hours(built)
    return {"searched_for": " ".join(words), "match_count": total, "matches": matches,
            "index_built": built, "index_age_hours": age,
            "note": ("Searched by file and folder name, not inside files. "
                     + (f"The index was built {age:.0f} hours ago, so anything newer is "
                        f"not in it yet." if age is not None else ""))}
