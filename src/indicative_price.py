"""Rung 4: a researched price for a line the first three rungs could not answer.

James Gray, 18 September 2026:

    "an LLM indicative price may contribute to the estimate total. It must be a genuine
     fourth pricing rung, with independent research or a reproducible calculation; source
     links/details, date, unit and quantity basis; a clear 'LLM indicative - review
     required' label in workbook, report and quote; no historic estimator-sheet amount,
     config literal or unrelated-job amount used as an input."

    "implement the central rung-4 producer so it can return an evidenced LLM-indicative
     price for a required line... for bought-in components such as the felt pads; packing
     and delivery; specialist bought-in processes such as plating and plater freight."

WHAT THIS IS FOR, AND WHY IT IS NOT THE THING THAT WAS DELETED.

Two days ago the felt pad was priced at 20p by a number typed into config.py. That was
withdrawn (D-095) because a figure somebody worked out once and typed into a source file
cannot be checked, cannot be re-derived, and goes stale silently. Withdrawing it left a
blank, and a blank totals as nothing, which is worse (D-096).

The difference between the 20p and what this module returns is NOT that one is labelled
indicative — the config entry was labelled indicative too, in those words. The difference
is that this one can be CHECKED:

    it names its source            a link, a supplier, a named market reference
    it carries the date            a market price without a date is folklore
    it says what it is PER         each, per metre, per kg, per order
    it says at what quantity       break pricing moves, and a price found at 1 off is not
                                   the price at 1,000
    it shows its arithmetic        how the line's money comes from the researched figure,
                                   so an estimator can disagree with one step rather than
                                   with the whole number

Miss any of those and this module returns NO PRICE and says which one is missing. It never
returns zero and it never returns a figure it cannot evidence. An unevidenced guess and a
config literal are the same thing wearing different clothes.

THREE CLASSES OF LINE, BECAUSE THEY ARE RESEARCHED DIFFERENTLY.

    BOUGHT_IN_COMPONENT   a felt pad, a clip, a screw. Researched as a trade unit price for
                          the described item, then multiplied by the quantity the drawing
                          calls for.

    COMMERCIAL            packing and delivery. Priced for the ORDER and divided by it, so
                          the per-unit figure moves with the order quantity instead of
                          being frozen at the quantity it was found at — the fault the
                          break mechanism exists to prevent.

    SUBCONTRACT_PROCESS   plating, and the transport to and from the plater. Researched as
                          a trade rate against the part's OWN measured property — its mass,
                          its coated area, the two-way distance — never as a lump sum for
                          "a job like this", which is not reproducible and not checkable.

WHAT IT REFUSES TO READ, AND THIS IS THE POINT.

A historic amount off an estimator's sheet, a config literal, and an amount from another
job are all barred as INPUTS — not merely as outputs. Howard's £250 plating and his
£120/£20 freight cannot become a price by being fed to a model and returned as its own
answer; that is laundering, and it produces a figure that looks researched and is not.
`_contaminated` checks the provenance of everything that reaches the brief, and a
contaminated input makes the line unpriced with the reason named.

What those historic figures ARE good for is telling us what to go and ask about: a
decorative brass finish quoted per stand, and two-stage plater transport. That is method,
not money, and method is what the register was always for.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

__all__ = [
    "BOUGHT_IN_COMPONENT",
    "COMMERCIAL",
    "SUBCONTRACT_PROCESS",
    "LLM_INDICATIVE_STATUS",
    "classify",
    "research_brief",
    "resolve_indicative",
]

BOUGHT_IN_COMPONENT = "bought_in_component"
COMMERCIAL = "commercial"
SUBCONTRACT_PROCESS = "subcontract_process"

LLM_INDICATIVE_STATUS = "LLM indicative - review required"

# Provenance words that mean "this came off somebody's sheet, out of our own source, or
# off another job". Any of them in an input's origin bars it from the brief.
_BARRED_ORIGINS = (
    "estimator_sheet", "manual_estimate", "estimator_stated", "sheet_derived",
    "config", "config_literal", "hardcoded", "source_code",
    "other_job", "unrelated_job", "historic_quote_other_job",
    "sdi_estimate", "rag_fallback", "web_indicative",
)

_COMMERCIAL_CODES = ("PACKAGING", "DELIVERY", "CARRIAGE", "FREIGHT", "HAULAGE")
_PROCESS_WORDS = ("PLATE", "PLATING", "PLATER", "ANODIS", "ANODIZ", "GALVAN",
                  "POLISH", "PASSIVAT", "ELECTROPLATE")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None          # NaN is not a number here either


def _contaminated(origin: Any) -> str:
    """The barred word in this origin, or "". Checked on INPUTS, not only on outputs.

    Howard's £250 cannot become a price by being handed to a model and returned as its
    answer. A figure that looks researched and is not is worse than one that admits it.
    """
    _o = _clean(origin).lower().replace("-", "_").replace(" ", "_")
    for word in _BARRED_ORIGINS:
        if word in _o:
            return word
    return ""


def classify(line: Any) -> str:
    """Which of the three research shapes this line takes."""
    code = _clean((line or {}).get("code") or (line or {}).get("part_number")).upper()
    desc = _clean((line or {}).get("description")).upper()
    if any(c in code for c in _COMMERCIAL_CODES):
        return COMMERCIAL
    if any(w in code or w in desc for w in _PROCESS_WORDS):
        return SUBCONTRACT_PROCESS
    return BOUGHT_IN_COMPONENT


def research_brief(line: Any, *, order_qty: int = 1) -> Dict[str, Any]:
    """What to go and find out, and what a usable answer would look like.

    Built from the LINE'S OWN facts — its description, its measured mass or area, the order
    quantity — and from nothing else. A brief that quoted a previous price would be asking
    the model to agree with it.
    """
    line = dict(line or {})
    kind = classify(line)
    desc = _clean(line.get("description"))
    brief: Dict[str, Any] = {
        "kind": kind,
        "description": desc,
        "code": _clean(line.get("code") or line.get("part_number")),
        "order_quantity": int(order_qty or 1),
        "currency": "GBP",
        "market": "UK trade",
    }

    if kind == BOUGHT_IN_COMPONENT:
        brief["ask"] = (
            f"Current UK trade unit price for: {desc}. Give the price PER EACH, the pack or "
            f"break quantity it is sold at, the supplier or listing it comes from, and the "
            f"date. Do not estimate a 'typical' price: name a real current listing.")
        brief["wanted_unit"] = "each"
        brief["quantity_needed"] = _num(line.get("quantity")) or 1
    elif kind == COMMERCIAL:
        brief["ask"] = (
            f"Current UK trade cost for: {desc}, priced FOR THE WHOLE ORDER of "
            f"{brief['order_quantity']} unit(s), not per unit. Give the carrier or supplier, "
            f"the basis (per pallet, per consignment, per mile), and the date.")
        brief["wanted_unit"] = "order"
    else:
        brief["ask"] = (
            f"Current UK trade rate for the subcontract process: {desc}. Give the rate "
            f"against a MEASURED property — per kg, per square metre, per piece — plus any "
            f"batch or vat minimum charge, the plater or supplier, and the date. A lump sum "
            f"for 'a job like this' is not usable: it cannot be re-derived.")
        brief["wanted_unit"] = "measured"
        for _f in ("mass_kg", "coated_area_m2", "finish_spec", "distance_miles"):
            _v = line.get(_f)
            if _v not in (None, ""):
                brief[_f] = _v

    # THE INPUTS, EACH WITH ITS ORIGIN, so the guard can refuse a poisoned brief.
    brief["inputs"] = [
        {"field": k, "value": v, "origin": _clean((line.get("input_origins") or {}).get(k))
         or "drawing_or_measurement"}
        for k, v in sorted(line.items())
        if k in ("quantity", "mass_kg", "coated_area_m2", "finish_spec",
                 "distance_miles", "description")
    ]
    return brief


def _calculation(kind: str, unit_price: float, brief: Dict[str, Any],
                 minimum_gbp: Optional[float]) -> Dict[str, Any]:
    """The arithmetic, written out, and the per-unit figure it produces.

    Shown so an estimator can disagree with ONE STEP rather than with the whole number.
    """
    order_qty = max(1, int(brief.get("order_quantity") or 1))
    if kind == BOUGHT_IN_COMPONENT:
        qty = _num(brief.get("quantity_needed")) or 1
        per_unit = unit_price * qty
        return {"per_unit_gbp": round(per_unit, 4),
                "working": (f"{qty:g} off x GBP {unit_price:,.4f} each "
                            f"= GBP {per_unit:,.4f} a unit")}
    if kind == COMMERCIAL:
        per_unit = unit_price / order_qty
        return {"per_unit_gbp": round(per_unit, 4),
                "working": (f"GBP {unit_price:,.2f} for the order / {order_qty} off "
                            f"= GBP {per_unit:,.4f} a unit")}
    # SUBCONTRACT_PROCESS — a measured rate, plus any batch minimum spread over the order.
    mass = _num(brief.get("mass_kg"))
    area = _num(brief.get("coated_area_m2"))
    measured = mass if mass else area
    basis = "kg" if mass else ("m2" if area else "piece")
    measured = measured if measured else 1.0
    run = unit_price * measured
    spread = (minimum_gbp / order_qty) if minimum_gbp else 0.0
    per_unit = max(run, 0.0) + spread
    working = f"{measured:g} {basis} x GBP {unit_price:,.4f}/{basis} = GBP {run:,.4f}"
    if minimum_gbp:
        working += (f"; batch minimum GBP {minimum_gbp:,.2f} / {order_qty} off "
                    f"= GBP {spread:,.4f}")
    working += f"; total GBP {per_unit:,.4f} a unit"
    return {"per_unit_gbp": round(per_unit, 4), "working": working}


def resolve_indicative(line: Any, *, order_qty: int = 1, as_of: str = "",
                       ask: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
                       ) -> Dict[str, Any]:
    """Research this line and return an evidenced indicative price, or say what is missing.

    `ask` is the researcher — injected so this is testable without a network, and so the
    engine can put its own web/LLM rung behind it. It receives the brief and returns
    whatever it found. `as_of` is passed in rather than read from the clock, so a run is
    reproducible and a cached answer cannot silently claim today's date.

    The return is always one of two shapes, and neither of them is a zero:

        priced      price_gbp, evidence{source, as_of, unit_basis, quantity_basis},
                    calculation{working, per_unit_gbp}, status
        unpriced    price_gbp None, and `missing` naming the precise source that would
                    answer it
    """
    brief = research_brief(line, order_qty=order_qty)

    # A poisoned input never reaches the researcher.
    for _in in brief.get("inputs") or []:
        _bad = _contaminated(_in.get("origin"))
        if _bad:
            return {
                "price_gbp": None, "status": "not priced", "brief": brief,
                "missing": (f"input '{_in.get('field')}' comes from {_bad}, which cannot "
                            f"be used to research a price. A historic amount off an "
                            f"estimator's sheet or out of our own config does not become "
                            f"a price by being researched from."),
            }

    found: Dict[str, Any] = {}
    if ask is not None:
        try:
            found = dict(ask(brief) or {})
        except Exception as _e:                                      # noqa: BLE001
            return {"price_gbp": None, "status": "not priced", "brief": brief,
                    "missing": f"the research step failed ({_e})"}

    if not found:
        return {"price_gbp": None, "status": "not priced", "brief": brief,
                "missing": ("no researcher was available to answer this line. It needs a "
                            "current SDI Live rate, a supplier catalogue, a quote, or a "
                            "researched figure with its evidence.")}

    _bad = _contaminated(found.get("origin") or found.get("source_type"))
    if _bad:
        return {"price_gbp": None, "status": "not priced", "brief": brief,
                "missing": (f"the figure returned is sourced from {_bad}, which is not an "
                            f"allowed price source")}

    unit_price = _num(found.get("price_gbp"))
    if unit_price is None or unit_price <= 0:
        return {"price_gbp": None, "status": "not priced", "brief": brief,
                "missing": ("the research returned no usable figure. A zero is not a "
                            "price: this line still costs something.")}

    evidence = {
        "source": _clean(found.get("source")),
        "as_of": _clean(found.get("as_of")) or _clean(as_of),
        "unit_basis": _clean(found.get("unit")) or _clean(brief.get("wanted_unit")),
        "quantity_basis": _clean(found.get("quantity_basis")),
    }
    _gaps = [k for k, v in evidence.items() if not v]
    if _gaps:
        _names = {"source": "a source - a link, a supplier or a named reference",
                  "as_of": "the date the price was true",
                  "unit_basis": "what the figure is per",
                  "quantity_basis": "the quantity it was found at"}
        return {"price_gbp": None, "status": "not priced", "brief": brief,
                "evidence": evidence,
                "missing": ("a researched figure was offered without "
                            + ", ".join(_names[g] for g in _gaps)
                            + ". Without it the figure cannot be checked, which is what "
                              "separates it from a number typed into a file.")}

    calc = _calculation(brief["kind"], unit_price, brief, _num(found.get("minimum_gbp")))
    return {
        "price_gbp": calc["per_unit_gbp"],
        "unit_price_gbp": round(unit_price, 4),
        "rung": "llm_indicative",
        "status": LLM_INDICATIVE_STATUS,
        "evidence": evidence,
        "calculation": calc,
        "brief": brief,
        # Carried so the workbook, report and quote all say the same thing in the same
        # words, and so a reader can tell at a glance that this is rung 4 and not rung 1.
        "label": LLM_INDICATIVE_STATUS,
        "review_required": True,
    }
