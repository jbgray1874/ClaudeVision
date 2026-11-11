"""The estimator named on a Live Enquiry row can hear about its estimate too (D-614).

JG, 1 Nov 2026: the finished estimate goes to the people in "Email the finished estimate to"
("just me now, but I can add anyone"), and "we ultimately will drive off the liveenquiry
s/sheet in addition that has an estimator e-mail on there in one of the columns".

Switched off until JG turns it on. When on, the row's own estimator address is added beside the
saved list, never instead of it, and only at SDI's own domain: the estimate is internal costing.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config  # noqa: E402
import live_enquiry_runner as L  # noqa: E402

HEADER = [None, "Enquiry Received", "Account Manager", "Customer", "Job Description",
          "Drawing No.", "Requested Estimate Completion Date", "AI CHECK", "QTY", "AICompleted",
          "Estimator", "Estimator Email"]


def _row(estimator="Tony", email="tony.smith@wearesdi.com", header=HEADER):
    line = [None, datetime(2026, 10, 30), "Andy Morrans", "M&S", "Podium", "12678-01-GA",
            datetime(2026, 11, 5), "YES", "1,5,10", "", estimator, email][:len(header)]
    return L.rows_from_table([header, line])[0]


def _decision(row):
    located = L.Located(status="found", folder=Path("C:/LE/M&S/12678-01-GA"),
                        client_folder_name="M&S")
    return L.Decision(row=row, status="ready", reason="", located=located, quantities=[1, 5, 10])


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(config, "LIVE_ENQUIRY_EMAIL_ESTIMATOR", True)
    monkeypatch.setattr(config, "LIVE_ENQUIRY_EMAIL_DOMAINS", ("wearesdi.com",))
    monkeypatch.setattr(config, "LIVE_ENQUIRY_EMAIL_TO", "")


# ── reading the sheet ───────────────────────────────────────────────────────────────────

def test_the_estimator_email_column_is_read_and_the_estimator_column_kept():
    row = _row()
    assert row.estimator_email == "tony.smith@wearesdi.com" and row.estimator == "Tony"


def test_a_bare_email_header_counts():
    header = HEADER[:11] + ["E-mail"]
    assert _row(header=header).estimator_email == "tony.smith@wearesdi.com"


def test_an_address_written_in_the_estimator_column_is_found(on):
    row = _row(estimator="Dave Wright <Dave.Wright@wearesdi.com>", header=HEADER[:11])
    assert L.estimator_addresses(row) == (["dave.wright@wearesdi.com"], [])


# ── who it goes to ──────────────────────────────────────────────────────────────────────

def test_off_by_default_the_saved_list_alone_hears(monkeypatch):
    monkeypatch.setattr(config, "LIVE_ENQUIRY_EMAIL_ESTIMATOR", False)
    assert L.recipients_for(_decision(_row()), ["james.gray@wearesdi.com"]) == \
        ["james.gray@wearesdi.com"]


def test_the_switch_is_off_unless_the_env_says_on():
    import subprocess
    env = {k: v for k, v in os.environ.items() if k != "SDI_LIVE_ENQUIRY_EMAIL_ESTIMATOR"}
    out = subprocess.run([sys.executable, "-c", "import config; print(config."
                          "LIVE_ENQUIRY_EMAIL_ESTIMATOR, config.LIVE_ENQUIRY_EMAIL_DOMAINS)"],
                         cwd=str(ROOT / "src"), env=dict(env, SDI_OFFLINE="1"),
                         capture_output=True, text=True, timeout=120)
    assert out.stdout.strip().splitlines()[-1] == "False ('wearesdi.com',)"


def test_on_the_estimator_is_added_beside_the_saved_list(on):
    assert L.recipients_for(_decision(_row()), ["james.gray@wearesdi.com"]) == \
        ["james.gray@wearesdi.com", "tony.smith@wearesdi.com"]


def test_on_with_no_saved_list_the_estimator_alone_hears(on):
    assert L.recipients_for(_decision(_row()), []) == ["tony.smith@wearesdi.com"]


def test_the_same_person_is_not_sent_it_twice(on):
    row = _row(email="James.Gray@wearesdi.com")
    assert L.recipients_for(_decision(row), ["james.gray@wearesdi.com"]) == \
        ["james.gray@wearesdi.com"]


def test_an_address_outside_sdi_is_never_sent_the_estimate(on):
    row = _row(email="buyer@customer.co.uk; tony.smith@wearesdi.com")
    assert L.estimator_addresses(row) == (["tony.smith@wearesdi.com"],
                                          ["buyer@customer.co.uk"])
    assert "buyer@customer.co.uk" not in L.recipients_for(_decision(row), [])


def test_a_row_with_no_address_changes_nothing(on):
    row = _row(email="", estimator="Tony")
    assert L.recipients_for(_decision(row), ["james.gray@wearesdi.com"]) == \
        ["james.gray@wearesdi.com"]


def test_the_env_list_still_stands_in_for_the_saved_list(on, monkeypatch):
    monkeypatch.setattr(config, "LIVE_ENQUIRY_EMAIL_TO", "a@wearesdi.com, b@wearesdi.com")
    assert L.recipients_for(_decision(_row()), None) == \
        ["a@wearesdi.com", "b@wearesdi.com", "tony.smith@wearesdi.com"]


# ── what the portal is asked, and what the log says ────────────────────────────────────

class _Portal:
    def __init__(self):
        self.bodies = []

    def start(self, body):
        self.bodies.append(body)
        return {"run_id": "r1", "output_path": "C:\\out"}

    def status(self, run_id):
        return {"status": "done", "engine_price_gbp": 538.06, "deliverables": []}


def test_the_run_is_queued_with_both_and_the_log_says_who(on, tmp_path):
    portal, said = _Portal(), []
    ledger = {"schema": L.LEDGER_SCHEMA, "jobs": {}, "quantities": {}}
    row = _row(email="tony.smith@wearesdi.com, buyer@customer.co.uk")
    attempt = L.run_one(_decision(row), portal, ledger, tmp_path / "ledger.json",
                        say=said.append, sleep=lambda s: None,
                        email_to=["james.gray@wearesdi.com"])
    assert portal.bodies[0]["email_to"] == "james.gray@wearesdi.com, tony.smith@wearesdi.com"
    assert attempt["email_to"] == ["james.gray@wearesdi.com", "tony.smith@wearesdi.com"]
    text = "\n".join(said)
    assert "e-mailed when finished to james.gray@wearesdi.com, tony.smith@wearesdi.com" in text
    assert "NOT e-mailed to buyer@customer.co.uk" in text


def test_nobody_is_said_plainly(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LIVE_ENQUIRY_EMAIL_ESTIMATOR", False)
    monkeypatch.setattr(config, "LIVE_ENQUIRY_EMAIL_TO", "")
    portal, said = _Portal(), []
    ledger = {"schema": L.LEDGER_SCHEMA, "jobs": {}, "quantities": {}}
    L.run_one(_decision(_row()), portal, ledger, tmp_path / "ledger.json",
              say=said.append, sleep=lambda s: None, email_to=[])
    assert portal.bodies[0]["email_to"] is None
    assert any("e-mailed to nobody" in s for s in said)
