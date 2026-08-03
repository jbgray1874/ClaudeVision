"""
Merge flat-pattern DXF geometry into PDF scan summaries.

Policy:
  - DXF wins: area/extents, cut length, holes, bends, geometry reliability.
  - PDF wins: BOM, quantities, materials, finish, client, revision, assembly structure.
  - No matching DXF: PDF geometry unchanged (typically ~0.97 reliability, not 1.0).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from source_precedence import apply_field as _apply_field

import config
from document_builder import _empty_geometry_rollup, _empty_part_record, _interpret_part, _rollup_geometry
from dxf_reader import (
    analyse_dxf_document_geometry,
    extract_dxf_geometry,
    extract_dxf_pages,
    extract_flat_pattern_data,
    is_dxf_path,
)

try:
    from dxf_reader import _parse_filename
except ImportError:
    _parse_filename = None  # type: ignore

from estimator import estimate_document


def _normalize_part_key(part_number: str) -> str:
    try:
        from part_identity import normalize_part_code

        return normalize_part_code(part_number)
    except Exception:
        return re.sub(r"\s+", "", str(part_number or "")).upper()


def part_number_from_dxf_path(path: Path) -> Optional[str]:
    """Extract BOM part number from a flat DXF filename (e.g. 9376-01-001)."""
    if _parse_filename is not None:
        try:
            parsed = _parse_filename(path)
            if parsed.get("part_number"):
                return str(parsed["part_number"]).upper().replace(" ", "")
        except Exception:
            pass
    stem = path.stem.upper().replace("_", "-")
    cfg = getattr(config, "DRAWING_JOB_DISCOVERY", {}) or {}
    patterns: Sequence[str] = cfg.get(
        "part_number_from_dxf_patterns",
        [r"(?P<pn>\d{4,5}-\d{2}-\d{3}[A-Z]?)"],
    )
    for pattern in patterns:
        match = re.search(pattern, stem, flags=re.IGNORECASE)
        if match:
            return match.group("pn").upper().replace(" ", "")
    return None


def job_prefix_from_path(path: Path) -> Optional[str]:
    """Job family prefix such as 9376-01 from drawing or DXF names."""
    match = re.search(r"(\d{4,5}-\d{2})\b", path.stem, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def is_ignored_ga_dxf(path: Path) -> bool:
    """GA / assembly sheet DXFs are not flat-pattern geometry sources."""
    name = path.name.upper()
    if "-GA_" in name or "_GA_" in name:
        return True
    if re.search(r"[-_]GA[-_.]", name, flags=re.IGNORECASE):
        return True
    cfg = getattr(config, "DRAWING_JOB_DISCOVERY", {}) or {}
    for token in cfg.get("ignore_dxf_name_tokens", ["-GA-", "_GA_"]):
        if token.upper() in name:
            return True
    return False


def is_flat_part_dxf(path: Path) -> bool:
    """CHEAP, FILENAME-ONLY gate used during discovery. Content is checked separately by
    drawing_export_reason() at the point geometry is actually applied — see there for why a
    name alone cannot tell a flat pattern from a drawing of one."""
    return is_dxf_path(path) and not is_ignored_ga_dxf(path) and bool(part_number_from_dxf_path(path))


# A flat pattern may carry an etch label or two. A DRAWING carries a title block.
_DRAWING_TEXT_ENTITIES = 8


def dxf_declares_bend_layer(path: Path) -> Optional[bool]:
    """Does this DXF's layer table contain a bend layer AT ALL? None when unreadable.

    THE DIFFERENCE BETWEEN A MEASURED ZERO AND NO MEASUREMENT. The bend reader returns an
    empty list both when a bend layer exists and is empty, and when the export carries no
    bend layer whatsoever. Those are opposite facts and the caller was treating them the
    same: on job 11350 the left arm's flat is a cut-only export with no bend layer, so
    "0 bend lines" ruled the fold off a part the drawing plainly shows formed.

    An explicit zero is a value; an absent layer is silence. Only the first can rule work
    out — which is the rule this codebase already applies everywhere else."""
    try:
        import ezdxf
        doc = ezdxf.readfile(str(path))
    except Exception:
        return None
    try:
        from dxf_reader import BEND_LAYERS as _BL
        _wanted = {str(n).upper() for n in _BL}
    except Exception:
        _wanted = {"BENDLINES", "BEND", "BEND_LINES"}
    try:
        return bool({str(layer.dxf.name).upper() for layer in doc.layers} & _wanted)
    except Exception:
        return None


def drawing_export_reason(path: Path) -> Optional[str]:
    """Why this DXF is a DRAWING of a part rather than the part's flat pattern — or None.

    THE FILENAME CANNOT TELL YOU. is_flat_part_dxf accepts anything that is a .dxf, is not
    named as a GA, and has a part number in its name — and a drawing exported straight out
    of SolidWorks satisfies all three. Job 11350 shipped five DXFs of which three are
    drawing exports carrying title blocks, dimensions and hundreds of annotation entities,
    under names indistinguishable from the two real flats.

    What that costs if it is missed: the title-block border and every dimension line get
    measured as cut path. The part comes back with a bounding box the size of an A3 sheet,
    a cut length several times the real one, and a hole count that includes the arrowheads
    — and every one of those numbers looks like a measurement, because it was measured.

    DIMENSION entities are decisive: a flat pattern has none, ever. A large body of
    TEXT/MTEXT is the second signal, thresholded so a flat with a couple of etch labels is
    not rejected. Deliberately conservative in that direction — wrongly rejecting a real
    flat costs geometry we could have had, which the run already reports; wrongly accepting
    a drawing puts fiction on the sheet.
    """
    try:
        import ezdxf
    except Exception:
        return None          # cannot read it — say nothing rather than guess
    try:
        doc = ezdxf.readfile(str(path))
        msp = doc.modelspace()
    except Exception:
        return None
    _dims = 0
    _texts = 0
    for _e in msp:
        _t = _e.dxftype()
        if _t == "DIMENSION":
            _dims += 1
        elif _t in ("TEXT", "MTEXT"):
            _texts += 1
    if _dims:
        return (f"{_dims} dimension entit{'y' if _dims == 1 else 'ies'} — this is a drawing "
                f"of the part, not its flat pattern")
    if _texts >= _DRAWING_TEXT_ENTITIES:
        return (f"{_texts} text entities (title block / notes) — this is a drawing of the "
                f"part, not its flat pattern")
    return None


# The range a sheet gauge can credibly be. Anything outside it in a filename is a
# dimension, a product name or a part code — not the material thickness.
SHEET_GAUGE_MIN_MM = 0.3
SHEET_GAUGE_MAX_MM = 25.0


def thickness_mm_from_dxf_filename(path: Path) -> Optional[float]:
    if _parse_filename is not None:
        try:
            parsed = _parse_filename(path)
            if parsed.get("thickness_mm") is not None:
                # BOUNDED HERE TOO. The shared parser runs first, so bounding only the
                # fallback below left the defect fully intact: "Left Arm 200mm_flat.dxf"
                # still came back as a 200mm gauge. A guard on the second reader is no
                # guard at all when the first one answers.
                _pv = float(parsed["thickness_mm"])
                if SHEET_GAUGE_MIN_MM <= _pv <= SHEET_GAUGE_MAX_MM:
                    return _pv
        except Exception:
            pass
    stem = path.stem
    # Comma decimal inside a thickness token: "1,2mm" -> "1.2mm" (SDI/European
    # SolidWorks exports use the comma; without this, "1,2mm" matched "2mm" -> 2.0).
    stem_norm = re.sub(r"(\d),(\d+)(\s*mm)", r"\1.\2\3", stem, flags=re.IGNORECASE)
    # Underscore decimal, but ONLY a single leading digit preceded by a non-digit
    # (e.g. "_1_5mm" -> "1.5mm"). The lookbehind stops the old rule mangling a part
    # number like "...-01_1mm" into "01.1mm" -> 1.1; that must read as 1.0.
    stem_norm = re.sub(r"(?<![\d.])(\d)_(\d+\s*mm)", r"\1.\2", stem_norm, flags=re.IGNORECASE)
    # A GAUGE, NOT THE FIRST NUMBER FOLLOWED BY "mm".
    #
    # This took the first <n>mm token in the stem with no plausibility bound, so
    # "Boots Comms Bar - Left Arm 200mm_flat.dxf" returned 200.0 — a 200mm-thick mild steel
    # arm — because the PRODUCT LENGTH is in the filename. Same class as the 1310-02 STUD,
    # where a bar's diameter was read as a sheet thickness: a number with a unit is not
    # automatically the number this function is looking for.
    #
    # Every token is considered and the first PLAUSIBLE one wins, so
    # "Left Arm 200mm_1mm MS" resolves to 1.0 rather than to the length that happens to come
    # first. Nothing plausible means no reading — the DXF geometry and the drawing still
    # carry a thickness, and a wrong gauge is far worse than an absent one.
    for _m in re.finditer(r"(\d+(?:\.\d+)?)\s*mm", stem_norm, flags=re.IGNORECASE):
        _v = float(_m.group(1))
        if SHEET_GAUGE_MIN_MM <= _v <= SHEET_GAUGE_MAX_MM:
            return _v
    return None


# Material tokens as they appear in SDI DXF filenames, most-specific first. The DXF
# filename is the manufacturing source of truth for material (it's what the laser/router
# is set from), so it is authoritative when the PDF-derived part record has no material
# or an unreliable one (e.g. MDF bleed onto an acrylic panel). Stem is underscore->space
# normalised so "_MS_" / "_HI ACR_" read as word-bounded tokens.
_DXF_MATERIAL_TOKENS: List[Tuple[str, str]] = [
    # HIPS (High Impact PolyStyrene) — must come before the ACRYLIC/HI-ACR tokens so a
    # "1mm HIPS" filename resolves to HIPS, not acrylic. HIPS is a distinct plastic with
    # its own live UDEF sheet price (labour still routes acrylic-like in the estimator).
    (r"\bHIPS\b|POLYSTYRENE", "HIPS"),
    (r"HI\s*ACR|HIGH\s*IMPACT\s*ACR", "HIGH IMPACT ACRYLIC"),
    (r"\bACRYLIC\b|\bACR\b|\bPERSPEX\b|\bPMMA\b", "ACRYLIC"),
    (r"POLYCARB|\bPC\b", "POLYCARBONATE"),
    (r"\bCARD\b|GREYBOARD|GREY\s*BOARD", "CARD"),
    (r"\bMDF\b", "MDF"),
    (r"PLYWOOD|\bPLY\b", "PLYWOOD"),
    (r"STAINLESS|\bSS\b|\b304\b|\b316\b", "STAINLESS STEEL"),
    (r"ALUMINI?UM|\bALUM?\b", "ALUMINIUM"),
    (r"GALV|ZINTEC", "ZINTEC"),
    (r"MILD\s*STEEL|\bMS\b|\bCR4\b|\bSPCC\b", "MILD STEEL"),
]


def material_from_dxf_filename(path: Path) -> Optional[str]:
    """Canonical material from a DXF filename token, or None if no token is present."""
    stem = path.stem.upper().replace("_", " ")
    for pat, mat in _DXF_MATERIAL_TOKENS:
        if re.search(pat, stem):
            return mat
    return None


def build_geometry_summary_for_dxf(dxf_path: Path) -> Tuple[Dict[str, Any], Dict[str, Any], float]:
    pages = extract_dxf_pages(dxf_path)
    geo_results = analyse_dxf_document_geometry(pages, dxf_path)
    page0 = (geo_results.get("pages") or [{}])[0]
    geometry = page0.get("geometry", {}) if isinstance(page0, dict) else {}
    reliability = float(
        (geometry.get("confidence") or {}).get("geometry_reliability", 0.0)
        or geo_results.get("document_geometry_reliability", 0.0)
        or 0.0
    )
    raw = extract_dxf_geometry(dxf_path)
    return geometry, raw, reliability


def _pierce_fields(verdict: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Flatten the arbitration into the geometry record: the VALUE costing reads, the SOURCE
    that produced it, and whether it is a measurement or a floor. Kept as three fields rather
    than one number, so a provisional figure cannot be mistaken for a measured one."""
    if not verdict:
        return {"estimated_pierce_count": None}
    return {
        "estimated_pierce_count": verdict.get("value"),
        "estimated_pierce_count_source": verdict.get("source"),
        "estimated_pierce_count_uncertain": bool(verdict.get("uncertain")),
    }


def _arbitrate_pierces(flat: Dict[str, Any], raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Which reader's pierce count do we cost?

    The two readers are not equal and must not be treated as interchangeable. The flat
    reader walks the file topologically: it explodes blocks, resolves inherited layers, and
    counts closed contours — circles, closed polylines, and loops assembled from separate
    lines and arcs. The raw reader does none of that. It never enters a block, and it counts
    every closed polyline as a pierce whether or not that polyline is the outer profile, so
    a part drawn as several short closed polylines is counted twice over: once as holes, once
    as profiles.

    So taking max() unconditionally, as this did, hands the decision to whichever reader
    happens to be more wrong in the upward direction. When the flat reader reports a complete
    walk, it IS the answer — a higher raw figure is inflation, not detail.

    The raw reader is used only where the flat walk admits it is incomplete: segments left
    unchained because the outline is drawn with gaps too large to close. There the flat
    count is a floor rather than an answer, a higher raw figure may be catching something
    real, and the part is flagged either way so a person sees it.
    """
    _flat = int(flat.get("estimated_pierce_count") or 0)
    _raw = int(raw.get("estimated_pierce_count") or 0)
    if not flat.get("pierce_count_incomplete"):
        if _flat:
            return {"value": _flat, "source": "dxf_contour_walk", "uncertain": False}
        if _raw:
            return {"value": _raw, "source": "dxf_raw_fallback", "uncertain": True,
                    "note": ("The contour walk found no pierces and the raw parser found "
                             f"{_raw}. Using the raw count, which does not enter blocks and "
                             "can count a profile twice — confirm against the drawing")}
        return None
    # The walk could not close its loops. Neither reading is a measurement now: the walk is a
    # floor, and the raw count is a different reader's guess with a known upward bias. Taking
    # the larger is a choice between two unreliable numbers, so it is recorded AS a choice —
    # value, source and uncertainty kept apart — and the part is marked provisional rather
    # than the maximum being laundered into a confident measured figure.
    _val = max(_flat, _raw)
    if not _val:
        return None
    return {"value": _val, "source": "dxf_incomplete_walk_max", "uncertain": True,
            "note": (f"DXF outline could not be fully closed. Pierce count is the larger of "
                     f"the contour walk ({_flat}) and the raw parser ({_raw}); it is a FLOOR, "
                     f"not a measurement")}


def apply_dxf_geometry_to_part(part: Dict[str, Any], dxf_path: Path) -> Dict[str, Any]:
    """
    Augment a part dict with DXF geometry.

    Priority:
      1. extract_flat_pattern_data — exact area, perimeter, weight, bends
         (geometry_score = 1.0, geometry_source = dxf_flat_pattern)
      2. build_geometry_summary_for_dxf — bbox extents, geometry rollup
         (fallback when flat-pattern detection fails)
    """
    # A DRAWING IS NOT A FLAT PATTERN, AND MEASURING ONE PRODUCES A MEASUREMENT.
    #
    # Refused here rather than at discovery, because this is the single point where DXF
    # geometry lands on a part — a guard anywhere else leaves the other callers open.
    # Recorded on the part, never silently skipped: a DXF that exists and was rejected is a
    # different fact from no DXF at all, and the estimator needs to know a flat is missing.
    _export_reason = drawing_export_reason(dxf_path)
    if _export_reason:
        part.setdefault("rejected_dxf_files", []).append(
            {"file": dxf_path.name, "reason": _export_reason})
        part.setdefault("review_flags", []).append(
            f"DXF {dxf_path.name} rejected: {_export_reason}. No flat pattern for this "
            f"part — geometry is from the drawing only.")
        return part

    geometry, raw, reliability = build_geometry_summary_for_dxf(dxf_path)
    part["geometry_rollup"] = _empty_geometry_rollup()
    _rollup_geometry(part["geometry_rollup"], geometry)

    flat: Optional[Dict[str, Any]] = None
    try:
        flat = extract_flat_pattern_data(dxf_path)
    except Exception:
        flat = None

    if flat and flat.get("flat_pattern_detected") and float(flat.get("blank_area_mm2") or 0) > 0:
        ng = part.get("normalized_geometry") or {}
        ng.update({
            "blank_length_mm": flat["blank_length_mm"],
            "blank_width_mm": flat["blank_width_mm"],
            "blank_area_mm2": flat["blank_area_mm2"],
            "perimeter_mm": flat["perimeter_mm"],
            "weight_kg": flat["weight_kg"],
            "weight_g": flat["weight_g"],
            "geometry_source": "dxf_flat_pattern",
            "geometry_confidence": 1.0,
        })
        part["normalized_geometry"] = ng
        part["geometry_score"] = 1.0
        part["flat_pattern_detected"] = True
        part["overall_length_mm"] = flat["blank_length_mm"]
        part["overall_width_mm"] = flat["blank_width_mm"]
        reliability = 1.0
        # DXF flat-pattern is what the press brake bends from — ground truth.
        # If it shows 0 bends, this part does NOT fold, even if a shared/document
        # 'fold' note baked 'folding' into textual_operations at extraction time.
        # Strip it here — this branch runs for every genuine flat-pattern part and
        # is upstream of (and not gated by) the conditional re-infer block. The
        # downstream routing reads this exact list to emit the Fold op.
        if int(flat.get("bend_count") or 0) == 0:
            for _k in ("operations", "textual_operations"):
                _ops = part.get(_k)
                if isinstance(_ops, list) and "folding" in _ops:
                    part[_k] = [_o for _o in _ops if _o != "folding"]   # precedence: direct-write ok — removes an op, adds no evidence   # precedence: direct-write ok — removes an op, adds no evidence

        if flat.get("thickness_mm"):
            # From the measured flat pattern — rank 80. Submitted even when a value is
            # already present: `is None` protected whatever arrived first rather than
            # whatever is better, and left the datum unattributed either way.
            _apply_field(part, "normalized_thickness_mm", flat["thickness_mm"], "dxf")
            if not part.get("thicknesses_mm"):
                part["thicknesses_mm"] = [str(flat["thickness_mm"])]

        _mat_fn = flat.get("material_from_filename") or material_from_dxf_filename(dxf_path)
        if _mat_fn and (
            not part.get("normalized_material")
            or str(part.get("normalized_material") or "").strip().upper() in {"MDF", "NONE", ""}
        ):
            # "Authoritative" overstated it: this is the characters in a FILENAME, a naming
            # convention someone typed, not a measurement. It ranks as inference and must
            # lose to the model, a measured DXF material and the printed title block.
            _apply_field(part, "normalized_material", _mat_fn, "inference")

        weight_g = float(flat.get("weight_g") or 0.0)
        if weight_g > 0:
            weight_label = f"{weight_g:.2f}g"
            weights = list(part.get("weights") or [])
            if weight_label not in weights:
                weights.append(weight_label)
            part["weights"] = weights
            part["dxf_weight_g"] = weight_g
            part["dxf_weight_kg"] = float(flat.get("weight_kg") or weight_g / 1000.0)

        if flat.get("bend_count", 0) > 0:
            part["bend_count_dxf"] = flat["bend_count"]
            part["flange_lengths_mm"] = flat["flange_lengths_mm"]
            part["bend_positions_mm"] = flat["bend_positions_mm"]
            part["symmetric_flanges"] = flat.get("symmetric_flanges", False)
            part["fold_count_textual"] = max(part.get("fold_count_textual", 0), int(flat["bend_count"]))

        if flat.get("corner_notch_count", 0) > 0:
            part["corner_notch_count"] = flat["corner_notch_count"]
            part["notch_length_mm"] = flat.get("notch_length_mm")

        if flat.get("hole_diameters_mm"):
            existing = [float(h) for h in part.get("hole_sizes_mm", []) if h is not None]
            part["hole_sizes_mm"] = sorted(set(existing + [float(h) for h in flat["hole_diameters_mm"]]))

        dxf_raw = {
            "estimated_cut_length_mm": flat["perimeter_mm"],
            "blank_area_mm2": flat["blank_area_mm2"],
            "weight_kg": flat["weight_kg"],
            "drawing_extents_mm": [flat["blank_length_mm"], flat["blank_width_mm"]],
            "estimated_hole_count": flat["hole_count"],
            "estimated_bend_line_count": flat["bend_count"],
            **_pierce_fields(_arbitrate_pierces(flat, raw)),
            # Carried so a reader can tell "no internal cut-outs" from "we could not tell".
            "pierce_count_incomplete": bool(flat.get("pierce_count_incomplete")),
            "closed_contour_count": flat.get("closed_contour_count"),
        }
        _pv = _arbitrate_pierces(flat, raw)
        if _pv and _pv.get("uncertain"):
            part["geometry_provisional"] = True
            part.setdefault("review_flags", []).append(str(_pv.get("note") or ""))
        if flat.get("pierce_count_incomplete"):
            part.setdefault("review_flags", []).append(
                "DXF outline has segments that could not be chained into closed loops, so "
                "some cut-outs may not have been counted. The pierce count is a FLOOR — "
                "check the drawing for cut-outs the laser has not been charged for")
    else:
        extents = raw.get("drawing_extents_mm") or []
        if isinstance(extents, (list, tuple)) and len(extents) >= 2:
            a = float(extents[0] or 0)
            b = float(extents[1] or 0)
            if a > 0 and b > 0:
                length, width = sorted([a, b], reverse=True)
                part["overall_length_mm"] = length
                part["overall_width_mm"] = width
                part["flat_pattern_detected"] = True

        thk = thickness_mm_from_dxf_filename(dxf_path)
        if thk is not None:
            # A gauge read from the FILENAME, not the geometry — inference, not measurement.
            _apply_field(part, "normalized_thickness_mm", thk, "inference")
            if not part.get("thicknesses_mm"):
                part["thicknesses_mm"] = [str(thk)]

        holes = raw.get("hole_diameters_mm") or geometry.get("hole_diameters_mm") or []
        if holes:
            existing = [float(h) for h in part.get("hole_sizes_mm", []) if h is not None]
            part["hole_sizes_mm"] = sorted(set(existing + [float(h) for h in holes]))

        dxf_raw = {
            "estimated_cut_length_mm": raw.get("estimated_cut_length_mm"),
            "blank_area_mm2": None,
            "weight_kg": None,
            "drawing_extents_mm": list(extents) if extents else [],
            "estimated_hole_count": raw.get("estimated_hole_count"),
            "estimated_bend_line_count": raw.get("estimated_bend_line_count"),
            "estimated_pierce_count": raw.get("estimated_pierce_count"),
        }

    # ── DID THE DXF ACTUALLY YIELD MEASURED GEOMETRY? ────────────────────────────
    # A matched file is not the same as a measured part. dxf_reader collects the outline
    # from LINE/ARC/CIRCLE entities on the cut layers and does NOT explode INSERT blocks
    # ("Model-space entities only (INSERT blocks are not exploded in v1)"). Where a
    # SolidWorks export wraps the profile in a block — 4 of 7 parts on job 12120 — the cut
    # layer yields nothing, the blank comes back 0, and the part's dimensions fall through
    # to the drawing's DIMENSION TEXT instead. That number can be perfectly correct, but it
    # is TRANSCRIBED, not measured, and it carries none of the guarantees a measured outline
    # does: no cut length, no hole count, no proof the profile is what the text claims.
    #
    # Setting dxf_augmented unconditionally told the credibility gate that every matched
    # part was DXF-backed, so a job could report full measured coverage while most of its
    # blanks came from text. The gate exists to answer exactly that question, and it was
    # being fed the wrong answer. Claim measurement only where there is measurement.
    _blank_area = 0.0
    try:
        _blank_area = float((flat or {}).get("blank_area_mm2") or 0.0)
    except (TypeError, ValueError):
        _blank_area = 0.0
    # TWO DIFFERENT CLAIMS, AND THEY WERE SHARING ONE FLAG. A DXF can yield a measured cut
    # PATH without yielding a measured BLANK — the cut layer holds geometry the reader can
    # follow, but nothing that closes into an outline with an area. Both are real
    # measurement, and they license completely different things:
    #
    #   outline measured   -> we know the blank, so no blank allowance is needed
    #   cut length measured -> we know the cut time, and nothing at all about the blank
    #
    # dxf_measured_outline was being set from EITHER, so five parts on 12120 skipped their
    # blank allowance on the strength of a measurement that says nothing about their blank.
    # bought_in_policy already documents the contract this breaks — "dxf_augmented is set
    # ONLY where an outline was actually measured" — so the reader was right and the writer
    # was wrong. Keep the claims apart and each gate reads the one it actually needs.
    _outline_measured = bool(flat and flat.get("flat_pattern_detected") and _blank_area > 0)
    try:
        _cut_length_measured = float((raw or {}).get("estimated_cut_length_mm") or 0.0) > 0.0
    except (TypeError, ValueError):
        _cut_length_measured = False

    part["geometry_source"] = (
        "dxf_flat_pattern" if _outline_measured
        else ("dxf_cut_length_only" if _cut_length_measured else "dxf_matched_no_geometry")
    )
    part["geometry_source_path"] = str(dxf_path.resolve())
    part["dxf_source_file"] = dxf_path.name
    part["dxf_measured_outline"] = _outline_measured
    part["dxf_measured_cut_length"] = _cut_length_measured
    # Only a measured OUTLINE counts as augmentation, because augmentation is what tells the
    # costing path the blank extents can be trusted. The filename still gives thickness and
    # material (dxf_source_file is kept), and a measured cut length is still recorded above
    # for the operations that need it — but the blank claim is withdrawn.
    part["dxf_augmented"] = _outline_measured
    if not _outline_measured:
        _what = ("Its cut layer yielded a measured cut path but no closed outline, so the cut "
                 "time is measured and the blank is not"
                 if _cut_length_measured else
                 "Its cut layer holds no line/arc/circle geometry at all")
        part.setdefault("review_flags", []).append(
            f"DXF '{dxf_path.name}' matched but yielded NO measured blank outline. {_what} "
            f"(commonly a block/INSERT export, which the reader does not explode). Any blank "
            f"shown for this part is transcribed from the drawing's dimension text, not "
            f"measured, and it takes the blank allowance accordingly. Re-export the flat "
            f"pattern as exploded geometry to measure it")
    part["dxf_geometry_reliability"] = reliability
    part["dxf_raw_geometry"] = dxf_raw

    # ── THE SECOND READ OF THE SAME FILE ─────────────────────────────────────────────
    # ezdxf has now measured everything it can. What it cannot say is what the geometry
    # MEANS — which layer is the cut profile, what each hole is for, whether this is one
    # part or a nest — and those are the answers that decide how a part is made and, in the
    # nest case, whether its price is out by a factor of six.
    #
    # Measurement above is untouched: this is gap-fill and judgement, stamped `inference`.
    # Failure-isolated and off unless a key is present, so a job with no model reaching it
    # costs exactly as it does today.
    try:
        import os as _os_di
        _di_flag = _os_di.getenv("SDI_DXF_LLM_INTERPRET", "").strip().lower()
        if _di_flag not in {"0", "false", "no", "off"} and (
                _di_flag in {"1", "true", "yes", "on"} or _os_di.getenv("XAI_API_KEY")):
            from dxf_llm_interpret import interpret as _dxf_interpret, apply_to_part as _dxf_apply
            _measured = {
                "layers": (raw or {}).get("layers") or (geometry or {}).get("layers"),
                "entity_counts": (raw or {}).get("entity_counts"),
                "text_entities": (raw or {}).get("text_entities"),
                "blank_mm": [part.get("overall_length_mm"), part.get("overall_width_mm")],
                "hole_diameters_mm": part.get("hole_sizes_mm"),
                "closed_contour_count": (raw or {}).get("closed_contour_count"),
                "cut_length_mm": dxf_raw.get("estimated_cut_length_mm"),
            }
            _interp = _dxf_interpret(_measured, filename=dxf_path.name)
            if _interp:
                _ic = _dxf_apply(part, _interp)
                print(f"   [dxf-interpret] {dxf_path.name}: {_interp.get('recommended_process')}"
                      f"/{_interp.get('complexity')} — filled {_ic['filled']}, "
                      f"raised {_ic['flags']} for review", flush=True)
    except Exception as _e_di:
        print(f"   [dxf-interpret] skipped for {dxf_path.name} ({_e_di}) — run continues",
              flush=True)
    # DXF flat-pattern is ground truth for folding: a genuine flat-pattern part
    # whose resolved DXF bend count is 0 does NOT fold. Strip a stale 'folding'
    # op that a shared/document note baked into the ops upstream. Runs at the
    # augment convergence point, so it applies regardless of which geometry
    # branch handled the part; the downstream routing reads this ops list.
    try:
        _gr = part.get("geometry_rollup") or {}
        _bcx = part.get("bend_count_dxf")
        _ebl = _gr.get("estimated_bend_line_count")
        _resolved_bends = int((_bcx if _bcx is not None else (_ebl if _ebl is not None else 0)) or 0)
        # A MEASURED ZERO, NOT AN ABSENT LAYER. See dxf_declares_bend_layer: a cut-only
        # export carries no bend layer, and reading its silence as "does not fold" ruled the
        # fold off 11350's left arm — a part the drawing shows formed. Where the layer is
        # missing the question is left OPEN, so the drawing's own reading still decides.
        _declares_bends = dxf_declares_bend_layer(dxf_path)
        if part.get("flat_pattern_detected") and _resolved_bends == 0 and not _declares_bends:
            part.setdefault("review_flags", []).append(
                f"DXF {dxf_path.name} carries no bend layer, so it cannot say whether this "
                f"part folds. Folding left as the drawing states it — confirm.")
        if (part.get("flat_pattern_detected") and _resolved_bends == 0
                and _declares_bends):
            for _k in ("operations", "textual_operations"):
                _ops = part.get(_k)
                if isinstance(_ops, list) and "folding" in _ops:
                    part[_k] = [_o for _o in _ops if _o != "folding"]   # precedence: direct-write ok — removes an op, adds no evidence
            # RECORD THE RULING, NOT JUST THE REMOVAL.
            #
            # This deleted the op and left nothing to say it had. A later pass — the LLM
            # route, which reads formed walls off the drawing views — simply adds `folding`
            # back, and now that a routed operation without a cost model reaches the sheet,
            # it would be COSTED. A measured zero overwritten by a conclusion is the exact
            # failure that took three commits on 12120.
            #
            # An explicit zero is a value. Recorded here so every later pass can see that
            # this one was measured, not merely absent.
            part.setdefault("operations_ruled_out", {})["folding"] = (
                "DXF flat pattern measured 0 bend lines — the part does not fold")
    except Exception:
        pass

    # DXF-only flats with no detail page (e.g. a kick-plate assembly stub bound only via
    # its flat DXF) arrive here with flat geometry but no PRIMARY CUT operation, so they
    # cost ~\u00a30 (only "handling"). Stamp baseline fab ops inferred from the flat geometry
    # \u2014 cut length -> laser/profile cut, bend lines -> folding \u2014 and MERGE them with any
    # existing ops (so "handling" is preserved). The trigger is the absence of a cutting
    # op, NOT the absence of all ops: a lone "handling" must still qualify.
    _ops_now = set(part.get("operations") or []) | set(part.get("textual_operations") or [])
    _has_primary_cut = bool(
        _ops_now & {"laser_cutting", "punch", "guillotine", "profiling", "profile_cut"}
    )
    if not _has_primary_cut:
        try:
            cut_len = float((dxf_raw or {}).get("estimated_cut_length_mm") or 0.0)
        except (TypeError, ValueError):
            cut_len = 0.0
        if cut_len > 0:
            try:
                from extractor_patterns import infer_operations_from_text as _infer_ops

                bends = int((dxf_raw or {}).get("estimated_bend_line_count") or 0) or int(
                    part.get("bend_count_dxf") or 0
                )
                inferred = _infer_ops(
                    "",
                    material=str(part.get("normalized_material") or ""),
                    finishes=part.get("finishes") or part.get("surface_finishes") or [],
                    has_fold_geometry=bends > 0,
                    has_cut_length=True,
                )
                if inferred:
                    merged = sorted(_ops_now | set(inferred))
                    # DXF flat-pattern is what the press brake bends from — ground
                    # truth. If it shows 0 bends, this part does NOT fold, even if a
                    # shared/document 'fold' note put 'folding' in the ops upstream.
                    # The merge above only ADDs, so a stale 'folding' would survive;
                    # strip it here. process_router reads this exact list to emit the
                    # Fold op, so removing it here removes the phantom fold.
                    if part.get("flat_pattern_detected") and bends == 0:
                        merged = [op for op in merged if op != "folding"]
                    part["operations"] = merged
                    part["textual_operations"] = merged
                    part["operations_source"] = "inferred_from_dxf_flat"
            except Exception:
                pass

    _interpret_part(part)
    return part


def _loose_part_key(part_number: str) -> Tuple[str, str]:
    """Leading numeric block + trailing letter: '1449C' / '1449-01C' -> ('1449','C')."""
    k = _normalize_part_key(part_number)
    m = re.match(r"^(\d{3,5})", k)
    lead = m.group(1) if m else ""
    tail = k[-1] if k and k[-1].isalpha() else ""
    return lead, tail


def _pick_best_flat(part: Dict[str, Any], paths: Sequence[Path]) -> Path:
    """Choose the most credible flat when several resolve to one part.

    Scores by revision match against the part, then by a plausible sheet
    thickness in the filename; ties broken deterministically by name. Used only
    after the caller has decided the set is ambiguous and flagged it.
    """
    part_rev = str(part.get("revision") or part.get("drawing_revision") or "").upper()

    def score(p: Path) -> Tuple[float, str]:
        s = 0.0
        t = thickness_mm_from_dxf_filename(p)
        if t is not None and 0 < t <= 6.0:        # plausible sheet thickness
            s += 2.0
        m = re.search(r"rev[\s_]*([A-Z])", p.stem, flags=re.IGNORECASE)
        if m and part_rev and m.group(1).upper() == part_rev:
            s += 3.0
        try:
            from part_identity import score_dxf_candidate

            s += score_dxf_candidate(part, p)
        except Exception:
            pass
        return s, p.name.lower()

    return max(paths, key=score)


def _lookup_part(parts_by_key: Dict[str, Dict[str, Any]], part_number: str) -> Optional[Dict[str, Any]]:
    key = _normalize_part_key(part_number)
    try:
        from part_identity import dxf_alias_target

        alias = dxf_alias_target(key)
        if alias:
            alias_key = _normalize_part_key(alias)
            if alias_key in parts_by_key:
                return parts_by_key[alias_key]
    except Exception:
        pass
    if key in parts_by_key:
        return parts_by_key[key]
    try:
        from part_identity import GA_TO_DETAIL_PREFERENCE, normalize_part_code

        norm = normalize_part_code(part_number)
        for ga_code, detail_code in GA_TO_DETAIL_PREFERENCE.items():
            if normalize_part_code(detail_code) == norm:
                ga_key = normalize_part_code(ga_code)
                if ga_key in parts_by_key:
                    return parts_by_key[ga_key]
    except Exception:
        pass
    # THE DRAWING'S BOM OWNS IDENTITY, AND IS CONSULTED BEFORE A PART IS INVENTED.
    #
    # A DXF that matches no BOM line is promoted to a NEW part by the caller. That is right
    # for a flat whose part has no PDF detail page — it would otherwise be lost — and wrong
    # for a flat whose part IS on the drawing under the code the drawing uses. On 11350
    # "11350-01-01M.DXF" found no "11350-01-01M" and minted a second bar, so a five-item BOM
    # became seven nodes with the hierarchy on one copy and the measured blank on the other.
    #
    # The trailing-segment fallback below cannot bridge it: "01M" does not end with "01".
    # Resolved here, upstream, where it PREVENTS the phantom — the compiler's alias could
    # only merge one after the fact, and merging is not the same as never splitting.
    try:
        from part_code_conventions import alias_targets

        for _cand in alias_targets(part_number):
            _cand_key = _normalize_part_key(_cand)
            if _cand_key and _cand_key in parts_by_key:
                return parts_by_key[_cand_key]
    except Exception:
        pass
    suffix = key.split("-")[-1]
    for candidate_key, part in parts_by_key.items():
        if candidate_key.endswith(suffix) or candidate_key.replace("-", "") == key.replace("-", ""):
            return part
    # Tolerant fall-back: bridge abbreviated DXF part numbers ("1449C", "1450")
    # to full BOM numbers ("1449-01C", "1450-01C") via leading numeric block +
    # trailing letter. Only bind when exactly one BOM part shares it; if several
    # do, it is genuinely ambiguous, so return None rather than guess.
    lead, tail = _loose_part_key(key)
    if lead:
        hits = [
            part
            for candidate_key, part in parts_by_key.items()
            if _loose_part_key(candidate_key)[0] == lead
            and (not tail or _loose_part_key(candidate_key)[1] == tail)
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def _numeric_part_prefix(part_number: str) -> str:
    m = re.match(r"^(\d+)", str(part_number or "").upper())
    return m.group(1) if m else ""


def _description_for_orphan_dxf(summary: Dict[str, Any], part_number: str) -> str:
    """Best-effort description from pooled BOM rows sharing the numeric family prefix."""
    pn_key = _normalize_part_key(part_number)
    prefix = _numeric_part_prefix(pn_key)
    bom_rows = (summary.get("document_analysis") or {}).get("bom_rows") or []
    best_desc = ""
    best_len = 0
    for row in bom_rows:
        row_pn = _normalize_part_key(str(row.get("part_number") or ""))
        if not row_pn:
            continue
        row_prefix = _numeric_part_prefix(row_pn)
        if row_prefix != prefix and not row_pn.startswith(prefix):
            continue
        desc = str(row.get("description") or row_pn).strip()
        if len(desc) > best_len:
            best_desc = desc
            best_len = len(desc)
    return best_desc or pn_key


def _create_orphan_dxf_part(summary: Dict[str, Any], part_number: str, dxf_path: Path) -> Dict[str, Any]:
    """Standalone part record for a flat DXF with no PDF detail page in the writeup."""
    parsed_pn = part_number_from_dxf_path(dxf_path) or part_number
    pn = _normalize_part_key(parsed_pn) or part_number
    desc = _description_for_orphan_dxf(summary, pn)
    if desc == pn or desc == part_number:
        desc = dxf_path.stem.replace("_", " ").strip()
    part = _empty_part_record(pn, description=desc, quantity=None)
    # Born with a source. A quantity of 1 written silently is indistinguishable from a
    # quantity of 1 somebody established, and the next pass is free to replace it.
    _apply_field(part, "quantity", 1, "inference")
    part["page_roles"] = ["dxf_only"]
    part["source"] = "dxf_orphan_no_bom_part"
    part["geometry_source"] = "dxf_flat_pattern"
    part.setdefault("review_flags", []).append("dxf_orphan_no_detail_ga")
    part["dxf_orphan"] = {"path": str(dxf_path.resolve()), "note": "Flat DXF in folder — no detail GA/PDF part record"}
    _mat_fn = material_from_dxf_filename(dxf_path)
    if _mat_fn:
        _apply_field(part, "normalized_material", _mat_fn, "inference")
    return part


def _dxf_bbox_wh(path: Path) -> Optional[Tuple[float, float]]:
    """Blank bounding box as (long_mm, short_mm), order-independent. None if unreadable.

    Used only to decide whether several flats that resolved to one part are genuine
    duplicates (same blank) or distinct child flats (different blanks). A direct
    extents read is deliberate: it must work even when flat-pattern detection is partial.
    """
    try:
        import ezdxf
        from ezdxf import bbox as _bbox

        doc = ezdxf.readfile(str(path))
        b = _bbox.extents(doc.modelspace())
        a, c = float(b.size.x), float(b.size.y)
        if a > 0 and c > 0:
            return (max(a, c), min(a, c))
    except Exception:
        pass
    return None


def _part_expected_dims(part: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Best-available expected blank dims for a part as (long_mm, short_mm)."""
    for lf, wf in (
        ("blank_length_mm", "blank_width_mm"),
        ("developed_length_mm", "developed_width_mm"),
        ("overall_length_mm", "overall_width_mm"),
    ):
        l, w = part.get(lf), part.get(wf)
        try:
            if l and w:
                a, b = float(l), float(w)
                return (max(a, b), min(a, b))
        except Exception:
            continue
    return None


def _bbox_close(a: Tuple[float, float], b: Tuple[float, float], *, tol_pct: float = 0.08, tol_mm: float = 12.0) -> bool:
    """Two blanks are 'the same' (duplicate) when both dims agree within tolerance."""
    for x, y in zip(a, b):
        if abs(x - y) > max(tol_mm, tol_pct * max(x, y)):
            return False
    return True


def _cluster_paths_by_bbox(paths: Sequence[Path]) -> List[Tuple[Optional[Tuple[float, float]], List[Path]]]:
    """Group paths whose blank bounding boxes match. Each cluster = one physical flat."""
    clusters: List[Tuple[Optional[Tuple[float, float]], List[Path]]] = []
    for p in paths:
        bb = _dxf_bbox_wh(p)
        placed = False
        for i, (rep, members) in enumerate(clusters):
            if bb and rep and _bbox_close(bb, rep):
                members.append(p)
                placed = True
                break
        if not placed:
            clusters.append((bb, [p]))
    return clusters


def _orphan_child_pn(parent: Dict[str, Any], path: Path, index: int = 0) -> str:
    """Distinct, collision-safe child PN for a parent flat with no matching child.

    Carries a 'DXF' marker and ends in a digit so the synthesised suffix can never
    be misread by SDI's single-letter material/identity conventions — a trailing
    '-T' was routing the acrylic TOP PANEL to MDF/timber, and '-S' to stainless."""
    parent_pn = _normalize_part_key(parent.get("part_number", "")) or "PART"
    stem = re.sub(r"(?i)rev[\s_]*[a-z]\b|\d+(?:[.,]\d+)?\s*mm|_+", " ", path.stem)
    slug = re.sub(r"[^A-Z0-9]+", "", stem.upper())[:10] or "FLAT"
    return f"{parent_pn}-DXF{slug}{index}"


def _apply_and_report(part: Dict[str, Any], chosen: Path, report: Dict[str, Any], matched_keys: set, *, reason: str = "matched") -> None:
    apply_dxf_geometry_to_part(part, chosen)
    matched_keys.add(_normalize_part_key(part.get("part_number", "")))
    dxf_raw = part.get("dxf_raw_geometry") or {}
    report["matched"].append(
        {
            "part_number": part.get("part_number"),
            "dxf": str(chosen.resolve()),
            "geometry_reliability": part.get("dxf_geometry_reliability"),
            "geometry_source": part.get("geometry_source"),
            "blank_area_mm2": dxf_raw.get("blank_area_mm2"),
            "weight_kg": dxf_raw.get("weight_kg"),
            "weight_g": part.get("dxf_weight_g"),
            "bend_count_dxf": part.get("bend_count_dxf"),
            "bind_reason": reason,
        }
    )


def _split_parent_flats_to_children(
    parent: Dict[str, Any],
    clusters: List[Tuple[Optional[Tuple[float, float]], List[Path]]],
    parts: List[Dict[str, Any]],
    parts_by_key: Dict[str, Dict[str, Any]],
    summary: Dict[str, Any],
    report: Dict[str, Any],
    matched_keys: set,
) -> None:
    """Several DISTINCT blanks resolved to one (parent/assembly) part — e.g. descriptor
    DXFs 04_TOP_PANEL / 04_SIDE_PANEL both reading parent PN ...-04. Bind each blank to
    the child detail part whose dimensions match; promote a distinct part if no child is
    in scope. Never collapse two different blanks onto one part."""
    parent_key = _normalize_part_key(parent.get("part_number", ""))
    children = [
        p
        for k, p in parts_by_key.items()
        if k != parent_key and k.startswith(parent_key + "-") and not k.endswith("-GA")
    ]
    used: set = set()

    # Bind the most descriptor-specific flats FIRST. With no child dims to match on, an
    # ambiguous flat ("SIDE PANEL" shares no token with child "ENDS") must not greedily
    # grab the child that a descriptor-matched flat needs ("TOP PANEL" -> "FRONT/TOP/BACK").
    # On the M18 tank, file order bound SIDE->qty-1 child and TOP->qty-2 child, costing the
    # large TOP panel twice. Ordering by best token overlap fixes the per-child quantity.
    def _cluster_overlap(cl: Tuple[Optional[Tuple[float, float]], List[Path]]) -> int:
        _paths = cl[1]
        ch_path = _pick_best_flat(parent, _paths) if len(_paths) > 1 else _paths[0]
        _st = set(re.findall(r"[A-Z]+", ch_path.stem.upper()))
        return max(
            (len(_st & set(re.findall(r"[A-Z]+", str(c.get("description") or "").upper()))) for c in children),
            default=0,
        )
    ordered = sorted(clusters, key=_cluster_overlap, reverse=True)
    for _ci, (rep_bbox, cl_paths) in enumerate(ordered):
        chosen = _pick_best_flat(parent, cl_paths) if len(cl_paths) > 1 else cl_paths[0]
        target = None
        best_d = None
        for ch in children:
            if id(ch) in used:
                continue
            dims = _part_expected_dims(ch)
            if not dims or not rep_bbox:
                continue
            d = abs(dims[0] - rep_bbox[0]) + abs(dims[1] - rep_bbox[1])
            tol = max(40.0, 0.12 * max(dims[0], rep_bbox[0]))
            if d <= tol and (best_d is None or d < best_d):
                best_d, target = d, ch
        bind_reason = "geometry_matched_child"
        if target is None:
            # 2a: dims-match failed (child carries no extractable dims — reliability 0).
            # Bind by elimination to an unused no-dims child of this parent, preferring a
            # description-token overlap (e.g. flat "...TOP PANEL" -> child "FRONT/TOP/BACK",
            # "...SIDE PANEL"/"END" -> "ENDS"). This lands the parent's real flats on its
            # children — correct geometry AND material — instead of leaving them as orphan
            # phantoms ALONGSIDE the no-geometry children (the double-count we saw on the
            # M18 tank). Falls back to current orphan behaviour when there is no such child.
            _cand = [ch for ch in children if id(ch) not in used and not _part_expected_dims(ch)]
            if _cand:
                _st = set(re.findall(r"[A-Z]+", chosen.stem.upper()))
                _cand.sort(key=lambda c: -len(_st & set(re.findall(r"[A-Z]+", str(c.get("description") or "").upper()))))
                target = _cand[0]
                bind_reason = "bound_to_childless_child_by_elimination"
        if target is not None:
            used.add(id(target))
            _mat_fn = material_from_dxf_filename(chosen)
            if _mat_fn and (
                not target.get("normalized_material")
                or str(target.get("normalized_material") or "").strip().upper() in {"MDF", "NONE", ""}
            ):
                # Filename, therefore inference — see above.
                _apply_field(target, "normalized_material", _mat_fn, "inference")
            _apply_and_report(target, chosen, report, matched_keys, reason=bind_reason)
        else:
            pn = _orphan_child_pn(parent, chosen, _ci)
            orphan = _create_orphan_dxf_part(summary, pn, chosen)
            orphan["part_number"] = pn
            orphan.setdefault("review_flags", []).append("distinct_child_flat_promoted_by_geometry")
            parts.append(orphan)
            parts_by_key[_normalize_part_key(pn)] = orphan
            summary.setdefault("manufacturing_writeup", {})["parts"] = parts
            _apply_and_report(orphan, chosen, report, matched_keys, reason="distinct_child_flat_promoted")
            report["orphan_dxf_promoted"].append(
                {
                    "part_number": pn,
                    "dxf": str(chosen.resolve()),
                    "reason": "distinct_child_flat_no_matching_child_in_scope",
                }
            )


def _stamp_assembly_parents(parts: List[Dict[str, Any]]) -> None:
    """Flag sub-assembly / parent parts so they are not double-costed.

    A part is an assembly parent when it has NO flat DXF of its own AND its part
    number is a strict prefix ("<pn>-") of >=2 other parts in the job. Such a part
    is a roll-up of its already-costed children, so it must carry neither its own
    sheet material nor geometry-derived fabrication labour — e.g. TANK 10897-01-04
    read £45.55 material + 12.1h phantom laser off the assembly PDF, while its real
    cost lives in children 04-01/04-02.

    Deliberately general and additive: it never flags a leaf part (no children) or a
    part that owns a flat DXF. Weld-assembly parents (-WA/-SA) are handled by their
    own existing suffix rule and are NOT prefix-parents of their detail parts (those
    carry sibling numbers, not -WAnn- children), so they are untouched here.
    """
    keyed = [(_normalize_part_key(p.get("part_number", "")), p) for p in parts]
    keyed = [(k, p) for k, p in keyed if k]
    for k, p in keyed:
        if "dxf" in str(p.get("geometry_source") or "").lower():
            continue
        prefix = k + "-"
        n_children = sum(1 for ok, _ in keyed if ok != k and ok.startswith(prefix))
        if n_children >= 2:
            p["is_assembly_parent"] = True
            flags = p.setdefault("review_flags", [])
            if "assembly_parent_rolled_up_to_children" not in flags:
                flags.append("assembly_parent_rolled_up_to_children")
    _stamp_described_assemblies(parts)


_WITH_SPLIT = re.compile(r"\s+WITH\s+", re.IGNORECASE)
_AND_SPLIT = re.compile(r"\s*(?:,|\s\+\s|\bAND\b)\s*", re.IGNORECASE)


def _desc_key(text: Any) -> str:
    """A description reduced to comparable words. Punctuation and spacing vary between the
    BOM table and the title block; the words do not."""
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", str(text or "").upper()).split())


def _singular(text: str) -> str:
    """"PEM STUDS" -> "PEM STUD". The BOM names one of a thing; the parent names several."""
    return re.sub(r"S$", "", text) if text.endswith("S") and not text.endswith("SS") else text


def _stamp_described_assemblies(parts: List[Dict[str, Any]]) -> None:
    """"<A> WITH <B>" is A with B fitted — an assembly — when A and B are BOTH on this BOM.

    JOB 11350 CHARGED ONE BLANK TWICE. "11350-01-101 TICKET STRIP BAR WITH PEM STUDS" was
    routed as a fabricated leaf: its own Laser row, its own Fold row, its own material and
    its own share of powder — on top of "11350-01-01 TICKET STRIP BAR", which is the same
    physical bar and already carries all of it. It has no DXF, no model and no blank, so its
    2.5mm gauge came from an LLM inference and both operations priced at default throughput.

    The numbering rule above cannot see it: -101 is not a prefix-parent of -01, and it has
    no numbered children at all. The hierarchy simply is not in the part numbers on this
    pack — but it IS on the drawing, written the way drawings write it.

    THE EVIDENCE IS THAT BOTH HALVES ARE LINES ON THIS BOM. "BAR WITH PEM STUDS" claims
    nothing on its own: "PANEL WITH CUTOUTS" is a panel, not an assembly, and reading it as
    one would delete real fabrication. So the claim requires the base description to match
    another line EXACTLY, and every named component to be a line here too. A cut-out is not
    a BOM line and never will be; a PEM stud is, because somebody has to buy it.

    Refused where the part has a flat of its own — a part somebody exported a blank for is a
    part somebody cuts, whatever its description says. Same guard as the numbering rule, and
    the same direction of safety: a missed assembly costs a visible double-count an estimator
    can strike out, a wrongly claimed one silently deletes work the job actually does.
    """
    records = [p for p in parts if isinstance(p, dict)]
    by_desc: Dict[str, Dict[str, Any]] = {}
    for p in records:
        _k = _desc_key(p.get("description"))
        if _k:
            by_desc.setdefault(_k, p)

    for part in records:
        if part.get("is_assembly_parent") or "dxf" in str(part.get("geometry_source") or "").lower():
            continue
        if (part.get("normalized_geometry") or {}).get("blank_length_mm"):
            continue
        _pieces = _WITH_SPLIT.split(_desc_key(part.get("description")), maxsplit=1)
        if len(_pieces) != 2:
            continue
        _base_desc, _rest = _pieces[0].strip(), _pieces[1].strip()
        _base = by_desc.get(_base_desc)
        if _base is None or _base is part:
            continue

        # EVERY named component must be a line on this BOM, or the phrase is describing a
        # feature rather than listing parts.
        _components: List[Dict[str, Any]] = []
        _names = [n.strip() for n in _AND_SPLIT.split(_rest) if len(n.strip()) >= 3]
        if not _names:
            continue
        for _name in _names:
            _want = _singular(_name)
            _hit = next((p for k, p in by_desc.items()
                         if p is not part and p is not _base
                         and (k == _want or k.endswith(" " + _want))), None)
            if _hit is None:
                _components = []
                break
            _components.append(_hit)
        if not _components:
            continue

        part["is_assembly_parent"] = True
        part["assembly_children"] = [_base.get("part_number")] + \
                                    [c.get("part_number") for c in _components]
        flags = part.setdefault("review_flags", [])
        if "assembly_parent_rolled_up_to_children" not in flags:
            flags.append("assembly_parent_rolled_up_to_children")
        flags.append(
            f"ASSEMBLY FROM THE DESCRIPTION: '{part.get('description')}' names "
            f"{_base.get('part_number')} plus "
            f"{', '.join(str(c.get('part_number')) for c in _components)}, and every one of "
            f"them is a line on this BOM — so this is those parts fitted together, not a "
            f"second blank. Its material and fabrication labour belong to them; only "
            f"assembly work belongs here.")


def _num(value: Any) -> Optional[float]:
    """A positive finite number, or None. A zero blank is not a blank."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") and f > 0 else None


def _is_blank(value: Any) -> bool:
    """No-data. An explicit 0 and an explicit False are VALUES, not absence — a measured
    zero bend count is the whole basis of the fold rule-out, and overwriting it here would
    give a flat part its mirror's folds."""
    return value is None or (isinstance(value, (str, list, tuple, dict)) and not value)


_MIRROR_GEOMETRY_FIELDS = ["blank_length_mm", "blank_width_mm", "blank_area_mm2",
                           "perimeter_mm", "weight_kg", "weight_g"]
_MIRROR_TOP_FIELDS = ["overall_length_mm", "overall_width_mm", "blank_length_mm",
                      "blank_width_mm", "dxf_weight_g", "dxf_weight_kg", "bend_count_dxf",
                      "flange_lengths_mm", "bend_positions_mm", "symmetric_flanges",
                      "fold_count_textual", "flat_pattern_detected"]


def apply_mirror_geometry(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Give a mirrored part the flat pattern of the part it mirrors.

    JOB 11350'S RIGHT ARM WAS PRICED BY AN LLM AT 97% OF THE MATERIAL TOTAL WHILE ITS OWN
    GEOMETRY SAT TWO ROWS ABOVE IT. Only "11350-01-02_2MM MS_flat.dxf" was exported, so the
    left arm had a measured 258.35 x 84.8 x 2.0 blank and "11350-01-02 MIR" had nothing.
    With no blank there is no material to cost, so the engine went looking for a price:
    catalogue, then web, then — with the search provider exhausted — a market estimate that
    came back GBP 79.04 on one run and GBP 86.04 on the next. It also had no cut length and
    no hole count, so its laser and fold rows fell back to default throughput.

    A MIRRORED DERIVATION IS THE SAME FLAT. Same blank, same perimeter, same pierces, same
    bend count, same gauge, same material — that is what mirroring means, and it is why one
    DXF is exported for a handed pair in the first place. This is geometry we hold, not a
    figure we generate, and it is ranked accordingly: mirror_of_measured (75), below the
    flat it was copied from and below a model or DXF of the mirror ITSELF, above everything
    inferred or generated.

    THE DIRECTION OF SAFETY. Gap-fill only — a mirror that HAS its own export keeps every
    figure of its own, and a field the base never had stays missing rather than becoming a
    zero. Nothing is inherited from a base that was itself inherited or inferred: the base
    must carry a real measurement, or this would propagate a guess and dress it as geometry.

    Returns one record per part filled, for the report. Both naming conventions are handled
    by part_code_conventions, so a pack that spells it "Mirror<code>" and a pack that spells
    it "<code> MIR" behave identically.
    """
    from part_code_conventions import mirror_base

    filled: List[Dict[str, Any]] = []
    if not isinstance(parts, list):
        return filled
    by_key = {_normalize_part_key(str(p.get("part_number") or "")): p
              for p in parts if isinstance(p, dict)}

    for part in parts:
        if not isinstance(part, dict):
            continue
        base_pn = mirror_base(str(part.get("part_number") or ""))
        if not base_pn:
            continue
        base = by_key.get(_normalize_part_key(base_pn))
        if base is None or base is part:
            continue

        # THE BASE MUST HAVE BEEN MEASURED. Inheriting from a part whose own blank was
        # inferred would launder an inference into geometry at rank 75 — the exact move
        # every source rule in this codebase exists to prevent. A base that itself inherited
        # is refused for the same reason, and that also stops two mirrors of each other from
        # trading an empty record back and forth.
        base_ng = base.get("normalized_geometry") or {}
        _base_src = str(base_ng.get("geometry_source") or "")
        if not base.get("flat_pattern_detected") or _base_src.startswith("mirror"):
            continue
        if not (_num(base_ng.get("blank_length_mm")) and _num(base_ng.get("blank_width_mm"))):
            continue
        # ITS OWN MEASUREMENT WINS OUTRIGHT. A mirror with its own export needs nothing.
        _ng = part.get("normalized_geometry") or {}
        if _num(_ng.get("blank_length_mm")) and _num(_ng.get("blank_width_mm")):
            continue

        _got: List[str] = []
        for _f in _MIRROR_GEOMETRY_FIELDS:
            if _is_blank(_ng.get(_f)) and not _is_blank(base_ng.get(_f)):
                _ng[_f] = base_ng[_f]
                _got.append(_f)
        if not _got:
            continue
        _ng["geometry_source"] = "mirror_of_measured"
        # The confidence of the flat it came from, never higher — and never invented where
        # the base carried none.
        if base_ng.get("geometry_confidence") is not None:
            _ng["geometry_confidence"] = base_ng["geometry_confidence"]
        _ng["mirrored_from"] = base.get("part_number")
        part["normalized_geometry"] = _ng
        # THROUGH THE RESOLVER, NOT AROUND IT. These are written under a COMPUTED key, so
        # the field name is not visible at the write — which is exactly the shape that let
        # the override rules overwrite material in silence. Submitting them instead means a
        # stronger source is defended whatever the list grows to contain, and every figure
        # arrives carrying the name of where it came from.
        for _f in _MIRROR_TOP_FIELDS:
            if _is_blank(part.get(_f)) and not _is_blank(base.get(_f)):
                _apply_field(part, _f, base[_f], "mirror_of_measured",
                             note=f"mirrored from {base.get('part_number')}")
        # THE CUT LENGTH, THE PIERCES AND THE HOLES. Without these the laser row falls back
        # to a default throughput, which is how this part got a default rate on both its
        # laser and its fold row even after its blank was known.
        _base_roll = base.get("geometry_rollup")
        if isinstance(_base_roll, dict) and not isinstance(part.get("geometry_rollup"), dict):
            import copy as _copy
            part["geometry_rollup"] = _copy.deepcopy(_base_roll)
            _got.append("geometry_rollup")
        # Thickness and material go through the resolver so a printed title block or a model
        # still outranks them, and so the disagreement is recorded if one does.
        for _field, _key in (("normalized_thickness_mm", "normalized_thickness_mm"),
                             ("normalized_material", "normalized_material")):
            if not _is_blank(base.get(_key)):
                _apply_field(part, _field, base[_key], "mirror_of_measured",
                             note=f"mirrored from {base.get('part_number')}")

        part.setdefault("review_flags", []).append(
            f"GEOMETRY MIRRORED from {base.get('part_number')}: no flat was exported for "
            f"this hand, so its blank, cut length and bend count are the measured ones of "
            f"the part it mirrors. A mirrored derivation is the same flat — but if these "
            f"two hands are NOT identical, this part is wrong and needs its own DXF.")
        filled.append({"part_number": part.get("part_number"),
                       "mirrored_from": base.get("part_number"), "fields": _got})
    return filled


def augment_summary_with_dxf(
    summary: Dict[str, Any],
    dxf_paths: Sequence[Path],
    *,
    reestimate: bool = True,
) -> Dict[str, Any]:
    writeup = summary.get("manufacturing_writeup") or {}
    parts: List[Dict[str, Any]] = writeup.get("parts") or []
    parts_by_key = {_normalize_part_key(p.get("part_number", "")): p for p in parts if p.get("part_number")}

    report: Dict[str, Any] = {
        "matched": [],
        "unmatched_dxf": [],
        "ambiguous_dxf": [],
        "orphan_dxf_promoted": [],
        "skipped": [],
        "parts_without_dxf": [],
    }

    matched_keys: set[str] = set()

    # Phase 1 - resolve each flat DXF to a BOM part (no geometry applied yet).
    resolved: List[Tuple[Dict[str, Any], Path]] = []
    for dxf_path in dxf_paths:
        path = Path(dxf_path)
        if not path.is_file():
            report["skipped"].append({"path": str(path), "reason": "missing_file"})
            continue
        if not is_dxf_path(path):
            report["skipped"].append({"path": str(path), "reason": "not_dxf"})
            continue
        if is_ignored_ga_dxf(path):
            report["skipped"].append({"path": str(path), "reason": "ga_dxf_ignored"})
            continue

        pn = part_number_from_dxf_path(path)
        if not pn:
            report["unmatched_dxf"].append({"path": str(path), "reason": "no_part_number_in_filename"})
            continue

        part = _lookup_part(parts_by_key, pn)
        if not part:
            part = _create_orphan_dxf_part(summary, pn, path)
            parts.append(part)
            parts_by_key[_normalize_part_key(pn)] = part
            writeup["parts"] = parts
            report["orphan_dxf_promoted"].append(
                {
                    "part_number": pn,
                    "dxf": str(path.resolve()),
                    "description": part.get("description"),
                    "reason": "no_bom_part_record_promoted_from_dxf",
                }
            )

        resolved.append((part, path))

    # Phase 2 - group flats by the part they resolved to. When several flats
    # claim one part (e.g. stale revisions of the same drawing left in the
    # folder), pick the best by revision / plausible thickness and FLAG the set
    # rather than letting the last write silently win.
    by_part: Dict[int, List[Path]] = {}
    part_by_id: Dict[int, Dict[str, Any]] = {}
    for part, path in resolved:
        by_part.setdefault(id(part), []).append(path)
        part_by_id[id(part)] = part

    for pid, paths in by_part.items():
        part = part_by_id[pid]
        if len(paths) == 1:
            _apply_and_report(part, paths[0], report, matched_keys)
            continue
        # Several flats resolved to one part. Cluster by blank geometry:
        #   1 cluster  -> genuine duplicates / stale revisions (e.g. 08_1_2mm_MS +
        #                 08_TEXT both reading ...-08) -> pick best, flag, dedupe.
        #   >1 cluster -> distinct child flats collapsed onto a parent (e.g. descriptor
        #                 DXFs 04_TOP_PANEL/04_SIDE_PANEL both reading parent ...-04)
        #                 -> split each to the child detail part it matches by dimension.
        clusters = _cluster_paths_by_bbox(paths)
        if len(clusters) <= 1:
            chosen = _pick_best_flat(part, paths)
            report["ambiguous_dxf"].append(
                {
                    "part_number": part.get("part_number"),
                    "candidates": [str(p) for p in paths],
                    "chosen": str(chosen),
                    "reason": "multiple_flats_one_part_same_blank_deduped",
                }
            )
            _apply_and_report(part, chosen, report, matched_keys)
        else:
            # >1 distinct blank on one resolved part. Only treat as a parent→children
            # split when child detail parts actually exist in scope (e.g. tank 04 with
            # 04-01/04-02). If there are NO children, these are competing variants for a
            # single leaf part (e.g. a stale revision left in the folder) — preserve the
            # prior behaviour: pick the best and flag, never promote phantoms. This keeps
            # every existing single-parent job (1282 etc.) byte-identical.
            parent_key = _normalize_part_key(part.get("part_number", ""))
            has_children = any(
                k != parent_key and k.startswith(parent_key + "-") and not k.endswith("-GA")
                for k in parts_by_key
            )
            if has_children:
                report["ambiguous_dxf"].append(
                    {
                        "part_number": part.get("part_number"),
                        "candidates": [str(p) for p in paths],
                        "reason": "distinct_blanks_on_one_parent_split_to_children",
                        "clusters": len(clusters),
                    }
                )
                _split_parent_flats_to_children(
                    part, clusters, parts, parts_by_key, summary, report, matched_keys
                )
            else:
                chosen = _pick_best_flat(part, paths)
                report["ambiguous_dxf"].append(
                    {
                        "part_number": part.get("part_number"),
                        "candidates": [str(p) for p in paths],
                        "chosen": str(chosen),
                        "reason": "distinct_blanks_no_children_in_scope_pick_best",
                    }
                )
                _apply_and_report(part, chosen, report, matched_keys)

    for key, part in parts_by_key.items():
        if key not in matched_keys and part.get("geometry_rollup", {}).get("confidence", {}).get(
            "geometry_reliability", 0
        ):
            report["parts_without_dxf"].append(
                {
                    "part_number": part.get("part_number"),
                    "geometry_reliability": (part.get("geometry_rollup", {}).get("confidence") or {}).get(
                        "geometry_reliability"
                    ),
                }
            )

    summary["dxf_augmentation"] = report
    summary["geometry_source_policy"] = "dxf_wins_geometry_pdf_wins_bom"

    # A mirrored part has its own hand's flat only when somebody exported one. Where nobody
    # did, its other hand was measured and is sitting in this same list.
    report["mirror_inherited"] = apply_mirror_geometry(parts)

    # Flag sub-assembly parents (e.g. TANK 04 over 04-01/04-02) so estimation
    # suppresses their material + phantom fab labour. Must run before re-estimate.
    _stamp_assembly_parents(parts)

    if reestimate:
        summary["estimate_summary"] = estimate_document(parts, summary=summary)

    return summary


def discover_flat_dxf_files(
    pdf_path: Path,
    *,
    part_numbers: Optional[Sequence[str]] = None,
    extra_roots: Optional[Sequence[Path]] = None,
) -> List[Path]:
    cfg = getattr(config, "DRAWING_JOB_DISCOVERY", {}) or {}
    if not cfg.get("enabled", True):
        return []

    job_prefix = job_prefix_from_path(pdf_path)
    pn_set = {_normalize_part_key(p) for p in (part_numbers or []) if p}

    roots: List[Path] = [pdf_path.parent]
    subdir = cfg.get("dxf_subdir", "DXF")
    if subdir:
        roots.append(pdf_path.parent / subdir)
    roots.append(config.DRAWINGS_DIR)
    if subdir:
        roots.append(config.DRAWINGS_DIR / subdir)
    if extra_roots:
        roots.extend(extra_roots)

    glob_pat = cfg.get("flat_dxf_glob", "*.[Dd][Xx][Ff]")
    found: Dict[str, Path] = {}

    for root in roots:
        if not root.exists():
            continue
        for path in root.glob(glob_pat):
            if not path.is_file() or not is_flat_part_dxf(path):
                continue
            pn = part_number_from_dxf_path(path)
            if not pn:
                continue
            pn_key = _normalize_part_key(pn)
            if job_prefix and not pn_key.startswith(_normalize_part_key(job_prefix)):
                if pn_set and pn_key not in pn_set:
                    continue
            found[str(path.resolve())] = path

    return sorted(found.values(), key=lambda p: p.name.lower())


def discover_flat_dxf_files_in_folder(
    job_folder: Path,
    *,
    extra_roots: Optional[Sequence[Path]] = None,
) -> List[Path]:
    """All flat-part DXFs in a job folder — no job-prefix filter (folder-as-job scope)."""
    cfg = getattr(config, "DRAWING_JOB_DISCOVERY", {}) or {}
    if not cfg.get("enabled", True):
        return []

    roots: List[Path] = [Path(job_folder)]
    subdir = cfg.get("dxf_subdir", "DXF")
    if subdir:
        roots.append(Path(job_folder) / subdir)
    # A subfolder named for the job is still the DXF subfolder. Only the literal name "DXF"
    # was matched, so M&S job 2085 — flats in "2085 - DXFs_DEV1" — would have had every part
    # sized from drawing text had a root copy not happened to exist. Immediate children only:
    # recursing a job folder pulls in whatever else has been left there, and 12120 already
    # had another job's DXF sitting beside its own.
    _tokens = [str(t).upper() for t in (cfg.get("dxf_subdir_tokens") or []) if str(t).strip()]
    if _tokens:
        try:
            for _child in sorted(Path(job_folder).iterdir()):
                if _child.is_dir() and any(t in _child.name.upper() for t in _tokens):
                    roots.append(_child)
        except OSError:
            pass
    if extra_roots:
        roots.extend(extra_roots)

    glob_pat = cfg.get("flat_dxf_glob", "*.[Dd][Xx][Ff]")
    found: Dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob(glob_pat):
            if path.is_file() and is_flat_part_dxf(path):
                found[str(path.resolve())] = path
    return sorted(found.values(), key=lambda p: p.name.lower())


def collect_dxf_paths_for_job(
    job_folder: Path,
    summary: Dict[str, Any],
    *,
    attach_dxf_paths: Optional[Sequence[Path]] = None,
    auto_discover_dxf: bool = True,
) -> List[Path]:
    paths: Dict[str, Path] = {}
    for raw in attach_dxf_paths or []:
        path = Path(raw)
        if path.is_file():
            paths[str(path.resolve())] = path
    if auto_discover_dxf:
        for path in discover_flat_dxf_files_in_folder(job_folder):
            paths[str(path.resolve())] = path
    return _drop_duplicate_files(sorted(paths.values(), key=lambda p: p.name.lower()))


def _drop_duplicate_files(paths: Sequence[Path]) -> List[Path]:
    """One file is one file, however many places it has been copied to.

    Deduplication was by resolved PATH, which is right for the same file reached two ways and
    wrong for the same file COPIED twice. 2085 keeps its plate flat both in the job folder and
    in "2085 - DXFs_DEV1"; once discovery searches both, the identical file is read twice and
    the part looks ambiguous when nothing about it is.

    Identical CONTENT is the test, not the name. Two files sharing a name and differing inside
    are a real ambiguity — a superseded revision beside a current one — and both are kept so
    the existing candidate scoring can choose between them and flag it. Silently dropping one
    would pick a revision by accident of filesystem order.
    """
    import hashlib

    seen: Dict[str, Path] = {}
    out: List[Path] = []
    for path in paths:
        try:
            digest = hashlib.sha1(Path(path).read_bytes()).hexdigest()
        except OSError:
            out.append(path)          # unreadable here; let the reader report it properly
            continue
        if digest in seen:
            continue                  # byte-identical to one already taken
        seen[digest] = path
        out.append(path)
    return out


def collect_dxf_paths_for_pdf_scan(
    pdf_path: Path,
    summary: Dict[str, Any],
    *,
    attach_dxf_paths: Optional[Sequence[Path]] = None,
    auto_discover_dxf: bool = True,
) -> List[Path]:
    paths: Dict[str, Path] = {}
    for raw in attach_dxf_paths or []:
        path = Path(raw)
        if path.is_file():
            paths[str(path.resolve())] = path

    if auto_discover_dxf:
        part_numbers = [
            p.get("part_number")
            for p in (summary.get("manufacturing_writeup") or {}).get("parts", [])
            if p.get("part_number")
        ]
        for path in discover_flat_dxf_files(pdf_path, part_numbers=part_numbers):
            paths[str(path.resolve())] = path

    return sorted(paths.values(), key=lambda p: p.name.lower())


def merge_dxf_into_json_file(
    json_path: Path,
    dxf_paths: Sequence[Path],
    *,
    output_path: Optional[Path] = None,
    reestimate: bool = True,
) -> Path:
    import json

    with json_path.open("r", encoding="utf-8") as handle:
        summary = json.load(handle)

    summary = augment_summary_with_dxf(summary, dxf_paths, reestimate=reestimate)
    from json_normaliser import normalise_json

    summary = normalise_json(summary)

    out = output_path or json_path
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, default=str)
    return out
