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

# THE SAME ANSWER THE REST OF THE ENGINE USES. bought_in_policy is the union of every
# bought-in rule in the codebase, and FABRICATION_OPS is its own list of what a purchased
# component can never incur — handling and assembly deliberately excluded, because we do
# receive and fit bought-in parts. A local copy of either would be free to drift from the
# gates upstream of this one, which is exactly how a part gets refused a blank in one pass
# and given a laser in the next.
from bought_in_policy import (FABRICATION_OPS as _FABRICATION_OPS,
                              bought_in_reason as _bought_in_reason,
                              is_bought_in as _is_bought_in)

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
    # A PART ON TWO PAGES IS ONE PART.
    #
    # This summed every row sharing a part number, and the extract's `bom` is the whole pack
    # flattened — so a tube listed once in the GA's parts table and once again from its own
    # detail page's title block came out as qty 2. On 2085 both tubes did exactly that the
    # first run the rollup was able to fire at all.
    #
    # Only an explicit_bom_table row carries a PRINTED quantity. A row sourced from a title
    # block, a note or a filename tells us the part EXISTS; its qty is a default, not a count,
    # and adding it is inventing stock. So table rows sum (a part legitimately appears on more
    # than one line of a real BOM), and everything else only fills in for a part no table
    # mentioned at all.
    _fallback: Dict[str, float] = {}
    for line in bom:
        if not isinstance(line, dict):
            continue
        pn = _clean_pn(line.get("part_number"))
        if not pn:
            continue
        q = _num(line.get("qty")) or 1.0
        if str(line.get("source") or "").strip().lower() == "explicit_bom_table":
            bom_qty[pn] = bom_qty.get(pn, 0.0) + q
        else:
            _fallback[pn] = max(_fallback.get(pn, 0.0), q)
    for pn, q in _fallback.items():
        bom_qty.setdefault(pn, q)
    asm_pns = {_clean_pn(a.get("part_number")) for a in asms if isinstance(a, dict)}
    totals: Dict[str, float] = {}
    # Direct GA leaf lines (a part listed on the GA that is NOT itself a sub-assembly).
    for pn, q in bom_qty.items():
        if pn not in asm_pns:
            totals[pn] = totals.get(pn, 0.0) + q
    # Children of each sub-assembly, multiplied by how many of that assembly the GA calls for.
    #
    # A PART ALREADY COUNTED AS A GA LINE IS NOT COUNTED AGAIN AS SOMEBODY'S CHILD.
    #
    # 2085 is a single-page pack: one GA whose parts table reads 2085-01 x1, 2085-02 x1,
    # 2085-03 x1. The extract also -- correctly -- describes the top assembly as having those
    # three as its children. This loop then added the child qty on top of the GA line and
    # every part in the job came out at 2. The tubes doubled; so did the plate.
    #
    # A genuine SUB-assembly's children are not GA lines (that is what makes them children),
    # so they still roll up and still multiply. Only the echo is dropped.
    _direct = set(totals)
    for a in asms:
        if not isinstance(a, dict):
            continue
        amult = bom_qty.get(_clean_pn(a.get("part_number")), 1.0) or 1.0
        for ch in (a.get("children") or []):
            if not isinstance(ch, dict):
                continue
            cpn = _clean_pn(ch.get("part_number"))
            if cpn and cpn not in _direct:
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

    def _src(jp: Dict[str, Any], field: str) -> str:
        """Which pass produced this datum. The second (inference) pass merges into the same
        part rows as the first, marking what it filled in `field_sources`; without reading it
        back here an inferred material would reach the estimate indistinguishable from one
        printed on the drawing, which is the difference between a reading and a judgement."""
        fs = jp.get("field_sources")
        return str((fs or {}).get(field) or SOURCE_NAME)
    if not isinstance(job, dict) or not job.get("found") or not isinstance(parts, list):
        return out

    # The drawing's general notes: stated once, applying to every part that states nothing
    # of its own. Read here because nothing else in the engine reads them at all.
    _di = job.get("drawing_info") or {}
    _job_material = str(_di.get("material_general") or "").strip()
    _job_finish = str(_di.get("finish_general") or "").strip()

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

        # The family the drawing was classified into, carried onto the part record because
        # bought_in_policy uses it to decide make/buy. Without this the classification stops
        # at the extract and a tube reads as an unidentified purchase.
        _fam = str(jp.get("material_family") or "").strip().lower()
        if _fam and not part.get("material_family"):
            part["material_family"] = _fam
        if jp.get("is_bought_in"):
            part["is_bought_in"] = True
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

        # A MATERIAL STATED ONCE FOR THE WHOLE DRAWING STILL APPLIES TO EVERY PART ON IT.
        #
        # The schema asks for drawing_info.material_general and Grok returns it. Nothing in
        # the engine has ever read it -- the field appears exactly once in the whole
        # codebase, in the schema that requests it.
        #
        # 2085 is the case this exists for: the GA prints "MATERIAL: MILD STEEL" once at
        # assembly level and names no material on either tube row, so the tubes reached the
        # sheet with no material at all and could not be priced. The drawing does say what
        # they are made of. It just says it once, in the place nobody looked.
        #
        # Strictly weaker than a part-level reading: this only fills a part the row itself
        # left blank, and it never overrides. Flagged on the part, because "inherited from
        # the drawing's general note" is a different quality of evidence from "printed on
        # this row" and an estimator quoting firm needs to see which one they have.
        mat = jp.get("material")
        if not mat and _job_material:
            mat = _job_material
            if not str(part.get("normalized_material") or "").strip():
                part.setdefault("review_flags", []).append(
                    f"material '{_norm_material(_job_material)}' inherited from the drawing's "
                    f"GENERAL material note — this part's own BOM row states none")
                out["material_from_general"] = out.get("material_from_general", 0) + 1
        if mat:
            _new_mat = _norm_material(mat)
            _cur_mat = str(part.get("normalized_material") or "").strip().upper()
            if not _cur_mat:
                # gap fill — engine had nothing
                part["normalized_material"] = _new_mat
                part["material_source"] = _src(jp, "material")
                if part["material_source"] == "inference":
                    part.setdefault("review_flags", []).append(
                        f"material '{_new_mat}' INFERRED — the drawing does not print one for "
                        f"this part; verify before quoting firm")
                    out["inferred"] += 1
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

        # FINISH AND COLOUR WERE READ, PROJECTED, AND THEN DROPPED HERE.
        #
        # The extract asks for them per BOM row and Grok returns them — 2085's GA states
        # "SURFACE FINISH: POWDER COATED  COLOUR: RAL9006". project_row carried them onto the
        # LLM part row and this fold never looked at them, so they never reached
        # normalized_finish, which is exactly the field the powder gate reads. On this job the
        # gate's assembly-pointer path saved it; on a pack that states the finish per part in
        # the BOM table, the coat would simply not be costed.
        # Same for the finish: "SURFACE FINISH: POWDER COATED" printed once on the GA covers
        # every part it does not contradict. drawing_info.finish_general was equally unread.
        _fin = jp.get("finish")
        if not _fin and _job_finish:
            _fin = _job_finish
            if not str(part.get("normalized_finish") or "").strip():
                part.setdefault("review_flags", []).append(
                    f"finish '{_job_finish}' inherited from the drawing's GENERAL finish note "
                    f"— this part's own BOM row states none")
                out["finish_from_general"] = out.get("finish_from_general", 0) + 1
        if _fin and not str(part.get("normalized_finish") or "").strip():
            part["normalized_finish"] = _fin
            part["finish_source"] = _src(jp, "finish")
            _sf = part.setdefault("surface_finishes", [])
            if isinstance(_sf, list) and _fin not in _sf:
                _sf.append(_fin)
            _flagged = True
        _col = jp.get("colour")
        if _col and not str(part.get("normalized_colour") or "").strip():
            part["normalized_colour"] = _col
            _flagged = True

        wt = _num(jp.get("weight_g"))
        if wt and wt > 0 and not _num(part.get("stated_weight_g")):
            part["stated_weight_g"] = round(wt, 2)
            _flagged = True
            out["weight"] += 1

        thk = _num(jp.get("thickness_mm"))
        if thk and thk > 0 and not _num(part.get("normalized_thickness_mm")):
            part["normalized_thickness_mm"] = thk
            part["thickness_source"] = _src(jp, "thickness_mm")
            if part["thickness_source"] == "inference":
                part.setdefault("review_flags", []).append(
                    f"thickness {thk}mm INFERRED — not printed for this part; verify")
                out["inferred"] += 1
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
            ss["source"] = _src(jp, "tube_section")
            part["section_stock"] = ss
            if ss["source"] == "inference":
                part.setdefault("review_flags", []).append(
                    f"section {a}x{b}x{t} @ {cut}mm INFERRED from the views — not printed as a "
                    f"section callout; verify the stock size before quoting firm")
                out["inferred"] += 1
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
            # A MEASUREMENT ALREADY ANSWERED THIS, AND IT OUTRANKS A READING.
            #
            # Where a DXF flat pattern measured zero bend lines, `folding` was stripped and
            # the ruling recorded. This pass reads formed walls off the drawing views and
            # would put it straight back — and now that a routed operation reaches the sheet
            # whether or not the estimator costed it, putting it back means charging for it.
            #
            # Not silent, though: the model saw walls and the reader measured no bends, and
            # one of them is wrong about a part we are costing. The commonest cause is a
            # flat exported as a block, where the bend layer is real but unreadable — which
            # is worth an estimator's attention, not a quiet drop.
            _ruled = (part.get("operations_ruled_out") or {}).get(op)
            if _ruled:
                part.setdefault("review_flags", []).append(
                    f"operation '{op}' was read from the drawing pack but NOT applied: "
                    f"{_ruled}. The measurement stands. If the part does fold, the flat "
                    f"pattern is not showing its bend lines (commonly a block export) — "
                    f"check the DXF before accepting the route")
                continue
            # WE DO NOT LASER SOMETHING WE BUY.
            #
            # The rule above refuses a route a MEASUREMENT contradicts. This refuses one the
            # part's own identity contradicts, and it is the same argument: the model is
            # reading a drawing, and a drawing shows a purchased component sitting in the
            # assembly it was bought for. Nothing about that picture says SDI cuts it.
            #
            # 12552-01-01X SURVIVED TWO EARLIER GUARDS TO GET HERE. A 62012RS ball bearing,
            # 12x32x10mm. The assembly-page guard would not let it take ops from the shared
            # sheet; the borrow refusal would not give it another part's blank. This pass
            # then added laser_cutting to it anyway, stamped `inference`, and the workbook
            # billed 269 seconds of laser on 8 bearings. Two gates held and the route came in
            # through the third door.
            #
            # FABRICATION_OPS, not every operation. Handling and assembly are deliberately
            # not in that set: we do receive and fit bought-in parts and that bench time is
            # real work. Only the ops a purchased component can never incur are refused.
            #
            # Flagged, never silent — if the part is genuinely something we make and the
            # numbering says otherwise, the drawing office needs to hear it, and the estimator
            # needs to know a route was declined rather than never seen.
            if op in _FABRICATION_OPS and _is_bought_in(part):
                part.setdefault("review_flags", []).append(
                    f"operation '{op}' was read from the drawing pack but NOT applied to "
                    f"{part.get('part_number') or 'this line'}: it is a bought-in "
                    f"({_bought_in_reason(part) or 'purchased'}), and we do not "
                    f"{op.replace('_', ' ')} something we buy. If SDI does make this part, "
                    f"its part number or its page role is wrong.")
                continue
            # THE NAME IS NOT THE DECISION.
            #
            # This used to `continue` whenever the operation name was already on the part,
            # which skipped everything below it: source, sequence, department, SCOPE and
            # qty_per_unit. The operation survived and the information needed to cost it
            # correctly did not.
            #
            # That is how an assembly-level weld loses its scope. If any earlier reader has
            # already put `welding` on 12120-01-02M, this route line -- the one that says
            # scope=assembly, participants 02M/03M/101, qty_per_unit 1, sequence 40 -- was
            # discarded in full, and the workbook then had nothing to tell it the weld
            # happens once rather than once per part it names.
            #
            # Adding the name and merging its metadata are separate acts. Metadata merges by
            # setdefault, so a stronger earlier source still wins every field it filled --
            # this fills the holes it left, and never overwrites.
            ops = part.setdefault("textual_operations", [])
            if not isinstance(ops, list):
                continue
            _was_present = set(ops)
            if op not in ops:
                ops.append(op)
            part.setdefault("operation_sources", {}).setdefault(op, src)
            # THE SEQUENCE IS AN ANSWER WE ASKED FOR AND THREW AWAY.
            # The schema carries `sequence` (10, 20, 30...) and nothing read it, so the
            # workbook fell back to sorting labour rows ALPHABETICALLY by department —
            # Assemble/pack, Laser, P.Coat. That is not a route, it is a word list.
            _seq = _num(route.get("sequence"))
            if _seq is not None:
                part.setdefault("operation_sequence", {}).setdefault(op, _seq)
            # Grok's own department is kept for comparison, never used as the value: a
            # department string the workbook's rate table does not carry makes its LOOKUP
            # return 0, which costs the work at nothing and reads exactly like it was
            # never there. OP_NAME_MAP stays authoritative; a disagreement is worth seeing.
            _dept = str(route.get("department") or "").strip()
            if _dept:
                part.setdefault("operation_department_read", {}).setdefault(op, _dept)
            # SCOPE: how often the operation happens, which is NOT how many parts it names.
            # Welding three components into one bracket is one welding. The workbook has
            # been summing a per-part quantity across every part a route line names, so an
            # assembly-level weld, its dressing and the coat of the built unit were each
            # charged three times on 2085 -- GBP 6.85 of a GBP 11.14 labour figure.
            _scope = str(route.get("scope") or "").strip().lower()
            if _scope in ("part", "assembly"):
                part.setdefault("operation_scope", {}).setdefault(op, _scope)
            _qpu = _num(route.get("qty_per_unit"))
            if _qpu and _qpu > 0:
                part.setdefault("operation_qty_per_unit", {}).setdefault(op, _qpu)
            if op not in _was_present:
                part.setdefault("review_flags", []).append(
                    f"operation '{op}' {'INFERRED' if route.get('inferred') else 'read'} from "
                    f"the drawing pack ({route.get('confidence') or 'confidence unstated'})"
                    + (f": {route.get('notes')}" if route.get("notes") else ""))
                added += 1
    return added
