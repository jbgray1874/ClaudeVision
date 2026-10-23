"""A saved change is one cell, verified against the sheet, and traceable when it fails.

Nick Garrish, 23 October 2026, after ChatGPT could read the tracker but not write to it:
"The available SharePoint write actions replace the whole file, so no write was
attempted." That is ChatGPT's own SharePoint connector, not this one. He asked us to
confirm four things about our route, and these are those four:

  * only the requested cells are updated, through the Excel range API, with no
    replacing or re-uploading of the workbook;
  * the changed cell is read back to verify the save;
  * delegated permissions are used (application permissions are not supported for
    workbook operations at all);
  * a failure reports HTTP status, error code and the correlation/request ID.
"""
import sys
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import voicecrm_excel as vx  # noqa: E402

SHEET, ADDR = "Tracker", "G14"
WB = {"base": "https://graph.microsoft.com/v1.0/drives/d1/items/i1/workbook", "sheet": SHEET}
ITEM = {"_wb": WB, "_addr": {"Status": ADDR, "End date": "K14"}}


def _store() -> vx.ExcelStore:
    store = vx.ExcelStore.__new__(vx.ExcelStore)
    store.key_columns = []
    return store


class _Graph:
    """Records every call, and answers the range GET with whatever the cell holds."""

    def __init__(self, cell="old", patch_status=200, headers=None, get_status=200):
        self.cell, self.patch_status, self.get_status = cell, patch_status, get_status
        self.headers = headers or {"request-id": "abc-123"}
        self.calls = []

    def __call__(self, *a, **kw):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def patch(self, url, headers=None, json=None, **kw):
        self.calls.append(("PATCH", url, json, headers))
        if self.patch_status < 300:
            self.cell = json["values"][0][0]
        body = {} if self.patch_status < 300 else {
            "error": {"code": "accessDenied", "message": "Access denied."}}
        return httpx.Response(self.patch_status, json=body, headers=self.headers,
                              request=httpx.Request("PATCH", url))

    def get(self, url, headers=None, params=None, **kw):
        self.calls.append(("GET", url, params, headers))
        return httpx.Response(self.get_status,
                              json={"text": [[self.cell]], "values": [[self.cell]]},
                              headers=self.headers, request=httpx.Request("GET", url))


def test_only_the_named_cell_is_written_and_the_file_is_never_replaced(monkeypatch):
    graph = _Graph()
    monkeypatch.setattr(vx.httpx, "Client", graph)
    assert _store().apply("tok", ITEM, "Status", "Presentation in with Morrisons") is None

    patches = [c for c in graph.calls if c[0] == "PATCH"]
    assert len(patches) == 1, graph.calls
    _, url, body, _ = patches[0]
    assert url.endswith(f"/worksheets('{SHEET}')/range(address='{ADDR}')"), url
    assert body == {"values": [["Presentation in with Morrisons"]]}
    # Nothing that replaces or re-uploads the workbook.
    for _, url, _, _ in graph.calls:
        assert "/content" not in url, f"the file itself was touched: {url}"
        assert "createUploadSession" not in url and "createSession" not in url, url


def test_the_cell_is_read_back_after_the_write(monkeypatch):
    graph = _Graph()
    monkeypatch.setattr(vx.httpx, "Client", graph)
    _store().apply("tok", ITEM, "Status", "Follow up January 2027")
    kinds = [c[0] for c in graph.calls]
    assert kinds == ["PATCH", "GET"], kinds
    assert graph.calls[1][1] == graph.calls[0][1], "it reads back the address it wrote"


def test_a_write_graph_accepted_but_did_not_save_is_reported_as_a_failure(monkeypatch):
    """A 200 on the PATCH is not a saved cell. Telling somebody their change is
    saved when it is not is the one outcome this whole path exists to prevent."""
    graph = _Graph()

    def patch(url, headers=None, json=None, **kw):          # accepted, then discarded
        graph.calls.append(("PATCH", url, json, headers))
        return httpx.Response(200, json={}, headers={"request-id": "trace-me"},
                              request=httpx.Request("PATCH", url))

    monkeypatch.setattr(vx.httpx, "Client", graph)
    monkeypatch.setattr(graph, "patch", patch)
    err = _store().apply("tok", ITEM, "Status", "Follow up January 2027")
    assert err and err["state"] == "not_saved", err
    assert "Nothing was saved" in err["detail"]
    assert ADDR in err["detail"] and "trace-me" in err["detail"]


def test_excel_reformatting_the_value_is_not_a_failure(monkeypatch):
    """Excel stores a typed date as a serial and shows it in the column's format.
    The cell is right if either face of it matches what was asked for."""
    graph = _Graph()
    monkeypatch.setattr(vx.httpx, "Client", graph)

    def get(url, headers=None, params=None, **kw):
        graph.calls.append(("GET", url, params, headers))
        return httpx.Response(200, json={"text": [["30/01/2027"]], "values": [["46416"]]},
                              headers={}, request=httpx.Request("GET", url))

    monkeypatch.setattr(graph, "get", get)
    assert _store().apply("tok", ITEM, "End date", "30/01/2027") is None


def test_a_read_back_that_cannot_be_done_is_not_called_a_failure(monkeypatch):
    """The write answered 200. A second call failing on the network says nothing
    about the first, and reporting it as "not saved" would be a guess."""
    graph = _Graph(get_status=503)
    monkeypatch.setattr(vx.httpx, "Client", graph)
    assert _store().apply("tok", ITEM, "Status", "On hold") is None


def test_a_refused_write_reports_status_code_and_request_id(monkeypatch):
    graph = _Graph(patch_status=403, headers={"request-id": "corr-9876"})
    monkeypatch.setattr(vx.httpx, "Client", graph)
    err = _store().apply("tok", ITEM, "Status", "On hold")
    assert err["state"] == "failed" and err["status"] == 403
    assert "accessDenied" in err["detail"]
    assert "corr-9876" in err["detail"], err["detail"]


@pytest.mark.parametrize("header", ["request-id", "client-request-id", "x-ms-request-id"])
def test_the_request_id_is_found_whichever_header_carries_it(header):
    res = httpx.Response(500, headers={header: "the-id"},
                         request=httpx.Request("GET", "https://graph.microsoft.com/"))
    assert vx.ExcelStore.request_id(res) == "the-id"


def test_the_write_carries_the_signed_in_persons_own_token(monkeypatch):
    """Delegated, not application: Graph does not accept app-only tokens for
    workbook operations at all, which is why the morning review downloads the
    file instead of using this route."""
    graph = _Graph()
    monkeypatch.setattr(vx.httpx, "Client", graph)
    _store().apply("nicks-delegated-token", ITEM, "Status", "On hold")
    for _, _, _, headers in graph.calls:
        assert headers["Authorization"] == "Bearer nicks-delegated-token", headers


def test_no_workbook_session_is_opened():
    """A non-persistent session accepts a write and discards it. We open no session,
    and a range write with no session header is saved to the file."""
    source = (BACKEND / "voicecrm_excel.py").read_text(encoding="utf-8")
    assert "workbook-session-id" not in source
    assert "createSession" not in source
