"""
commercial_lines.py — what it costs to box this order and get it there.

PACKAGING AND DELIVERY WERE ON EVERY QUOTE AT GBP 0.00 AND ASKED OF NOTHING. The comment
beside them said their real cost is order-specific — box size, pallet count, destination,
haulier — and lives in the enquiry rather than the engineering, so the engine "cannot
genuinely derive a price from the drawings".

THAT WAS TRUE ABOUT DERIVING AND FALSE ABOUT ASKING. The engine holds the assembly's overall
size, every part's blank area and gauge, the material densities, and the order quantity. That
is a describable shipment — "five 1250 x 525 panel assemblies, flat-packed, about 34 kg, to a
UK address" — and a describable shipment is a question a supplier or a market lookup answers
every day. Refusing to INVENT a number was right; declining to ASK for one put two zeros on
every estimate this business has produced.

A ZERO IS THE WORST OF THE THREE ANSWERS. It sums into the total as free, it looks deliberate,
and no reviewer argues with it. A figure labelled indicative gets checked; an explicit nil with
an owner gets actioned; a zero gets shipped.

SO: CATALOGUE FIRST, MARKET SECOND, EXPLICIT NIL THIRD — the same ladder as the sheet
materials, the bought-in fixings and the applied finishes, asked through the same lookup. One
way this engine asks the market what something costs.

ORDER-LEVEL, DIVIDED PER UNIT. Neither cost belongs to a part: one box holds five panels and
one pallet goes on one lorry. The figure comes back for the order and is divided by the order
quantity, because that is the column the workbook has — and the divisor is written down, so an
estimator changing the quantity can see what the number was built from.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import config

SCHEMA = "commercial_lines.v1"

# Rough kg per cubic metre, by material family, for turning blanks into a shipping weight.
# Deliberately coarse: a haulage bracket does not turn on the third significant figure, and a
# weight good to twenty per cent picks the right band every time.
_DENSITY_KG_M3 = {
    "STEEL": 7850.0, "MILD STEEL": 7850.0, "STAINLESS": 7900.0, "ZINTEC": 7850.0,
    "ALUMINIUM": 2700.0,
    "ACRYLIC": 1190.0, "PERSPEX": 1190.0, "PMMA": 1190.0, "POLYCARBONATE": 1200.0,
    "PETG": 1270.0, "ABS": 1040.0, "HIPS": 1050.0, "PVC": 1400.0, "FOAMEX": 500.0,
    "MDF": 750.0, "CHIPBOARD": 650.0, "PLYWOOD": 600.0, "MELAMINE FACED CHIPBOARD": 700.0,
}
_DEFAULT_DENSITY_KG_M3 = 1200.0       # a mid plastic; nothing here is decided by it


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _density_for(material: Any) -> float:
    m = str(material or "").upper().replace("_", " ")
    for name, d in sorted(_DENSITY_KG_M3.items(), key=lambda kv: -len(kv[0])):
        if name in m:
            return d
    return _DEFAULT_DENSITY_KG_M3


def describe_order(parts: List[Dict[str, Any]], order_qty: Any) -> Dict[str, Any]:
    """The shipment, in the terms a haulier or a packer would ask for.

    Built from what the engine already measured, not from anything new: every part's blank,
    its gauge, its material's density, and how many of the assembly are being made. A part
    with no blank contributes nothing rather than a guess — the description says how many
    were counted, so a figure resting on two parts out of nine can be seen for what it is.
    """
    try:
        qty = max(1, int(order_qty))
    except (TypeError, ValueError):
        qty = 1
    weight_kg = 0.0
    longest = widest = 0.0
    counted = skipped = 0
    for part in parts or ():
        if not isinstance(part, dict) or part.get("_commercial_placeholder"):
            continue
        L, W = _num(part.get("blank_length_mm")), _num(part.get("blank_width_mm"))
        T = _num(part.get("normalized_thickness_mm"))
        if not (L and W and T):
            skipped += 1
            continue
        counted += 1
        try:
            per = max(1, int(part.get("quantity") or 1))
        except (TypeError, ValueError):
            per = 1
        volume_m3 = (L / 1000.0) * (W / 1000.0) * (T / 1000.0)
        weight_kg += volume_m3 * _density_for(part.get("normalized_material")) * per
        longest, widest = max(longest, L), max(widest, W)
    return {
        "schema": SCHEMA, "order_quantity": qty,
        "unit_weight_kg": round(weight_kg, 2) if weight_kg else None,
        "order_weight_kg": round(weight_kg * qty, 2) if weight_kg else None,
        "largest_part_mm": [longest, widest] if longest and widest else None,
        "parts_measured": counted, "parts_without_a_blank": skipped,
    }


def _ask_market(description: str, tag: str) -> Optional[Dict[str, Any]]:
    """The same lookup the sheet rates, the fixings and the finishes use. Never raises."""
    try:
        from web_ai_price_lookup import lookup_web_ai_price
        result = lookup_web_ai_price(
            {"material": tag, "description": description, "quantity": 1},
            enable_web_search=True, enable_llm_estimate=True)
    except Exception:                                        # noqa: BLE001
        return None
    if not result or not result.get("found"):
        return None
    try:
        gbp = float(result.get("price_gbp") or 0.0)
    except (TypeError, ValueError):
        return None
    if gbp <= 0:
        return None
    return {"order_gbp": round(gbp, 2), "source_class": "llm",
            "source_name": result.get("source_type") or "web_ai_fallback",
            "reproducible": False, "indicative": True,
            "confidence": result.get("confidence")}


def _held_rate(key: str) -> Optional[float]:
    """A figure the business has entered, which beats any lookup. One config line closes
    either of these for good, on every job, exactly as the finish rates do."""
    rates = getattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {}) or {}
    try:
        v = float(rates[key])
    except (KeyError, TypeError, ValueError):
        return None
    return v if v > 0 else None


def _line(code: str, order: Dict[str, Any], description: str,
          held_key: str) -> Dict[str, Any]:
    qty = order.get("order_quantity") or 1
    out: Dict[str, Any] = {"code": code, "order_quantity": qty,
                           "described_as": description, "basis": dict(order)}
    _held = _held_rate(held_key)
    if _held is not None:
        _order_gbp, _src = _held, {
            "source_class": "catalogue", "reproducible": True,
            "source_name": "config.COMMERCIAL_LINE_GBP_PER_ORDER"}
    else:
        _ind = _ask_market(description, code.title())
        if not _ind:
            # NOTHING CAME BACK, SO NOTHING IS INVENTED — and the line still says what it
            # would have been asked, so an estimator can answer the question themselves
            # rather than rediscover it.
            out.update({"unit_gbp": None, "order_gbp": None,
                        "estimator_input_required": True, "reason": "no_price_for_" + code.lower(),
                        "note": (f"{code.title()} could not be priced. It was described as: "
                                 f"{description}. Price it, or put a per-order figure in "
                                 f"config.COMMERCIAL_LINE_GBP_PER_ORDER['{held_key}'] and "
                                 f"every job carries it.")})
            return out
        _order_gbp, _src = _ind["order_gbp"], _ind
    out.update({
        "order_gbp": round(_order_gbp, 2),
        # ORDER-LEVEL, DIVIDED PER UNIT, AND THE DIVISOR IS ON THE RECORD. One box holds five
        # panels; the workbook has a per-unit column and nowhere to say so otherwise.
        "unit_gbp": round(_order_gbp / qty, 2),
        "price_source": _src, "estimator_input_required": False,
        "note": (f"{code.title()} for the whole order of {qty}, divided per unit. "
                 f"Described as: {description}."),
    })
    return out


def packaging_line(parts: List[Dict[str, Any]], order_qty: Any) -> Dict[str, Any]:
    order = describe_order(parts, order_qty)
    size = order.get("largest_part_mm")
    where = (f"largest panel {size[0]:.0f} x {size[1]:.0f}mm, " if size else "")
    weight = (f"about {order['order_weight_kg']:.0f} kg total, "
              if order.get("order_weight_kg") else "")
    return _line("PACKAGING", order,
                 f"Protective packaging and a pallet for {order['order_quantity']} "
                 f"flat-packed display assemblies, {where}{weight}UK trade, per order",
                 "PACKAGING")


def delivery_line(parts: List[Dict[str, Any]], order_qty: Any) -> Dict[str, Any]:
    order = describe_order(parts, order_qty)
    weight = (f"about {order['order_weight_kg']:.0f} kg" if order.get("order_weight_kg")
              else "a part pallet")
    return _line("DELIVERY", order,
                 f"Palletised haulage of {weight} for {order['order_quantity']} display "
                 f"assemblies, one UK mainland delivery, per order",
                 "DELIVERY")
