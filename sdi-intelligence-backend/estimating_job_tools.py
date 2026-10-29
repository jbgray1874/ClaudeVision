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
# What the scanner shows. Drawings the estimator can run from, plus the notes
# and emails that come with a brief. Anything else is counted, not listed - see
# browse_briefs.
# A "completed AI brief" folder holds the OUTPUT of a finished estimate, not a
# pack of incoming drawings: the record, the report, the client quotation, the
# BOM and routes, the covering email. Listing only drawing types showed one
# file out of eleven and read as an empty job.
SHOWN = (".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw", ".step",
         ".stp", ".txt", ".msg", ".eml", ".xlsx", ".xls", ".csv",
         ".docx", ".doc", ".html", ".htm", ".json",
         ".png", ".jpg", ".jpeg")

BRIEFS_ROOT = Path(os.getenv(
    "SDI_COMPLETED_AI_BRIEFS_ROOT",
    r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Live Enquiries\completed AI briefs",
))

# ── TWO AREAS, BECAUSE AN ESTIMATOR ASKS TWO DIFFERENT QUESTIONS ──────────────
# "What did we quote for this?" and "what has come in to be priced?" are not the
# same question and do not live in the same folder. Completed AI briefs holds
# what a finished estimate PRODUCED - the record, the report, the quotation - and
# has no drawings in it at all. Live Enquiry holds the drawing packs waiting to
# be run. One scanner over one root could only ever answer one of them, and
# answered the other by showing an empty folder.
LIVE_ENQUIRY_ROOT = Path(os.getenv(
    "SDI_LIVE_ENQUIRY_ROOT",
    r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry",
))


def areas() -> dict:
    """The approved trees, by the name the page asks for them with."""
    return {"briefs": BRIEFS_ROOT, "enquiries": LIVE_ENQUIRY_ROOT}


def area_root(area: str) -> Path:
    found = areas().get(str(area or "briefs"))
    if found is None:
        raise ValueError("Unknown area. The scanner browses the completed "
                         "estimates and the live enquiries, and nothing else.")
    return found


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


def browse_briefs(relative: str = "", area: str = "briefs") -> dict[str, Any]:
    """List one level of one approved area; never an absolute path from a caller."""
    chosen = area_root(area)
    if len(relative) > 512:
        raise ValueError("Folder path is too long.")
    segments = relative.split("/") if relative else []
    if any(not s or s in (".", "..") or "\\" in s or ":" in s
           or any(ord(c) < 32 for c in s) for s in segments):
        raise ValueError("Invalid folder path.")
    root = chosen.resolve(strict=True)
    try:
        target = root.joinpath(*segments).resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("Folder not found in the approved briefs area.") from exc
    if target != root and root not in target.parents:
        raise ValueError("Folder is outside the approved briefs area.")
    if not target.is_dir():
        raise ValueError("Not a folder.")
    # ── "0 items" HAS THREE MEANINGS, AND ONLY ONE OF THEM IS "EMPTY" ─────────
    # A child is skipped silently when its type is not on the list below, and
    # again when it cannot be read at all - a permission, a broken shortcut, a
    # file that has gone. All three looked identical on the screen: a job
    # folder full of spreadsheets and one full of files the service account
    # cannot open both said "0 items". They are counted and reported, because
    # "empty" and "you cannot see this" need different people to fix them.
    rows, other_types, unreadable = [], 0, 0
    for child in target.iterdir():
        if child.name.startswith("."):
            continue
        try:
            resolved = child.resolve(strict=True)
            if root not in resolved.parents:
                continue
            is_dir = child.is_dir()
            if not is_dir and child.suffix.lower() not in SHOWN:
                other_types += 1
                continue
            rows.append({"name": child.name,
                         "relative": "/".join(segments + [child.name]),
                         "is_dir": is_dir,
                         "kind": "folder" if is_dir else "file",
                         "size": None if is_dir else child.stat().st_size})
        except (OSError, ValueError):
            unreadable += 1
            continue
    rows.sort(key=lambda r: (r["kind"] != "folder", r["name"].casefold()))
    # What can actually be ESTIMATED from. Narrower than what is shown: a
    # spreadsheet beside a drawing is worth seeing and is not a drawing.
    drawing_names = [r["name"] for r in rows if r["kind"] == "file" and
                     Path(r["name"]).suffix.lower() in (
                         ".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw")]
    can_select = len(segments) >= 2 and bool(drawing_names)
    return {"area": area, "relative": relative, "parent": "/".join(segments[:-1]),
            "folder_path": str(target), "folder_name": target.name,
            "entries": rows[:300], "truncated": len(rows) > 300,
            "can_select": can_select, "drawing_count": len(drawing_names),
            "other_types": other_types, "unreadable": unreadable}


def _segments(relative: str) -> list[str]:
    """The same path rule browse_briefs uses, so one place decides what a
    caller may name: folder names only, never an absolute path, never "..".
    """
    if len(relative or "") > 512:
        raise ValueError("Folder path is too long.")
    found = relative.split("/") if relative else []
    if any(not s or s in (".", "..") or "\\" in s or ":" in s
           or any(ord(c) < 32 for c in s) for s in found):
        raise ValueError("Invalid folder path.")
    return found


MAX_RECORD_BYTES = 30_000_000


def filed_record(relative: str, area: str = "briefs") -> dict[str, Any]:
    """The saved estimate record inside one filed brief folder.

    ── WHY THIS EXISTS AT ALL ────────────────────────────────────────────────
    The questions endpoint answered only from runs the service still held in
    memory, so everything from before the last restart replied "Run not found.
    The service may have restarted." Standing in front of a customer asking
    what we quoted for a job last month, that is the whole feature failing.

    The record is on the share, in the brief folder, and is the same shape the
    in-memory path reads. So it is read from there, confined to the approved
    areas by the same rule that confines browsing, and nothing else about the
    answer changes.
    """
    root = area_root(area).resolve(strict=True)
    parts = _segments(relative)
    if not parts:
        raise ValueError("Name the job folder to ask about.")
    try:
        folder = root.joinpath(*parts).resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("That job folder is not in the approved area.") from exc
    if folder != root and root not in folder.parents:
        raise ValueError("That job folder is outside the approved area.")
    if not folder.is_dir():
        raise ValueError("That is a file, not a job folder.")

    # The folder itself, then one level down - a brief is sometimes filed with
    # its record in a subfolder. Deeper than that is a different job.
    found: list[Path] = []
    for depth in (folder.glob("*_record.json"), folder.glob("*/*_record.json")):
        found.extend(p for p in depth if p.is_file())
        if found:
            break
    if not found:
        raise ValueError("No saved estimate record is filed in that folder, so "
                         "there is nothing to answer from. Open its report instead.")
    if len(found) > 1:
        raise ValueError(f"{len(found)} saved records are filed in that folder, so "
                         f"it is not clear which job is being asked about.")
    record_path = found[0].resolve(strict=True)
    if root not in record_path.parents:
        raise ValueError("That record is outside the approved area.")
    if record_path.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError("That saved record is too large to read here.")
    import json
    with record_path.open("r", encoding="utf-8") as stream:
        record = json.load(stream)
    if not isinstance(record, dict):
        raise ValueError("That saved record is not in the expected shape.")
    return {"record": record, "record_name": record_path.name,
            "folder_name": folder.name, "relative": relative, "area": area}


def answer_saved_record(record: dict[str, Any], question: str) -> dict[str, Any]:
    """Answer only from the supplied run record; never invent a cost or drawing fact."""
    q = " ".join(question.split()).lower()
    if not q or len(q) > 500:
        raise ValueError("Ask a question of up to 500 characters.")
    final = record.get("final_estimate") or {}
    costed = record.get("costed_job") or {}
    lines = costed.get("lines") or []
    # ── THE WORDS ESTIMATORS ACTUALLY USE ────────────────────────────────────
    # The list was price/cost/total/amount/charge, and "what did this come out
    # at?" - the first thing anybody types, and one of the four prompts the
    # pocket page offers - matched none of them and fell through to "I cannot
    # establish that". A bounded tool that refuses the plainest form of the
    # question it exists to answer reads as broken rather than careful.
    if any(w in q for w in ("price", "cost", "total", "amount", "charge",
                            "come out at", "came out at", "how much", "quote",
                            "quoted", "£")):
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
    # "held" is not "hold", and "anything held?" is how the question gets asked
    # out loud. Same fault as the price words, found by the same test.
    if any(w in q for w in ("release", "hold", "held", "risk", "missing",
                            "unresolved", "question", "blocked", "outstanding")):
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
