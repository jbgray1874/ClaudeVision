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

        if len(bound) != 1:
            if bound:
                part.setdefault("review_flags", []).append(
                    f"{pn or 'this part'} is bound to {len(bound)} pages "
                    f"({', '.join(str(b) for b in sorted(bound))}) — no single sheet defines it, "
                    f"so its blank is UNRESOLVED and the size used is a fallback envelope")
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
            part.setdefault("review_flags", []).append(
                f"{pn or 'this part'}: page {page_no} is its detail sheet but its blank could "
                f"not be taken from it — {verdict.get('reason') or 'refused'}. UNRESOLVED; the "
                f"size used is a fallback envelope")
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
