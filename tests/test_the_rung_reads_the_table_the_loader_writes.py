"""Rung 3 read one table. The only thing that fills it wrote to another.

    supplier_price_list.py -> catalogue_loader.upsert_catalogue
                           -> INSERT INTO AIEstimating.BoughtInCatalogue

    pricing_service._get_bought_in_part
                           -> SELECT ... FROM dbo.bought_in_parts WHERE is_active = 1

A migration moved the catalogue and set every migrated row inactive, so the old table returns
nothing and the new one is never read. Which means: email Elite, Eagle and Thermaset, get all
three files, ingest them cleanly, `--commit` — and every price still falls straight past rung
3 into text-matched history, exactly as it does today. No error. The work feels finished and
changes nothing.

That is why this test exists rather than a comment. Two files, 400 lines apart, agreeing about
a table name by coincidence.

AND THE ROWS WERE NOT ALL PRICES. Inspecting the successor before repointing found four kinds
of number sitting together:

    migrated:dbo.bip                    real net, carried from the old table
    web_indicative:20260614             A WEB GUESS                          (19 rows)
    rag_fallback:workbook:11087-17-GA   lifted from one historical workbook
    sdi_estimate:20260614               our own estimate
    parallel-run:12479 ? UNCONFIRMED    and this one at GBP 0.0000

Rung 3 answers at 0.93 for an exact code, 0.80 otherwise — above historical comparables, and
far above the 0.68 ceiling the web/LLM rung is deliberately capped at. Repointing without a
filter would have taken the same web guess that is capped at 0.68 through one rung and served
it at 0.80 through another. The ceiling would still be in the code and would mean nothing.

So the allowlist is as load-bearing as the table name, and both are pinned here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PRICING = (_ROOT / "src" / "pricing_service.py").read_text(encoding="utf-8")
_LOADER = (_ROOT / "src" / "catalogue_loader.py").read_text(encoding="utf-8")


def _rung_three() -> str:
    at = _PRICING.index("def _get_bought_in_part")
    return _PRICING[at:_PRICING.index("def _get_supplier_catalog", at)]


def _rung_three_code() -> str:
    """The rung with its commentary blanked.

    The comment above the query explains which table it USED to read, so a search for the
    dead name matches the explanation of why it is dead. That is the seventh time in this
    suite a text search has been fooled by prose about the thing it was searching for, and
    the pattern is always the same: the more carefully a change is documented, the more
    likely a naive search matches the documentation.
    """
    return "\n".join(" " * len(ln) if ln.lstrip().startswith("#") else ln
                     for ln in _rung_three().splitlines())


def _table(sql: str) -> str | None:
    m = re.search(r"(?:FROM|INTO)\s+([A-Za-z_][\w.]*)", sql)
    return m.group(1) if m else None


# ── the two halves name the same table ───────────────────────────────────────

def test_the_rung_reads_where_the_loader_writes():
    """THE ASSERTION. Not that either name is right — that they are the SAME name."""
    at = _LOADER.index("INSERT INTO AIEstimating.BoughtInCatalogue")
    written = _table(_LOADER[at:at + 80])
    code = _rung_three_code()
    read = _table(code[code.index("SELECT TOP 1"):])
    assert read == written, (
        f"the price chain reads {read} and every price file is written to {written}. "
        f"Loading a supplier's list would change nothing, and nothing would say so.")


def test_the_dead_table_is_not_read_any_more():
    """dbo.bought_in_parts has no active rows — the migration set them all inactive. A rung
    pointed at it is a rung that always returns None."""
    assert "dbo.bought_in_parts" not in _rung_three_code(), (
        "rung 3 still reads the table the migration emptied")


# ── only prices we actually pay ──────────────────────────────────────────────

def test_only_firm_sources_can_answer_at_this_rung():
    """A web guess served here at 0.80 outranks the historical evidence beneath it and beats
    the 0.68 cap it would have been given one rung down. The cap has to mean something."""
    body = _rung_three()
    assert "_FIRM_CATALOGUE_SOURCES" in body, (
        "rung 3 accepts any row in the catalogue, including web_indicative and rag_fallback")
    assert "source LIKE ?" in body.replace("c.source", "source"), (
        "the source is not actually constrained in the query")


def test_the_allowlist_holds_only_things_somebody_paid():
    allowed = re.search(r"_FIRM_CATALOGUE_SOURCES = \((.*?)\)", _PRICING, re.S)
    assert allowed, "_FIRM_CATALOGUE_SOURCES not found"
    entries = set(re.findall(r'"([^"]+)"', allowed.group(1)))
    assert entries == {"migrated:", "supplier_file:"}, (
        f"the allowlist is {sorted(entries)} — every entry must be a price a supplier or an "
        f"invoice actually stated, not one this system worked out for itself")
    for indicative in ("web_indicative", "rag_fallback", "sdi_estimate", "parallel-run"):
        assert indicative not in allowed.group(1), (
            f"{indicative} is an indication, and this rung reports firm prices")


def test_it_is_an_allowlist_and_not_a_denylist():
    """A denylist admits the next indicative source somebody adds, silently. A missing
    allowlist entry shows up as a rung that answers nothing, which somebody notices."""
    body = _rung_three_code()
    assert "NOT LIKE" not in body.upper(), (
        "the source filter excludes named sources instead of admitting named ones")


def test_a_zero_is_still_not_a_price():
    """There is a GBP 0.0000 row in that table right now, marked PRICE UNCONFIRMED. Excluded
    in SQL as well as in Python: TOP 1 could otherwise select the zero and return None, when a
    real row for the same part existed underneath it."""
    body = _rung_three()
    assert "unit_price_gbp > 0" in body.replace("c.unit_price_gbp", "unit_price_gbp"), (
        "a zero row can be selected by TOP 1 and mask a real price beneath it")
    assert "if price <= 0" in body, "the Python guard has gone"


# ── the row it returns still describes itself ────────────────────────────────

def test_the_rung_key_is_unchanged_because_other_things_key_off_it():
    """"bought_in_parts" names the RUNG, not the table. The parity report, the provenance
    icons and the sources audit all match on that string."""
    assert '"source": "bought_in_parts"' in _rung_three()


def test_the_provenance_names_the_table_that_was_actually_read():
    """Otherwise somebody goes looking for the row in the empty table and concludes the
    engine invented it."""
    body = _rung_three()
    assert "AIEstimating.BoughtInCatalogue" in body[body.index('"provenance"'):], (
        "the provenance line does not say which table the price came from")


def test_the_unit_comes_back_with_the_price():
    """After c2222e9 the catalogue stores a real unit. A price of 60.43 means nothing without
    knowing it is per SHEET — and there are rows in there priced per sheet, per metre and
    per kg today."""
    body = _rung_three()
    assert "uom" in body, "the rung drops the unit, so a per-sheet price reads as per-each"


# ── the historical rung is not ordered by a corrupt column ───────────────────
#
# dbo.historical_quote_material_line.line_total_gbp is unit_price multiplied by something
# that is not a quantity:
#
#     unit £    line_total_gbp        implied "qty"
#     1.8568    481,025,690,167.31    259,061,659,935
#     5.0000    410,759,110,550.00     82,151,822,110
#    17.2500        126,802,059.00          7,350,844   <- a PART NUMBER. 7350845 is a
#                                                          lens cover in our own catalogue.
#
# It never becomes a price — the price is unit_price_gbp, which is sane — and no other
# module reads the key. But it was the ONLY sort key on the fallback fetch, so it decided
# which comparables were CONSIDERED before token scoring ran. A candidate that is never
# fetched cannot be scored, and nothing downstream could tell it had been passed over.

def _historical() -> str:
    at = _PRICING.index("def _get_historical_rag")
    end = _PRICING.index("def _get_bought_in_part", at)
    return "\n".join(" " * len(ln) if ln.lstrip().startswith(("#", "--")) else ln
                     for ln in _PRICING[at:end].splitlines())


def test_no_comparable_is_chosen_by_a_column_that_holds_a_part_number():
    """THE ASSERTION. Not that the column is fixed — it is not, and fixing it is a database
    job — but that nothing in the price chain ranks on it."""
    body = _historical()
    assert "line_total_gbp" not in body.split("ORDER BY", 1)[-1] or \
           "COALESCE(hml.line_total_gbp" not in body, (
        "the historical rung still orders by line_total_gbp, so its comparables are ranked "
        "by part-code magnitude")
    for bad in ("COALESCE(line_total_gbp, 0) DESC", "COALESCE(hml.line_total_gbp, 0) DESC"):
        assert bad not in body, f"still ordering by the corrupt column: {bad}"


def test_the_fallback_fetch_sorts_by_recency_like_the_primary_one():
    """It had no header join at all, so it could not sort by date even if it wanted to. Two
    queries answering the same question by different rules is how they drift."""
    body = _historical()
    fallback = body[body.index("SELECT TOP (?)"):]
    assert "historical_quote_header" in fallback, (
        "the fallback fetch still cannot see a quote date")
    assert "hh.quote_date DESC" in fallback, (
        "the fallback does not prefer recent quotes, which is what freshness already values")


# ── the guard refuses, rather than merely being present ──────────────────────
#
# Everything above reads source text, which pins intent and cannot prove behaviour. These
# two drive the actual code paths with the row that is wrong in the live table today:
#
#     FIXING1784  Edging Seal Strip 10m Roll (Rubusec)  uom=metre  £29.80
#
# £29.80 is the roll. Two metres of edging costs £59.60 instead of £5.96. Delete the guard
# and these fail; weaken it to a warning and these fail.

import sys                                                          # noqa: E402
sys.path.insert(0, str(_ROOT / "src"))


def _service():
    """A service with a stub connection.

    PricingService opens one in __init__ unless it is handed one, and pyodbc is not installed
    here. Every query below is monkeypatched, so the object only has to be truthy — the point
    of these tests is the decision the rung makes about a row, not how the row was fetched.
    """
    from pricing_service import PricingService                      # noqa: PLC0415
    return PricingService(conn=_FakeConn())


_BAD_ROW = ("FIXING1784", "Edging Seal Strip 10m Roll (Rubusec)", 29.80, "Rubusec", "metre")
_GOOD_ROW = ("FIXING636", "No.8 x 16mm Pan Head Wood Screw Pozi", 0.03, "Elite", "each")


def test_rung_three_refuses_the_row_that_is_wrong_by_ten(monkeypatch):
    """THE ASSERTION, driven not asserted. The migration wrote this row years before the
    loader existed, so a guard only the importer runs could never have caught it."""
    svc = _service()
    monkeypatch.setattr(svc, "_fetch_one_with_retry", lambda *a, **k: _BAD_ROW)
    out = svc._get_bought_in_part({"part_number": "FIXING1784", "description": "edging strip"})
    assert out is None, (
        "rung 3 served a roll price as a metre price — every line using it is out by 10x")


def test_the_refusal_is_visible_and_names_the_row_to_fix():
    """A silent fall-through looks exactly like an empty catalogue, and would send somebody
    chasing price files that are already loaded."""
    svc = _service()
    svc._fetch_one_with_retry = lambda *a, **k: _BAD_ROW           # noqa: SLF001
    svc._get_bought_in_part({"part_number": "FIXING1784", "description": "edging strip"})
    notes = " ".join(svc.catalogue_quarantine)
    assert "FIXING1784" in notes, "the quarantined row is not named"
    assert "BoughtInCatalogue" in notes, "nothing says where to correct it"


def test_a_healthy_row_still_prices(monkeypatch):
    """The half that decides whether this survives contact with a real job. A guard that
    also refuses good rows empties the rung it was added to protect."""
    svc = _service()
    monkeypatch.setattr(svc, "_fetch_one_with_retry", lambda *a, **k: _GOOD_ROW)
    out = svc._get_bought_in_part({"part_number": "FIXING636", "description": "wood screw"})
    assert out and out["unit_price_gbp"] == pytest.approx(0.03)
    assert out["confidence"] == pytest.approx(0.93), "an exact code match lost its confidence"
    assert svc.catalogue_quarantine == [], "a healthy row was quarantined"


def test_the_loader_will_not_write_another_one(monkeypatch):
    """FIXING1784 entered the table by this route. Elite's file is the first one large enough
    for that to happen at scale without anybody reading every row."""
    import catalogue_loader as cl                                   # noqa: PLC0415
    import supplier_price_list as spl                               # noqa: PLC0415

    written = []
    monkeypatch.setattr(cl, "connect", lambda: _FakeConn())
    monkeypatch.setattr(cl, "upsert_catalogue",
                        lambda cur, line, source, today: written.append(line) or "insert x")

    parsed = {"rows": [
        {"description": "Edging Seal Strip 10m Roll (Rubusec)", "unit": "metre",
         "net_gbp": 29.80, "supplier": "Rubusec", "class": "edging",
         "their_sku": "FIXING1784", "our_sku": ""},
        {"description": "No.8 x 16mm Pan Head Wood Screw Pozi", "unit": "each",
         "net_gbp": 0.03, "supplier": "Elite", "class": "fixing",
         "their_sku": "FIXING636", "our_sku": ""},
    ]}
    out = spl.commit(parsed, source_label="supplier_file:test.xlsx")
    assert len(written) == 1, "the conflicting row was written to the catalogue"
    assert written[0]["description"].startswith("No.8"), "the wrong row was kept"
    assert out["refused"] and "FIXING1784" in out["refused"][0]


def test_it_can_still_be_overridden_by_somebody_who_checked(monkeypatch):
    """The supplier may confirm the file is right and the checker is being conservative. That
    has to be possible — and it has to be typed on the run that writes, so the record shows a
    person decided rather than that nobody looked."""
    import catalogue_loader as cl                                   # noqa: PLC0415
    import supplier_price_list as spl                               # noqa: PLC0415

    written = []
    monkeypatch.setattr(cl, "connect", lambda: _FakeConn())
    monkeypatch.setattr(cl, "upsert_catalogue",
                        lambda cur, line, source, today: written.append(line) or "insert x")
    parsed = {"rows": [
        {"description": "Edging Seal Strip 10m Roll (Rubusec)", "unit": "metre",
         "net_gbp": 29.80, "supplier": "Rubusec", "class": "edging",
         "their_sku": "FIXING1784", "our_sku": ""}]}
    spl.commit(parsed, source_label="supplier_file:test.xlsx", allow_unit_conflicts=True)
    assert len(written) == 1, "the override does not work, so a correct file cannot be loaded"


class _FakeConn:
    def cursor(self):
        return self

    def commit(self):
        pass

    def close(self):
        pass
