"""A part's blank, read off the part's OWN detail sheet.

0359342 is the job this exists for. Its parts were bound to their parent's parts list rather
than to their own drawing (fixed in part_index), so nothing ever read a dimension off a detail
sheet — and geometry_inference handed every part a category-default envelope instead:

    350 x 250   anything whose name contains PLATE / BASE / TRAY / SHELF / TIER
    400 x 300   anything whose name contains PANEL / BACK / FRONT / SIDE / DOOR

Those envelopes then drove the nest, the laser time and the coated area. Seven of eight board
panels on this job nested from 400 x 300 against real printed sizes up to 1680 x 560, which is
an UNDER-charge of between three and nine times on the board — the direction nobody notices. The
sizes were on the sheets the whole time: MBY434 is Ø24 x 2 on p26, MBY439 is 1578 x 188 x 2 on
p28, JAE826 is 1680 x 560 x 18 on p14.

WHAT THIS MODULE IS AND IS NOT. It is a stamper, on the pattern of
bom_pipeline.apply_bom_row_evidence_to_parts: it reads one already-computed figure per part, puts
it through the existing credibility guard, and writes it through source_precedence so arbitration
can refuse it. It does not measure anything, it does not parse a drawing, and it does not invent
a dimension — blank_credibility.blank_from_drawing_overalls holds the guardrails and every
refusal is recorded on the part in the drawing's own terms.

It is NOT a claim that the bound page is certainly the part's detail sheet. part_index binds by a
ranked fallback (a page that is not a parts list, preferred over one that is) because the exact
test — does this page's TITLE BLOCK name this part — cannot fire on a pack whose codes the
recognisers do not admit. So a dimension is taken only where the binding is SINGLE and
UNAMBIGUOUS, and a part bound to more than one page, or to a parts list, is left to the fallback
and said to be unresolved. An envelope that announces itself is better than a wrong number that
does not.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

# The rank blank_from_drawing_overalls already returns, registered in source_precedence at 65:
# below anything measured (DXF 80, model 90, deterministic title block 70) and above anything
# reasoned (geometry_inference 20). Named here so the two cannot drift apart.
SOURCE = "pdf_overall_dims"


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _page_index(summary: Mapping[str, Any]) -> Dict[int, Mapping[str, Any]]:
    out: Dict[int, Mapping[str, Any]] = {}
    for page in (summary.get("pages") or []):
        if isinstance(page, Mapping) and isinstance(page.get("page_number"), int):
            out[page["page_number"]] = page
    return out


def _overalls(page: Mapping[str, Any]) -> tuple:
    """The overall length/width this page prints, as extractor_patterns already computed them.

    classify_dimensions does the reading (it prefers an explicit "L x W" pair and falls back to
    the two largest plausible figures); nothing is re-parsed here. Returned as a pair so the
    caller can refuse one-without-the-other in one place.
    """
    dims = (page.get("page_analysis") or {}).get("dimensions") or {}
    return _num(dims.get("overall_length_mm")), _num(dims.get("overall_width_mm"))


def _is_folded(part: Mapping[str, Any]) -> bool:
    ops = part.get("operations") or part.get("textual_operations") or []
    text = " ".join(str(o) for o in ops).lower() if not isinstance(ops, str) else ops.lower()
    return any(cue in text for cue in ("fold", "bend", "linebend", "line_bend"))


# Where a flat that was MEASURED says it came from. A size from a drawing's printed overall or
# a category default is not one of these.
_MEASURED_GEOMETRY = ("dxf", "solidworks", "model", "flat_pattern", "mirror_of_measured")
_ENVELOPE_WORDS = "the size used is a fallback envelope"


def has_measured_flat(part: Mapping[str, Any]) -> bool:
    """Does this part carry a flat a DXF, a model or a measured mirror supplied?"""
    ng = part.get("normalized_geometry") if isinstance(part.get("normalized_geometry"),
                                                        Mapping) else {}
    src = " ".join(str(v or "") for v in (
        part.get("geometry_source"), ng.get("geometry_source"),
        part.get("blank_length_mm_source"))).lower()
    measured = (bool(part.get("dxf_augmented")) or bool(part.get("flat_pattern_detected"))
                or any(w in src for w in _MEASURED_GEOMETRY))
    if not measured:
        return False
    try:
        from document_builder import flat_blank_mm
        length, width = flat_blank_mm(dict(part))
    except Exception:                                            # noqa: BLE001
        length, width = part.get("blank_length_mm"), part.get("blank_width_mm")
    return bool(_num(length) and _num(width))


def not_cut_from_a_blank(part: Mapping[str, Any]) -> bool:
    """An assembly (sized through its members) or a line SDI does not make (bought in, or
    supplied by another party) uses no blank of its own, so no envelope stands in for one.
    12527-22's live book told the estimator the weldment 101 and the customer's ticket 03X were
    both costed on "a fallback envelope"; neither was costed on any size at all."""
    ctx = part.get("route_context") if isinstance(part.get("route_context"), Mapping) else {}
    if (part.get("is_assembly_parent") or part.get("is_sub_assembly")
            or part.get("assembly_children") or ctx.get("is_assembly_parent")
            # A part its own sheet shows JOINING members (a weld read off that sheet, or a
            # coat charged over its members' blanks) is an assembly whatever the tree says.
            or part.get("spot_weld_count") or part.get("_powder_members_coated_m2")
            or part.get("supplied_by_third_party")
            or str(part.get("costing_basis") or "") == "supplied_by_third_party"):
        return True
    # A CODE NAMING AN ASSEMBLY DRAWING IS EVIDENCE THE RECORD IS ONE (D-451) — not proof. The
    # product root 8188-08_GA carried no assembly flag and was checked as a 53 x 20 sheet
    # blank. The role token is taken as an assembly only where nothing says otherwise: an
    # explicit classification as a part (is_assembly_parent set False) or a flat a DXF, a
    # model or a measured mirror supplied wins over the name.
    try:
        from part_code_conventions import carries_assembly_role
        if (carries_assembly_role(part.get("part_number"))
                and part.get("is_assembly_parent") is not False
                and not has_measured_flat(part)):
            return True
    except Exception:                                            # noqa: BLE001
        pass
    try:
        from bought_in_policy import is_bought_in
        return bool(is_bought_in(dict(part)))
    except Exception:                                            # noqa: BLE001
        return False


def withdraw_stale_envelope_flags(parts: Any) -> int:
    """Take "the size used is a fallback envelope" off every part a measured flat now sizes,
    and off every part that uses no blank of its own.

    The detail-sheet pass may run before a DXF, a model or a mirror lands; a flag about a size
    that is no longer used is withdrawn once every reader has run (as D-291 does for the
    mirror, here for all of them). Returns how many parts it cleared."""
    cleared = 0
    for part in parts or ():
        if not isinstance(part, dict) or not (has_measured_flat(part)
                                              or not_cut_from_a_blank(part)):
            continue
        flags = part.get("review_flags") or []
        kept = [f for f in flags if _ENVELOPE_WORDS not in str(f)]
        if len(kept) != len(flags):
            part["review_flags"] = kept
            cleared += 1
    return cleared


# ── WHEN THE SHEET PRINTS NO OVERALL PAIR (D-505) ──────────────────────────────────────
#
# 12665's back panel, side wing, shelf pan and lock plate each have their own detail sheet,
# and every one was refused a blank: the dimension reader keeps only figures printed with
# "mm" after them, a SolidWorks sheet prints bare numbers, so one sheet "did not print both
# an overall length and an overall width" and another offered a slot's 8 mm as the overall.
# The parts were then costed on a category default (a "panel" is 400 x 300 whatever it is),
# their coat on almost nothing. The sheet DID print the part's size — as dimension figures on
# its views: the largest figure along each axis (title block and revision box left out) is
# its formed envelope; folded, it is developed one flange per fold — the depths the drawing
# states first, the configured allowance otherwise — unless the sheet shows its flat
# pattern, and a stated weight must agree (see provisional_blank_from_sheets). A PROVISIONAL
# blank, labelled with its working and put on the estimator's list — better than a default
# that knows nothing about the part, and never ranked above a printed overall, a flat or a
# model.
PROVISIONAL_SOURCE = "printed_extents_provisional"
_NUMBER_WORD = re.compile(r"\d{2,4}(?:\.\d+)?")


def _local_page_number(page: Mapping[str, Any]) -> Optional[int]:
    for key in ("source_page_number", "pdf_page_number", "page_number"):
        try:
            if page.get(key) is not None:
                return int(page.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _cfg() -> Dict[str, Any]:
    base = {"flange_allowance_mm": 25, "weight_ratio_bounds": (0.6, 1.6),
            "density_kg_m3": {"STEEL": 7850, "MILD": 7850, "STAINLESS": 8000,
                              "ALUMIN": 2700, "ACRYLIC": 1190},
            "developed_words": r"FLAT\s*PATTERN|DEVELOPED|BLANK\s*SIZE|FLAT\s*BLANK|UNFOLDED"}
    try:
        import config as _c
        base.update(dict(getattr(_c, "PROVISIONAL_BLANK_FROM_SHEET", {}) or {}))
    except Exception:                                                # noqa: BLE001
        pass
    return base


def read_sheet_figures(page: Mapping[str, Any]) -> Dict[str, Any]:
    """{"figures": [(value, axis)], "text": page text} — the bare dimension figures printed
    in a sheet's drawing area, each with the axis its text runs along ("h" or "v"), read with
    PyMuPDF (which keeps rotated text). The title block and revision zones are left out —
    that is where a date, a sheet size or a weight sits. Text at an angle is left out (it
    belongs to no axis). Figures from 10 mm to 4 m only. Empty when the PDF is not at hand."""
    out: Dict[str, Any] = {"figures": [], "text": ""}
    path = str(page.get("source_pdf_path") or "")
    local = _local_page_number(page)
    if not path or not local:
        return out
    try:
        import fitz                                                  # noqa: WPS433
        doc = fitz.open(path)
    except Exception:                                                # noqa: BLE001
        return out
    try:
        if not 0 < local <= doc.page_count:
            return out
        pg = doc.load_page(local - 1)
        width, height = float(pg.rect.width), float(pg.rect.height)
        layout = pg.get_text("dict") or {}
        out["text"] = pg.get_text() or ""
    except Exception:                                                # noqa: BLE001
        return out
    finally:
        try:
            doc.close()
        except Exception:                                            # noqa: BLE001
            pass
    try:
        from layout_zones import zone_boxes
        zones = zone_boxes(width, height)
        skip = [zones["title_block"], zones["revision"]]
    except Exception:                                                # noqa: BLE001
        skip = [(width * 0.58, height * 0.72, width, height)]
    for block in layout.get("blocks") or []:
        for line in block.get("lines") or []:
            dx, dy = (line.get("dir") or (1.0, 0.0))[:2]
            axis = "h" if abs(dx) >= 0.9 else ("v" if abs(dy) >= 0.9 else "")
            if not axis:
                continue
            x0, y0, x1, y1 = (float(v) for v in (line.get("bbox") or (0, 0, 0, 0)))
            if any(x1 >= b[0] and x0 <= b[2] and y1 >= b[1] and y0 <= b[3] for b in skip):
                continue
            text = "".join(str(sp.get("text") or "") for sp in line.get("spans") or [])
            for token in text.split():
                if not _NUMBER_WORD.fullmatch(token.strip()):
                    continue
                value = float(token)
                if 10.0 <= value <= 4000.0:
                    out["figures"].append((value, axis))
    return out


def printed_dimension_values(page: Mapping[str, Any]) -> List[float]:
    """The figures alone (see read_sheet_figures)."""
    return [v for v, _a in read_sheet_figures(page)["figures"]]


def _fold_count(part: Mapping[str, Any]) -> int:
    try:
        from fold_count import press_brake_folds
        return int(press_brake_folds(dict(part)).get("count") or 0)
    except Exception:                                                # noqa: BLE001
        return 0


def _stated_flanges(part: Mapping[str, Any]) -> List[float]:
    out: List[float] = []
    for v in (part.get("fold_values_mm") or []):
        f = _num(v)
        if f and 3.0 <= f <= 300.0:
            out.append(f)
    return out


def _stated_weight_kg(part: Mapping[str, Any]) -> Optional[float]:
    g = _num(part.get("stated_weight_g"))
    if g:
        return g / 1000.0
    kg = _num(part.get("stated_weight_kg") or part.get("weight_kg"))
    return kg


def provisional_blank_from_sheets(part: Mapping[str, Any],
                                  sheets: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """{length, width, formed, folds, flange_mm, pages, working, developed} — or None, with
    the reason on `part["_provisional_blank_refused"]` where a reason exists.

    THE SAFEGUARDS (review of D-505). The two largest figures on a sheet are not a blank by
    themselves — they could be one length printed twice, a diagonal, or figures from views
    that do not share an axis. So:
      1. the axes are ESTABLISHED: the larger extent is the largest figure whose text runs one
         way, the smaller the largest whose text runs the other — figures that cannot be put
         on two perpendicular axes give no blank;
      2. a sheet that shows a FLAT PATTERN or developed size has its figures taken as the
         developed blank — nothing is added for the folds;
      3. otherwise each fold adds a flange: the depths the drawing STATES first, the
         configured allowance only for folds it states none for, said as such;
      4. a stated WEIGHT must agree within the configured ratio, or no blank is made;
      5. the result must be a size something is cut to and fit a stocked sheet."""
    cfg = _cfg()
    figures: List[Any] = []
    text = ""
    for sheet in sheets:
        read = read_sheet_figures(sheet)
        figures.extend(read["figures"])
        text += "\n" + str(read["text"] or "")
    hs = sorted({round(v, 1) for v, a in figures if a == "h"}, reverse=True)
    vs = sorted({round(v, 1) for v, a in figures if a == "v"}, reverse=True)
    if not hs or not vs:
        if figures and isinstance(part, dict):
            part["_provisional_blank_refused"] = (
                "the figures printed on its sheet all run one way, so they cannot be put on "
                "two axes")
        return None
    formed_l, formed_w = max(hs[0], vs[0]), min(hs[0], vs[0])
    developed = bool(re.search(str(cfg.get("developed_words") or "$^"), text, re.I))
    folds = _fold_count(part)
    if _is_folded(part) and not folds:
        folds = 2
    stated = _stated_flanges(part)
    length, width, flange_note = formed_l, formed_w, ""
    if folds and not developed:
        house = float(cfg.get("flange_allowance_mm") or 25)
        depths = [stated[i] if i < len(stated) else house for i in range(folds)]
        short_is_l = formed_l < formed_w
        add = {"l": 0.0, "w": 0.0}
        for i, d in enumerate(depths):
            on_short = i % 4 < 2
            key = ("l" if short_is_l else "w") if on_short else ("w" if short_is_l else "l")
            add[key] += d
        length, width = formed_l + add["l"], formed_w + add["w"]
        n_stated = min(len(stated), folds)
        flange_note = (f", developed for {folds} fold(s): "
                       + (f"{n_stated} at the flange depth(s) the drawing states "
                          f"({', '.join(f'{d:g}' for d in stated[:n_stated])} mm)"
                          if n_stated else "")
                       + ("; " if n_stated and folds > n_stated else "")
                       + (f"{folds - n_stated} at the house allowance of {house:g} mm (config "
                          f"PROVISIONAL_BLANK_FROM_SHEET) — the drawing states none for them"
                          if folds > n_stated else "")
                       + f": {length:g} x {width:g} mm")
    elif developed:
        flange_note = (", the sheet shows a flat pattern / developed size, so these figures are "
                       "taken as the developed blank and nothing is added for the folds")
    else:
        flange_note = ", flat: no fold on the part"
    try:
        from blank_credibility import fits_a_stock_sheet, plausible_as_a_sheet_part
        if not plausible_as_a_sheet_part(length, width):
            return None
        if fits_a_stock_sheet(length, width, part.get("normalized_material")) is False:
            if isinstance(part, dict):
                part["_provisional_blank_refused"] = (
                    f"{length:g} x {width:g} mm fits no stocked sheet")
            return None
    except Exception:                                                # noqa: BLE001
        pass
    weight = _stated_weight_kg(part)
    t = _num(part.get("normalized_thickness_mm") or part.get("thickness_mm"))
    weight_note = ""
    if weight and t:
        mat = str(part.get("normalized_material") or "").upper()
        dens = next((float(d) for k, d in (cfg.get("density_kg_m3") or {}).items()
                     if k in mat), None)
        if dens:
            implied_m2 = weight / (t / 1000.0 * dens)
            ratio = (length * width / 1e6) / implied_m2 if implied_m2 else None
            lo, hi = cfg.get("weight_ratio_bounds") or (0.6, 1.6)
            if ratio is not None and not (lo <= ratio <= hi):
                if isinstance(part, dict):
                    part["_provisional_blank_refused"] = (
                        f"{length:g} x {width:g} mm is {ratio:.2f}x the area its stated "
                        f"{weight:g} kg implies at {t:g} mm — the figures do not describe its "
                        f"blank")
                return None
            if ratio is not None:
                weight_note = (f"; it agrees with the stated {weight:g} kg ({ratio:.2f}x the "
                               f"area that weight implies)")
    pages = [p.get("page_number") for p in sheets]
    working = (f"formed envelope {formed_l:g} x {formed_w:g} mm — the largest figure printed "
               f"along each axis of its own sheet (page {', '.join(str(p) for p in pages)})"
               + flange_note + weight_note)
    return {"length": length, "width": width, "formed": (formed_l, formed_w), "folds": folds,
            "flange_mm": stated or [float(cfg.get('flange_allowance_mm') or 25)],
            "developed": developed, "pages": pages, "working": working}


def _stamp_provisional(part: Dict[str, Any], blank: Mapping[str, Any], why_refused: str) -> None:
    pn = str(part.get("part_number") or "this part")
    why = (f"PROVISIONAL BLANK, NOT A MEASURED ONE — {pn}: {why_refused}; sized from its own "
           f"sheet instead: {blank['working']}. Material, cutting, coat and shipment follow "
           f"it; give the flat blank (or the DXF) and it is replaced.")
    ng = part.setdefault("normalized_geometry", {})
    if not isinstance(ng, dict):
        ng = {}
        part["normalized_geometry"] = ng
    for holder in (ng, part):
        holder["blank_length_mm"], holder["blank_width_mm"] = blank["length"], blank["width"]
        holder["blank_length_mm_source"] = holder["blank_width_mm_source"] = PROVISIONAL_SOURCE
    ng.pop("_inferred", None)
    part["_blank_provisional"] = {"basis": PROVISIONAL_SOURCE, **dict(blank)}
    part["blank_is_inferred"] = True
    part["blank_inferred_reason"] = why
    part.setdefault("review_flags", []).append(why)
    try:
        from source_precedence import raise_manufacturing_question as _ask
        _ask(part, f"Blank of {pn}: provisional {blank['length']:g} x {blank['width']:g} mm "
                   f"from the dimensions printed on its own sheet", why,
             "confirm the flat blank; the material, cut, coat and shipment follow it",
             "detail_page_geometry.provisional_blank_from_sheets")
    except Exception:                                                # noqa: BLE001
        pass


def apply_detail_page_geometry(parts: Any, summary: Mapping[str, Any]) -> int:
    """Stamp each part's blank from the detail page it is bound to. Returns how many gained one.

    Only a part with EXACTLY ONE bound page is considered, and that page must not be a parts
    list: two pages means the binding did not resolve, and a parts list prints the assembly's
    overall size, not the component's. Both cases are recorded on the part as an unresolved
    geometry decision rather than guessed at — which is the acceptance condition for this work
    ("sourced dimensions or an explicit unresolved geometry decision", not a quiet fallback).
    """
    if not isinstance(parts, Sequence) or not isinstance(summary, Mapping):
        return 0
    import source_precedence as sp
    from blank_credibility import blank_from_drawing_overalls
    try:
        from part_index import _bom_table_pages
        bom_pages, owned = _bom_table_pages(summary)
    except Exception:                                            # noqa: BLE001
        bom_pages, owned = set(), {}

    pages = _page_index(summary)
    stamped = 0
    for part in parts:
        if not isinstance(part, dict):
            continue
        pn = str(part.get("part_number") or "").strip()
        bound = [p for p in (part.get("pages") or []) if isinstance(p, int)]

        # ALREADY MEASURED WINS AND IS NOT TOUCHED. A DXF flat or a model blank outranks this by
        # design; asking arbitration to refuse it would still cost a recorded displacement on
        # every structured part in the job, for nothing.
        if _num(part.get("blank_length_mm")) and str(
                part.get("blank_length_mm_source") or "") not in ("", "geometry_inference"):
            continue
        # AND A MEASURED FLAT HELD UNDER THE GEOMETRY RECORD IS MEASURED TOO. A DXF or model
        # flat lands in normalized_geometry, not at the top of the part, so 12527-22's riser
        # and rail — both cut from their own DXFs — were told their size was "a fallback
        # envelope".
        if has_measured_flat(part):
            continue

        if len(bound) != 1:
            if bound:
                _why = (f"it is bound to {len(bound)} pages "
                        f"({', '.join(str(b) for b in sorted(bound))}) and no single sheet "
                        f"prints its overall size")
                _sheets = [pages[b] for b in sorted(bound) if b in pages
                           and not (b in bom_pages and b not in (owned.get(pn) or set()))]
                _prov = (provisional_blank_from_sheets(part, _sheets)
                         if _sheets and not not_cut_from_a_blank(part) else None)
                if _prov:
                    _stamp_provisional(part, _prov, _why)
                    stamped += 1
                else:
                    part.setdefault("review_flags", []).append(
                        f"{pn or 'this part'} is bound to {len(bound)} pages "
                        f"({', '.join(str(b) for b in sorted(bound))}) — no single sheet defines it, "
                        f"so its blank is UNRESOLVED and the size used is a fallback envelope"
                        + (f"; no provisional blank from its sheets either: "
                           f"{part['_provisional_blank_refused']}"
                           if part.get("_provisional_blank_refused") else ""))
            continue

        page_no = bound[0]
        page = pages.get(page_no)
        if page is None:
            continue
        if page_no in bom_pages and page_no not in (owned.get(pn) or set()):
            part.setdefault("review_flags", []).append(
                f"{pn or 'this part'} is bound to page {page_no}, a parts list — that page "
                f"prints the assembly's overall size, not this component's, so its blank is "
                f"UNRESOLVED and the size used is a fallback envelope")
            continue

        length, width = _overalls(page)
        verdict = blank_from_drawing_overalls(
            length, width,
            part.get("normalized_thickness_mm") or part.get("thickness_mm"),
            is_folded=_is_folded(part),
            developed_length_mm=part.get("developed_length_mm"),
            bbox_mm=part.get("bbox_mm"),
        )
        if not verdict.get("usable"):
            _why = (f"page {page_no} is its detail sheet but its printed overall could not be "
                    f"used — {verdict.get('reason') or 'refused'}")
            _prov = (provisional_blank_from_sheets(part, [page])
                     if not not_cut_from_a_blank(part) else None)
            if _prov:
                _stamp_provisional(part, _prov, _why)
                stamped += 1
                continue
            part.setdefault("review_flags", []).append(
                f"{pn or 'this part'}: page {page_no} is its detail sheet but its blank could "
                f"not be taken from it — {verdict.get('reason') or 'refused'}. UNRESOLVED; the "
                f"size used is a fallback envelope"
                + (f"; no provisional blank from its sheet either: "
                   f"{part['_provisional_blank_refused']}"
                   if part.get("_provisional_blank_refused") else ""))
            continue

        before = _num(part.get("blank_length_mm"))
        sp.apply_field(part, "blank_length_mm", verdict["blank_length_mm"], SOURCE)
        sp.apply_field(part, "blank_width_mm", verdict["blank_width_mm"], SOURCE)
        part["blank_from_detail_page"] = {
            "page": page_no,
            "blank_length_mm": verdict["blank_length_mm"],
            "blank_width_mm": verdict["blank_width_mm"],
            "replaced_envelope_mm": before,
            "reason": verdict.get("reason"),
        }
        if _num(part.get("blank_length_mm")) == _num(verdict["blank_length_mm"]):
            stamped += 1
            part.setdefault("review_flags", []).append(
                f"{pn or 'this part'} sized {verdict['blank_length_mm']:g} x "
                f"{verdict['blank_width_mm']:g} mm from its own detail sheet, page {page_no}"
                + (f" (was a {before:g} mm fallback envelope)" if before else "")
                + " — inferred from the drawing's printed overall, confirm before a firm quote")
    return stamped


def isolate_dimension_text(parts: Any, summary: Mapping[str, Any]) -> int:
    """Drop dimension text a part collected from pages that are not its own.

    THE SECOND HALF OF THE SAME DEFECT, and it has to be in the same change as the first. A
    part accumulates `all_dimensions_mm` from EVERY page it claims, ungated, and the estimator's
    sizing waterfall reads that list as a last resort. So a part bound to a parts list does not
    merely miss its own dimensions — it inherits the assembly's, and a correct page selection
    upstream can still produce a wrong blank downstream.

    Only figures from pages the part is actually bound to survive. Returns how many parts were
    trimmed. A part whose list is already clean is untouched and uncounted.
    """
    if not isinstance(parts, Sequence) or not isinstance(summary, Mapping):
        return 0
    pages = _page_index(summary)
    trimmed = 0
    for part in parts:
        if not isinstance(part, dict):
            continue
        have = [str(d) for d in (part.get("all_dimensions_mm") or [])]
        if not have:
            continue
        bound = {p for p in (part.get("pages") or []) if isinstance(p, int)}
        if not bound:
            continue
        keep: List[str] = []
        for page_no in sorted(bound):
            page = pages.get(page_no) or {}
            own = (page.get("page_analysis") or {}).get("dimensions") or {}
            for value in (own.get("all_dimensions_mm") or []):
                if str(value) in have and str(value) not in keep:
                    keep.append(str(value))
        if len(keep) < len(have):
            part["all_dimensions_mm"] = keep
            part.setdefault("review_flags", []).append(
                f"{len(have) - len(keep)} dimension figure(s) dropped: they were read off pages "
                f"this part is not bound to, and the sizing waterfall reads this list")
            trimmed += 1
    return trimmed
