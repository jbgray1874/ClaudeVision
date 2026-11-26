"""Three read-only lists built with each Live Orders run. Written 26 Nov 2026.

James (26 Nov), on the ideas list: "we should look at advancing as far as we can now that the users are engaged."
None of these write to Sage X3 or send anything.

  late_pos      Purchasing: open PO lines past their expected receipt date (and those due in the next 7 days),
                with the works orders waiting on each part - and, in the portal, chase text per supplier.
  order_lookup  Customer Services: every open sales-order line, with its customer order reference, and the works
                order(s) making it - status, due date, and whether that's after the customer's date.
  data_checks   Go-live (4 Jan): Sage X3 master data to fix - made parts with no BOM or no route, BOM components
                that aren't X3 products, route work centres Live Orders doesn't know, products with no description.
"""
import datetime as dt
from collections import defaultdict


def _d(v):
    s = str(v or "").strip()[:10]
    try:
        return dt.date.fromisoformat(s) if s else None
    except ValueError:
        for f in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                return dt.datetime.strptime(s, f).date()
            except ValueError:
                pass
    return None


def _n(v):
    try:
        return float(str(v).replace(",", "")) if str(v or "").strip() else 0.0
    except ValueError:
        return 0.0


def _iso(d):
    return d.isoformat() if d else ""


def waiting_on(wos):
    """part -> the works orders that need it (any BOM level), earliest due first."""
    out = defaultdict(list)
    for w in sorted(wos, key=lambda w: (w["due"] or dt.date.max, w["wo"])):
        for e in w.get("explode", []):
            if not out[e["comp"]] or out[e["comp"]][-1][0] != w["wo"]:
                out[e["comp"]].append((w["wo"], w["due"], w["status"]))
    return out


def late_pos(poh, wos, prods, today, soon_days=7):
    """Open PO lines late or due within soon_days, most overdue first."""
    wait = waiting_on(wos)
    out = []
    for p in poh:
        qty = _n(p.get("QTYUOM"))
        if qty <= 1e-9:
            continue
        exp = _d(p.get("EXTRCPDAT"))
        late = (today - exp).days if exp else None
        if exp and late < -soon_days:
            continue
        part = p.get("ITMREF", "")
        ws = wait.get(part, [])
        out.append(dict(po=p.get("order_no") or p.get("POHNUM", ""), line=p.get("POPLIN", ""), supplier=p.get("BPSNUM", ""),
                        part=part, des=p.get("ITMDES") or (prods.get(part) or {}).get("des", ""), qty=round(qty, 3),
                        unit=p.get("UOM", ""), expected=_iso(exp), ordered=_iso(_d(p.get("ORDDAT"))),
                        days_late=late if late is not None else None,
                        status="NODATE" if exp is None else "LATE" if late > 0 else "SOON",
                        wos=[w[0] for w in ws][:20], wos_n=len(ws), first_due=_iso(ws[0][1]) if ws else "",
                        red=sum(1 for w in ws if w[2] == "RED")))
    out.sort(key=lambda x: (x["status"] != "LATE", -(x["days_late"] or 0), x["supplier"], x["po"]))
    return out


def order_lookup(soh, wos, sug, prods, today):
    """Every open sales-order line, with the works orders making it."""
    by_line, by_order = defaultdict(list), defaultdict(list)
    for w in wos:
        if w.get("so_no"):
            by_line[(w["so_no"], w["code"])].append(w)
            by_order[w["so_no"]].append(w)
    sug_keys = {(s["so"], s["code"]) for s in sug}
    out = []
    for s in soh:
        qty = _n(s.get("QTY"))
        if qty <= 1e-9:
            continue
        so, part = s.get("order_no", ""), s.get("ITMREF", "")
        req = _d(s.get("DEMDLVDAT"))
        ws = by_line.get((so, part)) or by_order.get(so, [])
        ws = sorted(ws, key=lambda w: (w["due"] or dt.date.max, w["wo"]))
        last_due = max((w["due"] for w in ws if w["due"]), default=None)
        if ws:
            worst = "RED" if any(w["status"] == "RED" for w in ws) else "AMBER" if any(w["status"] == "AMBER" for w in ws) \
                else "GREEN"
            state = "Works order" + ("s" if len(ws) > 1 else "") + (" due after the customer's date" if req and last_due
                                                                   and last_due > req else "")
        elif (so, part) in sug_keys:
            worst, state = "", "No works order yet - on WO Suggestions"
        else:
            worst, state = "", "No works order (bought in, or from stock)"
        out.append(dict(so=so, line=s.get("SOPLIN", ""), account=s.get("BPCORD", ""), ref=s.get("CUSORDREF", ""),
                        part=part, des=s.get("ITMDES") or (prods.get(part) or {}).get("des", ""), qty=round(qty, 3),
                        unit=s.get("SAU", ""), requested=_iso(req), ordered=_iso(_d(s.get("ORDDAT"))), state=state,
                        status=worst, late=bool(req and last_due and last_due > req), overdue=bool(req and req < today),
                        wos=[[w["wo"], w["status"], _iso(w["due"]), round(w["bal"], 3)] for w in ws][:10]))
    out.sort(key=lambda x: (x["requested"] or "9999", x["so"], str(x["line"])))
    return out


def data_checks(prods, boms, routes, wcnames, limit=5000):
    """Master data to fix before go-live, worst first. Rows: [check, part, description, detail]."""
    out = []
    made = {c for c, p in prods.items() if p.get("made") or str(p.get("cat", "")).upper().startswith("FG")}
    for c in sorted(made):
        if c not in boms:
            out.append(["Made part with no BOM", c, prods[c].get("des", ""),
                        "works orders for it show RED; WO Suggestions flag it"])
    for c in sorted(made):
        if c not in routes:
            out.append(["Made part with no route", c, prods[c].get("des", ""), "no work-centre hours for it"])
    seen = set()
    for parent in sorted(boms):
        for comp, _ in boms[parent]:
            if comp not in prods and (parent, comp) not in seen:
                seen.add((parent, comp))
                out.append(["BOM component that isn't an X3 product", comp, "", f"on the BOM of {parent}"])
    if wcnames:
        bad = defaultdict(set)
        for part, ops in routes.items():
            for op in ops:
                if op[1] and op[1] not in wcnames:
                    bad[op[1]].add(part)
        for wc, parts in sorted(bad.items()):
            out.append(["Route work centre Live Orders doesn't know", wc, "",
                        f"on {len(parts)} route(s), e.g. {', '.join(sorted(parts)[:3])} - its hours show under the code"])
    for c, p in sorted(prods.items()):
        if not str(p.get("des", "")).strip():
            out.append(["Product with no description", c, "", ""])
    return out[:limit], len(out)
