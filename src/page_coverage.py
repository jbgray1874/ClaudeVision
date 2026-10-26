"""Every page of every document, what read it, and what nothing read (D-597).

"Pages sent" is not "pages read". The concept read sends every page's text and image; the
whole-pack read now takes every PDF of the job in whole-page batches; and until this record
nothing said, page by page, which read had which page, whether its text went whole, how fine
its image was, or which page no LLM read at all. On a normal drawing job a page with no text
layer is seen only by the page-image BOM reader, which looks for parts tables and nothing else:
its notes reach no reading. That is a gap, and it is named.

    summary["page_coverage"] = {
        "pages": [{document, page, paper, size_pt, text_chars, has_text,
                   whole_pack_read, concept_text, concept_image, text_processed,
                   content_read, content_read_by, gaps}],
        "content_not_read": ["<document> page <n>"],
        "gaps":  [{document, page, kind, detail}],
        "readers": {"whole_pack": bool, "concept": bool}}

Gap kinds: `text_not_read` (no reading of any kind took its text), `text_llm_read_failed` (the
rule-based readers read it and the whole-pack LLM read did not return it), `text_not_sent` (the
concept read could not send the page's text whole), `image_only` (no text layer and no LLM read
took its image), `image_coarse` (its image went at a resolution where small notes are at risk),
`document_unread`, `image_response_unverified`, `image_detail_unknown`. EVIDENCE, NOT A READER
(review of D-598): a page the rule-based readers read for its text is read; a normal pack fully
read by them is not held because no LLM ran. invariants.check_every_page_reached_a_read raises
them.

TEXT PROCESSED IS NOT CONTENT READ (D-598f). `text_processed` says the page's text layer was
extracted and counted; `content_read` says some reading took what the page carries: its text,
where it has any, or its image, by an LLM read that answered. 0320730's drawing page had no text
layer, went through the whole-pack text read, and was marked read; nothing had read it.

Read-only: nothing here reads a document, calls a model, or changes a record but its own.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

SCHEMA = "page_coverage.v1"

# ISO A sizes in points, portrait (short side, long side).
_PAPER_PT = (("A4", 595.0, 842.0), ("A3", 842.0, 1191.0), ("A2", 1191.0, 1684.0),
             ("A1", 1684.0, 2384.0), ("A0", 2384.0, 3370.0))


def _cfg(name: str, default: Any) -> Any:
    try:
        import config                                               # noqa: WPS433
        return getattr(config, name, default)
    except Exception:                                                # noqa: BLE001
        return default


def paper(width_pt: Any, height_pt: Any) -> str:
    """The A size a page is printed at, by its own dimensions, or its size in mm."""
    try:
        short, long_ = sorted((float(width_pt), float(height_pt)))
    except (TypeError, ValueError):
        return ""
    for name, s, l in _PAPER_PT:
        if abs(short - s) <= s * 0.04 and abs(long_ - l) <= l * 0.04:
            return name
    return f"{round(short / 72 * 25.4)} x {round(long_ / 72 * 25.4)} mm"


def effective_dpi(px: Any, width_pt: Any, height_pt: Any) -> Optional[int]:
    """The resolution a rendered page image gives the printed page, on its long side."""
    try:
        short_px, long_px = sorted((int(px[0]), int(px[1])))
        short_pt, long_pt = sorted((float(width_pt), float(height_pt)))
    except (TypeError, ValueError, IndexError):
        return None
    if min(short_px, long_px, short_pt, long_pt) <= 0:
        return None
    return int(round(min(short_px / (short_pt / 72.0), long_px / (long_pt / 72.0))))


def build(summary: Mapping[str, Any], pages: Optional[List[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """The coverage record from what the run kept: the whole-pack read's coverage, the concept
    read's pages and text coverage. `pages` (document, page, chars, has_text, width_pt,
    height_pt) defaults to the whole-pack read's own page list."""
    wp = summary.get("llm_full_extract_coverage") if isinstance(summary.get("llm_full_extract_coverage"), Mapping) else {}
    concept = summary.get("concept_read") if isinstance(summary.get("concept_read"), Mapping) else {}
    inventory = list(pages if pages is not None else (wp.get("pages") or []))
    page_list = [p for p in inventory
                 if isinstance(p, Mapping) and p.get("page") is not None]
    wp_ran = bool(wp.get("batches"))
    rendered = {(str(r.get("document")), int(r.get("page"))): r.get("px")
                for r in (concept.get("pages_rendered") or []) if isinstance(r, Mapping)}
    # Rendering is preparation, not a successful answer. Retained raw response is the
    # current adapter's receipt; it proves response availability, not semantic completeness.
    concept_ran = bool(rendered) and bool(concept.get("raw_response")) and not (
        concept.get("error") or concept.get("refused"))
    tc = concept.get("text_coverage") if isinstance(concept.get("text_coverage"), Mapping) else {}
    not_sent = {str(x) for x in (tc.get("omitted_pages") or [])} | {
        str(x) for x in (tc.get("cut_pages") or [])}
    min_dpi = int(_cfg("PAGE_IMAGE_MIN_DPI", 150) or 150)
    wp_pages = {(str(p.get("document")), p.get("page")): p for p in (wp.get("pages") or [])
                if isinstance(p, Mapping)}
    # THE RULE-BASED READERS' OWN RECEIPT (review of D-598): each page the scan read for its
    # text, title block and patterns, by document and page. Coverage measures the evidence a
    # page reached, not which reader gave it.
    rule_read = set()
    for sp in (summary.get("pages") or []):
        if not isinstance(sp, Mapping) or not str(sp.get("pdfplumber_text")
                                                  or sp.get("normalized_text") or "").strip():
            continue
        try:
            rule_read.add((Path(str(sp.get("source_pdf_path") or "")).name,
                           int(sp.get("page_number"))))
        except (TypeError, ValueError):
            continue
    entries: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []
    for p in inventory:
        if isinstance(p, Mapping) and p.get("page") is None:
            gaps.append({"document": str(p.get("document") or p.get("path") or "unknown"),
                         "page": None, "kind": "document_unread",
                         "detail": str(p.get("error") or "document has no page inventory")})
    if not inventory:
        gaps.append({"document": "", "page": None, "kind": "inventory_missing",
                     "detail": "No page inventory; completeness cannot be checked."})
    for p in page_list:
        doc, num = str(p.get("document")), int(p.get("page"))
        has_text = bool(p.get("has_text"))
        entry: Dict[str, Any] = {
            "document": doc, "page": num,
            "paper": paper(p.get("width_pt"), p.get("height_pt")),
            "size_pt": [p.get("width_pt"), p.get("height_pt")],
            "text_chars": p.get("chars"), "has_text": has_text,
            "whole_pack_read": None, "concept_text": None, "concept_image": None,
            "rule_based_text": "read" if (doc, num) in rule_read else None, "gaps": []}

        def gap(kind: str, detail: str) -> None:
            entry["gaps"].append({"kind": kind, "detail": detail})
            gaps.append({"document": doc, "page": num, "kind": kind, "detail": detail})

        if wp_ran:
            w = wp_pages.get((doc, num)) or {}
            entry["whole_pack_read"] = {"batches": w.get("batches") or [],
                                        "read": bool(w.get("read"))}
            if has_text and not w.get("read"):
                if (doc, num) in rule_read:
                    gap("text_llm_read_failed", "its text reached the rule-based readers, and "
                                                "the whole-pack LLM read did not return it — "
                                                "what the rules do not look for went unread")
                else:
                    gap("text_not_read", "its text is in a part of the pack the whole-pack read "
                                         "did not return, and no other reading took it")
        if concept_ran:
            label = f"{doc}, page {num}"
            if has_text and (doc, num) in rendered:
                entry["concept_text"] = "not sent" if label in not_sent else "sent whole"
                if label in not_sent:
                    gap("text_not_sent", "its text did not go to the concept read whole — read "
                                         "from its image only")
            px = rendered.get((doc, num))
            if px:
                dpi = effective_dpi(px, p.get("width_pt"), p.get("height_pt"))
                entry["concept_image"] = {"px": px, "dpi": dpi}
                if dpi is not None and dpi < min_dpi:
                    gap("image_coarse", f"its image went at about {dpi} dpi on the printed "
                                        f"page — small notes and dimensions are at risk")
        if not has_text and not entry["concept_image"]:
            gap("image_only", "no text layer, and no LLM read took its image — its notes and "
                              "lettering reached no reading (the page-image BOM reader looks "
                              "for parts tables only)")
        if (has_text and not entry["concept_text"] and (doc, num) not in rule_read
                and not (wp_pages.get((doc, num)) or {}).get("read")):
            if not any(g["kind"] == "text_not_read" for g in entry["gaps"]):
                gap("text_not_read", "no reading of any kind took this page's text")
        if (doc, num) in rendered and not concept_ran:
            gap("image_response_unverified", "Page rendered, but no successful concept response retained")
        if entry["concept_image"] and entry["concept_image"]["dpi"] is None:
            gap("image_detail_unknown", "Image resolution cannot be checked against page dimensions")
        by: List[str] = []
        if has_text and (doc, num) in rule_read:
            by.append("rule-based text")
        if has_text and (wp_pages.get((doc, num)) or {}).get("read"):
            by.append("whole-pack LLM text")
        if has_text and entry["concept_text"] == "sent whole":
            by.append("concept read text")
        if entry["concept_image"] and concept_ran:
            by.append("concept read image")
        entry["text_processed"] = p.get("chars") is not None and not p.get("error")
        entry["content_read"] = bool(by)
        entry["content_read_by"] = by
        entries.append(entry)
    return {"schema": SCHEMA, "pages": entries, "gaps": gaps,
            "documents": sorted({e["document"] for e in entries}),
            "pages_text_processed": sum(1 for e in entries if e["text_processed"]),
            "pages_content_read": sum(1 for e in entries if e["content_read"]),
            "content_not_read": [f"{e['document']} page {e['page']}" for e in entries
                                 if not e["content_read"]],
            "readers": {"whole_pack": wp_ran, "concept": concept_ran},
            # NO LLM READING AT ALL IS SAID, not reported as every page read: the rule-based
            # readers saw these pages, and nothing read their notes (an offline or keyless run).
            "llm_read": wp_ran or concept_ran,
            "whole_pack_batches": len(wp.get("batches") or []),
            "min_dpi": min_dpi}
