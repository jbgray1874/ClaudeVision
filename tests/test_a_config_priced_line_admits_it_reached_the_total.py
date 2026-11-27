r"""
test_a_config_priced_line_admits_it_reached_the_total.py

THE STAMP WAS TELLING THE TRUTH ABOUT ONE QUESTION AND BEING READ FOR ANOTHER.

Chasing 11650-05-02M SLIDER's GBP 9.73, the diagnostic printed:

    material_estimate.price_source
      source        config_default_material_rates
      reproducible  False    reached the total  False

and the money was in the total. Twice that sent the investigation down the wrong path -- the
tool printed exactly what the stamp said, and what the stamp said was not true.

estimator builds that stamp with  applied = applied_price_per_kg is not None, where
applied_price_per_kg is the EXTERNAL lookup. A part priced from config's
MATERIAL_PRICE_GBP_PER_KG therefore has applied=False and a real cost. price_provenance's
stamp_affects_total has no affects_total to read on that stamp, so it falls back to
`applied` -- and reports every config-priced material line as money that never landed.

Two questions, one field: "where did the RATE come from" and "did this line get a price".
They are now separate. `applied` keeps its meaning; affects_total is stated outright.

This is not cosmetic. invariants and the reports read affects_total to decide what reached
the estimate, so a whole class of priced line was invisible to them -- and any future check
asking "what money is on this job" would have missed it.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import price_provenance as pp  # noqa: E402


def test_a_stamp_with_no_verdict_still_falls_back_to_applied():
    """Unchanged behaviour for older documents, and the reason the bug was invisible."""
    assert pp.stamp_affects_total({"applied": True}) is True
    assert pp.stamp_affects_total({"applied": False}) is False


def test_an_explicit_verdict_wins_over_applied():
    """The whole point: a line priced from a config fallback has applied False and money in
    the total, and only an explicit affects_total can say so."""
    assert pp.stamp_affects_total({"applied": False, "affects_total": True}) is True
    assert pp.stamp_affects_total({"applied": True, "affects_total": False}) is False


def _material_stamp_call() -> ast.Call:
    """The _build_price_source_metadata call that builds material_estimate.price_source."""
    tree = ast.parse((ROOT / "src" / "estimator.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_build_price_source_metadata"):
            continue
        kw = {k.arg: ast.unparse(k.value) for k in node.keywords}
        if "config_default_material_rates" in (kw.get("fallback_source") or ""):
            return node
    pytest.fail("the material price stamp is no longer built in a recognisable way")


def test_the_material_stamp_states_whether_the_money_landed():
    node = _material_stamp_call()
    kw = {k.arg: ast.unparse(k.value) for k in node.keywords}
    assert "affects_total" in kw, (
        "the material stamp does not say whether its figure reached the total, so "
        "stamp_affects_total falls back to `applied` -- which on this stamp means 'an "
        "EXTERNAL lookup supplied the rate' and is False for every config-priced line.")
    assert kw["affects_total"] != kw.get("applied"), (
        "affects_total has been set to the same expression as applied, which reintroduces "
        "the collision: one field answering two different questions.")
    assert "material_cost" in kw["affects_total"], (
        "whether the money landed is whether a figure exists for this line -- "
        "material_cost is not None -- not where its rate came from")


def test_applied_still_means_where_the_rate_came_from():
    """The fix must not redefine `applied`. Reports read it to say whether a real lookup
    priced the line, which is a different and still-useful fact."""
    kw = {k.arg: ast.unparse(k.value) for k in _material_stamp_call().keywords}
    assert "applied_price_per_kg" in kw.get("applied", ""), \
        "`applied` no longer reports whether an external rate was applied"
