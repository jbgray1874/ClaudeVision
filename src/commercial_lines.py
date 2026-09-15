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
    phantom = 0
    shippable: List[Dict[str, Any]] = []
    counted_parts: List[Dict[str, Any]] = []
    # A PART LEFT OUT BY NAME, NOT A TALLY. "1.35 kg" against a title block that says 2283 g
    # is a dropped side or divider, and a count of parts-without-a-blank cannot tell you which
    # one. The reason is kept with the name so the covering note can say "the divider was not
    # weighed because it has no blank" — a sentence design can act on.
    left_out: List[Dict[str, Any]] = []

    def _leave_out(part: Dict[str, Any], why: str) -> None:
        # ENOUGH TO JUDGE THE JOB BY, not just to name the gap. The packing gate has to
        # know whether a part it could not weigh is something SDI MAKES (unassessed
        # evidence about what kind of job this is) or something bought that rides along —
        # a record holding only name and reason forced that call to be a guess.
        try:
            from bought_in_policy import is_bought_in as _bi        # noqa: PLC0415
            _bought = bool(_bi(part))
        except Exception:                                            # noqa: BLE001
            _bought = False
        left_out.append({"part_number": part.get("part_number"),
                         "description": part.get("description"), "reason": why,
                         "material": part.get("normalized_material"),
                         "bought_in": _bought,
                         "is_assembly": bool(part.get("is_assembly_parent")
                                             or (part.get("route_context") or {}).get(
                                                 "is_assembly_parent")
                                             or part.get("is_sub_assembly"))})

    for part in parts or ():
        if not isinstance(part, dict) or part.get("_commercial_placeholder"):
            continue
        # AN ASSEMBLY IS NOT A THING YOU PUT IN A BOX. Its material is already counted on its
        # children, so weighing it too counts the same steel twice — and its "blank" is not a
        # blank at all: it is the envelope the finished unit occupies.
        #
        # 12349-02 shipped on that. The description read "largest panel 2026 x 1144mm, about
        # 446 kg total" for seven feeders whose drawings mass about 28 kg each — 196 kg, not
        # 446 — and 2026 mm is the install width, not a part anybody wraps. Both the
        # packaging and the delivery indication were asked against that phantom, and they are
        # the two largest bought-in lines on the job.
        if part.get("is_assembly_parent") or (part.get("route_context") or {}).get(
                "is_assembly_parent") or part.get("is_sub_assembly"):
            skipped += 1
            _leave_out(part, "an assembly, weighed through its children")
            continue
        L, W = _num(part.get("blank_length_mm")), _num(part.get("blank_width_mm"))
        T = _num(part.get("normalized_thickness_mm"))
        if not (L and W and T):
            skipped += 1
            _leave_out(part, "no blank size and gauge recorded"
                       if not T else "no blank size recorded")
            continue
        # A BLANK THAT FITS NO SHEET THE MATERIAL IS STOCKED IN IS NOT A BLANK. The same
        # test that stops such a figure being PRICED should stop it being SHIPPED — a
        # bounding box promoted onto a leaf inflates a weight exactly as it inflates a cost,
        # and this is the quieter of the two because nobody checks a haulage description.
        try:
            from blank_credibility import fits_a_stock_sheet
            if not fits_a_stock_sheet(L, W, part.get("normalized_material")):
                phantom += 1
                skipped += 1
                _leave_out(part, f"blank {L:.0f} × {W:.0f} mm fits no stock sheet")
                continue
        except Exception:                                            # noqa: BLE001
            pass
        counted += 1
        shippable.append(part)
        # THE WORKING, KEPT. A shipment description is a sentence somebody prices, and when
        # it says "about 49 kg" for a 2.3 kg tray there is no way to see which part put the
        # 46 kg in. Every counted part is recorded with what it contributed, so the covering
        # note can print the arithmetic and a phantom names itself.
        _line_kg = ((_num(part.get("blank_length_mm")) or 0) / 1000.0
                    * (_num(part.get("blank_width_mm")) or 0) / 1000.0
                    * (_num(part.get("normalized_thickness_mm")) or 0) / 1000.0
                    * _density_for(part.get("normalized_material")))
        try:
            per = max(1, int(part.get("quantity") or 1))
        except (TypeError, ValueError):
            per = 1
        volume_m3 = (L / 1000.0) * (W / 1000.0) * (T / 1000.0)
        weight_kg += volume_m3 * _density_for(part.get("normalized_material")) * per
        longest, widest = max(longest, L), max(widest, W)
        counted_parts.append({
            "part_number": part.get("part_number"), "length_mm": L, "width_mm": W,
            "thickness_mm": T, "material": part.get("normalized_material"),
            "density_kg_m3": _density_for(part.get("normalized_material")),
            "per_assembly": per, "kg_each": round(_line_kg, 3),
            "kg_in_order": round(_line_kg * per * qty, 3),
        })
    out = {
        "schema": SCHEMA, "order_quantity": qty,
        "unit_weight_kg": round(weight_kg, 2) if weight_kg else None,
        "order_weight_kg": round(weight_kg * qty, 2) if weight_kg else None,
        "largest_part_mm": [longest, widest] if longest and widest else None,
        "parts_measured": counted, "parts_without_a_blank": skipped,
        # Counted separately from an ordinary miss: a part left out because its recorded
        # blank fits no stock sheet is a defect upstream, not a gap in the drawings.
        "parts_with_an_impossible_blank": phantom,
        # What the weight and the envelope are actually made of, per part.
        "counted_parts": counted_parts,
        # And what it is NOT made of. A weight that comes up short is a part that was left
        # out; this says which, and why, so the shortfall is readable instead of arguable.
        "left_out_parts": left_out,
        "shape": None,
    }
    # THE SHIPMENT AS CARTONS AND PALLETS, counted deterministically from the same blanks. It
    # turns "about 34 kg" into "about 34 kg, ~3 cartons on 1 pallet" — a better question whoever
    # answers it, and an outright count the moment a carton/pallet rate is on the catalogue. Its
    # one assumption (the packing factor) is declared on the plan, not hidden in this total.
    try:
        import palletising
        # THE SAME PARTS THE WEIGHT WAS BUILT FROM. Handing this the unfiltered list left the
        # carton and pallet count resting on the assembly envelope the weight had just been
        # cleared of — half a fix, and the half nobody reads.
        out["shipment"] = palletising.plan_shipment(shippable, order_qty)
    except Exception:                                                # noqa: BLE001
        out["shipment"] = None
    return out


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


import re as _re

# "PACK OF 1000", "PK OF 50", "BOX OF 250" — the catalogue's own way of saying the price
# is for a multiple. Nothing else is treated as a pack: a size like "18 x 24 x 100G" is a
# dimension, and reading dimensions as quantities is how a bag becomes a thousand bags.
_PACK_OF = _re.compile(r"\b(?:PACK|PK|BOX|BAG|ROLL)\s+OF\s+(\d{2,6})\b", _re.IGNORECASE)


def _consumable_price(code: str) -> Optional[Dict[str, Any]]:
    """What ONE of this consumable costs, from SDI's own priced sources. Never raises,
    never invents — None is an honest answer and the caller says which code it was.

    THE CATALOGUE SELLS PACKS AND THE METHOD COUNTS EACHES. PACK13 is on UDEF at £29.68 —
    "POLY BAG 18 x 24 x 100G (PACK OF 1000)". Read as a per-bag price, a 50-off order
    carries £1,484 of poly bags: exactly the crazy number this whole area exists to stop,
    and it would have shipped wearing a real supplier's name. The pack size is stated in
    the catalogue row's own description, so it is divided out HERE, once, and the working
    says so — the caller only ever sees the price of one.
    """
    try:
        from stated_prices import system_price                        # noqa: PLC0415
        _px = system_price(code)
    except Exception:                                                 # noqa: BLE001
        return None
    if not _px or not _px.get("gbp"):
        return _px
    _m = _PACK_OF.search(str(_px.get("description") or ""))
    if _m:
        _n = int(_m.group(1))
        if _n > 1:
            _each = round(float(_px["gbp"]) / _n, 5)
            _px = dict(_px, gbp=_each, pack_of=_n, pack_gbp=float(_px["gbp"]))
    return _px


def _boxes_for(steps: Dict[Any, Any], qty: int) -> Optional[int]:
    """Howard's step rule: the count at the smallest stated threshold >= the order.
    Beyond the last stated point, None — nothing he said tells us how 2,000 pack, and a
    straight line past the last real point is invention."""
    _n, _inferred = _boxes_for_with_basis(steps, qty)
    return _n


def _boxes_for_with_basis(steps: Dict[Any, Any], qty: int):
    """(count, inferred) — inferred is True when qty is not one of the STATED points.

    Howard supplied 10, 50, 250 and 1,000 and nothing else. An order of 100 taking the
    250 step's three boxes is our reading of his rule, not his figure — it is still
    priced (a labelled inference beats a zero) and it says so, pending his answer on
    whether the counts are job-fixed or a capacity rule."""
    try:
        _pts = sorted((int(k), int(v)) for k, v in (steps or {}).items())
    except (TypeError, ValueError):
        return None, False
    if not _pts:
        return None, False
    _stated = {t for t, _ in _pts}
    for _t, _n in _pts:
        if qty <= _t:
            return _n, qty not in _stated
    return None, False


def _method_applies(order: Dict[str, Any]) -> Any:
    """Does Howard's method fit THIS job? "" when it does; the reason when it does not.

    "Every PACKAGING line invokes _method_price() without checking product type,
    dimensions, material or source job" — James, 15 Sep review. The method was stated
    for small flat-packed acrylic display goods; ungated it would bag a steel stand.
    Judged on the counted parts' material families (fact) and the unit weight (our
    declared "small" ceiling); a job with nothing measured cannot be judged, so it is
    not priced by a method nobody can check it against.
    """
    _gate = (getattr(config, "PACKING_METHOD", {}) or {}).get("applies_to") or {}
    _fams = tuple(str(f).upper() for f in (_gate.get("material_families") or ()))
    _counted = [p for p in (order.get("counted_parts") or []) if isinstance(p, dict)]
    if not _counted:
        return "no part was measured, so nothing says this job fits the stated basis"
    if _fams:
        for p in _counted:
            _m = str(p.get("material") or "").upper().replace("_", " ")
            if not any(f in _m for f in _fams):
                return (f"{p.get('part_number')} is {p.get('material')!r} — the method "
                        f"was stated for {', '.join(_fams[:3]).title()}-family display "
                        f"goods, and a job with other materials in it is not bagged and "
                        f"boxed on its say-so")
    # AND THE PARTS NOBODY COULD MEASURE STILL COUNT AS EVIDENCE. One measured acrylic
    # part beside an unmeasured fabricated leaf used to pass the gate on the strength of
    # the half that happened to have a blank — partial evidence bypassing the check, per
    # James's review. A FABRICATED leaf we could not assess means we cannot say the job
    # fits the stated basis, so the method declines and names the part. Bought-in items
    # ride along in the same bag; assembly parents are counted through their children.
    _content = tuple(str(t).upper() for t in (_gate.get("packed_content_tokens") or ()))
    for p in (order.get("left_out_parts") or []):
        if not isinstance(p, dict) or p.get("is_assembly") or p.get("bought_in"):
            continue
        # PACKED CONTENTS RIDE ALONG. The 18:21 run declined the whole method because
        # G01 — the printed graphic the holder exists to HOLD — read as "a non-plastic
        # fabricated part". A graphic, a label, an insert goes inside the bag; it cannot
        # change how the job packs. Suitability is judged from the principal structural
        # product, and only a STRUCTURAL fabricated component may veto.
        _blob = " ".join(str(p.get(k) or "") for k in
                         ("description", "part_number", "material")).upper()
        if _content and any(t in _blob for t in _content):
            continue
        _m = str(p.get("material") or "").upper().replace("_", " ")
        if _m and _fams and not any(f in _m for f in _fams):
            return (f"{p.get('part_number')} is {p.get('material')!r} (unmeasured) — a "
                    f"non-plastic structural part is on the job, whatever its blank")
        return (f"{p.get('part_number')} could not be assessed ({p.get('reason')}) — a "
                f"structural leaf nobody measured leaves the stated basis unproven")
    _max_kg = _gate.get("max_unit_weight_kg")
    _kg = order.get("unit_weight_kg")
    if _max_kg and _kg and float(_kg) > float(_max_kg):
        return (f"the unit weighs about {float(_kg):.1f} kg against the method's "
                f"{float(_max_kg):g} kg 'small goods' ceiling (an SDI Intelligence "
                f"assumption, declared in config.PACKING_METHOD)")
    return ""


def _method_price(order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Price the order's packing from the STATED METHOD and LIVE consumable prices.

    "put it into config and start to build it in... Better than 0 or crazy numbers" —
    James, 15 Sep 2026. The method (bag each, box in steps) is Howard's, held in
    config.PACKING_METHOD with his name on; the bag and box PRICES are asked of SDI's own
    priced sources at run time, so nothing is typed and nothing goes stale invisibly.

    ALL OR NOTHING. A half-priced method (bag found, box missing) would put a number on
    the sheet that is confidently short — worse than the honest zero, because nothing
    about it says "short". The failure names the code that would not price, so the fix is
    one catalogue row, not a diagnosis.
    """
    _m = getattr(config, "PACKING_METHOD", {}) or {}
    if not _m.get("enabled"):
        return None
    _no_fit = _method_applies(order)
    if _no_fit:
        return {"not_applicable": _no_fit}
    qty = int(order.get("order_quantity") or 1)
    _parts, _total, _breaks_needed = [], 0.0, []
    _inferred_note = ""
    for c in (_m.get("consumables") or []):
        _code = str(c.get("code") or "").strip()
        _px = _consumable_price(_code)
        if not _px or not _px.get("gbp"):
            return {"unpriced_consumable": _code,
                    "note": f"{_code} ({c.get('what')}) has no price in SDI's own sources — "
                            f"the packing method is counted and waiting on that one rate"}
        _gbp = float(_px["gbp"])
        if c.get("per_unit"):
            _n = int(c["per_unit"]) * qty
        else:
            _n, _inferred_step = _boxes_for_with_basis(c.get("per_order_steps") or {}, qty)
            if _n is None:
                return {"unpriced_consumable": _code,
                        "note": f"the stated box steps stop at "
                                f"{max(c.get('per_order_steps') or [0])} and this order is "
                                f"{qty} — how it packs beyond the last stated point is "
                                f"Howard's to say, not ours to extrapolate"}
            _breaks_needed = sorted(int(k) for k in (c.get("per_order_steps") or {}))
        _pk = (f", £{_px['pack_gbp']:.2f} a pack of {_px['pack_of']}"
               if _px.get("pack_of") else "")
        _parts.append((_code, c.get("what"), _n, _gbp,
                       str(_px.get("source") or "system") + _pk))
        _total += _n * _gbp
        if not c.get("per_unit") and _inferred_step:
            _inferred_note = (
                f" The {_code} count at {qty} off is INFERRED from the "
                f"{ {int(k): int(v) for k, v in (c.get('per_order_steps') or {}).items()} } "
                f"steps — Howard stated 10/50/250/1000 and nothing between; priced rather "
                f"than zeroed, pending his answer on whether the counts are job-fixed or a "
                f"capacity rule.")
    if not _parts:
        return None
    # THE SAME METHOD AT EVERY STATED BREAK, so the break table divides real order costs
    # rather than scaling this order's linearly — the boxes are a step, not a rate.
    _at: Dict[int, float] = {}
    # QTY 1 IS ALWAYS ON THE SHEET'S VECTOR (the break header opens at 1 as a sanity
    # anchor), so the method answers for it too: one bag, and the below-first-step box
    # count — otherwise the 1-off column would show the RUN's order cost divided by one.
    for _q in sorted(set([1] + list(_breaks_needed))):
        _t = 0.0
        for c in (_m.get("consumables") or []):
            _code = str(c.get("code") or "").strip()
            _gbp = next((g for cd, _w, _nn, g, _s in _parts if cd == _code), 0.0)
            _t += (_gbp * int(c["per_unit"]) * _q if c.get("per_unit")
                   else _gbp * (_boxes_for(c.get("per_order_steps") or {}, _q) or 0))
        _at[_q] = round(_t, 2)
    _working = " + ".join(f"{n} x {code} ({what}) at £{g:.2f} [{src}]"
                          for code, what, n, g, src in _parts)
    return {"order_gbp": round(_total, 2), "order_gbp_at_breaks": _at,
            "inferred_step_note": _inferred_note or None,
            "source_class": "packing_method",
            "source_name": "stated_method_system_priced",
            # A STAMP THE WALKER CAN SEE — the roll-goods lesson, applied on the day it
            # was learned rather than rediscovered: without `applied`, iter_price_stamps
            # skips this block and the supplier column labels the line from nothing.
            "applied": True, "affects_total": True,
            "reproducible": True, "indicative": True,
            "method_source": (f"{_m.get('stated_by')}, stated for {_m.get('source_job')} "
                              f"on {_m.get('stated_on')}"),
            "working": _working}


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
    _method = _method_price(order) if code == "PACKAGING" else None
    _method_gap = ""
    # THE METHOD'S DECISION IS A FIELD, NOT A SENTENCE BURIED IN A NOTE. The 18:21 book
    # showed packaging at £0 with the old placeholder text and nothing anywhere said
    # whether the gate declined, a consumable failed to price, or the method never ran —
    # diagnosing it needed a grep of the JSON on the box. One structured status, printed
    # on the run log and carried to the sheet flag, so the next silent zero explains
    # itself in the two places people actually look.
    if code == "PACKAGING":
        if _method is None:
            out["method_status"] = ("method disabled in config.PACKING_METHOD"
                                    if not (getattr(config, "PACKING_METHOD", {}) or {})
                                    .get("enabled") else "method returned nothing")
        elif _method.get("not_applicable"):
            out["method_status"] = f"declined — {_method['not_applicable']}"
        elif _method.get("unpriced_consumable"):
            out["method_status"] = (f"missing rate — {_method['unpriced_consumable']} "
                                    f"has no price in SDI's own sources this run")
        else:
            out["method_status"] = "priced by the stated method"
    if _method and _method.get("not_applicable"):
        # THE METHOD KNOWS ITS OWN LIMITS. The reason it declined this job goes on the
        # line, so "£0 and silent" becomes "£0 and here is why the stated method did not
        # answer for it".
        _method_gap = (" Howard's bag-and-box method was not applied: "
                       + str(_method["not_applicable"]) + ".")
        _method = None
    if _method and _method.get("unpriced_consumable"):
        # The method exists and one rate is missing — the withheld line below says WHICH,
        # so the fix is one catalogue row rather than a diagnosis.
        _method_gap = " " + str(_method.get("note") or "")
        _method = None
    if _held is not None:
        # A HOUSE HOLD, NOT A CONFIRMED CATALOGUE PRICE. The figure is reproducible (same every
        # run, so it does not trip price_not_reproducible) but it is an INDICATIVE hold an
        # estimator entered, not a quoted rate — so it is flagged for verify and carries no
        # "firm" claim. Tim confirms or overwrites it in config.
        _order_gbp, _src = _held, {
            "source_class": "config_house_rate", "reproducible": True, "indicative": True,
            "source_name": "config.COMMERCIAL_LINE_GBP_PER_ORDER"}
    elif _method:
        # THE STATED METHOD, PRICED LIVE. Counts are Howard's, in config with his name on;
        # each consumable's price came from SDI's own sources this run. Indicative until an
        # estimator confirms the method fits this job, and the working is ON the line so
        # confirming it is reading, not reverse-engineering.
        _order_gbp = _method["order_gbp"]
        _src = {k: _method[k] for k in ("source_class", "source_name", "reproducible",
                                        "indicative", "applied", "affects_total")}
        out["order_gbp_at_breaks"] = _method.get("order_gbp_at_breaks") or {}
        out["packing_working"] = (_method.get("working") or "") +             (_method.get("inferred_step_note") or "")
        out["method_source"] = _method.get("method_source")
        if _method.get("inferred_step_note"):
            out["inferred_step"] = True
    else:
        # THE COUNT IS KEPT; THE PRICE IS WITHHELD. Asking a model to price the sentence gave
        # 12349-02 three different answers for one unchanged pack at one quantity — £424.97,
        # £175.00, £74.97 at order level. A figure that moves 5.7x cannot be sanity-checked by
        # an estimator or compared by the parity harness, so it is worse than a zero that
        # states its own question. config.COMMERCIAL_LINE_ASK_MARKET restores it; the real fix
        # is a house rate in COMMERCIAL_LINE_GBP_PER_ORDER, which is asked first and always.
        _ind = (_ask_market(description, code.title())
                if bool(getattr(config, "COMMERCIAL_LINE_ASK_MARKET", False)) else None)
        if not _ind:
            # NOTHING CAME BACK, SO NOTHING IS INVENTED — and the line still says what it
            # would have been asked, so an estimator can answer the question themselves
            # rather than rediscover it.
            _why = ("could not be priced"
                    if bool(getattr(config, "COMMERCIAL_LINE_ASK_MARKET", False))
                    else "is deliberately left at £0.00 until SDI's own rate is entered — a "
                         "market indication for this line moved 5.7x between runs of the same "
                         "job, so it is withheld rather than quoted")
            out.update({"unit_gbp": None, "order_gbp": None,
                        "estimator_input_required": True, "reason": "no_price_for_" + code.lower(),
                        # The shipment was still COUNTED. That work is the useful half and it
                        # is on the line whether or not anybody has priced it yet.
                        "shipment_counted": bool((order.get("shipment") or {}).get("pallet_count")
                                                 or (order.get("shipment") or {}).get("carton_count")),
                        "note": (f"{code.title()} {_why}.{_method_gap} The shipment was still "
                                 f"measured and counted: {description}. Price it from that, or "
                                 f"put a per-order figure in "
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
                 + (f"Packed by the stated method ({out.get('method_source')}): "
                    f"{out.get('packing_working')} = £{_order_gbp:,.2f} the order — counts "
                    f"stated, prices live from the system this run; confirm the method "
                    f"fits this job. " if out.get('packing_working') else "")
                 + f"Described as: {description}."),
    })
    return out


def _count_phrase(order: Dict[str, Any]) -> str:
    """The carton/pallet count for the description, when the shipment could be counted."""
    try:
        import palletising
        return palletising.summary_phrase(order.get("shipment") or {})
    except Exception:                                                # noqa: BLE001
        return ""


def shipment_shape(order: Dict[str, Any]) -> str:
    """"parcel" or "pallet" — what this order actually is.

    THE QUESTION DECIDED THE ANSWER, AND THE QUESTION WAS ALWAYS A PALLET.

    Both descriptions read "a pallet ... palletised haulage" whatever the order was, so a
    haulier was asked to price a pallet for 11908-21: one sunglasses tray, 400 x 390 mm and
    about 2.3 kg. It came back GBP 95 packaging + GBP 65 delivery — 64% of a GBP 249 unit
    against GBP 3.74 of MDF. The lookup did not invent that; it answered the question it was
    asked, correctly, and the question was wrong. Same shape as 12349's 2026 mm envelope.

    palletising has counted cartons and pallets all along and nothing consulted it. One
    carton that a person can lift and a courier will take is a parcel; anything more is a
    pallet. The limits are palletising's, not a second set of numbers here.
    """
    plan = order.get("shipment") or {}
    cartons, pallets = plan.get("carton_count"), plan.get("pallet_count")
    weight = _num(order.get("order_weight_kg")) or 0.0
    try:
        from palletising import _limits
        max_parcel_kg = float(_limits().get("carton_max_weight_kg") or 25.0)
    except Exception:                                            # noqa: BLE001
        max_parcel_kg = 25.0
    # Oversize for a carton is a pallet however light it is: a 2 m panel does not go by
    # courier because it weighs nothing.
    if plan.get("oversize_for_carton"):
        return "pallet"
    if cartons is not None and cartons <= 1 and weight and weight <= max_parcel_kg:
        return "parcel"
    if cartons is None and pallets is None and weight and weight <= max_parcel_kg:
        # No plan (no carton catalogue yet) but a weight a person can carry.
        return "parcel"
    return "pallet"


def packaging_line(parts: List[Dict[str, Any]], order_qty: Any) -> Dict[str, Any]:
    order = describe_order(parts, order_qty)
    size = order.get("largest_part_mm")
    where = (f"largest panel {size[0]:.0f} x {size[1]:.0f}mm, " if size else "")
    weight = (f"about {order['order_weight_kg']:.0f} kg total, "
              if order.get("order_weight_kg") else "")
    count = _count_phrase(order)
    count = (f"{count}, " if count else "")
    shape = shipment_shape(order)
    what = ("a carton and protective packing" if shape == "parcel"
            else "protective packaging and a pallet")
    return _line("PACKAGING", order,
                 f"{what[0].upper()}{what[1:]} for {order['order_quantity']} "
                 f"flat-packed display assemblies, {where}{weight}{count}UK trade, per order",
                 "PACKAGING")


def delivery_line(parts: List[Dict[str, Any]], order_qty: Any) -> Dict[str, Any]:
    order = describe_order(parts, order_qty)
    weight = (f"about {order['order_weight_kg']:.0f} kg" if order.get("order_weight_kg")
              else "a part pallet")
    ship = order.get("shipment") or {}
    pallets = ship.get("pallet_count")
    on = (f" on {pallets} pallet(s)" if pallets else "")
    shape = shipment_shape(order)
    return _line(
        "DELIVERY", order,
        (f"Next-day courier parcel of {weight} for {order['order_quantity']} display "
         f"assemblies, one UK mainland delivery, per order" if shape == "parcel"
         else f"Palletised haulage of {weight}{on} for {order['order_quantity']} display "
              f"assemblies, one UK mainland delivery, per order"),
        "DELIVERY")


def collect_lines(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every commercial line on the job, harvested from wherever the parts live.

    summary["commercial_lines"] was READ in two places — the sweep's freight repricing
    and the break table — and WRITTEN nowhere: the line only ever existed on its part
    stub. So the break table fell back to the flat per-unit figure (£31.57 in every
    column of the 17:56 book) and the sweep's freight hand-down never once had data.
    One harvester, called by both readers, so a line minted anywhere on the record is a
    line everywhere the record is read.
    """
    out: List[Dict[str, Any]] = []
    seen: set = set()

    def _scan(plist):
        for p in plist or []:
            if not isinstance(p, dict):
                continue
            cl = p.get("commercial_line")
            if isinstance(cl, dict) and cl.get("code") and cl["code"] not in seen:
                seen.add(cl["code"])
                out.append(cl)

    # anything already on the summary wins; the part records fill the gaps
    for cl in ((summary or {}).get("commercial_lines") or []):
        if isinstance(cl, dict) and cl.get("code") and cl["code"] not in seen:
            seen.add(cl["code"])
            out.append(cl)
    _scan((summary or {}).get("parts"))
    _scan(((summary or {}).get("estimate_summary") or {}).get("part_estimates"))
    return out
