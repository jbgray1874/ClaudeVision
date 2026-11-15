"""The drawings an estimate was built from, and the ones we believe are missing (JG, 15 Nov
2026).

"yes, we identify the drawings used in the estimate and we make a statement about what we
think are drawings that are missing and would have helped the estimate." ... "both runners also
need to display the drawings used and a list of drawings that ideally we have that are missing
also in the email. html and the e-mail that is produced."

ONE STATEMENT, READ FROM THE RUN'S OWN RECORD. `statement(record)` is built from the saved
record alone, never from a runner's state, so the report page, the covering e-mail, either
runner and a reprint a month later all say the same thing.

  used      every file the run read, with what read it and what it gave: the rows of the
            report's own table (job_report_html.files_read_rows).
  not_read  files that were in the pack and that nothing read. They are named, not counted
            as used and not called missing: the drawing was supplied.
  missing   what we believe is missing and would have helped, each with the reason:
              * a line on the parts list that names a drawing the pack does not hold, and
                nothing costed (costed_facts.undrawn_bom_lines);
              * the same, where the line is charged from something other than its own sheet
                (costed_facts.priced_without_a_drawing);
              * a made part, named by a drawing number, that the estimate prices and that has
                no detail sheet of its own: bound only to a parts list page
                (part_index's `bound_to_parts_list_page`), or to no page at all, and with no
                flat pattern. What is known of it comes from the model or from another sheet.
            A bought-in item needs no drawing and is never listed.

Nothing believed missing is said in words. The heading is never left empty.
"""
from __future__ import annotations

import html as _html
from typing import Any, Dict, List

SCHEMA = "drawings_statement.v1"
NONE_MISSING = ("Nothing is believed missing: every made part priced here has a detail sheet or "
                "a flat pattern of its own in the pack.")
NOT_RECORDED = ("The run did not record which files it read, so they cannot be listed here.")


def _e(text: Any) -> str:
    return _html.escape(str(text if text is not None else ""))


def _bought_in(part: Dict[str, Any]) -> bool:
    roles = [str(r).lower() for r in (part.get("page_roles") or [])]
    src = str(part.get("source") or "").lower()
    return bool(part.get("is_bought_in")) or ("bought_in" in roles and "detail" not in roles) \
        or "bom_row" in src or src.startswith(("sdi_bom_code", "prose_recogniser", "llm_note_scan"))


def _has_own_drawing(part: Dict[str, Any]) -> bool:
    """A detail sheet bound to the part, or a flat pattern of it. A parts list page that
    lists the part is not a drawing of it."""
    if str(part.get("dxf_source_file") or "").strip():
        return True
    return bool(part.get("pages")) and not part.get("bound_to_parts_list_page")


def _from_the_model(part: Dict[str, Any]) -> bool:
    native = part.get("solidworks_native")
    return bool(native) and not (isinstance(native, dict) and native.get("found") is False)


def _names_a_drawing(pn: str) -> bool:
    try:
        from part_code_conventions import looks_like_a_drawing_number
        return bool(looks_like_a_drawing_number(pn))
    except Exception:                                                # noqa: BLE001
        return False


def _priced(record: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    es = record.get("estimate_summary") if isinstance(record.get("estimate_summary"), dict) else {}
    return {str(p.get("part_number") or "").upper(): p
            for p in (es.get("part_estimates") or record.get("part_estimates") or [])
            if isinstance(p, dict) and p.get("part_number")}


def statement(record: Any) -> Dict[str, Any]:
    """{"schema", "used": [{name, kind, what}], "recorded": bool, "missing": [{part_number,
    description, kind, why}]} from the run's record."""
    out: Dict[str, Any] = {"schema": SCHEMA, "used": [], "not_read": [], "recorded": False,
                           "missing": []}
    if not isinstance(record, dict):
        return out
    try:
        from job_report_html import files_read_rows
        seen = set()
        for name, kind, what in files_read_rows(record)["rows"]:
            key = (str(name).lower(), kind)
            if key in seen:
                continue
            seen.add(key)
            row = {"name": str(name), "kind": kind, "what": what}
            out["not_read" if "NOT READ" in str(what) else "used"].append(row)
    except Exception:                                                # noqa: BLE001
        pass
    out["recorded"] = bool(out["used"] or out["not_read"])

    listed = {m["part_number"].upper() for m in out["missing"]}
    try:
        from costed_facts import priced_without_a_drawing, undrawn_bom_lines
        for m in undrawn_bom_lines(record) or []:
            pn = str(m.get("part_number") or "")
            if pn and pn.upper() not in listed:
                listed.add(pn.upper())
                out["missing"].append({
                    "part_number": pn, "description": str(m.get("description") or ""),
                    "kind": "named_not_supplied",
                    "why": "named on the parts list; no drawing of it is in the pack, so "
                           "nothing read it and nothing is charged for it"})
        for m in priced_without_a_drawing(record) or []:
            pn = str(m.get("part_number") or "")
            if pn and pn.upper() not in listed:
                listed.add(pn.upper())
                out["missing"].append({
                    "part_number": pn, "description": str(m.get("description") or ""),
                    "kind": "priced_without_its_drawing",
                    "why": f"named on the parts list with no drawing of its own; it is charged "
                           f"from {m.get('basis') or 'another source'}, not from its drawing"})
    except Exception:                                                # noqa: BLE001
        pass

    priced = _priced(record)
    for part in record.get("parts") or []:
        if not isinstance(part, dict):
            continue
        pn = str(part.get("part_number") or "").strip()
        if not pn or pn.upper() in listed or _bought_in(part) or _has_own_drawing(part):
            continue
        if str(part.get("canonical_kind") or "").lower() == "bought_in" or not _names_a_drawing(pn):
            continue
        if priced and pn.upper() not in priced:
            continue                                     # not a line of this estimate
        _page = part.get("bound_to_parts_list_page")
        _asm = (part.get("is_assembly_parent") or part.get("assembly_candidate")
                or str(part.get("canonical_kind") or "").lower() == "assembly")
        if _asm and not _page:
            continue             # an assembly the model's tree gave; its members carry the price
        what = ("no detail sheet of its own is in the pack"
                + (f"; the only page that names it is the parts list on page {_page}" if _page else "")
                + ("; its size and material are the model's, with no sheet to check them against"
                   if _from_the_model(part) else
                   "; nothing in the pack measures it")
                + ("; its sheet would state how it is joined" if _asm else ""))
        listed.add(pn.upper())
        out["missing"].append({"part_number": pn, "description": str(part.get("description") or ""),
                               "kind": "no_sheet_of_its_own", "why": what})
    return out


def count_line(st: Dict[str, Any]) -> str:
    """'64 files were read for this estimate: 13 PDF, 15 DXF, 36 MODEL.' '' when not recorded."""
    used = st.get("used") or []
    if not used:
        return ""
    kinds: Dict[str, int] = {}
    for u in used:
        kinds[str(u.get("kind") or "file")] = kinds.get(str(u.get("kind") or "file"), 0) + 1
    n = len(used)
    return (f"{n} file{'' if n == 1 else 's'} {'was' if n == 1 else 'were'} read for this estimate: "
            + ", ".join(f"{c} {k}" for k, c in kinds.items()) + ".")


def used_html(st: Dict[str, Any]) -> str:
    if not st.get("used"):
        return f"<p>{_e(NOT_RECORDED)}</p>"
    rows = "".join(f"<li><code>{_e(u['name'])}</code> ({_e(u['kind'])}): {_e(u['what'])}</li>"
                   for u in st["used"])
    return f"<ul>{rows}</ul>"


def not_read_html(st: Dict[str, Any]) -> str:
    rows = st.get("not_read") or []
    if not rows:
        return ""
    return ("<p><b>In the pack and not read</b></p>"
            f"<p>{len(rows)} file{'' if len(rows) == 1 else 's'} supplied in a format the run "
            "does not read. They added nothing to the estimate.</p><ul>"
            + "".join(f"<li><code>{_e(u['name'])}</code></li>" for u in rows) + "</ul>")


def missing_html(st: Dict[str, Any]) -> str:
    """The believed-missing block on its own, for a page that already lists the files used."""
    missing = st.get("missing") or []
    head = "<p><b>Drawings we believe are missing and would have helped</b></p>"
    if not missing:
        return head + f"<p>{_e(NONE_MISSING)}</p>"
    rows = "".join(
        f"<li><b>{_e(m['part_number'])}</b>"
        + (f" {_e(m['description'])}" if m.get("description") else "")
        + f": {_e(m['why'])}.</li>" for m in missing)
    return (head + f"<p>{len(missing)} listed. Each is a drawing, flat or model we did not have. "
            "With it, the line would be measured, not inferred.</p>" + f"<ul>{rows}</ul>")


def html(st: Dict[str, Any], heading: str = "h3") -> str:
    """Both halves under one heading, for the covering e-mail."""
    return (f"<{heading}>Drawings used, and drawings believed missing</{heading}>"
            "<p><b>Drawings used in this estimate</b></p>"
            + (f"<p>{_e(count_line(st))}</p>" if count_line(st) else "") + used_html(st)
            + not_read_html(st) + missing_html(st))


def text(st: Dict[str, Any]) -> str:
    lines: List[str] = ["DRAWINGS USED IN THIS ESTIMATE"]
    if count_line(st):
        lines.append(count_line(st))
    lines += [f"- {u['name']} ({u['kind']}): {u['what']}" for u in st.get("used") or []] \
        or [NOT_RECORDED]
    if st.get("not_read"):
        lines += ["", "IN THE PACK AND NOT READ"] + [f"- {u['name']}" for u in st["not_read"]]
    lines.append("")
    lines.append("DRAWINGS WE BELIEVE ARE MISSING AND WOULD HAVE HELPED")
    lines += [f"- {m['part_number']}" + (f" {m['description']}" if m.get("description") else "")
              + f": {m['why']}." for m in st.get("missing") or []] or [NONE_MISSING]
    return "\n".join(lines)
