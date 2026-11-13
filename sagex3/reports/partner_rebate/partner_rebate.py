"""Customer partnership rebate calculator (REP-23) - FINANCE ONLY.

The agreement's figures (bands, rates, baseline, caps) are commercially confidential: they are read
from a parameters file kept OUT of git (default: $PARTNER_REBATE_PARAMS). This module only holds the
arithmetic, which follows the agreement's wording:
  * progressive tiered rebate - each rate applies only to revenue inside its band (marginal);
  * year-end performance bonus - a flat rate on qualifying revenue above the agreed baseline;
  * referral bonus - per introduced customer: goods rate x goods + services rate x separately
    invoiced design services, capped per customer, no overall cap; first 12 months from the
    customer's first qualifying invoice.
Amounts are kept to the penny (the agreement: "actual annual reconciliation should use full-precision
values to pence"). Run it with --check to prove it against the worked examples in the agreement.
"""
import argparse
import json
import os
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

D = Decimal


def pence(x):
    return D(x).quantize(D("0.01"), ROUND_HALF_UP)


def load(path=None):
    p = Path(path or os.environ.get("PARTNER_REBATE_PARAMS", ""))
    if not p.is_file():
        raise SystemExit("Parameters file not found - set PARTNER_REBATE_PARAMS (finance-only, not in git)")
    return json.loads(p.read_text())


def tiered(revenue, bands, above_top=None):
    """bands: [[upper limit, rate %], ...] in order. Revenue above the last limit earns `above_top` %
    (the agreement leaves this to be documented - None means it earns nothing and is flagged)."""
    revenue, lower, total, lines = D(str(revenue)), D(0), D(0), []
    for upper, rate in bands:
        upper, rate = D(str(upper)), D(str(rate))
        inside = max(D(0), min(revenue, upper) - lower)
        if inside:
            total += inside * rate / 100
            lines.append((lower, upper, inside, rate, pence(inside * rate / 100)))
        lower = upper
    excess = max(D(0), revenue - lower)
    if excess and above_top is not None:
        total += excess * D(str(above_top)) / 100
        lines.append((lower, None, excess, D(str(above_top)), pence(excess * D(str(above_top)) / 100)))
    return pence(total), lines, excess


def bonus(revenue, baseline, rate):
    return pence(max(D(0), D(str(revenue)) - D(str(baseline))) * D(str(rate)) / 100)


def referral(goods, design, goods_rate, design_rate, cap):
    calc = pence(D(str(goods)) * D(str(goods_rate)) / 100 + D(str(design)) * D(str(design_rate)) / 100)
    return calc, min(calc, D(str(cap)))


def annual(revenue, p):
    t, lines, excess = tiered(revenue, p["bands"], p.get("above_top_rate"))
    b = bonus(revenue, p["baseline"], p["bonus_rate"])
    return dict(tiered=t, bonus=b, total=t + b, lines=lines, unpriced_excess=excess if p.get("above_top_rate") is None else 0)


def check(p):
    """Every worked figure in the agreement. The agreement rounds the tiered rebate and the bonus to the
    pound separately and adds them (so a pound-rounded example can differ from the exact pence figure by under £1)."""
    ok = True
    for revenue, want_t, want_b, want_total in p["examples"]["annual"]:
        r = annual(revenue, p)
        whole = lambda x: int(D(x).quantize(D(1), ROUND_HALF_UP))      # the PDF rounds each part to the pound
        got = (whole(r["tiered"]), whole(r["bonus"]), whole(r["tiered"]) + whole(r["bonus"]))
        good = got == (want_t, want_b, want_total)
        ok &= good
        print(f"annual {revenue:>12,}: tiered {r['tiered']:>12,} bonus {r['bonus']:>10,} total {r['total']:>12,}"
              f"  {'OK' if good else 'DIFFERS from ' + str((want_t, want_b, want_total))}")
    for goods, design, want_calc, want_pay in p["examples"]["referral"]:
        calc, pay = referral(goods, design, p["referral_goods_rate"], p["referral_design_rate"], p["referral_cap"])
        good = (int(calc.quantize(D(1), ROUND_HALF_UP)), int(D(pay).quantize(D(1), ROUND_HALF_UP))) == (want_calc, want_pay)
        ok &= good
        print(f"referral goods {goods:>10,} design {design:>10,}: calc {calc:>10,} payable {pay:>10,}  {'OK' if good else 'DIFFERS'}")
    print("ALL AGREE" if ok else "SOME DIFFER")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--params")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revenue", type=float, help="annual qualifying revenue to calculate")
    a = ap.parse_args()
    p = load(a.params)
    if a.check:
        check(p)
    if a.revenue is not None:
        r = annual(a.revenue, p)
        for lo, hi, inside, rate, val in r["lines"]:
            print(f"  {lo:>12,.0f} - {('top' if hi is None else f'{hi:,.0f}'):>12}: {inside:>14,.2f} x {rate}% = {val:>12,}")
        print(f"tiered {r['tiered']:,}  bonus {r['bonus']:,}  total {r['total']:,}"
              + (f"  (NOTE {r['unpriced_excess']:,} above the top band has no agreed rate)" if r["unpriced_excess"] else ""))
