"""
sheet_steel_costing.py — laser / CNC / powder / labour, reverse-engineered from the
SDI 2026 blank estimate sheet (Estimate tab: laser calc rows 38-48, CNC calc rows
51-58, powder qty cols AB-AD, rate card rows 115-146, labour engine rows 63-102).

THE KEY FINDING (powder / P.Coat):
The sheet does NOT charge £355.43 per part. £355.43 is the P.Coat *line rate £/hr*.
Every labour line — laser, fold, CNC, powder — is costed the same way:

    cost_per_unit = (rate_per_hr / throughput_parts_per_hr) * qty_per_unit
                    + (rate_per_hr/60 * setup_mins) / order_qty        # setup amortised

So powder cost per part = £355.43/hr ÷ (parts-per-hour through the powder line) × qty.
The engine's overstatement is the MISSING throughput divisor: applying £355.43/hr as if
each part takes a large slice of an hour. Supply a realistic powder-line throughput and
it falls into line. (The powder QTY calc below gives kg of powder by area — that's a
separate material/coverage figure; in the template it isn't even wired into the cost.)
"""
from __future__ import annotations
from typing import Optional

# ---- rate card (rows 115-146): name -> (£/hr, setup_mins, dept_code) -----------------
RATE_CARD = {
    "Assemble/pack (Acrylic)": (25.4257, 15, "PACP"),
    "Assemble/pack (Metal)":   (28.5588, 15, "PACM"),
    "Bench Work Joinery":      (28.7350, 30, "BENC"),
    "CNC":                     (43.3575, 10, "CNC"),
    "CNC Joinery":             (64.0658, 15, "CNCJ"),
    "Diamond Polish":          (31.6024, 10, "DPOL"),
    "Dress Welds":             (28.6816, 30, "DRES"),
    "Drill (Acrylic)":         (25.1266, 30, "DRIL"),
    "Edge Banding":            (39.03,   30, "EDGE"),
    "Fold":                    (40.4678, 30, "FOLD"),
    "Glue":                    (25.4257, 30, "GLUE"),
    "Guillotine":              (31.2856, 15, "GUIL"),
    "Laser (Acrylic)":         (41.2119, 10, "LASA"),
    "Laser (Metal)":           (68.1868, 10, "LASM"),
    "Linebend":                (25.4257, 30, "LINE"),
    "Machines Joinery":        (28.7350, 30, "MC J"),
    "Manual labour (Acrylic)": (25.4257, 15, "MANA"),
    "Manual labour (Metal)":   (31.1765, 15, "MANM"),
    "Oven":                    (25.4257, 30, "OVEN"),
    "P.Coat":                  (355.43,  15, "P/C"),
    "Packing Joinery":         (28.7350, 15, "PACJ"),
}

# ---- laser cutting speed by gauge (rows 38-46): gauge_mm -> mm/sec -------------------
LASER_SPEED_BY_GAUGE = [
    (0.7, 118), (1.0, 105), (1.2, 100), (1.5, 91),
    (2.0, 75), (2.5, 60), (3.0, 55), (4.0, 45), (5.0, 28),
]
POWDER_COVERAGE_M2_PER_KG = 6.0   # AC = 6/AB in the workbook; HELD at 6 pending 5-vs-6 confirmation
POWDER_SCRAP_PERCENT = 0.04       # per James: keep at 4% (team practice; blank sheet carries none)
CNC_SPEED_MM_S = 50               # CNC fixed speed (Q col, rows 51-58)


def _laser_speed(gauge_mm: float) -> Optional[float]:
    match = None
    for g, s in LASER_SPEED_BY_GAUGE:
        if g <= gauge_mm + 1e-9:
            match = s
        else:
            break
    return match  # None if below smallest (Excel LOOKUP would #N/A)


def laser_throughput_parts_hr(gauge_mm: float, profile_mm: float, internal_mm: float = 0.0,
                              holes: int = 0, load_unload_secs: float = 6.0) -> Optional[float]:
    """Laser calc: V = load/unload + profile/speed + (internal/speed + 1s/hole); W = 3600/V."""
    speed = _laser_speed(gauge_mm)
    if not speed:
        return None
    v = load_unload_secs + (profile_mm / speed) + (internal_mm / speed + holes)  # 1s per hole
    return 3600.0 / v if v else None


def cnc_throughput_parts_hr(profile_mm: float, internal_mm: float = 0.0, holes: int = 0,
                            load_unload_secs: float = 6.0) -> float:
    """CNC calc: fixed 50 mm/s, 3 secs per hole, V = load + profile/50 + (internal/50 + 3*holes)."""
    v = load_unload_secs + (profile_mm / CNC_SPEED_MM_S) + (internal_mm / CNC_SPEED_MM_S + 3 * holes)
    return 3600.0 / v if v else 0.0


def powder_qty_kg(length_mm: float, width_mm: float, qty: float = 1.0,
                  include_scrap: bool = True) -> float:
    """Powder QTY calc: m2/part = (L*W in m) * 2 faces; kg = m2/part / coverage * qty.
    Scrap (+4%) added per team practice; the blank sheet itself has none."""
    m2 = (length_mm / 1000.0 * width_mm / 1000.0) * 2.0
    kg = (m2 / POWDER_COVERAGE_M2_PER_KG) * qty
    return kg * (1 + POWDER_SCRAP_PERCENT) if include_scrap else kg


# ---- powder pricing: line TIME (bars/hr x items/bar) + powder MATERIAL (£/kg) ----
# Powder-line spec from the production team (note, 05/06/2026):
#   track speed 2.5 m/min = 150 m/hr; bars at 470mm pitch (420mm window + 50mm gap)
#   => 319 bars/hr at standard speed. Thicker work runs slower:
#       3mm and above  -> ~1.5 m/min -> 191 bars/hr
#       8-10mm         -> 1 m/min    -> 127 bars/hr
#   Max 5 items per bar. Hang envelope 2200(L) x 1950(H) x 1350(D) mm.
#   Powder coverage 1 kg per 6 m^2 (confirms POWDER_COVERAGE_M2_PER_KG = 6 above).
POWDER_PRICE_GBP_PER_KG = 12.50        # standard (special = 16.00)
POWDER_BARS_PER_HOUR = {"standard": 319, "thick_3mm_plus": 191, "thick_8_10mm": 127}
POWDER_MAX_ITEMS_PER_BAR = 5
POWDER_HANG_LENGTH_MM = 2200.0
POWDER_HANG_HEIGHT_MM = 1950.0
POWDER_HANG_DEPTH_MM  = 1350.0
POWDER_ITEM_GAP_MM    = 50.0           # gap between items on the bar (420mm window + 50mm gap)


def powder_bars_per_hour(thickness_mm: float = None) -> int:
    """Hanging bars through the line per hour, by item thickness (line slows for thick work)."""
    if thickness_mm is not None and thickness_mm >= 8.0:
        return POWDER_BARS_PER_HOUR["thick_8_10mm"]
    if thickness_mm is not None and thickness_mm >= 3.0:
        return POWDER_BARS_PER_HOUR["thick_3mm_plus"]
    return POWDER_BARS_PER_HOUR["standard"]


def powder_items_per_bar(length_mm: float = None, width_mm: float = None) -> int:
    """How many of this item hang on one 2.2m bar (item + 50mm gap), capped at 5.
    NOTE: this is a FLAT-PART fit. A 3D welded assembly (e.g. a basket) should be
    treated as 1 per bar with its full 3D surface area — pass items_per_bar=1 and the
    real coated area from the caller. No size -> 1 (the safe, non-understating default)."""
    if not length_mm or not width_mm:
        return 1
    L, W = float(length_mm), float(width_mm)
    along_bar = min(L, W)
    if max(L, W) > POWDER_HANG_HEIGHT_MM:      # too tall to hang upright -> long side along bar
        along_bar = max(L, W)
    if along_bar > POWDER_HANG_LENGTH_MM:      # bigger than the bar -> assembly-sized, 1 per bar
        return 1
    fit = int(POWDER_HANG_LENGTH_MM // (along_bar + POWDER_ITEM_GAP_MM))
    return max(1, min(POWDER_MAX_ITEMS_PER_BAR, fit))


def powder_line_cost_per_item(thickness_mm: float = None, items_per_bar: int = 1) -> float:
    """£/item of line time = P.Coat line rate £/hr ÷ (bars/hr × items/bar).
    This is the divisor the old engine was MISSING — it charged the full £355.43/hr
    to each part. With ~319 bars/hr × up to 5 items, the real figure is pennies-to-£1."""
    bph = powder_bars_per_hour(thickness_mm)
    ipb = max(1, min(POWDER_MAX_ITEMS_PER_BAR, int(items_per_bar)))
    return RATE_CARD["P.Coat"][0] / (bph * ipb)


def powder_total_cost(length_mm: float, width_mm: float, qty: float = 1.0,
                      order_qty: float = 1.0, thickness_mm: float = None,
                      items_per_bar: int = None, coated_area_m2: float = None,
                      price_per_kg: float = None, special: bool = False) -> dict:
    """Per-unit powder cost = line time (bars/hr × items/bar) + powder material
    (coated area ÷ 6 m²/kg, + scrap). For a flat part, items/bar and coated area come
    from the bbox; for a 3D assembly, pass items_per_bar=1 and coated_area_m2."""
    price = price_per_kg if price_per_kg is not None else (16.0 if special else POWDER_PRICE_GBP_PER_KG)
    ipb = powder_items_per_bar(length_mm, width_mm) if items_per_bar is None else items_per_bar
    line_run = powder_line_cost_per_item(thickness_mm, ipb) * qty
    if coated_area_m2 is not None:
        kg = (coated_area_m2 / POWDER_COVERAGE_M2_PER_KG) * qty * (1 + POWDER_SCRAP_PERCENT)
    else:
        kg = powder_qty_kg(length_mm, width_mm, qty)          # 2-face bbox area / 6 + scrap
    material = kg * price
    rate, setup_min, _ = RATE_CARD["P.Coat"]
    setup = ((rate / 60.0) * setup_min) / max(order_qty, 1)
    return {"powder_kg": round(kg, 4), "material_gbp": round(material, 4),
            "items_per_bar": ipb, "bars_per_hour": powder_bars_per_hour(thickness_mm),
            "line_run_gbp": round(line_run, 4), "setup_amortised_gbp": round(setup, 4),
            "total_gbp_per_unit": round(material + line_run + setup, 4)}


# ---- material weight (from the same production note) ----
STEEL_KG_PER_M2_PER_MM = 7.85          # 7.85 × thickness(mm) = kg/m^2  (1.2mm -> 9.42)
PLASTIC_DENSITY_G_CM3  = {"PETG": 1.27, "ACRYLIC": 1.19, "PERSPEX": 1.19}


def steel_weight_kg(length_mm: float, width_mm: float, thickness_mm: float) -> float:
    return (length_mm / 1000.0) * (width_mm / 1000.0) * STEEL_KG_PER_M2_PER_MM * thickness_mm


def plastic_weight_kg(length_mm: float, width_mm: float, thickness_mm: float,
                      material: str = "PETG") -> float:
    """L(m) × W(m) × t(mm) × density. m²·mm = 1 litre, density in kg/litre (= g/cm³)."""
    dens = PLASTIC_DENSITY_G_CM3.get(str(material).upper(), 1.27)
    return (length_mm / 1000.0) * (width_mm / 1000.0) * thickness_mm * dens


def labour_line_cost(rate_per_hr: float, throughput_parts_hr: float, qty_per_unit: float,
                     setup_mins: float, order_qty: float) -> dict:
    """The sheet's per-unit labour value (M col). throughput is REQUIRED — its absence is
    exactly the M18 powder overstatement, so we flag rather than silently assume."""
    if not throughput_parts_hr or throughput_parts_hr <= 0:
        return {"cost_per_unit_gbp": None,
                "flag": "no throughput (parts/hr) supplied — cannot apply an hourly rate per-part"}
    run = (rate_per_hr / throughput_parts_hr) * qty_per_unit
    setup = ((rate_per_hr / 60.0) * setup_mins) / max(order_qty, 1)
    return {"run_gbp": round(run, 4), "setup_amortised_gbp": round(setup, 4),
            "cost_per_unit_gbp": round(run + setup, 4), "flag": None}


def operation_cost(op_name: str, throughput_parts_hr: float, qty_per_unit: float = 1.0,
                   order_qty: float = 1.0) -> dict:
    """Cost one operation by name from the rate card (laser/fold/powder/etc.)."""
    if op_name not in RATE_CARD:
        return {"cost_per_unit_gbp": None, "flag": f"'{op_name}' not in rate card"}
    rate, setup, dept = RATE_CARD[op_name]
    out = labour_line_cost(rate, throughput_parts_hr, qty_per_unit, setup, order_qty)
    out.update({"op": op_name, "dept": dept, "rate_per_hr": rate, "setup_mins": setup})
    return out


if __name__ == "__main__":
    # a 1.2mm part, 2186mm profile, 200mm internal, 2 holes
    tp = laser_throughput_parts_hr(1.2, 2186, 200, 2)
    print("laser throughput parts/hr:", round(tp, 1))
    print("laser cost/unit:", operation_cost("Laser (Metal)", tp, 1, 100))
    # powder the same part both faces, qty 1, at an ASSUMED 300 parts/hr line throughput
    print("powder qty kg:", round(powder_qty_kg(751, 342, 1), 4))
    print("powder cost/unit @300/hr:", operation_cost("P.Coat", 300, 1, 100))
    print("powder cost/unit @ NO throughput:", operation_cost("P.Coat", 0, 1, 100))
