"""Prices live in a register that can be reviewed without a code edit — and today it is empty.

    "Prices are data, not hidden logic. A price must state its source, date, scope, status
     and review/expiry date. A job-specific quote must never become an automatic shared
     rate."                              — the operating rules, added 16 Sep 2026

    "A number copied from an estimator's sheet is not a price source, even as a
     'reference'. It must not be retained in the current register, documentation, reports,
     prompts, tests, or audit payloads."          — James Gray, 16 Sep 2026, later the same day

THE FIGURES WERE NUMERIC LITERALS IN config.py — a roll price, an edging rate, a plater's
quote. Each was attributed and dated, which made them honest and did not make them right.
Moving them to a register fixed where money lives; it did not fix where it CAME FROM. Every
one of them was a number off a manual estimate, and an attributed copy is still a copy: it
cannot be re-derived from anything current, so it cannot be trusted current.

So the register ships EMPTY — prices and audit record both — and stays empty until an entry
can cite a CURRENT, REPRODUCIBLE source: an SDI Live / UDEF lookup, a supplier catalogue or
API, or an identified quote document for the job in hand. What carries forward from the old
entries is the METHOD, number-free: the tape's roll length and length arithmetic, the edging
spec and its measured-length method, the knowledge that Harrods 01 is decorative plating
needing a fresh quote. The MECHANISM below is proven on synthetic entries in temp files.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import pytest                                                         # noqa: E402

import config                                                         # noqa: E402
import price_register                                                 # noqa: E402

# A synthetic, complete entry — nobody's figure — for proving the mechanism.
SYNTH_ENTRY = {
    "price_key": "SYNTH01", "label": "synthetic mechanism-test entry",
    "amount": 9.99, "unit": "each", "currency": "GBP",
    "source_type": "supplier_catalogue", "source_reference": "a test, not a sheet",
    "source_date": "2026-09-01", "review_date": "2026-12-01",
    "scope": {"kind": "material", "value": "test goods"},
    "status": "confirmed", "supersedes": None,
}


@pytest.fixture(autouse=True)
def _fresh_register():
    """The register is cached per process, and a test that points it at a tmp file must not
    leave that pointing behind it — monkeypatch restores the PATH after the body runs, which
    is too late for a cache filled during it."""
    price_register._CACHE = None
    yield
    price_register._CACHE = None


def _tmp_register(tmp_path, monkeypatch, prices=(), audit=()):
    f = tmp_path / "price_register.json"
    f.write_text(json.dumps({"prices": list(prices),
                             "historical_audit_record": list(audit)}), encoding="utf-8")
    monkeypatch.setattr(price_register, "_REGISTER_PATH", f)
    return price_register.load(refresh=True)


# ── the shipped state: empty, by rule ────────────────────────────────────────────────────

def test_the_shipped_register_holds_no_prices_and_no_audit_figures():
    """Nothing SDI holds today meets the standard, so nothing is here — not chargeable,
    not 'historical', not as an audit payload. A run cannot discover a manual-estimate
    amount because none exists to discover."""
    assert price_register.problems() == [], price_register.problems()
    assert price_register.load()["prices"] == {}
    raw = json.loads(price_register._REGISTER_PATH.read_text(encoding="utf-8"))
    assert raw["prices"] == []
    assert raw["historical_audit_record"] == []


def test_the_readme_states_the_standard():
    raw = json.loads(price_register._REGISTER_PATH.read_text(encoding="utf-8"))
    readme = " ".join(raw.get("_README") or [])
    assert "not a price source" in readme
    assert "CURRENT, REPRODUCIBLE source" in readme


def test_no_earlier_jobs_figure_is_reachable_by_any_key():
    """James Gray, 16 Sep 2026: "it must be impossible for an estimator run to read,
    display or charge it." The strongest form: the keys do not exist."""
    for key in ("HARRODS01", "PLATER_FREIGHT", "TAPE113C", "EDGE23X1ABS"):
        assert price_register.lookup(key, job=("7332-01",)) is None, key
        assert price_register.lookup(key, job=("9001-01",)) is None, key


# ── the mechanism, proven on entries nobody's sheet supplied ─────────────────────────────

def test_a_complete_entry_loads_and_prices(tmp_path, monkeypatch):
    loaded = _tmp_register(tmp_path, monkeypatch, prices=[SYNTH_ENTRY])
    assert "SYNTH01" in loaded["prices"]
    got = price_register.lookup("SYNTH01", job=("9999-99",))
    assert got["chargeable"] is True and got["amount"] == 9.99


def test_an_incomplete_price_is_refused_and_named(monkeypatch, tmp_path):
    """The one shape this register exists to prevent: a number with no date, scope or
    status is the literal it replaced, wearing a JSON file's clothes."""
    loaded = _tmp_register(tmp_path, monkeypatch,
                           prices=[{"price_key": "X", "amount": 1.0}])
    assert "X" not in loaded["prices"], "an incomplete price must not be applied"
    assert any("X:" in p and "NOT APPLIED" in p for p in loaded["problems"])


def test_a_missing_register_costs_the_run_nothing(monkeypatch, tmp_path):
    """A job must still be estimated. It falls through to the sources below, exactly as it
    does when SDI Live is unreachable — but it says so rather than failing silently."""
    monkeypatch.setattr(price_register, "_REGISTER_PATH", tmp_path / "nope.json")
    loaded = price_register.load(refresh=True)
    assert loaded["prices"] == {}
    assert loaded["problems"], "silence would be the fault"


def test_a_job_only_entry_prices_its_job_and_no_other(tmp_path, monkeypatch):
    entry = dict(SYNTH_ENTRY, price_key="SYNTHJOB",
                 scope={"kind": "job_only", "value": "1234-56"})
    _tmp_register(tmp_path, monkeypatch, prices=[entry])
    assert price_register.lookup("SYNTHJOB", job=("1234-56",))["chargeable"] is True
    other = price_register.lookup("SYNTHJOB", job=("9999-99",))
    assert other["chargeable"] is False


def test_the_audit_record_is_invisible_to_the_resolver(tmp_path, monkeypatch):
    """Whatever ends up in the audit array — and by rule no manual-estimate amount may —
    load() never reads it and lookup() can never return it."""
    _tmp_register(tmp_path, monkeypatch, prices=[],
                  audit=[dict(SYNTH_ENTRY, price_key="SYNTHAUDIT",
                              status="historical_audit_only")])
    assert price_register.load()["prices"] == {}
    assert price_register.lookup("SYNTHAUDIT", job=("1234-56",)) is None


# ── the review date is not decoration ────────────────────────────────────────────────────

def test_a_price_past_its_review_still_answers_and_says_so(monkeypatch, tmp_path):
    """Silence is worse than an old number, so it keeps pricing — and nobody may mistake
    age for agreement."""
    _tmp_register(tmp_path, monkeypatch, prices=[SYNTH_ENTRY])
    monkeypatch.setenv("SDI_REGISTER_TODAY", "2031-01-01")
    e = price_register.lookup("SYNTH01", job=("9999-99",))
    assert e["chargeable"] is True
    assert e["out_of_review"] is True
    assert "PAST ITS REVIEW DATE" in price_register.describe(e)


def test_a_price_within_review_says_nothing_extra(monkeypatch, tmp_path):
    _tmp_register(tmp_path, monkeypatch, prices=[SYNTH_ENTRY])
    monkeypatch.setenv("SDI_REGISTER_TODAY", "2026-09-16")
    assert "PAST ITS REVIEW" not in price_register.describe(
        price_register.lookup("SYNTH01", job=("9999-99",)))


# ── and the engine's consumers hold no fallback of their own ─────────────────────────────

def test_the_stated_price_waterfall_answers_nothing_shipped(monkeypatch):
    """Register empty, stated table empty: resolve() has nothing, and the lines downstream
    are withheld/awaiting price rather than filled from anywhere else."""
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: None)
    for code in ("TAPE113C", "EDGE23X1ABS", "HARRODS01", "PLATER_FREIGHT"):
        got = stated_prices.resolve(code, "")
        assert got["gbp"] is None, code


def test_the_money_has_left_config():
    """config keeps the METHOD — what the finish is and how it is priced — and nothing that
    can be charged."""
    spec = config.NAMED_PLATE_SPECS["HARRODS01"]
    assert spec["decorative"] is True and spec["requires_quote"] is True
    assert "gbp_per_unit" not in spec
    assert "last_known_quote" not in spec, "the figure belongs nowhere"
    assert config.ESTIMATOR_STATED_PRICES == {}
    edging = config.FACED_BOARD_EDGING_SPEC
    assert "gbp" not in str(sorted(edging)) and "amount" not in edging
    assert "Ostermann" in edging["supplier"]


def test_plating_asks_rather_than_reaching_for_an_earlier_jobs_figure():
    """Independence is the rule: the line asks for a current quote, every time."""
    from estimator import plating_unit_price
    for job in (("7332-01",), ("9001-01",), ()):
        unit, note, method = plating_unit_price(
            2.4, 6, config.PLATE_SUBCONTRACT_POLICY, "Harrods 01", job)
        assert unit is None, job
        assert method == "subcontract_plating_quote_needed", job
        assert "250" not in note, job
