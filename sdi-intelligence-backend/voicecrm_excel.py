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
from typing import Optional
from urllib.parse import quote

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"


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
        # Column names the app depends on (the owner column and the editable
        # ones), set by voicecrm.py. The header row — and, when no sheet is
        # configured, the worksheet — is the one where these actually appear:
        # real trackers put a title row above the headings and summary tabs
        # in front of the data, and "first row with text on the first tab" read
        # Nick's title row as headings and matched none of his 76 records.
        self.key_columns: list[str] = []
        self._download_only = False
        self._chosen_sheet: Optional[str] = None

    # ── Graph plumbing ──────────────────────────────────────────────────────

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def _graph_detail(self, response: httpx.Response) -> str:
        try:
            err = response.json().get("error", {})
            return f"{err.get('code', '')}: {err.get('message', '')}"[:400]
        except Exception:  # noqa: BLE001 — a non-JSON error body is still worth showing
            return response.text[:400]

    def _err(self, response: httpx.Response) -> dict:
        return {"state": "graph_error", "status": response.status_code,
                "detail": self._graph_detail(response)}

    def _workbook(self, client: httpx.Client, token: str) -> tuple[Optional[dict], Optional[dict]]:
        """Resolve site -> drive item -> workbook base URL + file metadata."""
        headers = self._headers(token)
        site = client.get(f"{GRAPH}/sites/{self.site}", headers=headers)
        if site.status_code != 200:
            return None, self._err(site)
        site_id = site.json().get("id", "")

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
        if self._download_only:
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

        return {"base": base, "sheets": names,
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

    def _used_range(self, client: httpx.Client, token: str,
                    wb: dict) -> tuple[Optional[dict], Optional[dict]]:
        """The sheet's used range: rendered text plus where it starts.

        `text` (what Excel displays) is used rather than `values` so dates read
        as dates, not as day-count serial numbers — this is what gets spoken
        back to the person, and what the fingerprint is computed over.
        """
        res = client.get(
            f"{wb['base']}/worksheets('{wb['sheet']}')/usedRange(valuesOnly=true)",
            params={"$select": "text,rowIndex,columnIndex"},
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

    def _load(self, client: httpx.Client, token: str):
        """Workbook + chosen sheet + its grid + header row, or an error payload."""
        wb, err = self._workbook(client, token)
        if err:
            return None, err
        order = list(wb["sheets"])
        if self._chosen_sheet in order:
            order.remove(self._chosen_sheet)
            order.insert(0, self._chosen_sheet)
        fallback, last_err = None, None
        for name in order[:12]:
            used, err = self._used_range(client, token, {**wb, "sheet": name})
            if err:
                last_err = err
                continue
            off, headers, found = self._headers_row(used["grid"])
            if found or not self.key_columns:
                self._chosen_sheet = name
                return {**wb, "sheet": name, "used": used, "hdr": off,
                        "headers": headers, "found": True}, None
            if fallback is None:
                fallback = {**wb, "sheet": name, "used": used, "hdr": off,
                            "headers": headers, "found": False}
        if fallback:
            self._chosen_sheet = fallback["sheet"]
            return fallback, None
        return None, last_err or {"state": "empty_sheet", "detail": "No readable worksheet."}

    # ── The backend interface voicecrm.py consumes ──────────────────────────

    def rows(self, token: str) -> dict:
        """Every data row, shaped like List items. Caller applies the owner filter."""
        try:
            with httpx.Client(timeout=30) as client:
                wb, err = self._load(client, token)
                if err:
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
                "headers": [h for h in headers if h], "key_columns_found": wb["found"]}

    def fetch(self, token: str, item_id: str) -> tuple[Optional[dict], Optional[dict]]:
        """One row by its xl<row> id, with the addresses needed to write to it."""
        if not item_id.startswith("xl"):
            return None, {"state": "graph_error", "status": 400,
                          "detail": f"'{item_id}' is not an Excel row id (expected xl<row>)."}
        try:
            sheet_row = int(item_id[2:])
        except ValueError:
            return None, {"state": "graph_error", "status": 400,
                          "detail": f"'{item_id}' is not an Excel row id (expected xl<row>)."}

        try:
            with httpx.Client(timeout=30) as client:
                wb, err = self._load(client, token)
                if err:
                    return None, err
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

        return {
            "fields": fields,
            "eTag": _fingerprint(cells),
            "_wb": wb,
            "_addr": addr,
            # The row as read and each column's place in it: lets confirm()
            # tell this person's own just-saved changes from someone else's.
            "_cells": cells,
            "_col": {h: j for j, h in enumerate(headers) if h},
        }, None

    def is_formula(self, token: str, item: dict, field: str) -> bool:
        """True when the cell holds a formula. A calculated cell is never typed
        over: it would silently replace the calculation with a fixed value.
        Unreadable counts as a formula - refusing is the safe side."""
        addr = item.get("_addr", {}).get(field)
        if not addr:
            return False
        wb = item["_wb"]
        try:
            with httpx.Client(timeout=30) as client:
                res = client.get(f"{wb['base']}/worksheets('{wb['sheet']}')/range(address='{addr}')",
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
        try:
            with httpx.Client(timeout=30) as client:
                res = client.patch(url, headers={**self._headers(token),
                                                 "Content-Type": "application/json"},
                                   json={"values": [[new_value]]})
        except httpx.HTTPError as exc:
            return {"state": "unreachable",
                    "detail": f"Could not reach Microsoft Graph: {exc}"}
        if res.status_code >= 300:
            return {"state": "failed", "status": res.status_code,
                    "detail": self._graph_detail(res)}
        return None

    def download(self, token: str) -> tuple[Optional[bytes], Optional[dict]]:
        """The whole workbook file, for a reader with no signed-in user.

        The scheduled morning review runs with an app-only token, which the
        workbook (Excel) API does not accept; the file itself can always be
        downloaded, and is then read locally. Read-only by construction.
        """
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                self._download_only = True
                try:
                    loc, err = self._workbook(client, token)
                finally:
                    self._download_only = False
                if err:
                    return None, err
                res = client.get(f"{GRAPH}/drives/{loc['drive_id']}/items/{loc['item_id']}/content",
                                 headers=self._headers(token))
        except httpx.HTTPError as exc:
            return None, {"state": "unreachable", "detail": f"Could not reach Microsoft Graph: {exc}"}
        if res.status_code != 200:
            return None, self._err(res)
        return res.content, None
