from typing import Any, Dict, List

from extractor_patterns import build_textual_manufacturing_summary, normalize_text


def _dedupe(values: List[Any]) -> List[Any]:
    seen: List[Any] = []
    for value in values:
        if value not in seen and value not in (None, "", []):
            seen.append(value)
    return seen


def reconcile_page_analysis(page: Dict[str, Any], vision_page: Dict[str, Any] | None = None, llm_page: Dict[str, Any] | None = None) -> Dict[str, Any]:
    base_analysis = page.get("page_analysis", {})
    if not vision_page and not llm_page:
        return base_analysis

    merged_title = normalize_text(f"{page.get('region_text', {}).get('title_block', '')} {(vision_page or {}).get('region_text', {}).get('title_block', '')}")
    merged_bom = normalize_text(f"{page.get('region_text', {}).get('bom', '')} {(vision_page or {}).get('bom_table_text', '')}")
    merged_notes = normalize_text(f"{page.get('region_text', {}).get('notes', '')} {(vision_page or {}).get('region_text', {}).get('notes', '')} {(vision_page or {}).get('revision_table_text', '')}")
    merged_page_text = normalize_text(f"{page.get('pdfplumber_text', '')} {(vision_page or {}).get('ocr_text', '')}")

    reconciled = build_textual_manufacturing_summary(
        merged_page_text,
        title_block_text=merged_title or merged_page_text,
        bom_text=merged_bom,
        notes_text=merged_notes,
        page_role_hint=page.get("page_role", {}).get("primary_role"),
    )

    process_notes = reconciled.get("process_notes", {})
    process_notes["note_snippets"] = _dedupe(process_notes.get("note_snippets", []) + list((vision_page or {}).get("process_callouts", [])))
    process_notes["detected_note_types"] = _dedupe(process_notes.get("detected_note_types", []) + list((vision_page or {}).get("process_callouts", [])))
    reconciled["process_notes"] = process_notes

    if llm_page:
        thickness_override = llm_page.get("thickness_override_mm")
        if thickness_override not in (None, ""):
            reconciled["title_block"].setdefault("thicknesses_mm", [])
            thickness_value = str(thickness_override)
            if thickness_value not in reconciled["title_block"]["thicknesses_mm"]:
                reconciled["title_block"]["thicknesses_mm"].insert(0, thickness_value)
            reconciled["title_block"].setdefault("normalized", {})
            reconciled["title_block"]["normalized"]["primary_thickness_mm"] = thickness_value
            reconciled.setdefault("primary_fields", {})
            reconciled["primary_fields"]["thickness_mm"] = float(thickness_override)
            reconciled["primary_fields"]["normalized_thickness_mm"] = float(thickness_override)

        if llm_page.get("revision_override"):
            reconciled["title_block"]["revisions"] = [str(llm_page["revision_override"])]
            reconciled.setdefault("primary_fields", {})
            reconciled["primary_fields"]["revision"] = str(llm_page["revision_override"])

        reconciled["review_flags"] = _dedupe(reconciled.get("review_flags", []) + llm_page.get("risk_flags", []))

    reconciled["vision_extraction"] = vision_page or {}
    reconciled["llm_reconciliation"] = llm_page or {}
    reconciled["reconciliation_metadata"] = {
        "vision_used": bool(vision_page),
        "llm_used": bool(llm_page),
        "ocr_word_count": (vision_page or {}).get("ocr_word_count", 0),
    }
    return reconciled
