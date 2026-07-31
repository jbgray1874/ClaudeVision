"""
SDI Intelligence — Estimation Provenance Report
===========================================
Generates a detailed "how we got there" report alongside
every estimate xlsx. Shows exactly where each material,
thickness, cost and operation came from.
Critical for:
  - MD/FD confidence in AI estimates
  - Estimator trust and verification
  - Learning system audit trail
  - Identifying where AI is uncertain
Output: Added as extra sheet "AI Provenance" in estimate xlsx
        AND as a standalone PDF report (optional)
Called from estimator.py after xlsx is written.
"""
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
try:
    import openpyxl
    from openpyxl.styles import (Font, PatternFill, Alignment,
                                  Border, Side, GradientFill)
    from openpyxl.utils import get_column_letter
    _XLSX_OK = True
except ImportError:
    _XLSX_OK = False
try:
    import corrections_db as db
    _DB_OK = True
except ImportError:
    _DB_OK = False

# Reuse the SAME bought-in detection + WB Sell Price finder proven on the Decision
# Report — one source of truth, so both supplementary sheets behave identically.
# Fallbacks keep this module importable if job_decision_report is unavailable.
try:
    from job_decision_report import (_is_bought_in, _find_wb_sell_price_ref,
                                     replace_generated_sheet)
except Exception:  # pragma: no cover - defensive
    def _is_bought_in(part: Dict) -> bool:
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

    def replace_generated_sheet(wb, title):
        if title in wb.sheetnames:
            del wb[title]
        for _n in [n for n in wb.sheetnames
                   if n.startswith(title) and n[len(title):].isdigit()]:
            del wb[_n]
        return wb.create_sheet(title)

    def _find_wb_sell_price_ref(wb):
        try:
            ws = None
            for name in ("Estimate", "estimate"):
                if name in wb.sheetnames:
                    ws = wb[name]
                    break
            if ws is None:
                return None
            for r in ws.iter_rows():
                for c in r:
                    v = c.value
                    if isinstance(v, str) and "sell" in v.lower() and "price" in v.lower():
                        target_col = None
                        for cc in range(c.column + 1, c.column + 9):
                            if ws.cell(row=c.row, column=cc).value not in (None, ""):
                                target_col = cc
                                break
                        if target_col is None:
                            target_col = 13
                        return f"='{ws.title}'!{get_column_letter(target_col)}{c.row}"
            return None
        except Exception:
            return None
# ── Colours ────────────────────────────────────────────────────────────────────
C_HEADER_BG   = "1F3864"   # SDI dark navy
C_HEADER_FG   = "FFFFFF"
C_HIGH        = "C6EFCE"   # green  — high confidence
C_MEDIUM      = "FFEB9C"   # amber  — medium confidence
C_LOW         = "FFC7CE"   # red    — low confidence / needs review
C_KB          = "DDEEFF"   # blue   — from knowledge base
C_HIST        = "E8D5FF"   # purple — from historical data
C_AI          = "FFF2CC"   # yellow — AI inference
C_RULE        = "D9EAD3"   # light green — override rule fired
C_BOUGHT      = "EDEDED"   # grey   — bought-in / catalogue component
C_SECTION     = "2F5496"   # section header blue
C_ALT_ROW     = "F5F5F5"   # alternating row
def confidence_colour(confidence: float) -> str:
    if confidence >= 0.85:
        return C_HIGH
    elif confidence >= 0.60:
        return C_MEDIUM
    else:
        return C_LOW
def confidence_label(confidence: float) -> str:
    if confidence >= 0.85:
        return "HIGH ✓"
    elif confidence >= 0.60:
        return "MEDIUM"
    else:
        return "LOW — REVIEW"
def source_label(source: str) -> str:
    """Human-readable explanation of where a value came from."""
    s = str(source or "").lower()
    if "knowledge_base" in s:
        return "SDI Knowledge Base (previously confirmed)"
    elif "override_rule" in s:
        name = re.search(r'override_rule:(.+)', s)
        rule = name.group(1) if name else "learning rule"
        return f"Learning Rule fired: {rule}"
    elif "dxf_flat_pattern" in s:
        return "DXF flat pattern file (exact geometry)"
    elif "dxf_filename" in s:
        return "DXF filename material code (e.g. _MS_, PETG)"
    elif "historical" in s:
        return "Historical SDI estimate match"
    elif "pn_suffix" in s:
        return "Part number suffix (-M=Steel, -A=Acrylic, -T=MDF)"
    elif "pdf" in s:
        return "PDF drawing text extraction"
    elif "ai" in s or "inference" in s:
        return "AI inference (Claude)"
    else:
        return str(source or "AI inference")
def _price_basis_label(price_source: Dict[str, Any], material: str = "") -> str:
    """One-line 'where did this price come from?' for the provenance sheet, built
    from the engine's own per-part price_source metadata (pricing_service /
    _build_price_source_metadata). Surfaces the source the engine actually used —
    DB price book, historical quote, ERP/UDEF, config rate card — or a loud flag
    when no price source was found. No new pricing logic; display only."""
    if not price_source:
        return "—"
    src   = str(price_source.get("source_name") or "").strip()
    stype = str(price_source.get("source_type") or "").strip()
    supp  = str(price_source.get("supplier_source") or "").strip()
    pdate = str(price_source.get("price_date") or "").strip()
    low   = src.lower()
    _supp = f" — {supp}" if supp and supp.lower() not in low else ""
    if low == "fallback" or "no price" in low or "no_price" in low:
        return "⚠ No price source — add to price book"
    if "bought_in" in low:
        return f"Price book (bought-in){_supp}" + (f", {pdate}" if pdate else "")
    if "historical_quote" in low:
        return f"Historical quote{_supp}"
    if "udef" in low:
        return "UDEF parts table"
    if "pma" in low or "erp" in low:
        return "ERP parts master"
    if stype == "web_ai_fallback" or "web_ai" in low:
        return "⚠ Web/AI fallback — verify"
    if stype == "web_catalog" or "catalog" in low:
        return f"Supplier catalogue{_supp}"
    if "config" in low or stype == "config":
        return "Config rate card"
    if stype == "external":
        return (supp or src) + (f", {pdate}" if pdate else "")
    return src or "—"
def build_provenance(summary: Dict[str, Any]) -> List[Dict]:
    """
    Extract provenance data from a scan summary.
    Returns list of part provenance records.
    """
    # The canonical job part list — the same rows the Estimate sheet was built from, each
    # overlaid on its manufacturing_writeup entry so the provenance fields below survive.
    from costed_facts import job_parts as _job_parts
    parts = _job_parts(summary) or (
        (summary.get("manufacturing_writeup") or {}).get("parts") or [])
    provenance = []
    # SDI Intelligence — cost lives in estimate_summary.part_estimates, keyed by
    # part_number. Build a lookup so the provenance report shows real costs.
    # PRE-FILTER engine figures; the sheet's totals are Excel's. See the reconciliation
    # note the provenance sheet writes under its total.
    _est_lookup = {}
    for _pe in (summary.get("estimate_summary") or {}).get("part_estimates", []):
        _pn = _pe.get("part_number")
        if _pn:
            _est_lookup[_pn] = _pe
    from costed_facts import (canonical_quantity, decision_ids_for_part,
                              is_placeholder_price, operations_for_part,
                              part_material_cost, priced_route_known,
                              priced_rows_for_part)
    _canonical = priced_route_known(summary)
    for part in parts:
        pn   = part.get("part_number") or "—"
        desc = part.get("description") or "—"
        # Bought-in components carry no fabrication material — surface them honestly
        # rather than defaulting/mis-inferring MILD_STEEL (foam tape, loom, cable…).
        _bought = _is_bought_in(part)
        if _bought:
            mat = "Bought-in"
        else:
            mat = part.get("normalized_material") or part.get("material") or "Unknown"
        # Quantity PER TOP-LEVEL UNIT from the compiled hierarchy, not the BOM row's
        # per-parent figure. A part reached through a sub-assembly needs the parent's
        # multiplicity rolled in, which is what the workbook charges on; without it this
        # sheet under-states every item below the first level.
        _cq = canonical_quantity(summary, pn)
        qty  = _cq if _cq is not None else part.get("quantity", 1)
        if isinstance(qty, float) and qty.is_integer():
            qty = int(qty)
        _pe = _est_lookup.get(pn, {})
        # Material only — see costed_facts.part_material_cost. The engine's
        # unit_total_cost_gbp is labour-inclusive and reconciles to nothing on a canonical
        # job; labour lives on the department rows, not on the part.
        if _canonical:
            unit, ext = part_material_cost(part)
        else:
            unit = float(_pe.get("unit_total_cost_gbp") or 0)
            ext  = float(_pe.get("extended_total_cost_gbp") or 0)
        geo  = str(part.get("geometry_source") or "pdf")
        # Operations as the workbook ACCEPTED them, from the one shared post-costing source.
        # This tab sits inside the same .xlsx as the Estimate, so narrating the raw textual
        # + inferred lists here made one workbook describe two different routes: laser,
        # powder and weld against timber panels the Estimate sheet charges saw, glue, CNC
        # and spray for. Falls back to the raw lists only when no workbook rows exist.
        ops = operations_for_part(summary, pn, _pe)
        _ops_priced = True
        if not ops and not _canonical:
            # No workbook — nothing is priced yet, so the drawing's own reading is the best
            # available evidence. Labelled as unpriced below rather than passed off as the
            # route. Once the workbook HAS run, a part in no labour row carries no charged
            # operation, and reaching for the raw lists there is how the gated-off route —
            # powder on timber, weld/dress on artefact records — came back onto the page.
            ops = (list(part.get("textual_operations") or [])
                   + list(part.get("inferred_operations") or []))
            _ops_priced = False
        # ── Material provenance ────────────────────────────────────────────────
        if _bought:
            mat_source_str = "Bought-in / catalogue component — no fabrication material"
            mat_conf       = 1.0
        else:
            mat_source   = part.get("material_source") or geo
            mat_conf     = 0.9 if "knowledge_base" in mat_source else \
                           0.95 if "dxf_filename" in mat_source or "dxf_flat" in geo else \
                           0.7  if "pn_suffix" in mat_source else \
                           0.6  if "pdf" in geo else 0.5
            mat_source_str = source_label(mat_source)
        # ── Thickness provenance ───────────────────────────────────────────────
        # DXF filename FIRST — most reliable, and avoids real 2mm/3mm acrylic
        # being wrongly stripped as tolerance-table values.
        import re as _re
        thk_val = None
        thk_source = "Not extracted (tolerance table only)"
        if _bought:
            thk_source = "— bought-in component (no fabrication thickness)"
        else:
            _dfn = str(part.get("dxf_source_file") or "")
            _tm = _re.search(r"[_\-\s](\d+\.?\d*)\s*mm", _dfn, _re.IGNORECASE)
            if _tm:
                _tv = float(_tm.group(1))
                if 0.3 <= _tv <= 25.0:
                    thk_val = _tv
                    thk_source = f"DXF filename ({_dfn})"
            if thk_val is None:
                thicknesses = part.get("thicknesses_mm") or []
                tol_set     = {0.5, 1.0, 1.5, 2.0, 3.0}
                _t_set      = {round(float(t),1) for t in thicknesses if t}
                # Only strip tolerance values if the FULL sequence is present;
                # a standalone 2.0/3.0 is a real thickness.
                if tol_set.issubset(_t_set):
                    thk_clean = [t for t in thicknesses
                                 if t and round(float(t), 1) not in tol_set]
                else:
                    thk_clean = [t for t in thicknesses if t]
                if thk_clean:
                    thk_val = thk_clean[0]
                    thk_source = "DXF geometry" if "dxf" in geo else "PDF text"
        thk_conf     = 0.95 if "dxf" in thk_source.lower() else \
                       0.7  if thk_val else 0.2
        # ── Geometry provenance ────────────────────────────────────────────────
        geo_data     = part.get("geometry_rollup") or {}
        cut_len      = float(geo_data.get("estimated_cut_length_mm") or 0)
        n_holes      = int(geo_data.get("estimated_hole_count") or 0)
        n_bends      = int(geo_data.get("estimated_bend_line_count") or 0)
        geo_conf_raw = float((geo_data.get("confidence") or {})
                             .get("estimated_cut_length_mm") or
                             geo_data.get("geometry_reliability") or 0)
        if _bought:
            geo_source = "— bought-in component (no fabrication geometry)"
        else:
            geo_source = "DXF flat pattern (exact)" if "dxf" in geo else \
                         f"PDF vector extraction (reliability {geo_conf_raw:.0%})"
        # ── Cost provenance ────────────────────────────────────────────────────
        hist_match   = None
        if _DB_OK and pn and pn != "—":
            hist_match = db.get_historical_cost(part_number=pn)
        # ── Flags ──────────────────────────────────────────────────────────────
        flags = []
        learning_flag = part.get("_learning_flag") or ""
        if learning_flag:
            flags.extend(learning_flag.split(" | "))
        # Bought-in components are catalogue-priced with no fabrication geometry, so
        # the zero-cost / unresolved-material / no-thickness review flags do not apply.
        if not _bought:
            if unit == 0.0 and mat not in ("BOUGHT_IN",):
                flags.append("Zero cost — thickness or geometry missing")
            if mat in ("Unknown", "UNKNOWN", "LED", "CARD"):
                flags.append(f"Material unresolved: {mat!r}")
            if not thk_val and mat in ("MILD_STEEL", "ACRYLIC", "MDF"):
                flags.append("No thickness extracted — manual review needed")
        # ── Override rules that fired ──────────────────────────────────────────
        # Skip for bought-ins — the DXF-token material codes never apply to them.
        overrides_fired = []
        if not _bought:
            if "override_rule:" in str(part.get("material_source") or ""):
                rule_name = str(part.get("material_source")).split("override_rule:")[-1]
                overrides_fired.append(f"Material rule: {rule_name}")
            if part.get("dxf_source_file"):
                dxf = part["dxf_source_file"].upper()
                if "_MS_" in dxf:
                    overrides_fired.append("DXF filename _MS_ → MILD_STEEL")
                elif "PETG" in dxf:
                    overrides_fired.append("DXF filename PETG → ACRYLIC")
                elif "JOINERY" in dxf:
                    overrides_fired.append("DXF filename JOINERY → MDF")
        # ── Overall confidence ─────────────────────────────────────────────────
        if _bought:
            overall_conf = 1.0
        else:
            overall_conf = min(mat_conf, thk_conf if thk_val else 0.6,
                               geo_conf_raw if geo_conf_raw > 0 else 0.7)
        # ── Rate / price source ────────────────────────────────────────────────
        # The engine tags every price with a source; it lives on the material
        # estimate (part_estimate.material_estimate.price_source), not top-level.
        _ps = ((_pe.get("material_estimate") or {}).get("price_source")
               or _pe.get("price_source") or {})
        rate_basis = _price_basis_label(_ps, mat)
        # ── Route text, and the audit trail behind it ──────────────────────────
        _ops_text = (", ".join(ops) if ops
                     else ("none charged" if _canonical else "—"))
        if not _ops_priced:
            _ops_text += "  (read from drawing — not yet priced)"
        if not _canonical:
            _priced_by = "— no workbook built"
        else:
            _rows_for_part = priced_rows_for_part(summary, pn)
            _wb_rows = sorted({int(float(r["workbook_row"])) for r in _rows_for_part
                               if r.get("workbook_row")})
            _dids = decision_ids_for_part(summary, pn)
            if _wb_rows or _dids:
                _priced_by = "\n".join(filter(None, [
                    ("Estimate row " + ", ".join(str(r) for r in _wb_rows)) if _wb_rows else "",
                    " · ".join(_dids) if _dids else "",
                ]))
            else:
                _priced_by = "not priced on any labour row"
        provenance.append({
            "part_number":       pn,
            "rate_basis":        rate_basis,
            "description":       desc,
            "quantity":          qty,
            "material":          mat,
            "material_source":   mat_source_str,
            "material_conf":     mat_conf,
            "thickness_mm":      thk_val,
            "thickness_source":  thk_source,
            "thickness_conf":    thk_conf,
            "cut_length_mm":     cut_len,
            "n_holes":           n_holes,
            "n_bends":           n_bends,
            "geometry_source":   geo_source,
            "geometry_conf":     geo_conf_raw,
            "dxf_file":          part.get("dxf_source_file") or "—",
            "operations":        _ops_text,
            # Part -> the Estimate rows charging it -> the compiler decisions behind them.
            "priced_by":         _priced_by,
            "unit_cost":         unit,
            "extended_cost":     ext,
            "overall_confidence":overall_conf,
            "is_bought_in":      _bought,
            "flags":             flags,
            "overrides_fired":   overrides_fired,
            "historical_match":  hist_match,
        })
    return provenance
def add_provenance_sheet(wb, summary: Dict[str, Any],
                          scan_meta: Dict[str, Any] = None) -> None:
    """
    Add an 'AI Provenance' sheet to an existing openpyxl workbook.
    Call this after the main estimate sheet is written.
    """
    if not _XLSX_OK:
        return
    provenance = build_provenance(summary)
    if not provenance:
        return
    ws = replace_generated_sheet(wb, "AI Provenance")
    scan_meta = scan_meta or {}

    # Authoritative total = the WB's Sell Price, found by label so it survives layout
    # shifts. If present we write a LIVE cross-sheet formula (Excel computes on open),
    # so this sheet agrees with the WB and the Decision Report. Else fall back below.
    _sell_ref = _find_wb_sell_price_ref(wb)
    from costed_facts import job_totals
    _totals = job_totals(summary)

    # THE HEADLINE FIGURE IS THE WORKBOOK'S.
    #
    # This summed the part column and called the result "Est. Total / engine part-sum".
    # Once that column became material-only the label was wrong twice over: it is not the
    # engine part-sum, and it is not a job total — driven with a workbook unit cost of
    # £6.33 and £0.10 of part material, this sheet printed "Est. Total: £0.10". The
    # Decision Report already prefers the workbook; this is the same hierarchy.
    _part_material_total = sum(p["extended_cost"] for p in provenance)
    _wb_unit = _totals.get("unit_gbp")
    _engine_total = float(_wb_unit) if _wb_unit is not None else _part_material_total

    def cell(row, col, value="", bold=False, bg=None, fg="000000",
             align="left", wrap=False, size=10, border=False, num_fmt=None):
        c = ws.cell(row=row, column=col, value=value)
        c.font = Font(name="Calibri", bold=bold, color=fg, size=size)
        if bg:
            c.fill = PatternFill("solid", fgColor=bg)
        c.alignment = Alignment(horizontal=align, vertical="center",
                                 wrap_text=wrap)
        if num_fmt:
            c.number_format = num_fmt
        if border:
            thin = Side(style="thin", color="BBBBBB")
            c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        return c
    # ── Title block ────────────────────────────────────────────────────────────
    ws.merge_cells("A1:O1")
    cell(1, 1, "SDI Intelligence — Estimate Provenance Report",
         bold=True, bg=C_HEADER_BG, fg=C_HEADER_FG, align="center", size=13)
    ws.row_dimensions[1].height = 28
    ws.merge_cells("A2:O2")
    pdf_name = scan_meta.get("pdf_name") or summary.get("source_file") or "—"
    job_no   = scan_meta.get("job_number") or "—"
    scan_dt  = scan_meta.get("scan_date") or datetime.now().strftime("%d/%m/%Y %H:%M")
    # Header total text: prefer the WB Sell Price label when we can reference it.
    _tot_txt = ("Sell Price: see Estimate sheet (mirrored below)"
                if _sell_ref else
                f"Unit cost (calculated by the Estimate sheet): £{_engine_total:.2f}"
                if _wb_unit is not None else
                f"Part material only — no workbook total: £{_engine_total:.2f}")
    cell(2, 1,
         f"Drawing: {pdf_name}   |   Job: {job_no}   |   Scanned: {scan_dt}   |   "
         f"Parts: {len(provenance)}   |   {_tot_txt}",
         bg="2F5496", fg=C_HEADER_FG, align="center", size=10)
    ws.row_dimensions[2].height = 18
    # ── Legend ─────────────────────────────────────────────────────────────────
    ws.merge_cells("A3:O3")
    cell(3, 1,
         "CONFIDENCE KEY:   🟢 HIGH ≥85%  (Knowledge Base / DXF file)     "
         "🟡 MEDIUM 60-85%  (PDF extraction / PN suffix)     "
         "🔴 LOW <60%  (AI inference only — review recommended)",
         bg="F0F0F0", align="left", size=9)
    ws.row_dimensions[3].height = 16
    ws.row_dimensions[4].height = 6  # spacer
    # ── Column headers ─────────────────────────────────────────────────────────
    # The money columns are the ENGINE's per-part figures. Once Excel has calculated the
    # sheet they are not what the job is charged, and a column headed plainly "Unit £" next
    # to a Sell Price that disagrees is the report contradicting itself.
    from costed_facts import priced_route_known as _prk
    _money_basis = " material" if _prk(summary) else ""
    headers = [
        ("Part Number",       15), ("Description",     28), ("Qty", 5),
        ("Material",          14), ("Mat. Source",      32), ("Conf.",  8),
        ("Thickness",          9), ("Thk. Source",      22), ("Geometry Source", 26),
        ("Cut (mm)",          10), ("Ops",              22),
        (f"Unit £{_money_basis}",  11), (f"Ext £{_money_basis}", 11),
        ("Rate / source",     34), ("Priced by — sheet row / decision", 26),
    ]
    for ci, (hdr, width) in enumerate(headers, 1):
        c = cell(5, ci, hdr, bold=True, bg=C_SECTION, fg=C_HEADER_FG,
                 align="center", size=10)
        ws.column_dimensions[get_column_letter(ci)].width = width
    ws.row_dimensions[5].height = 20
    # ── Part rows ──────────────────────────────────────────────────────────────
    row = 6
    for i, p in enumerate(provenance):
        bg = C_ALT_ROW if i % 2 == 0 else "FFFFFF"
        # Bought-ins get a neutral grey; fabricated parts keep the confidence colour.
        conf_bg = C_BOUGHT if p.get("is_bought_in") else confidence_colour(p["overall_confidence"])
        cell(row, 1,  p["part_number"],        bg=bg,       border=True)
        cell(row, 2,  p["description"],        bg=bg,       border=True, wrap=True)
        cell(row, 3,  p["quantity"],            bg=bg,       align="center", border=True)
        cell(row, 4,  p["material"],            bg=conf_bg,  bold=True, border=True)
        cell(row, 5,  p["material_source"],     bg=conf_bg,  border=True, wrap=True, size=9)
        cell(row, 6,  "—" if p.get("is_bought_in") else f"{p['material_conf']:.0%}",
                                                bg=conf_bg,  align="center", border=True)
        cell(row, 7,  f"{p['thickness_mm']}mm" if p["thickness_mm"] else "—",
                                                bg=bg,       align="center", border=True)
        cell(row, 8,  p["thickness_source"],    bg=bg,       border=True, size=9, wrap=True)
        cell(row, 9,  p["geometry_source"],     bg=bg,       border=True, size=9, wrap=True)
        cell(row, 10, f"{p['cut_length_mm']:.0f}" if p["cut_length_mm"] else "—",
                                                bg=bg,       align="right", border=True)
        cell(row, 11, p["operations"],          bg=bg,       border=True, size=9, wrap=True)
        cell(row, 12, f"£{p['unit_cost']:.2f}", bg=bg,       align="right",
             bold=True, border=True)
        cell(row, 13, f"£{p['extended_cost']:.2f}", bg=bg,   align="right",
             bold=True, border=True)
        _rb = p.get("rate_basis") or "—"
        cell(row, 14, _rb, bg=(C_LOW if _rb.startswith("⚠") else bg),
             border=True, size=9, wrap=True)
        cell(row, 15, p.get("priced_by") or "—", bg=bg, border=True, size=8, wrap=True)
        ws.row_dimensions[row].height = 28
        row += 1
        # ── Flags / warnings ───────────────────────────────────────────────────
        if p["flags"]:
            for flag in p["flags"]:
                ws.merge_cells(f"B{row}:O{row}")
                cell(row, 1, "⚠",              bg=C_LOW, align="center", size=9)
                cell(row, 2, f"REVIEW: {flag}", bg=C_LOW, size=9, wrap=True)
                ws.row_dimensions[row].height = 16
                row += 1
        # ── Override rules that fired ──────────────────────────────────────────
        if p["overrides_fired"]:
            ws.merge_cells(f"B{row}:O{row}")
            cell(row, 1, "🧠",                  bg=C_RULE, align="center", size=9)
            cell(row, 2, "Learning: " + " | ".join(p["overrides_fired"]),
                 bg=C_RULE, size=9)
            ws.row_dimensions[row].height = 14
            row += 1
        # ── Historical matches ─────────────────────────────────────────────────
        if p["historical_match"]:
            for hm in (p["historical_match"] or [])[:2]:
                avg  = hm.get("AvgCost") or hm.get("avg_cost") or 0
                cnt  = hm.get("SampleCount") or hm.get("sample_count") or 0
                hmat = hm.get("Material") or hm.get("material") or "?"
                ws.merge_cells(f"B{row}:O{row}")
                cell(row, 1, "📚",              bg=C_HIST, align="center", size=9)
                cell(row, 2,
                     f"Historical: {cnt} SDI estimate(s) for this part as "
                     f"{hmat} — avg £{avg:.2f}",
                     bg=C_HIST, size=9)
                ws.row_dimensions[row].height = 14
                row += 1
    # ── Summary footer ─────────────────────────────────────────────────────────
    row += 1
    ws.merge_cells(f"A{row}:L{row}")
    # Authoritative total: WB Sell Price (live formula) when found, else engine sum.
    _total_label = ("SELL PRICE (from Estimate sheet)" if _sell_ref
                    else "UNIT COST (calculated by the Estimate sheet)" if _wb_unit is not None
                    else "PART MATERIAL ONLY — no workbook total")
    cell(row, 1,  _total_label, bold=True, bg=C_HEADER_BG, fg=C_HEADER_FG,
         align="right", size=11)
    if _sell_ref:
        cell(row, 13, _sell_ref, bold=True, bg=C_HEADER_BG, fg=C_HEADER_FG,
             align="right", size=12, num_fmt="£#,##0.00")
    else:
        cell(row, 13, f"£{_engine_total:.2f}",  bold=True, bg=C_HEADER_BG, fg=C_HEADER_FG,
             align="right", size=12)
    ws.row_dimensions[row].height = 22
    # Two calculators on one page. The Ext £ column sums the engine's per-part figures; the
    # total row shows what Excel computed from the accepted labour and material rows. They
    # differ, and saying which is authoritative is not optional on a sheet whose whole
    # purpose is to be checkable.
    if _totals["source"] == "excel_calculated":
        row += 1
        ws.merge_cells(f"A{row}:O{row}")
        # Same basis as the Decision Report: reconcile the MATERIAL column against the
        # sheet's material total, and state labour as what it is — a department-row charge
        # with no per-part figure. The engine part-sum is an obsolete labour-inclusive
        # number and is deliberately not quoted here.
        _mat, _lab = _totals.get("material_gbp"), _totals.get("labour_gbp")
        _col_mat = sum(float(p.get("extended_cost") or 0) for p in provenance)
        _mat_txt = (f"The material column above sums to £{_col_mat:,.2f} against the "
                    f"sheet's £{float(_mat):,.2f}. " if _mat is not None else "")
        _lab_txt = (f"Labour is £{float(_lab):,.2f}, charged per department row across "
                    f"every part in that setup — see 'Priced by' for the rows and "
                    f"decisions behind each part. " if _lab is not None else "")
        cell(row, 1,
             f"RECONCILIATION — the Estimate sheet calculated "
             f"£{float(_totals.get('unit_gbp') or 0):,.2f} per unit. "
             f"{_mat_txt}{_lab_txt}The workbook is authoritative.",
             bg=C_KB, size=9, wrap=True)
        ws.row_dimensions[row].height = 32
    row += 2
    ws.merge_cells(f"A{row}:O{row}")
    high_count = sum(1 for p in provenance if p["overall_confidence"] >= 0.85)
    med_count  = sum(1 for p in provenance if 0.60 <= p["overall_confidence"] < 0.85)
    low_count  = sum(1 for p in provenance if p["overall_confidence"] < 0.60)
    cell(row, 1,
         f"Confidence summary:  "
         f"🟢 HIGH: {high_count} parts   "
         f"🟡 MEDIUM: {med_count} parts   "
         f"🔴 LOW: {low_count} parts   |   "
         f"Generated by SDI Intelligence  |  {datetime.now().strftime('%d/%m/%Y %H:%M')}",
         bg="F0F0F0", size=9, align="left")
    # Freeze panes below header + column A
    ws.freeze_panes = "B6"
    # Tab colour
    ws.sheet_properties.tabColor = "1F3864"
def generate_standalone_report(summary: Dict[str, Any],
                                output_path: str,
                                scan_meta: Dict[str, Any] = None) -> str:
    """
    Generate a standalone provenance xlsx report.
    Returns path to created file.
    """
    if not _XLSX_OK:
        print("[provenance] openpyxl not available")
        return ""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cover"
    # Simple cover page
    ws["A1"] = "SDI Intelligence Estimation Provenance Report"
    ws["A2"] = f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws["A3"] = f"Drawing: {(scan_meta or {}).get('pdf_name', '—')}"
    ws["A4"] = f"Job: {(scan_meta or {}).get('job_number', '—')}"
    add_provenance_sheet(wb, summary, scan_meta)
    wb.save(output_path)
    print(f"[provenance] Report saved: {output_path}")
    return output_path
if __name__ == "__main__":
    print("SDI Intelligence Provenance Report module ready.")
    print()
    print("Integration into estimator.py:")
    print("  from estimation_report import add_provenance_sheet")
    print("  # After writing main estimate sheet:")
    print("  add_provenance_sheet(wb, summary, scan_meta)")
    print("  wb.save(xlsx_path)")
