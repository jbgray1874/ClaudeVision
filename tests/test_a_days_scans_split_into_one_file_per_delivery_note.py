"""A day's scans become one PDF per delivery note, named for the note and the client.

James Gray, 21 September 2026: "We get a number of these each day and we want to have a
process that runs once a day and splits each delivery note out to a new folder
K:\\Logistics\\Scans\\SplitScan with a delivery note number as the file name and client name
if we can find it."

THE FIXTURE IS REAL OCR OF THE REAL SCANS. `tests/fixtures/delivery_notes/ocr_regions.json`
holds what Tesseract actually returned for each region of each of the twelve pages of the four
files sent on 21 September — including everything it got wrong. Tests run offline and in
milliseconds, and they are testing the text the machine will really be handed rather than a
tidy version of it somebody typed out.

WHAT IT GOT WRONG IS THE POINT. "Page 1 of 1" comes back as "Page Lot 1", "Pageloftl",
"Page lofi" and once as "rage ord"; TES01 as "Tes01"; MAR002 as "MAROO2"; and one page — a GB
Lift Trucks LOLER examination report, scanned upside down — is not a delivery note at all. A
fixture written by hand would have had none of that in it, and every one of those cost a
version of the reader.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "logistics"))

from delivery_note_reader import (account_code, client_name,          # noqa: E402
                                  delivery_note_number, group_into_notes,
                                  looks_like_a_delivery_note, page_position,
                                  read_page)
from split_delivery_notes import note_filename, safe_name             # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "delivery_notes" / "ocr_regions.json"
pytestmark = pytest.mark.skipif(not FIXTURE.is_file(), reason="OCR fixture not present")

PAGES = json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.is_file() else {}

# What a person reading the twelve pages sees. Transcribed from the scans themselves, not
# from the engine's output — so this is the answer being checked against, not a recording of
# whatever the code happened to produce.
EXPECTED = {
    "Delivery_Notes_21_09_2026.pdf#1": ("30022230", "Tesco"),
    "Delivery_Notes_21_09_2026.pdf#2": ("30022351", "Tesco"),
    "Delivery_Notes_21_09_2026.pdf#3": ("30022282", "Marks & Spencer"),
    "Delivery_Notes_21_09_2026.pdf#4": ("30022284", "Marks & Spencer"),
    "Delivery_Notes_21_09_2026.pdf#5": ("30022283", "Marks & Spencer"),
    "Delivery_Notes_21_09_2026.pdf#6": ("30022285", "Marks & Spencer"),
    "scan21092026_20260921131144.pdf#1": ("30022337", "Boots"),
    "scan21092026_20260921131206.pdf#1": ("30022344", "Marks & Spencer"),
    "scan21092026_20260921131206.pdf#2": ("30022349", "Marks & Spencer"),
    "scan21092026_20260921131206.pdf#3": ("30022348", "Marks & Spencer"),
    "scan21092026_20260921131206.pdf#4": ("30022346", "Marks & Spencer"),
}
NOT_A_NOTE = "scan21092026.pdf#1"


def _read(key):
    regions = PAGES[key]
    return read_page(lambda name: regions.get(name, ""))


# ── every note on the day, from the real OCR ────────────────────────────────────────

@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_every_delivery_note_is_read(key):
    """Eleven for eleven. The first two attempts managed four and three."""
    number, client = EXPECTED[key]
    found = _read(key)
    assert found["is_note"] is True
    assert found["number"] == number
    assert found["client"] == client


def test_the_page_that_is_not_a_delivery_note_is_not_treated_as_one():
    """A GB Lift Trucks LOLER examination report, upside down in the tray.

    IT HAS A REFERENCE NUMBER, A DATE AND A COMPANY ADDRESS, and every one of them would
    parse. This is why the reader asks "is this one of ours" before it reads any field: a
    delivery note filed under somebody's forklift inspection is never opened again.
    """
    found = _read(NOT_A_NOTE)
    assert found["is_note"] is False
    assert found["number"] is None
    assert found["client"] is None


def test_the_forklift_report_is_not_rescued_by_looking_harder():
    """Not merely unmatched by the field readers — refused by the gate, which is what stops
    a future change to the readers quietly promoting it."""
    assert looks_like_a_delivery_note(PAGES[NOT_A_NOTE].get("whole", "")) is False


# ── the OCR damage that each cost a version of this ─────────────────────────────────

def test_the_page_marker_survives_page_1_of_1_becoming_page_lot_1():
    """The footer is the boundary between one note and the next, and a strict
    `Page (\\d+) of (\\d+)` matches NONE of the twelve pages."""
    assert page_position("Page Lot 1") == (1, 1)
    assert page_position("Pageloftl") == (1, 1)
    assert page_position("Page lofi") == (1, 1)
    assert page_position("Page 1 of 1 |") == (1, 1)
    assert page_position("Page 2 of 3") == (2, 3)
    # And it says nothing rather than something wrong when the footer is illegible.
    assert page_position("rage ord") == (None, None)
    assert page_position("") == (None, None)


def test_an_account_code_keeps_its_letters_and_fixes_its_digits():
    """"Tes01" and "MAROO2" are the same field mis-read two different ways. Normalising the
    whole token turns TES01 into 1E501; normalising only the tail is the fix."""
    assert account_code("Account No Tes01") == "TES01"
    assert account_code("Account No MAROO2") == "MAR002"
    assert account_code("Account No BOTO1") == "BOT01"


def test_the_note_number_is_not_the_sales_order_or_the_customer_ref():
    """Three eight-digit numbers sit in the same column. The note's is the first row."""
    assert delivery_note_number("30022351\n21/09/2026\n10016225\n32206404") == "30022351"


def test_a_company_becomes_a_name_somebody_would_use_for_a_folder():
    assert client_name("Invoice Address\nTESCO STORES LIMITED\nACCTS PAYABLE") == "Tesco"
    assert client_name("Invoice Address\nBOOTS UK LIMITED") == "Boots"
    assert client_name("Invoice Address\nMarks & Spencer plc") == "Marks & Spencer"
    # The crop clips the column beside it, so a stray letter arrives after the suffix and
    # shields it: "Marks & Spencer plc E" filed as "Marks & Spencer Plc E".
    assert client_name("Invoice Address c\nMarks & Spencer plc E") == "Marks & Spencer"
    # And "ple" is what OCR makes of "plc" on half these pages.
    assert client_name("Invoice Address\nMarks & Spencer ple") == "Marks & Spencer"


def test_the_delivery_address_is_never_the_client():
    """It is the store or the carrier — "TESCO WALLYFORD EXPRESS", "Diebold Nixdorf (M&S)",
    "ECC COLLECTION" — and it changes every drop, so filing on it scatters one customer
    across a hundred names. The reader is given the invoice crop and only that."""
    for key, (_number, client) in EXPECTED.items():
        found = _read(key)
        assert found["client"] == client, key
        assert "Wallyford" not in str(found["client"])
        assert "Diebold" not in str(found["client"])


# ── grouping, and the filename ──────────────────────────────────────────────────────

def test_each_note_in_the_real_batch_becomes_its_own_file():
    key_order = [k for k in PAGES if k.startswith("Delivery_Notes")]
    pages = [_read(k) for k in sorted(key_order)]
    notes, unsorted = group_into_notes(pages)
    assert len(notes) == 6, [n["number"] for n in notes]
    assert unsorted == []
    assert [n["number"] for n in notes] == ["30022230", "30022351", "30022282",
                                            "30022284", "30022283", "30022285"]


def test_a_two_page_note_stays_one_file():
    """No note in the sample runs to two pages, so this is the case the batch cannot prove.
    A continuation carries no number of its own and joins the note above it."""
    pages = [
        {"is_note": True, "number": "30022400", "client": "Tesco", "account": "TES01",
         "page": 1, "of": 2},
        {"is_note": True, "number": None, "client": None, "account": None,
         "page": 2, "of": 2},
        {"is_note": True, "number": "30022401", "client": "Boots", "account": "BOT01",
         "page": 1, "of": 1},
    ]
    notes, unsorted = group_into_notes(pages)
    assert [n["pages"] for n in notes] == [[0, 1], [2]]
    assert unsorted == []


def test_a_page_that_is_not_ours_never_joins_the_note_above_it():
    """The forklift report sat between two delivery notes in the day's tray."""
    pages = [
        {"is_note": True, "number": "30022400", "client": "Tesco", "account": "TES01",
         "page": 1, "of": 1},
        {"is_note": False, "number": None, "client": None, "account": None,
         "page": None, "of": None},
        {"is_note": True, "number": "30022401", "client": "Boots", "account": "BOT01",
         "page": 1, "of": 1},
    ]
    notes, unsorted = group_into_notes(pages)
    assert [n["pages"] for n in notes] == [[0], [2]]
    assert unsorted == [1]


def test_the_filename_is_the_number_then_the_client():
    assert note_filename({"number": "30022230", "client": "Tesco"}, "x") == \
        "30022230 Tesco.pdf"
    # No client read — the number alone, never a guess.
    assert note_filename({"number": "30022230", "client": None}, "x") == "30022230.pdf"
    # No number either — it is not filed as a delivery note at all.
    assert note_filename({"number": None, "client": "Tesco"}, "scan p3") == "scan p3.pdf"


def test_a_filename_cannot_break_windows():
    """A client name comes off a scan, so it can contain anything OCR imagines."""
    assert safe_name('Marks & Spencer plc <"/\\|?*>') == "Marks & Spencer plc"
    assert safe_name("Trailing dot.") == "Trailing dot"
    assert safe_name("  spaced  out  ") == "spaced out"


# ── running it as often as you like ─────────────────────────────────────────────────

def test_a_note_already_on_the_share_is_recognised_by_its_number(tmp_path):
    """James Gray, 21 September 2026: "We can run as often as we want but how do we make sure
    it doesn't re generate the same individual invoices again over and over?"

    ASKED OF THE FOLDER, NOT OF A RECORD ABOUT THE FOLDER. A note is already done when a file
    for it is sitting there — the same question a person answers by looking — so the answer
    cannot drift from what is actually on the share.

    Matched on the NUMBER, so a note re-scanned on a day when the client line reads
    differently is still recognised as the same note rather than filed twice.
    """
    from split_delivery_notes import already_filed
    (tmp_path / "30022230 Tesco.pdf").write_bytes(b"%PDF-1.4\n")
    assert already_filed(tmp_path, "30022230") is not None
    # Same note, a different reading of the client line.
    assert already_filed(tmp_path, "30022230") is not None
    assert already_filed(tmp_path, "30022231") is None
    assert already_filed(tmp_path, None) is None


def test_a_number_is_not_matched_by_a_longer_one(tmp_path):
    """3002223 must not be answered by 30022230's file."""
    from split_delivery_notes import already_filed
    (tmp_path / "30022230 Tesco.pdf").write_bytes(b"%PDF-1.4\n")
    assert already_filed(tmp_path, "3002223") is None


def test_a_deleted_note_comes_back_and_the_rest_do_not_move(tmp_path, monkeypatch):
    """THE FAILURE A SEPARATE RECORD HAS AND THE FOLDER DOES NOT.

    Skipping a scan that has not changed is a speed decision — re-OCRing forty unchanged
    pages is minutes of nothing — but a ledger that is simply believed means a note somebody
    deleted never comes back. The skip verifies its own claim against the share.
    """
    import split_delivery_notes as S

    calls = []

    def _fake_split(pdf, out_dir, dry_run=False):
        calls.append(pdf.name)
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"{pdf.stem}-note.pdf"
        (out_dir / name).write_bytes(b"%PDF-1.4\n")
        return {"source": pdf.name, "pages": 1, "unsorted": [],
                "notes": [{"file": name, "written": True, "path": str(out_dir / name),
                           "number": "30022230", "client": "Tesco", "account": "TES01",
                           "pages": [1], "already": False}]}

    monkeypatch.setattr(S, "split_pdf", _fake_split)
    source, out = tmp_path / "in", tmp_path / "out"
    source.mkdir()
    (source / "scan.pdf").write_bytes(b"%PDF-1.4\n")

    S.run(source, out)
    assert calls == ["scan.pdf"]

    S.run(source, out)
    assert calls == ["scan.pdf"], "an unchanged scan was read again"

    (out / "scan-note.pdf").unlink()
    S.run(source, out)
    assert calls == ["scan.pdf", "scan.pdf"], "a deleted note did not come back"
    assert (out / "scan-note.pdf").exists()
