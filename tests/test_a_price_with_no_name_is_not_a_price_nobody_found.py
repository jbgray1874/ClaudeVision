r"""
test_a_price_with_no_name_is_not_a_price_nobody_found.py

THE TWO FACTS THIS MODULE EXISTS TO KEEP APART, CONFLATED IN THE MODULE ITSELF.

"no_price_found" is a source SAYING it looked and found nothing. "" is nobody having written
a name down. _UNPRICED_SOURCES held both:

    _UNPRICED_SOURCES = frozenset({"fallback", "system_cost_not_found", "no_price_found", ""})

so an APPLIED price whose stamp recorded no source name classified as "unpriced" -- a line
reported as costing nothing while its money sat in the total. Found while writing
tools/diagnose/why_this_price.py against 11650's GBP 20.24 slider: the tool printed
`class=unpriced` beside `reached the total  True`, which cannot both be so.

It also made two branches unreachable, and they had never once run:

    classify_price_source:  if n in _UNPRICED_SOURCES: return "unpriced"
                            if not n:                  return "config"      <- dead
    source_class_of:        if not n or n in _UNPRICED_SOURCES:
                                return UNPRICED if n in _UNPRICED_SOURCES else CATALOGUE
                                                                            ^^^^^^^^^ dead

Both are documented behaviour. "config" is what the docstring promises for a rate written
into this repository; CATALOGUE is what an unnamed but real price should be. Neither could
be returned by any input, and the whole suite passed either way -- which is why this file
exists rather than a comment.

Second defect, same investigation: FIVE readers each had their own idea of where a stamp
keeps its source name. confidence.py and estimation_report.py read source_name ALONE;
estimate_parity_pretty_report and apply_pretty_report read source, then source_type, then
source_name. So one stamp was named three different things depending on which report you
opened, and a stamp written with `source` was invisible to the two that only knew
`source_name`. One accessor now, asked by everybody.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import price_provenance as pp  # noqa: E402


# ── an unnamed price is not an absent price ─────────────────────────────────────────
def test_a_priced_line_with_no_source_name_is_not_reported_as_unpriced():
    assert pp.classify_price_source(None, priced=True) != "unpriced"
    assert pp.source_class_of(None, priced=True) != pp.UNPRICED


def test_the_config_branch_is_reachable():
    """The docstring promises "config -- a rate or default written into this repository".
    With "" in the unpriced set that line could not be reached by any input at all."""
    assert pp.classify_price_source(None, priced=True) == "config"
    assert pp.classify_price_source("", priced=True) == "config"


def test_the_catalogue_branch_is_reachable():
    """source_class_of's `else CATALOGUE` was equally dead, under a guard that could only be
    entered by the value its other half already caught."""
    assert pp.source_class_of("", priced=True) == pp.CATALOGUE


def test_a_source_that_says_it_found_nothing_is_still_unpriced():
    """The fix must not go the other way. A source NAMING itself as a miss is a real fact and
    keeps its answer, whatever `priced` claims."""
    for name in ("no_price_found", "system_cost_not_found", "fallback"):
        assert pp.classify_price_source(name, priced=True) == "unpriced", name
        assert pp.source_class_of(name, priced=True) == pp.UNPRICED, name


def test_not_priced_is_still_unpriced():
    assert pp.classify_price_source(None, priced=False) == "unpriced"
    assert pp.source_class_of(None, priced=False) == pp.UNPRICED


# ── the stamp that reached the total, classified for what it is ─────────────────────
def test_an_applied_catalogue_stamp_is_not_called_unpriced():
    """The exact block that exposed this: 11650-05-02M's GBP 9.73, applied, reaching the
    total, and reported as no price at all."""
    block = {"schema": pp.PRICE_SOURCE_SCHEMA, "source": "udef_description_match",
             "applied": True, "source_type": "catalogue"}
    assert pp.stamp_affects_total(block) is True
    assert pp.stamp_source_class(block) != "unpriced", (
        "a stamp cannot both reach the total and be classified as nothing being found")


# ── one accessor, so the reports agree with each other ──────────────────────────────
@pytest.mark.parametrize("block,expected", [
    ({"source_name": "udef"}, "udef"),
    ({"source": "udef"}, "udef"),
    ({"source_type": "catalogue"}, "catalogue"),
    ({"selected": {"source": "udef"}}, "udef"),
    # Preference order: the dedicated field wins over the generic one.
    ({"source_name": "udef", "source": "web"}, "udef"),
    ({}, ""),
    (None, ""),
    ({"source_name": "   "}, ""),
])
def test_the_source_name_is_found_wherever_the_stamp_put_it(block, expected):
    assert pp.stamp_source_name(block) == expected


def _hand_rolled_source_name_chains():
    """Files that build their own `x.get("source_name") or x.get("source") or ...` fallback.

    PRECISE, BECAUSE THE LOOSE VERSION WAS USELESS. The first attempt matched any line
    mentioning `.get("source` twice and returned fifteen files, nearly all innocent --
    source_page, geometry_source, a source_type on an unrelated dict, a workbook's source
    field. A guard whose output is mostly noise gets its assertion deleted rather than its
    findings fixed.

    So: an `or` chain, over .get() calls with at least TWO DISTINCT keys drawn from the three
    a price stamp actually uses, against the SAME receiver. That is the shape that drifts,
    and nothing else is flagged.
    """
    import ast
    keys = set(pp._SOURCE_NAME_KEYS)
    offenders = []
    for path in sorted((ROOT / "src").glob("*.py")):
        if not path.is_file() or path.name == "price_provenance.py" or ".baclkup" in path.name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
                continue
            seen: dict[str, set] = {}
            for value in node.values:
                call = value.operand if isinstance(value, ast.UnaryOp) else value
                while isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                        and call.func.attr in {"lower", "upper", "strip"}:
                    call = call.func.value
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                        and call.func.attr == "get" and call.args \
                        and isinstance(call.args[0], ast.Constant) \
                        and call.args[0].value in keys:
                    seen.setdefault(ast.unparse(call.func.value), set()).add(call.args[0].value)
            if any(len(k) >= 2 for k in seen.values()):
                offenders.append(f"{path.name}:{node.lineno}")
    return sorted(set(offenders))


# The chains present when stamp_source_name was introduced. Each one is a reader that will
# disagree with the others on a stamp recording its name under a key that reader checks last
# -- which is how one price came to be named three different things in three reports. Fixing
# one means deleting its entry; a new one fails. A bare count would let a fix and a
# regression cancel out.
_KNOWN_HAND_ROLLED = {
    # source_name or source            -- misses a stamp that records only source_type
    "check_tiers.py:20", "check_tiers.py:26",
    "generate_estimate_report.py:50",
    # source or source_type            -- prefers the generic key over the dedicated one, so
    "parity_tab.py:280",               #    it disagrees with the three above on the same stamp
    "estimate_parity_pretty_report.py:203", "estimate_parity_pretty_report.py:419",
    "estimate_parity_pretty_report.py:711",
    # source_type or source_name       -- a third ordering again
    "web_ai_price_lookup.py:862", "web_ai_price_lookup.py:909",
    "estimator.py:1108",
}


def test_no_new_reader_rolls_its_own_source_name_chain():
    found = set(_hand_rolled_source_name_chains())
    new = found - _KNOWN_HAND_ROLLED
    assert not new, (
        "New hand-rolled source-name fallback(s). Call price_provenance.stamp_source_name "
        "instead, or these will disagree with every other reader on stamps that record the "
        f"name under a different key:\n  " + "\n  ".join(sorted(new)))
    stale = _KNOWN_HAND_ROLLED - found
    assert not stale, (
        "These are recorded as hand-rolled and no longer are. Delete them from "
        f"_KNOWN_HAND_ROLLED so the list stays true:\n  " + "\n  ".join(sorted(stale)))
