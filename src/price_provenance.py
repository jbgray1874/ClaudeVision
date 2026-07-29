"""
price_provenance.py — one answer to "where did this price come from, and would it come
back the same tomorrow?"

WHY THIS EXISTS. Job 12120 priced three times on identical inputs at GBP 27.67, GBP 29.39
and GBP 32.86. Labour was identical to the penny every run and the steel never moved. Three
bought-in codes missed in SQL every time, fell through the catalogue chain, and were answered
by an AI market estimate — the screen cable came back at GBP 4.54, then GBP 6.00, then
GBP 8.54. Every one of those runs reconciled perfectly: rows to subtotals, subtotals to the
unit price. The engine was internally consistent and externally unrepeatable.

An AI estimate filling a catalogue gap is defensible. What is not defensible is that it
arrived on the sheet stamped `source_type: "external"` — the same word a SQL catalogue hit
carries — so nothing downstream could tell a looked-up price from a guessed one.

This module is the single place that decides. It is deliberately dependency-free (no config,
no database, no connectors) so that the estimator, the pricing service and the invariants can
all import it and reach the same verdict about the same source. It classifies by what the
source IS, never by part number, description or job — a code added to the catalogue next week
is reproducible for the same reason THUM620 is not today.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, Optional, Tuple

# Every price stamp built through this module carries this marker. Consumers find priced
# lines by looking for the marker rather than by knowing where in a part a price is stored,
# so a block added to a new part shape is checked without the checker being taught about it.
PRICE_SOURCE_SCHEMA = "price_source.v1"

# Sources that answer a different number when asked the same question twice. These are
# generative or search-backed lookups, not catalogues.
NON_REPRODUCIBLE_SOURCES = frozenset({
    "llm_market_estimate",
    "web_ai_fallback",
    "web_ai_llm_estimate",
    "ai_market_estimate",
    "web_search",
    "web",
})

# Name fragments, for sources this list has not met yet. A connector named
# "openai_price_probe" or "grok_market" should be caught the day it is written, not the day
# someone remembers to add it above.
_NON_REPRODUCIBLE_TOKENS = (
    "llm", "web_ai", "ai_estimate", "ai_market", "market_estimate",
    "generative", "gpt", "grok", "claude_estimate",
)

# A price nobody found. Distinct from a guessed one: an unpriced line is honestly empty.
_UNPRICED_SOURCES = frozenset({"fallback", "system_cost_not_found", "no_price_found", ""})


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def is_non_reproducible_source(*names: Any) -> bool:
    """True when ANY of the supplied identifiers names a source that cannot answer twice.

    Several identifiers are accepted because the same fact reaches us under different keys
    depending on the path — `source`, `source_type`, `pricing_mode`. Requiring the caller to
    pick the right one is how an LLM estimate came to be labelled "external": the first key
    was populated and truthy, so the informative one was never read.
    """
    for name in names:
        n = _norm(name)
        if not n:
            continue
        if n in NON_REPRODUCIBLE_SOURCES:
            return True
        if any(token in n for token in _NON_REPRODUCIBLE_TOKENS):
            return True
    return False


def classify_price_source(
    source_name: Any = None,
    *,
    source_type: Any = None,
    pricing_mode: Any = None,
    priced: bool = True,
) -> str:
    """One word for what kind of thing produced this price.

        ai_estimate  — generated on demand; will differ next run
        web_catalog  — a real listing, fetched live; may move, but it is a quoted price
        catalogue    — a database or workbook row; the same input gives the same output
        config       — a rate or default written into this repository
        unpriced     — nothing was found
    """
    if not priced:
        return "unpriced"
    n = _norm(source_name)
    if is_non_reproducible_source(source_name, source_type, pricing_mode):
        # "web" alone is the connector, not the method: it serves both live listings and LLM
        # estimates. Only the LLM mode makes it unrepeatable, so a plain web catalogue hit is
        # not condemned by the connector's name.
        if n == "web" and not is_non_reproducible_source(source_type, pricing_mode):
            return "web_catalog"
        return "ai_estimate"
    if n in _UNPRICED_SOURCES:
        return "unpriced"
    if not n:
        return "config"
    return "catalogue"


def is_reproducible(
    source_name: Any = None,
    *,
    source_type: Any = None,
    pricing_mode: Any = None,
    priced: bool = True,
) -> bool:
    """Would this price come back the same tomorrow, given the same inputs?

    An unpriced line counts as reproducible: "no price found" is a stable answer, and it is
    already visible as a gap. Only a number that moves on its own is the problem here.
    """
    return classify_price_source(
        source_name, source_type=source_type, pricing_mode=pricing_mode, priced=priced
    ) != "ai_estimate"


def _looks_like_price_stamp(node: Dict[str, Any]) -> bool:
    """Recognise a price stamp that predates the schema marker.

    A job JSON written before this module existed carries the same block shape without the
    marker. Recognising it by shape means the checks work on estimates already on disk,
    instead of reporting "nothing to look at" — which is the failure this whole module is
    here to stop.
    """
    return "source_name" in node and ("applied" in node or "source_rank" in node)


def iter_price_stamps(node: Any, _path: str = "") -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Walk any job/part/estimate structure and yield (path, block) for every price stamp.

    Bought-in unit costs live at cost_breakdown.system_cost.source; material prices live at
    material_estimate.price_source; labour rates live under labour.rate_sources keyed by
    operation; and the priced records themselves live under estimate_summary.part_estimates,
    not the top-level `parts` list. A checker that reads two of those paths passes a job whose
    only guessed price is in the third — which is exactly what happened. The reproducibility
    check read part["price_source"] over the top-level parts, and 12120's three AI-priced
    bought-ins were stamped somewhere else entirely, so the check reported CLEAR.

    So nothing here knows a field path, and nothing here is given a list of parts. It is
    handed the whole job and it finds every price in it.
    """
    if isinstance(node, dict):
        if node.get("schema") == PRICE_SOURCE_SCHEMA or _looks_like_price_stamp(node):
            yield _path, node
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                yield from iter_price_stamps(value, f"{_path}.{key}" if _path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, (dict, list)):
                yield from iter_price_stamps(value, f"{_path}[{index}]")


def stamp_affects_total(block: Dict[str, Any]) -> bool:
    """Did this price actually reach the estimate's total?

    `applied` means a price was found and used for this line. `affects_total` is narrower: a
    bought-in unit cost can be resolved and then not added, because the part was costed as a
    fabrication instead. Only money that reached the total can make the total move.
    """
    if "affects_total" in block:
        return bool(block.get("affects_total"))
    return bool(block.get("applied"))


def stamp_is_ai_estimate(block: Dict[str, Any]) -> bool:
    """Was this price generated rather than looked up?

    Checked three ways because the block may have been written before this module existed:
    the explicit verdict, the class, or — for older JSON — the raw source names. The last is
    the one that matters in practice, because `source_type` on those blocks reads "external",
    which is also what a SQL catalogue hit reads. Trusting `source_type` alone is precisely
    how three AI-priced lines passed as catalogue prices.
    """
    if block.get("reproducible") is False:
        return True
    if block.get("source_class") == "ai_estimate":
        return True
    return is_non_reproducible_source(
        block.get("source_name"),
        block.get("pricing_mode"),
        (block.get("selected") or {}).get("source") if isinstance(block.get("selected"), dict) else None,
    )


def applied_ai_prices(node: Any) -> list:
    """Every stamped price on this structure that was BOTH generated and actually used.

    A candidate the resolver considered and rejected costs nothing and is not reported; only
    a guessed number that reached the total is a problem for reproducing the job.
    """
    found = []
    for path, block in iter_price_stamps(node):
        if stamp_affects_total(block) and stamp_is_ai_estimate(block):
            found.append((path, block))
    return found


def declared_price_disagreements(node: Any) -> list:
    """Every stamped price where the sources that answered did not agree on the number."""
    out = []
    for path, block in iter_price_stamps(node):
        prov = block.get("provenance")
        if isinstance(prov, dict) and prov.get("disagreement"):
            out.append((path, block))
    return out


def review_reason_for(source_class: str, source_name: Any = None) -> Optional[str]:
    """The sentence an estimator needs to see next to this price, or None if it needs none."""
    if source_class == "ai_estimate":
        return (
            f"Indicative AI market estimate ({_norm(source_name) or 'ai'}) — not a catalogue "
            f"price. It will differ on the next run; confirm before quoting firm."
        )
    if source_class == "web_catalog":
        return "Live web listing — verify the supplier and quantity break before quoting firm."
    if source_class == "unpriced":
        return "No price source found — add the code to the catalogue or price it by hand."
    return None
