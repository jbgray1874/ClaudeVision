"""The answer to "what did we pay for this?" is already in the building, in four places.

WHAT PROMPTED IT. An estimator asked for a price on five bought-in mounting items from an M&S
drawing (402179-01-GA, PEAK TILL PODIA 26). The research that followed went to the public web,
established that the supplier publishes no prices at all, and recommended pulling the purchase
ledger — at which point the estimator pointed out the obvious: SDI has already ingested all of it.
1,982 historical jobs, the UDEF contract table, the bought-in catalogue and the Material Price
Break sheets. The answer had been in the database the whole time and the research had gone
outside for it.

That is worth a tool rather than an apology, because the reason nobody asks all four is that all
four take a different query with different column names, and an estimator with a drawing in front
of them is not going to write them. So the question gets answered by ringing a supplier, or by a
market guess, while a firm already-paid number sits unread.

SEARCHING BY CODE ALONE WOULD HAVE FOUND NOTHING, which is the design decision this file mostly
exists to pin. The five items are coded TP-1113, TP-1314, TP-1433, TP-1325 and TP-1205 — strings
that appear nowhere in SDI's data and nowhere on the public web, and are most likely somebody's
internal purchase reference. What travels between jobs is the WORDS: VESA, SWINGARM, ELBOW ARM,
MULTIGRIP, INGENICO. A previous till podium bought the same class of hardware and its line
description says so, whatever code was typed beside it.

AND IT MUST NOT PICK A PRICE. "We paid £46.20 on an M&S job in March" and "we paid £46.20 on a
one-off in 2019" are different facts and only an estimator can say which one governs. A tool that
returned one number would hide the context that makes the number worth anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import price_history_lookup as phl  # noqa: E402


# ── what it searches on ────────────────────────────────────────────────────────

def test_the_words_that_travel_between_jobs_survive_tokenising():
    """These are the ones a previous job's line description would carry."""
    got = set(phl._tokens("TP-1113 TECHPOLE SCREEN MOUNT WITH 300MM ELBOW ARM"))
    for word in ("TECHPOLE", "SCREEN", "MOUNT", "ELBOW"):
        assert word in got, f"{word} was dropped, and it is how this item is found"


def test_noise_is_not_searched_on():
    """A search for 'WITH' returns the catalogue, and a result set nobody reads is the same as
    no result set."""
    got = set(phl._tokens("PTP - REMOVABLE SHELF ASSY x 2 off 300mm"))
    for noise in ("WITH", "ASSY", "OFF", "MM", "300"):
        assert noise not in got


def test_a_bare_number_is_not_a_search_term():
    assert phl._tokens("402179 1113 2026") == []


# ── reading the terms off a drawing ────────────────────────────────────────────

_BOM_TEXT_ITEMS = (
    "SCREEN MOUNT WITH 300MM ELBOW ARM",
    "SWINGARM SP2 - 200MM WITH DURATILT",
    "INGENICO LANE 3000 MULTIGRIP",
    "75/100 VESA MOUNT DIA38MM",
)


def test_a_bom_yields_both_the_whole_line_and_its_words(tmp_path):
    """The row is the unit the estimator is pricing; the words are what recur. Both are needed —
    the row as written is often unique to one drawing and matches nothing, ever."""
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "bom.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((40, 60), "\n".join(_BOM_TEXT_ITEMS), fontsize=9)
    doc.save(str(pdf)); doc.close()

    terms = [t.upper() for t in phl.terms_from_bom(str(pdf))]
    assert "SWINGARM SP2 - 200MM WITH DURATILT" in terms, "the whole line is missing"
    for word in ("SWINGARM", "DURATILT", "INGENICO", "MULTIGRIP"):
        assert word in terms, f"{word} is missing, and it is the part that recurs"


def test_the_same_term_is_not_searched_twice(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "dupe.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((40, 60), "VESA MOUNT PLATE\nVESA MOUNT PLATE\nVESA MOUNT BRACKET", fontsize=9)
    doc.save(str(pdf)); doc.close()
    terms = [t.upper() for t in phl.terms_from_bom(str(pdf))]
    assert len(terms) == len(set(terms))


# ── all four sources, and none of them fatal ───────────────────────────────────

def test_every_source_we_hold_is_asked():
    src = (_ROOT / "src" / "price_history_lookup.py").read_text(encoding="utf-8")
    for table in ("UDEF_PARTS_TABLE_FOR_ESTIMATING",
                  "bought_in_parts",
                  "historical_quote_material_line"):
        assert table in src, f"{table} is not consulted, so its prices stay unread"


def test_a_missing_table_does_not_take_the_other_sources_with_it():
    """Not every machine carries every table. One absent source must cost its own answer and no
    more — otherwise a partial deployment silently returns 'nothing found' for everything."""
    class _Cur:
        def execute(self, *a, **k):
            raise RuntimeError("Invalid object name 'dbo.bought_in_parts'")
    rows = phl._rows(_Cur(), "SELECT 1", [])
    assert rows and rows[0][0] == "__error__"
    assert "Invalid object name" in rows[0][1], "the reason has to reach the reader"


def test_no_statement_writes():
    """Read-only, asserted rather than intended. This runs against the live estimating database."""
    src = (_ROOT / "src" / "price_history_lookup.py").read_text(encoding="utf-8")
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE ", "MERGE "):
        assert verb not in src.upper(), f"{verb.strip()} appears in a read-only tool"


# ── what it must not do ────────────────────────────────────────────────────────

def test_it_reports_findings_rather_than_choosing_a_price():
    """No 'best price', no average, no single number. The date, the drawing and the customer are
    what decide which historical price governs, and only a person can weigh those."""
    src = (_ROOT / "src" / "price_history_lookup.py").read_text(encoding="utf-8")
    for shortcut in ("best_price", "chosen_price", "def average", "mean(", "median("):
        assert shortcut not in src, f"{shortcut} picks a price the estimator should pick"


def test_the_history_rows_carry_the_context_that_makes_them_usable():
    src = (_ROOT / "src" / "price_history_lookup.py").read_text(encoding="utf-8")
    at = src.index("_HISTORY_SQL")
    body = src[at:src.index('"""', src.index('"""', at) + 3)]
    for column in ("quote_date", "drawing_number", "customer_name", "supplier_name"):
        assert column in body, f"without {column} a price is a number with no provenance"


def test_no_database_is_said_plainly_rather_than_returned_as_nothing_found():
    """THE FAILURE THAT WOULD MATTER MOST. An unreachable database reported as 'no history' would
    send an estimator to a supplier for a price we already hold."""
    out = phl.report({"connected": False, "error": "ModuleNotFoundError: pyodbc", "terms": []})
    assert "Could not reach" in out
    assert "nothing was searched" in out
    assert "no history" not in out.lower() and "not found" not in out.lower()


def test_nothing_found_is_offered_as_an_answer_not_a_failure():
    out = phl.report({"connected": True, "terms": [{"term": "VESA", "hits": 0,
                                                    "udef": [], "bought_in": [], "history": []}]})
    assert "Nothing found for" in out
    assert "needs a supplier quote" in out


# ── "shelves and" contains "vesa" ──────────────────────────────────────────────
#
# THE FIRST REAL RUN. Searching VESA against UDEF returned six rows and four were coincidences:
#
#     Shelf Support, Plug in, for Wooden Shel[VES A]n Elite Sourcing    £0.11
#     Shelf Support, Plug in, for Wooden Shel[VES A]n Hafele U.K. Ltd   £0.11
#     PALLET WRAP WITH COLOURED SHEL[VES A]ND RE-INFO                   £0.00
#     Shelf Support, Plug in, for Glass Shel[VES A]nd                   £0.00
#
# SQL LIKE '%VESA%' is a substring test and "shelves and" contains "vesa". A shelf support at 11p
# offered against a line for a monitor mount is worse than finding nothing: £0.11 and £35.95 are
# both plausible-looking numbers and nothing on the row says the match was an accident. This is
# the same fault class as the FIXING591 containment bug in bought_in_pricing — a containment that
# is not word-boundary aligned is not a match.
#
# The LIKE stays; it is the coarse, index-friendly filter the server does well. The word-boundary
# pass is what makes the match mean something.

@pytest.mark.parametrize("desc", [
    "Shelf Support, Plug in, for Wooden Shelvesan Elite Sourcing Solutions Ltd",
    "Shelf Support, Plug in, for Wooden Shelvesan Hafele U.K. Ltd",
    "PALLET WRAP WITH COLOURED SHELVESAND RE-INFO",
    "Shelf Support, Plug in, for Glass Shelvesand",
])
def test_shelves_and_is_not_a_vesa_mount(desc):
    """The four rows from the first run, pinned by name."""
    assert not phl._word_match("VESA", desc)


@pytest.mark.parametrize("desc", [
    "IPAD UNIT SECUTIRY MOUNT AND VESA CASE",
    "75/100 VESA MOUNT DIA38MM",
    "vesa mount, 100mm",
    "Bracket (VESA)",
])
def test_a_real_vesa_line_still_matches(desc):
    """The filter must be narrow. Losing the genuine hits to kill the noise would be a worse
    trade than the noise — the whole tool exists to find these."""
    assert phl._word_match("VESA", desc)


def test_a_multi_word_term_survives_punctuation_between_the_words():
    """A description writes it however it likes and all three mean the same part."""
    for desc in ("SCREEN MOUNT WITH 300MM ELBOW ARM", "ELBOW-ARM BRACKET", "elbow_arm"):
        assert phl._word_match("ELBOW ARM", desc), desc


def test_a_short_term_inside_a_longer_word_is_not_a_hit():
    assert not phl._word_match("ARM", "ALARM SOUNDER")
    assert phl._word_match("ARM", "SWING ARM, 200MM")


def test_the_part_code_column_is_checked_too():
    """A code is matched on its own field, not only in the description."""
    assert phl._word_match("TP-1113", "TP-1113")


def test_discarded_coincidences_are_counted_rather_than_dropped_in_silence():
    """A filter nobody is told about is its own kind of lie — and if it ever over-filters, the
    count is the only thing that would reveal it."""
    src = (_ROOT / "src" / "price_history_lookup.py").read_text(encoding="utf-8")
    assert "coincidences" in src
    assert "substring" in phl.report(
        {"connected": True,
         "terms": [{"term": "VESA", "hits": 0, "coincidences": 4,
                    "udef": [], "bought_in": [], "history": []}]}).lower()


# ── a zero is not a price ──────────────────────────────────────────────────────
#
# UDEF carries plenty of rows with no system cost — a catalogue entry that exists but was never
# priced. The first run showed four of them rendered as "£0.00" in a column beside a real £35.95:
#
#     UDEF  £0.00  PSL04-MONITOR    56 / 60 inch monitor with adjustable stand
#     UDEF  £0.00  ELEC-221         49 Video Wall LCD Monitor Set
#
# A 60-inch monitor is not free. The engine's own UDEF anchor already refuses these
# (`AND u.[System cost per] > 0`), so no estimate was ever built on one — this is purely about
# a person reading the column and taking the number at face value, which is exactly what the
# powder-at-£0.00 fault turned out to be.

def test_a_missing_price_does_not_render_as_free():
    assert phl._money(0) == "no price"
    assert phl._money(0.0) == "no price"


def test_a_real_price_is_still_money():
    assert phl._money(35.95) == "£35.95"
    assert phl._money(0.11) == "£0.11"
    assert phl._money(1827.6) == "£1,827.60"


def test_an_absent_value_is_neither():
    assert phl._money(None) == "—"
    assert phl._money("") == "—"


def test_the_discard_note_does_not_explain_one_term_with_another_terms_example():
    """It printed "'shelves and' contains 'vesa'" under a MONITOR search — true in general,
    false about the row in front of the reader. Small wrongness costs trust in the rest."""
    out = phl.report({"connected": True,
                      "terms": [{"term": "MONITOR", "hits": 1, "coincidences": 1,
                                 "udef": [("X", "Monitor Bracket", 10.0, "S", "EA")],
                                 "bought_in": [], "history": []}]})
    assert "vesa" not in out.lower()
    assert "substring" in out.lower()
