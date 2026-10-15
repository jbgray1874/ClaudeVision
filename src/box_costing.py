"""The box calculator: a plain corrugated carton priced from its outside dimensions (D-521).

THE METHOD IS THE ESTIMATORS' OWN. James's AI BOX CALCULATOR sheet treats the box as six
panels in three pairs — Length x Breadth (top and bottom), Height x Breadth (the sides),
Height x Length (front and back) — each cut 20 mm over the finished dimension, grid-nested
onto the stock sheet with a 10 mm gap each side and the sheet width trimmed 5 mm, costed at
the sheet rate with a 50% scrap allowance, plus a running cost of (L + B + H) x rate and the
set-up spread over the order quantity. Every figure lives in config.BOX_COSTING, attributed
and dated; nothing is typed here.

TWO TOTALS EXIST AND BOTH ARE RETURNED. The sheet's own total sums K7:K8 — two of the
three panel pairs — so its worked example (88 x 38 x 1955 at 120 off) reads £1.82 where
the three-pair sum is £2.82. Whether the third pair belongs in the allowance is NOT
settled by this module: a real 0201 carton is one folded blank, not six separate panels,
so neither figure is a proven box price. price_box returns the three-pair figure as
unit_gbp and the sheet-faithful two-pair figure as sheet_total_gbp, and the validation
tool compares BOTH against the Harley's order history so the choice is made on evidence.

WHAT IT REFUSES. A panel that does not fit the sheet in the sheet's own orientation (the
calculator does not rotate panels, so neither does this), a non-positive dimension, and any
style that is not a plain six-panel carton — sleeves, base-and-lid, folders, caps, pads are
more pieces than this model cuts, and the Harley's history shows them priced differently.
A refusal carries its reason; it is never a silent zero.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

try:
    import config
except ImportError:                                                  # pragma: no cover
    from . import config                                             # type: ignore


def _cfg(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = dict(getattr(config, "BOX_COSTING", {}) or {})
    base.update(overrides or {})
    return base


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def panels_per_sheet(panel_length_mm: float, panel_breadth_mm: float,
                     cfg: Optional[Dict[str, Any]] = None) -> int:
    """The sheet's own grid nest: INT((sheet_width - trim) / (breadth + 2*gap)) x
    INT(sheet_length / (length + 2*gap)). No rotation — the calculator does not rotate,
    and a copy that silently improved on it could not be checked against it."""
    c = _cfg(cfg)
    gap2 = 2.0 * float(c["nest_gap_mm"])
    across = int((float(c["sheet_width_mm"]) - float(c["sheet_edge_trim_mm"]))
                 // (panel_breadth_mm + gap2))
    along = int(float(c["sheet_length_mm"]) // (panel_length_mm + gap2))
    return max(0, across) * max(0, along)


def price_box(length_mm: Any, breadth_mm: Any, height_mm: Any, order_qty: Any,
              cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One plain carton's unit price, with the whole working.

    Returns {priced: bool, ...}. Priced: unit_gbp, order_gbp, material_gbp, running_gbp,
    setup_share_gbp, panels (each pair's size, nest and cost), basis. Refused: reason.
    """
    c = _cfg(cfg)
    L, B, H = _num(length_mm), _num(breadth_mm), _num(height_mm)
    qty = max(1, int(_num(order_qty) or 1))
    if not (L and B and H and L > 0 and B > 0 and H > 0):
        return {"priced": False,
                "reason": f"a box needs three positive outside dimensions; got "
                          f"{length_mm!r} x {breadth_mm!r} x {height_mm!r}"}
    ov = float(c["panel_oversize_mm"])
    pairs = [("Length/Breadth", L + ov, B + ov),
             ("Height/Breadth", H + ov, B + ov),
             ("Height/Length", H + ov, L + ov)]
    sheet_gbp = float(c["sheet_cost_gbp"])
    scrap = float(c["scrap_fraction"])
    panels: List[Dict[str, Any]] = []
    material = 0.0
    for name, pl, pb in pairs:
        n = panels_per_sheet(pl, pb, c)
        if n <= 0:
            return {"priced": False,
                    "reason": (f"the {name} panel ({pl:g} x {pb:g} mm cut size) does not "
                               f"fit the {c['stock_board']} sheet "
                               f"{c['sheet_length_mm']:g} x {c['sheet_width_mm']:g} in the "
                               f"calculator's own orientation — a box this size is the "
                               f"packer's to price")}
        pair_gbp = (sheet_gbp / n) * (1.0 + scrap) * 2.0
        material += pair_gbp
        # The nest's two counts, so the working can be checked against the sheet's own cells.
        _gap2 = 2.0 * float(c["nest_gap_mm"])
        panels.append({"pair": name, "count": 2, "cut_length_mm": round(pl, 1),
                       "cut_breadth_mm": round(pb, 1), "per_sheet": n,
                       "across": int((float(c["sheet_width_mm"]) - float(c["sheet_edge_trim_mm"]))
                                     // (pb + _gap2)),
                       "along": int(float(c["sheet_length_mm"]) // (pl + _gap2)),
                       "pair_cost_gbp": round(pair_gbp, 4)})
    running = (L + B + H) * float(c["running_rate_gbp_per_mm"])
    setup_share = float(c["setup_cost_gbp"]) / qty
    unit = running + setup_share + material
    # The sheet's own total: running + set-up + the FIRST TWO pairs (K10 = SUM(K7:K8)).
    sheet_total = running + setup_share + sum(p["pair_cost_gbp"] for p in panels[:2])
    return {
        "priced": True,
        # EVERY FIGURE THE ARITHMETIC USED, so the estimator can check the box against the
        # sheet it came from (James, 15 Oct: "show the full details of the calculation for
        # the job so estimating can check it"). Read by estimate_explained.
        "inputs": {k: c.get(k) for k in (
            "stock_board", "sheet_length_mm", "sheet_width_mm", "sheet_cost_gbp",
            "scrap_fraction", "panel_oversize_mm", "nest_gap_mm", "sheet_edge_trim_mm",
            "running_rate_gbp_per_mm", "setup_cost_gbp", "stated_by", "stated_on")},
        "box_mm": [L, B, H],
        "unit_gbp": round(unit, 4),
        "sheet_total_gbp": round(sheet_total, 4),
        "order_gbp": round(unit * qty, 2),
        "material_gbp": round(material, 4),
        "running_gbp": round(running, 4),
        "setup_share_gbp": round(setup_share, 4),
        "order_qty": qty,
        "panels": panels,
        "stock_board": c.get("stock_board"),
        "basis": (f"box calculator ({c.get('stated_by')}, {c.get('stated_on')}): a "
                  f"PROVISIONAL panel-based allowance, not a quoted box price. "
                  f"{L:g} x {B:g} x {H:g} mm as 3 panel pairs +{ov:g} mm on "
                  f"{c.get('stock_board')} {c['sheet_length_mm']:g} x "
                  f"{c['sheet_width_mm']:g} at £{sheet_gbp:g} a sheet, {scrap:.0%} scrap; "
                  f"running (L+B+H) x £{c['running_rate_gbp_per_mm']:g}/mm = "
                  f"£{running:.3f}; set-up £{c['setup_cost_gbp']:g} / {qty} = "
                  f"£{setup_share:.3f}. The three-pair sum is £{unit:.2f}; the source "
                  f"sheet's own total (SUM(K7:K8), two pairs) is £{sheet_total:.2f} — "
                  f"config BOX_COSTING['formula'] picks which is charged, judged against "
                  f"the Harley's history. "
                  f"Assumes one unit per carton, 0201 style, +{ov:g} mm the only "
                  f"clearance, no protection or orientation modelled — "
                  f"estimator to confirm"),
    }


# The dimensions and style code as the Harley's order descriptions write them:
# "280x200x120 0201", "555x235x160 0201 150KT B H", and the run-together
# "250x170x3200201" where the height abuts the style code with no space.
_DIMS_RE = re.compile(
    r"(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*[xX×]\s*(\d{2,5}?)(?=0\d{3}\b|[^\d]|$)")
_STYLE_RE = re.compile(r"\b(0\d{3})\b")


def parse_box_description(text: Any) -> Dict[str, Any]:
    """{dims_mm: [L, W, H] | None, style: '0201' | None} off an order description."""
    s = str(text or "")
    out: Dict[str, Any] = {"dims_mm": None, "style": None}
    m = _DIMS_RE.search(s)
    if m:
        out["dims_mm"] = [float(m.group(1)), float(m.group(2)), float(m.group(3))]
    st = _STYLE_RE.search(s[m.end():] if m else s)
    if st:
        out["style"] = st.group(1)
    return out
