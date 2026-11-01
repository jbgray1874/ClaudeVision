"""The e-mail leads with the price at every quantity, and its button opens the estimate's
question screen through the portal's public address (D-613).

JG, 1 Nov 2026: "the email had a detailed but readable summary of the estimate across the
units priced also, we need the option of being able to question through prompting the result.
so, when you select the button on the e-mail to prompt / question the estimate, it takes you
to the app with the prompt part of the estimating app screen" on a phone, without the VPN.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

PAGE = (BACKEND / "sdi-walkthrough.html").read_text(encoding="utf-8")


def _walkthrough():
    sys.path.insert(0, str(BACKEND))
    return importlib.import_module("estimate_walkthrough")


# ── the link goes where a phone can open it ─────────────────────────────────────────────

def test_the_link_uses_the_portals_public_address(monkeypatch):
    ew = _walkthrough()
    monkeypatch.delenv("SDI_PORTAL_URL", raising=False)
    monkeypatch.setenv("SDI_PUBLIC_HOSTS", "SDIIntelligence-sdidisplays.msappproxy.net, other.example")
    assert ew.url_for("tok") == ("https://sdiintelligence-sdidisplays.msappproxy.net"
                                 "/estimating/walkthrough/tok")


def test_an_explicit_portal_url_still_wins(monkeypatch):
    ew = _walkthrough()
    monkeypatch.setenv("SDI_PORTAL_URL", "https://apps.example/")
    monkeypatch.setenv("SDI_PUBLIC_HOSTS", "sdiintelligence-sdidisplays.msappproxy.net")
    assert ew.portal_base() == "https://apps.example"


def test_with_no_public_address_it_is_this_machine_never_localhost(monkeypatch):
    ew = _walkthrough()
    monkeypatch.delenv("SDI_PORTAL_URL", raising=False)
    monkeypatch.delenv("SDI_PUBLIC_HOSTS", raising=False)
    monkeypatch.setenv("SDI_PORT", "8071")
    base = ew.portal_base()
    assert base.startswith("http://") and base.endswith(":8071") and "localhost" not in base


# ── the e-mail's buttons ────────────────────────────────────────────────────────────────

def test_the_ask_button_leads_and_opens_the_question_box():
    ew = _walkthrough()
    url = "https://portal.example/estimating/walkthrough/tok"
    note = ew.email_button({"html": '<div style="x"><p>Here is the estimate</p></div>',
                            "text": "Here is the estimate"}, url)
    html = note["html"]
    assert f'href="{url}#ask"' in html and f'href="{url}#listen"' in html
    assert html.index("Ask a question about this estimate") < html.index("Listen to the walkthrough")
    assert html.index("Listen to the walkthrough") < html.index("Here is the estimate")
    assert "sign in with your SDI Microsoft account" in html
    assert note["text"].splitlines()[:2] == [f"Ask a question about this estimate: {url}#ask",
                                            f"Listen to the walkthrough: {url}#listen"]


def test_a_link_that_already_carries_a_fragment_is_not_doubled():
    ew = _walkthrough()
    assert ew.ask_url("https://p/estimating/walkthrough/t#listen") == \
        "https://p/estimating/walkthrough/t#ask"


# ── the page is the question screen ─────────────────────────────────────────────────────

def test_the_page_puts_the_question_box_before_the_player():
    assert PAGE.index('id="pricesBox"') < PAGE.index('<section id="ask"') < PAGE.index(
        '<section id="listen"')


def test_the_page_goes_to_the_box_the_link_names():
    assert 'where === "ask"' in PAGE and '$("question").focus' in PAGE
    assert 'where === "listen"' in PAGE and 'addEventListener("hashchange", goToHash)' in PAGE


def test_a_suggested_question_is_one_tap():
    assert PAGE.count('class="chip"') >= 3
    assert '$("question").value = c.textContent; ask();' in PAGE


def test_the_page_shows_the_order_value_at_each_quantity():
    assert "<th class=\"n\">Order value</th>" in PAGE
    assert "p.unit_gbp * p.quantity" in PAGE
    assert "times the quantity" in PAGE


def test_the_page_links_back_to_the_estimating_app():
    assert '<a href="/estimating">Open the estimating app</a>' in PAGE


# ── the e-mail's own summary ────────────────────────────────────────────────────────────

def _note(tmp_path, sweep=None):
    openpyxl = pytest.importorskip("openpyxl")
    import estimate_explained as ee
    import invariants
    import read_charge_contract as rcc
    from test_a_rolled_part_is_charged_by_the_roll_row import B, _book, _rolled_bracket, _with_row
    os.environ["SDI_QUANTITY_BREAKS"] = "1000"
    s = _with_row(_book(answer=_rolled_bracket()), 161, ["roll"], B, .77, 23.74, "Roll", 2)
    s["read_charge_result"] = rcc.audit(s)
    s.setdefault("job_number", "1234567")
    s.setdefault("job_output_stem", "1234567")
    invariants.check_job(s, write_back=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["D6"] = 1
    xlsx = tmp_path / "1234567_20261101_010000.xlsx"
    wb.save(xlsx)
    jp = tmp_path / "1234567.json"
    jp.write_text(json.dumps(s, default=str), encoding="utf-8")
    return ee.covering_email(xlsx, jp, client="M&S", deliverables=[str(xlsx)],
                             quantity_sweep=sweep)


SWEEP = {"baseline_quantity": 1, "rows": [
    {"quantity": 1, "unit": 538.06, "material": 300.0, "labour": 238.06},
    {"quantity": 5, "unit": 401.2, "material": 290.0, "labour": 111.2},
    {"quantity": 10, "unit": 372.45, "material": 288.0, "labour": 84.45}]}


def test_the_note_leads_with_the_price_at_every_quantity(tmp_path):
    html = _note(tmp_path, SWEEP)["html"]
    top = html.index("Price at each quantity")
    assert top < html.index("What needs your eye") < html.index("At the other quantities")
    table = html[top:html.index("</table>", top)]
    rows = [" | ".join(re.findall(r"<td[^>]*>(.*?)</td>", tr))
            for tr in table.split("</tr>") if "<td" in tr]
    assert rows == ["1 off (as run) | £538.06 | £538.06",
                    "5 off | £401.20 | £2,006.00",
                    "10 off | £372.45 | £3,724.50"]
    assert "The order value is that unit cost times the quantity." in html


def test_the_plain_text_keeps_the_summary_readable(tmp_path):
    text = _note(tmp_path, SWEEP)["text"]
    block = text[text.index("Price at each quantity"):]
    assert "5 off  £401.20  £2,006.00" in block
    assert "10 off  £372.45  £3,724.50" in block


def test_a_quantity_with_no_unit_cost_is_left_out_not_priced_at_nothing(tmp_path):
    sweep = {"baseline_quantity": 1, "rows": [SWEEP["rows"][0], SWEEP["rows"][1],
                                              {"quantity": 50, "unit": None}]}
    html = _note(tmp_path, sweep)["html"]
    table = html[html.index("Price at each quantity"):]
    table = table[:table.index("</table>")]
    assert "50 off" not in table and "£0.00" not in table


def test_with_one_quantity_there_is_no_summary_table(tmp_path):
    html = _note(tmp_path, None)["html"]
    assert "Price at each quantity" not in html
