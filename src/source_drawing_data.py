"""Everything the engine read out of every file, one row at a time, in the estimating folder.

WHY THIS EXISTS. "When I open up DXF files they contain only images." That is what the
viewer shows; it is not what the file holds. Every flat export in this corpus is vector
geometry — SDI's own 117620202M is 55 LINEs, 2 CIRCLEs and 2 ARCs across two layers, SLD-0
carrying the profile and BENDLINES carrying the folds. Its blank measures 1009.49 x 363.91
and its holes are Ø5.0, and not one of those figures is a printed dimension: the circle IS
its diameter. The GA export alongside it carries 64 MTEXT and 20 DIMENSION entities, and its
text includes a stated weight of 384g.

So the question that actually matters is not what the files contain. It is which of it we
READ, which part we attached it to, and whether it reached the price. Three different
failures hide in that gap and they look identical from outside:

    the file did not have it          -> nothing anyone can do
    we did not read it                -> a reader to fix
    we read it and dropped it later   -> a pipeline join to fix, and the worst of the three,
                                         because the evidence was in the building

This workbook makes those distinguishable. One row per fact, every file in the pack listed
one after another, with where it came from and where it ended up. It prices nothing and
decides nothing; it is the audit that says which of the three we are looking at, and it is
the thing to read before writing another rule on a guess.

Written to the estimating folder as source_drawing_data.xlsx, per job.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

SHEETS = ("Files", "DXF file vs engine", "Facts", "BOM rows", "Operations", "Not extracted")


def _text(value: Any, limit: int = 300) -> str:
    if value is None:
        return ""
    out = str(value)
    return out if len(out) <= limit else out[: limit - 1] + "…"


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parts(summary: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    for holder in (summary.get("estimate_summary") or {}, summary):
        if isinstance(holder, Mapping):
            for key in ("canonical_part_estimates", "part_estimates"):
                rows = holder.get(key)
                if isinstance(rows, list) and rows:
                    return [r for r in rows if isinstance(r, Mapping)]
    writeup = (summary.get("manufacturing_writeup") or {}).get("parts")
    return [r for r in (writeup or []) if isinstance(r, Mapping)]


def _costed_fields(part: Mapping[str, Any]) -> Dict[str, Any]:
    """The fields that actually move money, so a fact can be marked used or not."""
    material = part.get("material_estimate") if isinstance(
        part.get("material_estimate"), Mapping) else {}
    return {
        "normalized_material": part.get("normalized_material"),
        "normalized_thickness_mm": part.get("normalized_thickness_mm"),
        "blank_length_mm": part.get("blank_length_mm") or material.get("blank_length_mm"),
        "blank_width_mm": part.get("blank_width_mm") or material.get("blank_width_mm"),
        "quantity": part.get("quantity"),
        "wire_gauge_mm": part.get("wire_gauge_mm"),
        "wire_length_mm": part.get("wire_length_mm"),
        "stated_weight_kg": part.get("stated_weight_kg"),
    }


def files_rows(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every source file the job saw, and what came out of it."""
    rows: List[Dict[str, Any]] = []
    seen: set = set()

    pages_by_file: Dict[str, int] = {}
    for page in (summary.get("pages") or []):
        if isinstance(page, Mapping):
            name = str(page.get("source_pdf_name") or page.get("source_file") or "").strip()
            if name:
                pages_by_file[name] = pages_by_file.get(name, 0) + 1
    for name, count in sorted(pages_by_file.items()):
        seen.add(name.lower())
        rows.append({"file": name, "kind": "PDF", "read": "yes",
                     "pages_or_entities": count, "yielded": f"{count} page(s) analysed"})

    # DXF and model files, wherever the readers recorded them on the parts.
    for part in _parts(summary):
        for key, kind in (("dxf_file", "DXF"), ("dxf_path", "DXF"),
                          ("solidworks_file", "SolidWorks"),
                          ("source_file", "source")):
            name = str(part.get(key) or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            rows.append({"file": Path(name).name, "kind": kind, "read": "yes",
                         "pages_or_entities": "",
                         "yielded": f"geometry for {part.get('part_number')}"})

    # Files the pack contained and NOTHING read — the ones worth the most attention.
    for issue in ((summary.get("document_analysis") or {}).get("pack_issues") or []):
        if not isinstance(issue, Mapping):
            continue
        for name in (issue.get("files") or []):
            base = Path(str(name)).name
            if base.lower() in seen:
                continue
            seen.add(base.lower())
            rows.append({"file": base, "kind": Path(base).suffix.upper().lstrip(".") or "?",
                         "read": "NO", "pages_or_entities": "",
                         "yielded": _text(issue.get("message") or "not read")})
    return rows


def _match_part(summary: Mapping[str, Any], dxf_name: str) -> Optional[Mapping[str, Any]]:
    """The part record this DXF belongs to, matched on the code in its filename."""
    stem = Path(dxf_name).stem.upper().replace("_", "-")
    best = None
    for part in _parts(summary):
        code = str(part.get("part_number") or "").strip().upper().replace("_", "-")
        if code and code in stem:
            if best is None or len(code) > len(str(best.get("part_number") or "")):
                best = part
    return best


def dxf_comparison_rows(summary: Mapping[str, Any],
                        dxf_paths: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    """AVAILABLE IN THE FILE -> EXTRACTED -> ASSIGNED TO A PART -> USED IN COSTING.

    The other sheets can only report what the pipeline recorded, which makes them blind to
    the failure that matters most: a fact that was in the file and never reached anything.
    This one opens the DXFs itself and puts the file's own measurements beside the engine's,
    so "the reader gets the blank" is something you check rather than believe.

    A mismatch is NOT automatically an engine defect and the sheet does not call it one — a
    drawing export's extent is its sheet border, and a part legitimately sized from a model
    may differ from its flat. What the sheet guarantees is that the difference is visible.
    """
    try:
        from dxf_probe import probe_dxf
    except Exception:                                                    # noqa: BLE001
        return []

    paths: List[Any] = list(dxf_paths or [])
    if not paths:
        seen: set = set()
        for part in _parts(summary):
            for key in ("dxf_file", "dxf_path", "flat_pattern_file"):
                value = part.get(key)
                if value and str(value).lower() not in seen:
                    seen.add(str(value).lower())
                    paths.append(value)
    if not paths:
        return []

    rows: List[Dict[str, Any]] = []
    for path in paths:
        try:
            probe = probe_dxf(path)
        except Exception as err:                                         # noqa: BLE001
            rows.append({"file": Path(str(path)).name, "in_the_file": "could not be read",
                         "engine_has": "", "agrees": "",
                         "note": f"{type(err).__name__}: {err}"})
            continue
        if not probe.get("readable"):
            rows.append({"file": probe["file"], "in_the_file": "no entities found",
                         "engine_has": "", "agrees": "",
                         "note": "the file could not be parsed as a DXF"})
            continue
        if probe.get("entities_are_raster_only"):
            rows.append({"file": probe["file"], "in_the_file": "a raster image only",
                         "engine_has": "", "agrees": "n/a",
                         "note": "there is no geometry in this file to extract — no API will "
                                 "reveal what is not there. Ask for a vector export"})
            continue

        part = _match_part(summary, probe["file"])
        pn = _text(part.get("part_number")) if part else ""
        geometry = (part.get("geometry_rollup") or {}) if part else {}
        features = (part.get("manufacturing_features") or {}) if part else {}

        def _engine(*keys: str) -> Any:
            for source in (part or {}, geometry, features):
                for key in keys:
                    value = (source or {}).get(key)
                    if value not in (None, "", []):
                        return value
            return None

        comparisons = [
            ("blank length mm", probe.get("blank_length_mm"), _engine("blank_length_mm")),
            ("blank width mm", probe.get("blank_width_mm"), _engine("blank_width_mm")),
            ("hole count", probe.get("hole_count") or None,
             _engine("hole_count", "estimated_hole_count")),
            ("bend lines", probe.get("bend_line_count") or None,
             _engine("bend_count", "bend_count_dxf", "estimated_bend_line_count",
                     "fold_count")),
            ("cut length mm", probe.get("cut_length_mm"),
             _engine("cut_length_mm", "dxf_measured_cut_length", "estimated_cut_length_mm")),
        ]
        for label, available, extracted in comparisons:
            if available is None and extracted in (None, "", []):
                continue
            agrees = ""
            if available is not None and extracted not in (None, "", []):
                a, b = _num(available), _num(extracted)
                if a is not None and b is not None:
                    agrees = "yes" if abs(a - b) <= max(0.5, abs(a) * 0.02) else "NO"
            elif available is not None:
                agrees = "NOT EXTRACTED"
            rows.append({
                "file": probe["file"],
                "part": pn or "(no part matched to this file)",
                "fact": label,
                "in_the_file": available,
                "engine_has": extracted,
                "agrees": agrees,
                "note": (probe.get("extent_is") if label.startswith("blank") else "")
                        or ("" if probe.get("looks_like_flat_export")
                            else "drawing export, not a flat"),
            })
    return rows


def fact_rows(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """One row per extracted datum: what, on which part, from where, and did it get used.

    The `used_in_costing` column is the point of the sheet. A value that was read, attached
    to the right part and then beaten by a stronger source is CORRECT behaviour and says so;
    a value that was read and simply never referenced again is a join to fix.
    """
    rows: List[Dict[str, Any]] = []
    for part in _parts(summary):
        pn = _text(part.get("part_number"))
        live = _costed_fields(part)
        displaced = part.get("_displaced") if isinstance(part.get("_displaced"), Mapping) else {}

        for field, value in live.items():
            if value in (None, ""):
                continue
            rows.append({
                "part": pn,
                "field": field,
                "value": value,
                "source": _text(part.get(f"{field.replace('normalized_', '')}_source")
                                or part.get(f"{field}_source") or ""),
                "outcome": "USED — this is the figure the price is built on",
                "file_or_page": _text(part.get("drawing_files") or part.get("pages") or ""),
            })

        for field, entries in (displaced or {}).items():
            for entry in (entries or []):
                if not isinstance(entry, Mapping):
                    continue
                applied = entry.get("applied")
                rows.append({
                    "part": pn,
                    "field": field,
                    "value": entry.get("value"),
                    "source": _text(entry.get("source")),
                    "outcome": ("USED" if applied else
                                f"read, then beaten by a stronger source"
                                + (f" ({_text(entry.get('displaced_by'))})"
                                   if entry.get("displaced_by") else "")),
                    "file_or_page": _text(entry.get("page") or entry.get("file") or ""),
                })
    return rows


def bom_rows(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every parts-list row the readers returned, with the page it was read from."""
    out: List[Dict[str, Any]] = []
    for row in ((summary.get("document_analysis") or {}).get("bom_rows") or []):
        if not isinstance(row, Mapping):
            continue
        out.append({
            "file_or_page": _text(row.get("source_page") or row.get("page") or ""),
            "item": _text(row.get("item") or row.get("item_no") or ""),
            "part_number": _text(row.get("part_number")),
            "description": _text(row.get("description")),
            "quantity": row.get("quantity"),
            "material_as_printed": _text(row.get("material_text")),
            "thickness_mm": row.get("thickness_mm"),
            "stated_weight_kg": row.get("stated_weight_kg"),
            "read_by": _text(row.get("source") or row.get("reader") or ""),
        })
    return out


def operation_rows(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every route decision, its target and why it stands or does not."""
    out: List[Dict[str, Any]] = []
    route = (summary.get("estimate_summary") or {}).get("canonical_route") or {}
    for decision in (route.get("decisions") or []):
        if not isinstance(decision, Mapping):
            continue
        out.append({
            "operation": _text(decision.get("operation")),
            "target": _text(decision.get("part_number") or decision.get("target")),
            "status": _text(decision.get("status")),
            "decided_by": _text(decision.get("decided_by")),
            "reason": _text(decision.get("reason")),
        })
    return out


def not_extracted_rows(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """What the pack held that nothing read. The shortest sheet worth the most attention."""
    out: List[Dict[str, Any]] = []
    for issue in ((summary.get("document_analysis") or {}).get("pack_issues") or []):
        if isinstance(issue, Mapping):
            out.append({"what": _text(issue.get("code") or "pack issue"),
                        "detail": _text(issue.get("message"), 600)})
    for part in _parts(summary):
        for flag in (part.get("review_flags") or []):
            text = str(flag)
            if any(cue in text for cue in ("UNRESOLVED", "not in the material lexicon",
                                           "NOT read as a diameter", "is not known",
                                           "could not be taken")):
                out.append({"what": _text(part.get("part_number")), "detail": _text(text, 600)})
    return out


def build_tables(summary: Mapping[str, Any],
                 dxf_paths: Optional[Sequence[Any]] = None) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "Files": files_rows(summary),
        "DXF file vs engine": dxf_comparison_rows(summary, dxf_paths),
        "Facts": fact_rows(summary),
        "BOM rows": bom_rows(summary),
        "Operations": operation_rows(summary),
        "Not extracted": not_extracted_rows(summary),
    }


def write_source_drawing_data(summary: Mapping[str, Any], out_dir: Any,
                              job: str = "",
                              dxf_paths: Optional[Sequence[Any]] = None) -> Optional[Path]:
    """Write source_drawing_data.xlsx into the estimating folder. Returns the path.

    Never raises into the run: an audit that breaks the job it audits is worse than no audit.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except Exception:                                                    # noqa: BLE001
        return None
    tables = build_tables(summary, dxf_paths)
    book = Workbook()
    book.remove(book.active)
    for name in SHEETS:
        rows = tables.get(name) or []
        sheet = book.create_sheet(name[:31])
        if not rows:
            sheet.cell(row=1, column=1, value=f"No {name.lower()} recorded for this job.")
            continue
        headers = list(rows[0].keys())
        for column, header in enumerate(headers, start=1):
            cell = sheet.cell(row=1, column=column, value=header)
            cell.font = Font(bold=True)
        for index, row in enumerate(rows, start=2):
            for column, header in enumerate(headers, start=1):
                sheet.cell(row=index, column=column, value=row.get(header))
        for column, header in enumerate(headers, start=1):
            width = max(len(str(header)),
                        *(len(str(r.get(header) or "")) for r in rows[:200]))
            sheet.column_dimensions[
                sheet.cell(row=1, column=column).column_letter].width = min(max(width + 2, 10), 80)
        sheet.freeze_panes = "A2"

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / (f"{job}_source_drawing_data.xlsx" if job else "source_drawing_data.xlsx")
    book.save(path)
    return path
