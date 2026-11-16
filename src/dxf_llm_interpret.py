"""
dxf_llm_interpret.py — two independent reads of one DXF, merged with a stated precedence.

THE SHAPE OF THIS, AND WHY IT IS THIS SHAPE.

Both sides extract as much as they can on their own, and the merge decides. ezdxf reads the
file exactly — entities, layers, closed loops, areas, cut lengths, hole diameters — and those
are measurements. What ezdxf cannot do is say what the geometry MEANS: which layer carries the
cut profile and which the bend lines, whether a 7mm circle is a clearance hole or a keyhole,
whether the file is one part or a nest of six, whether it should be lasered or punched. That is
process judgement, and it is what a model is for.

PRECEDENCE, per datum, stated once here so no consumer has to infer it:

  MEASURED WINS      overall size, cut lengths, hole count, areas. ezdxf's number is the value.
  MODEL WINS         process, complexity, hole TYPE, profile role by layer, material and
                     thickness read from text, nesting, warnings. Taken and stamped
                     `inference` — the lowest rank in the waterfall — so it fills gaps in the
                     costing record and can never overwrite anything measured.

WHAT THE MODEL IS SENT, AND WHAT THAT MAKES THE CROSS-CHECK WORTH.

The model gets the extraction, not the file. A DXF is tens of thousands of coordinate triples;
a model handed those does arithmetic it cannot do reliably and returns a confident cut length
with nothing behind it. That is the exact failure this engine spent a day removing from prices.

But it is deliberately NOT sent ezdxf's cut lengths. Those are the numbers that cost money, so
the model's own figure is worth having as a second opinion, and a second opinion is only worth
something if it was arrived at independently. Where the two differ materially that is reported
— two reads disagreeing about a file we are about to cost means one of them is wrong.

The model IS sent the bounding box and the hole diameters, because it cannot type a hole it
cannot see. So overall size and hole count are NOT independent and are not cross-checked; only
cut length is. Said plainly here because a cross-check that quietly compares a number against
itself is worse than none.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

SOURCE_NAME = "dxf_llm_interpret"
INFERENCE_SOURCE = "inference"

# One vocabulary, shared with the PDF passes and cross-checked against the workbook's
# department map. A word we ask for that the sheet cannot cost is work silently deleted.
from llm_full_extract import ROUTE_OPERATIONS

# A measured value and an independently read one that differ by more than this are not the
# same answer.
_DISAGREE_PCT = 0.10

_SYSTEM = ("You are a process engineer interpreting a DXF flat pattern and answering in JSON. "
           "Extract every useful geometric and manufacturing insight you can. Where a value "
           "cannot be determined, return null — never invent a number.")

# The model's own schema: it extracts as richly as it can, independently, and the merge below
# decides which of its answers become values and which stay as judgement.
_PROMPT = """You are an expert sheet-metal, acrylic, timber and multi-material manufacturing
engineer with deep experience reading DXF flat patterns.

Analyse the DXF described below — its filename, layers, entity counts, bounding box, hole
diameters and every piece of text in the file — and extract the richest possible manufacturing
and geometric interpretation.

Return ONLY valid JSON in this schema:

{
  "file_info": {
    "filename": "",
    "interpreted_units": "mm|inch|unknown"
  },
  "geometry_interpretation": {
    "overall_width_mm": null,
    "overall_height_mm": null,
    "is_flat_pattern": true,
    "profile_type": "closed|open|multiple",
    "has_internal_cutouts": false,
    "estimated_total_cut_length_mm": null,
    "estimated_outer_profile_length_mm": null,
    "estimated_internal_cut_length_mm": null
  },
  "holes": [
    {"diameter_mm": null, "count": 0, "type": "round|slot|square|obround|other", "notes": ""}
  ],
  "manufacturing": {
    "recommended_process": "laser|punch|combination|router|saw|unknown",
    "secondary_processes": [],
    "complexity": "simple|medium|complex",
    "estimated_pierce_count": null,
    "material_inferred": "",
    "thickness_inferred_mm": null,
    "finish_inferred": "",
    "grain_or_direction_sensitive": false,
    "profile_role_by_layer": {"<layer name>": "cut|bend|annotation|dimension|other"},
    "is_nested": false,
    "part_count": 1,
    "operations_implied": [],
    "notes": ""
  },
  "warnings": [],
  "extraction_confidence": "high|medium|low",
  "comments": ""
}

Rules:
- Extract every useful geometric and manufacturing insight you can.
- Prefer explicit information (filename, text entities, clear geometry) over guesses.
- If a value cannot be determined, use null or empty string — do not invent numbers.
- Classify holes by type even if only the diameter is known.
- recommended_process is the primary process; list likely secondary processes separately.
- Flag open contours, tiny features, missing thickness, ambiguous units, or anything that
  would affect nesting or costing, in warnings.
- Be conservative with confidence when material or thickness is not clear.

WHAT MATTERS MOST — the fields only you can answer:
- profile_role_by_layer: which layer carries the cut profile, which the bend lines, which is
  annotation. Exporters name these inconsistently and getting it wrong costs a part its bends.
- holes[].type: a diameter alone does not say whether it is a clearance hole, a tapped hole,
  a keyhole or a slot. The shape and the repetition do.
- is_nested / part_count: one part, or several on a sheet? A nest costed as one part is wrong
  by however many parts are on it.
- material_inferred / thickness_inferred_mm: ONLY from the text or the filename shown below.
- operations_implied: from this list and no other — """ + ", ".join(ROUTE_OPERATIONS) + """.

THE CUT LENGTHS. You have not been given the reader's figures, deliberately — yours is wanted
as an independent second opinion, and it is compared against the reader's rather than used in
its place. Estimate from what you can see, and use null if you cannot tell. A null is honest.
"""


def measured_payload(measured: Dict[str, Any], filename: str = "") -> Dict[str, Any]:
    """What the model is shown: the extraction, minus the numbers it is being cross-checked on.

    Mirrors the code-side extraction shape (file_info + geometry) so both halves of the pair
    line up field for field, with the cut lengths withheld — see the module docstring.
    """
    bbox = measured.get("blank_mm") or measured.get("bounding_box_mm") or [None, None]
    return {
        "file_info": {
            "filename": filename or measured.get("filename") or "",
            "dxf_version": measured.get("dxf_version"),
            "units": measured.get("units"),
            "layers": measured.get("layers"),
        },
        "geometry": {
            "overall_width_mm": (bbox or [None, None])[0],
            "overall_height_mm": (bbox or [None, None])[1],
            "raw_hole_diameters_mm": measured.get("hole_diameters_mm"),
            "closed_contour_count": measured.get("closed_contour_count"),
            "entity_summary": measured.get("entity_counts"),
            "text_entities": measured.get("text_entities"),
        },
    }


def build_payload(measured: Dict[str, Any], filename: str = "") -> str:
    return json.dumps(measured_payload(measured, filename),
                      ensure_ascii=False, indent=1)[:30000]


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


# The ONLY fields sent to the model, so the only ones whose agreement means nothing.
_NOT_INDEPENDENT = ("overall_width_mm", "overall_height_mm", "hole_count")


def reconcile(measured: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
    """Cross-check the model's independent read against the measurement.

    Measurement is the value, always. This exists because two independent reads that differ
    materially mean one of them is wrong about a file we are about to cost, and silently
    preferring either is how a short blank or a doubled cut length reaches a quote unchallenged.

    Only cut length is compared: it is the one figure the model was not shown.
    """
    geom = (model or {}).get("geometry_interpretation") or (model or {}).get("geometry") or {}
    out: Dict[str, Any] = {"disagreements": [], "model_read": geom,
                           "not_cross_checked": list(_NOT_INDEPENDENT)}
    pairs = (
        ("estimated_total_cut_length_mm", measured.get("cut_length_mm")),
        ("estimated_outer_profile_length_mm", measured.get("outer_profile_length_mm")),
        ("estimated_internal_cut_length_mm", measured.get("internal_cut_length_mm")),
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
            from llm_full_extract import _call_llm, DEFAULT_MODEL
            # Its own system message. This pass is asked for judgement over a measurement,
            # not transcription, and shipping it under "Never invent" returns exactly the
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
    geo = parsed.get("geometry_interpretation") or {}
    result = {
        "source": SOURCE_NAME,
        "found": True,
        # Judgement — taken, and ranked below every measurement.
        "interpretation_source": INFERENCE_SOURCE,
        "profile_role_by_layer": mfg.get("profile_role_by_layer") or {},
        "hole_types": parsed.get("holes") or [],
        "recommended_process": mfg.get("recommended_process"),
        "secondary_processes": mfg.get("secondary_processes") or [],
        "complexity": mfg.get("complexity"),
        "estimated_pierce_count": _num(mfg.get("estimated_pierce_count")),
        "is_flat_pattern": geo.get("is_flat_pattern"),
        "profile_type": geo.get("profile_type"),
        "has_internal_cutouts": geo.get("has_internal_cutouts"),
        "is_nested": mfg.get("is_nested"),
        "part_count": mfg.get("part_count"),
        "material_inferred": mfg.get("material_inferred") or None,
        "thickness_inferred_mm": _num(mfg.get("thickness_inferred_mm")),
        "finish_inferred": mfg.get("finish_inferred") or None,
        "grain_or_direction_sensitive": mfg.get("grain_or_direction_sensitive"),
        "operations_implied": [str(o).strip().lower() for o in
                               (mfg.get("operations_implied") or []) if str(o).strip()],
        "warnings": parsed.get("warnings") or [],
        "extraction_confidence": parsed.get("extraction_confidence"),
        "comments": parsed.get("comments"),
    }
    result.update(reconcile(measured, parsed))
    return result


# Fields the interpretation may fill on a part record, and the part key each lands on. Kept
# explicit: a judgement layer that writes wherever a key happens to match is how an inferred
# value ends up outranking a measured one by accident.
_GAP_FILL = (
    ("material_inferred", "normalized_material", "material_source"),
    ("thickness_inferred_mm", "normalized_thickness_mm", "thickness_source"),
)


def apply_to_part(part: Dict[str, Any], interp: Dict[str, Any]) -> Dict[str, int]:
    """Fold an interpretation onto a measured part. Gap-fill only, stamped `inference`.

    Everything ezdxf measured is already on the part and is not touched. What this adds is the
    judgement: process, complexity, hole typing, nesting, and material/thickness ONLY where the
    part has none. Disagreements and warnings go to review_flags, where a person sees them.
    """
    counts = {"filled": 0, "flags": 0}
    if not isinstance(part, dict) or not isinstance(interp, dict) or not interp.get("found"):
        return counts

    part["dxf_interpretation"] = interp

    for src_key, part_key, source_key in _GAP_FILL:
        val = interp.get(src_key)
        if val in (None, "", []) or part.get(part_key) not in (None, "", []):
            continue
        part[part_key] = val
        part[source_key] = INFERENCE_SOURCE
        part.setdefault("review_flags", []).append(
            f"{part_key} '{val}' INFERRED from the DXF's text and filename — not measured; verify")
        counts["filled"] += 1

    # A NEST COSTED AS ONE PART IS WRONG BY HOWEVER MANY PARTS ARE ON IT, and it is the one
    # judgement here that moves a price on its own. Never applied silently.
    try:
        pc = int(interp.get("part_count") or 1)
    except (TypeError, ValueError):
        pc = 1
    if interp.get("is_nested") and pc > 1:
        part.setdefault("review_flags", []).append(
            f"DXF read as a NEST of {pc} parts, not one part. The measured blank and cut "
            f"length cover the whole sheet, so costing it as a single part is wrong by a "
            f"factor of about {pc}. Confirm before quoting")
        counts["flags"] += 1

    for d in (interp.get("disagreements") or []):
        part.setdefault("review_flags", []).append(
            f"DXF cross-check: {d['field']} measured {d['measured']} vs independently read "
            f"{d['model_read']} ({d['difference_pct']}% apart). The measurement is used; the "
            f"gap means one of the two reads is wrong about this file")
        counts["flags"] += 1

    for w in (interp.get("warnings") or [])[:6]:
        part.setdefault("review_flags", []).append(f"DXF: {w}")
        counts["flags"] += 1

    return counts
