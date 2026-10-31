"""A finished self-running estimate is e-mailed with its files and a spoken walkthrough (D-609).

31 Oct 2026, James: "after each run can we have an e-mail sent to the email set at 'Email the
finished estimate to' ... with the files associated with the run and a voice walk through
also."

The e-mail already existed for a run that names recipients: the service sends the workbook,
the report and the explanation, and holds the customer quote back while it is provisional.
Self-running named nobody. Now it names the page's saved list, and every finished estimate
carries <stem>_walkthrough.wav: the covering note's own figures, spoken by the laptop's own
voice, so no word of the job leaves the building.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimate_explained as ee  # noqa: E402
import live_enquiry_runner as L  # noqa: E402
import walkthrough_audio as wa  # noqa: E402


# ── the words ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, said", [
    (538.06, "538 pounds and 6 pence"),
    (1, "1 pound"),
    (1234.5, "1,234 pounds and 50 pence"),
    (0.999, "1 pound"),
    (None, "an amount not yet known"),
])
def test_money_is_said_as_a_voice_reads_it(value, said):
    assert ee.say_gbp(value) == said


def _walk(**over):
    args = dict(
        job="12678-01-GA", client="M&S", order_qty=1,
        total={"amount": 538.06, "cell": "Estimate!M225"},
        totals={"material": 300.0, "labour": 200.0}, other=38.06,
        by_block={"bom": 120.0, "steel": 180.0, "other_sheet": 0},
        block_words={"bom": "bought-in and commercial", "steel": "sheet steel"},
        labour_rows=[{"operation": "Laser", "total_value_gbp": 20},
                     {"operation": "Weld (CO2)", "total_value_gbp": 90},
                     {"operation": "Powder coat", "total_value_gbp": 60},
                     {"operation": "Packing", "total_value_gbp": 5}],
        quantity_rows=[{"quantity": 1, "unit": 538.06}, {"quantity": 5, "unit": 401.2},
                       {"quantity": 10, "unit": 377.0}],
        need="To confirm: 1 price to add + 14 market figures to replace",
        focus=["<b>1 line carries no price</b> — §5 names it.",
               "<b>14 market figures</b> to replace before quoting. §3",
               "<b>Bought-in prices do not step down at quantity</b> on the table in §1",
               "<b>a fourth item</b>"],
        provisional=True)
    args.update(over)
    return ee.spoken_walkthrough(**args)


def test_the_walkthrough_says_the_note_in_order():
    said = _walk()
    assert said.startswith("SDI Intelligence walkthrough for 12678-01-GA, for M&S.")
    assert "costed at 1 off, at 538 pounds and 6 pence a unit, excluding VAT" in said
    assert "Material comes to 300 pounds and labour to 200 pounds, with 38 pounds and 6 " \
           "pence added by the unit price's own uplift." in said
    assert "Most of the material is sheet steel at 180 pounds and bought-in and commercial " \
           "at 120 pounds." in said
    assert ("The largest labour lines are weld (co2) at 90 pounds, powder coat at 60 pounds "
            "and laser at 20 pounds.") in said
    assert "At the other quantities: 5 off, 401 pounds and 20 pence a unit; 10 off, 377 " \
           "pounds a unit." in said
    assert "Still to confirm: 1 price to add, 14 market figures to replace" in said
    assert ("What needs your eye. First: 1 line carries no price. Second: 14 market figures. "
            "Third: Bought-in prices do not step down at quantity.") in said
    assert "a fourth item" not in said, "three items, not a list read aloud"
    assert "This estimate is provisional." in said


def test_the_walkthrough_carries_no_markup_section_marks_or_symbols():
    said = _walk()
    assert "<" not in said and "§" not in said and "£" not in said and "+" not in said
    assert len(said.split()) < 300, "about a minute and a half"


def test_a_total_that_cannot_be_traced_is_said_as_pending_never_spoken_as_a_figure():
    said = _walk(total={"amount": None, "why": "the sheet's total could not be traced"})
    assert "the unit cost is pending: the sheet's total could not be traced." in said
    assert "538 pounds and 6 pence a unit" not in said


def test_a_released_estimate_does_not_say_provisional():
    assert "provisional" not in _walk(provisional=False)


def test_money_brackets_and_long_detail_inside_the_items_are_made_speakable():
    said = _walk(
        need="To confirm: 1 price to add + 14 market figures to replace (£1,664.83)",
        focus=["<b>£26.50 a unit rests on engine allowances not confirmed for this job; the "
               "rest is detail.</b> More words.",
               "<b>Blocks release: schema 'none' (expected one of ['v1', 'v2']).</b>"])
    assert "Still to confirm: 1 price to add, 14 market figures to replace, 1,664 pounds " \
           "and 83 pence." in said
    assert "First: 26 pounds and 50 pence a unit rests on engine allowances not confirmed " \
           "for this job." in said
    assert "the rest is detail" not in said, "the first sentence only"
    assert "Second: Blocks release: schema 'none'." in said, "brackets are not read aloud"
    assert "£" not in said and "[" not in said


def test_unknown_totals_and_unnamed_material_are_not_read_out():
    said = _walk(totals={"material": None, "labour": None}, other=None,
                 by_block={"?": 65.58, "steel": 10})
    assert "The sheet's material and labour totals could not be read." in said
    assert "not yet known" not in said and "? at" not in said
    assert "Most of the material is sheet steel at 10 pounds." in said


def test_the_covering_note_returns_the_walkthrough_from_its_own_figures(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
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
    ws["C9"] = "Bill of Materials (Per Unit)"
    xlsx = tmp_path / "1234567_20261031_010000.xlsx"
    wb.save(xlsx)
    jp = tmp_path / "1234567.json"
    jp.write_text(json.dumps(s, default=str), encoding="utf-8")
    note = ee.covering_email(xlsx, jp, client="M&S", deliverables=[str(xlsx)])
    said = note["spoken"]
    assert said.startswith("SDI Intelligence walkthrough for 1234567, for M&S.")
    assert "<" not in said and "§" not in said
    assert "This estimate is provisional." in said


# ── the sound ──────────────────────────────────────────────────────────────────────────

def test_without_a_speech_synthesiser_the_words_are_written_and_it_says_why(tmp_path):
    xlsx = tmp_path / "12678-01-GA_20261031_191633.xlsx"
    ok, said = wa.write_walkthrough("Hello  there.", xlsx, windows=False)
    txt, wav = wa.paths_for(xlsx)
    assert not ok and "no Windows speech synthesiser" in said
    assert txt.read_text(encoding="utf-8") == "Hello there.\n" and not wav.exists()


def test_the_laptops_own_voice_speaks_it_with_paths_kept_out_of_the_command(tmp_path):
    xlsx = tmp_path / "M&S $job 'x'" / "12678-01-GA_20261031.xlsx"
    xlsx.parent.mkdir()
    seen = {}

    def fake_run(cmd, env=None, **kw):
        seen.update(cmd=cmd, env=env, kw=kw)
        Path(env["SDI_WALKTHROUGH_WAV"]).write_bytes(b"RIFF" + b"\0" * 2048)
        return subprocess.CompletedProcess(cmd, 0)

    ok, said = wa.write_walkthrough("The estimate.", xlsx, run=fake_run, windows=True)
    txt, wav = wa.paths_for(xlsx)
    assert ok and wav.name in said and txt.name in said
    script = seen["cmd"][-1]
    assert seen["cmd"][0] == "powershell"
    assert "System.Speech" in script and "SetOutputToWaveFile" in script
    assert f"SpeechAudioFormatInfo({wa.AUDIO_HZ}" in script and "en-GB" in script
    assert seen["env"]["SDI_WALKTHROUGH_TXT"] == str(txt)
    assert str(xlsx.parent) not in script, "paths travel in the environment, never the command"
    assert seen["kw"]["timeout"] == wa.TIMEOUT_SECONDS and seen["kw"]["check"] is True


def test_a_voice_that_fails_never_stops_the_estimate(tmp_path):
    xlsx = tmp_path / "J_20261031.xlsx"

    def broken(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd)

    ok, said = wa.write_walkthrough("Words.", xlsx, run=broken, windows=True)
    assert not ok and "could not be made" in said and wa.paths_for(xlsx)[0].exists()
    assert wa.write_walkthrough("", xlsx, windows=True)[0] is False


def test_the_engine_writes_the_walkthrough_after_the_covering_note():
    main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    note = main.index('_sop["covering_email"] = str(_note_path)')
    walk = main.index('_walkthrough(_note["spoken"], Path(xlsx_path))')
    assert note < walk < main.index('_time_stage("deliverables", False)')


def test_the_runner_files_the_sound_with_the_estimate():
    sys.path.insert(0, str(ROOT / "tools" / "runner"))
    import sdi_estimate_runner as runner
    assert ".wav" in runner.DELIVERABLE_SUFFIXES


def test_the_mail_attaches_the_walkthrough_and_still_holds_the_quote(tmp_path):
    sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
    import estimate_email
    files = [{"path": str(tmp_path / n)} for n in
             ("J_20261031.xlsx", "J_report.html", "J_walkthrough.wav", "J_walkthrough.txt",
              "J_quote.html")]
    keep, held = estimate_email.choose_attachments(files, provisional=True, include_quote=False)
    names = {Path(p).name for p in keep}
    assert {"J_walkthrough.wav", "J_walkthrough.txt", "J_20261031.xlsx"} <= names
    assert "J_quote.html" not in names and held


# ── who it goes to ─────────────────────────────────────────────────────────────────────

def _decision(tmp_path):
    folder = tmp_path / "M&S" / "0359974-12678-01-GA"
    folder.mkdir(parents=True)
    (folder / "GA.pdf").write_bytes(b"%PDF")
    row = L.EnquiryRow(row=39, customer="M&S", drawing="12678-01-GA", quantities="1,5,10",
                       ai_check="YES", completed_column=True)
    return L.Decision(row, "ready", "first run",
                      located=L.Located("found", folder=folder, client_folder_name="M&S"),
                      quantities=[1, 5, 10])


def test_the_request_names_the_saved_list(tmp_path, monkeypatch):
    d = _decision(tmp_path)
    assert L.request_body(d, ["a@wearesdi.com", "b@wearesdi.com"])["email_to"] == \
        "a@wearesdi.com, b@wearesdi.com"
    monkeypatch.setattr(L.config, "LIVE_ENQUIRY_EMAIL_TO", "")
    assert L.request_body(d)["email_to"] is None, "nobody named: sent to nobody"


def test_the_portal_is_asked_for_the_pages_saved_list(monkeypatch):
    portal = L.Portal("http://localhost:8071")
    asked = []
    monkeypatch.setattr(portal, "_call", lambda method, path, body=None: (
        asked.append((method, path)), {"recipients": ["james.gray@wearesdi.com", " "]})[1])
    assert portal.recipients() == ["james.gray@wearesdi.com"]
    assert asked == [("GET", "/api/estimate/recipients")]


class _Portal:
    def __init__(self, recipients=None):
        self.bodies, self._recipients = [], recipients

    def recipients(self):
        if self._recipients is None:
            raise L.PortalError(0, "the portal did not answer")
        return self._recipients

    def start(self, body):
        self.bodies.append(body)
        return {"run_id": "r1", "output_path": "C:\\out"}

    def status(self, run_id):
        return {"status": "done", "engine_price_gbp": 538.06, "seconds": 1,
                "output_path": "C:\\out", "deliverables": []}


class _On:
    def beat(self, rep):
        return True


def _cycle(tmp_path, monkeypatch, portal, email_env=""):
    import self_running as sr
    root = tmp_path / "Live Enquiry"
    (root / "M&S" / "0359974-12678-01-GA").mkdir(parents=True)
    (root / "M&S" / "0359974-12678-01-GA" / "GA.pdf").write_bytes(b"%PDF")
    rows = [L.EnquiryRow(row=39, customer="M&S", drawing="12678-01-GA", quantities="1,5,10",
                         ai_check="YES", received=date(2026, 10, 30))]
    monkeypatch.setattr(L, "read_sheet", lambda path, sheet="": rows)
    monkeypatch.setattr(sr.config, "LIVE_ENQUIRY_EMAIL_TO", email_env)
    said = []
    sr.cycle({"root": root, "ledger": tmp_path / "ledger.json",
              "workbook": tmp_path / "AI-Live-Enquiry.xlsx"}, portal, _On(),
             say=said.append, wait={"poll_seconds": 0, "sleep": lambda x: None})
    return said


def test_self_running_emails_each_finished_estimate_to_the_saved_list(tmp_path, monkeypatch):
    portal = _Portal(["james.gray@wearesdi.com"])
    said = _cycle(tmp_path, monkeypatch, portal)
    assert portal.bodies[0]["email_to"] == "james.gray@wearesdi.com"
    assert any("e-mailed to james.gray@wearesdi.com" in s for s in said)


def test_a_list_that_cannot_be_read_files_the_estimate_and_sends_to_nobody(tmp_path,
                                                                         monkeypatch):
    portal = _Portal(None)
    said = _cycle(tmp_path, monkeypatch, portal)
    assert portal.bodies[0]["email_to"] is None
    assert any("could not be read" in s for s in said)


def test_the_live_enquiry_setting_wins_over_the_saved_list(tmp_path, monkeypatch):
    portal = _Portal(["someone@else.com"])
    _cycle(tmp_path, monkeypatch, portal, email_env="estimating@wearesdi.com")
    assert portal.bodies[0]["email_to"] == "estimating@wearesdi.com"
