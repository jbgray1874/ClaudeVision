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


# ── two axes, not one ────────────────────────────────────────────────────────────────
# REPRODUCIBLE and FIRM are different questions and this module used to answer only the
# first. "Would the same input give the same number tomorrow?" is not "may we put this in
# front of a customer as a price we will honour?" A public distributor list price is
# perfectly reproducible and is not a firm quote: it carries no contract, no validity date
# and no commitment. Treating reproducible as sufficient let a list price sit on a quote
# looking exactly like a negotiated one.
#
#   reproducible  — same inputs, same answer. About repeatability.
#   firm          — we will stand behind it. About commitment and expiry.
#
# Nothing here decides whether a given SUPPLIER is any good; it decides what KIND of thing a
# price is, so the same rule applies to a supplier nobody has onboarded yet.
CONTRACT = "contract"                # agreed rate: UDEF, an active contract price
ACCOUNT_FEED = "account_feed"        # supplier's own feed for our account, with a valid_to
SUPPLIER_QUOTE = "supplier_quote"    # written quotation with an expiry
PURCHASE_HISTORY = "purchase_history"  # what we last actually paid
CATALOGUE = "catalogue"              # public list price, no contract behind it
COMMODITY_INDEX = "commodity_index"  # market benchmark, never a sell price
AI_ESTIMATE = "ai_estimate"
UNPRICED = "unpriced"

#                       reproducible   firm            needs a validity date to be firm
SOURCE_CLASS_RULES = {
    CONTRACT:         (True,  True,  True),
    ACCOUNT_FEED:     (True,  True,  True),
    SUPPLIER_QUOTE:   (True,  True,  True),
    # WHAT WE LAST PAID IS EVIDENCE, NOT A COMMITMENT. An invoice records a transaction that
    # completed under conditions that may no longer hold; nobody has undertaken to repeat it.
    # Putting a validity date on an old invoice does not create an agreement, so history is
    # never firm on its own — it is promoted to `contract` below only when it cites an
    # agreement that is still in force.
    PURCHASE_HISTORY: (True,  False, False),
    CATALOGUE:        (True,  False, False),  # reproducible, never firm on its own
    COMMODITY_INDEX:  (True,  False, False),
    AI_ESTIMATE:      (False, False, False),
    UNPRICED:         (True,  False, False),
}


# ── WHY A LINE CARRIES NO PRICE ─────────────────────────────────────────────────────
#
# The other half of the ledger, and the half that was missing. A line with a price says
# where the price came from; a line WITHOUT one said nothing at all, so every unpriced
# line looked identical -- and they are not remotely the same thing. On 11650-05 five BOM
# lines carried no price for four different reasons, and only one of them was a reason an
# estimator should have to act on.
#
# THE CATEGORY SAYS WHOSE PROBLEM IT IS. That is the whole point. "Not priced" hides the
# difference between work the estimator must supply and work the engine is failing to
# charge for, and the second silently under-quotes every job it touches.
NOT_MEASURED = "not_measured"        # the datum is absent. The estimator supplies it.
POLICY_WITHHELD = "policy_withheld"  # a figure exists and we deliberately do not use it.
NO_VOCABULARY = "no_vocabulary"      # no operation or rate exists for this work. OURS.
MISREAD = "misread"                  # the datum exists and was read wrong. OURS.
ORDER_LEVEL = "order_level"          # not a per-unit price by design (haulage, packaging).
NOT_APPLICABLE = "not_applicable"    # correctly nil -- an assembly parent, a mirror.
UNEXPLAINED = "unexplained"          # nothing recorded. The one that must never survive.

# Who has to act. An estimator scanning a sheet needs to know which blanks are theirs.
UNPRICED_OWNER = {
    NOT_MEASURED:    "estimator",
    POLICY_WITHHELD: "estimator",
    ORDER_LEVEL:     "estimator",
    NO_VOCABULARY:   "engine",
    MISREAD:         "engine",
    NOT_APPLICABLE:  "nobody",
    UNEXPLAINED:     "engine",
}

# Categories that mean the job is being UNDER-CHARGED rather than merely incomplete. These
# are the ones worth a person's time: the work is real, the customer will be invoiced for
# it, and nothing on the sheet is asking for it.
UNDERCHARGING_REASONS = frozenset({NO_VOCABULARY, MISREAD, UNEXPLAINED})

_UNPRICED_REASON_TEXT = {
    NOT_MEASURED: "the dimension or quantity it needs was never measured",
    POLICY_WITHHELD: "a figure exists but is not reproducible enough to stand behind",
    NO_VOCABULARY: "this engine has no operation or rate for this work",
    MISREAD: "the data exists on the drawing and was read incorrectly",
    ORDER_LEVEL: "it is an order-level cost, not a per-unit price",
    NOT_APPLICABLE: "there is correctly nothing to charge here",
    UNEXPLAINED: "NO REASON WAS RECORDED",
}


def unpriced_reason(category: Any, detail: Any = "") -> Dict[str, Any]:
    """A structured, readable statement of why a line carries no price.

    Every unpriced line must carry one. A blank on an estimate reads as "free", and the
    only defence against that is a sentence saying which kind of nothing it is.
    """
    key = str(category or "").strip().lower()
    if key not in _UNPRICED_REASON_TEXT:
        key = UNEXPLAINED
    return {
        "schema": "unpriced_reason.v1",
        "category": key,
        "owner": UNPRICED_OWNER.get(key, "engine"),
        "undercharging": key in UNDERCHARGING_REASONS,
        "why": _UNPRICED_REASON_TEXT[key],
        "detail": str(detail or ""),
    }


def describe_unpriced(category: Any, detail: Any = "") -> str:
    """One line for a sheet cell or a report row."""
    r = unpriced_reason(category, detail)
    who = {"estimator": "ESTIMATOR TO PRICE",
           "engine": "ENGINE GAP - THIS JOB IS UNDER-CHARGED",
           "nobody": "nothing to charge"}[r["owner"]]
    tail = f" ({r['detail']})" if r["detail"] else ""
    return f"NOT PRICED - {r['why']}{tail}. {who}."


# Internal, agreed prices. These are SDI's own record of what a thing costs under agreement.
_CONTRACT_SOURCES = ("udef", "sqlserver", "access", "spreadsheet", "bought_in_parts",
                     "pma_tbl", "labour_rates", "material_prices")
# What we last paid — traceable and reproducible, but not automatically still true.
_HISTORY_SOURCES = ("historical_quote", "purchase_history", "last_paid", "previous_quote")
# Somebody else's published list.
_CATALOGUE_SOURCES = ("supplier_catalog", "catalog_url", "web_catalog", "distributor_list")
_INDEX_SOURCES = ("argus", "platts", "fastmarkets", "commodity_index", "hrc", "crc")

# How stale a purchase may be and still be quoted as firm. A price you paid last week is
# evidence; one you paid two years ago is history. Overridable by whoever owns the policy.
PURCHASE_HISTORY_FIRM_DAYS = 90


def source_class_of(source_name: Any, *, source_type: Any = None, pricing_mode: Any = None,
                    priced: bool = True) -> str:
    """Which of the classes above produced this price."""
    if not priced:
        return UNPRICED
    if is_non_reproducible_source(source_name, source_type, pricing_mode):
        return AI_ESTIMATE
    n = _norm(source_name)
    if not n or n in _UNPRICED_SOURCES:
        return UNPRICED if n in _UNPRICED_SOURCES else CATALOGUE
    for token in _INDEX_SOURCES:
        if token in n:
            return COMMODITY_INDEX
    for token in _HISTORY_SOURCES:
        if token in n:
            return PURCHASE_HISTORY
    for token in _CATALOGUE_SOURCES:
        if token in n:
            return CATALOGUE
    for token in _CONTRACT_SOURCES:
        if token in n:
            return CONTRACT
    return CATALOGUE          # unknown source: reproducible, but nobody has agreed it


def price_firmness(block: Dict[str, Any], today: Any = None) -> Dict[str, Any]:
    """Is this price firm, and if not, exactly what is missing?

    Returns {"class", "reproducible", "firm", "reason"}. `reason` is empty when firm, and
    otherwise names the one thing standing in the way — because "not firm" on its own tells
    an estimator nothing they can act on.

    NOTHING IS FIRM TODAY. No price source in this engine carries a validity date, so every
    line resolves to "firm status cannot be established". That is the honest answer, and it
    is why the check that reads this reports a warning rather than blocking every job: a gate
    that fails everything is one people learn to ignore. It becomes blocking the day the
    first supplier feed lands carrying price_valid_to.
    """
    # Always computed from the source itself, never read off source_class. That field carries
    # the older, coarser vocabulary used for the spreadsheet's supplier label, where
    # "catalogue" means "a real lookup of any kind" — including UDEF. Reading it here would
    # file every contract price as a public list price and rule it non-firm.
    _sel = block.get("selected") if isinstance(block.get("selected"), dict) else {}
    cls = block.get("price_class")
    if cls not in SOURCE_CLASS_RULES:
        cls = source_class_of(block.get("source_name") or _sel.get("source"),
                              source_type=block.get("source_type"),
                              pricing_mode=block.get("pricing_mode"),
                              priced=_sel.get("price") is not None or bool(block.get("applied")))
    # A purchase still covered by an unexpired agreement IS a contract price — the invoice is
    # just where we happen to have read it. The agreement reference is what does the work:
    # without it there is nothing anyone has undertaken to honour, and a date alone would
    # turn every old invoice firm.
    if cls == PURCHASE_HISTORY:
        _ref = (block.get("quote_reference") or block.get("contract_id")
                or block.get("agreement_ref"))
        _valid = block.get("price_valid_to") or block.get("valid_to")
        if _ref and _valid and not (today and str(_valid) < str(today)):
            cls = CONTRACT

    reproducible, firm, needs_validity = SOURCE_CLASS_RULES[cls]
    reason = ""
    if not reproducible:
        reason = "the price is generated, not looked up — it differs every run"
    elif not firm:
        reason = (f"a {cls.replace('_', ' ')} price carries no commitment to honour it")
    elif needs_validity:
        valid_to = block.get("price_valid_to") or block.get("valid_to")
        effective = block.get("price_effective_at") or block.get("price_date")
        if not valid_to and not (cls == PURCHASE_HISTORY and effective):
            firm, reason = False, "no price_valid_to on the source — validity cannot be checked"
        elif valid_to and today and str(valid_to) < str(today):
            firm, reason = False, f"the price expired on {valid_to}"
    return {"class": cls, "reproducible": reproducible, "firm": firm, "reason": reason}


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


# What a priced line is made of, for deciding which supplier connector would own it. Keyed
# on material family and stock form, never on a part code, so a job nobody has seen yet is
# routed by the same rule.
MATERIAL_CLASS_TOKENS = (
    ("plastic_sheet", ("HIPS", "ABS", "PETG", "ACRYLIC", "PERSPEX", "HDPE", "POLYPROP",
                       "POLYCARB", "PVC", "FOAMEX")),
    ("timber_board", ("MDF", "PLYWOOD", "PLY", "TIMBER", "CHIPBOARD", "OSB", "HARDBOARD",
                      "OAK", "PINE", "BIRCH", "BEECH")),
    ("sheet_steel", ("MILD_STEEL", "MILD STEEL", "CR4", "GALV", "ZINTEC", "ALUMINISED",
                     "STAINLESS", "ALUMINIUM", "STEEL")),
)


def material_class_of(context: Dict[str, Any]) -> str:
    """Which supplier class would own this line: sheet_steel, plastic_sheet, timber_board,
    fasteners_mro, or other.

    A bought-in with no material is a purchased component — fasteners, cable, knobs — which
    is a different supplier from any of the sheet materials, so it is its own class rather
    than an unknown.
    """
    blob = " ".join(str(context.get(k) or "") for k in
                    ("normalized_material", "material", "stock_form")).upper()
    for name, tokens in MATERIAL_CLASS_TOKENS:
        if any(t in blob for t in tokens):
            return name
    if context.get("bought_in") or "BOUGHT" in blob:
        return "fasteners_mro"
    return "other"


def iter_price_stamps_with_context(
    node: Any, _path: str = "", _ctx: Optional[Dict[str, Any]] = None,
) -> Iterator[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """As iter_price_stamps, carrying what the nearest enclosing record says about the part.

    The owner variant returns a name, which is enough to report a line and not enough to
    decide which supplier would price it. Severity now depends on whether a firm-capable
    connector exists for the line's MATERIAL, so the material has to travel with the stamp.
    """
    if isinstance(node, dict):
        ctx = dict(_ctx or {})
        for key in ("part_number", "matched_part_code", "part_code", "description",
                    "normalized_material", "material", "stock_form"):
            v = node.get(key)
            if isinstance(v, str) and v.strip():
                ctx[key] = v.strip()          # the nearest enclosing record wins
        _pn = ctx.get("part_number") or ctx.get("matched_part_code") or ctx.get("part_code")
        if _pn and str(_pn).upper().startswith("BI-"):
            ctx["bought_in"] = True
        if node.get("schema") == PRICE_SOURCE_SCHEMA or _looks_like_price_stamp(node):
            yield _path, node, ctx
        for key, value in node.items():
            if isinstance(value, dict):
                if "applied_to_total" in node and "affects_total" not in value:
                    value = dict(value, affects_total=bool(node.get("applied_to_total")))
                yield from iter_price_stamps_with_context(
                    value, f"{_path}.{key}" if _path else str(key), ctx)
            elif isinstance(value, list):
                yield from iter_price_stamps_with_context(
                    value, f"{_path}.{key}" if _path else str(key), ctx)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, (dict, list)):
                yield from iter_price_stamps_with_context(value, f"{_path}[{index}]", _ctx)


def iter_price_stamps_with_owner(
    node: Any, _path: str = "", _owner: Optional[str] = None,
) -> Iterator[Tuple[str, Dict[str, Any], Optional[str]]]:
    """As iter_price_stamps, but also carrying the part the stamp was found under.

    A verdict that says estimate_summary.part_estimates[11] is unactionable — nobody can add
    an array index to a catalogue, and that violation ends by instructing someone to do
    exactly that. The owner is the nearest enclosing record that names itself, so the message
    can say BI-SCREENCABLE instead.
    """
    if isinstance(node, dict):
        owner = _owner
        for key in ("part_number", "matched_part_code", "part_code", "description"):
            _v = node.get(key)
            if isinstance(_v, str) and _v.strip():
                owner = _v.strip()
                break
        if node.get("schema") == PRICE_SOURCE_SCHEMA or _looks_like_price_stamp(node):
            yield _path, node, owner
        for key, value in node.items():
            if isinstance(value, dict):
                # THE ENCLOSING BLOCK KNOWS WHETHER THE MONEY WAS ADDED. A system_cost block
                # carries applied_to_total beside the stamp; the stamp's own `applied` only
                # means a price was resolved. On a document written before affects_total
                # existed those two differ, and reading the looser one reports a GBP 75.00
                # line as reaching a GBP 32.86 unit price — which it plainly did not.
                if "applied_to_total" in node and "affects_total" not in value:
                    value = dict(value, affects_total=bool(node.get("applied_to_total")))
                yield from iter_price_stamps_with_owner(
                    value, f"{_path}.{key}" if _path else str(key), owner)
            elif isinstance(value, list):
                yield from iter_price_stamps_with_owner(
                    value, f"{_path}.{key}" if _path else str(key), owner)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, (dict, list)):
                yield from iter_price_stamps_with_owner(value, f"{_path}[{index}]", _owner)


def stamp_source_class(block: Dict[str, Any]) -> str:
    """What kind of thing priced this line, for a block that may predate the stamp.

    Older JSON carries no source_class, and reading that absence as "unknown" makes a listing
    of every price on a job over a hundred rows of question marks — which tells a reader
    nothing and invites them to stop looking before reaching the rows that matter.
    """
    declared = block.get("source_class")
    if isinstance(declared, str) and declared:
        return declared
    _sel = block.get("selected") if isinstance(block.get("selected"), dict) else {}
    return classify_price_source(
        block.get("source_name") or _sel.get("source"),
        source_type=block.get("source_type"),
        pricing_mode=block.get("pricing_mode"),
        priced=_sel.get("price") is not None or block.get("applied") is True,
    )


def stamp_is_reproducible(block: Dict[str, Any]) -> bool:
    """Will this price come back the same on the next run of the same job?

    Only a GENERATED price can fail this. A catalogue rate, a spreadsheet cell and a
    historical line all repeat perfectly by their nature — the question only arises for
    a figure the model composed, which is why the flag is written by the generated-price
    cache and read here.

    Note the difference from FIRM. A list price repeats perfectly and commits nobody;
    reproducible means two people reading this job on the same day see the same number,
    which is the minimum for it to be discussed at all. check_prices_are_firm asks the
    other question.
    """
    if not isinstance(block, dict):
        return False
    if block.get("price_is_reproducible") is True:
        return True
    for key in ("selected", "result", "price", "detail"):
        inner = block.get(key)
        if isinstance(inner, dict) and inner.get("price_is_reproducible") is True:
            return True
    return False


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
    for path, block, _owner in iter_price_stamps_with_owner(node, _path):
        yield path, block


def stamp_affects_total(block: Dict[str, Any]) -> bool:
    """Did this price actually reach the estimate's total?

    `applied` means a price was found and used for this line. `affects_total` is narrower: a
    bought-in unit cost can be resolved and then not added, because the part was costed as a
    fabrication instead. Only money that reached the total can make the total move.
    """
    if "affects_total" in block:
        return bool(block.get("affects_total"))
    return bool(block.get("applied"))


def mark_withheld(record: Any) -> int:
    """Record that this line's price did NOT reach the total. Returns how many stamps changed.

    THE WRITER KNEW AND NEVER SAID SO. stamp_affects_total already asks the right question —
    a price can be resolved and then not added — but it can only read what somebody wrote,
    and it falls back to `applied`, which is True for a price that was found. When
    wb_populate withholds an AI market estimate from the price column and writes GBP 0.00 on
    the line, the stamp still read as money in the total, and price_not_reproducible blocked
    job 12392 for a figure the sheet had deliberately refused.

    THE GUARD IT PROTECTS MUST SURVIVE. On 11350 an AI estimate of GBP 86.04 DID enter the
    material total and moved it every run; that is what this invariant exists to catch, and
    it is untouched, because a price that reached the total is never marked here. The
    distinction is not "was it generated" but "is it in the money" — mentioned in provenance
    is not the same as added to a number.
    """
    changed = 0
    for _path, block in iter_price_stamps(record):
        if block.get("affects_total") is not False:
            block["affects_total"] = False
            block["withheld_reason"] = str(block.get("withheld_reason")
                                           or "kept off the price column by the engine")
            changed += 1
    return changed


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
    for path, block, owner in iter_price_stamps_with_owner(node):
        if stamp_affects_total(block) and stamp_is_ai_estimate(block):
            found.append((path, block, owner))
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
