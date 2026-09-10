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
def _powder_labour_gbp(summary: Dict[str, Any]) -> float:
    """What the sheet charges for the coating OPERATION, which is not the consumable.

    A CONSUMABLE AND AN OPERATION ARE NOT THE SAME CHARGE, AND ONE SENTENCE CANNOT SPEAK FOR
    BOTH. The material reconciliation asks whether powder is in the MATERIAL total, and when
    the answer was no it declared the job carried none at all — on 0359342, whose Labour block
    charges GBP 224.79 of P.Coat across 122 components. The claim was true of the column and
    false of the job, and the reader had no way to tell which was meant.

    So the sentence asks this too, and names the labour figure when there is one. Matched on
    the operation/department text rather than a single rate code, because the coating row
    reaches the read-back as powder_coating, "P.Coat" and "P/C" depending on which witness
    filled it.
    """
    total = 0.0
    try:
        from costed_facts import _final_estimate_of as _fe_of
        for row in (_fe_of(summary).get("labour_rows") or []):
            if not isinstance(row, dict):
                continue
            text = " ".join(str(row.get(k) or "") for k in
                            ("operation", "description", "department", "dept")).upper()
            if "POWDER" in text or "P.COAT" in text or "P/C" in text:
                total += float(row.get("total_value_gbp") or 0)
    except Exception:                                            # noqa: BLE001
        return 0.0
    return round(total, 2)


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


# The PHYSICAL FACTS the engine read off the drawing and model — what the part is made of, how
# thick, and its geometry. Kept separate from whether a rate has been typed (pricing) and from
# what is DONE to the part (route is a decision, reported on the Decisions tab, not a read), so a
# strong read is never hidden behind a pending price or a routine BOM-sourced route.
_READING_FIELDS = frozenset({"material identity", "thickness", "geometry"})


def reading_and_pricing_counts(provenance):
    """Split a job's parts into a READING readout (how well the engine pulled material,
    thickness, geometry and route off the drawing/model) and a PRICING readout (how many lines
    are priced versus waiting on the estimator's rate).

    Reading is scored on its own fields only — never on the price. An estimate is EXPECTED to
    arrive with prices pending; folding that into one weakest-link band is what made a fully-read
    job report '0 HIGH / 22 LOW' and read as an engine failure. Returns a dict of six counts."""
    from confidence import (STATUS_ORDER, MEASURED, CONFIRMED, REPORTED, UNKNOWN)

    def _weakest(statuses):
        real = [s for s in statuses if s in STATUS_ORDER]
        return min(real, key=STATUS_ORDER.index) if real else None

    out = {"read_high": 0, "read_med": 0, "read_low": 0, "priced": 0, "pending": 0}
    for _p in (provenance or []):
        _fields = _p.get("fields") or []
        _r = _weakest([f.get("status") for f in _fields
                       if f.get("field") in _READING_FIELDS])
        if _r in (MEASURED, CONFIRMED):
            out["read_high"] += 1
        elif _r == REPORTED:
            out["read_med"] += 1
        elif _r is not None:
            out["read_low"] += 1
        # AWAITING A RATE IS NOT THE SAME AS CARRYING NO NUMBER. This counted every row whose
        # "material price" field read UNKNOWN as pending — which swept in the nest pointers
        # (a fabricated leaf costed in the Sheet Steel block), the assembly parent (£0, its
        # material is its children's) and any duplicate. Those are correctly nil, owned by
        # NOBODY, and putting them on "awaiting your rate" is exactly why the footer said 5
        # while the honest gap list is 2. A positive price, or a stated (non-UNKNOWN) price
        # field, is priced; an otherwise-blank row is pending ONLY when a person (estimator or
        # engine) owns it, per the SAME canonical classifier the row already carries — never
        # when it is correctly nil.
        _mp = next((f.get("status") for f in _fields
                    if f.get("field") == "material price"), None)
        _unit = _p.get("unit_cost") or _p.get("extended_cost") or 0
        try:
            _unit_num = float(_unit)
        except (TypeError, ValueError):
            _unit_num = 0.0
        _owner = str((_p.get("unpriced_reason") or {}).get("owner") or "").lower()
        if _unit_num > 0 or (_mp is not None and _mp != UNKNOWN):
            out["priced"] += 1
        elif _owner == "nobody":
            pass                                    # correctly nil — awaiting no one
        else:
            out["pending"] += 1
    return out
def source_label(source: str) -> str:
    """Human-readable explanation of where a value came from.

    THE ONE VOCABULARY FIRST. source_precedence is where every source name is defined and
    displayed; this chain is older than it and had drifted into a second, partial copy —
    `dxf_matched_no_geometry` matched none of its branches and fell through to `return
    str(source)`, so the raw identifier printed in the Mat. Source column of the tab whose
    whole purpose is saying where numbers came from.

    AND IT NAMED THE WRONG MODEL. The final branch read "AI inference (Claude)". This engine's
    vision reader is Grok, on the xAI API; the name has been wrong on every provenance sheet
    it has ever written, and it is the kind of error that ends a conversation with an estimator
    who spots it. source_precedence has said "Grok (xAI)" all along.

    The chain below is kept for the keys source_precedence does not hold — override_rule with
    its payload, pn_suffix, historical — which are real and have no entry there.
    """
    try:
        from source_precedence import SOURCE_DISPLAY_NAME, display_name
        _key = str(source or "").strip().lower()
        if _key in SOURCE_DISPLAY_NAME:
            return display_name(_key)
    except ImportError:
        pass
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
        return "engine inference"
    # A NAME NOBODY HAS WRITTEN UP IS NOT A LABEL. Returning the raw key put
    # `dxf_matched_no_geometry` in a column an estimator reads; saying the source is
    # unrecognised is honest and puts the gap where somebody will fill it in.
    elif s:
        return f"{s.replace('_', ' ')} (source name not in the glossary)"
    else:
        return "not recorded"
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
        # NOT "Config rate card" — that claimed a firmness a config default does not have.
        # A config rate is an INDICATIVE hold (a standard-commodity provisional, a section/
        # linear-stock default) that an estimator or Tim overwrites; say so, as the covering
        # note and the AI Price Provenance tab now do.
        return "SDI config rate (INDICATIVE) — verify"
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
    # THE ONE RECORD. Once the sheet has been read back, the money on this tab is the
    # money the sheet CHARGED — the nest figure for a sheet part, the section figure for
    # a tube — joined to the canonical part. The engine's own net-part figure is kept in
    # the rate column, labelled as not charged, so the two calculators are shown as two
    # calculators rather than the smaller one presented as the provenance of the larger.
    try:
        from costed_facts import (record_lines as _record_lines,
                                  charged_material_rows_present as _charged_present)
        _rec = _record_lines(summary) if _canonical else {}
        _charged = bool(_charged_present(summary)) if _canonical else False
    except Exception:                                            # noqa: BLE001
        _rec, _charged = {}, False

    # WHICH DRAWING EACH PART CAME FROM — the same reader the covering note and section 9 of
    # the report use, so the three surfaces cannot name different files for one part. Two
    # records of one fact is the defect this tab exists to expose; it must not be one.
    try:
        from estimate_explained import _page_index as _pgidx
        from estimate_explained import _pack_files as _packf
        from estimate_explained import _sources_of as _srcof
        _pack, _pages = _packf(summary), _pgidx(summary)
    except Exception:                                            # noqa: BLE001
        _srcof, _pack, _pages = None, [], {}

    # THE ESTIMATOR'S ACTION, PER LINE, from the record's decision list — the same list the
    # report leads with and the e-mail panel prints. A line with nothing to do says so.
    _actions: Dict[str, List[str]] = {}
    try:
        from costed_facts import costed_job as _cj
        for _d in (_cj(summary).get("decisions_required") or []):
            if isinstance(_d, dict) and _d.get("part"):
                _actions.setdefault(str(_d["part"]).strip().upper(), []).append(
                    str(_d.get("action") or "").strip())
    except Exception:                                            # noqa: BLE001
        _actions = {}

    def _action_for(_pn: Any) -> str:
        acts = [a for a in _actions.get(str(_pn or "").strip().upper(), []) if a]
        return "; ".join(dict.fromkeys(acts)) if acts else "none — priced from the sheet"

    def _drawing_files_for(part: Dict[str, Any], bought: bool) -> str:
        if _srcof is None:
            return ""
        try:
            found = _srcof(part, _pack, _pages)
        except Exception:                                        # noqa: BLE001
            return ""
        if found:
            return "\n".join(found[:4]) + (
                f"\n…and {len(found) - 4} more" if len(found) > 4 else "")
        # A bought-in has no drawing of its own and never will. Saying "not recorded" about
        # one reads as a gap somebody should close, and there is nothing to close.
        return "bought in — no drawing of its own" if bought else "not recorded"

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
        _line = _rec.get(str(pn).strip().upper()) if _rec else None
        # A commercial line or a subcontract service is not made of anything; the record
        # says what kind of line it is, and MILD STEEL beside PACKAGING is the defect.
        _line_kind = str((_line or {}).get("kind") or "") if _line is not None else ""
        if _line_kind in ("commercial", "service"):
            mat = str(_line.get("material_label") or mat)
        _engine_unit, _engine_ext = part_material_cost(part)
        if _canonical:
            unit, ext = _engine_unit, _engine_ext
            if _charged and _line is not None and _line.get("charged_ext_gbp") is not None:
                unit = float(_line.get("charged_unit_gbp") or 0.0)
                ext = float(_line.get("charged_ext_gbp") or 0.0)
        else:
            unit = float(_pe.get("unit_total_cost_gbp") or 0)
            ext  = float(_pe.get("extended_total_cost_gbp") or 0)
        geo  = str(part.get("geometry_source") or "pdf")
        # Operations as the workbook ACCEPTED them, from the one shared post-costing source.
        # This tab sits inside the same .xlsx as the Estimate, so narrating the raw textual
        # + inferred lists here made one workbook describe two different routes: laser,
        # powder and weld against timber panels the Estimate sheet charges saw, glue, CNC
        # and spray for. Falls back to the raw lists only when no workbook rows exist.
        #
        # FROM THE DECISIONS, NOT THE DEPARTMENT INVERTED. The Tubebend row inverted to
        # tube_bending, tubebend, folding AND fold — the fold the route had ruled out, on
        # the tab that documents the route. The record names the operation the decision
        # on the row says.
        ops = (list(_line.get("operations") or []) if _line is not None and _canonical
               else operations_for_part(summary, pn, _pe))
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
        # ONE SHARED ASSESSMENT, FIELD BY FIELD.
        #
        # This block scored MATERIAL confidence from `geometry_source` — "dxf_flat" in geo
        # raised it to 95% — while printing the label from `material_source`. The score and
        # the label described different fields, so the 95% was never a statement about the
        # material at all. And a bought-in scored 1.0 for being bought-in, which is how two
        # unpriced placeholders were counted among the job's HIGH-confidence parts.
        from confidence import assess_part as _assess
        _assessment = _assess(part, summary)
        _by_field = {f["field"]: f for f in _assessment["fields"]}
        _mat_field = _by_field.get("material identity") or {}
        if _bought:
            mat_source_str = "Bought-in / catalogue component — no fabrication material"
        else:
            # NOT `or geo`. Where no material source was recorded this fell back to the
            # GEOMETRY source, which is a different question about a different field: knowing
            # a blank was measured off a DXF says nothing about who decided the part is mild
            # steel. On 10575-01-001 that put `dxf_matched_no_geometry` in the Mat. Source
            # column — a geometry state, reported as the material's provenance.
            mat_source_str = source_label(part.get("material_source"))
        # A commercial line or a subcontract service is not made of anything; the record
        # says what kind of line it is, and MILD STEEL beside PACKAGING is the defect.
        if _line_kind == "commercial":
            mat_source_str = "a commercial allowance — no fabrication material"
        elif _line_kind == "service":
            mat_source_str = "a subcontract service on the parts it names"
        # ── Thickness provenance ───────────────────────────────────────────────
        # DXF filename FIRST — most reliable, and avoids real 2mm/3mm acrylic
        # being wrongly stripped as tolerance-table values.
        import re as _re
        thk_val = None
        thk_source = "Not extracted (tolerance table only)"
        if _bought:
            thk_source = "— bought-in component (no fabrication thickness)"
        else:
            # THE ARBITRATED DATUM FIRST, exactly as the Decision Report asks for it.
            #
            # This re-derived the source by parsing the DXF filename, and on 10575-02 it
            # published "DXF filename (10575-01-001_MS_1.2mm_Rev D.DXF)" against the Decision
            # Report's "from the SolidWorks model" — one part, one thickness, two tabs of one
            # workbook naming different origins for it. Both said 1.2mm; only one was
            # describing the estimate.
            #
            # The model is rank 90 and the filename rank 70, so with both reading 1.2 the model
            # wins the arbitration and the Decision Report was right. This tab simply was not
            # asking. That is the same defect 7060e27 fixed for MATERIAL in the other file —
            # a document whose purpose is provenance must READ the provenance, because two
            # readers that each guess will eventually disagree in front of an estimator
            # deciding whether to trust a number.
            _costed = part.get("normalized_thickness_mm")
            try:
                _costed = float(_costed) if _costed not in (None, "") else None
            except (TypeError, ValueError):
                _costed = None
            if _costed and _costed > 0:
                thk_val = _costed
                _tsrc = ""
                try:
                    from source_precedence import source_of, display_name as _disp
                    _tsrc = str(source_of(part, "normalized_thickness_mm") or "")
                except Exception:
                    _tsrc = ""
                thk_source = _disp(_tsrc) if _tsrc else "costed value (source not recorded)"

            _dfn = str(part.get("dxf_source_file") or "")
            if thk_val is None:
                # FALLBACK ONLY, for records with no arbitrated value — a report of an older
                # JSON, or a part the resolver never touched.
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
        _thk_field = _by_field.get("thickness") or {}
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
            # READ THE RECORD, DO NOT RE-DERIVE IT. This was:
            #     "DXF flat pattern (exact)" if "dxf" in geo else "PDF vector extraction …"
            # A substring test over a field drawing_job_merge writes in three deliberate
            # grades, so `dxf_matched_no_geometry` — which means the DXF was found and carried
            # NO geometry — printed "DXF flat pattern (exact)". The one state where "exact
            # flat pattern" is precisely the wrong claim.
            #
            # And the AI Material Detail tab asked the same field the opposite way, an exact
            # lookup over two keys defaulting to "pdf", so on 10575-01-001 one tab said `pdf`
            # and this one said `DXF flat pattern (exact)` about the same part. Two
            # derivations of one recorded fact will always eventually disagree; the fix in
            # both places is to stop deriving.
            from wb_populate import _geom_source_words
            _words = _geom_source_words(geo if geo != "pdf" else "")
            geo_source = (_words if _words != "not recorded" else
                          f"PDF vector extraction (reliability {geo_conf_raw:.0%})")
        # A SECTION IS PRICED BY LENGTH, SO THE LENGTH IS ITS GEOMETRY. The leg printed
        # 9,106 mm here — the page-summed cut path — against the 1,397 mm it was priced
        # on, and "PDF vector extraction" for a length a language model transcribed. The
        # record carries the millimetres, the rung and the reader; print those.
        _len = (_line or {}).get("length") if _line is not None else None
        if _len and _len.get("mm"):
            cut_len = float(_len["mm"])
            _prof = (_line or {}).get("section_profile") or {}
            _dims = " × ".join(str(_prof[k]) for k in ("a", "b", "t") if _prof.get(k))
            geo_source = ((f"section stock {_dims} × " if _dims else "section length ")
                          + f"{cut_len:,.0f} mm — {_len.get('source') or 'length'} read by "
                          + f"{_len.get('reader') or 'an unrecorded reader'}"
                          + (" (INDICATIVE — taken as the largest dimension)"
                             if _len.get("indicative") else ""))
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
            # A NESTED PART THE ENGINE ROUNDS TO NOTHING IS NOT A ZERO-COST REVIEW. The
            # 15.88 mm cap is £0.00 net-part and £0.04 on the sheet; it was flagged. An
            # assembly is nil by design. Only a LEAF with no money anywhere is the gap.
            _kind = str((_line or {}).get("kind") or "leaf")
            if unit == 0.0 and ext == 0.0 and mat not in ("BOUGHT_IN",) and _kind == "leaf":
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
        # The WEAKEST REQUIRED field, never a mean — and a bought-in is judged on the
        # fields it actually has, so "no fabrication thickness" cannot drag it down and
        # "it is bought-in" cannot prop it up.
        _status = _assessment["overall"]
        # ── Rate / price source ────────────────────────────────────────────────
        # The engine tags every price with a source; it lives on the material
        # estimate (part_estimate.material_estimate.price_source), not top-level.
        _ps = ((_pe.get("material_estimate") or {}).get("price_source")
               or _pe.get("price_source") or {})
        rate_basis = _price_basis_label(_ps, mat)
        # THE RECORD'S LABEL, where there is one: origin and firmness in the words every
        # other deliverable uses. Then the engine's own figure, if it differs from what
        # was charged, named as exactly that.
        _origin = (_line or {}).get("price_origin") or {}
        if _origin.get("label"):
            rate_basis = str(_origin["label"])
        if _charged and _line is not None and _line.get("charged_ext_gbp") is not None \
                and abs(_engine_ext - ext) >= 0.01:
            rate_basis += (f" · engine net-part figure £{_engine_ext:,.2f} — not charged; "
                           f"the sheet's £{ext:,.2f} is the money")
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
        _drawing_files = _drawing_files_for(part, _bought)
        provenance.append({
            "drawing_files": _drawing_files,
            "part_number":       pn,
            "rate_basis":        rate_basis,
            "description":       desc,
            "quantity":          qty,
            "material":          mat,
            "material_source":   mat_source_str,
            "material_status":   (_mat_field.get("status") or "unknown"),
            "material_reason":   (_mat_field.get("reason") or ""),
            "thickness_mm":      thk_val,
            "thickness_source":  thk_source,
            "thickness_status":  (_thk_field.get("status") or "unknown"),
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
            # The engine's own net-part figure and whether the money above is the sheet's.
            "engine_extended_cost": round(_engine_ext, 4),
            "charged":           bool(_charged and _line is not None
                                      and _line.get("charged_ext_gbp") is not None),
            # What a person has to do about this line, from the record's decisions.
            "estimator_action":  _action_for(pn),
            "overall_status":    _status,
            "overall_label":     _assessment["overall_label"],
            "overall_reason":    _assessment.get("reason") or "",
            "decided_by":        list(_assessment.get("decided_by") or []),
            "fields":            _assessment["fields"],
            "is_bought_in":      _bought,
            "flags":             flags,
            "overrides_fired":   overrides_fired,
            "historical_match":  hist_match,
            # WHY THIS LINE CARRIES NO MONEY. Computed from the part record by the SAME
            # classifier the workbook read-back and the HTML report use, rather than joined
            # back through final_estimate.material_rows — because the read-back is exactly
            # what fails when Excel is busy or a workbook will not open, and a sheet that explains
            # its blanks only when everything worked explains nothing on the runs that
            # needed it. A private second opinion here is also how two documents describing
            # one job come to disagree about which blanks are somebody's job.
            "unpriced_reason":   (_unpriced_reason_for(part)
                                  if not (unit or ext) else None),
        })
    return provenance


def _unpriced_reason_for(part: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from estimator_inputs import unpriced_reason_for_row
        return unpriced_reason_for_row(part)
    except Exception:                                    # pragma: no cover
        return {}
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
         # WHOSE QUESTION THIS TAB ANSWERS, on the line the reader already looks at.
         #
         # Eleven of the Decision Report's twelve columns are also here, and the twelfth is
         # one of these under a different name. Every deliverable has to describe the same
         # part list, so the two tabs cannot be told apart by which rows they carry — only by
         # what they are FOR. Unsaid, an estimator reads the same rows twice with no way to
         # know which to believe when they differ, which they did on 001's thickness.
         #
         # Put here rather than in a row of its own: rows 3 and 4 are both already written,
         # and inserting one silently overwrote the legend that lives below.
         # THE ONE TAB, NOW THAT THERE IS ONLY ONE. This line used to send the reader to the
         # Decision Report for what had to be decided. That tab has gone — its part list was
         # this one's part list, twenty-five rows twice — and its four unique blocks are
         # further down this sheet. Pointing at a tab the workbook no longer has is how a
         # reader concludes the file is broken.
         "THIS TAB: WHERE EVERY NUMBER CAME FROM — source, confidence, geometry, the rate "
         "that priced it. Below the totals: who decided powder, the material breakdown that "
         "adds back to the sheet's own total, and every value two sources disagreed about.\n"
         "STATUS — the WEAKEST field decides the line, never an average:   "
         "CONFIRMED/MEASURED — read from a model, a DXF or the estimators' own calculator   "
         "REPORTED — read from the drawing; reproducible, not verified   "
         "ASSUMED — a default or an inference is standing in   "
         "UNKNOWN — a required field has no reading   "
         "N/A — that field does not exist for this line",
         bg="F0F0F0", align="left", size=9)
    ws.row_dimensions[3].height = 16
    # ── THE SHEET SAYS WHEN IT COULD NOT BE CHECKED ────────────────────────────
    # The Excel read-back fails for reasons nothing to do with the estimate — an elevated
    # console, a workbook that will not open, Excel busy — and when it does, the figures on
    # this tab are the engine's PRE-Excel numbers rather than the ones the Estimate sheet
    # calculated. Those are different totals. Silence there is the worst case: the tab looks
    # exactly as it does on a run that reconciled perfectly.
    _fe = summary.get("final_estimate")
    if not isinstance(_fe, dict):
        _fe = (summary.get("estimate_summary") or {}).get("final_estimate")
    if not isinstance(_fe, dict) or not _fe:
        ws.merge_cells("A4:O4")
        cell(4, 1,
             "THE CALCULATED SHEET WAS NOT READ BACK — Excel did not return this workbook's "
             "computed totals (Excel busy or absent, or a workbook that would not open). "
             "The money columns below are the ENGINE's figures, not what the Estimate sheet "
             "calculates. Re-run once Excel can be driven before using these numbers.",
             bg=C_LOW, align="left", size=9, wrap=True)
        ws.row_dimensions[4].height = 30
    else:
        ws.row_dimensions[4].height = 6  # spacer
    # ── Column headers ─────────────────────────────────────────────────────────
    # VALUE USED → SOURCE → EVIDENCE → ESTIMATOR ACTION. Seventeen columns became these:
    # each datum sits beside the source that gave it, the money is the sheet's CHARGED
    # figure with the engine's own beside it as not charged, the confidence percentage is a
    # word about the evidence, and the last thing on the row is what a person has to do.
    from costed_facts import priced_route_known as _prk
    _canonical = bool(_prk(summary))
    headers = [
        ("Part Number",       15), ("Description",     28), ("Qty", 5),
        ("Material — source", 30), ("Thickness — source", 24),
        ("Geometry / size — source", 34), ("Operations charged", 22),
        ("Charged £ unit" if _canonical else "Engine £ unit", 12),
        ("Charged £ ext" if _canonical else "Engine £ ext", 12),
        ("Engine £ ext — not charged", 14),
        ("Price source", 40), ("Priced by — sheet row / decision", 26),
        ("Evidence", 12), ("Estimator action", 44),
        # WHICH DRAWING, NOT WHICH KIND OF DRAWING. In a pack of eleven sheets "the drawing"
        # names none of them; this is the file, as the covering note and the report name it.
        ("Which drawing files and pages", 44),
    ]
    _LAST = get_column_letter(len(headers))
    for ci, (hdr, width) in enumerate(headers, 1):
        c = cell(5, ci, hdr, bold=True, bg=C_SECTION, fg=C_HEADER_FG,
                 align="center", size=10)
        ws.column_dimensions[get_column_letter(ci)].width = width
    ws.row_dimensions[5].height = 20
    # THE EVIDENCE, AS A WORD. "measured" — a model, a DXF or the estimators' calculator;
    # "transcribed" — read from the drawing, reproducible, not verified; "inferred" — a
    # default or an inference is standing in; "unread" — a required field has no reading.
    _EVIDENCE = {"measured": "measured", "confirmed": "measured", "reported": "transcribed",
                 "assumed": "inferred", "unknown": "unread", "n/a": "n/a"}
    # ── Part rows ──────────────────────────────────────────────────────────────
    row = 6
    for i, p in enumerate(provenance):
        bg = C_ALT_ROW if i % 2 == 0 else "FFFFFF"
        # Shaded by STATUS, from the shared table, so every tab colours a status the same
        # way. A bought-in is no longer given a neutral grey that reads as "fine": an
        # unpriced placeholder shades UNKNOWN like anything else missing a required field.
        from confidence import STATUS_FILL as _SF
        conf_bg = _SF.get(p.get("overall_status"), ("EDEDED", "555555"))[0]

        def _with_source(value: str, source: str) -> str:
            source = str(source or "").strip()
            return f"{value} — {source}" if source and source != "—" else value

        cell(row, 1,  p["part_number"],        bg=bg,       border=True)
        cell(row, 2,  p["description"],        bg=bg,       border=True, wrap=True)
        cell(row, 3,  p["quantity"],            bg=bg,       align="center", border=True)
        _mat_cell = (str(p["material_source"]) if str(p["material"]) == "Bought-in"
                     else _with_source(str(p["material"]), p["material_source"]))
        cell(row, 4,  _mat_cell, bg=conf_bg, bold=True, border=True, wrap=True, size=9)
        cell(row, 5,  _with_source(f"{p['thickness_mm']}mm" if p["thickness_mm"] else "—",
                                   p["thickness_source"] if p["thickness_mm"] else ""),
             bg=bg, border=True, size=9, wrap=True)
        _geo = str(p["geometry_source"] or "")
        if p["cut_length_mm"] and "mm" not in _geo:
            _geo += f" · cut {p['cut_length_mm']:,.0f} mm"
        cell(row, 6,  _geo, bg=bg, border=True, size=9, wrap=True)
        cell(row, 7,  p["operations"],          bg=bg,       border=True, size=9, wrap=True)
        cell(row, 8,  f"£{p['unit_cost']:.2f}", bg=bg,       align="right",
             bold=True, border=True)
        cell(row, 9,  f"£{p['extended_cost']:.2f}", bg=bg,   align="right",
             bold=True, border=True)
        _eng = float(p.get("engine_extended_cost") or 0.0)
        _differs = p.get("charged") and abs(_eng - float(p["extended_cost"] or 0)) >= 0.01
        cell(row, 10, f"£{_eng:.2f}" if _differs else "—", bg=bg, align="right",
             border=True, size=9, fg="666666")
        _rb = p.get("rate_basis") or "—"
        # The engine-figure note is its own column now; keep the source column to the source.
        _rb = _rb.split(" · engine net-part figure")[0]
        # WHOSE BLANK THIS IS. An engine gap is work that will be done and invoiced with
        # nothing on the sheet asking anyone to price it — the one an estimator cannot fix,
        # and the one that gets the warning fill. A line correctly nil is left plain.
        _ur = p.get("unpriced_reason") or {}
        if _ur:
            _owner = {"estimator": "ESTIMATOR TO PRICE",
                      "engine": "ENGINE GAP — THIS JOB IS UNDER-CHARGED",
                      "nobody": "nothing to charge here"}.get(_ur.get("owner"), "")
            _txt = f"{_ur.get('why')}" + (f" — {_ur['detail']}" if _ur.get("detail") else "")
            _rb = f"{_owner}: {_txt}" if _owner else _txt
        cell(row, 11, _rb,
             bg=(C_LOW if (_rb.startswith("⚠") or _ur.get("undercharging")) else bg),
             border=True, size=9, wrap=True)
        cell(row, 12, p.get("priced_by") or "—", bg=bg, border=True, size=8, wrap=True)
        cell(row, 13, _EVIDENCE.get(str(p.get("overall_status") or "").lower(),
                                    str(p.get("overall_status") or "—")),
             bg=conf_bg, align="center", border=True, size=9)
        _act = str(p.get("estimator_action") or "—")
        cell(row, 14, _act, bg=(bg if _act.startswith("none") else "FFF2CC"),
             border=True, size=9, wrap=True)
        cell(row, 15, p.get("drawing_files") or "—", bg=bg, border=True, size=8, wrap=True)
        ws.row_dimensions[row].height = 28
        row += 1
        # ── Flags / warnings ───────────────────────────────────────────────────
        if p["flags"]:
            for flag in p["flags"]:
                ws.merge_cells(f"B{row}:{_LAST}{row}")
                cell(row, 1, "⚠",              bg=C_LOW, align="center", size=9)
                cell(row, 2, f"REVIEW: {flag}", bg=C_LOW, size=9, wrap=True)
                ws.row_dimensions[row].height = 16
                row += 1
        # ── Override rules that fired ──────────────────────────────────────────
        if p["overrides_fired"]:
            ws.merge_cells(f"B{row}:{_LAST}{row}")
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
                ws.merge_cells(f"B{row}:{_LAST}{row}")
                cell(row, 1, "📚",              bg=C_HIST, align="center", size=9)
                cell(row, 2,
                     f"Historical: {cnt} SDI estimate(s) for this part as "
                     f"{hmat} — avg £{avg:.2f}",
                     bg=C_HIST, size=9)
                ws.row_dimensions[row].height = 14
                row += 1
    # ── Summary footer ─────────────────────────────────────────────────────────
    row += 1
    ws.merge_cells(f"A{row}:H{row}")
    # Authoritative total: WB Sell Price (live formula) when found, else engine sum.
    _total_label = ("SELL PRICE (from Estimate sheet)" if _sell_ref
                    else "UNIT COST (calculated by the Estimate sheet)" if _wb_unit is not None
                    else "PART MATERIAL ONLY — no workbook total")
    cell(row, 1,  _total_label, bold=True, bg=C_HEADER_BG, fg=C_HEADER_FG,
         align="right", size=11)
    if _sell_ref:
        cell(row, 9, _sell_ref, bold=True, bg=C_HEADER_BG, fg=C_HEADER_FG,
             align="right", size=12, num_fmt="£#,##0.00")
    else:
        cell(row, 9, f"£{_engine_total:.2f}",  bold=True, bg=C_HEADER_BG, fg=C_HEADER_FG,
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
        # NAME THE GAP — IN THE WORDS THE OTHER TAB ALREADY USES.
        #
        # This printed both figures and stopped, leaving the reader to decide which was wrong.
        # Neither is. The first attempt at explaining it then got the CONTENTS wrong, and that
        # was worse than saying nothing: it named "purchased items on the Bill of Materials,
        # packaging and delivery", every one of which is already IN this column — packaging at
        # £28, the pallet, FIXING2104, the screws, the TESA tape. A reader who went looking for
        # packaging in the gap would have found it in the column instead and concluded the tab
        # could not account for itself, which is exactly the distrust the sentence exists to
        # prevent.
        #
        # The Decision Report has computed this residual all along and labels it
        # "Powder / scrap / other workbook material" — the powder consumable and the per-line
        # scrap uplift, lines that belong to no single part and so cannot appear in a per-part
        # column. Same arithmetic, same words, and the reader is sent there to see the figure
        # broken out rather than asked to take this sentence on trust.
        if _mat is None:
            _mat_txt = ""
        else:
            _gap = float(_mat) - _col_mat
            _gap_txt = ""
            if abs(_gap) >= 0.02:
                # DO NOT NAME A PROCESS THIS JOB DOES NOT HAVE. The label was fixed text, so a
                # job with NOTHING COATED still had its residual called "powder", and an
                # estimator reading "Powder / scrap £5.13" on a plated stand rightly stopped
                # trusting the tab. Powder is named only when a powder figure actually exists;
                # otherwise the residual is what it really is on this job.
                #
                # And the bigger half of the gap is not scrap at all: it is the two costing
                # BASES. The sheet charges a nested part its share of a WHOLE SHEET (cost per
                # sheet / parts per sheet), so it carries the drop and the skeleton; this column
                # shows the engine's NET-PART price (blank mass x £/kg, or blank area x £/m²),
                # which charges only the metal in the part. Said once, plainly, instead of
                # lumped under a process name.
                _has_powder = False
                try:
                    _pc = (summary.get("powder_coating_summary") or {}).get(
                        "total_powder_cost_gbp")
                    _has_powder = bool(_pc) and float(_pc) > 0
                except (TypeError, ValueError, AttributeError):
                    _has_powder = False
                if not _has_powder:
                    # THE SHEET'S OWN POWDER ROW IS THE SECOND WITNESS. 11350-01 charges
                    # 3p of powder through the coated-area path, which never fills
                    # powder_coating_summary — and this sentence said "no powder is
                    # charged on this job" directly beside a POWDER row with money on
                    # it. A read-back POWDER row carrying value means powder IS charged,
                    # whichever book computed it.
                    try:
                        from costed_facts import _final_estimate_of
                        for _r in (_final_estimate_of(summary).get("material_rows") or []):
                            if (isinstance(_r, dict)
                                    and str(_r.get("description") or "").strip()
                                    .upper().startswith("POWDER")
                                    and float(_r.get("total_value_gbp") or 0) > 0):
                                _has_powder = True
                                break
                    except Exception:                            # noqa: BLE001
                        pass
                # A CONSUMABLE AND AN OPERATION ARE NOT THE SAME CHARGE — see
                # _powder_labour_gbp. When the coating is priced as LABOUR, say so rather than
                # telling the reader no powder is charged on the job.
                _powder_labour = _powder_labour_gbp(summary)
                _resid = ("POWDER / SCRAP / OTHER WORKBOOK MATERIAL — the powder consumable and "
                          "the per-line scrap uplift" if _has_powder else
                          "NEST-vs-NET-PART BASIS, SCRAP AND OTHER WORKBOOK MATERIAL — no powder "
                          + (f"CONSUMABLE is in the material total; the coating IS charged, as "
                             f"labour: £{_powder_labour:,.2f}" if _powder_labour > 0
                             else "is charged on this job"))
                _gap_txt = (f"The £{abs(_gap):,.2f} difference is the sheet's "
                            f"{_resid}. The sheet charges a nested part its share of a WHOLE "
                            f"SHEET, so it carries the drop and the skeleton; this column is the "
                            f"engine's NET-PART price, which charges only the metal in the part. "
                            f"Neither figure is wrong — this column is per-part provenance, the "
                            f"sheet is the money. The MATERIAL COST BREAKDOWN below shows the "
                            f"residual as its own row. ")
            elif abs(_gap) >= 0.005:
                # A PENNY IS ROUNDING. Each row is charged at two decimals and the sheet
                # sums the unrounded cells; a £0.01 gap is arithmetic, not a basis.
                _gap_txt = (f"The £{abs(_gap):,.2f} difference is rounding across the rows; "
                            f"the column is the sheet's own charged figures. ")
            _mat_txt = (f"The material column above sums to £{_col_mat:,.2f} against the "
                        f"sheet's £{float(_mat):,.2f}. {_gap_txt}")
        _lab_txt = (f"Labour is £{float(_lab):,.2f}, charged per department row across "
                    f"every part in that setup — see 'Priced by' for the rows and "
                    f"decisions behind each part. " if _lab is not None else "")
        cell(row, 1,
             f"RECONCILIATION — the Estimate sheet calculated "
             f"£{float(_totals.get('unit_gbp') or 0):,.2f} per unit. "
             f"{_mat_txt}{_lab_txt}The workbook is authoritative.",
             bg=C_KB, size=9, wrap=True)
        ws.row_dimensions[row].height = 32

    # ── 2, 3, 4: the hierarchy, the route, and identity through the pack ────────
    # The Canonical BOM and Canonical Route tabs, folded in with presentation, and the
    # tracking questions James set for this tab: which drawing, which reader, which price
    # source, and where a part's name did not carry across the drawings. The undrawn lines
    # that used to be one merged sentence here are rows in block 4.
    try:
        row = _append_traceability_blocks(ws, row, summary, provenance, cell)
    except Exception as _tb:                                     # noqa: BLE001
        row += 2
        cell(row, 1,
             f"The hierarchy, route and tracking blocks could not be built ({_tb}) — a "
             f"rendering failure, not a job with nothing to trace.",
             bg=C_LOW, size=9, wrap=True, bold=True)
        ws.row_dimensions[row].height = 28

    # ── WHAT THE DECISION REPORT KNEW AND THIS TAB DID NOT ──────────────────────
    #
    # The workbook shipped nine sheets, two of which listed every part with its material, its
    # gauge and where each came from. Twenty-five rows, twice, and not identically: the two
    # derived geometry source independently and disagreed about it on 10575-01-001. James:
    # "we don't want overlapping data between the two sheets decision and ai governance...
    # let's get rid of one and just keep the other one then. we don't want clutter."
    #
    # The Decision Report is the one that goes. What it held alone comes here first — who
    # decided powder, the material breakdown that adds back to the sheet's own total, and the
    # two contest tables. The DATA contests especially: material decides the rate and whether
    # the part has a rate at all, gauge decides the rate AND steps the cut time, and nowhere
    # else in the workbook says two sources disagreed about either.
    try:
        from job_decision_report import append_decision_blocks
        row = append_decision_blocks(ws, row, summary)
    except Exception as _blk:                                    # noqa: BLE001
        # SAID ON THE SHEET, not swallowed. These blocks are now the ONLY place the contests
        # appear; a silent failure here reads as a job where nothing was contested.
        row += 2
        cell(row, 1,
             f"The decision blocks could not be built ({_blk}). Powder authority, the material "
             f"breakdown and the two contest tables are missing from this tab — that is a "
             f"rendering failure, not a job with nothing contested.",
             bg=C_LOW, size=9, wrap=True, bold=True)
        ws.row_dimensions[row].height = 28

    row += 2
    ws.merge_cells(f"A{row}:O{row}")
    # READING SEPARATED FROM PRICING, because they are two different questions and merging
    # them destroyed the tab's trust. The old summary took each part's WEAKEST field — and on
    # an estimate that field is almost always the price, which is "NOT YET PRICED, estimator to
    # enter a figure": a normal, expected state, not a bad read. So a part whose material,
    # thickness and geometry were ALL measured off the SolidWorks model was counted LOW because
    # nobody had typed its rate yet, and a whole job read "0 HIGH / 22 LOW" — which says the
    # engine failed when it did not. Now the engine's READING (what it pulled off the drawing and
    # the model) is scored on its own, and PRICING is reported as what it is: how many lines are
    # priced versus waiting on the estimator's rate.
    _rp = reading_and_pricing_counts(provenance)
    read_hi, read_md, read_lo = _rp["read_high"], _rp["read_med"], _rp["read_low"]
    priced, pending = _rp["priced"], _rp["pending"]
    cell(row, 1,
         f"Engine read the drawing & model:  "
         f"🟢 {read_hi} measured/confirmed   "
         f"🟡 {read_md} reported   "
         f"🔴 {read_lo} needs a look      |      "
         f"Pricing:  💷 {priced} priced   "
         f"⏳ {pending} awaiting your rate      |      "
         f"Generated by SDI Intelligence  |  {datetime.now().strftime('%d/%m/%Y %H:%M')}",
         bg="F0F0F0", size=9, align="left")
    # Freeze panes below header + column A
    ws.freeze_panes = "B6"
    # Tab colour
    ws.sheet_properties.tabColor = "1F3864"
def _source_words(source: Any) -> str:
    """Which reader or rule decided it, in the words the rest of the workbook uses."""
    key = str(source or "").strip()
    if not key:
        return "unrecorded"
    try:
        from source_precedence import display_name
        return display_name(key) or key
    except Exception:                                            # noqa: BLE001
        return key.replace("_", " ")


def _append_traceability_blocks(ws, row: int, summary: Dict[str, Any],
                                provenance: List[Dict[str, Any]], cell) -> int:
    """Blocks 2–4 of the AI Provenance tab.

    WHAT THIS TAB IS, in James's words: a view onto what the drawing extraction and the
    estimating layer did. So for every part it has to say which drawing and page, which
    reader or rule decided each thing, which source priced it — and where a part's identity
    did not track through the pack, because names change between a GA and a detail sheet
    and a DXF filename. The audience is the estimator; the same rows are how we diagnose a
    run that went wrong.

    Block 2 is the bill of materials as the compiler assembled it, indented under its
    assemblies. Block 3 is the route decision by decision, kept and ruled out, grouped by
    part. Block 4 is identity and tracking: names merged, colourways collapsed, lines costed
    with no drawing, drawing files matched to no part or to more than one.
    """
    from wb_populate import canonical_route_payload, colourway_note
    payload = canonical_route_payload(summary) or {}
    nodes = [n for n in (payload.get("nodes") or []) if isinstance(n, dict)]
    decisions = [d for d in (payload.get("decisions") or []) if isinstance(d, dict)]
    prov_by = {str(p.get("part_number") or "").strip().upper(): p for p in provenance}
    try:
        from costed_facts import record_lines, _workbook_rows
        lines = record_lines(summary)
        rows_by_decision: Dict[str, List[int]] = {}
        for r in (_workbook_rows(summary) or []):
            for d in (r.get("decision_ids") or []):
                try:
                    rows_by_decision.setdefault(str(d), []).append(int(float(r.get("workbook_row") or 0)))
                except (TypeError, ValueError):
                    continue
    except Exception:                                            # noqa: BLE001
        lines, rows_by_decision = {}, {}
    _LAST = "O"

    def heading(text: str) -> None:
        nonlocal row
        row += 2
        ws.merge_cells(f"A{row}:{_LAST}{row}")
        cell(row, 1, text, bold=True, bg=C_SECTION, fg=C_HEADER_FG, size=11)
        ws.row_dimensions[row].height = 22
        row += 1

    def header(cols: List[str]) -> None:
        nonlocal row
        for ci, h in enumerate(cols, 1):
            cell(row, ci, h, bold=True, bg="D9E2F3", size=9, border=True)
        row += 1

    def money(pn: str) -> str:
        # The column says "Charged £", so only the sheet's own figure prints bare. The
        # engine's fallback is BATCH money on an assembly node (GA carried £215.65 of
        # engine rollup on 7332-01 while the unit was £80.34) — printing it unlabelled
        # made Tim's review require knowing which figures to ignore. It is named for
        # what it is instead, matching the HTML report's own tree.
        line = lines.get(pn) or {}
        v = line.get("charged_ext_gbp")
        engine_only = v is None
        if engine_only:
            v = line.get("engine_ext_gbp")
        try:
            if v is None:
                return "—"
            return (f"engine £{float(v):.2f} — not charged" if engine_only
                    else f"£{float(v):.2f}")
        except (TypeError, ValueError):
            return "—"

    def drawing(pn: str) -> str:
        return str((prov_by.get(pn) or {}).get("drawing_files") or "—")

    # ── 2 · the hierarchy ────────────────────────────────────────────────────
    by_pn = {str(n.get("part_number") or "").strip().upper(): n for n in nodes}
    children: Dict[str, List[Any]] = {}
    for n in nodes:
        pn = str(n.get("part_number") or "").strip().upper()
        for edge in (n.get("children") or []):
            if isinstance(edge, dict) and edge.get("part_number"):
                children.setdefault(pn, []).append(edge)
    # A graph that records only parents (an older shadow, a fixture) still has a hierarchy.
    if not children:
        for n in nodes:
            pn = str(n.get("part_number") or "").strip().upper()
            for parent in (n.get("parents") or []):
                children.setdefault(str(parent).strip().upper(), []).append(
                    {"part_number": pn, "qty": n.get("qty_per_unit")})
    # A node with no description takes the part's own, so the block reads as a BOM.
    for pn, n in by_pn.items():
        if not n.get("description"):
            n = dict(n)
            n["description"] = ((lines.get(pn) or {}).get("description")
                                or (prov_by.get(pn) or {}).get("description") or "")
            by_pn[pn] = n
    roots = [str(n.get("part_number") or "").strip().upper() for n in nodes
             if not (n.get("parents") or [])]
    order: List[str] = []
    if nodes:
        heading("2 — THE BILL OF MATERIALS AS THE ENGINE ASSEMBLED IT — every line under the "
                "assembly it belongs to; 'also called' is the name another drawing used for it")
        header(["Part", "Description", "Kind", "Qty/unit", "Also called / variant",
                "Charged £", "Which drawing files and pages"])
        seen: set = set()

        def walk(pn: str, depth: int) -> None:
            nonlocal row
            if pn in seen:
                return
            seen.add(pn)
            order.append(pn)
            n = by_pn.get(pn) or {"part_number": pn}
            kids = children.get(pn, [])
            aliases = [str(a) for a in ((n.get("evidence") or {}).get("raw_aliases") or [])
                       if str(a).strip().upper() != pn]
            note = "; ".join(x for x in (", ".join(aliases[:4]), colourway_note(n)) if x)
            bg = "EEF3F9" if kids else ("F5F5F5" if depth % 2 else "FFFFFF")
            cell(row, 1, ("    " * depth) + ("▸ " if kids else "") + str(n.get("part_number") or pn),
                 bg=bg, bold=bool(kids), border=True, size=9)
            cell(row, 2, str(n.get("description") or ""), bg=bg, border=True, size=9, wrap=True)
            cell(row, 3, str(n.get("kind") or ""), bg=bg, border=True, size=9)
            cell(row, 4, n.get("qty_per_unit") if n.get("qty_per_unit") is not None else "—",
                 bg=bg, border=True, size=9, align="center")
            cell(row, 5, note or "—", bg=bg, border=True, size=9, wrap=True)
            cell(row, 6, money(pn), bg=bg, border=True, size=9, align="right")
            cell(row, 7, drawing(pn), bg=bg, border=True, size=8, wrap=True)
            ws.row_dimensions[row].height = 16
            row += 1
            for edge in kids:
                walk(str(edge.get("part_number") or "").strip().upper(), depth + 1)

        for r in roots:
            walk(r, 0)
        for n in nodes:
            walk(str(n.get("part_number") or "").strip().upper(), 0)

    # ── 3 · the route, decision by decision ──────────────────────────────────
    if decisions:
        heading("3 — THE ROUTE, DECISION BY DECISION — every operation the compiler "
                "considered, kept or ruled out, who decided it, and the sheet row it charges")
        header(["Part", "Operation", "Kept?", "Qty/unit", "Decided by", "Reason",
                "Sheet row", "Decision ID"])
        by_target: Dict[str, List[Dict[str, Any]]] = {}
        for d in decisions:
            by_target.setdefault(str(d.get("target_id") or "").strip().upper(), []).append(d)
        targets = [pn for pn in order if pn in by_target] + \
                  [pn for pn in by_target if pn not in order]
        for pn in targets:
            group = sorted(by_target[pn],
                           key=lambda d: (0 if str(d.get("status")) == "required" else 1,
                                          float(d.get("sequence") or 999)))
            for d in group:
                status = str(d.get("status") or "")
                did = str(d.get("decision_id") or "")
                charged_rows = rows_by_decision.get(did) or []
                kept = ("charged" if status == "required" and charged_rows else
                        "required — not on a priced row" if status == "required" else
                        "ruled out" if status == "not_applicable" else status)
                bg = ("FFFFFF" if kept == "charged" else
                      "FFF2CC" if kept.startswith("required") else "EDEDED")
                cell(row, 1, pn, bg=bg, border=True, size=9)
                cell(row, 2, str(d.get("operation") or ""), bg=bg, border=True, size=9,
                     bold=(kept == "charged"))
                cell(row, 3, kept, bg=bg, border=True, size=9)
                cell(row, 4, d.get("qty_per_unit") if d.get("qty_per_unit") is not None else "—",
                     bg=bg, border=True, size=9, align="center")
                cell(row, 5, _source_words(d.get("source")), bg=bg, border=True, size=9, wrap=True)
                cell(row, 6, str(d.get("reason") or ""), bg=bg, border=True, size=8, wrap=True)
                cell(row, 7, ", ".join(f"Estimate!{r}" for r in sorted(set(charged_rows))) or "—",
                     bg=bg, border=True, size=8)
                cell(row, 8, did, bg=bg, border=True, size=8)
                ws.row_dimensions[row].height = 16
                row += 1

    # ── 4 · identity and tracking through the pack ───────────────────────────
    issues: List[List[str]] = []
    for n in nodes:
        pn = str(n.get("part_number") or "").strip().upper()
        aliases = [str(a) for a in ((n.get("evidence") or {}).get("raw_aliases") or [])
                   if str(a).strip().upper() != pn]
        if aliases:
            issues.append(["Merged under one name", pn,
                           f"also appears as {', '.join(aliases[:6])} — the same part under "
                           f"another spelling, joined by the compiler; check that is right"])
        cv = colourway_note(n)
        if cv:
            issues.append(["Colourway collapsed", pn, cv])
    try:
        from costed_facts import undrawn_bom_lines as _undrawn
        for m in _undrawn(summary) or []:
            issues.append(["Costed with no drawing of its own", str(m.get("part_number") or ""),
                           (str(m.get("description") or "") + " — no detail sheet in the pack; "
                            "priced from the BOM line alone").strip(" —")])
    except Exception:                                            # noqa: BLE001
        pass
    dxf = summary.get("dxf_augmentation") if isinstance(summary.get("dxf_augmentation"), dict) else {}

    def _basename(path: Any) -> str:
        # The paths are Windows paths written on the box; split on either separator.
        return re.split(r"[\\/]", str(path or ""))[-1] or "?"

    for x in (dxf.get("unmatched_dxf") or []):
        if isinstance(x, dict):
            issues.append(["Drawing file matched to no part", _basename(x.get("path")),
                           str(x.get("reason") or "no part number in the filename matched a "
                                                  "BOM line").replace("_", " ")])
    for x in (dxf.get("ambiguous_dxf") or []):
        if isinstance(x, dict):
            cands = x.get("candidates") or x.get("matches") or []
            issues.append(["Drawing file matched to more than one part", _basename(x.get("path")),
                           (", ".join(str(c) for c in cands) if cands else
                            str(x.get("reason") or "")).replace("_", " ")])
    for x in (dxf.get("parts_without_dxf") or []):
        pn = str(x.get("part_number") if isinstance(x, dict) else x).strip()
        if pn:
            issues.append(["No DXF flat for this part", pn,
                           "geometry came from the model or the sheet, not a flat pattern"])
    # A MODELLED PART IN NO ASSEMBLY BOM — a fixture, a jig, a setup block in the job
    # folder. The SolidWorks reader names them; they are not costed into the job.
    _sw = summary.get("solidworks_native") if isinstance(summary.get("solidworks_native"), dict) else {}
    for pn in ((_sw.get("applied") or {}).get("not_in_bom_parts") or []):
        issues.append(["Modelled but in no assembly BOM", str(pn),
                       "a fixture, jig or setup part in the model folder — not a component "
                       "of the product, not costed; confirm"])
    heading("4 — IDENTITY AND TRACKING THROUGH THE PACK — where a part's name did not carry "
            "across the drawings, what was costed that nothing drew, and what was read that "
            "nothing costed")
    if issues:
        header(["What", "Part / file", "Detail"])
        for kind, what, detail in issues:
            bg = C_LOW if kind.startswith(("Costed with no", "Drawing file")) else "FFF2CC"
            cell(row, 1, kind, bg=bg, border=True, size=9, bold=True)
            cell(row, 2, what, bg=bg, border=True, size=9)
            cell(row, 3, detail, bg=bg, border=True, size=9, wrap=True)
            ws.merge_cells(f"C{row}:{_LAST}{row}")
            ws.row_dimensions[row].height = 18
            row += 1
    else:
        ws.merge_cells(f"A{row}:{_LAST}{row}")
        cell(row, 1, "Every part tracked through the pack under one name, every costed line "
                     "has a drawing, and every drawing file matched one part.",
             bg="E8F6EF", size=9)
        row += 1
    return row


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
