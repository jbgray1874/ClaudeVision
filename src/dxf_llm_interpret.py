"""
dxf_llm_interpret.py — a judgement layer over a MEASURED DXF.

WHAT THIS IS FOR. ezdxf reads a DXF exactly: entities, layers, closed loops, areas, cut
lengths, hole diameters. Those are measurements and nothing here replaces them. What ezdxf
cannot do is say what the geometry MEANS — which layer is the cut profile and which is bend
lines, whether a 7mm circle is a clearance hole or a keyhole, whether this file is one part or
a nest of six, whether it should be lasered or punched. That is process judgement, and it is
what a model is for.

TWO THINGS ARE ASKED OF THE MODEL, AND THEY ARE TREATED DIFFERENTLY.

  JUDGEMENT   recommended_process, complexity, is_flat_pattern, hole types, material and
              thickness read from text, warnings. Taken and stamped `inference` — the lowest
              rank there is, so it fills gaps and never overwrites anything real.

  GEOMETRY    widths, cut lengths, hole counts. Asked for DELIBERATELY, and then NOT used as
              the value. ezdxf's number stands. The model's is kept beside it, and where the
              two disagree materially that disagreement is reported — because two independent
              reads that differ mean one of them is wrong about a file we are about to cost,
              and neither silently winning is the right answer.

The model is sent what ezdxf extracted, not the file. A DXF is tens of thousands of coordinate
triples; a model handed those will do arithmetic it cannot do reliably, and produce a confident
cut length with nothing behind it. That is the exact failure this engine spent a day removing
from prices, and it is not being reintroduced through geometry.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

SOURCE_NAME = "dxf_llm_interpret"
INFERENCE_SOURCE = "inference"

# A measured value and a read value that differ by more than this are not the same answer.
_DISAGREE_PCT = 0.10

_SYSTEM = ("You are a process engineer interpreting an already-measured DXF and answering in "
           "JSON. The measurements are given to you and are exact; your job is to say what "
           "they mean — which layer is the cut profile, what each hole is for, how the part "
           "should be made. Say null where you cannot tell.")

_PROMPT = """You are an expert laser and sheet-metal nesting and process engineer at SDI
Displays, working across mild steel, stainless, aluminium, acrylic, timber, wire and tube.

Below is what has been MEASURED from a DXF file by a geometry reader: its layers, entity
counts, bounding box, closed contours, hole diameters, cut lengths, and every piece of text in
the file. The measurements are exact. Your job is to say what they MEAN.

Return ONLY valid JSON in this schema:
{
  "file_info": {"filename": "", "layers": [], "units": ""},
  "geometry": {
    "overall_width_mm": null, "overall_height_mm": null,
    "total_cut_length_mm": null, "outer_profile_length_mm": null,
    "internal_cut_length_mm": null, "hole_count": null,
    "holes": [{"diameter_mm": 0.0, "count": 0, "type": "round|slot|keyhole|other"}]
  },
  "manufacturing": {
    "recommended_process": "laser|punch|combination",
    "material_inferred": null, "thickness_inferred_mm": null,
    "is_flat_pattern": true, "is_nested": false, "part_count": 1,
    "complexity": "simple|medium|complex",
    "profile_role_by_layer": {"<layer name>": "cut|bend|annotation|dimension|other"},
    "operations_implied": []
  },
  "warnings": [],
  "extraction_confidence": "high|medium|low"
}

WHAT MATTERS MOST — the fields only you can answer:
- profile_role_by_layer: which layer carries the cut profile, which the bend lines, which is
  annotation. Exporters name these inconsistently and getting it wrong costs a part its bends.
- holes[].type: a diameter alone does not say whether it is a clearance hole, a tapped hole, a
  keyhole or a slot. The shape and repetition do.
- is_nested / part_count: one part, or several on a sheet? A nest costed as one part is wrong
  by however many parts are on it.
- recommended_process and complexity: what the shop should do with it.
- material_inferred / thickness_inferred_mm: ONLY from the text or the filename shown below.
- operations_implied: from laser_cutting, punch, saw, tube_cut, folding, rolling, tube_bending,
  welding, dress_welds, hole_machining, tapping, deburring, cnc_routing, edge_banding, glue,
  powder_coating, wet_spray, diamond_polish, wire_forming, handling.

THE GEOMETRY BLOCK. Fill it from what you can see in the measurements — it is compared against
the reader's own figures as a cross-check, not used as the value. If the two disagree, that
tells us something is wrong with the file or the read, which is worth knowing. Do not compute
from coordinates; if you cannot tell, use null. A null is honest.

Put anything odd in warnings: open contours, geometry on an unexpected layer, a profile that
does not close, duplicated entities, dimensions that contradict the outline.
"""


def build_payload(measured: Dict[str, Any], filename: str = "") -> str:
    """What the model is shown: the extraction, never the file."""
    return json.dumps({
        "filename": filename,
        "layers": measured.get("layers"),
        "entity_counts": measured.get("entity_counts"),
        "bounding_box_mm": measured.get("bounding_box_mm"),
        "closed_contour_count": measured.get("closed_contour_count"),
        "hole_diameters_mm": measured.get("hole_diameters_mm"),
        "measured_cut_length_mm": measured.get("cut_length_mm"),
        "measured_blank_mm": measured.get("blank_mm"),
        "text_entities": measured.get("text_entities"),
    }, ensure_ascii=False, indent=1)[:30000]


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def reconcile(measured: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
    """Measurement wins; disagreement is reported.

    The model was asked for geometry on purpose. Not to use it — ezdxf measured the file and
    that number stands — but because a second independent read that differs materially means
    one of them is wrong about a file we are about to cost. Silently preferring either is how
    a short blank or a doubled cut length reaches a quote unchallenged.
    """
    geom = (model or {}).get("geometry") or {}
    out: Dict[str, Any] = {"disagreements": [], "model_read": geom}
    pairs = (
        ("total_cut_length_mm", measured.get("cut_length_mm")),
        ("hole_count", measured.get("hole_count")),
        ("overall_width_mm", (measured.get("blank_mm") or [None, None])[0]),
        ("overall_height_mm", (measured.get("blank_mm") or [None, None])[1]),
    )
    for key, measured_value in pairs:
        m, r = _num(measured_value), _num(geom.get(key))
        if m is None or r is None or m <= 0:
            continue
        if abs(m - r) / m > _DISAGREE_PCT:
            out["disagreements"].append({
                "field": key, "measured": round(m, 3), "model_read": round(r, 3),
                "difference_pct": round(abs(m - r) / m * 100.0, 1),
            })
    return out


def interpret(measured: Dict[str, Any], filename: str = "",
              caller: Optional[Any] = None) -> Dict[str, Any]:
    """Interpret one measured DXF. {} on any failure — the geometry still costs the part.

    `caller` is injectable so this is testable without a model: a function that can only run
    where an API key happens to be present is a function nobody tests.
    """
    if not isinstance(measured, dict) or not measured:
        return {}
    payload = _PROMPT + "\n\n===== MEASURED FROM THE FILE =====\n" + build_payload(measured, filename)
    try:
        if caller is not None:
            raw = caller(payload)
        else:
            from llm_full_extract import _call_llm, _parse, DEFAULT_MODEL
            # Its own system message. This pass is asked for judgement over a measurement,
            # not transcription, and shipping it under "Never invent" would get exactly the
            # nulls that judgement is supposed to replace.
            raw = _call_llm(payload, DEFAULT_MODEL, system=_SYSTEM)
        parsed = raw if isinstance(raw, dict) else None
        if parsed is None and raw:
            from llm_full_extract import _parse
            parsed = _parse(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}

    mfg = parsed.get("manufacturing") or {}
    result = {
        "source": SOURCE_NAME,
        "found": True,
        # Judgement — taken, and ranked below every measurement.
        "interpretation_source": INFERENCE_SOURCE,
        "profile_role_by_layer": mfg.get("profile_role_by_layer") or {},
        "hole_types": (parsed.get("geometry") or {}).get("holes") or [],
        "recommended_process": mfg.get("recommended_process"),
        "complexity": mfg.get("complexity"),
        "is_flat_pattern": mfg.get("is_flat_pattern"),
        "is_nested": mfg.get("is_nested"),
        "part_count": mfg.get("part_count"),
        "material_inferred": mfg.get("material_inferred"),
        "thickness_inferred_mm": _num(mfg.get("thickness_inferred_mm")),
        "operations_implied": [str(o).strip().lower() for o in
                               (mfg.get("operations_implied") or []) if str(o).strip()],
        "warnings": parsed.get("warnings") or [],
        "extraction_confidence": parsed.get("extraction_confidence"),
    }
    result.update(reconcile(measured, parsed))
    return result
