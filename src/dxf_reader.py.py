"""
Read SOLIDWORKS / AutoCAD DXF exports and produce geometry + text compatible with file_scan.

Model-space entities only (INSERT blocks are not exploded in v1).
Lengths are normalised to millimetres using $INSUNITS when present.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import ezdxf  # type: ignore
    from ezdxf import bbox  # type: ignore
    from ezdxf.entities import DXFEntity  # type: ignore
except ImportError:  # pragma: no cover
    ezdxf = None
    bbox = None
    DXFEntity = Any  # type: ignore

from extractor_patterns import normalize_text
from geometry_calibration import calibrate_page_geometry

# AutoCAD $INSUNITS → multiplier to millimetres
_INSUNITS_TO_MM: Dict[int, float] = {
    0: 1.0,  # unitless — assume mm (typical SOLIDWORKS export)
    1: 25.4,
    2: 304.8,
    3: 1609344.0,
    4: 1.0,
    5: 10.0,
    6: 1000.0,
}

_BEND_LAYER_TOKENS = ("BEND", "FOLD", "CENTER", "PHANTOM", "CONSTRUCTION")
_BEND_LTYPE_TOKENS = ("DASH", "CENTER", "PHANTOM", "HIDDEN")


def _require_ezdxf() -> None:
    if ezdxf is None:
        raise RuntimeError("ezdxf is not installed. Run: pip install ezdxf")


def insunits_to_mm_factor(insunits: int) -> float:
    return float(_INSUNITS_TO_MM.get(int(insunits), 1.0))


def read_dxf_document(path: Path) -> Any:
    _require_ezdxf()
    return ezdxf.readfile(str(path))


def extract_dxf_metadata(dxf_path: Path) -> Dict[str, Any]:
    try:
        doc = read_dxf_document(dxf_path)
        header = doc.header
        return {
            "format": "dxf",
            "$INSUNITS": int(header.get("$INSUNITS", 0) or 0),
            "$MEASUREMENT": int(header.get("$MEASUREMENT", 0) or 0),
            "$ACADVER": str(header.get("$ACADVER", "") or ""),
            "dxfversion": str(doc.dxfversion),
            "filename": dxf_path.name,
        }
    except Exception as exc:
        return {"format": "dxf", "error": str(exc), "filename": dxf_path.name}


def _entity_layer(entity: DXFEntity) -> str:
    return str(getattr(entity.dxf, "layer", "") or "").upper()


def _entity_linetype(entity: DXFEntity) -> str:
    return str(getattr(entity.dxf, "linetype", "") or "").upper()


def _is_bend_candidate(entity: DXFEntity, length_mm: float) -> bool:
    if length_mm < 15.0:
        return False
    layer = _entity_layer(entity)
    if any(token in layer for token in _BEND_LAYER_TOKENS):
        return True
    ltype = _entity_linetype(entity)
    if any(token in ltype for token in _BEND_LTYPE_TOKENS):
        return True
    return False


def _dist2d(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def _arc_length(entity: DXFEntity, scale: float) -> float:
    try:
        return float(entity.length()) * scale
    except Exception:
        radius = float(getattr(entity.dxf, "radius", 0.0) or 0.0) * scale
        start = math.radians(float(getattr(entity.dxf, "start_angle", 0.0) or 0.0))
        end = math.radians(float(getattr(entity.dxf, "end_angle", 0.0) or 0.0))
        sweep = (end - start) % (2 * math.pi)
        return abs(radius * sweep)


def _circle_diameter_mm(entity: DXFEntity, scale: float) -> float:
    radius = float(getattr(entity.dxf, "radius", 0.0) or 0.0) * scale
    return round(2.0 * radius, 3)


def _polyline_length(entity: DXFEntity, scale: float) -> float:
    try:
        return float(entity.length()) * scale
    except Exception:
        points = list(entity.get_points("xy")) if hasattr(entity, "get_points") else []
        if len(points) < 2:
            return 0.0
        total = 0.0
        for i in range(1, len(points)):
            total += _dist2d(points[i - 1], points[i])
        if getattr(entity, "closed", False) or getattr(entity.dxf, "flags", 0) & 1:
            total += _dist2d(points[-1], points[0])
        return total * scale


def _entity_text(entity: DXFEntity) -> str:
    dxftype = entity.dxftype()
    try:
        if dxftype == "TEXT":
            return str(entity.dxf.text or "").strip()
        if dxftype == "MTEXT":
            if hasattr(entity, "plain_text"):
                return str(entity.plain_text() or "").strip()
            return str(getattr(entity.dxf, "text", "") or "").strip()
        if dxftype == "ATTRIB":
            return str(entity.dxf.text or "").strip()
    except Exception:
        return ""
    return ""


def _dimension_text(entity: DXFEntity) -> str:
    try:
        measurement = entity.get_measurement()
        if measurement is not None:
            return f"{measurement:g}"
    except Exception:
        pass
    for attr in ("text", "dimpost"):
        raw = getattr(entity.dxf, attr, None)
        if raw:
            return str(raw).strip()
    return ""


def _collect_texts(msp: Any) -> List[str]:
    texts: List[str] = []
    for entity in msp:
        dxftype = entity.dxftype()
        if dxftype in {"TEXT", "MTEXT", "ATTRIB"}:
            value = _entity_text(entity)
            if value:
                texts.append(value)
        elif dxftype == "DIMENSION":
            value = _dimension_text(entity)
            if value:
                texts.append(value)
    return texts


def _iter_modelspace_entities(doc: Any) -> Iterable[DXFEntity]:
    yield from doc.modelspace()


def extract_dxf_geometry(dxf_path: Path) -> Dict[str, Any]:
    """
    Parse DXF model space and return a single-page geometry summary (mm).
    """
    doc = read_dxf_document(dxf_path)
    insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    scale = insunits_to_mm_factor(insunits)

    line_count = 0
    arc_count = 0
    circle_count = 0
    closed_polylines = 0
    open_polylines = 0
    bend_line_count = 0
    cut_length_mm = 0.0
    hole_diameters_mm: List[float] = []
    dimension_values_mm: List[float] = []
    max_span_mm = 0.0

    for entity in _iter_modelspace_entities(doc):
        dxftype = entity.dxftype()

        if dxftype == "LINE":
            start = entity.dxf.start
            end = entity.dxf.end
            length_mm = _dist2d((start.x, start.y), (end.x, end.y)) * scale
            if length_mm < 0.05:
                continue
            line_count += 1
            if _is_bend_candidate(entity, length_mm):
                bend_line_count += 1
            else:
                cut_length_mm += length_mm
                max_span_mm = max(max_span_mm, length_mm)

        elif dxftype == "ARC":
            length_mm = _arc_length(entity, scale)
            if length_mm < 0.05:
                continue
            arc_count += 1
            if _is_bend_candidate(entity, length_mm):
                bend_line_count += 1
            else:
                cut_length_mm += length_mm
                max_span_mm = max(max_span_mm, length_mm)

        elif dxftype == "CIRCLE":
            diameter = _circle_diameter_mm(entity, scale)
            if diameter < 0.5:
                continue
            circle_count += 1
            hole_diameters_mm.append(diameter)
            circumference = math.pi * diameter
            cut_length_mm += circumference
            max_span_mm = max(max_span_mm, diameter)

        elif dxftype in {"LWPOLYLINE", "POLYLINE"}:
            length_mm = _polyline_length(entity, scale)
            if length_mm < 0.05:
                continue
            is_closed = bool(getattr(entity, "closed", False))
            if not is_closed and hasattr(entity.dxf, "flags"):
                is_closed = bool(int(entity.dxf.flags or 0) & 1)
            if is_closed:
                closed_polylines += 1
                if length_mm < 80.0:
                    hole_diameters_mm.append(round(length_mm / math.pi, 3))
            else:
                open_polylines += 1
            cut_length_mm += length_mm
            max_span_mm = max(max_span_mm, length_mm)

        elif dxftype == "SPLINE":
            try:
                length_mm = float(entity.length()) * scale
            except Exception:
                length_mm = 0.0
            if length_mm >= 0.05:
                arc_count += 1
                cut_length_mm += length_mm
                max_span_mm = max(max_span_mm, length_mm)

        elif dxftype == "DIMENSION":
            try:
                measurement = entity.get_measurement()
                if measurement is not None:
                    dimension_values_mm.append(round(float(measurement) * scale, 3))
            except Exception:
                pass

    hole_diameters_mm = sorted(set(round(d, 3) for d in hole_diameters_mm if d > 0))
    estimated_hole_count = max(circle_count, len(hole_diameters_mm))
    estimated_pierce_count = estimated_hole_count + closed_polylines

    extents_mm: List[float] = [0.0, 0.0]
    try:
        if bbox is not None:
            ext = bbox.extents(_iter_modelspace_entities(doc))
            if ext.has_data:
                mn, mx = ext
                extents_mm = [
                    round((mx.x - mn.x) * scale, 2),
                    round((mx.y - mn.y) * scale, 2),
                ]
    except Exception:
        pass

    geometry_reliability = 0.95
    if line_count + arc_count + circle_count + closed_polylines + open_polylines > 0:
        geometry_reliability = 1.0

    vector_features = {
        "connected_contour_groups": max(1, closed_polylines + open_polylines),
        "internal_loops": estimated_hole_count,
        "external_contours": closed_polylines,
        "open_profiles": open_polylines,
        "closed_profiles": closed_polylines,
        "arc_candidates": arc_count,
        "circle_candidates": circle_count,
        "dashed_long_axis_lines": bend_line_count,
        "collinear_groups": 0,
        "symmetry_detected": False,
        "feature_clusters": max(1, estimated_hole_count + 1),
        "max_line_length_points": round(max_span_mm, 2),
        "confidence": {
            "geometry_reliability": geometry_reliability,
            "circle_candidates": geometry_reliability if circle_count else 0.0,
            "bend_lines": geometry_reliability if bend_line_count else 0.0,
        },
    }

    return {
        "source": "dxf",
        "dxf_native_mm": True,
        "insunits": insunits,
        "scale_to_mm": scale,
        "line_entities": line_count,
        "arc_entities": arc_count,
        "circle_entities": circle_count,
        "closed_polylines": closed_polylines,
        "open_polylines": open_polylines,
        "estimated_cut_length_mm": round(cut_length_mm, 2),
        "estimated_hole_count": estimated_hole_count,
        "hole_diameters_mm": hole_diameters_mm,
        "estimated_bend_line_count": bend_line_count,
        "estimated_pierce_count": estimated_pierce_count,
        "dimension_values_mm": dimension_values_mm,
        "drawing_extents_mm": extents_mm,
        "vector_features": vector_features,
        "confidence": {
            "geometry_reliability": geometry_reliability,
            "estimated_cut_length_mm": geometry_reliability if cut_length_mm > 0 else 0.0,
            "estimated_hole_count": geometry_reliability if estimated_hole_count > 0 else 0.0,
            "estimated_bend_line_count": geometry_reliability if bend_line_count > 0 else 0.0,
        },
        "units_note": "DXF model-space lengths converted to mm from $INSUNITS (default mm when unitless).",
    }


def extract_dxf_pages(dxf_path: Path) -> List[Dict[str, Any]]:
    """
    Build a pdfplumber-compatible single-page record from DXF text entities.
    """
    doc = read_dxf_document(dxf_path)
    texts = _collect_texts(doc.modelspace())
    full_text = "\n".join(texts)
    normalized = normalize_text(full_text)

    width = 1000.0
    height = 1000.0
    try:
        if bbox is not None:
            ext = bbox.extents(_iter_modelspace_entities(doc))
            if ext.has_data:
                mn, mx = ext
                scale = insunits_to_mm_factor(int(doc.header.get("$INSUNITS", 0) or 0))
                width = max(100.0, (mx.x - mn.x) * scale)
                height = max(100.0, (mx.y - mn.y) * scale)
    except Exception:
        pass

    part_numbers = re.findall(
        r"\b(?:\d{4,5}[A-Z]?|[A-Z]{1,6}\d{0,4})\s*(?:-\s*[A-Z0-9_]{1,12}){1,4}\b",
        normalized,
        flags=re.IGNORECASE,
    )
    bom_row_count = len(re.findall(r"\bQTY\b", normalized, flags=re.IGNORECASE))
    primary_role = "assembly" if bom_row_count >= 2 or len(set(part_numbers)) > 1 else "detail"

    return [
        {
            "page_number": 1,
            "text": full_text,
            "normalized_text": normalized,
            "word_count": len(normalized.split()),
            "words": [],
            "page_width": width,
            "page_height": height,
            "region_text": {
                "title_block": full_text,
                "bom": "",
                "notes": "",
                "revision": "",
            },
            "layout_regions": {
                "boxes": {},
                "counts": {
                    "title_block_words": len(normalized.split()),
                    "bom_words": 0,
                    "notes_words": 0,
                    "revision_words": 0,
                },
            },
            "page_role": {
                "primary_role": primary_role,
                "signals": ["dxf_text_extract"],
            },
            "title_block_calibration": {
                "use_region_text": True,
                "region_label_count": 0,
                "full_page_label_count": 0,
                "confidence": 0.5,
            },
        }
    ]


def analyse_dxf_document_geometry(
    processed_pages: List[Dict[str, Any]],
    dxf_path: Path,
) -> Dict[str, Any]:
    """Return the same shape as geometry_analysis.analyse_document_geometry for DXF inputs."""
    geometry = extract_dxf_geometry(dxf_path)
    results: List[Dict[str, Any]] = []
    total_reliability = 0.0

    for page in processed_pages:
        page_number = int(page.get("page_number") or 1)
        page_analysis = dict(page.get("page_analysis", {}) or {})
        page_role = (page.get("page_role", {}) or {}).get("primary_role")
        page_text = str(page.get("pdfplumber_text") or page.get("normalized_text") or "")
        page_width = float(page.get("page_width", 0.0) or 0.0)
        page_height = float(page.get("page_height", 0.0) or 0.0)

        page_geometry = {
            **geometry["vector_features"],
            "estimated_cut_length_mm": geometry["estimated_cut_length_mm"],
            "estimated_hole_count": geometry["estimated_hole_count"],
            "estimated_bend_line_count": geometry["estimated_bend_line_count"],
            "estimated_pierce_count": geometry["estimated_pierce_count"],
            "hole_diameters_mm": geometry.get("hole_diameters_mm", []),
            "vector_features": geometry["vector_features"],
            "confidence": geometry["confidence"],
            "source": "dxf",
            "dxf_native_mm": True,
            "inferred_features": {
                "estimated_cut_length_mm": geometry["estimated_cut_length_mm"],
                "estimated_hole_count": geometry["estimated_hole_count"],
                "estimated_bend_line_count": geometry["estimated_bend_line_count"],
                "estimated_pierce_count": geometry["estimated_pierce_count"],
                "hole_diameters_mm": geometry.get("hole_diameters_mm", []),
            },
            "units_note": geometry["units_note"],
        }

        calibration = calibrate_page_geometry(
            page_analysis,
            page_geometry,
            [page_width, page_height],
            page_role=page_role,
            page_text=page_text,
        )

        rel = float((page_geometry.get("confidence") or {}).get("geometry_reliability", 0.0) or 0.0)
        total_reliability += rel
        results.append(
            {
                "page_number": page_number,
                "geometry": page_geometry,
                "calibration": calibration,
            }
        )

    avg = round(total_reliability / len(results), 2) if results else 0.0
    return {
        "pages": results,
        "document_geometry_reliability": avg,
        "overall_confidence": round(min(1.0, avg), 2),
        "fitz_available": False,
        "pdf_path_recovered": False,
        "dxf_path": str(dxf_path.resolve()),
        "pages_with_fitz_drawings": 0,
        "pages_with_dxf_geometry": len(results),
        "source": "dxf",
    }


def is_dxf_path(path: Path) -> bool:
    return path.suffix.lower() == ".dxf"


# ─────────────────────────────────────────────────────────────────────────────
# FLAT-PATTERN UPGRADE  (appended below existing functions)
# ─────────────────────────────────────────────────────────────────────────────

# Layer name sets — both SDI and M&S/SolidWorks conventions
CUT_LAYERS  = {
    "SLD-0", "0",                        # SDI / SolidWorks default
    "Visible Edges(Benchmark)",          # M&S Benchmark CAD export
    "VISIBLE EDGES(BENCHMARK)",
}
BEND_LAYERS = {
    "BENDLINES", "BEND", "BEND_LINES",   # SDI SolidWorks
    # M&S Benchmark does not export bend lines — bend_count=0 for M&S parts
}
ETCH_LAYERS = {"ETCHING", "ETCH", "SCRIBE"}
SKIP_LAYERS = {                          # decorative / non-geometry — excluded from hole detection
    "BORDER_-_FORMAT", "DIMS+NOTES", "SKETCHES",
    "DEFPOINTS", "RIB", "C_SNK", "HIDDEN", "REBATE",
    "Dimensions(Benchmark)", "DIMENSIONS(BENCHMARK)",    # M&S annotation layers
    "Symbols(Benchmark)",    "SYMBOLS(BENCHMARK)",
}

# Material densities  g/mm³
_MATERIAL_DENSITY_G_PER_MM3: Dict[str, float] = {
    "MILD_STEEL":           7.85e-3,
    "MILD STEEL":           7.85e-3,
    "ALUMINIUM":            2.70e-3,
    "ALUMINUM":             2.70e-3,
    "STAINLESS":            7.93e-3,
    "STAINLESS STEEL":      7.93e-3,
    "ACRYLIC":              1.19e-3,
    "HIGH_IMPACT_ACRYLIC":  1.19e-3,
    "HIGH IMPACT ACRYLIC":  1.19e-3,
    "PETG":                 1.27e-3,
    "POLYCARBONATE":        1.20e-3,
    "MDF":                  0.75e-3,
}

# Short codes used in SDI filenames  e.g. _MS_  _AL_  _HIA_
_FILENAME_MATERIAL_CODES: Dict[str, str] = {
    "MS":   "MILD_STEEL",
    "CRS":  "MILD_STEEL",
    "AL":   "ALUMINIUM",
    "ALU":  "ALUMINIUM",
    "SS":   "STAINLESS",
    "HIA":  "HIGH_IMPACT_ACRYLIC",
    "HI":   "HIGH_IMPACT_ACRYLIC",
    "AC":   "ACRYLIC",
    "ACR":  "ACRYLIC",
    "PC":   "POLYCARBONATE",
    "PETG": "PETG",
    "MDF":  "MDF",
}



def _parse_material_from_stem(stem: str) -> Optional[str]:
    """Extract material code from stem tokens (e.g. _MS_, _AL_)."""
    if re.search(r"MFMDF|MELAMINE\s*FACED|PRE\s*LAM(?:INATE)?|PRELAM|\bMFC\b", stem.upper()):
        return "MFC"
    for t in re.split(r'[_\s]+', stem.upper()):
        if t in _FILENAME_MATERIAL_CODES:
            return _FILENAME_MATERIAL_CODES[t]
    return None


def _parse_thickness_from_stem(stem: str) -> Optional[float]:
    """Extract thickness in mm from stem (e.g. _1_5mm_, _2mm_)."""
    stem_norm = re.sub(r'(\d+)_(\d+mm)', lambda m: f'{m.group(1)}.{m.group(2)}', stem,
                       flags=re.IGNORECASE)
    for t in re.split(r'[_\s]+', stem_norm):
        m = re.match(r'^(\d+)[\.](\d+)mm$', t, re.IGNORECASE)
        if m:
            return float(f'{m.group(1)}.{m.group(2)}')
        m = re.match(r'^(\d+(?:\.\d+)?)mm$', t, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None


def _parse_revision_from_stem(stem: str) -> Optional[str]:
    """Extract revision letter from stem (e.g. _revL_)."""
    for t in re.split(r'[_\s]+', stem):
        m = re.match(r'^rev([A-Z])$', t, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return None


def _parse_filename(path: Path) -> Dict[str, Any]:
    """
    Extract part number, material, thickness and revision from filename.

    Handles patterns like:
      9376-01-001_MS_1_5mm_revL.DXF                  (SDI: material + thickness)
      12242-01-01M_MS_1_5mm_revD.DXF
      9233-12-GA_UK_MW_Dressing_Kit_2020.DXF
      4002-00 Ambient Produce Unit_4002-01.dxf        (M&S: parent_description_PARTNO)
      4083-555_4083-557.dxf                           (M&S: parent_PARTNO)
      -_4083-102.dxf                                  (M&S: -_PARTNO)
    """
    stem   = path.stem                          # without extension

    # ── M&S convention: detail part number after the LAST underscore ──────────
    # Matches: 4002-01, 4083-102, 4005-18, 4002-02M — NOT revL/MS/1.5mm/words.
    _MS_PART_RE = re.compile(r'^(\d{4,5}-\d{2,4}[A-Z]?)$', re.IGNORECASE)
    raw_segments = stem.split('_')
    if len(raw_segments) >= 2:
        last_seg = raw_segments[-1].strip()
        if _MS_PART_RE.match(last_seg):
            remainder = '_'.join(raw_segments[:-1])
            return {
                "part_number":   last_seg,
                "material":      _parse_material_from_stem(remainder),
                "thickness_mm":  _parse_thickness_from_stem(remainder),
                "revision":      _parse_revision_from_stem(remainder),
                "filename_stem": path.stem,
            }

    # Pre-join  1_5mm → 1.5mm  before general tokenisation so thickness
    # is not split into ["1", "5mm"] by the underscore splitter
    # Guard with a lookbehind so this only repairs a genuine decimal thickness
    # (e.g. 1_5mm -> 1.5mm) and does NOT fire on a part-number tail such as
    # 1455-C-002_1mm, where it would merge "002_1mm" -> "002.1mm", break the
    # part-number regex, and silently drop the flat from discovery.
    stem_norm = re.sub(r"(?<![\d-])(\d{1,2})_(\d+mm)", lambda m: f"{m.group(1)}.{m.group(2)}", stem,
                       flags=re.IGNORECASE)
    tokens = re.split(r"[_\s]+", stem_norm)

    part_number: Optional[str] = None
    material:    Optional[str] = None
    thickness_mm: Optional[float] = None
    revision:    Optional[str] = None

    # Part number — first token(s) matching  NNNN-NN-NNN  or  NNNN-NN-GA  etc.
    pn_tokens: List[str] = []
    for t in tokens:
        if re.match(r"^\d{4,5}([A-Z]|\-[A-Z0-9]+)*$", t, re.IGNORECASE) or \
           re.match(r"^[A-Z]{1,4}\d{2,5}$", t, re.IGNORECASE):
            pn_tokens.append(t)
        elif pn_tokens and re.match(r"^[A-Z0-9]{1,8}$", t) and not any(
                t.upper() in _FILENAME_MATERIAL_CODES or
                re.match(r"^\d+[_\d]*mm$", t, re.I) or
                re.match(r"^rev[a-z]$", t, re.I)
                for _ in [0]):
            pn_tokens.append(t)
        else:
            break

    if pn_tokens:
        part_number = "-".join(pn_tokens) if len(pn_tokens) > 1 else pn_tokens[0]
        # Try joining first two if they look like  9376  01  001
        if len(pn_tokens) >= 3 and all(re.match(r"^\d+$", t) for t in pn_tokens[:3]):
            part_number = "-".join(pn_tokens[:3])
        # Cap at 3 dash-segments: 9233-12-GA-UK-MW → 9233-12-GA
        if part_number and part_number.count("-") > 2:
            part_number = "-".join(part_number.split("-")[:3])

    # SDI filenames like "1453 -01C - 50cm Kick Plate_1mm" — family + detail suffix
    # without a full dashed token in pn_tokens (1453 then -01C breaks the loop).
    if part_number and re.match(r"^\d{4}$", part_number):
        start_at = len(pn_tokens) if pn_tokens else 1
        for j in range(start_at, min(start_at + 2, len(tokens))):
            cand = tokens[j].lstrip("-").upper()
            if re.match(r"^\d{2}[A-Z]?$", cand):
                part_number = f"{part_number}-{cand}"
                break

    # Walk remaining tokens for material, thickness, revision
    for t in tokens[len(pn_tokens):]:
        tu = t.upper()

        # Material code
        if tu in _FILENAME_MATERIAL_CODES and material is None:
            material = _FILENAME_MATERIAL_CODES[tu]
            continue

        # Thickness: 1_5mm → 1.5  or  1.5mm  or  3mm
        m = re.match(r"^(\d+)[_\.](\d+)mm$", t, re.IGNORECASE)
        if m and thickness_mm is None:
            thickness_mm = float(f"{m.group(1)}.{m.group(2)}")
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)mm$", t, re.IGNORECASE)
        if m and thickness_mm is None:
            thickness_mm = float(m.group(1))
            continue

        # Revision:  revL  revD  revA  or standalone single letter after rev token
        m = re.match(r"^rev([A-Z])$", t, re.IGNORECASE)
        if m and revision is None:
            revision = m.group(1).upper()
            continue

    if re.search(r"MFMDF|MELAMINE\s*FACED|PRE\s*LAM(?:INATE)?|PRELAM|\bMFC\b", stem.upper()):
        material = "MFC"
    return {
        "part_number":    part_number,
        "material":       material,
        "thickness_mm":   thickness_mm,
        "revision":       revision,
        "filename_stem":  stem,
    }


def _all_entities_with_layers(msp: Any,
                              entity_types: Optional[set] = None) -> List[Tuple[Any, str]]:
    """Every model-space entity INCLUDING block contents, each paired with its EFFECTIVE
    layer, transformed to model coordinates.

    ezdxf's msp.query() does not enter an INSERT. Anything counting features — holes,
    pierces — must explode the same way the outline does, or the two disagree about what
    the file contains.

    The effective layer matters as much as the entity. An entity drawn on layer '0' inside
    a block sits on whatever layer its INSERT sits on — that is how SolidWorks and the M&S
    templates export them. Reading the entity's own layer instead returns '0' for every one
    of them, so a circle inside a SYMBOLS(BENCHMARK) or DIMS+NOTES block passes a skip-layer
    filter untouched and is priced as a hole. _get_layer_entities has always resolved this;
    this walk did not, which left the two disagreeing about the same file.
    """
    out: List[Tuple[Any, str]] = []

    def _walk(entities: Any, depth: int = 0, inherited: Optional[str] = None) -> None:
        for e in entities:
            _own = _entity_layer(e)
            _eff = inherited if (_own in ("", "0") and inherited) else _own
            if e.dxftype() == "INSERT" and depth < 5:
                try:
                    kids = list(e.virtual_entities())
                except Exception:
                    kids = []
                if kids:
                    _walk(kids, depth + 1, _eff or inherited)
                    continue
            if entity_types is None or e.dxftype() in entity_types:
                out.append((e, _eff))

    _walk(msp)
    return out


def _all_entities(msp: Any, entity_types: Optional[set] = None) -> List[Any]:
    """As _all_entities_with_layers, entities only. Prefer the layer-aware form wherever
    the result is filtered by layer."""
    return [e for e, _ in _all_entities_with_layers(msp, entity_types)]


def _entity_points(e: Any) -> List[Tuple[float, float]]:
    """Every defining point of an entity, in drawing units. Used for extents and for
    chaining open segments into loops; approximate is fine for both."""
    t = e.dxftype()
    try:
        if t == "LINE":
            return [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        if t == "ARC":
            cx, cy, r = e.dxf.center.x, e.dxf.center.y, float(e.dxf.radius)
            a0, a1 = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
            return [(cx + r * math.cos(a0), cy + r * math.sin(a0)),
                    (cx + r * math.cos(a1), cy + r * math.sin(a1))]
        if t == "CIRCLE":
            cx, cy, r = e.dxf.center.x, e.dxf.center.y, float(e.dxf.radius)
            return [(cx - r, cy - r), (cx + r, cy + r)]
        if t == "LWPOLYLINE":
            return [(float(p[0]), float(p[1])) for p in e.get_points("xy")]
        if t == "POLYLINE":
            return [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in e.vertices]
        if t == "SPLINE":
            pts = list(getattr(e, "fit_points", []) or []) or list(getattr(e, "control_points", []) or [])
            return [(float(p[0]), float(p[1])) for p in pts]
    except Exception:
        pass
    return []


def _is_closed_polyline(e: Any) -> bool:
    if bool(getattr(e, "closed", False)):
        return True
    try:
        return bool(int(getattr(e.dxf, "flags", 0) or 0) & 1)
    except Exception:
        return False


# One threshold for every contour shape. A circle, a closed polyline and a chained loop are
# three ways of drawing the same thing, so a size that is too small to be an aperture in one
# must be too small in all three — otherwise the check is only as strong as its weakest door.
_MIN_CONTOUR_MM = 1.0
# A segment shorter than this is a duplicated vertex, not geometry. Left in, it chains into a
# self-loop that satisfies the closed-contour test on its own.
_MIN_SEGMENT_MM = 0.05


def _contour_span_mm(points: List[Tuple[float, float]], scale: float) -> float:
    """The SMALLER bounding dimension of a contour, in mm.

    The larger dimension is the wrong test: a 100 x 0 closed polyline — a line drawn back on
    itself, which is what a collapsed or duplicated edge looks like — spans 100mm on its long
    side and passes, then counts as an aperture the laser pierces. A real cut-out has extent
    in BOTH directions, so the minor dimension is what has to clear the bar.
    """
    if not points:
        return 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min((max(xs) - min(xs)), (max(ys) - min(ys))) * (scale or 1.0)


def _entity_length_mm(e: Any, scale: float) -> float:
    """Length of a single entity, measured the way its own type requires.

    Measuring end-to-end works for a LINE and for nothing else. A SPLINE's first and last fit
    points can sit close together while the curve between them is long — an S-curve, or a
    nearly closed profile — so a straight-line measurement discards valid large geometry as
    degenerate. Ask each type for its own length and fall back only when it cannot answer.
    """
    t = e.dxftype()
    try:
        if t == "ARC":
            return _arc_length(e, scale)
        if t in ("LWPOLYLINE", "POLYLINE"):
            return _polyline_length(e, scale)
        if t == "SPLINE":
            try:
                return float(e.length()) * scale          # ezdxf measures the curve itself
            except Exception:
                pts = _entity_points(e)
                return sum(_dist2d(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) * scale
        if t == "CIRCLE":
            return math.pi * _circle_diameter_mm(e, scale)
    except Exception:
        pass
    pts = _entity_points(e)
    return _dist2d(pts[0], pts[-1]) * scale if len(pts) >= 2 else 0.0


def _count_closed_contours(msp: Any, scale: float, skip_layers: set,
                           blank_l: float = 0.0, blank_w: float = 0.0,
                           cut_layers: Optional[set] = None) -> Dict[str, Any]:
    """How many separate closed profiles the laser has to cut — the pierce count.

    A pierce is one closed contour: the outer profile, and every internal cut-out. Counting
    only CIRCLEs answers this for round holes alone and silently prices a slot, a rectangular
    aperture or a D-cut at nothing. Cut-outs arrive in three shapes and all three are counted
    here: a circle, a closed polyline, and a loop assembled from separate lines and arcs
    (which is how a slot with radiused ends is usually exported).

    Bend lines are excluded — they are not cut, and chaining them would fuse real contours
    into one. Annotation layers are excluded by EFFECTIVE layer, so geometry inheriting
    layer '0' from an annotation block is still skipped.

    The outer profile is one of these contours, not an extra: it is added only when no
    detected contour spans the blank, which is the case when the outline is drawn with gaps
    too large to chain. `incomplete` is set when open segments were left unclosed, so a
    caller can tell "no internal cut-outs" from "we could not tell".
    """
    types = {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "SPLINE"}
    contours: List[List[Tuple[float, float]]] = []
    loose: List[Any] = []

    items = [(e, (lay or "").upper())
             for e, lay in _all_entities_with_layers(msp, types)
             if (lay or "").upper() not in skip_layers]
    # PREFER THE CUT LAYERS. A production drawing carries a frame, a title block and
    # revision boxes, and those are closed rectangles too: chaining every non-annotation
    # segment in the file would invent contours and charge pierces for the border. Where the
    # cut layers hold geometry — the normal case for a flat-pattern export — only they are
    # counted. A file whose cut layers are empty falls back to everything not skipped, so an
    # unusual layer scheme still gets a count rather than a silent zero.
    if cut_layers:
        _wanted = {l.upper() for l in cut_layers}
        _on_cut = [it for it in items if it[1] in _wanted]
        if _on_cut:
            items = _on_cut

    for e, layer in items:
        t = e.dxftype()
        if t == "CIRCLE":
            if _circle_diameter_mm(e, scale) >= _MIN_CONTOUR_MM:
                contours.append(_entity_points(e))
            continue
        if t in ("LWPOLYLINE", "POLYLINE"):
            # The same minimum a circle must clear. A closed polyline of a few microns is a
            # duplicated vertex or a construction artefact, not an aperture the laser pierces
            # — and applying the threshold to circles alone let it in by the other door.
            if _is_closed_polyline(e):
                if _contour_span_mm(_entity_points(e), scale) >= _MIN_CONTOUR_MM:
                    contours.append(_entity_points(e))
            else:
                loose.append(e)
            continue
        # A bend line is not a cut. It must not be chained, or two cut-outs joined by a
        # bend line would be counted as one contour.
        _len = _entity_length_mm(e, scale)
        if _is_bend_candidate(e, _len):
            continue
        # A ZERO-LENGTH segment starts and ends on the same point. Chained, it becomes a
        # self-loop whose single node has degree two — which is exactly the test for a closed
        # contour, so every stray duplicate vertex in the file would invent a pierce.
        if _len < _MIN_SEGMENT_MM:
            continue
        loose.append(e)

    # Chain the loose segments: shared endpoints, within a 0.1mm tolerance.
    tol = (0.1 / scale) if scale else 0.1

    def _key(p: Tuple[float, float]) -> Tuple[int, int]:
        q = tol if tol > 0 else 0.1
        return (int(round(p[0] / q)), int(round(p[1] / q)))

    parent: Dict[Tuple[int, int], Tuple[int, int]] = {}

    def _find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a, b):
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    degree: Dict[Tuple[int, int], int] = {}
    seg_nodes: List[Tuple[Tuple[int, int], Tuple[int, int], List[Tuple[float, float]]]] = []
    for e in loose:
        pts = _entity_points(e)
        if len(pts) < 2:
            continue
        a, b = _key(pts[0]), _key(pts[-1])
        if a == b and _contour_span_mm(pts, scale) < _MIN_CONTOUR_MM:
            # Starts and ends on the same snapped node and spans nothing: a self-loop, which
            # would pass the degree test alone and count as a contour of its own.
            continue
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
        _union(a, b)
        seg_nodes.append((a, b, pts))

    comps: Dict[Tuple[int, int], List[Tuple[Tuple[int, int], Tuple[int, int], List]]] = {}
    for a, b, pts in seg_nodes:
        comps.setdefault(_find(a), []).append((a, b, pts))

    incomplete = False
    for segs in comps.values():
        nodes = set()
        for a, b, _ in segs:
            nodes.add(a); nodes.add(b)
        # A closed loop visits every node at least twice; a chain has two loose ends.
        if segs and all(degree.get(n, 0) >= 2 for n in nodes):
            _pts = [p for _, _, pts in segs for p in pts]
            # Same minimum as a circle and a closed polyline must clear.
            if _contour_span_mm(_pts, scale) >= _MIN_CONTOUR_MM:
                contours.append(_pts)
        elif segs:
            incomplete = True

    def _spans_blank(pts: List[Tuple[float, float]]) -> bool:
        if not (blank_l and blank_w and pts):
            return False
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        dims = sorted([(max(xs) - min(xs)) * scale, (max(ys) - min(ys)) * scale], reverse=True)
        return dims[0] >= 0.9 * max(blank_l, blank_w) and dims[1] >= 0.9 * min(blank_l, blank_w)

    outer_counted = any(_spans_blank(c) for c in contours)
    pierces = len(contours) + (0 if outer_counted else (1 if blank_l else 0))
    return {
        "pierce_count": pierces,
        "closed_contours": len(contours),
        "outer_counted": outer_counted,
        "incomplete": incomplete,
    }


def _get_layer_entities(
    msp: Any,
    target_layers: set,
    entity_types: Optional[set] = None,
) -> List[Any]:
    """Return modelspace entities whose layer (uppercased) is in target_layers.

    INSERTs ARE EXPLODED. A SolidWorks flat-pattern export commonly wraps the whole profile
    in a block, and iterating model space alone then finds a single INSERT and no geometry —
    the cut layer looks empty, the blank comes back 0, and the part silently falls through to
    the drawing's dimension TEXT for its size. On job 12120 that hit 4 of 7 parts, and the
    geometry was in the file the whole time: exploding 01M's block gives 126.39 x 82.20mm,
    matching the SolidWorks cut-list flat exactly.

    virtual_entities() yields the block's contents transformed into model-space coordinates,
    so extents and lengths are correct without touching the file. Nested blocks are followed
    to a bounded depth. An entity inheriting layer 0 from its INSERT takes the INSERT's layer,
    which is how SolidWorks exports them.
    """
    wanted = {l.upper() for l in target_layers}
    result = []

    def _consider(e: Any, inherited_layer: Optional[str] = None) -> None:
        lay = _entity_layer(e)
        # ByBlock/inherited: an entity on layer '0' inside a block sits on the INSERT's layer.
        if inherited_layer and lay in ("", "0"):
            lay = inherited_layer
        if lay in wanted and (entity_types is None or e.dxftype() in entity_types):
            result.append(e)

    def _walk(entities: Any, depth: int = 0, inherited: Optional[str] = None) -> None:
        for e in entities:
            if e.dxftype() == "INSERT" and depth < 5:
                try:
                    kids = list(e.virtual_entities())
                except Exception:
                    kids = []
                if kids:
                    # A nested INSERT on layer '0' is ByBlock: it belongs to whatever
                    # its parent sits on. Taking its own '0' would drop the cut layer
                    # a level down and lose the geometry inside it.
                    _own = _entity_layer(e)
                    _walk(kids, depth + 1,
                          inherited if _own in ('', '0') else (_own or inherited))
                    continue
            _consider(e, inherited)

    _walk(msp)
    return result


def _order_segments(
    lines: List[Any],
    scale: float = 1.0,
    tol: float = 0.05,
) -> List[Tuple[float, float]]:
    """
    Order disconnected LINE entities into a continuous polygon vertex list.
    Returns list of (x, y) tuples in mm.  Tolerance in mm.
    """
    if not lines:
        return []

    segs = [
        (
            (float(e.dxf.start.x) * scale, float(e.dxf.start.y) * scale),
            (float(e.dxf.end.x)   * scale, float(e.dxf.end.y)   * scale),
        )
        for e in lines
    ]

    used   = [False] * len(segs)
    pts    = list(segs[0])
    used[0] = True

    for _ in range(len(segs) - 1):
        last = pts[-1]
        found = False
        for i, (s, e) in enumerate(segs):
            if used[i]:
                continue
            if _dist2d(last, s) < tol:
                pts.append(e)
                used[i] = True
                found = True
                break
            if _dist2d(last, e) < tol:
                pts.append(s)
                used[i] = True
                found = True
                break
        if not found:
            break  # open or disconnected profile — return what we have

    return pts


def _shoelace_area(pts: List[Tuple[float, float]]) -> float:
    """Shoelace / Gauss area for an ordered polygon. Returns mm²."""
    n   = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2.0


def _shapely_net_area_mm2(cut_lines, cut_arcs, cut_circs, scale, bbox_area_mm2):
    """Reconstruct true net blank area (outer contour minus holes) from loose LINE+ARC
    cut geometry using shapely polygonize. Returns (area_mm2, method, fill_pct).

    Replaces _order_segments/_shoelace_area (endpoint-walk of LINES only, ignored ARCs)
    which collapsed to ~0 on curved/perforated profiles. ABSTAIN GATE: no ring, or net
    area not a sane fraction of bbox (fill 30-100%) -> return bbox flagged, never garbage.
    Falls back to bbox if shapely is unavailable. Proven on all 14 job-1282 DXFs.
    """
    try:
        from shapely.ops import polygonize, unary_union, snap as _snap
        from shapely.geometry import LineString, Point
        import math as _m
    except Exception:
        return (bbox_area_mm2, "bbox_no_shapely", 100.0)

    segs = []
    _sag = 0.20 / max(scale, 1e-9)
    for e in cut_lines:
        a = (e.dxf.start.x * scale, e.dxf.start.y * scale)
        b = (e.dxf.end.x * scale, e.dxf.end.y * scale)
        if _m.dist(a, b) > 1e-6:
            segs.append(LineString([a, b]))
    for e in cut_arcs:
        try:
            pts = [(v.x * scale, v.y * scale) for v in e.flattening(_sag)]
        except Exception:
            continue
        for i in range(len(pts) - 1):
            if _m.dist(pts[i], pts[i + 1]) > 1e-6:
                segs.append(LineString([pts[i], pts[i + 1]]))
    if not segs:
        return (bbox_area_mm2, "bbox_no_segments", 100.0)

    net = unary_union(segs)
    try:
        net = _snap(net, net, 0.05)           # weld sub-micron CAD endpoint gaps (mm)
    except Exception:
        pass
    polys = list(polygonize(unary_union(net)))
    if not polys:
        return (bbox_area_mm2, "bbox_polygonize_empty", 0.0)

    outer = max(polys, key=lambda p: p.area)
    interior = [p for p in polys if p is not outer]
    net_area = max(0.0, outer.area - sum(p.area for p in interior))

    for e in (cut_circs or []):
        try:
            r = float(getattr(e.dxf, "radius", 0.0) or 0.0) * scale
            if r < 0.5:
                continue
            c = (e.dxf.center.x * scale, e.dxf.center.y * scale)
            disc = Point(c).buffer(r, resolution=16)
            if outer.contains(disc.representative_point()):
                net_area = max(0.0, net_area - disc.area)
        except Exception:
            continue

    fill = (100.0 * net_area / bbox_area_mm2) if bbox_area_mm2 > 0 else 0.0
    if not (30.0 <= fill <= 100.5):
        return (bbox_area_mm2, "bbox_fill_out_of_band", round(fill, 1))
    return (round(net_area, 2), "shapely_polygonize", round(fill, 1))


def _exact_perimeter_and_area(
    cut_lines: List[Any],
    cut_arcs:  List[Any],
    scale: float,
    cut_circs: List[Any] = None,
) -> Dict[str, float]:
    """
    Compute exact perimeter (laser cut length) and polygon area from the
    cut-outline layer.  Net area comes from shapely polygonize (outer contour minus
    holes); arc-length is added to the perimeter (laser cut length).
    """
    line_length = sum(
        _dist2d(
            (e.dxf.start.x * scale, e.dxf.start.y * scale),
            (e.dxf.end.x   * scale, e.dxf.end.y   * scale),
        )
        for e in cut_lines
    )
    arc_length = sum(_arc_length(e, scale) for e in cut_arcs)
    perimeter  = line_length + arc_length

    # Bounding box from cut lines
    xs = [e.dxf.start.x * scale for e in cut_lines] + \
         [e.dxf.end.x   * scale for e in cut_lines]
    ys = [e.dxf.start.y * scale for e in cut_lines] + \
         [e.dxf.end.y   * scale for e in cut_lines]
    if not xs:
        return {"perimeter_mm": round(perimeter, 3), "area_mm2": 0.0,
                "blank_length_mm": 0.0, "blank_width_mm": 0.0, "bbox_fill_pct": 0.0}

    blank_l = round(max(xs) - min(xs), 3)
    blank_w = round(max(ys) - min(ys), 3)
    # Normalise so length ≥ width
    blank_length = max(blank_l, blank_w)
    blank_width  = min(blank_l, blank_w)

    bbox_area = blank_length * blank_width

    # Net area via shapely polygonize (outer contour minus holes). Replaces the
    # _order_segments endpoint-walk, which ignored ARCs and collapsed to ~0 on any
    # profile with curved corners/holes (peg panel 90mm2 for a 553x525 part). Proven on
    # all 14 job-1282 DXFs: 14/14 close, fill 83-100%. Abstains to bbox (flagged) if the
    # reconstruction is implausible, so a bad export never poisons area/weight/powder.
    area, _area_method, fill_pct = _shapely_net_area_mm2(
        cut_lines, cut_arcs, cut_circs, scale, bbox_area
    )
    if area < 1.0 and bbox_area > 0:
        area = bbox_area                      # last-resort guard (function already abstains)
        _area_method = "bbox_guard"

    return {
        "perimeter_mm":   round(perimeter, 3),
        "area_mm2":       round(area, 2),
        "bbox_area_mm2":  round(bbox_area, 2),
        "blank_length_mm": blank_length,
        "blank_width_mm":  blank_width,
        "bbox_fill_pct":   fill_pct,
        "area_method":     _area_method,
    }


def _extract_bend_data(
    msp: Any,
    scale: float,
) -> Dict[str, Any]:
    """
    Analyse BENDLINES layer entities.
    Returns bend count, horizontal axis positions, flange zone lengths.
    """
    bend_lines = _get_layer_entities(msp, BEND_LAYERS, {"LINE"})
    if not bend_lines:
        return {"bend_count": 0, "bend_positions_mm": [], "flange_lengths_mm": [],
                "bend_line_widths_mm": [], "symmetric_flanges": False}

    h_bends: List[float] = []   # horizontal fold axes (angle ~0°)
    v_bends: List[float] = []   # vertical fold lines  (angle ~90°)
    widths:  List[float] = []

    for e in bend_lines:
        s  = e.dxf.start
        en = e.dxf.end
        dx = (en.x - s.x) * scale
        dy = (en.y - s.y) * scale
        length = math.hypot(dx, dy)
        angle  = abs(math.degrees(math.atan2(dy, dx)))

        if length < 0.5:
            continue
        if angle < 5 or angle > 175:
            # Horizontal fold axis
            y_mm = round((s.y * scale + en.y * scale) / 2, 3)
            h_bends.append(y_mm)
            widths.append(round(length, 3))
        elif 85 < angle < 95:
            # Vertical flange line
            v_bends.append(round((s.x * scale + en.x * scale) / 2, 3))

    # Distinct fold axis Y positions
    bend_ys = sorted(set(round(y, 1) for y in h_bends))
    unique_widths = sorted(set(round(w, 3) for w in widths))

    # Flange zone lengths from bend axis positions + outline extents
    flange_lengths: List[float] = []
    if bend_ys:
        cut_lines = _get_layer_entities(msp, CUT_LAYERS, {"LINE"})
        if cut_lines:
            all_ys = [e.dxf.start.y * scale for e in cut_lines] + \
                     [e.dxf.end.y * scale for e in cut_lines]
            y_stops = sorted(set([round(min(all_ys), 2)] + bend_ys + [round(max(all_ys), 2)]))
            for i in range(len(y_stops) - 1):
                flange_lengths.append(round(abs(y_stops[i+1] - y_stops[i]), 3))

    sym = (
        len(flange_lengths) >= 2 and
        abs(flange_lengths[0] - flange_lengths[-1]) < 1.0
    )

    return {
        "bend_count":        len(bend_ys),
        "bend_positions_mm": bend_ys,
        "flange_lengths_mm": flange_lengths,
        "bend_line_widths_mm": unique_widths,
        "symmetric_flanges": sym,
    }


def _detect_corner_notches(cut_lines: List[Any], scale: float) -> Dict[str, Any]:
    """
    Count diagonal lines (notches / corner relief cuts) in the cut outline.
    Returns count and typical notch dimensions.
    """
    notches = []
    for e in cut_lines:
        s  = e.dxf.start
        en = e.dxf.end
        dx = (en.x - s.x) * scale
        dy = (en.y - s.y) * scale
        angle = abs(math.degrees(math.atan2(dy, dx))) % 90
        if 10 < angle < 80:   # diagonal — not H or V
            length = math.hypot(dx, dy)
            if 3.0 < length < 50.0:
                notches.append({"length_mm": round(length, 3),
                                "angle_deg": round(angle, 1)})

    if not notches:
        return {"corner_notch_count": 0}

    avg_len   = round(sum(n["length_mm"] for n in notches) / len(notches), 3)
    avg_angle = round(sum(n["angle_deg"] for n in notches) / len(notches), 1)
    return {
        "corner_notch_count": len(notches),
        "notch_length_mm":    avg_len,
        "notch_angle_deg":    avg_angle,
        "notch_type":         "corner_relief",
    }


def _extract_bom_blocks(doc: Any) -> List[Dict[str, Any]]:
    """
    Parse SW_TABLEANNOTATION_* blocks for BOM rows.
    Returns [{item, part_number, description, qty}]
    """
    items: List[Dict[str, Any]] = []
    for blk in doc.blocks:
        if not re.match(r"^SW_TABLEANNOTATION", blk.name, re.IGNORECASE):
            continue
        texts: List[str] = []
        for e in blk:
            if e.dxftype() in ("TEXT", "MTEXT"):
                try:
                    t = e.dxf.text.strip() if e.dxftype() == "TEXT" \
                        else re.sub(r"\s+", " ", e.plain_text()).strip()
                    if t:
                        texts.append(t)
                except Exception:
                    pass

        # Detect if this is a BOM table (has ITEM / DWG NO. header)
        text_upper = [t.upper() for t in texts]
        if "ITEM" not in text_upper or "QTY" not in text_upper:
            continue

        # Find header row
        try:
            item_idx = text_upper.index("ITEM")
        except ValueError:
            continue

        # After the header row (ITEM / DWG NO. / DESCRIPTION / QTY)
        # rows come in groups of 4
        header_end = max(
            (i for i, t in enumerate(text_upper)
             if t in {"ITEM", "DWG NO.", "DESCRIPTION", "QTY"}),
            default=item_idx,
        ) + 1

        row_texts = texts[header_end:]
        i = 0
        while i + 3 < len(row_texts):
            try:
                item_no = row_texts[i].strip()
                part_no = row_texts[i + 1].strip()
                desc    = row_texts[i + 2].strip()
                qty_raw = row_texts[i + 3].strip()
                qty     = int(re.sub(r"[^\d]", "", qty_raw) or "0")
                if re.match(r"^\d+$", item_no) and qty > 0:
                    items.append({
                        "item":        int(item_no),
                        "part_number": part_no,
                        "description": desc,
                        "quantity":    qty,
                    })
            except (ValueError, IndexError):
                pass
            i += 4

    # Deduplicate by part_number
    seen: set = set()
    unique = []
    for item in items:
        if item["part_number"] not in seen:
            seen.add(item["part_number"])
            unique.append(item)
    return unique


def _extract_d_block_dims(doc: Any) -> List[float]:
    """
    Harvest numeric values from SolidWorks _D / _D_N dimension blocks.
    Returns sorted unique float list.
    """
    values: List[float] = []
    for blk in doc.blocks:
        if not re.match(r"^_D(_\d+)?$", blk.name):
            continue
        for e in blk:
            if e.dxftype() in ("TEXT", "MTEXT"):
                try:
                    t = e.dxf.text.strip() if e.dxftype() == "TEXT" \
                        else e.plain_text().strip()
                    # Strip INT suffix, R prefix etc.
                    clean = re.sub(r"[^\d\.]", "", re.sub(r"^[RrΦ]", "", t))
                    if clean:
                        values.append(float(clean))
                except (ValueError, Exception):
                    pass
    return sorted(set(round(v, 3) for v in values if 0.01 < v < 100000))


def _collect_block_texts(doc: Any) -> str:
    """Collect all text from non-model-space blocks (title block, notes, BOM)."""
    texts: List[str] = []
    for blk in doc.blocks:
        if blk.name.startswith("*"):   # skip *Model_Space, *Paper_Space
            continue
        for e in blk:
            if e.dxftype() in ("TEXT", "MTEXT"):
                try:
                    t = e.dxf.text.strip() if e.dxftype() == "TEXT" \
                        else re.sub(r"\s+", " ", e.plain_text()).strip()
                    if t:
                        texts.append(t)
                except Exception:
                    pass
    return "\n".join(texts)


def _calculate_weight(
    area_mm2:     float,
    thickness_mm: float,
    material:     Optional[str],
) -> Dict[str, float]:
    """Compute weight from polygon area, thickness and material density."""
    density = _MATERIAL_DENSITY_G_PER_MM3.get(
        (material or "").upper(),
        _MATERIAL_DENSITY_G_PER_MM3["MILD_STEEL"],
    )
    volume_mm3 = area_mm2 * thickness_mm
    weight_g   = volume_mm3 * density
    weight_kg  = weight_g / 1000.0
    return {
        "volume_mm3":   round(volume_mm3, 2),
        "weight_g":     round(weight_g,   3),
        "weight_kg":    round(weight_kg,  6),
        "density_used": density,
    }


def _is_flat_pattern(msp: Any, scale: float = 1.0) -> bool:
    """
    Return True if this DXF looks like a flat pattern:
    - Has entities on CUT_LAYERS
    - Cut outline forms a sensible blank (area > 100mm², aspect < 50:1)
    - Optionally has BENDLINES layer
    """
    cut_lines = _get_layer_entities(msp, CUT_LAYERS, {"LINE"})
    if len(cut_lines) < 4:
        return False

    xs = [e.dxf.start.x * scale for e in cut_lines] + \
         [e.dxf.end.x   * scale for e in cut_lines]
    ys = [e.dxf.start.y * scale for e in cut_lines] + \
         [e.dxf.end.y   * scale for e in cut_lines]
    if not xs or not ys:
        return False

    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    if w < 1.0 or h < 1.0:
        return False
    aspect = max(w, h) / max(min(w, h), 0.001)
    area   = w * h
    return area > 100.0 and aspect < 100.0


def extract_flat_pattern_data(dxf_path: Path) -> Dict[str, Any]:
    """
    Full flat-pattern extraction.  Returns rich geometry dict including:
      - exact blank size (mm) from cut outline
      - shoelace area (mm²)
      - perimeter / laser cut length (mm)
      - weight (g / kg) from area × thickness × density
      - bend count and flange lengths from BENDLINES layer
      - corner notch count and dimensions
      - BOM (from SW_TABLEANNOTATION blocks, GA drawings only)
      - all dimension values (from _D blocks and DIMENSION entities)
      - filename-parsed part number / material / thickness / revision
      - geometry_score = 1.0 (exact geometry, no inference)
    """
    doc    = read_dxf_document(dxf_path)
    msp    = doc.modelspace()
    meta   = extract_dxf_metadata(dxf_path)
    scale  = insunits_to_mm_factor(meta["$INSUNITS"])

    # ── Filename metadata ─────────────────────────────────────────────────────
    fn_data  = _parse_filename(dxf_path)
    material = fn_data.get("material")
    thick_fn = fn_data.get("thickness_mm")

    # ── Flat-pattern detection ────────────────────────────────────────────────
    is_flat = _is_flat_pattern(msp, scale)

    # ── Cut outline geometry ──────────────────────────────────────────────────
    cut_lines = _get_layer_entities(msp, CUT_LAYERS, {"LINE"})
    cut_arcs  = _get_layer_entities(msp, CUT_LAYERS, {"ARC"})
    cut_circs = _get_layer_entities(msp, CUT_LAYERS, {"CIRCLE"})

    outline  = _exact_perimeter_and_area(cut_lines, cut_arcs, scale, cut_circs)
    notches  = _detect_corner_notches(cut_lines, scale)

    # Holes — circles on CUT_LAYERS or all layers (excluding tiny features)
    # Circles inside a block are geometry too. msp.query("CIRCLE") never enters an INSERT,
    # so on an export that blocks the profile every hole vanished: 06M carries eight circles
    # in its block and reported zero holes and zero pierces, which under-prices the laser.
    # Same walk as the outline uses, so holes and profile can never disagree about what is
    # in the file.
    _skip = {l.upper() for l in SKIP_LAYERS}
    # FILTER FIRST, THEN COUNT. hole_diams excluded sub-1mm circles and annotation layers;
    # hole_count then counted every circle in the file regardless, so a title block or
    # symbol layer inflated the laser's hole count. Now one filtered list feeds both, so
    # the count and the diameters can never describe different sets of circles.
    # Skip by EFFECTIVE layer: a circle drawn on layer '0' inside a SYMBOLS(BENCHMARK) or
    # DIMS+NOTES block reports its own layer as '0' and would otherwise sail through the
    # skip list and be priced as a hole.
    _hole_circles = [
        e for e, _lay in _all_entities_with_layers(msp, {"CIRCLE"})
        if _circle_diameter_mm(e, scale) >= 1.0 and (_lay or "").upper() not in _skip
    ]
    all_circles = _hole_circles
    hole_diams  = sorted(set(round(_circle_diameter_mm(e, scale), 2) for e in _hole_circles))
    hole_count  = len(_hole_circles)
    # PIERCES ARE CONTOURS, NOT HOLES. Counting holes + 1 prices a slot, a rectangular
    # aperture and a D-cut at nothing — only round holes were ever counted. Every closed
    # profile needs its own pierce, whether it is a circle, a closed polyline, or a loop of
    # separate lines and arcs, and the outer profile is one of them rather than an extra.
    _contours = _count_closed_contours(msp, scale, _skip,
                                       outline.get("blank_length_mm", 0.0) or 0.0,
                                       outline.get("blank_width_mm", 0.0) or 0.0,
                                       CUT_LAYERS)
    pierce_from_holes = _contours["pierce_count"]

    # ── Bend data ─────────────────────────────────────────────────────────────
    bend = _extract_bend_data(msp, scale)

    # ── Thickness from drawing text if not in filename ─────────────────────────
    block_text = _collect_block_texts(doc)
    msp_texts  = "\n".join(_collect_texts(msp))
    all_text   = f"{block_text}\n{msp_texts}"

    thickness_mm: Optional[float] = thick_fn
    if thickness_mm is None:
        for m in re.finditer(
            r"(?:MATL\s+THK|THICKNESS|THK)[:\s]*(\d+(?:\.\d+)?)\s*mm",
            all_text, re.IGNORECASE
        ):
            try:
                thickness_mm = float(m.group(1))
                break
            except ValueError:
                pass

    # ── Weight ────────────────────────────────────────────────────────────────
    area_mm2 = outline.get("area_mm2", 0.0)
    weight   = _calculate_weight(area_mm2, thickness_mm or 1.5, material) \
               if area_mm2 > 0 else {}

    # ── BOM (GA drawings) ─────────────────────────────────────────────────────
    bom = _extract_bom_blocks(doc)

    # ── Dimension values ──────────────────────────────────────────────────────
    d_block_dims = _extract_d_block_dims(doc)
    dim_entities = []
    for e in msp:
        if e.dxftype() == "DIMENSION":
            try:
                v = e.get_measurement()
                if v is not None:
                    dim_entities.append(round(float(v) * scale, 3))
            except Exception:
                pass
    all_dims = sorted(set(d_block_dims + dim_entities))

    # ── Geometry score ────────────────────────────────────────────────────────
    geometry_score = 1.0 if is_flat and area_mm2 > 0 else 0.97

    # ── Entity counts (all layers) ────────────────────────────────────────────
    all_lines   = [e for e in msp if e.dxftype() == "LINE"]
    bend_lines  = _get_layer_entities(msp, BEND_LAYERS, {"LINE"})
    etch_lines  = _get_layer_entities(msp, ETCH_LAYERS, {"LINE"})

    return {
        # Source
        "source":               "dxf_flat_pattern",
        "dxf_path":             str(dxf_path),
        "dxf_native_mm":        True,
        "insunits":             meta["$INSUNITS"],
        "scale_to_mm":          scale,
        "flat_pattern_detected": is_flat,
        "geometry_score":       geometry_score,

        # Filename metadata
        "part_number":          fn_data.get("part_number"),
        "revision":             fn_data.get("revision"),
        "material_from_filename": material,
        "thickness_mm_from_filename": thick_fn,
        "filename_stem":        fn_data.get("filename_stem"),

        # Blank geometry (exact)
        "estimated_pierce_count": pierce_from_holes,
        "closed_contour_count":   _contours["closed_contours"],
        # Open segments were left unchained, so some cut-outs may not have been seen. Lets a
        # caller tell "no internal cut-outs" from "we could not tell".
        "pierce_count_incomplete": bool(_contours["incomplete"]),
        "blank_length_mm":      outline.get("blank_length_mm", 0.0),
        "blank_width_mm":       outline.get("blank_width_mm",  0.0),
        "blank_area_mm2":       area_mm2,
        "bbox_area_mm2":        outline.get("bbox_area_mm2",   0.0),
        "bbox_fill_pct":        outline.get("bbox_fill_pct",   0.0),
        "perimeter_mm":         outline.get("perimeter_mm",    0.0),

        # Weight
        "thickness_mm":         thickness_mm,
        "weight_g":             weight.get("weight_g",  0.0),
        "weight_kg":            weight.get("weight_kg", 0.0),
        "density_g_per_mm3":    weight.get("density_used", 0.0),

        # Bends
        "bend_count":           bend.get("bend_count", 0),
        "bend_positions_mm":    bend.get("bend_positions_mm", []),
        "flange_lengths_mm":    bend.get("flange_lengths_mm", []),
        "bend_line_widths_mm":  bend.get("bend_line_widths_mm", []),
        "symmetric_flanges":    bend.get("symmetric_flanges", False),

        # Features
        "corner_notch_count":   notches.get("corner_notch_count", 0),
        "notch_length_mm":      notches.get("notch_length_mm", 0.0),
        "notch_angle_deg":      notches.get("notch_angle_deg", 0.0),
        "hole_count":           hole_count,
        "hole_diameters_mm":    hole_diams,

        # Entity counts by layer
        "cut_layer_lines":      len(cut_lines),
        "cut_layer_arcs":       len(cut_arcs),
        "bend_layer_lines":     len(bend_lines),
        "etch_layer_lines":     len(etch_lines),
        "total_line_entities":  len(all_lines),

        # Dimensions
        "dimension_values_mm":  all_dims,

        # BOM (GA drawings only)
        "bom_items":            bom,
        "is_assembly_drawing":  len(bom) > 0,

        # Full text for downstream processing
        "all_text":             all_text.strip(),
    }


def merge_dxf_into_scan_json(
    scan_json:  Dict[str, Any],
    dxf_path:   Path,
) -> Dict[str, Any]:
    """
    Augment an existing PDF scan JSON with DXF flat-pattern geometry.

    Match strategy: DXF filename part number (e.g. 9376-01-001) is looked up
    in scan_json['parts'].  Matched parts get geometry_score=1.0 and exact
    weight / perimeter / bend fields.  Unmatched parts are untouched.

    Returns the augmented scan_json (mutated in-place copy).
    """
    import copy
    result = copy.deepcopy(scan_json)

    try:
        flat = extract_flat_pattern_data(dxf_path)
    except Exception as exc:
        result.setdefault("dxf_merge_errors", []).append(
            {"dxf": str(dxf_path), "error": str(exc)}
        )
        return result

    dxf_pn = (flat.get("part_number") or "").strip().upper()
    if not dxf_pn:
        return result

    # Walk the parts list in the scan JSON
    parts = (result.get("manufacturing_writeup") or {}).get("parts", []) or \
            result.get("parts", [])

    matched = False
    for part in parts:
        pn = str(part.get("part_number") or "").strip().upper()
        if pn != dxf_pn:
            continue

        # Augment with DXF data — geometry wins
        geo = part.get("normalized_geometry") or {}
        geo.update({
            "blank_length_mm":   flat["blank_length_mm"],
            "blank_width_mm":    flat["blank_width_mm"],
            "blank_area_mm2":    flat["blank_area_mm2"],
            "perimeter_mm":      flat["perimeter_mm"],
            "weight_kg":         flat["weight_kg"],
            "weight_g":          flat["weight_g"],
            "geometry_source":   "dxf_flat_pattern",
            "geometry_confidence": 1.0,
            "dxf_augmented":     True,
        })
        part["normalized_geometry"] = geo
        part["geometry_score"]      = 1.0
        part["flat_pattern_detected"] = True

        # Material from filename if not already set
        if flat.get("material_from_filename") and not part.get("normalized_material"):
            part["normalized_material"] = flat["material_from_filename"]
        if flat.get("thickness_mm") and not part.get("normalized_thickness_mm"):
            part["normalized_thickness_mm"] = flat["thickness_mm"]

        # Bends
        if flat["bend_count"] > 0:
            part["bend_count_dxf"]       = flat["bend_count"]
            part["flange_lengths_mm"]    = flat["flange_lengths_mm"]
            part["bend_positions_mm"]    = flat["bend_positions_mm"]
            part["symmetric_flanges"]    = flat["symmetric_flanges"]

        # Notches / holes
        if flat["corner_notch_count"] > 0:
            part["corner_notch_count"]   = flat["corner_notch_count"]
        if flat["hole_count"] > 0:
            part["hole_count_dxf"]       = flat["hole_count"]
            part["hole_diameters_mm"]    = flat["hole_diameters_mm"]

        matched = True

    result.setdefault("dxf_augmentations", []).append({
        "dxf_file":       str(dxf_path.name),
        "part_number":    dxf_pn,
        "matched":        matched,
        "geometry_score": flat["geometry_score"],
        "weight_kg":      flat["weight_kg"],
        "perimeter_mm":   flat["perimeter_mm"],
        "bend_count":     flat["bend_count"],
    })

    return result
