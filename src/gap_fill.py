"""Targeted model help for the gaps the deterministic read left, one gap at a time (SCRUM-194,
requirement 3; JG, 9 Nov 2026: "deterministic first, targeted assistance next, reasonable priced
inference where needed, and no silent omissions").

The deterministic reader comes first and its findings stand. Once the build is done, each made
part is checked for the facts costing cannot do without: a material, a gauge or a section, a
size (a blank, or a section length), a quantity. For each gap the model is shown ONLY that
part's own pages and its parts-list row, asked one narrow question, and answered in JSON. The
answer is checked against what is already established before it is used:

    a thickness must agree with the title block's gauge where the sheet prints one;
    a blank must be at least as large as the part's own feature spread (hole pitches);
    a figure must be positive, in millimetres, and name the page it was read from.

An answer that passes is written through source_precedence as `llm_assisted`, ranked below every
deterministic reading of the sheet and above the whole-pack read and every inference, so the
model fills a gap and never displaces a reading. Every ask is recorded on the run, asked or not:

    summary["gap_fill"] = {"items": [{part, gap, pages, question, answer, validation, effect}]}

A deterministic-only run never asks and records each gap as "not asked: deterministic-only".
Without a key, likewise. A gap the model could not fill stays a gap, named, for the costing
stage's provisional allowance or the release hold, never dropped. An LLM recovery does not make
the deterministic reading test pass: that test reads the record's `*_source` fields and this
module writes `llm_assisted`.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Mapping, Optional

SOURCE = "llm_assisted"
SCHEMA = "gap_fill.v1"
GAPS = ("material", "thickness_or_section", "size", "quantity")

_SYSTEM = ("You read one engineering drawing sheet for one named part and answer one question in JSON. "
           "Never invent: if the sheet does not print the figure, answer null and say so. Name the page "
           "and quote the words you read.")

_QUESTION = {
    "material": "What material does this part's own sheet state for it (the title block's MATERIALS field "
                "or a note)? Answer {\"material\": <text or null>, \"page\": <n>, \"words\": <quoted>}.",
    "thickness_or_section": "What gauge (sheet thickness in mm) or hollow-section profile (A x B x T mm) does "
                            "this part's own sheet state? Answer {\"thickness_mm\": <number or null>, "
                            "\"section_mm\": [A, B, T] or null, \"page\": <n>, \"words\": <quoted>}.",
    "size": "What are this part's overall finished dimensions as printed on its own sheet (its flat blank "
            "length and width for a sheet part, or its cut length for a section)? Answer "
            "{\"length_mm\": <number or null>, \"width_mm\": <number or null>, \"page\": <n>, \"words\": <quoted>}.",
    "quantity": "How many of this part does the parts list call for per unit? Answer "
                "{\"quantity\": <integer or null>, \"page\": <n>, \"words\": <quoted>}.",
}


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f and f > 0 else None
    except (TypeError, ValueError):
        return None


def _own_pages(part: Mapping[str, Any]) -> List[int]:
    return [p for p in (part.get("pages") or []) if isinstance(p, int)
            and p != part.get("bound_to_parts_list_page")]


def gaps_of(part: Mapping[str, Any]) -> List[str]:
    """Which costing-critical facts this made part lacks."""
    out: List[str] = []
    ss = part.get("section_stock") if isinstance(part.get("section_stock"), Mapping) else {}
    if not [m for m in (part.get("materials") or []) if m]:
        out.append("material")
    if _num(part.get("normalized_thickness_mm")) is None and not ss.get("a"):
        out.append("thickness_or_section")
    if ss.get("a"):
        if _num(ss.get("length_mm")) is None and not ss.get("cut_lengths_mm"):
            out.append("size")
    elif _num(part.get("blank_length_mm")) is None or _num(part.get("blank_width_mm")) is None:
        out.append("size")
    if _num(part.get("quantity")) is None:
        out.append("quantity")
    return out


def _made(part: Mapping[str, Any]) -> bool:
    if not part.get("part_number") or part.get("is_assembly_parent"):
        return False
    try:
        from bought_in_policy import is_bought_in
        if is_bought_in(dict(part)):
            return False
    except Exception:                                                # noqa: BLE001
        if part.get("is_bought_in") or "bought_in" in (part.get("page_roles") or []):
            return False
    return bool(_own_pages(part) or part.get("materials") or part.get("section_stock"))


def _page_text(summary: Mapping[str, Any], pno: int) -> str:
    for p in summary.get("pages") or []:
        if isinstance(p, Mapping) and p.get("page_number") == pno:
            for k in ("pdfplumber_text", "normalized_text", "pypdf_text"):
                if p.get(k) and str(p[k]).strip():
                    return str(p[k])
    return ""


def _row_text(summary: Mapping[str, Any], pn: str) -> str:
    da = summary.get("document_analysis") if isinstance(summary.get("document_analysis"), Mapping) else {}
    for row in (da.get("bom_rows") or []):
        if isinstance(row, Mapping) and " ".join(str(row.get("part_number") or "").split()).upper() == pn:
            return json.dumps({k: row.get(k) for k in ("part_number", "description", "quantity") if row.get(k) is not None})
    return ""


def validate(gap: str, answer: Mapping[str, Any], part: Mapping[str, Any]) -> Dict[str, Any]:
    """{ok, why, value} — the answer held against what the deterministic read established."""
    pages = set(_own_pages(part)) | ({part["bound_to_parts_list_page"]} if part.get("bound_to_parts_list_page") else set())
    page = answer.get("page")
    if not answer.get("words"):
        return {"ok": False, "why": "no words quoted from the sheet"}
    if pages and page not in pages:
        return {"ok": False, "why": f"page {page} is not one of the part's own pages {sorted(pages)}"}
    tbm = part.get("title_block_material") if isinstance(part.get("title_block_material"), Mapping) else {}
    if gap == "material":
        mat = str(answer.get("material") or "").strip().upper()
        if not mat:
            return {"ok": False, "why": "the model found no material"}
        if tbm.get("material") and re.sub(r"[^A-Z]", "", tbm["material"]) != re.sub(r"[^A-Z]", "", mat):
            return {"ok": False, "why": f"disagrees with the title block's {tbm['material']}"}
        return {"ok": True, "value": mat}
    if gap == "thickness_or_section":
        sec = answer.get("section_mm")
        if isinstance(sec, list) and len(sec) == 3 and all(_num(v) for v in sec):
            return {"ok": True, "value": {"section_mm": [float(v) for v in sec]}}
        t = _num(answer.get("thickness_mm"))
        if t is None:
            return {"ok": False, "why": "the model found no gauge or section"}
        if tbm.get("thickness_mm") and abs(float(tbm["thickness_mm"]) - t) > 0.05:
            return {"ok": False, "why": f"disagrees with the title block's {tbm['thickness_mm']} mm"}
        if t > 50:
            return {"ok": False, "why": f"{t} mm is not a sheet gauge"}
        return {"ok": True, "value": {"thickness_mm": t}}
    if gap == "size":
        length, width = _num(answer.get("length_mm")), _num(answer.get("width_mm"))
        ss = part.get("section_stock") if isinstance(part.get("section_stock"), Mapping) else {}
        if length is None:
            return {"ok": False, "why": "the model found no length"}
        if ss.get("a"):
            if length < 2 * max(float(ss.get("a") or 0), float(ss.get("b") or 0)):
                return {"ok": False, "why": "shorter than twice the section's side"}
            return {"ok": True, "value": {"length_mm": length}}
        if width is None:
            return {"ok": False, "why": "the model found no width for a sheet part"}
        spread = max([_num(v) for v in (part.get("pitch_values_mm") or []) if _num(v)] or [0])
        if spread and max(length, width) < spread:
            return {"ok": False, "why": f"smaller than the part's own feature spread {spread:g} mm"}
        return {"ok": True, "value": {"length_mm": max(length, width), "width_mm": min(length, width)}}
    if gap == "quantity":
        q = _num(answer.get("quantity"))
        if q is None or q != int(q):
            return {"ok": False, "why": "the model found no whole-number quantity"}
        return {"ok": True, "value": int(q)}
    return {"ok": False, "why": f"no rule for {gap}"}


def apply(gap: str, value: Any, part: Dict[str, Any], page: Any, words: Any) -> List[str]:
    """Write a validated answer through source precedence; the fields it set."""
    from source_precedence import apply_field
    done: List[str] = []
    note = f"LLM-assisted from the part's own page {page}: {str(words)[:120]!r}"
    if gap == "material":
        if apply_field(part, "materials", [value], SOURCE, note=note):
            done.append("materials")
    elif gap == "thickness_or_section":
        if "section_mm" in value:
            a, b, t = value["section_mm"]
            for k, v in (("a", a), ("b", b), ("t", t)):
                if apply_field(part, f"section_stock.{k}", v, SOURCE, note=note):
                    done.append(f"section_stock.{k}")
        elif apply_field(part, "normalized_thickness_mm", value["thickness_mm"], SOURCE, note=note):
            done.append("normalized_thickness_mm")
    elif gap == "size":
        ss = part.get("section_stock") if isinstance(part.get("section_stock"), Mapping) else {}
        if ss.get("a"):
            if apply_field(part, "section_stock.length_mm", value["length_mm"], SOURCE, note=note):
                done.append("section_stock.length_mm")
        else:
            for k in ("length_mm", "width_mm"):
                if apply_field(part, f"blank_{k}", value[k], SOURCE, note=note):
                    done.append(f"blank_{k}")
    elif gap == "quantity":
        if apply_field(part, "quantity", value, SOURCE, note=note):
            done.append("quantity")
    if done:
        part.setdefault("review_flags", []).append(
            f"{gap} filled with the model's help from page {page} ({str(words)[:60]!r}); checked against "
            f"the sheet's own readings; source llm_assisted")
    return done


def enabled(summary: Mapping[str, Any]) -> Optional[str]:
    """None when asking is allowed, else why not."""
    if summary.get("deterministic_only") or os.getenv("SDI_DETERMINISTIC_ONLY", "").strip() == "1":
        return "deterministic-only run"
    if os.getenv("SDI_LLM_GAP_FILL", "1").strip().lower() in ("0", "false", "no", "off"):
        return "SDI_LLM_GAP_FILL is off"
    if not os.environ.get("XAI_API_KEY"):
        return "no model key on this machine"
    return None


def _default_call(user_content: str) -> Optional[str]:
    from llm_full_extract import _call_llm, DEFAULT_MODEL
    return _call_llm(user_content, DEFAULT_MODEL, system=_SYSTEM)


def run(summary: Dict[str, Any], call: Optional[Callable[[str], Optional[str]]] = None,
        force: bool = False) -> Dict[str, Any]:
    """Find every gap, ask what may be asked, validate, apply, record. Returns the record."""
    parts = ((summary.get("manufacturing_writeup") or {}).get("parts") or [])
    why_not = None if force else enabled(summary)
    items: List[Dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, dict) or not _made(part):
            continue
        pn = " ".join(str(part.get("part_number")).split()).upper()
        for gap in gaps_of(part):
            pages = _own_pages(part)
            item: Dict[str, Any] = {"part": pn, "gap": gap, "pages": pages, "asked": False,
                                    "question": _QUESTION[gap], "answer": None, "validation": None, "effect": []}
            if why_not:
                item["effect"] = [f"not asked: {why_not}; the gap stays open and named"]
                items.append(item)
                continue
            if not pages:
                item["effect"] = ["not asked: the part has no sheet of its own to show"]
                items.append(item)
                continue
            payload = (f"PART: {pn} ({part.get('description') or ''})\nPARTS-LIST ROW: {_row_text(summary, pn)}\n"
                       f"QUESTION: {_QUESTION[gap]}\n" + "".join(
                           f"\n===== PAGE {p} =====\n{_page_text(summary, p)[:12000]}\n" for p in pages))
            item["asked"] = True
            try:
                raw = (call or _default_call)(payload)
            except Exception as exc:                                 # noqa: BLE001
                item["effect"] = [f"the model could not be reached: {type(exc).__name__}: {exc}"]
                items.append(item)
                continue
            try:
                from llm_full_extract import _parse
                answer = _parse(raw or "") or {}
            except Exception:                                        # noqa: BLE001
                answer = {}
            item["answer"] = answer
            v = validate(gap, answer, part) if answer else {"ok": False, "why": "no JSON answer"}
            item["validation"] = v
            if v.get("ok"):
                item["effect"] = apply(gap, v["value"], part, answer.get("page"), answer.get("words")) or [
                    "validated, and a stronger reading already held the field"]
            else:
                item["effect"] = [f"not used: {v.get('why')}; the gap stays open and named"]
            items.append(item)
    rec = {"schema": SCHEMA, "items": items, "asked": sum(1 for i in items if i["asked"]),
           "filled": sum(1 for i in items if i.get("validation", {}) and (i.get("validation") or {}).get("ok")
                         and i["effect"] and not str(i["effect"][0]).startswith("validated, and")),
           "open": [f"{i['part']}: {i['gap']}" for i in items
                    if not ((i.get("validation") or {}).get("ok"))],
           "why_not_asked": why_not}
    summary["gap_fill"] = rec
    return rec
