"""
confidence.py — THE one answer to "how much of this line do we actually know?"

There were three implementations before this. job_decision_report._conf_info and
estimation_report's inline scoring disagreed about the same part in the same file — 2085-01
came out 0.92 HIGH on one tab and 0.70 MEDIUM on the other — and calibration.py carried a
third that the reporting pipeline never called. Adding a fourth scalar helper would have
compounded the problem, so this replaces them rather than joining them.

WHY A SCALAR WAS THE WRONG SHAPE.

A single percentage has to average things that are not commensurable, and averaging is
exactly how a job hides its own gap. On 2085 the tube material is entirely missing; a mean
of "material identity known, thickness unknown, geometry unknown, route known" lands in the
sixties and reads like partial knowledge rather than an absent input. Worse, a bought-in
placeholder scored 1.00 simply for being bought-in, so PACKAGING and DELIVERY — two lines
carrying no price at all — were counted among the job's HIGH-confidence parts.

So confidence is reported PER FIELD, each with its own status, source and reason, and the
overall status is the WEAKEST REQUIRED field. Nothing is averaged. A part whose material
price is missing is not "82% confident"; it is UNKNOWN on price and that is what decides it.

WHICH FIELDS ARE REQUIRED depends on what the line IS. A bought-in has no thickness to
know, so thickness is NOT_APPLICABLE and cannot drag it down; it does have a price, and a
missing one is decisive. A fabricated part has both. Judging every line against the same
field list is how "no fabrication thickness" became a defect on a box of packaging.

STATUSES, weakest first:
    UNKNOWN         nothing was read, or what was read cannot be stood behind
    ASSUMED         a value is in use, but it is a default or an inference, not a reading
    REPORTED        read from the drawing or an extract — reproducible, not verified
    MEASURED        read from geometry, a native model, or the estimators' own calculator
    CONFIRMED       previously agreed by an estimator (knowledge base)
    NOT_APPLICABLE  this field does not exist for this kind of line
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

__all__ = [
    "UNKNOWN", "ASSUMED", "REPORTED", "MEASURED", "CONFIRMED", "NOT_APPLICABLE",
    "STATUS_ORDER", "FieldConfidence", "assess_part", "overall_label",
    "counts_by_status",
]

UNKNOWN = "unknown"
ASSUMED = "assumed"
REPORTED = "reported"
MEASURED = "measured"
CONFIRMED = "confirmed"
NOT_APPLICABLE = "n/a"

# Weakest first. NOT_APPLICABLE is deliberately absent: a field that does not exist cannot
# be the weakest thing about a line, and treating it as zero is what made "no fabrication
# thickness" read as a defect on a box of packaging.
STATUS_ORDER = [UNKNOWN, ASSUMED, REPORTED, MEASURED, CONFIRMED]

_LABEL = {
    UNKNOWN: "UNKNOWN",
    ASSUMED: "ASSUMED",
    REPORTED: "REPORTED",
    MEASURED: "MEASURED",
    CONFIRMED: "CONFIRMED",
    NOT_APPLICABLE: "N/A",
}

# Display colours, shared so both tabs shade a status the same way.
STATUS_FILL = {
    UNKNOWN: ("FFC7CE", "9C0006"),
    ASSUMED: ("FFE699", "7F6000"),
    REPORTED: ("FFF2CC", "7F6000"),
    MEASURED: ("C6EFCE", "276221"),
    CONFIRMED: ("C6EFCE", "276221"),
    NOT_APPLICABLE: ("EDEDED", "555555"),
}


class FieldConfidence(dict):
    """{field, status, source, reason} — a dict so it serialises into the job JSON."""

    def __init__(self, field: str, status: str, source: str = "", reason: str = ""):
        super().__init__(field=field, status=status, source=source, reason=reason)

    @property
    def status(self) -> str:
        return str(self.get("status") or UNKNOWN)

    @property
    def label(self) -> str:
        return _LABEL.get(self.status, self.status.upper())


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _is_bought_in(part: Mapping[str, Any]) -> bool:
    material = str(part.get("normalized_material") or part.get("material") or "").upper()
    if material == "BOUGHT_IN":
        return True
    if "bought_in" in [str(r).lower() for r in (part.get("page_roles") or [])]:
        return True
    source = str(part.get("source") or "").lower()
    if "recogniser" in source or "bought_in" in source or "note_scan" in source:
        return True
    return str(part.get("part_number") or "").upper().startswith(
        ("BI-", "FIXING", "VINYL", "PACKAGING", "DELIVERY"))


def _material_identity(part: Mapping[str, Any]) -> FieldConfidence:
    """What the part is made of, judged on material_source ALONE.

    AI Provenance scored this from `geometry_source` — a DXF flat pattern raised the
    MATERIAL confidence to 95% — while printing the label from `material_source`. The score
    and the label described different fields, so the 95% was never a statement about the
    material at all. Geometry says nothing about alloy."""
    if _is_bought_in(part):
        return FieldConfidence("material identity", NOT_APPLICABLE, "",
                               "bought-in / catalogue line — no fabrication material")
    source = str(part.get("material_source") or "")
    material = str(part.get("normalized_material") or part.get("material") or "")
    if not material or material.upper() in ("UNKNOWN", "NONE"):
        return FieldConfidence("material identity", UNKNOWN, source,
                               "no material resolved")
    if "knowledge_base" in source:
        return FieldConfidence("material identity", CONFIRMED, source,
                               "previously confirmed by an estimator")
    if "dxf_filename" in source or "dxf" in source:
        return FieldConfidence("material identity", MEASURED, source,
                               "material code read from the DXF filename")
    if "solidworks" in source or "native" in source:
        return FieldConfidence("material identity", MEASURED, source,
                               "read from the native model")
    if "override_rule" in source:
        return FieldConfidence("material identity", REPORTED, source,
                               "a learning rule fired on the drawing's own text")
    if "pn_suffix" in source:
        return FieldConfidence("material identity", ASSUMED, source,
                               "inferred from the part-number suffix")
    if source:
        return FieldConfidence("material identity", REPORTED, source,
                               "read from the drawing or extract")
    return FieldConfidence("material identity", ASSUMED, "",
                           "in use, but nothing records where it came from")


def _thickness(part: Mapping[str, Any]) -> FieldConfidence:
    if _is_bought_in(part):
        return FieldConfidence("thickness", NOT_APPLICABLE, "",
                               "bought-in line — no fabrication thickness")
    filename = str(part.get("dxf_source_file") or "")
    import re as _re
    hit = _re.search(r"[_\-\s](\d+\.?\d*)\s*mm", filename, _re.IGNORECASE)
    if hit and 0.3 <= float(hit.group(1)) <= 25.0:
        return FieldConfidence("thickness", MEASURED, f"dxf_filename:{filename}",
                               f"{float(hit.group(1)):g}mm stated in the DXF filename")
    thicknesses = [t for t in (part.get("thicknesses_mm") or []) if _num(t)]
    tolerance = {0.5, 1.0, 1.5, 2.0, 3.0}
    real = [t for t in thicknesses if round(float(t), 1) not in tolerance] \
        if tolerance.issubset({round(float(t), 1) for t in thicknesses}) else thicknesses
    if real:
        geometry = str(part.get("geometry_source") or "")
        if "dxf" in geometry:
            return FieldConfidence("thickness", MEASURED, geometry,
                                   f"{float(real[0]):g}mm from DXF geometry")
        return FieldConfidence("thickness", REPORTED, geometry or "pdf",
                               f"{float(real[0]):g}mm from the drawing text")
    if thicknesses:
        return FieldConfidence("thickness", UNKNOWN, "tolerance_table",
                               "only tolerance-table values were found, not a thickness")
    return FieldConfidence("thickness", UNKNOWN, "", "no thickness was read")


def _geometry(part: Mapping[str, Any]) -> FieldConfidence:
    if _is_bought_in(part):
        return FieldConfidence("geometry", NOT_APPLICABLE, "",
                               "bought-in line — no fabrication geometry")
    source = str(part.get("geometry_source") or "")
    if part.get("geometry_inferred") and not part.get("dxf_augmented"):
        basis = (part.get("geometry_inference") or {}).get("basis") or "inference"
        return FieldConfidence("geometry", ASSUMED, str(basis),
                               "blank size inferred — no flat pattern supplied")
    if "solidworks" in source or "native" in source:
        return FieldConfidence("geometry", MEASURED, source, "from the native model")
    if "dxf" in source:
        return FieldConfidence("geometry", MEASURED, source, "DXF flat pattern")
    reliability = _num((part.get("geometry_rollup") or {}).get("geometry_reliability")) or 0.0
    if reliability >= 0.5:
        return FieldConfidence("geometry", REPORTED, source or "pdf",
                               f"PDF vector extraction, reliability {reliability:.0%}")
    return FieldConfidence("geometry", UNKNOWN, source or "pdf",
                           "no usable geometry — PDF extraction only")


def _route(part: Mapping[str, Any], summary: Any) -> FieldConfidence:
    """Whether we know what happens to this part, from the PRICED route only."""
    try:
        from costed_facts import operations_for_part, priced_route_known
    except Exception:
        return FieldConfidence("route", UNKNOWN, "", "the priced route could not be read")
    if not priced_route_known(summary):
        return FieldConfidence("route", ASSUMED, "drawing",
                               "no workbook built — the route is the drawing's reading, "
                               "not a priced one")
    operations = operations_for_part(summary, part.get("part_number"), part)
    if operations:
        return FieldConfidence("route", MEASURED, "workbook_labour",
                               f"{len(operations)} operation(s) charged on the sheet")
    if _is_bought_in(part):
        return FieldConfidence("route", NOT_APPLICABLE, "workbook_labour",
                               "bought-in line — no fabrication route")
    return FieldConfidence("route", UNKNOWN, "workbook_labour",
                           "the priced route charges this part nothing")


def _material_price(part: Mapping[str, Any]) -> FieldConfidence:
    """The one field a placeholder line is genuinely judged on.

    A bought-in scored 1.00 for being bought-in, so PACKAGING and DELIVERY — carrying no
    price at all — were counted among the job's HIGH-confidence parts. Being purchased
    rather than made says nothing about whether anyone has priced it."""
    try:
        from costed_facts import part_material_cost, is_placeholder_price
    except Exception:
        return FieldConfidence("material price", UNKNOWN, "", "price could not be read")
    if is_placeholder_price(part):
        return FieldConfidence("material price", UNKNOWN, "placeholder",
                               "NOT YET PRICED — estimator to enter a figure")
    unit, _extended = part_material_cost(part)
    if not unit:
        return FieldConfidence("material price", UNKNOWN, "",
                               "no material cost — the rate or the stock size is missing")
    source = ((part.get("material_estimate") or {}).get("price_source") or {})
    name = str(source.get("source_name") or "")
    if "knowledge_base" in name or source.get("price_verified"):
        return FieldConfidence("material price", CONFIRMED, name, "agreed rate")
    if source.get("source_type") in ("web_ai_fallback",) or "web_ai" in name.lower():
        return FieldConfidence("material price", ASSUMED, name,
                               "web/AI fallback price — verify before quoting")
    if name:
        return FieldConfidence("material price", REPORTED, name,
                               "list or catalogue rate — reproducible, not agreed")
    return FieldConfidence("material price", ASSUMED, "",
                           "a rate is in use but its source was not recorded")


def _labour_rate(part: Mapping[str, Any], summary: Any) -> FieldConfidence:
    """How the throughput behind this part's labour rows was arrived at.

    The distinction the audit tabs never showed: Tube 40/hr is an UNMEASURED constant,
    P.Coat 458/hr is a historical observation used UNBANDED because no part area was
    computed, and the laser rate is the estimators' OWN calculator read off the template.
    Three very different claims, presented identically."""
    try:
        from costed_facts import priced_rows_for_part, priced_route_known
    except Exception:
        return FieldConfidence("labour rate", UNKNOWN, "", "labour rows could not be read")
    if not priced_route_known(summary):
        return FieldConfidence("labour rate", UNKNOWN, "", "no workbook built")
    rows = priced_rows_for_part(summary, part.get("part_number"))
    if not rows:
        if _is_bought_in(part):
            return FieldConfidence("labour rate", NOT_APPLICABLE, "",
                                   "bought-in line — no labour")
        return FieldConfidence("labour rate", UNKNOWN, "",
                               "this part is on no labour row")
    bases = [str(r.get("rate_basis") or "") for r in rows]
    weakest = ASSUMED if any(b == "unmeasured_default" for b in bases) else None
    if weakest is None and any(b == "historical_unbanded" for b in bases):
        weakest = REPORTED
    if weakest is None and all(b in ("template_calculated", "size_banded", "historical")
                               for b in bases if b):
        weakest = MEASURED
    named = sorted({b for b in bases if b})
    reason = {
        "unmeasured_default": "at least one rate is an UNMEASURED default, not observed",
        "historical_unbanded": "historical rate used un-banded — no part area to band on",
    }.get(named[0] if len(named) == 1 else "", "")
    if not reason:
        if weakest == MEASURED:
            reason = "rates are template-calculated or measured from history"
        else:
            reason = "mixed rate bases: " + ", ".join(named) if named else \
                "no rate basis was recorded"
    return FieldConfidence("labour rate", weakest or UNKNOWN,
                           ", ".join(named), reason)


def _completeness(part: Mapping[str, Any], fields: List[FieldConfidence]) -> FieldConfidence:
    """Whether the line has everything it needs to be a price."""
    missing = [f["field"] for f in fields if f.status == UNKNOWN]
    if missing:
        return FieldConfidence("completeness", UNKNOWN, "",
                               "missing: " + ", ".join(missing))
    assumed = [f["field"] for f in fields if f.status == ASSUMED]
    if assumed:
        return FieldConfidence("completeness", ASSUMED, "",
                               "resting on assumptions: " + ", ".join(assumed))
    return FieldConfidence("completeness", MEASURED, "",
                           "every required field has a reading")


def assess_part(part: Mapping[str, Any], summary: Any = None) -> Dict[str, Any]:
    """Field-by-field confidence for ONE line, plus the overall status it implies.

    Overall is the WEAKEST REQUIRED field, never a mean. Averaging is how a job hides its
    own gap: a part with no material price at all can average into the sixties and read as
    partial knowledge rather than an absent input."""
    if not isinstance(part, Mapping):
        part = {}
    fields: List[FieldConfidence] = [
        _material_identity(part),
        _thickness(part),
        _geometry(part),
        _route(part, summary),
        _material_price(part),
        _labour_rate(part, summary),
    ]
    fields.append(_completeness(part, fields))

    required = [f for f in fields if f.status != NOT_APPLICABLE]
    overall = UNKNOWN
    if required:
        overall = min(required, key=lambda f: STATUS_ORDER.index(f.status)
                      if f.status in STATUS_ORDER else 0).status
    weakest = [f["field"] for f in required if f.status == overall]
    return {
        "part_number": part.get("part_number"),
        "fields": fields,
        "overall": overall,
        "overall_label": _LABEL.get(overall, overall.upper()),
        "decided_by": weakest,
        "is_bought_in": _is_bought_in(part),
        "reason": "; ".join(
            f"{f['field']}: {f['reason']}" for f in required if f.status == overall),
    }


def overall_label(assessment: Mapping[str, Any]) -> str:
    return str((assessment or {}).get("overall_label") or "UNKNOWN")


def counts_by_status(assessments: List[Mapping[str, Any]]) -> Dict[str, int]:
    """How many lines sit at each status.

    Replaces the "HIGH: 3 parts" summary that counted two unpriced placeholders as the most
    confident items on the job — because a bought-in was scored 1.00 for being bought-in."""
    out: Dict[str, int] = {s: 0 for s in STATUS_ORDER}
    for item in assessments or []:
        status = str((item or {}).get("overall") or UNKNOWN)
        out[status] = out.get(status, 0) + 1
    return out
