"""
SDI Intelligence — Excel storage backend for the Voice CRM pilot.

Nick's sandbox is not a SharePoint List: it is two workbooks in the site's
document library, and the tracker — "CRM TEST - 2026 Account and Project
Tracker.xlsx" — is the thing his team actually lives in. This module reads and
writes that workbook through the Microsoft Graph workbook API, as the
signed-in user, so the propose → read back → confirm → journal loop in
voicecrm.py can run against a spreadsheet exactly as it does against a List.

Two realities of a spreadsheet shape the design:

  * Rows have no identity. A List item has an id and an eTag; a worksheet row
    has neither, and Nick's rows have a blank "Project code" column, so there
    is no business key either. A row is therefore addressed by its sheet row
    number, and versioned by a FINGERPRINT — a hash of the row's rendered
    cell text. If anything in the row changes, or a row is inserted or
    deleted above it (shifting different data under the same row number), the
    fingerprint no longer matches and the confirm step refuses to write.
    That turns both edit-races and row-shifts into an honest "conflict"
    instead of a silent write to the wrong record.

  * There is no If-Match on a cell write. The fingerprint is re-checked
    immediately before writing, but Graph cannot make the write itself
    conditional, so a change landing in the few hundred milliseconds between
    the re-read and the PATCH would not be detected. For a single-owner
    sandbox pilot that window is accepted — and it is written down here so
    nobody mistakes it for a guarantee.

  * A write is ONE CELL, and it is read back. `apply()` PATCHes
    /workbook/worksheets('<sheet>')/range(address='<A1>') with that single
    value, then reads the same address and checks it holds it. The file is
    never replaced or re-uploaded, so nothing outside the named cell can
    change and nobody else's edit can be overwritten wholesale. Asked for by
    Nick Garrish, 23 October 2026, after ChatGPT's own SharePoint connector
    offered him only a whole-file replace.

    The write and the read-back share one PERSISTENT workbook session, so the
    read cannot be answered from a copy that has not caught up. Without that, a
    change already safely in the file reported itself to Nick as failed. (This
    paragraph said the opposite until 29 October 2026 - "No workbook session is
    opened" - left behind when the session was added. A comment that contradicts
    the code is worse than none, and it was contradicting it about exactly the
    thing that went wrong.)

Configuration (.env), alongside the voicecrm.py settings:

    SDI_VOICECRM_STORE=excel      selects this backend (default is "list")
    SDI_VOICECRM_SITE             same site setting, "hostname:/sites/SiteName"
    SDI_VOICECRM_XLSX             workbook path inside the site's default
                                  document library, e.g.
                                  "CRM TEST - 2026 Account and Project Tracker.xlsx"
                                  (include the folder if it is in one:
                                  "General/CRM TEST - ....xlsx")
    SDI_VOICECRM_SHEET            worksheet name; empty = first worksheet

Reading needs the delegated scope Files.Read.All (or Sites.Read.All);
writing needs Files.ReadWrite.All (or Sites.ReadWrite.All), consented.
"""

import hashlib
import json
import os
import threading
import time
from typing import Optional
from urllib.parse import quote

import httpx


# ── ONE CONNECTION, NOT ONE PER CALL ────────────────────────────────────────
# A single saved change used to open seven HTTP clients: three for the fetch,
# the formula check and the write, and four more inside them. Each one
# negotiated TLS to graph.microsoft.com from scratch, which is most of a
# round trip before a single byte of Graph's answer. One pooled client keeps
# the connection open between them.
#
# Created on first use rather than at import, so a test that stands in for
# httpx.Client is picked up; `reset_pool()` lets a test start clean.
_pool_lock = threading.Lock()
_pool: Optional[httpx.Client] = None
POOL_TIMEOUT = 30


def _client() -> httpx.Client:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = httpx.Client(timeout=POOL_TIMEOUT)
        return _pool


def reset_pool() -> None:
    """Drop the pooled client. For tests, and after a configuration change."""
    global _pool
    with _pool_lock:
        held, _pool = _pool, None
    if held is not None:
        try:
            held.close()
        except Exception:                                # noqa: BLE001
            pass

GRAPH = "https://graph.microsoft.com/v1.0"


def accept_text_in_number_cells() -> None:
    """Let openpyxl read a cell marked as a number that holds text, as that text.

    Nick's tracker, 14 October 2026: the 07:50 review stopped with
    "could not convert string to float: 'Completed'". The file had been
    rewritten outside Excel with text in cells typed as numbers; Excel Online
    refuses such a file (FileCorruptTryRepair) and openpyxl raised on the first
    one - so the morning email, the briefing and the read-only copy all failed
    together. The text is what the cell says, so it is read as text; nothing
    that openpyxl already reads changes. Idempotent; a no-op if openpyxl's
    internals move."""
    try:
        from openpyxl.worksheet import _reader
        cast, to_date = _reader._cast_number, _reader.from_excel
    except Exception:  # noqa: BLE001
        return
    if getattr(cast, "sdi_tolerant", False):
        return

    def _cast_number(value):
        try:
            return cast(value)
        except ValueError:
            return value

    def from_excel(value, *args, **kwargs):
        # A text value in a date-formatted number cell stays text.
        return value if isinstance(value, str) else to_date(value, *args, **kwargs)

    _cast_number.sdi_tolerant = True
    _reader._cast_number = _cast_number
    _reader.from_excel = from_excel


accept_text_in_number_cells()


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _col_letter(index: int) -> str:
    """0-based column index -> spreadsheet letter(s): 0->A, 25->Z, 26->AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _norm(name) -> str:
    """Heading comparison: case- and spacing-insensitive."""
    return " ".join(str(name or "").split()).lower()


def fingerprint(cells: list) -> str:
    """Public name for the row version stamp (used by voicecrm.confirm)."""
    return _fingerprint(cells)


def _fingerprint(cells: list) -> str:
    """Version stamp for one row: hash of its rendered text, order preserved."""
    return hashlib.sha256(
        json.dumps([str(c) if c is not None else "" for c in cells]).encode()
    ).hexdigest()[:16]


# Excel Online can refuse to open a workbook that is still a perfectly good
# file: one rewritten outside Excel (downloaded, edited, uploaded back), caught
# mid-save, or locked. Graph then answers 5xx / 423, or one of these codes.
_REFUSAL_CODES = ("FileCorrupt", "resourceLocked", "EditModeCannotAcquireLock",
                  "FileOpen", "ServiceUnavailable", "WorkbookNotSupported")


def excel_refused(err: Optional[dict]) -> bool:
    """True when the workbook service, not the person's access, is the problem."""
    if not err or err.get("state") != "graph_error":
        return False
    status = int(err.get("status") or 0)
    detail = str(err.get("detail", ""))
    return status >= 500 or status == 423 or any(code in detail for code in _REFUSAL_CODES)


def unavailable(err: dict) -> dict:
    """A refusal, in words for the person: nothing was changed, lookups still work."""
    return {"state": "tracker_unavailable", "status": err.get("status"),
            "graph_detail": str(err.get("detail", ""))[:300],
            "detail": ("Excel Online can't open the tracker right now, so changes can't be "
                       "saved. Nothing was changed. Looking things up still works, from a copy "
                       "of the file; changes will work again once the file is repaired.")}


def _display(value, fmt: str = "General") -> str:
    """A cell as Excel shows it, near enough for reading back: dates month-first
    (as the sheet shows them, and as the rest of the app reads them), percentages
    and money as formatted, whole numbers without a trailing .0."""
    import datetime as _dt
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (_dt.datetime, _dt.date)):
        return f"{value.month}/{value.day}/{value.year}"
    if isinstance(value, (int, float)):
        first = (fmt or "General").split(";")[0]          # the positive-number section
        decimals = min(sum(ch == "0" for ch in first.split(".", 1)[1]), 6) if "." in first else 0
        if "%" in first:
            return f"{value * 100:.{decimals}f}%"
        if "£" in first or "#,##" in first:
            text = f"{abs(value):,.{decimals}f}"
            sign = "-" if value < 0 else ""
            return f"{sign}£{text}" if "£" in first else f"{sign}{text}"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return f"{value:.{decimals}f}" if decimals else str(value)
    return str(value)


def _cell_format(cell) -> str:
    """A cell's number format, or "General" when the workbook points at a style it
    doesn't define (common in a file edited outside Excel - reading the format then
    fails, though the value itself is fine)."""
    try:
        return cell.number_format or "General"
    except Exception:  # noqa: BLE001
        return "General"


def _date_column(header: str) -> bool:
    h = _norm(header)
    return "date" in h or h in ("end", "start", "end date", "start date")


def _serial_date(value) -> str:
    """An Excel date serial shown as a date (month-first, as the sheet shows dates),
    for date columns whose date format was lost with a broken style."""
    import datetime as _dt
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 20000 < value < 80000:
        d = _dt.date(1899, 12, 30) + _dt.timedelta(days=int(value))
        return f"{d.month}/{d.day}/{d.year}"
    return ""


class ExcelStore:
    """Read/write access to one worksheet, shaped like the List backend:

    rows()  -> {"state": ..., "items": [{id, etag, modified, fields}, ...]}
    fetch() -> (item, None) or (None, error-payload); item carries fields,
               eTag (the fingerprint) and the cell addresses needed to write
    apply() -> None on success, or an error payload shaped like fetch()'s
    """

    def __init__(self) -> None:
        self.site = _opt("SDI_VOICECRM_SITE")
        self.xlsx = _opt("SDI_VOICECRM_XLSX")
        self.sheet = _opt("SDI_VOICECRM_SHEET")
        self.missing = [name for name, val in
                        (("SDI_VOICECRM_SITE", self.site), ("SDI_VOICECRM_XLSX", self.xlsx))
                        if not val]
        self.configured = not self.missing
        # (drive id, item id) once found, so a file located by search is not
        # searched for again on every request.
        self._located: Optional[tuple] = None
        # The site's id, resolved once for the life of the process. It is an
        # identifier, not a credential, and it does not change - so asking
        # Microsoft for it before every question was a round trip spent on an
        # answer we already had. (The same saving as tti_plan_source._RESOLVED.)
        self._site_id: str = ""
        # The last reading of the sheet, with the file version it came from:
        # {"version": eTag, "wb": ..., "rows": {...}}. Reused for LOOKUPS only
        # when Graph says the file has not been saved since - never for the
        # read immediately before a write. See _load().
        self._seen: Optional[dict] = None
        self._seen_lock = threading.Lock()
        # A persistent workbook session, reused across writes rather than
        # opened and closed for each one. {"id": ..., "until": monotonic}
        self._live_session: Optional[dict] = None
        # Column names the app depends on (the owner column and the editable
        # ones), set by voicecrm.py. The header row — and, when no sheet is
        # configured, the worksheet — is the one where these actually appear:
        # real trackers put a title row above the headings and summary tabs
        # in front of the data, and "first row with text on the first tab" read
        # Nick's title row as headings and matched none of his 76 records.
        self.key_columns: list[str] = []
        self._chosen_sheet: Optional[str] = None

    # ── Graph plumbing ──────────────────────────────────────────────────────

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def request_id(response: httpx.Response) -> str:
        """Graph's own id for this call, which Microsoft support asks for.

        Nick Garrish, 23 October 2026, on a write that did not happen: "capture the
        actual request result: success or failure, HTTP status, error code/message,
        and correlation/request ID." Without it a failure can be described but not
        traced, and the answer to "was it us or them" stays an opinion."""
        for header in ("request-id", "client-request-id", "x-ms-request-id"):
            value = response.headers.get(header)
            if value:
                return value
        return ""

    def _graph_detail(self, response: httpx.Response) -> str:
        try:
            err = response.json().get("error", {})
            detail = f"{err.get('code', '')}: {err.get('message', '')}"[:400]
        except Exception:  # noqa: BLE001 — a non-JSON error body is still worth showing
            detail = response.text[:400]
        rid = self.request_id(response)
        return f"{detail} [request-id {rid}]" if rid else detail

    def _err(self, response: httpx.Response) -> dict:
        return {"state": "graph_error", "status": response.status_code,
                "detail": self._graph_detail(response)}

    def _workbook(self, client: httpx.Client, token: str, download_only: bool = False,
                  light: bool = False) -> tuple[Optional[dict], Optional[dict]]:
        """Resolve site -> drive item -> workbook base URL + file metadata.

        ── `light`: THE FILE'S ADDRESS WITHOUT ASKING FOR ITS METADATA ────────
        The workbook's URL is built from the drive and item ids, both already
        known once the file has been located. A caller that does not need the
        file's VERSION - the read before a write, which must not reuse anything
        anyway - can therefore go straight to the sheet and save a round trip
        at the most latency-sensitive moment in the app.

        Access is not skipped with it: the sheet read that follows is made with
        this person's token and refuses them if it should. If the file has
        moved since, that read answers 404 and the caller clears the location
        and tries again the long way (see _load).
        """
        headers = self._headers(token)
        if light and self._located and (self.sheet or self._chosen_sheet):
            drive_id, item_id = self._located
            return {"base": f"{GRAPH}/drives/{drive_id}/items/{item_id}/workbook",
                    "sheets": [self.sheet or self._chosen_sheet],
                    "version": "", "modified": "", "light": True}, None
        site_id = self._site_id
        if not site_id:
            site = client.get(f"{GRAPH}/sites/{self.site}", headers=headers)
            if site.status_code != 200:
                return None, self._err(site)
            site_id = str(site.json().get("id") or "")
            if not site_id:
                return None, {"state": "graph_error", "status": site.status_code,
                              "detail": f"SharePoint did not recognise the site "
                                        f"'{self.site}'."}
            self._site_id = site_id

        path = self.xlsx.lstrip("/")
        meta = None
        if self._located:
            drive_id, item_id = self._located
            item = client.get(f"{GRAPH}/drives/{drive_id}/items/{item_id}", headers=headers)
            if item.status_code == 200:
                meta = item.json()
            else:
                self._located = None        # moved or deleted since; look again
        if meta is None:
            item = client.get(f"{GRAPH}/sites/{site_id}/drive/root:/{path}", headers=headers)
            if item.status_code == 200:
                meta = item.json()
            elif item.status_code == 404:
                meta, err = self._find_by_name(client, headers, site_id, path)
                if err:
                    return None, err
            else:
                return None, self._err(item)
        drive_id = (meta.get("parentReference") or {}).get("driveId", "")
        self._located = (drive_id, meta.get("id"))
        if download_only:
            return {"drive_id": drive_id, "item_id": meta.get("id"),
                    "modified": meta.get("lastModifiedDateTime", "")}, None

        base = f"{GRAPH}/drives/{drive_id}/items/{meta.get('id')}/workbook"

        names = [self.sheet] if self.sheet else []
        if not names:
            ws = client.get(f"{base}/worksheets", params={"$select": "name"}, headers=headers)
            if ws.status_code != 200:
                return None, self._err(ws)
            names = [w.get("name", "") for w in ws.json().get("value", [])]
            if not names:
                return None, {"state": "graph_error", "status": 200,
                              "detail": "The workbook has no worksheets."}

        # The file's version, as Graph states it. Used to tell whether the
        # sheet needs reading again for a LOOKUP; never to decide whether a
        # write is safe (see _load).
        version = str(meta.get("eTag") or meta.get("cTag") or "") \
            + "|" + str(meta.get("lastModifiedDateTime") or "")
        return {"base": base, "sheets": names, "version": version.strip("|"),
                "modified": meta.get("lastModifiedDateTime", "")}, None

    def _find_by_name(self, client: httpx.Client, headers: dict, site_id: str,
                      path: str) -> tuple[Optional[dict], Optional[dict]]:
        """Not at the configured path: search every library on the site for the
        exact file name. A shared document link (Doc.aspx?sourcedoc=...) never
        shows the folder, so the configured path is often just the name. One
        exact match is used; none or several is reported, never guessed."""
        name = path.rsplit("/", 1)[-1]
        drives = client.get(f"{GRAPH}/sites/{site_id}/drives",
                            params={"$select": "id,name"}, headers=headers)
        if drives.status_code != 200:
            return None, self._err(drives)
        q = quote(name.replace("'", "''"))
        matches = []
        for drive in drives.json().get("value", []):
            res = client.get(f"{GRAPH}/drives/{drive['id']}/root/search(q='{q}')",
                             headers=headers)
            if res.status_code != 200:
                continue
            for hit in res.json().get("value", []):
                if "file" in hit and hit.get("name", "").lower() == name.lower():
                    hit["_library"] = drive.get("name", "")
                    matches.append(hit)
        if not matches:
            # Search answers a signed-in person but not an app on its own (the
            # scheduled morning review): its index is per user. Walk the
            # folders instead - a sandbox library is small.
            for drive in drives.json().get("value", []):
                matches += self._walk_for(client, headers, drive, name)
        if len(matches) == 1:
            return matches[0], None

        def where(h: dict) -> str:
            parent = (h.get("parentReference") or {}).get("path", "").split("root:")[-1]
            return f"{h['_library']}{parent or ''}/{h.get('name')}"

        if not matches:
            return None, {"state": "graph_error", "status": 404,
                          "detail": (f"Workbook '{name}' was not found anywhere on the site "
                                     f"(searched {len(drives.json().get('value', []))} "
                                     f"libraries). Check SDI_VOICECRM_XLSX and that the "
                                     f"signed-in account can open the file.")}
        return None, {"state": "graph_error", "status": 409,
                      "detail": (f"Found {len(matches)} files named '{name}': "
                                 + "; ".join(where(m) for m in matches[:5])
                                 + ". Set SDI_VOICECRM_XLSX to the folder path of the "
                                   "right one so the app never picks between them.")}

    def _walk_for(self, client: httpx.Client, headers: dict, drive: dict, name: str,
                  max_folders: int = 300) -> list:
        """Every file called `name` in one library, found by listing folders."""
        found, queue, seen = [], [f"{GRAPH}/drives/{drive['id']}/root/children"], 0
        while queue and seen < max_folders:
            url = queue.pop(0)
            seen += 1
            while url:
                res = client.get(url, params=None if "$skiptoken" in url else
                                 {"$select": "id,name,file,folder,parentReference,lastModifiedDateTime",
                                  "$top": "200"}, headers=headers)
                if res.status_code != 200:
                    break
                body = res.json()
                for item in body.get("value", []):
                    if "folder" in item:
                        queue.append(f"{GRAPH}/drives/{drive['id']}/items/{item['id']}/children")
                    elif "file" in item and item.get("name", "").lower() == name.lower():
                        item["_library"] = drive.get("name", "")
                        found.append(item)
                url = body.get("@odata.nextLink")
        return found

    def _used_range(self, client: httpx.Client, token: str, wb: dict,
                    with_formulas: bool = False) -> tuple[Optional[dict], Optional[dict]]:
        """The sheet's used range: rendered text plus where it starts.

        `text` (what Excel displays) is used rather than `values` so dates read
        as dates, not as day-count serial numbers — this is what gets spoken
        back to the person, and what the fingerprint is computed over.

        ── WHY FORMULAS COME BACK IN THE SAME CALL ────────────────────────────
        A calculated cell must never be typed over, so every proposed change
        asked Graph a second question - "is this one cell a formula?" - a whole
        round trip after a request that had just read the entire sheet. Graph
        will return `formulas` beside `text`, so the answer arrives with the
        read that was happening anyway. Only asked for before a write; a
        lookup does not need it and the payload is not free.
        """
        select = "text,formulas,rowIndex,columnIndex" if with_formulas \
            else "text,rowIndex,columnIndex"
        res = client.get(
            f"{wb['base']}/worksheets('{wb['sheet']}')/usedRange(valuesOnly=true)",
            params={"$select": select},
            headers=self._headers(token),
        )
        if res.status_code != 200:
            return None, self._err(res)
        data = res.json()
        grid = data.get("text") or []
        if not grid:
            return None, {"state": "empty_sheet",
                          "detail": f"Worksheet '{wb['sheet']}' has no data."}
        return {"grid": grid,
                "formulas": data.get("formulas") or [],
                "row0": int(data.get("rowIndex", 0)),      # 0-based sheet row of grid[0]
                "col0": int(data.get("columnIndex", 0))}, None

    def _headers_row(self, grid: list) -> tuple[int, list[str], bool]:
        """The header row: among the first rows, the one naming the most key
        columns. Falls back to the first row with any text. Returns
        (offset, names, found) — names are whitespace-tidied, and a heading that
        matches a key column ignoring case and spacing takes the key's spelling,
        so "AM owner " in the sheet is the configured "AM Owner"."""
        keys = {_norm(k): k for k in self.key_columns}
        best, first = None, None
        for i, row in enumerate(grid[:25]):
            names = [" ".join(str(c or "").split()) for c in row]
            if not any(names):
                continue
            names = [keys.get(_norm(n), n) for n in names]
            if first is None:
                first = (i, names)
            hits = sum(1 for n in names if _norm(n) in keys)
            if hits and (best is None or hits > best[0]):
                best = (hits, i, names)
        if best:
            return best[1], best[2], True
        if first:
            return first[0], first[1], False
        return 0, [], False

    def _load(self, client: httpx.Client, token: str, *, with_formulas: bool = False,
              may_reuse: bool = False, light: bool = False):
        """Workbook + chosen sheet + its grid + header row, or an error payload.

        ── WHY `may_reuse` IS OFF BY DEFAULT, AND NEVER SET BEFORE A WRITE ────
        Reading the whole sheet is the most expensive thing here, and for a
        LOOKUP it can be skipped when Graph's own eTag says the file has not
        been saved since the last reading. The file's metadata is still
        fetched with THIS person's token every time, so their access still
        decides; what is saved is the sheet read.

        It is never reused for the read immediately before a write. That read
        exists to compute the row's fingerprint and catch somebody else's edit,
        and Excel Online can batch a co-author's save so the eTag lags behind
        it by seconds. Trusting the eTag there would quietly defeat the one
        protection against overwriting a colleague's change - a cheap saving
        paid for in the only currency this app cannot spend.
        """
        # ── THE INVARIANT, ENFORCED RATHER THAN DOCUMENTED ────────────────────
        # Formulas are only ever wanted by the read before a write, and that
        # read must be live. Relying on "light reads carry no version, so they
        # cannot match the cache" left the protection standing on a side
        # effect: a test that flipped may_reuse on in fetch() still passed.
        # This is a programming error, not a runtime condition, so it raises.
        if may_reuse and with_formulas:
            raise ValueError(
                "the read before a write may not be reused: it computes the "
                "row's fingerprint, which is what stops a colleague's edit "
                "being overwritten")
        wb, err = self._workbook(client, token, light=light)
        if err:
            return None, err
        if may_reuse:
            with self._seen_lock:
                held = self._seen
            if held and held["version"] and held["version"] == wb.get("version"):
                return {**held["wb"], "modified": wb["modified"], "reused": True}, None
        order = list(wb["sheets"])
        if self._chosen_sheet in order:
            order.remove(self._chosen_sheet)
            order.insert(0, self._chosen_sheet)
        fallback, last_err = None, None
        for name in order[:12]:
            used, err = self._used_range(client, token, {**wb, "sheet": name},
                                         with_formulas=with_formulas)
            if err:
                last_err = err
                continue
            off, headers, found = self._headers_row(used["grid"])
            if found or not self.key_columns:
                self._chosen_sheet = name
                return self._remember({**wb, "sheet": name, "used": used, "hdr": off,
                                       "headers": headers, "found": True}), None
            if fallback is None:
                fallback = {**wb, "sheet": name, "used": used, "hdr": off,
                            "headers": headers, "found": False}
        if fallback:
            self._chosen_sheet = fallback["sheet"]
            return self._remember(fallback), None
        if light and last_err and int(last_err.get("status") or 0) in (404, 410):
            # The remembered address is stale: the file was renamed, moved or
            # replaced. Locate it again, the long way, once.
            print("[voicecrm.excel] the workbook is no longer where it was; "
                  "locating it again", flush=True)
            self._located = None
            self._chosen_sheet = None
            return self._load(client, token, with_formulas=with_formulas,
                              may_reuse=may_reuse, light=False)
        return None, last_err or {"state": "empty_sheet", "detail": "No readable worksheet."}

    def _remember(self, wb: dict) -> dict:
        """Keep this reading against the file version it came from, so the next
        LOOKUP can skip the sheet read while the file is unchanged.

        Reused only where `may_reuse` says so, which is lookups and never the
        read before a write. Nothing is written to disk: this lives in the
        process and goes when the service restarts, which is the right
        lifetime for somebody's commercial tracker.
        """
        if wb.get("version"):
            with self._seen_lock:
                self._seen = {"version": wb["version"], "wb": wb}
        return wb

    # ── The backend interface voicecrm.py consumes ──────────────────────────

    def rows(self, token: str) -> dict:
        """Every data row, shaped like List items. Caller applies the owner filter.

        May answer from the last reading when Graph says the file has not been
        saved since. The file's metadata is still fetched as this person, so a
        lookup by somebody who has lost access is still refused.
        """
        try:
            wb, err = self._load(_client(), token, may_reuse=True)
            if err:
                if excel_refused(err):
                    try:
                        return self._rows_from_copy(token, err)
                    except Exception as exc:  # noqa: BLE001 - a fallback must never crash a lookup
                        print(f"[voicecrm.excel] copy fallback crashed: "
                              f"{type(exc).__name__}: {exc}"[:300], flush=True)
                        return {**err, "items": [],
                                "copy_error": f"{type(exc).__name__}: {exc}"[:200]}
                return {**err, "items": []}
        except httpx.HTTPError as exc:
            return {"state": "unreachable", "items": [],
                    "detail": f"Could not reach Microsoft Graph: {exc}"}

        used, hdr_offset, headers = wb["used"], wb["hdr"], wb["headers"]
        if not headers:
            return {"state": "empty_sheet", "items": [],
                    "detail": f"No header row found on '{wb['sheet']}'."}

        items = []
        for i, row in enumerate(used["grid"][hdr_offset + 1:]):
            cells = [str(c) if c is not None else "" for c in row]
            if not any(c.strip() for c in cells):
                continue        # blank spacer rows are not records
            sheet_row = used["row0"] + hdr_offset + 1 + i + 1   # 1-based sheet row
            fields = {h: cells[j] if j < len(cells) else ""
                      for j, h in enumerate(headers) if h}
            items.append({
                "id": f"xl{sheet_row}",
                # The fingerprint plays the role a List eTag plays: the confirm
                # step compares it and refuses to write if the row changed.
                "etag": _fingerprint(cells),
                "modified": wb["modified"],
                "fields": fields,
            })
        return {"state": "ok", "items": items, "sheet": wb["sheet"],
                "sheets": wb["sheets"], "header_row": used["row0"] + hdr_offset + 1,
                "headers": [h for h in headers if h], "key_columns_found": wb["found"],
                # True when the sheet itself was not read again because Graph
                # said the file was unchanged. Shown in the log, not to people.
                "reused": bool(wb.get("reused"))}

    def fetch(self, token: str, item_id: str) -> tuple[Optional[dict], Optional[dict]]:
        """One row by its xl<row> id, with the addresses needed to write to it.

        Always a live read of the sheet: this is the read the fingerprint is
        computed from, and it is what stops a colleague's edit being
        overwritten. See _load() on why it may not be reused.
        """
        if not item_id.startswith("xl"):
            return None, {"state": "graph_error", "status": 400,
                          "detail": f"'{item_id}' is not an Excel row id (expected xl<row>)."}
        try:
            sheet_row = int(item_id[2:])
        except ValueError:
            return None, {"state": "graph_error", "status": 400,
                          "detail": f"'{item_id}' is not an Excel row id (expected xl<row>)."}

        try:
            # with_formulas: so the "is this cell calculated?" question needs no
            # round trip of its own. may_reuse stays off - this read must be
            # live. light: the file's version is not wanted here precisely
            # BECAUSE nothing may be reused, so asking for it is a wasted call.
            wb, err = self._load(_client(), token, with_formulas=True, light=True)
            if err:
                return None, (unavailable(err) if excel_refused(err) else err)
        except httpx.HTTPError as exc:
            return None, {"state": "unreachable",
                          "detail": f"Could not reach Microsoft Graph: {exc}"}

        used, hdr_offset, headers = wb["used"], wb["hdr"], wb["headers"]
        grid_index = (sheet_row - 1) - used["row0"]
        if grid_index <= hdr_offset or grid_index >= len(used["grid"]):
            return None, {"state": "conflict",
                          "detail": (f"Row {sheet_row} is no longer inside the sheet's data. "
                                     f"Rows were probably deleted. Read the records again.")}

        row = used["grid"][grid_index]
        cells = [str(c) if c is not None else "" for c in row]
        fields = {h: cells[j] if j < len(cells) else ""
                  for j, h in enumerate(headers) if h}
        # Cell address per column, for the one-cell write in apply().
        addr = {h: f"{_col_letter(used['col0'] + j)}{sheet_row}"
                for j, h in enumerate(headers) if h}

        # This row's formulas, from the same read as its text. "" where the
        # read did not ask for them, which is_formula() tells from `_has_formulas`.
        formula_grid = used.get("formulas") or []
        formula_row = formula_grid[grid_index] if grid_index < len(formula_grid) else []
        formulas = {h: (str(formula_row[j]) if j < len(formula_row)
                        and formula_row[j] is not None else "")
                    for j, h in enumerate(headers) if h}

        return {
            "fields": fields,
            "eTag": _fingerprint(cells),
            "_wb": wb,
            "_addr": addr,
            # The row as read and each column's place in it: lets confirm()
            # tell this person's own just-saved changes from someone else's.
            "_cells": cells,
            "_col": {h: j for j, h in enumerate(headers) if h},
            "_formulas": formulas,
            "_has_formulas": bool(formula_grid),
        }, None

    def is_formula(self, token: str, item: dict, field: str) -> bool:
        """True when the cell holds a formula. A calculated cell is never typed
        over: it would silently replace the calculation with a fixed value.
        Unreadable counts as a formula - refusing is the safe side.

        ── NO ROUND TRIP OF ITS OWN ───────────────────────────────────────────
        fetch() asks for the sheet's formulas alongside its text, so the answer
        is already in hand. It used to be a separate Graph call for one cell,
        made immediately after a request that had just read the whole sheet:
        a round trip per proposed change, for information that had been sitting
        in the previous response's sibling field all along.

        The fallback below is for a row that came from a read without them.
        """
        addr = item.get("_addr", {}).get(field)
        if not addr:
            return False
        if item.get("_has_formulas"):
            return str(item.get("_formulas", {}).get(field, "")).startswith("=")
        wb = item["_wb"]
        try:
            res = _client().get(
                f"{wb['base']}/worksheets('{wb['sheet']}')/range(address='{addr}')",
                params={"$select": "formulas"}, headers=self._headers(token))
        except httpx.HTTPError:
            return True
        if res.status_code != 200:
            return True
        cell = ((res.json().get("formulas") or [[""]])[0] or [""])[0]
        return isinstance(cell, str) and cell.startswith("=")

    def apply(self, token: str, item: dict, field: str, new_value: str) -> Optional[dict]:
        """Write one cell. Returns None on success, an error payload otherwise.

        The caller (voicecrm.confirm) has already re-fetched the row and
        compared fingerprints; see the module docstring for the residual
        read-to-write race this cannot close.
        """
        addr = item.get("_addr", {}).get(field)
        if not addr:
            return {"state": "failed",
                    "detail": f"Column '{field}' was not found in the sheet's header row."}
        wb = item["_wb"]
        url = f"{wb['base']}/worksheets('{wb['sheet']}')/range(address='{addr}')"
        client = _client()
        try:
            # ── ONE SESSION FOR THE WRITE AND THE READ-BACK ────────────────────
            # Without a session each call is served independently, and a read a
            # moment after a write can still be answered from a copy that does
            # not have it yet. See `_session` - this is what made a saved change
            # report itself as failed on 23 October 2026.
            session = self._session(client, token, wb)
            headers = {**self._headers(token), "Content-Type": "application/json"}
            if session:
                headers["workbook-session-id"] = session
            res = client.patch(url, headers=headers, json={"values": [[new_value]]})
            if res.status_code >= 300 and session and self._session_is_gone(res):
                # The reused session had expired. Open a fresh one and write
                # once more - the first attempt changed nothing, so this is a
                # retry and not a second write.
                print(f"[voicecrm.excel] workbook session expired; opening a new one "
                      f"and writing {addr} again", flush=True)
                self._forget_session()
                session = self._session(client, token, wb)
                headers.pop("workbook-session-id", None)
                if session:
                    headers["workbook-session-id"] = session
                res = client.patch(url, headers=headers, json={"values": [[new_value]]})
            if res.status_code >= 300:
                err = {"state": "failed", "status": res.status_code,
                       "detail": self._graph_detail(res)}
                return (unavailable(err) if excel_refused({**err, "state": "graph_error"})
                        else err)
            # ── A SAVE MAKES THE HELD READING WRONG, AT ONCE ───────────────────
            # The lookup cache refreshes when Graph's eTag changes, and Excel
            # Online can batch a save so the eTag lags it. Waiting for that
            # would mean the question right after a change could still answer
            # with the old value - "I just changed that" is the same loss of
            # confidence as the failed-write report, by a different route.
            with self._seen_lock:
                self._seen = None
            return self._verify(client, token, wb, addr, new_value,
                                self.request_id(res), session)
        except httpx.HTTPError as exc:
            return {"state": "unreachable",
                    "detail": f"Could not reach Microsoft Graph: {exc}"}

    # Excel keeps a persistent session alive for several minutes of idleness.
    # Held for less than that, so an expired one is the exception rather than
    # something every write has to recover from.
    SESSION_SECONDS = 180

    _SESSION_GONE = ("InvalidSession", "SessionNotFound", "invalidSessionId",
                     "ActivityLimitReached", "SessionTimedOut", "sessionNotFound")

    def _session_is_gone(self, response) -> bool:
        """True when Graph refused the call because the session id is no longer
        good, as opposed to anything about the cell or the file."""
        if response.status_code not in (400, 404, 410):
            return False
        body = ""
        try:
            body = json.dumps(response.json())
        except Exception:                                # noqa: BLE001
            body = str(getattr(response, "text", ""))
        return any(code.lower() in body.lower() for code in self._SESSION_GONE)

    def _forget_session(self) -> None:
        with self._seen_lock:
            self._live_session = None

    def _session(self, client: httpx.Client, token: str, wb: dict) -> str:
        """A persistent workbook session id, or "" if one could not be opened.

        ── REUSED BETWEEN WRITES ───────────────────────────────────────────────────
        "Change the status, the next steps and the date" is three writes in one
        sentence, and each one used to open a session and close it again: six Graph
        calls spent on bookkeeping. One session serves them all, which is also
        better manners to a shared workbook than opening three. It is let go after
        SESSION_SECONDS, and if Excel has expired it first the write retries once
        with a fresh one.

        ── WHY A SESSION, WHEN THE WRITE SAVES WITHOUT ONE ─────────────────────────
        Not to make the write persist: a range write with no session header IS saved
        to the file, and persistChanges=true here says the same thing again. It is so
        that the WRITE AND THE READ-BACK ARE THE SAME CONVERSATION.

        Sessionless calls are independent, and Microsoft may answer two of them from
        different copies of the workbook. On 23 October 2026 a cell was written
        (PATCH 200), read back a fraction of a second later, still showed its old
        value, and a change that was safely in the file was reported to Nick Garrish
        as failed. The value was there all along; the second call had not seen it yet.
        Sharing one session id removes that, because every call carrying it is served
        by the same instance.

        Failing to open one is not fatal - the write still saves - but it does make
        the read-back untrustworthy, and `_verify` then declines to call a mismatch a
        failure rather than risk repeating that.
        """
        with self._seen_lock:
            held = self._live_session
        if held and held["base"] == wb["base"] and time.monotonic() < held["until"]:
            return held["id"]
        try:
            res = client.post(f"{wb['base']}/createSession",
                              headers={**self._headers(token),
                                       "Content-Type": "application/json"},
                              json={"persistChanges": True})
            if res.status_code < 300:
                made = str(res.json().get("id") or "")
                if made:
                    with self._seen_lock:
                        self._live_session = {
                            "id": made, "base": wb["base"],
                            "until": time.monotonic() + self.SESSION_SECONDS}
                return made
            print(f"[voicecrm.excel] no workbook session ({res.status_code} "
                  f"{self._graph_detail(res)}); the write still saves, the read-back "
                  f"becomes advisory", flush=True)
        except (httpx.HTTPError, ValueError) as exc:          # noqa: BLE001
            print(f"[voicecrm.excel] no workbook session ({type(exc).__name__}: {exc}); "
                  f"the write still saves, the read-back becomes advisory", flush=True)
        return ""

    def close_session(self, token: str = "") -> None:
        """Hand the live session back, if there is one.

        Not called after every write any more - one session serves a whole
        sentence of changes and is then let go on a timer. This exists so a
        caller that knows it has finished can give it back at once, and so the
        expiry retry in apply() can discard a dead one explicitly.
        """
        with self._seen_lock:
            held, self._live_session = self._live_session, None
        if not held:
            return
        try:
            _client().post(f"{held['base']}/closeSession",
                           headers={**self._headers(token),
                                    "workbook-session-id": held["id"]})
        except httpx.HTTPError:
            pass

    def _close_session(self, client: httpx.Client, token: str, wb: dict, session: str) -> None:
        """Hand one named session back, used by nothing on the write path now.
        Kept because Excel expires sessions anyway and an explicit close is
        better manners to a shared workbook."""
        if not session:
            return
        try:
            client.post(f"{wb['base']}/closeSession",
                        headers={**self._headers(token), "workbook-session-id": session})
        except httpx.HTTPError:
            pass

    def _verify(self, client: httpx.Client, token: str, wb: dict, addr: str, expected: str,
                wrote_id: str = "", session: str = "") -> Optional[dict]:
        """Read the cell back. None when the change stands, an error when it does not.

        ── A SUCCESSFUL WRITE IS NEVER REPORTED AS A FAILURE ───────────────────────
        Nick Garrish, 23 October 2026: "If the test succeeds, read the changed cell
        back and confirm it persisted." Right to ask, and the first version of this
        did exactly that and got it wrong: it ran without a session, read a copy of
        the workbook that had not caught up, and told him a change already saved in
        the file had failed. He then had every reason to believe writing was broken.

        So the PATCH's own 200 is what decides, and this check can only add doubt on
        top of it:
          * cell holds the new value            -> saved (the ordinary case)
          * cell differs, AND we had a session  -> not saved, and said plainly: the
                                                   same session cannot be out of date
                                                   with itself
          * cell differs, no session            -> saved, with a line in the log. The
                                                   read cannot be trusted to disagree
          * the read-back itself fails          -> saved. A second call failing says
                                                   nothing about the first
        """
        url = f"{wb['base']}/worksheets('{wb['sheet']}')/range(address='{addr}')"
        headers = self._headers(token)
        if session:
            headers["workbook-session-id"] = session
        try:
            res = client.get(url, params={"$select": "text,values"}, headers=headers)
            if res.status_code >= 300:
                return None
            body = res.json()
            shown = ((body.get("text") or [[""]])[0] or [""])[0]
            raw = ((body.get("values") or [[""]])[0] or [""])[0]
        except (httpx.HTTPError, ValueError, IndexError, TypeError):
            return None
        want = str(expected).strip()
        for got in (shown, raw):
            # Excel reformats as it stores: a typed date becomes a serial and shows
            # in the column's own format, a number loses its typed thousands comma.
            # The cell is right if either face of it matches what was asked for.
            if str(got).strip() == want:
                return None
        if not session:
            print(f"[voicecrm.excel] {addr} read back as '{shown}' rather than '{want}', "
                  f"with no workbook session to make that read reliable - the write "
                  f"answered 200 and is reported as saved", flush=True)
            return None
        return {"state": "not_saved", "status": 200,
                "detail": (f"Microsoft Graph accepted the change but {addr} still reads "
                           f"'{shown}', not '{want}'. Nothing was saved. "
                           + (f"[write request-id {wrote_id}]" if wrote_id else "")).strip()}

    def download(self, token: str) -> tuple[Optional[bytes], Optional[dict]]:
        """The whole workbook file, for a reader with no signed-in user.

        The scheduled morning review runs with an app-only token, which the
        workbook (Excel) API does not accept; the file itself can always be
        downloaded, and is then read locally. Read-only by construction.
        """
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:  # own client: a whole-file download
                loc, err = self._workbook(client, token, download_only=True)
                if err:
                    return None, err
                res = client.get(f"{GRAPH}/drives/{loc['drive_id']}/items/{loc['item_id']}/content",
                                 headers=self._headers(token))
        except httpx.HTTPError as exc:
            return None, {"state": "unreachable", "detail": f"Could not reach Microsoft Graph: {exc}"}
        if res.status_code != 200:
            return None, self._err(res)
        return res.content, None

    def _rows_from_copy(self, token: str, refused: dict) -> dict:
        """rows(), read from a downloaded copy because Excel Online refused the
        workbook. Same shape and the same xl<row> ids; marked source="copy" so
        callers can say so. Read-only: fetch() and apply() still go through Excel
        Online, so nothing can be saved until it opens the file again."""
        data, err = self.download(token)
        if err:
            print(f"[voicecrm.excel] copy fallback: download refused: {err.get('status')} "
                  f"{str(err.get('detail', ''))[:200]}", flush=True)
            return {**refused, "items": [], "copy_error": f"download: {str(err.get('detail', ''))[:180]}"}
        import io
        import warnings
        import openpyxl
        warnings.filterwarnings("ignore", message="Data Validation extension", category=UserWarning)
        try:
            book = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
            names = [ws.title for ws in book.worksheets]
            order = [self.sheet] if self.sheet in names else \
                ([self._chosen_sheet] if self._chosen_sheet in names else []) + \
                [n for n in names if n != self._chosen_sheet]
            chosen = None
            for name in order[:12]:
                ws = book[name]
                # Bounded: a file written outside Excel can claim a sheet of a
                # million rows; the tracker is a few hundred.
                raw = [[(c.value, _cell_format(c)) for c in row]
                       for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row or 20000, 20000),
                                               min_col=1, max_col=min(ws.max_column or 200, 200))]
                grid = [[_display(v, f) for v, f in row] for row in raw]
                off, headers, found = self._headers_row(grid)
                if found or not self.key_columns:
                    chosen = (name, raw, grid, off, headers, found)
                    break
                chosen = chosen or (name, raw, grid, off, headers, found)
            book.close()
        except Exception as exc:  # noqa: BLE001 - genuinely unreadable: report the original refusal
            print(f"[voicecrm.excel] copy fallback: unreadable copy: {type(exc).__name__}: {exc}"[:300], flush=True)
            return {**refused, "items": [], "copy_error": f"{type(exc).__name__}: {exc}"[:200]}
        if not chosen or not chosen[4]:
            print(f"[voicecrm.excel] copy fallback: no header row found (sheets {names[:6]})", flush=True)
            return {**refused, "items": [], "copy_error": "no header row found in the copy"}
        name, raw, grid, off, headers, found = chosen
        dated = [j for j, h in enumerate(headers) if h and _date_column(h)]
        items = []
        for i, row in enumerate(grid[off + 1:]):
            if not any(c.strip() for c in row):
                continue
            for j in dated:                                 # a date that lost its date format
                if j < len(row) and _serial_date(raw[off + 1 + i][j][0]):
                    row[j] = _serial_date(raw[off + 1 + i][j][0])
            sheet_row = off + 1 + i + 1                     # grid[0] is sheet row 1
            fields = {h: row[j] if j < len(row) else "" for j, h in enumerate(headers) if h}
            items.append({"id": f"xl{sheet_row}", "etag": _fingerprint(row),
                          "modified": "", "fields": fields})
        return {"state": "ok", "items": items, "sheet": name, "sheets": names,
                "header_row": off + 1, "headers": [h for h in headers if h],
                "key_columns_found": found, "source": "copy",
                "refused": str(refused.get("detail", ""))[:300],
                "note": ("Read from a copy of the tracker: Excel Online can't open the file "
                         "right now, so changes can't be saved until it's repaired.")}
