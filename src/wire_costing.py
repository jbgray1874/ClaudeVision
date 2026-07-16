"""
wire_costing.py — wire MATERIAL cost, reverse-engineered from the SDI 2026
blank estimate sheet (Estimate tab, wire section rows 26-30 + gauge table rows 151-159).

The template costs wire purely by GAUGE + LENGTH:
  price_per_metre = wire_rate_per_tonne / metres_per_tonne[gauge]
  cost            = price_per_metre * (length_mm / 1000) * qty * (1 + scrap)

metres_per_tonne is a physical constant per gauge (round MS wire, 7850 kg/m^3) —
verified to the integer against the template. Gauge -> stock code (WIRE1..WIRE5)
is SDI's stocked range; other gauges exist in the table but aren't stocked codes.

Lookup replicates Excel LOOKUP: the largest table gauge <= the requested gauge.

NOTE: the 2026 template rate is £1,600/tonne (was £1,500 in the engine — update it).
This module covers wire MATERIAL only. Weld labour (wire->mesh) and the mesh panel
itself (bought-in to size + bend) are costed separately.
"""
from __future__ import annotations
from typing import Optional

# gauge_mm, metres_per_tonne, stock_code  (sorted ascending by gauge)
WIRE_GAUGE_TABLE = [
    (2.0, 40550, None),
    (2.5, 25950, None),
    (3.0, 18020, "WIRE1"),
    (4.0, 10140, "WIRE2"),
    (4.5, 8010,  None),
    (5.0, 6488,  "WIRE3"),
    (6.0, 4505,  "WIRE4"),
    (8.0, 2534,  "WIRE5"),
    (10.0, 1622, None),
]

WIRE_RATE_PER_TONNE_GBP = 1600.0   # SDI 2026 template (L3). Engine currently holds 1500 — stale.
WIRE_SCRAP = 0.04                  # 4% (template col L)


def _lookup_gauge(gauge_mm: float):
    """Excel LOOKUP semantics: row with the largest table gauge <= requested."""
    match = None
    for g, mpt, code in WIRE_GAUGE_TABLE:
        if g <= gauge_mm + 1e-9:
            match = (g, mpt, code)
        else:
            break
    return match  # None if gauge below smallest (Excel would #N/A)


def wire_material_cost(gauge_mm: float, length_mm: float, qty: float = 1.0,
                       wire_rate_per_tonne: float = WIRE_RATE_PER_TONNE_GBP,
                       scrap: float = WIRE_SCRAP) -> dict:
    """One wire element. Mirrors the template's wire BOM line exactly."""
    row = _lookup_gauge(gauge_mm)
    if row is None or not length_mm or not qty:
        return {"gauge_mm": gauge_mm, "stock_code": None, "metres_per_tonne": None,
                "price_per_metre_gbp": 0.0, "kgs": 0.0, "cost_gbp": 0.0,
                "flag": "gauge below smallest stocked (2mm)" if row is None else None}
    table_gauge, mpt, code = row
    price_per_metre = wire_rate_per_tonne / mpt
    kgs = (length_mm / mpt) * qty                         # = G/I * E  (kg)
    cost = (price_per_metre / 1000.0) * length_mm * qty * (1.0 + scrap)
    return {"gauge_mm": gauge_mm, "matched_gauge_mm": table_gauge, "stock_code": code,
            "metres_per_tonne": mpt, "price_per_metre_gbp": round(price_per_metre, 4),
            "kgs": round(kgs, 4), "cost_gbp": round(cost, 4), "flag": None}


def wire_assembly_material(elements: list[dict], **kw) -> dict:
    """Sum a wire cut-list. Each element: {gauge_mm, length_mm, qty}."""
    lines = [wire_material_cost(e["gauge_mm"], e["length_mm"], e.get("qty", 1.0), **kw)
             for e in elements]
    return {"lines": lines,
            "total_kgs": round(sum(l["kgs"] for l in lines), 4),
            "total_cost_gbp": round(sum(l["cost_gbp"] for l in lines), 4)}


if __name__ == "__main__":
    # template check: 3mm x 1000mm x1 -> price/m £0.0888, kgs 0.0555, cost £0.0923
    print(wire_material_cost(3.0, 1000.0, 1.0))
