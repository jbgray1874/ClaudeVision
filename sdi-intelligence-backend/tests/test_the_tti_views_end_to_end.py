"""The six TTI views over HTTP, from the gate to the JSON.

The rest of the TTI tests read the modules. This one makes the requests, with
a workbook built here and SharePoint stood in for, because three things only
go wrong once a request is actually made:

  * the router is mounted but a view is not gated - the sort of thing that is
    invisible in a module and obvious in a 200 that should have been a 403;
  * a view answers but without saying how old the reading is;
  * a date or a search term arrives as a string and is trusted.

The page is served to named people and refused to everyone else, including
somebody who is signed in to SDI and simply is not on the list - which is most
of the company.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth                                                         # noqa: E402
import tti_data                                                     # noqa: E402
import tti_despatch_routes as routes                                # noqa: E402
import tti_plan_source as plan                                      # noqa: E402

SUE = {"name": "Sue Rogers", "email": "sue.rogers@wearesdi.com",
       "oid": "cc53597a-c1b5-4bf9-b862-f63f7392ff81", "kind": "user"}
SOMEBODY_ELSE = {"name": "Someone Else", "email": "someone@wearesdi.com",
                 "oid": "not-on-the-list", "kind": "user"}
SAVED = datetime(2026, 10, 23, 14, 5, tzinfo=timezone.utc)

HEADERS = ["DUE DATE", "TTI ACCOUNT", "SDI ORDER NO", "CUSTOMER PO", "PART CODE",
           "DESCRIPTION", "QTY", "COMMENTS", "PALLETS", "LORRY FROM SDI",
           "LABEL + Batch DONE", "BOOKED IN WITH TTI", "INVOICE NUMBER",
           "PROOF OF EXPORT"]

# Four lines, each one a different thing the views have to notice.
ROWS = [
    # Going out the day the plan was saved, picked, nothing booked in.
    ["30/10/2026", "TTI-001", "15194", "PO9981", "ABC-1", "Gondola", 12,
     "Pick note number: 40015908 \nDel Note -", 4, "23/10/2026", "", "", "", ""],
    # Was due out before the save and is still not invoiced.
    ["15/10/2026", "TTI-001", "15195", "PO9982", "ABC-2", "Bay", 3, "", "two",
     "15/10/2026", "YES", "YES", "", ""],
    # Customer wanted it three weeks ago; nobody has planned a lorry.
    ["01/10/2026", "TTI-002", "15300", "PO9983", "XYZ", "Shelf", 6, "", 1, "",
     "", "", "", ""],
    # A departure date nothing can read.
    ["30/10/2026", "TTI-002", "15301", "", "XYZ-2", "Shelf end", 2, "await po",
     1, "ask Sue", "", "", "", ""],
]


def workbook() -> bytes:
    import io
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "Oct 26 WK 40"
    sheet.append(["TTI DELIVERY SCHEDULE"])          # a title row above the headers
    sheet.append(HEADERS)
    for line in ROWS:
        sheet.append(line)
    held = io.BytesIO()
    book.save(held)
    return held.getvalue()


@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    tti_data.forget()
    who = {"user": SUE}
    monkeypatch.setattr(auth, "ENABLED", True)
    monkeypatch.setattr(auth, "current_user", lambda request: who["user"])
    monkeypatch.setattr(auth, "graph_token", lambda request: "graph-token-for-sue")
    monkeypatch.setenv("SDI_TTI_OIDS", SUE["oid"])
    monkeypatch.setenv("SDI_TTI_PLAN_SITE", "sdidisplays.sharepoint.com:/sites/SUESOSOD")
    monkeypatch.setenv("SDI_TTI_PLAN_PATH", "General/Plan.xlsx")
    monkeypatch.setattr(plan, "fetch_plan",
                        lambda token, client=None, known_version="":
                        (workbook(), SAVED, '"ETAG-1"'))

    app = FastAPI()
    app.include_router(routes.make_router())
    made = TestClient(app)
    made.who = who                          # tests swap the signed-in person
    yield made
    tti_data.forget()


VIEWS = ("/api/tti/despatch/day?day=2026-10-23",
         "/api/tti/despatch/week?day=2026-10-23",
         "/api/tti/despatch/search?q=15194",
         "/api/tti/despatch/chase",
         "/api/tti/despatch/overdue",
         "/api/tti/despatch/morning",
         "/api/tti/despatch/quality")


def test_the_page_is_served_to_a_named_person(client):
    answer = client.get("/api/tti/despatch")
    assert answer.status_code == 200
    assert "TTI DESPATCH" in answer.text
    assert answer.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("url", VIEWS + ("/api/tti/despatch",
                                         "/api/tti/despatch/morning.txt"))
def test_somebody_signed_in_but_not_on_the_list_is_refused_every_view(client, url):
    """Most of the company is signed in to SDI and not on this list. A view
    that checks the sign-in and not the list is open to all of them."""
    client.who["user"] = SOMEBODY_ELSE
    answer = client.get(url)
    assert answer.status_code == 403
    assert "named Customer Services people" in answer.json()["detail"]


@pytest.mark.parametrize("url", VIEWS)
def test_nobody_at_all_is_refused_every_view(client, url):
    client.who["user"] = None
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("url", VIEWS)
def test_every_view_says_which_save_of_the_plan_it_read(client, url):
    said = client.get(url).json()
    assert said["plan_saved"] == SAVED.isoformat()
    assert said["plan_version"]
    assert said["rows_read"] == 4
    assert said["source_version_date"] == "2026-10-23"


def test_what_is_leaving_on_the_day_the_plan_was_saved(client):
    said = client.get("/api/tti/despatch/day?day=2026-10-23").json()
    assert said["line_count"] == 1
    assert said["lines"][0]["order"] == "15194"
    assert said["lines"][0]["source"] == "Oct 26 WK 40!row 3"
    # The unreadable one is counted, so "that is all of them" is never implied.
    assert said["unresolved_date_count"] == 1


def test_search_finds_an_order_across_the_book(client):
    said = client.get("/api/tti/despatch/search?q=15194").json()
    assert said["match_count"] == 1
    assert said["matches"][0]["pick_note"] == "40015908"
    assert said["matches"][0]["delivery_note"] == ""       # "Del Note -" is not one


def test_search_refuses_an_empty_term_rather_than_returning_the_book(client):
    answer = client.get("/api/tti/despatch/search?q=%20%20")
    assert answer.status_code == 400
    assert "search for" in answer.json()["detail"]


def test_a_search_term_longer_than_the_box_is_refused(client):
    assert client.get("/api/tti/despatch/search?q=" + "x" * 200).status_code == 422


def test_the_chase_list_groups_by_what_is_blocking(client):
    said = client.get("/api/tti/despatch/chase").json()
    reasons = {g["reason"] for g in said["groups"]}
    assert "despatched_not_invoiced" in reasons
    assert "picked_but_not_despatched" in reasons
    assert "awaiting_customer_po" in reasons
    for group in said["groups"]:
        for line in group["lines"]:
            assert line["because"]
            assert line["source"].startswith("Oct 26 WK 40!row ")


def test_the_chase_horizon_is_bounded(client):
    assert client.get("/api/tti/despatch/chase?horizon=0").status_code == 200
    assert client.get("/api/tti/despatch/chase?horizon=900").status_code == 422
    assert client.get("/api/tti/despatch/chase?horizon=-1").status_code == 422


def test_overdue_finds_the_row_nobody_updated(client):
    said = client.get("/api/tti/despatch/overdue").json()
    assert said["line_count"] == 1
    assert said["lines"][0]["order"] == "15300"
    assert said["lines"][0]["overdue_by_days"] == 22


def test_the_morning_summary_comes_with_the_words_to_send(client):
    said = client.get("/api/tti/despatch/morning").json()
    assert said["due_out_count"] == 1
    assert said["slipped_count"] == 1
    assert said["incomplete_count"] == 1
    assert "15194" in said["as_text"]
    assert "Oct 26 WK 40!row 3" in said["as_text"]
    assert "not confirmation that goods have left" in said["as_text"]


def test_the_morning_summary_is_also_plain_text_to_paste(client):
    answer = client.get("/api/tti/despatch/morning.txt")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/plain")
    assert "TTI despatch - Friday 23 October 2026" in answer.text


def test_data_quality_names_the_cells_it_cannot_read(client):
    said = client.get("/api/tti/despatch/quality").json()
    problems = {g["problem"] for g in said["groups"]}
    assert "unreadable_departure_date" in problems
    assert "pallets_not_a_number" in problems


@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-45", "23/10/2026"])
def test_a_date_that_is_not_a_date_is_refused_rather_than_guessed(client, bad):
    answer = client.get("/api/tti/despatch/day?day=" + bad)
    assert answer.status_code in (400, 422)
    if answer.status_code == 400:
        assert "YYYY-MM-DD" in answer.json()["detail"]


def test_sharepoint_being_unreachable_is_said_and_not_guessed_around(client,
                                                                     monkeypatch):
    def refuse(token, client=None, known_version=""):
        raise plan.PlanUnavailable("Your account does not have access to the plan "
                                   "in SharePoint.")

    monkeypatch.setattr(plan, "fetch_plan", refuse)
    tti_data.forget()
    answer = client.get("/api/tti/despatch/chase")
    assert answer.status_code == 503
    assert "does not have access" in answer.json()["detail"]


def test_no_view_offers_a_way_to_change_anything(client):
    """Every route is a GET, and the ones that would change something do not
    exist. A POST to any of them is Method Not Allowed, not a surprise."""
    for url in VIEWS:
        assert client.post(url.split("?")[0]).status_code == 405
