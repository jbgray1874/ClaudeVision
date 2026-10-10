"""A size printed in two units is read by what can be, and priced at that reading (D-445).

8188-08: fourteen magnets printed "50mm x 10mm x 2m". D-427 said a size in two units is a
question; D-432 priced it as printed — fourteen two-metre magnet bars, £679 of the unit — marked
it UNRESOLVED and blocked the quote. James Gray, 10 Oct: "we need to infer as best we can and
also find prices". The pack says which reading is possible.

The readings a two-unit size allows are written out — as printed, and every figure in the
smaller unit — and each is held against two yardsticks the job itself supplies:
  * LENGTH: the largest overall size the job STATES (blank_credibility.stated_job_envelope_mm)
    or, where it states none, the largest size anything made on the job MEASURES. A reading
    with a figure longer than that cannot be.
  * MASS: the heaviest weight any sheet of the pack STATES (the GA's product weight, usually).
    A purchased line whose words name a material with a known density (config
    PURCHASED_MATERIAL_WORDS, MATERIAL_DENSITY_KG_PER_M3) has a mass at each reading; a reading
    whose pieces together outweigh the heaviest thing the job states cannot be. Fourteen
    50 x 10 x 2,000 magnet bars are 70 kg and more against a 43.6 kg product; at 2 mm they are
    70 g.
Where exactly one reading survives, it is the inferred reading: the price chain is asked that
reading (SDI Live by description, then the market) while the printed description stays on the
record, the line says "read as …, because …", the mark stays UNRESOLVED and the quote stays
blocked until a person confirms. Where neither yardstick decides, nothing is inferred and D-432
stands as it was.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

import config
from extractor_patterns import size_mixing_units

_UNIT_MM = {"MM": 1.0, "CM": 10.0, "M": 1000.0}
_FIG = re.compile(r"(\d+(?:\.\d+)?)\s*(MM|CM|M)\b", re.I)
_WEIGHT = re.compile(r"WEIGHT\s*(?:\([^)]*\))?\s*[:\s]+([0-9][0-9.,]*)\s*(KG|G)\b", re.I)
_DEFAULT_WORDS = {"MAGNET": "MAGNET", "MAGNETIC": "MAGNET", "NEODYMIUM": "NEODYMIUM",
                  "FERRITE": "FERRITE", "STEEL": "MILD STEEL", "STAINLESS": "STAINLESS STEEL",
                  "ALUMINIUM": "ALUMINIUM", "ALUMINUM": "ALUMINIUM", "BRASS": "BRASS",
                  "ACRYLIC": "ACRYLIC", "PERSPEX": "ACRYLIC", "MDF": "MDF", "PLYWOOD": "PLYWOOD"}


def _num(value: Any) -> Optional[float]:
    try:
        v = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _bought(p: Dict[str, Any]) -> bool:
    return bool(p.get("is_bought_in")) or "bought_in" in {str(r).lower() for r in (p.get("page_roles") or [])}


def readings_of(mix: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The readings a two-unit size allows: as printed, and every figure in the smallest
    unit printed. Each: {label, text, figures_mm}."""
    text = str((mix or {}).get("text") or "")
    figs = [(float(m.group(1)), m.group(2).upper()) for m in _FIG.finditer(text)]
    if len(figs) < 2:
        return []
    printed = {"label": "as printed", "text": " ".join(text.split()),
               "figures_mm": [v * _UNIT_MM[u] for v, u in figs]}
    small = min((u for _, u in figs), key=lambda u: _UNIT_MM[u])
    uniform_text = _FIG.sub(lambda m: f"{m.group(1)}{small.lower()}", text)
    uniform = {"label": f"every figure in {small.lower()}", "text": " ".join(uniform_text.split()),
               "figures_mm": [v * _UNIT_MM[small] for v, _ in figs]}
    return [printed, uniform] if uniform["figures_mm"] != printed["figures_mm"] else [printed]


def measured_job_yardstick_mm(parts: Sequence[Dict[str, Any]]) -> Optional[float]:
    """The largest size anything MADE on the job measures: a flat's length or width, a stated
    blank, a section's length or cut list. Purchased lines are not a yardstick for themselves."""
    best: Optional[float] = None
    for p in parts or ():
        if not isinstance(p, dict) or _bought(p):
            continue
        cands: List[Any] = [p.get("overall_length_mm"), p.get("overall_width_mm"),
                            p.get("blank_length_mm"), p.get("blank_width_mm")]
        ng = p.get("normalized_geometry") if isinstance(p.get("normalized_geometry"), dict) else {}
        cands += [ng.get("blank_length_mm"), ng.get("blank_width_mm")]
        ss = p.get("section_stock") if isinstance(p.get("section_stock"), dict) else {}
        cands += [ss.get("length_mm")]
        cuts = [c for c in (_num(x) for x in (ss.get("cut_lengths_mm") or [])) if c]
        if cuts:
            cands.append(sum(cuts))
        for v in (_num(x) for x in cands):
            if v and (best is None or v > best):
                best = v
    return best


def stated_mass_yardstick_kg(summary: Any) -> Optional[float]:
    """The heaviest weight any sheet of the pack states, in kg — the product's, usually."""
    best: Optional[float] = None
    for pg in ((summary or {}).get("pages") or []) if isinstance(summary, dict) else []:
        if not isinstance(pg, dict):
            continue
        text = " ".join(str(pg.get(k) or "") for k in ("pypdf_text", "pdfplumber_text", "normalized_text"))
        for m in _WEIGHT.finditer(text):
            v = _num(m.group(1))
            if v is None:
                continue
            kg = v / 1000.0 if m.group(2).upper() == "G" else v
            if best is None or kg > best:
                best = kg
    return best


def job_yardstick_mm(summary: Any, parts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """{mm, basis, kg, kg_basis} — the stated envelope first, else the largest measured
    member; the heaviest stated weight. None where the job states and measures nothing."""
    try:
        from blank_credibility import stated_job_envelope_mm
        stated = stated_job_envelope_mm(summary)
    except Exception:                                                # noqa: BLE001
        stated = None
    out: Dict[str, Any] = {"mm": None, "basis": "", "kg": None, "kg_basis": ""}
    if stated:
        out.update(mm=float(stated), basis="the largest overall size the job states")
    else:
        measured = measured_job_yardstick_mm(parts)
        if measured:
            out.update(mm=float(measured), basis="the largest size anything made on the job measures")
    kg = stated_mass_yardstick_kg(summary)
    if kg:
        out.update(kg=float(kg), kg_basis="the heaviest weight any sheet of the pack states")
    return out


def density_for_purchased(description: Any) -> Optional[Dict[str, Any]]:
    """{material, kg_per_m3} for a purchased line whose words name a material with a known
    density; None where they name none, or two."""
    words = getattr(config, "PURCHASED_MATERIAL_WORDS", None) or _DEFAULT_WORDS
    dens = getattr(config, "MATERIAL_DENSITY_KG_PER_M3", {}) or {}
    text = " " + " ".join(re.sub(r"[^A-Z0-9]+", " ", str(description or "").upper()).split()) + " "
    found = {str(words[w]).upper() for w in words if f" {str(w).upper()} " in text}
    found = {m for m in found if _num(dens.get(m)) or _num(dens.get(m.replace(" ", "_")))}
    if len(found) != 1:
        return None
    m = found.pop()
    return {"material": m, "kg_per_m3": float(dens.get(m) or dens.get(m.replace(" ", "_")))}


def _impossible(reading: Dict[str, Any], yard: Dict[str, Any], qty: int,
                density: Optional[Dict[str, Any]]) -> str:
    """Why a reading cannot be, or '' where nothing refutes it."""
    figs = reading["figures_mm"]
    limit = _num(yard.get("mm"))
    if limit and max(figs) > limit:
        return (f"{reading['text']} would be {max(figs):,.0f} mm long against {limit:,.0f} mm, "
                f"{yard.get('basis')}")
    kg_limit = _num(yard.get("kg"))
    if kg_limit and density and len(figs) == 3:
        m3 = (figs[0] / 1000.0) * (figs[1] / 1000.0) * (figs[2] / 1000.0)
        kg = m3 * density["kg_per_m3"] * max(1, qty)
        if kg > kg_limit:
            return (f"{reading['text']} x {qty} would weigh about {kg:,.1f} kg as "
                    f"{density['material'].lower()} against {kg_limit:,.1f} kg, {yard.get('kg_basis')}")
    return ""


def resolve_mixed_size(part: Dict[str, Any], yardstick: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Infer the one possible reading of a part's two-unit size against the yardsticks, stamp
    it on the part, and return it; None where nothing is inferred."""
    desc = str(part.get("description") or "")
    mix = size_mixing_units(f"{desc} {part.get('part_number') or ''}")
    if not mix:
        return None
    readings = readings_of(mix)
    if len(readings) < 2:
        return None
    qty = int(_num(part.get("quantity")) or 1)
    density = density_for_purchased(desc)
    verdicts = [(r, _impossible(r, yardstick or {}, qty, density)) for r in readings]
    possible = [r for r, why in verdicts if not why]
    if len(possible) != 1:
        return None
    chosen = possible[0]
    why = "; ".join(w for r, w in verdicts if w)
    inferred = {"printed": mix["text"], "text": chosen["text"], "label": chosen["label"],
                "figures_mm": chosen["figures_mm"], "why": why,
                "yardstick": {k: yardstick.get(k) for k in ("mm", "basis", "kg", "kg_basis")}}
    part["size_reading_inferred"] = inferred
    # THE PRICE CHAIN IS ASKED THE READING; THE PRINTED WORDS STAY ON THE RECORD.
    if mix["text"] in desc:
        part["price_chain_description"] = desc.replace(mix["text"], chosen["text"])
    part.setdefault("review_flags", []).append(
        f"size read as {chosen['text']} ({chosen['label']}): {why} — priced at that reading as "
        f"a working figure; confirm")
    return inferred


def apply_size_readings(parts: Sequence[Dict[str, Any]], summary: Any) -> int:
    """Resolve every purchased line's two-unit size that the job's yardsticks can decide.
    Returns the parts stamped."""
    yard = job_yardstick_mm(summary, parts)
    if not (yard.get("mm") or yard.get("kg")):
        return 0
    n = 0
    for p in parts or ():
        if not isinstance(p, dict) or p.get("size_reading_inferred") or not _bought(p):
            continue
        if resolve_mixed_size(p, yard):
            n += 1
    return n
