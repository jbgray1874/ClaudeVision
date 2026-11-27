"""Liam's project tracker, read from his SharePoint as the person asking.

Liam Treharne, 29 October 2026: the Milwaukee Amsterdam Conference 2027
tracker (PC 402426) as a trial, and, if it works, an account-wide tracker for
Liam, Nick and Callum. He wants to ask questions of it, and one column holds
W:\\ locations of PDF drawings he wants to open.

── READ WHERE IT LIVES, AS WHOEVER IS ASKING ───────────────────────────────
The tracker stays in the TTi Projects SharePoint site and is read there with
the signed-in person's own Microsoft access, exactly like Sue's Despatch Plan:
someone who cannot open it in SharePoint gets "cannot open" here too, and
nobody inherits access from the server. The file is configuration
(SDI_PROJECT_TRACKERS), never a request parameter.

── ANY LAYOUT ───────────────────────────────────────────────────────────────
Nobody here has seen the sheet's columns yet, and an account-wide tracker will
have others. So no column is assumed: each sheet's heading row is found, every
row is kept as heading -> value, and any cell that is (or links to) a drive or
network path is offered as a file to open. Answers name the file, sheet and
row, so anything can be checked at source.

It only reads. Nothing here writes to the tracker.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import re
import threading
from urllib.parse import quote

import httpx

import tti_plan_source as sp

DEFAULT_SITE = "sdidisplays.sharepoint.com:/sites/TTiProjects2022"
# "Label=what": `what` is a file name (found anywhere on the site), a file path,
# or a folder path (every spreadsheet directly in it). "|" between trackers.
DEFAULT_TRACKERS = "Amsterdam Conference 2027=TRACKER - MILWAUKEE AMSTERDAM CONFERENCE 2027.xlsx"
SHEET_TYPES = (".xlsx", ".xlsm")
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 3000
MAX_COLUMNS = 80

# A drive path (W:\..., W:/...) or a network one (\\server\share\...), in a cell
# or behind a hyperlink, up to the end of the line or a character a path cannot have.
_PATH = re.compile(r'(?:file:/{2,3})?((?:[A-Za-z]:[\\/]|\\\\[\w.$-]+\\)[^\r\n\t"<>|?*]+)')


class Unavailable(Exception):
    def __init__(self, message: str, reason: str = ""):
        super().__init__(message)
        self.reason = reason


def site() -> str:
    return (os.getenv("SDI_PROJECT_TRACKER_SITE", "") or DEFAULT_SITE).strip()


def trackers() -> list[dict]:
    out = []
    for item in (os.getenv("SDI_PROJECT_TRACKERS", "") or DEFAULT_TRACKERS).split("|"):
        label, _, what = item.strip().partition("=")
        if not what:
            label, what = "", label
        what = what.strip().strip("/")
        if what:
            out.append({"label": label.strip() or what.rsplit("/", 1)[-1], "what": what})
    return out


# ── SharePoint, as the person ───────────────────────────────────────────────

_sites: dict = {}
_lock = threading.Lock()
_parsed: dict = {}          # {item id: (eTag, sheets)} - a parse reused only while the file is unchanged


def _get(client, url, headers, what, **params):
    answer = client.get(url, headers=headers, params=params or None, follow_redirects=True)
    try:
        sp._complain(answer, what)
    except sp.PlanUnavailable as exc:
        raise Unavailable(str(exc), exc.reason) from exc
    return answer


def _site_id(client, headers) -> str:
    known = _sites.get(site())
    if known:
        return known
    found = str(_get(client, f"{sp.GRAPH}/sites/{site()}", headers, "the TTi Projects site",
                     **{"$select": "id"}).json().get("id") or "")
    if not found:
        raise Unavailable(f"SharePoint did not recognise the site {site()}.")
    _sites[site()] = found
    return found


_FIELDS = "id,name,size,eTag,lastModifiedDateTime,webUrl,file,folder,parentReference"


def _files_for(client, headers, sid: str, what: str) -> list[dict]:
    """The spreadsheets one tracker entry means."""
    if "/" not in what and what.lower().endswith(SHEET_TYPES):
        q = what.replace("'", "''")
        found = _get(client, f"{sp.GRAPH}/sites/{sid}/drive/root/search(q='{quote(q)}')",
                     headers, f"“{what}”", **{"$select": _FIELDS}).json().get("value") or []
        exact = [f for f in found if str(f.get("name", "")).lower() == what.lower() and "file" in f]
        if not exact:
            raise Unavailable(f"No spreadsheet called “{what}” was found on the TTi Projects "
                              f"site that your account can open.", "access")
        exact.sort(key=lambda f: f.get("lastModifiedDateTime") or "", reverse=True)
        return exact[:1]
    item = _get(client, f"{sp.GRAPH}/sites/{sid}/drive/root:/{quote(what, safe='/')}", headers,
                f"“{what}”", **{"$select": _FIELDS}).json()
    if "file" in item:
        return [item]
    kids = _get(client, f"{sp.GRAPH}/sites/{sid}/drive/items/{item['id']}/children", headers,
                f"the folder “{what}”", **{"$select": _FIELDS, "$top": "200"}).json().get("value") or []
    return [k for k in kids if "file" in k and str(k.get("name", "")).lower().endswith(SHEET_TYPES)
            and not str(k.get("name", "")).startswith("~$")]


def read_all(token: str, client=None) -> list[dict]:
    """Every configured tracker: [{label, files: [{name, saved, web_url, sheets}]}]."""
    if not token:
        raise Unavailable("Microsoft sign-in did not provide access to SharePoint. Sign in again.")
    headers = {"Authorization": "Bearer " + token}
    opened = client or httpx.Client(timeout=sp.TIMEOUT)
    try:
        sid = _site_id(opened, headers)
        out = []
        for entry in trackers():
            files = []
            for f in _files_for(opened, headers, sid, entry["what"]):
                if int(f.get("size") or 0) > MAX_BYTES:
                    raise Unavailable(f"{f['name']} is larger than this reads. Open it in Excel.")
                etag = str(f.get("eTag") or "")
                with _lock:
                    held = _parsed.get(f["id"])
                if held and etag and held[0] == etag:
                    sheets = held[1]
                else:
                    data = _get(opened, f"{sp.GRAPH}/sites/{sid}/drive/items/{f['id']}/content",
                                headers, f["name"]).content
                    sheets = parse(data, f["name"])
                    with _lock:
                        _parsed[f["id"]] = (etag, sheets)
                files.append({"name": f["name"], "saved": f.get("lastModifiedDateTime"),
                              "web_url": f.get("webUrl"), "sheets": sheets})
            out.append({"label": entry["label"], "files": files})
        return out
    finally:
        if client is None:
            opened.close()


# ── Any layout ──────────────────────────────────────────────────────────────

def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time() else value.isoformat(" ", "minutes")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def paths_in(text: str, link: str = "") -> list[str]:
    found = []
    for source in (link, text):
        for m in _PATH.finditer(str(source or "")):
            p = m.group(1).strip().rstrip(".,;)")
            if len(p) > 1 and p[1] == ":":
                p = p.replace("/", "\\")
            if p not in found:
                found.append(p)
    return found


def _heading_row(rows: list) -> int:
    """The first of the top 20 rows with at least two cells, mostly words, and no paths."""
    for i, row in enumerate(rows[:20]):
        cells = [c for c in row if _text(c)]
        words = [c for c in cells if isinstance(c, str) and not paths_in(c)]
        if len(cells) >= 2 and len(words) >= 0.6 * len(cells):
            return i
    return 0


def parse(data: bytes, name: str = "") -> list[dict]:
    """[{sheet, headings, rows: [{row, cells: {heading: text}, paths: [...]}]}]"""
    from openpyxl import load_workbook
    try:
        book = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:                                          # noqa: BLE001
        raise Unavailable(f"{name or 'The tracker'} does not open as a workbook ({type(exc).__name__}).")
    sheets = []
    for ws in book.worksheets:
        if ws.sheet_state != "visible":
            continue
        grid = [[c for c in r[:MAX_COLUMNS]] for r in ws.iter_rows(max_row=MAX_ROWS + 25)]
        values = [[c.value for c in r] for r in grid]
        if not any(_text(v) for r in values for v in r):
            continue
        top = _heading_row(values)
        headings, seen = [], {}
        for j, v in enumerate(values[top] if values else []):
            h = _text(v) or f"Column {j + 1}"
            seen[h] = seen.get(h, 0) + 1
            headings.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
        rows = []
        for i in range(top + 1, len(grid)):
            cells, paths = {}, []
            for j, c in enumerate(grid[i][:len(headings)]):
                text = _text(c.value)
                link = getattr(getattr(c, "hyperlink", None), "target", "") or ""
                if text or link:
                    cells[headings[j]] = text or link
                for p in paths_in(text, link):
                    paths.append({"path": p, "column": headings[j],
                                  "is_file": bool(re.search(r"\.[A-Za-z0-9]{2,5}$", p))})
            if cells:
                rows.append({"row": i + 1, "cells": cells, "paths": paths})
            if len(rows) >= MAX_ROWS:
                break
        sheets.append({"sheet": ws.title, "headings": [h for h in headings if not h.startswith("Column ")]
                       or headings, "rows": rows})
    return sheets


def search(trackers_read: list[dict], query: str = "", limit: int = 0) -> dict:
    """Rows containing every word, across every tracker, each with where it is."""
    words = [w for w in re.split(r"\s+", str(query or "").lower().strip()) if w][:10]
    matches, total = [], 0
    for t in trackers_read:
        for f in t["files"]:
            for s in f["sheets"]:
                for r in s["rows"]:
                    hay = " ".join([s["sheet"], *r["cells"].values()]).lower()
                    if all(w in hay for w in words):
                        total += 1
                        if not limit or len(matches) < limit:
                            matches.append({"tracker": t["label"], "file": f["name"], "sheet": s["sheet"],
                                            "row": r["row"], "source": f"{f['name']} › {s['sheet']} › row {r['row']}",
                                            "cells": r["cells"], "paths": r["paths"]})
    return {"searched_for": " ".join(words), "match_count": total, "matches": matches}
