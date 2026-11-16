"""One price source failing must not end the estimate.

Job 11650's side panels died mid-run. The spreadsheet connector tried to open the price
template through Excel COM and got

    RPC_E_CALL_REJECTED -- "Call was rejected by callee"

which means Excel was busy, or had a modal dialog open, or the shell was elevated and
Excel was not. That exception propagated out of estimate_material, out of estimate_part,
out of estimate_document, and killed main.py. No estimate, no workbook, no partial answer
-- over a single price lookup with three fallbacks sitting behind it.

The waterfall exists precisely so the next source is asked. A connector that cannot answer
is a source with no candidates, not the end of the run.

RECORDED AS FAILED, NOT SKIPPED. A source that errored and a source that had nothing to
say are different facts, and the audit trail is where an estimator finds out which prices
were never even asked for.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import price_sources                                                # noqa: E402


class _ExplodingConnector:
    """A connector that fails exactly as the spreadsheet one did."""

    def is_available(self):
        return True

    def get_material_price(self, *_a, **_kw):
        raise OSError("Call was rejected by callee. (0x80010001 RPC_E_CALL_REJECTED)")


class _WorkingConnector:
    def is_available(self):
        return True

    def get_material_price(self, *_a, **_kw):
        return [{"price": 12.50, "source": "test", "currency": "GBP",
                 "unit": "per_kg", "material": "MILD_STEEL"}]


def _request():
    return price_sources.PriceRequest(
        kind="material_price", material="MILD_STEEL", thickness_mm=2.0,
        quantity=45, description="TEST PART", finish=None)


def test_a_failing_connector_does_not_raise():
    """The whole point: estimate_document must survive a dead price source."""
    out = price_sources.get_best_price(
        _request(), connectors={"spreadsheet": _ExplodingConnector()},
        source_priority=["spreadsheet"])
    assert isinstance(out, dict), "the failure escaped and would kill the run"


def test_the_next_source_is_still_asked():
    """A waterfall that stops at the first broken step is not a waterfall."""
    out = price_sources.get_best_price(
        _request(),
        connectors={"spreadsheet": _ExplodingConnector(), "udef": _WorkingConnector()},
        source_priority=["spreadsheet", "udef"])
    assert (out.get("selected") or {}).get("price") == 12.50, \
        "a working source behind a broken one never got asked"


def test_the_failure_is_recorded_as_failed_not_skipped():
    """'Errored' and 'had nothing to say' are different facts. An audit trail that
    conflates them cannot tell an estimator which prices were never asked for."""
    out = price_sources.get_best_price(
        _request(), connectors={"spreadsheet": _ExplodingConnector()},
        source_priority=["spreadsheet"])

    trail = out.get("audit_trail") or []
    entry = next((e for e in trail if e.get("source") == "spreadsheet"), None)
    assert entry is not None
    assert entry.get("status") == "failed"
    assert "RPC_E_CALL_REJECTED" in str(entry.get("reason", "")), \
        "the reason must name the actual failure, not merely that one happened"


def test_a_working_connector_is_unaffected():
    out = price_sources.get_best_price(
        _request(), connectors={"udef": _WorkingConnector()}, source_priority=["udef"])
    trail = out.get("audit_trail") or []
    entry = next((e for e in trail if e.get("source") == "udef"), None)
    assert entry and entry.get("status") == "queried"
    assert "reason" not in entry, "a clean query must not carry a failure reason"


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
