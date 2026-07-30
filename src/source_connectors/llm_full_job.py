"""
source_connectors/llm_full_job.py — DRIVE the estimate from the whole-document LLM extract.

Takes the structured job from llm_full_extract.extract_full_job() and folds it into the
PRE-ESTIMATE part records (before costing), so the engine's EXISTING paths fire with the good
data instead of garbled vision geometry:
  - tube_section + cut_length  -> part["section_stock"] = {a,b,t,length_mm}  => the section/tube
    catalogue path costs by the REAL length (1342/529.8/1600/270), not a generic @1100.
  - material                   -> normalized_material  => timber/MDF no longer routed as steel.
  - weight_g                   -> stated_weight_g       => stated-weight material path (now
    trusted over garbled blanks when there is no DXF).
  - thickness_mm               -> normalized_thickness_mm.
  - is_assembly (from hierarchy) -> flagged as a sub-assembly (not a fabricated flat part).

Every touched field is tagged in review_flags as LLM-sourced (estimator to verify). This is
TRANSCRIBED data (printed on the drawing), cross-checked against the deterministic reads — not
an invented number.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

SOURCE_NAME = "llm_full_extract"
_RE_SECTION = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)")


def _clean_pn(s: Any) -> str:
    return str(s or "").strip().upper()


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_section(s: Optional[str]):
    """'30.00 x 30.00 x 1.50mm TUBE' -> (30.0, 30.0, 1.5)."""
    m = _RE_SECTION.search(str(s or ""))
    if not m:
        return None, None, None
    return _num(m.group(1)), _num(m.group(2)), _num(m.group(3))


_METAL_FAMILIES = {"MILD_STEEL", "STAINLESS_STEEL", "ALUMINIUM", "ZINTEC", "GALVANISED_STEEL"}
_NON_METAL_FAMILIES = {"TIMBER", "MDF", "PLYWOOD", "ACRYLIC", "HIPS", "PVC", "FOAMEX"}


def _norm_material(m: str) -> str:
    u = str(m or "").upper()
    if "STAINLESS" in u:
        return "STAINLESS_STEEL"
    if "MDF" in u or "VENEER" in u:                       # MRMDF, MR MDF, veneered MDF
        return "MDF"
    if "PLYWOOD" in u or "PLYWD" in u or "PLY" in u:      # PLYWOOD, MARINE PLY, BIRCH PLY
        return "PLYWOOD"
    # Solid timber / softwood species — a title block names the species (FSC PINE, SPRUCE, OAK),
    # not the generic "TIMBER"; map them all to the costable family.
    if any(t in u for t in ("PINE", "SPRUCE", "SOFTWOOD", "HARDWOOD", "TIMBER", "WOOD",
                            "OAK", "BEECH", "BIRCH", "FSC")):
        return "TIMBER"
    if "BOARD" in u:                                      # generic board / soft-touch laminate board
        return "MDF"
    if "MILD" in u or u.strip() == "STEEL":
        return "MILD_STEEL"
    if "ALUM" in u:
        return "ALUMINIUM"
    if "ACRYLIC" in u or "PERSPEX" in u:
        return "ACRYLIC"
    return str(m or "").strip()


def _rollup_quantities(job: Dict[str, Any]) -> Dict[str, int]:
    """Roll the PRINTED quantities up the hierarchy into a per-product total for every leaf part.
    The GA BOM lists top-level lines (each part or sub-assembly x qty); each sub-assembly page
    lists its children x qty. A leaf part's per-product total is:
        (its qty as a direct GA line)  +  sum over parents( child_qty x parent's GA qty ).
    All quantities are TRANSCRIBED (printed on the drawing), never computed — this only re-adds
    them the way the pack itself lays them out. Used to correct the per-part count (e.g. a tube
    the vision BOM double-counted as qty2 when the GA prints qty1)."""
    bom = job.get("bom") or []
    asms = job.get("assemblies") or []
    bom_qty: Dict[str, float] = {}
    for line in bom:
        if not isinstance(line, dict):
            continue
        pn = _clean_pn(line.get("part_number"))
        if pn:
            bom_qty[pn] = bom_qty.get(pn, 0.0) + (_num(line.get("qty")) or 1.0)
    asm_pns = {_clean_pn(a.get("part_number")) for a in asms if isinstance(a, dict)}
    totals: Dict[str, float] = {}
    # Direct GA leaf lines (a part listed on the GA that is NOT itself a sub-assembly).
    for pn, q in bom_qty.items():
        if pn not in asm_pns:
            totals[pn] = totals.get(pn, 0.0) + q
    # Children of each sub-assembly, multiplied by how many of that assembly the GA calls for.
    for a in asms:
        if not isinstance(a, dict):
            continue
        amult = bom_qty.get(_clean_pn(a.get("part_number")), 1.0) or 1.0
        for ch in (a.get("children") or []):
            if not isinstance(ch, dict):
                continue
            cpn = _clean_pn(ch.get("part_number"))
            if cpn:
                totals[cpn] = totals.get(cpn, 0.0) + (_num(ch.get("qty")) or 1.0) * amult
    return {k: int(round(v)) for k, v in totals.items() if v and v > 0}


def overlay_drawing_facts(job: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay the DETERMINISTIC drawing_facts onto the LLM job so each source covers the other's
    gaps — the responsibility for a PDF-only job. The LLM owns the hierarchy + structure; the
    deterministic reader owns the PRINTED title-block facts (per-part finish, thickness) and the
    letter-scrambled spec block the LLM misreads. Concretely: fill the LLM's null part fields with
    drawing_facts' printed values, and COMBINE the weld spec (the LLM caught 'set-down 20%',
    drawing_facts caught 'ALL WELDS TO BE TIG'). Mutates and returns job; records provenance."""
    if not (isinstance(job, dict) and job.get("found") and isinstance(facts, dict)):
        return job
    by_part = {_clean_pn(pn): d for pn, d in (facts.get("by_part") or {}).items() if isinstance(d, dict)}
    _EMPTY = (None, "", [])
    for p in (job.get("parts") or []):
        if not isinstance(p, dict):
            continue
        d = by_part.get(_clean_pn(p.get("part_number")))
        if not d:
            continue
        # HARD PRINTED FACTS: deterministic is AUTHORITATIVE where it has a value (it read the
        # exact printed value and cannot hallucinate). The LLM only fills where deterministic is
        # null. If both have a value and they DISAGREE, deterministic wins and it is flagged.
        for k in ("material", "thickness_mm", "tube_section", "cut_length_mm", "weight_g", "finish"):
            dv, lv = d.get(k), p.get(k)
            if dv in (None, ""):
                continue  # deterministic has nothing here -> keep the LLM value (gap fill)
            if lv not in _EMPTY and str(lv).strip().upper() != str(dv).strip().upper():
                p.setdefault("_merge_flags", []).append(
                    f"{k}: LLM='{lv}' vs deterministic='{dv}' — used deterministic (printed)")
            p[k] = dv
            p.setdefault("_deterministic", []).append(k)
    # Spec: COMBINE the weld line (each source has half), fill the rest from the deterministic block.
    sb = facts.get("spec_block") or {}
    spec = job.setdefault("spec", {})
    _det_weld, _llm_weld = sb.get("weld_spec"), spec.get("weld")
    if _det_weld and _llm_weld and _det_weld.strip().lower() not in _llm_weld.strip().lower():
        spec["weld"] = f"{_det_weld}; {_llm_weld}"
    elif _det_weld and not _llm_weld:
        spec["weld"] = _det_weld
    for k in ("powder_micron", "tolerances", "timber_note"):
        if not spec.get(k) and sb.get(k):
            spec[k] = sb[k]
    job["_overlay"] = "drawing_facts merged (deterministic fills LLM nulls; weld combined)"
    return job


def apply_full_job_to_pre_estimate(parts: List[Dict[str, Any]], job: Dict[str, Any]) -> Dict[str, int]:
    """Fold the LLM whole-document job into the pre-estimate part records. Non-destructive:
    fills a field only where the engine has nothing solid, EXCEPT it deliberately provides
    section_stock + stated_weight so the good paths win over garbled vision geometry.
    Returns counts of what changed."""
    out = {"material": 0, "weight": 0, "thickness": 0, "tube": 0, "assembly_flagged": 0,
           "qty": 0, "operations": 0, "inferred": 0}
    if not isinstance(job, dict) or not job.get("found") or not isinstance(parts, list):
        return out

    by_pn = {_clean_pn(p.get("part_number")): p for p in (job.get("parts") or []) if isinstance(p, dict)}
    assembly_pns = {_clean_pn(a.get("part_number")) for a in (job.get("assemblies") or []) if isinstance(a, dict)}
    qty_rollup = _rollup_quantities(job)

    for part in parts:
        if not isinstance(part, dict):
            continue
        pn = _clean_pn(part.get("part_number"))
        jp = by_pn.get(pn)

        # Sub-assembly: flag it (it is a weld/build step, not a fabricated flat part).
        if pn in assembly_pns:
            part["is_sub_assembly"] = True
            part.setdefault("review_flags", []).append(
                "LLM: sub-assembly (has its own parts page) — not a fabricated flat part")
            out["assembly_flagged"] += 1

        if not jp:
            continue
        _flagged = False
        # SOURCE WATERFALL: a DXF flat pattern (or SolidWorks native) is MEASURED truth and wins
        # on GEOMETRY. Where it exists (e.g. 12120), the LLM must NOT override the blank/section —
        # it only fills material/finish the engine lacks. The LLM drives geometry ONLY for the
        # no-DXF PDF-only parts (e.g. the M&S tender). So LLM vars can be live on every job safely.
        # Match the engine's OWN definition of DXF-backed (estimator.py:109 uses
        # geometry_source=='dxf_flat_pattern' OR dxf_augmented) plus the other DXF markers it
        # sets, so NO measured part slips through and gets overridden by the LLM.
        # SolidWorks native sits ABOVE DXF in the waterfall, so a natively-measured part is
        # treated exactly like a DXF-backed one here: the LLM must not override it.
        _dxf_backed = (
            str(part.get("geometry_source") or "").lower() in (
                "dxf_flat_pattern", "dxf", "dxf_flat", "solidworks_flat_pattern")
            or bool(part.get("dxf_augmented"))
            or bool(part.get("flat_pattern_detected"))
            or bool(part.get("dxf_source_file"))
            or bool(part.get("native_flat_pattern"))
        )
        # PER-DATUM, not per-file. A part can be in the native BOM (so its QUANTITY is
        # modelled truth) while the model gave it no blank and no material — there the LLM
        # must still be free to fill the gap. Gating all three on one flag would silence
        # the LLM on parts native never actually measured. Each datum has its own gate:
        _native_qty = bool(part.get("solidworks_native"))          # BOM count applied
        _native_material = str(part.get("material_source") or "") == "solidworks_api"

        # QUANTITY — the GA's PRINTED per-product count, rolled up the hierarchy. The vision BOM
        # sometimes double-counts a line (e.g. a tube read as qty2 when the GA prints qty1). The
        # transcribed rollup is authoritative for no-DXF parts; correct it and flag. DXF jobs keep
        # their measured/BOM count untouched.
        _roll_q = qty_rollup.get(pn)
        if _roll_q and _roll_q > 0 and not _dxf_backed and not _native_qty:
            _cur_q = _num(part.get("quantity"))
            if _cur_q is None or int(_cur_q) != _roll_q:
                part["quantity"] = _roll_q
                part.setdefault("review_flags", []).append(
                    f"qty set to {_roll_q} from GA rollup (was {_cur_q}) — printed BOM quantity")
                _flagged = True
                out["qty"] += 1

        mat = jp.get("material")
        if mat:
            _new_mat = _norm_material(mat)
            _cur_mat = str(part.get("normalized_material") or "").strip().upper()
            if not _cur_mat:
                # gap fill — engine had nothing
                part["normalized_material"] = _new_mat
                _flagged = True
                out["material"] += 1
            elif (not _dxf_backed
                  and not _native_material
                  and _new_mat in _NON_METAL_FAMILIES
                  and _cur_mat in _METAL_FAMILIES):
                # OVERRIDE a wrong metal DEFAULT. The engine defaults unknown material to mild
                # steel; on a no-DXF timber/board part the title-block material (FSC PINE, MRMDF)
                # is authoritative and a wood/board part is definitively NOT steel. Without this
                # the panels cost as steel-by-weight + metal laser and the timber path never fires.
                part.setdefault("review_flags", []).append(
                    f"material '{_cur_mat}' (engine default) overridden to '{_new_mat}' from the "
                    f"drawing title block (no DXF) — part is not steel")
                part["normalized_material"] = _new_mat
                _flagged = True
                out["material"] += 1

        wt = _num(jp.get("weight_g"))
        if wt and wt > 0 and not _num(part.get("stated_weight_g")):
            part["stated_weight_g"] = round(wt, 2)
            _flagged = True
            out["weight"] += 1

        thk = _num(jp.get("thickness_mm"))
        if thk and thk > 0 and not _num(part.get("normalized_thickness_mm")):
            part["normalized_thickness_mm"] = thk
            _flagged = True
            out["thickness"] += 1

        # Tube: real section + cut length -> section_stock so the tube path costs by the REAL
        # length. OVERRIDE any existing section_stock the engine stamped (its length is the
        # generic @1100 / garbled one); the LLM cut length is the printed truth.
        a, b, t = _parse_section(jp.get("tube_section"))
        cut = _num(jp.get("cut_length_mm"))
        if a and b and t and cut and cut > 0 and not _dxf_backed:  # DXF geometry wins; LLM drives no-DXF
            ss = part.get("section_stock")
            ss = dict(ss) if isinstance(ss, dict) else {}
            _before_len = _num(ss.get("length_mm"))
            ss.update({"a": a, "b": b, "t": t, "length_mm": cut})
            part["section_stock"] = ss
            if _before_len != cut:
                _flagged = True
                out["tube"] += 1

        if _flagged:
            part.setdefault("review_flags", []).append(
                "enriched from whole-document LLM extract (transcribed from drawing — verify)")

    out["operations"] += apply_routes_to_parts(parts, job)
    return out


def apply_routes_to_parts(parts: List[Dict[str, Any]], job: Dict[str, Any]) -> int:
    """Fold the extracted ROUTE onto the parts it names.

    These packs say a great deal out loud — POWDER COATED, ALL WELDS TO BE TIG, TAP M4 — and
    none of it reached a part record, so M&S 2085 booked no operation at all for either tube
    and GBP 2.00 of labour on a welded bracket.

    Additive only, and never subtractive: this pass cannot see what a measurement ruled out,
    and 12120 spent three commits proving how easily a fold grows back. An operation already
    on the part is left alone; a new one is added with its source recorded, so a route the
    model INFERRED is distinguishable from one the drawing stated for the rest of its life.
    """
    added = 0
    for route in (job.get("routes") or []):
        if not isinstance(route, dict):
            continue
        op = str(route.get("operation") or "").strip().lower().replace(" ", "_")
        if not op:
            continue
        # `inferred` is the model's own word for whether it read this or concluded it, and it
        # decides the source rank: a stated operation is transcription, a concluded one is
        # inference and must never outrank a measurement.
        src = "inference" if route.get("inferred") else "llm_full_extract"
        wanted = {_clean_pn(p) for p in (route.get("part_numbers") or []) if p}
        for part in parts:
            if not isinstance(part, dict) or _clean_pn(part.get("part_number")) not in wanted:
                continue
            ops = part.setdefault("textual_operations", [])
            if not isinstance(ops, list) or op in ops:
                continue
            ops.append(op)
            part.setdefault("operation_sources", {})[op] = src
            part.setdefault("review_flags", []).append(
                f"operation '{op}' {'INFERRED' if route.get('inferred') else 'read'} from the "
                f"drawing pack ({route.get('confidence') or 'confidence unstated'})"
                + (f": {route.get('notes')}" if route.get("notes") else ""))
            added += 1
    return added
