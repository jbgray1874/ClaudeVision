"""A purchased line that states a cut length is a piece cut from stock, and is priced as one (D-441).

8188-08: the parts list carries STRENGTHENER — "EXTRUSION 92: LENGTH =100mm" — twenty-four off.
D-436 made it a purchased line; the bought-in chain then prices it as quantity × the figure the
catalogue or the market gives for "EXTRUSION 92". That figure is for whatever the seller sells:
a metre, a stock length, or (for a pre-cut fitting) a piece. Twenty-four pieces of 100 mm are
2.4 m of extrusion. Charged as twenty-four of a stock length they are 24 × 3 m or more of it;
charged as twenty-four of a metre they are ten times the material. James Gray, 9 Oct: "×24 at
100 mm means 2.4 m of cut pieces, with an appropriate stock-buying allowance … must not charge
24 full stock lengths."

What this does, for a purchased line that (a) names a thing bought by the length (config
BOUGHT_IN_STOCK_BY_LENGTH_WORDS: extrusion, tube, bar, strip, trim …) and (b) states a cut
length on the line (config CUT_LENGTH_WORDS: LENGTH =100mm, 100MM LONG, L=100 …):
  * sold BY THE METRE (unit in config SECTION_PER_METRE_UOMS): the piece is its length in
    metres at the rate, plus the section cut-loss allowance (config SECTION_STOCK_POLICY);
  * sold BY THE LENGTH with the stock length stated (the unit says 3M, 6000MM, or the row's
    words do): the piece is its share of the stock length at the length's price, plus the same
    allowance, and the line says how many stock lengths the order buys;
  * sold EACH, or the unit unknown: a thing bought by the length is not bought in 100 mm
    pieces, so "each" is read as a stock length — the shop's standard stock length (config
    SECTION_STOCK_LENGTH_MIN_MM) where the row states none — as a WORKING FIGURE, and a
    manufacturing question names the unit of sale, the stock length, and what the line would
    be at the other reading. The figure is never silently 24 stock lengths and never silently
    24 metres.
A line with no stated cut length, or naming nothing bought by the length, is left alone.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Optional, Sequence

import config

_DEFAULT_STOCK_WORDS = ("EXTRUSION", "PROFILE", "TUBE", "BAR", "ROD", "STRIP", "ANGLE",
                        "CHANNEL", "SECTION", "RAIL", "TRACK", "TRIM", "EDGING", "BEAD",
                        "FLAT", "BOX SECTION", "RHS", "SHS", "CHS")
_DEFAULT_CUT_WORDS = ("LENGTH", "LGTH", "LG", "LONG", "L")
_DEFAULT_PER_M = ("M", "MTR", "METRE", "METER", "LM", "PER M", "PER METRE")
_DEFAULT_LENGTH_UOMS = ("LGTH", "LENGTH", "LEN", "PER LENGTH", "PER LGTH", "STOCK LENGTH")


def _cfg(name: str, default: Any) -> Any:
    value = getattr(config, name, None)
    return value if value else default


def _num(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def names_a_thing_bought_by_the_length(description: Any) -> bool:
    text = " " + " ".join(str(description or "").upper().replace("-", " ").split()) + " "
    return any(f" {str(w).upper()} " in text or text.startswith(" " + str(w).upper() + ":")
               for w in _cfg("BOUGHT_IN_STOCK_BY_LENGTH_WORDS", _DEFAULT_STOCK_WORDS))


def _mm(figure: str, unit: str) -> float:
    v = float(figure)
    u = (unit or "").upper()
    if u in ("M", "MTR", "METRE", "METRES"):
        return v * 1000.0
    if u == "CM":
        return v * 10.0
    return v


def stated_cut_length_mm(description: Any) -> Optional[float]:
    """The cut length a purchased line states: 'LENGTH =100mm', 'LENGTH: 100', 'L=100',
    '100MM LONG', 'x 100 LG'. None where it states none, or states two."""
    text = " ".join(str(description or "").upper().split())
    words = [str(w).upper() for w in _cfg("CUT_LENGTH_WORDS", _DEFAULT_CUT_WORDS)]
    lead = [w for w in words if len(w) > 1] + ["L"]
    found: set = set()
    unit_re = r"(MM|CM|M|MTR|METRES?)?"
    for w in lead:
        for m in re.finditer(rf"(?<![A-Z]){re.escape(w)}\.?\s*[=:]\s*(\d+(?:\.\d+)?)\s*{unit_re}(?![A-Z0-9])",
                             text):
            found.add(round(_mm(m.group(1), m.group(2) or ""), 1))
    trail = [w for w in words if w in ("LONG", "LG", "LGTH", "LENGTH")]
    for w in trail:
        # '450 LG' and '1.8M LONG' trail; 'EXTRUSION 92 LENGTH: 100' leads with the 92 before it
        for m in re.finditer(rf"(?<![\dA-Z.])(\d+(?:\.\d+)?)\s*{unit_re}\s+{re.escape(w)}"
                             rf"(?![A-Z])(?!\.?\s*[=:])", text):
            found.add(round(_mm(m.group(1), m.group(2) or ""), 1))
    found = {f for f in found if f > 0}
    return found.pop() if len(found) == 1 else None


def unit_of_sale(selected: Dict[str, Any]) -> Dict[str, Any]:
    """{kind: per_metre | per_length | each | unknown, stock_length_mm, said} from a priced
    candidate: its uom/unit field first, then 'uom=X' or 'per X' in its provenance."""
    sel = selected if isinstance(selected, dict) else {}
    meta = sel.get("metadata") if isinstance(sel.get("metadata"), dict) else {}
    said = str(sel.get("uom") or sel.get("unit") or meta.get("uom") or "").strip()
    if not said:
        prov = str(sel.get("provenance") or meta.get("provenance") or "")
        m = re.search(r"\buom=([^|\]]+)", prov) or re.search(r"\bper\s+([A-Za-z0-9.]+)", prov)
        said = m.group(1).strip() if m else ""
    up = " ".join(said.upper().replace("_", " ").split())
    out: Dict[str, Any] = {"kind": "unknown", "stock_length_mm": None, "said": said}
    if not up:
        return out
    per_m = {str(u).upper() for u in _cfg("SECTION_PER_METRE_UOMS", _DEFAULT_PER_M)}
    if up in per_m or up in ("PER METRE", "/M", "P/M"):
        out["kind"] = "per_metre"
        return out
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(MM|M|MTR)\b.*", up)
    if m:
        out["kind"], out["stock_length_mm"] = "per_length", _mm(m.group(1), m.group(2))
        return out
    if any(up == str(w).upper() or up.startswith(str(w).upper()) for w in
           _cfg("UOM_LENGTH_WORDS", _DEFAULT_LENGTH_UOMS)):
        out["kind"] = "per_length"
        m2 = re.search(r"(\d+(?:\.\d+)?)\s*(MM|M|MTR)\b", up)
        if m2:
            out["stock_length_mm"] = _mm(m2.group(1), m2.group(2))
        return out
    if up in ("EA", "EACH", "PC", "PCS", "PIECE", "NO", "NR", "OFF", "UNIT", "ITEM"):
        out["kind"] = "each"
    return out


def stock_length_in_words(text: Any) -> Optional[float]:
    """A stock length a catalogue row's own words state: '3M', '3000MM', '6 MTR', 'x 3000'."""
    t = " ".join(str(text or "").upper().split())
    found = set()
    for m in re.finditer(r"(?<![\dA-Z.])(\d+(?:\.\d+)?)\s*(MM|M|MTR)(?![A-Z])", t):
        v = _mm(m.group(1), m.group(2))
        if 1000.0 <= v <= 15000.0:
            found.add(v)
    return found.pop() if len(found) == 1 else None


def price_as_cut_piece(description: Any, selected: Dict[str, Any], unit_price_gbp: Any,
                       quantity: Any, order_quantity: Any = 1) -> Optional[Dict[str, Any]]:
    """The per-piece price of a purchased line cut from stock, or None where the line is not
    one. Returns {unit_gbp, basis, cut_length_mm, unit_of_sale, stock_length_mm,
    lengths_bought, question} — question is None where the unit of sale was read."""
    piece = stated_cut_length_mm(description)
    price = _num(unit_price_gbp)
    if not piece or not price or not names_a_thing_bought_by_the_length(description):
        return None
    qty = int(_num(quantity) or 1)
    order = int(_num(order_quantity) or 1)
    policy = _cfg("SECTION_STOCK_POLICY", {}) or {}
    waste_pct = float(policy.get("waste_factor_pct", 4.0))
    waste = 1.0 + waste_pct / 100.0
    uos = unit_of_sale(selected)
    kind, stock = uos["kind"], uos["stock_length_mm"]
    sel = selected if isinstance(selected, dict) else {}
    if not stock:
        stock = stock_length_in_words(" ".join(str(sel.get(k) or "") for k in
                                               ("item_priced", "provenance", "description")))
    total_mm = piece * qty * order
    out: Dict[str, Any] = {"cut_length_mm": piece, "unit_of_sale": kind, "said": uos["said"],
                           "stock_length_mm": None, "lengths_bought": None, "question": None,
                           "waste_factor_pct": waste_pct}
    if kind == "per_metre":
        out["unit_gbp"] = round(price * piece / 1000.0 * waste, 4)
        out["basis"] = (f"{piece:g} mm cut from stock sold by the metre at GBP {price:.2f}/m, "
                        f"{waste_pct:g}% cut loss — {qty} off is {qty * piece / 1000.0:.2f} m a unit")
        return out
    if kind == "per_length" and stock:
        out["stock_length_mm"] = stock
        out["lengths_bought"] = int(math.ceil(total_mm * waste / stock))
        out["unit_gbp"] = round(price * piece / stock * waste, 4)
        out["basis"] = (f"{piece:g} mm cut from a {stock:g} mm stock length at GBP {price:.2f} "
                        f"a length, {waste_pct:g}% cut loss — {qty * order} pieces are "
                        f"{total_mm / 1000.0:.2f} m, {out['lengths_bought']} length(s) bought")
        return out
    # EACH, A LENGTH OF UNSTATED SIZE, OR UNKNOWN: read as a stock length, as a working figure
    std = float(_cfg("SECTION_STOCK_LENGTH_MIN_MM", 3000.0))
    stock_used = stock or std
    out["stock_length_mm"] = stock_used
    out["lengths_bought"] = int(math.ceil(total_mm * waste / stock_used))
    out["unit_gbp"] = round(price * piece / stock_used * waste, 4)
    where = (f"the row states a {stock:g} mm length" if stock
             else f"the shop's standard {std:g} mm stock length")
    unit_said = f"'{uos['said']}'" if uos["said"] else "no unit of sale"
    out["basis"] = (f"{piece:g} mm cut from stock priced GBP {price:.2f} {unit_said}, read as "
                    f"a stock length ({where}), {waste_pct:g}% cut loss — WORKING FIGURE")
    out["question"] = {
        "issue": (f"{str(description or '').strip()}: a thing bought by the length, priced "
                  f"GBP {price:.2f} with {unit_said} — per piece, per metre or per stock length? "
                  f"{qty * order} × {piece:g} mm is {total_mm / 1000.0:.2f} m"),
        "assumption": (f"GBP {price:.2f} buys a stock length ({where}): GBP {out['unit_gbp']:.2f} "
                       f"a piece as a working figure, {out['lengths_bought']} length(s) for the "
                       f"order; at GBP {price:.2f} a piece the line would be GBP "
                       f"{price * qty:.2f} a unit"),
        "action": "confirm the unit of sale and the stock length; the line follows the answer",
    }
    return out
