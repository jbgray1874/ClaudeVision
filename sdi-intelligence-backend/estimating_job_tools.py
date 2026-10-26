"""Bounded completed-brief browsing and evidence-only questions for saved runs."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# The share has a "Shared" folder before "Estimating" - the same prefix as the
# workbook template in app.py. Without it the folder simply is not there, and
# the failure reads as "the share is unavailable to this service", which sends
# somebody looking at share permissions that are fine.
BRIEFS_ROOT = Path(os.getenv(
    "SDI_COMPLETED_AI_BRIEFS_ROOT",
    r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Live Enquiries\completed AI briefs",
))


def _is_number(value: Any) -> bool:
    """A figure that is really there. False for None, "" and anything unparseable."""
    if value is None or isinstance(value, bool):
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _named_in(part_number: str, question: str) -> bool:
    """Was THIS part asked about?

    A plain substring test attributed a cost to the wrong part: a part numbered
    "A" or "S-1" appears inside half the words in an ordinary question. So the
    number has to stand on its own, with only separators around it.
    """
    part = part_number.strip().lower()
    if len(part) < 2:
        return False
    return re.search(r"(?<![0-9a-z])" + re.escape(part) + r"(?![0-9a-z])",
                     question) is not None


def browse_briefs(relative: str = "") -> dict[str, Any]:
    """List one level only; the caller never supplies an absolute path."""
    if len(relative) > 512:
        raise ValueError("Folder path is too long.")
    segments = relative.split("/") if relative else []
    if any(not s or s in (".", "..") or "\\" in s or ":" in s
           or any(ord(c) < 32 for c in s) for s in segments):
        raise ValueError("Invalid folder path.")
    root = BRIEFS_ROOT.resolve(strict=True)
    try:
        target = root.joinpath(*segments).resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("Folder not found in the approved briefs area.") from exc
    if target != root and root not in target.parents:
        raise ValueError("Folder is outside the approved briefs area.")
    if not target.is_dir():
        raise ValueError("Not a folder.")
    rows = []
    for child in target.iterdir():
        if child.name.startswith("."):
            continue
        try:
            resolved = child.resolve(strict=True)
            if root not in resolved.parents:
                continue
            is_dir = child.is_dir()
            if not is_dir and child.suffix.lower() not in (
                    ".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm",
                    ".slddrw", ".step", ".stp", ".txt", ".msg"):
                continue
            rows.append({"name": child.name,
                         "relative": "/".join(segments + [child.name]),
                         "is_dir": is_dir,
                         "kind": "folder" if is_dir else "file",
                         "size": None if is_dir else child.stat().st_size})
        except (OSError, ValueError):
            continue
    rows.sort(key=lambda r: (r["kind"] != "folder", r["name"].casefold()))
    drawing_names = [r["name"] for r in rows if r["kind"] == "file" and
                     Path(r["name"]).suffix.lower() in (
                         ".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw")]
    can_select = len(segments) >= 2 and bool(drawing_names)
    return {"relative": relative, "parent": "/".join(segments[:-1]),
            "folder_path": str(target), "folder_name": target.name,
            "entries": rows[:300], "truncated": len(rows) > 300,
            "can_select": can_select, "drawing_count": len(drawing_names)}


def answer_saved_record(record: dict[str, Any], question: str) -> dict[str, Any]:
    """Answer only from the supplied run record; never invent a cost or drawing fact."""
    q = " ".join(question.split()).lower()
    if not q or len(q) > 500:
        raise ValueError("Ask a question of up to 500 characters.")
    final = record.get("final_estimate") or {}
    costed = record.get("costed_job") or {}
    lines = costed.get("lines") or []
    if any(w in q for w in ("price", "cost", "total", "amount", "charge")):
        totals = final.get("totals") or {}
        if not totals:
            return {"answer": "No calculated total is present in this saved record.",
                    "sources": ["final_estimate.totals"], "complete": False}
        # A MISSING FIGURE IS NOT ZERO. "or 0" turned an absent unit total into
        # "£0.00", stated as a calculated fact - the one thing this is not
        # allowed to do. An absent figure says it is absent.
        money = lambda key: ("£{:.2f}".format(float(totals[key]))
                             if _is_number(totals.get(key)) else "not recorded")
        answer = ("Calculated unit total: {}; material {}, labour {}, other {}. "
                  "Workbook cell: {}.").format(
            money("unit_gbp"), money("material_gbp"), money("labour_gbp"),
            money("other_gbp"), totals.get("unit_cell") or "not recorded")
        matches = [l for l in lines if _named_in(str(l.get("part_number") or ""), q)]
        if matches:
            l = matches[0]
            charged = ("£{:.2f}".format(float(l["charged_ext_gbp"]))
                       if _is_number(l.get("charged_ext_gbp")) else "not recorded")
            answer += " {}: {} per finished unit, charged at {}.".format(
                l.get("part_number"), charged, l.get("charged_cell") or "cell not recorded")
        return {"answer": answer, "sources": ["final_estimate.totals", "costed_job.lines"],
                "complete": _is_number(totals.get("unit_gbp"))}
    if any(w in q for w in ("bom", "part", "material", "quantity", "component")):
        if not lines:
            return {"answer": "No charged part list is present in this saved record.",
                    "sources": ["costed_job.lines"], "complete": False}
        shown = lines[:25]
        answer = "; ".join("{} ×{} — {} ({})".format(
            l.get("part_number") or "unnumbered", l.get("qty_per_unit", "?"),
            l.get("description") or "unnamed", l.get("material_label") or "material unstated")
            for l in shown)
        if len(lines) > len(shown):
            answer += "; {} more lines in the saved record".format(len(lines) - len(shown))
        return {"answer": answer, "sources": ["costed_job.lines"], "complete": True}
    if any(w in q for w in ("route", "operation", "process", "weld", "laser", "saw", "glue")):
        if not lines:
            return {"answer": "No route list is present in this saved record.",
                    "sources": ["costed_job.lines"], "complete": False}
        shown = [l for l in lines if l.get("route_operations")][:25]
        answer = "; ".join("{}: {}".format(l.get("part_number") or "unnumbered",
                            ", ".join(map(str, l["route_operations"]))) for l in shown)
        return {"answer": ("Recorded route operations (these may include proposed or uncharged work): "
                           + answer) if answer else "No route operations are recorded.",
                "sources": ["costed_job.lines[*].route_operations"],
                "complete": bool(shown)}
    if any(w in q for w in ("release", "hold", "risk", "missing", "unresolved", "question")):
        release = costed.get("release") or {}
        reasons = release.get("reasons") or []
        answer = "Release status: {}. {}".format(
            release.get("status") or "not recorded",
            "; ".join(map(str, reasons[:15])) or "No release reasons recorded.")
        if len(reasons) > 15:
            answer += " {} more reasons in the saved record.".format(len(reasons) - 15)
        return {"answer": answer, "sources": ["costed_job.release"],
                "complete": bool(release)}
    return {"answer": "I cannot establish that from this saved record. Ask about its "
            "costs, BOM, routes or release checks, or open the source report. "
            "This evidence lookup does not perform a new drawing read.",
            "sources": [], "complete": False}
