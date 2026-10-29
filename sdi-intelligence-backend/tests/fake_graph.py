"""A stand-in for Microsoft Graph's workbook API, holding a real grid.

Nick's tracker is the only thing in the estate that WRITES to a live file, and
until now it was the only thing with no tests. The reason it had none is this
file: the write path is four Graph calls deep, and testing it needs something
that behaves like Excel Online rather than something that returns 200.

So this holds an actual grid of cells. A PATCH changes it, and the read-back
afterwards reads what the PATCH left. A test that writes "15500" and reads back
"15500" has proved the address arithmetic, not just that a mock was called.

Two behaviours of the real thing are reproducible here, because both caused
real faults:

  * `lagging=True` - a read made WITHOUT a workbook session can be answered
    from a copy that has not caught up with the write. On 23 October 2026 that
    told Nick Garrish a change already safely in the file had failed. A read
    carrying the session id always sees the write.
  * `refuse=...` - Excel Online declining to open a workbook that is a
    perfectly good file (rewritten outside Excel, caught mid-save, locked).

Every call is recorded, so a test can assert HOW MANY round trips a change
costs. That is what stops the eleven-calls-per-change problem coming back
quietly once it has been fixed.
"""
from __future__ import annotations

import json
import re

GRAPH = "https://graph.microsoft.com/v1.0"

# Nick's tracker in miniature: a title row above the headings (which is what
# made the first version read the title as headers and match none of his 76
# records), then the headings, then three records.
TITLE = ["2026 Account and Project Tracker"]
HEADINGS = ["CLIENT", "JOB", "AM Owner", "STATUS", "NEXT STEPS",
            "KEY DATES FOR NEXT STEPS", "BUDGET COST", "CONFIDENCE", "MARGIN"]
RECORDS = [
    ["Barbour", "Gateshead rollout", "NG", "Live", "Awaiting sign-off",
     "11/14/2026", "15000", "70%", "=G3*0.2"],
    ["The Perfume Shop", "Westfield refit", "NG", "Quoted", "Chase the PO",
     "11/21/2026", "42000", "50%", "=G4*0.2"],
    ["Someone Else Ltd", "Not Nick's job", "RW", "Live", "",
     "12/01/2026", "8000", "30%", "=G5*0.2"],
]


class Reply:
    def __init__(self, status=200, body=None, content=b"", headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.content = content
        self.headers = headers or {"request-id": "req-abc-123"}

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    @property
    def text(self):
        return json.dumps(self._body)


class FakeGraph:
    """One workbook, shared across the clients a single change opens.

    `ExcelStore` opens a fresh `httpx.Client` for the fetch, the formula check
    and the write, so the fixture hands the same instance back each time and
    the grid persists between them - as the real file does.
    """

    SITE_ID = "sdidisplays.sharepoint.com,site-guid,web-guid"
    DRIVE_ID = "drive-1"
    ITEM_ID = "item-1"
    SHEET = "Tracker"
    MODIFIED = "2026-10-28T09:15:00Z"
    ETAG = '"{GUID},7"'

    def __init__(self, *, lagging: bool = False, refuse: dict | None = None,
                 sheets: tuple = ("Summary", "Tracker"), no_session: bool = False):
        # grid[0] is sheet row 1. Cells are strings, as Graph's `text` gives them.
        self.grid = [list(TITLE) + [""] * (len(HEADINGS) - 1),
                     list(HEADINGS)] + [list(r) for r in RECORDS]
        # MARGIN is calculated. Excel shows the result in `text` and the
        # formula in `formulas`, which is the pair the app relies on to refuse
        # typing over a calculated cell.
        self.fgrid = [["" for _ in row] for row in self.grid]
        self.formulas = {}
        for row in range(3, 3 + len(RECORDS)):
            self.formulas[f"I{row}"] = self.grid[row - 1][8]
            self.fgrid[row - 1][8] = self.grid[row - 1][8]
            self.grid[row - 1][8] = "3000"          # the formula's calculated face
        self.sheets = sheets
        self.lagging = lagging              # a sessionless read may be stale
        self.refuse = refuse                # Excel Online declines the workbook
        self.no_session = no_session        # createSession fails
        self.calls: list[tuple] = []
        self.sessions: set = set()
        self.written: list[tuple] = []      # (address, value, had_session)
        self._stale: dict = {}              # address -> the value before the write

    # ── what the tests ask it ───────────────────────────────────────────────
    def count(self, *fragments: str) -> int:
        return sum(1 for _, url in self.calls
                   if all(f in url for f in fragments)) if fragments else len(self.calls)

    def urls(self) -> list:
        return [f"{method} {url.replace(GRAPH, '')}" for method, url in self.calls]

    def cell(self, address: str) -> str:
        column, row = re.fullmatch(r"([A-Z]+)(\d+)", address).groups()
        index = 0
        for ch in column:
            index = index * 26 + (ord(ch) - ord("A") + 1)
        return self.grid[int(row) - 1][index - 1]

    # ── the client interface ExcelStore uses ────────────────────────────────
    def __call__(self, *args, **kwargs):
        return self                       # httpx.Client(...) -> this instance

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    @property
    def base(self) -> str:
        return f"{GRAPH}/drives/{self.DRIVE_ID}/items/{self.ITEM_ID}/workbook"

    def get(self, url, headers=None, params=None, **kw):
        self.calls.append(("GET", url))
        params = params or {}
        session = (headers or {}).get("workbook-session-id", "")

        if url == f"{GRAPH}/sites/sdidisplays.sharepoint.com:/sites/CRMTEST":
            return Reply(200, {"id": self.SITE_ID})
        if re.fullmatch(rf"{re.escape(GRAPH)}/sites/[^/]+/drive/root:/.+", url) \
                or url == f"{GRAPH}/drives/{self.DRIVE_ID}/items/{self.ITEM_ID}":
            return Reply(200, {"id": self.ITEM_ID, "eTag": self.ETAG,
                               "lastModifiedDateTime": self.MODIFIED,
                               "parentReference": {"driveId": self.DRIVE_ID}})
        if url == f"{self.base}/worksheets":
            return Reply(200, {"value": [{"name": n} for n in self.sheets]})

        used = re.fullmatch(rf"{re.escape(self.base)}/worksheets\('(.+?)'\)/usedRange.*", url)
        if used:
            if self.refuse:
                return Reply(self.refuse.get("status", 503),
                             {"error": {"code": self.refuse.get("code", "ServiceUnavailable"),
                                        "message": "The workbook cannot be opened."}})
            asked = str(params.get("$select", ""))
            if used.group(1) != self.SHEET:
                # A real summary tab: text, but none of the key columns.
                body = {"text": [["Summary"], ["Totals", "99"]],
                        "rowIndex": 0, "columnIndex": 0}
                if "formulas" in asked:
                    body["formulas"] = [["", ""], ["", ""]]
                return Reply(200, body)
            body = {"text": [list(r) for r in self.grid],
                    "rowIndex": 0, "columnIndex": 0}
            # Only when asked for: the app does not pay for formulas on a lookup.
            if "formulas" in asked:
                body["formulas"] = [list(r) for r in self.fgrid]
            return Reply(200, body)

        rng = re.fullmatch(
            rf"{re.escape(self.base)}/worksheets\('(.+?)'\)/range\(address='(.+?)'\)", url)
        if rng:
            address = rng.group(2)
            wanted = str(params.get("$select", ""))
            if "formulas" in wanted:
                return Reply(200, {"formulas": [[self.formulas.get(address, "")]]})
            value = self.cell(address)
            if self.lagging and not session and address in self._stale:
                value = self._stale[address]          # the copy that has not caught up
            return Reply(200, {"text": [[value]], "values": [[value]]})

        return Reply(404, {"error": {"code": "itemNotFound", "message": url}})

    def patch(self, url, headers=None, json=None, **kw):
        self.calls.append(("PATCH", url))
        rng = re.fullmatch(
            rf"{re.escape(self.base)}/worksheets\('(.+?)'\)/range\(address='(.+?)'\)", url)
        if not rng:
            return Reply(400, {"error": {"code": "badRequest", "message": url}})
        if self.refuse:
            return Reply(self.refuse.get("status", 503),
                         {"error": {"code": self.refuse.get("code", "ServiceUnavailable"),
                                    "message": "The workbook cannot be opened."}})
        address = rng.group(2)
        value = str(((json or {}).get("values") or [[""]])[0][0])
        column, row = re.fullmatch(r"([A-Z]+)(\d+)", address).groups()
        index = 0
        for ch in column:
            index = index * 26 + (ord(ch) - ord("A") + 1)
        # A real sheet has a million rows, so Graph accepts an address beyond
        # the data. This fake's grid is three records, so it records the write
        # and leaves the grid alone rather than pretending the row exists.
        if int(row) - 1 < len(self.grid) and index - 1 < len(self.grid[int(row) - 1]):
            self._stale[address] = self.grid[int(row) - 1][index - 1]
            self.grid[int(row) - 1][index - 1] = value
        self.written.append((address, value,
                             bool((headers or {}).get("workbook-session-id"))))
        return Reply(200, {"values": [[value]]})

    def post(self, url, headers=None, json=None, **kw):
        self.calls.append(("POST", url))
        if url == f"{self.base}/createSession":
            if self.no_session:
                return Reply(500, {"error": {"code": "InternalServerError",
                                             "message": "no session"}})
            made = f"session-{len(self.sessions) + 1}"
            self.sessions.add(made)
            return Reply(201, {"id": made, "persistChanges": True})
        if url == f"{self.base}/closeSession":
            self.sessions.discard((headers or {}).get("workbook-session-id", ""))
            return Reply(204, {})
        return Reply(404, {"error": {"code": "itemNotFound", "message": url}})
