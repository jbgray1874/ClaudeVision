"""A price an estimator gave us: dated, attributed, and always second to the system.

    "where do we get the tape price? we can't hard code prices. we can log hourly throughput
     rates but we need to start understanding if these change and why."
                                                            — James Gray, SDI, 15 Sep 2026

He is right, and config.ROLL_GOODS_CATALOGUE had £4.50 written into it. That is a price in
source control: it cannot go stale visibly, nobody is told when it moves, and the first person
to notice is a customer.

THE SPLIT THIS MODULE EXISTS TO MAKE:

    how a thing is SUPPLIED     TAPE113C comes on a 10 metre roll        a packaging fact.
                                Stable for years, changes when the
                                supplier changes the product, and it
                                is not money. Config is right for it.

    what it COSTS               £4.50 a roll                             money.
                                Moves without telling anyone. Must come
                                from a priced source, carry a date, and
                                be checkable against the system.

SDI already has the priced source. price_sources.get_best_price runs the rungs — the part
system cost off Access Supply Chain, UDEF by description, historical quotes, the supplier
catalogue, and the market fallback last. The tape never asked any of them, because the answer
was sitting in config.

So: THE SYSTEM IS ASKED FIRST. A figure an estimator stated is used only where the system has
nothing, and when it is used it says so, with the name and the date on it, so an estimator
reading the sheet can see he is looking at his own six-week-old number rather than a live one.

AND WHERE BOTH ANSWER AND THEY DISAGREE, BOTH ARE REPORTED. That is the half James is really
asking for — not a better price, an understanding of when prices move and why. PLAS534 is the
live case and it has three answers already:

    £45.19   the supplier's current price, per Howard, 9 Sep
    £47.21   what our sheet charged on 15 Sep
    £49.55   the material cost on Access Supply Chain — "assume this is migrated from the
             old system", Howard's own words

Nobody can say which is right from inside the engine, and picking one silently is how the
question stops being asked. Naming the disagreement puts it in front of the person who can
settle it, which is the whole point of the review page.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _cfg() -> Dict[str, Any]:
    try:
        import config                                              # noqa: PLC0415
        return dict(getattr(config, "ESTIMATOR_STATED_PRICES", {}) or {})
    except Exception:                                              # noqa: BLE001
        return {}


def stated(code: Any) -> Optional[Dict[str, Any]]:
    """What an estimator told us this code costs, or None. Never a guess."""
    _c = str(code or "").strip().upper()
    if not _c:
        return None
    table = _cfg()
    if _c in table:
        return dict(table[_c], code=_c)
    # SAME SQUASHED MATCH AS THE ROLL CATALOGUE — one code is written three ways in a single
    # pack ("TAPE 113C" against "TAPE113C"), and a miss here is silent.
    import re                                                      # noqa: PLC0415
    _sq = re.sub(r"[^A-Z0-9]", "", _c)
    for k, v in table.items():
        if re.sub(r"[^A-Z0-9]", "", str(k).upper()) == _sq:
            return dict(v, code=str(k).upper())
    return None


def system_price(code: Any, description: Any = None) -> Optional[Dict[str, Any]]:
    """What SDI's own priced sources say, or None. Never raises into a costing pass."""
    _c = str(code or "").strip()
    if not _c and not description:
        return None
    try:
        from price_sources import PriceRequest, get_best_price      # noqa: PLC0415
        res = get_best_price(PriceRequest(kind="part_system_cost", part_code=_c,
                                          description=str(description or "") or None))
    except Exception:                                              # noqa: BLE001
        return None
    try:
        sel = (res or {}).get("selected") or {}
        gbp = sel.get("price")
        if gbp is None or float(gbp) <= 0:
            return None
        return {"gbp": float(gbp), "source": str(sel.get("source") or "system"),
                "evidence": sel.get("evidence") or {}}
    except Exception:                                              # noqa: BLE001
        return None


def resolve(code: Any, description: Any = None) -> Dict[str, Any]:
    """The price to use, where it came from, and whether the two sources disagree.

    Returns {gbp, basis, source, label, disagreement} — gbp None when nothing can answer,
    which is a withheld line and not a zero. `basis` is 'system' or 'estimator_stated'.

    `source` is the RUNG that answered — `udef_sqlserver`, `spreadsheet`, `estimator_stated`
    — as a machine name a caller can stamp and classify. It used to exist only inside the
    prose of `label`, so the one caller that needed to record which system priced the line
    had nothing to record but a sentence, and stamped a constant instead.
    """
    _sys = system_price(code, description)
    _sta = stated(code)
    out: Dict[str, Any] = {"gbp": None, "basis": None, "source": None, "label": "",
                           "disagreement": None}

    if _sys and _sta:
        _s, _e = float(_sys["gbp"]), float(_sta.get("gbp") or 0)
        # A TOLERANCE, BECAUSE ROUNDING IS NOT A DISAGREEMENT. A penny either way on a roll
        # is the same figure typed twice; ten per cent is two different facts.
        if _e > 0 and abs(_s - _e) / max(_s, _e) > 0.01:
            out["disagreement"] = (
                f"{_fmt(code)}: the system says £{_s:.2f} and "
                f"{_sta.get('by') or 'an estimator'} stated £{_e:.2f} on "
                f"{_sta.get('on') or 'an unrecorded date'}"
                + (f" for {_sta['job']}" if _sta.get("job") else "")
                + " — neither outranks the other from in here, and the difference is "
                  "whatever has happened to the price since")

    if _sys:
        # THE SYSTEM WINS WHERE IT ANSWERS. It is the thing that gets updated when a price
        # moves; a figure in config is only ever as new as the last person who edited it.
        out.update(gbp=round(float(_sys["gbp"]), 4), basis="system",
                   source=_sys["source"],
                   # THE SYSTEM'S OWN NAME FOR ITSELF IS NOT THE ESTIMATOR'S. This read
                   # "SDI system cost via udef_sqlserver" — a connector key, written for the
                   # code, put in front of the person who has to decide whether to trust the
                   # number. One module owns the translation so the sheet, the report and
                   # this sentence cannot call the same source three different things.
                   label=f"SDI system cost via {_system_name(_sys['source'])}")
        return out
    if _sta and _sta.get("gbp"):
        out.update(gbp=round(float(_sta["gbp"]), 4), basis="estimator_stated",
                   source="estimator_stated",
                   label=(f"stated by {_sta.get('by') or 'an estimator'} on "
                          f"{_sta.get('on') or 'an unrecorded date'}"
                          + (f" for {_sta['job']}" if _sta.get("job") else "")
                          + " — not a live system price, confirm it still stands"))
    return out


def _fmt(code: Any) -> str:
    return str(code or "").strip().upper() or "this code"


def _system_name(source: Any) -> str:
    """The connector's name as an estimator would say it. Never raises, never blank."""
    try:
        from price_provenance import source_system_label                # noqa: PLC0415
        return source_system_label(source) or str(source or "the system")
    except Exception:                                                   # noqa: BLE001
        return str(source or "the system")
