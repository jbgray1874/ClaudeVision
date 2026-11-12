"""
Fill a Blank Estimate-style .xlsx with values from a scan summary (estimate_summary paths).

Uses the same discovery-driven write-back as ``estimate_template_writeback``; requires a
``.xlsx`` template (openpyxl cannot write legacy ``.xls``).

Template resolution order:
1. ``template_path`` argument (from ``main.py --ai-spreadsheet-template`` when generating after a scan).
2. ``config.AI_ESTIMATE_XLSX_TEMPLATE`` if that file exists.
3. The ``.xlsx`` sibling of the configured ``.xls`` template workbook in ``PRICE_SOURCE_CONFIG``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import config
from estimate_template_writeback import write_estimate_template_from_summary


def resolve_ai_estimate_template(explicit: Optional[Path] = None) -> Path:
    if explicit is not None and explicit.is_file():
        return explicit.resolve()
    tpl = getattr(config, "AI_ESTIMATE_XLSX_TEMPLATE", None)
    if tpl is not None:
        p = Path(tpl)
        if p.is_file():
            return p.resolve()
    # Same stem as configured .xls template, but .xlsx
    sp = (config.PRICE_SOURCE_CONFIG or {}).get("spreadsheet") or {}
    xls_path = Path(str(sp.get("template_workbook", "")))
    if xls_path.suffix.lower() == ".xls":
        alt = xls_path.with_suffix(".xlsx")
        if alt.is_file():
            return alt.resolve()
    raise FileNotFoundError(
        "No .xlsx estimate template found. Add e.g. "
        f"{getattr(config, 'AI_ESTIMATE_XLSX_TEMPLATE', '')} "
        "or place Blank Estimate Sheet 2026.xlsx next to your .xls template."
    )


def generate_ai_estimating_spreadsheet(
    summary: Dict[str, Any],
    *,
    template_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
) -> Path:
    """
    Write ``AI_Estimate_<stem>.xlsx`` using discovered output cells (M59, M103, D6, etc.).
    """
    tpl = resolve_ai_estimate_template(Path(template_path) if template_path else None)
    stem = Path(str(summary.get("source_file") or "drawing")).stem
    out_dir = Path(config.OUTPUT_DIR) / "spreadsheets" / "ai_generated"
    out = output_path or (out_dir / f"AI_Estimate_{stem}.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    return write_estimate_template_from_summary(summary, tpl, out)
