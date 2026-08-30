"""
palletising.py — how many cartons and pallets this order is, before anyone prices them.

PACKAGING AND DELIVERY ARE ALREADY ASKED OF THE MARKET (commercial_lines.py), but the question
they ask is thin: "five 1250 x 525 assemblies, about 18 kg." A haulier's real question is how
many PALLETS that is, and a packer's is how many CARTONS — and both of those are countable from
what the engine already measured. The counting was skipped because the warehouse had not given a
box footprint (config's bays_per_box is None), and a count nobody could complete was left out
entirely. But a count with a STATED packing assumption is not the same as no count: it turns
"about 18 kg" into "about 18 kg, ~3 cartons on 1 pallet", which is a better question whoever
answers it, and an outright number the moment a carton and pallet rate are on the catalogue.

WHAT IS DETERMINISTIC AND WHAT IS ASSUMED, KEPT APART. The weight is arithmetic on the blanks
and the densities. The solid volume is arithmetic on the blanks. The step from solid volume to
PACKED volume needs one number the drawings cannot give — how much void a protective pack
carries — and that number is a named lever (PACKING_FACTOR), declared on every result, not
buried. Everything downstream of it is floor/ceil counting against config limits. So the reader
can see exactly which figure is measured and which rests on the one assumption, and tune the
assumption in one place for every job.

IT FLAGS WHAT IT CANNOT PACK RATHER THAN PACKING IT WRONGLY. A blank longer than the carton, or
wider than the pallet, is not silently crushed into a tidy count — it is called out as oversize,
because a 1250 mm panel that "fits" a 1200 mm carton in the arithmetic does not fit it on the
floor. Cartonisation of arbitrary shapes is a bin-packing problem this does not pretend to
solve; it gives a coarse, honest count good enough to pick the right haulage band and to price
against a carton/pallet catalogue, and it says so.

GENERAL BY CONSTRUCTION. It keys on blank geometry, material density and config limits — never a
customer, a job number or a filename — so a new order is counted by the same rules with no code
change. The limits live in config.PALLETISING_CONFIG with sane defaults here, so a business that
standardises on a different carton or a 1000 kg pallet changes one table and every job follows.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

SCHEMA = "palletising.v1"

# Coarse kg/m3 by family — the same order of accuracy the haulage band needs, shared in spirit
# with commercial_lines. A weight good to twenty per cent picks the right pallet count.
_DENSITY_KG_M3 = {
    "STEEL": 7850.0, "MILD STEEL": 7850.0, "STAINLESS": 7900.0, "ZINTEC": 7850.0,
    "ALUMINIUM": 2700.0,
    "ACRYLIC": 1190.0, "PERSPEX": 1190.0, "PMMA": 1190.0, "POLYCARBONATE": 1200.0,
    "PETG": 1270.0, "ABS": 1040.0, "HIPS": 1050.0, "PVC": 1400.0, "FOAMEX": 500.0,
    "MDF": 750.0, "CHIPBOARD": 650.0, "PLYWOOD": 600.0, "MELAMINE FACED CHIPBOARD": 700.0,
}
_DEFAULT_DENSITY_KG_M3 = 1200.0

# Defaults chosen to be safe and boring; every one is overridable in config.PALLETISING_CONFIG.
_DEFAULTS: Dict[str, Any] = {
    # The one assumption: how much of a protective pack is void. 0.8 => a pack is ~20% air.
    # This is the lever the whole carton/pallet count turns on, declared on every result.
    "packing_factor": 0.8,
    # A carton a person can lift and a courier will take. Internal usable dimensions, mm.
    "carton_internal_mm": [1200.0, 800.0, 600.0],
    "carton_max_weight_kg": 25.0,
    # A UK standard pallet and a conservative single-pallet weight/height a haulier accepts.
    "pallet_footprint_mm": [1200.0, 1000.0],
    "pallet_max_height_mm": 1800.0,          # includes the pallet itself
    "pallet_max_weight_kg": 500.0,
}


def _limits() -> Dict[str, Any]:
    """Config overrides on top of the defaults. Missing keys fall to the default, so a business
    can set only the pallet weight limit without restating the carton."""
    out = dict(_DEFAULTS)
    try:
        import config
        override = getattr(config, "PALLETISING_CONFIG", None) or {}
        for k, v in override.items():
            if v is not None:
                out[k] = v
    except Exception:                                                # noqa: BLE001
        pass
    return out


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


def _fit_per_layer(outer: List[float], inner: List[float]) -> int:
    """How many INNER footprints fit on one OUTER footprint, trying both orientations.

    Coarse grid nesting, not true 2D packing: floor(OL/IL) x floor(OW/IW), and the same with the
    inner rotated 90 degrees, whichever is larger. Zero means the inner is bigger than the outer
    in every orientation — an oversize the caller must handle, not paper over with a 1."""
    ol, ow = outer[0], outer[1]
    best = 0
    for il, iw in ((inner[0], inner[1]), (inner[1], inner[0])):
        if il <= ol and iw <= ow:
            best = max(best, int(math.floor(ol / il)) * int(math.floor(ow / iw)))
    return best


def _footprint_fits(blank: List[float], footprint: List[float]) -> bool:
    """Does a blank lie flat within a footprint, in either orientation?"""
    bl, bw = max(blank), min(blank)
    fl, fw = max(footprint), min(footprint)
    return bl <= fl and bw <= fw


def plan_shipment(parts: List[Dict[str, Any]], order_qty: Any) -> Dict[str, Any]:
    """The order as cartons and pallets, with the measured figures and the one assumption apart.

    Reads only what the engine already has: each part's blank, gauge, material density and
    per-assembly quantity, times the order quantity. A part with no blank contributes nothing
    and is counted as skipped, so a plan resting on two parts out of nine can be seen for what
    it is — the same discipline as describe_order.
    """
    lim = _limits()
    try:
        qty = max(1, int(order_qty))
    except (TypeError, ValueError):
        qty = 1

    weight_kg = 0.0
    solid_vol_m3 = 0.0
    longest = widest = 0.0
    counted = skipped = 0
    oversize_for_carton = oversize_for_pallet = 0

    carton_fp = lim["carton_internal_mm"][:2]
    pallet_fp = lim["pallet_footprint_mm"]

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
        n = per * qty
        vol = (L / 1000.0) * (W / 1000.0) * (T / 1000.0)
        solid_vol_m3 += vol * n
        weight_kg += vol * _density_for(part.get("normalized_material")) * n
        longest, widest = max(longest, L), max(widest, W)
        if not _footprint_fits([L, W], carton_fp):
            oversize_for_carton += 1
        if not _footprint_fits([L, W], pallet_fp):
            oversize_for_pallet += 1

    if not counted:
        # Nothing measurable to count. Say so rather than return a confident "1 carton".
        return {
            "schema": SCHEMA, "order_quantity": qty,
            "parts_measured": 0, "parts_without_a_blank": skipped,
            "order_weight_kg": None, "carton_count": None, "pallet_count": None,
            "packing_factor": lim["packing_factor"],
            "assumptions": ["No part carried a blank, so the shipment could not be counted."],
            "flags": ["shipment_not_countable"],
        }

    pf = float(lim["packing_factor"]) or 0.8
    packed_vol_m3 = solid_vol_m3 / pf

    assumptions = [
        f"Packing factor {pf:g}: a protective pack is treated as ~{(1 - pf) * 100:.0f}% void. "
        f"This is the one figure the drawings cannot give; change PALLETISING_CONFIG "
        f"['packing_factor'] to tune every job."
    ]
    flags: List[str] = []

    # ── cartons ──────────────────────────────────────────────────────────────────────
    ci = lim["carton_internal_mm"]
    carton_vol_m3 = (ci[0] / 1000.0) * (ci[1] / 1000.0) * (ci[2] / 1000.0)
    by_volume = math.ceil(packed_vol_m3 / carton_vol_m3) if carton_vol_m3 else 1
    by_weight = math.ceil(weight_kg / lim["carton_max_weight_kg"]) if lim["carton_max_weight_kg"] else 1
    carton_count: Optional[int]
    if oversize_for_carton:
        # A blank longer than the carton cannot go in one flat. These ship as flat-packed
        # stacks direct to the pallet, so cartons are not the unit and the count is withheld.
        carton_count = None
        flags.append("blank_exceeds_carton")
        assumptions.append(
            f"{oversize_for_carton} part(s) are larger than the carton "
            f"({ci[0]:.0f} x {ci[1]:.0f} mm), so the order is flat-packed onto pallets rather "
            f"than boxed; carton count does not apply.")
    else:
        carton_count = max(1, by_volume, by_weight)

    # ── pallets ──────────────────────────────────────────────────────────────────────
    by_pallet_weight = math.ceil(weight_kg / lim["pallet_max_weight_kg"]) if lim["pallet_max_weight_kg"] else 1
    if oversize_for_pallet:
        # Larger than the pallet footprint itself: a crate / oversize freight decision, not a
        # count this tool should make. One pallet-equivalent per weight band, and a loud flag.
        pallet_count = max(1, by_pallet_weight)
        flags.append("blank_exceeds_pallet")
        assumptions.append(
            f"{oversize_for_pallet} part(s) are larger than the pallet footprint "
            f"({pallet_fp[0]:.0f} x {pallet_fp[1]:.0f} mm) — this needs a crate or oversize "
            f"haulage the engine will not guess; the pallet count is a weight-only lower bound.")
    elif carton_count is None:
        # Flat-packed stacks on pallets: count by weight and by footprint-limited height.
        pallet_count = max(1, by_pallet_weight)
    else:
        per_layer = _fit_per_layer(pallet_fp, ci[:2])
        layers = int(math.floor(lim["pallet_max_height_mm"] / ci[2])) if ci[2] else 1
        per_pallet = max(1, per_layer * max(1, layers))
        by_pallet_cartons = math.ceil(carton_count / per_pallet)
        pallet_count = max(1, by_pallet_cartons, by_pallet_weight)

    return {
        "schema": SCHEMA,
        "order_quantity": qty,
        "parts_measured": counted,
        "parts_without_a_blank": skipped,
        "order_weight_kg": round(weight_kg, 2),
        "solid_volume_m3": round(solid_vol_m3, 4),
        "packed_volume_m3": round(packed_vol_m3, 4),
        "packing_factor": pf,
        "largest_blank_mm": [round(longest, 1), round(widest, 1)],
        "carton_internal_mm": ci,
        "carton_count": carton_count,
        "pallet_count": pallet_count,
        "cartons_by_volume": by_volume,
        "cartons_by_weight": by_weight,
        "assumptions": assumptions,
        "flags": flags,
    }


def summary_phrase(plan: Dict[str, Any]) -> str:
    """The count in the words that go onto the shipment description a supplier is asked to price."""
    if not plan or plan.get("carton_count") is None and plan.get("pallet_count") is None:
        return ""
    pallets = plan.get("pallet_count")
    cartons = plan.get("carton_count")
    if cartons:
        return f"~{cartons} carton(s) on {pallets} pallet(s)"
    return f"flat-packed on {pallets} pallet(s)"
