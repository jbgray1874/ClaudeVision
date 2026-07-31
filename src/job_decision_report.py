"""
SDI Intelligence — Job Decision Report
========================================
Generates a detailed per-job report showing exactly:
  - Every part estimated
  - What material was used and WHY
  - Where the thickness came from
  - What operations were detected and how
  - Cost breakdown per part
  - Confidence level with explanation
  - What's certain vs what needs review
Added as "Decision Report" sheet to every estimate xlsx.
Also generates a standalone per-job summary.
Called from estimator.py:
    from job_decision_report import add_decision_report_sheet
    add_decision_report_sheet(wb, summary, scan_meta)
"""
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from geometry_inference import _has_geometry as _has_real_dxf_geometry

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    _OK = True
except ImportError:
    _OK = False
# ── Colours ────────────────────────────────────────────────────────────────────
C_NAVY      = "1F3864"
C_BLUE      = "2F5496"
C_WHITE     = "FFFFFF"
C_HIGH      = "C6EFCE"
C_HIGH_TXT  = "276221"
C_MED       = "FFEB9C"
C_MED_TXT   = "7D6608"
C_LOW       = "FFC7CE"
C_LOW_TXT   = "9C0006"
C_BOUGHT    = "EDEDED"
C_LIGHT     = "EBF3FB"
C_ALT       = "F5F5F5"
C_BORDER    = "BDD7EE"
C_SECTION   = "D6E4F0"


def _is_bought_in(part: Dict) -> bool:
    """True when a part is a bought-in / catalogue component (not fabricated).

    Bought-in items have no fabrication material, so they must be kept OUT of the
    material-inference paths (DXF-filename tokens, part-number suffix heuristics).
    A code like BI-50CMLOOM ends in 'M' and BI-LEDLINKLIGHT ends in 'T'; without this
    guard the suffix heuristic mislabels them "-M → Mild Steel" / "-T → MDF/Timber".
    Detected by: normalized_material BOUGHT_IN, a 'bought_in' page role, the layer-2
    recogniser source, or the BI-/FIXING/VINYL code families.
    """
    mat = str(part.get("normalized_material") or part.get("material") or "").upper()
    if mat == "BOUGHT_IN":
        return True
    roles = part.get("page_roles") or []
    if "bought_in" in [str(r).lower() for r in roles]:
        return True
    src = str(part.get("source") or "").lower()
    if "recogniser" in src or "bought_in" in src or "note_scan" in src:
        return True
    pn = str(part.get("part_number") or "").upper()
    if pn.startswith(("BI-", "FIXING", "VINYL", "PACKAGING", "DELIVERY")):
        return True
    return False


def _c(ws, row, col, value="", bold=False, bg=None, fg="000000",
       align="left", wrap=False, size=10, italic=False,
       num_fmt=None, border=False):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = Font(name="Arial", bold=bold, color=fg,
                     size=size, italic=italic)
    if bg:
        cell.fill = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal=align, vertical="center",
                                wrap_text=wrap)
    if num_fmt:
        cell.number_format = num_fmt
    if border:
        s = Side(style="thin", color="CCCCCC")
        cell.border = Border(left=s, right=s, top=s, bottom=s)
    return cell


def _find_wb_sell_price_ref(wb) -> Optional[str]:
    """Locate the WB's Sell Price VALUE cell by scanning for its LABEL, and return a
    cross-sheet formula reference string like "='Estimate'!M143".

    WHY a formula, not a value: the WB computes Sell Price with its own Excel formulas
    that only evaluate when the file is opened (calc-on-load). At report-build time the
    value is still 0 in memory, so we cannot read it. Instead we point the report's total
    cell at the WB's cell with a live formula — Excel then shows the same authoritative
    number on both sheets.

    WHY scan for the label, not hardcode M143: the estimators' template layout shifts when
    the BOM block grows, moving the Sell Price down. Anchoring to the "Sell Price" label
    (which moves with its value) survives that; a hardcoded row would silently go stale.
    Returns None if the sheet/label is not found, so the caller falls back to the engine sum.
    """
    try:
        # The populated estimate lives on the "Estimate" sheet (CELL_MAP estimate_sheet).
        ws = None
        for name in ("Estimate", "estimate"):
            if name in wb.sheetnames:
                ws = wb[name]
                break
        if ws is None:
            return None
        # Scan for a cell whose text is (or contains) "Sell Price"; the £ value sits to its
        # right on the same row (from the template: label in col ~I-L, value in col M).
        for r in ws.iter_rows():
            for cell in r:
                v = cell.value
                if isinstance(v, str) and "sell" in v.lower() and "price" in v.lower():
                    # Find the first numeric/blank value cell to the RIGHT on this row.
                    # Prefer column M (the template's value column) if it is to the right.
                    label_col = cell.column  # 1-indexed
                    row_idx = cell.row
                    # Look rightward up to 8 columns for the value cell; take the furthest
                    # populated/known money column. Template value column is M (13).
                    target_col = None
                    for c in range(label_col + 1, label_col + 9):
                        cc = ws.cell(row=row_idx, column=c)
                        # A formula or a number here = the value cell.
                        if cc.value not in (None, ""):
                            target_col = c
                            break
                    # If nothing populated found (value is a not-yet-calculated formula that
                    # openpyxl read as 0/None), fall back to column M on the label's row.
                    if target_col is None:
                        target_col = 13  # M
                    col_letter = get_column_letter(target_col)
                    return f"='{ws.title}'!{col_letter}{row_idx}"
        return None
    except Exception:
        return None


def _conf_info(part: Dict, unit_cost: float = 0.0) -> tuple:
    """Return (confidence_float, label, bg_colour, fg_colour, explanation)"""
    mat    = str(part.get("normalized_material") or part.get("material") or "").upper()
    geo    = str(part.get("geometry_source") or "")
    src    = str(part.get("material_source") or "")
    unit   = float(unit_cost or 0)
    thks   = part.get("thicknesses_mm") or []
    tol    = {0.5, 1.0, 1.5, 2.0, 3.0}
    has_thk = any(t and round(float(t), 1) not in tol for t in thks)
    if _is_bought_in(part):
        return 1.0, "BOUGHT-IN", C_BOUGHT, "555555", "Hardware/bought-in component — not fabricated"
    if "knowledge_base" in src:
        return 0.99, "HIGH ✓", C_HIGH, C_HIGH_TXT, \
               "Previously confirmed by estimator — from SDI knowledge base"
    if "dxf_flat_pattern" in geo and has_thk and mat in ("MILD_STEEL","MDF","ACRYLIC","TIMBER"):
        return 0.92, "HIGH ✓", C_HIGH, C_HIGH_TXT, \
               "DXF flat pattern matched — exact geometry, material from DXF filename"
    if "dxf_flat_pattern" in geo and mat in ("MILD_STEEL","MDF","ACRYLIC","TIMBER"):
        return 0.80, "HIGH ✓", C_HIGH, C_HIGH_TXT, \
               "DXF flat pattern matched — exact geometry, thickness needs confirming"
    if "dxf" in geo and unit > 0:
        return 0.75, "MEDIUM", C_MED, C_MED_TXT, \
               "DXF geometry used — material or thickness inferred from context"
    if unit == 0 and mat not in ("BOUGHT_IN",):
        return 0.25, "REVIEW ⚠", C_LOW, C_LOW_TXT, \
               "Zero cost — thickness or geometry not extracted. Manual review needed"
    if not mat or mat in ("UNKNOWN","LED","CARD"):
        return 0.20, "REVIEW ⚠", C_LOW, C_LOW_TXT, \
               f"Material unresolved ({mat!r}). Check drawing and resubmit"
    if "pdf" in geo and unit > 0:
        return 0.60, "MEDIUM", C_MED, C_MED_TXT, \
               "PDF geometry extraction — accuracy depends on drawing detail level"
    return 0.50, "MEDIUM", C_MED, C_MED_TXT, "AI inference — no DXF available"


def _mat_source_explanation(part: Dict) -> str:
    """Plain English explanation of why this material was chosen."""
    # Bought-in components have NO fabrication material — never run them through the
    # DXF-token / part-number-suffix material heuristics (BI-...T would misread as
    # "-T → MDF/Timber", BI-...M as "-M → Mild Steel"). Return an honest bought-in note.
    if _is_bought_in(part):
        return "Bought-in / catalogue component — no fabrication material (priced from catalogue/history)"
    mat = str(part.get("normalized_material") or part.get("material") or "").upper()
    src = str(part.get("material_source") or "")
    geo = str(part.get("geometry_source") or "")
    dxf = str(part.get("dxf_source_file") or "")
    pn  = str(part.get("part_number") or "")
    if "knowledge_base" in src:
        return f"✅ SDI Knowledge Base — previously confirmed by estimator"
    if "_MS_" in dxf.upper() or "MS_" in dxf.upper():
        return f"✅ DXF filename contains '_MS_' → Mild Steel"
    if "PETG" in dxf.upper():
        return f"✅ DXF filename contains 'PETG' → Acrylic"
    if "JOINERY" in dxf.upper():
        return f"✅ DXF filename contains 'JOINERY' → MDF/Timber"
    if pn and pn.endswith("M"):
        return f"✅ Part number suffix '-M' → Mild Steel (SDI naming convention)"
    if pn and pn.endswith("A"):
        return f"✅ Part number suffix '-A' → Acrylic (SDI naming convention)"
    if pn and pn.endswith("T"):
        return f"✅ Part number suffix '-T' → MDF/Timber (SDI naming convention)"
    if mat == "MILD_STEEL" and "pdf" in geo:
        return "⚡ PDF drawing text — 'MILD STEEL' found in title block"
    if mat == "MDF":
        return "⚡ PDF drawing text — 'MDF' or 'FSC ACCREDITED' found"
    if mat == "BOUGHT_IN":
        return "✅ Description contains bought-in keyword (hinge/magnet/fixing)"
    if not mat or mat in ("UNKNOWN","LED","CARD"):
        return "⚠ Material unresolved — check drawing title block"
    return f"⚡ AI inference from drawing context"


def _thk_source_explanation(part: Dict) -> str:
    """Plain English explanation of thickness source.
    DXF filename checked FIRST (most reliable, avoids real 2mm/3mm acrylic
    being discarded as tolerance-table values)."""
    # Bought-in components have no fabrication thickness — don't imply one.
    if _is_bought_in(part):
        return "— bought-in component (no fabrication thickness)"
    import re
    dxf  = str(part.get("dxf_source_file") or "")
    geo  = str(part.get("geometry_source") or "")
    tol  = {0.5, 1.0, 1.5, 2.0, 3.0}
    # 1. DXF filename thickness — most reliable
    m = re.search(r'[_\-\s](\d+\.?\d*)\s*mm', dxf, re.IGNORECASE)
    if m:
        tv = float(m.group(1))
        if 0.3 <= tv <= 25.0:
            return f"✅ {tv}mm — from DXF filename: {dxf}"
    # 2. thicknesses_mm — only strip tolerance values if the FULL sequence is
    #    present (a standalone 2.0/3.0 is a real thickness, not table noise).
    thks = part.get("thicknesses_mm") or []
    thk_set = {round(float(t), 1) for t in thks if t}
    if tol.issubset(thk_set):
        real_thks = [t for t in thks if t and round(float(t), 1) not in tol]
    else:
        real_thks = [t for t in thks if t]
    if real_thks:
        thk = real_thks[0]
        if "dxf" in geo:
            return f"✅ {thk}mm — from DXF geometry / drawing dimensions"
        return f"⚡ {thk}mm — extracted from PDF drawing text"
    if thks and tol.issubset({round(float(t),1) for t in thks if t}):
        return "⚠ Tolerance table values only — real thickness not extracted"
    return "⚠ No thickness found — assembly-only page or missing dimension"


def _ops_explanation(part: Dict, est: Optional[Dict] = None,
                     summary: Optional[Dict] = None) -> str:
    """Explain how operations were determined.

    Driven by what we actually COSTED where the part estimate is available, not by the raw
    textual/inferred op lists. Those lists are the drawing's interpretation, and on these
    packs the shared specification legend puts processes on parts that never carry them —
    which is how "laser cutting" and "powder coating" ended up described against timber
    panels that the Estimate sheet charges only saw, glue, CNC and spray for. A provenance
    sheet that describes operations the estimate does not contain is worse than no
    provenance: it reads as evidence for a route we did not price. Same rule already
    applied to the client quote.
    """
    # Canonical where the workbook has run (the route the Estimate sheet two tabs away
    # actually charges); the part's own PRE-FILTER costed fields only as a fallback.
    from costed_facts import operations_for_part, priced_route_known
    ops: List[str] = operations_for_part(summary, part.get("part_number"), est)
    if not ops and priced_route_known(summary):
        # THE PRICED ROUTE IS KNOWN AND THIS PART IS IN NONE OF IT.
        #
        # That is an answer, not a gap, and the honest one is to say so. The old fallback
        # reached for the drawing's textual + inferred lists here, which is where the
        # suppressed route came back: every part a gate removed — powder on a timber panel,
        # weld/dress on an artefact record — lost its costed evidence and was then described
        # from the specification legend instead. The report ended up narrating exactly the
        # operations the workbook had just decided against.
        return ("No operation charged on this job — the priced route contains this part "
                "in no labour row")
    _priced = True
    if not ops:
        # No workbook yet (a report generated from a JSON alone). Nothing has been priced,
        # so the drawing's own reading is the best available evidence — and it is labelled
        # as such below rather than presented as what we charged.
        ops = list(part.get("textual_operations") or []) + list(part.get("inferred_operations") or [])
        _priced = False
    mat = str(part.get("normalized_material") or part.get("material") or "").upper()
    geo = str(part.get("geometry_source") or "")
    if not ops:
        return "No operations detected — assembly-only record"
    sources = []
    if "laser_cutting" in ops:
        sources.append("laser cutting (flat DXF detected)" if "dxf" in geo
                       else "laser cutting (inferred from material/geometry)")
    if "cnc_routing" in ops:
        sources.append("CNC routing (timber/MDF material)")
    if "folding" in ops:
        sources.append("folding (bend lines in DXF)")
    if "powder_coating" in ops:
        sources.append("powder coating (finish specified in drawing)")
    if "wet_spray" in ops:
        sources.append("wet spray (finish specified in drawing)")
    if "edge_banding" in ops:
        sources.append("edge banding (MDF/timber with 'EDGED' finish)")
    if "welding" in ops:
        sources.append("welding (assembly drawing indicates welds)")
    if "handling" in ops:
        sources.append("handling / assembly (bench time)")
    # "Read from the drawing" is not "charged". Saying which one this is costs a word and
    # stops an unpriced reading being mistaken for the route the sheet contains.
    _lead = "Operations" if _priced else "Read from drawing — NOT YET PRICED"
    return f"{_lead}: " + ", ".join(sources) if sources else \
           f"{_lead}: {', '.join(ops)}"


def add_decision_report_sheet(wb, summary: Dict[str, Any],
                               scan_meta: Dict[str, Any] = None) -> None:
    """Add a 'Decision Report' sheet to an existing workbook."""
    if not _OK:
        return

    parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    if not parts:
        return

    # SDI Intelligence — cost lives in estimate_summary.part_estimates,
    # keyed by part_number. Build a lookup so the report shows real costs.
    #
    # PRE-FILTER, and the columns fed from it say so. These are the engine's own per-part
    # numbers; the Estimate sheet's totals are calculated by Excel from the accepted labour
    # and material rows, and the two are different calculators. Per-part cost is not
    # recoverable from the sheet — a labour row is a department's batch value across every
    # part in the group — so the honest presentation is the engine figure, labelled as the
    # engine figure, reconciled against the workbook below.
    _est_lookup = {}
    for _pe in (summary.get("estimate_summary") or {}).get("part_estimates", []):
        _pn = _pe.get("part_number")
        if _pn:
            _est_lookup[_pn] = _pe

    from costed_facts import (canonical_quantity, decision_ids_for_part,
                              job_totals, priced_route_known, priced_rows_for_part)
    _totals = job_totals(summary)
    _canonical = priced_route_known(summary)

    scan_meta = scan_meta or {}
    ws = wb.create_sheet("Decision Report")
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = C_BLUE
    # ── Column widths ──────────────────────────────────────────────────────────
    col_widths = [16, 30, 6, 14, 10, 34, 34, 34, 10, 10, 14, 26]
    for ci, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    # ── Title ──────────────────────────────────────────────────────────────────
    ws.merge_cells("A1:L1")
    _c(ws, 1, 1, "SDI Intelligence — Estimate Decision Report",
       bold=True, bg=C_NAVY, fg=C_WHITE, align="center", size=14)
    ws.row_dimensions[1].height = 30
    pdf_name = scan_meta.get("pdf_name") or summary.get("source_file") or "—"
    job_no   = scan_meta.get("job_number") or "—"
    total    = sum(float(_est_lookup.get(p.get("part_number"), {}).get("extended_total_cost_gbp") or 0) for p in parts)

    # The AUTHORITATIVE total is the WB's Sell Price (computed by the WB's own formulas).
    # Find its cell by label so the report can reference it live; falls back to the engine
    # part-sum (`total`) if the WB sheet/label is not present.
    _sell_ref = _find_wb_sell_price_ref(wb)

    ds = (summary.get("estimate_summary") or {}).get("data_sufficiency") or {}
    if ds.get("status") == "insufficient_data":
        # Do NOT print the engine part-sum (ds.document_total_provisional_gbp) as "the
        # provisional total" — it is a different calculator from the workbook Sell Price and
        # can differ materially (Horti Crate: engine £102.07 vs workbook £46.53), which made
        # this header contradict the SELL PRICE total row below and the report/quote HTML.
        # Warn here; the authoritative provisional figure is the Sell Price shown below.
        total_line = (
            f"⚠ INSUFFICIENT DATA — PROVISIONAL, NOT for quoting "
            f"(credible {float(ds.get('credible_cost_ratio') or 0) * 100:.0f}% · "
            f"DXF {float(ds.get('dxf_part_ratio') or 0) * 100:.0f}% of parts) — see total below"
        )
    else:
        # Prefer the WB Sell Price; the header text still shows the engine sum as a
        # reference, but the authoritative figure is the WB's (see the TOTAL row below).
        if _sell_ref:
            total_line = "Total (Sell Price): see Estimate sheet — mirrored below"
        else:
            total_line = f"Total Estimate: £{total:,.2f}"
    ws.merge_cells("A2:L2")
    _c(ws, 2, 1,
       f"Drawing: {pdf_name}   |   Job: {job_no}   |   "
       f"{total_line}   |   "
       f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}   |   "
       f"SDI Intelligence — wearesdi.com",
       bg=C_BLUE, fg=C_WHITE, align="center", size=10)
    ws.row_dimensions[2].height = 16
    # ── Key ────────────────────────────────────────────────────────────────────
    ws.merge_cells("A3:L3")
    _c(ws, 3, 1,
       "CONFIDENCE:   ✅ HIGH — DXF matched or knowledge base confirmed   "
       "⚡ MEDIUM — PDF extraction or AI inference   "
       "⚠ REVIEW — zero cost, unknown material or assembly-only record",
       bg="F0F0F0", size=9, italic=True)
    ws.row_dimensions[3].height = 14
    ws.row_dimensions[4].height = 6  # spacer
    # ── Column headers ─────────────────────────────────────────────────────────
    # The money columns are the ENGINE's per-part figures, and once a workbook exists they
    # are not what the sheet charges. Naming the basis in the header is the difference
    # between a working figure and a price the reader will quote from.
    _money_basis = " (engine)" if _totals["source"] == "excel_calculated" else ""
    headers = [
        "Part Number", "Description", "Qty",
        "Material", "Thickness",
        "Material Source — WHY",
        "Thickness Source — WHY",
        "Operations — HOW DETECTED",
        f"Unit £{_money_basis}", f"Ext £{_money_basis}", "Confidence",
        "Priced by — sheet row / decision",
    ]
    for ci, hdr in enumerate(headers, 1):
        _c(ws, 5, ci, hdr, bold=True, bg=C_NAVY, fg=C_WHITE,
           align="center", size=9, border=True)
    ws.row_dimensions[5].height = 20
    # ── Part rows ──────────────────────────────────────────────────────────────
    row = 6
    review_parts = []
    for i, part in enumerate(parts):
        pn   = str(part.get("part_number") or "—")
        desc = str(part.get("description") or "—")
        # QUANTITY PER TOP-LEVEL UNIT, not per parent.
        #
        # A BOM row states how many the PARENT takes. For anything reached through a
        # sub-assembly that is not the quantity the job needs: a knob at qty 2 inside a
        # sub-assembly used twice is 4 per unit. The compiled hierarchy rolls the
        # multiplicity through, and the workbook already charges on the rolled figure —
        # so the raw row quantity here made the report disagree with its own Estimate sheet
        # for every part below the first level. Falls back to the row when the graph does
        # not know the part.
        _cq = canonical_quantity(summary, pn)
        qty  = int(_cq) if _cq is not None and float(_cq).is_integer() else (
            _cq if _cq is not None else int(part.get("quantity") or 1))
        # Bought-in components carry no fabrication material — show a clean label
        # instead of a defaulted/mis-inferred one (e.g. "MILD_STEEL" on a foam tape).
        if _is_bought_in(part):
            mat = "Bought-in"
        else:
            mat = str(part.get("normalized_material") or part.get("material") or "—")
        unit = float(_est_lookup.get(pn, {}).get("unit_total_cost_gbp") or 0)
        ext  = float(_est_lookup.get(pn, {}).get("extended_total_cost_gbp") or 0)
        # Thickness — real value only
        # Thickness column — DXF filename first, then non-tolerance values
        import re as _re_t
        _dfn_t = str(part.get("dxf_source_file") or "")
        _m_t = _re_t.search(r'[_\-\s](\d+\.?\d*)\s*mm', _dfn_t, _re_t.IGNORECASE)
        thks     = part.get("thicknesses_mm") or []
        tol      = {0.5, 1.0, 1.5, 2.0, 3.0}
        if _is_bought_in(part):
            real_thk = "—"
        elif _m_t and 0.3 <= float(_m_t.group(1)) <= 25.0:
            real_thk = f"{float(_m_t.group(1)):.1f}mm"
        else:
            _thk_set = {round(float(t),1) for t in thks if t}
            if tol.issubset(_thk_set):
                real_thk = next((f"{float(t):.1f}mm" for t in thks
                                 if t and round(float(t), 1) not in tol), "—")
            else:
                real_thk = next((f"{float(t):.1f}mm" for t in thks if t), "—")
        conf, conf_label, conf_bg, conf_fg, conf_expl = _conf_info(part, unit)
        mat_why  = _mat_source_explanation(part)
        thk_why  = _thk_source_explanation(part)
        ops_why  = _ops_explanation(part, _est_lookup.get(pn), summary)
        bg = C_ALT if i % 2 == 0 else C_WHITE
        if _is_bought_in(part):
            bg = C_BOUGHT
        _c(ws, row, 1,  pn,         bg=bg, bold=True, size=9, border=True)
        _c(ws, row, 2,  desc,       bg=bg, size=9,    border=True, wrap=True)
        _c(ws, row, 3,  qty,        bg=bg, align="center", size=9, border=True)
        _c(ws, row, 4,  mat,        bg=conf_bg, bold=True, fg=conf_fg,
           size=9, border=True)
        _c(ws, row, 5,  real_thk,   bg=bg, align="center", size=9, border=True)
        _c(ws, row, 6,  mat_why,    bg=bg, size=8, border=True, wrap=True)
        _c(ws, row, 7,  thk_why,    bg=bg, size=8, border=True, wrap=True)
        _c(ws, row, 8,  ops_why,    bg=bg, size=8, border=True, wrap=True)
        _c(ws, row, 9,  unit if unit > 0 else "—",
           bg=bg, align="right", bold=True, size=9,
           num_fmt="£#,##0.00", border=True)
        _c(ws, row, 10, ext if ext > 0 else "—",
           bg=bg, align="right", bold=True, size=9,
           num_fmt="£#,##0.00", border=True)
        _c(ws, row, 11, conf_label, bg=conf_bg, fg=conf_fg,
           align="center", bold=True, size=8, border=True)
        # ── Traceability: part -> the sheet rows charging it -> the decisions behind them.
        # Without this the Decision Report asserts a route and offers nothing to check it
        # against; with it every line on the page can be walked back to the Estimate tab and
        # forward to the compiler decision that put it there.
        _prows = priced_rows_for_part(summary, pn) if _canonical else []
        if _prows:
            _wbrows = sorted({int(float(r["workbook_row"])) for r in _prows
                              if r.get("workbook_row")})
            _dids = decision_ids_for_part(summary, pn)
            _trace = ("Estimate row " + ", ".join(str(r) for r in _wbrows)) if _wbrows else ""
            if _dids:
                _trace = (_trace + "\n" if _trace else "") + " · ".join(_dids)
        elif _canonical:
            _trace = "not priced on any labour row"
        else:
            _trace = "— no workbook built"
        _c(ws, row, 12, _trace, bg=bg, size=8, border=True, wrap=True)
        ws.row_dimensions[row].height = 36
        row += 1
        if (conf < 0.5 or unit == 0) and not _is_bought_in(part):
            review_parts.append((pn, desc, conf_expl))
    # ── Total row ──────────────────────────────────────────────────────────────
    row += 1
    ws.merge_cells(f"A{row}:H{row}")
    # Label reflects which number is shown: WB Sell Price (authoritative) if we found it,
    # otherwise the engine part-sum.
    _total_label = "SELL PRICE (from Estimate sheet)" if _sell_ref else "TOTAL ESTIMATE (engine part-sum)"
    _c(ws, row, 1, _total_label, bold=True, bg=C_NAVY, fg=C_WHITE,
       align="right", size=12)
    _c(ws, row, 9, "", bg=C_NAVY)
    if _sell_ref:
        # Live cross-sheet formula — Excel computes it on open, so the report total always
        # equals the WB's authoritative Sell Price (no duplicated maths, no drift).
        _tc = _c(ws, row, 10, _sell_ref, bold=True, bg=C_NAVY, fg=C_WHITE,
                 align="right", size=13, num_fmt="£#,##0.00")
    else:
        _c(ws, row, 10, total, bold=True, bg=C_NAVY, fg=C_WHITE,
           align="right", size=13, num_fmt="£#,##0.00")
    _c(ws, row, 11, "", bg=C_NAVY)
    _c(ws, row, 12, "", bg=C_NAVY)
    ws.row_dimensions[row].height = 24
    # ── Reconciliation: the engine part-sum against what Excel calculated ───────
    # Two calculators, both on this page: the Ext £ column sums the engine's per-part
    # figures, the total row shows the workbook's. They are not the same arithmetic and on
    # real jobs they differ materially. Leaving the reader to notice — and to guess which to
    # believe — is what made this sheet read as the engine contradicting itself.
    if _totals["source"] == "excel_calculated":
        row += 1
        ws.merge_cells(f"A{row}:L{row}")
        _eng = float(_totals.get("engine_part_sum_gbp") or 0.0)
        _unit = float(_totals.get("unit_gbp") or 0.0)
        _mat = _totals.get("material_gbp")
        _lab = _totals.get("labour_gbp")
        _parts_txt = " (material £{:,.2f} + labour £{:,.2f})".format(
            float(_mat), float(_lab)) if _mat is not None and _lab is not None else ""
        _c(ws, row, 1,
           f"RECONCILIATION — the Estimate sheet calculated £{_unit:,.2f} per unit"
           f"{_parts_txt}. The Ext £ column above sums the engine's own per-part figures to "
           f"£{_eng:,.2f}; the two are different calculators and the workbook is "
           f"authoritative. Per-part cost is not recoverable from the sheet — a labour row "
           f"is one department's batch value across every part in its group — so the "
           f"per-part columns are shown on the engine basis and labelled as such.",
           bg=C_LIGHT, size=9, wrap=True, italic=True)
        ws.row_dimensions[row].height = 34
    # ── Parts requiring review ─────────────────────────────────────────────────
    if review_parts:
        row += 2
        ws.merge_cells(f"A{row}:L{row}")
        _c(ws, row, 1, f"⚠  PARTS REQUIRING REVIEW ({len(review_parts)} items)",
           bold=True, bg="FFC7CE", fg="9C0006", size=11)
        ws.row_dimensions[row].height = 20
        row += 1
        for pn, desc, reason in review_parts:
            ws.merge_cells(f"B{row}:L{row}")
            _c(ws, row, 1, "⚠", bg="FFC7CE", align="center", size=9)
            _c(ws, row, 2, f"{pn}  —  {desc}  |  {reason}",
               bg="FFC7CE", fg="9C0006", size=9, wrap=True)
            ws.row_dimensions[row].height = 18
            row += 1
    # ── Insufficient data / unreliable-cost section ────────────────────────────
    if ds.get("status") == "insufficient_data":
        row += 2
        ws.merge_cells(f"A{row}:L{row}")
        _c(ws, row, 1, "⚠  INSUFFICIENT DATA — DO NOT QUOTE FROM THIS TOTAL",
           bold=True, bg="FFC7CE", fg="9C0006", size=11)
        ws.row_dimensions[row].height = 20
        row += 1
        ws.merge_cells(f"A{row}:L{row}")
        # Do NOT cite a second, static "provisional total" here. The authoritative total is
        # the workbook Sell Price shown in the SELL PRICE row directly above (a live cross-
        # sheet formula). The engine part-sum (ds.document_total_provisional_gbp) is a
        # different calculator and can differ materially — e.g. on the Horti Crate the engine
        # part-sum was £102.07 while the workbook Sell Price was £46.53. Printing that figure
        # here made the Decision Report contradict its own total row (and the report/quote
        # HTML). The banner's job is to WARN; the number is already above it.
        _c(ws, row, 1,
           f"Most of this estimate is not DXF-backed. The total shown above is "
           f"PROVISIONAL and must not be quoted — request part DXFs first. "
           f"Credible share: {float(ds.get('credible_cost_ratio') or 0) * 100:.0f}% · "
           f"Part DXFs: {int(ds.get('parts_with_dxf') or 0)}/"
           f"{int(ds.get('fabricated_part_count') or 0)} fabricated parts.",
           bg="FFC7CE", fg="9C0006", size=9, wrap=True)
        ws.row_dimensions[row].height = 28
        row += 1
        for up in (ds.get("unreliable_parts") or [])[:12]:
            ws.merge_cells(f"B{row}:L{row}")
            _c(ws, row, 1, "✗", bg="FFC7CE", align="center", size=9)
            _c(ws, row, 2,
               f"{up.get('part_number')}  —  {up.get('description')}  |  "
               f"£{float(up.get('extended_cost_gbp') or 0):,.2f}  —  "
               f"{', '.join(up.get('reasons') or [])}",
               bg="FFC7CE", fg="9C0006", size=9, wrap=True)
            ws.row_dimensions[row].height = 18
            row += 1
    # ── Missing-DXF / inferred-geometry section ────────────────────────────────
    _parts_all = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    _inferred = [p for p in _parts_all if p.get("geometry_inferred") and not p.get("dxf_augmented")]
    _no_dxf   = [p for p in _parts_all
                 if (p.get("source") == "sdi_bom_row_no_geometry"
                     and not p.get("geometry_inferred")
                     and not _has_real_dxf_geometry(p))]
    if _inferred or _no_dxf:
        row += 2
        ws.merge_cells(f"A{row}:L{row}")
        _c(ws, row, 1, "⚠  DRAWINGS OUTSTANDING — PROVISIONAL / MISSING COSTS",
           bold=True, bg="FFE699", fg="7F6000", size=11)
        ws.row_dimensions[row].height = 20
        row += 1
        ws.merge_cells(f"A{row}:L{row}")
        _c(ws, row, 1, "These parts have no flat DXF. Request the DXF from the "
           "drawing office; figures below are AI-inferred and provisional.",
           bg="FFF2CC", fg="7F6000", size=9, wrap=True)
        ws.row_dimensions[row].height = 16
        row += 1
        for p in _inferred:
            gi = p.get("geometry_inference") or {}
            basis = gi.get("basis", "inferred")
            _bn = {"historical_sdilive": "from SDILive history",
                   "sibling_borrow": "borrowed from similar part",
                   "category_default": "typical size for type"}.get(basis, basis)
            ws.merge_cells(f"B{row}:L{row}")
            _c(ws, row, 1, "✎", bg="FFF2CC", align="center", size=9)
            _c(ws, row, 2, f"{p.get('part_number')}  —  {p.get('description')}  |  "
               f"INFERRED ({_bn}): {gi.get('blank_length_mm')}×{gi.get('blank_width_mm')}mm "
               f"— VERIFY before quoting", bg="FFF2CC", fg="7F6000", size=9, wrap=True)
            ws.row_dimensions[row].height = 18
            row += 1
        for p in _no_dxf:
            ws.merge_cells(f"B{row}:L{row}")
            _c(ws, row, 1, "✗", bg="FFC7CE", align="center", size=9)
            _c(ws, row, 2, f"{p.get('part_number')}  —  {p.get('description')}  |  "
               f"NO DXF + could not infer — PRICE MANUALLY (currently £0)",
               bg="FFC7CE", fg="9C0006", size=9, wrap=True)
            ws.row_dimensions[row].height = 18
            row += 1
    # ── Cost breakdown by material ─────────────────────────────────────────────
    row += 2
    ws.merge_cells(f"A{row}:L{row}")
    # Named base. These are engine per-part figures and the percentages are shares of their
    # own sum — not of the Sell Price in the total row above, which is a different number.
    # An unlabelled "%" next to an unlabelled "£" invited exactly that reading.
    _c(ws, row, 1,
       "COST BREAKDOWN BY MATERIAL TYPE"
       + ("  —  engine per-part basis; % of the engine part-sum, not of the Sell Price"
          if _totals["source"] == "excel_calculated" else ""),
       bold=True, bg=C_BLUE, fg=C_WHITE, size=11)
    ws.row_dimensions[row].height = 20
    row += 1
    mat_totals: Dict[str, float] = {}
    for part in parts:
        # Group bought-ins together rather than under a mis-inferred "MILD_STEEL".
        if _is_bought_in(part):
            mat = "Bought-in"
        else:
            mat = str(part.get("normalized_material") or part.get("material") or "Unknown")
        ext  = float(_est_lookup.get(part.get("part_number"), {}).get("extended_total_cost_gbp") or 0)
        mat_totals[mat] = mat_totals.get(mat, 0) + ext
    for mi, (mat, cost) in enumerate(sorted(
            mat_totals.items(), key=lambda x: x[1], reverse=True)):
        bg = C_ALT if mi % 2 == 0 else C_WHITE
        pct = (cost / total * 100) if total > 0 else 0
        ws.merge_cells(f"A{row}:H{row}")
        _c(ws, row, 1, mat, bg=bg, bold=True, size=10, border=True)
        _c(ws, row, 9, cost, bg=bg, align="right", bold=True,
           num_fmt="£#,##0.00", size=10, border=True)
        _c(ws, row, 10, "", bg=bg, border=True)
        _c(ws, row, 11, f"{pct:.1f}%", bg=bg, align="center",
           size=10, border=True)
        _c(ws, row, 12, "", bg=bg, border=True)
        ws.row_dimensions[row].height = 18
        row += 1
    # ── Footer ─────────────────────────────────────────────────────────────────
    row += 2
    ws.merge_cells(f"A{row}:L{row}")
    _c(ws, row, 1,
       f"Generated by SDI Intelligence  |  wearesdi.com  |  "
       f"{datetime.now().strftime('%d/%m/%Y %H:%M')}  |  "
       f"Estimates based on SolidWorks drawings + SDILive knowledge base  |  "
       f"Subject to estimator review before quoting",
       size=8, italic=True, fg="888888", align="center")
    ws.freeze_panes = "A6"


if __name__ == "__main__":
    print("SDI Intelligence — Job Decision Report module ready.")
    print()
    print("Add to estimator.py before wb.save():")
    print("  from job_decision_report import add_decision_report_sheet")
    print("  add_decision_report_sheet(wb, summary, scan_meta)")
