"""Prices live in a register that can be reviewed without a code edit.

    "Prices are data, not hidden logic. A price must state its source, date, scope, status
     and review/expiry date. A job-specific quote must never become an automatic shared
     rate."                              — the operating rules, added 16 Sep 2026

THE FIGURES WERE NUMERIC LITERALS IN config.py — the tape's roll at £4.50, Tony's edging at
£0.35/m, a plater's £250. Each was attributed and dated, which made them honest and did not
make them right. Three things follow from money living in source:

  * changing a rate is a CODE change, so a commercial decision needs an engineer;
  * nothing carries an EXPIRY, so a figure is as loud on the day it goes stale as on the day
    it was given, and age becomes indistinguishable from agreement;
  * a job's quote and a shop's standing rate look identical in the file — which is how £250
    for one stand came to be chargeable on every job whose drawing named the same finish.

So the money moved to data/price_register.json and the engine kept the MECHANISM. The same
£250 is now this job's confirmed quote on 7332-01 and a labelled comparator anywhere else,
from ONE entry, because scope carries the restriction and status carries the firmness.
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import pytest                                                         # noqa: E402

import config                                                         # noqa: E402
import price_register                                                 # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_register():
    """The register is cached per process, and a test that points it at a tmp file must not
    leave that pointing behind it — monkeypatch restores the PATH after the body runs, which
    is too late for a cache filled during it."""
    price_register._CACHE = None
    yield
    price_register._CACHE = None


def test_the_register_is_readable_and_complete():
    """Every entry must say what it is, where it came from, when that was current, what it
    may price and how firm it is. A problem here is a price NOT APPLIED, so it must be
    empty on a healthy tree."""
    assert price_register.problems() == [], price_register.problems()
    assert price_register.load()["prices"], "the register must not be empty"


def test_every_entry_carries_every_field_the_policy_demands():
    for key, entry in price_register.load()["prices"].items():
        for field in price_register.REQUIRED_FIELDS:
            assert entry.get(field) not in (None, ""), (key, field)
        assert entry["status"] in price_register.STATUSES, (key, entry["status"])
        assert isinstance(entry["scope"], dict) and entry["scope"].get("kind"), key


def test_an_incomplete_price_is_refused_and_named(monkeypatch, tmp_path):
    """The one shape this register exists to prevent: a number with no date, scope or
    status is the literal it replaced, wearing a JSON file's clothes."""
    bad = tmp_path / "price_register.json"
    bad.write_text('{"prices": [{"price_key": "X", "amount": 1.0}]}', encoding="utf-8")
    monkeypatch.setattr(price_register, "_REGISTER_PATH", bad)
    loaded = price_register.load(refresh=True)
    assert "X" not in loaded["prices"], "an incomplete price must not be applied"
    assert any("X:" in p and "NOT APPLIED" in p for p in loaded["problems"])


def test_a_missing_register_costs_the_run_nothing(monkeypatch, tmp_path):
    """A job must still be estimated. It falls through to the sources below, exactly as it
    does when SDI Live is unreachable — but it says so rather than failing silently."""
    monkeypatch.setattr(price_register, "_REGISTER_PATH", tmp_path / "nope.json")
    loaded = price_register.load(refresh=True)
    assert loaded["prices"] == {}
    assert loaded["problems"], "silence would be the fault"


# ── scope carries the restriction, status carries the firmness ───────────────────────────

def test_an_earlier_jobs_quote_is_not_in_the_resolver_at_all():
    """THE RULE, and it is stronger than scoping. James Gray, 16 Sep 2026: "it should not
    appear in a new estimate at all — not as a charge, fallback, comparator, workbook note
    or suggested value… it must be impossible for an estimator run to read, display or
    charge it." Labelling it was not enough; a figure on the line is a figure somebody
    accepts. So it is not a price here — it is an audit record the resolver cannot see."""
    assert price_register.lookup("HARRODS01", job=("7332-01",)) is None
    assert price_register.lookup("HARRODS01", job=("9001-01",)) is None
    assert "HARRODS01" not in price_register.load()["prices"]


def test_the_audit_record_keeps_it_and_the_resolver_never_reads_it():
    """Not deleted — a figure somebody once quoted should not be lost to the audit trail.
    Kept where nothing that prices can reach it."""
    import json
    raw = json.loads(pathlib.Path(price_register._REGISTER_PATH).read_text(encoding="utf-8"))
    audit = {e["price_key"]: e for e in raw.get("historical_audit_record") or []}
    assert audit["HARRODS01"]["amount"] == 250.00
    assert audit["HARRODS01"]["status"] == "historical_audit_only"
    # and load() builds `prices` from the prices array alone
    assert set(price_register.load()["prices"]) == {"TAPE113C", "EDGE23X1ABS",
                                                    "PLATER_FREIGHT"}


def test_a_material_scoped_price_prices_any_job():
    """Only `job_only` narrows by job. A material rate is about the material."""
    for key in ("TAPE113C", "EDGE23X1ABS"):
        assert price_register.lookup(key, job=("9999-99",))["chargeable"] is True, key


# ── the review date is not decoration ────────────────────────────────────────────────────

def test_a_price_past_its_review_still_answers_and_says_so(monkeypatch):
    """Silence is worse than an old number, so it keeps pricing — and nobody may mistake
    age for agreement."""
    monkeypatch.setenv("SDI_REGISTER_TODAY", "2031-01-01")
    e = price_register.lookup("TAPE113C", job=("9999-99",))
    assert e["chargeable"] is True
    assert e["out_of_review"] is True
    assert "PAST ITS REVIEW DATE" in price_register.describe(e)


def test_a_price_within_review_says_nothing_extra(monkeypatch):
    monkeypatch.setenv("SDI_REGISTER_TODAY", "2026-09-16")
    assert "PAST ITS REVIEW" not in price_register.describe(
        price_register.lookup("TAPE113C", job=("9999-99",)))


# ── and the engine reads it ──────────────────────────────────────────────────────────────

def test_the_stated_price_waterfall_reads_the_register():
    import stated_prices
    got = stated_prices.resolve("EDGE23X1ABS", "ABS edging for faced board")
    assert got["gbp"] == 0.35
    assert "Tony Ford" in got["label"]


def test_a_job_only_price_never_enters_the_shared_waterfall():
    """stated() answers "what does this code cost on ANY job", and a quote given for one job
    is not an answer to that question."""
    import stated_prices
    assert "HARRODS01" not in stated_prices._cfg()


def test_the_money_has_left_config():
    """config keeps the METHOD — what the finish is and how it is priced — and nothing that
    can be charged."""
    spec = config.NAMED_PLATE_SPECS["HARRODS01"]
    assert spec["decorative"] is True and spec["requires_quote"] is True
    assert "gbp_per_unit" not in spec
    assert "last_known_quote" not in spec, "the figure belongs in the register, not here"


def test_plating_asks_rather_than_reaching_for_an_earlier_jobs_figure():
    """The register prices what it holds — and it deliberately holds no plating price, so
    the line asks. Scoping was the fix before this one; independence is the rule now."""
    from estimator import plating_unit_price
    for job in (("7332-01",), ("9001-01",), ()):
        unit, note, method = plating_unit_price(
            2.4, 6, config.PLATE_SUBCONTRACT_POLICY, "Harrods 01", job)
        assert unit is None, job
        assert method == "subcontract_plating_quote_needed", job
        assert "250" not in note, job
