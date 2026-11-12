from typing import Any, Dict, List


def build_document_validation(summary: Dict[str, Any], parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    if not parts:
        issues.append({"severity": "error", "code": "no_parts_extracted", "reason": "No manufacturable parts were extracted from the document."})

    assembly_pages = [page for page in summary["pages"] if page.get("page_role", {}).get("primary_role") == "assembly"]
    detail_pages = [page for page in summary["pages"] if page.get("page_role", {}).get("primary_role") == "detail"]
    if detail_pages and not parts:
        issues.append({"severity": "error", "code": "detail_pages_without_parts", "reason": "Detail pages were detected but no part records were created."})

    for part in parts:
        if len(part.get("materials", [])) > 2:
            issues.append({"severity": "warning", "code": "mixed_materials", "part_number": part.get("part_number"), "reason": "Part accumulated multiple materials, suggesting assembly contamination."})
        if len(part.get("surface_finishes", [])) > 2:
            issues.append({"severity": "warning", "code": "mixed_finishes", "part_number": part.get("part_number"), "reason": "Part accumulated multiple finishes, suggesting assembly contamination."})
        if part.get("page_roles") and "assembly" in part.get("page_roles", []) and "detail" not in part.get("page_roles", []):
            issues.append({"severity": "info", "code": "assembly_only_part_record", "part_number": part.get("part_number"), "reason": "Part record is derived from assembly pages only."})
        if not part.get("normalized_material") and part.get("manufacturing_features", {}).get("laser_required"):
            issues.append({"severity": "warning", "code": "missing_material_for_fabrication", "part_number": part.get("part_number"), "reason": "Fabrication cues exist but no reliable material was extracted."})

    status = "ok_for_pricing"
    if any(issue["severity"] == "error" for issue in issues):
        status = "failed_part_extraction"
    elif any(issue["severity"] == "warning" for issue in issues):
        status = "needs_review"

    return {
        "status": status,
        "issue_count": len(issues),
        "issues": issues,
        "page_role_breakdown": {
            "assembly_pages": len(assembly_pages),
            "detail_pages": len(detail_pages),
            "total_pages": len(summary["pages"]),
        },
    }
