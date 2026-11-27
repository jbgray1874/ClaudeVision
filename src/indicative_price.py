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

import re
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

# WHAT A BOUGHT-IN LINE IS SOLD BY. Most are sold each; edging is sold by the metre, and
# asking a model for the price of "one ABS edging" gets the price of a REEL — which then
# gets multiplied by the metres, because the arithmetic below cannot tell that the unit it
# was handed is not the unit it was answered in. The line already carries its own unit
# (`unit_of_measure`), so the brief asks in it and the working says it.
_UNIT_WORDS = {
    "M": "metre", "MM": "metre", "METRE": "metre", "METER": "metre", "LM": "metre",
    "LIN M": "metre", "LINEAR METRE": "metre", "MTR": "metre",
    "KG": "kilogram", "KILO": "kilogram", "KILOGRAM": "kilogram",
    "M2": "square metre", "M²": "square metre", "SQM": "square metre",
    "SQ M": "square metre", "SQUARE METRE": "square metre",
    "L": "litre", "LITRE": "litre", "LITER": "litre",
    "EA": "each", "EACH": "each", "OFF": "each", "NR": "each", "NO": "each", "PC": "each",
}


def _unit_word(value: Any) -> str:
    """The word to price this line by — "metre", "kilogram", "each". Never empty."""
    key = _clean(value).upper().replace(".", "")
    return _UNIT_WORDS.get(key) or ("each" if not key else key.lower())


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
        _unit = _unit_word(line.get("unit_of_measure"))
        brief["ask"] = (
            f"Current UK trade unit price for: {desc}. Give the price PER {_unit.upper()}, "
            f"the pack or break quantity it is sold at, the supplier or listing it comes "
            f"from, and the date. Do not estimate a 'typical' price: name a real current "
            f"listing."
            + ("" if _unit == "each" else
               f" This line is bought by the {_unit}, so a price for a whole reel, roll, "
               f"pack or coil must be divided down to one {_unit} and the division shown."))
        brief["wanted_unit"] = _unit
        brief["quantity_needed"] = _num(line.get("quantity")) or 1
        # A SET IS PRICED AS THE WHOLE SET (D-501): the 20:49 K-Wellness graphics set came
        # back as the price of one panel. The caller says the line is a set; the ask says so.
        if line.get("sold_as_set"):
            brief["sold_as_set"] = True
            brief["ask"] += (
                " This line is a SET: give the price of the COMPLETE set as one item — every "
                "panel, card or piece in it — and say what the set contains. The price of one "
                "panel or piece of it is not usable.")
            # ASKED AGAIN, WITH THE REFUSED ANSWER NAMED (D-502).
            if line.get("set_previous_answer"):
                brief["ask"] += (f" A previous answer priced only {line['set_previous_answer']}"
                                 f" — one piece of the set. Price the WHOLE set.")
        # A COUNTED ITEM IS PRICED AT THE JOB'S VOLUME (D-500). The K-Wellness 20:49 book asked
        # for "ONE item" of a 20 x 20 mm label and got a single-label retail listing — £5.76,
        # where the 18:17 book had found 12p — multiplied by 48 labels a unit. A line whose
        # count the engine worked out says how many the job needs in all, and asks the price
        # of one AT THAT VOLUME.
        if isinstance(line.get("quantity_counted"), dict):
            _total = brief["quantity_needed"] * brief["order_quantity"]
            brief["volume_needed"] = _total
            brief["ask"] += (
                f" This job needs {brief['quantity_needed']:g} a unit × "
                f"{brief['order_quantity']} unit(s) = {_total:g} in all: give the price of ONE "
                f"{_unit} when bought at that volume (a roll, sheet, box or trade break), with "
                f"the pack size it comes in — never a single-item retail listing.")
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

    # THE PRODUCT THE DRAWING NAMES, CARRIED TO THE RESEARCHER (D-386). A colour, a finish, a
    # maker's reference and the stock sheet the line is bought as are what turn "18mm MFC
    # board" into a product a listing can be found for. Carried only where the line has them.
    for _f in ("colour", "finish", "product_reference", "sheet_mm", "material"):
        _v = line.get(_f)
        if _v not in (None, "", [], ()):
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
        _unit = _clean(brief.get("wanted_unit")) or "each"
        _qty_said = f"{qty:g} off" if _unit == "each" else f"{qty:g} {_unit}"
        _rate_said = "each" if _unit == "each" else f"a {_unit}"
        return {"per_unit_gbp": round(per_unit, 4),
                "working": (f"{_qty_said} x GBP {unit_price:,.4f} {_rate_said} "
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

    # A RESEARCHER THAT RAN AND CAME BACK EMPTY SAYS WHY (D-351), and that reason is the
    # line's, not "no researcher was available" — which is only true when none was.
    _why_not = str(found.pop("not_found", "") or "").strip()
    if not found:
        return {"price_gbp": None, "status": "not priced", "brief": brief,
                "missing": ((f"{_why_not}. It needs a current SDI Live rate, a supplier "
                             f"catalogue or a quote") if _why_not else
                            ("no researcher was available to answer this line. It needs a "
                             "current SDI Live rate, a supplier catalogue, a quote, or a "
                             "researched figure with its evidence."))}

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

    # ── THE FIGURE MUST BE PER THE UNIT THE LINE IS BOUGHT BY ────────────────────────
    #
    # The arithmetic below multiplies the figure by the line's QUANTITY, and the quantity
    # for an edging line is metres. A researcher that answers with the price of a whole
    # 100 m reel — perfectly good evidence, correctly sourced and dated — would be
    # multiplied by 5 and put £2,000 of tape on a tray. Nothing in the evidence block
    # catches it, because every field is present and true; only the unit disagrees.
    #
    # So the units are compared, and a disagreement is a REFUSAL rather than a conversion:
    # dividing a reel price by a reel length nobody stated would be the engine inventing
    # the very quantity it is not allowed to invent. The refusal names both units, which
    # is enough for a person to ask the right question.
    _want_unit = _clean(brief.get("wanted_unit")) or "each"
    if brief["kind"] == BOUGHT_IN_COMPONENT and _want_unit != "each":
        _got_unit = _unit_word(
            _clean(found.get("unit")).replace("per_", "").replace("per ", "").lstrip("/"))
        if _got_unit != _want_unit:
            return {"price_gbp": None, "status": "not priced", "brief": brief,
                    "evidence": evidence,
                    "missing": (f"this line is bought by the {_want_unit} and the figure "
                                f"returned is per {_got_unit}. It is not converted here: "
                                f"turning a pack, reel or coil price into a per-{_want_unit} "
                                f"rate needs the length or weight that pack holds, and "
                                f"nothing has stated it. Ask for the price per "
                                f"{_want_unit}.")}

    # ── A PACK PRICE IS ONE ITEM'S PRICE ONLY ONCE IT IS DIVIDED BY THE PACK (D-501) ────────
    #
    # A line bought by the each that comes back priced per pack, roll, box, reel or bag is
    # divided by the pack size the answer STATES (its quantity basis or pack_size), with the
    # division written into the evidence; with no size stated it is refused, for the same
    # reason the unit refusal above exists: nothing may invent the pack.
    _packs = {"pack": "pack", "packet": "pack", "roll": "roll", "box": "box", "reel": "reel",
              "bag": "bag", "tub": "tub", "carton": "carton"}
    if brief["kind"] == BOUGHT_IN_COMPONENT and _want_unit == "each":
        _raw_u = _clean(found.get("unit")).lower().replace("per_", "").replace("per ", "")
        _pack_word = next((v for k, v in _packs.items() if re.search(rf"\b{k}s?\b", _raw_u)), "")
        if _pack_word:
            _size = _num(found.get("pack_size"))
            if not _size:
                _m = re.search(r"(\d[\d,]*)", _clean(found.get("quantity_basis")))
                _size = _num(_m.group(1).replace(",", "")) if _m else None
            if not _size or _size <= 0:
                return {"price_gbp": None, "status": "not priced", "brief": brief,
                        "evidence": evidence,
                        "missing": (f"this line is bought by the each and the figure returned "
                                    f"is per {_pack_word} with no pack size stated. It is not "
                                    f"divided here: nothing has said how many the {_pack_word} "
                                    f"holds. Ask for the price of one, or the pack size.")}
            evidence["quantity_basis"] = (
                f"{evidence['quantity_basis']} — GBP {unit_price:,.4f} a {_pack_word} ÷ "
                f"{_size:g} = GBP {unit_price / _size:,.4f} each")
            unit_price = unit_price / _size

    calc = _calculation(brief["kind"], unit_price, brief, _num(found.get("minimum_gbp")))
    return {
        "price_gbp": calc["per_unit_gbp"],
        # ONE ITEM'S PRICE, KEPT APART FROM THE LINE'S TOTAL (D-501). `price_gbp` is what the
        # line costs on one product — the item price × the line's quantity. The engine charges
        # a bought-in line as its item price × its quantity, so it must take THIS figure:
        # taking price_gbp charged 48 QR labels at 48 × 12p each — "48 off × GBP 0.1200 each
        # = GBP 5.7600 a unit", then × 48 again on the sheet.
        "unit_price_gbp": round(unit_price, 4),
        "applies_per_item": brief["kind"] == BOUGHT_IN_COMPONENT,
        "rung": "llm_indicative",
        "status": LLM_INDICATIVE_STATUS,
        "evidence": evidence,
        "calculation": calc,
        "brief": brief,
        # Carried so the workbook, report and quote all say the same thing in the same
        # words, and so a reader can tell at a glance that this is rung 4 and not rung 1.
        "label": LLM_INDICATIVE_STATUS,
        "review_required": True,
        # WHETHER IT HOLDS STILL, CARRIED THROUGH. The workbook's withholding rule turns
        # on exactly one question — "is this the same number next run?" — and a figure the
        # researcher asked once and stored answers it yes. Dropped here, the rule saw an
        # AI figure with nothing said about it and kept it off the price column, which is
        # how a castor with a researched price reached the sheet at zero.
        "price_is_reproducible": bool(found.get("price_is_reproducible")),
        "price_first_taken": _clean(found.get("price_first_taken")),
        # What the researcher says it priced — shown on the line so a wrong match is seen.
        "item_priced": _clean(found.get("item_priced")),
    }
