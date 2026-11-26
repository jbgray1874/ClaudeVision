"""PO Suggestions - Purchasing's to-do list: what to order, how much, by when, and who it was bought from last.
Written 26 Nov 2026. James (25 Nov): "suggest them for people to raise" - start with suggestions only.

Read-only: nothing is written to Sage X3. Purchasing raise the orders in X3 as now.

For each bought-in component the open works orders need (every BOM level - the same figures as the Shortages tab):
  * To order  = needed by all open works orders - in stock - on open POs - on works orders (only if above 0)
  * Needed by = the due date of the first works order the stock and open POs can't cover (works orders in due order)
  * Lead time = typical days from order date to expected receipt on the part's X3 PO lines (median), else 14 days
  * Order by  = needed by - lead time.  Status: LATE (needed date passed), NOW (order by today or earlier),
                WEEK (order within 7 days), LATER, NODATE (no due date on the works orders)
  * Last supplier / price / currency / purchase unit / last ordered: the part's most recent X3 PO line
  * Est. value = to order x last price, only when the purchase unit is the stock unit
  * Call-off materials (sheet, powder, packing, pallets, wire, carriage) are listed and marked: they're called off
    against an agreement rather than ordered per job.
"""
import datetime as dt
import statistics
from collections import defaultdict

DEFAULT_LEAD = 14
COLS = {"part": ["product.code", "ITMREF"], "supplier": ["orderFromSupplier._id", "orderFromSupplier.code", "BPSNUM"],
        "ordered": ["orderDate", "ORDDAT"], "expected": ["expectedReceiptDate", "EXTRCPDAT"],
        "price": ["grossPrice", "GROPRI"], "cur": ["currency.code", "CUR"], "unit": ["purchaseUnit.code", "UOM"],
        "order": ["purchaseOrder.id", "POHNUM", "order_no"]}
ORDER = {"LATE": 0, "NOW": 1, "WEEK": 2, "LATER": 3, "NODATE": 4}
LABEL = {"LATE": "Late - needed already", "NOW": "Order now", "WEEK": "Order this week", "LATER": "Later",
         "NODATE": "No date"}


def _d(v):
    s = str(v or "").strip()
    if not s:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v if isinstance(v, dt.date) and not isinstance(v, dt.datetime) else v.date()
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        pass
    for f in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s[:10], f).date()
        except ValueError:
            pass
    return None


def _n(v):
    try:
        return float(str(v).replace(",", "")) if str(v or "").strip() else None
    except ValueError:
        return None


def history(rows):
    """Per part, from X3 PO lines (open and closed): the last order and the typical lead time."""
    if not rows:
        return {}
    cols = set(k for r in rows[:200] for k in r)
    c = {k: next((n for n in names if n in cols), None) for k, names in COLS.items()}
    g = lambda r, k: r.get(c[k]) if c[k] else None
    by = defaultdict(list)
    for r in rows:
        part = str(g(r, "part") or "").strip()
        if part:
            by[part].append(r)
    out = {}
    for part, rs in by.items():
        rs.sort(key=lambda r: (_d(g(r, "ordered")) or dt.date.min, str(g(r, "order") or "")))
        last = rs[-1]
        leads = [(_d(g(r, "expected")) - _d(g(r, "ordered"))).days for r in rs
                 if _d(g(r, "expected")) and _d(g(r, "ordered"))]
        leads = [x for x in leads if 0 <= x <= 365]
        out[part] = dict(supplier=str(g(last, "supplier") or ""), price=_n(g(last, "price")), cur=str(g(last, "cur") or ""),
                         unit=str(g(last, "unit") or ""), last_order=_d(g(last, "ordered")),
                         lead=round(statistics.median(leads)) if leads else None, lead_n=len(leads),
                         orders=len({str(g(r, "order") or "") for r in rs}))
    return out


def suggest(wos, stock, pos, on_wo, prods, hist, today, call_off=()):
    """The suggestions, most urgent first. wos: the board's works orders (with 'explode' and 'due'); stock / on_wo:
    {part: qty}; pos: {part: [[expected date, qty, order], ...]}; prods: {part: {des, unit}}; hist: history()."""
    demand = defaultdict(list)
    for w in wos:
        for e in w.get("explode", []):
            if e["make"] == "Purchased" and e["need"] > 1e-9:
                demand[e["comp"]].append((w["due"], e["need"], w["wo"], e["des"]))
    out = []
    for comp, ev in demand.items():
        ev.sort(key=lambda x: (x[0] or dt.date.max, x[2]))
        need = sum(x[1] for x in ev)
        st, po, wo = stock.get(comp, 0) or 0, sum(x[1] for x in pos.get(comp, [])), on_wo.get(comp, 0) or 0
        short = need - st - po - wo
        if short <= 1e-6:
            continue
        have, cum, needed_by = st + po + wo, 0.0, None
        for due, q, _, _ in ev:
            cum += q
            if cum > have + 1e-9:
                needed_by = due
                break
        h = hist.get(comp, {})
        lead = h.get("lead")
        lead_from = f"X3 PO history ({h['lead_n']} line{'s' if h.get('lead_n') != 1 else ''})" if lead is not None \
            else f"assumed {DEFAULT_LEAD} days (no X3 PO history)"
        lead = DEFAULT_LEAD if lead is None else lead
        order_by = needed_by - dt.timedelta(days=lead) if needed_by else None
        status = ("NODATE" if not needed_by else "LATE" if needed_by < today else "NOW" if order_by <= today
                  else "WEEK" if order_by <= today + dt.timedelta(days=7) else "LATER")
        unit = (prods.get(comp) or {}).get("unit", "")
        value = (round(short * h["price"], 2) if h.get("price") is not None and h.get("unit") and unit
                 and h["unit"].upper() == unit.upper() else None)
        wos_ = list(dict.fromkeys(x[2] for x in ev))
        out.append(dict(part=comp, des=(prods.get(comp) or {}).get("des") or ev[0][3] or "", short=round(short, 3),
                        unit=unit, need=round(need, 3), stock=round(st, 3), on_po=round(po, 3), on_wo=round(wo, 3),
                        next_po=next((x[0] for x in pos.get(comp, []) if x[0]), None), needed_by=needed_by,
                        order_by=order_by, lead=lead, lead_from=lead_from, status=status, label=LABEL[status],
                        call_off=comp.startswith(tuple(call_off)), supplier=h.get("supplier", ""),
                        price=h.get("price"), cur=h.get("cur", ""), pu=h.get("unit", ""), last_order=h.get("last_order"),
                        orders=h.get("orders", 0), value=value, wos=wos_, first_wo=wos_[0] if wos_ else ""))
    out.sort(key=lambda s: (ORDER[s["status"]], s["order_by"] or dt.date.max, -s["short"]))
    return out
