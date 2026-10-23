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
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

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


_SECTION_FORMS = {"tube", "section", "bar", "wire", "angle_section", "channel"}


def _is_section_stock(part: Mapping[str, Any]) -> bool:
    """Does this record's own evidence say it is a length of section — a stock form already
    costed as one, a section reading on the record, or a BOM row whose dimension and material
    words name a profile ("MILD STEEL RECT TUBE - RAW 50X20X2MM")?"""
    me = part.get("material_estimate") if isinstance(part.get("material_estimate"), Mapping) else {}
    if str(me.get("stock_form") or "").lower() in _SECTION_FORMS:
        return True
    if isinstance(part.get("section_stock"), Mapping) and part["section_stock"]:
        return True
    words = " ".join(str(part.get(k) or "") for k in
                     ("description", "material", "normalized_material", "dimension",
                      "stock_size", "size", "bom_dimension", "profile",
                      "material_text_as_printed", "bom_material", "size_text"))
    words += " " + " ".join(str(m) for m in (part.get("materials") or []) if m)
    words += " " + " ".join(str(c) for c in (part.get("material_text_as_printed_candidates") or []) if c)
    if not re.search(r"\d", words):
        return False
    try:
        from section_profile import detect_section_stock
        return bool(detect_section_stock(words))
    except Exception:                                                # noqa: BLE001
        return False


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
    # A SECTION IS CUT TO LENGTH, NOT FROM A BLANK (D-584). A cross rail of 50 x 20 x 2 tube,
    # 703 long, was handed a 2 x 1.5 "blank" off its own sheet and then had it rejected, so
    # it reached costing with no material at all. The row's own dimension column names the
    # profile; the sheet's figures are its cut length, which the section readers own.
    if _is_section_stock(part):
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
# A DECIMAL COMMA IS A DECIMAL (D-584): European CAD prints 1435,2 and 208,9.
_NUMBER_WORD = re.compile(r"\d{2,4}(?:[.,]\d+)?")
# A SMALL DIMENSION PRINTED WITH ITS DECIMAL IS A DIMENSION (D-589). 0351292's top blank is
# 30 x 7,4 x 2: its own sheet prints "30" across and "7,4" upright, and the 10 mm floor that
# keeps a gauge label ("2") and a radius ("R2") out dropped the 7,4 with them — so the blank
# could not be put on two axes and the part had no size. A single-digit figure WITH a decimal
# is somebody dimensioning a small part; a bare single digit stays out. Used only where the
# axis has nothing larger (every reader takes the largest figure per axis), and checked
# against the weight the same sheet states.
_SMALL_DECIMAL = re.compile(r"\d[.,]\d+")
_SMALL_DECIMAL_MIN_MM = 3.0


def _local_page_number(page: Mapping[str, Any]) -> Optional[int]:
    for key in ("source_page_number", "pdf_page_number", "page_number"):
        try:
            if page.get(key) is not None:
                return int(page.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _cfg() -> Dict[str, Any]:
    base = {"flange_allowance_mm": 25, "min_blank_to_part_weight_ratio": 0.9,
            "weight_question_above_ratio": 1.6,
            "density_kg_m3": {"STEEL": 7850, "MILD": 7850, "STAINLESS": 8000,
                              "ALUMIN": 2700, "ACRYLIC": 1190},
            "developed_words": r"FLAT\s*PATTERN|DEVELOPED|BLANK\s*SIZE|FLAT\s*BLANK|UNFOLDED"}
    try:
        import config as _c
        base.update(dict(getattr(_c, "PROVISIONAL_BLANK_FROM_SHEET", {}) or {}))
    except Exception:                                                # noqa: BLE001
        pass
    return base


_REVISION_WORDS = re.compile(r"\b(?:REV|REVISION|REVISIONS|CHANGE|ECN|ECO|AMENDMENT|ISS|ISSUE)\b",
                             re.IGNORECASE)


def _zone_holds_words(layout: Mapping[str, Any], box: Sequence[float], words: Any) -> bool:
    """True when any text line inside `box` matches `words`."""
    bx0, by0, bx1, by1 = (float(v) for v in box)
    for block in layout.get("blocks") or []:
        for line in block.get("lines") or []:
            x0, y0, x1, y1 = (float(v) for v in (line.get("bbox") or (0, 0, 0, 0)))
            if x1 >= bx0 and x0 <= bx1 and y1 >= by0 and y0 <= by1:
                text = "".join(str(sp.get("text") or "") for sp in line.get("spans") or [])
                if words.search(text):
                    return True
    return False


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
        skip = [zones["title_block"]]
        # THE REVISION ZONE IS SKIPPED FOR WHAT IT HOLDS (D-589). 0351292's downstand sheet
        # keeps its revision table top right; the box where one usually sits held the flat's
        # 25 mm width instead, and the blank could not be read. Skipped only where revision
        # words are actually printed in it.
        if _zone_holds_words(layout, zones["revision"], _REVISION_WORDS):
            skip.append(zones["revision"])
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
            # A DIMENSION LEADS ITS LINE (D-584). "400 GRIT FINAL POLISH", "BETWEEN 80 - 120
            # MICRON", "304 - STAINLESS STEEL" and a postcode in the consultant's address put
            # 400, 304, 120, 93 and 80 on every sheet of a pack, and a 250 mm angle read as
            # 400 x 50. A printed dimension is a figure first — "1192 TUBE LENGTH", "1154
            # INT", "258 259 259" — so figures are taken from the front of a line up to its
            # first word, and a line that opens with a word, a bullet or a symbol gives none.
            for token in text.split():
                _tok = token.strip()
                _small = bool(_SMALL_DECIMAL.fullmatch(_tok))
                if not (_NUMBER_WORD.fullmatch(_tok) or _small):
                    break
                value = float(_tok.replace(",", "."))
                if 10.0 <= value <= 4000.0 or (_small and _SMALL_DECIMAL_MIN_MM <= value < 10.0):
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


_FOLD_EVIDENCE_SOURCES = frozenset({
    "flat_pattern_bend_lines", "drawing_fold_note", "solidworks_bend_features",
    "drawing_callouts_agreeing_with_model", "drawing_bend_callouts", "concept_read_fold_count",
})


def _evidenced_fold_count(part: Mapping[str, Any]) -> int:
    """The folds a reading of the part counted — not the dashed-line proxy (D-591)."""
    try:
        from fold_count import press_brake_folds
        res = press_brake_folds(dict(part))
    except Exception:                                                # noqa: BLE001
        return 0
    if str(res.get("source") or "") in _FOLD_EVIDENCE_SOURCES:
        return int(res.get("count") or 0)
    return int(res.get("count") or 0) if _fold_op_has_evidence(part) else 0


def _fold_op_has_evidence(part: Mapping[str, Any]) -> bool:
    """True when the part's fold operation carries the drawing's words or a recorded reader —
    not a bare operation name nobody can account for (the D-586/D-587 'unrecorded' case)."""
    for op in ("folding", "fold", "bending"):
        if str((part.get("operation_evidence") or {}).get(op) or "").strip():
            return True
        src = str((part.get("operation_sources") or {}).get(op) or "").strip().lower()
        if src and src not in ("unknown", "unrecorded", "drawing_notes"):
            return True
    return False


def _stated_flanges(part: Mapping[str, Any]) -> List[float]:
    out: List[float] = []
    for v in (part.get("fold_values_mm") or []):
        f = _num(v)
        if f and 3.0 <= f <= 300.0:
            out.append(f)
    return out


_WEIGHT_TEXT = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*(KG|G)$")


def _stated_weight_kg(part: Mapping[str, Any]) -> Optional[float]:
    """The FINISHED part's weight its own sheet states, in kg — from every place the readers
    put it, in either unit, or None.

    D-506 read only stated_weight_g / stated_weight_kg / weight_kg, and 12665's sheets carry
    their WEIGHT: box as text in `weights` ("2.9kg", "70g") — so the check never saw a weight
    and never ran (D-508). Read here as the estimator reads it; a figure outside 1 g to 500 kg
    is not a part's weight."""
    def _ok(kg: Optional[float]) -> Optional[float]:
        return kg if kg is not None and 0.001 <= kg <= 500.0 else None

    g = _num(part.get("stated_weight_g"))
    if g and _ok(g / 1000.0):
        return g / 1000.0
    kg = _ok(_num(part.get("stated_weight_kg") or part.get("weight_kg")))
    if kg:
        return kg
    tb = part.get("title_block") if isinstance(part.get("title_block"), Mapping) else {}
    weights = part.get("weights") or tb.get("weights") or []
    if isinstance(weights, str):
        weights = [weights]
    for w in weights if isinstance(weights, (list, tuple)) else []:
        m = _WEIGHT_TEXT.match(str(w).strip().upper().replace(",", ""))
        if not m:
            continue
        val = float(m.group(1)) / (1000.0 if m.group(2) == "G" else 1.0)
        if _ok(val):
            return val
    return None


def made_children(part: Mapping[str, Any], parts: Sequence[Any],
                  summary: Mapping[str, Any]) -> List[str]:
    """The parts this record's own parts list holds that SDI MAKES — or [] (D-508).

    An assembly of made parts has no blank of its own: its members carry the material. A
    parts list alone does not say so — a fabricated panel can list the PEM nuts pressed into
    it and still be cut from one blank — so only a child that is itself cut (its code's
    material letter, M/A/T, or a record carrying a fabrication route) counts, and a record
    whose OWN code carries that letter is a cut part whatever it lists."""
    try:
        from part_code_conventions import bare_code, material_suffix
    except Exception:                                                # noqa: BLE001
        return []
    pn = str(part.get("part_number") or "").strip()
    if not pn or material_suffix(pn):
        return []
    me = bare_code(pn)
    try:
        from bought_in_policy import is_bought_in
    except Exception:                                                # noqa: BLE001
        def is_bought_in(_r: Any) -> bool:                           # type: ignore
            return False
    by_code = {bare_code(str(p.get("part_number") or "")): p
               for p in parts or [] if isinstance(p, dict)}
    kids: List[str] = []
    rows = list(((summary.get("document_analysis") or {}).get("bom_rows") or [])
                if isinstance(summary, Mapping) else [])
    for rec in rows + [p for p in parts or [] if isinstance(p, dict)]:
        if not isinstance(rec, Mapping):
            continue
        if bare_code(str(rec.get("bom_parent") or "")) != me:
            continue
        code = str(rec.get("part_number") or "").strip()
        if not code or bare_code(code) == me or code in kids:
            continue
        full = by_code.get(bare_code(code)) or dict(rec)
        try:
            bought = bool(is_bought_in(dict(full)))
        except Exception:                                            # noqa: BLE001
            bought = False
        if bought:
            continue
        if material_suffix(code) or _is_folded(full) or full.get("blank_length_mm"):
            kids.append(code)
    return kids


def sheet_envelope(sheets: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The largest figure printed along each axis of these sheets — an assembly's outline,
    kept as a SIZE CHECK on its members (never as a blank)."""
    figures: List[Any] = []
    for sheet in sheets:
        figures.extend(read_sheet_figures(sheet)["figures"])
    hs = [v for v, a in figures if a == "h"]
    vs = [v for v, a in figures if a == "v"]
    if not hs or not vs:
        return None
    a, b = max(hs), max(vs)
    return {"length": max(a, b), "width": min(a, b),
            "pages": [s.get("page_number") for s in sheets]}


def _weight_on_sheets(sheets: Sequence[Mapping[str, Any]]) -> Optional[float]:
    """The one weight the given sheets' own title blocks state, in kg; None when they state
    none, or more than one (two weights on the sheets that size a part decide nothing)."""
    seen: List[float] = []
    for sheet in sheets or []:
        tb = ((sheet.get("page_analysis") or {}).get("title_block") or {}) \
            if isinstance(sheet, Mapping) else {}
        for w in (tb.get("weights") or []) if isinstance(tb, Mapping) else []:
            m = _WEIGHT_TEXT.match(str(w).strip().upper().replace(",", "").replace(" ", ""))
            if not m:
                continue
            val = float(m.group(1)) / (1000.0 if m.group(2) == "G" else 1.0)
            if 0.001 <= val <= 500.0 and not any(abs(val - s) < 1e-9 for s in seen):
                seen.append(val)
    return seen[0] if len(seen) == 1 else None


def _small_blank_agrees_with_its_weight(part: Mapping[str, Any],
                                        sheets: Sequence[Mapping[str, Any]],
                                        length: float, width: float,
                                        cfg: Mapping[str, Any]) -> bool:
    """True when a blank below the general floor is confirmed by the weight the same sheets
    state: both sides at least _SMALL_DECIMAL_MIN_MM, and the blank's mass within
    [min_blank_to_part_weight_ratio, weight_question_above_ratio] of that weight."""
    if min(length, width) < _SMALL_DECIMAL_MIN_MM:
        return False
    weight = _weight_on_sheets(sheets)
    t = _num(part.get("normalized_thickness_mm") or part.get("thickness_mm"))
    mat = str(part.get("normalized_material") or "").upper()
    dens = next((float(d) for k, d in (cfg.get("density_kg_m3") or {}).items() if k in mat),
                None)
    if not (weight and t and dens):
        return False
    implied_m2 = weight / (t / 1000.0 * dens)
    ratio = (length * width / 1e6) / implied_m2 if implied_m2 else None
    lo = float(cfg.get("min_blank_to_part_weight_ratio") or 0.9)
    hi = float(cfg.get("weight_question_above_ratio") or 1.6)
    return ratio is not None and lo <= ratio <= hi


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
    # A FLANGE ONLY FOR A FOLD WITH EVIDENCE (D-591). 0351292's strip carried a fold no reader
    # recorded a source for — an open question on the decisions list — and its blank was
    # still developed for it: 1293 x 12 became 1293 x 37 and the unproven fold reached the
    # material. A fold counted by a flat pattern, a drawing note or callouts, or the model
    # develops the blank; the weakest proxies and a bare operation name do not, unless the
    # operation itself carries the drawing's words.
    folds = _evidenced_fold_count(part)
    if _is_folded(part) and not folds and _fold_op_has_evidence(part):
        folds = 2
    if not folds:
        # A FORMED SHAPE HAS ITS FOLDS BEFORE ANYTHING ROUTES THEM (D-589): an angle cut from
        # sheet is developed for one flange, whether or not a fold has been charged yet.
        try:
            from formed_shape import shape_folds
            folds = shape_folds(part)
        except Exception:                                            # noqa: BLE001
            folds = 0
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
            # A SMALL PART IS SIZED ONLY WITH ITS WEIGHT'S AGREEMENT (D-589). The 10 mm floor
            # is there because a 16 x 3.7 feature callout was once read as a part (12392);
            # what tells a real 30 x 7.4 blank from that is the weight its own sheet states.
            # Below the floor, the blank stands only when the sheets it was read from state
            # a weight it agrees with, within the configured window — never on figures alone.
            if not _small_blank_agrees_with_its_weight(part, sheets, length, width, cfg):
                if isinstance(part, dict):
                    part["_provisional_blank_refused"] = (
                        f"{length:g} x {width:g} mm is below the smallest size a sheet part is "
                        f"taken at on figures alone, and its own sheet states no weight it "
                        f"agrees with")
                return None
        if fits_a_stock_sheet(length, width, part.get("normalized_material")) is False:
            if isinstance(part, dict):
                part["_provisional_blank_refused"] = (
                    f"{length:g} x {width:g} mm fits no stocked sheet")
            return None
    except Exception:                                                # noqa: BLE001
        pass
    # THE WEIGHT CHECKS THE BLANK, IT DOES NOT DECIDE IT (review of D-508). The stated weight is
    # the FINISHED part; the blank is the stock it is cut from, so a blank legitimately weighs
    # MORE — a window or a slot is paid for and thrown away — and a threshold on that side
    # cannot say which of the two figures is wrong. Only the impossible side is refused: a
    # blank LIGHTER than the part cut from it is too small, so the figures read are not its
    # size. Heavier is kept, with the factor written into the working, and the estimator's
    # WEIGHT CHECK on the costed blank puts the gauge question.
    # THE WEIGHT THESE SHEETS STATE, BEFORE ANY WEIGHT THE RECORD COLLECTED (D-589). A part
    # bound to its own sheet and to the assembly sheet that lists it collects both title
    # blocks' weights — 0351292's top blank holds 8.1 kg (the rail) and 0.003 kg (itself) —
    # and the first one decided. The blank is read from these sheets; so is its weight, when
    # they print exactly one. Otherwise the record's own reading stands, as before.
    weight = _weight_on_sheets(sheets) or _stated_weight_kg(part)
    t = _num(part.get("normalized_thickness_mm") or part.get("thickness_mm"))
    weight_note = ""
    weight_agrees = False
    if weight and t:
        mat = str(part.get("normalized_material") or "").upper()
        dens = next((float(d) for k, d in (cfg.get("density_kg_m3") or {}).items()
                     if k in mat), None)
        if dens:
            implied_m2 = weight / (t / 1000.0 * dens)
            ratio = (length * width / 1e6) / implied_m2 if implied_m2 else None
            lo = float(cfg.get("min_blank_to_part_weight_ratio") or 0.9)
            hi = float(cfg.get("weight_question_above_ratio") or 1.6)
            if ratio is not None and ratio < lo:
                if isinstance(part, dict):
                    part["_provisional_blank_refused"] = (
                        f"{length:g} x {width:g} mm at {t:g} mm would weigh "
                        f"{ratio:.2f}x the stated {weight:g} kg — LESS than the finished part "
                        f"cut from it, which a blank cannot, so the figures read are not its "
                        f"size")
                return None
            if ratio is not None and ratio > hi and developed:
                # THE DIMENSIONS SELECT, THE WEIGHT CORROBORATES (D-589, review). The largest
                # upright figure on a flat-pattern sheet can belong to the formed view —
                # 0351292's downstand prints 208.9 for its returns and 25 for its flat width.
                # The width is looked for where a width is printed: across the length's axis,
                # below the figure refused. The weight never chooses between figures: exactly
                # ONE such figure must give a blank the stated weight agrees with. Two, or
                # none, decide nothing and the refusal stands. A figure along the length's
                # axis is never a width, however well it fits the weight (31.7 on the same
                # sheet fits it too).
                _len_axis = "h" if hs[0] >= vs[0] else "v"
                _fits = sorted(
                    (w, (length * w / 1e6) / implied_m2)
                    for w in {round(v, 1) for v, a in figures if a != _len_axis}
                    if w < width and lo <= (length * w / 1e6) / implied_m2 <= hi)
                if len(_fits) == 1:
                    _w_was, width = width, _fits[0][0]
                    weight_note = (f"; the width is {width:g} mm, not {_w_was:g}: the largest "
                                   f"figure across the length would weigh {ratio:.2f}x the "
                                   f"stated {weight:g} kg on a flat pattern, and {width:g} mm is "
                                   f"the only other figure printed across it that the weight "
                                   f"agrees with ({_fits[0][1]:.2f}x) — confirm the flat width")
                    ratio = None
                    weight_agrees = True
                elif len(_fits) > 1 and isinstance(part, dict):
                    part["_provisional_blank_candidates"] = [w for w, _r in _fits]
            if ratio is not None and ratio > hi and developed:
                # A FLAT PATTERN IS THE NET BLANK (D-584): nothing is cut out of it after
                # development, so a developed size that weighs several times the stated part
                # is not the flat the sheet states — a figure from another view was taken for
                # one of its sides. Refused, and the sheet's own flat is asked for.
                if isinstance(part, dict):
                    part["_provisional_blank_refused"] = (
                        f"{length:g} x {width:g} mm at {t:g} mm would weigh {ratio:.2f}x the "
                        f"stated {weight:g} kg, and the sheet shows a flat pattern — a developed "
                        f"blank has nothing cut from it, so these figures are not its flat; "
                        f"read the flat pattern's own two sizes from the sheet")
                return None
            if ratio is not None and ratio > hi:
                weight_note = (f"; it weighs {ratio:.2f}x the stated finished {weight:g} kg — "
                               f"consistent with cut-outs, or with a thinner gauge than "
                               f"{t:g} mm; the gauge and the blank are asked")
            elif ratio is not None:
                weight_agrees = True
                weight_note = (f"; it agrees with the stated {weight:g} kg ({ratio:.2f}x the "
                               f"area that weight implies)")
    pages = [p.get("page_number") for p in sheets]
    working = (f"formed envelope {formed_l:g} x {formed_w:g} mm — the largest figure printed "
               f"along each axis of its own sheet (page {', '.join(str(p) for p in pages)})"
               + flange_note + weight_note)
    try:
        from blank_credibility import plausible_as_a_sheet_part as _plausible
        _small = not _plausible(length, width)
    except Exception:                                                # noqa: BLE001
        _small = False
    return {"length": length, "width": width, "formed": (formed_l, formed_w), "folds": folds,
            "flange_mm": stated or [float(cfg.get('flange_allowance_mm') or 25)],
            "developed": developed, "pages": pages, "working": working,
            # Below the general floor, the blank stands on its sheet's weight (D-589): said
            # on the result so the costing's own floor reads the same evidence.
            "weight_confirmed_small_part": bool(_small),
            # The stated weight on the sheets it was read from corroborates it (D-592) — the
            # evidence a reader needs before showing this blank as a worked example.
            "weight_agrees": bool(weight_agrees or _small)}


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

        # AN ASSEMBLY OF MADE PARTS HAS NO BLANK OF ITS OWN (D-508). 12665-04-201 NEW FASCIA
        # ASSEMBLY was given a 550 x 451.5 "provisional blank" and the estimator was asked to
        # confirm the flat of something that is never cut: its fascia and back plate carry
        # the material. Its sheet's outline is kept instead — as a size check on its members.
        _kids = made_children(part, parts, summary)
        if _kids:
            _env = sheet_envelope([pages[b] for b in sorted(bound) if b in pages])
            if _env:
                part["_sheet_envelope_mm"] = _env
            part["_assembly_of_made_parts"] = list(_kids)
            # Said only where the record would otherwise have been sized as a part; a GA is an
            # assembly already and needs no sentence about it.
            if not not_cut_from_a_blank(part):
                part.setdefault("review_flags", []).append(
                    f"{pn or 'this record'}: no blank of its own — it is an assembly of parts "
                    f"SDI makes ({', '.join(_kids[:4])}{', …' if len(_kids) > 4 else ''}), "
                    f"and they carry the material"
                    + (f"; its own sheet's outline, {_env['length']:g} x {_env['width']:g} "
                       f"mm, is kept as a size check on them" if _env else ""))
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


def _blank_pair(part: Mapping[str, Any]) -> tuple:
    ng = part.get("normalized_geometry") if isinstance(part.get("normalized_geometry"),
                                                        Mapping) else {}
    return (_num(ng.get("blank_length_mm")) or _num(part.get("blank_length_mm")),
            _num(ng.get("blank_width_mm")) or _num(part.get("blank_width_mm")))


def _write_blank(part: Dict[str, Any], length: float, width: float, source: str) -> None:
    """Both places a blank is read from carry it, under one source — or the resolver and the
    sheet would disagree about one part."""
    ng = part.setdefault("normalized_geometry", {})
    if not isinstance(ng, dict):
        ng = {}
        part["normalized_geometry"] = ng
    for holder in (ng, part):
        holder["blank_length_mm"], holder["blank_width_mm"] = round(length, 1), round(width, 1)
        holder["blank_length_mm_source"] = holder["blank_width_mm_source"] = source


_RADIUS_TEXT = re.compile(r"(?<![A-Z0-9])R\s?(\d{2,4}(?:[.,]\d+)?)(?![\d.,])", re.IGNORECASE)


def _squash(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def own_sheets(part: Mapping[str, Any], summary: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """The pages that ARE this part's drawing: bound to it, and titled with its own drawing
    number. A page that only lists it (a parts list, an assembly view) is someone else's sheet
    and prints someone else's radii."""
    pn = _squash(part.get("part_number"))
    if not pn:
        return []
    pages = _page_index(summary)
    # A PARTS LIST IS NOT THE PART'S OWN SHEET (D-591). A title block's drawing numbers on an
    # assembly sheet include every row of its table, so 0351292's base assembly (page 9)
    # read as the downstand's own sheet beside page 11. A page carrying a parts list counts
    # only for the part whose table it is — the same exclusion apply_detail_page_geometry
    # makes before it sizes a blank.
    try:
        from part_index import _bom_table_pages
        bom_pages, owned = _bom_table_pages(summary)
    except Exception:                                                # noqa: BLE001
        bom_pages, owned = set(), {}
    _raw_pn = str(part.get("part_number") or "").strip()
    _owned_here = set(owned.get(_raw_pn) or owned.get(_raw_pn.upper()) or set())
    out = []
    for b in sorted(p for p in (part.get("pages") or []) if isinstance(p, int)):
        page = pages.get(b)
        if not page:
            continue
        if b in bom_pages and b not in _owned_here:
            continue
        tb = ((page.get("page_analysis") or {}).get("title_block") or {})
        dns = [_squash(d) for d in (tb.get("drawing_numbers") or [])] if isinstance(tb, Mapping) else []
        dns += [_squash(page.get(k)) for k in ("drawing_number", "page_drawing_number")
                if page.get(k)]
        if pn in dns:
            out.append(page)
    return out


def _sum_page_geometry(sheets: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    """The numeric geometry the given sheets' own vector reads hold, summed (top level only)."""
    out: Dict[str, float] = {}
    for sheet in sheets:
        geo = sheet.get("geometry_summary") if isinstance(sheet.get("geometry_summary"), Mapping) else {}
        for k, v in geo.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = out.get(k, 0.0) + float(v)
    return out


_OWN_SHEET_CUES = ("hole_sizes_mm", "radii_mm", "angles_deg", "fold_values_mm", "slot_sizes_mm")


def revalidate_from_own_sheets(parts: Any, summary: Mapping[str, Any]) -> List[str]:
    """Every figure that depends on WHICH SHEET a part was read from is read again from its own
    sheet, once the part's own sheet is known (D-591). Returns the part numbers changed.

    0351292's top blank was sized correctly from its own sheet (30 x 7.4, page 8) while every
    figure computed from the same pages stayed as it was: a 12,637 mm cut path and the holes
    counted off the rail's assembly sheet (page 3) drove £24.13 of laser and a Punch share,
    and its weight check compared it with the rail's 8.1 kg. The downstand (pages 9 and 11)
    carried the base assembly's 8.6 kg and 8,631 mm of internal cutting the same way. Fixing
    one field without its dependants leaves the book contradicting itself.

    For a part bound to its own sheet AND to sheets that are someone else's (an assembly's,
    a parts list), the figures read per page are taken from its own sheets only: the stated
    weight, the feature cues (holes, radii, angles, fold values, slots) and the page-vector
    geometry (cut length, hole and pierce counts). A measured flat — DXF or model — is never
    touched: it was not read off a page. Each change is written on the part and flagged."""
    if not isinstance(parts, Sequence) or not isinstance(summary, Mapping):
        return []
    try:
        from blank_credibility import blank_is_measured
    except Exception:                                                # noqa: BLE001
        def blank_is_measured(_p: Any) -> bool:                      # type: ignore[misc]
            return False
    changed: List[str] = []
    for part in parts:
        if not isinstance(part, dict) or not _made_here(part):
            continue
        bound = sorted(p for p in (part.get("pages") or []) if isinstance(p, int))
        own = own_sheets(part, summary)
        own_pages = [s.get("page_number") for s in own]
        foreign = [b for b in bound if b not in own_pages]
        if not own:
            continue
        pn = str(part.get("part_number") or "this part")
        notes: List[str] = []
        # THE WEIGHT AND GAUGE ITS OWN SHEET STATES — whether or not another sheet is bound to it
        # (D-592): 0351292's strip is bound to its own sheet alone and still carried a 5 mm gauge
        # from a parts list elsewhere, against the 3 mm its sheet prints.
        w = _weight_on_sheets(own)
        cur = _stated_weight_kg(part)
        if w and (cur is None or abs(cur - w) > 1e-9):
            part["weights"] = [f"{w:g}KG"]
            part["stated_weight_g"] = round(w * 1000.0, 3)
            part["stated_weight_source"] = "own_sheet_title_block"
            notes.append(f"weight {w:g} kg from its own sheet"
                         + (f", not {cur:g} kg" if cur is not None else ""))
        # THE GAUGE ITS OWN SHEET STATES (D-592), through the resolver, so a measurement or a
        # person still wins and the displaced page read is recorded.
        _own_t: List[float] = []
        for s in own:
            tb = ((s.get("page_analysis") or {}).get("title_block") or {})
            for v in (tb.get("thicknesses_mm") or []) if isinstance(tb, Mapping) else []:
                n = _num(str(v).replace(",", ".").upper().replace("MM", "").strip())
                if n and 0.3 <= n <= 50.0 and not any(abs(n - x) < 1e-9 for x in _own_t):
                    _own_t.append(n)
        _cur_t = _num(part.get("normalized_thickness_mm"))
        if len(_own_t) == 1 and (_cur_t is None or abs(_cur_t - _own_t[0]) > 1e-9):
            try:
                import source_precedence as _sp
                if _sp.apply_field(part, "normalized_thickness_mm", _own_t[0],
                                   "own_sheet_title_block",
                                   note=f"stated on its own sheet (page "
                                        f"{', '.join(str(p) for p in own_pages)})"):
                    part["thicknesses_mm"] = [f"{_own_t[0]:g}"]
                    notes.append(f"gauge {_own_t[0]:g} mm from its own sheet"
                                 + (f", not {_cur_t:g} mm" if _cur_t else ""))
            except Exception:                                        # noqa: BLE001
                pass
        # THE FEATURES AND PAGE GEOMETRY — only where another sheet's were collected with them.
        for key in (_OWN_SHEET_CUES if foreign else ()):
            vals: List[Any] = []
            for s in own:
                vals.extend(((s.get("page_analysis") or {}).get("feature_cues") or {}).get(key) or [])
            if list(part.get(key) or []) != vals:
                part[key] = vals
                notes.append(f"{key.replace('_', ' ')} from its own sheet")
        # THE GEOMETRY ITS OWN SHEET'S VECTORS HOLD — never over a measured flat.
        if foreign and not blank_is_measured(part) and not part.get("dxf_augmented"):
            geo = _sum_page_geometry(own)
            roll = part.get("geometry_rollup") if isinstance(part.get("geometry_rollup"), dict) else None
            if roll is not None and geo:
                before = (roll.get("estimated_cut_length_mm"), roll.get("estimated_hole_count"))
                for k, v in geo.items():
                    if k in roll and isinstance(roll.get(k), (int, float)):
                        roll[k] = v
                after = (roll.get("estimated_cut_length_mm"), roll.get("estimated_hole_count"))
                if before != after:
                    notes.append(f"cut path {after[0]:,.0f} mm and {int(after[1] or 0)} hole(s) "
                                 f"from its own sheet, not {float(before[0] or 0):,.0f} mm and "
                                 f"{int(before[1] or 0)}")
                for holder in (part.get("normalized_geometry"), part.get("manufacturing_features")):
                    if not isinstance(holder, dict):
                        continue
                    for key, val in (("cut_length_mm", after[0]), ("raw_cut_length_mm", after[0]),
                                     ("hole_count", after[1])):
                        if key in holder and str(holder.get(f"{key}_source") or "") in ("", "pdf",
                                                                                      "page_vectors"):
                            holder[key] = val   # precedence: direct-write ok — re-derived from the part's own sheet
        if notes:
            part["_own_sheet_revalidation"] = {"own_pages": own_pages, "foreign_pages": foreign,
                                               "changed": notes}
            part.setdefault("review_flags", []).append(
                f"READ FROM ITS OWN SHEET: {pn} — " + (
                    f"bound to page(s) {', '.join(str(b) for b in foreign)} as well as its own "
                    f"({', '.join(str(p) for p in own_pages)}); " if foreign else
                    f"its own sheet is page(s) {', '.join(str(p) for p in own_pages)}; ")
                + f"{'; '.join(notes)}. Figures read elsewhere belong to the parts they draw")
            changed.append(pn)
    return changed


def _made_here(part: Mapping[str, Any]) -> bool:
    """A part SDI makes: not an assembly (sized through its members), not bought in, not supplied
    by another party. A section IS made here (D-592) — not_cut_from_a_blank says no blank stands
    in for it, which is true, but its weight and features are still read off a sheet, and on
    0351292 the cross rail kept the support assembly's 2.5 kg and both sheets' lines because the
    re-read skipped every section."""
    if not isinstance(part, Mapping):
        return False
    if not not_cut_from_a_blank(part):
        return True
    if not _is_section_stock(part):
        return False
    ctx = part.get("route_context") if isinstance(part.get("route_context"), Mapping) else {}
    if (part.get("is_assembly_parent") or part.get("is_sub_assembly") or part.get("assembly_children")
            or ctx.get("is_assembly_parent") or part.get("supplied_by_third_party")):
        return False
    try:
        from bought_in_policy import is_bought_in
        return not is_bought_in(dict(part))
    except Exception:                                                # noqa: BLE001
        return True


_OUTLINES_A_PAGE_CUT_PATH_MAY_SPAN = 3.0
_MIN_HOLE_PITCH_MM = 8.0
UNVERIFIED_FEATURES = "read_off_the_drawing_lines"
CUT_OUT_ALLOWANCE = "cut_out_allowance"


def _punched_family_named(part: Mapping[str, Any]) -> bool:
    """The drawing names a punched or perforated pattern — the estimator's own punch keywords
    (config PUNCH_RECOGNITION), read from the same words, so the two never disagree."""
    blob = " ".join([str(part.get("description") or ""), str(part.get("part_number") or ""),
                     ";".join(str(n) for n in (part.get("process_notes") or []))]).upper()
    try:
        import config as _c
        words = (getattr(_c, "PUNCH_RECOGNITION", {}) or {}).get("punch_keywords") or []
    except Exception:                                                # noqa: BLE001
        words = []
    return any(str(w).upper() in blob for w in words)


def _blank_holds_cutting(part: Mapping[str, Any], length: float,
                         width: float) -> Tuple[str, str]:
    """How far this blank may bound the part's page-read cutting (D-592, cross-pack replay).

    ("outline", why) — the blank stands for the part and little is cut from it: cut as its
    outline. ("ceiling", why) — the stated weight says material IS cut out: the cutting is
    real but unread, held at the most the rule lets a blank's own cutting be. ("", why) — the
    blank does not stand for the part, so it bounds nothing.

    401918's replay is why: its base panel's blank was its assembly's outline (an allowance,
    8 kg on 324 x 77 mm), and its bracket's blank weighs 3x the stated part — cut-outs. Both
    had their cutting cut to an outline that was not theirs."""
    src = str(part.get("blank_length_mm_source")
              or (part.get("normalized_geometry") or {}).get("blank_length_mm_source") or "")
    if src == ASSEMBLY_ALLOWANCE_SOURCE or part.get("_blank_capped_to_assembly"):
        return "", "its blank is its assembly's outline, an allowance and not its own size"
    if _punched_family_named(part):
        return "", "its drawing names a punched pattern, where a long cut path can be its own"
    cfg = _cfg()
    weight = _stated_weight_kg(part)
    t = _num(part.get("normalized_thickness_mm") or part.get("thickness_mm"))
    mat = str(part.get("normalized_material") or "").upper()
    dens = next((float(d) for k, d in (cfg.get("density_kg_m3") or {}).items() if k in mat), None)
    if not (weight and t and dens):
        return "outline", "no stated weight checks the blank"
    ratio = (length * width / 1e6) / (weight / (t / 1000.0 * dens))
    lo = float(cfg.get("min_blank_to_part_weight_ratio") or 0.9)
    hi = float(cfg.get("weight_question_above_ratio") or 1.6)
    if ratio < lo:
        return "", (f"a {length:g} x {width:g} mm blank at {t:g} mm would weigh {ratio:.2f}x the "
                    f"stated {weight:g} kg, less than the part cut from it, so the blank is in "
                    f"question, not the cutting")
    if ratio > hi:
        return "ceiling", (f"the blank weighs {ratio:.2f}x the stated {weight:g} kg, so material "
                           f"is cut out of it")
    return "outline", f"the blank agrees with the stated {weight:g} kg ({ratio:.2f}x)"


def bound_cutting_to_blank(part: Dict[str, Any], length_mm: Any = None,
                           width_mm: Any = None) -> List[str]:
    """Hold one part's page-read cutting and holes to what its blank can hold (D-591, D-592).
    Returns the sentences it wrote; [] when nothing was out of bounds, the flat is measured, or
    the blank does not stand for the part (`_blank_holds_cutting`: then the figures are kept
    as read, flagged and asked, under `_cut_path_not_bounded`).

    The figures read off a page are CANDIDATES, never measurements: a cut path past three times
    the blank's outline is the page's lines (views, borders, other parts) — cut as the outline,
    and the internal cutting is UNREAD; holes past what fits at an 8 mm pitch are UNREAD. Unread
    is recorded as unread — `None` on every holder and `_internal_features_unread` on the part —
    never as "no holes", and the part is put on the decisions list: the outline is a provisional
    allowance for the profile, not its finished contour. Called during the scan, and again by
    the estimator on the blank the material was costed on, so a blank that arrives late is held
    to the same rule."""
    if not isinstance(part, dict) or not _made_here(part) or _is_section_stock(part):
        return []
    try:
        from blank_credibility import blank_is_measured
    except Exception:                                                # noqa: BLE001
        return []
    if blank_is_measured(part) or part.get("dxf_augmented"):
        return []
    L, W = _num(length_mm), _num(width_mm)
    if not (L and W):
        L, W = _blank_pair(part)
    if not (L and W):
        return []
    outline = 2.0 * (L + W)
    ceiling = outline * _OUTLINES_A_PAGE_CUT_PATH_MAY_SPAN
    holders = [h for h in (part.get("normalized_geometry"), part.get("geometry_rollup"),
                           part.get("manufacturing_features")) if isinstance(h, dict)]
    cut_keys = ("cut_length_mm", "estimated_cut_length_mm", "raw_cut_length_mm")
    hole_keys = ("hole_count", "estimated_hole_count", "estimated_pierce_count")
    cuts = [float(h.get(k) or 0) for h in holders for k in cut_keys
            if isinstance(h.get(k), (int, float))]
    worst = max(cuts) if cuts else 0.0
    cap = max(1, int((L * W) // (_MIN_HOLE_PITCH_MM ** 2)))
    holes = [int(h.get(k) or 0) for h in holders for k in hole_keys
             if isinstance(h.get(k), (int, float))]
    over_cut = worst > ceiling
    holes_unread = bool(holes) and max(holes) > cap
    if not (over_cut or holes_unread):
        return []
    pn = str(part.get("part_number") or "this part")
    # THE BLANK MUST STAND FOR THE PART BEFORE IT BOUNDS ANYTHING (D-592). An allowance, a
    # blank the stated weight calls too small, or a punched pattern bounds nothing: the page's
    # figures are kept as read — candidates, said and asked — rather than cut to an outline
    # that is not the part's.
    mode, why = _blank_holds_cutting(part, L, W)
    if not mode:
        if not part.get("_cut_path_not_bounded"):
            part["_cut_path_not_bounded"] = why
            _n = max(holes or [0])
            _read = f"{worst:,.0f} mm of cutting" + (f" and {_n} hole(s)" if _n else "")
            part.setdefault("review_flags", []).append(
                f"CUTTING NOT HELD TO THE BLANK: {pn} — {_read} read off the drawing's lines, "
                f"more than a {L:g} x {W:g} blank holds, but {why}: kept as read, unverified, "
                f"and asked")
            try:
                from source_precedence import raise_manufacturing_question as _ask
                _ask(part, f"Cutting of {pn}: {_read} read off the drawing's lines, more than "
                           f"its {L:g} x {W:g} blank holds",
                     f"kept as read because {why} — the page's lines may include other views, "
                     f"notes and the title block, so the figure is a candidate, not a measurement",
                     "give the DXF, or confirm the blank, the hole count and the internal cutting",
                     "detail_page_geometry.bound_cutting_to_blank")
            except Exception:                                        # noqa: BLE001
                pass
        return []
    allow = outline if mode == "outline" else ceiling
    notes: List[str] = []
    if over_cut:
        for h in holders:
            for k in cut_keys:
                if isinstance(h.get(k), (int, float)) and float(h.get(k) or 0) > allow:
                    h[k] = round(allow, 1)   # precedence: direct-write ok — bounded by the part's own blank
        if mode == "outline":
            notes.append(f"the {worst:,.0f} mm cut path is more than "
                         f"{_OUTLINES_A_PAGE_CUT_PATH_MAY_SPAN:g}x the {L:g} x {W:g} blank's "
                         f"outline, so it is a page's lines, not this part's, and {why}: cut "
                         f"as the outline ({outline:,.0f} mm) — a provisional allowance — and "
                         f"internal cutting unread")
        else:
            notes.append(f"the {worst:,.0f} mm cut path is more than "
                         f"{_OUTLINES_A_PAGE_CUT_PATH_MAY_SPAN:g}x the {L:g} x {W:g} blank's "
                         f"outline, so it is a page's lines; but {why}: its own cutting is "
                         f"real and unread, held at {ceiling:,.0f} mm, the most this rule lets a "
                         f"blank's own cutting be — a provisional allowance")
    # Holes past what the blank holds are UNREAD. On an outline-only part every hole holder is
    # unread: the circles are the same page's as the lines just set aside. Unread is None on
    # the record, never zero.
    unread = False
    for h in holders:
        for k in hole_keys:
            if isinstance(h.get(k), (int, float)) and (mode == "outline" and over_cut
                                                        or int(h.get(k) or 0) > cap):
                h[k] = None   # precedence: direct-write ok — UNREAD, not zero
                unread = True
    if holes_unread:
        notes.append(f"{max(holes)} holes cannot fit a {L:g} x {W:g} blank at a "
                     f"{_MIN_HOLE_PITCH_MM:g} mm pitch (at most {cap}), so the count is the "
                     f"page's: holes UNREAD — not costed, and not zero")
    elif unread:
        notes.append("the circles on that page are not this part's either: holes UNREAD — not "
                     "costed, and not zero")
    if notes and not part.get("_cut_path_bounded"):
        part["_cut_path_bounded"] = notes
        part["_internal_features_unread"] = True
        part["_cut_allowance"] = {"mode": mode, "cut_mm": round(allow, 1), "why": why}
        part.setdefault("review_flags", []).append(
            f"CUTTING FROM THE BLANK: {pn} — {'; '.join(notes)}. Give the DXF and the cutting "
            f"is costed from it")
        try:
            from source_precedence import raise_manufacturing_question as _ask
            _ask(part, f"Cutting of {pn}: internal features unread",
                 (f"costed on its {L:g} x {W:g} outline only ({outline:,.0f} mm)"
                  if mode == "outline" else
                  f"its stated weight says material is cut out of its {L:g} x {W:g} blank; "
                  f"cutting held at {ceiling:,.0f} mm")
                 + " — a provisional allowance; the holes and internal cutting on its drawing "
                   "were not measured, and the page's lines are not them",
                 "give the DXF, or the hole count and sizes, and the cutting is costed from it",
                 "detail_page_geometry.bound_cutting_to_blank")
        except Exception:                                            # noqa: BLE001
            pass
    return notes


def bound_unmeasured_cut_path(parts: Any) -> List[str]:
    """Every part's page-read cutting held to its blank (see bound_cutting_to_blank). Returns
    the part numbers bounded."""
    if not isinstance(parts, Sequence):
        return []
    return [str(p.get("part_number") or "this part") for p in parts
            if isinstance(p, dict) and bound_cutting_to_blank(p)]


def machining_evidence(part: Mapping[str, Any]) -> Dict[str, Any]:
    """Where this part's holes and cutting come from, said once for every reader (D-592).

    {basis, measured, holes, cut_mm, label}. `basis` is "measured" (a DXF or model flat),
    "outline_only" (bounded: internal features unread), CUT_OUT_ALLOWANCE (bounded at the
    ceiling: the stated weight says material is cut out, its features unread), or
    UNVERIFIED_FEATURES (circles and
    lines read off the drawing's vectors — candidates, never measurements). A reader that
    charges punch hits or pierces from an unmeasured count says so in these words."""
    try:
        from blank_credibility import blank_is_measured
        measured = bool(blank_is_measured(dict(part)) or part.get("dxf_augmented"))
    except Exception:                                                # noqa: BLE001
        measured = bool(part.get("dxf_augmented"))
    ng = part.get("normalized_geometry") if isinstance(part.get("normalized_geometry"), Mapping) else {}
    holes = ng.get("hole_count")
    if part.get("_internal_features_unread"):
        allowance = part.get("_cut_allowance") if isinstance(part.get("_cut_allowance"), Mapping) else {}
        if allowance.get("mode") == "ceiling":
            return {"basis": CUT_OUT_ALLOWANCE, "measured": False, "holes": holes,
                    "cut_mm": ng.get("cut_length_mm"),
                    "label": (f"internal features unread — the weight says material is cut out; "
                              f"cutting held at {float(allowance.get('cut_mm') or 0):,.0f} mm, "
                              f"a provisional allowance")}
        return {"basis": "outline_only", "measured": False, "holes": None,
                "cut_mm": ng.get("cut_length_mm"),
                "label": "internal features unread — costed on the outline only"}
    if measured:
        return {"basis": "measured", "measured": True, "holes": holes,
                "cut_mm": ng.get("cut_length_mm"), "label": "measured"}
    return {"basis": UNVERIFIED_FEATURES, "measured": False, "holes": holes,
            "cut_mm": ng.get("cut_length_mm"),
            "label": "read off the drawing's lines — unverified, not measured"}


def settle_fold_evidence(parts: Any) -> List[str]:
    """A fold the fold counter charges from the drawing carries that drawing evidence on its
    operation too (D-592). Returns the part numbers settled.

    0351292's strip: its own sheet prints a 90° angle, the fold counter took it as a stated fold
    and developed the blank for one flange (1293 x 37), while the route said "Folding has no
    recorded source" and put the fold on the decisions list as unsupported. One fold, two
    verdicts. Where the counter's evidence is the drawing's — a fold note, its callouts, the
    flat pattern, the model — the operation is given that evidence in words, so the route and
    the blank agree; where it is not, neither the flange nor the fold is claimed from it."""
    out: List[str] = []
    if not isinstance(parts, Sequence):
        return out
    try:
        from fold_count import press_brake_folds
    except Exception:                                                # noqa: BLE001
        return out
    for part in parts:
        if not isinstance(part, dict):
            continue
        ops = {str(o).lower() for k in ("textual_operations", "inferred_operations", "operations")
               for o in (part.get(k) or [])}
        if not ops & {"folding", "fold", "bending"} or _fold_op_has_evidence(part):
            continue
        res = press_brake_folds(dict(part))
        if str(res.get("source") or "") not in _FOLD_EVIDENCE_SOURCES or not res.get("count"):
            continue
        _angles = [str(a) for a in (part.get("angles_deg") or [])][:4]
        words = (f"{int(res['count'])} fold(s) — {res.get('source_label') or res.get('source')}"
                 + (f" (angle{'s' if len(_angles) > 1 else ''} {', '.join(_angles)}° on its own sheet)"
                    if _angles else ""))
        part.setdefault("operation_evidence", {})["folding"] = words
        out.append(str(part.get("part_number") or "this part"))
    return out


def stamp_rolled_radii(parts: Any, summary: Mapping[str, Any]) -> List[str]:
    """Mark each sheet part its own drawing shows ROLLED: a radius printed on its own sheet that
    its flat cannot hold (D-589). Returns the part numbers marked.

    0351292's downstand ROL2021-2410 is a 25 mm strip, 1435.2 mm developed, whose sheet prints
    R225 beside a flat pattern; the base plate it runs round prints the same R225 on a 1154 x
    450 flat. On the plate it is a corner of the profile — the laser cuts it. On a 25 mm strip
    it cannot be: no 25 mm flat has a 225 mm corner, so the strip is rolled to it. Nothing
    charged a roll. The rule is the geometry, not the part: a radius at least
    ROLL_FROM_RADIUS's floor and multiple of the gauge, LARGER than the smaller side of the
    part's own blank, on a part its sheet shows formed (a flat pattern, or a fold). Read from
    the part's own sheet only (own_sheets), never from an assembly sheet that lists it."""
    if not isinstance(parts, Sequence) or not isinstance(summary, Mapping):
        return []
    try:
        import config
        rule = dict(getattr(config, "ROLL_FROM_RADIUS", {}) or {})
    except Exception:                                                # noqa: BLE001
        rule = {}
    if not rule:
        return []
    floor = float(rule.get("min_radius_mm") or 50.0)
    to_gauge = float(rule.get("min_radius_to_gauge") or 20.0)
    developed_re = re.compile(str(_cfg().get("developed_words") or "$^"), re.I)
    marked: List[str] = []
    for part in parts:
        if not isinstance(part, dict) or part.get("rolled_radius"):
            continue
        if _is_section_stock(part) or not_cut_from_a_blank(part):
            continue
        t = _num(part.get("normalized_thickness_mm") or part.get("thickness_mm"))
        bl, bw = _blank_pair(part)
        if not (t and bl and bw):
            continue
        short = min(bl, bw)
        sheets = own_sheets(part, summary)
        if not sheets:
            continue
        text = "\n".join(str(s.get("text") or s.get("page_text") or "") for s in sheets)
        if not text.strip():
            text = "\n".join(str(read_sheet_figures(s).get("text") or "") for s in sheets)
        radii = sorted({float(m.replace(",", ".")) for m in _RADIUS_TEXT.findall(text)},
                       reverse=True)
        big = [r for r in radii if r >= floor and r >= to_gauge * t and r > short]
        if not big:
            continue
        formed = bool(developed_re.search(text)) or _is_folded(part) or _fold_count(part) > 0
        if not formed:
            continue
        r = big[0]
        pgs = [s.get("page_number") for s in sheets]
        pn = str(part.get("part_number") or "this part")
        why = (f"R{r:g} is printed on its own sheet (page {', '.join(str(p) for p in pgs)}) "
               f"and its blank is {bl:g} x {bw:g} mm: no {short:g} mm flat holds a {r:g} mm "
               f"corner, so the part is rolled to that radius")
        part["rolled_radius"] = {"radius_mm": r, "pages": pgs, "why": why}
        part.setdefault("operation_evidence", {}).setdefault("roll", why)
        part.setdefault("review_flags", []).append(
            f"ROLLING FROM THE RADIUS: {pn} — {why}. Charged on the Roll row at the template's "
            f"set-up and an allowance per piece (config ROLL_FROM_RADIUS) — an allowance, not "
            f"a shop time; confirm it is rolled and the time")
        try:
            from source_precedence import raise_manufacturing_question as _ask
            _ask(part, f"Rolling of {pn}: R{r:g} from its own sheet",
                 why, "confirm it is rolled to this radius, and the rolling time",
                 "detail_page_geometry.stamp_rolled_radii")
        except Exception:                                            # noqa: BLE001
            pass
        marked.append(pn)
    return marked


def mirror_provisional_blanks(parts: Any) -> List[str]:
    """THE OTHER HAND TAKES ITS BASE'S PROVISIONAL BLANK, AND SAYS SO (D-508).

    12665-03-01M-H, the side wing built the other way round, was charged its laser and its fold
    and no steel: the mirror rule runs at merge time, before 03-01M had any blank, and it
    deliberately refuses an unmeasured base (inheriting a guess at a measured rank is the one
    thing it must never do). So the hand reached costing with nothing to nest.

    A hand develops the same flat as its base. Where the base was given a PROVISIONAL blank
    and the hand holds no size of its own (nothing, or only an engine inference), the hand
    takes it at the same provisional standing — labelled as mirrored, asked like the base —
    and its material, gauge and finish where it states none. A hand that states its own size
    or its own stock keeps them: its handed differences are the drawing's. Returns the hands
    filled."""
    if not isinstance(parts, Sequence):
        return []
    try:
        from part_code_conventions import carries_assembly_role, mirror_base
    except Exception:                                                # noqa: BLE001
        return []
    import source_precedence as sp

    def _key(pn: Any) -> str:
        return re.sub(r"\s+", "", str(pn or "")).upper()

    by_key = {_key(p.get("part_number")): p for p in parts if isinstance(p, dict)}
    filled: List[str] = []
    for hand in parts:
        if not isinstance(hand, dict):
            continue
        hpn = str(hand.get("part_number") or "")
        base_pn = mirror_base(hpn) or str(hand.get("mirror_of") or "").strip()
        base = by_key.get(_key(base_pn)) if base_pn else None
        if base is None or base is hand or not isinstance(base.get("_blank_provisional"), dict):
            continue
        if carries_assembly_role(hpn) or not_cut_from_a_blank(hand) or has_measured_flat(hand):
            continue
        _src = str(hand.get("blank_length_mm_source") or "")
        if _blank_pair(hand) != (None, None) and all(_blank_pair(hand)) \
                and sp.rank(_src) > sp.rank("geometry_inference"):
            continue                                  # its own size, whatever its standing
        bl, bw = _blank_pair(base)
        if not (bl and bw):
            continue
        _write_blank(hand, bl, bw, PROVISIONAL_SOURCE)
        for field in ("normalized_material", "normalized_thickness_mm", "normalized_finish"):
            if sp.value_of(hand, field) is sp.MISSING and sp.value_of(base, field) is not sp.MISSING:
                sp.apply_field(hand, field, sp.value_of(base, field), "mirror_of_provisional")
        hand["_blank_provisional"] = dict(base["_blank_provisional"],
                                          mirrored_from=str(base.get("part_number") or base_pn))
        hand["blank_is_inferred"] = True
        why = (f"PROVISIONAL BLANK, MIRRORED — {hpn} is the other hand of "
               f"{base.get('part_number')} and develops the same flat, so it takes that part's "
               f"provisional {bl:g} x {bw:g} mm ({base['_blank_provisional'].get('working') or 'its own sheet'}). "
               f"Confirm {base.get('part_number')}'s flat blank and both hands follow it.")
        hand["blank_inferred_reason"] = why
        hand.setdefault("review_flags", []).append(why)
        sp.raise_manufacturing_question(
            hand, f"Blank of {hpn}: provisional {bl:g} x {bw:g} mm, mirrored from "
                  f"{base.get('part_number')}", why,
            f"confirm {base.get('part_number')}'s flat blank; this hand follows it",
            "detail_page_geometry.mirror_provisional_blanks")
        filled.append(hpn)
    return filled


def mint_missing_hand_records(parts: Any, bom_rows: Any) -> List[str]:
    """A HANDED BOM ROW THE PACK NEVER DREW BECOMES A RECORD OF ITS OWN (D-509).

    12665's GA lists 12665-03-01M-H — the side wing built the other way round — and the pack
    holds no sheet for it, so no reader ever made it a part record. The route compiler still
    charged its laser and its fold (route rows come from the BOM graph, not from records),
    the coat covered it, and its steel was £0 in silence until the missing-price check caught
    it AFTER costing. mirror_provisional_blanks (D-508) fills a hand's geometry, but it walks
    the part records: a hand with no record is invisible to it.

    THE PARTS-LIST ROW ITSELF IS THE SOURCE, NOT THE COMPILED GRAPH. The first version of
    this mint walked the pre-cost graph's nodes, and the 18:13 run proved that wrong twice
    over: 12665-03-01M-H hangs under 12665-03-GA-H, a handed ASSEMBLY the graph refuses to
    own ("name an owner this job does not recognise"), and a row whose owner is refused gets
    no edge AND NO NODE — the hand was invisible to the very pass written for it. The
    drawing's printed row and the mirrorable base ARE the evidence; disconnection is the
    symptom this mint exists to price through.

    So: a stated BOM row whose code mirrors an existing cut part's and which no record
    answers to gets a record of its own — the base's material, gauge and finish at the
    mirror's gap-fill standing, the row's own quantity, and NO geometry of its own: the
    mirror pass that runs next fills the blank at provisional standing, labelled and asked,
    exactly as for a hand that was drawn. A hand of an assembly, a hand of a part that cuts
    no blank (bought in, supplied), and a code a record already answers to are left alone.
    Returns the codes minted."""
    if not isinstance(parts, list) or not isinstance(bom_rows, Sequence):
        return []
    try:
        from part_code_conventions import carries_assembly_role, mirror_base
    except Exception:                                                # noqa: BLE001
        return []
    import source_precedence as sp

    def _key(pn: Any) -> str:
        return re.sub(r"\s+", "", str(pn or "")).upper()

    by_key = {_key(p.get("part_number")): p for p in parts if isinstance(p, dict)}
    minted: List[str] = []
    for row in bom_rows:
        if not isinstance(row, Mapping):
            continue
        pn = str(row.get("part_number") or "").strip()
        if not pn or _key(pn) in by_key:
            continue                           # a record already answers to this row
        if carries_assembly_role(pn):
            continue                           # a handed ASSEMBLY mirrors as a route, not a blank
        base = by_key.get(_key(mirror_base(pn)))
        if base is None or not_cut_from_a_blank(base):
            continue                           # nothing to be the other hand OF
        base_pn = str(base.get("part_number") or "")
        try:
            qty = float(row.get("quantity") or 1.0) or 1.0
        except (TypeError, ValueError):
            qty = 1.0
        rec: Dict[str, Any] = {
            "part_number": pn,
            "description": (str(row.get("description") or "").strip()
                            or f"{str(base.get('description') or base_pn).strip()} (opposite hand)"),
            "quantity": qty,
            "mirror_of": base_pn,
            "is_assembly_parent": False,
            "manufacturing_questions": [],
            "normalized_geometry": {},
            "_minted_hand_record": True,
        }
        for field in ("normalized_material", "normalized_thickness_mm", "normalized_finish"):
            value = sp.value_of(base, field)
            if value is not sp.MISSING:
                sp.apply_field(rec, field, value, "mirror_of_provisional")
        why = (f"RECORD MINTED FOR A HANDED ROW — {pn} is on the bill as the other hand of "
               f"{base_pn} and the pack holds no sheet for it, so no reader made it a record "
               f"and its material was heading for a silent £0 beside a charged route. It "
               f"takes that part's material, gauge and finish; its blank follows the mirror "
               f"rule (provisional, asked).")
        rec["review_flags"] = [why]
        sp.raise_manufacturing_question(
            rec, f"{pn}: no sheet of its own — record minted as the other hand of {base_pn}",
            why, f"confirm {pn} is {base_pn} made the opposite hand; its stock and blank "
                 f"follow that part", "detail_page_geometry.mint_missing_hand_records")
        parts.append(rec)
        by_key[_key(pn)] = rec
        minted.append(pn)
    return minted


ASSEMBLY_ALLOWANCE_SOURCE = "assembly_envelope_allowance"


def check_parts_against_their_assembly(parts: Any, summary: Mapping[str, Any]) -> List[str]:
    """A PART READ LARGER THAN THE ASSEMBLY IT SITS IN IS ASKED, AND COSTED ON THAT ASSEMBLY
    (D-508).

    12665-04-03A NEW BACK PLATE was costed at 1737 x 1684.7 mm — a whole 3050 x 2050 sheet of
    acrylic, £128.75, twice — inside a fascia assembly whose own sheet is 400 x 251.5 mm. A
    part can legitimately exceed its assembly's outline (a developed flange, an angled or
    projecting piece), so the outline is developed for the part's own folds at the flange
    allowance and given a tolerance before anything is said. Past that, the reading is not
    the part's size: the part is costed on the assembly's developed outline — a labelled,
    provisional allowance, never left unpriced — and the estimator is asked, with both
    figures. Only a size READ off a drawing is checked; a DXF, a model or a person is not.
    Returns the parts re-sized."""
    if not isinstance(parts, Sequence) or not isinstance(summary, Mapping):
        return []
    try:
        from part_code_conventions import bare_code
    except Exception:                                                # noqa: BLE001
        return []
    import source_precedence as sp
    cfg = _cfg()
    tol = float(cfg.get("assembly_envelope_tolerance") or 0.10)
    allowance = float(cfg.get("flange_allowance_mm") or 25)
    by_code = {bare_code(str(p.get("part_number") or "")): p
               for p in parts if isinstance(p, dict)}
    parent_of: Dict[str, str] = {}
    for row in ((summary.get("document_analysis") or {}).get("bom_rows") or []):
        if isinstance(row, Mapping) and row.get("bom_parent") and row.get("part_number"):
            parent_of.setdefault(bare_code(str(row["part_number"])), str(row["bom_parent"]))
    resized: List[str] = []
    for part in parts:
        if not isinstance(part, dict) or not_cut_from_a_blank(part) or has_measured_flat(part):
            continue
        pl, pw = _blank_pair(part)
        if not (pl and pw):
            continue
        src = str(part.get("blank_length_mm_source")
                  or (part.get("normalized_geometry") or {}).get("blank_length_mm_source") or "")
        if sp.rank(src) >= sp.rank("estimator_read_drawing") or src == ASSEMBLY_ALLOWANCE_SOURCE:
            continue
        pn = str(part.get("part_number") or "")
        parent_pn = str(part.get("bom_parent") or parent_of.get(bare_code(pn)) or "")
        parent = by_code.get(bare_code(parent_pn)) if parent_pn else None
        if parent is None or parent is part:
            continue
        env = parent.get("_sheet_envelope_mm") if isinstance(parent.get("_sheet_envelope_mm"),
                                                             Mapping) else None
        if env is None:
            el, ew = _blank_pair(parent)
            env = {"length": max(el, ew), "width": min(el, ew)} if el and ew else None
        if not env:
            continue
        folds = _fold_count(part)
        cap_l = float(env["length"]) + folds * allowance
        cap_w = float(env["width"]) + folds * allowance
        big, small = max(pl, pw), min(pl, pw)
        if big <= cap_l * (1 + tol) and small <= cap_w * (1 + tol):
            continue
        new_l, new_w = min(big, cap_l), min(small, cap_w)
        part["_blank_capped_to_assembly"] = {
            "read_mm": [round(big, 1), round(small, 1)], "read_source": src or "unrecorded",
            "assembly": parent_pn, "assembly_outline_mm": [env["length"], env["width"]],
            "folds": folds, "costed_mm": [round(new_l, 1), round(new_w, 1)]}
        _write_blank(part, new_l, new_w, ASSEMBLY_ALLOWANCE_SOURCE)
        part["blank_is_inferred"] = True
        why = (f"SIZE LARGER THAN ITS ASSEMBLY — {pn} read as {big:g} x {small:g} mm "
               f"({sp.display_name(src) or 'an unrecorded reading'}), but it sits in "
               f"{parent_pn}, whose own outline is {float(env['length']):g} x "
               f"{float(env['width']):g} mm — {cap_l:g} x {cap_w:g} mm even allowing "
               f"{folds} fold(s) at {allowance:g} mm. The reading is not taken as its size: it "
               f"is costed PROVISIONALLY on {new_l:g} x {new_w:g} mm, the assembly's developed "
               f"outline, until its own size is confirmed.")
        part["blank_inferred_reason"] = why
        part.setdefault("review_flags", []).append(why)
        sp.raise_manufacturing_question(
            part, f"Size of {pn}: read {big:g} x {small:g} mm, larger than {parent_pn} "
                  f"({float(env['length']):g} x {float(env['width']):g} mm) it sits in", why,
            "confirm the part's own size (its blank, or the DXF) — material, cutting and "
            "shipment follow it", "detail_page_geometry.check_parts_against_their_assembly")
        resized.append(pn)
    return resized


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
