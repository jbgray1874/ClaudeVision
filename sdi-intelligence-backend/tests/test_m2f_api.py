"""Tests for the Monday2Friday workspace and its API, on the synthetic tracker."""
import os
import sys
from pathlib import Path

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import m2f_routes  # noqa: E402
from m2f.service import Workspace, describe  # noqa: E402


@pytest.fixture
def client(tracker, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    m2f_routes.set_workspace(Workspace(tracker, tmp_path / "data"))
    app = FastAPI()
    app.include_router(m2f_routes.router)
    yield TestClient(app)
    m2f_routes.set_workspace(None)


def _edit_tracker(path, changes):
    wb = openpyxl.load_workbook(path)
    ws = wb["Current -Boots"]
    for cell, value in changes.items():
        ws[cell] = value
    wb.save(path)
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + 5))


def _pid(client, name):
    return next(p["pid"] for p in client.get("/api/m2f/projects").json()["projects"] if p["name"] == name)


def test_status_reports_the_loaded_tracker(client):
    s = client.get("/api/m2f/status").json()
    assert s["ready"] and s["source"] == "tracker.xlsx" and s["summary"]["projects"] == 4


def test_dashboard_cards_and_accounts(client):
    d = client.get("/api/m2f/dashboard?asof=2026-10").json()
    assert d["periods"]["this_label"] == "Oct 2026" and d["periods"]["year_label"] == "FY26"
    assert d["cards"]["this_month"]["total"] == "100.00"
    assert d["cards"]["this_month"]["by_status"]["Risk"] == "100.00"
    assert d["cards"]["next_month"]["by_status"]["TBC"] == "1200.50"
    assert d["cards"]["full_year"]["total"] == "1600.50"
    assert d["cards"]["full_year"]["by_status"]["Unclassified"] == "300.00"
    assert {a["account"] for a in d["accounts"]} == {"Boots UK"}
    assert d["needs_decision"][0]["project"] == "Alpha display"


def test_bad_month_is_rejected(client):
    assert client.get("/api/m2f/dashboard?asof=Nov").status_code == 422


def test_pm_overview_hides_hidden_rows_and_follows_aliases(client):
    pm = client.get("/api/m2f/pm/Conor?asof=2026-10").json()
    assert [p["name"] for p in pm["projects"]] == ["Alpha display"]
    assert pm["hidden_projects"] == 1 and pm["projects"][0]["at_risk"]
    client.put("/api/m2f/assignments", json={"kind": "alias", "subject": "conor", "person": "Conor Smith"})
    assert client.get("/api/m2f/pm/Conor Smith").json()["counts"]["live"] == 1


def test_account_owner_drives_the_am_workspace(client):
    client.put("/api/m2f/assignments", json={"kind": "account_am", "subject": "Boots", "person": "Kayleigh"})
    am = client.get("/api/m2f/am/Kayleigh?asof=2026-10").json()
    assert am["accounts"] == ["Boots"]
    assert am["cards"]["this_month"]["total"] == "100.00"
    assert {p["name"] for p in am["projects"]} == {"Alpha display", "12345", "Gamma order"}
    client.put("/api/m2f/assignments", json={"kind": "account_am", "subject": "Boots", "person": None})
    assert client.get("/api/m2f/am/Kayleigh").json()["projects"] == []


def test_unknown_assignment_kind_is_refused(client):
    r = client.put("/api/m2f/assignments", json={"kind": "boss", "subject": "x", "person": "y"})
    assert r.status_code == 400


def test_weekly_review_shows_what_moved_since_the_freeze(client, tracker):
    freeze = client.post("/api/m2f/freezes", json={"label": "Week 1", "by": "Kayleigh"}).json()
    _edit_tracker(tracker, {"D3": None, "E3": 100})
    r = client.get(f"/api/m2f/review/{freeze['id']}?asof=2026-10").json()
    alpha = next(m for m in r["movements"] if m["project"] == "Alpha display")
    assert alpha["summary"] == "£100 moved from Oct 2026 to Nov 2026"
    assert r["compare"]["this_month"] == {"label": "Oct 2026", "at_freeze": "100.00", "now": "0.00", "change": "-100.00"}
    client.put(f"/api/m2f/review/{freeze['id']}/notes/{alpha['pid']}",
               json={"reason": "Retailer moved install", "next_action": "Confirm billing date"})
    again = client.get(f"/api/m2f/review/{freeze['id']}").json()
    assert next(m for m in again["movements"] if m["pid"] == alpha["pid"])["reason"] == "Retailer moved install"


def test_review_of_unknown_freeze_is_404(client):
    assert client.get("/api/m2f/review/99").status_code == 404


def test_variations_register(client):
    pid = _pid(client, "Alpha display")
    assert client.post("/api/m2f/variations", json={"pid": pid}).status_code == 400
    assert client.post("/api/m2f/variations", json={"title": "x", "approval_status": "Maybe"}).status_code == 400
    v = client.post("/api/m2f/variations", json={"title": "Extra install night", "pid": pid,
                                                 "sell_value": "4250", "approval_status": "Decision needed"}).json()
    assert v["project"] == "Alpha display" and v["account"] == "Boots UK"
    v = client.patch(f"/api/m2f/variations/{v['id']}", json={"approval_status": "Approved"}).json()
    assert v["approval_status"] == "Approved"
    assert client.get("/api/m2f/variations?open_only=true").json()["variations"] == []
    assert client.get(f"/api/m2f/projects/{pid}").json()["variations"][0]["title"] == "Extra install night"


def test_answering_the_status_question_relabels_the_dashboard(client):
    q = {x["id"]: x for x in client.get("/api/m2f/questions").json()["questions"]}
    assert q["status_mapping"]["decision"] is None and q["unclassified_colours"]["evidence"]
    client.put("/api/m2f/questions/status_mapping", json={"choice": "yes", "answer": "Agreed", "by": "Kayleigh"})
    labels = client.get("/api/m2f/dashboard").json()["labels"]
    assert labels["Confirmed"] == "PO received" and labels["TBC"] == "Awaiting PO"
    assert client.put("/api/m2f/questions/nope", json={}).status_code == 404


def test_project_detail_lists_lines_and_issues(client):
    d = client.get(f"/api/m2f/projects/{_pid(client, 'Gamma order')}").json()
    assert d["account"] == "Sigma"
    assert d["lines"][0]["raw"] == "loade" and d["lines"][0]["amount"] is None
    assert any(i["code"] == "amount_unreadable" for i in d["issues"])
    assert client.get("/api/m2f/projects/nope").status_code == 404


def test_upload_replaces_the_tracker(tracker, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    m2f_routes.set_workspace(Workspace(None, tmp_path / "upload-data"))
    app = FastAPI()
    app.include_router(m2f_routes.router)
    c = TestClient(app)
    assert c.get("/api/m2f/dashboard").status_code == 409
    assert c.put("/api/m2f/tracker", content=b"not a workbook").status_code == 400
    s = c.put("/api/m2f/tracker", content=tracker.read_bytes()).json()
    assert s["ready"] and s["source_kind"] == "uploaded"
    m2f_routes.set_workspace(None)


def test_key_is_required_when_set(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "secret")
    assert client.get("/api/m2f/status").status_code == 401
    assert client.get("/api/m2f/status", headers={"X-SDI-Key": "secret"}).status_code == 200


def test_pages_are_served(client):
    for path in ("/m2f", "/m2f/architecture", "/m2f/guide"):
        r = client.get(path)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"], path


def test_describe_movements():
    def c(label, before, after, sb=None, sa=None):
        return {"label": label, "before": before, "after": after, "status_before": sb, "status_after": sa}
    assert describe([c("Mar 2027", "20000", "0"), c("Apr 2027", "0", "20000")]) == "£20,000 moved from Mar 2027 to Apr 2027"
    assert describe([c("Mar 2027", "0", "500")]) == "£500 added in Mar 2027"
    assert describe([c("Mar 2027", "500", "0")]) == "£500 removed from Mar 2027"
    assert describe([c("Mar 2027", "500", "500", "TBC", "Confirmed")]) == "Mar 2027 TBC to Confirmed"
